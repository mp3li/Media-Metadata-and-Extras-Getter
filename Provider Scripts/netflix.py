#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any


NAME = "Netflix"
PAGE_HOSTS = {"netflix.com", "www.netflix.com"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in PAGE_HOSTS and "/title/" in parsed.path


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    html_text = fetch_text(url, timeout=timeout)
    visible_lines = extract_visible_lines(html_text)
    video_object = extract_video_object(html_text)
    state = extract_next_data(html_text)
    title = first_non_empty(
        clean_text(video_object.get("name")),
        nested_text(state, "props", "pageProps", "metadata", "title"),
        clean_title(meta_value(html_text, "og:title")),
        title_from_lines(visible_lines),
    )
    plot = first_non_empty(
        clean_text(video_object.get("description")),
        nested_text(state, "props", "pageProps", "metadata", "synopsis"),
        meta_value(html_text, "og:description"),
    )
    year = first_non_empty(
        year_from_text(clean_text(video_object.get("datePublished"))),
        nested_text(state, "props", "pageProps", "metadata", "year"),
        parse_year(visible_lines),
    )
    rating = first_non_empty(
        clean_text(video_object.get("contentRating")),
        nested_text(state, "props", "pageProps", "metadata", "maturity", "rating", "value"),
        parse_rating(visible_lines),
    )
    runtime = first_non_empty(
        duration_minutes(clean_text(video_object.get("duration"))),
        parse_runtime(visible_lines),
    )
    genres = dedupe(
        split_csv(nested_text(state, "props", "pageProps", "metadata", "genres"))
        or parse_visible_block(visible_lines, "Genres")
        or parse_summary_genres(visible_lines)
    )
    tags = dedupe(parse_visible_block(visible_lines, "This show is ..."))
    cast = dedupe(parse_visible_block(visible_lines, "Cast"))
    if not cast:
        cast = dedupe(parse_starring_fallback(visible_lines))
    poster = first_non_empty(
        meta_value(html_text, "og:image"),
        nested_text(state, "props", "pageProps", "metadata", "boxArt", "url"),
    )
    fanart = first_non_empty(
        nested_text(state, "props", "pageProps", "metadata", "storyArt", "url"),
        nested_text(state, "props", "pageProps", "metadata", "bg", "url"),
        poster,
    )
    trailer = first_non_empty(
        parse_direct_video_url(html_text),
        nested_text(state, "props", "pageProps", "metadata", "trailer", "url"),
    )
    source_url = first_non_empty(meta_value(html_text, "og:url"), url)
    title_id = match_group(r"/title/(\d+)", url)
    extra_fields: dict[str, list[str]] = {}
    starring = dedupe(parse_starring_fallback(visible_lines))
    if starring:
        extra_fields["Starring"] = starring
    return {
        "source_url": source_url,
        "source_site": NAME,
        "title": title,
        "outline": plot,
        "plot": plot,
        "year": year,
        "runtime_minutes": runtime,
        "content_rating": rating,
        "poster_url": poster,
        "fanart_url": fanart,
        "trailer_url": trailer,
        "production_label": "Provider",
        "genres": genres,
        "tags": tags,
        "studios": [NAME],
        "actors": [{"name": name, "role": ""} for name in cast],
        "unique_ids": {"netflix": title_id} if title_id else {},
        "extra_fields": extra_fields,
        "folder_name_override": title,
    }


def fetch_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        result = subprocess.run(
            [
                "/usr/bin/curl",
                "--location",
                "--silent",
                "--show-error",
                "--compressed",
                "--max-time",
                str(timeout),
                "--user-agent",
                USER_AGENT,
                url,
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")
        return result.stdout


class VisibleTextParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "button",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "section",
        "span",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def extract_visible_lines(html_text: str) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(html_text)
    text = html.unescape("".join(parser.parts))
    return [line.strip() for line in text.splitlines() if line.strip()]


def extract_video_object(html_text: str) -> dict[str, Any]:
    for match in re.finditer(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw = html.unescape(match.group(1).strip())
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        objects = []
        if isinstance(data, dict):
            objects.append(data)
            graph = data.get("@graph")
            if isinstance(graph, list):
                objects.extend(item for item in graph if isinstance(item, dict))
        elif isinstance(data, list):
            objects.extend(item for item in data if isinstance(item, dict))
        for item in objects:
            if clean_text(item.get("@type")).casefold() in {"movie", "videoobject", "tvseries"}:
                return item
    return {}


def extract_next_data(html_text: str) -> dict[str, Any]:
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    try:
        data = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def nested_text(data: Any, *path: str) -> str:
    current = data
    for part in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(part)
    return clean_text(current)


def parse_visible_block(lines: list[str], label: str) -> list[str]:
    values: list[str] = []
    label_key = label.casefold()
    for index, line in enumerate(lines):
        if line.casefold() != label_key:
            continue
        cursor = index + 1
        while cursor < len(lines):
            item = clean_text(lines[cursor])
            if not item:
                break
            if re.fullmatch(r"[A-Z][A-Za-z .,&'/-]{1,40}", item) and item.casefold() in {
                "cast",
                "genres",
                "this show is ...",
                "starring:",
            }:
                break
            values.extend(split_csv(item))
            cursor += 1
        break
    return [value for value in values if value]


def parse_starring_fallback(lines: list[str]) -> list[str]:
    joined = " ".join(lines)
    match = re.search(r"Starring:\s*(.+?)(?:Genres|This show is|$)", joined, flags=re.IGNORECASE)
    if not match:
        return []
    return split_csv(match.group(1))


def parse_summary_genres(lines: list[str]) -> list[str]:
    joined = " ".join(lines)
    match = re.search(
        r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\s+(?:[^A-Za-z0-9]+\s*)?([A-Za-z][A-Za-z ,&/-]+)",
        joined,
    )
    if not match:
        return []
    return split_csv(match.group(2))


def parse_runtime(lines: list[str]) -> str:
    joined = " ".join(lines)
    match = re.search(r"\b(?:(\d+)\s*h(?:ours?)?\s*)?(?:(\d+)\s*m(?:in)?)\b", joined, flags=re.IGNORECASE)
    if not match:
        return ""
    hours = int(match.group(1) or "0")
    minutes = int(match.group(2) or "0")
    return str(hours * 60 + minutes)


def parse_year(lines: list[str]) -> str:
    joined = " ".join(lines)
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", joined)
    return match.group(1) if match else ""


def parse_rating(lines: list[str]) -> str:
    joined = " ".join(lines)
    match = re.search(r"\b(G|PG|PG-13|R|NC-17|TV-Y7|TV-G|TV-PG|TV-14|TV-MA)\b", joined)
    return match.group(1) if match else ""


def parse_direct_video_url(html_text: str) -> str:
    match = re.search(r"https://[^\"' ]+\.(?:mp4|m3u8)(?:\?[^\"' ]+)?", html_text, flags=re.IGNORECASE)
    return clean_text(match.group(0)) if match else ""


def meta_value(html_text: str, name: str) -> str:
    pattern = (
        r'<meta[^>]+(?:property|name)=["\']'
        + re.escape(name)
        + r'["\'][^>]+content=["\'](.*?)["\']'
    )
    return html.unescape(match_group(pattern, html_text))


def title_from_lines(lines: list[str]) -> str:
    for line in lines:
        if not line or line.casefold() in {"cast", "genres", "this show is ..."}:
            continue
        if len(line) > 2 and len(line) < 140 and not re.search(r"https?://", line):
            return line
    return ""


def duration_minutes(text: str) -> str:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if not match:
        return ""
    hours = int(match.group(1) or "0")
    minutes = int(match.group(2) or "0")
    return str(hours * 60 + minutes)


def year_from_text(text: str) -> str:
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", text)
    return match.group(1) if match else ""


def split_csv(text: str) -> list[str]:
    return [clean_text(part) for part in re.split(r",\s*", clean_text(text)) if clean_text(part)]


def match_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return clean_text(match.group(1)) if match else ""


def clean_title(text: str) -> str:
    value = clean_text(text)
    return re.sub(r"\s*-\s*Netflix.*$", "", value, flags=re.IGNORECASE)


def first_non_empty(*values: str) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen = set()
    for value in values:
        text = clean_text(value)
        if text and text.casefold() not in seen:
            output.append(text)
            seen.add(text.casefold())
    return output


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
