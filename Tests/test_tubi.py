from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EPISODE_URL = "https://tubitv.com/tv-shows/200310461/s01-e01-house-of-bloo-s-pt-1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tubi = load_module("test_tubi_provider", ROOT / "Provider Scripts" / "tubi.py")
base = load_module("test_tubi_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")


EPISODE = {
    "id": "200310461", "series_id": "300019076", "detailed_type": "episode",
    "title": "S01:E01 - House of Bloo's (Pt. 1)", "description": "Episode plot.",
    "year": 2004, "duration": 1384, "lang": "English", "country": "United States",
    "ratings": [{"code": "TV-G"}], "tags": ["Kids & Family", "Comedy"],
    "actors": ["Keith Ferguson"], "directors": [],
    "thumbnails": ["https://img.example/episode.jpg"],
}
SERIES = {
    "id": "300019076", "detailed_type": "series", "title": "Foster's Home for Imaginary Friends",
    "description": "Series plot.", "year": 2004, "lang": "English", "country": "United States",
    "ratings": [{"code": "TV-G"}], "tags": ["Kids & Family", "Adventure", "Comedy"],
    "actors": ["Keith Ferguson"], "directors": [],
    "posterarts": ["https://img.example/poster.jpg"],
    "backgrounds": ["https://img.example/backdrop.jpg"],
    "title_art": ["https://img.example/logo.png"],
}
GUIDE = {
    "series_id": 300019076, "is_recurring": False, "is_sequential": True,
    "episodes_by_season": [
        {"name": "Season 1", "season": 1, "episodes": [{"id": 200310461, "num": 1}, {"id": 200310460, "num": 2}]},
        {"name": "Season 2", "season": 2, "episodes": [{"id": 200310758, "num": 3}]},
    ],
}


class FakeClient:
    def __init__(self, timeout: int = 25):
        self.timeout = timeout

    def content(self, identifier: str):
        return EPISODE if str(identifier) == "200310461" else SERIES

    def series_guide(self, series_id: str):
        return GUIDE


class TubiProviderTests(unittest.TestCase):
    def extract(self):
        with patch.object(tubi, "GuestClient", FakeClient):
            return tubi.extract_metadata(EPISODE_URL)

    def test_episode_resolves_exact_id_and_complete_multi_season_guide(self):
        item = self.extract()
        self.assertEqual(item["source_site"], "Tubi")
        self.assertEqual(item["show_title"], "Foster's Home for Imaginary Friends")
        self.assertEqual((item["season_number"], item["episode_number"]), ("1", "1"))
        self.assertEqual(item["episode_title"], "House of Bloo's (Pt. 1)")
        self.assertEqual(item["unique_ids"]["tubi"], "200310461")
        self.assertEqual(len(item["series_episodes"]), 3)
        self.assertEqual({record["season"] for record in item["series_episodes"]}, {1, 2})
        self.assertIn("Tubi Provider", item["tags"])

    def test_incomplete_or_duplicate_guides_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "incomplete Season"):
            tubi.guide_records({"episodes_by_season": [{"season": 1, "episodes": []}]})
        with self.assertRaisesRegex(ValueError, "duplicate episode identities"):
            tubi.guide_records({"episodes_by_season": [{"season": 1, "episodes": [{"id": 1, "num": 1}, {"id": 2, "num": 1}]}]})

    def test_exact_handoff_escapes_tubi_wrapper_and_builds_jellyfin_bundle(self):
        meta = base.metadata_from_provider_dict(self.extract())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Tubi"
            wrapper = root / "Fosters Home S01E01 1080p"
            wrapper.mkdir(parents=True)
            video = wrapper / "manifest.mkv"
            subtitle = wrapper / "manifest.en.srt"
            video.write_bytes(b"video"); subtitle.write_text("subtitle", encoding="utf-8")

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b"art"); return target

            with patch.object(base, "download_binary", side_effect=fake_download):
                saved = base.save_tubi_series_metadata(meta, {}, explicit_folder=str(video))

            show = root / "Foster's Home for Imaginary Friends (2004)"
            stem = "S01E01 Foster's Home for Imaginary Friends - House of Bloo's (Pt. 1)"
            self.assertTrue((show / "tvshow.nfo").exists())
            self.assertTrue((show / "poster.jpg").exists())
            self.assertTrue((show / "backdrop.jpg").exists())
            self.assertTrue((show / "logo.png").exists())
            self.assertTrue((show / "Season 01" / f"{stem}.mkv").exists())
            self.assertTrue((show / "Season 01" / f"{stem}.en.srt").exists())
            self.assertTrue((show / "Season 01" / f"{stem}.nfo").exists())
            self.assertFalse(wrapper.exists())
            self.assertTrue(saved)

    def test_url_support_is_strict(self):
        self.assertTrue(tubi.is_supported_url(EPISODE_URL))
        self.assertTrue(tubi.is_supported_url("https://tubitv.com/series/300019076/title"))
        self.assertTrue(tubi.is_supported_url("https://tubitv.com/movies/123/title"))
        self.assertFalse(tubi.is_supported_url("https://example.com/tv-shows/200310461/title"))

    def test_movie_handoff_preserves_sidecars_and_uses_year_folder(self):
        meta = base.Metadata(
            source_url="https://tubitv.com/movies/123/example-movie", source_site="Tubi",
            media_kind="movie", title="Example Movie", year="2026",
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / "manifest.mkv"
            subtitle = root / "manifest.en.srt"
            video.write_bytes(b"video"); subtitle.write_text("subtitle", encoding="utf-8")
            match = base.MediaMatch(root, video, video.stem, 100.0)
            organized = base.organize_tubi_movie(match, meta, {}, explicit_folder=str(video))
            destination = root / "Example Movie (2026)"
            self.assertEqual(organized.video_path, destination / "Example Movie (2026).mkv")
            self.assertTrue((destination / "Example Movie (2026).en.srt").exists())


if __name__ == "__main__":
    unittest.main()
