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
        return movie_metadata_from_page(page, normalized)
    if "/shows/video/" in path or "/movies/trailer/video/" in path:
        try:
            return episode_metadata_from_page(page, normalized, timeout=timeout)
        except ValueError:
            return clip_metadata_from_page(page, normalized)
    if "/shows/" not in path:
        raise ValueError("Paramount+ metadata currently supports show, episode, movie, and public clip pages.")
    return show_metadata_from_page(page, normalized, timeout=timeout)


def movie_metadata_from_page(page: str, source_url: str) -> dict[str, Any]:
    data = jsonld_of_type(page, "Movie")
    title = clean_text(data.get("name"))
    description = first_non_empty(
        html_text(text_between(page, r'<div id="movie-description" class="description">', r"</div>")),
        clean_text(data.get("description")),
    )
    movie_id = tracking_value(page, "movieId")
    runtime = first_match(page, r'<span class="duration">\s*([^<]+)')
    hero_image = first_match(page, r'(https://[^"\s,]*w1920[^"\s,]*pplcrn[^"\s,]*)')
    artwork = first_non_empty(hero_image, clean_text(data.get("image")), meta_content(page, "og:image"))
    logo = first_match(page, r'<div class="movieLogo">\s*<img[^>]+src="([^"]+)"')
    brand_logo = first_match(page, r'<div class="brand-logo">.*?<img[^>]+src="([^"]+)"',)
    cast_text = html_text(text_between(page, r'<section class="movie__cast">', r"</section>"))
    cast_text = re.sub(r"^Featuring:\s*", "", cast_text, flags=re.I)
    preview_url = first_match(page, r'data-media-url="([^"]*previewhls[^"]*)"')
    trailer_page = first_match(page, r'href="([^"]*/movies/trailer/video/[^"]+/)"')
    fields: dict[str, list[str]] = {}
    add_field(fields, "Paramount+ movie ID", movie_id)
    add_field(fields, "Trailer page", urllib.parse.urljoin(source_url, trailer_page))
    add_field(fields, "Public preview manifest", preview_url)
    add_field(fields, "Availability", "Subscription movie; the public autoplay preview is handled separately")
    attached_extras = attached_public_extras(movie_id)
    for extra in attached_extras:
        add_field(fields, "Attached related-world extra", extra["title"] + " | " + extra["page"])
    return {
        "source_url": source_url,
        "source_site": NAME,
        "title": title,
        "outline": description,
        "plot": clean_text(data.get("description")) or description,
        "year": iso_date(clean_text(data.get("datePublished")))[:4],
        "runtime_minutes": duration_minutes(runtime),
        "content_rating": clean_text(data.get("contentRating")),
        "poster_url": artwork,
        "fanart_url": artwork,
        "logo_url": logo,
        "trailer_url": preview_url,
        "production_label": "Provider",
        "genres": [clean_text(data.get("genre"))],
        "tags": provider_tags(),
        "studios": ["Paramount Pictures", STUDIO_NAME],
        "actors": [{"name": name, "role": ""} for name in cast_text.split(",") if clean_text(name)],
        "unique_ids": {"paramountplus": movie_id} if movie_id else {},
        "extra_fields": fields,
        "extra_videos": attached_extras,
        "gallery_urls": dedupe([artwork, brand_logo]),
        "folder_name_override": title,
        "warnings": [
            "The feature film is subscription playback. Only its separately exposed, public autoplay preview is downloaded."
        ],
    }


def clip_metadata_from_page(page: str, source_url: str) -> dict[str, Any]:
    data = player_api_metadata(page)
    jsonld = jsonld_of_type(page, "TVClip")
    title = first_non_empty(clean_text(data.get("label")), clean_text(jsonld.get("name")))
    description = first_non_empty(clean_text(data.get("description")), clean_text(jsonld.get("description")))
    image = first_non_empty(clean_text(data.get("thumbnail")), clean_text(jsonld.get("image")), meta_content(page, "og:image"))
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
        "poster_url": image,
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
    portrait = first_match(page, r'(https://[^"\s,]*w2400[^"\s,]*)')
    social = meta_content(page, "og:image")
    preview_url = first_match(page, r'data-media-url="([^"]*previewhls[^"]*)"')
    seasons = all_season_urls(page, source_url)
    if season_count.isdigit():
        for season_number in range(1, int(season_count) + 1):
            seasons.setdefault(season_number, source_url.rstrip("/") + f"/episodes/{season_number}/")
    episode_records = parse_episode_cards(page, source_url)
    for season_number, season_url in seasons.items():
        if season_number == 1:
            continue
        try:
            season_page = fetch_text(season_url, timeout=timeout)
        except Exception:
            continue
        episode_records.extend(parse_episode_cards(season_page, source_url))
    episode_records = dedupe_records(episode_records)
    start_year, end_year, is_current = series_run_years(values.get("Year", ""), episode_records)
    fields: dict[str, list[str]] = {}
    add_field(fields, "Paramount+ show ID", show_id)
    add_field(fields, "Brand", values.get("Brand", ""))
    add_field(fields, "Season count", season_count)
    add_field(fields, "Public preview manifest", preview_url)
    add_field(fields, "Public preview captions", "None advertised by the manifest") if preview_url else None
    for season_number in sorted(seasons):
        add_field(fields, "Available season", f"Season {season_number} | {seasons[season_number]}")
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
        "poster_url": portrait or social,
        "fanart_url": landscape or social,
        "logo_url": logo_url,
        "trailer_url": preview_url,
        "production_label": "Provider",
        "genres": [values.get("Genre", "")],
        "tags": provider_tags(),
        "studios": [values.get("Brand", ""), STUDIO_NAME],
        "unique_ids": {"paramountplus": show_id} if show_id else {},
        "extra_fields": fields,
        "gallery_urls": dedupe([social, portrait, landscape]),
        "folder_name_override": title,
        "warnings": [
            "The public preview manifest advertises no closed-caption track. "
            "Paramount+ subscription episode playback is not downloaded by this tool."
        ],
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
        "series_episodes": [record],
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
                "show_title": clean_text(first_match(article, r'aa-link="Full Episodes\|\|play\|\d+\|([^|]+)')),
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
            "image": clean_text(data.get("image")),
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


def add_field(fields: dict[str, list[str]], label: str, value: str) -> None:
    text = clean_text(value)
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
