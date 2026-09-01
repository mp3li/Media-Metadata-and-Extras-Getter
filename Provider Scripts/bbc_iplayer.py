#!/usr/bin/env python3
"""BBC iPlayer public episode and programme metadata helpers."""

from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any


NAME = "BBC iPlayer"
STUDIO_NAME = "BBC"
PAGE_HOSTS = {"bbc.co.uk", "www.bbc.co.uk", "iplayer.bbc.co.uk"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
IMAGE_RECIPE = "1920x1080"


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in PAGE_HOSTS and "/iplayer/episode/" in parsed.path


def episode_id_from_url(url: str) -> str:
    match = re.search(r"/iplayer/episode/([a-z0-9]{8})(?:/|$)", urllib.parse.urlparse(url).path, re.I)
    return clean_text(match.group(1)) if match else ""


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    state = extract_page_state(fetch_text(url, timeout=timeout))
    item = metadata_from_state(state, url)
    if item.get("media_kind") != "episode":
        return item
    related = as_dict(state.get("relatedEpisodes"))
    records = related_episode_records(related, clean_text(item.get("title")))
    current_slice = clean_text(related.get("currentSliceId"))
    for slice_item in as_list(related.get("slices")):
        slice_id = clean_text(as_dict(slice_item).get("id"))
        if not slice_id or slice_id == current_slice:
            continue
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        query["seriesId"] = [slice_id]
        slice_url = urllib.parse.urlunsplit(
            (parsed.scheme or "https", parsed.netloc, parsed.path, urllib.parse.urlencode(query, doseq=True), "")
        )
        try:
            slice_state = extract_page_state(fetch_text(slice_url, timeout=timeout))
        except Exception as exc:
            raise RuntimeError(
                f"BBC iPlayer series slice {slice_id} could not be loaded; refusing a partial Queue Mode catalog."
            ) from exc
        records.extend(
            related_episode_records(
                as_dict(slice_state.get("relatedEpisodes")), clean_text(item.get("title"))
            )
        )
    records = dedupe_episode_records(records)
    item["series_episodes"] = records
    years = sorted({clean_text(record.get("date"))[:4] for record in records if clean_text(record.get("date"))[:4].isdigit()})
    start = years[0] if years else clean_text(item.get("year"))
    end = years[-1] if years else start
    latest_dates = [clean_text(record.get("date")) for record in records if clean_text(record.get("date"))]
    latest = max(latest_dates, default="")
    current = False
    try:
        current = bool(latest and date.fromisoformat(latest) >= date.today() - timedelta(days=45))
    except ValueError:
        current = False
    item["series_start_year"] = start
    item["series_end_year"] = end
    item["series_is_current"] = current
    series = dict(item)
    series.update({
        "media_kind": "series",
        "show_title": clean_text(item.get("title")),
        "season_number": "",
        "episode_number": "",
        "episode_title": "",
        "date": "",
        "runtime_minutes": "",
        "series_metadata": {},
    })
    item["series_metadata"] = series
    return item


def metadata_from_state(state: dict[str, Any], source_url: str) -> dict[str, Any]:
    episode = as_dict(state.get("episode"))
    if not episode:
        raise ValueError("BBC iPlayer page did not expose episode metadata.")
    versions = as_list(state.get("versions"))
    version = first_dict(versions)
    synopses = as_dict(episode.get("synopses"))
    images = as_dict(episode.get("images"))
    related = as_dict(state.get("relatedEpisodes"))
    title = clean_text(episode.get("title"))
    subtitle = clean_text(episode.get("subtitle"))
    season, episode_number = series_and_episode(subtitle)
    if not season:
        season, episode_number = related_series_placement(related, clean_text(episode.get("id")))
    image_urls = dedupe(
        image_url(images.get(key))
        for key in ("standard", "promotional", "promotional_with_logo")
        if isinstance(images.get(key), str)
    )
    poster = image_urls[0] if image_urls else ""
    logo = image_urls[2] if len(image_urls) > 2 else ""
    programme_id = clean_text(episode.get("tleoId"))
    episode_id = clean_text(episode.get("id"))
    duration = duration_minutes(
        nested(version, "duration", "seconds") or episode.get("firstVersionDuration")
    )
    short = clean_text(synopses.get("small"))
    medium = clean_text(synopses.get("medium"))
    long = clean_text(synopses.get("large"))
    fields: dict[str, list[str]] = {}
    add_field(fields, "BBC Episode ID", episode_id)
    add_field(fields, "BBC Programme ID", programme_id)
    add_field(fields, "BBC Slice ID", clean_text(episode.get("sliceId")))
    add_field(fields, "Programme type", clean_text(episode.get("programmeType")))
    add_field(fields, "Series / episode label", subtitle)
    add_field(fields, "Short synopsis", short)
    add_field(fields, "Medium synopsis", medium)
    add_field(fields, "Programme synopsis", clean_text(synopses.get("programme_small")))
    add_field(fields, "First broadcast", clean_text(version.get("firstBroadcast")))
    add_field(fields, "Release date shown", clean_text(episode.get("releaseDate")))
    add_field(fields, "BBC channel", nested(episode, "masterBrand", "titles", "large"))
    add_field(fields, "Availability", nested(version, "availability", "remaining", "text"))
    add_field(fields, "Available until", nested(version, "availability", "end"))
    add_field(fields, "Available until", clean_text(version.get("isoEndTime")))
    add_field(fields, "Version ID", clean_text(version.get("id")))
    add_field(fields, "Version kind", clean_text(version.get("kind")))
    if version.get("hd") is not None:
        add_field(fields, "HD", "Yes" if version.get("hd") else "No")
    add_field(fields, "Exact duration seconds", nested(version, "duration", "seconds"))
    add_related_episode_fields(fields, related)
    return {
        "source_url": canonical_url(source_url),
        "source_site": NAME,
        "title": title,
        "outline": short or medium or long,
        "plot": long or medium or short,
        "year": year_from_date(clean_text(episode.get("releaseDateTime")) or clean_text(episode.get("releaseDate"))),
        "date": iso_date(clean_text(episode.get("releaseDateTime"))),
        "runtime_minutes": duration,
        "language": "",  # The page language is UI language, not a verified subtitle language.
        "poster_url": poster,
        "fanart_url": image_urls[1] if len(image_urls) > 1 else poster,
        "logo_url": logo,
        "production_label": "Broadcaster",
        "genres": [nested(episode, "labels", "category")],
        "studios": [STUDIO_NAME],
        "tags": [NAME, f"Provider: {NAME}", "BBC iPlayer Provider"],
        "unique_ids": {"bbc_iplayer": episode_id, "bbc_programme": programme_id},
        "extra_fields": fields,
        "folder_name_override": title,
        "media_kind": "episode" if season else "movie",
        "show_title": title if season else "",
        "season_number": str(season) if season else "",
        "episode_number": str(episode_number) if episode_number else "",
        "episode_title": episode_label(subtitle) if season else "",
        "bbc_episode_id": episode_id,
        "bbc_programme_id": programme_id,
    }


def related_episode_records(related: dict[str, Any], show_title: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for wrapper in as_list(related.get("episodes")):
        episode = as_dict(as_dict(wrapper).get("episode"))
        episode_id = clean_text(episode.get("id"))
        subtitle_default = nested(episode, "subtitle", "default")
        subtitle_slice = nested(episode, "subtitle", "slice")
        season, number = series_and_episode(subtitle_default)
        if not (episode_id and season and number):
            continue
        versions = as_list(episode.get("versions"))
        version = first_dict(versions)
        synopsis = as_dict(episode.get("synopsis")) or as_dict(episode.get("synopses"))
        images = as_dict(episode.get("images"))
        image = (
            image_url(images.get("standard")) if isinstance(images.get("standard"), str) else ""
        ) or (
            image_url(images.get("promotional")) if isinstance(images.get("promotional"), str) else ""
        )
        release = iso_date(
            clean_text(episode.get("releaseDateTime"))
            or clean_text(episode.get("releaseDate"))
            or clean_text(version.get("firstBroadcast"))
        )
        records.append({
            "id": episode_id,
            "url": canonical_episode_url(episode_id),
            "show_title": show_title,
            "season": season,
            "episode": number,
            "title": episode_label(subtitle_slice or subtitle_default),
            "description": clean_text(synopsis.get("large") or synopsis.get("medium") or synopsis.get("small")),
            "outline": clean_text(synopsis.get("small") or synopsis.get("medium") or synopsis.get("large")),
            "duration": clean_text(nested(version, "duration", "seconds") or episode.get("firstVersionDuration")),
            "date": release,
            "image": image,
        })
    return records


def dedupe_episode_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[tuple[int, int, str], dict[str, Any]] = {}
    for record in records:
        key = (int(record.get("season") or 0), int(record.get("episode") or 0), clean_text(record.get("id")))
        if key[0] and key[1] and key[2]:
            output[key] = record
    return sorted(output.values(), key=lambda record: (record["season"], record["episode"], record["id"]))


def fetch_series_episodes(url: str, timeout: int = 25) -> list[dict[str, Any]]:
    """Return the public episode cards for the selected iPlayer series slice."""
    state = extract_page_state(fetch_text(url, timeout=timeout))
    related = as_dict(state.get("relatedEpisodes"))
    return [as_dict(item).get("episode", {}) for item in as_list(related.get("episodes"))]


def canonical_episode_url(episode_id: str) -> str:
    return f"https://www.bbc.co.uk/iplayer/episode/{episode_id}"


def fetch_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(80 * 1024 * 1024).decode("utf-8", errors="replace")
    except Exception:
        result = subprocess.run(
            [
                "/usr/bin/curl", "--location", "--fail", "--silent", "--show-error", "--compressed",
                "--max-time", str(timeout), "--user-agent", USER_AGENT, url,
            ], capture_output=True, check=False, text=True, timeout=timeout + 10,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")
        return result.stdout


def extract_page_state(page: str) -> dict[str, Any]:
    match = re.search(
        r"(?:window\.)?__IPLAYER_REDUX_STATE__\s*=\s*(\{.*?\})\s*;</script>", page, re.S
    )
    if not match:
        raise ValueError("BBC iPlayer page-state data was not found.")
    try:
        state = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise ValueError("BBC iPlayer page-state data was invalid.") from exc
    return state if isinstance(state, dict) else {}


def image_url(value: str) -> str:
    return clean_text(value).replace("{recipe}", IMAGE_RECIPE)


def series_and_episode(subtitle: str) -> tuple[int, int]:
    match = re.search(r"\bSeries\s+(\d+)\s*:\s*Episode\s+(\d+)\b", subtitle, re.I)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def related_series_placement(related: dict[str, Any], episode_id: str) -> tuple[int, int]:
    """Place an untitled special as the final episode of its BBC series slice."""
    slice_id = clean_text(related.get("currentSliceId"))
    series_number = 0
    for item in as_list(related.get("slices")):
        item_dict = as_dict(item)
        if clean_text(item_dict.get("id")) != slice_id:
            continue
        match = re.fullmatch(r"Series\s+(\d+)", nested(item_dict, "title", "default"), re.I)
        if match:
            series_number = int(match.group(1))
        break
    if not series_number:
        return 0, 0
    cards = [as_dict(as_dict(item).get("episode")) for item in as_list(related.get("episodes"))]
    target_index = next((index for index, card in enumerate(cards) if clean_text(card.get("id")) == episode_id), -1)
    if target_index < 0:
        return 0, 0
    regular_numbers = []
    for card in cards:
        card_season, card_episode = series_and_episode(nested(card, "subtitle", "default"))
        if card_season == series_number and card_episode:
            regular_numbers.append(card_episode)
    if not regular_numbers:
        return 0, 0
    # iPlayer presents specials after the ordinary episodes in this series slice.
    return series_number, max(regular_numbers) + sum(
        1
        for card in cards[: target_index + 1]
        if not series_and_episode(nested(card, "subtitle", "default"))[0]
    )


def episode_label(subtitle: str) -> str:
    match = re.search(r"(?:^|:)\s*(Episode\s+\d+)\s*$", subtitle, re.I)
    return clean_text(match.group(1)) if match else clean_text(subtitle)


def duration_minutes(value: Any) -> str:
    text = clean_text(value)
    if text.isdigit():
        return str(round(int(text) / 60))
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", text, re.I)
    if not match:
        return ""
    seconds = int(match.group(1) or 0) * 3600 + int(match.group(2) or 0) * 60 + float(match.group(3) or 0)
    return str(round(seconds / 60))


def add_related_episode_fields(fields: dict[str, list[str]], related: dict[str, Any]) -> None:
    for item in as_list(related.get("episodes")):
        episode = as_dict(as_dict(item).get("episode"))
        if not episode:
            continue
        subtitle = nested(episode, "subtitle", "slice") or nested(episode, "subtitle", "default")
        duration = nested(first_dict(as_list(episode.get("versions"))), "duration", "text")
        availability = nested(first_dict(as_list(episode.get("versions"))), "availability", "remaining")
        description = nested(episode, "synopsis", "small")
        record = " | ".join(part for part in (subtitle, description, duration, availability, clean_text(episode.get("id"))) if part)
        add_field(fields, "Series episode", record)
    for item in as_list(related.get("slices")):
        label = nested(as_dict(item), "title", "default")
        slice_id = clean_text(as_dict(item).get("id"))
        if label and slice_id != "more-like-this":
            add_field(fields, "Available series / collection", f"{label} | {slice_id}")


def add_field(fields: dict[str, list[str]], label: str, value: Any) -> None:
    text = clean_text(value)
    if text and text not in fields.setdefault(label, []):
        fields[label].append(text)


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def first_dict(items: list[Any]) -> dict[str, Any]:
    return next((item for item in items if isinstance(item, dict)), {})


def nested(value: Any, *keys: str) -> str:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return clean_text(current)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def dedupe(values: Any) -> list[str]:
    output: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text.casefold() not in {item.casefold() for item in output}:
            output.append(text)
    return output


def year_from_date(value: str) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", value)
    return match.group(0) if match else ""


def iso_date(value: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return match.group(1) if match else ""


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme or "https", parsed.netloc, parsed.path, "", ""))
