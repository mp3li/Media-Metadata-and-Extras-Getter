from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EPISODE_URL = "https://www.bbc.co.uk/iplayer/episode/m0000001/example-show"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bbc = load_module("test_bbc_queue_provider", ROOT / "Provider Scripts" / "bbc_iplayer.py")
base = load_module("test_bbc_queue_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")


def related_episode(identifier: str, season: int, episode: int, title: str, released: str):
    return {
        "episode": {
            "id": identifier,
            "subtitle": {"default": f"Series {season}: Episode {episode}", "slice": title},
            "synopsis": {"small": f"Short {title}", "large": f"Full {title}"},
            "releaseDate": released,
            "versions": [{"duration": {"seconds": 1800}, "firstBroadcast": released}],
            "images": {"standard": f"https://img.example/{identifier}/{{recipe}}.jpg"},
        }
    }


def state(current_slice: str, episodes: list[dict]):
    return {
        "episode": {
            "id": "m0000001",
            "tleoId": "p0000001",
            "title": "Example Show",
            "subtitle": "Series 1: Episode 1",
            "programmeType": "episode",
            "releaseDate": "2025-01-01",
            "releaseDateTime": "2025-01-01T00:00:00Z",
            "synopses": {"small": "Series short.", "large": "Series full description."},
            "images": {
                "standard": "https://img.example/poster/{recipe}.jpg",
                "promotional": "https://img.example/backdrop/{recipe}.jpg",
                "promotional_with_logo": "https://img.example/logo/{recipe}.png",
            },
            "masterBrand": {"titles": {"large": "BBC One"}},
        },
        "versions": [{"duration": {"seconds": 1800}, "firstBroadcast": "2025-01-01"}],
        "relatedEpisodes": {
            "currentSliceId": current_slice,
            "slices": [
                {"id": "slice-1", "title": {"default": "Series 1"}},
                {"id": "slice-2", "title": {"default": "Series 2"}},
            ],
            "episodes": episodes,
        },
    }


def page(payload: dict) -> str:
    return f"<script>window.__IPLAYER_REDUX_STATE__ = {json.dumps(payload)};</script>"


class BBCQueueModeTests(unittest.TestCase):
    def extract(self):
        first = state("slice-1", [
            related_episode("m0000001", 1, 1, "First", "2025-01-01"),
            related_episode("m0000002", 1, 2, "Second", "2025-01-08"),
        ])
        second = state("slice-2", [related_episode("m0000003", 2, 1, "Return", "2026-08-15")])
        with patch.object(bbc, "fetch_text", side_effect=lambda url, timeout=25: page(second if "slice-2" in url else first)):
            return bbc.extract_metadata(EPISODE_URL)

    def test_episode_link_builds_complete_multi_slice_catalog_and_provider_tag(self):
        item = self.extract()
        self.assertEqual(len(item["series_episodes"]), 3)
        self.assertEqual([(r["season"], r["episode"]) for r in item["series_episodes"]], [(1, 1), (1, 2), (2, 1)])
        self.assertIn("BBC iPlayer Provider", item["tags"])
        self.assertEqual(item["series_metadata"]["media_kind"], "series")

    def test_queue_ids_outrank_stale_positions_and_use_one_output_root(self):
        meta = base.metadata_from_provider_dict(self.extract())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "job-one"; second = root / "job-two"
            first.mkdir(); second.mkdir()
            (first / "S09E09_m0000001.mkv").write_bytes(b"one")
            (second / "S09E09_m0000003.mkv").write_bytes(b"two")

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b"art"); return target

            with patch.object(base, "download_binary", side_effect=fake_download):
                base.save_bbc_queue_series_metadata(meta, {}, explicit_folder=temp)
            show = root / "Example Show (2025-)"
            self.assertTrue((show / "S01" / "S01E01 Example Show - First.mkv").exists())
            self.assertTrue((show / "S02" / "S02E01 Example Show - Return.mkv").exists())
            self.assertTrue((show / "tvshow.nfo").exists())
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_slice_failure_refuses_partial_catalog(self):
        first = state("slice-1", [related_episode("m0000001", 1, 1, "First", "2025-01-01")])
        with patch.object(bbc, "fetch_text", side_effect=[page(first), RuntimeError("offline")]):
            with self.assertRaisesRegex(RuntimeError, "refusing a partial Queue Mode catalog"):
                bbc.extract_metadata(EPISODE_URL)


if __name__ == "__main__":
    unittest.main()
