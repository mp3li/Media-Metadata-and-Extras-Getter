from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_base():
    path = ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py"
    spec = importlib.util.spec_from_file_location("test_queue_contract_base", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()


class QueueModeContractTests(unittest.TestCase):
    def test_series_providers_consolidate_jobs_and_preserve_generated_sidecars(self):
        cases = [
            ("Crunchyroll", base.CrunchyrollMediaGroup, base.prepare_crunchyroll_media_group, base.crunchyroll_series_folder_name),
            ("Disney+", base.DisneyPlusMediaGroup, base.prepare_disneyplus_media_group, base.disneyplus_series_folder_name),
            ("HBO Max", base.HBOMaxMediaGroup, base.prepare_hbomax_media_group, base.hbomax_series_folder_name),
            ("Amazon Prime Video", base.AmazonPrimeMediaGroup, base.prepare_amazon_prime_media_group, base.amazon_prime_series_folder_name),
            ("PBS KIDS", base.PBSKidsMediaGroup, base.prepare_pbs_kids_media_group, base.pbs_kids_series_folder_name),
        ]
        for provider, group_type, prepare, folder_name in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); first = root / "job-one"; second = root / "job-two"
                first.mkdir(); second.mkdir()
                meta = base.Metadata(
                    source_url="https://example.test/show", source_site=provider,
                    media_kind="episode", title="Example Show", show_title="Example Show",
                    season_number="1", episode_number="1", episode_title="Pilot",
                    series_start_year="2025", series_end_year="2025", series_is_current=False,
                )
                source_folders = {first, second}
                for index, source in enumerate((first, second), start=1):
                    stem = f"capture-{index}"
                    video = source / f"{stem}.mkv"; nfo = source / f"{stem}.nfo"; thumb = source / f"{stem}-thumb.jpg"
                    video.write_bytes(b"video"); nfo.write_text("nfo", encoding="utf-8"); thumb.write_bytes(b"thumb")
                    group = group_type(source, stem, index, 1, [video, nfo, thumb])
                    canonical = base.explicit_series_show_folder(temp, meta, folder_name)
                    prepared = prepare(meta, group, {}, explicit_show_folder=canonical)
                    self.assertEqual(prepared.folder, canonical / f"S{index:02d}")
                    self.assertTrue(any(path.name.endswith("-thumb.jpg") for path in prepared.files))
                    self.assertTrue(any(path.suffix == ".nfo" for path in prepared.files))
                base.cleanup_empty_provider_source_folders(source_folders, canonical, provider)
                self.assertFalse(first.exists()); self.assertFalse(second.exists())
                self.assertEqual([path.name for path in root.iterdir()], [folder_name(meta)])

    def test_queue_identity_outranks_stale_position_for_remaining_providers(self):
        records = [
            {"id": "IDENTITY0001", "season": 1, "episode": 1, "title": "One"},
            {"id": "IDENTITY0002", "season": 1, "episode": 2, "title": "Two"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / "S09E09_IDENTITY0002.mkv"; video.write_bytes(b"video")
            crunchy = base.Metadata(
                source_url="https://example.test", source_site="Crunchyroll", media_kind="series",
                title="Show", show_title="Show", series_episodes=records,
            )
            disney = base.Metadata(
                source_url="https://example.test", source_site="Disney+", media_kind="series",
                title="Show", show_title="Show", series_episodes=records,
            )
            self.assertEqual(
                [(g.season, g.episode) for g, _r in base.crunchyroll_media_groups(crunchy, {}, explicit_folder=temp)],
                [(1, 2)],
            )
            self.assertEqual(
                [(g.season, g.episode) for g, _r in base.disneyplus_media_groups(disney, {}, explicit_folder=temp)],
                [(1, 2)],
            )

        prime_records = [
            {"id": "GTI0001", "compact_id": "PRIME0001", "season": 1, "episode": 1, "title": "One"},
            {"id": "GTI0002", "compact_id": "PRIME0002", "season": 1, "episode": 2, "title": "Two"},
        ]
        pbs_records = [
            {"id": "2756001", "legacy_id": "3000001", "season": 1, "episode": 1, "title": "One"},
            {"id": "2756002", "legacy_id": "3000002", "season": 1, "episode": 2, "title": "Two"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            prime_video = Path(temp) / "S09E09_PRIME0002.mkv"; prime_video.write_bytes(b"video")
            self.assertEqual(base.amazon_prime_match_record(prime_video, prime_records)["episode"], 2)
        with tempfile.TemporaryDirectory() as temp:
            pbs_video = Path(temp) / "S09E09_2756002.mkv"; pbs_video.write_bytes(b"video")
            self.assertEqual(base.pbs_kids_match_record(pbs_video, pbs_records)["episode"], 2)

    def test_broad_handoff_root_never_claims_another_shows_bare_position(self):
        records = [
            {"id": "IDENTITY0001", "compact_id": "PRIME0001", "legacy_id": "3000001", "season": 1, "episode": 1, "title": "Pilot"},
            {"id": "IDENTITY0002", "compact_id": "PRIME0002", "legacy_id": "3000002", "season": 1, "episode": 2, "title": "Second"},
        ]
        cases = [
            ("Crunchyroll", base.crunchyroll_media_groups),
            ("Disney+", base.disneyplus_media_groups),
            ("HBO Max", base.hbomax_media_groups),
            ("Paramount+", base.paramountplus_media_groups),
            ("BBC iPlayer", base.bbc_queue_media_groups),
            ("Netflix", base.netflix_media_groups),
            ("Amazon Prime Video", base.amazon_prime_media_groups),
            ("PBS KIDS", base.pbs_kids_media_groups),
        ]
        for provider, matcher in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                unrelated = root / "Another Show (2020)" / "S01"
                incoming = root / "queue-job"
                unrelated.mkdir(parents=True); incoming.mkdir()
                wrong = unrelated / "S01E01 Another Show - Pilot.mkv"
                right = incoming / "capture_IDENTITY0002_PRIME0002_3000002.mkv"
                wrong.write_bytes(b"wrong"); right.write_bytes(b"right")
                meta = base.Metadata(
                    source_url="https://example.test/show", source_site=provider,
                    media_kind="series", title="Example Show", show_title="Example Show",
                    series_episodes=records,
                )
                groups = matcher(meta, {}, explicit_folder=temp)
                self.assertEqual([(group.season, group.episode) for group, _record in groups], [(1, 2)])
                self.assertTrue(wrong.exists())


if __name__ == "__main__":
    unittest.main()
