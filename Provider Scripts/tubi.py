#!/usr/bin/env python3
"""Public Tubi movie, series, and episode metadata helpers."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import subprocess
import urllib.parse
import urllib.request
import uuid
from typing import Any


NAME = "Tubi"
STUDIO_NAME = "Tubi"
PAGE_HOSTS = {"tubitv.com", "www.tubitv.com"}
ACCOUNT_ROOT = "https://account.production-public.tubi.io"
CONTENT_ROOT = "https://content-cdn.production-public.tubi.io/api/v3"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


def is_supported_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    if parsed.netloc.casefold() not in PAGE_HOSTS:
        return False
    return bool(re.search(r"/(?:[a-z]{2}-[a-z]{2}/)?(?:movies|tv-shows|series)/(\d+)", parsed.path, re.I))


def content_id_from_url(url: str) -> str:
    match = re.search(r"/(?:[a-z]{2}-[a-z]{2}/)?(?:movies|tv-shows|series)/(\d+)", urllib.parse.urlparse(url).path, re.I)
    return match.group(1) if match else ""


def canonical_episode_url(record: dict[str, Any]) -> str:
    identifier = clean_text(record.get("id"))
    season = integer(record.get("season"))
    episode = integer(record.get("episode"))
    title = slug(clean_text(record.get("title")))
    suffix = f"/s{season:02d}-e{episode:02d}-{title}" if season and episode and title else ""
    return f"https://tubitv.com/tv-shows/{identifier}{suffix}"


def canonical_series_url(identifier: Any, title: str = "") -> str:
    suffix = f"/{slug(title)}" if clean_text(title) else ""
    return f"https://tubitv.com/series/{clean_text(identifier)}{suffix}"


def extract_metadata(url: str, timeout: int = 25) -> dict[str, Any]:
    if not is_supported_url(url):
        raise ValueError("Tubi links need a movie, series, or TV-show episode URL.")
    identifier = content_id_from_url(url)
    client = GuestClient(timeout=timeout)
    selected = client.content(identifier)
    kind = clean_text(selected.get("detailed_type")).casefold()
    if kind == "episode" or clean_text(selected.get("series_id")):
        series_id = clean_text(selected.get("series_id"))
        if not series_id:
            raise ValueError("Tubi episode metadata did not expose its parent series ID.")
        series_item = client.content(series_id)
        guide = client.series_guide(series_id)
        records = guide_records(guide)
        selected_id = clean_text(selected.get("id"))
        record = next((item for item in records if clean_text(item.get("id")) == selected_id), None)
        if not record:
            raise ValueError("Tubi's complete series guide did not contain the selected episode ID.")
        record.update(episode_record(selected, int(record["season"]), int(record["episode"])))
        series = series_metadata(series_item, records, canonical_series_url(series_id, clean_text(series_item.get("title"))))
        return episode_metadata(series, record, url)
    if kind == "series" or selected.get("children"):
        guide = client.series_guide(identifier)
        records = guide_records(guide)
        return series_metadata(selected, records, url)
    return movie_metadata(selected, url)


class GuestClient:
    def __init__(self, timeout: int = 25):
        self.timeout = timeout
        self.device_id = str(uuid.uuid4())
        self.access_token = self._guest_token()

    def _guest_token(self) -> str:
        verifier = secrets.token_hex(16)
        challenge = base64.b64encode(hashlib.sha256(verifier.encode()).digest()).decode().translate(str.maketrans("+/", "-_"))
        signing = request_json(
            f"{ACCOUNT_ROOT}/device/anonymous/signing_key", self.timeout,
            data={"challenge": challenge, "version": "1.0.0", "platform": "web", "device_id": self.device_id},
        )
        signing_id = clean_text(signing.get("id"))
        signing_key = clean_text(signing.get("key"))
        if not signing_id or not signing_key:
            raise RuntimeError("Tubi did not issue an anonymous metadata signing key.")
        body = {"verifier": verifier, "id": signing_id, "platform": "web", "device_id": self.device_id}
        raw = json.dumps(body, separators=(",", ":")).encode()
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        canonical = "POST\n/device/anonymous/token\n\ncontent-type:application/json\n\ncontent-type\n" + hashlib.sha256(raw).hexdigest()
        string_to_sign = "TUBI-HMAC-SHA256\n" + stamp + "\n" + hashlib.sha256(canonical.encode()).hexdigest()
        date_key = hmac.new(b"TUBI" + base64.b64decode(signing_key), stamp[:8].encode(), hashlib.sha256).digest()
        request_key = hmac.new(date_key, b"tubi_request", hashlib.sha256).digest()
        signature = hmac.new(request_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        query = urllib.parse.urlencode({
            "X-Tubi-Algorithm": "TUBI-HMAC-SHA256", "X-Tubi-Date": stamp,
            "X-Tubi-Expires": "30", "X-Tubi-SignedHeaders": "content-type",
            "X-Tubi-Signature": signature,
        })
        token = request_json(f"{ACCOUNT_ROOT}/device/anonymous/token?{query}", self.timeout, data=body)
        access_token = clean_text(token.get("access_token"))
        if not access_token:
            raise RuntimeError("Tubi did not issue an anonymous metadata token.")
        return access_token

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params, doseq=True)
        return request_json(
            f"{CONTENT_ROOT}{path}?{query}", self.timeout,
            headers={"Authorization": f"Bearer {self.access_token}", "Accept-Version": "~5.0.0", "x-capability": '{"content_types":["se"]}'},
        )

    def content(self, identifier: str) -> dict[str, Any]:
        item = self.get("/content", {
            "app_id": "tubitv", "platform": "web", "content_id": identifier,
            "device_id": self.device_id, "include_channels": "true",
            "images[posterarts]": "w408h583_poster", "images[hero_16x9]": "w1280h720_hero",
            "images[backgrounds]": "w1614h906_background", "images[title_art]": "w430h180_title",
        })
        if not isinstance(item, dict) or not clean_text(item.get("id")):
            raise ValueError(f"Tubi did not expose public metadata for content ID {identifier}.")
        return item

    def series_guide(self, series_id: str) -> dict[str, Any]:
        guide = self.get(f"/series/{series_id}/episodes", {"platform": "web"})
        if not isinstance(guide, dict) or clean_text(guide.get("series_id")) != clean_text(series_id):
            raise ValueError("Tubi did not expose a provider-confirmed series guide.")
        return guide


def guide_records(guide: dict[str, Any]) -> list[dict[str, Any]]:
    groups = guide.get("episodes_by_season")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Tubi did not expose any provider-confirmed seasons.")
    records: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Tubi exposed a malformed season in its series guide.")
        season = integer(group.get("season"))
        episodes = group.get("episodes")
        if not season or not isinstance(episodes, list) or not episodes:
            raise ValueError(f"Tubi exposed an incomplete Season {season or '?'} guide.")
        for item in episodes:
            identifier = clean_text(item.get("id")) if isinstance(item, dict) else ""
            number = integer(item.get("num")) if isinstance(item, dict) else 0
            if not identifier or not number:
                raise ValueError(f"Tubi exposed an incomplete episode identity in Season {season}.")
            records.append({"id": identifier, "season": season, "episode": number, "title": "", "description": "", "duration": "", "date": "", "image": ""})
    identities = {(item["season"], item["episode"]) for item in records}
    ids = {item["id"] for item in records}
    if len(identities) != len(records) or len(ids) != len(records):
        raise ValueError("Tubi exposed duplicate episode identities; refusing an ambiguous catalog.")
    return sorted(records, key=lambda item: (item["season"], item["episode"]))


def episode_record(item: dict[str, Any], season: int, episode: int) -> dict[str, Any]:
    title = clean_text(item.get("title"))
    title = re.sub(r"^S\d+\s*:\s*E\d+\s*-\s*", "", title, flags=re.I)
    return {
        "id": clean_text(item.get("id")), "season": season, "episode": episode, "title": title,
        "description": clean_text(item.get("description")), "duration": clean_text(item.get("duration")),
        "date": clean_text(item.get("air_datetime"))[:10], "image": first_image(item, "thumbnails", "hero_16x9", "landscape_images"),
        "url": "",
        "content_rating": first_rating(item.get("ratings")), "year": clean_text(item.get("year")),
        "language": clean_text(item.get("lang")), "genres": text_list(item.get("tags")),
        "actors": text_list(item.get("actors")), "countries": text_list(item.get("country")),
    }


def series_metadata(item: dict[str, Any], records: list[dict[str, Any]], source_url: str) -> dict[str, Any]:
    title = clean_text(item.get("title"))
    year = clean_text(item.get("year"))
    fields: dict[str, list[str]] = {"Tubi series ID": [clean_text(item.get("id"))], "Season count": [str(len({r['season'] for r in records}))], "Episode count": [str(len(records))]}
    return common_metadata(item, source_url) | {
        "media_kind": "series", "title": title, "show_title": title,
        "year": year, "series_start_year": year, "series_end_year": year,
        "series_is_current": False, "unique_ids": {"tubi": clean_text(item.get("id"))},
        "extra_fields": fields, "series_episodes": records, "folder_name_override": title,
    }


def episode_metadata(series: dict[str, Any], record: dict[str, Any], source_url: str) -> dict[str, Any]:
    result = dict(series)
    result.update({
        "source_url": source_url, "media_kind": "episode", "title": series["title"], "show_title": series["title"],
        "season_number": str(record["season"]), "episode_number": str(record["episode"]),
        "episode_title": clean_text(record.get("title")), "plot": clean_text(record.get("description")),
        "outline": clean_text(record.get("description")), "runtime_minutes": minutes(record.get("duration")),
        "date": clean_text(record.get("date")), "thumb_url": clean_text(record.get("image")),
        "year": clean_text(record.get("year")) or series.get("year", ""),
        "content_rating": clean_text(record.get("content_rating")) or series.get("content_rating", ""),
        "language": clean_text(record.get("language")) or series.get("language", ""),
        "genres": text_list(record.get("genres")) or series.get("genres", []),
        "countries": text_list(record.get("countries")) or series.get("countries", []),
        "actors": [{"name": name, "role": ""} for name in text_list(record.get("actors"))] or series.get("actors", []),
        "poster_url": "", "fanart_url": first_image(series, "fanart_url"), "logo_url": "",
        "unique_ids": {"tubi": clean_text(record.get("id"))},
        "extra_fields": {"Tubi series ID": [clean_text(series.get("unique_ids", {}).get("tubi"))], "Tubi episode ID": [clean_text(record.get("id"))]},
        "series_metadata": series,
    })
    record["url"] = canonical_episode_url(record)
    return result


def movie_metadata(item: dict[str, Any], source_url: str) -> dict[str, Any]:
    result = common_metadata(item, source_url)
    result.update({"media_kind": "movie", "unique_ids": {"tubi": clean_text(item.get("id"))}, "extra_fields": {"Tubi movie ID": [clean_text(item.get("id"))]}})
    return result


def common_metadata(item: dict[str, Any], source_url: str) -> dict[str, Any]:
    rating = first_rating(item.get("ratings"))
    title = clean_text(item.get("title"))
    return {
        "source_url": source_url, "source_site": NAME, "title": title,
        "outline": clean_text(item.get("description")), "plot": clean_text(item.get("description")),
        "year": clean_text(item.get("year")), "runtime_minutes": minutes(item.get("duration")),
        "content_rating": rating, "language": clean_text(item.get("lang")),
        "poster_url": first_image(item, "posterarts"),
        "fanart_url": first_image(item, "backgrounds", "hero_images", "landscape_images"),
        "thumb_url": first_image(item, "thumbnails", "hero_images", "landscape_images"),
        "logo_url": first_image(item, "title_art"), "production_label": "Provider",
        "genres": text_list(item.get("tags")), "tags": [NAME, "Provider: Tubi", "Tubi Provider"],
        "studios": [], "countries": text_list(item.get("country")), "directors": text_list(item.get("directors")),
        "actors": [{"name": value, "role": ""} for value in text_list(item.get("actors"))],
        "gallery_urls": [], "trailer_url": "", "extra_videos": [],
    }


def request_json(url: str, timeout: int, data: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(data, separators=(",", ":")).encode() if data is not None else None
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Origin": "https://tubitv.com", **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
            return value if isinstance(value, dict) else {}
    except Exception:
        command = ["/usr/bin/curl", "--location", "--fail", "--silent", "--show-error", "--compressed", "--max-time", str(timeout), "--user-agent", USER_AGENT]
        for key, value in request_headers.items():
            if key.casefold() != "user-agent":
                command.extend(["--header", f"{key}: {value}"])
        if body is not None:
            command.extend(["--data-binary", body.decode()])
        command.append(url)
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 10, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Tubi returned an empty metadata response.")
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else {}


def first_image(item: Any, *keys: str) -> str:
    if not isinstance(item, dict):
        return ""
    nested = item.get("images") if isinstance(item.get("images"), dict) else {}
    for key in keys:
        value = item.get(key) or nested.get(key)
        if isinstance(value, list) and value and clean_text(value[0]):
            return clean_text(value[0])
        if clean_text(value):
            return clean_text(value)
    return ""


def first_rating(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and clean_text(item.get("code") or item.get("value")):
                return clean_text(item.get("code") or item.get("value"))
    return ""


def text_list(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return list(dict.fromkeys(clean_text(item) for item in values if clean_text(item)))


def minutes(value: Any) -> str:
    number = integer(value)
    return str(max(1, round(number / 60))) if number else ""


def integer(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean_text(value).casefold()).strip("-")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
