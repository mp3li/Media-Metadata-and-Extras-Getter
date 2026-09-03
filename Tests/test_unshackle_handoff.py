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
    spec = importlib.util.spec_from_file_location("test_unshackle_handoff_base", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


base = load_base()


def arguments(media_file: Path, **overrides):
    values = {
        "media_folder": str(media_file),
        "detail_link": "",
        "skip_existing": True,
        "unshackle_service": "DSNP",
        "unshackle_id": "ad5f6c58-8513-4de1-8420-350ce867ffdd",
        "unshackle_title": "Unshackle Show",
        "unshackle_year": "2025",
        "unshackle_season": "1",
        "unshackle_episode": "2",
        "unshackle_episode_title": "The Second Episode",
        "unshackle_sidecars": "",
    }
    values.update(overrides)
    return Namespace(**values)


class UnshackleHandoffTests(unittest.TestCase):
    def test_known_service_ids_resolve_to_supported_public_pages(self):
        cases = {
            ("AMZN", "B012345678", "1"): "https://www.primevideo.com/detail/B012345678",
            ("BBCIPLAYER", "m002abcd", "1"): "https://www.bbc.co.uk/iplayer/episode/m002abcd",
            ("CR", "GE00123456ENUS", "1"): "https://www.crunchyroll.com/watch/GE00123456ENUS",
            ("DSNP", "ad5f6c58-8513-4de1-8420-350ce867ffdd", "1"): "https://www.disneyplus.com/play/ad5f6c58-8513-4de1-8420-350ce867ffdd",
            ("HMAX", "8e38bcf0-5f39-44db-b891-372c9d99fb51", "1"): "https://play.hbomax.com/video/watch/8e38bcf0-5f39-44db-b891-372c9d99fb51",
            ("NF", "81767569", "1"): "https://www.netflix.com/title/81767569",
            ("PMTP", "Episode_ID-123", "1"): "https://www.paramountplus.com/shows/video/Episode_ID-123/",
            ("PARAMOUNTPLUS", "Movie_ID-123", ""): "https://www.paramountplus.com/movies/video/Movie_ID-123/",
        }
        for (service, title_id, season), expected in cases.items():
            with self.subTest(service=service):
                self.assertEqual(base.unshackle_detail_link(service, title_id, season), expected)

    def test_explicit_supported_link_outranks_service_identity(self):
        link = "https://www.crunchyroll.com/watch/GE00123456ENUS"
        self.assertEqual(base.unshackle_detail_link("UNKNOWN", "bad id", detail_link=link), link)
        with self.assertRaises(ValueError):
            base.unshackle_detail_link("UNKNOWN", "bad id")

    def test_episode_handoff_writes_title_based_bundle_without_moving_media_or_subtitles(self):
        with tempfile.TemporaryDirectory() as temp:
            show = Path(temp) / "Unshackle Show (2025)"
            season = show / "Season 01"
            season.mkdir(parents=True)
            video = season / "Unshackle.Show.S01E02.WEB-DL.mkv"
            subtitle = season / "Unshackle.Show.S01E02.WEB-DL.en.srt"
            video.write_bytes(b"original video")
            subtitle.write_text("original subtitle", encoding="utf-8")

            series = {
                "source_url": "https://www.disneyplus.com/browse/entity-series",
                "source_site": base.disneyplus.NAME,
                "media_kind": "series",
                "title": "Provider Show Title",
                "show_title": "Provider Show Title",
                "plot": "Series plot.",
                "year": "2025",
                "poster_url": "https://images.test/poster.jpg",
                "fanart_url": "https://images.test/backdrop.jpg",
                "thumb_url": "https://images.test/title-thumb.jpg",
                "logo_url": "https://images.test/logo.png",
                "trailer_url": "https://video.test/trailer.mp4",
                "tags": ["Disney+ Provider"],
            }
            episode = base.Metadata(
                source_url="https://www.disneyplus.com/play/ad5f6c58-8513-4de1-8420-350ce867ffdd",
                source_site=base.disneyplus.NAME,
                media_kind="episode",
                title="Provider Show Title",
                show_title="Provider Show Title",
                season_number="1",
                episode_number="2",
                episode_title="Provider Episode Title",
                plot="Episode plot.",
                thumb_url="https://images.test/episode-thumb.jpg",
                tags=["Disney+ Provider"],
                series_metadata=series,
            )

            def fake_download(_url, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"downloaded")
                return target

            args = arguments(video, unshackle_sidecars=str(subtitle))
            with (
                patch.object(base, "AnimatedStatus"),
                patch.object(base, "scrape_url", return_value=episode),
                patch.object(base, "download_binary", side_effect=fake_download),
                patch.object(base, "save_provider_series_metadata") as normal_series,
                patch.object(base, "save_metadata_bundle") as normal_bundle,
            ):
                self.assertEqual(base.run_unshackle_handoff(args), 0)

            self.assertEqual(video.read_bytes(), b"original video")
            self.assertEqual(subtitle.read_text(encoding="utf-8"), "original subtitle")
            self.assertTrue(video.exists())
            self.assertTrue(subtitle.exists())
            self.assertEqual(list(season.glob("*.mkv")), [video])
            self.assertTrue(video.with_suffix(".nfo").exists())
            self.assertTrue(season.joinpath(f"{video.stem}-thumb.jpg").exists())
            self.assertTrue(show.joinpath("tvshow.nfo").exists())
            self.assertTrue(show.joinpath("Unshackle Show-poster.jpg").exists())
            self.assertTrue(show.joinpath("Unshackle Show-backdrop.jpg").exists())
            self.assertTrue(show.joinpath("Unshackle Show-thumb.jpg").exists())
            self.assertTrue(show.joinpath("Unshackle Show-logo.png").exists())
            self.assertTrue(show.joinpath("Unshackle Show-trailer.mp4").exists())
            normal_series.assert_not_called()
            normal_bundle.assert_not_called()

    def test_movie_bundle_uses_the_existing_media_stem_and_never_renames_it(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "Movie Folder"
            folder.mkdir()
            video = folder / "Existing.Unshackle.Movie.2026.mkv"
            video.write_bytes(b"movie")
            movie = base.Metadata(
                source_url="https://www.netflix.com/title/81767569",
                source_site=base.netflix.NAME,
                media_kind="movie",
                title="Provider Movie Title",
                plot="Movie plot.",
                poster_url="https://images.test/poster.jpg",
                fanart_url="https://images.test/backdrop.jpg",
                trailer_url="https://video.test/trailer.mp4",
            )

            def fake_download(_url, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"downloaded")
                return target

            args = arguments(
                video,
                unshackle_service="NF",
                unshackle_id="81767569",
                unshackle_title="Provider Movie Title",
                unshackle_season="",
                unshackle_episode="",
                unshackle_episode_title="",
            )
            with (
                patch.object(base, "AnimatedStatus"),
                patch.object(base, "scrape_url", return_value=movie),
                patch.object(base, "download_binary", side_effect=fake_download),
            ):
                self.assertEqual(base.run_unshackle_handoff(args), 0)

            stem = video.stem
            self.assertEqual(video.read_bytes(), b"movie")
            self.assertTrue(folder.joinpath(f"{stem}.nfo").exists())
            self.assertTrue(folder.joinpath(f"{stem}-poster.jpg").exists())
            self.assertTrue(folder.joinpath(f"{stem}-backdrop.jpg").exists())
            self.assertTrue(folder.joinpath(f"{stem}-trailer.mp4").exists())
            self.assertEqual(list(folder.glob("*.mkv")), [video])

    def test_series_catalog_is_reduced_to_only_the_completed_episode(self):
        with tempfile.TemporaryDirectory() as temp:
            show = Path(temp) / "Catalog Show (2024)"
            season = show / "S02"
            season.mkdir(parents=True)
            video = season / "Catalog.Show.S02E03.mkv"
            video.write_bytes(b"episode")
            catalog = base.Metadata(
                source_url="https://www.netflix.com/title/81767569",
                detail_link="https://www.netflix.com/title/81767569",
                source_site=base.netflix.NAME,
                media_kind="series",
                title="Catalog Show",
                show_title="Catalog Show",
                plot="Complete series plot.",
                poster_url="https://images.test/poster.jpg",
                tags=["Netflix Provider"],
                series_episodes=[
                    {
                        "id": "81767570",
                        "season": 2,
                        "episode": 3,
                        "title": "Only This Episode",
                        "description": "Episode plot.",
                        "image": "https://images.test/episode.jpg",
                    },
                    {
                        "id": "81767571",
                        "season": 2,
                        "episode": 4,
                        "title": "Not Downloaded",
                        "description": "Must not be written.",
                    },
                ],
            )

            def fake_download(_url, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"downloaded")
                return target

            args = arguments(
                video,
                unshackle_service="NF",
                unshackle_id="81767570",
                unshackle_title="Catalog Show",
                unshackle_season="2",
                unshackle_episode="3",
                unshackle_episode_title="Only This Episode",
            )
            with (
                patch.object(base, "AnimatedStatus"),
                patch.object(base, "scrape_url", return_value=catalog),
                patch.object(base, "download_binary", side_effect=fake_download),
            ):
                self.assertEqual(base.run_unshackle_handoff(args), 0)

            self.assertTrue(video.exists())
            self.assertTrue(video.with_suffix(".nfo").exists())
            self.assertTrue(show.joinpath("tvshow.nfo").exists())
            self.assertFalse(any(path.name.startswith("Not Downloaded") for path in show.rglob("*")))

    def test_parser_accepts_unshackle_post_script_context(self):
        args = base.build_parser().parse_args([
            "--unshackle-handoff",
            "--media-folder=/tmp/finished.mkv",
            "--unshackle-service=HMAX",
            "--unshackle-id=episode-id",
            "--unshackle-title=Example Show",
            "--unshackle-season=1",
            "--unshackle-episode=2",
            "--unshackle-episode-title=Example Episode",
            "--unshackle-sidecars=/tmp/finished.en.srt",
            "--skip-existing",
        ])
        self.assertTrue(args.unshackle_handoff)
        self.assertEqual(args.unshackle_service, "HMAX")
        self.assertEqual(args.unshackle_episode, "2")


if __name__ == "__main__":
    unittest.main()
