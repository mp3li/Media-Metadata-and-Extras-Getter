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
SHOW_URL = "https://www.paramountplus.com/shows/spongebob-squarepants/"
SHOW = "SpongeBob SquarePants"


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
<article class="grid-view-item" data-tracking="x|S1|Ep1|x|Help Wanted||">
  <a href="/shows/video/ZvEow_nZm5WAiLeMlEmISm3Deti40Ciu/" aa-link="Full Episodes||play|1|SpongeBob SquarePants"></a>
  <div class="meta-wrapper title-shorten">S1 E1 Help Wanted</div>
  <div class="description-wrapper">SpongeBob applies for a job.</div>
  <meta itemprop="duration" content="PT23M">
  <time datetime="2026-08-20"></time>
  <img vilynx-id="ZvEow_nZm5WAiLeMlEmISm3Deti40Ciu" src="https://thumbnails.cbsig.net/_x/w640/episode.jpg">
</article>
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
        item = paramountplus.show_metadata_from_page(SHOW_PAGE, SHOW_URL, timeout=25)
        self.assertEqual(item["media_kind"], "series")
        self.assertEqual(item["series_start_year"], "1999")
        self.assertEqual(item["series_end_year"], "2026")
        self.assertTrue(item["series_is_current"])
        self.assertEqual(len(item["series_episodes"]), 1)
        root = ET.fromstring(base.build_nfo(base.metadata_from_provider_dict(item)))
        self.assertEqual(root.tag, "tvshow")
        self.assertIn("Paramount+ Provider", [node.text for node in root.findall("tag")])

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
            with patch.object(base, "download_binary", side_effect=lambda _url, target: target.write_bytes(b"asset") or target):
                saved = base.save_paramountplus_series_metadata(meta, settings, explicit_folder=str(video))
            root = download / "SpongeBob SquarePants (1999-)"
            season = root / "S01"
            stem = "S01E01 SpongeBob SquarePants - Help Wanted"
            self.assertTrue((season / f"{stem}.mp4").exists())
            self.assertTrue((season / f"{stem}.en_us.srt").exists())
            self.assertTrue((season / f"{stem}.nfo").exists())
            self.assertTrue((season / f"{stem}-thumb.jpg").exists())
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertTrue((root / "poster.jpg").exists())
            self.assertTrue((root / "backdrop.jpg").exists())
            self.assertTrue((root / "logo.png").exists())
            self.assertTrue((root / "trailers" / "trailer.mp4").exists())
            self.assertTrue(saved)

    def test_broad_root_rejects_unrelated_same_episode_number(self):
        meta = base.metadata_from_provider_dict(self.extract_episode())
        with tempfile.TemporaryDirectory() as temp:
            unrelated = Path(temp) / "Another Show" / "S01"
            unrelated.mkdir(parents=True)
            (unrelated / "S01E01 Another Show.mp4").write_bytes(b"video")
            settings = {"media_folders": [temp], "paramountplus_series_metadata_enabled": True}
            self.assertEqual(base.paramountplus_media_groups(meta, settings), [])

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


if __name__ == "__main__":
    unittest.main()
