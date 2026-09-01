from __future__ import annotations

import importlib.util
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


amazon = load_module("test_amazon_prime_provider", ROOT / "Provider Scripts" / "amazon.py")
base = load_module("test_amazon_prime_base", ROOT / "Base Script" / "media_metadata_and_extras_getter_base.py")

SEASON_1 = "https://www.primevideo.com/region/na/detail/SEASON0001"
SEASON_2 = "https://www.primevideo.com/region/na/detail/SEASON0002"
EPISODE_1 = "https://www.primevideo.com/region/na/detail/EPISODE001"


def header(season: int, year: int) -> dict:
    return {
        "title": f"Example Show - Season {season}",
        "parentTitle": "Example Show",
        "titleType": "season",
        "entityType": "TV Show",
        "seasonNumber": season,
        "releaseDate": f"Jan 0{season}, {year}",
        "releaseYear": year,
        "synopsis": f"Season {season} description.",
        "catalogId": f"gti-season-{season}",
        "images": {
            "covershot": "https://img.example/ignored-covershot.png",
            "heroshot": "https://img.example/backdrop.jpg",
            "packshot": "https://img.example/thumb.jpg",
            "titleLogo": "https://img.example/logo.png",
        },
        "genres": [{"text": "Reality"}],
        "studios": ["Amazon Studios"],
        "contributors": {
            "cast": [{"name": "Host Person"}],
            "directors": [{"name": "Director Person"}],
            "producers": [{"name": "Producer Person"}],
        },
        "ratingBadge": {"displayText": "TV-14"},
        "amazonRating": {"value": 3.8, "count": 280, "countFormatted": "280"},
        "reviews": {
            "allReviewsLink": "https://www.amazon.com/product-reviews/B08BYY92B2",
            "reviewsAnalysisModel": {"ratingsHistogram": {
                "fiveStar": {"percentageDisplay": "51%"},
                "fourStar": {"percentageDisplay": "18%"},
                "threeStar": {"percentageDisplay": "5%"},
                "twoStar": {"percentageDisplay": "13%"},
                "oneStar": {"percentageDisplay": "13%"},
            }},
        },
        "audioTracks": ["English", "English [Audio Description]"],
        "subtitles": ["English [CC]", "Español"],
        "isClosedCaption": True,
        "isDolby51": True,
        "isPrime": True,
        "isXRay": True,
    }


def episode_detail(number: int, year: int) -> dict:
    return {
        "title": "The Beginning" if number == 1 else "The Next Step",
        "titleType": "episode",
        "entityType": "TV Show",
        "episodeNumber": number,
        "synopsis": f"Episode {number} description.",
        "releaseDate": f"Jan 0{number}, {year}",
        "releaseYear": year,
        "duration": 3600 + number,
        "runtime": "1 h 0 min",
        "images": {"packshot": f"https://img.example/episode-{number}.jpg"},
        "audioTracks": ["English", "English [Audio Description]"],
        "subtitles": ["English [CC]"],
        "isClosedCaption": True,
        "isDolby51": True,
        "isPrime": True,
    }


def page(season: int, season_id: str, episode_id: str, year: int) -> dict:
    season_gti = f"gti-season-{season}"
    episode_gti = f"gti-episode-{season}"
    seasons = [
        {"sequenceNumber": 1, "seasonLink": "/region/na/detail/SEASON0001"},
        {"sequenceNumber": 2, "seasonLink": "/region/na/detail/SEASON0002"},
    ]
    return {"init": {"preparations": {"body": {
        "atf": {"state": {
            "pageTitleId": season_gti,
            "detail": {"headerDetail": {season_gti: header(season, year)}},
            "seasons": {season_gti: seasons},
            "action": {"atf": {season_gti: {"secondaryActions": [{
                "isTrailer": True,
                "playbackID": "gti-trailer",
                "playbackURL": "/region/na/detail/TRAILER001?autoplay=trailer",
            }]}}},
        }},
        "btf": {"state": {
            "detail": {"detail": {episode_gti: episode_detail(season, year)}},
            "self": {episode_gti: {
                "compactGTI": episode_id,
                "gti": episode_gti,
                "asins": [f"ASIN00000{season}"],
                "sequenceNumber": season,
                "titleType": "episode",
                "link": f"/region/na/detail/{episode_id}",
            }},
            "action": {"btf": {}},
            "episodeList": {"cardTitleIds": [episode_gti]},
        }},
    }}}}


PAGES = {
    "SEASON0001": page(1, "SEASON0001", "EPISODE001", 2020),
    "SEASON0002": page(2, "SEASON0002", "EPISODE002", 2021),
    "EPISODE001": page(1, "SEASON0001", "EPISODE001", 2020),
}


class AmazonPrimeProviderTests(unittest.TestCase):
    def extract(self, url: str):
        with patch.object(amazon, "prime_page", side_effect=lambda page_url, timeout=25: PAGES[amazon.prime_compact_id(page_url)]):
            return amazon.extract_metadata(url)

    def test_primevideo_urls_are_supported_without_removing_legacy_amazon(self):
        self.assertTrue(amazon.is_supported_url(SEASON_1))
        self.assertTrue(amazon.is_supported_url("https://www.amazon.com/gp/video/detail/B012345678"))
        legacy_page = """
            <html><head><title>Watch Legacy Movie - Prime Video</title>
            <meta property="og:image" content="https://img.example/legacy.jpg">
            <meta name="description" content="Legacy description."></head><body></body></html>
        """
        with patch.object(amazon, "fetch_text", return_value=legacy_page):
            legacy = amazon.extract_metadata("https://www.amazon.com/gp/video/detail/B012345678")
        self.assertEqual(legacy["source_site"], "amazon.com")
        self.assertEqual(legacy["title"], "Legacy Movie")

    def test_season_page_builds_multi_season_series_and_exact_rating_tags(self):
        item = self.extract(SEASON_1)
        self.assertEqual(item["source_site"], "Amazon Prime Video")
        self.assertEqual(item["media_kind"], "series")
        self.assertEqual(item["title"], "Example Show")
        self.assertEqual((item["series_start_year"], item["series_end_year"]), ("2020", "2021"))
        self.assertEqual(len(item["series_episodes"]), 2)
        self.assertEqual(item["tags"][2:], [
            "Amazon Prime Video Provider",
            "amazonratings: 3.8 / 5 from 280 ratings",
            "amazonrating5stars: 51%",
            "amazonrating4stars: 18%",
            "amazonrating3stars: 5%",
            "amazonrating2stars: 13%",
            "amazonrating1star: 13%",
        ])
        self.assertEqual(item["fanart_url"], "https://img.example/thumb.jpg")
        self.assertEqual(item["thumb_url"], "https://img.example/backdrop.jpg")
        self.assertEqual(item["logo_url"], "https://img.example/logo.png")
        self.assertEqual(
            item["trailer_url"],
            "https://www.primevideo.com/region/na/detail/TRAILER001?autoplay=trailer",
        )
        self.assertEqual(item.get("poster_url", ""), "")
        self.assertNotIn("ignored-covershot", repr(item))

    def test_episode_link_resolves_episode_and_parent_series(self):
        item = self.extract(EPISODE_1)
        self.assertEqual(item["media_kind"], "episode")
        self.assertEqual((item["season_number"], item["episode_number"]), ("1", "1"))
        self.assertEqual(item["episode_title"], "The Beginning")
        self.assertEqual(item["runtime_minutes"], "60")
        self.assertEqual(item["extra_fields"]["Runtime seconds"], ["3601"])
        self.assertEqual(item["unique_ids"]["primevideo"], "EPISODE001")
        self.assertEqual(item["series_metadata"]["title"], "Example Show")

    def test_exact_episode_handoff_uses_year_series_root_and_requested_art(self):
        meta = base.metadata_from_provider_dict(self.extract(EPISODE_1))
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "manifest_2026-08-29.mp4"
            subtitle = Path(temp) / "manifest_2026-08-29.en.srt"
            video.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")

            def fake_download(_url: str, target: Path):
                target.write_bytes(b"art")
                return target

            with patch.object(base, "download_binary", side_effect=fake_download), patch.object(
                base, "save_amazon_prime_series_trailer", return_value=[]
            ):
                saved = base.save_amazon_prime_series_metadata(meta, {}, explicit_folder=str(video))
            root = Path(temp) / "Example Show (2020-2021)"
            season = root / "S01"
            stem = "S01E01 Example Show - The Beginning"
            self.assertTrue((season / f"{stem}.mp4").exists())
            self.assertTrue((season / f"{stem}.en.srt").exists())
            self.assertTrue((season / f"{stem}.nfo").exists())
            self.assertTrue((season / f"{stem}-thumb.jpg").exists())
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertTrue((root / "backdrop.jpg").exists())
            self.assertTrue((root / "thumb.jpg").exists())
            self.assertTrue((root / "logo.png").exists())
            self.assertFalse((root / "poster.jpg").exists())
            self.assertTrue(saved)

    def test_queue_matches_titles_but_broad_root_rejects_another_show(self):
        meta = base.metadata_from_provider_dict(self.extract(SEASON_1))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "The Beginning.mp4").write_bytes(b"video")
            (root / "The Next Step.mp4").write_bytes(b"video")
            groups = base.amazon_prime_media_groups(meta, {}, explicit_folder=temp)
            self.assertEqual([(group.season, group.episode) for group, _record in groups], [(1, 1), (2, 2)])
        with tempfile.TemporaryDirectory() as temp:
            unrelated = Path(temp) / "Another Show" / "S01"
            unrelated.mkdir(parents=True)
            (unrelated / "S01E01 Another Show.mp4").write_bytes(b"video")
            self.assertEqual(base.amazon_prime_media_groups(meta, {"media_folders": [temp]}), [])

    def test_anonymous_series_handoff_refuses_to_guess_or_fall_back(self):
        meta = base.metadata_from_provider_dict(self.extract(SEASON_1))
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "9ce4090d-980a-4214-b74c-bf8b98cc0762_corrected.mkv"
            video.write_bytes(b"video")
            self.assertEqual(
                base.save_amazon_prime_series_metadata(meta, {}, explicit_folder=temp),
                [],
            )
            self.assertEqual(list(Path(temp).glob("*.nfo")), [])

    def test_prime_trailer_is_saved_last_in_jellyfin_native_folder(self):
        meta = base.metadata_from_provider_dict(self.extract(SEASON_1))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(base, "fetch_bytes", return_value=b'<video src="https://cdn.example/trailer.mp4">'), patch.object(
                base, "download_binary"
            ) as download:
                target = root / "trailers" / "trailer.mp4"
                download.side_effect = lambda _url, path: path
                saved = base.save_amazon_prime_series_trailer(meta, root)
            download.assert_called_once_with("https://cdn.example/trailer.mp4", target)
            self.assertEqual(saved, [target])


if __name__ == "__main__":
    unittest.main()
