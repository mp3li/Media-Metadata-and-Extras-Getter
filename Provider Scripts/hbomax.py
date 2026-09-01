#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Any


NAME = "HBO Max"
HOSTS = {"hbomax.com", "www.hbomax.com", "play.hbomax.com"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in HOSTS and bool(re.search(
        r"/(?:movie|show)/[0-9a-f-]{36}(?:/.*)?$|/video/watch/(?:[0-9a-f-]{36}|PROM\d+)$",
        parsed.path, re.I,
    ))


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    normalized = public_catalog_url(url)
    html_text = fetch_text(normalized, timeout=timeout)
    props = next_page_props(html_text)
    content = find_content_record(props)
    requested_id = content_id(url)
    if not content or not clean_text(content.get("title")) and not isinstance(content.get("title"), dict):
        if "/video/watch/" in urllib.parse.urlparse(url).path:
            raise ValueError(
                "The HBO Max player URL exposes only an episode ID publicly. Pass its public show/episode catalog URL, "
                "or use the show URL in Queue Mode so that ID can be matched against the complete episode guide."
            )
        raise ValueError("HBO Max did not expose public catalog metadata for this title.")

    is_movie = bool(content.get("featureId")) or "/movie/" in normalized
    if is_movie:
        return movie_metadata(content, normalized)

    content = complete_series_record(content, normalized, timeout=timeout)
    series = series_metadata(content, canonical_show_url(content, normalized))
    selected = next((record for record in series["series_episodes"] if record["id"] == requested_id), None)
    return episode_metadata(series, selected, normalized) if selected else series


def public_catalog_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(clean_text(url))
    return urllib.parse.urlunsplit(("https", "www.hbomax.com", parsed.path, "", ""))


def next_page_props(html_text: str) -> dict[str, Any]:
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html_text, re.I | re.S
    )
    if not match:
        return {}
    try:
        data = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return {}
    value = data.get("props", {}).get("pageProps", {})
    return value if isinstance(value, dict) else {}


def mapped_values(props: dict[str, Any]) -> list[Any]:
    mapped = props.get("mappedData") if isinstance(props.get("mappedData"), dict) else {}
    output: list[Any] = []
    for value in mapped.values():
        if isinstance(value, str) and value.lstrip().startswith("{"):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        output.append(value)
    return output


def find_content_record(props: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        value for value in mapped_values(props)
        if isinstance(value, dict)
        and clean_text(value.get("hbomaxId"))
        and isinstance(value.get("title"), dict)
        and isinstance(value.get("images"), dict)
    ]
    return max(candidates, key=lambda item: (bool(item.get("seasons")), len(item)), default={})


def complete_series_record(content: dict[str, Any], source_url: str, timeout: int) -> dict[str, Any]:
    seasons = content.get("seasons") if isinstance(content.get("seasons"), list) else []
    expected = sum(int_value(season.get("numberOfEpisodes")) for season in seasons if isinstance(season, dict))
    present = sum(len(season.get("episodes", [])) for season in seasons if isinstance(season, dict) and isinstance(season.get("episodes"), list))
    incomplete_season = any(
        isinstance(season, dict)
        and int_value(season.get("seasonNumber"))
        and not season.get("episodes")
        for season in seasons
    )
    if (present >= expected and not incomplete_season) or not seasons:
        return content
    first_url = next((
        clean_text(episode.get("episodeUrl"))
        for season in seasons if isinstance(season, dict)
        for episode in season.get("episodes", []) if isinstance(episode, dict)
        if clean_text(episode.get("episodeUrl"))
    ), "")
    if not first_url:
        return content
    try:
        richer = find_content_record(next_page_props(fetch_text(urllib.parse.urljoin(source_url, first_url), timeout=timeout)))
    except Exception:
        return content
    richer_seasons = richer.get("seasons") if isinstance(richer.get("seasons"), list) else []
    richer_count = sum(len(item.get("episodes", [])) for item in richer_seasons if isinstance(item, dict) and isinstance(item.get("episodes"), list))
    if richer_count <= present:
        return content
    merged = dict(content)
    merged.update(richer)
    for key in ("trailer", "flags"):
        if content.get(key) and not richer.get(key):
            merged[key] = content[key]
    return merged


def movie_metadata(item: dict[str, Any], source_url: str) -> dict[str, Any]:
    title = title_value(item)
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    images = item.get("images") if isinstance(item.get("images"), dict) else {}
    rating = item.get("localizedRating") if isinstance(item.get("localizedRating"), dict) else {}
    fields = common_fields(item)
    add_field(fields, "Feature ID", item.get("featureId"))
    add_language_fields(fields, item)
    trailer = trailer_fields(fields, item)
    return {
        "source_url": source_url, "source_site": NAME, "media_kind": "movie",
        "title": title, "outline": clean_text(summary.get("short")), "plot": clean_text(summary.get("full")),
        "year": clean_text(item.get("releaseYear")), "date": iso_date(item.get("releaseDate")),
        "runtime_minutes": runtime_minutes(item.get("runtime")),
        "content_rating": clean_text(rating.get("classifier")),
        "poster_url": image(images, "cover-artwork"),
        "fanart_url": image(images, "default-wide"),
        "thumb_url": image(images, "cover-artwork-horizontal"),
        "logo_url": image(images, "logo-centered"),
        "gallery_urls": dedupe([image(images, "centered-background")]),
        "genres": string_list(item.get("genres")), "studios": string_list(item.get("brand")),
        **credit_fields(item), "tags": provider_tags(),
        "unique_ids": {"hbomax": clean_text(item.get("hbomaxId"))},
        "trailer_url": trailer,
        "extra_fields": fields, "extra_videos": extra_video_records(item),
        "folder_name_override": title,
    }


def series_metadata(item: dict[str, Any], source_url: str) -> dict[str, Any]:
    title = title_value(item)
    summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
    images = item.get("images") if isinstance(item.get("images"), dict) else {}
    rating = item.get("localizedRating") if isinstance(item.get("localizedRating"), dict) else {}
    records = episode_records(item, source_url)
    fields = common_fields(item)
    add_language_fields(fields, item)
    add_field(fields, "Season count", item.get("numberOfSeasons") or len(item.get("seasons", [])))
    add_field(fields, "Episode count", item.get("numberOfEpisodes") or len(records))
    for season in item.get("seasons", []):
        if isinstance(season, dict):
            add_field(fields, f"Season {int_value(season.get('seasonNumber'))} episode count", season.get("numberOfEpisodes"))
            add_field(fields, f"Season {int_value(season.get('seasonNumber'))} ID", season.get("seasonId"))
    trailer = trailer_fields(fields, item)
    start_year = clean_text(item.get("releaseYear"))
    dated_years = [record["year"] for record in records if record["year"].isdigit()]
    end_year = max(dated_years, default=start_year)
    status = clean_text(item.get("seriesStatus") or item.get("productionStatus")).casefold()
    if status in {"ended", "completed", "cancelled", "canceled"}:
        current = False
    elif status in {"returning", "returning series", "continuing", "active", "in production"}:
        current = True
    elif dated_years:
        current = int(end_year) >= dt.date.today().year
    else:
        # Max exposes no reliable end-state on many public catalog records. Keep
        # the range open rather than falsely declaring a completion year.
        current = True
    return {
        "source_url": source_url, "source_site": NAME, "media_kind": "series",
        "title": title, "show_title": title,
        "outline": clean_text(summary.get("short")), "plot": clean_text(summary.get("full")),
        "year": start_year, "series_start_year": start_year, "series_end_year": end_year,
        "series_is_current": current, "content_rating": clean_text(rating.get("classifier")),
        "poster_url": image(images, "cover-artwork"), "fanart_url": image(images, "default-wide"),
        "thumb_url": image(images, "cover-artwork-horizontal"), "logo_url": image(images, "logo-centered"),
        "gallery_urls": dedupe([image(images, "centered-background")]),
        "genres": string_list(item.get("genres")), "studios": string_list(item.get("brand")),
        **credit_fields(item), "tags": provider_tags(),
        "unique_ids": {"hbomax": clean_text(item.get("hbomaxId"))},
        "extra_fields": fields, "series_episodes": records,
        "trailer_url": trailer,
        "extra_videos": extra_video_records(item), "folder_name_override": title,
    }


def episode_metadata(series: dict[str, Any], record: dict[str, Any], source_url: str) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    add_field(fields, "HBO Max episode ID", record.get("id"))
    add_field(fields, "Episode page", record.get("url"))
    add_field(fields, "Availability start", record.get("availability_start"))
    add_field(fields, "Availability end", record.get("availability_end"))
    add_field(fields, "Audio", record.get("audio"))
    add_field(fields, "Subtitles", record.get("subtitles"))
    return {
        "source_url": source_url, "source_site": NAME, "media_kind": "episode",
        "title": series["title"], "show_title": series["title"],
        "season_number": str(record["season"]), "episode_number": str(record["episode"]),
        "episode_title": record["title"], "outline": record["outline"], "plot": record["description"],
        "date": record.get("date", ""), "year": record["year"],
        "runtime_minutes": record.get("runtime_minutes", ""),
        "content_rating": series.get("content_rating", ""),
        "thumb_url": record.get("image", ""),
        "genres": list(series.get("genres", [])), "studios": list(series.get("studios", [])),
        "tags": list(series.get("tags", [])), "unique_ids": {"hbomax": record["id"]},
        "extra_fields": fields, "series_episodes": list(series.get("series_episodes", [])),
        "series_metadata": series, "folder_name_override": series["title"],
    }


def episode_records(item: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for season in item.get("seasons", []):
        if not isinstance(season, dict):
            continue
        season_number = int_value(season.get("seasonNumber"))
        for episode in season.get("episodes", []):
            if not isinstance(episode, dict):
                continue
            url = absolute_max_url(episode.get("episodeUrl"))
            episode_id = content_id(url)
            images = episode.get("images") if isinstance(episode.get("images"), dict) else {}
            summary = episode.get("summary") if isinstance(episode.get("summary"), dict) else {}
            dates = episode.get("offeringDates") if isinstance(episode.get("offeringDates"), dict) else {}
            premiere = first_text(episode, "releaseDate", "airDate", "originalAirDate", "premiereDate", "datePublished")
            runtime = first_text(episode, "runtime", "duration", "runningTime")
            audio = language_values(episode, "audioLanguages", "audioLanguage", "audioTracks")
            subtitles = language_values(
                episode, "subtitleLanguages", "subtitleLanguage", "subtitleTracks", "subtitles"
            )
            output.append({
                "id": episode_id, "url": url, "season_id": clean_text(season.get("seasonId")),
                "season": season_number, "episode": int_value(episode.get("episodeNumber")),
                "title": title_value(episode), "outline": clean_text(summary.get("short")),
                "description": clean_text(summary.get("full")),
                "image": image(images, "default"),
                "date": iso_date(premiere),
                "runtime_minutes": runtime_minutes(runtime),
                "audio": audio, "subtitles": subtitles,
                "availability_start": iso_datetime(dates.get("startDate")),
                "availability_end": iso_datetime(dates.get("endDate")),
                "year": str(date_year(premiere)) if date_year(premiere) else "",
            })
    unique = {(record["season"], record["episode"], record["id"]): record for record in output if record["season"] and record["episode"] and record["id"]}
    return sorted(unique.values(), key=lambda record: (record["season"], record["episode"]))


def common_fields(item: dict[str, Any]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    rating = item.get("localizedRating") if isinstance(item.get("localizedRating"), dict) else {}
    add_field(fields, "HBO Max ID", item.get("hbomaxId"))
    add_field(fields, "Primary genre", item.get("primaryGenre"))
    add_field(fields, "Secondary genre", item.get("secondaryGenre"))
    add_field(fields, "Provider brand", item.get("brand"))
    add_field(fields, "Rating authority", rating.get("rating_authority"))
    add_field(fields, "Rating descriptors", rating.get("descriptors"))
    credits = item.get("credits") if isinstance(item.get("credits"), dict) else {}
    add_field(fields, "Created by", credits.get("creators"))
    add_field(fields, "Source material by", credits.get("sources"))
    return fields


def trailer_fields(fields: dict[str, list[str]], item: dict[str, Any]) -> str:
    trailer = item.get("trailer") if isinstance(item.get("trailer"), dict) else {}
    page = absolute_max_url(trailer.get("url"), play=True)
    add_field(fields, "Trailer title", trailer.get("title"))
    add_field(fields, "Trailer description", trailer.get("description"))
    add_field(fields, "Trailer program ID", trailer.get("programId"))
    add_field(fields, "Trailer page", page)
    return page


def add_language_fields(fields: dict[str, list[str]], item: dict[str, Any]) -> None:
    add_field(fields, "Audio", language_values(item, "audioLanguages", "audioLanguage", "audioTracks"))
    add_field(
        fields,
        "Subtitles",
        language_values(item, "subtitleLanguages", "subtitleLanguage", "subtitleTracks", "subtitles"),
    )


def first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if clean_text(value) and not isinstance(value, (dict, list)):
            return clean_text(value)
    for container_key in ("metadata", "details", "playback"):
        nested = item.get(container_key)
        if isinstance(nested, dict):
            value = first_text(nested, *keys)
            if value:
                return value
    return ""


def language_values(item: dict[str, Any], *keys: str) -> list[str]:
    output: list[str] = []
    for key in keys:
        if key in item:
            output.extend(named_values(item.get(key)))
    for container_key in ("metadata", "details", "playback"):
        nested = item.get(container_key)
        if isinstance(nested, dict):
            output.extend(language_values(nested, *keys))
    return dedupe(output)


def named_values(value: Any) -> list[str]:
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, list):
        return dedupe([item for value_item in value for item in named_values(value_item)])
    if isinstance(value, dict):
        for key in ("displayName", "localizedName", "label", "name", "languageName"):
            if clean_text(value.get(key)):
                return [clean_text(value[key])]
        return dedupe([
            item
            for key, nested in value.items()
            if key not in {"id", "url", "href", "type"}
            for item in named_values(nested)
        ])
    return [clean_text(value)] if clean_text(value) else []


def credit_fields(item: dict[str, Any]) -> dict[str, Any]:
    credits = item.get("credits") if isinstance(item.get("credits"), dict) else {}
    return {
        "actors": [{"name": name, "role": ""} for name in csv_values(credits.get("starring"))],
        "directors": csv_values(credits.get("directors")), "writers": csv_values(credits.get("writers")),
        "credits": csv_values(credits.get("producers")),
    }


def extra_video_records(item: dict[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for key in ("extras", "videos"):
        for value in item.get(key, []) if isinstance(item.get(key), list) else []:
            if not isinstance(value, dict):
                continue
            url = absolute_max_url(value.get("url"), play=True)
            if url:
                output.append({"title": title_value(value), "description": clean_text(value.get("description")), "url": url, "kind": "extra"})
    return output


def provider_tags() -> list[str]:
    return ["HBO Max", "Provider: HBO Max", "HBO Max Provider"]


def canonical_show_url(item: dict[str, Any], fallback: str) -> str:
    path = clean_text(item.get("imageUrlLink"))
    return absolute_max_url(path) or fallback


def absolute_max_url(value: Any, play: bool = False) -> str:
    text = clean_text(value)
    if not text:
        return ""
    host = "https://play.hbomax.com" if play and text.startswith("/video/watch/") else "https://www.hbomax.com"
    return urllib.parse.urljoin(host, text)


def content_id(value: Any) -> str:
    matches = re.findall(r"(?:[0-9a-f]{8}-[0-9a-f-]{27}|PROM\d+)", clean_text(value), re.I)
    return matches[-1] if matches else ""


def image(images: dict[str, Any], key: str) -> str:
    return clean_text(images.get(key))


def title_value(item: dict[str, Any]) -> str:
    title = item.get("title") if isinstance(item.get("title"), dict) else {}
    return clean_text(title.get("full") or title.get("short"))


def add_field(fields: dict[str, list[str]], label: str, value: Any) -> None:
    values = string_list(value)
    if values:
        fields[label] = dedupe(fields.get(label, []) + values)


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    return [clean_text(value)] if clean_text(value) else []


def csv_values(value: Any) -> list[str]:
    return dedupe([clean_text(item) for item in clean_text(value).split(",") if clean_text(item)])


def dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        if text and text.casefold() not in seen:
            seen.add(text.casefold()); output.append(text)
    return output


def runtime_minutes(value: Any) -> str:
    text = clean_text(value)
    iso = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", text, re.I)
    if iso:
        seconds = int(iso.group(1) or 0) * 3600 + int(iso.group(2) or 0) * 60 + float(iso.group(3) or 0)
        return str(max(1, round(seconds / 60))) if seconds else ""
    hours = int_value(re.search(r"(\d+)\s*h", text, re.I).group(1)) if re.search(r"(\d+)\s*h", text, re.I) else 0
    minutes = int_value(re.search(r"(\d+)\s*m", text, re.I).group(1)) if re.search(r"(\d+)\s*m", text, re.I) else 0
    return str(hours * 60 + minutes) if hours or minutes else ""


def iso_date(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", clean_text(value))
    return match.group(0) if match else ""


def iso_datetime(value: Any) -> str:
    return clean_text(value)


def date_year(value: Any) -> int:
    match = re.search(r"(\d{4})", clean_text(value))
    return int(match.group(1)) if match else 0


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def fetch_text(url: str, timeout: int = 25) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        result = subprocess.run([
            "/usr/bin/curl", "--location", "--silent", "--show-error", "--compressed",
            "--max-time", str(timeout), "--user-agent", USER_AGENT, url,
        ], capture_output=True, check=False)
        if result.returncode:
            raise ValueError("Unable to retrieve the public HBO Max catalog page.")
        return result.stdout.decode("utf-8", errors="replace")
