#!/usr/bin/env python3
"""Public Paramount+ show, season, and episode metadata helpers."""

from __future__ import annotations

import html
import json
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any


NAME = "Paramount+"
STUDIO_NAME = "Paramount+"
PAGE_HOSTS = {"paramountplus.com", "www.paramountplus.com"}
ATTACHED_PUBLIC_EXTRAS = {
    # User-designated related-world teaser for the Avatar Aang movie page.
    "ALVE01KRF3YJMCEJB92T78193MJ4HP": [
        "https://www.paramountplus.com/shows/video/ALVE01KY3BC68WEY1B97ZF0A0RVRFW/"
    ],
}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
CURRENT_SERIES_WINDOW_DAYS = 45
SERIES_CATALOG_URL = "https://www.paramountplus.com/browse/all/"
MOVIE_CATALOG_URL = "https://www.paramountplus.com/movies/all/"


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in PAGE_HOSTS and (
        parsed.path.startswith("/shows/") or parsed.path.startswith("/movies/")
    )


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    normalized = canonical_url(url)
    page = fetch_text(normalized, timeout=timeout)
    path = urllib.parse.urlparse(normalized).path
    if "/movies/video/" in path:
        return movie_metadata_from_page(page, normalized, timeout=timeout)
    if "/shows/video/" in path or "/movies/trailer/video/" in path:
        try:
            return episode_metadata_from_page(page, normalized, timeout=timeout)
        except ValueError:
            return clip_metadata_from_page(page, normalized)
    if "/shows/" not in path:
        raise ValueError("Paramount+ metadata currently supports show, episode, movie, and public clip pages.")
    return show_metadata_from_page(page, normalized, timeout=timeout)


def movie_metadata_from_page(page: str, source_url: str, timeout: int = 25) -> dict[str, Any]:
    data = jsonld_of_type(page, "Movie")
    title = clean_text(data.get("name"))
    description = first_non_empty(
        html_text(text_between(page, r'<div id="movie-description" class="description">', r"</div>")),
        clean_text(data.get("description")),
    )
    movie_id = tracking_value(page, "movieId")
    runtime = first_match(page, r'<span class="duration">\s*([^<]+)')
    hero_image = first_match(page, r'(https://[^"\s,]*w1920[^"\s,]*pplcrn[^"\s,]*)')
    poster = paramount_catalog_poster(title, movie_id, "movie", timeout=timeout)
    backdrop = first_non_empty(hero_image, meta_content(page, "og:image"))
    if poster and clean_url_key(poster) == clean_url_key(backdrop):
        backdrop = ""
    logo = first_match(page, r'<div class="movieLogo">\s*<img[^>]+src="([^"]+)"')
    cast_text = html_text(text_between(page, r'<section class="movie__cast">', r"</section>"))
    cast_text = re.sub(r"^Featuring:\s*", "", cast_text, flags=re.I)
    preview_url = first_match(page, r'data-media-url="([^"]*previewhls[^"]*)"')
    trailer_page = first_match(page, r'href="([^"]*/movies/trailer/video/[^"]+/)"')
    fields: dict[str, list[str]] = {}
    add_field(fields, "Paramount+ movie ID", movie_id)
    add_field(fields, "Trailer page", urllib.parse.urljoin(source_url, trailer_page))
    add_field(fields, "Public preview manifest", preview_url)
    add_language_fields(fields, page)
    attached_extras = attached_public_extras(movie_id)
    for extra in attached_extras:
        add_field(fields, "Attached related-world extra", extra["title"] + " | " + extra["page"])
    cast_names = dedupe(
        [clean_text(name) for name in cast_text.split(",") if clean_text(name)]
        or person_names(data.get("actor"))
    )
    visible_year = first_match(page, r'class=["\'][^"\']*movie__air-year[^"\']*["\'][^>]*>\s*(\d{4})')
    return {
        "source_url": source_url,
        "source_site": NAME,
        "media_kind": "movie",
        "title": title,
        "outline": description,
        "plot": clean_text(data.get("description")) or description,
        "year": visible_year or iso_date(clean_text(data.get("datePublished")))[:4],
        "runtime_minutes": duration_minutes(runtime),
        "content_rating": clean_text(data.get("contentRating")),
        "poster_url": poster,
        "fanart_url": backdrop,
        "logo_url": logo,
        "trailer_url": preview_url,
        "production_label": "Provider",
        "genres": split_list(data.get("genre")),
        "tags": provider_tags(),
        "studios": [STUDIO_NAME],
        "actors": [{"name": name, "role": ""} for name in cast_names],
        "directors": person_names(data.get("director")),
        "writers": person_names(data.get("creator")),
        "unique_ids": {"paramountplus": movie_id} if movie_id else {},
        "extra_fields": fields,
        "extra_videos": attached_extras,
        "gallery_urls": [],
        "folder_name_override": title,
        "warnings": [],
    }


def clip_metadata_from_page(page: str, source_url: str) -> dict[str, Any]:
    data = player_api_metadata(page)
    jsonld = jsonld_of_type(page, "TVClip")
    title = first_non_empty(clean_text(data.get("label")), clean_text(jsonld.get("name")))
    description = first_non_empty(clean_text(data.get("description")), clean_text(jsonld.get("description")))
    image = first_non_empty(
        image_value(data.get("thumbnail")), image_value(jsonld.get("image")), meta_content(page, "og:image")
    )
    stream_url = clean_text(data.get("streamingUrl"))
    clip_id = first_non_empty(clean_text(data.get("contentId")), clean_text(jsonld.get("@id")))
    fields: dict[str, list[str]] = {}
    add_field(fields, "Paramount+ clip ID", clip_id)
    add_field(fields, "Clip type", clean_text(data.get("mediaType")))
    add_field(fields, "DRM", "None" if data.get("isProtected") is False else "Not confirmed")
    add_field(fields, "Public stream manifest", stream_url)
    add_field(fields, "Closed captions", clean_text(data.get("closedCaptionUrl")) or "None exposed")
    return {
        "source_url": source_url,
        "source_site": NAME,
        "title": title,
        "outline": description,
        "plot": description,
        "year": iso_date(clean_text(data.get("_airDateISO")))[:4],
        "date": iso_date(clean_text(data.get("_airDateISO"))),
        "runtime_minutes": str(round(float(data.get("duration") or 0) / 60)) if data.get("duration") else "",
        "content_rating": clean_text(data.get("rating")),
        "poster_url": "",
        "fanart_url": image,
        "production_label": "Provider",
        "tags": provider_tags(["Public Clip"]),
        "studios": [STUDIO_NAME],
        "unique_ids": {"paramountplus": clip_id} if clip_id else {},
        "extra_fields": fields,
        "extra_videos": [{"title": title, "kind": "Public clip", "description": description, "url": stream_url}] if stream_url else [],
        "folder_name_override": title,
    }


def attached_public_extras(movie_id: str) -> list[dict[str, str]]:
    extras: list[dict[str, str]] = []
    for page_url in ATTACHED_PUBLIC_EXTRAS.get(movie_id, []):
        try:
            item = clip_metadata_from_page(fetch_text(page_url), page_url)
        except Exception:
            continue
        video = next(iter(item.get("extra_videos", [])), {})
        if not isinstance(video, dict) or not clean_text(video.get("url")):
            continue
        extras.append(
            {
                "title": clean_text(video.get("title")),
                "kind": "Attached related-world public teaser",
                "description": clean_text(video.get("description")),
                "url": clean_text(video.get("url")),
                "page": page_url,
            }
        )
    return extras


def _paramount_catalog_poster_from_catalog(
    title: str,
    provider_id: str,
    media_kind: str,
    catalog_url: str,
    wanted_heading: str,
    timeout: int,
) -> str:
    try:
        catalog_page = fetch_text(catalog_url, timeout=timeout)
        raw_config = first_match(catalog_page, r"var\s+collectionConfig\s*=\s*(\[.*?\]);")
        configs = json.loads(raw_config)
    except Exception:
        return ""
    if not isinstance(configs, list):
        return ""
    config = next(
        (
            item
            for item in configs
            if isinstance(item, dict)
            and clean_text(urllib.parse.unquote_plus(item.get("title", ""))).casefold() == wanted_heading
        ),
        {},
    )
    model = clean_text(config.get("model"))
    token = clean_text(config.get("token"))
    if not model or not token:
        return ""
    endpoint = (
        "https://www.paramountplus.com/carousels/collections/configItems/"
        + urllib.parse.quote(model, safe="")
        + "/"
        + urllib.parse.quote(token, safe="")
    )
    target_title = clean_text(title).casefold()
    target_sort_title = re.sub(r"^(?:a|an|the)\s+", "", target_title)
    target_id = clean_text(provider_id)

    def page_at(offset: int) -> tuple[list[dict[str, Any]], int]:
        try:
            raw = fetch_text(f"{endpoint}/offset/{offset}/limit/20/", timeout=timeout)
            payload = json.loads(raw)
            if isinstance(payload, str):
                payload = json.loads(payload)
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            items = result.get("data", []) if isinstance(result, dict) else []
            orientation = clean_text(result.get("orientation")) if isinstance(result, dict) else ""
            records = []
            for item in items:
                if isinstance(item, dict):
                    record = dict(item)
                    record["_catalog_orientation"] = orientation
                    records.append(record)
            return (records, int(result.get("total") or 0))
        except Exception:
            return ([], 0)

    def matching_poster(items: list[dict[str, Any]]) -> str:
        for item in items:
            is_movie = item.get("isMovie") is True
            if is_movie != (media_kind == "movie"):
                continue
            item_ids = {
                clean_text(item.get("id")),
                clean_text(item.get("showSeriesId")),
                clean_text(item.get("content_id")),
                clean_text(item.get("contentId")),
            }
            exact_id = bool(target_id and target_id in item_ids)
            exact_title = clean_text(item.get("alt")).casefold() == target_title
            if (target_id and not exact_id) or (not target_id and not exact_title):
                continue
            orientation = first_non_empty(item.get("orientation"), item.get("_catalog_orientation"))
            if clean_text(orientation).casefold() != "portrait":
                continue
            poster = first_non_empty(item.get("thumb"), item.get("filepathPromoTilePosterImage"))
            if poster:
                return re.sub(r"/w\d+-q\d+/", "/w1400-q90/", poster, count=1)
        return ""

    first_items, total = page_at(0)
    poster = matching_poster(first_items)
    if poster or not first_items:
        return poster
    page_size = len(first_items)
    low = 0
    high = max(0, (total - 1) // page_size)
    visited = {0}
    while low <= high:
        page_number = (low + high) // 2
        if page_number in visited:
            page_number += 1
            if page_number > high or page_number in visited:
                break
        visited.add(page_number)
        items, _ = page_at(page_number * page_size)
        if not items:
            break
        poster = matching_poster(items)
        if poster:
            return poster
        first_title = re.sub(r"^(?:a|an|the)\s+", "", clean_text(items[0].get("alt")).casefold())
        last_title = re.sub(r"^(?:a|an|the)\s+", "", clean_text(items[-1].get("alt")).casefold())
        if target_sort_title < first_title:
            high = page_number - 1
        elif target_sort_title > last_title:
            low = page_number + 1
        else:
            break
    return ""


def paramount_catalog_poster(
    title: str,
    provider_id: str,
    media_kind: str,
    timeout: int = 25,
    brand: str = "",
) -> str:
    """Return Paramount+'s own portrait catalog card, never a detail-page hero."""
    catalog_url = MOVIE_CATALOG_URL if media_kind == "movie" else SERIES_CATALOG_URL
    heading = "all movies a-z" if media_kind == "movie" else "all shows a-z"
    poster = _paramount_catalog_poster_from_catalog(
        title, provider_id, media_kind, catalog_url, heading, timeout
    )
    if poster or media_kind == "movie" or not clean_text(brand):
        return poster
    brand_slug = re.sub(r"[^a-z0-9]+", "-", clean_text(brand).casefold()).strip("-")
    if not brand_slug:
        return ""
    return _paramount_catalog_poster_from_catalog(
        title,
        provider_id,
        media_kind,
        f"https://www.paramountplus.com/brands/{brand_slug}/",
        "a-z",
        timeout,
    )


def show_metadata_from_page(page: str, source_url: str, timeout: int) -> dict[str, Any]:
    title = first_non_empty(
        text_between(page, r'<div class="about__header-title">', r"</div>"),
        meta_content(page, "og:title").replace(" - Nickelodeon - Watch on Paramount Plus", ""),
    )
    description = first_non_empty(
        meta_content(page, "description"),
        text_between(page, r'<div class="about__header-description">', r"</div>"),
    )
    values = about_metadata(page)
    season_count = number_text(values.get("Seasons", ""))
    show_id = tracking_value(page, "showSeriesId")
    logo_url = first_match(page, r'<img[^>]+alt="' + re.escape(title) + r'"[^>]+src="([^"]+)"')
    landscape = first_match(page, r'(https://[^"\s,]*w3200[^"\s,]*)') or first_match(
        page, r'<img src="([^"]+lok_[^"]*hero_landscape[^"]*)"'
    )
    social = meta_content(page, "og:image")
    poster = paramount_catalog_poster(title, show_id, "series", timeout=timeout, brand=values.get("Brand", ""))
    preview_url = first_match(page, r'data-media-url="([^"]*previewhls[^"]*)"')
    seasons = all_season_urls(page, source_url)
    if season_count.isdigit():
        for season_number in range(1, int(season_count) + 1):
            explicit_url = source_url.rstrip("/") + f"/episodes/{season_number}/"
            discovered = seasons.get(season_number, "")
            if not discovered or urllib.parse.urlparse(discovered).path.rstrip("/") == urllib.parse.urlparse(source_url).path.rstrip("/"):
                seasons[season_number] = explicit_url
    episode_records = parse_episode_cards(page, source_url)
    for season_number, season_url in seasons.items():
        try:
            season_page = fetch_text(season_url, timeout=timeout)
        except Exception as exc:
            raise RuntimeError(
                f"Paramount+ Season {season_number} could not be loaded; refusing a partial Queue Mode catalog."
            ) from exc
        episode_records.extend(parse_episode_cards(season_page, source_url))
    episode_records = dedupe_records(episode_records)
    start_year, end_year, is_current = series_run_years(values.get("Year", ""), episode_records)
    fields: dict[str, list[str]] = {}
    add_field(fields, "Paramount+ show ID", show_id)
    add_field(fields, "Brand", values.get("Brand", ""))
    add_field(fields, "Season count", season_count)
    add_field(fields, "Episode count", str(len(episode_records)))
    add_field(fields, "Public preview manifest", preview_url)
    add_language_fields(fields, page)
    for season_number in sorted(seasons):
        add_field(fields, "Available season", f"Season {season_number} | {seasons[season_number]}")
        add_field(
            fields,
            f"Season {season_number} episode count",
            str(sum(1 for record in episode_records if record.get("season") == season_number)),
        )
    for record in episode_records:
        add_field(
            fields,
            "Episode guide",
            " | ".join(
                part
                for part in (
                    f"S{record['season']:02d}E{record['episode']:02d}",
                    record["title"],
                    record["duration"],
                    record["date"],
                    record["id"],
                )
                if part
            ),
        )
    return {
        "source_url": source_url,
        "source_site": NAME,
        "media_kind": "series",
        "title": title,
        "show_title": title,
        "outline": description,
        "plot": description,
        "year": start_year,
        "series_start_year": start_year,
        "series_end_year": end_year,
        "series_is_current": is_current,
        "content_rating": values.get("Rating", ""),
        "poster_url": poster,
        "fanart_url": landscape or social,
        "logo_url": logo_url,
        "trailer_url": preview_url,
        "production_label": "Provider",
        "genres": split_list(values.get("Genre", "")),
        "tags": provider_tags(),
        "studios": [values.get("Brand", ""), STUDIO_NAME],
        "unique_ids": {"paramountplus": show_id} if show_id else {},
        "extra_fields": fields,
        "gallery_urls": [],
        "folder_name_override": title,
        "warnings": [],
        "series_episodes": episode_records,
    }


def episode_metadata_from_page(page: str, source_url: str, timeout: int = 25) -> dict[str, Any]:
    episode_id = first_match(urllib.parse.urlparse(source_url).path, r"/shows/video/([^/]+)/")
    record = jsonld_episode(page, source_url)
    if not record:
        cards = parse_episode_cards(page, source_url)
        record = next((item for item in cards if clean_text(item.get("id")) == episode_id), {})
        record = record or next(iter(cards), {})
    title_text = clean_text(re.sub(r"\s*\|\s*Paramount\+.*$", "", meta_content(page, "og:title")))
    show_title, season_number = split_episode_heading(title_text)
    if not record:
        raise ValueError("Paramount+ episode page did not expose episode metadata.")
    if episode_id:
        record["id"] = episode_id
    show_url = series_url_from_episode_page(page, source_url)
    series_metadata: dict[str, Any] = {}
    if show_url:
        try:
            series_metadata = show_metadata_from_page(fetch_text(show_url, timeout=timeout), show_url, timeout=timeout)
        except Exception:
            series_metadata = {}
    resolved_show_title = first_non_empty(
        clean_text(series_metadata.get("title")),
        show_title,
        clean_text(record.get("show_title")),
        clean_text(jsonld_of_type(page, "TVEpisode").get("partOfSeries", {}).get("name")),
    )
    series_fields = series_metadata.get("extra_fields", {}) if isinstance(series_metadata.get("extra_fields"), dict) else {}
    fields: dict[str, list[str]] = {}
    add_field(fields, "Paramount+ episode ID", record.get("id", ""))
    add_field(fields, "Episode page", record.get("url", source_url))
    add_field(fields, "Paramount+ show ID", first_value(series_fields.get("Paramount+ show ID")))
    add_field(fields, "Brand", first_value(series_fields.get("Brand")))
    add_field(fields, "Season count", first_value(series_fields.get("Season count")))
    audio = page_language_values(page, "audio") or list(series_fields.get("Audio", []))
    subtitles = page_language_values(page, "subtitles") or list(series_fields.get("Subtitles", []))
    add_field(fields, "Audio", audio)
    add_field(fields, "Subtitles", subtitles)
    full_guide = dedupe_records([
        *(
            series_metadata.get("series_episodes", [])
            if isinstance(series_metadata.get("series_episodes"), list)
            else []
        ),
        record,
    ])
    return {
        "source_url": source_url,
        "source_site": NAME,
        "media_kind": "episode",
        "title": resolved_show_title,
        "show_title": resolved_show_title,
        "season_number": str(record.get("season", season_number or "")),
        "episode_number": str(record.get("episode", "")),
        "episode_title": record.get("title", ""),
        "outline": record.get("description", ""),
        "plot": record.get("description", ""),
        "year": iso_date(record.get("date", ""))[:4],
        "series_start_year": clean_text(series_metadata.get("series_start_year")),
        "series_end_year": clean_text(series_metadata.get("series_end_year")),
        "series_is_current": bool(series_metadata.get("series_is_current")),
        "date": record.get("date", ""),
        "runtime_minutes": duration_minutes(record.get("duration", "")),
        "content_rating": clean_text(series_metadata.get("content_rating")),
        "poster_url": clean_text(series_metadata.get("poster_url")),
        "fanart_url": clean_text(series_metadata.get("fanart_url")),
        "logo_url": clean_text(series_metadata.get("logo_url")),
        "trailer_url": clean_text(series_metadata.get("trailer_url")),
        "thumb_url": record.get("image", ""),
        "production_label": "Provider",
        "genres": list(series_metadata.get("genres", [])),
        "tags": provider_tags(),
        "studios": list(series_metadata.get("studios", [])) or [STUDIO_NAME],
        "unique_ids": {"paramountplus": record.get("id", "")} if record.get("id") else {},
        "extra_fields": fields,
        "series_episodes": full_guide,
        "series_metadata": series_metadata,
        "folder_name_override": resolved_show_title,
    }


def parse_episode_cards(page: str, show_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for article_match in re.finditer(
        r'(<article[^>]*class=["\'][^"\']*\bgrid-view-item\b[^"\']*["\'][^>]*>)(.*?)</article>',
        page,
        re.S | re.I,
    ):
        article = article_match.group(1) + article_match.group(2)
        link = first_match(article, r'href="([^"]*/shows/video/[^"]+/)"')
        tracking = first_match(article, r'data-tracking="([^"]+)"')
        match = re.search(r"\|S(\d+)\|Ep(\d+)\|([^|]*)\|([^|]*)\|\|", html.unescape(tracking))
        if not (link and match):
            continue
        heading = html_text(text_between(article, r'<div class="meta-wrapper title-shorten">', r"</div>"))
        heading = re.sub(r"\bS\d+\s*E\d+\b", "", heading).strip()
        description = html_text(text_between(article, r'<div class="description-wrapper[^>]*>', r"</div>"))
        duration = first_match(article, r'itemprop="duration"\s+content="([^"]+)"')
        date = first_match(article, r'<time datetime="([^"]+)"')
        image = first_match(article, r'(?:data-src|src)="([^"]+thumbnails\.cbsig\.net[^"]+)"')
        records.append(
            {
                "id": first_match(article, r'vilynx-id="([^"]+)"'),
                "url": urllib.parse.urljoin(show_url, html.unescape(link)),
                "show_title": clean_text(first_match(article, r'aa-link="Full Episodes\|\|play\|\d+\|([^|"]+)')),
                "season": int(match.group(1)),
                "episode": int(match.group(2)),
                "title": heading or match.group(4).strip(),
                "description": description,
                "duration": duration,
                "date": iso_date(date),
                "image": high_res_episode_image(image),
            }
        )
    if records:
        return records
    show_title = re.sub(r"\s+Season\s+\d+\s+Episodes.*$", "", meta_content(page, "og:title"), flags=re.I)
    for block in re.split(r'<div class="episode">', page, flags=re.S)[1:]:
        link = first_match(block, r'href="([^"]*/shows/video/[^"]+/)"')
        season = first_match(block, r'<abbr class="seNum"[^>]*>S(\d+)</abbr>')
        episode = first_match(block, r"<abbr class=['\"]epNum['\"][^>]*>E(\d+)</abbr>")
        if not (link and season and episode):
            continue
        records.append(
            {
                "id": first_match(link, r"/video/([^/]+)/"),
                "url": urllib.parse.urljoin(show_url, html.unescape(link)),
                "show_title": clean_text(show_title),
                "season": int(season),
                "episode": int(episode),
                "title": html_text(text_between(block, r"<div class=\"epTitle\">", r"</div>")),
                "description": html_text(text_between(block, r'<div class="ep__copy[^>]*>', r"</div>")),
                "duration": "",
                "date": iso_date(first_match(block, r'<time[^>]+datetime="([^"]+)"')),
                "image": high_res_episode_image(first_match(block, r'<img src="([^"]+thumbnails\.cbsig\.net[^"]+)"')),
            }
        )
    return records


def all_season_urls(page: str, show_url: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for path, number in re.findall(r'href="([^"]*/episodes/(\d+)/?)"', page, re.S):
        found[int(number)] = urllib.parse.urljoin(show_url, html.unescape(path))
    return found or {1: show_url}


def jsonld_episode(page: str, source_url: str) -> dict[str, Any]:
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "TVEpisode":
            continue
        return {
            "id": first_non_empty(
                first_match(clean_text(data.get("url")), r"/video/([^/]+)/"),
                first_match(urllib.parse.urlparse(source_url).path, r"/shows/video/([^/]+)/"),
            ),
            "url": source_url,
            "show_title": clean_text(data.get("partOfSeries", {}).get("name")),
            "season": int(data.get("partOfSeason", {}).get("seasonNumber") or 0),
            "episode": int(data.get("episodeNumber") or 0),
            "title": clean_text(data.get("name")),
            "description": clean_text(data.get("description")),
            "duration": clean_text(data.get("duration")),
            "date": iso_date(clean_text(data.get("datePublished"))),
            "image": image_value(data.get("image")),
        }
    return {}


def series_url_from_episode_page(page: str, source_url: str) -> str:
    """Resolve a stable parent-show page from a Paramount+ playing page."""
    candidates = [
        first_match(page, r'player\.baseUrl\s*=\s*["\']([^"\']+)["\']'),
        first_match(page, r'<a[^>]+href=["\'](/shows/[^/"\']+/)["\'][^>]*aa-link=["\']show header'),
    ]
    show_key = first_match(page, r'CBS\.Registry\.Show\s*=\s*\{.*?["\']key["\']\s*:\s*["\']([^"\']+)')
    if show_key:
        candidates.append(f"/shows/{show_key}/")
    for value in candidates:
        if not value:
            continue
        url = urllib.parse.urljoin(source_url, html.unescape(value))
        path = urllib.parse.urlparse(url).path
        match = re.match(r"^/shows/([^/]+)/", path, re.IGNORECASE)
        if match and match.group(1).casefold() != "video":
            return urllib.parse.urljoin(source_url, f"/shows/{match.group(1)}/")
    return ""


def series_run_years(
    launch_year: Any,
    episodes: list[dict[str, Any]],
    current_date: date | None = None,
) -> tuple[str, str, bool]:
    start = clean_text(launch_year)
    dates: list[date] = []
    for episode in episodes:
        value = clean_text(episode.get("date"))
        try:
            dates.append(date.fromisoformat(value))
        except ValueError:
            continue
    if not start and dates:
        start = str(min(dates).year)
    if not start.isdigit():
        return "", "", False
    latest = max(dates, default=None)
    end = str(latest.year) if latest else start
    today = current_date or date.today()
    current = bool(latest and latest >= today - timedelta(days=CURRENT_SERIES_WINDOW_DAYS))
    return start, end, current


def provider_tags(additional: list[str] | None = None) -> list[str]:
    return dedupe([NAME, f"Provider: {NAME}", "Paramount+ Provider", *(additional or [])])


def add_language_fields(fields: dict[str, list[str]], page: str) -> None:
    add_field(fields, "Audio", page_language_values(page, "audio"))
    add_field(fields, "Subtitles", page_language_values(page, "subtitles"))


def page_language_values(page: str, kind: str) -> list[str]:
    keys = (
        ("audioLanguages", "audioLanguage", "availableAudioLanguages")
        if kind == "audio"
        else ("subtitleLanguages", "subtitleLanguage", "availableSubtitleLanguages")
    )
    values: list[str] = []
    for key in keys:
        for raw in re.findall(r'"' + re.escape(key) + r'"\s*:\s*(\[[^\]]*\]|"(?:\\.|[^"])*")', page, re.I):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            values.extend(language_names(parsed))
    label = "Audio Languages" if kind == "audio" else "Subtitle Languages"
    for raw in re.findall(
        r'<[^>]+>\s*' + re.escape(label) + r'\s*</[^>]+>\s*<[^>]+>(.*?)</[^>]+>',
        page,
        re.I | re.S,
    ):
        values.extend(re.split(r"\s*[,;]\s*", html_text(raw)))
    return dedupe(values)


def language_names(value: Any) -> list[str]:
    if isinstance(value, list):
        return dedupe([name for item in value for name in language_names(item)])
    if isinstance(value, dict):
        for key in ("displayName", "localizedName", "label", "name", "languageName"):
            if clean_text(value.get(key)):
                return [clean_text(value[key])]
        return []
    if isinstance(value, bool) or value is None:
        return []
    return [clean_text(value)] if clean_text(value) else []


def person_names(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in values:
        if isinstance(item, dict):
            names.append(clean_text(item.get("name")))
        else:
            names.append(clean_text(item))
    return dedupe(names)


def split_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return dedupe([item for entry in value for item in split_list(entry)])
    return dedupe(re.split(r"\s*[;,]\s*", clean_text(value)))


def image_value(value: Any) -> str:
    if isinstance(value, list):
        return next((image_value(item) for item in value if image_value(item)), "")
    if isinstance(value, dict):
        return first_non_empty(
            clean_text(value.get("url")), clean_text(value.get("contentUrl")), clean_text(value.get("@id"))
        )
    return clean_text(value)


def clean_url_key(value: str) -> str:
    parsed = urllib.parse.urlsplit(clean_text(value))
    return urllib.parse.urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, parsed.query, ""))


def jsonld_of_type(page: str, wanted_type: str) -> dict[str, Any]:
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == wanted_type:
            return data
    return {}


def player_api_metadata(page: str) -> dict[str, Any]:
    raw = first_match(page, r'player\.apiMetadata\s*=\s*(\{.*?\});')
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def fetch_text(url: str, timeout: int = 25) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read(80 * 1024 * 1024).decode("utf-8", errors="replace")
            if text.strip():
                return text
    except Exception:
        pass
    result = subprocess.run(
        ["/usr/bin/curl", "--http1.1", "--location", "--fail", "--silent", "--show-error", "--compressed", "--max-time", str(timeout), "--user-agent", USER_AGENT, "--header", headers["Accept"], "--header", headers["Accept-Language"], url],
        capture_output=True, check=False, text=True, timeout=timeout + 10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "Paramount+ returned an empty page.")
    return result.stdout


def canonical_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(clean_text(url))
    return urllib.parse.urlunsplit((parsed.scheme or "https", parsed.netloc, parsed.path.rstrip("/") + "/", "", ""))


def about_metadata(page: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for label in ("Genre", "Year", "Seasons", "Rating", "Brand"):
        value = first_match(
            page,
            r'<span class="about__metadata-title">' + re.escape(label) + r'</span>\s*(?:<span[^>]*>|<a[^>]*>)\s*([^<]+)',
        )
        if label and value:
            found[label] = value
    return found


def tracking_value(page: str, key: str) -> str:
    return first_match(page, re.escape(key) + r'":\s*"?([^,}\"]+)')


def split_episode_heading(value: str) -> tuple[str, int]:
    match = re.match(r"(.+?)\s*[•|]\s*Season\s+(\d+)", value)
    return (clean_text(match.group(1)), int(match.group(2))) if match else ("", 0)


def duration_minutes(value: str) -> str:
    text = clean_text(value)
    short = re.fullmatch(r"(?:(\d+)H\s*)?(?:(\d+)M)?", text, re.I)
    if short and (short.group(1) or short.group(2)):
        return str(int(short.group(1) or 0) * 60 + int(short.group(2) or 0))
    iso = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text, re.I)
    if iso:
        return str(round(int(iso.group(1) or 0) * 60 + int(iso.group(2) or 0) + int(iso.group(3) or 0) / 60))
    return ""


def high_res_episode_image(url: str) -> str:
    return re.sub(r"/_x/w\d+/", "/_x/w1920/", clean_text(url), count=1)


def iso_date(value: str) -> str:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", clean_text(value))
    return match.group(1) if match else ""


def number_text(value: str) -> str:
    match = re.search(r"\d+", clean_text(value))
    return match.group(0) if match else ""


def meta_content(page: str, name: str) -> str:
    return html.unescape(first_match(page, r'<meta[^>]+(?:name|property)="' + re.escape(name) + r'"[^>]+content="([^"]*)"'))


def text_between(text: str, start: str, end: str) -> str:
    match = re.search(start + r"(.*?)" + end, text, re.S | re.I)
    return match.group(1) if match else ""


def html_text(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", html.unescape(value)))


def first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.S | re.I)
    return html.unescape(match.group(1).strip()) if match else ""


def first_non_empty(*values: str) -> str:
    return next((clean_text(value) for value in values if clean_text(value)), "")


def first_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return clean_text(value[0]) if value else ""
    return clean_text(value)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def add_field(fields: dict[str, list[str]], label: str, value: Any) -> None:
    values = value if isinstance(value, (list, tuple)) else [value]
    for item in values:
        text = clean_text(item)
        if text and text not in fields.setdefault(label, []):
            fields[label].append(text)


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def dedupe_records(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = {str(value.get("id") or value.get("url")): value for value in values}
    return sorted(records.values(), key=lambda value: (value.get("season", 0), value.get("episode", 0)))
