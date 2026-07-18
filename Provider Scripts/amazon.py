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


NAME = "amazon.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
PAGE_HOSTS = {"amazon.com", "www.amazon.com"}


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in PAGE_HOSTS and (
        "/gp/video/detail/" in parsed.path or "/dp/" in parsed.path
    )


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    html_text = fetch_text(url, timeout=timeout)
    visible_lines = extract_visible_lines(html_text)
    video_object = extract_video_object(html_text)
    title = clean_title(
        first_non_empty(
            clean_text(video_object.get("name")),
            meta_value(html_text, "og:title"),
            match_group(r"<title>(.*?)</title>", html_text),
            visible_lines[0] if visible_lines else "",
        )
    )
    plot = first_non_empty(
        clean_text(video_object.get("description")),
        meta_value(html_text, "description"),
        meta_value(html_text, "og:description"),
    )
    source_url = first_non_empty(meta_value(html_text, "og:url"), url)
    poster = first_non_empty(meta_value(html_text, "og:image"), meta_value(html_text, "twitter:image"))
    genres = dedupe(parse_genres(html_text, visible_lines))
    studios = dedupe(parse_label_block("Studio", visible_lines))
    directors = dedupe(parse_label_block("Directors", visible_lines) + parse_label_block("Director", visible_lines))
    credits = dedupe(parse_label_block("Producers", visible_lines) + parse_label_block("Producer", visible_lines))
    cast = parse_cast(visible_lines)
    year = first_non_empty(
        year_from_text(clean_text(video_object.get("datePublished"))),
        parse_year(visible_lines),
    )
    runtime = first_non_empty(
        duration_minutes(clean_text(video_object.get("duration"))),
        parse_runtime(visible_lines),
    )
    rating = first_non_empty(
        clean_text(video_object.get("contentRating")),
        parse_content_rating(visible_lines),
    )
    trailer_url = parse_direct_mp4(html_text)
    wide_art = parse_wide_art(html_text, poster)
    unique_ids = {}
    asin = first_non_empty(
        match_group(r"/detail/([A-Z0-9]{10})", url),
        match_group(r"/dp/([A-Z0-9]{10})", source_url),
    )
    if asin:
        unique_ids["amazon"] = asin
    folder_name = build_folder_name(title, studios[:1])
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
        "fanart_url": wide_art,
        "trailer_url": trailer_url,
        "production_label": "Production/Studio",
        "genres": genres,
        "studios": studios,
        "directors": directors,
        "credits": credits,
        "actors": [{"name": name, "role": ""} for name in cast],
        "unique_ids": unique_ids,
        "folder_name_override": folder_name,
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
        if isinstance(data, dict):
            objects = [data] + [item for item in data.get("@graph", []) if isinstance(item, dict)]
        elif isinstance(data, list):
            objects = [item for item in data if isinstance(item, dict)]
        else:
            objects = []
        for item in objects:
            if clean_text(item.get("@type")).casefold() in {"movie", "videoobject", "tvseries", "episode"}:
                return item
    return {}


def parse_label_block(label: str, lines: list[str]) -> list[str]:
    values: list[str] = []
    lowered = label.casefold()
    for index, line in enumerate(lines):
        if line.casefold() != lowered:
            continue
        cursor = index + 1
        while cursor < len(lines):
            item = clean_text(lines[cursor])
            if not item or item.casefold() in {
                "cast",
                "director",
                "directors",
                "producer",
                "producers",
                "studio",
                "creators and cast",
                "genre",
                "genres",
            }:
                break
            if looks_like_section_break(item):
                break
            values.extend(split_people(item))
            cursor += 1
        break
    return [value for value in values if value]


def parse_cast(lines: list[str]) -> list[str]:
    values = parse_label_block("Cast", lines)
    return dedupe(values)


def parse_genres(html_text: str, lines: list[str]) -> list[str]:
    matches = re.findall(r"atv_dp_pd_gen[^>]*>([^<]+)</a>", html_text, flags=re.IGNORECASE)
    if matches:
        return [clean_text(match) for match in matches if clean_text(match)]
    for line in lines:
        if "•" in line and not re.search(r"\d", line):
            parts = [clean_text(part) for part in line.split("•")]
            if len(parts) >= 2:
                return [part for part in parts if part]
    return []


def parse_year(lines: list[str]) -> str:
    joined = " ".join(lines)
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", joined)
    return match.group(1) if match else ""


def parse_runtime(lines: list[str]) -> str:
    joined = " ".join(lines)
    match = re.search(r"\b(?:(\d+)\s*h\s*)?(?:(\d+)\s*min)\b", joined, flags=re.IGNORECASE)
    if not match:
        return ""
    hours = int(match.group(1) or "0")
    minutes = int(match.group(2) or "0")
    return str(hours * 60 + minutes)


def parse_content_rating(lines: list[str]) -> str:
    joined = " ".join(lines)
    match = re.search(r"\b(G|PG|PG-13|R|NC-17|TV-Y7|TV-G|TV-PG|TV-14|TV-MA)\b", joined)
    return match.group(1) if match else ""


def parse_direct_mp4(html_text: str) -> str:
    match = re.search(r"https://[^\"' ]+\.mp4(?:\?[^\"' ]+)?", html_text, flags=re.IGNORECASE)
    return clean_text(match.group(0)) if match else ""


def parse_wide_art(html_text: str, fallback: str) -> str:
    match = re.search(r"https://[^\"' ]+_UX\d+_.*?\.(?:jpg|jpeg|png)", html_text, flags=re.IGNORECASE)
    return clean_text(match.group(0)) if match else fallback


def match_group(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return clean_text(match.group(1)) if match else ""


def meta_value(html_text: str, name: str) -> str:
    pattern = (
        r'<meta[^>]+(?:property|name)=["\']'
        + re.escape(name)
        + r'["\'][^>]+content=["\'](.*?)["\']'
    )
    return html.unescape(match_group(pattern, html_text))


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


def split_people(text: str) -> list[str]:
    return [clean_text(part) for part in re.split(r",\s*", text) if clean_text(part)]


def clean_title(text: str) -> str:
    value = clean_text(text)
    value = re.sub(r"^Watch\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*-\s*Prime Video.*$", "", value, flags=re.IGNORECASE)
    return value


def first_non_empty(*values: str) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def looks_like_section_break(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Za-z ,&/-]{1,40}", text)) and text.casefold() in {
        "studio",
        "cast",
        "director",
        "directors",
        "producers",
        "producer",
        "creators and cast",
        "audio languages",
        "subtitles",
    }


def dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen = set()
    for value in values:
        text = clean_text(value)
        if text and text.casefold() not in seen:
            output.append(text)
            seen.add(text.casefold())
    return output


def build_folder_name(title: str, studios: list[str]) -> str:
    if title and studios:
        return f"{title} - {studios[0]}"
    return title


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
