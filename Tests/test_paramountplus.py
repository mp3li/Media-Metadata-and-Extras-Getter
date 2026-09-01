from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
EPISODE_URL = "https://www.paramountplus.com/shows/video/ZvEow_nZm5WAiLeMlEmISm3Deti40Ciu/"
SECOND_EPISODE_ID = "AbCdEfGhIjKlMnOpQrStUvWxYz123456"
SHOW_URL = "https://www.paramountplus.com/shows/spongebob-squarepants/"
SHOW = "SpongeBob SquarePants"
MOVIE_URL = "https://www.paramountplus.com/movies/video/MOVIE1234567890/"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


paramountplus = load_module("test_paramountplus_provider", ROOT / "Provider Scripts" / "paramountplus.py")
base = load_module("test_paramountplus_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")


SHOW_PAGE = """
<meta property="og:title" content="SpongeBob SquarePants - Nickelodeon - Watch on Paramount Plus">
<meta name="description" content="A square yellow sponge lives in a pineapple under the sea.">
<meta property="og:image" content="https://img.example/social.jpg">
<div class="about__header-title">SpongeBob SquarePants</div>
<span class="about__metadata-title">Genre</span><span>Comedy; Animation</span>
<span class="about__metadata-title">Year</span><span>1999</span>
<span class="about__metadata-title">Seasons</span><span>1 Season</span>
<span class="about__metadata-title">Rating</span><span>TV-Y7</span>
<span class="about__metadata-title">Brand</span><span>Nickelodeon</span>
<script>var tracking = {"showSeriesId":"61456636"};</script>
<img alt="SpongeBob SquarePants" src="https://img.example/logo.png">
<img src="https://img.example/keyart_w3200_landscape.jpg">
<img src="https://img.example/keyart_w2400_portrait.jpg">
<div data-media-url="https://splice.paramountplus.com/previewhls/master.m3u8"></div>
<script>var languages = {"audioLanguages":["English", "Spanish"],"subtitleLanguages":[{"displayName":"English - CC"}]};</script>
<article class="grid-view-item" data-tracking="x|S1|Ep1|x|Help Wanted||">
  <a href="/shows/video/ZvEow_nZm5WAiLeMlEmISm3Deti40Ciu/" aa-link="Full Episodes||play|1|SpongeBob SquarePants"></a>
  <div class="meta-wrapper title-shorten">S1 E1 Help Wanted</div>
  <div class="description-wrapper">SpongeBob applies for a job.</div>
  <meta itemprop="duration" content="PT23M">
  <time datetime="2026-08-20"></time>
  <img vilynx-id="ZvEow_nZm5WAiLeMlEmISm3Deti40Ciu" src="https://thumbnails.cbsig.net/_x/w640/episode.jpg">
</article>
"""


SECOND_EPISODE = f"""
<article class="grid-view-item" data-tracking="x|S1|Ep2|x|Reef Blower||">
  <a href="/shows/video/{SECOND_EPISODE_ID}/" aa-link="Full Episodes||play|2|SpongeBob SquarePants"></a>
  <div class="meta-wrapper title-shorten">S1 E2 Reef Blower</div>
  <div class="description-wrapper">SpongeBob cleans his yard.</div>
  <meta itemprop="duration" content="PT11M">
  <time datetime="2026-08-21"></time>
  <img vilynx-id="{SECOND_EPISODE_ID}" src="https://thumbnails.cbsig.net/_x/w640/episode-2.jpg">
</article>
"""


MOVIE_PAGE = """
<script type="application/ld+json">
{"@type":"Movie","name":"Example Movie","description":"Movie description.",
"datePublished":"2026-04-01","contentRating":"PG-13","genre":"Adventure",
"image":"https://img.example/movie-poster.jpg",
"director":{"@type":"Person","name":"Example Director"},
"creator":[{"@type":"Person","name":"Example Writer"}]}
</script>
<script>var tracking = {"movieId":"MOVIE1234567890"};</script>
<span class="duration">1H 42M</span>
<img src="https://img.example/movie_w1920_pplcrn_backdrop.jpg">
<div class="movieLogo"><img src="https://img.example/movie-logo.png"></div>
<section class="movie__cast">Featuring: Actor One, Actor Two</section>
<div data-media-url="https://splice.paramountplus.com/previewhls/movie.m3u8"></div>
<script>var languages = {"audioLanguages":["English"],"subtitleLanguages":["English - CC"]};</script>
"""


EPISODE_PAGE = """
<meta property="og:title" content="SpongeBob SquarePants • Season 1 | Paramount+">
<script type="application/ld+json">
{"@type":"TVEpisode","name":"Help Wanted","description":"SpongeBob applies for a job.",
"episodeNumber":1,"duration":"PT23M","datePublished":"2026-08-20",
"image":"https://thumbnails.cbsig.net/_x/w1920/episode.jpg",
"partOfSeries":{"name":"SpongeBob SquarePants"},"partOfSeason":{"seasonNumber":1}}
</script>
<script>player.baseUrl = "/shows/spongebob-squarepants/";</script>
<a href="/shows/spongebob-squarepants/" aa-link="show header">Show</a>
<script>CBS.Registry.Show = {"key":"spongebob-squarepants"};</script>
"""


class ParamountPlusProviderTests(unittest.TestCase):
    def extract_episode(self):
        def fixture(url: str, timeout: int = 25):
            return SHOW_PAGE if url == SHOW_URL else EPISODE_PAGE

        with patch.object(paramountplus, "fetch_text", side_effect=fixture):
            return paramountplus.extract_metadata(EPISODE_URL)

    def test_playing_page_resolves_parent_show(self):
        self.assertEqual(paramountplus.series_url_from_episode_page(EPISODE_PAGE, EPISODE_URL), SHOW_URL)
        item = self.extract_episode()
        self.assertEqual(item["media_kind"], "episode")
        self.assertEqual(item["title"], SHOW)
        self.assertEqual(item["episode_title"], "Help Wanted")
        self.assertEqual((item["season_number"], item["episode_number"]), ("1", "1"))
        self.assertEqual(item["poster_url"], "https://img.example/keyart_w2400_portrait.jpg")
        self.assertEqual(item["fanart_url"], "https://img.example/keyart_w3200_landscape.jpg")
        self.assertEqual(item["logo_url"], "https://img.example/logo.png")
        self.assertEqual(item["thumb_url"], "https://thumbnails.cbsig.net/_x/w1920/episode.jpg")
        self.assertEqual(item["series_metadata"]["media_kind"], "series")
        self.assertIn("Paramount+ Provider", item["tags"])

    def test_show_has_tvshow_metadata_and_run_years(self):
        with patch.object(paramountplus, "fetch_text", return_value=SHOW_PAGE):
            item = paramountplus.show_metadata_from_page(SHOW_PAGE, SHOW_URL, timeout=25)
        self.assertEqual(item["media_kind"], "series")
        self.assertEqual(item["series_start_year"], "1999")
        self.assertEqual(item["series_end_year"], "2026")
        self.assertTrue(item["series_is_current"])
        self.assertEqual(len(item["series_episodes"]), 1)
        self.assertEqual(item["extra_fields"]["Audio"], ["English", "Spanish"])
        self.assertEqual(item["extra_fields"]["Subtitles"], ["English - CC"])
        root = ET.fromstring(base.build_nfo(base.metadata_from_provider_dict(item)))
        self.assertEqual(root.tag, "tvshow")
        self.assertIn("Paramount+ Provider", [node.text for node in root.findall("tag")])

    def test_advertised_season_failure_refuses_partial_queue_catalog(self):
        with patch.object(paramountplus, "all_season_urls", return_value={2: "https://example.test/season/2/"}), patch.object(
            paramountplus, "fetch_text", side_effect=RuntimeError("offline")
        ):
            with self.assertRaisesRegex(RuntimeError, "refusing a partial Queue Mode catalog"):
                paramountplus.show_metadata_from_page(SHOW_PAGE, SHOW_URL, timeout=25)

    def test_series_year_forms(self):
        records = [{"date": "2025-01-01"}]
        self.assertEqual(paramountplus.series_run_years("2025", records, date(2025, 2, 1)), ("2025", "2025", True))
        self.assertEqual(paramountplus.series_run_years("2025", records, date(2026, 1, 1)), ("2025", "2025", False))

    def test_explicit_handoff_renames_organizes_and_preserves_subtitle_suffixes(self):
        meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            download = Path(temp) / "download"
            download.mkdir()
            video = download / "manifest_2026-08-29_12-00-00.mp4"
            subtitle = download / "manifest_2026-08-29_12-00-00.en_us.srt"
            video.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")
            settings = {
                "paramountplus_series_metadata_enabled": True,
                "paramountplus_series_rename_enabled": True,
                "paramountplus_series_organize_enabled": True,
            }
            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"\x89PNG\r\n\x1a\npng" if target.suffix == ".png" else b"asset")
                return target

            with patch.object(base, "download_binary", side_effect=fake_download):
                saved = base.save_paramountplus_series_metadata(meta, settings, explicit_folder=str(video))
            root = download / "SpongeBob SquarePants (1999-)"
            season = root / "S01"
            stem = "S01E01 SpongeBob SquarePants - Help Wanted"
            self.assertTrue((season / f"{stem}.mp4").exists())
            self.assertTrue((season / f"{stem}.en_us.srt").exists())
            self.assertTrue((season / f"{stem}.nfo").exists())
            self.assertTrue((season / f"{stem}-thumb.png").exists())
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertTrue((root / "poster.png").exists())
            self.assertTrue((root / "backdrop.png").exists())
            self.assertTrue((root / "logo.png").exists())
            self.assertTrue((root / "trailers" / "trailer.mp4").exists())
            self.assertTrue(saved)

    def test_show_queue_matches_episode_ids_before_stale_positions(self):
        with patch.object(paramountplus, "fetch_text", return_value=SHOW_PAGE + SECOND_EPISODE):
            item = paramountplus.show_metadata_from_page(SHOW_PAGE + SECOND_EPISODE, SHOW_URL, timeout=25)
        meta = base.metadata_from_provider_dict(item)
        with tempfile.TemporaryDirectory() as temp:
            stale = Path(temp) / f"S09E99 stale {EPISODE_URL.rstrip('/').split('/')[-1]}.mp4"
            second = Path(temp) / f"capture_{SECOND_EPISODE_ID}.mp4"
            stale.write_bytes(b"video")
            second.write_bytes(b"video")
            order: list[str] = []

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"\x89PNG\r\n\x1a\npng" if target.suffix == ".png" else b"asset")
                return target

            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base, "save_paramountplus_series_trailer", side_effect=lambda *_args: order.append("trailer") or []
            ), patch.object(
                base, "save_paramountplus_extra_videos", side_effect=lambda *_args: order.append("extras") or []
            ):
                base.save_paramountplus_series_metadata(meta, {}, explicit_folder=temp)

            root = Path(temp) / "SpongeBob SquarePants (1999-)" / "S01"
            first_stem = "S01E01 SpongeBob SquarePants - Help Wanted"
            second_stem = "S01E02 SpongeBob SquarePants - Reef Blower"
            self.assertTrue((root / f"{first_stem}.mp4").exists())
            self.assertTrue((root / f"{second_stem}.mp4").exists())
            self.assertTrue((root / f"{first_stem}-thumb.png").exists())
            self.assertTrue((root / f"{second_stem}-thumb.png").exists())
            self.assertFalse(any("poster" in path.name.casefold() for path in root.iterdir()))
            self.assertEqual(order, ["trailer", "extras"])

    def test_explicit_output_root_consolidates_multiple_source_folders(self):
        with patch.object(paramountplus, "fetch_text", return_value=SHOW_PAGE + SECOND_EPISODE):
            item = paramountplus.show_metadata_from_page(SHOW_PAGE + SECOND_EPISODE, SHOW_URL, timeout=25)
        meta = base.metadata_from_provider_dict(item)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first_source = root / "SpongeBob S01 540p"
            second_source = root / "SpongeBob S01 576p"
            first_source.mkdir()
            second_source.mkdir()
            (first_source / "SpongeBob S01E01.mp4").write_bytes(b"video")
            (second_source / "SpongeBob S01E02.mp4").write_bytes(b"video")

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"\x89PNG\r\n\x1a\npng" if target.suffix == ".png" else b"asset")
                return target

            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base, "save_paramountplus_series_trailer", return_value=[]
            ), patch.object(base, "save_paramountplus_extra_videos", return_value=[]):
                base.save_paramountplus_series_metadata(meta, {}, explicit_folder=temp)

            show = root / "SpongeBob SquarePants (1999-)"
            self.assertTrue((show / "S01" / "S01E01 SpongeBob SquarePants - Help Wanted.mp4").exists())
            self.assertTrue((show / "S01" / "S01E02 SpongeBob SquarePants - Reef Blower.mp4").exists())
            self.assertFalse(first_source.exists())
            self.assertFalse(second_source.exists())

    def test_episode_page_carries_the_complete_parent_catalog(self):
        def fixture(url: str, timeout: int = 25):
            return SHOW_PAGE + SECOND_EPISODE if url == SHOW_URL else EPISODE_PAGE

        with patch.object(paramountplus, "fetch_text", side_effect=fixture):
            item = paramountplus.extract_metadata(EPISODE_URL)
        self.assertEqual(len(item["series_episodes"]), 2)

    def test_dedicated_season_one_page_completes_partial_main_catalog(self):
        with patch.object(paramountplus, "fetch_text", return_value=SHOW_PAGE + SECOND_EPISODE) as fetch:
            item = paramountplus.show_metadata_from_page(SHOW_PAGE, SHOW_URL, timeout=25)
        self.assertEqual(len(item["series_episodes"]), 2)
        fetch.assert_called_once_with(SHOW_URL + "episodes/1/", timeout=25)

    def test_broad_root_rejects_unrelated_same_episode_number(self):
        meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            unrelated = Path(temp) / "Another Show" / "S01"
            unrelated.mkdir(parents=True)
            (unrelated / "S01E01 Another Show.mp4").write_bytes(b"video")
            settings = {"media_folders": [temp], "paramountplus_series_metadata_enabled": True}
            self.assertEqual(base.paramountplus_media_groups(meta, settings), [])
            self.assertEqual(base.save_paramountplus_series_metadata(meta, settings), [])

    def test_existing_series_root_is_reused_without_nesting(self):
        meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "SpongeBob SquarePants (1999-)"
            season = root / "S01"
            season.mkdir(parents=True)
            video = season / "S01E01 SpongeBob SquarePants - Help Wanted.mp4"
            video.write_bytes(b"video")
            groups = base.paramountplus_media_groups(meta, {}, explicit_folder=str(video))
            prepared = base.prepare_paramountplus_media_group(meta, groups[0][0], {})
            self.assertEqual(prepared.folder, season.resolve())
            self.assertFalse((root / root.name).exists())

    def test_folder_collision_is_refused(self):
        meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            legacy = Path(temp) / SHOW
            legacy.mkdir()
            video = legacy / "S01E01.mp4"
            video.write_bytes(b"video")
            (Path(temp) / "SpongeBob SquarePants (1999-)").mkdir()
            group = base.ParamountPlusMediaGroup(legacy, video.stem, 1, 1, [video])
            with self.assertRaises(FileExistsError):
                base.migrate_paramountplus_series_folder(group, meta)

    def test_closed_run_migrates_the_whole_current_series_root(self):
        meta = base.metadata_from_provider_dict(self.extract_episode())
        meta.series_is_current = False
        meta.series_end_year = "2026"
        with tempfile.TemporaryDirectory() as temp:
            old_root = Path(temp) / "SpongeBob SquarePants (1999-)"
            season = old_root / "S01"
            season.mkdir(parents=True)
            video = season / "S01E01 SpongeBob SquarePants - Help Wanted.mp4"
            video.write_bytes(b"video")
            (old_root / "poster.jpg").write_bytes(b"poster")
            group = base.ParamountPlusMediaGroup(season, video.stem, 1, 1, [video])
            migrated = base.migrate_paramountplus_series_folder(group, meta)
            new_root = Path(temp) / "SpongeBob SquarePants (1999-2026)"
            self.assertEqual(migrated.folder, (new_root / "S01").resolve())
            self.assertTrue((new_root / "poster.jpg").exists())
            self.assertFalse(old_root.exists())

    def test_paramountplus_movie_preview_uses_native_trailer_folder(self):
        meta = base.Metadata(
            source_url="https://www.paramountplus.com/movies/video/example/",
            source_site="Paramount+",
            title="Example Movie",
            year="2026",
            poster_url="https://img.example/poster.jpg",
            trailer_url="https://splice.paramountplus.com/previewhls/master.m3u8",
            tags=["Paramount+ Provider"],
            extra_fields={"Paramount+ movie ID": ["MOVIE1"]},
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(
            base, "download_binary", side_effect=lambda _url, target: (target.write_bytes(b"asset"), target)[1]
        ):
            settings = {"default_output_dir": temp}
            base.save_metadata_bundle(meta, settings)
            root = Path(temp) / "Paramount+" / "Example Movie (2026)"
            self.assertTrue((root / "trailers" / "trailer.mp4").exists())
            self.assertFalse((root / "Extras" / "Trailers").exists())

    def test_movie_handoff_stays_under_supplied_folder_with_source_art_roles(self):
        item = paramountplus.movie_metadata_from_page(MOVIE_PAGE, MOVIE_URL)
        self.assertEqual(item["poster_url"], "https://img.example/movie-poster.jpg")
        self.assertEqual(item["fanart_url"], "https://img.example/movie_w1920_pplcrn_backdrop.jpg")
        self.assertEqual(item["gallery_urls"], [])
        self.assertEqual(item["extra_fields"]["Audio"], ["English"])
        self.assertEqual(item["extra_fields"]["Subtitles"], ["English - CC"])
        meta = base.metadata_from_provider_dict(item)
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "manifest_movie.mp4"
            subtitle = Path(temp) / "manifest_movie.en.srt"
            video.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")
            order: list[str] = []

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"\x89PNG\r\n\x1a\nasset" if target.suffix == ".png" else b"asset")
                return target

            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base, "save_paramountplus_series_trailer", side_effect=lambda *_args: order.append("trailer") or []
            ), patch.object(
                base, "save_paramountplus_extra_videos", side_effect=lambda *_args: order.append("extras") or []
            ):
                base.save_metadata_bundle(meta, {}, explicit_folder=temp)

            root = Path(temp) / "Example Movie (2026)"
            self.assertTrue((root / "Example Movie (2026).mp4").exists())
            self.assertTrue((root / "Example Movie (2026).en.srt").exists())
            self.assertTrue((root / "Example Movie (2026)-poster.png").exists())
            self.assertTrue((root / "Example Movie (2026)-backdrop.png").exists())
            self.assertTrue((root / "Example Movie (2026)-logo.png").exists())
            self.assertFalse((root / "Example Movie (2026)-fanart.jpg").exists())
            self.assertFalse((root / "Example Movie (2026)-banner.jpg").exists())
            self.assertFalse((root / "Example Movie (2026)-landscape.jpg").exists())
            self.assertEqual(order, ["trailer", "extras"])

    def test_movie_prefers_visible_year_and_rejects_landscape_poster(self):
        page = MOVIE_PAGE.replace(
            "https://img.example/movie-poster.jpg",
            "https://img.example/movie_16.9_1920x1080.jpg",
        ) + '<span class="movie__air-year">1991</span>'
        item = paramountplus.movie_metadata_from_page(page, MOVIE_URL)
        self.assertEqual(item["year"], "1991")
        self.assertEqual(item["poster_url"], "")
        self.assertEqual(item["fanart_url"], "https://img.example/movie_w1920_pplcrn_backdrop.jpg")

    def test_missing_ffmpeg_skips_only_optional_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "trailer.mp4"
            with patch.object(base, "fetch_bytes", return_value=b"#EXTM3U\n#EXTINF:1"), patch.object(
                base.subprocess, "run", side_effect=FileNotFoundError
            ):
                self.assertIsNone(base.download_public_hls("https://example.test/trailer.m3u8", target))
            self.assertFalse(target.exists())

    def test_paramount_cdn_requested_format_controls_saved_extension(self):
        self.assertEqual(
            base.image_extension_from_url("https://img.example/title.png?format=webp"),
            ".webp",
        )

    def test_all_paramount_art_is_saved_as_genuine_png(self):
        with patch.object(paramountplus, "fetch_text", return_value=SHOW_PAGE):
            item = paramountplus.show_metadata_from_page(SHOW_PAGE, SHOW_URL, timeout=25)
        meta = base.metadata_from_provider_dict(item)
        meta.logo_url = "https://img.example/title.webp?format=webp"
        with tempfile.TemporaryDirectory() as temp:
            def fake_download(_url: str, target: Path):
                target.write_bytes(b"RIFF\x08\x00\x00\x00WEBPasset")
                return target

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"\x89PNG\r\n\x1a\npng")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base.shutil, "which", return_value="/usr/bin/sips"
            ), patch.object(base.subprocess, "run", side_effect=fake_run):
                saved = base.save_paramountplus_show_art(meta, Path(temp))
            for name in ("poster.png", "backdrop.png", "logo.png"):
                path = Path(temp) / name
                self.assertTrue(path.exists())
                self.assertEqual(base.image_file_extension(path), ".png")
                self.assertIn(path, saved)
            self.assertFalse(any(path.suffix in {".jpg", ".webp"} for path in Path(temp).iterdir()))


if __name__ == "__main__":
    unittest.main()
