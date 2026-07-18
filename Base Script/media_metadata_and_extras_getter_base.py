#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any


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
    title: str = ""
    original_title: str = ""
    sort_title: str = ""
    plot: str = ""
    outline: str = ""
    tagline: str = ""
    year: str = ""
    date: str = ""
    runtime_minutes: str = ""
    content_rating: str = ""
    numeric_rating: str = ""
    language: str = ""
    poster_url: str = ""
    fanart_url: str = ""
    logo_url: str = ""
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

PROVIDER_HANDLERS = [
    ("amazon", amazon.NAME, amazon.is_supported_url),
    ("netflix", netflix.NAME, netflix.is_supported_url),
    ("disneyplus", disneyplus.NAME, disneyplus.is_supported_url),
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
    meta.title = clean_text(item.get("title"))
    meta.original_title = clean_text(item.get("original_title"))
    meta.sort_title = clean_text(item.get("sort_title"))
    meta.plot = clean_text(item.get("plot"))
    meta.outline = clean_text(item.get("outline")) or meta.plot
    meta.tagline = clean_text(item.get("tagline"))
    meta.year = clean_text(item.get("year"))
    meta.date = clean_text(item.get("date"))
    meta.runtime_minutes = clean_text(item.get("runtime_minutes"))
    meta.content_rating = clean_text(item.get("content_rating"))
    meta.numeric_rating = clean_text(item.get("numeric_rating"))
    meta.language = clean_text(item.get("language"))
    meta.poster_url = clean_text(item.get("poster_url"))
    meta.fanart_url = clean_text(item.get("fanart_url"))
    meta.logo_url = clean_text(item.get("logo_url"))
    meta.trailer_url = clean_text(item.get("trailer_url"))
    meta.production_label = clean_text(item.get("production_label")) or meta.production_label
    meta.folder_name_override = clean_text(item.get("folder_name_override"))
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
    item = disneyplus.extract_metadata(url, timeout=HTTP_TIMEOUT_SECONDS)
    meta = Metadata(source_url=clean_text(item.source_url) or detail_link, detail_link=detail_link)
    meta.source_site = clean_text(item.NAME if hasattr(item, "NAME") else "Disney+")
    meta.title = clean_text(item.title)
    meta.folder_name_override = clean_text(item.title)
    meta.outline = clean_text(item.short_description or item.long_description)
    meta.plot = clean_text(item.long_description or item.short_description)
    meta.year = clean_text(item.year)
    meta.runtime_minutes = clean_text(item.runtime_minutes)
    meta.content_rating = clean_text(item.content_rating)
    meta.poster_url = clean_text(item.poster_url)
    meta.fanart_url = clean_text(item.wide_url)
    meta.logo_url = clean_text(item.logo_url)
    meta.trailer_url = clean_text(item.trailer_url)
    meta.production_label = "Provider"
    meta.add_values("genres", item.genres)
    meta.add_values("studios", [disneyplus.STUDIO_NAME])
    meta.add_values("directors", item.directors)
    meta.actors = [Actor(name=clean_text(name)) for name in item.cast if clean_text(name)]
    if clean_text(item.entity_id):
        meta.unique_ids["disneyplus"] = clean_text(item.entity_id)
        meta.add_extra("Disney+ Entity ID", item.entity_id)
    if clean_text(item.category):
        meta.add_extra("Category", item.category)
    clean_final_metadata(meta)
    return meta


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
        ("Cover Art", found_status(meta.poster_url)),
        ("Wide Art", wide_art_status(meta.fanart_url)),
        ("Logo", found_status(meta.logo_url)),
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


def default_folder_name(meta: Metadata) -> str:
    if meta.folder_name_override:
        return safe_filename(meta.folder_name_override)
    if meta.studios and meta.source_site.casefold() != "netflix":
        return safe_filename(f"{meta.title} - {meta.studios[0]}")
    return safe_filename(meta.title)


def maybe_rename_generic_video(match: MediaMatch, meta: Metadata, settings: dict[str, Any]) -> MediaMatch:
    if not settings.get("rename_generic_video_filenames"):
        return match
    if not match.video_path.exists():
        return match
    stem = match.video_path.stem
    if not re.fullmatch(r"master-[a-f0-9-]+(?:_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})?", stem):
        return match
    new_base = safe_filename(meta.folder_name_override or meta.title)
    new_path = match.video_path.with_name(new_base + match.video_path.suffix)
    if new_path.exists():
        return match
    match.video_path.rename(new_path)
    return MediaMatch(folder=match.folder, video_path=new_path, filename_base=new_base, score=match.score)


def output_plan(meta: Metadata, settings: dict[str, Any], explicit_folder: str = "") -> tuple[Path, str]:
    match = find_media_match(meta, settings, explicit_folder=explicit_folder)
    if match:
        match = maybe_rename_generic_video(match, meta, settings)
        return match.folder, match.filename_base
    folder = settings_output_dir(settings) / default_folder_name(meta)
    return folder, safe_filename(meta.folder_name_override or meta.title)


def nfo_path(folder: Path, base_name: str) -> Path:
    return folder / f"{base_name}.nfo"


def save_metadata_bundle(meta: Metadata, settings: dict[str, Any], explicit_folder: str = "", skip_existing: bool = False) -> list[Path]:
    folder, base_name = output_plan(meta, settings, explicit_folder=explicit_folder)
    folder.mkdir(parents=True, exist_ok=True)
    if skip_existing and nfo_path(folder, base_name).exists():
        return []
    saved: list[Path] = []
    nfo = nfo_path(folder, base_name)
    nfo.write_text(build_nfo(meta), encoding="utf-8")
    saved.append(nfo)

    poster = download_binary(meta.poster_url, folder / f"{base_name}-poster.jpg")
    if poster:
        saved.append(poster)
    fanart = download_binary(meta.fanart_url, folder / f"{base_name}-fanart.jpg")
    if fanart:
        saved.append(fanart)
        for suffix in ("-banner.jpg", "-landscape.jpg"):
            duplicate = folder / f"{base_name}{suffix}"
            if not duplicate.exists():
                shutil.copy2(fanart, duplicate)
            saved.append(duplicate)
    logo_extension = image_extension_from_url(meta.logo_url) or ".png"
    logo = download_binary(meta.logo_url, folder / f"{base_name}-logo{logo_extension}")
    if logo:
        saved.append(logo)

    if meta.gallery_urls:
        gallery_dir = folder / "extrafanart"
        gallery_dir.mkdir(parents=True, exist_ok=True)
        for index, url in enumerate(meta.gallery_urls, start=1):
            path = download_binary(url, gallery_dir / f"fanart-{index:02d}.jpg")
            if path:
                saved.append(path)

    if meta.trailer_url:
        trailer_dir = folder / "Extras" / "Trailers"
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
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.casefold()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ""


def guess_media_extension(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix
    return suffix if suffix else ".mp4"


def download_binary(url: str, target: Path) -> Path | None:
    text = clean_text(url)
    if not text:
        return None
    data = fetch_bytes(text)
    if data is None:
        return None
    target.write_bytes(data)
    return target


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
    root = ET.Element("movie")
    add_xml(root, "title", meta.title)
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
