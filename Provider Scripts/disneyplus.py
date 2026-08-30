#!/usr/bin/env python3
"""Public Disney+ movie, series, and episode metadata helpers."""

from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Any

NAME = "Disney+"
STUDIO_NAME = "Disney+"
PAGE_HOSTS = {"disneyplus.com", "www.disneyplus.com"}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def is_disneyplus_url(url: str) -> bool:
    return urllib.parse.urlparse(clean_text(url)).netloc.casefold() in PAGE_HOSTS


def is_supported_url(url: str) -> bool:
    return bool(is_disneyplus_url(url) and (entity_id_from_url(url) or play_id_from_url(url)))


def entity_id_from_url(url: str) -> str:
    match = re.search(r"/browse/entity-([0-9a-f-]+)", urllib.parse.urlparse(clean_text(url)).path, re.I)
    return clean_text(match.group(1)) if match else ""


def play_id_from_url(url: str) -> str:
    match = re.search(r"/play/([0-9a-f-]+)", urllib.parse.urlparse(clean_text(url)).path, re.I)
    return clean_text(match.group(1)) if match else ""


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    if not is_supported_url(url):
        raise ValueError("Disney+ links need a /browse/entity-... or /play/... ID.")
    page = fetch_text(url, timeout=timeout)
    data = extract_next_data(page)
    main = main_content(data)
    metadata_block = content_block(main, "Metadata")
    hero = content_block(main, "DetailEntityHero")
    details = content_block(main, "MediaDetails")
    episodes = content_block(main, "Episodes")
    canonical = meta_content(metadata_block, "og:url") or canonical_url(page) or url
    entity_id = entity_id_from_url(canonical) or entity_id_from_url(url)
    if episodes.get("seriesTitle") or episodes.get("seasons"):
        series = series_metadata(hero, details, episodes, metadata_block, canonical, entity_id, data)
        play_id = play_id_from_url(url)
        if not play_id:
            return series
        record = next((item for item in series["series_episodes"] if item.get("id") == play_id), None)
        if not record:
            raise ValueError("Disney+ play page did not expose the selected episode in its public series guide.")
        return episode_metadata(series, record, url)
    if play_id_from_url(url):
        raise ValueError("Disney+ play page did not expose a public episode-to-series relationship.")
    return movie_metadata(hero, details, metadata_block, canonical, entity_id, data)


def series_metadata(hero: dict[str, Any], details: dict[str, Any], episodes: dict[str, Any], metadata_block: dict[str, Any], source_url: str, entity_id: str, data: dict[str, Any]) -> dict[str, Any]:
    title = clean_title(first_non_empty(episodes.get("seriesTitle"), details.get("title"), meta_content(metadata_block, "og:title")))
    short_description = first_non_empty(meta_content(metadata_block, "description"), hero.get("synopsisText"))
    description = first_non_empty(details.get("summary"), hero.get("synopsisText"), short_description)
    release = first_non_empty(details.get("release"), hero.get("releaseYear"))
    start_year, end_year, current = release_years(release)
    records = episode_records(episodes, title)
    seasons = episodes.get("seasons") if isinstance(episodes.get("seasons"), list) else []
    icons = detail_icon_labels(hero)
    rating = content_rating(hero, details)
    directors, cast, creators = credits_from_details(details.get("credits"))
    social = meta_content(metadata_block, "og:image")
    hero_image = image_source(hero.get("backgroundImage"))
    backdrop = social or hero_image
    fields: dict[str, list[str]] = {}
    add_field(fields, "Disney+ entity ID", entity_id)
    add_field(fields, "Season count", str(len(seasons)) if seasons else number_text(hero.get("seasonsAvailable")))
    add_field(fields, "Release range", release)
    for value in icons:
        if value != rating:
            add_field(fields, "Accessibility", value)
    for creator in creators:
        add_field(fields, "Creator", creator)
    for season in seasons:
        if isinstance(season, dict):
            add_field(fields, "Available season", f"{clean_text(season.get('name'))} | {clean_text(season.get('id'))}")
    for record in records:
        add_field(fields, "Episode guide", f"S{record['season']:02d}E{record['episode']:02d} | {record['title']} | {record['id']}")
    return {
        "source_url": source_url, "source_site": NAME, "media_kind": "series",
        "title": title, "show_title": title, "outline": short_description or description, "plot": description,
        "year": start_year, "series_start_year": start_year, "series_end_year": end_year,
        "series_is_current": current, "content_rating": rating,
        "poster_url": "", "fanart_url": backdrop, "thumb_url": hero_image or backdrop,
        "logo_url": trimmed_png_logo_url(hero.get("titleVisual")), "trailer_url": public_trailer_url(data),
        "production_label": "Provider", "genres": split_values(hero.get("genres") or details.get("genres")),
        "tags": provider_tags(), "studios": [STUDIO_NAME], "directors": directors,
        "actors": [{"name": name, "role": ""} for name in cast],
        "unique_ids": {"disneyplus": entity_id} if entity_id else {}, "extra_fields": fields,
        "gallery_urls": [], "series_episodes": records,
        "folder_name_override": title,
    }


def episode_metadata(series: dict[str, Any], record: dict[str, Any], source_url: str) -> dict[str, Any]:
    fields: dict[str, list[str]] = {}
    series_fields = series.get("extra_fields", {})
    add_field(fields, "Disney+ entity ID", first_value(series_fields.get("Disney+ entity ID")))
    add_field(fields, "Disney+ episode ID", record.get("id"))
    add_field(fields, "Episode page", source_url)
    add_field(fields, "Season count", first_value(series_fields.get("Season count")))
    for value in series_fields.get("Accessibility", []):
        add_field(fields, "Accessibility", value)
    return {
        "source_url": source_url, "source_site": NAME, "media_kind": "episode",
        "title": series.get("title", ""), "show_title": series.get("title", ""),
        "season_number": str(record.get("season", "")), "episode_number": str(record.get("episode", "")),
        "episode_title": record.get("title", ""), "outline": record.get("description", ""),
        "plot": record.get("description", ""), "year": series.get("year", ""),
        "series_start_year": series.get("series_start_year", ""),
        "series_end_year": series.get("series_end_year", ""),
        "series_is_current": bool(series.get("series_is_current")),
        "content_rating": series.get("content_rating", ""), "poster_url": series.get("poster_url", ""),
        "fanart_url": series.get("fanart_url", ""), "logo_url": series.get("logo_url", ""),
        "thumb_url": record.get("image", ""), "trailer_url": series.get("trailer_url", ""),
        "production_label": "Provider", "genres": list(series.get("genres", [])),
        "tags": provider_tags(), "studios": list(series.get("studios", [])),
        "directors": list(series.get("directors", [])), "actors": list(series.get("actors", [])),
        "unique_ids": {"disneyplus": record.get("id", "")} if record.get("id") else {},
        "extra_fields": fields, "series_episodes": [record], "series_metadata": series,
        "folder_name_override": series.get("title", ""),
    }


def movie_metadata(hero: dict[str, Any], details: dict[str, Any], metadata_block: dict[str, Any], source_url: str, entity_id: str, data: dict[str, Any]) -> dict[str, Any]:
    json_ld = extract_ldjson(metadata_block)
    title = clean_title(first_non_empty(json_ld.get("name"), details.get("title"), meta_content(metadata_block, "og:title")))
    short_description = first_non_empty(json_ld.get("description"), meta_content(metadata_block, "description"), hero.get("synopsisText"))
    description = first_non_empty(details.get("summary"), hero.get("synopsisText"), short_description)
    release = first_non_empty(details.get("release"), hero.get("releaseYear"), json_ld.get("datePublished"))
    directors, cast, creators = credits_from_details(details.get("credits"))
    social = meta_content(metadata_block, "og:image") or clean_text(json_ld.get("image"))
    hero_image = image_source(hero.get("backgroundImage"))
    backdrop = social or hero_image
    rating = content_rating(hero, details)
    fields: dict[str, list[str]] = {}
    add_field(fields, "Disney+ entity ID", entity_id)
    add_field(fields, "Release date", release)
    for creator in creators:
        add_field(fields, "Creator", creator)
    for value in detail_icon_labels(hero):
        if value != rating:
            add_field(fields, "Accessibility", value)
    return {
        "source_url": source_url, "source_site": NAME, "media_kind": "movie", "title": title,
        "outline": short_description or description, "plot": description, "year": first_year(release),
        "runtime_minutes": first_non_empty(runtime_minutes_from_ms(hero.get("runtimeMs")), runtime_minutes_from_ms(details.get("runtimeMs"))),
        "content_rating": rating, "poster_url": "", "fanart_url": backdrop,
        "thumb_url": hero_image or backdrop, "logo_url": trimmed_png_logo_url(hero.get("titleVisual")),
        "trailer_url": public_trailer_url(data), "production_label": "Provider",
        "genres": split_values(hero.get("genres") or details.get("genres") or json_ld.get("genre")),
        "tags": provider_tags(), "studios": [STUDIO_NAME], "directors": directors,
        "actors": [{"name": name, "role": ""} for name in cast],
        "unique_ids": {"disneyplus": entity_id} if entity_id else {}, "extra_fields": fields,
        "gallery_urls": [], "folder_name_override": title,
    }


def episode_records(block: dict[str, Any], show_title: str) -> list[dict[str, Any]]:
    groups = block.get("seoSeasons")
    groups = list(groups) if isinstance(groups, list) else []
    selected_episodes = block.get("episodes")
    if isinstance(selected_episodes, list) and selected_episodes:
        # Disney keeps older seasons in seoSeasons and the selected/latest
        # season in episodes. Merge both; the identity key below deduplicates
        # one-season pages that repeat the same cards in both locations.
        groups.append({"episodes": selected_episodes})
    records: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        for card in group.get("episodes") or []:
            if not isinstance(card, dict):
                continue
            match = re.match(r"S(\d+)\s*:\s*E(\d+)\s+(.+)", clean_text(card.get("title")), re.I)
            episode_id = clean_text(card.get("_id"))
            if not (match and episode_id):
                continue
            image = image_source(card.get("imageVariants")) or ripcut_image_url(card.get("imageVariants"), 1920, "1.78")
            records.append({
                "id": episode_id, "url": f"https://www.disneyplus.com/play/{episode_id}",
                "show_title": show_title, "season": int(match.group(1)), "episode": int(match.group(2)),
                "title": clean_text(match.group(3)),
                "description": clean_text((card.get("metadata") or {}).get("summary")),
                "duration": "", "date": "", "image": image,
            })
    unique = {(item["season"], item["episode"], item["id"]): item for item in records}
    return sorted(unique.values(), key=lambda item: (item["season"], item["episode"]))


def main_content(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = nested_value(data, ("props", "pageProps", "stitchDocument", "mainContent"))
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def content_block(main: list[dict[str, Any]], type_name: str) -> dict[str, Any]:
    return next((item for item in main if clean_text(item.get("_type")) == type_name), {})


def release_years(value: Any) -> tuple[str, str, bool]:
    text = clean_text(value)
    years = re.findall(r"\b(?:19|20)\d{2}\b", text)
    return (years[0], years[-1], bool(re.search(r"(?:present|current|ongoing)\b", text, re.I))) if years else ("", "", False)


def first_year(value: Any) -> str:
    match = re.search(r"\b((?:19|20)\d{2})\b", clean_text(value))
    return match.group(1) if match else ""


def content_rating(hero: dict[str, Any], details: dict[str, Any]) -> str:
    for item in details.get("ratings") or []:
        if isinstance(item, dict) and isinstance(item.get("image"), dict):
            value = clean_text(item["image"].get("alt"))
            if value:
                return value
    return next((value for value in detail_icon_labels(hero) if re.fullmatch(r"[A-Z0-9-]+", value)), "")


def detail_icon_labels(hero: dict[str, Any]) -> list[str]:
    icons = hero.get("detailIcons")
    return dedupe_text([item.get("alt") for item in icons if isinstance(item, dict)]) if isinstance(icons, list) else []


def credits_from_details(credits: Any) -> tuple[list[str], list[str], list[str]]:
    directors: list[str] = []
    cast: list[str] = []
    creators: list[str] = []
    for credit in credits if isinstance(credits, list) else []:
        if not isinstance(credit, dict):
            continue
        heading = clean_text(credit.get("heading")).casefold().rstrip(":")
        values = dedupe_text([item.get("displayText") for item in credit.get("items") or [] if isinstance(item, dict)])
        if heading in {"director", "directors"}:
            directors.extend(values)
        elif heading in {"cast", "starring"}:
            cast.extend(values)
        elif heading in {"creator", "creators", "created by"}:
            creators.extend(values)
    return dedupe_text(directors), dedupe_text(cast), dedupe_text(creators)


def image_source(image_block: Any) -> str:
    if not isinstance(image_block, dict):
        return ""
    for key in ("xxlargeImage", "xlargeImage", "largeImage", "defaultImage", "mediumImage", "smallImage"):
        value = image_block.get(key)
        if isinstance(value, dict) and clean_text(value.get("source")):
            source = clean_text(value.get("source"))
            return "https:" + source if source.startswith("//") else source
    return ""


def ripcut_image_url(image_block: Any, width: int, aspect_ratio: str) -> str:
    if not isinstance(image_block, dict):
        return ""
    for key in ("xxlargeImage", "xlargeImage", "largeImage", "defaultImage", "mediumImage", "smallImage"):
        value = image_block.get(key)
        if isinstance(value, dict):
            ripcut_id = clean_text(value.get("ripcutId") or value.get("imageId"))
            if ripcut_id:
                return f"https://disney.images.edge.bamgrid.com/ripcut-delivery/v2/variant/disney/{ripcut_id}/compose?aspectRatio={aspect_ratio}&format=webp&width={width}"
    return ""


def trimmed_png_logo_url(image_block: Any) -> str:
    """Request Disney's own tightly trimmed title art as an actual PNG."""
    if not isinstance(image_block, dict):
        return ""
    for key in ("xxlargeImage", "xlargeImage", "largeImage", "defaultImage", "mediumImage", "smallImage"):
        value = image_block.get(key)
        if not isinstance(value, dict):
            continue
        ripcut_id = clean_text(value.get("ripcutId") or value.get("imageId"))
        if ripcut_id:
            return (
                "https://disney.images.edge.bamgrid.com/ripcut-delivery/v2/variant/disney/"
                f"{ripcut_id}/trim?format=png&max=800%7C300"
            )
    return ""


def public_trailer_url(data: Any) -> str:
    """Accept only trailer-labelled public media, never a Disney+ /play page."""
    if isinstance(data, dict):
        label = " ".join(clean_text(data.get(key)) for key in ("title", "label", "name", "kind"))
        if "trailer" in label.casefold():
            for key in ("mediaUrl", "streamingUrl", "videoUrl", "url"):
                value = clean_text(data.get(key))
                if urllib.parse.urlparse(value).path.casefold().endswith((".mp4", ".m3u8", ".mpd")):
                    return value
        for value in data.values():
            found = public_trailer_url(value)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = public_trailer_url(item)
            if found:
                return found
    return ""


def provider_tags(additional: list[str] | None = None) -> list[str]:
    return dedupe_text([NAME, f"Provider: {NAME}", "Disney+ Provider", *(additional or [])])


def fetch_text(url: str, timeout: int = 25, max_bytes: int = 80 * 1024 * 1024) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read(max_bytes).decode("utf-8", errors="replace")
            if text.strip():
                return text
    except Exception:
        pass
    result = subprocess.run(
        ["/usr/bin/curl", "--location", "--fail", "--silent", "--show-error", "--compressed", "--max-time", str(timeout), "--max-filesize", str(max_bytes), "--user-agent", USER_AGENT, url],
        capture_output=True, check=False, text=True, timeout=timeout + 10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "Disney+ returned an empty page.")
    return result.stdout


def extract_next_data(page: str) -> dict[str, Any]:
    match = re.search(r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>", page, re.I | re.S)
    if not match:
        return {}
    try:
        value = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def extract_ldjson(metadata_block: dict[str, Any]) -> dict[str, Any]:
    value = metadata_block.get("ldJSON")
    if not isinstance(value, dict):
        return {}
    graph = value.get("@graph")
    if isinstance(graph, list):
        return next((item for item in graph if isinstance(item, dict) and item.get("@type") in {"Movie", "TVSeries"}), {})
    return value


def meta_content(metadata_block: dict[str, Any], key: str) -> str:
    for item in metadata_block.get("metaTags") or []:
        if isinstance(item, dict) and any(clean_text(item.get(attr)).casefold() == key.casefold() for attr in ("property", "name", "itemProp")):
            return clean_text(item.get("content"))
    return ""


def canonical_url(page: str) -> str:
    match = re.search(r"<link\b[^>]*rel=[\"']canonical[\"'][^>]*href=[\"']([^\"']+)", page, re.I)
    return clean_text(match.group(1)) if match else ""


def runtime_minutes_from_ms(value: Any) -> str:
    text = clean_text(value)
    return str(int(text) // 60000) if text.isdigit() and int(text) > 0 else ""


def nested_value(data: Any, path: tuple[Any, ...]) -> Any:
    current = data
    for step in path:
        if isinstance(step, int):
            if not isinstance(current, list) or step >= len(current):
                return None
            current = current[step]
        elif isinstance(current, dict):
            current = current.get(step)
        else:
            return None
    return current


def clean_title(value: Any) -> str:
    return re.sub(r"\s*\|\s*(?:Watch (?:Full Episodes|Now|on Disney\+)|Disney\+).*$", "", clean_text(value), flags=re.I)


def split_values(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        output: list[str] = []
        for item in value:
            output.extend(split_values(item))
        return dedupe_text(output)
    text = clean_text(value)
    return [part.strip() for part in re.split(r"[|;]", text) if part.strip()] if text else []


def first_non_empty(*values: Any) -> str:
    return next((clean_text(value) for value in values if clean_text(value)), "")


def first_value(value: Any) -> str:
    return clean_text(value[0]) if isinstance(value, (list, tuple)) and value else clean_text(value)


def number_text(value: Any) -> str:
    match = re.search(r"\d+", clean_text(value))
    return match.group(0) if match else ""


def add_field(fields: dict[str, list[str]], label: str, value: Any) -> None:
    text = clean_text(value)
    if text and text not in fields.setdefault(label, []):
        fields[label].append(text)


def dedupe_text(values: list[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
        folded = text.casefold()
        if text and folded not in seen:
            output.append(text)
            seen.add(folded)
    return output


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()
