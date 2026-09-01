from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERIES_URL = "https://pbskids.org/videos/wild-kratts"
PLAYLIST_URL = "https://pbskids.org/videos/playlist/wild-kratts-full-episodes/1385807"
WATCH_URL = "https://pbskids.org/videos/watch/wild-kratts-full-episodes/1385807/duck-duck-loon/2756856"
SECOND_WATCH_URL = "https://pbskids.org/videos/watch/wild-kratts-full-episodes/1385807/butternut-tree/2703471"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pbs = load_module("test_pbs_kids_provider", ROOT / "Provider Scripts" / "pbs_kids.py")
base = load_module("test_pbs_kids_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")


PROPERTY = {
    "id": "1310964",
    "guid": "a3605d94-a8e8-11e5-8e9a-0ac638653743",
    "slug": "wild-kratts",
    "title": "Wild Kratts",
    "nolaRoot": "WILK",
    "productionCopyrightNotice": "Wild Kratts copyright notice.",
    "logo": [{"url": "https://img.example/wild-kratts-logo.png", "width": 498, "height": 480}],
    "mezzanine": [{"url": "https://img.example/wild-kratts-card.jpg", "width": 908, "height": 510}],
    "theme": [{"backgroundImage": [{"url": "https://img.example/unused-theme.jpg"}]}],
    "sponsors": [{"imageAltText": "Corporation for Public Broadcasting"}],
}


def entry(video_id: str, guid: str, legacy: str, slug: str, title: str, premiered: int):
    return {
        "id": video_id,
        "guid": guid,
        "slug": slug,
        "title": title,
        "videoType": "fullEpisode",
        "mediaManagerAsset": {
            "legacy_tp_media_id": legacy,
            "description_short": f"Short description for {title}.",
            "duration": 1585,
            "premiered_on": str(premiered),
            "images": [{"profile": "asset-kids-mezzanine1-16x9", "image": f"https://img.example/{video_id}.png"}],
        },
        "properties": [PROPERTY],
    }


ENTRIES = [
    entry("2756856", "1d759e7d-1e5d-4f97-aa3b-65248f351baf", "3111889207", "duck-duck-loon", "Duck, Duck, Loon!", 1784505600),
    entry("2703471", "8fa2a533-3b7d-40bb-ad69-e8bdaabb3931", "3109489420", "butternut-tree", "Butternut Tree", 1776643200),
]


COLLECTION = {
    "id": "1385807",
    "slug": "wild-kratts-full-episodes",
    "title": "Full Episodes",
    "entries": ENTRIES,
    "properties": [PROPERTY],
}


def next_page(page_props: dict):
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": page_props}})}</script>'


def series_page():
    return next_page({
        "pageTitle": "Watch Wild Kratts Videos",
        "pageDescription": "Join Chris and Martin as they encounter incredible wild animals.",
        "pageProperty": PROPERTY,
        "pageData": {
            "bodyContentModules": [{
                "__typename": "BodyContentModulesVideoPlaylist",
                "heading": "Episodes",
                "collection": [COLLECTION],
            }]
        },
    })


def playlist_page():
    return next_page({"collectionData": COLLECTION, "pageProperty": PROPERTY})


def watch_page(item: dict, season: int, episode_number: int, long_description: str):
    media = dict(item["mediaManagerAsset"])
    media.update({
        "id": item["guid"],
        "title": item["title"],
        "description_long": long_description,
        "season_number": season,
        "episode_number": episode_number,
        "drm_enabled": False,
    })
    video = {
        "id": item["id"],
        "slug": item["slug"],
        "title": item["title"],
        "videoType": "fullEpisode",
        "dateCreated": 1783000888,
        "expiryDate": 1788494400,
        "mediaManagerAsset": media,
        "properties": [PROPERTY],
    }
    return next_page({
        "videoData": video,
        "videoDescription": item["mediaManagerAsset"]["description_short"],
        "contextData": {"id": COLLECTION["id"], "slug": COLLECTION["slug"]},
        "pageProperty": PROPERTY,
    })


PAGES = {
    SERIES_URL: series_page(),
    PLAYLIST_URL: playlist_page(),
    WATCH_URL: watch_page(ENTRIES[0], 7, 17, "Long description for Duck, Duck, Loon! with considerably more detail."),
    SECOND_WATCH_URL: watch_page(ENTRIES[1], 7, 16, "Long description for Butternut Tree with considerably more detail."),
}


class PBSKidsProviderTests(unittest.TestCase):
    def extract(self, url: str):
        with patch.object(pbs, "fetch_text", side_effect=lambda page_url, timeout=25: PAGES[page_url]):
            return pbs.extract_metadata(url)

    def test_all_three_url_types_resolve_same_complete_current_episode_guide(self):
        for url in (SERIES_URL, PLAYLIST_URL, WATCH_URL):
            item = self.extract(url)
            guide = item["series_metadata"]["series_episodes"] if item["media_kind"] == "episode" else item["series_episodes"]
            self.assertEqual(
                [(record["season"], record["episode"], record["title"]) for record in guide],
                [(7, 16, "Butternut Tree"), (7, 17, "Duck, Duck, Loon!")],
            )

    def test_watch_page_maps_requested_episode_fields_to_jellyfin(self):
        item = self.extract(WATCH_URL)
        self.assertEqual(item["media_kind"], "episode")
        self.assertEqual(item["show_title"], "Wild Kratts")
        self.assertEqual(item["episode_title"], "Duck, Duck, Loon!")
        self.assertEqual((item["season_number"], item["episode_number"]), ("7", "17"))
        self.assertEqual(item["outline"], "Short description for Duck, Duck, Loon!.")
        self.assertIn("considerably more detail", item["plot"])
        self.assertEqual(item["runtime_minutes"], "26")
        self.assertEqual(item["date"], "2026-07-20")
        self.assertEqual(item["thumb_url"], "https://img.example/2756856.png")
        self.assertEqual(item["extra_fields"]["PBS KIDS video ID"], ["2756856"])
        self.assertEqual(item["extra_fields"]["Legacy PBS media ID"], ["3111889207"])
        self.assertEqual(item["extra_fields"]["Video type"], ["Full Episode"])
        self.assertEqual(item["extra_fields"]["Runtime seconds"], ["1585"])
        self.assertEqual(set(item["extra_fields"]), {
            "PBS KIDS video ID", "Legacy PBS media ID", "Video type", "Runtime seconds"
        })
        self.assertEqual(set(item["unique_ids"]), {"pbskids", "pbs"})
        self.assertIn("PBS KIDS Provider", item["tags"])
        nfo = ET.fromstring(base.build_nfo(base.metadata_from_provider_dict(item)))
        self.assertEqual(nfo.tag, "episodedetails")
        self.assertEqual(nfo.findtext("outline"), "Short description for Duck, Duck, Loon!.")
        self.assertIn("considerably more detail", nfo.findtext("plot"))
        self.assertEqual(nfo.findtext("premiered"), "2026-07-20")

    def test_series_uses_only_requested_logo_and_card_art(self):
        item = self.extract(SERIES_URL)
        self.assertEqual(item["plot"], "Join Chris and Martin as they encounter incredible wild animals.")
        self.assertEqual(item["logo_url"], "https://img.example/wild-kratts-logo.png")
        self.assertEqual(item["thumb_url"], "https://img.example/wild-kratts-card.jpg")
        self.assertEqual(item.get("poster_url", ""), "")
        self.assertEqual(item.get("fanart_url", ""), "")
        self.assertNotIn("banner_url", item)

    def test_exact_watch_handoff_renames_generic_file_and_preserves_subtitle(self):
        meta = base.metadata_from_provider_dict(self.extract(WATCH_URL))
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "manifest_2026-08-29.mp4"
            subtitle = Path(temp) / "manifest_2026-08-29.en.srt"
            video.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")
            with patch.object(base, "download_binary", side_effect=lambda _url, target: target.write_bytes(b"art") or target):
                saved = base.save_pbs_kids_series_metadata(meta, {}, explicit_folder=str(video))
            root = Path(temp) / "Wild Kratts"
            season = root / "S07"
            stem = "S07E17 Wild Kratts - Duck, Duck, Loon!"
            self.assertTrue((season / f"{stem}.mp4").exists())
            self.assertTrue((season / f"{stem}.en.srt").exists())
            self.assertTrue((season / f"{stem}.nfo").exists())
            self.assertTrue((season / f"{stem}-thumb.png").exists())
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertTrue((root / "thumb.jpg").exists())
            self.assertTrue((root / "logo.png").exists())
            self.assertFalse((root / "poster.jpg").exists())
            self.assertFalse((root / "backdrop.jpg").exists())
            self.assertFalse((root / "banner.jpg").exists())
            self.assertTrue(saved)

    def test_queue_folder_matches_multiple_episode_titles(self):
        meta = base.metadata_from_provider_dict(self.extract(SERIES_URL))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Duck Duck Loon.mp4").write_bytes(b"video")
            (root / "Butternut Tree.mp4").write_bytes(b"video")
            groups = base.pbs_kids_media_groups(meta, {}, explicit_folder=temp)
            self.assertEqual([(group.season, group.episode) for group, _record in groups], [(7, 16), (7, 17)])

    def test_broad_root_rejects_unrelated_episode_number(self):
        meta = base.metadata_from_provider_dict(self.extract(SERIES_URL))
        with tempfile.TemporaryDirectory() as temp:
            unrelated = Path(temp) / "Another Show" / "S07"
            unrelated.mkdir(parents=True)
            (unrelated / "S07E17 Another Show.mp4").write_bytes(b"video")
            self.assertEqual(base.pbs_kids_media_groups(meta, {"media_folders": [temp]}), [])

    def test_cleanup_removes_only_empty_mediafab_timestamp_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            removable = root / "wilk720-ep_2026-08-29_21-46-55"
            removable.mkdir()
            (removable / ".DS_Store").write_bytes(b"finder")
            occupied = root / "wilk713-ep_2026-08-29_21-46-15"
            occupied.mkdir()
            (occupied / ".DS_Store").write_bytes(b"finder")
            (occupied / "keep.txt").write_text("keep", encoding="utf-8")
            unrelated = root / "My Empty Folder"
            unrelated.mkdir()
            removed = base.cleanup_pbs_kids_handoff_folders(str(root))
            self.assertEqual(removed, [removable])
            self.assertFalse(removable.exists())
            self.assertTrue(occupied.exists())
            self.assertTrue(unrelated.exists())


if __name__ == "__main__":
    unittest.main()
