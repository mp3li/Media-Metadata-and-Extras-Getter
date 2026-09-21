#!/usr/bin/env python3
from __future__ import annotations

import ast
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
    return (
        parsed.netloc.casefold() in PAGE_HOSTS
        and re.search(r"/(?:title|watch)/\d+", parsed.path, flags=re.IGNORECASE) is not None
    )


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    html_text = fetch_text(url, timeout=timeout)
    visible_lines = extract_visible_lines(html_text)
    video_object = extract_video_object(html_text)
    state = extract_next_data(html_text)
    graph = extract_graphql_data(html_text)
    requested_id = match_group(r"/(?:title|watch)/(\d+)", url)
    main_record = netflix_main_record(graph)
    graph_type = clean_text(main_record.get("__typename")).casefold()
    graph_id = clean_text(main_record.get("videoId"))
    title = first_non_empty(
        clean_text(main_record.get("title")),
        clean_text(video_object.get("name")),
        nested_text(state, "props", "pageProps", "metadata", "title"),
        clean_title(meta_value(html_text, "og:title")),
        title_from_lines(visible_lines),
    )
    plot = first_non_empty(
        clean_text(main_record.get("shortSynopsis")),
        clean_text(video_object.get("description")),
        nested_text(state, "props", "pageProps", "metadata", "synopsis"),
        meta_value(html_text, "og:description"),
    )
    year = first_non_empty(
        year_from_text(clean_text(main_record.get("availabilityStartTime"))),
        year_from_text(clean_text(video_object.get("startDate"))),
        year_from_text(clean_text(video_object.get("datePublished"))),
        year_from_text(clean_text(video_object.get("dateCreated"))),
        nested_text(state, "props", "pageProps", "metadata", "year"),
        parse_year(visible_lines),
    )
    rating = first_non_empty(
        nested_text(main_record, "contentAdvisory", "certificationValue"),
        clean_text(video_object.get("contentRating")),
        nested_text(state, "props", "pageProps", "metadata", "maturity", "rating", "value"),
        parse_rating(visible_lines),
    )
    runtime = first_non_empty(
        duration_minutes(clean_text(video_object.get("duration"))),
        parse_summary_runtime(visible_lines),
    )
    genres = dedupe(
        netflix_linked_names(main_record, graph, ("coreGenres", "primaryGenres", "genres"))
        or split_value(video_object.get("genre"))
        or split_csv(nested_text(state, "props", "pageProps", "metadata", "genres"))
        or parse_visible_block(visible_lines, "Genres")
        or parse_summary_genres(visible_lines)
    )
    tags = dedupe([
        *netflix_linked_names(main_record, graph, ("tags",)),
        *parse_visible_block(visible_lines, "This show is ..."),
    ])
    cast = dedupe(
        netflix_person_names(main_record, graph, "ACTOR")
        or people_names(video_object.get("actor"))
        or parse_visible_block(visible_lines, "Cast")
    )
    if not cast:
        cast = dedupe(parse_starring_fallback(visible_lines))
    poster = first_non_empty(
        netflix_artwork(main_record, "BOXSHOT"),
        nested_text(state, "props", "pageProps", "metadata", "boxArt", "url"),
    )
    fanart = first_non_empty(
        netflix_artwork(main_record, "BILLBOARD"),
        nested_text(state, "props", "pageProps", "metadata", "storyArt", "url"),
        nested_text(state, "props", "pageProps", "metadata", "bg", "url"),
        meta_value(html_text, "og:image"),
    )
    logo = first_non_empty(
        netflix_artwork(main_record, "LOGO_HORIZONTAL_CROPPED"),
        netflix_artwork(main_record, "BRAND_LOGO_CROPPED"),
    )
    supplemental = netflix_supplemental_videos(main_record, graph)
    trailer_item = next((item for item in supplemental if item["kind"] == "TRAILER"), None)
    trailer = first_non_empty(
        clean_text(trailer_item.get("url")) if trailer_item else "",
        clean_text((video_object.get("trailer") or {}).get("contentUrl"))
        if isinstance(video_object.get("trailer"), dict) else "",
        nested_text(state, "props", "pageProps", "metadata", "trailer", "url"),
        parse_direct_video_url(html_text),
    )
    source_url = first_non_empty(meta_value(html_text, "og:url"), url)
    parent_id = graph_id or match_group(r"/title/(\d+)", source_url)
    object_type = clean_text(video_object.get("@type")).casefold()
    media_kind = (
        "movie" if graph_type == "movie" or object_type == "movie"
        else "series" if graph_type == "show" or object_type == "tvseries"
        else ""
    )
    graph_episodes, catalog_complete = netflix_graph_episode_records(main_record, graph, title)
    episodes = graph_episodes or netflix_episode_records([video_object, state], title)
    if episodes and not graph_episodes:
        catalog_complete = True
    start_year, end_year, is_current = netflix_series_years(main_record, video_object, episodes, year)
    extra_fields: dict[str, list[str]] = {}
    if cast:
        extra_fields["Starring"] = cast
    audio_languages, subtitle_languages = netflix_media_tracks(main_record)
    if audio_languages:
        extra_fields["Audio"] = audio_languages
    if subtitle_languages:
        extra_fields["Subtitles"] = subtitle_languages
    if media_kind == "series":
        season_count = netflix_season_count(main_record)
        if season_count:
            extra_fields["Seasons"] = [str(season_count)]
        extra_fields["Netflix catalog status"] = ["Complete" if catalog_complete else "Partial"]
    provider_tags = [NAME, f"Provider: {NAME}", "Netflix Provider"]
    directors = dedupe(
        netflix_person_names(main_record, graph, "DIRECTOR")
        or people_names(video_object.get("director"))
    )
    creators = dedupe(
        netflix_person_names(main_record, graph, "CREATOR")
        or people_names(video_object.get("creator"))
    )
    extras = [item for item in supplemental if clean_text(item.get("url")) != trailer]
    series_item = {
        "source_url": source_url,
        "source_site": NAME,
        "media_kind": media_kind,
        "title": title,
        "outline": plot,
        "plot": plot,
        "year": year,
        "runtime_minutes": runtime,
        "content_rating": rating,
        "poster_url": poster,
        "fanart_url": fanart,
        "logo_url": logo,
        "trailer_url": trailer,
        "production_label": "Provider",
        "genres": genres,
        "tags": dedupe([*provider_tags, *tags]),
        "studios": [NAME],
        "actors": [{"name": name, "role": ""} for name in cast],
        "directors": directors,
        "writers": creators,
        "credits": creators,
        "unique_ids": {"netflix": parent_id or requested_id} if (parent_id or requested_id) else {},
        "extra_fields": extra_fields,
        "extra_videos": extras,
        "folder_name_override": title,
        "series_episodes": episodes,
        "series_start_year": start_year if media_kind == "series" else "",
        "series_end_year": end_year if media_kind == "series" else "",
        "series_is_current": is_current if media_kind == "series" else False,
    }
    requested_episode = next(
        (record for record in episodes if clean_text(record.get("id")) == requested_id), None
    )
    if media_kind == "series" and requested_id and parent_id and requested_id != parent_id:
        if not requested_episode:
            raise RuntimeError(
                "Netflix resolved this link to a series, but its public page did not expose "
                "the requested episode ID and placement. The completed media was left untouched."
            )
        return netflix_episode_item(series_item, requested_episode, url)
    return series_item


def extract_graphql_data(html_text: str) -> dict[str, Any]:
    match = re.search(
        r"netflix\.reactContext\.models\.graphql\s*=\s*JSON\.parse\('(.*?)'\);",
        html_text,
        flags=re.DOTALL,
    )
    if not match:
        return {}
    try:
        decoded = ast.literal_eval("'" + match.group(1) + "'")
        payload = json.loads(decoded)
    except (SyntaxError, ValueError, json.JSONDecodeError):
        return {}
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def netflix_main_record(graph: dict[str, Any]) -> dict[str, Any]:
    root = graph.get("ROOT_QUERY", {})
    videos = root.get("videos", {}) if isinstance(root, dict) else {}
    if isinstance(videos, dict):
        for reference in videos.values():
            record = netflix_resolve_ref(reference, graph)
            if record:
                return record
    return {}


def netflix_resolve_ref(value: Any, graph: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    reference = clean_text(value.get("__ref"))
    if reference:
        resolved = graph.get(reference)
        return resolved if isinstance(resolved, dict) else {}
    return value


def netflix_connection(record: dict[str, Any], name: str) -> dict[str, Any]:
    for key, value in record.items():
        if (key == name or key.startswith(name + ":") or key.startswith(name + "(")) and isinstance(value, dict):
            return value
    return {}


def netflix_connection_records(record: dict[str, Any], graph: dict[str, Any], name: str) -> list[dict[str, Any]]:
    connection = netflix_connection(record, name)
    output: list[dict[str, Any]] = []
    for edge in connection.get("edges", []) if isinstance(connection.get("edges"), list) else []:
        if not isinstance(edge, dict):
            continue
        child = netflix_resolve_ref(edge.get("node"), graph)
        if child:
            output.append(child)
    return output


def netflix_artwork(record: dict[str, Any], artwork_type: str) -> str:
    token = f'"artworkType":"{artwork_type}"'
    for key, value in record.items():
        if key.startswith("artwork(") and token in key and isinstance(value, dict):
            if value.get("available") is False:
                continue
            url = clean_text(value.get("url"))
            if url:
                return url
    return ""


def netflix_linked_names(
    record: dict[str, Any], graph: dict[str, Any], connection_names: tuple[str, ...]
) -> list[str]:
    output: list[str] = []
    for name in connection_names:
        for item in netflix_connection_records(record, graph, name):
            output.append(clean_text(item.get("name") or item.get("title") or item.get("displayName")))
        direct = record.get(name)
        if isinstance(direct, list):
            for item in direct:
                resolved = netflix_resolve_ref(item, graph)
                output.append(clean_text(resolved.get("name") or resolved.get("title") or resolved.get("displayName")))
    return dedupe(output)


def netflix_person_names(record: dict[str, Any], graph: dict[str, Any], role: str) -> list[str]:
    return [
        clean_text(item.get("name"))
        for item in netflix_connection_records(record, graph, f'persons:{{"roles":"{role}"}}')
        if clean_text(item.get("name"))
    ]


def netflix_graph_episode_records(
    show: dict[str, Any], graph: dict[str, Any], show_title: str
) -> tuple[list[dict[str, Any]], bool]:
    if clean_text(show.get("__typename")).casefold() != "show":
        return [], False
    seasons_connection = netflix_connection(show, "seasons")
    seasons = netflix_connection_records(show, graph, "seasons")
    complete = bool(seasons)
    page_info = seasons_connection.get("pageInfo", {})
    if isinstance(page_info, dict) and page_info.get("hasNextPage") is True:
        complete = False
    total = seasons_connection.get("totalCount")
    if isinstance(total, int) and total > len(seasons):
        complete = False
    output: list[dict[str, Any]] = []
    for fallback_season, season in enumerate(seasons, start=1):
        label = first_non_empty(
            clean_text(season.get('numberLabelV2({"label":"LONG"})')),
            clean_text(season.get("shortTitle")),
            clean_text(season.get("title")),
        )
        season_number_text = match_group(r"(\d+)", label)
        season_number = int(season_number_text) if season_number_text.isdigit() else fallback_season
        episodes_connection = netflix_connection(season, "episodes")
        episodes = netflix_connection_records(season, graph, "episodes")
        episode_page_info = episodes_connection.get("pageInfo", {})
        if isinstance(episode_page_info, dict) and episode_page_info.get("hasNextPage") is True:
            complete = False
        episode_total = episodes_connection.get("totalCount")
        if isinstance(episode_total, int) and episode_total > 0 and episode_total > len(episodes):
            complete = False
        for fallback_episode, episode in enumerate(episodes, start=1):
            identifier = clean_text(episode.get("videoId"))
            number = clean_text(episode.get("number"))
            if not identifier.isdigit() or not number.isdigit():
                complete = False
                continue
            output.append({
                "id": identifier,
                "url": f"https://www.netflix.com/title/{identifier}",
                "show_title": show_title,
                "season": season_number,
                "episode": int(number or fallback_episode),
                "title": clean_text(episode.get("title")),
                "description": clean_text(episode.get("shortSynopsis")),
                "duration": runtime_minutes_from_seconds(episode.get("runtimeSec")),
                "date": clean_text(episode.get("availabilityStartTime"))[:10],
                "image": netflix_artwork(episode, "MERCH_STILL"),
            })
    return sorted(output, key=lambda item: (item["season"], item["episode"], item["id"])), complete


def netflix_media_tracks(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    tracks = record.get("mediaTracks", {})
    if not isinstance(tracks, dict):
        return [], []
    audio = [clean_text(item.get("language")) for item in tracks.get("audioTracks", []) if isinstance(item, dict)]
    subtitles = [clean_text(item.get("language")) for item in tracks.get("subtitles", []) if isinstance(item, dict)]
    return dedupe(audio), dedupe(subtitles)


def netflix_supplemental_videos(record: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in netflix_connection_records(record, graph, 'supplementalVideosList'):
        url = ""
        for key, value in item.items():
            if key.startswith("playableVideo(") and isinstance(value, dict):
                url = clean_text(value.get("url"))
                if url:
                    break
        if not url or url in seen:
            continue
        seen.add(url)
        output.append({
            "title": clean_text(item.get("title")),
            "kind": clean_text(item.get("type")),
            "description": clean_text(item.get("shortSynopsis")),
            "url": url,
        })
    for key, value in record.items():
        if not key.startswith("promoVideo("):
            continue
        promo = netflix_resolve_ref(value, graph)
        item = netflix_resolve_ref(promo.get("video"), graph)
        url = ""
        for playable_key, playable in item.items():
            if playable_key.startswith("playableVideo(") and isinstance(playable, dict):
                url = clean_text(playable.get("url"))
                if url:
                    break
        if url and url not in seen:
            seen.add(url)
            output.append({
                "title": clean_text(item.get("title")),
                "kind": "PROMO",
                "description": clean_text(item.get("shortSynopsis")),
                "url": url,
            })
    return output


def netflix_season_count(record: dict[str, Any]) -> int:
    connection = netflix_connection(record, "seasons")
    total = connection.get("totalCount")
    if isinstance(total, int) and total > 0:
        return total
    return len(connection.get("edges", [])) if isinstance(connection.get("edges"), list) else 0


def netflix_series_years(
    record: dict[str, Any], video_object: dict[str, Any], episodes: list[dict[str, Any]], fallback: str
) -> tuple[str, str, bool]:
    dates = [
        clean_text(video_object.get("startDate")),
        clean_text(video_object.get("dateCreated")),
        clean_text(record.get("availabilityStartTime")),
        *[clean_text(item.get("date")) for item in episodes],
    ]
    years = [year_from_text(value) for value in dates if year_from_text(value)]
    start = min(years) if years else fallback
    explicit_end = year_from_text(clean_text(video_object.get("endDate")))
    latest = clean_text(record.get("latestYear"))
    end = explicit_end or (latest if latest.isdigit() else (max(years) if years else start))
    tagline_values = [clean_text(value.get("tagline")) for key, values in record.items()
                      if key.startswith("taglineMessages(") and isinstance(values, list)
                      for value in values if isinstance(value, dict)]
    current = any(re.search(r"another season is coming|new season|returning", value, re.I) for value in tagline_values)
    return start, end, current


def netflix_episode_item(series_item: dict[str, Any], record: dict[str, Any], requested_url: str) -> dict[str, Any]:
    item = dict(series_item)
    identifier = clean_text(record.get("id"))
    item.update({
        "source_url": requested_url,
        "media_kind": "episode",
        "show_title": clean_text(series_item.get("title")),
        "season_number": clean_text(record.get("season")),
        "episode_number": clean_text(record.get("episode")),
        "episode_title": clean_text(record.get("title")),
        "outline": clean_text(record.get("description")),
        "plot": clean_text(record.get("description")),
        "date": clean_text(record.get("date")),
        "year": clean_text(record.get("date"))[:4],
        "runtime_minutes": clean_text(record.get("duration")),
        "thumb_url": clean_text(record.get("image")),
        "unique_ids": {"netflix": identifier} if identifier else {},
        "series_metadata": series_item,
    })
    return item


def netflix_episode_records(values: list[Any], show_title: str) -> list[dict[str, Any]]:
    """Collect only public records with a provable Netflix ID and season/episode placement."""
    records: dict[tuple[int, int, str], dict[str, Any]] = {}

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        episode_number = clean_text(value.get("episodeNumber") or value.get("episode"))
        season_value = value.get("seasonNumber") or value.get("season")
        if isinstance(value.get("partOfSeason"), dict):
            season_value = value["partOfSeason"].get("seasonNumber") or season_value
        season_number = clean_text(season_value)
        url = clean_text(value.get("url") or value.get("canonicalUrl"))
        identifier = first_non_empty(
            match_group(r"/title/(\d+)", url),
            clean_text(value.get("videoId") or value.get("titleId") or value.get("id")),
        )
        if season_number.isdigit() and episode_number.isdigit() and identifier.isdigit():
            image = value.get("image")
            if isinstance(image, dict):
                image = image.get("url")
            records[(int(season_number), int(episode_number), identifier)] = {
                "id": identifier,
                "url": url or f"https://www.netflix.com/title/{identifier}",
                "show_title": show_title,
                "season": int(season_number),
                "episode": int(episode_number),
                "title": clean_text(value.get("name") or value.get("title")),
                "description": clean_text(value.get("description") or value.get("synopsis")),
                "duration": duration_minutes(clean_text(value.get("duration"))),
                "date": clean_text(value.get("datePublished"))[:10],
                "image": clean_text(image),
            }
        for child in value.values():
            if isinstance(child, (dict, list)):
                visit(child)

    visit(values)
    return sorted(records.values(), key=lambda record: (record["season"], record["episode"], record["id"]))


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
            if clean_text(item.get("@type")).casefold() in {"movie", "videoobject", "tvseries", "tvepisode"}:
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


def parse_summary_runtime(lines: list[str]) -> str:
    """Read runtime only from the title summary, never from trailer or episode cards."""
    for index, line in enumerate(lines):
        if not re.fullmatch(r"18\d{2}|19\d{2}|20\d{2}|21\d{2}", clean_text(line)):
            continue
        for candidate in lines[index + 1:index + 6]:
            text = clean_text(candidate)
            if re.fullmatch(r"(?:(?:\d+)\s*h(?:ours?)?\s*)?(?:(?:\d+)\s*m(?:in)?)", text, re.IGNORECASE):
                return parse_runtime([text])
    return ""


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


def runtime_minutes_from_seconds(value: Any) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    return str(max(1, round(seconds / 60))) if seconds > 0 else ""


def year_from_text(text: str) -> str:
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2}|21\d{2})\b", text)
    return match.group(1) if match else ""


def split_csv(text: str) -> list[str]:
    return [clean_text(part) for part in re.split(r",\s*", clean_text(text)) if clean_text(part)]


def split_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    return split_csv(clean_text(value))


def people_names(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    output: list[str] = []
    for item in values:
        if isinstance(item, dict):
            name = clean_text(item.get("name"))
        else:
            name = clean_text(item)
        if name:
            output.append(name)
    return output


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
