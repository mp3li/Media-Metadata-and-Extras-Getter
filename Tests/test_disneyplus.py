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
SERIES_URL = "https://www.disneyplus.com/browse/entity-2e025d27-260e-48ce-a038-c87707de8e9e"
EPISODE_URL = "https://www.disneyplus.com/play/ad5f6c58-8513-4de1-8420-350ce867ffdd"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


disneyplus = load_module("test_disneyplus_provider", ROOT / "Provider Scripts" / "disneyplus.py")
base = load_module("test_disneyplus_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")


def image(source: str = "", ripcut_id: str = ""):
    return {"defaultImage": {"source": source, "ripcutId": ripcut_id, "imageId": ripcut_id}}


def episode(episode_id: str, number: int, title: str):
    return {
        "_type": "ImageCard",
        "_id": episode_id,
        "title": f"S1:E{number} {title}",
        "imageVariants": image(ripcut_id=f"thumb-{number}"),
        "metadata": {"summary": f"Description for {title}."},
    }


def next_data():
    first = episode("ad5f6c58-8513-4de1-8420-350ce867ffdd", 1, "Taxi")
    second = episode("a1e78cb3-2704-4fa2-bf6a-ef0de2d3a233", 2, "Here Come the Grannies")
    main = [
        {
            "_type": "DetailEntityHero",
            "releaseYear": "2026",
            "seasonsAvailable": "1 Season",
            "synopsisText": "Enjoy the most popular tracks from the Bluey Albums.",
            "genres": ["Comedy", "Music", "Animation"],
            "detailIcons": [{"alt": "TV-Y"}, {"alt": "Subtitles / CC"}],
            "backgroundImage": image("https://img.example/backdrop.webp?format=webp"),
            "titleVisual": image(
                "https://img.example/logo.webp?format=webp",
                "logo-id",
            ),
        },
        {
            "_type": "MediaDetails",
            "title": "Bluey Tunes",
            "summary": "Bluey Tunes is a musical adventure.",
            "release": "2026",
            "genres": ["Comedy", "Music", "Animation"],
            "ratings": [{"image": {"alt": "TV-Y"}}],
            "credits": [{"heading": "Creator:", "items": [{"displayText": "Ludo Studio"}]}],
        },
        {
            "_type": "Episodes",
            "seriesTitle": "Bluey Tunes",
            "episodes": [first, second],
            "seasons": [{"id": "season-1", "name": "Season 1"}],
            "selectedSeasonId": "season-1",
            "seoSeasons": [{"seasonId": "season-1", "seasonName": "Season 1", "episodes": [first, second]}],
        },
        {
            "_type": "Metadata",
            "metaTags": [
                {"property": "og:title", "content": "Bluey Tunes | Watch Full Episodes | Disney+"},
                {"name": "description", "content": "Enjoy top Bluey album songs."},
                {"property": "og:image", "content": "https://disney.images.edge.bamgrid.com/ripcut-delivery/v2/variant/disney/poster-id/compose?aspectRatio=1.78&format=webp&width=1200"},
                {"property": "og:url", "content": SERIES_URL},
            ],
        },
    ]
    return {"props": {"pageProps": {"stitchDocument": {"mainContent": main}}}}


def page_fixture():
    return (
        f'<link rel="canonical" href="{SERIES_URL}">'
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data())}</script>'
    )


class DisneyPlusProviderTests(unittest.TestCase):
    def extract(self, url: str):
        with patch.object(disneyplus, "fetch_text", return_value=page_fixture()):
            return disneyplus.extract_metadata(url)

    def test_series_metadata_uses_complete_public_guide_and_jellyfin_art(self):
        item = self.extract(SERIES_URL)
        self.assertEqual(item["media_kind"], "series")
        self.assertEqual(item["title"], "Bluey Tunes")
        self.assertEqual((item["series_start_year"], item["series_end_year"]), ("2026", "2026"))
        self.assertFalse(item["series_is_current"])
        self.assertEqual(len(item["series_episodes"]), 2)
        self.assertEqual(item["poster_url"], "")
        self.assertIn("aspectRatio=1.78", item["fanart_url"])
        self.assertEqual(item["thumb_url"], "https://img.example/backdrop.webp?format=webp")
        self.assertIn("logo-id/trim?format=png", item["logo_url"])
        self.assertEqual(item["gallery_urls"], [])
        self.assertIn("Disney+ Provider", item["tags"])
        self.assertEqual(item["extra_fields"]["Accessibility"], ["Subtitles / CC"])
        self.assertEqual(item["extra_fields"]["Creator"], ["Ludo Studio"])
        self.assertEqual(item["trailer_url"], "")
        root = ET.fromstring(base.build_nfo(base.metadata_from_provider_dict(item)))
        self.assertEqual(root.tag, "tvshow")

    def test_seo_seasons_and_selected_latest_season_are_merged(self):
        data = next_data()
        main = data["props"]["pageProps"]["stitchDocument"]["mainContent"]
        block = next(item for item in main if item.get("_type") == "Episodes")
        block["seoSeasons"] = [{
            "seasonId": "season-1",
            "seasonName": "Season 1",
            "episodes": [episode("old-season-id", 1, "Old Season")],
        }]
        latest = episode("latest-season-id", 1, "Latest Season")
        latest["title"] = "S2:E1 Latest Season"
        block["episodes"] = [latest]
        records = disneyplus.episode_records(block, "Example")
        self.assertEqual([(item["season"], item["episode"]) for item in records], [(1, 1), (2, 1)])

    def test_play_page_resolves_exact_episode_and_embeds_parent_series(self):
        item = self.extract(EPISODE_URL)
        self.assertEqual(item["media_kind"], "episode")
        self.assertEqual(item["title"], "Bluey Tunes")
        self.assertEqual((item["season_number"], item["episode_number"]), ("1", "1"))
        self.assertEqual(item["episode_title"], "Taxi")
        self.assertIn("thumb-1", item["thumb_url"])
        self.assertEqual(item["series_metadata"]["media_kind"], "series")
        self.assertEqual(item["extra_fields"]["Disney+ episode ID"], ["ad5f6c58-8513-4de1-8420-350ce867ffdd"])

    def test_play_webpage_is_never_treated_as_a_trailer(self):
        data = {"title": "Play", "url": EPISODE_URL, "nested": {"label": "Official Trailer", "url": EPISODE_URL}}
        self.assertEqual(disneyplus.public_trailer_url(data), "")

    def test_explicit_handoff_renames_organizes_preserves_subtitles_and_saves_root(self):
        meta = base.metadata_from_provider_dict(self.extract(EPISODE_URL))
        with tempfile.TemporaryDirectory() as temp:
            download = Path(temp) / "download"
            download.mkdir()
            video = download / "manifest_2026-08-29_12-00-00.mp4"
            subtitle = download / "manifest_2026-08-29_12-00-00.en_us.srt"
            video.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")
            settings = {
                "disneyplus_series_metadata_enabled": True,
                "disneyplus_series_rename_enabled": True,
                "disneyplus_series_organize_enabled": True,
            }
            def save_asset(_url, target):
                target.write_bytes(b"asset")
                return target
            with patch.object(base, "download_binary", side_effect=save_asset):
                saved = base.save_disneyplus_series_metadata(meta, settings, explicit_folder=str(video))
            root = download / "Bluey Tunes (2026)"
            season = root / "S01"
            stem = "S01E01 Bluey Tunes - Taxi"
            self.assertTrue((season / f"{stem}.mp4").exists())
            self.assertTrue((season / f"{stem}.en_us.srt").exists())
            self.assertTrue((season / f"{stem}.nfo").exists())
            self.assertTrue((season / f"{stem}-thumb.webp").exists())
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertTrue((root / "backdrop.webp").exists())
            self.assertTrue((root / "thumb.webp").exists())
            self.assertTrue((root / "logo.png").exists())
            self.assertFalse((root / "poster.webp").exists())
            self.assertFalse((root / "trailers").exists())
            self.assertTrue(saved)

    def test_broad_root_rejects_unrelated_same_episode_number(self):
        meta = base.metadata_from_provider_dict(self.extract(EPISODE_URL))
        with tempfile.TemporaryDirectory() as temp:
            unrelated = Path(temp) / "Another Show" / "S01"
            unrelated.mkdir(parents=True)
            (unrelated / "S01E01 Another Show.mp4").write_bytes(b"video")
            self.assertEqual(base.disneyplus_media_groups(meta, {"media_folders": [temp]}), [])

    def test_existing_root_is_reused_and_collision_is_refused(self):
        meta = base.metadata_from_provider_dict(self.extract(EPISODE_URL))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Bluey Tunes (2026)"
            season = root / "S01"
            season.mkdir(parents=True)
            video = season / "S01E01 Bluey Tunes - Taxi.mp4"
            video.write_bytes(b"video")
            groups = base.disneyplus_media_groups(meta, {}, explicit_folder=str(video))
            prepared = base.prepare_disneyplus_media_group(meta, groups[0][0], {})
            self.assertEqual(prepared.folder, season.resolve())
            legacy = Path(temp) / "Bluey Tunes"
            legacy.mkdir()
            legacy_video = legacy / "S01E01.mp4"
            legacy_video.write_bytes(b"video")
            group = base.DisneyPlusMediaGroup(legacy, legacy_video.stem, 1, 1, [legacy_video])
            with self.assertRaises(FileExistsError):
                base.migrate_disneyplus_series_folder(group, meta)

    def test_disney_movie_uses_year_folder_native_trailer_and_provider_tag(self):
        meta = base.Metadata(
            source_url="https://www.disneyplus.com/browse/entity-movie",
            source_site="Disney+", media_kind="movie", title="Example Movie", year="2026",
            fanart_url="https://img.example/backdrop.webp?format=webp",
            thumb_url="https://img.example/thumb.webp?format=webp",
            logo_url="https://img.example/logo.png?format=png",
            trailer_url="https://media.example/trailer.mp4", tags=["Disney+ Provider"],
        )
        with tempfile.TemporaryDirectory() as temp:
            def save_asset(_url, target):
                target.write_bytes(b"asset")
                return target
            with patch.object(base, "download_binary", side_effect=save_asset):
                base.save_metadata_bundle(meta, {"default_output_dir": temp})
            root = Path(temp) / "Disney+" / "Example Movie (2026)"
            self.assertTrue((root / "Example Movie (2026).nfo").exists())
            self.assertTrue((root / "Example Movie (2026)-backdrop.webp").exists())
            self.assertTrue((root / "Example Movie (2026)-thumb.webp").exists())
            self.assertTrue((root / "Example Movie (2026)-logo.png").exists())
            self.assertFalse((root / "Example Movie (2026)-poster.jpg").exists())
            self.assertFalse((root / "Example Movie (2026)-banner.jpg").exists())
            self.assertFalse((root / "Example Movie (2026)-landscape.jpg").exists())
            self.assertFalse((root / "Example Movie (2026)-fanart.jpg").exists())
            self.assertFalse((root / "extrafanart").exists())
            self.assertTrue((root / "trailers" / "trailer.mp4").exists())

    def test_disney_movie_handoff_stays_beneath_supplied_media_location(self):
        meta = base.Metadata(
            source_url="https://www.disneyplus.com/browse/entity-movie",
            source_site="Disney+", media_kind="movie", title="Descendants", year="2015",
            tags=["Disney+ Provider"],
        )
        with tempfile.TemporaryDirectory() as temp:
            selected = Path(temp) / "selected destination"
            selected.mkdir()
            video = selected / "ctr-all-download.mp4"
            subtitle = selected / "ctr-all-download.en_us.srt"
            video.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")
            default_output = Path(temp) / "wrong default output"

            saved = base.save_metadata_bundle(
                meta,
                {"default_output_dir": str(default_output)},
                explicit_folder=str(video),
            )

            root = selected / "Descendants (2015)"
            self.assertTrue((root / "Descendants (2015).mp4").exists())
            self.assertTrue((root / "Descendants (2015).en_us.srt").exists())
            self.assertTrue((root / "Descendants (2015).nfo").exists())
            self.assertFalse(default_output.exists())
            self.assertTrue(saved)


if __name__ == "__main__":
    unittest.main()
