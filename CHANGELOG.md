# Changelog

All notable project changes are documented here. Published entries are derived from the repository's Git history; the Unreleased section records completed local work that has not yet been committed.

## Unreleased

### Added

- Crunchyroll provider for public series and episode/watch pages using Crunchyroll's anonymous public catalog metadata.
- Crunchyroll portrait poster, wide backdrop, transparent title logo, and smaller episode-thumbnail saving with Jellyfin-standard artwork names.
- Ordered Jellyfin tags for episode upvotes/downvotes and the exact series average, rating total, and five-to-one-star distribution.
- Crunchyroll audio, subtitle, sub/dub, advisory, studio, launch year, season tag/count, episode count, exact runtime, original audio, separate air/upload dates, and next-episode metadata.
- Local-only Crunchyroll series matching with safe video/subtitle renaming and season-folder organization.
- End-of-workflow Crunchyroll series trailers in Jellyfin's native `trailers/trailer.mp4` location, preferring provider-supplied media and otherwise requiring an exact verified official Crunchyroll YouTube match.
- The exact `Crunchyroll Provider` tag on every Crunchyroll series and episode NFO.
- Paramount+ provider for public show, season, and episode pages.
- Paramount+ movie and public-clip page support, including cast, movie runtime/rating, clip metadata, and explicit clear-DASH safeguards.
- Full public season-guide extraction, including episode titles, placements, synopses, dates, IDs, public episode URLs, and exposed durations.
- Paramount+ show portrait, wide hero, social, logo, and 1920-pixel episode-art saving.
- Public, unencrypted Paramount+ autoplay-preview download support through standard `ffmpeg` remuxing only; no keys, DRM tooling, or protected playback support.
- User-designated related-world public teaser attachment for *Avatar Aang: The Last Airbender*, while preserving the teaser's own *Avatar: Seven Havens* identity and metadata.
- Paramount+ source and provider tags in generated NFO metadata.

### Changed

- Crunchyroll series folders now include provider-derived run years: `Series Title (Year)` for completed single-year runs, `Series Title (Start Year-End Year)` for completed multi-year runs, and `Series Title (Start Year-)` while currently airing, with legacy or stale year-qualified paths migrated atomically rather than nested.
- Crunchyroll's `yt-dlp`, FFmpeg, and JavaScript-runtime trailer dependencies are explicitly optional and isolated from startup, baseline metadata handling, and every other provider; a missing trailer dependency skips only that optional trailer.
- The README now links to the live-performance-specific companion tool and lists its currently documented providers.

- Individual Crunchyroll watch-page handoffs now ensure a show-level `tvshow.nfo`, poster, backdrop, and logo beside the season folders before saving episode metadata; existing show metadata and artwork are preserved.
- Crunchyroll subtitle organization now identifies full accessibility tracks with Jellyfin's `cc` flag, discards proven same-language forced signs/title-card tracks, and preserves ambiguous distinct tracks without filename collisions.
- Crunchyroll episode handoffs now create or reuse a series-named folder beneath the selected download location, keeping shared show metadata at its root and routing present and future episodes into the correct season folders without double nesting.
- Relative handoff paths such as `./episode.mkv` are resolved before Crunchyroll series-folder detection, preventing a terminal already opened inside the series folder from creating a duplicate nested series folder.
- Crunchyroll series guides are used only to identify locally present episodes; missing episodes do not receive NFO files or artwork.
- Crunchyroll series pages use `<tvshow>` NFO output, while matched episodes use `<episodedetails>` and preserve the exact ordered rating-tag contract for Jellyfin plugins.
- Added enabled-by-default Crunchyroll metadata, rename, and organization settings; collision checks and two-phase moves prevent existing destinations from being overwritten.
- Generic `master_YYYY-MM-DD_HH-MM-SS` captures can be renamed alongside matching subtitle sidecars when generic renaming is enabled and a specific Paramount+ episode link provides an unambiguous title and placement.
- Paramount+ show guides now match only existing local videos with a supported season/episode placement and save every NFO and image with that exact video filename as its base; missing episodes are never saved.
- Added the enabled-by-default `paramountplus_series_metadata_enabled` setting for that local-series workflow.
- Paramount+ movies now save in `Output/Paramount+/Movie Title (Year)/`; a matched local movie and directly matching subtitles are safely moved there and renamed to `Movie Title (Year)` after destination collision checks.
- README coverage, provider badge, and media-matching documentation now include Paramount+.

## 2026-07-24 — BBC iPlayer series metadata provider

Git commit: [`7eeb19a`](https://github.com/mp3li/Media-Metadata-and-Extras-Getter/commit/7eeb19a802966242eae605a3ccd5189ef928ae12)

### Added

- BBC iPlayer public episode metadata provider and series-aware local episode matching.
- Jellyfin `<episodedetails>` NFO output for BBC series episodes, with show title, season, and episode placement.
- BBC series settings for metadata, safe optional renaming, and safe optional season-folder organization.
- Support for BBC download, editorial, descriptive, Get iPlayer, normalized, and special-episode filename forms.

### Changed

- README and default settings now document BBC coverage, one-link-per-show processing, artwork behavior, and opt-in file actions.

## 2026-07-20 — Non-commercial source-available license

Git commit: [`c9f2746`](https://github.com/mp3li/Media-Metadata-and-Extras-Getter/commit/c9f27467d0684b2566c37f3e8643f9e2218b17de)

### Added

- Project license file establishing the non-commercial source-available terms.

## 2026-07-17 — Initial public release

Git commit: [`5b4e47e`](https://github.com/mp3li/Media-Metadata-and-Extras-Getter/commit/5b4e47e698dd12df6df1a156f04706357b178225)

### Added

- macOS terminal workflow for local Jellyfin-style metadata bundles.
- Amazon Prime Video, Netflix, and Disney+ public detail-page providers.
- NFO creation, available artwork/trailer/gallery/extra handling, local-media matching, optional generic-name renaming, default settings, launcher, and public repository documentation.
