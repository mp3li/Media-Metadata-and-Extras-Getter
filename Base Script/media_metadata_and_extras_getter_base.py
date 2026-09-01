#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, Callable


TOOL_NAME = "Media Metadata and Extras Getter by mp3li"
UNSUPPORTED_PROVIDER_MESSAGE = (
    "Unfortunately this tool does not cover that provider at this time. "
    "Please make an Issue on Github for a Feature Request."
)
HTTP_TIMEOUT_SECONDS = 25
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)
CHROME_APP_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PRIME_TRAILER_CAPTURE_TIMEOUT_SECONDS = 30
VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".ts",
    ".m2ts",
    ".webm",
    ".flv",
}
IMAGE_SUFFIXES = {
    "poster": "-poster.jpg",
    "fanart": "-fanart.jpg",
    "banner": "-banner.jpg",
    "landscape": "-landscape.jpg",
}


@dataclass
class Actor:
    name: str
    role: str = ""


@dataclass
class ExtraMedia:
    title: str
    kind: str = ""
    description: str = ""
    url: str = ""


@dataclass
class Metadata:
    source_url: str
    detail_link: str = ""
    source_site: str = ""
    media_kind: str = "movie"
    title: str = ""
    show_title: str = ""
    season_number: str = ""
    episode_number: str = ""
    episode_title: str = ""
    original_title: str = ""
    sort_title: str = ""
    plot: str = ""
    outline: str = ""
    tagline: str = ""
    year: str = ""
    series_start_year: str = ""
    series_end_year: str = ""
    series_is_current: bool = False
    date: str = ""
    runtime_minutes: str = ""
    content_rating: str = ""
    numeric_rating: str = ""
    language: str = ""
    poster_url: str = ""
    fanart_url: str = ""
    logo_url: str = ""
    thumb_url: str = ""
    trailer_url: str = ""
    production_label: str = "Production/Studio"
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    writers: list[str] = field(default_factory=list)
    credits: list[str] = field(default_factory=list)
    actors: list[Actor] = field(default_factory=list)
    unique_ids: dict[str, str] = field(default_factory=dict)
    extra_fields: dict[str, list[str]] = field(default_factory=dict)
    gallery_urls: list[str] = field(default_factory=list)
    extra_videos: list[ExtraMedia] = field(default_factory=list)
    series_episodes: list[dict[str, Any]] = field(default_factory=list)
    series_metadata: dict[str, Any] = field(default_factory=dict)
    folder_name_override: str = ""
    warnings: list[str] = field(default_factory=list)

    def add_values(self, field_name: str, values: Any) -> None:
        bucket = getattr(self, field_name)
        seen = {item.casefold() for item in bucket}
        for value in split_values(values):
            if value.casefold() not in seen:
                bucket.append(value)
                seen.add(value.casefold())

    def add_actors(self, values: list[dict[str, str]] | list[Actor]) -> None:
        seen = {(item.name.casefold(), item.role.casefold()) for item in self.actors}
        for value in values:
            if isinstance(value, Actor):
                actor = value
            else:
                actor = Actor(name=clean_text(value.get("name")), role=clean_text(value.get("role")))
            if not actor.name:
                continue
            key = (actor.name.casefold(), actor.role.casefold())
            if key not in seen:
                self.actors.append(actor)
                seen.add(key)

    def add_extra(self, label: str, value: Any) -> None:
        label_text = clean_text(label)
        value_text = clean_text(value)
        if not label_text or not value_text:
            return
        bucket = self.extra_fields.setdefault(label_text, [])
        if value_text.casefold() not in {item.casefold() for item in bucket}:
            bucket.append(value_text)


@dataclass
class MediaMatch:
    folder: Path
    video_path: Path
    filename_base: str
    score: float


@dataclass
class BBCMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    episode_id: str = ""
    episode_name: str = ""
    files: list[Path] = field(default_factory=list)


@dataclass
class CrunchyrollMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    files: list[Path] = field(default_factory=list)


@dataclass
class DisneyPlusMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    files: list[Path] = field(default_factory=list)


@dataclass
class AmazonPrimeMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    files: list[Path] = field(default_factory=list)


@dataclass
class HBOMaxMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    files: list[Path] = field(default_factory=list)


@dataclass
class NetflixMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    files: list[Path] = field(default_factory=list)


@dataclass
class PBSKidsMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    files: list[Path] = field(default_factory=list)


@dataclass
class ParamountPlusMediaGroup:
    folder: Path
    stem: str
    season: int
    episode: int
    files: list[Path] = field(default_factory=list)


class UnsupportedProviderError(ValueError):
    pass


class AnimatedStatus:
    def __init__(self, message: str) -> None:
        self.message = message
        self._enabled = sys.stdout.isatty()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "AnimatedStatus":
        if not self._enabled:
            print(self.message + "...")
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        if self._enabled:
            sys.stdout.write("\r" + (" " * (len(self.message) + 8)) + "\r")
            sys.stdout.flush()

    def _run(self) -> None:
        frames = ("   ", ".  ", ".. ", "...")
        index = 0
        while not self._stop.is_set():
            sys.stdout.write("\r" + self.message + frames[index % len(frames)])
            sys.stdout.flush()
            index += 1
            self._stop.wait(0.35)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def settings_dir() -> Path:
    return repo_root() / "Settings"


def load_settings() -> dict[str, Any]:
    default_path = settings_dir() / "settings-default.json"
    settings_path = settings_dir() / "settings.json"
    data: dict[str, Any] = {}
    if default_path.exists():
        data.update(load_json_file(default_path))
    if settings_path.exists():
        data.update(load_json_file(settings_path))
    return data


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            content = json.load(handle)
    except Exception:
        return {}
    return content if isinstance(content, dict) else {}


def provider_dir() -> Path:
    return repo_root() / "Provider Scripts"


def load_provider_script(module_name: str):
    path = provider_dir() / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Could not load provider script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


amazon = load_provider_script("amazon")
netflix = load_provider_script("netflix")
disneyplus = load_provider_script("disneyplus")
hbomax = load_provider_script("hbomax")
pbs_kids = load_provider_script("pbs_kids")
bbc_iplayer = load_provider_script("bbc_iplayer")
paramountplus = load_provider_script("paramountplus")
crunchyroll = load_provider_script("crunchyroll")

PROVIDER_HANDLERS = [
    ("amazon", amazon.NAME, amazon.is_supported_url),
    ("netflix", netflix.NAME, netflix.is_supported_url),
    ("disneyplus", disneyplus.NAME, disneyplus.is_supported_url),
    ("hbomax", hbomax.NAME, hbomax.is_supported_url),
    ("pbs_kids", pbs_kids.NAME, pbs_kids.is_supported_url),
    ("bbc_iplayer", bbc_iplayer.NAME, bbc_iplayer.is_supported_url),
    ("paramountplus", paramountplus.NAME, paramountplus.is_supported_url),
    ("crunchyroll", crunchyroll.NAME, crunchyroll.is_supported_url),
]


def provider_for_url(url: str) -> str:
    for key, _label, predicate in PROVIDER_HANDLERS:
        try:
            if predicate(url):
                return key
        except Exception:
            continue
    return ""


def metadata_from_provider_dict(item: dict[str, Any], detail_link: str = "") -> Metadata:
    meta = Metadata(source_url=clean_text(item.get("source_url")) or detail_link, detail_link=detail_link)
    meta.source_site = clean_text(item.get("source_site"))
    meta.media_kind = clean_text(item.get("media_kind")) or "movie"
    meta.title = clean_text(item.get("title"))
    meta.show_title = clean_text(item.get("show_title"))
    meta.season_number = clean_text(item.get("season_number"))
    meta.episode_number = clean_text(item.get("episode_number"))
    meta.episode_title = clean_text(item.get("episode_title"))
    meta.original_title = clean_text(item.get("original_title"))
    meta.sort_title = clean_text(item.get("sort_title"))
    meta.plot = clean_text(item.get("plot"))
    meta.outline = clean_text(item.get("outline")) or meta.plot
    meta.tagline = clean_text(item.get("tagline"))
    meta.year = clean_text(item.get("year"))
    meta.series_start_year = clean_text(item.get("series_start_year"))
    meta.series_end_year = clean_text(item.get("series_end_year"))
    meta.series_is_current = bool(item.get("series_is_current"))
    meta.date = clean_text(item.get("date"))
    meta.runtime_minutes = clean_text(item.get("runtime_minutes"))
    meta.content_rating = clean_text(item.get("content_rating"))
    meta.numeric_rating = clean_text(item.get("numeric_rating"))
    meta.language = clean_text(item.get("language"))
    meta.poster_url = clean_text(item.get("poster_url"))
    meta.fanart_url = clean_text(item.get("fanart_url"))
    meta.logo_url = clean_text(item.get("logo_url"))
    meta.thumb_url = clean_text(item.get("thumb_url"))
    meta.trailer_url = clean_text(item.get("trailer_url"))
    meta.production_label = clean_text(item.get("production_label")) or meta.production_label
    meta.folder_name_override = clean_text(item.get("folder_name_override"))
    raw_series_episodes = item.get("series_episodes", [])
    if isinstance(raw_series_episodes, list):
        meta.series_episodes = [value for value in raw_series_episodes if isinstance(value, dict)]
    raw_series_metadata = item.get("series_metadata", {})
    if isinstance(raw_series_metadata, dict):
        meta.series_metadata = raw_series_metadata
    meta.add_values("genres", item.get("genres", []))
    meta.add_values("tags", item.get("tags", []))
    meta.add_values("studios", item.get("studios", []))
    meta.add_values("countries", item.get("countries", []))
    meta.add_values("directors", item.get("directors", []))
    meta.add_values("writers", item.get("writers", []))
    meta.add_values("credits", item.get("credits", []))
    meta.add_actors(item.get("actors", []))
    meta.gallery_urls = [clean_text(url) for url in item.get("gallery_urls", []) if clean_text(url)]
    for extra in item.get("extra_videos", []):
        if isinstance(extra, dict):
            meta.extra_videos.append(
                ExtraMedia(
                    title=clean_text(extra.get("title")),
                    kind=clean_text(extra.get("kind")),
                    description=clean_text(extra.get("description")),
                    url=clean_text(extra.get("url")),
                )
            )
    unique_ids = item.get("unique_ids", {})
    if isinstance(unique_ids, dict):
        for key, value in unique_ids.items():
            if clean_text(key) and clean_text(value):
                meta.unique_ids[clean_text(key)] = clean_text(value)
    extra_fields = item.get("extra_fields", {})
    if isinstance(extra_fields, dict):
        for label, values in extra_fields.items():
            for value in split_values(values):
                meta.add_extra(str(label), value)
    warnings = item.get("warnings", [])
    if isinstance(warnings, list):
        meta.warnings = [clean_text(value) for value in warnings if clean_text(value)]
    clean_final_metadata(meta)
    return meta


def metadata_from_disneyplus(url: str, detail_link: str = "") -> Metadata:
    return metadata_from_provider_dict(
        disneyplus.extract_metadata(url, timeout=HTTP_TIMEOUT_SECONDS),
        detail_link=detail_link or url,
    )


def scrape_url(url: str) -> Metadata:
    normalized = normalize_url(url)
    provider = provider_for_url(normalized)
    if not provider:
        raise UnsupportedProviderError(UNSUPPORTED_PROVIDER_MESSAGE)
    if provider == "amazon":
        return metadata_from_provider_dict(amazon.extract_metadata(normalized), detail_link=url)
    if provider == "netflix":
        return metadata_from_provider_dict(netflix.extract_metadata(normalized), detail_link=url)
    if provider == "disneyplus":
        return metadata_from_disneyplus(normalized, detail_link=url)
    if provider == "hbomax":
        return metadata_from_provider_dict(hbomax.extract_metadata(normalized), detail_link=url)
    if provider == "pbs_kids":
        return metadata_from_provider_dict(pbs_kids.extract_metadata(normalized), detail_link=url)
    if provider == "bbc_iplayer":
        return metadata_from_provider_dict(bbc_iplayer.extract_metadata(normalized), detail_link=url)
    if provider == "paramountplus":
        return metadata_from_provider_dict(paramountplus.extract_metadata(normalized), detail_link=url)
    if provider == "crunchyroll":
        return metadata_from_provider_dict(crunchyroll.extract_metadata(normalized), detail_link=url)
    raise UnsupportedProviderError(UNSUPPORTED_PROVIDER_MESSAGE)


def normalize_url(url: str) -> str:
    text = clean_text(url)
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if not parsed.scheme:
        return "https://" + text
    return text


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def split_values(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (list, tuple, set)):
        output: list[str] = []
        for value in values:
            output.extend(split_values(value))
        return output
    text = clean_text(values)
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[|;]", text)]
    return [part for part in parts if part]


def clean_final_metadata(meta: Metadata) -> None:
    if not meta.outline and meta.plot:
        meta.outline = meta.plot
    if not meta.plot and meta.outline:
        meta.plot = meta.outline
    if meta.title.startswith("Watch "):
        meta.title = meta.title[6:].strip()
    for field_name in (
        "genres",
        "tags",
        "studios",
        "countries",
        "directors",
        "writers",
        "credits",
    ):
        values = getattr(meta, field_name)
        deduped = []
        seen = set()
        for value in values:
            folded = value.casefold()
            if value and folded not in seen:
                deduped.append(value)
                seen.add(folded)
        setattr(meta, field_name, deduped)


def format_preview(meta: Metadata) -> str:
    jellyfin_named_art = meta.source_site in {
        crunchyroll.NAME, disneyplus.NAME, hbomax.NAME, paramountplus.NAME, pbs_kids.NAME, amazon.PRIME_NAME
    }
    rows = [
        ("Source Site", meta.source_site),
        ("Detail Link Given", meta.detail_link),
        ("Fetched/Canonical URL", meta.source_url),
        ("Title", meta.title),
        ("Tagline", meta.tagline),
        ("Outline", meta.outline),
        ("Date", meta.date),
        ("Year", meta.year),
        ("Runtime", f"{meta.runtime_minutes} minutes" if meta.runtime_minutes else ""),
        ("Content Rating", meta.content_rating),
        ("Language", meta.language),
        (meta.production_label, join_list(meta.studios)),
        ("Country", join_list(meta.countries)),
        ("Genre", join_list(meta.genres)),
        ("Tags", join_list(meta.tags)),
        ("Director", join_list(meta.directors)),
        ("Writer", join_list(meta.writers)),
        ("Credits/Producer", join_list(meta.credits)),
        ("Cast", format_cast(meta.actors)),
        ("Poster" if jellyfin_named_art else "Cover Art", found_status(meta.poster_url)),
        (
            "Backdrop" if jellyfin_named_art else "Wide Art",
            found_status(meta.fanart_url) if jellyfin_named_art else wide_art_status(meta.fanart_url),
        ),
        ("Logo", found_status(meta.logo_url)),
        ("Thumbnail" if jellyfin_named_art else "Episode Thumbnail", found_status(meta.thumb_url)),
        ("Gallery", count_status(meta.gallery_urls, "image")),
        ("Extra Videos", count_status(meta.extra_videos, "video")),
        ("Trailer", found_status(meta.trailer_url)),
        ("Plot", meta.plot),
    ]
    output = ["-" * 72]
    for label, value in rows:
        if value:
            output.extend(wrap_row(label, value))
    if meta.extra_fields:
        output.append("")
        output.append("Additional scraped fields:")
        for label in sorted(meta.extra_fields, key=str.casefold):
            for value in meta.extra_fields[label]:
                output.extend(wrap_row(label, value))
    if meta.warnings:
        output.append("")
        output.append("Warnings:")
        output.extend(f"- {warning}" for warning in meta.warnings)
    output.append("-" * 72)
    return "\n".join(output)


def wrap_row(label: str, value: str) -> list[str]:
    prefix = f"{label}: "
    wrapped = textwrap.wrap(
        value,
        width=100,
        initial_indent=prefix,
        subsequent_indent=" " * len(prefix),
        break_long_words=False,
        break_on_hyphens=False,
    )
    return wrapped or [prefix.rstrip()]


def join_list(values: list[str]) -> str:
    return ", ".join(values)


def format_cast(actors: list[Actor]) -> str:
    parts = []
    for actor in actors:
        parts.append(f"{actor.name} as {actor.role}" if actor.role else actor.name)
    return ", ".join(parts)


def found_status(value: str) -> str:
    return "found" if clean_text(value) else ""


def wide_art_status(value: str) -> str:
    return "found (fanart, banner, landscape)" if clean_text(value) else ""


def count_status(values: list[Any], noun: str) -> str:
    count = len(values)
    if not count:
        return ""
    return f"found ({count} {noun if count == 1 else noun + 's'})"


def settings_output_dir(settings: dict[str, Any]) -> Path:
    path = clean_text(settings.get("default_output_dir")) or "Output"
    base = Path(path)
    if not base.is_absolute():
        base = repo_root() / base
    return base


def media_search_roots(settings: dict[str, Any]) -> list[Path]:
    roots = []
    for value in settings.get("media_folders", []):
        text = clean_text(value)
        if not text:
            continue
        roots.append(Path(text).expanduser())
    return roots


def file_candidates_for_title(meta: Metadata) -> list[str]:
    candidates = [meta.title]
    if meta.folder_name_override:
        candidates.append(meta.folder_name_override)
    if meta.studios:
        candidates.append(f"{meta.title} - {meta.studios[0]}")
    return [candidate for candidate in candidates if clean_text(candidate)]


def normalize_match_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def find_media_match(meta: Metadata, settings: dict[str, Any], explicit_folder: str = "") -> MediaMatch | None:
    if explicit_folder:
        folder = Path(explicit_folder).expanduser()
        return media_match_for_folder(meta, folder)
    if not settings.get("media_matching_enabled"):
        return None
    best: MediaMatch | None = None
    targets = [normalize_match_key(candidate) for candidate in file_candidates_for_title(meta)]
    if not any(targets):
        return None
    for root in media_search_roots(settings):
        if not root.exists():
            continue
        for folder, _dirs, files in os.walk(root):
            video_files = [
                Path(folder) / name
                for name in files
                if Path(name).suffix.casefold() in VIDEO_EXTENSIONS
            ]
            if not video_files:
                continue
            folder_path = Path(folder)
            folder_key = normalize_match_key(folder_path.name)
            for video in video_files:
                stem_key = normalize_match_key(video.stem)
                score = match_score(targets, folder_key, stem_key)
                if score <= 0:
                    continue
                candidate = MediaMatch(
                    folder=folder_path,
                    video_path=video,
                    filename_base=video.stem,
                    score=score,
                )
                if best is None or candidate.score > best.score:
                    best = candidate
    return best


def media_match_for_folder(meta: Metadata, folder: Path) -> MediaMatch | None:
    if not folder.exists():
        return None
    if folder.is_file():
        if folder.suffix.casefold() not in VIDEO_EXTENSIONS:
            return None
        return MediaMatch(folder=folder.parent, video_path=folder, filename_base=folder.stem, score=1.0)
    videos = sorted(
        [path for path in folder.iterdir() if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS]
    )
    if not videos:
        return None
    chosen = videos[0]
    return MediaMatch(folder=folder, video_path=chosen, filename_base=chosen.stem, score=1.0)


def match_score(targets: list[str], folder_key: str, stem_key: str) -> float:
    best = 0.0
    for target in targets:
        if not target:
            continue
        if target == stem_key:
            best = max(best, 1.0)
        elif target == folder_key:
            best = max(best, 0.95)
        elif target in stem_key or stem_key in target:
            best = max(best, 0.8)
        elif target in folder_key or folder_key in target:
            best = max(best, 0.75)
    return best


def safe_filename(text: str) -> str:
    value = clean_text(text).replace("/", " - ").replace(":", " -")
    value = value.replace("?", "").replace("*", "").replace('"', "")
    value = value.replace("<", "").replace(">", "").replace("|", "")
    value = value.replace("\\", " - ")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "Untitled"


def explicit_series_show_folder(
    explicit_folder: str,
    meta: Metadata,
    series_folder_name: Callable[[Metadata], str],
) -> Path | None:
    """Resolve one canonical series root beneath the exact MediaFab handoff location."""
    if not clean_text(explicit_folder):
        return None
    supplied = Path(explicit_folder).expanduser().resolve()
    root = supplied.parent if supplied.is_file() or supplied.suffix.casefold() in VIDEO_EXTENSIONS else supplied
    desired = series_folder_name(meta)
    if normalize_match_key(root.name) == normalize_match_key(desired):
        return root
    title = safe_filename(meta.show_title or meta.title)
    root_title = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(root_title) == normalize_match_key(title):
        return root.parent / desired
    return root / desired


def candidate_is_in_foreign_series_root(video: Path, explicit_folder: str, wanted_title: str) -> bool:
    """Keep broad handoff roots from donating an already-organized episode to another show."""
    if not clean_text(explicit_folder):
        return False
    supplied = Path(explicit_folder).expanduser().resolve()
    root = supplied.parent if supplied.is_file() else supplied
    try:
        relative_parent = video.resolve().parent.relative_to(root)
    except ValueError:
        return False
    wanted = normalize_match_key(wanted_title)
    current = root
    for part in relative_parent.parts:
        current /= part
        name_without_year = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", part)
        looks_like_series_root = bool(re.search(r" \(\d{4}(?:-(?:\d{4})?)?\)$", part)) or (
            current / "tvshow.nfo"
        ).exists()
        if looks_like_series_root and wanted not in normalize_match_key(name_without_year):
            return True
    return False


def local_episode_sidecars(video: Path) -> list[Path]:
    """Return only sidecars whose basename proves that they belong to one local episode."""
    output: list[Path] = []
    for sidecar in video.parent.iterdir():
        if not sidecar.is_file() or sidecar == video:
            continue
        if (
            sidecar.suffix.casefold() in {".srt", ".vtt", ".ass", ".ssa", ".sub", ".nfo"}
            and (sidecar.stem == video.stem or sidecar.name.startswith(video.stem + "."))
        ) or (
            sidecar.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".avif"}
            and sidecar.name.startswith(video.stem + "-thumb.")
        ):
            output.append(sidecar)
    return sorted(output)


def cleanup_empty_provider_source_folders(
    folders: set[Path], canonical_show_folder: Path | None, provider_name: str
) -> list[Path]:
    """Remove only matched source folders proven empty after successful organization."""
    removed: list[Path] = []
    canonical = canonical_show_folder.resolve() if canonical_show_folder else None
    for folder in sorted({path.resolve() for path in folders}, key=lambda path: len(path.parts), reverse=True):
        if not folder.is_dir() or folder.is_symlink():
            continue
        if canonical and (folder == canonical or canonical in folder.parents):
            continue
        entries = list(folder.iterdir())
        if any(entry.name != ".DS_Store" for entry in entries):
            continue
        ds_store = folder / ".DS_Store"
        if ds_store.exists() and ds_store.is_file() and not ds_store.is_symlink():
            ds_store.unlink()
        try:
            folder.rmdir()
        except OSError:
            continue
        removed.append(folder)
    if removed:
        print(f"{provider_name} cleanup removed {len(removed)} empty source folder(s).")
    return removed


def default_folder_name(meta: Metadata) -> str:
    if is_netflix_movie(meta):
        return netflix_movie_name(meta)
    if is_hbomax_movie(meta):
        return hbomax_movie_name(meta)
    if is_paramountplus_movie(meta):
        return paramountplus_movie_name(meta)
    if is_disneyplus_movie(meta):
        return disneyplus_movie_name(meta)
    if meta.folder_name_override:
        return safe_filename(meta.folder_name_override)
    if meta.studios and meta.source_site.casefold() != "netflix":
        return safe_filename(f"{meta.title} - {meta.studios[0]}")
    return safe_filename(meta.title)


def is_paramountplus_movie(meta: Metadata) -> bool:
    return meta.source_site == paramountplus.NAME and bool(meta.extra_fields.get("Paramount+ movie ID"))


def is_netflix_movie(meta: Metadata) -> bool:
    return meta.source_site == netflix.NAME and meta.media_kind.casefold() == "movie"


def netflix_movie_name(meta: Metadata) -> str:
    title = safe_filename(meta.title)
    return safe_filename(f"{title} ({meta.year})") if meta.year.isdigit() else title


def organize_netflix_movie(
    match: MediaMatch, meta: Metadata, explicit_folder: str = ""
) -> MediaMatch:
    if not is_netflix_movie(meta) or not match.video_path.exists():
        return match
    base = netflix_movie_name(meta)
    destination_parent = match.folder if explicit_folder else match.folder
    destination = destination_parent / base
    source_stem = match.video_path.stem
    related = [
        path for path in match.folder.iterdir()
        if path.is_file()
        and path.suffix.casefold() in VIDEO_EXTENSIONS | {".srt", ".vtt", ".ass", ".ssa", ".sub"}
        and (path.stem == source_stem or path.name.startswith(source_stem + "."))
    ]
    targets = [destination / (base + path.name[len(source_stem):]) for path in related]
    if any(target.exists() and target not in related for target in targets):
        raise FileExistsError(f"Netflix movie destination already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in zip(related, targets):
        if source != target:
            shutil.move(str(source), str(target))
    video = next((target for target in targets if target.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return MediaMatch(destination, video or match.video_path, base, match.score)


def paramountplus_movie_name(meta: Metadata) -> str:
    title = safe_filename(meta.title)
    return safe_filename(f"{title} ({meta.year})") if meta.year.isdigit() else title


def is_disneyplus_movie(meta: Metadata) -> bool:
    return meta.source_site == disneyplus.NAME and meta.media_kind.casefold() == "movie"


def disneyplus_movie_name(meta: Metadata) -> str:
    title = safe_filename(meta.title)
    return safe_filename(f"{title} ({meta.year})") if meta.year.isdigit() else title


def is_hbomax_movie(meta: Metadata) -> bool:
    return meta.source_site == hbomax.NAME and meta.media_kind.casefold() == "movie"


def hbomax_movie_name(meta: Metadata) -> str:
    title = safe_filename(meta.title)
    return safe_filename(f"{title} ({meta.year})") if meta.year.isdigit() else title


def organize_hbomax_movie(
    match: MediaMatch, meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> MediaMatch:
    if not is_hbomax_movie(meta) or not match.video_path.exists():
        return match
    base = hbomax_movie_name(meta)
    destination_parent = match.folder if explicit_folder else settings_output_dir(settings) / hbomax.NAME
    destination = destination_parent / base
    source_stem = match.video_path.stem
    related = [
        path for path in match.folder.iterdir()
        if path.is_file()
        and path.suffix.casefold() in VIDEO_EXTENSIONS | {".srt", ".vtt", ".ass", ".ssa", ".sub"}
        and (path.stem == source_stem or path.name.startswith(source_stem + "."))
    ]
    targets = [destination / (base + path.name[len(source_stem):]) for path in related]
    if any(target.exists() and target not in related for target in targets):
        raise FileExistsError(f"HBO Max movie destination already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in zip(related, targets):
        if source != target:
            shutil.move(str(source), str(target))
    video_target = destination / (base + match.video_path.suffix)
    return MediaMatch(destination, video_target, base, match.score)


def organize_disneyplus_movie(
    match: MediaMatch,
    meta: Metadata,
    settings: dict[str, Any],
    explicit_folder: str = "",
) -> MediaMatch:
    if not is_disneyplus_movie(meta) or not match.video_path.exists():
        return match
    base = disneyplus_movie_name(meta)
    destination_parent = match.folder if explicit_folder else settings_output_dir(settings) / disneyplus.NAME
    destination = destination_parent / base
    source_stem = match.video_path.stem
    related_files = [
        path for path in match.folder.iterdir()
        if path.is_file()
        and path.suffix.casefold() in VIDEO_EXTENSIONS | {".srt", ".vtt", ".ass", ".ssa", ".sub"}
        and (path.stem == source_stem or path.name.startswith(source_stem + "."))
    ]
    targets = [destination / (base + path.name[len(source_stem):]) for path in related_files]
    if any(target.exists() and target not in related_files for target in targets):
        raise FileExistsError(f"Disney+ movie destination already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in zip(related_files, targets):
        if source != target:
            shutil.move(str(source), str(target))
    video_target = destination / (base + match.video_path.suffix)
    return MediaMatch(destination, video_target, base, match.score)


def organize_paramountplus_movie(
    match: MediaMatch, meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> MediaMatch:
    """Move a matched Paramount+ movie and its matching subtitle sidecars into its requested library folder."""
    if not is_paramountplus_movie(meta) or not match.video_path.exists():
        return match
    base = paramountplus_movie_name(meta)
    destination_parent = match.folder if explicit_folder else settings_output_dir(settings) / paramountplus.NAME
    destination = destination_parent / base
    source_stem = match.video_path.stem
    subtitle_extensions = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
    related_files = [
        path for path in match.folder.iterdir()
        if (
            path.is_file()
            and path.suffix.casefold() in VIDEO_EXTENSIONS | subtitle_extensions
            and (path.stem == source_stem or path.name.startswith(source_stem + "."))
        )
    ]
    targets = [
        destination / (base + path.name[len(source_stem):])
        for path in related_files
    ]
    if any(target.exists() and target not in related_files for target in targets):
        raise FileExistsError(f"Paramount+ movie destination already exists: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in zip(related_files, targets):
        if source != target:
            shutil.move(str(source), str(target))
    video_target = destination / (base + match.video_path.suffix)
    return MediaMatch(folder=destination, video_path=video_target, filename_base=base, score=match.score)


def maybe_rename_generic_video(match: MediaMatch, meta: Metadata, settings: dict[str, Any]) -> MediaMatch:
    if not settings.get("rename_generic_video_filenames"):
        return match
    if not match.video_path.exists():
        return match
    stem = match.video_path.stem
    if not re.fullmatch(r"master(?:-[a-f0-9-]+|_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:_\d+)?", stem):
        return match
    if (
        meta.source_site == paramountplus.NAME
        and meta.media_kind.casefold() == "episode"
        and meta.season_number.isdigit()
        and meta.episode_number.isdigit()
    ):
        new_base = safe_filename(
            f"S{int(meta.season_number):02d}E{int(meta.episode_number):02d} "
            f"{meta.show_title or meta.title} - {meta.episode_title}"
        )
    else:
        new_base = safe_filename(meta.folder_name_override or meta.title)
    new_path = match.video_path.with_name(new_base + match.video_path.suffix)
    related_files = [
        path for path in match.folder.iterdir()
        if path.is_file() and (path.stem == stem or path.name.startswith(stem + "."))
    ]
    targets = [
        path.with_name(new_base + path.name[len(stem):])
        for path in related_files
    ]
    if any(target.exists() and target not in related_files for target in targets):
        return match
    for path, target in zip(related_files, targets):
        path.rename(target)
    return MediaMatch(folder=match.folder, video_path=new_path, filename_base=new_base, score=match.score)


def bbc_series_enabled(meta: Metadata, settings: dict[str, Any]) -> bool:
    return (
        meta.source_site == bbc_iplayer.NAME
        and meta.media_kind.casefold() == "episode"
        and bool(settings.get("bbc_series_metadata_enabled", True))
        and bool(media_search_roots(settings))
    )


def bbc_media_groups(meta: Metadata, settings: dict[str, Any]) -> list[BBCMediaGroup]:
    wanted_title = normalize_match_key(meta.show_title or meta.title)
    grouped: dict[tuple[Path, str], BBCMediaGroup] = {}
    subtitle_extensions = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
    for root in media_search_roots(settings):
        if not root.exists():
            continue
        for folder_text, _dirs, filenames in os.walk(root):
            folder = Path(folder_text)
            for filename in filenames:
                path = folder / filename
                if path.suffix.casefold() not in VIDEO_EXTENSIONS | subtitle_extensions:
                    continue
                parsed = parse_bbc_media_stem(path.stem)
                if not parsed:
                    continue
                source_title, season, episode, episode_id = parsed
                title_key = normalize_match_key(source_title)
                if not (wanted_title and (wanted_title in title_key or title_key in wanted_title)):
                    continue
                key = (folder, path.stem)
                group = grouped.setdefault(
                    key,
                    BBCMediaGroup(
                        folder=folder,
                        stem=path.stem,
                        season=season,
                        episode=episode,
                        episode_id=episode_id,
                        episode_name=bbc_filename_episode_name(
                            path.stem, meta.show_title or meta.title, is_special=(season == 0)
                        ),
                    ),
                )
                group.files.append(path)
    completed = [
        group for group in grouped.values()
        if not (group.folder / f"{group.stem}.jpg").exists()
    ]
    return sorted(completed, key=lambda item: (item.season, item.episode, str(item.folder), item.stem))


def parse_bbc_media_stem(stem: str) -> tuple[str, int, int, str] | None:
    text = re.sub(r"[_]+", " ", stem).strip()
    downloaded = re.match(
        r"^(.*?)\s+(?:series|season)\s+(\d+)\s*-\s*(\d+)\.\s*episode\s+\d+\s+([a-z0-9]{8})\s+(?:original|editorial)$",
        text,
        flags=re.IGNORECASE,
    )
    if downloaded:
        return downloaded.group(1), int(downloaded.group(2)), int(downloaded.group(3)), downloaded.group(4).casefold()
    titled_episode = re.match(
        r"^(.*?)\s+(?:series|season)\s+(\d+)\s*-\s*(\d+)\.\s*.+?\s+([a-z0-9]{8})\s+(?:original|editorial)$",
        text,
        flags=re.IGNORECASE,
    )
    if titled_episode:
        return (
            titled_episode.group(1),
            int(titled_episode.group(2)),
            int(titled_episode.group(3)),
            titled_episode.group(4).casefold(),
        )
    getter_series = re.match(
        r"^(.*?)\s*-\s*S(\d{1,2})E(\d{1,3})\s*-\s+.+?\s+-\s+([a-z0-9]{8})$",
        text,
        flags=re.IGNORECASE,
    )
    if getter_series:
        return (
            getter_series.group(1),
            int(getter_series.group(2)),
            int(getter_series.group(3)),
            getter_series.group(4).casefold(),
        )
    special = re.match(
        r"^(.*?)\s*-\s*(\d+)\.\s*.+?\s+([a-z0-9]{8})\s+(?:original|editorial)$",
        text,
        flags=re.IGNORECASE,
    )
    if special:
        return special.group(1), 0, int(special.group(2)), special.group(3).casefold()
    renamed = re.match(r"^S(\d{1,2})E(\d{1,3})\s+(.+?)(?:\.[a-z]{2,3})?$", text, flags=re.IGNORECASE)
    if renamed:
        return renamed.group(3), int(renamed.group(1)), int(renamed.group(2)), ""
    return None


def bbc_filename_episode_name(stem: str, show_title: str, is_special: bool = False) -> str:
    """Keep the descriptive episode title used by the Get iPlayer naming style."""
    text = re.sub(r"[_]+", " ", stem).strip()
    getter_name = re.match(
        r"^.*?\s*-\s*S\d{1,2}E\d{1,3}\s*-\s+(.+?)\s+-\s+[a-z0-9]{8}$",
        text,
        flags=re.IGNORECASE,
    )
    if getter_name:
        descriptive_title = clean_text(getter_name.group(1))
        series_title, separator, episode_title = descriptive_title.partition(" - ")
        if not separator:
            return descriptive_title
        series_title = re.sub(r"\s*\([^)]*\)\s*$", "", series_title).strip()
        return " - ".join(part for part in (series_title, episode_title) if part)
    if is_special:
        special_name = re.match(
            r"^.*?\s*-\s*\d+\.\s*(.+?)\s+[a-z0-9]{8}\s+(?:original|editorial)$",
            text,
            flags=re.IGNORECASE,
        )
        if special_name:
            return clean_text(special_name.group(1))
    normalized = re.match(
        rf"^S\d{{1,2}}E\d{{1,3}}\s+{re.escape(clean_text(show_title))}\s*-\s+(.+?)(?:\.[a-z]{{2,3}})?$",
        text,
        flags=re.IGNORECASE,
    )
    return clean_text(normalized.group(1)) if normalized else ""


def bbc_series_links(meta: Metadata, original_url: str) -> dict[int, str]:
    links: dict[int, str] = {}
    for value in meta.extra_fields.get("Available series / collection", []):
        label, separator, slice_id = value.partition(" | ")
        match = re.fullmatch(r"Series\s+(\d+)", label, flags=re.IGNORECASE)
        if not (separator and match and slice_id):
            continue
        parsed = urllib.parse.urlsplit(original_url)
        query = urllib.parse.parse_qs(parsed.query)
        query["seriesId"] = [slice_id]
        links[int(match.group(1))] = urllib.parse.urlunsplit(
            (parsed.scheme or "https", parsed.netloc, parsed.path, urllib.parse.urlencode(query, doseq=True), "")
        )
    return links


def bbc_resolve_local_episode_ids(
    groups: list[BBCMediaGroup], meta: Metadata, original_url: str
) -> None:
    unresolved_seasons = {item.season for item in groups if not item.episode_id}
    links = bbc_series_links(meta, original_url)
    id_by_position: dict[tuple[int, int], str] = {}
    for season in unresolved_seasons:
        link = links.get(season)
        if not link:
            continue
        try:
            cards = bbc_iplayer.fetch_series_episodes(link, timeout=HTTP_TIMEOUT_SECONDS)
        except Exception:
            continue
        for card in cards:
            subtitle = clean_text(((card.get("subtitle") or {}).get("default"))) if isinstance(card, dict) else ""
            match = re.search(r"\bSeries\s+(\d+)\s*:\s*Episode\s+(\d+)\b", subtitle, re.IGNORECASE)
            episode_id = clean_text(card.get("id")) if isinstance(card, dict) else ""
            if match and episode_id:
                id_by_position[(int(match.group(1)), int(match.group(2)))] = episode_id
    for group in groups:
        if not group.episode_id:
            group.episode_id = id_by_position.get((group.season, group.episode), "")


def bbc_target_base(meta: Metadata, group: BBCMediaGroup) -> str:
    base = f"S{group.season:02d}E{group.episode:02d} {meta.show_title or meta.title}"
    if group.episode_name:
        base += f" - {group.episode_name}"
    return safe_filename(base)


def bbc_subtitle_language(path: Path) -> str:
    match = re.search(r"(?:^|[._ -])(en|eng|english|cy|wel|welsh|gd|gla)(?:[._ -]|$)", path.stem, re.I)
    if not match:
        return "und"
    return {"eng": "en", "english": "en", "wel": "cy", "welsh": "cy", "gla": "gd"}.get(match.group(1).casefold(), match.group(1).casefold())


def prepare_bbc_media_group(meta: Metadata, group: BBCMediaGroup, settings: dict[str, Any]) -> BBCMediaGroup:
    rename = bool(settings.get("bbc_series_rename_enabled"))
    organize = bool(settings.get("bbc_series_organize_enabled"))
    if not (rename or organize):
        return group
    destination = group.folder / f"S{group.season:02d}" if organize else group.folder
    base = bbc_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    for path in group.files:
        suffix = path.suffix
        target_name = base + suffix
        if suffix.casefold() in {".srt", ".vtt", ".ass", ".ssa", ".sub"} and rename:
            target_name = f"{base}.{bbc_subtitle_language(path)}{suffix}"
        target = destination / target_name
        if target in used or (target.exists() and target not in group.files):
            raise FileExistsError(f"BBC rename target already exists: {target}")
        used.add(target)
        targets.append((path, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        temp = source.with_name(f".bbc-rename-{index}-{source.name}")
        source.rename(temp)
        temporary.append((temp, target))
    for temp, target in temporary:
        temp.rename(target)
    video_files = [target for _temp, target in temporary if target.suffix.casefold() in VIDEO_EXTENSIONS]
    return BBCMediaGroup(
        folder=destination,
        stem=(video_files[0].stem if video_files else base),
        season=group.season,
        episode=group.episode,
        episode_id=group.episode_id,
        episode_name=group.episode_name,
        files=[target for _temp, target in temporary],
    )


def save_bbc_series_metadata(
    meta: Metadata, original_url: str, settings: dict[str, Any], skip_existing: bool = False
) -> list[Path] | None:
    if not bbc_series_enabled(meta, settings):
        return None
    groups = bbc_media_groups(meta, settings)
    if not groups:
        return None
    bbc_resolve_local_episode_ids(groups, meta, original_url)
    saved: list[Path] = []
    unresolved: list[str] = []
    resolved: list[tuple[BBCMediaGroup, Metadata]] = []
    for group in groups:
        if not group.episode_id:
            unresolved.append(f"S{group.season:02d}E{group.episode:02d}")
            continue
        episode_url = bbc_iplayer.canonical_episode_url(group.episode_id)
        episode_meta = metadata_from_provider_dict(bbc_iplayer.extract_metadata(episode_url), detail_link=episode_url)
        if group.season == 0:
            if not (episode_meta.season_number.isdigit() and episode_meta.episode_number.isdigit()):
                unresolved.append(f"special {group.episode_id} (BBC series placement unavailable)")
                continue
            group.season = int(episode_meta.season_number)
            group.episode = int(episode_meta.episode_number)
        else:
            # The user's established Get iPlayer filename numbering is authoritative.
            episode_meta.media_kind = "episode"
            episode_meta.show_title = meta.show_title or meta.title
            episode_meta.season_number = str(group.season)
            episode_meta.episode_number = str(group.episode)
        resolved.append((group, episode_meta))

    artwork_saved_for: set[tuple[Path, int]] = set()
    for group, episode_meta in sorted(resolved, key=lambda item: (item[0].season, item[0].episode, item[0].episode_id)):
        prepared = prepare_bbc_media_group(episode_meta, group, settings)
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            unresolved.append(f"S{group.season:02d}E{group.episode:02d} (no video file)")
            continue
        artwork_key = (prepared.folder, prepared.season)
        include_artwork = artwork_key not in artwork_saved_for
        saved.extend(
            save_metadata_bundle_to_location(
                episode_meta,
                prepared.folder,
                video.stem,
                skip_existing=skip_existing,
                include_artwork=include_artwork,
                artwork_base_name=f"{episode_meta.show_title or episode_meta.title} - season{prepared.season:02d}",
            )
        )
        if include_artwork:
            artwork_saved_for.add(artwork_key)
    if unresolved:
        print("BBC metadata not saved for: " + ", ".join(unresolved))
    print(f"BBC series mode found {len(groups)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def bbc_queue_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[BBCMediaGroup, dict[str, Any]]]:
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    guide = {
        (int(record["season"]), int(record["episode"])): record
        for record in records
        if clean_text(record.get("season")).isdigit() and clean_text(record.get("episode")).isdigit()
    }
    roots = [Path(explicit_folder).expanduser().resolve()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
        elif root.is_dir():
            for folder_text, _dirs, filenames in os.walk(root):
                candidates.extend(
                    Path(folder_text) / filename
                    for filename in filenames
                    if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS
                )
    direct = None
    if meta.media_kind.casefold() == "episode" and meta.season_number.isdigit() and meta.episode_number.isdigit():
        direct = (int(meta.season_number), int(meta.episode_number))
    wanted_title = normalize_match_key(meta.show_title or meta.title)
    matched: list[tuple[BBCMediaGroup, dict[str, Any]]] = []
    claimed: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        if video.with_suffix(".jpg").exists():
            continue
        path_key = normalize_match_key(str(video))
        if not explicit_folder and wanted_title not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        id_matches = [
            record for record in records
            if clean_text(record.get("id")) and normalize_match_key(record["id"]) in stem_key
        ]
        if len(id_matches) == 1:
            position = (int(id_matches[0]["season"]), int(id_matches[0]["episode"]))
        elif explicit_folder and len(candidates) == 1 and direct:
            position = direct
        else:
            position = paramountplus_episode_position(f"{video.stem} {video.parent.name}")
        record = guide.get(position) if position else None
        if not record:
            title_matches = [
                item for item in records
                if len(normalize_match_key(clean_text(item.get("title")))) >= 4
                and normalize_match_key(clean_text(item.get("title"))) in stem_key
            ]
            record = title_matches[0] if len(title_matches) == 1 else None
            position = (
                (int(record["season"]), int(record["episode"]))
                if record else None
            )
        if not (record and position) or position in claimed:
            continue
        claimed.add(position)
        matched.append((
            BBCMediaGroup(
                video.parent, video.stem, position[0], position[1],
                clean_text(record.get("id")), clean_text(record.get("title")),
                [video, *local_episode_sidecars(video)],
            ),
            record,
        ))
    return sorted(matched, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def bbc_queue_series_folder_name(meta: Metadata) -> str:
    title = safe_filename(meta.show_title or meta.title)
    start = clean_text(meta.series_start_year)
    end = clean_text(meta.series_end_year)
    if not start.isdigit():
        return title
    years = f"{start}-" if meta.series_is_current else (start if not end or end == start else f"{start}-{end}")
    return safe_filename(f"{title} ({years})")


def bbc_queue_target_base(meta: Metadata, group: BBCMediaGroup) -> str:
    value = f"S{group.season:02d}E{group.episode:02d} {meta.show_title or meta.title}"
    if group.episode_name:
        value += f" - {group.episode_name}"
    return safe_filename(value)


def prepare_bbc_queue_media_group(
    meta: Metadata,
    group: BBCMediaGroup,
    settings: dict[str, Any],
    explicit_show_folder: Path | None,
) -> BBCMediaGroup:
    rename = bool(settings.get("bbc_series_rename_enabled", True))
    organize = bool(settings.get("bbc_series_organize_enabled", True))
    if not (rename or organize):
        return group
    destination = (
        (explicit_show_folder or group.folder / bbc_queue_series_folder_name(meta)) / f"S{group.season:02d}"
        if organize else group.folder
    )
    base = bbc_queue_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    for source in group.files:
        suffix = source.name[len(group.stem):]
        target = destination / ((base + suffix) if rename else source.name)
        if target in used or (target.exists() and target not in group.files):
            raise FileExistsError(f"BBC iPlayer rename target already exists: {target}")
        used.add(target)
        targets.append((source, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        if source == target:
            temporary.append((source, target)); continue
        temp = source.with_name(f".bbc-queue-rename-{index}-{source.name}")
        source.rename(temp); temporary.append((temp, target))
    for temp, target in temporary:
        if temp != target:
            temp.rename(target)
    final_files = [target for _source, target in targets]
    video = next((path for path in final_files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return BBCMediaGroup(
        destination, video.stem if video else base, group.season, group.episode,
        group.episode_id, group.episode_name, final_files,
    )


def bbc_queue_episode_metadata(meta: Metadata, record: dict[str, Any]) -> Metadata:
    series = metadata_from_provider_dict(meta.series_metadata) if meta.series_metadata else meta
    episode_id = clean_text(record.get("id"))
    duration = clean_text(record.get("duration"))
    runtime = str(round(int(duration) / 60)) if duration.isdigit() else duration_minutes_text(duration)
    episode = Metadata(
        source_url=clean_text(record.get("url")) or meta.source_url,
        detail_link=clean_text(record.get("url")), source_site=bbc_iplayer.NAME,
        media_kind="episode", title=series.title, show_title=series.title,
        season_number=clean_text(record.get("season")), episode_number=clean_text(record.get("episode")),
        episode_title=clean_text(record.get("title")), outline=clean_text(record.get("outline")),
        plot=clean_text(record.get("description")) or clean_text(record.get("outline")),
        date=clean_text(record.get("date")), year=clean_text(record.get("date"))[:4],
        runtime_minutes=runtime,
        series_start_year=series.series_start_year, series_end_year=series.series_end_year,
        series_is_current=series.series_is_current, thumb_url=clean_text(record.get("image")),
        genres=list(series.genres), tags=list(series.tags), studios=list(series.studios),
        unique_ids={"bbc_iplayer": episode_id} if episode_id else {}, series_metadata=meta.series_metadata,
    )
    episode.add_extra("BBC Episode ID", episode_id)
    episode.add_extra("Episode page", episode.detail_link)
    return episode


def save_bbc_queue_series_bundle(meta: Metadata, show_folder: Path) -> list[Path]:
    series = metadata_from_provider_dict(meta.series_metadata) if meta.series_metadata else meta
    show_folder.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    nfo = show_folder / "tvshow.nfo"
    if not nfo.exists():
        nfo.write_text(build_nfo(series), encoding="utf-8"); saved.append(nfo)
    for name, url in (("poster", series.poster_url), ("backdrop", series.fanart_url), ("logo", series.logo_url)):
        if not clean_text(url):
            continue
        target = show_folder / f"{name}{image_extension_from_url(url) or ('.png' if name == 'logo' else '.jpg')}"
        if not target.exists():
            path = download_binary(url, target)
            if path:
                if name == "logo" and isinstance(path, Path):
                    path = normalize_provider_logo_file(path)
                saved.append(path)
    return saved


def save_bbc_queue_series_metadata(
    meta: Metadata,
    settings: dict[str, Any],
    explicit_folder: str = "",
    skip_existing: bool = False,
) -> list[Path] | None:
    if not (
        meta.source_site == bbc_iplayer.NAME
        and meta.media_kind.casefold() == "episode"
        and meta.series_episodes
        and bool(settings.get("bbc_series_metadata_enabled", True))
        and bool(explicit_folder or media_search_roots(settings))
    ):
        return None
    matches = bbc_queue_media_groups(meta, settings, explicit_folder)
    if not matches:
        return []
    explicit_show_folder = explicit_series_show_folder(explicit_folder, meta, bbc_queue_series_folder_name)
    source_folders = {group.folder for group, _record in matches}
    saved: list[Path] = []
    bundled = False
    for group, record in matches:
        episode_meta = bbc_queue_episode_metadata(meta, record)
        prepared = prepare_bbc_queue_media_group(episode_meta, group, settings, explicit_show_folder)
        show_folder = explicit_show_folder or prepared.folder.parent
        if not bundled:
            saved.extend(save_bbc_queue_series_bundle(meta, show_folder)); bundled = True
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            continue
        nfo = video.with_suffix(".nfo")
        if not (skip_existing and nfo.exists()):
            nfo.write_text(build_nfo(episode_meta), encoding="utf-8"); saved.append(nfo)
        thumb = video.with_name(f"{video.stem}-thumb{image_extension_from_url(episode_meta.thumb_url) or '.jpg'}")
        if episode_meta.thumb_url and not thumb.exists():
            path = download_binary(episode_meta.thumb_url, thumb)
            if path:
                saved.append(path)
    cleanup_empty_provider_source_folders(source_folders, explicit_show_folder, bbc_iplayer.NAME)
    print(f"BBC iPlayer Queue Mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def netflix_series_folder_name(meta: Metadata) -> str:
    title = safe_filename(meta.show_title or meta.title)
    start = clean_text(meta.series_start_year or meta.year)
    end = clean_text(meta.series_end_year)
    if not start.isdigit():
        return title
    years = f"{start}-" if meta.series_is_current else (start if not end or end == start else f"{start}-{end}")
    return safe_filename(f"{title} ({years})")


def netflix_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[NetflixMediaGroup, dict[str, Any]]]:
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    guide = {
        (int(record["season"]), int(record["episode"])): record
        for record in records
        if clean_text(record.get("season")).isdigit() and clean_text(record.get("episode")).isdigit()
    }
    roots = [Path(explicit_folder).expanduser().resolve()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
        elif root.is_dir():
            for folder_text, _dirs, filenames in os.walk(root):
                candidates.extend(
                    Path(folder_text) / filename
                    for filename in filenames
                    if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS
                )
    wanted = normalize_match_key(meta.show_title or meta.title)
    matched: list[tuple[NetflixMediaGroup, dict[str, Any]]] = []
    claimed: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        path_key = normalize_match_key(str(video))
        if not explicit_folder and wanted not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        identity = [
            record for record in records
            if clean_text(record.get("id")) and normalize_match_key(record["id"]) in stem_key
        ]
        if len(identity) == 1:
            position = (int(identity[0]["season"]), int(identity[0]["episode"]))
        else:
            position = paramountplus_episode_position(f"{video.stem} {video.parent.name}")
        record = guide.get(position) if position else None
        if not record:
            title_matches = [
                item for item in records
                if len(normalize_match_key(clean_text(item.get("title")))) >= 4
                and normalize_match_key(clean_text(item.get("title"))) in stem_key
            ]
            record = title_matches[0] if len(title_matches) == 1 else None
            position = (int(record["season"]), int(record["episode"])) if record else None
        if not (record and position) or position in claimed:
            continue
        claimed.add(position)
        matched.append((
            NetflixMediaGroup(video.parent, video.stem, position[0], position[1], [video, *local_episode_sidecars(video)]),
            record,
        ))
    return sorted(matched, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def netflix_episode_metadata(meta: Metadata, record: dict[str, Any]) -> Metadata:
    identifier = clean_text(record.get("id"))
    return Metadata(
        source_url=clean_text(record.get("url")) or meta.source_url,
        detail_link=clean_text(record.get("url")), source_site=netflix.NAME,
        media_kind="episode", title=meta.title, show_title=meta.title,
        season_number=clean_text(record.get("season")), episode_number=clean_text(record.get("episode")),
        episode_title=clean_text(record.get("title")), outline=clean_text(record.get("description")),
        plot=clean_text(record.get("description")), date=clean_text(record.get("date")),
        year=clean_text(record.get("date"))[:4], runtime_minutes=clean_text(record.get("duration")),
        series_start_year=meta.series_start_year, series_end_year=meta.series_end_year,
        series_is_current=meta.series_is_current, content_rating=meta.content_rating,
        thumb_url=clean_text(record.get("image")), genres=list(meta.genres), tags=list(meta.tags),
        studios=list(meta.studios), actors=list(meta.actors),
        unique_ids={"netflix": identifier} if identifier else {},
    )


def save_netflix_series_metadata(
    meta: Metadata,
    settings: dict[str, Any],
    explicit_folder: str = "",
    skip_existing: bool = False,
) -> list[Path] | None:
    if meta.source_site != netflix.NAME or meta.media_kind.casefold() != "series":
        return None
    if not meta.series_episodes:
        print("Netflix Queue Mode skipped: the public title page did not expose an identifiable episode catalog.")
        return []
    matches = netflix_media_groups(meta, settings, explicit_folder)
    if not matches:
        return []
    show_folder = explicit_series_show_folder(explicit_folder, meta, netflix_series_folder_name)
    source_folders = {group.folder for group, _record in matches}
    saved: list[Path] = []
    bundled = False
    for group, record in matches:
        episode_meta = netflix_episode_metadata(meta, record)
        destination = (show_folder or group.folder / netflix_series_folder_name(meta)) / f"S{group.season:02d}"
        base = safe_filename(
            f"S{group.season:02d}E{group.episode:02d} {meta.title}"
            + (f" - {episode_meta.episode_title}" if episode_meta.episode_title else "")
        )
        targets = [(source, destination / (base + source.name[len(group.stem):])) for source in group.files]
        if any(target.exists() and target not in group.files for _source, target in targets):
            raise FileExistsError(f"Netflix rename target already exists under {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        for index, (source, target) in enumerate(targets, start=1):
            if source == target:
                continue
            temporary = source.with_name(f".netflix-queue-{index}-{source.name}")
            source.rename(temporary); temporary.rename(target)
        video = next((target for _source, target in targets if target.suffix.casefold() in VIDEO_EXTENSIONS), None)
        canonical = show_folder or destination.parent
        if not bundled:
            canonical.mkdir(parents=True, exist_ok=True)
            nfo = canonical / "tvshow.nfo"
            if not nfo.exists():
                nfo.write_text(build_nfo(meta), encoding="utf-8"); saved.append(nfo)
            for name, url in (("poster", meta.poster_url), ("backdrop", meta.fanart_url)):
                if clean_text(url):
                    target = canonical / f"{name}{image_extension_from_url(url) or '.jpg'}"
                    if not target.exists():
                        path = download_binary(url, target)
                        if path:
                            saved.append(path)
            bundled = True
        if not video:
            continue
        episode_nfo = video.with_suffix(".nfo")
        if not (skip_existing and episode_nfo.exists()):
            episode_nfo.write_text(build_nfo(episode_meta), encoding="utf-8"); saved.append(episode_nfo)
        thumb = video.with_name(f"{video.stem}-thumb{image_extension_from_url(episode_meta.thumb_url) or '.jpg'}")
        if episode_meta.thumb_url and not thumb.exists():
            path = download_binary(episode_meta.thumb_url, thumb)
            if path:
                saved.append(path)
    canonical = show_folder or next(iter(matches))[0].folder / netflix_series_folder_name(meta)
    if meta.trailer_url:
        trailer_dir = canonical / "trailers"; trailer_dir.mkdir(parents=True, exist_ok=True)
        trailer = download_binary(meta.trailer_url, trailer_dir / "trailer.mp4")
        if trailer:
            saved.append(trailer)
    cleanup_empty_provider_source_folders(source_folders, show_folder, netflix.NAME)
    print(f"Netflix Queue Mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def crunchyroll_series_enabled(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> bool:
    return (
        meta.source_site == crunchyroll.NAME
        and meta.media_kind.casefold() in {"series", "episode"}
        and bool(meta.series_episodes)
        and bool(settings.get("crunchyroll_series_metadata_enabled", True))
        and bool(explicit_folder or media_search_roots(settings))
    )


def crunchyroll_episode_position(text: str) -> tuple[int, int] | None:
    """Read common local anime season/episode spellings, including an E-only season-one form."""
    position = paramountplus_episode_position(text)
    if position:
        return position
    match = re.search(
        r"(?:^|[^a-z0-9])(?:episode|ep|e)\s*0?(\d{1,3})(?:$|[^a-z0-9])",
        text,
        re.IGNORECASE,
    )
    return (1, int(match.group(1))) if match else None


def crunchyroll_target_base(meta: Metadata, group: CrunchyrollMediaGroup | None = None) -> str:
    season = group.season if group else int(meta.season_number or 1)
    episode = group.episode if group else int(meta.episode_number or 0)
    show = meta.show_title or meta.title
    title = meta.episode_title
    base = f"S{season:02d}E{episode:02d} {show}"
    if title:
        base += f" - {title}"
    return safe_filename(base)


def crunchyroll_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[CrunchyrollMediaGroup, dict[str, Any]]]:
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    guide = {
        (int(record["season"]), int(record["episode"])): record
        for record in records
        if clean_text(record.get("season")).isdigit() and clean_text(record.get("episode")).isdigit()
    }
    roots = [Path(explicit_folder).expanduser()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
            continue
        for folder_text, _dirs, filenames in os.walk(root):
            candidates.extend(
                Path(folder_text) / filename
                for filename in filenames
                if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS
            )
    wanted_title = normalize_match_key(meta.show_title or meta.title)
    direct_position = None
    if meta.media_kind.casefold() == "episode" and meta.season_number.isdigit() and meta.episode_number.isdigit():
        direct_position = (int(meta.season_number), int(meta.episode_number))
    matched: list[tuple[CrunchyrollMediaGroup, dict[str, Any]]] = []
    claimed: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        path_key = normalize_match_key(str(video))
        if not explicit_folder and wanted_title and wanted_title not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        id_matches = [
            record for record in records
            if clean_text(record.get("id")) and normalize_match_key(record["id"]) in stem_key
        ]
        if len(id_matches) == 1:
            position = (int(id_matches[0]["season"]), int(id_matches[0]["episode"]))
        elif explicit_folder and len(candidates) == 1 and direct_position:
            position = direct_position
        else:
            position = crunchyroll_episode_position(f"{video.stem} {video.parent.name}")
        record = guide.get(position) if position else None
        if not (position and record) or position in claimed:
            continue
        claimed.add(position)
        if video.with_suffix(".jpg").exists():
            continue
        files = [video, *local_episode_sidecars(video)]
        matched.append(
            (
                CrunchyrollMediaGroup(
                    folder=video.parent,
                    stem=video.stem,
                    season=position[0],
                    episode=position[1],
                    files=files,
                ),
                record,
            )
        )
    return sorted(matched, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def crunchyroll_subtitle_language(path: Path, video_stem: str) -> str:
    suffix_text = path.name[len(video_stem):]
    match = re.match(r"[._ -]([a-z]{2,3}(?:-[a-z]{2})?)[._ -]", suffix_text, re.IGNORECASE)
    return match.group(1).casefold() if match else "und"


def crunchyroll_subtitle_content(path: Path) -> tuple[str, int]:
    """Read a text subtitle and count cues without assuming its role from its filename."""
    try:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return "", 0
    cue_count = len(
        re.findall(
            r"(?m)^\s*(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3}\s+-->",
            content,
        )
    )
    if not cue_count and path.suffix.casefold() in {".ass", ".ssa"}:
        cue_count = len(re.findall(r"(?mi)^Dialogue\s*:", content))
    return content, cue_count


def crunchyroll_subtitle_role(path: Path, sibling_cue_counts: list[int] | None = None) -> str:
    """Infer Jellyfin's forced/CC flags only when the subtitle content proves the role."""
    content, cue_count = crunchyroll_subtitle_content(path)
    larger_sibling = max(sibling_cue_counts or [0])
    if 0 < cue_count <= 10 and len(content) <= 5000 and larger_sibling >= max(20, cue_count * 5):
        return "forced"
    if re.search(r"(?m)^\s*(?:<[^>]+>)*\[[^]\r\n]{2,80}\]", content):
        return "cc"
    return ""


def prepare_crunchyroll_media_group(
    meta: Metadata,
    group: CrunchyrollMediaGroup,
    settings: dict[str, Any],
    explicit_show_folder: Path | None = None,
) -> CrunchyrollMediaGroup:
    rename = bool(settings.get("crunchyroll_series_rename_enabled", True))
    organize = bool(settings.get("crunchyroll_series_organize_enabled", True))
    if not (rename or organize):
        return group
    if organize and explicit_show_folder is None:
        group = migrate_crunchyroll_series_folder(group, meta)
    season_folder = f"S{group.season:02d}"
    destination = (
        (explicit_show_folder or crunchyroll_show_folder(group.folder, meta)) / season_folder
        if organize
        else group.folder
    )
    base = crunchyroll_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    subtitle_extensions = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
    subtitle_languages = {
        source: crunchyroll_subtitle_language(source, group.stem)
        for source in group.files
        if source.suffix.casefold() in subtitle_extensions
    }
    subtitle_cue_counts = {
        source: crunchyroll_subtitle_content(source)[1]
        for source in subtitle_languages
    }
    discarded_subtitles: list[Path] = []
    for source in group.files:
        if source.suffix.casefold() in subtitle_extensions and rename:
            language = subtitle_languages[source]
            sibling_cue_counts = [
                count
                for sibling, count in subtitle_cue_counts.items()
                if sibling != source and subtitle_languages[sibling] == language
            ]
            role = crunchyroll_subtitle_role(source, sibling_cue_counts)
            if role == "forced":
                discarded_subtitles.append(source)
                continue
            subtitle_label = ".".join(value for value in (language, role) if value)
            target = destination / f"{base}.{subtitle_label}{source.suffix}"
            duplicate_number = 2
            while target in used:
                target = destination / f"{base}.{subtitle_label}.{duplicate_number:02d}{source.suffix}"
                duplicate_number += 1
        else:
            target = destination / f"{base}{source.name[len(group.stem):]}"
        if target.exists() and target not in group.files:
            raise FileExistsError(f"Crunchyroll rename target already exists: {target}")
        used.add(target)
        targets.append((source, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        if source == target:
            temporary.append((source, target))
            continue
        temp = source.with_name(f".crunchyroll-rename-{index}-{source.name}")
        source.rename(temp)
        temporary.append((temp, target))
    for temporary_path, target in temporary:
        if temporary_path != target:
            temporary_path.rename(target)
    for discarded in discarded_subtitles:
        if discarded.exists():
            discarded.unlink()
    final_files = [target for _source, target in targets]
    video = next((path for path in final_files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return CrunchyrollMediaGroup(
        folder=destination,
        stem=video.stem if video else base,
        season=group.season,
        episode=group.episode,
        files=final_files,
    )


def migrate_crunchyroll_series_folder(
    group: CrunchyrollMediaGroup, meta: Metadata
) -> CrunchyrollMediaGroup:
    """Atomically rename a legacy or stale year-range series root before organizing an episode."""
    folder = group.folder.resolve()
    root = folder.parent if re.fullmatch(r"S\d{1,2}", folder.name, re.IGNORECASE) else folder
    title = safe_filename(meta.show_title or meta.title)
    root_title = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(root_title) != normalize_match_key(title):
        return group
    desired = root.parent / crunchyroll_series_folder_name(meta)
    if desired == root:
        return group
    if desired.exists():
        raise FileExistsError(f"Crunchyroll series folder already exists: {desired}")
    relative_folder = folder.relative_to(root)
    relative_files = [path.resolve().relative_to(root) for path in group.files]
    root.rename(desired)
    return CrunchyrollMediaGroup(
        folder=desired / relative_folder,
        stem=group.stem,
        season=group.season,
        episode=group.episode,
        files=[desired / path for path in relative_files],
    )


def crunchyroll_art_target(folder: Path, artwork_type: str, url: str) -> Path:
    extension = image_extension_from_url(url) or (".png" if artwork_type == "logo" else ".jpg")
    return folder / f"{artwork_type}{extension}"


def save_crunchyroll_show_art(meta: Metadata, folder: Path) -> list[Path]:
    saved: list[Path] = []
    for artwork_type, url in (
        ("poster", meta.poster_url),
        ("backdrop", meta.fanart_url),
        ("logo", meta.logo_url),
    ):
        if not clean_text(url):
            continue
        target = crunchyroll_art_target(folder, artwork_type, url)
        if target.exists():
            continue
        path = download_binary(url, target)
        if path:
            if artwork_type == "logo" and isinstance(path, Path):
                path = normalize_provider_logo_file(path)
            saved.append(path)
    return saved


def crunchyroll_show_folder(folder: Path, meta: Metadata) -> Path:
    resolved_folder = folder.resolve()
    root = (
        resolved_folder.parent
        if re.fullmatch(r"S\d{1,2}", resolved_folder.name, re.IGNORECASE)
        else resolved_folder
    )
    show_title = safe_filename(meta.show_title or meta.title)
    show_name = crunchyroll_series_folder_name(meta)
    if normalize_match_key(root.name) == normalize_match_key(show_name):
        return root
    legacy_name = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(legacy_name) == normalize_match_key(show_title):
        return root.parent / show_name
    return root / show_name


def crunchyroll_series_folder_name(meta: Metadata) -> str:
    title = safe_filename(meta.show_title or meta.title)
    start = clean_text(meta.series_start_year)
    end = clean_text(meta.series_end_year)
    if not start.isdigit():
        return title
    if meta.series_is_current:
        years = f"{start}-"
    elif not end or end == start:
        years = start
    else:
        years = f"{start}-{end}"
    return safe_filename(f"{title} ({years})")


def crunchyroll_series_id(meta: Metadata) -> str:
    values = meta.extra_fields.get("Crunchyroll series ID", [])
    return clean_text(values[0]) if values else ""


def ensure_crunchyroll_series_bundle(episode_meta: Metadata, show_folder: Path) -> list[Path]:
    """Ensure an episode never stands without its linked show NFO and artwork."""
    show_folder.mkdir(parents=True, exist_ok=True)
    tvshow_nfo = show_folder / "tvshow.nfo"
    if tvshow_nfo.exists():
        return save_crunchyroll_show_art(episode_meta, show_folder)

    series_item = episode_meta.series_metadata
    if not series_item:
        series_id = crunchyroll_series_id(episode_meta)
        if not series_id:
            raise ValueError("Crunchyroll episode metadata did not include its linked series ID.")
        series_url = crunchyroll.canonical_series_url(series_id, "")
        series_item = crunchyroll.extract_series_metadata(
            series_id,
            series_url,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    series_meta = metadata_from_provider_dict(
        series_item,
        detail_link=clean_text(series_item.get("source_url")),
    )
    if series_meta.media_kind.casefold() != "series" or not series_meta.plot:
        raise ValueError("Crunchyroll linked series metadata was incomplete; episode metadata was not saved.")
    return save_metadata_bundle_to_location(series_meta, show_folder, "tvshow", skip_existing=True)


def save_crunchyroll_series_trailer(meta: Metadata, show_folder: Path) -> list[Path]:
    """Save one series trailer last, preferring any URL supplied directly by Crunchyroll."""
    trailer_dir = show_folder / "trailers"
    if trailer_dir.exists() and any(
        path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS
        for path in trailer_dir.iterdir()
    ):
        return []
    trailer_url = clean_text(meta.trailer_url)
    youtube_fallback = False
    if not trailer_url:
        match = crunchyroll.find_official_youtube_trailer(meta.show_title or meta.title)
        trailer_url = clean_text(match.get("url"))
        youtube_fallback = bool(trailer_url)
    if not trailer_url:
        return []
    trailer_dir.mkdir(parents=True, exist_ok=True)
    target = trailer_dir / "trailer.mp4"
    if youtube_fallback or is_youtube_url(trailer_url):
        trailer = download_youtube_trailer(trailer_url, target)
    else:
        trailer = download_binary(trailer_url, target)
    if trailer:
        print(f"Crunchyroll series trailer saved to {trailer}")
        return [trailer]
    return []


def is_youtube_url(url: str) -> bool:
    host = urllib.parse.urlparse(clean_text(url)).hostname or ""
    return host.casefold() in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def download_youtube_trailer(url: str, target: Path) -> Path | None:
    """Download a public YouTube trailer in a Jellyfin-friendly MP4 container."""
    with tempfile.TemporaryDirectory(prefix=".trailer-download-", dir=target.parent) as temporary_directory:
        temporary_template = Path(temporary_directory) / "trailer.%(ext)s"
        command = [
            "yt-dlp",
            "--no-playlist",
            "--no-overwrites",
            "--no-warnings",
            *youtube_js_runtime_args(),
            "--extractor-args",
            "youtube:player_client=web_embedded",
            "--merge-output-format",
            "mp4",
            "--format",
            "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]/best[height<=1080]",
            "--output",
            str(temporary_template),
            url,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=900,
            )
        except FileNotFoundError:
            print("Crunchyroll trailer skipped: yt-dlp is not installed.")
            return None
        except subprocess.TimeoutExpired:
            print("Crunchyroll trailer skipped: the YouTube download timed out.")
            return None
        candidates = sorted(
            path
            for path in Path(temporary_directory).iterdir()
            if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS and path.stat().st_size
        )
        if result.returncode != 0:
            detail = clean_text(result.stderr).splitlines()
            suffix = f" {detail[-1]}" if detail else ""
            print(f"Crunchyroll trailer skipped: yt-dlp failed.{suffix}")
            return None
        if len(candidates) != 1 or target.exists():
            print("Crunchyroll trailer skipped: yt-dlp did not produce one unambiguous video file.")
            return None
        candidates[0].rename(target)
    return target


def youtube_js_runtime_args() -> list[str]:
    """Enable an installed yt-dlp JavaScript runtime; Deno is enabled by default."""
    if shutil.which("deno"):
        return []
    for executable, runtime_name in (("node", "node"), ("qjs", "quickjs"), ("bun", "bun")):
        runtime_path = shutil.which(executable)
        if runtime_path:
            return ["--js-runtimes", f"{runtime_name}:{runtime_path}"]
    return []


def save_crunchyroll_series_metadata(
    meta: Metadata,
    settings: dict[str, Any],
    explicit_folder: str = "",
    skip_existing: bool = False,
) -> list[Path] | None:
    if not crunchyroll_series_enabled(meta, settings, explicit_folder=explicit_folder):
        return None
    matches = crunchyroll_media_groups(meta, settings, explicit_folder=explicit_folder)
    if not matches:
        return None
    saved: list[Path] = []
    artwork_saved_for: set[Path] = set()
    trailer_meta_for: dict[Path, Metadata] = {}
    explicit_show_folder = explicit_series_show_folder(explicit_folder, meta, crunchyroll_series_folder_name)
    source_folders = {group.folder for group, _record in matches}
    for group, record in matches:
        episode_id = clean_text(record.get("id"))
        if (
            meta.media_kind.casefold() == "episode"
            and meta.season_number == str(group.season)
            and meta.episode_number == str(group.episode)
        ):
            episode_meta = meta
        elif episode_id:
            episode_url = clean_text(record.get("url")) or crunchyroll.canonical_episode_url(episode_id, "")
            episode_meta = metadata_from_provider_dict(
                crunchyroll.extract_episode_metadata(episode_id, episode_url, timeout=HTTP_TIMEOUT_SECONDS),
                detail_link=episode_url,
            )
        else:
            continue
        episode_meta.media_kind = "episode"
        episode_meta.show_title = meta.show_title or meta.title
        episode_meta.season_number = str(group.season)
        episode_meta.episode_number = str(group.episode)
        prepared = prepare_crunchyroll_media_group(
            episode_meta, group, settings, explicit_show_folder=explicit_show_folder
        )
        show_folder = explicit_show_folder or crunchyroll_show_folder(prepared.folder, episode_meta)
        if show_folder not in artwork_saved_for:
            saved.extend(ensure_crunchyroll_series_bundle(episode_meta, show_folder))
            artwork_saved_for.add(show_folder)
        trailer_meta_for[show_folder] = episode_meta
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            continue
        nfo = video.with_suffix(".nfo")
        if not (skip_existing and nfo.exists()):
            nfo.write_text(build_nfo(episode_meta), encoding="utf-8")
            saved.append(nfo)
        thumb_extension = image_extension_from_url(episode_meta.thumb_url) or ".jpg"
        thumb = video.with_name(f"{video.stem}-thumb{thumb_extension}")
        if episode_meta.thumb_url and not thumb.exists():
            downloaded = download_binary(episode_meta.thumb_url, thumb)
            if downloaded:
                saved.append(downloaded)
    for show_folder, episode_meta in trailer_meta_for.items():
        saved.extend(save_crunchyroll_series_trailer(episode_meta, show_folder))
    cleanup_empty_provider_source_folders(source_folders, explicit_show_folder, crunchyroll.NAME)
    print(f"Crunchyroll series mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def disneyplus_series_enabled(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> bool:
    return (
        meta.source_site == disneyplus.NAME
        and meta.media_kind.casefold() in {"series", "episode"}
        and bool(meta.series_episodes)
        and bool(settings.get("disneyplus_series_metadata_enabled", True))
        and bool(explicit_folder or media_search_roots(settings))
    )


def disneyplus_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[DisneyPlusMediaGroup, dict[str, Any]]]:
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    guide = {
        (int(record["season"]), int(record["episode"])): record
        for record in records
        if clean_text(record.get("season")).isdigit() and clean_text(record.get("episode")).isdigit()
    }
    roots = [Path(explicit_folder).expanduser().resolve()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
            continue
        for folder_text, _dirs, filenames in os.walk(root):
            candidates.extend(
                Path(folder_text) / filename
                for filename in filenames
                if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS
            )
    wanted_title = normalize_match_key(meta.show_title or meta.title)
    direct_position = None
    if meta.media_kind.casefold() == "episode" and meta.season_number.isdigit() and meta.episode_number.isdigit():
        direct_position = (int(meta.season_number), int(meta.episode_number))
    matched: list[tuple[DisneyPlusMediaGroup, dict[str, Any]]] = []
    claimed: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        path_key = normalize_match_key(str(video))
        if not explicit_folder and wanted_title not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        id_matches = [
            record for record in records
            if clean_text(record.get("id")) and normalize_match_key(record["id"]) in stem_key
        ]
        if len(id_matches) == 1:
            position = (int(id_matches[0]["season"]), int(id_matches[0]["episode"]))
        elif explicit_folder and len(candidates) == 1 and direct_position:
            position = direct_position
        else:
            position = paramountplus_episode_position(f"{video.stem} {video.parent.name}")
        record = guide.get(position) if position else None
        if not (position and record) or position in claimed:
            continue
        claimed.add(position)
        files = [video, *local_episode_sidecars(video)]
        matched.append((DisneyPlusMediaGroup(video.parent, video.stem, *position, files), record))
    return sorted(matched, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def disneyplus_target_base(meta: Metadata, group: DisneyPlusMediaGroup | None = None) -> str:
    season = group.season if group else int(meta.season_number or 1)
    episode = group.episode if group else int(meta.episode_number or 0)
    base = f"S{season:02d}E{episode:02d} {meta.show_title or meta.title}"
    if meta.episode_title:
        base += f" - {meta.episode_title}"
    return safe_filename(base)


def disneyplus_series_folder_name(meta: Metadata) -> str:
    title = safe_filename(meta.show_title or meta.title)
    start = clean_text(meta.series_start_year)
    end = clean_text(meta.series_end_year)
    if not start.isdigit():
        return title
    if meta.series_is_current:
        years = f"{start}-"
    elif not end or end == start:
        years = start
    else:
        years = f"{start}-{end}"
    return safe_filename(f"{title} ({years})")


def disneyplus_show_folder(folder: Path, meta: Metadata) -> Path:
    resolved = folder.resolve()
    root = resolved.parent if re.fullmatch(r"S\d{1,2}", resolved.name, re.I) else resolved
    desired_name = disneyplus_series_folder_name(meta)
    if normalize_match_key(root.name) == normalize_match_key(desired_name):
        return root
    legacy_name = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(legacy_name) == normalize_match_key(safe_filename(meta.show_title or meta.title)):
        return root.parent / desired_name
    return root / desired_name


def migrate_disneyplus_series_folder(group: DisneyPlusMediaGroup, meta: Metadata) -> DisneyPlusMediaGroup:
    folder = group.folder.resolve()
    root = folder.parent if re.fullmatch(r"S\d{1,2}", folder.name, re.I) else folder
    title = safe_filename(meta.show_title or meta.title)
    root_title = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(root_title) != normalize_match_key(title):
        return group
    desired = root.parent / disneyplus_series_folder_name(meta)
    if desired == root:
        return group
    if desired.exists():
        raise FileExistsError(f"Disney+ series folder already exists: {desired}")
    relative_folder = folder.relative_to(root)
    relative_files = [path.resolve().relative_to(root) for path in group.files]
    root.rename(desired)
    return DisneyPlusMediaGroup(
        desired / relative_folder, group.stem, group.season, group.episode,
        [desired / path for path in relative_files],
    )


def prepare_disneyplus_media_group(
    meta: Metadata,
    group: DisneyPlusMediaGroup,
    settings: dict[str, Any],
    explicit_show_folder: Path | None = None,
) -> DisneyPlusMediaGroup:
    rename = bool(settings.get("disneyplus_series_rename_enabled", True))
    organize = bool(settings.get("disneyplus_series_organize_enabled", True))
    if not (rename or organize):
        return group
    if organize and explicit_show_folder is None:
        group = migrate_disneyplus_series_folder(group, meta)
    destination = (
        (explicit_show_folder or disneyplus_show_folder(group.folder, meta)) / f"S{group.season:02d}"
        if organize else group.folder
    )
    base = disneyplus_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    for source in group.files:
        suffix = source.name[len(group.stem):]
        target = destination / ((base + suffix) if rename else source.name)
        if target in used or (target.exists() and target not in group.files):
            raise FileExistsError(f"Disney+ rename target already exists: {target}")
        used.add(target)
        targets.append((source, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        if source == target:
            temporary.append((source, target))
            continue
        temp = source.with_name(f".disneyplus-rename-{index}-{source.name}")
        source.rename(temp)
        temporary.append((temp, target))
    for temporary_path, target in temporary:
        if temporary_path != target:
            temporary_path.rename(target)
    final_files = [target for _source, target in targets]
    video = next((path for path in final_files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return DisneyPlusMediaGroup(destination, video.stem if video else base, group.season, group.episode, final_files)


def disneyplus_episode_metadata(meta: Metadata, record: dict[str, Any]) -> Metadata:
    episode_id = clean_text(record.get("id"))
    episode = Metadata(
        source_url=clean_text(record.get("url")) or meta.source_url,
        detail_link=clean_text(record.get("url")), source_site=meta.source_site, media_kind="episode",
        title=meta.title, show_title=clean_text(record.get("show_title")) or meta.title,
        season_number=clean_text(record.get("season")), episode_number=clean_text(record.get("episode")),
        episode_title=clean_text(record.get("title")), outline=clean_text(record.get("description")),
        plot=clean_text(record.get("description")), year=meta.year,
        series_start_year=meta.series_start_year, series_end_year=meta.series_end_year,
        series_is_current=meta.series_is_current, content_rating=meta.content_rating,
        poster_url=meta.poster_url, fanart_url=meta.fanart_url, logo_url=meta.logo_url,
        thumb_url=clean_text(record.get("image")), trailer_url=meta.trailer_url,
        genres=list(meta.genres), tags=list(meta.tags), studios=list(meta.studios),
        directors=list(meta.directors), actors=list(meta.actors),
        unique_ids={"disneyplus": episode_id} if episode_id else {}, series_metadata=meta.series_metadata,
    )
    for label in ("Disney+ entity ID", "Season count", "Accessibility"):
        for value in meta.extra_fields.get(label, []):
            episode.add_extra(label, value)
    episode.add_extra("Disney+ episode ID", episode_id)
    episode.add_extra("Episode page", episode.detail_link)
    return episode


def save_disneyplus_show_art(meta: Metadata, folder: Path, base_name: str = "") -> list[Path]:
    saved: list[Path] = []
    for artwork_type, url in (("backdrop", meta.fanart_url), ("thumb", meta.thumb_url), ("logo", meta.logo_url)):
        if not clean_text(url):
            continue
        extension = ".png" if artwork_type == "logo" else (image_extension_from_url(url) or ".jpg")
        name = f"{base_name}-{artwork_type}" if base_name else artwork_type
        target = folder / f"{name}{extension}"
        if target.exists():
            continue
        path = download_binary(url, target)
        if path:
            if artwork_type == "logo" and isinstance(path, Path):
                path = normalize_provider_logo_file(path)
            saved.append(path)
    return saved


def ensure_disneyplus_series_bundle(meta: Metadata, show_folder: Path) -> list[Path]:
    show_folder.mkdir(parents=True, exist_ok=True)
    if meta.media_kind.casefold() == "series":
        series_meta = meta
    elif meta.series_metadata:
        series_meta = metadata_from_provider_dict(meta.series_metadata, detail_link=clean_text(meta.series_metadata.get("source_url")))
    else:
        raise ValueError("Disney+ episode metadata did not include its linked series metadata.")
    if series_meta.media_kind.casefold() != "series" or not series_meta.plot:
        raise ValueError("Disney+ linked series metadata was incomplete; episode metadata was not saved.")
    saved: list[Path] = []
    nfo = show_folder / "tvshow.nfo"
    if not nfo.exists():
        nfo.write_text(build_nfo(series_meta), encoding="utf-8")
        saved.append(nfo)
    saved.extend(save_disneyplus_show_art(series_meta, show_folder))
    return saved


def save_disneyplus_series_trailer(meta: Metadata, show_folder: Path) -> list[Path]:
    trailer_dir = show_folder / "trailers"
    if trailer_dir.exists() and any(path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS for path in trailer_dir.iterdir()):
        return []
    if not clean_text(meta.trailer_url):
        return []
    trailer_dir.mkdir(parents=True, exist_ok=True)
    trailer = download_binary(meta.trailer_url, trailer_dir / "trailer.mp4")
    return [trailer] if trailer else []


def save_disneyplus_series_metadata(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = "", skip_existing: bool = False
) -> list[Path] | None:
    if not disneyplus_series_enabled(meta, settings, explicit_folder):
        return None
    matches = disneyplus_media_groups(meta, settings, explicit_folder)
    if not matches:
        return None
    saved: list[Path] = []
    bundled: set[Path] = set()
    trailer_meta_for: dict[Path, Metadata] = {}
    explicit_show_folder = explicit_series_show_folder(explicit_folder, meta, disneyplus_series_folder_name)
    source_folders = {group.folder for group, _record in matches}
    for group, record in matches:
        episode_meta = meta if (
            meta.media_kind.casefold() == "episode"
            and meta.season_number == str(group.season)
            and meta.episode_number == str(group.episode)
        ) else disneyplus_episode_metadata(meta, record)
        episode_meta.season_number = str(group.season)
        episode_meta.episode_number = str(group.episode)
        prepared = prepare_disneyplus_media_group(
            episode_meta, group, settings, explicit_show_folder=explicit_show_folder
        )
        show_folder = explicit_show_folder or disneyplus_show_folder(prepared.folder, episode_meta)
        if show_folder not in bundled:
            saved.extend(ensure_disneyplus_series_bundle(meta if meta.media_kind.casefold() == "series" else episode_meta, show_folder))
            bundled.add(show_folder)
        trailer_meta_for[show_folder] = meta if meta.media_kind.casefold() == "series" else episode_meta
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            continue
        nfo = video.with_suffix(".nfo")
        if not (skip_existing and nfo.exists()):
            nfo.write_text(build_nfo(episode_meta), encoding="utf-8")
            saved.append(nfo)
        extension = image_extension_from_url(episode_meta.thumb_url) or ".jpg"
        thumb = video.with_name(f"{video.stem}-thumb{extension}")
        if episode_meta.thumb_url and not thumb.exists():
            path = download_binary(episode_meta.thumb_url, thumb)
            if path:
                saved.append(path)
    for show_folder, trailer_meta in trailer_meta_for.items():
        series_meta = metadata_from_provider_dict(trailer_meta.series_metadata) if trailer_meta.series_metadata else trailer_meta
        saved.extend(save_disneyplus_series_trailer(series_meta, show_folder))
    cleanup_empty_provider_source_folders(source_folders, explicit_show_folder, disneyplus.NAME)
    print(f"Disney+ series mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def hbomax_series_enabled(meta: Metadata, settings: dict[str, Any], explicit_folder: str = "") -> bool:
    return (
        meta.source_site == hbomax.NAME
        and meta.media_kind.casefold() in {"series", "episode"}
        and bool(meta.series_episodes)
        and bool(settings.get("hbomax_series_metadata_enabled", True))
        and bool(explicit_folder or media_search_roots(settings))
    )


def hbomax_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[HBOMaxMediaGroup, dict[str, Any]]]:
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    guide = {
        (int(record["season"]), int(record["episode"])): record
        for record in records
        if clean_text(record.get("season")).isdigit() and clean_text(record.get("episode")).isdigit()
    }
    roots = [Path(explicit_folder).expanduser().resolve()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
        elif root.is_dir():
            for folder_text, _dirs, filenames in os.walk(root):
                candidates.extend(Path(folder_text) / name for name in filenames if Path(name).suffix.casefold() in VIDEO_EXTENSIONS)
    direct = None
    if meta.media_kind.casefold() == "episode" and meta.season_number.isdigit() and meta.episode_number.isdigit():
        direct = (int(meta.season_number), int(meta.episode_number))
    wanted_title = normalize_match_key(meta.show_title or meta.title)
    matched: list[tuple[HBOMaxMediaGroup, dict[str, Any]]] = []
    claimed: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        path_key = normalize_match_key(str(video))
        if not explicit_folder and wanted_title not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        id_matches = [
            record for record in records
            if clean_text(record.get("id")) and normalize_match_key(record["id"]) in stem_key
        ]
        if len(id_matches) == 1:
            position = (int(id_matches[0]["season"]), int(id_matches[0]["episode"]))
        elif explicit_folder and len(candidates) == 1 and direct:
            position = direct
        else:
            position = paramountplus_episode_position(f"{video.stem} {video.parent.name}")
        record = guide.get(position) if position else None
        if not record or position in claimed:
            continue
        claimed.add(position)
        files = [video]
        for sidecar in video.parent.iterdir():
            if (
                sidecar.is_file()
                and (
                    (
                        sidecar.suffix.casefold() in {".srt", ".vtt", ".ass", ".ssa", ".sub", ".nfo"}
                        and (sidecar.stem == video.stem or sidecar.name.startswith(video.stem + "."))
                    )
                    or (
                        sidecar.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}
                        and sidecar.name.startswith(video.stem + "-thumb.")
                    )
                )
            ):
                files.append(sidecar)
        matched.append((HBOMaxMediaGroup(video.parent, video.stem, *position, files), record))
    return sorted(matched, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def hbomax_series_folder_name(meta: Metadata) -> str:
    return crunchyroll_series_folder_name(meta)


def hbomax_target_base(meta: Metadata, group: HBOMaxMediaGroup | None = None) -> str:
    season = group.season if group else int(meta.season_number or 1)
    episode = group.episode if group else int(meta.episode_number or 0)
    value = f"S{season:02d}E{episode:02d} {meta.show_title or meta.title}"
    if meta.episode_title:
        value += f" - {meta.episode_title}"
    return safe_filename(value)


def hbomax_show_folder(folder: Path, meta: Metadata) -> Path:
    resolved = folder.resolve()
    root = resolved.parent if re.fullmatch(r"S\d{1,2}", resolved.name, re.I) else resolved
    desired = hbomax_series_folder_name(meta)
    if normalize_match_key(root.name) == normalize_match_key(desired):
        return root
    title = safe_filename(meta.show_title or meta.title)
    root_title = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(root_title) == normalize_match_key(title):
        return root.parent / desired
    return root / desired


def prepare_hbomax_media_group(
    meta: Metadata,
    group: HBOMaxMediaGroup,
    settings: dict[str, Any],
    explicit_show_folder: Path | None = None,
) -> HBOMaxMediaGroup:
    rename = bool(settings.get("hbomax_series_rename_enabled", True))
    organize = bool(settings.get("hbomax_series_organize_enabled", True))
    if not (rename or organize):
        return group
    destination = (
        (explicit_show_folder or hbomax_show_folder(group.folder, meta)) / f"S{group.season:02d}"
        if organize else group.folder
    )
    base = hbomax_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    for source in group.files:
        suffix = source.name[len(group.stem):]
        target = destination / ((base + suffix) if rename else source.name)
        if target in used or (target.exists() and target not in group.files):
            raise FileExistsError(f"HBO Max rename target already exists: {target}")
        used.add(target); targets.append((source, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        if source == target:
            temporary.append((source, target)); continue
        temp = source.with_name(f".hbomax-rename-{index}-{source.name}")
        source.rename(temp); temporary.append((temp, target))
    for temp, target in temporary:
        if temp != target:
            temp.rename(target)
    files = [target for _source, target in targets]
    video = next((path for path in files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return HBOMaxMediaGroup(destination, video.stem if video else base, group.season, group.episode, files)


def hbomax_parent_series_meta(meta: Metadata) -> Metadata:
    if meta.media_kind.casefold() == "series":
        return meta
    if meta.series_metadata:
        return metadata_from_provider_dict(meta.series_metadata, detail_link=clean_text(meta.series_metadata.get("source_url")))
    raise ValueError("HBO Max episode metadata did not include its linked series metadata.")


def hbomax_episode_metadata(meta: Metadata, record: dict[str, Any]) -> Metadata:
    series = hbomax_parent_series_meta(meta)
    episode_id = clean_text(record.get("id"))
    episode = Metadata(
        source_url=clean_text(record.get("url")) or meta.source_url, detail_link=clean_text(record.get("url")),
        source_site=hbomax.NAME, media_kind="episode", title=series.title, show_title=series.title,
        season_number=clean_text(record.get("season")), episode_number=clean_text(record.get("episode")),
        episode_title=clean_text(record.get("title")), outline=clean_text(record.get("outline")),
        plot=clean_text(record.get("description")), date=clean_text(record.get("date")),
        year=clean_text(record.get("year")), runtime_minutes=clean_text(record.get("runtime_minutes")),
        series_start_year=series.series_start_year, series_end_year=series.series_end_year,
        series_is_current=series.series_is_current, content_rating=series.content_rating,
        thumb_url=clean_text(record.get("image")),
        genres=list(series.genres), studios=list(series.studios), tags=list(series.tags),
        unique_ids={"hbomax": episode_id} if episode_id else {}, series_metadata=meta.series_metadata,
    )
    for label, value in (
        ("HBO Max episode ID", episode_id), ("Episode page", record.get("url")),
        ("Availability start", record.get("availability_start")), ("Availability end", record.get("availability_end")),
        ("Audio", record.get("audio")), ("Subtitles", record.get("subtitles")),
    ):
        for item in split_values(value):
            episode.add_extra(label, item)
    return episode


def save_hbomax_show_art(meta: Metadata, folder: Path, base_name: str = "") -> list[Path]:
    saved: list[Path] = []
    for artwork_type, url in (
        ("poster", meta.poster_url), ("backdrop", meta.fanart_url), ("thumb", meta.thumb_url), ("logo", meta.logo_url),
    ):
        if not clean_text(url):
            continue
        extension = ".png" if artwork_type == "logo" else (image_extension_from_url(url) or ".jpg")
        name = f"{base_name}-{artwork_type}" if base_name else artwork_type
        target = folder / f"{name}{extension}"
        if not target.exists():
            path = download_binary(url, target)
            if path:
                if artwork_type == "logo":
                    path = normalize_hbomax_logo_file(path)
                saved.append(path)
    if meta.gallery_urls:
        gallery = folder / "extrafanart"
        for index, url in enumerate(meta.gallery_urls, start=1):
            if clean_text(url):
                gallery.mkdir(parents=True, exist_ok=True)
                path = download_binary(url, gallery / f"fanart-{index:02d}.jpg")
                if path:
                    saved.append(path)
    return saved


def image_file_extension(path: Path) -> str:
    try:
        signature = path.read_bytes()[:16]
    except OSError:
        return ""
    if signature.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if signature.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if signature.startswith(b"RIFF") and signature[8:12] == b"WEBP":
        return ".webp"
    return ""


def normalize_provider_logo_file(path: Path) -> Path:
    """Keep provider logos truthful on disk and prefer Jellyfin's conventional PNG."""
    detected = image_file_extension(path)
    if not detected or detected == ".png":
        return path
    png_target = path.with_suffix(".png")
    source = path.with_name(f".{path.stem}-hbomax-source{detected}")
    path.replace(source)
    executable = shutil.which("sips")
    if executable:
        result = subprocess.run(
            [executable, "-s", "format", "png", str(source), "--out", str(png_target)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and png_target.exists() and image_file_extension(png_target) == ".png":
            source.unlink(missing_ok=True)
            return png_target
        png_target.unlink(missing_ok=True)
    truthful_target = path.with_suffix(detected)
    if truthful_target.exists():
        source.unlink(missing_ok=True)
        return truthful_target
    source.replace(truthful_target)
    return truthful_target


def normalize_paramountplus_image_file(path: Path) -> Path | None:
    """Convert Paramount+ artwork to genuine PNG data or reject the download."""
    detected = image_file_extension(path)
    if detected == ".png":
        png_target = path.with_suffix(".png")
        if png_target != path:
            path.replace(png_target)
        return png_target
    if detected not in {".jpg", ".webp"}:
        path.unlink(missing_ok=True)
        return None

    png_target = path.with_suffix(".png")
    source = path.with_name(f".{path.stem}-paramountplus-source{detected}")
    source.unlink(missing_ok=True)
    path.replace(source)
    executable = shutil.which("sips")
    if executable:
        result = subprocess.run(
            [executable, "-s", "format", "png", str(source), "--out", str(png_target)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and png_target.exists() and image_file_extension(png_target) == ".png":
            source.unlink(missing_ok=True)
            return png_target
        png_target.unlink(missing_ok=True)

    executable = shutil.which("ffmpeg")
    if executable:
        result = subprocess.run(
            [executable, "-y", "-i", str(source), str(png_target)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and png_target.exists() and image_file_extension(png_target) == ".png":
            source.unlink(missing_ok=True)
            return png_target
        png_target.unlink(missing_ok=True)

    source.unlink(missing_ok=True)
    return None


def normalize_hbomax_logo_file(path: Path) -> Path:
    return normalize_provider_logo_file(path)


def ensure_hbomax_series_bundle(meta: Metadata, show_folder: Path) -> list[Path]:
    series = hbomax_parent_series_meta(meta)
    if series.media_kind.casefold() != "series" or not series.plot:
        raise ValueError("HBO Max linked series metadata was incomplete; episode metadata was not saved.")
    show_folder.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    nfo = show_folder / "tvshow.nfo"
    if not nfo.exists():
        nfo.write_text(build_nfo(series), encoding="utf-8"); saved.append(nfo)
    saved.extend(save_hbomax_show_art(series, show_folder))
    return saved


def is_hbomax_public_preview_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    text = (parsed.netloc + parsed.path + "?" + parsed.query).casefold()
    return parsed.path.casefold().endswith((".mp4", ".m3u8", ".mpd")) and (
        "amer-free" in text or "creative" in text or "trailer" in text or "promo" in text
    )


def hbomax_capture_public_preview(page_url: str) -> str:
    if not CHROME_APP_PATH.exists():
        return ""
    with tempfile.TemporaryDirectory(prefix="hbomax-preview-", dir="/private/tmp") as profile:
        process = subprocess.Popen([
            str(CHROME_APP_PATH), "--headless=new", "--disable-gpu", "--disable-extensions",
            "--mute-audio", "--no-first-run", "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required", "--remote-debugging-port=0",
            f"--user-data-dir={profile}", f"--user-agent={USER_AGENT}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active = Path(profile) / "DevToolsActivePort"; deadline = time.time() + 10; port = 0
            while time.time() < deadline and process.poll() is None:
                if active.exists():
                    lines = active.read_text(encoding="utf-8", errors="replace").splitlines()
                    if lines and lines[0].isdigit():
                        port = int(lines[0]); break
                time.sleep(0.1)
            if not port:
                return ""
            request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new", method="PUT")
            with urllib.request.urlopen(request, timeout=5) as response:
                page = json.loads(response.read().decode("utf-8", errors="replace"))
            websocket = AmazonPrimeDevToolsWebSocket(clean_text(page.get("webSocketDebuggerUrl")))
            websocket.connect()
            try:
                for identifier, (method, params) in enumerate((("Network.enable", {}), ("Page.enable", {}), ("Page.navigate", {"url": page_url})), start=1):
                    websocket.send_json({"id": identifier, "method": method, "params": params})
                deadline = time.time() + 30
                next_click = time.time() + 1
                click_identifier = 10
                while time.time() < deadline:
                    if time.time() >= next_click:
                        websocket.send_json({
                            "id": click_identifier,
                            "method": "Runtime.evaluate",
                            "params": {
                                "expression": "(() => { const e = Array.from(document.querySelectorAll('button,a,[role=button]')).find(x => /trailer|tease|preview/i.test(x.innerText || x.ariaLabel || '')); if (e) { e.click(); return true; } return false; })()"
                            },
                        })
                        click_identifier += 1
                        next_click = time.time() + 2
                    message = websocket.recv_json(timeout=1)
                    if not message or message.get("method") not in {"Network.requestWillBeSent", "Network.responseReceived"}:
                        continue
                    kind = "request" if message.get("method") == "Network.requestWillBeSent" else "response"
                    candidate = clean_text(message.get("params", {}).get(kind, {}).get("url"))
                    if is_hbomax_public_preview_url(candidate):
                        return candidate
                return ""
            finally:
                websocket.close()
        except Exception:
            return ""
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)


def save_hbomax_trailer(meta: Metadata, folder: Path) -> list[Path]:
    trailer_dir = folder / "trailers"
    if trailer_dir.exists() and any(path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS for path in trailer_dir.iterdir()):
        return []
    page_url = clean_text(meta.trailer_url) or clean_text(meta.detail_link) or clean_text(meta.source_url)
    if not page_url:
        return []
    direct = page_url if is_hbomax_public_preview_url(page_url) else hbomax_capture_public_preview(page_url)
    if not direct:
        print("HBO Max trailer skipped: no public preview stream could be resolved.")
        return []
    trailer_dir.mkdir(parents=True, exist_ok=True)
    trailer = download_binary(direct, trailer_dir / "trailer.mp4")
    if trailer:
        print(f"HBO Max trailer saved to {trailer}"); return [trailer]
    try:
        trailer_dir.rmdir()
    except OSError:
        pass
    print("HBO Max trailer skipped: the preview was unavailable or protected.")
    return []


def save_hbomax_extra_videos(meta: Metadata, folder: Path) -> list[Path]:
    saved: list[Path] = []
    trailer_page = clean_text(meta.trailer_url)
    used_names: set[str] = set()
    for index, video in enumerate(meta.extra_videos, start=1):
        page_url = clean_text(video.url)
        if not page_url or page_url == trailer_page:
            continue
        direct = page_url if is_hbomax_public_preview_url(page_url) else hbomax_capture_public_preview(page_url)
        if not direct:
            continue
        base = safe_filename(video.title or f"extra-{index:02d}")
        candidate = base
        duplicate = 2
        while candidate.casefold() in used_names:
            candidate = f"{base} ({duplicate})"
            duplicate += 1
        used_names.add(candidate.casefold())
        extra_dir = folder / "Extras" / "Videos"
        extra_dir.mkdir(parents=True, exist_ok=True)
        path = download_binary(direct, extra_dir / f"{candidate}.mp4")
        if path:
            saved.append(path)
        else:
            try:
                extra_dir.rmdir()
                extra_dir.parent.rmdir()
            except OSError:
                pass
    return saved


def save_hbomax_series_metadata(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = "", skip_existing: bool = False
) -> list[Path] | None:
    if not hbomax_series_enabled(meta, settings, explicit_folder):
        return None
    matches = hbomax_media_groups(meta, settings, explicit_folder)
    if not matches:
        return []
    saved: list[Path] = []; bundled: set[Path] = set(); trailer_for: dict[Path, Metadata] = {}
    explicit_show_folder = explicit_series_show_folder(explicit_folder, meta, hbomax_series_folder_name)
    source_folders = {group.folder for group, _record in matches}
    for group, record in matches:
        episode_meta = meta if (
            meta.media_kind.casefold() == "episode" and meta.season_number == str(group.season) and meta.episode_number == str(group.episode)
        ) else hbomax_episode_metadata(meta, record)
        prepared = prepare_hbomax_media_group(
            episode_meta, group, settings, explicit_show_folder=explicit_show_folder
        )
        show_folder = explicit_show_folder or hbomax_show_folder(prepared.folder, episode_meta)
        if show_folder not in bundled:
            saved.extend(ensure_hbomax_series_bundle(meta if meta.media_kind.casefold() == "series" else episode_meta, show_folder)); bundled.add(show_folder)
        trailer_for[show_folder] = hbomax_parent_series_meta(meta if meta.media_kind.casefold() == "series" else episode_meta)
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            continue
        nfo = video.with_suffix(".nfo")
        if not (skip_existing and nfo.exists()):
            nfo.write_text(build_nfo(episode_meta), encoding="utf-8"); saved.append(nfo)
        target = video.with_name(f"{video.stem}-thumb{image_extension_from_url(episode_meta.thumb_url) or '.jpg'}")
        if clean_text(episode_meta.thumb_url) and not target.exists():
            path = download_binary(episode_meta.thumb_url, target)
            if path:
                saved.append(path)
    for folder, series in trailer_for.items():
        saved.extend(save_hbomax_trailer(series, folder))
        saved.extend(save_hbomax_extra_videos(series, folder))
    cleanup_empty_provider_source_folders(source_folders, explicit_show_folder, hbomax.NAME)
    print(f"HBO Max series mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def amazon_prime_series_enabled(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> bool:
    return (
        meta.source_site == amazon.PRIME_NAME
        and meta.media_kind.casefold() in {"series", "episode"}
        and bool(meta.series_episodes)
        and bool(settings.get("amazon_prime_series_metadata_enabled", True))
        and bool(explicit_folder or media_search_roots(settings))
    )


def amazon_prime_match_record(video: Path, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    stem_key = normalize_match_key(video.stem)
    identity_matches = []
    for record in records:
        identities = [record.get("compact_id"), record.get("id"), record.get("asin"), *(record.get("asins") or [])]
        if any(clean_text(value) and normalize_match_key(clean_text(value)) in stem_key for value in identities):
            identity_matches.append(record)
    if len(identity_matches) == 1:
        return identity_matches[0]
    position = paramountplus_episode_position(f"{video.stem} {video.parent.name}")
    if position:
        matches = [
            record for record in records
            if clean_text(record.get("season")).isdigit()
            and clean_text(record.get("episode")).isdigit()
            and (int(record["season"]), int(record["episode"])) == position
        ]
        if len(matches) == 1:
            return matches[0]
    title_matches = [
        record for record in records
        if len(normalize_match_key(clean_text(record.get("title")))) >= 4
        and normalize_match_key(clean_text(record.get("title"))) in stem_key
    ]
    return title_matches[0] if len(title_matches) == 1 else None


def amazon_prime_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[AmazonPrimeMediaGroup, dict[str, Any]]]:
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    roots = [Path(explicit_folder).expanduser().resolve()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
            continue
        for folder_text, _dirs, filenames in os.walk(root):
            candidates.extend(
                Path(folder_text) / filename
                for filename in filenames
                if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS
            )
    direct = None
    if meta.media_kind.casefold() == "episode":
        direct = next((
            record for record in records
            if clean_text(record.get("season")) == meta.season_number
            and clean_text(record.get("episode")) == meta.episode_number
        ), None)
    title_key = normalize_match_key(meta.show_title or meta.title)
    output: list[tuple[AmazonPrimeMediaGroup, dict[str, Any]]] = []
    claimed_records: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        path_key = normalize_match_key(str(video))
        if not explicit_folder and title_key not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        identity_matches = [
            record for record in records
            if any(
                clean_text(value) and normalize_match_key(clean_text(value)) in stem_key
                for value in (record.get("compact_id"), record.get("id"), record.get("asin"), *(record.get("asins") or []))
            )
        ]
        if explicit_folder and len(candidates) == 1 and direct:
            record = direct
        elif len(identity_matches) == 1:
            record = identity_matches[0]
        else:
            record = amazon_prime_match_record(video, records)
        season = clean_text(record.get("season")) if record else ""
        episode = clean_text(record.get("episode")) if record else ""
        if not (record and season.isdigit() and episode.isdigit()):
            continue
        identity = (int(season), int(episode))
        if identity in claimed_records:
            continue
        claimed_records.add(identity)
        files = [video, *local_episode_sidecars(video)]
        output.append((AmazonPrimeMediaGroup(video.parent, video.stem, int(season), int(episode), files), record))
    return sorted(output, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def amazon_prime_series_folder_name(meta: Metadata) -> str:
    return crunchyroll_series_folder_name(meta)


def amazon_prime_target_base(meta: Metadata, group: AmazonPrimeMediaGroup | None = None) -> str:
    season = group.season if group else int(meta.season_number or 1)
    episode = group.episode if group else int(meta.episode_number or 0)
    value = f"S{season:02d}E{episode:02d} {meta.show_title or meta.title}"
    if meta.episode_title:
        value += f" - {meta.episode_title}"
    return safe_filename(value)


def amazon_prime_show_folder(folder: Path, meta: Metadata) -> Path:
    resolved = folder.resolve()
    root = resolved.parent if re.fullmatch(r"S\d{1,2}", resolved.name, re.I) else resolved
    title = safe_filename(meta.show_title or meta.title)
    desired = amazon_prime_series_folder_name(meta)
    if normalize_match_key(root.name) == normalize_match_key(desired):
        return root
    root_title = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(root_title) == normalize_match_key(title):
        return root.parent / desired
    return root / desired


def migrate_amazon_prime_series_folder(group: AmazonPrimeMediaGroup, meta: Metadata) -> AmazonPrimeMediaGroup:
    folder = group.folder.resolve()
    root = folder.parent if re.fullmatch(r"S\d{1,2}", folder.name, re.I) else folder
    title = safe_filename(meta.show_title or meta.title)
    root_title = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(root_title) != normalize_match_key(title):
        return group
    desired = root.parent / amazon_prime_series_folder_name(meta)
    if desired == root:
        return group
    if desired.exists():
        raise FileExistsError(f"Amazon Prime Video series folder already exists: {desired}")
    relative_folder = folder.relative_to(root)
    relative_files = [path.resolve().relative_to(root) for path in group.files]
    root.rename(desired)
    return AmazonPrimeMediaGroup(
        desired / relative_folder, group.stem, group.season, group.episode,
        [desired / path for path in relative_files],
    )


def prepare_amazon_prime_media_group(
    meta: Metadata,
    group: AmazonPrimeMediaGroup,
    settings: dict[str, Any],
    explicit_show_folder: Path | None = None,
) -> AmazonPrimeMediaGroup:
    rename = bool(settings.get("amazon_prime_series_rename_enabled", True))
    organize = bool(settings.get("amazon_prime_series_organize_enabled", True))
    if not (rename or organize):
        return group
    if organize and explicit_show_folder is None:
        group = migrate_amazon_prime_series_folder(group, meta)
    destination = (
        (explicit_show_folder or amazon_prime_show_folder(group.folder, meta)) / f"S{group.season:02d}"
        if organize else group.folder
    )
    base = amazon_prime_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    for source in group.files:
        suffix = source.name[len(group.stem):]
        target = destination / ((base + suffix) if rename else source.name)
        if target in used or (target.exists() and target not in group.files):
            raise FileExistsError(f"Amazon Prime Video rename target already exists: {target}")
        used.add(target)
        targets.append((source, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        if source == target:
            temporary.append((source, target))
            continue
        temp = source.with_name(f".amazon-prime-rename-{index}-{source.name}")
        source.rename(temp)
        temporary.append((temp, target))
    for temp, target in temporary:
        if temp != target:
            temp.rename(target)
    final_files = [target for _source, target in targets]
    video = next((path for path in final_files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return AmazonPrimeMediaGroup(destination, video.stem if video else base, group.season, group.episode, final_files)


def amazon_prime_parent_series_meta(meta: Metadata) -> Metadata:
    if meta.media_kind.casefold() == "series":
        return meta
    if meta.series_metadata:
        return metadata_from_provider_dict(meta.series_metadata, detail_link=clean_text(meta.series_metadata.get("source_url")))
    raise ValueError("Amazon Prime Video episode metadata did not include its linked series metadata.")


def amazon_prime_episode_metadata(meta: Metadata, record: dict[str, Any]) -> Metadata:
    series = amazon_prime_parent_series_meta(meta)
    compact_id = clean_text(record.get("compact_id"))
    gti = clean_text(record.get("id"))
    asin = clean_text(record.get("asin"))
    episode = Metadata(
        source_url=clean_text(record.get("url")) or meta.source_url,
        detail_link=clean_text(record.get("url")),
        source_site=amazon.PRIME_NAME,
        media_kind="episode",
        title=series.title,
        show_title=series.title,
        season_number=clean_text(record.get("season")),
        episode_number=clean_text(record.get("episode")),
        episode_title=clean_text(record.get("title")),
        outline=clean_text(record.get("description")),
        plot=clean_text(record.get("description")),
        date=clean_text(record.get("date")),
        year=clean_text(record.get("year")),
        series_start_year=series.series_start_year,
        series_end_year=series.series_end_year,
        series_is_current=series.series_is_current,
        runtime_minutes=clean_text(record.get("runtime_minutes")),
        content_rating=series.content_rating,
        thumb_url=clean_text(record.get("image")),
        genres=list(series.genres), tags=list(series.tags), studios=list(series.studios),
        unique_ids={key: value for key, value in (("primevideo", compact_id), ("primevideo-gti", gti), ("amazon", asin)) if value},
        series_metadata=meta.series_metadata,
    )
    for label, value in (
        ("Prime Video ID", compact_id), ("Prime Video GTI", gti), ("Amazon ASIN", asin),
        ("Runtime seconds", record.get("duration_seconds")), ("Audio", record.get("audio")),
        ("Subtitles", record.get("subtitles")),
        ("Accessibility and playback features", record.get("features")),
    ):
        for item in split_values(value):
            episode.add_extra(label, item)
    return episode


def save_amazon_prime_show_art(meta: Metadata, folder: Path) -> list[Path]:
    saved: list[Path] = []
    for artwork_type, url in (("backdrop", meta.fanart_url), ("thumb", meta.thumb_url), ("logo", meta.logo_url)):
        if not clean_text(url):
            continue
        extension = image_extension_from_url(url) or (".png" if artwork_type == "logo" else ".jpg")
        target = folder / f"{artwork_type}{extension}"
        if target.exists() or (artwork_type == "logo" and any(folder.glob("logo.*"))):
            continue
        path = download_binary(url, target)
        if path:
            if artwork_type == "logo" and isinstance(path, Path):
                path = normalize_provider_logo_file(path)
            saved.append(path)
    return saved


def amazon_prime_direct_trailer_url_from_html(html_text: str) -> str:
    candidates: list[str] = []
    for match in re.finditer(r'https?://[^"\'<>\\\s]+', html_text):
        value = match.group(0).replace("\\u0026", "&").replace("\\/", "/")
        if urllib.parse.urlparse(value).path.casefold().endswith((".mp4", ".m3u8", ".mpd")):
            candidates.append(value)
    return next((url for url in candidates if urllib.parse.urlparse(url).path.casefold().endswith(".mp4")), candidates[0] if candidates else "")


def amazon_prime_capture_trailer_url(trailer_page_url: str) -> str:
    """Optionally observe public trailer media requested by a headless browser."""
    if not CHROME_APP_PATH.exists():
        return ""
    with tempfile.TemporaryDirectory(prefix="prime-trailer-", dir="/private/tmp") as profile:
        process = subprocess.Popen([
            str(CHROME_APP_PATH), "--headless=new", "--disable-gpu", "--disable-extensions",
            "--disable-background-networking", "--mute-audio", "--no-first-run",
            "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
            "--remote-debugging-port=0", f"--user-data-dir={profile}",
            f"--user-agent={USER_AGENT}", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            active_port = Path(profile) / "DevToolsActivePort"
            deadline = time.time() + 10
            port = 0
            while time.time() < deadline and process.poll() is None:
                if active_port.exists():
                    lines = active_port.read_text(encoding="utf-8", errors="replace").splitlines()
                    if lines and lines[0].isdigit():
                        port = int(lines[0])
                        break
                time.sleep(0.1)
            if not port:
                return ""
            websocket_url = ""
            for method in ("PUT", "GET"):
                try:
                    request = urllib.request.Request(f"http://127.0.0.1:{port}/json/new", method=method)
                    with urllib.request.urlopen(request, timeout=5) as response:
                        page = json.loads(response.read().decode("utf-8", errors="replace"))
                    websocket_url = clean_text(page.get("webSocketDebuggerUrl"))
                    if websocket_url:
                        break
                except Exception:
                    continue
            if not websocket_url:
                return ""
            return amazon_prime_watch_trailer_network(websocket_url, trailer_page_url)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def amazon_prime_watch_trailer_network(websocket_url: str, page_url: str) -> str:
    websocket = AmazonPrimeDevToolsWebSocket(websocket_url)
    try:
        websocket.connect()
        for identifier, (method, params) in enumerate((
            ("Network.enable", {}), ("Page.enable", {}),
            ("Page.navigate", {"url": page_url}),
        ), start=1):
            websocket.send_json({"id": identifier, "method": method, "params": params})
        deadline = time.time() + PRIME_TRAILER_CAPTURE_TIMEOUT_SECONDS
        while time.time() < deadline:
            message = websocket.recv_json(timeout=1)
            if not message or message.get("method") not in {"Network.requestWillBeSent", "Network.responseReceived"}:
                continue
            container = message.get("params", {}).get(
                "request" if message.get("method") == "Network.requestWillBeSent" else "response", {}
            )
            candidate = clean_text(container.get("url"))
            if urllib.parse.urlparse(candidate).path.casefold().endswith((".mp4", ".m3u8", ".mpd")):
                return candidate
        return ""
    except (OSError, RuntimeError):
        return ""
    finally:
        websocket.close()


class AmazonPrimeDevToolsWebSocket:
    def __init__(self, websocket_url: str) -> None:
        parsed = urllib.parse.urlparse(websocket_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        self.sock: socket.socket | None = None

    def connect(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        sock = socket.create_connection((self.host, self.port), timeout=10)
        request = (
            f"GET {self.path} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            sock.close()
            raise RuntimeError("Chrome DevTools WebSocket handshake failed")
        self.sock = sock

    def send_json(self, payload: dict[str, Any]) -> None:
        if not self.sock:
            return
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        if len(data) < 126:
            header.append(0x80 | len(data))
        elif len(data) <= 0xFFFF:
            header.extend([0x80 | 126]); header.extend(struct.pack("!H", len(data)))
        else:
            header.extend([0x80 | 127]); header.extend(struct.pack("!Q", len(data)))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self, timeout: float) -> dict[str, Any] | None:
        if not self.sock:
            return None
        self.sock.settimeout(timeout)
        try:
            first = self._read_exact(2)
            if len(first) < 2:
                return None
            opcode, length = first[0] & 0x0F, first[1] & 0x7F
            masked = bool(first[1] & 0x80)
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if masked else b""
            payload = self._read_exact(length)
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode != 1:
                return None
            return json.loads(payload.decode("utf-8", errors="replace"))
        except (OSError, ValueError, json.JSONDecodeError, struct.error):
            return None

    def _read_exact(self, size: int) -> bytes:
        data = bytearray()
        while self.sock and len(data) < size:
            data.extend(self.sock.recv(size - len(data)))
        return bytes(data)

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None


def save_amazon_prime_series_trailer(meta: Metadata, show_folder: Path) -> list[Path]:
    trailer_dir = show_folder / "trailers"
    if trailer_dir.exists() and any(path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS for path in trailer_dir.iterdir()):
        return []
    page_url = clean_text(meta.trailer_url)
    if not page_url:
        return []
    direct_url = ""
    if urllib.parse.urlparse(page_url).path.casefold().endswith((".mp4", ".m3u8", ".mpd")):
        direct_url = page_url
    else:
        try:
            page_bytes = fetch_bytes(page_url)
            direct_url = amazon_prime_direct_trailer_url_from_html(
                page_bytes.decode("utf-8", errors="replace") if page_bytes else ""
            )
        except Exception:
            direct_url = ""
        direct_url = direct_url or amazon_prime_capture_trailer_url(page_url)
    if not direct_url:
        print("Amazon Prime Video trailer skipped: public trailer media could not be resolved.")
        return []
    trailer_dir.mkdir(parents=True, exist_ok=True)
    trailer = download_binary(direct_url, trailer_dir / "trailer.mp4")
    if trailer:
        print(f"Amazon Prime Video series trailer saved to {trailer}")
        return [trailer]
    print("Amazon Prime Video trailer skipped: the public stream was unavailable or protected.")
    return []


def ensure_amazon_prime_series_bundle(meta: Metadata, show_folder: Path) -> list[Path]:
    series = amazon_prime_parent_series_meta(meta)
    if series.media_kind.casefold() != "series" or not series.plot:
        raise ValueError("Amazon Prime Video linked series metadata was incomplete; episode metadata was not saved.")
    show_folder.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    nfo = show_folder / "tvshow.nfo"
    if not nfo.exists():
        nfo.write_text(build_nfo(series), encoding="utf-8")
        saved.append(nfo)
    saved.extend(save_amazon_prime_show_art(series, show_folder))
    return saved


def save_amazon_prime_series_metadata(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = "", skip_existing: bool = False
) -> list[Path] | None:
    if not amazon_prime_series_enabled(meta, settings, explicit_folder):
        return None
    matches = amazon_prime_media_groups(meta, settings, explicit_folder)
    if not matches:
        # Amazon series mode recognized the request but could not prove which
        # anonymous local file belongs to which guide entry. Do not fall back to
        # a generic UUID-named series bundle beside arbitrary media.
        return []
    saved: list[Path] = []
    bundled: set[Path] = set()
    trailer_meta_for: dict[Path, Metadata] = {}
    explicit_show_folder = explicit_series_show_folder(explicit_folder, meta, amazon_prime_series_folder_name)
    source_folders = {group.folder for group, _record in matches}
    for group, record in matches:
        episode_meta = meta if (
            meta.media_kind.casefold() == "episode"
            and meta.season_number == str(group.season)
            and meta.episode_number == str(group.episode)
        ) else amazon_prime_episode_metadata(meta, record)
        prepared = prepare_amazon_prime_media_group(
            episode_meta, group, settings, explicit_show_folder=explicit_show_folder
        )
        show_folder = explicit_show_folder or amazon_prime_show_folder(prepared.folder, episode_meta)
        if show_folder not in bundled:
            saved.extend(ensure_amazon_prime_series_bundle(meta if meta.media_kind.casefold() == "series" else episode_meta, show_folder))
            bundled.add(show_folder)
        trailer_meta_for[show_folder] = amazon_prime_parent_series_meta(
            meta if meta.media_kind.casefold() == "series" else episode_meta
        )
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            continue
        nfo = video.with_suffix(".nfo")
        if not (skip_existing and nfo.exists()):
            nfo.write_text(build_nfo(episode_meta), encoding="utf-8")
            saved.append(nfo)
        extension = image_extension_from_url(episode_meta.thumb_url) or ".jpg"
        thumb = video.with_name(f"{video.stem}-thumb{extension}")
        if episode_meta.thumb_url and not thumb.exists():
            path = download_binary(episode_meta.thumb_url, thumb)
            if path:
                saved.append(path)
    for show_folder, series_meta in trailer_meta_for.items():
        saved.extend(save_amazon_prime_series_trailer(series_meta, show_folder))
    cleanup_empty_provider_source_folders(source_folders, explicit_show_folder, amazon.PRIME_NAME)
    print(f"Amazon Prime Video series mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def pbs_kids_series_enabled(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> bool:
    return (
        meta.source_site == pbs_kids.NAME
        and meta.media_kind.casefold() in {"series", "episode"}
        and bool(meta.series_episodes)
        and bool(settings.get("pbs_kids_series_metadata_enabled", True))
        and bool(explicit_folder or media_search_roots(settings))
    )


def pbs_kids_match_record(video: Path, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    stem_key = normalize_match_key(video.stem)
    identity_matches = []
    for record in records:
        identities = [
            clean_text(record.get("id")),
            clean_text(record.get("legacy_id")),
            normalize_match_key(clean_text(record.get("guid"))),
        ]
        if any(identity and normalize_match_key(identity) in stem_key for identity in identities):
            identity_matches.append(record)
    if len(identity_matches) == 1:
        return identity_matches[0]
    position = paramountplus_episode_position(f"{video.stem} {video.parent.name}")
    if position:
        positional = [
            record for record in records
            if clean_text(record.get("season")).isdigit()
            and clean_text(record.get("episode")).isdigit()
            and (int(record["season"]), int(record["episode"])) == position
        ]
        if len(positional) == 1:
            return positional[0]
    title_matches = []
    for record in records:
        title_key = normalize_match_key(clean_text(record.get("title")))
        if len(title_key) >= 4 and title_key in stem_key:
            title_matches.append(record)
    return title_matches[0] if len(title_matches) == 1 else None


def pbs_kids_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[PBSKidsMediaGroup, dict[str, Any]]]:
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    roots = [Path(explicit_folder).expanduser().resolve()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
            continue
        for folder_text, _dirs, filenames in os.walk(root):
            candidates.extend(
                Path(folder_text) / filename
                for filename in filenames
                if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS
            )
    direct_record = None
    if meta.media_kind.casefold() == "episode":
        direct_record = next(
            (
                record for record in records
                if clean_text(record.get("season")) == meta.season_number
                and clean_text(record.get("episode")) == meta.episode_number
            ),
            None,
        )
    wanted_title = normalize_match_key(meta.show_title or meta.title)
    matched: list[tuple[PBSKidsMediaGroup, dict[str, Any]]] = []
    claimed: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        path_key = normalize_match_key(str(video))
        if not explicit_folder and wanted_title not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        identity_matches = [
            record for record in records
            if any(
                clean_text(value) and normalize_match_key(clean_text(value)) in stem_key
                for value in (record.get("id"), record.get("legacy_id"), record.get("guid"))
            )
        ]
        if explicit_folder and len(candidates) == 1 and direct_record:
            record = direct_record
        elif len(identity_matches) == 1:
            record = identity_matches[0]
        else:
            record = pbs_kids_match_record(video, records)
        season = clean_text(record.get("season")) if record else ""
        episode = clean_text(record.get("episode")) if record else ""
        if not (record and season.isdigit() and episode.isdigit()):
            continue
        position = (int(season), int(episode))
        if position in claimed:
            continue
        claimed.add(position)
        files = [video, *local_episode_sidecars(video)]
        matched.append(
            (
                PBSKidsMediaGroup(video.parent, video.stem, int(season), int(episode), files),
                record,
            )
        )
    return sorted(matched, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def pbs_kids_target_base(meta: Metadata, group: PBSKidsMediaGroup | None = None) -> str:
    season = group.season if group else int(meta.season_number or 1)
    episode = group.episode if group else int(meta.episode_number or 0)
    base = f"S{season:02d}E{episode:02d} {meta.show_title or meta.title}"
    if meta.episode_title:
        base += f" - {meta.episode_title}"
    return safe_filename(base)


def pbs_kids_series_folder_name(meta: Metadata) -> str:
    return safe_filename(meta.show_title or meta.title)


def pbs_kids_show_folder(folder: Path, meta: Metadata) -> Path:
    resolved = folder.resolve()
    root = resolved.parent if re.fullmatch(r"S\d{1,2}", resolved.name, re.I) else resolved
    desired = pbs_kids_series_folder_name(meta)
    if normalize_match_key(root.name) == normalize_match_key(desired):
        return root
    return root / desired


def prepare_pbs_kids_media_group(
    meta: Metadata,
    group: PBSKidsMediaGroup,
    settings: dict[str, Any],
    explicit_show_folder: Path | None = None,
) -> PBSKidsMediaGroup:
    rename = bool(settings.get("pbs_kids_series_rename_enabled", True))
    organize = bool(settings.get("pbs_kids_series_organize_enabled", True))
    if not (rename or organize):
        return group
    destination = (
        (explicit_show_folder or pbs_kids_show_folder(group.folder, meta)) / f"S{group.season:02d}"
        if organize else group.folder
    )
    base = pbs_kids_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    for source in group.files:
        suffix = source.name[len(group.stem):]
        target = destination / ((base + suffix) if rename else source.name)
        if target in used or (target.exists() and target not in group.files):
            raise FileExistsError(f"PBS KIDS rename target already exists: {target}")
        used.add(target)
        targets.append((source, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        if source == target:
            temporary.append((source, target))
            continue
        temp = source.with_name(f".pbs-kids-rename-{index}-{source.name}")
        source.rename(temp)
        temporary.append((temp, target))
    for temporary_path, target in temporary:
        if temporary_path != target:
            temporary_path.rename(target)
    final_files = [target for _source, target in targets]
    video = next((path for path in final_files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return PBSKidsMediaGroup(destination, video.stem if video else base, group.season, group.episode, final_files)


def pbs_kids_parent_series_meta(meta: Metadata) -> Metadata:
    if meta.media_kind.casefold() == "series":
        return meta
    if meta.series_metadata:
        return metadata_from_provider_dict(
            meta.series_metadata,
            detail_link=clean_text(meta.series_metadata.get("source_url")),
        )
    raise ValueError("PBS KIDS episode metadata did not include its linked series metadata.")


def pbs_kids_episode_metadata(meta: Metadata, record: dict[str, Any]) -> Metadata:
    series_meta = pbs_kids_parent_series_meta(meta)
    video_id = clean_text(record.get("id"))
    legacy_id = clean_text(record.get("legacy_id"))
    episode = Metadata(
        source_url=clean_text(record.get("url")) or meta.source_url,
        detail_link=clean_text(record.get("url")),
        source_site=pbs_kids.NAME,
        media_kind="episode",
        title=series_meta.title,
        show_title=series_meta.title,
        season_number=clean_text(record.get("season")),
        episode_number=clean_text(record.get("episode")),
        episode_title=clean_text(record.get("title")),
        outline=clean_text(record.get("short_description")),
        plot=clean_text(record.get("long_description")) or clean_text(record.get("short_description")),
        date=clean_text(record.get("date")),
        year=clean_text(record.get("date"))[:4],
        runtime_minutes=clean_text(record.get("runtime_minutes")),
        thumb_url=clean_text(record.get("image")),
        genres=list(series_meta.genres),
        tags=list(series_meta.tags),
        studios=list(series_meta.studios),
        unique_ids={
            key: value
            for key, value in (
                ("pbskids", video_id),
                ("pbs", legacy_id),
            )
            if value
        },
        series_metadata=meta.series_metadata,
    )
    for label, value in (
        ("PBS KIDS video ID", video_id),
        ("Legacy PBS media ID", legacy_id),
        ("Video type", record.get("type")),
        ("Runtime seconds", record.get("duration_seconds")),
    ):
        episode.add_extra(label, value)
    return episode


def save_pbs_kids_show_art(meta: Metadata, folder: Path) -> list[Path]:
    saved: list[Path] = []
    for artwork_type, url in (("thumb", meta.thumb_url), ("logo", meta.logo_url)):
        if not clean_text(url):
            continue
        extension = image_extension_from_url(url) or (".png" if artwork_type == "logo" else ".jpg")
        target = folder / f"{artwork_type}{extension}"
        if target.exists():
            continue
        path = download_binary(url, target)
        if path:
            if artwork_type == "logo" and isinstance(path, Path):
                path = normalize_provider_logo_file(path)
            saved.append(path)
    return saved


def ensure_pbs_kids_series_bundle(meta: Metadata, show_folder: Path) -> list[Path]:
    series_meta = pbs_kids_parent_series_meta(meta)
    if series_meta.media_kind.casefold() != "series" or not series_meta.plot:
        raise ValueError("PBS KIDS linked series metadata was incomplete; episode metadata was not saved.")
    show_folder.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    nfo = show_folder / "tvshow.nfo"
    if not nfo.exists():
        nfo.write_text(build_nfo(series_meta), encoding="utf-8")
        saved.append(nfo)
    saved.extend(save_pbs_kids_show_art(series_meta, show_folder))
    return saved


def cleanup_pbs_kids_handoff_folders(explicit_folder: str) -> list[Path]:
    """Remove proven-empty MediaFab timestamp folders after a successful PBS KIDS handoff."""
    if not explicit_folder:
        return []
    supplied = Path(explicit_folder).expanduser()
    root = supplied.parent if supplied.suffix.casefold() in VIDEO_EXTENSIONS else supplied
    if not root.is_dir():
        return []
    timestamp_suffix = re.compile(r"_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$")
    removed: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.is_symlink() or not timestamp_suffix.search(child.name):
            continue
        entries = list(child.iterdir())
        if any(entry.name != ".DS_Store" for entry in entries):
            continue
        ds_store = child / ".DS_Store"
        if ds_store.exists() and ds_store.is_file() and not ds_store.is_symlink():
            ds_store.unlink()
        try:
            child.rmdir()
        except OSError:
            continue
        removed.append(child)
    if removed:
        print(f"PBS KIDS cleanup removed {len(removed)} empty MediaFab handoff folder(s).")
    return removed


def save_pbs_kids_series_metadata(
    meta: Metadata,
    settings: dict[str, Any],
    explicit_folder: str = "",
    skip_existing: bool = False,
) -> list[Path] | None:
    if not pbs_kids_series_enabled(meta, settings, explicit_folder):
        return None
    matches = pbs_kids_media_groups(meta, settings, explicit_folder)
    if not matches:
        return []
    saved: list[Path] = []
    bundled: set[Path] = set()
    explicit_show_folder = explicit_series_show_folder(explicit_folder, meta, pbs_kids_series_folder_name)
    source_folders = {group.folder for group, _record in matches}
    for group, record in matches:
        episode_meta = pbs_kids_episode_metadata(meta, record)
        prepared = prepare_pbs_kids_media_group(
            episode_meta, group, settings, explicit_show_folder=explicit_show_folder
        )
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            continue
        show_folder = explicit_show_folder or pbs_kids_show_folder(prepared.folder, episode_meta)
        if show_folder not in bundled:
            saved.extend(ensure_pbs_kids_series_bundle(meta, show_folder))
            bundled.add(show_folder)
        nfo = video.with_suffix(".nfo")
        if not (skip_existing and nfo.exists()):
            nfo.write_text(build_nfo(episode_meta), encoding="utf-8")
            saved.append(nfo)
        extension = image_extension_from_url(episode_meta.thumb_url) or ".jpg"
        thumb = video.with_name(f"{video.stem}-thumb{extension}")
        if episode_meta.thumb_url and not thumb.exists():
            path = download_binary(episode_meta.thumb_url, thumb)
            if path:
                saved.append(path)
    cleanup_empty_provider_source_folders(source_folders, explicit_show_folder, pbs_kids.NAME)
    print(f"PBS KIDS series mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    cleanup_pbs_kids_handoff_folders(explicit_folder)
    return saved


def paramountplus_series_enabled(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> bool:
    return (
        meta.source_site == paramountplus.NAME
        and meta.media_kind.casefold() in {"series", "episode"}
        and bool(meta.series_episodes)
        and bool(settings.get("paramountplus_series_metadata_enabled", True))
        and bool(explicit_folder or media_search_roots(settings))
    )


def paramountplus_media_groups(
    meta: Metadata, settings: dict[str, Any], explicit_folder: str = ""
) -> list[tuple[ParamountPlusMediaGroup, dict[str, Any]]]:
    """Match only an explicit handoff or title-confirmed local Paramount+ episodes."""
    records = [record for record in meta.series_episodes if isinstance(record, dict)]
    guide = {
        (int(record["season"]), int(record["episode"])): record
        for record in records
        if clean_text(record.get("season")).isdigit() and clean_text(record.get("episode")).isdigit()
    }
    roots = [Path(explicit_folder).expanduser().resolve()] if explicit_folder else media_search_roots(settings)
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix.casefold() in VIDEO_EXTENSIONS:
            candidates.append(root)
            continue
        for folder_text, _dirs, filenames in os.walk(root):
            candidates.extend(
                Path(folder_text) / filename
                for filename in filenames
                if Path(filename).suffix.casefold() in VIDEO_EXTENSIONS
            )
    wanted_title = normalize_match_key(meta.show_title or meta.title)
    direct_position = None
    if meta.media_kind.casefold() == "episode" and meta.season_number.isdigit() and meta.episode_number.isdigit():
        direct_position = (int(meta.season_number), int(meta.episode_number))
    matched: list[tuple[ParamountPlusMediaGroup, dict[str, Any]]] = []
    claimed: set[tuple[int, int]] = set()
    for video in sorted(set(candidates)):
        path_key = normalize_match_key(str(video))
        if not explicit_folder and wanted_title and wanted_title not in path_key:
            continue
        if candidate_is_in_foreign_series_root(video, explicit_folder, meta.show_title or meta.title):
            continue
        stem_key = normalize_match_key(video.stem)
        id_matches = [
            record for record in records
            if clean_text(record.get("id")) and normalize_match_key(record["id"]) in stem_key
        ]
        if len(id_matches) == 1:
            position = (int(id_matches[0]["season"]), int(id_matches[0]["episode"]))
        elif explicit_folder and len(candidates) == 1 and direct_position:
            # The playing-page handoff identifies the one newly completed file;
            # timestamp digits in a generic manifest name are not episode placement.
            position = direct_position
        else:
            position = paramountplus_episode_position(f"{video.stem} {video.parent.name}")
        record = guide.get(position) if position else None
        if not (position and record) or position in claimed:
            continue
        claimed.add(position)
        files = [video]
        for sidecar in video.parent.iterdir():
            if (
                sidecar.is_file()
                and (
                    (
                        sidecar.suffix.casefold() in {".srt", ".vtt", ".ass", ".ssa", ".sub", ".nfo"}
                        and (sidecar.stem == video.stem or sidecar.name.startswith(video.stem + "."))
                    )
                    or (
                        sidecar.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}
                        and sidecar.name.startswith(video.stem + "-thumb.")
                    )
                )
            ):
                files.append(sidecar)
        matched.append((ParamountPlusMediaGroup(video.parent, video.stem, *position, files), record))
    return sorted(matched, key=lambda item: (item[0].season, item[0].episode, str(item[0].folder)))


def paramountplus_episode_position(text: str) -> tuple[int, int] | None:
    """Read common local season/episode spellings without requiring a show title."""
    patterns = (
        r"(?:^|[^a-z0-9])s(?:eason)?\s*0?(\d{1,2})\s*[-._ ]*e(?:pisode)?\s*0?(\d{1,3})(?:$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])(?:season|series)\s*0?(\d{1,2})\s*[-._ ]*(?:episode|ep)\s*0?(\d{1,3})(?:$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])0?(\d{1,2})\s*[xX]\s*0?(\d{1,3})(?:$|[^a-z0-9])",
        r"(?:^|[^a-z0-9])0?(\d{1,2})\s*[-._]\s*0?(\d{1,3})(?:$|[^a-z0-9])",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def paramountplus_target_base(meta: Metadata, group: ParamountPlusMediaGroup | None = None) -> str:
    season = group.season if group else int(meta.season_number or 1)
    episode = group.episode if group else int(meta.episode_number or 0)
    base = f"S{season:02d}E{episode:02d} {meta.show_title or meta.title}"
    if meta.episode_title:
        base += f" - {meta.episode_title}"
    return safe_filename(base)


def paramountplus_series_folder_name(meta: Metadata) -> str:
    title = safe_filename(meta.show_title or meta.title)
    start = clean_text(meta.series_start_year)
    end = clean_text(meta.series_end_year)
    if not start.isdigit():
        return title
    if meta.series_is_current:
        years = f"{start}-"
    elif not end or end == start:
        years = start
    else:
        years = f"{start}-{end}"
    return safe_filename(f"{title} ({years})")


def paramountplus_show_folder(folder: Path, meta: Metadata) -> Path:
    resolved = folder.resolve()
    root = resolved.parent if re.fullmatch(r"S\d{1,2}", resolved.name, re.IGNORECASE) else resolved
    desired_name = paramountplus_series_folder_name(meta)
    if normalize_match_key(root.name) == normalize_match_key(desired_name):
        return root
    legacy_name = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(legacy_name) == normalize_match_key(safe_filename(meta.show_title or meta.title)):
        return root.parent / desired_name
    return root / desired_name


def paramountplus_explicit_show_folder(explicit_folder: str, meta: Metadata) -> Path | None:
    if not clean_text(explicit_folder):
        return None
    supplied = Path(explicit_folder).expanduser().resolve()
    root = supplied.parent if supplied.is_file() or supplied.suffix.casefold() in VIDEO_EXTENSIONS else supplied
    return paramountplus_show_folder(root, meta)


def migrate_paramountplus_series_folder(
    group: ParamountPlusMediaGroup, meta: Metadata
) -> ParamountPlusMediaGroup:
    folder = group.folder.resolve()
    root = folder.parent if re.fullmatch(r"S\d{1,2}", folder.name, re.IGNORECASE) else folder
    title = safe_filename(meta.show_title or meta.title)
    root_title = re.sub(r" \(\d{4}(?:-(?:\d{4})?)?\)$", "", root.name)
    if normalize_match_key(root_title) != normalize_match_key(title):
        return group
    desired = root.parent / paramountplus_series_folder_name(meta)
    if desired == root:
        return group
    if desired.exists():
        raise FileExistsError(f"Paramount+ series folder already exists: {desired}")
    relative_folder = folder.relative_to(root)
    relative_files = [path.resolve().relative_to(root) for path in group.files]
    root.rename(desired)
    return ParamountPlusMediaGroup(
        desired / relative_folder,
        group.stem,
        group.season,
        group.episode,
        [desired / path for path in relative_files],
    )


def prepare_paramountplus_media_group(
    meta: Metadata,
    group: ParamountPlusMediaGroup,
    settings: dict[str, Any],
    explicit_show_folder: Path | None = None,
) -> ParamountPlusMediaGroup:
    rename = bool(settings.get("paramountplus_series_rename_enabled", True))
    organize = bool(settings.get("paramountplus_series_organize_enabled", True))
    if not (rename or organize):
        return group
    if organize and explicit_show_folder is None:
        group = migrate_paramountplus_series_folder(group, meta)
    destination = (
        (explicit_show_folder or paramountplus_show_folder(group.folder, meta)) / f"S{group.season:02d}"
        if organize else group.folder
    )
    base = paramountplus_target_base(meta, group) if rename else group.stem
    targets: list[tuple[Path, Path]] = []
    used: set[Path] = set()
    for source in group.files:
        suffix = source.name[len(group.stem):]
        target = destination / ((base + suffix) if rename else source.name)
        if target in used or (target.exists() and target not in group.files):
            raise FileExistsError(f"Paramount+ rename target already exists: {target}")
        used.add(target)
        targets.append((source, target))
    destination.mkdir(parents=True, exist_ok=True)
    temporary: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(targets, start=1):
        if source == target:
            temporary.append((source, target))
            continue
        temp = source.with_name(f".paramountplus-rename-{index}-{source.name}")
        source.rename(temp)
        temporary.append((temp, target))
    for temporary_path, target in temporary:
        if temporary_path != target:
            temporary_path.rename(target)
    final_files = [target for _source, target in targets]
    video = next((path for path in final_files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
    return ParamountPlusMediaGroup(
        destination, video.stem if video else base, group.season, group.episode, final_files
    )


def paramountplus_episode_metadata(meta: Metadata, record: dict[str, Any]) -> Metadata:
    episode_id = clean_text(record.get("id"))
    episode = Metadata(
        source_url=clean_text(record.get("url")) or meta.source_url,
        detail_link=clean_text(record.get("url")),
        source_site=meta.source_site,
        media_kind="episode",
        title=meta.title,
        show_title=clean_text(record.get("show_title")) or meta.title,
        season_number=clean_text(record.get("season")),
        episode_number=clean_text(record.get("episode")),
        episode_title=clean_text(record.get("title")),
        outline=clean_text(record.get("description")),
        plot=clean_text(record.get("description")),
        year=clean_text(record.get("date"))[:4] or meta.year,
        series_start_year=meta.series_start_year,
        series_end_year=meta.series_end_year,
        series_is_current=meta.series_is_current,
        date=clean_text(record.get("date")),
        runtime_minutes=duration_minutes_text(clean_text(record.get("duration"))),
        content_rating=meta.content_rating,
        poster_url=meta.poster_url,
        fanart_url=meta.fanart_url,
        logo_url=meta.logo_url,
        thumb_url=clean_text(record.get("image")),
        trailer_url=meta.trailer_url,
        genres=list(meta.genres),
        tags=list(meta.tags),
        studios=list(meta.studios),
        unique_ids={"paramountplus": episode_id} if episode_id else {},
        series_metadata=meta.series_metadata,
    )
    for label in ("Paramount+ show ID", "Brand", "Season count", "Episode count", "Audio", "Subtitles"):
        for value in meta.extra_fields.get(label, []):
            episode.add_extra(label, value)
    episode.add_extra("Paramount+ episode ID", episode_id)
    episode.add_extra("Episode page", episode.detail_link)
    return episode


def duration_minutes_text(value: str) -> str:
    text = clean_text(value)
    iso = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", text, re.IGNORECASE)
    if iso:
        return str(int(iso.group(1) or 0) * 60 + int(iso.group(2) or 0))
    minutes = re.search(r"(\d+)\s*(?:m|min|minutes?)\b", text, re.IGNORECASE)
    return minutes.group(1) if minutes else ""


def save_paramountplus_show_art(meta: Metadata, folder: Path) -> list[Path]:
    saved: list[Path] = []
    for artwork_type, url in (("poster", meta.poster_url), ("backdrop", meta.fanart_url), ("logo", meta.logo_url)):
        if not clean_text(url):
            continue
        target = folder / f"{artwork_type}.png"
        if target.exists():
            continue
        path = download_binary(url, target)
        if path:
            normalized = normalize_paramountplus_image_file(path)
            if normalized:
                saved.append(normalized)
    return saved


def save_paramountplus_movie_art(meta: Metadata, folder: Path, base_name: str) -> list[Path]:
    saved: list[Path] = []
    for artwork_type, url in (
        ("poster", meta.poster_url), ("backdrop", meta.fanart_url), ("logo", meta.logo_url),
    ):
        if not clean_text(url):
            continue
        target = folder / f"{base_name}-{artwork_type}.png"
        if target.exists() or (
            artwork_type == "logo"
            and any(path.is_file() and path.stem == f"{base_name}-logo" for path in folder.iterdir())
        ):
            continue
        path = download_binary(url, target)
        if path:
            normalized = normalize_paramountplus_image_file(path)
            if normalized:
                saved.append(normalized)
    return saved


def ensure_paramountplus_series_bundle(meta: Metadata, show_folder: Path) -> list[Path]:
    """Ensure a Paramount+ episode always has its parent-series NFO and artwork."""
    show_folder.mkdir(parents=True, exist_ok=True)
    series_item = meta.series_metadata
    if meta.media_kind.casefold() == "series":
        series_meta = meta
    elif series_item:
        series_meta = metadata_from_provider_dict(series_item, detail_link=clean_text(series_item.get("source_url")))
    else:
        raise ValueError("Paramount+ episode metadata did not include its linked series metadata.")
    if series_meta.media_kind.casefold() != "series" or not series_meta.plot:
        raise ValueError("Paramount+ linked series metadata was incomplete; episode metadata was not saved.")
    tvshow_nfo = show_folder / "tvshow.nfo"
    saved: list[Path] = []
    if not tvshow_nfo.exists():
        tvshow_nfo.write_text(build_nfo(series_meta), encoding="utf-8")
        saved.append(tvshow_nfo)
    saved.extend(save_paramountplus_show_art(series_meta, show_folder))
    return saved


def save_paramountplus_series_trailer(meta: Metadata, show_folder: Path) -> list[Path]:
    """Save one provider-supplied public preview in Jellyfin's native trailer folder."""
    trailer_dir = show_folder / "trailers"
    if trailer_dir.exists() and any(
        path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS for path in trailer_dir.iterdir()
    ):
        return []
    trailer_url = clean_text(meta.trailer_url)
    if not trailer_url:
        return []
    trailer_dir.mkdir(parents=True, exist_ok=True)
    trailer = download_binary(trailer_url, trailer_dir / "trailer.mp4")
    if trailer:
        return [trailer]
    try:
        trailer_dir.rmdir()
    except OSError:
        pass
    return []


def save_paramountplus_extra_videos(meta: Metadata, folder: Path) -> list[Path]:
    saved: list[Path] = []
    used_names: set[str] = set()
    for index, video in enumerate(meta.extra_videos, start=1):
        url = clean_text(video.url)
        if not url or url == clean_text(meta.trailer_url):
            continue
        base = safe_filename(video.title or f"extra-{index:02d}")
        name = base
        duplicate = 2
        while name.casefold() in used_names:
            name = f"{base} ({duplicate})"
            duplicate += 1
        used_names.add(name.casefold())
        extra_dir = folder / "Extras" / "Videos"
        extra_dir.mkdir(parents=True, exist_ok=True)
        target = extra_dir / f"{name}{guess_media_extension(url)}"
        path = download_binary(url, target)
        if path:
            saved.append(path)
        else:
            try:
                extra_dir.rmdir()
                extra_dir.parent.rmdir()
            except OSError:
                pass
    return saved


def cleanup_paramountplus_source_folders(folders: set[Path], show_folder: Path | None) -> list[Path]:
    """Remove only source folders proven empty after their matched files were organized."""
    removed: list[Path] = []
    canonical = show_folder.resolve() if show_folder else None
    for folder in sorted({path.resolve() for path in folders}, key=lambda path: len(path.parts), reverse=True):
        if not folder.is_dir() or folder.is_symlink():
            continue
        if canonical and (folder == canonical or canonical in folder.parents):
            continue
        entries = list(folder.iterdir())
        if any(entry.name != ".DS_Store" for entry in entries):
            continue
        ds_store = folder / ".DS_Store"
        if ds_store.exists() and ds_store.is_file() and not ds_store.is_symlink():
            ds_store.unlink()
        try:
            folder.rmdir()
        except OSError:
            continue
        removed.append(folder)
    if removed:
        print(f"Paramount+ cleanup removed {len(removed)} empty source folder(s).")
    return removed


def save_paramountplus_series_metadata(
    meta: Metadata,
    settings: dict[str, Any],
    explicit_folder: str = "",
    skip_existing: bool = False,
) -> list[Path] | None:
    if not paramountplus_series_enabled(meta, settings, explicit_folder=explicit_folder):
        return None
    matches = paramountplus_media_groups(meta, settings, explicit_folder=explicit_folder)
    if not matches:
        # A series/detail link with no exact local identity must not fall back
        # to generic output or create sidecars for guide-only episodes.
        return []
    saved: list[Path] = []
    trailer_meta_for: dict[Path, Metadata] = {}
    bundled: set[Path] = set()
    explicit_show_folder = paramountplus_explicit_show_folder(explicit_folder, meta)
    source_folders = {group.folder for group, _record in matches}
    for group, record in matches:
        if (
            meta.media_kind.casefold() == "episode"
            and meta.season_number == str(group.season)
            and meta.episode_number == str(group.episode)
        ):
            episode_meta = meta
        else:
            episode_meta = paramountplus_episode_metadata(meta, record)
        episode_meta.season_number = str(group.season)
        episode_meta.episode_number = str(group.episode)
        prepared = prepare_paramountplus_media_group(
            episode_meta, group, settings, explicit_show_folder=explicit_show_folder
        )
        show_folder = explicit_show_folder or paramountplus_show_folder(prepared.folder, episode_meta)
        if show_folder not in bundled:
            bundle_meta = meta if meta.media_kind.casefold() == "series" else episode_meta
            saved.extend(ensure_paramountplus_series_bundle(bundle_meta, show_folder))
            bundled.add(show_folder)
        trailer_meta_for[show_folder] = meta if meta.media_kind.casefold() == "series" else episode_meta
        video = next((path for path in prepared.files if path.suffix.casefold() in VIDEO_EXTENSIONS), None)
        if not video:
            continue
        nfo = video.with_suffix(".nfo")
        if not (skip_existing and nfo.exists()):
            nfo.write_text(build_nfo(episode_meta), encoding="utf-8")
            saved.append(nfo)
        thumb = video.with_name(f"{video.stem}-thumb.png")
        if episode_meta.thumb_url and not thumb.exists():
            path = download_binary(episode_meta.thumb_url, thumb)
            if path:
                normalized = normalize_paramountplus_image_file(path)
                if normalized:
                    saved.append(normalized)
    for show_folder, trailer_meta in trailer_meta_for.items():
        series_item = trailer_meta.series_metadata
        series_meta = metadata_from_provider_dict(series_item) if series_item else trailer_meta
        saved.extend(save_paramountplus_series_trailer(series_meta, show_folder))
        saved.extend(save_paramountplus_extra_videos(series_meta, show_folder))
    cleanup_paramountplus_source_folders(source_folders, explicit_show_folder)
    print(f"Paramount+ series mode found {len(matches)} local episode(s) and saved {len(saved)} item(s).")
    return saved


def save_provider_series_metadata(
    meta: Metadata,
    original_url: str,
    settings: dict[str, Any],
    skip_existing: bool = False,
    explicit_folder: str = "",
) -> list[Path] | None:
    saved = save_netflix_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )
    if saved is not None:
        return saved
    saved = save_bbc_queue_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )
    if saved is not None:
        return saved
    saved = save_bbc_series_metadata(meta, original_url, settings, skip_existing=skip_existing)
    if saved is not None:
        return saved
    saved = save_amazon_prime_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )
    if saved is not None:
        return saved
    saved = save_crunchyroll_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )
    if saved is not None:
        return saved
    saved = save_disneyplus_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )
    if saved is not None:
        return saved
    saved = save_hbomax_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )
    if saved is not None:
        return saved
    saved = save_pbs_kids_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )
    if saved is not None:
        return saved
    return save_paramountplus_series_metadata(
        meta,
        settings,
        explicit_folder=explicit_folder,
        skip_existing=skip_existing,
    )


def output_plan(meta: Metadata, settings: dict[str, Any], explicit_folder: str = "") -> tuple[Path, str]:
    match = find_media_match(meta, settings, explicit_folder=explicit_folder)
    if match:
        match = maybe_rename_generic_video(match, meta, settings)
        match = organize_netflix_movie(match, meta, explicit_folder=explicit_folder)
        match = organize_disneyplus_movie(match, meta, settings, explicit_folder=explicit_folder)
        match = organize_hbomax_movie(match, meta, settings, explicit_folder=explicit_folder)
        match = organize_paramountplus_movie(match, meta, settings, explicit_folder=explicit_folder)
        return match.folder, match.filename_base
    if is_disneyplus_movie(meta):
        base = disneyplus_movie_name(meta)
        return settings_output_dir(settings) / disneyplus.NAME / base, base
    if is_paramountplus_movie(meta):
        base = paramountplus_movie_name(meta)
        return settings_output_dir(settings) / paramountplus.NAME / base, base
    if is_hbomax_movie(meta):
        base = hbomax_movie_name(meta)
        return settings_output_dir(settings) / hbomax.NAME / base, base
    if is_netflix_movie(meta):
        base = netflix_movie_name(meta)
        return settings_output_dir(settings) / netflix.NAME / base, base
    if meta.source_site == amazon.PRIME_NAME and meta.media_kind.casefold() == "series":
        return settings_output_dir(settings) / amazon_prime_series_folder_name(meta), "tvshow"
    if (
        meta.source_site == amazon.PRIME_NAME
        and meta.media_kind.casefold() == "episode"
        and meta.season_number.isdigit()
        and meta.episode_number.isdigit()
    ):
        base = amazon_prime_target_base(meta)
        return (
            settings_output_dir(settings)
            / amazon_prime_series_folder_name(meta)
            / f"S{int(meta.season_number):02d}",
            base,
        )
    if meta.source_site == disneyplus.NAME and meta.media_kind.casefold() == "series":
        return settings_output_dir(settings) / disneyplus_series_folder_name(meta), "tvshow"
    if (
        meta.source_site == disneyplus.NAME
        and meta.media_kind.casefold() == "episode"
        and meta.season_number.isdigit()
        and meta.episode_number.isdigit()
    ):
        base = disneyplus_target_base(meta)
        return (
            settings_output_dir(settings)
            / disneyplus_series_folder_name(meta)
            / f"S{int(meta.season_number):02d}",
            base,
        )
    if meta.source_site == hbomax.NAME and meta.media_kind.casefold() == "series":
        return settings_output_dir(settings) / hbomax_series_folder_name(meta), "tvshow"
    if (
        meta.source_site == hbomax.NAME
        and meta.media_kind.casefold() == "episode"
        and meta.season_number.isdigit()
        and meta.episode_number.isdigit()
    ):
        base = hbomax_target_base(meta)
        return (
            settings_output_dir(settings) / hbomax_series_folder_name(meta) / f"S{int(meta.season_number):02d}",
            base,
        )
    if meta.source_site == pbs_kids.NAME and meta.media_kind.casefold() == "series":
        return settings_output_dir(settings) / pbs_kids_series_folder_name(meta), "tvshow"
    if (
        meta.source_site == pbs_kids.NAME
        and meta.media_kind.casefold() == "episode"
        and meta.season_number.isdigit()
        and meta.episode_number.isdigit()
    ):
        base = pbs_kids_target_base(meta)
        return (
            settings_output_dir(settings)
            / pbs_kids_series_folder_name(meta)
            / f"S{int(meta.season_number):02d}",
            base,
        )
    if meta.source_site == paramountplus.NAME and meta.media_kind.casefold() == "series":
        return settings_output_dir(settings) / paramountplus_series_folder_name(meta), "tvshow"
    if (
        meta.source_site == paramountplus.NAME
        and meta.media_kind.casefold() == "episode"
        and meta.season_number.isdigit()
        and meta.episode_number.isdigit()
    ):
        base = paramountplus_target_base(meta)
        return (
            settings_output_dir(settings)
            / paramountplus_series_folder_name(meta)
            / f"S{int(meta.season_number):02d}",
            base,
        )
    if meta.source_site == crunchyroll.NAME and meta.media_kind.casefold() == "series":
        return settings_output_dir(settings) / crunchyroll_series_folder_name(meta), "tvshow"
    if (
        meta.source_site == crunchyroll.NAME
        and meta.media_kind.casefold() == "episode"
        and meta.season_number.isdigit()
        and meta.episode_number.isdigit()
    ):
        base = crunchyroll_target_base(meta)
        return (
            settings_output_dir(settings)
            / crunchyroll_series_folder_name(meta)
            / f"S{int(meta.season_number):02d}",
            base,
        )
    folder = settings_output_dir(settings) / default_folder_name(meta)
    return folder, safe_filename(meta.folder_name_override or meta.title)


def nfo_path(folder: Path, base_name: str) -> Path:
    return folder / f"{base_name}.nfo"


def save_metadata_bundle(meta: Metadata, settings: dict[str, Any], explicit_folder: str = "", skip_existing: bool = False) -> list[Path]:
    folder, base_name = output_plan(meta, settings, explicit_folder=explicit_folder)
    saved: list[Path] = []
    crunchyroll_series_folder: Path | None = None
    disneyplus_series_folder: Path | None = None
    hbomax_series_folder: Path | None = None
    paramountplus_series_folder: Path | None = None
    pbs_kids_series_folder: Path | None = None
    amazon_prime_series_folder: Path | None = None
    if meta.source_site == amazon.PRIME_NAME and meta.media_kind.casefold() == "episode":
        amazon_prime_series_folder = amazon_prime_show_folder(folder, meta)
        saved.extend(ensure_amazon_prime_series_bundle(meta, amazon_prime_series_folder))
    if meta.source_site == crunchyroll.NAME and meta.media_kind.casefold() == "episode":
        crunchyroll_series_folder = crunchyroll_show_folder(folder, meta)
        saved.extend(ensure_crunchyroll_series_bundle(meta, crunchyroll_series_folder))
    if meta.source_site == disneyplus.NAME and meta.media_kind.casefold() == "episode":
        disneyplus_series_folder = disneyplus_show_folder(folder, meta)
        saved.extend(ensure_disneyplus_series_bundle(meta, disneyplus_series_folder))
    if meta.source_site == hbomax.NAME and meta.media_kind.casefold() == "episode":
        hbomax_series_folder = hbomax_show_folder(folder, meta)
        saved.extend(ensure_hbomax_series_bundle(meta, hbomax_series_folder))
    if meta.source_site == pbs_kids.NAME and meta.media_kind.casefold() == "episode":
        pbs_kids_series_folder = pbs_kids_show_folder(folder, meta)
        saved.extend(ensure_pbs_kids_series_bundle(meta, pbs_kids_series_folder))
    if meta.source_site == paramountplus.NAME and meta.media_kind.casefold() == "episode":
        paramountplus_series_folder = paramountplus_show_folder(folder, meta)
        saved.extend(ensure_paramountplus_series_bundle(meta, paramountplus_series_folder))
    saved.extend(save_metadata_bundle_to_location(meta, folder, base_name, skip_existing=skip_existing))
    if meta.source_site == crunchyroll.NAME:
        crunchyroll_series_folder = crunchyroll_series_folder or crunchyroll_show_folder(folder, meta)
        saved.extend(save_crunchyroll_series_trailer(meta, crunchyroll_series_folder))
    if meta.source_site == disneyplus.NAME and meta.media_kind.casefold() in {"series", "episode"}:
        disneyplus_series_folder = disneyplus_series_folder or disneyplus_show_folder(folder, meta)
        trailer_meta = metadata_from_provider_dict(meta.series_metadata) if meta.series_metadata else meta
        saved.extend(save_disneyplus_series_trailer(trailer_meta, disneyplus_series_folder))
    if meta.source_site == hbomax.NAME and meta.media_kind.casefold() in {"movie", "series", "episode"}:
        trailer_folder = folder if meta.media_kind.casefold() == "movie" else (
            hbomax_series_folder or hbomax_show_folder(folder, meta)
        )
        trailer_meta = metadata_from_provider_dict(meta.series_metadata) if meta.series_metadata else meta
        saved.extend(save_hbomax_trailer(trailer_meta, trailer_folder))
        saved.extend(save_hbomax_extra_videos(trailer_meta, trailer_folder))
    if meta.source_site == paramountplus.NAME and meta.media_kind.casefold() in {"movie", "series", "episode"}:
        trailer_folder = folder if meta.media_kind.casefold() == "movie" else (
            paramountplus_series_folder or paramountplus_show_folder(folder, meta)
        )
        trailer_meta = metadata_from_provider_dict(meta.series_metadata) if meta.series_metadata else meta
        saved.extend(save_paramountplus_series_trailer(trailer_meta, trailer_folder))
        saved.extend(save_paramountplus_extra_videos(trailer_meta, trailer_folder))
    if meta.source_site == amazon.PRIME_NAME and meta.media_kind.casefold() in {"series", "episode"}:
        amazon_prime_series_folder = amazon_prime_series_folder or amazon_prime_show_folder(folder, meta)
        trailer_meta = amazon_prime_parent_series_meta(meta)
        saved.extend(save_amazon_prime_series_trailer(trailer_meta, amazon_prime_series_folder))
    if is_netflix_movie(meta) and meta.trailer_url:
        trailer_dir = folder / "trailers"
        trailer_dir.mkdir(parents=True, exist_ok=True)
        trailer = download_binary(meta.trailer_url, trailer_dir / "trailer.mp4")
        if trailer:
            saved.append(trailer)
    return saved


def save_metadata_bundle_to_location(
    meta: Metadata,
    folder: Path,
    base_name: str,
    skip_existing: bool = False,
    include_artwork: bool = True,
    artwork_base_name: str = "",
    filename_based_gallery: bool = False,
) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    if skip_existing and nfo_path(folder, base_name).exists():
        return []
    saved: list[Path] = []
    nfo = nfo_path(folder, base_name)
    nfo.write_text(build_nfo(meta), encoding="utf-8")
    saved.append(nfo)
    thumb_extension = image_extension_from_url(meta.thumb_url) or ".jpg"
    thumb_name = (
        f"thumb{thumb_extension}"
        if meta.media_kind.casefold() == "series" and base_name == "tvshow"
        else f"{base_name}-thumb{thumb_extension}"
    )
    thumb = download_binary(meta.thumb_url, folder / thumb_name)
    if thumb:
        saved.append(thumb)
    if not include_artwork:
        return saved
    disneyplus_movie_art = meta.source_site == disneyplus.NAME and meta.media_kind.casefold() == "movie"
    hbomax_movie_art = meta.source_site == hbomax.NAME and meta.media_kind.casefold() == "movie"
    paramountplus_movie_art = is_paramountplus_movie(meta)
    netflix_movie_art = is_netflix_movie(meta)
    if disneyplus_movie_art:
        saved.extend(save_disneyplus_show_art(meta, folder, base_name=base_name))
    if hbomax_movie_art:
        saved.extend(save_hbomax_show_art(meta, folder, base_name=base_name))
    if paramountplus_movie_art:
        saved.extend(save_paramountplus_movie_art(meta, folder, base_name))
    if netflix_movie_art:
        for artwork_type, url in (("poster", meta.poster_url), ("backdrop", meta.fanart_url)):
            if not clean_text(url):
                continue
            target = folder / f"{base_name}-{artwork_type}{image_extension_from_url(url) or '.jpg'}"
            if not target.exists():
                path = download_binary(url, target)
                if path:
                    saved.append(path)
    if meta.source_site == crunchyroll.NAME or (
        meta.source_site in {disneyplus.NAME, hbomax.NAME, paramountplus.NAME, pbs_kids.NAME, amazon.PRIME_NAME}
        and meta.media_kind.casefold() in {"series", "episode"}
    ):
        show_folder = folder
        if meta.media_kind.casefold() == "episode" and re.fullmatch(r"S\d{2}", folder.name, re.IGNORECASE):
            show_folder = folder.parent
        if meta.source_site == crunchyroll.NAME:
            saved.extend(save_crunchyroll_show_art(meta, show_folder))
        elif meta.source_site == amazon.PRIME_NAME:
            saved.extend(save_amazon_prime_show_art(meta, show_folder))
        elif meta.source_site == disneyplus.NAME:
            saved.extend(save_disneyplus_show_art(meta, show_folder))
        elif meta.source_site == hbomax.NAME:
            # The linked series bundle was already saved above. Never promote an
            # episode thumbnail into title-level artwork.
            if meta.media_kind.casefold() != "episode":
                saved.extend(save_hbomax_show_art(meta, show_folder))
        elif meta.source_site == pbs_kids.NAME:
            saved.extend(save_pbs_kids_show_art(meta, show_folder))
        else:
            saved.extend(save_paramountplus_show_art(meta, show_folder))
        return saved
    if hbomax_movie_art or paramountplus_movie_art or netflix_movie_art:
        return saved
    artwork_base = safe_filename(artwork_base_name) if artwork_base_name else base_name
    is_tvshow_bundle = meta.media_kind.casefold() == "series" and base_name == "tvshow" and not artwork_base_name

    poster_target = folder / ("poster.jpg" if is_tvshow_bundle else f"{artwork_base}-poster.jpg")
    poster = None if disneyplus_movie_art else download_binary(meta.poster_url, poster_target)
    if poster:
        saved.append(poster)
    fanart_target = folder / ("fanart.jpg" if is_tvshow_bundle else f"{artwork_base}-fanart.jpg")
    fanart = None if disneyplus_movie_art else download_binary(meta.fanart_url, fanart_target)
    if fanart:
        saved.append(fanart)
        for suffix in ("-banner.jpg", "-landscape.jpg"):
            duplicate = folder / (suffix.removeprefix("-") if is_tvshow_bundle else f"{artwork_base}{suffix}")
            if not duplicate.exists():
                shutil.copy2(fanart, duplicate)
            saved.append(duplicate)
    logo_extension = image_extension_from_url(meta.logo_url) or ".png"
    logo_target = folder / (f"logo{logo_extension}" if is_tvshow_bundle else f"{artwork_base}-logo{logo_extension}")
    logo = None if disneyplus_movie_art else download_binary(meta.logo_url, logo_target)
    if logo:
        saved.append(logo)

    if meta.gallery_urls:
        gallery_dir = folder / "extrafanart"
        gallery_dir.mkdir(parents=True, exist_ok=True)
        for index, url in enumerate(meta.gallery_urls, start=1):
            gallery_name = (
                f"{artwork_base}-fanart-{index:02d}.jpg"
                if filename_based_gallery
                else f"fanart-{index:02d}.jpg"
            )
            path = download_binary(url, gallery_dir / gallery_name)
            if path:
                saved.append(path)

    if meta.series_episodes and meta.source_site not in {paramountplus.NAME, crunchyroll.NAME}:
        episode_art_dir = folder / "Episode Artwork"
        for record in meta.series_episodes:
            image_url = clean_text(record.get("image"))
            season = clean_text(record.get("season"))
            episode = clean_text(record.get("episode"))
            title = clean_text(record.get("title"))
            if not (image_url and season.isdigit() and episode.isdigit() and title):
                continue
            name = safe_filename(
                f"S{int(season):02d}E{int(episode):02d} {meta.title} - {title}"
            ) + ".jpg"
            target = episode_art_dir / name
            if target.exists():
                saved.append(target)
                continue
            episode_art_dir.mkdir(parents=True, exist_ok=True)
            path = download_binary(image_url, target)
            if path:
                saved.append(path)

    if meta.trailer_url and meta.source_site != amazon.PRIME_NAME:
        trailer_dir = folder / (
            "trailers" if meta.source_site in {disneyplus.NAME, paramountplus.NAME} else "Extras/Trailers"
        )
        trailer_dir.mkdir(parents=True, exist_ok=True)
        trailer = download_binary(meta.trailer_url, trailer_dir / "trailer.mp4")
        if trailer:
            saved.append(trailer)

    if meta.extra_videos:
        extra_dir = folder / "Extras" / "Videos"
        extra_dir.mkdir(parents=True, exist_ok=True)
        for index, video in enumerate(meta.extra_videos, start=1):
            if not clean_text(video.url):
                continue
            name = safe_filename(video.title or f"extra-{index:02d}") + guess_media_extension(video.url)
            path = download_binary(video.url, extra_dir / name)
            if path:
                saved.append(path)
    return saved


def image_extension_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    requested_format = clean_text(urllib.parse.parse_qs(parsed.query).get("format", [""])[0]).casefold()
    if requested_format in {"jpg", "jpeg", "png", "webp"}:
        return ".jpg" if requested_format == "jpeg" else f".{requested_format}"
    path = parsed.path
    suffix = Path(path).suffix.casefold()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ""


def guess_media_extension(url: str) -> str:
    if is_public_hls_url(url) or is_public_dash_url(url):
        return ".mp4"
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix
    return suffix if suffix else ".mp4"


def download_binary(url: str, target: Path) -> Path | None:
    text = clean_text(url)
    if not text:
        return None
    if is_public_hls_url(text):
        return download_public_hls(text, target)
    if is_public_dash_url(text):
        return download_public_dash(text, target)
    data = fetch_bytes(text)
    if data is None:
        return None
    target.write_bytes(data)
    return target


def is_public_hls_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.path.casefold().endswith(".m3u8") or parsed.netloc.casefold().endswith("splice.paramountplus.com")


def is_public_dash_url(url: str) -> bool:
    return urllib.parse.urlparse(url).path.casefold().endswith(".mpd")


def download_public_hls(url: str, target: Path) -> Path | None:
    """Save an explicitly public, unencrypted HLS preview without keys or DRM tooling."""
    manifest = fetch_bytes(url)
    if not manifest or b"#EXTM3U" not in manifest or b"#EXT-X-KEY" in manifest:
        return None
    command = [
        "ffmpeg", "-nostdin", "-y", "-i", url, "-map", "0:v?", "-map", "0:a?", "-c", "copy", str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=900)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        target.unlink(missing_ok=True)
        return None
    if result.returncode != 0:
        target.unlink(missing_ok=True)
    return target if result.returncode == 0 and target.exists() and target.stat().st_size else None


def download_public_dash(url: str, target: Path) -> Path | None:
    """Save a public DASH clip only when its manifest declares no protection."""
    manifest = fetch_bytes(url)
    if not manifest or b"<MPD" not in manifest or b"ContentProtection" in manifest or b"pssh" in manifest:
        return None
    command = [
        "ffmpeg", "-nostdin", "-y", "-i", url, "-map", "0:v?", "-map", "0:a?", "-c", "copy", str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=False, timeout=900)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        target.unlink(missing_ok=True)
        return None
    if result.returncode != 0:
        target.unlink(missing_ok=True)
    return target if result.returncode == 0 and target.exists() and target.stat().st_size else None


def fetch_bytes(url: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except Exception:
        command = [
            "/usr/bin/curl",
            "--location",
            "--silent",
            "--show-error",
            "--compressed",
            "--max-time",
            str(HTTP_TIMEOUT_SECONDS),
            "--user-agent",
            USER_AGENT,
            url,
        ]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode == 0:
            return result.stdout
    return None


def build_nfo(meta: Metadata) -> str:
    is_episode = meta.media_kind.casefold() == "episode"
    is_series = meta.media_kind.casefold() == "series"
    root = ET.Element("episodedetails" if is_episode else "tvshow" if is_series else "movie")
    add_xml(root, "title", meta.episode_title if is_episode else meta.title)
    if is_episode:
        add_xml(root, "showtitle", meta.show_title or meta.title)
        add_xml(root, "season", meta.season_number)
        add_xml(root, "episode", meta.episode_number)
    add_xml(root, "originaltitle", meta.original_title)
    add_xml(root, "sorttitle", meta.sort_title)
    add_xml(root, "outline", meta.outline)
    add_xml(root, "plot", meta.plot)
    add_xml(root, "tagline", meta.tagline)
    add_xml(root, "year", meta.year)
    add_xml(root, "premiered", meta.date)
    add_xml(root, "releasedate", meta.date)
    add_xml(root, "runtime", meta.runtime_minutes)
    add_xml(root, "rating", meta.numeric_rating)
    add_xml(root, "mpaa", meta.content_rating)
    add_xml(root, "language", meta.language)
    add_xml(root, "studio", join_list(meta.studios))
    add_xml(root, "source", meta.source_site)
    add_xml(root, "detailpage", meta.detail_link)
    add_xml(root, "website", meta.source_url)

    for genre in meta.genres:
        add_xml(root, "genre", genre)
    for tag in meta.tags:
        add_xml(root, "tag", tag)
    for country in meta.countries:
        add_xml(root, "country", country)
    for director in meta.directors:
        add_xml(root, "director", director)
    for writer in meta.writers:
        add_xml(root, "credits", writer)
    for credit in meta.credits:
        add_xml(root, "credits", credit)
    for actor in meta.actors:
        actor_node = ET.SubElement(root, "actor")
        add_xml(actor_node, "name", actor.name)
        add_xml(actor_node, "role", actor.role)
    for provider, value in meta.unique_ids.items():
        uniqueid = ET.SubElement(root, "uniqueid", {"type": provider, "default": "false"})
        uniqueid.text = value
    for label in sorted(meta.extra_fields, key=str.casefold):
        for value in meta.extra_fields[label]:
            field = ET.SubElement(root, "customfield")
            add_xml(field, "label", label)
            add_xml(field, "value", value)
    xml_text = ET.tostring(root, encoding="unicode")
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + xml_text + "\n"


def add_xml(parent: ET.Element, tag: str, value: str) -> None:
    text = clean_text(value)
    if not text:
        return
    node = ET.SubElement(parent, tag)
    node.text = text


def parse_link_entries(text: str) -> list[str]:
    return re.findall(r"https?://\S+", text)


def read_mylinks_file() -> list[str]:
    path = repo_root() / "My Links Txt" / "mylinks.txt"
    if not path.exists():
        return []
    return parse_link_entries(path.read_text(encoding="utf-8", errors="replace"))


def print_welcome() -> None:
    print()
    print(f"Welcome to {TOOL_NAME}")
    print()
    print(
        "This tool scrapes publicly available information on supported video detail pages and "
        "turns it into a local .nfo metadata bundle. It is prepared for Jellyfin-style naming "
        "but can also support other media-library workflows that use local NFO files and artwork."
    )
    print()


def choose_link_mode() -> list[str]:
    print("Would you like to import your mylinks.txt or manually insert links here?")
    print("1. Import your mylinks.txt")
    print("2. Manually insert links here")
    while True:
        choice = input("Choose 1 or 2: ").strip()
        if choice == "1":
            return read_mylinks_file()
        if choice == "2":
            return read_manual_links()
        print("Please choose 1 or 2.")


def read_manual_links() -> list[str]:
    links: list[str] = []
    while True:
        link = clean_text(input("Paste your detail page link: "))
        if link:
            links.append(link)
        again = input("Would you like to paste another link? [Y/N]: ").strip().upper()
        if again != "Y":
            break
    return links


def process_import_links(links: list[str], settings: dict[str, Any]) -> None:
    if not links:
        print("No links were found.")
        return
    folders_saved = 0
    items_saved = 0
    for link in links:
        print(f"\nChecking {link} ...")
        try:
            with AnimatedStatus("Creating your .nfo file and grabbing your trailer/images"):
                meta = scrape_url(link)
                saved = save_provider_series_metadata(meta, link, settings)
                if saved is None:
                    saved = save_metadata_bundle(meta, settings)
        except UnsupportedProviderError as exc:
            print(str(exc))
            continue
        except Exception as exc:
            print(f"Could not scrape {link}: {exc}")
            continue
        if saved:
            folders_saved += 1
            items_saved += len(saved)
    print(
        f"\nDone. Saved {folders_saved} folder(s) with {items_saved} item(s) total."
    )


def process_manual_links(links: list[str], settings: dict[str, Any]) -> None:
    folders_saved = 0
    items_saved = 0
    for link in links:
        print(f"\nChecking {link} ...")
        try:
            meta = scrape_url(link)
        except UnsupportedProviderError as exc:
            print(str(exc))
            continue
        except Exception as exc:
            print(f"Could not scrape {link}: {exc}")
            continue
        print(format_preview(meta))
        choice = input("Save this .nfo file? [Y/n]: ").strip().lower()
        if choice not in {"", "y", "yes"}:
            continue
        try:
            with AnimatedStatus("Creating your .nfo file and grabbing your trailer/images"):
                saved = save_provider_series_metadata(meta, link, settings)
                if saved is None:
                    saved = save_metadata_bundle(meta, settings)
        except Exception as exc:
            print(f"Could not save {link}: {exc}")
            continue
        if saved:
            folders_saved += 1
            items_saved += len(saved)
    print(
        f"\nDone. Saved {folders_saved} folder(s) with {items_saved} item(s) total."
    )


def run_handoff(args: argparse.Namespace, settings: dict[str, Any]) -> int:
    detail_link = clean_text(args.detail_link)
    if not detail_link:
        print("A detail link is required for --handoff.")
        return 1
    try:
        with AnimatedStatus("Creating your .nfo file and grabbing your trailer/images"):
            meta = scrape_url(detail_link)
            saved = save_provider_series_metadata(
                meta,
                detail_link,
                settings,
                skip_existing=bool(args.skip_existing),
                explicit_folder=clean_text(args.media_folder),
            )
            if saved is None:
                saved = save_metadata_bundle(
                    meta,
                    settings,
                    explicit_folder=clean_text(args.media_folder),
                    skip_existing=bool(args.skip_existing),
                )
    except UnsupportedProviderError as exc:
        print(str(exc))
        return 1
    except Exception as exc:
        print(f"Could not scrape {detail_link}: {exc}")
        return 1
    if not saved and args.skip_existing:
        print("Skipped because matching metadata already exists.")
        return 0
    print(f"Saved {len(saved)} item(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--handoff", action="store_true")
    parser.add_argument("--detail-link", default="")
    parser.add_argument("--media-folder", default="")
    parser.add_argument("--skip-existing", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = load_settings()
    if args.handoff:
        return run_handoff(args, settings)

    print_welcome()
    links = choose_link_mode()
    if not links:
        print("No links were found.")
        return 0
    if len(links) == 1:
        process_manual_links(links, settings)
        return 0
    if links == read_mylinks_file():
        process_import_links(links, settings)
    else:
        process_manual_links(links, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
