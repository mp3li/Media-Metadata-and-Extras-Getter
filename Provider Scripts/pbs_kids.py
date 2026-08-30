#!/usr/bin/env python3
"""Public PBS KIDS series, playlist, and episode metadata helpers."""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Any


NAME = "PBS KIDS"
STUDIO_NAME = "PBS KIDS"
PAGE_HOSTS = {"pbskids.org", "www.pbskids.org"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    if parsed.netloc.casefold() not in PAGE_HOSTS:
        return False
    path = parsed.path.rstrip("/")
    return bool(
        re.fullmatch(r"/videos/playlist/[^/]+/\d+", path, re.I)
        or re.fullmatch(r"/videos/watch/[^/]+/\d+/[^/]+/\d+", path, re.I)
        or re.fullmatch(r"/videos/(?!playlist$|watch$)[^/]+", path, re.I)
    )


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    if not is_supported_url(url):
        raise ValueError("PBS KIDS links need a series, full-episode playlist, or episode watch URL.")
    normalized = canonical_page_url(url)
    pages: dict[str, dict[str, Any]] = {}

    def load(page_url: str) -> dict[str, Any]:
        key = canonical_page_url(page_url)
        if key not in pages:
            pages[key] = page_props(extract_next_data(fetch_text(key, timeout=timeout)))
        return pages[key]

    initial = load(normalized)
    route = route_parts(normalized)
    property_data = property_from_props(initial)
    series_slug = clean_text(property_data.get("slug")) or clean_text(route.get("series_slug"))
    if not series_slug:
        raise ValueError("PBS KIDS page did not expose its parent series.")
    series_url = f"https://pbskids.org/videos/{series_slug}"
    series_props = initial if route["kind"] == "series" else load(series_url)
    property_data = merge_dicts(property_from_props(series_props), property_data)

    collection = collection_from_props(initial, route)
    if not collection:
        collection = episodes_collection(series_props)
    if not collection and route["kind"] == "watch":
        context = initial.get("contextData") if isinstance(initial.get("contextData"), dict) else {}
        context_slug = clean_text(context.get("slug")) or clean_text(route.get("collection_slug"))
        context_id = clean_text(context.get("id")) or clean_text(route.get("collection_id"))
        if context_slug and context_id:
            playlist_url = f"https://pbskids.org/videos/playlist/{context_slug}/{context_id}"
            collection = collection_from_props(load(playlist_url), {"kind": "playlist"})

    entries = collection.get("entries") if isinstance(collection, dict) else []
    entries = [entry for entry in entries if isinstance(entry, dict) and clean_text(entry.get("videoType")) == "fullEpisode"]
    current_video = initial.get("videoData") if route["kind"] == "watch" and isinstance(initial.get("videoData"), dict) else {}
    if current_video and not any(clean_text(entry.get("id")) == clean_text(current_video.get("id")) for entry in entries):
        entries.append(current_video)

    collection_slug = clean_text(collection.get("slug")) if isinstance(collection, dict) else ""
    collection_id = clean_text(collection.get("id")) if isinstance(collection, dict) else ""
    collection_slug = collection_slug or clean_text(route.get("collection_slug"))
    collection_id = collection_id or clean_text(route.get("collection_id"))
    records = enrich_episode_records(
        entries,
        collection_slug,
        collection_id,
        current_video=current_video,
        current_props=initial,
        timeout=timeout,
    )
    if not records:
        raise ValueError("PBS KIDS page did not expose any currently available full episodes.")

    series = series_metadata(
        series_props,
        property_data,
        collection if isinstance(collection, dict) else {},
        records,
        series_url,
    )
    if route["kind"] != "watch":
        return series
    video_id = clean_text(route.get("video_id"))
    record = next((item for item in records if clean_text(item.get("id")) == video_id), None)
    if not record:
        raise ValueError("PBS KIDS watch page did not expose the selected episode.")
    return episode_metadata(series, record, normalized)


def series_metadata(
    series_props: dict[str, Any],
    property_data: dict[str, Any],
    collection: dict[str, Any],
    records: list[dict[str, Any]],
    source_url: str,
) -> dict[str, Any]:
    title = first_non_empty(property_data.get("title"), series_props.get("pageProperty", {}).get("title"))
    description = clean_text(series_props.get("pageDescription"))
    logo = first_asset_url(property_data.get("logo"))
    thumb = first_asset_url(property_data.get("mezzanine"))
    return {
        "source_url": source_url,
        "source_site": NAME,
        "media_kind": "series",
        "title": title,
        "show_title": title,
        "outline": description,
        "plot": description,
        "logo_url": logo,
        "thumb_url": thumb,
        "production_label": "Network",
        "tags": provider_tags(),
        "studios": [STUDIO_NAME],
        "unique_ids": {},
        "extra_fields": {},
        "series_episodes": records,
        "folder_name_override": title,
    }


def episode_metadata(series: dict[str, Any], record: dict[str, Any], source_url: str) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    add_field(fields, "PBS KIDS video ID", record.get("id"))
    add_field(fields, "Legacy PBS media ID", record.get("legacy_id"))
    add_field(fields, "Video type", record.get("type"))
    add_field(fields, "Runtime seconds", record.get("duration_seconds"))
    unique_ids = {
        key: clean_text(value)
        for key, value in (
            ("pbskids", record.get("id")),
            ("pbs", record.get("legacy_id")),
        )
        if clean_text(value)
    }
    return {
        "source_url": source_url,
        "source_site": NAME,
        "media_kind": "episode",
        "title": series.get("title", ""),
        "show_title": series.get("title", ""),
        "season_number": str(record.get("season", "")),
        "episode_number": str(record.get("episode", "")),
        "episode_title": record.get("title", ""),
        "outline": record.get("short_description", ""),
        "plot": record.get("long_description") or record.get("short_description", ""),
        "date": record.get("date", ""),
        "year": clean_text(record.get("date"))[:4],
        "runtime_minutes": record.get("runtime_minutes", ""),
        "thumb_url": record.get("image", ""),
        "logo_url": series.get("logo_url", ""),
        "production_label": "Network",
        "tags": provider_tags(),
        "studios": [STUDIO_NAME],
        "unique_ids": unique_ids,
        "extra_fields": fields,
        "series_episodes": list(series.get("series_episodes", [])),
        "series_metadata": series,
        "folder_name_override": series.get("title", ""),
    }


def enrich_episode_records(
    entries: list[dict[str, Any]],
    collection_slug: str,
    collection_id: str,
    current_video: dict[str, Any],
    current_props: dict[str, Any],
    timeout: int,
) -> list[dict[str, Any]]:
    current_id = clean_text(current_video.get("id"))

    def enrich(entry: dict[str, Any]) -> dict[str, Any]:
        video_id = clean_text(entry.get("id"))
        slug = clean_text(entry.get("slug"))
        watch_url = (
            f"https://pbskids.org/videos/watch/{collection_slug}/{collection_id}/{slug}/{video_id}"
            if collection_slug and collection_id and slug and video_id
            else ""
        )
        full = current_video if video_id == current_id else {}
        props = current_props if video_id == current_id else {}
        if not full and watch_url:
            try:
                props = page_props(extract_next_data(fetch_text(watch_url, timeout=timeout)))
                full = props.get("videoData") if isinstance(props.get("videoData"), dict) else {}
            except Exception:
                full = {}
        return episode_record(entry, full, props, watch_url)

    workers = min(6, max(1, len(entries)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        records = list(executor.map(enrich, entries))
    unique = {clean_text(record.get("id")): record for record in records if clean_text(record.get("id"))}
    return sorted(
        unique.values(),
        key=lambda item: (
            int(item.get("season") or 9999),
            int(item.get("episode") or 9999),
            clean_text(item.get("title")),
        ),
    )


def episode_record(entry: dict[str, Any], full: dict[str, Any], props: dict[str, Any], watch_url: str) -> dict[str, Any]:
    merged = merge_dicts(entry, full)
    media = merge_dicts(
        entry.get("mediaManagerAsset") if isinstance(entry.get("mediaManagerAsset"), dict) else {},
        full.get("mediaManagerAsset") if isinstance(full.get("mediaManagerAsset"), dict) else {},
    )
    duration = integer_value(media.get("duration"))
    premiered = first_non_empty(media.get("premiered_on"), nested_value(entry, ("mediaManagerAsset", "premiered_on")))
    image = preferred_episode_image(media.get("images"))
    video_id = clean_text(merged.get("id"))
    return {
        "id": video_id,
        "guid": first_non_empty(media.get("id"), entry.get("guid")),
        "legacy_id": clean_text(media.get("legacy_tp_media_id")),
        "url": watch_url,
        "title": first_non_empty(media.get("title"), merged.get("title")),
        "season": integer_value(media.get("season_number")),
        "episode": integer_value(media.get("episode_number")),
        "type": display_video_type(merged.get("videoType")),
        "short_description": first_non_empty(props.get("videoDescription"), media.get("description_short")),
        "long_description": first_non_empty(media.get("description_long"), media.get("description_short")),
        "duration_seconds": duration,
        "runtime_minutes": str(max(1, round(duration / 60))) if duration else "",
        "date": epoch_date(premiered),
        "created_date": epoch_date(merged.get("dateCreated"), include_time=True),
        "expiry_date": epoch_date(merged.get("expiryDate"), include_time=True),
        "image": image,
        "drm_enabled": media.get("drm_enabled"),
    }


def route_parts(url: str) -> dict[str, str]:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    match = re.fullmatch(r"/videos/watch/([^/]+)/(\d+)/([^/]+)/(\d+)", path, re.I)
    if match:
        return {
            "kind": "watch",
            "collection_slug": match.group(1),
            "collection_id": match.group(2),
            "video_slug": match.group(3),
            "video_id": match.group(4),
        }
    match = re.fullmatch(r"/videos/playlist/([^/]+)/(\d+)", path, re.I)
    if match:
        return {"kind": "playlist", "collection_slug": match.group(1), "collection_id": match.group(2)}
    match = re.fullmatch(r"/videos/([^/]+)", path, re.I)
    return {"kind": "series", "series_slug": match.group(1) if match else ""}


def collection_from_props(props: dict[str, Any], route: dict[str, str]) -> dict[str, Any]:
    if route.get("kind") == "playlist" and isinstance(props.get("collectionData"), dict):
        return props["collectionData"]
    if route.get("kind") == "series":
        return episodes_collection(props)
    return {}


def episodes_collection(props: dict[str, Any]) -> dict[str, Any]:
    modules = nested_value(props, ("pageData", "bodyContentModules"))
    for module in modules if isinstance(modules, list) else []:
        if not isinstance(module, dict) or clean_text(module.get("heading")).casefold() != "episodes":
            continue
        collections = module.get("collection")
        if isinstance(collections, list):
            return next((item for item in collections if isinstance(item, dict)), {})
    return {}


def property_from_props(props: dict[str, Any]) -> dict[str, Any]:
    page_property = props.get("pageProperty") if isinstance(props.get("pageProperty"), dict) else {}
    video = props.get("videoData") if isinstance(props.get("videoData"), dict) else {}
    collection = props.get("collectionData") if isinstance(props.get("collectionData"), dict) else {}
    for source in (video, collection):
        properties = source.get("properties")
        if isinstance(properties, list):
            value = next((item for item in properties if isinstance(item, dict)), None)
            if value:
                return merge_dicts(page_property, value)
    episode_collection = episodes_collection(props)
    properties = episode_collection.get("properties") if isinstance(episode_collection, dict) else []
    if isinstance(properties, list):
        value = next((item for item in properties if isinstance(item, dict)), None)
        if value:
            return merge_dicts(page_property, value)
    return page_property


def preferred_episode_image(images: Any) -> str:
    values = [item for item in images if isinstance(item, dict)] if isinstance(images, list) else []
    for profile in ("asset-kids-mezzanine1-16x9", "asset-kids-mezzanine-16x9"):
        found = next((clean_text(item.get("image")) for item in values if clean_text(item.get("profile")) == profile), "")
        if found:
            return found
    return next((clean_text(item.get("image")) for item in values if clean_text(item.get("image"))), "")


def first_asset_url(value: Any) -> str:
    items = value if isinstance(value, list) else []
    for item in items:
        if isinstance(item, dict):
            url = first_non_empty(item.get("url"), item.get("its_url"))
            if url:
                return url
    return ""


def display_video_type(value: Any) -> str:
    text = clean_text(value)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text).title()


def epoch_date(value: Any, include_time: bool = False) -> str:
    number = integer_value(value)
    if not number:
        return ""
    moment = dt.datetime.fromtimestamp(number, tz=dt.timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC" if include_time else "%Y-%m-%d")


def integer_value(value: Any) -> int:
    text = clean_text(value)
    try:
        return int(float(text)) if text else 0
    except ValueError:
        return 0


def provider_tags() -> list[str]:
    return [NAME, f"Provider: {NAME}", "PBS KIDS Provider"]


def add_field(fields: dict[str, list[str]], label: Any, value: Any) -> None:
    key = clean_text(label)
    text = clean_text(value)
    if key and text and text.casefold() not in {item.casefold() for item in fields.get(key, [])}:
        fields.setdefault(key, []).append(text)


def merge_dicts(first: Any, second: Any) -> dict[str, Any]:
    output = dict(first) if isinstance(first, dict) else {}
    if isinstance(second, dict):
        for key, value in second.items():
            if value not in (None, "", [], {}):
                output[key] = value
    return output


def nested_value(data: Any, path: tuple[Any, ...]) -> Any:
    value = data
    for key in path:
        if isinstance(key, int) and isinstance(value, list) and 0 <= key < len(value):
            value = value[key]
        elif isinstance(key, str) and isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def first_non_empty(*values: Any) -> str:
    return next((clean_text(value) for value in values if clean_text(value)), "")


def page_props(data: dict[str, Any]) -> dict[str, Any]:
    value = nested_value(data, ("props", "pageProps"))
    return value if isinstance(value, dict) else {}


def extract_next_data(page: str) -> dict[str, Any]:
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        page,
        re.I | re.S,
    )
    if not match:
        raise ValueError("PBS KIDS page did not expose its public Next.js data.")
    value = json.loads(html.unescape(match.group(1)))
    if not isinstance(value, dict):
        raise ValueError("PBS KIDS public page data was not an object.")
    return value


def canonical_page_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(clean_text(url))
    return urllib.parse.urlunsplit(("https", "pbskids.org", parsed.path.rstrip("/"), "", ""))


def fetch_text(url: str, timeout: int = 25, max_bytes: int = 80 * 1024 * 1024) -> str:
    result = subprocess.run(
        [
            "/usr/bin/curl", "--location", "--silent", "--show-error", "--compressed",
            "--max-time", str(timeout), "--user-agent", USER_AGENT, url,
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout[:max_bytes]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(max_bytes).decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(result.stderr.strip() or str(exc) or "PBS KIDS returned an empty page.") from exc


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()
