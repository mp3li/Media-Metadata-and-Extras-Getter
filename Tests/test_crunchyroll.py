from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


crunchyroll = load_module("test_crunchyroll_provider", ROOT / "Provider Scripts" / "crunchyroll.py")
base = load_module("test_crunchyroll_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")


SERIES_ID = "GW4HM7WQ5"
EPISODE_ID = "GE00362087ENUS"
SHOW = "May I Ask for One Final Thing?"
EPISODE_TITLE = "May I Kindly Beat the Tar Out of Those Evil Nobles (Pigs)?"


RATING = {
    "average": "4.8",
    "total": 52354,
    "5s": {"displayed": "44.6", "unit": "K", "percentage": 86},
    "4s": {"displayed": "4.7", "unit": "K", "percentage": 10},
    "3s": {"displayed": "1.7", "unit": "K", "percentage": 4},
    "2s": {"displayed": "556", "percentage": 2},
    "1s": {"displayed": "676", "percentage": 2},
}


def series_object():
    return {
        "id": SERIES_ID,
        "title": SHOW,
        "description": "Scarlet has put up with her fiancé’s bullying long enough.",
        "slug_title": "may-i-ask-for-one-final-thing",
        "rating": RATING,
        "images": {
            "poster_tall": [[
                {"source": "https://img.example/poster-small.png", "width": 260, "height": 390},
                {"source": "https://img.example/poster.png", "width": 1560, "height": 2340},
            ]],
            "poster_wide": [[
                {"source": "https://img.example/backdrop.png", "width": 1920, "height": 1080}
            ]],
        },
        "series_metadata": {
            "tenant_categories": ["Action", "Comedy", "Fantasy"],
            "content_descriptors": ["Violence", "Profanity"],
            "maturity_ratings": ["TV-14"],
        },
    }


def series_detail():
    return {
        "id": SERIES_ID,
        "series_launch_year": 2025,
        "episode_count": 13,
        "season_count": 1,
        "season_tags": ["fall-2025"],
        "content_provider": "LIDEN FILMS",
        "is_subbed": True,
        "is_dubbed": True,
        "audio_locales": ["ja-JP", "en-US"],
        "subtitle_locales": ["en-US", "de-DE"],
        "content_descriptors": ["Violence", "Profanity"],
        "maturity_ratings": ["TV-14"],
    }


def episode_object():
    return {
        "id": EPISODE_ID,
        "title": EPISODE_TITLE,
        "description": "When Scarlet's fiancé dumps her at a ball, she requests satisfaction.",
        "slug_title": "may-i-kindly-beat-the-tar-out-of-those-evil-nobles-pigs",
        "rating": {
            "up": {"displayed": "15.2", "unit": "K"},
            "down": {"displayed": "96"},
            "total": 15334,
        },
        "images": {"thumbnail": [[
            {"source": "https://img.example/thumb-320.png", "width": 320, "height": 180},
            {"source": "https://img.example/thumb-640.png", "width": 640, "height": 360},
            {"source": "https://img.example/thumb-1920.png", "width": 1920, "height": 1080},
        ]]},
    }


def episode_detail():
    return {
        "id": EPISODE_ID,
        "series_id": SERIES_ID,
        "series_title": SHOW,
        "season_number": 1,
        "episode_number": 1,
        "duration_ms": 1420046,
        "episode_air_date": "2025-10-03T17:00:00Z",
        "upload_date": "2025-10-03T18:30:00Z",
        "maturity_ratings": ["TV-14"],
        "content_descriptors": ["Violence", "Profanity"],
        "is_subbed": True,
        "is_dubbed": True,
        "versions": [
            {"guid": "GE00362087JAJP", "audio_locale": "ja-JP", "original": True},
            {"guid": EPISODE_ID, "audio_locale": "en-US"},
        ],
        "subtitle_locales": ["en-US", "de-DE"],
        "next_episode_id": "GE00362089ENUS",
        "next_episode_title": "May I Offer You the Taste of My Fist?",
    }


def api_fixture(path: str, timeout: int = 25):
    if path == f"objects/{SERIES_ID}":
        return {"data": [series_object()]}
    if path == f"series/{SERIES_ID}":
        return {"data": [series_detail()]}
    if path == f"objects/{EPISODE_ID}":
        return {"data": [episode_object()]}
    if path == f"episodes/{EPISODE_ID}":
        return {"data": [episode_detail()]}
    if path == f"series/{SERIES_ID}/seasons":
        return {"data": [{"id": "SEASON1", "season_number": 1}]}
    if path == "seasons/SEASON1/episodes":
        first = dict(episode_detail())
        first.update(episode_object())
        second = dict(first)
        second.update({"id": "EPISODE2", "episode_number": 2, "title": "Episode Two"})
        return {"data": [first, second]}
    raise AssertionError(f"Unexpected API path: {path}")


class CrunchyrollProviderTests(unittest.TestCase):
    def extract_series(self):
        with patch.object(crunchyroll, "api_get", side_effect=api_fixture):
            return crunchyroll.extract_series_metadata(SERIES_ID)

    def extract_episode(self):
        with patch.object(crunchyroll, "api_get", side_effect=api_fixture):
            return crunchyroll.extract_episode_metadata(EPISODE_ID)

    def test_series_selected_metadata_and_artwork(self):
        item = self.extract_series()
        self.assertEqual(item["poster_url"], "https://img.example/poster.png")
        self.assertEqual(item["fanart_url"], "https://img.example/backdrop.png")
        self.assertEqual(
            item["logo_url"],
            "https://imgsrv.crunchyroll.com/cdn-cgi/image/fit=contain,format=png,quality=100,width=1200/"
            "keyart/GW4HM7WQ5-title_logo-en-us",
        )
        self.assertEqual(item["year"], "2025")
        self.assertEqual(item["series_start_year"], "2025")
        self.assertEqual(item["series_end_year"], "2025")
        self.assertFalse(item["series_is_current"])
        self.assertEqual(item["studios"], ["LIDEN FILMS"])
        self.assertEqual(item["extra_fields"]["Episode count"], ["13"])
        self.assertEqual(item["extra_fields"]["Season count"], ["1"])
        self.assertEqual(item["extra_fields"]["Season tag"], ["fall-2025"])
        self.assertNotIn("Availability", item["extra_fields"])
        self.assertEqual(len(item["series_episodes"]), 2)
        self.assertEqual(item["trailer_url"], "")
        self.assertIn("Crunchyroll Provider", item["tags"])

    def test_official_youtube_trailer_requires_exact_title_and_channel(self):
        results = {
            "entries": [
                {
                    "id": "fan-upload",
                    "title": f"{SHOW} | Official Trailer | Crunchyroll",
                    "uploader_id": "@fan-channel",
                    "url": "https://www.youtube.com/watch?v=fan-upload",
                },
                {
                    "id": "wrong-show",
                    "title": "Another Show | Official Trailer | Crunchyroll",
                    "uploader_id": "@crunchyroll",
                    "url": "https://www.youtube.com/watch?v=wrong-show",
                },
                {
                    "id": "official-trailer",
                    "title": f"{SHOW} - Official Trailer",
                    "uploader_id": "@crunchyrolldubs",
                    "channel": "Crunchyroll Dubs",
                    "url": "https://www.youtube.com/watch?v=official-trailer",
                },
            ]
        }
        completed = crunchyroll.subprocess.CompletedProcess(
            args=["yt-dlp"],
            returncode=0,
            stdout=json.dumps(results),
            stderr="",
        )
        with patch.object(crunchyroll.subprocess, "run", return_value=completed):
            match = crunchyroll.find_official_youtube_trailer(SHOW)
        self.assertEqual(match["id"], "official-trailer")
        self.assertEqual(match["channel"], "Crunchyroll Dubs")

    def test_episode_rating_tags_are_adjacent_and_exact(self):
        item = self.extract_episode()
        self.assertIn("Crunchyroll Provider", item["tags"])
        first = item["tags"].index("crunchyrollratings: 15.2k upvotes / 96 downvotes")
        self.assertEqual(
            item["tags"][first:first + 7],
            [
                "crunchyrollratings: 15.2k upvotes / 96 downvotes",
                "crunchyrollrating: 4.8 / 5 from 52,354 ratings",
                "crunchyrollrating5stars: 44.6k / 86%",
                "crunchyrollrating4stars: 4.7k / 10%",
                "crunchyrollrating3stars: 1.7k / 4%",
                "crunchyrollrating2stars: 556 / 2%",
                "crunchyrollrating1star: 676 / 2%",
            ],
        )
        self.assertEqual(item["thumb_url"], "https://img.example/thumb-640.png")
        self.assertEqual(item["language"], "Japanese")
        self.assertEqual(item["extra_fields"]["Exact runtime"], ["23:40.046 | 1,420,046 ms"])
        self.assertEqual(item["extra_fields"]["Air date"], ["2025-10-03T17:00:00Z"])
        self.assertEqual(item["extra_fields"]["Upload date"], ["2025-10-03T18:30:00Z"])
        self.assertNotIn("Premium Only", item["extra_fields"])
        self.assertEqual(item["series_metadata"]["media_kind"], "series")
        self.assertEqual(
            item["series_metadata"]["plot"],
            "Scarlet has put up with her fiancé’s bullying long enough.",
        )

    def test_series_nfo_uses_tvshow_root(self):
        meta = base.metadata_from_provider_dict(self.extract_series())
        root = ET.fromstring(base.build_nfo(meta))
        self.assertEqual(root.tag, "tvshow")
        self.assertEqual(root.findtext("uniqueid"), SERIES_ID)

    def test_local_only_episode_is_renamed_organized_and_saved(self):
        series_meta = base.metadata_from_provider_dict(self.extract_series())
        episode_item = self.extract_episode()
        with tempfile.TemporaryDirectory() as temp:
            legacy_folder = Path(temp) / SHOW
            legacy_folder.mkdir()
            (legacy_folder / "E1.mp4").write_bytes(b"video")
            (legacy_folder / "E1.srt").write_text("subtitle", encoding="utf-8")
            settings = {
                "media_folders": [str(legacy_folder)],
                "crunchyroll_series_metadata_enabled": True,
                "crunchyroll_series_rename_enabled": True,
                "crunchyroll_series_organize_enabled": True,
            }

            def fake_download(url: str, target: Path):
                if not url:
                    return None
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"image")
                return target

            with (
                patch.object(base.crunchyroll, "extract_episode_metadata", return_value=episode_item) as extract,
                patch.object(base.crunchyroll, "find_official_youtube_trailer", return_value={}),
                patch.object(base, "download_binary", side_effect=fake_download),
            ):
                saved = base.save_crunchyroll_series_metadata(series_meta, settings)

            target_base = f"S01E01 {SHOW[:-1]} - {EPISODE_TITLE[:-1]}"
            show_folder = Path(temp) / base.crunchyroll_series_folder_name(series_meta)
            season_folder = show_folder / "S01"
            video = season_folder / f"{target_base}.mp4"
            nfo = season_folder / f"{target_base}.nfo"
            self.assertTrue(video.exists())
            self.assertTrue((season_folder / f"{target_base}.und.srt").exists())
            self.assertTrue(nfo.exists())
            self.assertTrue((season_folder / f"{target_base}-thumb.png").exists())
            self.assertTrue((show_folder / "poster.png").exists())
            self.assertTrue((show_folder / "backdrop.png").exists())
            self.assertTrue((show_folder / "logo.png").exists())
            tvshow_nfo = show_folder / "tvshow.nfo"
            self.assertTrue(tvshow_nfo.exists())
            self.assertEqual(extract.call_count, 1)
            self.assertFalse(any("EPISODE2" in str(path) for path in saved or []))

            root = ET.fromstring(nfo.read_text(encoding="utf-8"))
            tags = [node.text for node in root.findall("tag")]
            vote_index = tags.index("crunchyrollratings: 15.2k upvotes / 96 downvotes")
            self.assertEqual(tags[vote_index + 1], "crunchyrollrating: 4.8 / 5 from 52,354 ratings")
            self.assertEqual(root.findtext("language"), "Japanese")
            self.assertEqual(
                ET.fromstring(tvshow_nfo.read_text(encoding="utf-8")).findtext("plot"),
                "Scarlet has put up with her fiancé’s bullying long enough.",
            )

    def test_episode_save_preserves_existing_series_bundle(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            show_folder = Path(temp) / SHOW
            season_folder = show_folder / "S01"
            season_folder.mkdir(parents=True)
            tvshow_nfo = show_folder / "tvshow.nfo"
            poster = show_folder / "poster.png"
            tvshow_nfo.write_text("manual series metadata", encoding="utf-8")
            poster.write_bytes(b"manual poster")

            def fake_download(url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"new image")
                return target

            with (
                patch.object(base.crunchyroll, "extract_series_metadata") as extract_series,
                patch.object(base.crunchyroll, "find_official_youtube_trailer", return_value={}),
                patch.object(base, "download_binary", side_effect=fake_download),
            ):
                base.save_metadata_bundle_to_location(
                    episode_meta,
                    season_folder,
                    base.crunchyroll_target_base(episode_meta),
                )
                base.ensure_crunchyroll_series_bundle(episode_meta, show_folder)

            extract_series.assert_not_called()
            self.assertEqual(tvshow_nfo.read_text(encoding="utf-8"), "manual series metadata")
            self.assertEqual(poster.read_bytes(), b"manual poster")
            self.assertTrue((show_folder / "backdrop.png").exists())
            self.assertTrue((show_folder / "logo.png").exists())

    def test_direct_episode_output_also_saves_linked_series_bundle(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            settings = {"default_output_dir": temp, "media_folders": []}

            def fake_download(url: str, target: Path):
                if not url:
                    return None
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"image")
                return target

            with (
                patch.object(base.crunchyroll, "extract_series_metadata") as extract_series,
                patch.object(base, "download_binary", side_effect=fake_download),
            ):
                base.save_metadata_bundle(episode_meta, settings)

            extract_series.assert_not_called()
            show_folder = Path(temp) / base.crunchyroll_series_folder_name(episode_meta)
            self.assertTrue((show_folder / "tvshow.nfo").exists())
            self.assertTrue((show_folder / "poster.png").exists())
            episode_nfo = show_folder / "S01" / f"{base.crunchyroll_target_base(episode_meta)}.nfo"
            self.assertTrue(episode_nfo.exists())
            self.assertEqual(
                ET.fromstring((show_folder / "tvshow.nfo").read_text(encoding="utf-8")).findtext("plot"),
                "Scarlet has put up with her fiancé’s bullying long enough.",
            )
            self.assertEqual(
                ET.fromstring(episode_nfo.read_text(encoding="utf-8")).findtext("plot"),
                "When Scarlet's fiancé dumps her at a ball, she requests satisfaction.",
            )

    def test_crunchyroll_trailer_uses_jellyfin_folder_and_provider_url_first(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        episode_meta.trailer_url = "https://cdn.crunchyroll.example/trailer.mp4"
        with tempfile.TemporaryDirectory() as temp:
            show_folder = Path(temp) / base.safe_filename(SHOW)

            def fake_download(url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"provider trailer")
                return target

            with (
                patch.object(base.crunchyroll, "find_official_youtube_trailer") as youtube_search,
                patch.object(base, "download_binary", side_effect=fake_download),
            ):
                saved = base.save_crunchyroll_series_trailer(episode_meta, show_folder)

            youtube_search.assert_not_called()
            trailer = show_folder / "trailers" / "trailer.mp4"
            self.assertEqual(saved, [trailer])
            self.assertEqual(trailer.read_bytes(), b"provider trailer")

    def test_crunchyroll_trailer_falls_back_to_official_youtube_last(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            show_folder = Path(temp) / base.safe_filename(SHOW)
            youtube_url = "https://www.youtube.com/watch?v=official-trailer"

            def fake_youtube_download(url: str, target: Path):
                self.assertEqual(url, youtube_url)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"youtube trailer")
                return target

            with (
                patch.object(
                    base.crunchyroll,
                    "find_official_youtube_trailer",
                    return_value={"url": youtube_url, "id": "official-trailer"},
                ),
                patch.object(base, "download_youtube_trailer", side_effect=fake_youtube_download),
            ):
                saved = base.save_crunchyroll_series_trailer(episode_meta, show_folder)

            trailer = show_folder / "trailers" / "trailer.mp4"
            self.assertEqual(saved, [trailer])
            self.assertEqual(trailer.read_bytes(), b"youtube trailer")

    def test_youtube_download_uses_embedded_client_and_installed_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "trailers" / "trailer.mp4"
            target.parent.mkdir()

            def fake_run(command, **kwargs):
                output = command[command.index("--output") + 1].replace("%(ext)s", "mp4")
                Path(output).write_bytes(b"downloaded trailer")
                self.assertIn("youtube:player_client=web_embedded", command)
                self.assertIn("node:/usr/local/bin/node", command)
                return base.subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.object(base.shutil, "which", side_effect=lambda name: "/usr/local/bin/node" if name == "node" else None),
                patch.object(base.subprocess, "run", side_effect=fake_run),
            ):
                saved = base.download_youtube_trailer("https://www.youtube.com/watch?v=trailer", target)

            self.assertEqual(saved, target)
            self.assertEqual(target.read_bytes(), b"downloaded trailer")

    def test_missing_youtube_tools_skip_only_optional_trailer(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "trailers" / "trailer.mp4"
            target.parent.mkdir()
            with (
                patch.object(base.shutil, "which", return_value=None),
                patch.object(base.subprocess, "run", side_effect=FileNotFoundError),
            ):
                saved = base.download_youtube_trailer(
                    "https://www.youtube.com/watch?v=trailer",
                    target,
                )

            self.assertIsNone(saved)
            self.assertFalse(target.exists())

    def test_other_provider_never_invokes_crunchyroll_trailer_path(self):
        with tempfile.TemporaryDirectory() as temp:
            meta = base.Metadata(
                source_url="https://example.test/movie",
                source_site="Netflix",
                media_kind="movie",
                title="Example Movie",
                plot="Example metadata",
            )
            with patch.object(base, "save_crunchyroll_series_trailer") as trailer_save:
                saved = base.save_metadata_bundle(meta, {"default_output_dir": temp})

            trailer_save.assert_not_called()
            self.assertTrue(any(path.suffix == ".nfo" for path in saved))

    def test_episode_position_forms(self):
        for text in ("S01E01", "S1 E1", "Season 1 Episode 1", "Series 1 Episode 1", "1x01", "01-01", "E1"):
            with self.subTest(text=text):
                self.assertEqual(base.crunchyroll_episode_position(text), (1, 1))

    def test_existing_rename_destination_is_never_overwritten(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / "E1.mp4"
            source.write_bytes(b"source")
            season_folder = folder / base.crunchyroll_series_folder_name(episode_meta) / "S01"
            season_folder.mkdir(parents=True)
            target = season_folder / f"{base.crunchyroll_target_base(episode_meta)}.mp4"
            target.write_bytes(b"existing")
            group = base.CrunchyrollMediaGroup(
                folder=folder,
                stem="E1",
                season=1,
                episode=1,
                files=[source],
            )
            settings = {
                "crunchyroll_series_rename_enabled": True,
                "crunchyroll_series_organize_enabled": True,
            }
            with self.assertRaises(FileExistsError):
                base.prepare_crunchyroll_media_group(episode_meta, group, settings)
            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(target.read_bytes(), b"existing")

    def test_shared_download_location_creates_and_reuses_one_series_folder(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            download_folder = Path(temp)
            first_video = download_folder / "manifest-first.mkv"
            first_video.write_bytes(b"episode one")
            first_group = base.CrunchyrollMediaGroup(
                folder=download_folder,
                stem=first_video.stem,
                season=1,
                episode=1,
                files=[first_video],
            )
            settings = {
                "crunchyroll_series_rename_enabled": True,
                "crunchyroll_series_organize_enabled": True,
            }
            first_prepared = base.prepare_crunchyroll_media_group(episode_meta, first_group, settings)

            second_video = download_folder / "manifest-second.mkv"
            second_video.write_bytes(b"episode two")
            second_meta = base.metadata_from_provider_dict(self.extract_episode())
            second_meta.episode_number = "2"
            second_meta.episode_title = "Episode Two"
            second_group = base.CrunchyrollMediaGroup(
                folder=download_folder,
                stem=second_video.stem,
                season=1,
                episode=2,
                files=[second_video],
            )
            second_prepared = base.prepare_crunchyroll_media_group(second_meta, second_group, settings)

            show_folder = download_folder / base.crunchyroll_series_folder_name(episode_meta)
            self.assertEqual(first_prepared.folder, (show_folder / "S01").resolve())
            self.assertEqual(second_prepared.folder, (show_folder / "S01").resolve())
            self.assertTrue((show_folder / "S01" / f"{base.crunchyroll_target_base(episode_meta, first_group)}.mkv").exists())
            self.assertTrue((show_folder / "S01" / f"{base.crunchyroll_target_base(second_meta, second_group)}.mkv").exists())
            self.assertFalse((show_folder / base.safe_filename(SHOW)).exists())

    def test_relative_media_path_recognizes_current_series_folder(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            legacy_folder = Path(temp) / base.safe_filename(SHOW)
            legacy_folder.mkdir()
            video = legacy_folder / f"crunchyroll-{EPISODE_ID}.mkv"
            video.write_bytes(b"video")
            previous_directory = Path.cwd()
            try:
                os.chdir(legacy_folder)
                relative_video = Path(f"./crunchyroll-{EPISODE_ID}.mkv")
                group = base.CrunchyrollMediaGroup(
                    folder=relative_video.parent,
                    stem=relative_video.stem,
                    season=1,
                    episode=1,
                    files=[relative_video],
                )
                prepared = base.prepare_crunchyroll_media_group(
                    episode_meta,
                    group,
                    {
                        "crunchyroll_series_rename_enabled": True,
                        "crunchyroll_series_organize_enabled": True,
                    },
                )
            finally:
                os.chdir(previous_directory)

            show_folder = Path(temp) / base.crunchyroll_series_folder_name(episode_meta)
            self.assertEqual(prepared.folder, (show_folder / "S01").resolve())
            self.assertFalse(legacy_folder.exists())

    def test_series_folder_name_uses_closed_and_current_year_ranges(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        self.assertEqual(
            base.crunchyroll_series_folder_name(episode_meta),
            "May I Ask for One Final Thing (2025)",
        )
        start, end, current = crunchyroll.series_run_years(
            "2026",
            [{"date": "2026-08-27"}],
            current_date=date(2026, 8, 28),
        )
        episode_meta.series_start_year = start
        episode_meta.series_end_year = end
        episode_meta.series_is_current = current
        self.assertEqual(
            base.crunchyroll_series_folder_name(episode_meta),
            "May I Ask for One Final Thing (2026-)",
        )

    def test_closed_year_range_renames_whole_current_series_folder(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        episode_meta.series_start_year = "2026"
        episode_meta.series_end_year = "2026"
        episode_meta.series_is_current = False
        with tempfile.TemporaryDirectory() as temp:
            current_folder = Path(temp) / f"{base.safe_filename(SHOW)} (2026-)"
            season_folder = current_folder / "S01"
            season_folder.mkdir(parents=True)
            poster = current_folder / "poster.png"
            video = season_folder / "E1.mkv"
            poster.write_bytes(b"poster")
            video.write_bytes(b"video")
            group = base.CrunchyrollMediaGroup(
                folder=season_folder,
                stem="E1",
                season=1,
                episode=1,
                files=[video],
            )

            prepared = base.prepare_crunchyroll_media_group(
                episode_meta,
                group,
                {
                    "crunchyroll_series_rename_enabled": True,
                    "crunchyroll_series_organize_enabled": True,
                },
            )

            closed_folder = Path(temp) / f"{base.safe_filename(SHOW)} (2026)"
            self.assertFalse(current_folder.exists())
            self.assertEqual(prepared.folder, (closed_folder / "S01").resolve())
            self.assertEqual((closed_folder / "poster.png").read_bytes(), b"poster")

    def test_english_cc_is_kept_and_forced_sign_track_is_discarded(self):
        episode_meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            stem = f"crunchyroll-{EPISODE_ID}"
            video = folder / f"{stem}.mkv"
            captions = folder / f"{stem}.en_us.srt"
            forced = folder / f"{stem}.en_us.02.srt"
            video.write_bytes(b"video")
            captions.write_text(
                "1\n00:00:00,793 --> 00:00:02,377\n[indistinct chatter]\n\n"
                + "\n".join(
                    f"{number}\n00:00:{number:02d},000 --> 00:00:{number:02d},500\nDialogue"
                    for number in range(2, 26)
                ),
                encoding="utf-8",
            )
            forced.write_text(
                "1\n00:05:03,950 --> 00:05:08,960\nMay I Kindly Beat the Tar Out of Those Evil Nobles?\n\n"
                "2\n00:23:36,020 --> 00:23:40,020\nNext Episode\n",
                encoding="utf-8",
            )
            group = base.CrunchyrollMediaGroup(
                folder=folder,
                stem=stem,
                season=1,
                episode=1,
                files=[video, captions, forced],
            )
            prepared = base.prepare_crunchyroll_media_group(
                episode_meta,
                group,
                {
                    "crunchyroll_series_rename_enabled": True,
                    "crunchyroll_series_organize_enabled": True,
                },
            )

            target_base = base.crunchyroll_target_base(episode_meta, group)
            self.assertEqual(
                prepared.folder,
                (folder / base.crunchyroll_series_folder_name(episode_meta) / "S01").resolve(),
            )
            self.assertTrue((prepared.folder / f"{target_base}.en.cc.srt").exists())
            self.assertFalse((prepared.folder / f"{target_base}.en.forced.srt").exists())
            self.assertFalse(forced.exists())


if __name__ == "__main__":
    unittest.main()
