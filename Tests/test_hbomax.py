from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
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


hbomax = load_module("test_hbomax_provider", ROOT / "Provider Scripts" / "hbomax.py")
base = load_module("test_hbomax_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")

MOVIE = "https://play.hbomax.com/movie/fad09d13-9973-4de6-9387-8698ba6ef4cf"
SHOW = "https://play.hbomax.com/show/4ffd33c9-e0d6-4cd6-bd13-34c266c79be0"
EPISODE_ID = "a4c77a14-d711-440f-9907-0afc17f0e2a9"
EPISODE = f"https://www.hbomax.com/show/4ffd33c9-e0d6-4cd6-bd13-34c266c79be0/s1/e1-pilot/{EPISODE_ID}"


def episode(number: int, identifier: str, title: str, season: int = 1) -> dict:
    return {
        "episodeNumber": number,
        "episodeUrl": f"/show/4ffd33c9-e0d6-4cd6-bd13-34c266c79be0/s{season}/e{number}/{identifier}",
        "title": {"short": title, "full": title},
        "summary": {"short": f"Short {number}", "full": f"Full episode {number}"},
        "images": {
            "default": f"https://img.example/episode-{number}-thumb.jpg",
            "centered-background-small": f"https://img.example/episode-{number}-portrait.jpg",
            "cover-artwork": f"https://img.example/episode-{number}-square.jpg",
        },
        "offeringDates": {"startDate": "2023-02-01T05:00:00Z", "endDate": "2101-01-01T04:59:00Z"},
        "flags": {"isWatchFree": False},
    }


def show_record(complete: bool) -> dict:
    seasons = [
        {
            "seasonId": "season-one", "seasonNumber": 1, "numberOfEpisodes": 2,
            "episodes": [episode(1, EPISODE_ID, "Pilot")] + ([episode(2, "5175ef20-29bc-499d-930e-f50805ff266d", "Next")] if complete else []),
        },
        {
            "seasonId": "season-two", "seasonNumber": 2, "numberOfEpisodes": 1,
            "episodes": [episode(1, "7f388f5d-89f6-42fd-a74c-197d3e535885", "Season Two", season=2)] if complete else [],
        },
    ]
    return {
        "hbomaxId": "4ffd33c9-e0d6-4cd6-bd13-34c266c79be0", "seriesId": "4ffd33c9-e0d6-4cd6-bd13-34c266c79be0",
        "imageUrlLink": "/show/4ffd33c9-e0d6-4cd6-bd13-34c266c79be0",
        "title": {"short": "Euphoria", "full": "Euphoria"},
        "summary": {"short": "Short series", "full": "Full series description"},
        "releaseYear": "2019", "numberOfSeasons": 2, "numberOfEpisodes": 3,
        "genres": ["Drama"], "primaryGenre": "Drama", "secondaryGenre": "",
        "brand": ["HBOTV"], "status": "published",
        "localizedRating": {"rating_authority": "us-fcc-tv", "classifier": "TV-MA", "descriptors": ["L", "S", "V"]},
        "credits": {"starring": "Zendaya", "directors": "Sam Levinson", "writers": "Sam Levinson", "producers": "Producer", "creators": "Sam Levinson", "sources": ""},
        "images": {"cover-artwork": "https://img.example/poster.jpg", "default-wide": "https://img.example/backdrop.jpg", "centered-background": "https://img.example/fanart.jpg", "cover-artwork-horizontal": "https://img.example/thumb.jpg", "logo-centered": "https://img.example/logo.png"},
        "trailer": {"programId": "PROM649125", "title": "Euphoria: Tease", "description": "Trailer description", "url": "/video/watch/PROM649125"},
        "seasons": seasons,
    }


def movie_record() -> dict:
    return {
        "hbomaxId": "fad09d13-9973-4de6-9387-8698ba6ef4cf", "featureId": "fad09d13-9973-4de6-9387-8698ba6ef4cf",
        "title": {"short": "The Drama", "full": "The Drama"},
        "summary": {"short": "Short movie", "full": "Full movie description"},
        "releaseYear": "2026", "releaseDate": "2026-04-01", "runtime": "1h 46m",
        "genres": ["Comedy", "Drama"], "primaryGenre": "Comedy", "secondaryGenre": "Drama",
        "brand": ["HBOTV"], "localizedRating": {"rating_authority": "us-mpaa-film", "classifier": "R", "descriptors": []},
        "credits": {"starring": "Zendaya, Robert Pattinson", "directors": "Kristoffer Borgli", "writers": "Kristoffer Borgli", "producers": "Amy Greene", "creators": "", "sources": ""},
        "images": {"cover-artwork": "https://img.example/movie-poster.jpg", "default-wide": "https://img.example/movie-backdrop.jpg", "centered-background": "https://img.example/movie-fanart.jpg", "cover-artwork-horizontal": "https://img.example/movie-thumb.jpg", "logo-centered": "https://img.example/movie-logo.png"},
    }


def page(record: dict) -> str:
    payload = {"props": {"pageProps": {"mappedData": {"idref": record}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


class HBOMaxTests(unittest.TestCase):
    def extract(self, url: str):
        def fetch(page_url: str, timeout: int = 25):
            if "/movie/" in page_url:
                return page(movie_record())
            return page(show_record(complete=EPISODE_ID in page_url and "/s1/" in page_url))
        with patch.object(hbomax, "fetch_text", side_effect=fetch):
            return hbomax.extract_metadata(url)

    def test_movie_selected_fields_and_single_title_art_roles(self):
        item = self.extract(MOVIE)
        self.assertEqual((item["title"], item["year"], item["date"], item["runtime_minutes"]), ("The Drama", "2026", "2026-04-01", "106"))
        self.assertEqual(item["outline"], "Short movie")
        self.assertEqual(item["plot"], "Full movie description")
        self.assertEqual(item["poster_url"], "https://img.example/movie-poster.jpg")
        self.assertEqual(item["fanart_url"], "https://img.example/movie-backdrop.jpg")
        self.assertEqual(item["thumb_url"], "https://img.example/movie-thumb.jpg")
        self.assertEqual(item["logo_url"], "https://img.example/movie-logo.png")
        self.assertEqual(item["tags"], ["HBO Max", "Provider: HBO Max", "HBO Max Provider"])

    def test_show_enriches_complete_guide_and_keeps_trailer_metadata(self):
        item = self.extract(SHOW)
        self.assertEqual(len(item["series_episodes"]), 3)
        self.assertEqual(
            [(record["season"], record["episode"]) for record in item["series_episodes"]],
            [(1, 1), (1, 2), (2, 1)],
        )
        self.assertEqual(item["extra_fields"]["Trailer title"], ["Euphoria: Tease"])
        self.assertEqual(item["extra_fields"]["Trailer program ID"], ["PROM649125"])
        self.assertEqual(item["trailer_url"], "https://play.hbomax.com/video/watch/PROM649125")

    def test_exact_episode_has_only_one_landscape_thumb(self):
        item = self.extract(EPISODE)
        self.assertEqual(item["media_kind"], "episode")
        self.assertEqual((item["season_number"], item["episode_number"], item["episode_title"]), ("1", "1", "Pilot"))
        self.assertEqual(item["thumb_url"], "https://img.example/episode-1-thumb.jpg")
        self.assertNotIn("poster_url", item)
        self.assertNotIn("gallery_urls", item)

    def test_optional_episode_date_runtime_and_languages_are_source_backed(self):
        record = episode(1, EPISODE_ID, "Pilot")
        record.update({
            "releaseDate": "2019-06-16T01:00:00Z",
            "runtime": "58m",
            "audioLanguages": [{"displayName": "English - Original"}],
            "subtitleTracks": [{"label": "English - CC"}],
        })
        item = show_record(complete=True)
        item["seasons"][0]["episodes"][0] = record
        series = hbomax.series_metadata(item, SHOW)
        selected = series["series_episodes"][0]
        episode_item = hbomax.episode_metadata(series, selected, EPISODE)
        self.assertEqual((episode_item["date"], episode_item["year"], episode_item["runtime_minutes"]), ("2019-06-16", "2019", "58"))
        self.assertEqual(episode_item["extra_fields"]["Audio"], ["English - Original"])
        self.assertEqual(episode_item["extra_fields"]["Subtitles"], ["English - CC"])

    def test_uuid_matching_outranks_stale_filename_position(self):
        meta = base.metadata_from_provider_dict(self.extract(SHOW))
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / f"S02E01 stale {EPISODE_ID}.mkv"
            video.write_bytes(b"video")
            matches = base.hbomax_media_groups(meta, {}, explicit_folder=temp)
            self.assertEqual(len(matches), 1)
            self.assertEqual((matches[0][0].season, matches[0][0].episode), (1, 1))

    def test_queue_matches_uuid_and_saves_only_one_episode_image(self):
        meta = base.metadata_from_provider_dict(self.extract(SHOW))
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / f"{EPISODE_ID}_corrected.mkv"
            video.write_bytes(b"video")
            downloaded: list[Path] = []
            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(b"art"); downloaded.append(target); return target
            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base, "save_hbomax_trailer", return_value=[]
            ) as trailer, patch.object(base, "save_hbomax_extra_videos", return_value=[]) as extras:
                saved = base.save_hbomax_series_metadata(meta, {}, explicit_folder=temp)
            root = Path(temp) / "Euphoria (2019-)"
            stem = "S01E01 Euphoria - Pilot"
            self.assertTrue((root / "S01" / f"{stem}.mkv").exists())
            self.assertTrue((root / "S01" / f"{stem}.nfo").exists())
            self.assertTrue((root / "S01" / f"{stem}-thumb.jpg").exists())
            self.assertFalse((root / "S01" / f"{stem}-poster.jpg").exists())
            self.assertFalse((root / "S01" / f"{stem}-cover.jpg").exists())
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertIn("<tag>HBO Max Provider</tag>", (root / "tvshow.nfo").read_text(encoding="utf-8"))
            self.assertIn(
                "<tag>HBO Max Provider</tag>",
                (root / "S01" / f"{stem}.nfo").read_text(encoding="utf-8"),
            )
            self.assertTrue(saved)
            trailer.assert_called_once()
            extras.assert_called_once()

    def test_single_episode_bundle_never_promotes_episode_thumb_to_series_root(self):
        meta = base.metadata_from_provider_dict(self.extract(EPISODE))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "Euphoria (2019-)"
            season = root / "S01"
            downloaded: list[tuple[str, Path]] = []

            def fake_download(url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"art")
                downloaded.append((url, target))
                return target

            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base, "save_hbomax_trailer", return_value=[]
            ):
                base.ensure_hbomax_series_bundle(meta, root)
                base.save_metadata_bundle_to_location(
                    meta,
                    season,
                    "S01E01 Euphoria - Pilot",
                )

            episode_thumb = root / "S01" / "S01E01 Euphoria - Pilot-thumb.jpg"
            self.assertTrue(episode_thumb.exists())
            self.assertTrue((root / "thumb.jpg").exists())
            self.assertFalse(any("poster" in path.name.casefold() for path in (root / "S01").iterdir()))
            self.assertEqual(
                [(url, path) for url, path in downloaded if path.parent == root / "S01"],
                [("https://img.example/episode-1-thumb.jpg", episode_thumb)],
            )
            self.assertIn(("https://img.example/thumb.jpg", root / "thumb.jpg"), downloaded)

    def test_standalone_player_episode_refuses_to_guess_parent(self):
        player = f"https://play.hbomax.com/video/watch/{EPISODE_ID}"
        with patch.object(hbomax, "fetch_text", return_value=page({})):
            with self.assertRaisesRegex(ValueError, "show URL in Queue Mode"):
                hbomax.extract_metadata(player)

    def test_movie_handoff_stays_under_supplied_folder_and_saves_title_art_once(self):
        meta = base.metadata_from_provider_dict(self.extract(MOVIE))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "manifest_download.mkv"
            subtitle = Path(temp) / "manifest_download.en.srt"
            source.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")

            def fake_download(_url: str, target: Path):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"\x89PNG\r\n\x1a\nart" if target.suffix == ".png" else b"art")
                return target

            workflow_order: list[str] = []

            def fake_trailer(_meta, folder: Path):
                self.assertTrue((folder / "The Drama (2026).nfo").exists())
                workflow_order.append("trailer")
                return []

            def fake_extras(_meta, folder: Path):
                self.assertTrue((folder / "The Drama (2026)-poster.jpg").exists())
                workflow_order.append("extras")
                return []

            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base, "save_hbomax_trailer", side_effect=fake_trailer
            ), patch.object(base, "save_hbomax_extra_videos", side_effect=fake_extras):
                base.save_metadata_bundle(meta, {}, explicit_folder=temp)

            root = Path(temp) / "The Drama (2026)"
            self.assertTrue((root / "The Drama (2026).mkv").exists())
            self.assertTrue((root / "The Drama (2026).en.srt").exists())
            self.assertTrue((root / "The Drama (2026).nfo").exists())
            for role in ("poster", "backdrop", "thumb", "logo"):
                self.assertEqual(len(list(root.glob(f"The Drama (2026)-{role}.*"))), 1)
            self.assertFalse(any(path.name.endswith("-poster.jpg") for path in root.rglob("S*/*")))
            self.assertEqual(workflow_order, ["trailer", "extras"])

    def test_clear_max_dash_trailer_uses_jellyfin_trailer_folder(self):
        meta = base.Metadata(
            source_url=MOVIE,
            source_site=hbomax.NAME,
            media_kind="movie",
            title="The Drama",
            trailer_url="https://gcp.amer-free.prd.media.max.com/amer/public-trailer/dash.mpd",
        )
        with tempfile.TemporaryDirectory() as temp:
            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"video")
                return __import__("subprocess").CompletedProcess(command, 0)

            with patch.object(base, "fetch_bytes", return_value=b'<MPD mediaPresentationDuration="PT2M"><Period/></MPD>'), patch.object(
                base.subprocess, "run", side_effect=fake_run
            ):
                saved = base.save_hbomax_trailer(meta, Path(temp))
            self.assertEqual(saved, [Path(temp) / "trailers" / "trailer.mp4"])
            self.assertTrue(saved[0].exists())

    def test_public_extra_page_is_resolved_and_saved_as_real_video(self):
        meta = base.Metadata(source_url=SHOW, source_site=hbomax.NAME, media_kind="series", title="Euphoria")
        meta.extra_videos = [base.ExtraMedia(title="Behind the Scenes", url="https://play.hbomax.com/video/watch/PROM123")]
        direct = "https://gcp.amer-free.prd.media.max.com/amer/public-extra/dash.mpd"
        with tempfile.TemporaryDirectory() as temp:
            def fake_download(url: str, target: Path):
                self.assertEqual(url, direct)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"video")
                return target

            with patch.object(base, "hbomax_capture_public_preview", return_value=direct), patch.object(
                base, "download_binary", side_effect=fake_download
            ):
                saved = base.save_hbomax_extra_videos(meta, Path(temp))
            self.assertEqual(saved, [Path(temp) / "Extras" / "Videos" / "Behind the Scenes.mp4"])

    def test_non_png_max_logo_is_converted_instead_of_mislabeled(self):
        with tempfile.TemporaryDirectory() as temp:
            logo = Path(temp) / "logo.png"
            logo.write_bytes(b"\xff\xd8\xffjpeg")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"\x89PNG\r\n\x1a\npng")
                return __import__("subprocess").CompletedProcess(command, 0)

            with patch.object(base.shutil, "which", return_value="/usr/bin/sips"), patch.object(
                base.subprocess, "run", side_effect=fake_run
            ):
                result = base.normalize_hbomax_logo_file(logo)
            self.assertEqual(result, logo)
            self.assertEqual(base.image_file_extension(result), ".png")


if __name__ == "__main__":
    unittest.main()
