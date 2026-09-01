#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import subprocess
import concurrent.futures
import datetime as dt
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any


NAME = "amazon.com"
PRIME_NAME = "Amazon Prime Video"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
PAGE_HOSTS = {"amazon.com", "www.amazon.com"}
PRIME_HOSTS = {"primevideo.com", "www.primevideo.com"}


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    host = parsed.netloc.casefold()
    return (
        host in PAGE_HOSTS
        and ("/gp/video/detail/" in parsed.path or "/dp/" in parsed.path)
    ) or (
        host in PRIME_HOSTS
        and bool(re.search(r"/(?:region/[^/]+/)?detail/[A-Z0-9]+", parsed.path, re.I))
    )


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    if urllib.parse.urlparse(clean_text(url)).netloc.casefold() in PRIME_HOSTS:
        return extract_prime_metadata(url, timeout=timeout)
    return extract_legacy_metadata(url, timeout=timeout)


def extract_legacy_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
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


def extract_prime_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    normalized = canonical_prime_url(url)
    initial = prime_page(normalized, timeout=timeout)
    state = prime_state(initial, "atf")
    header = first_detail(state, "headerDetail")
    if not header:
        raise ValueError("Prime Video page did not expose public title metadata.")
    requested_id = prime_compact_id(normalized)
    season_links = prime_season_links(state, normalized)
    pages: dict[str, dict[str, Any]] = {prime_compact_id(normalized): initial}

    def load(item: tuple[int, str]) -> tuple[int, dict[str, Any]]:
        season, season_url = item
        compact_id = prime_compact_id(season_url)
        page = pages.get(compact_id) or prime_page(season_url, timeout=timeout)
        return season, page

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, max(1, len(season_links)))) as executor:
        season_pages = sorted(executor.map(load, season_links), key=lambda item: item[0])
    records: list[dict[str, Any]] = []
    season_headers: list[tuple[int, dict[str, Any], str]] = []
    for season_number, page in season_pages:
        season_state = prime_state(page, "atf")
        season_header = first_detail(season_state, "headerDetail")
        season_url = next(url_value for number, url_value in season_links if number == season_number)
        season_headers.append((season_number, season_header, season_url))
        records.extend(prime_episode_records(page, season_number))
    records = dedupe_records(records)
    if not records:
        raise ValueError("Prime Video page did not expose a public episode guide.")

    selected_episode = next(
        (record for record in records if clean_text(record.get("compact_id")) == requested_id),
        None,
    )
    selected_header = header
    selected_season = int_value(header.get("seasonNumber")) or season_headers[0][0]
    series_source = next((season_url for number, _header, season_url in season_headers if number == selected_season), normalized)
    trailer_url = prime_trailer_page_url(state, normalized)
    series = prime_series_metadata(
        selected_header, season_headers, records, series_source, trailer_url=trailer_url
    )
    if not selected_episode:
        return series
    return prime_episode_metadata(series, selected_episode, normalized)


def prime_page(url: str, timeout: int) -> dict[str, Any]:
    match = None
    for _attempt in range(2):
        text = fetch_text(url, timeout=timeout)
        match = re.search(
            r'<script[^>]+id=["\']dv-web-page-hydration-data["\'][^>]*>(.*?)</script>',
            text,
            re.I | re.S,
        )
        if match:
            break
    if not match:
        raise ValueError("Prime Video page did not expose its public hydration data.")
    value = json.loads(html.unescape(match.group(1)))
    return value if isinstance(value, dict) else {}


def prime_state(page: dict[str, Any], scope: str) -> dict[str, Any]:
    value: Any = page
    for key in ("init", "preparations", "body", scope, "state"):
        value = value.get(key) if isinstance(value, dict) else None
    return value if isinstance(value, dict) else {}


def first_detail(state: dict[str, Any], bucket: str) -> dict[str, Any]:
    details = state.get("detail") if isinstance(state.get("detail"), dict) else {}
    values = details.get(bucket) if isinstance(details.get(bucket), dict) else {}
    return next((value for value in values.values() if isinstance(value, dict)), {})


def prime_season_links(state: dict[str, Any], fallback_url: str) -> list[tuple[int, str]]:
    output: list[tuple[int, str]] = []
    seasons = state.get("seasons") if isinstance(state.get("seasons"), dict) else {}
    for choices in seasons.values():
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            number = int_value(choice.get("sequenceNumber"))
            link = absolute_prime_url(choice.get("seasonLink"))
            if number and link:
                output.append((number, link))
    if not output:
        output.append((int_value(first_detail(state, "headerDetail").get("seasonNumber")) or 1, fallback_url))
    unique = {number: url for number, url in output}
    return sorted(unique.items())


def prime_episode_records(page: dict[str, Any], season_number: int) -> list[dict[str, Any]]:
    btf = prime_state(page, "btf")
    details_root = btf.get("detail") if isinstance(btf.get("detail"), dict) else {}
    details = details_root.get("detail") if isinstance(details_root.get("detail"), dict) else {}
    selves = btf.get("self") if isinstance(btf.get("self"), dict) else {}
    actions_root = btf.get("action") if isinstance(btf.get("action"), dict) else {}
    actions = actions_root.get("btf") if isinstance(actions_root.get("btf"), dict) else {}
    episode_list = btf.get("episodeList") if isinstance(btf.get("episodeList"), dict) else {}
    ids = episode_list.get("cardTitleIds") if isinstance(episode_list.get("cardTitleIds"), list) else list(details)
    records: list[dict[str, Any]] = []
    for gti in ids:
        detail = details.get(gti) if isinstance(details.get(gti), dict) else {}
        self_item = selves.get(gti) if isinstance(selves.get(gti), dict) else {}
        if clean_text(detail.get("titleType")).casefold() != "episode":
            continue
        episode_number = int_value(detail.get("episodeNumber")) or int_value(self_item.get("sequenceNumber"))
        images = detail.get("images") if isinstance(detail.get("images"), dict) else {}
        action = actions.get(gti) if isinstance(actions.get(gti), dict) else {}
        playback = prime_playback(action)
        compact_id = first_non_empty(self_item.get("compactGTI"), prime_compact_id(self_item.get("link")))
        link = absolute_prime_url(self_item.get("link"))
        asins = [clean_text(value) for value in self_item.get("asins", []) if clean_text(value)] if isinstance(self_item.get("asins"), list) else []
        records.append({
            "id": clean_text(gti),
            "compact_id": compact_id,
            "asin": asins[0] if asins else "",
            "asins": asins,
            "url": link,
            "season": season_number,
            "episode": episode_number,
            "title": clean_text(detail.get("title")),
            "description": clean_text(detail.get("synopsis")),
            "date": iso_date(detail.get("releaseDate")),
            "year": clean_text(detail.get("releaseYear")),
            "duration_seconds": int_value(detail.get("duration")) or int_value(playback.get("runTime")),
            "runtime_minutes": runtime_minutes(detail),
            "image": clean_text(images.get("packshot")),
            "audio": text_list(detail.get("audioTracks")),
            "subtitles": text_list(detail.get("subtitles")),
            "features": prime_features(detail),
        })
    return [record for record in records if record["episode"] and record["title"]]


def prime_playback(action: dict[str, Any]) -> dict[str, Any]:
    primary = action.get("primaryActions") if isinstance(action.get("primaryActions"), list) else []
    for item in primary:
        if not isinstance(item, dict) or clean_text(item.get("actionType")) != "PLAY":
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        playback = payload.get("playback") if isinstance(payload.get("playback"), dict) else {}
        return playback
    return {}


def prime_series_metadata(
    selected: dict[str, Any],
    season_headers: list[tuple[int, dict[str, Any], str]],
    records: list[dict[str, Any]],
    source_url: str,
    trailer_url: str = "",
) -> dict[str, Any]:
    first_header = next((header for _number, header, _url in season_headers if header), selected)
    title = first_non_empty(selected.get("parentTitle"), first_header.get("parentTitle"), strip_season(selected.get("title")))
    images = selected.get("images") if isinstance(selected.get("images"), dict) else {}
    contributors = selected.get("contributors") if isinstance(selected.get("contributors"), dict) else {}
    rating = selected.get("amazonRating") if isinstance(selected.get("amazonRating"), dict) else {}
    reviews = selected.get("reviews") if isinstance(selected.get("reviews"), dict) else {}
    years = sorted({int_value(record.get("year")) for record in records if int_value(record.get("year"))})
    latest_date = max((clean_text(record.get("date")) for record in records), default="")
    fields: dict[str, list[str]] = {}
    add_field(fields, "Audio", text_list(selected.get("audioTracks")))
    add_field(fields, "Subtitles", text_list(selected.get("subtitles")))
    add_field(fields, "Accessibility and playback features", prime_features(selected))
    rating_asin = prime_review_asin(reviews)
    compact_id = prime_compact_id(source_url)
    add_field(fields, "Prime Video ID", compact_id)
    add_field(fields, "Amazon rating ASIN", rating_asin)
    tags = prime_provider_tags() + prime_rating_tags(rating, reviews)
    return {
        "source_url": source_url,
        "source_site": PRIME_NAME,
        "media_kind": "series",
        "title": title,
        "show_title": title,
        "outline": clean_text(first_header.get("synopsis")),
        "plot": clean_text(first_header.get("synopsis")),
        "year": str(years[0]) if years else clean_text(first_header.get("releaseYear")),
        "series_start_year": str(years[0]) if years else "",
        "series_end_year": str(years[-1]) if years else "",
        "series_is_current": is_current_release(latest_date),
        "date": iso_date(first_header.get("releaseDate")),
        "content_rating": clean_text((selected.get("ratingBadge") or {}).get("displayText")) if isinstance(selected.get("ratingBadge"), dict) else "",
        "numeric_rating": clean_text(rating.get("value")),
        "fanart_url": clean_text(images.get("packshot")),
        "thumb_url": clean_text(images.get("heroshot")),
        "logo_url": clean_text(images.get("titleLogo")),
        "trailer_url": clean_text(trailer_url),
        "production_label": "Studio",
        "genres": named_values(selected.get("genres"), "text"),
        "studios": text_list(selected.get("studios")),
        "directors": named_values(contributors.get("directors"), "name"),
        "credits": named_values(contributors.get("producers"), "name"),
        "actors": [{"name": name, "role": ""} for name in named_values(contributors.get("cast"), "name")],
        "tags": tags,
        "unique_ids": {key: value for key, value in (("primevideo", compact_id), ("amazon", rating_asin)) if value},
        "extra_fields": fields,
        "series_episodes": records,
        "folder_name_override": title,
    }


def prime_episode_metadata(series: dict[str, Any], record: dict[str, Any], source_url: str) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    add_field(fields, "Prime Video ID", record.get("compact_id"))
    add_field(fields, "Prime Video GTI", record.get("id"))
    add_field(fields, "Amazon ASIN", record.get("asin"))
    add_field(fields, "Runtime seconds", record.get("duration_seconds"))
    add_field(fields, "Audio", record.get("audio"))
    add_field(fields, "Subtitles", record.get("subtitles"))
    add_field(fields, "Accessibility and playback features", record.get("features"))
    return {
        "source_url": source_url,
        "source_site": PRIME_NAME,
        "media_kind": "episode",
        "title": series.get("title", ""),
        "show_title": series.get("title", ""),
        "season_number": str(record.get("season", "")),
        "episode_number": str(record.get("episode", "")),
        "episode_title": record.get("title", ""),
        "outline": record.get("description", ""),
        "plot": record.get("description", ""),
        "date": record.get("date", ""),
        "year": record.get("year", ""),
        "series_start_year": series.get("series_start_year", ""),
        "series_end_year": series.get("series_end_year", ""),
        "series_is_current": bool(series.get("series_is_current")),
        "runtime_minutes": record.get("runtime_minutes", ""),
        "content_rating": series.get("content_rating", ""),
        "thumb_url": record.get("image", ""),
        "tags": list(series.get("tags", [])),
        "studios": list(series.get("studios", [])),
        "genres": list(series.get("genres", [])),
        "unique_ids": {
            key: value for key, value in (
                ("primevideo", clean_text(record.get("compact_id"))),
                ("primevideo-gti", clean_text(record.get("id"))),
                ("amazon", clean_text(record.get("asin"))),
            ) if value
        },
        "extra_fields": fields,
        "series_episodes": list(series.get("series_episodes", [])),
        "series_metadata": series,
        "folder_name_override": series.get("title", ""),
    }


def prime_provider_tags() -> list[str]:
    return ["Prime Video", "Provider: Prime Video", "Amazon Prime Video Provider"]


def prime_rating_tags(rating: dict[str, Any], reviews: dict[str, Any]) -> list[str]:
    value = clean_text(rating.get("value"))
    count = clean_text(rating.get("countFormatted") or rating.get("count"))
    output = [f"amazonratings: {value} / 5 from {count} ratings"] if value and count else []
    model = reviews.get("reviewsAnalysisModel") if isinstance(reviews.get("reviewsAnalysisModel"), dict) else {}
    histogram = model.get("ratingsHistogram") if isinstance(model.get("ratingsHistogram"), dict) else {}
    names = (("fiveStar", "amazonrating5stars"), ("fourStar", "amazonrating4stars"), ("threeStar", "amazonrating3stars"), ("twoStar", "amazonrating2stars"), ("oneStar", "amazonrating1star"))
    for key, label in names:
        item = histogram.get(key) if isinstance(histogram.get(key), dict) else {}
        percentage = clean_text(item.get("percentageDisplay"))
        if percentage:
            output.append(f"{label}: {percentage}")
    return output


def prime_features(detail: dict[str, Any]) -> list[str]:
    values = []
    if detail.get("isClosedCaption"):
        values.append("Closed Captions")
    if any("audio description" in value.casefold() for value in text_list(detail.get("audioTracks"))):
        values.append("Audio Description")
    for key, label in (("isDolby51", "Dolby 5.1"), ("isDolbyAtmos", "Dolby Atmos"), ("isDolbyVision", "Dolby Vision"), ("isHdr", "HDR"), ("isHdr10Plus", "HDR10+"), ("isUhd", "UHD"), ("isXRay", "X-Ray"), ("isPrime", "Included with Prime")):
        if detail.get(key):
            values.append(label)
    return values


def prime_review_asin(reviews: dict[str, Any]) -> str:
    return first_non_empty(
        match_group(r"/product-reviews/([A-Z0-9]{10})", clean_text(reviews.get("allReviewsLink"))),
        match_group(r"[?&]asin=([A-Z0-9]{10})", clean_text(reviews.get("createReviewLink"))),
    )


def prime_trailer_page_url(state: dict[str, Any], base_url: str) -> str:
    """Return Prime's explicitly labelled public trailer page, never a normal play action."""
    stack: list[Any] = [state.get("action")]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if value.get("isTrailer") is True:
                playback_url = clean_text(value.get("playbackURL"))
                if playback_url:
                    absolute = urllib.parse.urljoin(base_url, html.unescape(playback_url))
                    parsed = urllib.parse.urlsplit(absolute)
                    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
                    if not any(key.casefold() == "autoplay" for key, _item in query):
                        query.append(("autoplay", "trailer"))
                    return urllib.parse.urlunsplit(
                        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
                    )
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return ""


def canonical_prime_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(clean_text(url))
    match = re.search(r"/(?:region/([^/]+)/)?detail/([A-Z0-9]+)", parsed.path, re.I)
    if not match:
        return clean_text(url)
    region = match.group(1) or "na"
    return f"https://www.primevideo.com/region/{region}/detail/{match.group(2).upper()}"


def absolute_prime_url(value: Any) -> str:
    text = html.unescape(clean_text(value)).replace("\\u0026", "&")
    if not text:
        return ""
    return canonical_prime_url(urllib.parse.urljoin("https://www.primevideo.com", text))


def prime_compact_id(value: Any) -> str:
    match = re.search(r"/detail/([A-Z0-9]+)", clean_text(value), re.I)
    return match.group(1).upper() if match else ""


def runtime_minutes(detail: dict[str, Any]) -> str:
    seconds = int_value(detail.get("duration"))
    if seconds:
        return str(max(1, round(seconds / 60)))
    return parse_runtime([clean_text(detail.get("runtime"))])


def iso_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for pattern in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return text


def is_current_release(value: str) -> bool:
    try:
        latest = dt.date.fromisoformat(value)
    except ValueError:
        return False
    today = dt.datetime.now(dt.timezone.utc).date()
    return 0 <= (today - latest).days <= 180


def strip_season(value: Any) -> str:
    return re.sub(r"\s*-?\s*Season\s+\d+\s*$", "", clean_text(value), flags=re.I)


def named_values(value: Any, key: str) -> list[str]:
    return dedupe(item.get(key) for item in value if isinstance(item, dict)) if isinstance(value, list) else []


def text_list(value: Any) -> list[str]:
    return dedupe(value if isinstance(value, list) else [value])


def add_field(fields: dict[str, list[str]], label: str, values: Any) -> None:
    for value in text_list(values):
        if value.casefold() not in {item.casefold() for item in fields.get(label, [])}:
            fields.setdefault(label, []).append(value)


def int_value(value: Any) -> int:
    try:
        return int(float(clean_text(value)))
    except ValueError:
        return 0


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {(int_value(record.get("season")), int_value(record.get("episode"))): record for record in records}
    return [unique[key] for key in sorted(unique) if all(key)]


def fetch_text(url: str, timeout: int = 25) -> str:
    result = subprocess.run(
        [
            "/usr/bin/curl",
            "--location",
            "--silent",
            "--show-error",
            "--compressed",
            "--retry",
            "2",
            "--retry-all-errors",
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
    if result.returncode == 0 and result.stdout:
        return result.stdout
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(result.stderr.strip() or str(exc) or f"curl exited with {result.returncode}") from exc


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
