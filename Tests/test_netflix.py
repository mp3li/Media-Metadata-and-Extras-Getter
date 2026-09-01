from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SERIES_URL = "https://www.netflix.com/title/80000000"
MOVIE_URL = "https://www.netflix.com/title/90000000"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


netflix = load_module("test_netflix_provider", ROOT / "Provider Scripts" / "netflix.py")
base = load_module("test_netflix_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")


def html_page(payload: dict) -> str:
    return (
        '<meta property="og:title" content="Example Show - Netflix">'
        '<meta property="og:image" content="https://img.example/poster.jpg">'
        f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    )


SERIES = {
    "@type": "TVSeries",
    "name": "Example Show",
    "description": "Series description.",
    "datePublished": "2025-01-01",
    "contentRating": "TV-14",
    "containsSeason": [{
        "seasonNumber": 1,
        "episode": [
            {"@type": "TVEpisode", "seasonNumber": 1, "episodeNumber": 1, "name": "Beginning", "description": "First.", "url": "https://www.netflix.com/title/80000001", "image": "https://img.example/e1.jpg", "duration": "PT30M", "datePublished": "2025-01-01"},
            {"@type": "TVEpisode", "seasonNumber": 1, "episodeNumber": 2, "name": "Return", "description": "Second.", "url": "https://www.netflix.com/title/80000002", "image": "https://img.example/e2.jpg", "duration": "PT31M", "datePublished": "2025-01-08"},
        ],
    }],
}


MOVIE = {
    "@type": "Movie", "name": "Example Movie", "description": "Movie description.",
    "datePublished": "2024-01-01", "contentRating": "PG", "duration": "PT1H30M",
    "image": "https://img.example/movie-poster.jpg",
}


class NetflixProviderTests(unittest.TestCase):
    def test_public_series_catalog_gets_provider_tag_and_exact_ids(self):
        with patch.object(netflix, "fetch_text", return_value=html_page(SERIES)):
            item = netflix.extract_metadata(SERIES_URL)
        self.assertEqual(item["media_kind"], "series")
        self.assertEqual(len(item["series_episodes"]), 2)
        self.assertEqual(item["series_episodes"][0]["id"], "80000001")
        self.assertIn("Netflix Provider", item["tags"])

    def test_independent_exact_file_handoffs_reuse_one_output_root(self):
        with patch.object(netflix, "fetch_text", return_value=html_page(SERIES)):
            meta = base.metadata_from_provider_dict(netflix.extract_metadata(SERIES_URL))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "S09E09_80000001.mkv"
            second = root / "S09E09_80000002.mkv"
            unrelated = root / "unrelated.mkv"
            first.write_bytes(b"one")
            unrelated.write_bytes(b"unrelated")

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b"art"); return target

            with patch.object(base, "download_binary", side_effect=fake_download):
                base.save_netflix_series_metadata(meta, {}, explicit_folder=str(first))
                show = root / "Example Show (2025)"
                series_nfo = show / "tvshow.nfo"
                self.assertTrue((show / "S01" / "S01E01 Example Show - Beginning.mkv").exists())
                self.assertTrue(series_nfo.exists())
                series_nfo.write_text("preserve me", encoding="utf-8")

                second.write_bytes(b"two")
                base.save_netflix_series_metadata(meta, {}, explicit_folder=str(second))
            show = root / "Example Show (2025)"
            self.assertTrue((show / "S01" / "S01E02 Example Show - Return.mkv").exists())
            self.assertEqual((show / "tvshow.nfo").read_text(encoding="utf-8"), "preserve me")
            self.assertTrue(unrelated.exists())
            self.assertFalse(first.exists()); self.assertFalse(second.exists())

    def test_series_without_public_catalog_fails_closed(self):
        meta = base.Metadata(source_url=SERIES_URL, source_site="Netflix", media_kind="series", title="Hidden Catalog")
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "manifest.mkv").write_bytes(b"video")
            self.assertEqual(base.save_netflix_series_metadata(meta, {}, explicit_folder=temp), [])
            self.assertEqual(list(Path(temp).glob("*.nfo")), [])

    def test_movie_handoff_uses_year_folder_provider_tag_and_native_trailer(self):
        movie = dict(MOVIE)
        movie["trailer"] = {"url": "https://media.example/trailer.mp4"}
        page = html_page(movie).replace("Example Show - Netflix", "Example Movie - Netflix")
        with patch.object(netflix, "fetch_text", return_value=page):
            meta = base.metadata_from_provider_dict(netflix.extract_metadata(MOVIE_URL))
        meta.trailer_url = "https://media.example/trailer.mp4"
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "Example Movie download.mkv"; source.write_bytes(b"video")

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b"asset"); return target

            with patch.object(base, "download_binary", side_effect=fake_download):
                base.save_metadata_bundle(meta, {}, explicit_folder=temp)
            root = Path(temp) / "Example Movie (2024)"
            self.assertTrue((root / "Example Movie (2024).mkv").exists())
            self.assertTrue((root / "Example Movie (2024).nfo").exists())
            self.assertTrue((root / "trailers" / "trailer.mp4").exists())
            self.assertFalse((root / "Example Movie (2024)-fanart.jpg").exists())


if __name__ == "__main__":
    unittest.main()
