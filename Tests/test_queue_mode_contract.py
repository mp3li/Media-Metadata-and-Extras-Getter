from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


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
    def test_series_providers_process_two_exact_files_and_reuse_one_series_root(self):
        cases = [
            ("Crunchyroll", base.CrunchyrollMediaGroup, base.prepare_crunchyroll_media_group, base.crunchyroll_series_folder_name),
            ("Disney+", base.DisneyPlusMediaGroup, base.prepare_disneyplus_media_group, base.disneyplus_series_folder_name),
            ("HBO Max", base.HBOMaxMediaGroup, base.prepare_hbomax_media_group, base.hbomax_series_folder_name),
            ("Amazon Prime Video", base.AmazonPrimeMediaGroup, base.prepare_amazon_prime_media_group, base.amazon_prime_series_folder_name),
            ("PBS KIDS", base.PBSKidsMediaGroup, base.prepare_pbs_kids_media_group, base.pbs_kids_series_folder_name),
            ("Paramount+", base.ParamountPlusMediaGroup, base.prepare_paramountplus_media_group, base.paramountplus_series_folder_name),
        ]
        for provider, group_type, prepare, folder_name in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                meta = base.Metadata(
                    source_url="https://example.test/show", source_site=provider,
                    media_kind="episode", title="Example Show", show_title="Example Show",
                    season_number="1", episode_number="1", episode_title="Pilot",
                    series_start_year="2025", series_end_year="2025", series_is_current=False,
                )
                unrelated = root / "unrelated.mkv"
                unrelated.write_bytes(b"unrelated")
                canonical = root / folder_name(meta)
                for index in (1, 2):
                    stem = f"capture-{index}"
                    video = root / f"{stem}.mkv"; nfo = root / f"{stem}.nfo"; thumb = root / f"{stem}-thumb.jpg"
                    video.write_bytes(b"video"); nfo.write_text("nfo", encoding="utf-8"); thumb.write_bytes(b"thumb")
                    group = group_type(root, stem, index, 1, [video, nfo, thumb])
                    prepared = prepare(meta, group, {})
                    self.assertEqual(prepared.folder, canonical / f"S{index:02d}")
                    self.assertTrue(any(path.name.endswith("-thumb.jpg") for path in prepared.files))
                    self.assertTrue(any(path.suffix == ".nfo" for path in prepared.files))
                    self.assertTrue(unrelated.exists())
                    self.assertFalse(any(root.glob(f"{stem}*")))
                self.assertEqual(len(list(canonical.rglob("*.mkv"))), 2)
                self.assertTrue(unrelated.exists())

    def test_verified_repeat_handoff_preserves_existing_media_and_consumes_only_duplicate(self):
        cases = [
            ("Crunchyroll", base.CrunchyrollMediaGroup, base.prepare_crunchyroll_media_group, base.crunchyroll_series_folder_name),
            ("Disney+", base.DisneyPlusMediaGroup, base.prepare_disneyplus_media_group, base.disneyplus_series_folder_name),
            ("HBO Max", base.HBOMaxMediaGroup, base.prepare_hbomax_media_group, base.hbomax_series_folder_name),
            ("Amazon Prime Video", base.AmazonPrimeMediaGroup, base.prepare_amazon_prime_media_group, base.amazon_prime_series_folder_name),
            ("PBS KIDS", base.PBSKidsMediaGroup, base.prepare_pbs_kids_media_group, base.pbs_kids_series_folder_name),
            ("Paramount+", base.ParamountPlusMediaGroup, base.prepare_paramountplus_media_group, base.paramountplus_series_folder_name),
        ]
        for provider, group_type, prepare, folder_name in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                meta = base.Metadata(
                    source_url="https://example.test/watch/episode", source_site=provider,
                    media_kind="episode", title="Example Show", show_title="Example Show",
                    season_number="1", episode_number="1", episode_title="Pilot",
                    series_start_year="2025", series_end_year="2025", series_is_current=False,
                )
                original = root / "original.mkv"
                original.write_bytes(b"existing media")
                first = prepare(meta, group_type(root, original.stem, 1, 1, [original]), {})
                existing_video = next(path for path in first.files if path.suffix == ".mkv")

                incoming = root / "repeat.mkv"
                incoming_subtitle = root / "repeat.en.srt"
                unrelated = root / "unrelated.txt"
                incoming.write_bytes(b"incoming container")
                incoming_subtitle.write_text("new subtitle", encoding="utf-8")
                unrelated.write_text("leave me", encoding="utf-8")
                repeat = group_type(root, incoming.stem, 1, 1, [incoming, incoming_subtitle])
                with patch.object(base, "exact_media_streams_match", return_value=True) as matched:
                    prepared = prepare(meta, repeat, {}, skip_existing=True)

                matched.assert_called_once_with(incoming, existing_video)
                self.assertEqual(existing_video.read_bytes(), b"existing media")
                self.assertFalse(incoming.exists())
                self.assertFalse(incoming_subtitle.exists())
                self.assertTrue(unrelated.exists())
                self.assertEqual(len(list((root / folder_name(meta)).rglob("*.mkv"))), 1)
                self.assertTrue(any(path.suffix == ".srt" and path.exists() for path in prepared.files))

    def test_skip_existing_still_refuses_a_different_media_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            meta = base.Metadata(
                source_url="https://example.test/watch/episode", source_site="Crunchyroll",
                media_kind="episode", title="Example Show", show_title="Example Show",
                season_number="1", episode_number="1", episode_title="Pilot",
                series_start_year="2025", series_end_year="2025", series_is_current=False,
            )
            original = root / "original.mkv"
            original.write_bytes(b"existing media")
            first_group = base.CrunchyrollMediaGroup(root, original.stem, 1, 1, [original])
            prepared = base.prepare_crunchyroll_media_group(meta, first_group, {})
            existing_video = next(path for path in prepared.files if path.suffix == ".mkv")
            incoming = root / "repeat.mkv"
            incoming.write_bytes(b"different media")
            repeat_group = base.CrunchyrollMediaGroup(root, incoming.stem, 1, 1, [incoming])

            with patch.object(base, "exact_media_streams_match", return_value=False):
                with self.assertRaises(FileExistsError):
                    base.prepare_crunchyroll_media_group(
                        meta, repeat_group, {}, skip_existing=True
                    )

            self.assertTrue(incoming.exists())
            self.assertEqual(existing_video.read_bytes(), b"existing media")

    def test_verified_repeat_movie_handoff_preserves_existing_title_folder(self):
        cases = [
            (
                "Netflix",
                lambda match, meta: base.organize_netflix_movie(
                    match, meta, explicit_folder=str(match.video_path), skip_existing=True
                ),
                {},
            ),
            (
                "Disney+",
                lambda match, meta: base.organize_disneyplus_movie(
                    match, meta, {}, explicit_folder=str(match.video_path), skip_existing=True
                ),
                {},
            ),
            (
                "HBO Max",
                lambda match, meta: base.organize_hbomax_movie(
                    match, meta, {}, explicit_folder=str(match.video_path), skip_existing=True
                ),
                {},
            ),
            (
                "Paramount+",
                lambda match, meta: base.organize_paramountplus_movie(
                    match, meta, {}, explicit_folder=str(match.video_path), skip_existing=True
                ),
                {"Paramount+ movie ID": ["MOVIE1"]},
            ),
        ]
        for provider, organize, extra_fields in cases:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                meta = base.Metadata(
                    source_url="https://example.test/movie",
                    source_site=provider,
                    media_kind="movie",
                    title="Example Movie",
                    year="2025",
                    extra_fields=extra_fields,
                )
                destination = root / "Example Movie (2025)"
                destination.mkdir()
                existing = destination / "Example Movie (2025).mkv"
                existing.write_bytes(b"existing movie")
                incoming = root / "repeat-movie.mkv"
                incoming.write_bytes(b"incoming container")
                match = base.MediaMatch(root, incoming, incoming.stem, 100.0)

                with patch.object(base, "exact_media_streams_match", return_value=True) as matched:
                    organized = organize(match, meta)

                matched.assert_called_once_with(incoming, existing)
                self.assertEqual(organized.video_path, existing)
                self.assertEqual(existing.read_bytes(), b"existing movie")
                self.assertFalse(incoming.exists())

    def test_bbc_and_netflix_queue_paths_use_verified_duplicate_handling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            bbc_meta = base.Metadata(
                source_url="https://www.bbc.co.uk/iplayer/episode/example",
                source_site="BBC iPlayer", media_kind="episode",
                title="Example Show", show_title="Example Show",
                season_number="1", episode_number="1", episode_title="Pilot",
                series_start_year="2025", series_end_year="2025",
            )
            original = root / "bbc-original.mkv"
            original.write_bytes(b"bbc existing")
            first = base.prepare_bbc_queue_media_group(
                bbc_meta,
                base.BBCMediaGroup(root, original.stem, 1, 1, "bbc-id", "Pilot", [original]),
                {},
            )
            existing = next(path for path in first.files if path.suffix == ".mkv")
            incoming = root / "bbc-repeat.mkv"
            incoming.write_bytes(b"bbc incoming")
            with patch.object(base, "exact_media_streams_match", return_value=True):
                repeated = base.prepare_bbc_queue_media_group(
                    bbc_meta,
                    base.BBCMediaGroup(root, incoming.stem, 1, 1, "bbc-id", "Pilot", [incoming]),
                    {},
                    skip_existing=True,
                )
            self.assertFalse(incoming.exists())
            self.assertEqual(next(path for path in repeated.files if path.suffix == ".mkv"), existing)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            netflix_meta = base.Metadata(
                source_url="https://www.netflix.com/title/example",
                source_site="Netflix", media_kind="series", title="Example Show",
                series_start_year="2025", series_end_year="2025",
                series_episodes=[{
                    "id": "episode-id", "season": 1, "episode": 1,
                    "title": "Pilot", "url": "https://www.netflix.com/watch/episode-id",
                }],
            )
            show = root / base.netflix_series_folder_name(netflix_meta)
            season = show / "S01"
            season.mkdir(parents=True)
            existing = season / "S01E01 Example Show - Pilot.mkv"
            existing.write_bytes(b"netflix existing")
            incoming = root / "netflix-repeat.mkv"
            incoming.write_bytes(b"netflix incoming")
            group = base.NetflixMediaGroup(root, incoming.stem, 1, 1, [incoming])
            record = netflix_meta.series_episodes[0]
            with (
                patch.object(base, "netflix_media_groups", return_value=[(group, record)]),
                patch.object(base, "exact_media_streams_match", return_value=True),
            ):
                base.save_netflix_series_metadata(
                    netflix_meta, {}, explicit_folder=str(incoming), skip_existing=True
                )
            self.assertFalse(incoming.exists())
            self.assertEqual(existing.read_bytes(), b"netflix existing")

    def test_handoff_requires_one_exact_completed_video_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = Namespace(
                detail_link="https://example.test/watch/item",
                media_folder=temp,
                skip_existing=True,
            )
            with patch.object(base, "scrape_url") as scrape:
                self.assertEqual(base.run_handoff(args, {}), 1)
                scrape.assert_not_called()

            video = root / "completed.mkv"
            video.write_bytes(b"video")
            args.media_folder = str(video)
            meta = base.Metadata(
                source_url=args.detail_link,
                source_site="Example",
                media_kind="movie",
                title="Example",
            )
            with (
                patch.object(base, "AnimatedStatus"),
                patch.object(base, "scrape_url", return_value=meta),
                patch.object(base, "save_provider_series_metadata", return_value=[]) as save,
            ):
                self.assertEqual(base.run_handoff(args, {}), 0)
                self.assertEqual(save.call_args.kwargs["explicit_folder"], str(video.resolve()))

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
