# Changelog

All notable project changes are documented here. Published entries are derived from the repository's Git history; the Unreleased section records completed local work that has not yet been committed.

## Unreleased

### Added

- Paramount+ provider for public show, season, and episode pages.
- Paramount+ movie and public-clip page support, including cast, movie runtime/rating, clip metadata, and explicit clear-DASH safeguards.
- Full public season-guide extraction, including episode titles, placements, synopses, dates, IDs, public episode URLs, and exposed durations.
- Paramount+ show portrait, wide hero, social, logo, and 1920-pixel episode-art saving.
- Public, unencrypted Paramount+ autoplay-preview download support through standard `ffmpeg` remuxing only; no keys, DRM tooling, or protected playback support.
- User-designated related-world public teaser attachment for *Avatar Aang: The Last Airbender*, while preserving the teaser's own *Avatar: Seven Havens* identity and metadata.
- Paramount+ source and provider tags in generated NFO metadata.

### Changed

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
