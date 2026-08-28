#!/usr/bin/env python3
"""Public Crunchyroll series and episode metadata helpers."""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


NAME = "Crunchyroll"
PAGE_HOSTS = {"crunchyroll.com", "www.crunchyroll.com"}
API_ROOT = "https://www.crunchyroll.com/content/v2/cms"
TOKEN_URL = "https://www.crunchyroll.com/auth/v1/token"
LOCALE = "en-US"
USER_AGENT = "Crunchyroll/1.8.0"

_TOKEN = ""
_TOKEN_EXPIRES_AT = 0.0

LOCALE_NAMES = {
    "ar-SA": "العربية",
    "de-DE": "Deutsch",
    "en-US": "English",
    "es-419": "Español (América Latina)",
    "es-ES": "Español (España)",
    "fr-FR": "Français",
    "hi-IN": "हिंदी",
    "id-ID": "Bahasa Indonesia",
    "it-IT": "Italiano",
    "ja-JP": "Japanese",
    "ms-MY": "Bahasa Melayu",
    "pl-PL": "Polski",
    "pt-BR": "Português (Brasil)",
    "ru-RU": "Русский",
    "th-TH": "ไทย",
    "vi-VN": "Tiếng Việt",
    "zh-CN": "中文 (简体)",
    "zh-HK": "中文 (繁體)",
}


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    if parsed.netloc.casefold() not in PAGE_HOSTS:
        return False
    return bool(re.search(r"/(?:series|watch)/[A-Z0-9]+(?:/|$)", parsed.path, re.I))


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    normalized = canonical_url(url)
    parsed = parse_url(normalized)
    if parsed[0] == "series":
        return extract_series_metadata(parsed[1], normalized, timeout=timeout)
    if parsed[0] == "episode":
        return extract_episode_metadata(parsed[1], normalized, timeout=timeout)
    raise ValueError("Crunchyroll metadata supports public series and watch pages.")


def extract_series_metadata(series_id: str, source_url: str = "", timeout: int = 25) -> dict[str, Any]:
    series_object = first_data(api_get(f"objects/{series_id}", timeout=timeout))
    if not series_object:
        raise ValueError("Crunchyroll series metadata was not found.")
    series_detail = first_data(api_get(f"series/{series_id}", timeout=timeout))
    nested = as_dict(series_object.get("series_metadata"))
    detail = series_detail or nested
    episodes = series_episode_guide(series_id, timeout=timeout)
    rating = as_dict(series_object.get("rating"))
    audio_locales = dedupe(detail.get("audio_locales") or nested.get("audio_locales") or [])
    subtitle_locales = dedupe(detail.get("subtitle_locales") or nested.get("subtitle_locales") or [])
    descriptors = dedupe(detail.get("content_descriptors") or nested.get("content_descriptors") or [])
    title = clean_text(series_object.get("title"))
    canonical = source_url or canonical_series_url(series_id, clean_text(series_object.get("slug_title")))
    poster = largest_image(series_object.get("images"), "poster_tall")
    cover = largest_image(series_object.get("images"), "poster_wide")
    logo = title_logo_url(series_id)
    fields: dict[str, list[str]] = {}
    add_field(fields, "Average Rating", average_rating_text(rating))
    add_field(fields, "Audio", locale_names(audio_locales))
    add_field(fields, "Subtitles", locale_names(subtitle_locales))
    add_field(fields, "Sub and Dub Available", yes_no(detail.get("is_subbed") and detail.get("is_dubbed")))
    add_field(fields, "Content Advisory", descriptors)
    add_field(fields, "Crunchyroll series ID", series_id)
    add_field(fields, "Episode count", detail.get("episode_count") or nested.get("episode_count"))
    add_field(fields, "Season count", detail.get("season_count") or nested.get("season_count"))
    add_field(fields, "Season tag", detail.get("season_tags") or nested.get("season_tags") or [])
    tags = provider_tags(detail)
    tags.extend(series_rating_tags(rating))
    return {
        "source_url": canonical,
        "source_site": NAME,
        "media_kind": "series",
        "title": title,
        "show_title": title,
        "outline": clean_text(series_object.get("description")),
        "plot": clean_text(series_object.get("description")),
        "year": clean_text(detail.get("series_launch_year") or nested.get("series_launch_year")),
        "numeric_rating": clean_text(rating.get("average")),
        "content_rating": first_value(detail.get("maturity_ratings") or nested.get("maturity_ratings")),
        "poster_url": poster,
        "fanart_url": cover,
        "logo_url": logo,
        "production_label": "Studio",
        "genres": dedupe(nested.get("tenant_categories") or []),
        "tags": tags,
        "studios": dedupe([series_detail.get("content_provider")]),
        "unique_ids": {"crunchyroll": series_id},
        "extra_fields": fields,
        "series_episodes": episodes,
        "folder_name_override": title,
        "warnings": [],
    }


def extract_episode_metadata(episode_id: str, source_url: str = "", timeout: int = 25) -> dict[str, Any]:
    episode_object = first_data(api_get(f"objects/{episode_id}", timeout=timeout))
    episode_detail = first_data(api_get(f"episodes/{episode_id}", timeout=timeout))
    if not episode_object and not episode_detail:
        raise ValueError("Crunchyroll episode metadata was not found.")
    embedded = as_dict(episode_object.get("episode_metadata"))
    detail = episode_detail or embedded
    series_id = clean_text(detail.get("series_id") or embedded.get("series_id"))
    series_object = first_data(api_get(f"objects/{series_id}", timeout=timeout)) if series_id else {}
    series_nested = as_dict(series_object.get("series_metadata"))
    series_detail = first_data(api_get(f"series/{series_id}", timeout=timeout)) if series_id else {}
    title = clean_text(episode_object.get("title") or detail.get("title"))
    show_title = clean_text(detail.get("series_title") or embedded.get("series_title") or series_object.get("title"))
    season = int_value(detail.get("season_number") or embedded.get("season_number")) or 1
    episode = int_value(detail.get("episode_number") or embedded.get("episode_number"))
    slug = clean_text(episode_object.get("slug_title") or detail.get("slug_title"))
    canonical = source_url or canonical_episode_url(episode_id, slug)
    rating = as_dict(episode_object.get("rating"))
    descriptors = dedupe(detail.get("content_descriptors") or embedded.get("content_descriptors") or series_nested.get("content_descriptors") or [])
    audio_locales = version_audio_locales(detail.get("versions") or embedded.get("versions") or [])
    subtitle_locales = dedupe(detail.get("subtitle_locales") or embedded.get("subtitle_locales") or [])
    tags = provider_tags(detail)
    vote_tag = episode_rating_tag(rating)
    if vote_tag:
        tags.append(vote_tag)
    tags.extend(series_rating_tags(as_dict(series_object.get("rating"))))
    next_id = clean_text(detail.get("next_episode_id"))
    next_title = clean_text(detail.get("next_episode_title"))
    next_link = canonical_episode_url(next_id, "") if next_id else ""
    fields: dict[str, list[str]] = {}
    add_field(fields, "Audio", locale_names(audio_locales))
    add_field(fields, "Subtitles", locale_names(subtitle_locales))
    add_field(fields, "Sub and Dub Available", yes_no(detail.get("is_subbed") and detail.get("is_dubbed")))
    add_field(fields, "Content Advisory", descriptors)
    add_field(fields, "Crunchyroll series ID", series_id)
    add_field(fields, "Average Rating", average_rating_text(as_dict(series_object.get("rating"))))
    add_field(fields, "Episode count", series_detail.get("episode_count") or series_nested.get("episode_count"))
    add_field(fields, "Season count", series_detail.get("season_count") or series_nested.get("season_count"))
    add_field(fields, "Season tag", series_detail.get("season_tags") or series_nested.get("season_tags") or [])
    duration_ms = int_value(detail.get("duration_ms") or embedded.get("duration_ms"))
    original_audio = original_audio_name(detail.get("versions") or embedded.get("versions") or [])
    air_date = clean_text(detail.get("episode_air_date") or embedded.get("episode_air_date"))
    upload_date = clean_text(detail.get("upload_date") or embedded.get("upload_date"))
    add_field(fields, "Exact runtime", exact_runtime(duration_ms))
    add_field(fields, "Original Audio", original_audio)
    add_field(fields, "Air date", air_date)
    add_field(fields, "Upload date", upload_date)
    add_field(fields, "Next Episode", " | ".join(value for value in (next_title, next_link) if value))
    record = episode_record(episode_object, detail, preferred_id=episode_id)
    return {
        "source_url": canonical,
        "source_site": NAME,
        "media_kind": "episode",
        "title": show_title,
        "show_title": show_title,
        "season_number": str(season),
        "episode_number": str(episode),
        "episode_title": title,
        "outline": clean_text(episode_object.get("description") or detail.get("description")),
        "plot": clean_text(episode_object.get("description") or detail.get("description")),
        "year": year_from_date(detail.get("episode_air_date") or embedded.get("episode_air_date")),
        "date": iso_date(detail.get("episode_air_date") or embedded.get("episode_air_date")),
        "runtime_minutes": duration_minutes(duration_ms),
        "content_rating": first_value(detail.get("maturity_ratings") or embedded.get("maturity_ratings") or series_nested.get("maturity_ratings")),
        "poster_url": largest_image(series_object.get("images"), "poster_tall"),
        "fanart_url": largest_image(series_object.get("images"), "poster_wide"),
        "logo_url": title_logo_url(series_id),
        "thumb_url": thumbnail_image(episode_object.get("images") or detail.get("images")),
        "language": original_audio,
        "production_label": "Studio",
        "genres": dedupe(embedded.get("tenant_categories") or series_nested.get("tenant_categories") or []),
        "tags": dedupe(tags),
        "studios": dedupe([series_detail.get("content_provider")]),
        "unique_ids": {},
        "extra_fields": fields,
        "series_episodes": [record] if record else [],
        "folder_name_override": show_title,
    }


def series_episode_guide(series_id: str, timeout: int = 25) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for season in data_list(api_get(f"series/{series_id}/seasons", timeout=timeout)):
        season_number = int_value(season.get("season_number")) or int_value(season.get("season_sequence_number")) or 1
        season_id = preferred_version_id(season.get("versions"), fallback=clean_text(season.get("id")), prefer_original=True)
        if not season_id:
            continue
        for episode in data_list(api_get(f"seasons/{season_id}/episodes", timeout=timeout)):
            record = episode_record({}, episode)
            if record:
                record["season"] = season_number
                records.append(record)
    return dedupe_records(records)


def episode_record(episode_object: dict[str, Any], detail: dict[str, Any], preferred_id: str = "") -> dict[str, Any]:
    episode_number = int_value(detail.get("episode_number"))
    if not episode_number:
        return {}
    episode_id = preferred_id or preferred_version_id(detail.get("versions"), fallback=clean_text(detail.get("id")))
    title = clean_text(episode_object.get("title") or detail.get("title"))
    return {
        "id": episode_id,
        "url": canonical_episode_url(episode_id, clean_text(episode_object.get("slug_title") or detail.get("slug_title"))),
        "show_title": clean_text(detail.get("series_title")),
        "season": int_value(detail.get("season_number")) or 1,
        "episode": episode_number,
        "title": title,
        "description": clean_text(episode_object.get("description") or detail.get("description")),
        "duration": duration_minutes(detail.get("duration_ms")),
        "date": iso_date(detail.get("episode_air_date")),
        "image": thumbnail_image(episode_object.get("images") or detail.get("images")),
    }


def api_get(path: str, timeout: int = 25) -> dict[str, Any]:
    separator = "&" if "?" in path else "?"
    url = f"{API_ROOT}/{path}{separator}locale={urllib.parse.quote(LOCALE)}"
    return request_json(url, timeout=timeout, token=anonymous_token(timeout=timeout))


def anonymous_token(timeout: int = 25) -> str:
    global _TOKEN, _TOKEN_EXPIRES_AT
    if _TOKEN and time.time() < _TOKEN_EXPIRES_AT - 60:
        return _TOKEN
    form = urllib.parse.urlencode(
        {
            "grant_type": "client_id",
            "client_id": "cr_web",
            "device_id": str(uuid.uuid4()),
            "device_type": "Chrome on OS X",
            "device_name": "Chrome",
        }
    ).encode("utf-8")
    payload = request_json(TOKEN_URL, timeout=timeout, form=form)
    token = clean_text(payload.get("access_token"))
    if not token:
        raise RuntimeError("Crunchyroll did not return an anonymous metadata token.")
    _TOKEN = token
    _TOKEN_EXPIRES_AT = time.time() + int_value(payload.get("expires_in"), 3600)
    return token


def request_json(
    url: str, timeout: int = 25, token: str = "", form: bytes | None = None
) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=form, headers=headers, method="POST" if form is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read(30 * 1024 * 1024).decode("utf-8", errors="replace"))
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    command = [
        "/usr/bin/curl", "--http1.1", "--location", "--fail", "--silent", "--show-error",
        "--compressed", "--max-time", str(timeout), "--user-agent", USER_AGENT,
        "--header", "Accept: application/json",
    ]
    if token:
        command.extend(["--header", f"Authorization: Bearer {token}"])
    if form is not None:
        command.extend(["--request", "POST", "--header", "Content-Type: application/x-www-form-urlencoded", "--data", form.decode("utf-8")])
    command.append(url)
    result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Crunchyroll metadata request failed.")
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Crunchyroll returned invalid metadata JSON.") from error
    return parsed if isinstance(parsed, dict) else {}


def parse_url(url: str) -> tuple[str, str]:
    match = re.search(r"/(series|watch)/([A-Z0-9]+)(?:/|$)", urllib.parse.urlparse(url).path, re.I)
    if not match:
        return "", ""
    return ("episode" if match.group(1).casefold() == "watch" else "series", match.group(2).upper())


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(clean_text(url))
    return urllib.parse.urlunsplit((parsed.scheme or "https", parsed.netloc, parsed.path.rstrip("/"), "", ""))


def canonical_series_url(series_id: str, slug: str) -> str:
    suffix = f"/{slug}" if slug else ""
    return f"https://www.crunchyroll.com/series/{series_id}{suffix}"


def canonical_episode_url(episode_id: str, slug: str) -> str:
    suffix = f"/{slug}" if slug else ""
    return f"https://www.crunchyroll.com/watch/{episode_id}{suffix}" if episode_id else ""


def provider_tags(detail: dict[str, Any]) -> list[str]:
    tags = [NAME, f"Provider: {NAME}"]
    if detail.get("is_subbed"):
        tags.append("Subtitled")
    if detail.get("is_dubbed"):
        tags.append("Dubbed")
    return tags


def episode_rating_tag(rating: dict[str, Any]) -> str:
    up = rating_count(as_dict(rating.get("up")))
    down = rating_count(as_dict(rating.get("down")))
    return f"crunchyrollratings: {up} upvotes / {down} downvotes" if up and down else ""


def series_rating_tags(rating: dict[str, Any]) -> list[str]:
    """Return the exact, ordered tags consumed by the user's Jellyfin plugin."""
    average = clean_text(rating.get("average"))
    total = int_value(rating.get("total"))
    tags: list[str] = []
    if average and total:
        tags.append(f"crunchyrollrating: {average} / 5 from {total:,} ratings")
    for stars in range(5, 0, -1):
        item = as_dict(rating.get(f"{stars}s"))
        count = rating_count(item)
        percentage = clean_text(item.get("percentage"))
        if not (count and percentage):
            continue
        label = f"crunchyrollrating{stars}star" + ("s" if stars != 1 else "")
        tags.append(f"{label}: {count} / {percentage}%")
    return tags


def rating_count(value: dict[str, Any]) -> str:
    displayed = clean_text(value.get("displayed"))
    unit = clean_text(value.get("unit")).casefold()
    return displayed + unit if displayed else ""


def average_rating_text(rating: dict[str, Any]) -> str:
    average = clean_text(rating.get("average"))
    total = int_value(rating.get("total"))
    return f"{average} ({compact_count(total)})" if average and total else average


def compact_count(value: int) -> str:
    if value >= 1000:
        return f"{int(value / 100) / 10:g}k"
    return str(value) if value else ""


def largest_image(images: Any, *types: str) -> str:
    source = as_dict(images)
    candidates: list[dict[str, Any]] = []
    for image_type in types:
        candidates.extend(flatten_dicts(source.get(image_type)))
    if not candidates:
        for key, value in source.items():
            if "logo" in clean_text(key).casefold() and any("logo" in wanted.casefold() for wanted in types):
                candidates.extend(flatten_dicts(value))
    best = max(candidates, key=lambda item: int_value(item.get("width")) * int_value(item.get("height")), default={})
    return clean_text(best.get("source"))


def thumbnail_image(images: Any) -> str:
    """Choose a smaller 16:9 rendition suitable for Jellyfin's episode thumb."""
    candidates = flatten_dicts(as_dict(images).get("thumbnail"))
    sized = [item for item in candidates if int_value(item.get("width")) > 0]
    preferred = [item for item in sized if int_value(item.get("width")) <= 640]
    best = max(preferred or sized, key=lambda item: int_value(item.get("width")) * int_value(item.get("height")), default={})
    return clean_text(best.get("source"))


def title_logo_url(series_id: str) -> str:
    identifier = clean_text(series_id)
    if not identifier:
        return ""
    return (
        "https://imgsrv.crunchyroll.com/cdn-cgi/image/"
        f"fit=contain,format=png,quality=100,width=1200/keyart/{identifier}-title_logo-en-us"
    )


def flatten_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    output: list[dict[str, Any]] = []
    for item in value:
        output.extend(flatten_dicts(item))
    return output


def preferred_version_id(versions: Any, fallback: str = "", prefer_original: bool = False) -> str:
    items = [item for item in versions if isinstance(item, dict)] if isinstance(versions, list) else []
    if prefer_original:
        original = next((item for item in items if item.get("original") is True), {})
        if original:
            return clean_text(original.get("guid"))
    english = next((item for item in items if clean_text(item.get("audio_locale")) == LOCALE), {})
    return clean_text(english.get("guid")) or fallback


def version_audio_locales(versions: Any) -> list[str]:
    return dedupe(item.get("audio_locale") for item in versions if isinstance(item, dict)) if isinstance(versions, list) else []


def original_audio_name(versions: Any) -> str:
    if not isinstance(versions, list):
        return ""
    original = next((item for item in versions if isinstance(item, dict) and item.get("original") is True), {})
    return LOCALE_NAMES.get(clean_text(original.get("audio_locale")), clean_text(original.get("audio_locale")))


def locale_names(locales: Any) -> list[str]:
    return [LOCALE_NAMES.get(value, value) for value in dedupe(locales)]


def duration_minutes(value: Any) -> str:
    milliseconds = int_value(value)
    return str(round(milliseconds / 60000)) if milliseconds else ""


def exact_runtime(value: Any) -> str:
    milliseconds = int_value(value)
    if not milliseconds:
        return ""
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    clock = f"{hours}:{minutes:02d}:{seconds:02d}.{millis:03d}" if hours else f"{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{clock} | {milliseconds:,} ms"


def iso_date(value: Any) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", clean_text(value))
    return match.group(1) if match else ""


def year_from_date(value: Any) -> str:
    return iso_date(value)[:4]


def add_field(fields: dict[str, list[str]], label: str, value: Any) -> None:
    values = value if isinstance(value, (list, tuple, set)) else [value]
    for item in values:
        text = clean_text(item)
        if text and text not in fields.setdefault(label, []):
            fields[label].append(text)


def first_data(payload: dict[str, Any]) -> dict[str, Any]:
    return next(iter(data_list(payload)), {})


def data_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", []) if isinstance(payload, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def first_value(value: Any) -> str:
    values = dedupe(value if isinstance(value, list) else [value])
    return values[0] if values else ""


def yes_no(value: Any) -> str:
    return "Yes" if bool(value) else "No"


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def dedupe(values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
    return output


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for record in records:
        key = (int_value(record.get("season")), int_value(record.get("episode")))
        if key not in seen:
            output.append(record)
            seen.add(key)
    return sorted(output, key=lambda item: (int_value(item.get("season")), int_value(item.get("episode"))))
