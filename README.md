<h1 align="center">Media Metadata and Extras Getter</h1>

<p align="center">
  A macOS Python tool that turns supported public film and video detail pages into local metadata bundles, prepared for Jellyfin while remaining useful for any media-library workflow that uses standard NFO files and local artwork.
</p>

<p align="center">
  <img alt="Status" src="https://img.shields.io/badge/Status-In_Active_Development-660000?style=flat-square&labelColor=04040c" />
  <img alt="Interface" src="https://img.shields.io/badge/Interface-Terminal-660000?style=flat-square&labelColor=04040c" />
  <img alt="Metadata" src="https://img.shields.io/badge/Metadata-Jellyfin_Style_NFO-660000?style=flat-square&labelColor=04040c" />
  <img alt="Providers" src="https://img.shields.io/badge/Providers-Amazon%2C_Netflix%2C_Disney%2B%2C_BBC%2C_Paramount%2B%2C_Crunchyroll_%26_PBS_KIDS-660000?style=flat-square&labelColor=04040c" />
  <img alt="Downloads" src="https://img.shields.io/badge/Downloads-Artwork%2C_Trailers_%26_Metadata-660000?style=flat-square&labelColor=04040c" />
  <img alt="Bulk Processing" src="https://img.shields.io/badge/Bulk_Processing-Optional-660000?style=flat-square&labelColor=04040c" />
  <img alt="Platform" src="https://img.shields.io/badge/Platform-macOS-660000?style=flat-square&labelColor=04040c" />
</p>

## Table of Contents

<details>
<summary>Open Table of Contents</summary>

<br />

- [About the Project](#about-the-project)
- [What the Tool Does](#what-the-tool-does)
- [Supported Providers](#supported-providers)
- [Provider Coverage](#provider-coverage)
- [Requirements](#requirements)
- [How to Run](#how-to-run)
- [How to Use the Tool](#how-to-use-the-tool)
- [Importing mylinks.txt](#importing-mylinkstxt)
- [Settings](#settings)
- [Amazon Prime Video Series Mode](#amazon-prime-video-series-mode)
- [BBC Series Mode](#bbc-series-mode)
- [Disney+ Series Mode](#disney-series-mode)
- [HBO Max Series Mode](#hbo-max-series-mode)
- [Paramount+ Series Mode](#paramount-series-mode)
- [Crunchyroll Series Mode](#crunchyroll-series-mode)
- [PBS KIDS Series Mode](#pbs-kids-series-mode)
- [Media Matching](#media-matching)
- [Output Structure and Naming](#output-structure-and-naming)
- [Metadata Written to the NFO](#metadata-written-to-the-nfo)
- [Platform Notes](#platform-notes)
- [Known Limitations](#known-limitations)
- [Project Structure](#project-structure)
- [Changelog](CHANGELOG.md)
- [Responsible Use and Accommodation Disclaimer](#responsible-use-and-accommodation-disclaimer)

</details>

## About the Project

Media Metadata and Extras Getter is a macOS Python tool that collects public metadata, artwork, trailers, and other extras for supported movies, television series, episodes, programmes, and clips, then saves them as Jellyfin-friendly local metadata bundles.

For a version of this tool specifically made for live performances, including Amazon Prime Video, OperaVision, Metropolitan Opera, BroadwayHD, MarqueeTV, PBS Great Performances, Disney+, and Netflix, check out [Live Performance Metadata and Extras Getter](https://github.com/mp3li/Live-Performance-Metadata-and-Extras-Getter).

Media Metadata and Extras Getter gathers information that supported public detail pages expose and saves it as a local metadata bundle: an NFO file plus available artwork, trailers, gallery images, and extra videos. It currently supports public detail pages from Amazon Prime Video, Netflix, Disney+, HBO Max, BBC iPlayer, Paramount+, Crunchyroll, and PBS KIDS.

The filenames and folder layout are designed to work especially well with Jellyfin's local-metadata conventions. The output is not locked to Jellyfin, though: the files stay local, use a standard XML NFO structure, and can also support your own organized media folders or other software that reads local NFO files and artwork.

The practical workflow is simple:

- paste a supported public detail-page link, or import several from a text file
- review the scraped result in manual mode
- save a metadata bundle into `Output/`, or next to a matching video file
- let the real video filename anchor sidecar names when media matching is enabled

It is intended for supported provider detail pages. It is not a video downloader, it does not accept manifest or stream URLs, and it does not scrape arbitrary sites.

The tags and metadata written by this tool can also become the foundation of a Jellyfin workflow using multiple plugins also made by mp3li. [Media Tagging Manager Jellyfin Plugin](https://github.com/mp3li/Media-Tagging-Manager-Jellyfin-Plugin) expands each title with provider, network, genre, keyword, people, rating, language, and other useful metadata while preserving tags supplied by local NFO files. [Collection Manager Jellyfin Plugin](https://github.com/mp3li/Collection-Manager-Jellyfin-Plugin) uses that metadata to create and automatically maintain native Jellyfin collections. [Home Screen Manager Jellyfin Plugin](https://github.com/mp3li/Home-Screen-Sections-Manager-Jellyfin-Plugin) uses those tags, Crunchyroll ratings, collections, libraries, and viewing activity to build custom home-screen sections, ranked rows, and discovery pages. Used together, metadata gathered here can travel from local NFO files into Jellyfin, become organized collections, and ultimately shape how the library is browsed, while every plugin also remains useful on its own.

This tool can also serve as the metadata stage of [MediaFab](https://github.com/mp3li/WidevineProxy2-With-Extras)'s workflow. After MediaFab completes its tasks, it can pass the finished media and provider detail link to this tool for matching, naming, season organization, NFO creation, artwork, trailers, and other available extras. [Live Performance Metadata and Extras Getter](https://github.com/mp3li/Live-Performance-Metadata-and-Extras-Getter) supports the same optional MediaFab handoff for live-performance providers, allowing MediaFab to route general media and live performances to the appropriate metadata tool.

## What the Tool Does

- Scrapes supported public detail pages.
- Builds local Jellyfin-friendly `<movie>`, `<tvshow>`, or `<episodedetails>` NFO files as appropriate.
- Saves the source site, detail page link, and fetched/canonical source URL in the NFO.
- Downloads available poster, wide, and logo artwork.
- Saves a downloaded wide image as `fanart`, `banner`, and `landscape` artwork.
- Downloads available direct trailers, gallery images, and extra videos when the provider exposes usable direct URLs; Crunchyroll alone can use a strictly matched official-channel YouTube trailer when its own catalog supplies none.
- Lets you process one link at a time with a preview, or automatically process many links from `mylinks.txt`.
- Can find a matching local video file and write metadata beside it.
- Can rename a matching generic `master-...` video filename when that option is explicitly enabled.

## Supported Providers

The current provider scripts support these public detail-page links:

- Amazon Prime Video detail pages on `primevideo.com`, plus the existing Amazon video detail-page forms on `amazon.com`
- Netflix title pages
- Disney+ browse entity and episode `/play/...` pages
- HBO Max movie, show, and public show-episode catalog pages; `play.hbomax.com` movie/show links are normalized to their public catalog pages
- BBC iPlayer episode pages, including episodes in a series and one-off programmes such as films or plays
- Paramount+ show, season, episode, movie, and public clip pages
- Crunchyroll series and episode/watch pages
- PBS KIDS series, full-episode playlist, and episode watch pages

Unsupported providers do not fall back to generic scraping. The tool prints:

```text
Unfortunately this tool does not cover that provider at this time. Please make an Issue on Github for a Feature Request.
```

## Provider Coverage

Coverage depends on what the provider exposes in the public page data for each individual title. A missing field means the page did not provide a usable value; the tool does not invent one.

### Amazon Prime Video

- movie metadata from the existing supported Amazon detail-page forms, including title, plot, year, runtime, rating, genres, studio, directors, producers, cast, identifiers, and exposed artwork
- Prime Video season and exact episode detail links, including complete public multi-season guides, parent-series resolution, episode titles and placements, synopses, dates, exact runtimes, Prime Video IDs, GTIs, ASINs, audio languages, subtitle languages, and accessibility/playback features
- series rating and review total plus the ordered five-to-one-star breakdown using the exact `amazonratings` and `amazonrating5stars` through `amazonrating1star` Jellyfin tag contract
- the exact `Amazon Prime Video Provider` tag on every Prime Video series and episode NFO
- Prime Video's card artwork as Jellyfin `backdrop`, its clean hero image as `thumb`, its transparent title art as `logo`, and each episode image as its matching `-thumb`; the duplicate title-composited wide `covershot` is deliberately ignored and no portrait poster is invented
- an exact episode detail link resolves its parent season and complete series guide, ensuring that an episode is never written without its series-root `tvshow.nfo` and available series artwork
- year-qualified series roots, local-only episode matching, safe media/subtitle renaming, season organization, collision refusal, and no-double-nesting behavior consistent with Crunchyroll, Paramount+, Disney+, and PBS KIDS
- Prime Video's explicitly labelled public trailer page is attempted last and saved as `trailers/trailer.mp4` only when a usable clear preview stream can be resolved; failure to resolve the optional trailer does not affect metadata or other providers

### Netflix

- title, plot, year, runtime, content rating, genres, tags, cast, and starring information when exposed
- Netflix title identifier
- poster and wide artwork
- a direct trailer only when a usable direct media URL is exposed

### Disney+

- movie or series title, short and full descriptions, release year/range, runtime when exposed, content rating, genres, directors, creators, cast, accessibility indicators, and Disney+ entity ID
- complete public multi-season guides from Disney+'s SEO season data, including episode IDs, season/episode placement, titles, synopses, `/play/...` URLs, and reconstructable 1920-wide thumbnails
- the exact `Disney+ Provider` tag on every Disney+ movie, series, and episode NFO
- an episode `/play/...` URL resolves the canonical parent entity and carries the full series metadata into the save, so an episode is never written without its `tvshow.nfo` and available series artwork
- Disney's public social key art as Jellyfin `backdrop`, its hero/banner art as `thumb`, its tightly trimmed transparent title art as a genuine PNG `logo`, and a provider image as each episode's `-thumb`; no portrait `poster` is invented when Disney does not expose one
- the same year-qualified series folders, local-only guide matching, safe renaming, subtitle-suffix preservation, season organization, collision refusal, and no-double-nesting behavior as Crunchyroll and Paramount+
- Disney+ movies use `Output/Disney+/Movie Title (Year)/` during ordinary link processing. A MediaFab handoff instead keeps the movie beneath the supplied media location as `Movie Title (Year)/`; local movie and subtitle sidecars are moved and renamed only after collision validation
- a provider-exposed direct trailer, when one exists, is saved under Jellyfin's native `trailers/trailer.mp4`; a Disney+ `/play/...` webpage is never mistaken for downloadable trailer media, and no YouTube fallback is used

### HBO Max

- movie, series, and episode titles; separate short `outline` and full `plot` descriptions; release year/date; runtime when public; complete genres plus primary and secondary genres; provider brand; content rating; rating authority and descriptor codes; cast, director, writer, producer, creator, and source-material credits; and exact Max IDs
- complete public season and episode guides assembled by MME from Max's catalog pages, with season IDs, per-season counts, total season/episode counts, episode UUIDs, placements, titles, separate short/full descriptions, public URLs, availability dates, and one landscape episode thumbnail
- episode premiere date, runtime, audio languages, and subtitle languages when those exact fields are exposed; Max availability dates are retained separately and are never relabeled as original air dates
- the exact `HBO Max Provider` tag on every HBO Max movie, series, and episode NFO
- one clean provider portrait as Jellyfin `poster`, one provider wide image as `backdrop`, horizontal title art as `thumb`, centered title art as `logo`, and the selected secondary series/movie backdrop under `extrafanart`; episodes receive only one landscape `-thumb` and never receive episode posters or alternate covers
- movies use `Movie Title (Year)/`; series use `Series Title (Year)`, `Series Title (Start Year-End Year)`, or `Series Title (Start Year-)` with `tvshow.nfo` beside `S01`, `S02`, and later folders
- Queue Mode uses the public guide only as an identity table: a Max episode UUID in the completed filename can be matched to exactly one guide entry, and only locally present episodes are renamed, organized, and written; no duration or queue-order guessing is used
- provider trailer title, description, program ID, and exact public trailer page are retained when exposed; public Max free/creative trailers and selected extra-video pages are resolved only at the end of the workflow and saved in Jellyfin's native `trailers/` and `Extras/Videos/` locations only when their HLS/DASH manifests are clear and contain no content-protection declaration
- the signed-in player may display audio and subtitle lists that the anonymous public catalog omits; missing private player fields are not invented
- MME supplies the complete show catalog used by Queue Mode; MediaFab only needs to preserve each Max episode UUID in the completed filename and pass the show URL once for that queue
- a standalone `play.hbomax.com/video/watch/<episode-id>` page publicly exposes only the episode UUID and cannot bootstrap its unknown parent show by itself; an exact public `/show/.../<episode-id>` catalog URL can identify a single episode directly

### BBC iPlayer

- title, full/medium/short/programme synopses, first broadcast, release date, duration, BBC channel, category, version, availability, and public BBC identifiers when exposed
- poster, promotional wide image, and promotional image with logo when exposed
- the complete visible episode-card metadata for the selected series: each episode's title, short synopsis, duration, availability, BBC episode ID, plus the available series/collection selector entries
- a proper Jellyfin-style `<episodedetails>` NFO for series episodes, including `showtitle`, `season`, and `episode`; one-off programmes continue to use a `<movie>` NFO
- BBC provides media playback through its own service. This tool only retrieves public page metadata and directly exposed artwork; it is not a BBC downloader.

### Paramount+

- show title, description, complete genres, year, season count, per-season episode counts, total episode count, TV rating, brand, Paramount+ show ID, public episode URLs, and every public season/episode guide entry
- episode title, season/episode number, synopsis, date, duration where Paramount+ exposes it, public episode ID, available episode artwork, and exact audio/subtitle languages when a public page exposes them
- the exact `Paramount+ Provider` tag on every Paramount+ NFO, alongside the existing source/provider tags
- show portrait as Jellyfin `poster`, wide hero artwork as `backdrop`, and title art as `logo` at the series root; each local episode receives its own full-resolution `-thumb` image
- MME builds the complete Paramount+ catalog from one show link for Queue Mode; exact episode IDs preserved in completed filenames outrank stale `SxxExx` text, while recognized season/episode placement remains the fallback
- a playing-page URL resolves its public parent-show page and carries the complete show catalog and metadata into the save, so an episode is never written without `tvshow.nfo` and available series artwork beside its season folders
- Jellyfin series folders named `Series Title (Year)` for a completed single-year run, `Series Title (Start Year-End Year)` for a completed multi-year run, or `Series Title (Start Year-)` while currently airing
- one provider-supplied public preview, when available and confirmed clear, under Jellyfin's native `trailers/trailer.mp4` layout; provider-exposed public extras use `Extras/Videos/`, both run last, and Paramount+ never uses the Crunchyroll YouTube fallback
- movie pages add feature-film synopsis, runtime, rating, genre, cast/credit, movie ID, distinct provider poster/backdrop/title-logo roles, and their autoplaying public preview; a MediaFab handoff remains beneath the explicitly supplied location instead of being redirected to the default output directory
- title logos are byte-checked and converted to genuine PNG when necessary; a single source image is never duplicated into invented movie poster, fanart, banner, and landscape roles
- public clip pages add clip title, synopsis, duration, date, rating, full-resolution artwork, public manifest, and exposed caption status. A clear DASH or HLS manifest is saved only when it contains no DRM declaration; the provider uses ordinary `ffmpeg` remuxing without keys or DRM tooling.
- the Korra preview currently advertises `CLOSED-CAPTIONS=NONE`; subscription feature/episode playback and any subtitle tracks behind it are not downloaded by this tool.

### Crunchyroll

- series title and description, launch year, studio, season tag, season count, episode count, genres, TV rating, audio languages, subtitle languages, sub/dub availability, content advisories, and Crunchyroll series ID
- the visible average rating plus its exact rating total and the five-to-one-star distribution as ordered Jellyfin tags
- the exact `Crunchyroll Provider` tag on every Crunchyroll series and episode NFO, alongside the existing provider tags
- episode title, placement, description, release date, separate air/upload timestamps, exact runtime, original audio, audio/subtitle availability, advisories, next-episode details, and live upvote/downvote totals
- the tall portrait image as Jellyfin `poster`, the wide image as `backdrop`, the transparent title art as `logo`, and a smaller 640-pixel episode rendition as `-thumb`
- one series-level trailer under Jellyfin's native `trailers/trailer.mp4` layout, preferring a trailer exposed by Crunchyroll and otherwise accepting only an exact-title “Official Trailer” result from the verified official `@crunchyroll` or `@crunchyrolldubs` YouTube channels
- Jellyfin series folders named `Series Title (Year)` for a completed single-year run, `Series Title (Start Year-End Year)` for a completed multi-year run, or `Series Title (Start Year-)` while episodes are currently airing
- every public guide entry is used only as a lookup table; detailed episode metadata, NFOs, and thumbnails are fetched and saved only for episodes that actually exist in the configured local folders
- Crunchyroll subscription video is not downloaded. This provider retrieves public catalog metadata and artwork only.

### PBS KIDS

- series name and series description
- episode name, season and episode placement, video type, short description as Jellyfin `outline`, full description as Jellyfin `plot`, runtime, and premiere date
- PBS KIDS video ID and legacy PBS media ID in both Jellyfin unique IDs and clearly named custom fields
- the exact `PBS KIDS Provider` tag on every PBS KIDS series and episode NFO
- the series transparent logo as Jellyfin `logo.png`, the provider's series card artwork as Jellyfin `thumb`, and each episode image as its matching `-thumb`
- a series, full-episode playlist, or episode watch URL resolves the same currently available full-episode guide; an episode watch URL also identifies the exact completed episode and carries its parent series metadata into the save
- local-only episode matching, safe media/subtitle renaming, season organization, collision refusal, and no-double-nesting behavior consistent with the Crunchyroll, Paramount+, and Disney+ series workflows
- after a successful handoff, proven-empty MediaFab timestamp folders containing nothing except `.DS_Store` are removed; folders with any other content and ordinary user-created empty folders are preserved
- PBS KIDS video is not downloaded. This provider retrieves the requested public catalog metadata and artwork only.

## Requirements

### Core requirements

These requirements cover every provider and the complete baseline metadata workflow:

- **macOS** — this first release is supported and tested on macOS only.
- **Python 3** — the launcher runs with `python3`.
- **Internet access** — the tool fetches supported detail pages and any available local-metadata assets.
- **A supported public detail or watch-page link** — use one of the provider page types listed above, not a manifest or direct-stream URL.

The project uses Python's standard library. No package installation is required for the documented baseline workflow.

### Optional Crunchyroll YouTube-trailer requirements

These are needed only when Crunchyroll supplies no direct trailer and the provider finds an exact official Crunchyroll YouTube fallback:

- **yt-dlp** — retrieves the verified public trailer.
- **FFmpeg** — merges the selected H.264 video and AAC audio into `trailers/trailer.mp4`.
- **A yt-dlp-supported JavaScript runtime** — Deno is used automatically by yt-dlp; installed Node, QuickJS, or Bun runtimes are enabled by the tool.

These optional programs are not checked at startup and are never invoked for another provider. If any one is missing, outdated, or unable to download the trailer, only that optional Crunchyroll trailer is skipped. Crunchyroll metadata, NFOs, artwork, renaming, subtitles, season organization, and all other providers continue normally.

### Optional Paramount+ preview requirement

**FFmpeg** is used only when Paramount+ exposes a public, unencrypted HLS or DASH preview. If FFmpeg is absent, the preview times out, or the manifest declares encryption or content protection, only the optional trailer is skipped; metadata, artwork, naming, subtitle sidecars, season organization, and other providers continue normally.

### Optional HBO Max preview and extra-video requirements

**Google Chrome** is used only to observe public free/creative media requests made by HBO Max trailer and selected extra-video pages. **FFmpeg** remuxes those previews into Jellyfin's `trailers/` or `Extras/Videos/` layout only after the tool verifies that the public HLS/DASH manifest declares no encryption or content protection. If Chrome or FFmpeg is absent, Max exposes no preview, or the stream is protected, only the optional trailer/extra is skipped; metadata, artwork, naming, subtitles, season organization, and every other provider continue normally.

## How to Run

Run the launcher with:

```bash
cd "/Users/stellar/MyWork/Media Metadata and Extras Getter by mp3li"
python3 "Launchers/media_metadata_and_extras_getter.py"
```

By default, saved title folders go in:

```text
Output/
```

## How to Use the Tool

When it starts, the tool explains that it creates local metadata for media servers and media-library applications, with Jellyfin-style names by default. It then asks:

```text
Would you like to import your mylinks.txt or manually insert links here?
1. Import your mylinks.txt
2. Manually insert links here
Choose 1 or 2:
```

### Manual mode

Choose `2` to process one or more detail-page links yourself.

For each link, the tool:

- fetches the page through its matching provider parser
- displays the metadata and available assets it found
- asks whether to save the local metadata bundle
- asks whether you want to enter another link

The save prompt is:

```text
Save this .nfo file? [Y/n]:
```

### Import mode

Choose `1` to load links from:

```text
My Links Txt/mylinks.txt
```

Import mode processes every link it finds without individual save prompts. It reports unsupported links and scrape failures, then shows the number of folders and files saved.

## Importing mylinks.txt

Your local import file must be named exactly:

```text
mylinks.txt
```

and it must live in:

```text
My Links Txt/
```

The repository includes a safe example here:

```text
My Links Txt/mylinks-default.txt
```

Copy or rename that example before using it. Your real `mylinks.txt` is ignored by Git.

Rules:

- links must begin with `http://` or `https://`
- optional notes above links are fine
- blank lines are fine
- non-link text is ignored
- title information still comes from the provider page, not your notes

## Settings

The tracked defaults are in:

```text
Settings/settings-default.json
```

To keep your own settings private:

1. copy or rename `settings-default.json`
2. name the new file `settings.json`
3. keep it inside `Settings/`

The local `Settings/settings.json` overrides the defaults and is ignored by Git.

### `default_output_dir`

Sets the normal destination for generated title folders. A relative path is resolved from the project folder.

Default:

```json
"default_output_dir": "Output"
```

### `media_matching_enabled`

Turns matching against your existing video folders on or off.

Default:

```json
"media_matching_enabled": false
```

### `media_folders`

Lists the folders the tool may search when media matching is enabled.

Example:

```json
"media_folders": [
  "/Volumes/Media/Movies",
  "/Users/you/Media"
]
```

### `rename_generic_video_filenames`

When enabled, the tool may rename a matching video only if its filename has the narrow generic form `master-...` or `master_YYYY-MM-DD_HH-MM-SS`. Matching subtitle sidecars are renamed with it, and it will not replace an existing file.

Default:

```json
"rename_generic_video_filenames": false
```

For a Paramount+ episode URL, the one explicitly handed-off capture is renamed with the public episode placement. For example, the episode page for `Welcome to Republic City` changes `master_2026-07-24_23-29-44.mp4` to:

```text
S01E01 The Legend of Korra - Welcome to Republic City.mp4
```

Use an individual Paramount+ playing-page URL when naming a generic capture: that link identifies the one completed episode and resolves its parent show automatically. A show link intentionally lists every episode, so a timestamp-only filename does not identify which one was captured. The series guide is used only to match episodes that actually exist locally; it does not create metadata or artwork for missing episodes.

### Amazon Prime Video series settings

Prime Video series processing is enabled by default. A season page builds the complete public multi-season guide, while an exact episode detail link safely identifies one newly completed generic file and carries the parent-series metadata into the save.

```json
"amazon_prime_series_metadata_enabled": true,
"amazon_prime_series_rename_enabled": true,
"amazon_prime_series_organize_enabled": true
```

- `amazon_prime_series_rename_enabled` renames matched episodes and existing subtitle sidecars to `S01E01 Show Title - Episode Title` while preserving the complete subtitle suffix.
- `amazon_prime_series_organize_enabled` places those files beneath the year-qualified series root in `S01`, `S02`, and later season folders.
- Every destination is validated before a two-phase move. Existing conflicts stop the operation rather than being overwritten.
- Set either file-action setting to `false` to disable that action. Set `amazon_prime_series_metadata_enabled` to `false` to use ordinary single-page output.

### Disney+ series mode

Disney+ series mode uses the same Jellyfin layout and safety contract as Crunchyroll and Paramount+. A `/play/...` URL identifies the exact episode and resolves the canonical `/browse/entity-...` series page automatically:

```text
Bluey Tunes (2026)/
  tvshow.nfo
  backdrop.webp
  thumb.webp
  logo.png
  S01/
    S01E01 Bluey Tunes - Taxi.mkv
    S01E01 Bluey Tunes - Taxi.en_us.srt
    S01E01 Bluey Tunes - Taxi.nfo
    S01E01 Bluey Tunes - Taxi-thumb.webp
```

Disney+'s complete public `seoSeasons` guide is used only as a lookup table. A series page can match already named local episodes across every public season, but it does not create NFOs or thumbnails for episodes that are not present locally. For a MediaFab/WidevineProxy2 handoff, pass the current `/play/...` URL and preferably the exact newly completed media file; this lets the provider safely assign a generic `manifest_...` file to the correct episode.

Subtitle sidecars retain the complete suffix following the original media stem, including labels such as `.en_us.srt`. The provider does not infer or delete Disney+ subtitle tracks. Broad media-root scans additionally require the series title in the path, and every rename/move destination is validated before a two-phase operation.

```json
"disneyplus_series_metadata_enabled": true,
"disneyplus_series_rename_enabled": true,
"disneyplus_series_organize_enabled": true
```

- `disneyplus_series_rename_enabled` applies `S01E01 Show Title - Episode Title` to the episode and its existing subtitle sidecars.
- `disneyplus_series_organize_enabled` places those files beneath the correct year-qualified series root and season folder.
- Set either file-action setting to `false` to disable that action. Set `disneyplus_series_metadata_enabled` to `false` to use ordinary single-page output.

### HBO Max series mode

HBO Max series processing follows the same local-only Jellyfin contract as Crunchyroll, Disney+, Paramount+, and Prime Video:

```text
Series Title (Start Year-)/
  tvshow.nfo
  poster.jpg
  backdrop.jpg
  thumb.jpg
  logo.png
  extrafanart/
    fanart-01.jpg
  trailers/
    trailer.mp4
  S01/
    S01E01 Series Title - Episode Title.mkv
    S01E01 Series Title - Episode Title.en.srt
    S01E01 Series Title - Episode Title.nfo
    S01E01 Series Title - Episode Title-thumb.jpg
```

The guide is a lookup table, not an instruction to create missing episodes. MME builds that complete guide from the show page; Queue Mode only needs to pass that show page and preserve each Max episode UUID in its completed filename. The tool matches that UUID to the exact guide record, and the UUID takes priority over a stale `S01E01` string. Recognized `S01E01`-style placements also work when no UUID is present. Anonymous files without a UUID or placement are left untouched instead of being guessed from duration or queue order.

```json
"hbomax_series_metadata_enabled": true,
"hbomax_series_rename_enabled": true,
"hbomax_series_organize_enabled": true
```

- `hbomax_series_rename_enabled` renames the matched episode and its existing subtitle sidecars to `S01E01 Show Title - Episode Title`, preserving the complete subtitle suffix.
- `hbomax_series_organize_enabled` places those files in `S01`, `S02`, and later folders under the year-qualified series root.
- Every destination is validated before the two-phase move; conflicts stop the operation instead of replacing files.
- Each episode receives exactly one landscape `-thumb`. Episode posters, square covers, alternate episode art, and invented artwork roles are not created.
- Set either file-action setting to `false` to disable that action. Set `hbomax_series_metadata_enabled` to `false` to use ordinary single-page output.

### Paramount+ series mode

Paramount+ series mode produces the same Jellyfin layout and safety guarantees as Crunchyroll and HBO Max, using Paramount+'s own public metadata and preview media:

```text
Series Title (Start Year-)/
  tvshow.nfo
  poster.ext
  backdrop.ext
  logo.ext
  trailers/
    trailer.mp4
  S01/
    S01E01 Series Title - Episode Title.mkv
    S01E01 Series Title - Episode Title.en_us.srt
    S01E01 Series Title - Episode Title.nfo
    S01E01 Series Title - Episode Title-thumb.jpg
```

For Queue Mode, pass the Paramount+ show page once and preserve each episode's Paramount+ ID in its completed filename. MME builds the complete multi-season catalog and matches those IDs itself; an exact ID takes priority over stale season/episode text. A recognized placement such as `S01E01` remains the fallback when no ID is present. The guide is only an identity table, so missing local episodes receive no files and an unmatched queue cannot fall back to generic guide-only output.

An individual playing-page handoff also remains supported: pass that page URL and the exact newly completed media file when processing one episode. The tool gives that file the page's season and episode placement even when its temporary name is only `manifest_...`, and the playing page carries the complete parent catalog. Subtitle sidecars retain their complete existing suffix after the old video stem, so provider language labels such as `.en_us.srt` are preserved and distinct tracks are neither guessed nor deleted.

For configured broad media roots, matching is stricter: the path must contain the show title and the file must use a recognized placement such as `S01E01`, `S1 E1`, `Season 1 Episode 1`, `Series 1 Episode 1`, `1x01`, or `01-01`. This prevents an unrelated show's `S01E01` from being claimed. Existing destinations are validated before a two-phase move, conflicts stop the operation, and an existing series root is reused instead of nested.

```json
"paramountplus_series_metadata_enabled": true,
"paramountplus_series_rename_enabled": true,
"paramountplus_series_organize_enabled": true
```

- `paramountplus_series_rename_enabled` renames the episode and its subtitle sidecars to the public `S01E01 Show Title - Episode Title` identity.
- `paramountplus_series_organize_enabled` places them in the correct `S01`, `S02`, or later folder beneath the year-qualified series root.
- Every episode receives exactly one landscape `-thumb`; episode posters, alternate covers, and gallery artwork are not created.
- Set either file-action setting to `false` to disable that action. Set `paramountplus_series_metadata_enabled` to `false` to use ordinary single-page output.

### Crunchyroll series settings

Crunchyroll series mode is enabled by default and applies the requested BBC-style safe organization rules. It matches only local episodes found under `media_folders`, fetches detailed metadata only for those matches, and never writes guide-only episodes.

An individual Crunchyroll watch link also carries its linked main-series metadata into the save. Before writing the episode, the tool ensures that the series folder has `tvshow.nfo`, `poster`, `backdrop`, and `logo` beside the `S01`, `S02`, and later season folders. Existing show NFO and artwork files are preserved; only missing parts are added.

```json
"crunchyroll_series_metadata_enabled": true,
"crunchyroll_series_rename_enabled": true,
"crunchyroll_series_organize_enabled": true
```

- `crunchyroll_series_rename_enabled` renames the matched video and its subtitle sidecars to `S01E01 Show Title - Episode Title`. A subtitle without a recognizable language suffix receives `.und`.
- `crunchyroll_series_organize_enabled` places those files under `S01`, `S02`, and so on without nesting an existing season directory.
- Both operations validate every destination before a two-phase rename, so an existing conflicting file is never replaced.
- Set either file-action setting to `false` if you want metadata without that action. Set `crunchyroll_series_metadata_enabled` to `false` to use normal single-page output instead.

### PBS KIDS series settings

PBS KIDS series processing is enabled by default. All three supported PBS KIDS URL forms resolve the currently available full-episode guide, while NFO files and episode thumbnails are written only for episodes matched to local media.

```json
"pbs_kids_series_metadata_enabled": true,
"pbs_kids_series_rename_enabled": true,
"pbs_kids_series_organize_enabled": true
```

- `pbs_kids_series_rename_enabled` renames matched episodes and their existing subtitle sidecars to `S07E17 Show Title - Episode Title`.
- `pbs_kids_series_organize_enabled` places those files beneath the series root in `S01`, `S02`, and later season folders.
- Every destination is checked before a two-phase rename or move, so an existing file is never overwritten.
- After the metadata workflow succeeds, timestamp-named MediaFab handoff folders are removed only when they contain nothing except `.DS_Store`.
- Set either file-action setting to `false` to disable that action. Set `pbs_kids_series_metadata_enabled` to `false` to use ordinary single-page output.

### Paramount+ movie folders

Paramount+ movie pages use a provider and movie-title folder, with the title and year as the filename base:

```text
Output/Paramount+/Avatar Aang - The Last Airbender (2026)/
  Avatar Aang - The Last Airbender (2026).nfo
  Avatar Aang - The Last Airbender (2026)-poster.jpg
  trailers/
    trailer.mp4
```

When media matching finds a Paramount+ movie, the matching video and directly matching subtitle sidecars are moved into that same folder and renamed to `Movie Title (Year)`. The destination is checked first, so an existing file is never replaced. If no local video matches, only the downloaded metadata bundle is saved there.

### BBC series settings

BBC series processing automatically inspects the files that already exist under `media_folders`. It only retrieves metadata for the BBC episodes it can match there, so a library with four downloaded seasons does not cause the missing fifth season to be fetched.

It recognises BBC-style downloaded names such as:

```text
The_Great_British_Sewing_Bee_Series_2_-_07._Episode_7_b0405yck_original.mp4
```

It also recognises the standard series names produced by the user's Get iPlayer workflow, for example:

```text
One Piece - S02E75 - Alabasta (62-135) - A Hex on Luffy! Colors Trap! - m0021yfg.mp4
```

When its BBC rename option is enabled, this becomes `S02E75 One Piece - Alabasta - A Hex on Luffy! Colors Trap!.mp4`; the show, series/arc title, and episode title are retained while the BBC ID and a trailing episode-range label such as `(62-135)` are removed.

Both BBC `original` and `editorial` versions are recognised. Downloaded specials without a series number use their public BBC series placement and become the final numbered episode in that series; no artificial `S00` folder is created.
Their descriptive label is retained, for example `S01E05 The Great British Sewing Bee - Christmas Special.mp4`.

It also recognises the normalized names it produces, such as `S02E07 The Great British Sewing Bee.mp4`, on later runs. BBC series processing is enabled by default when `media_folders` contains a matching local BBC series; a normal single-page save is used when it finds no local matching episodes.

```json
"bbc_series_metadata_enabled": true,
"bbc_series_rename_enabled": false,
"bbc_series_organize_enabled": false
```

- Set `bbc_series_rename_enabled` to `true` to rename matching local videos to `S01E07 The Great British Sewing Bee.mp4`. Matching subtitle files are renamed alongside the video; when the original filename does not establish the subtitle language, the safe `und` language code is used, for example `S01E07 The Great British Sewing Bee.und.srt`.
- Set `bbc_series_organize_enabled` to `true` to move the matching video and subtitle files into `S01`, `S02`, and so on within their existing parent folder. Every episode gets its own NFO, while the public BBC artwork bundle is saved only once per season with a show-specific name, such as `The Great British Sewing Bee - season01-poster.jpg` and `The Great British Sewing Bee - season01-fanart.jpg`.
- Both actions are deliberately opt-in. The tool will not overwrite a conflicting destination filename.

## Amazon Prime Video Series Mode

Provide a Prime Video season page to match every locally present episode across its public season selector, or provide an exact episode detail page for one completed file. Prime Video episode pages use the same `/detail/...` form as seasons, but their compact Prime Video ID identifies the selected episode while the page still exposes its parent season and full series guide.

The resulting Jellyfin layout is:

```text
Making The Cut (2020-2022)/
  tvshow.nfo
  backdrop.jpg
  thumb.jpg
  logo.png
  S01/
    S01E01 Making The Cut - Heidi and Tim Are Back.mkv
    S01E01 Making The Cut - Heidi and Tim Are Back.en.srt
    S01E01 Making The Cut - Heidi and Tim Are Back.nfo
    S01E01 Making The Cut - Heidi and Tim Are Back-thumb.jpg
```

Series folders use `Series Title (Year)` for a single completed year, `Series Title (Start Year-End Year)` for a completed multi-year run, or `Series Title (Start Year-)` for a currently releasing series. An existing title-only or stale year-qualified root is migrated safely rather than nested.

A Queue Mode folder can match episodes by SxxExx placement, title, compact Prime Video ID, GTI, or ASIN. The guide is only a lookup table: missing local episodes do not receive NFO files or images, and multiple anonymous timestamp-only files remain untouched because they cannot be assigned safely. An exact episode link plus one exact completed file is unambiguous even when that file still has a generic `manifest_...` name.

The rating tags are written together and in this exact order for Jellyfin plugin consumption:

```xml
<tag>amazonratings: 3.8 / 5 from 280 ratings</tag>
<tag>amazonrating5stars: 51%</tag>
<tag>amazonrating4stars: 18%</tag>
<tag>amazonrating3stars: 5%</tag>
<tag>amazonrating2stars: 13%</tag>
<tag>amazonrating1star: 13%</tag>
```

The values come from the selected Prime Video detail page and can change; the tag names and ordering remain fixed. Series artwork uses only the clean hero `backdrop`, card `thumb`, and transparent `logo`. Episode images use the matching `-thumb` name.

## BBC Series Mode

BBC series mode is designed for a library that already contains the episodes. It does not download video or subtitle media. Instead, it matches the BBC IDs and season/episode numbers in your existing files, retrieves public BBC metadata for those matched episodes, and writes local sidecars beside them.

### Links to provide

Give the tool **one representative BBC iPlayer episode link per show**. You do not need one link per season: one Sewing Bee link can process every locally present Sewing Bee season, while one One Piece link can process every locally present One Piece episode.

For several shows, add one representative link for each show to `My Links Txt/mylinks.txt` and choose import mode. The tool processes the shows one at a time; each link only matches files belonging to that show.

### What it matches

The BBC matcher works within the `media_folders` paths, independently of the ordinary `media_matching_enabled` setting. It recognizes:

- BBC `original` and `editorial` download names
- BBC download names whose numbered entries use descriptive titles instead of `Episode N`
- Get iPlayer series names in the form `Title - S02E75 - Series/Arc Title - Episode Title - BBC-ID.ext`
- the normalized names the BBC rename option produces on a later run
- BBC specials, using BBC's public placement at the end of their real series

If a same-basename `.jpg` sits beside an otherwise matching BBC media file, the tool treats that as an incomplete download marker and skips the episode until the marker is gone. It never creates a subtitle for a video that has none.

### Metadata and artwork saved

For every matched episode, the tool fetches its own public BBC page data and writes an episode NFO beside the local video. BBC episode NFOs use `<episodedetails>` with `showtitle`, `season`, and `episode`, along with the available full/medium/short synopses, dates, runtime, channel, category, availability, BBC IDs, related episode cards, and available series selectors.

Public BBC poster, wide, banner, landscape, and logo artwork is saved once per populated season rather than once per episode. Its show-specific name prevents collisions in shared folders, for example:

```text
One Piece - season02-poster.jpg
One Piece - season02-fanart.jpg
The Great British Sewing Bee - season01-poster.jpg
```

### Optional file actions

With both BBC rename and organize settings set to `false`, the source video and subtitle filenames remain untouched. The NFO is written beside the existing video and the season artwork is written in that existing folder.

With `bbc_series_rename_enabled` set to `true`, matching files are renamed as follows:

```text
S01E07 The Great British Sewing Bee.mp4
S01E07 The Great British Sewing Bee.und.srt

S02E75 One Piece - Alabasta - A Hex on Luffy! Colors Trap!.mp4
S02E75 One Piece - Alabasta - A Hex on Luffy! Colors Trap!.und.srt

S01E05 The Great British Sewing Bee - Christmas Special.mp4
```

The One Piece pattern retains the show, series/arc title, and episode title; it removes only the BBC ID and a trailing range such as `(62-135)`. The Sewing Bee pattern uses the shorter show-only name, except that specials retain their descriptive label.

With `bbc_series_organize_enabled` set to `true`, the matching video, subtitle, NFO, and season artwork are placed under `S01`, `S02`, and so on in their existing parent folder. The tool checks for collisions before renaming or moving files and will not overwrite an existing destination.

## Crunchyroll Series Mode

Provide one Crunchyroll series page to process every locally present episode of that show, or provide one episode/watch page for a specific file. The matcher recognizes `S01E01`, `S1 E1`, `Season 1 Episode 1`, `Series 1 Episode 1`, `1x01`, `01-01`, and season-one forms such as `E1`. Outside an explicit handoff folder, the show title must also occur in the local path to prevent an episode number from matching another series.

A same-basename `.jpg` is treated as an incomplete-download marker and causes that media file to be skipped. Videos and subtitle sidecars are moved together; no subtitle is invented when one is absent.

When Crunchyroll supplies both a full same-language accessibility track and a tiny signs/title-card-only track, the full track is retained with Jellyfin's `cc` flag (for example, `.en.cc.srt`) and the proven forced-only track is discarded as requested. Ambiguous distinct subtitle tracks are preserved with collision-safe numbering rather than overwritten.

With the default Crunchyroll settings, the chosen download location is treated as the parent. The tool creates or reuses one series-named folder beneath it, unless the chosen location is already that series folder:

```text
Chosen Download Location/
  May I Ask for One Final Thing (2025)/
    tvshow.nfo
    poster.png
    backdrop.png
    logo.png
    trailers/
      trailer.mp4
    S01/
      S01E01 May I Ask for One Final Thing - May I Kindly Beat the Tar Out of Those Evil Nobles (Pigs).mkv
      S01E01 May I Ask for One Final Thing - May I Kindly Beat the Tar Out of Those Evil Nobles (Pigs).und.srt
      S01E01 May I Ask for One Final Thing - May I Kindly Beat the Tar Out of Those Evil Nobles (Pigs).nfo
      S01E01 May I Ask for One Final Thing - May I Kindly Beat the Tar Out of Those Evil Nobles (Pigs)-thumb.png
```

Later episodes downloaded into the same parent location reuse that year-qualified series folder and are routed into their corresponding season folders. The provider derives the start and latest years from Crunchyroll's launch year and released-episode dates. A show whose latest release is inside the active airing window uses an open range such as `Smoking Behind the Supermarket with You (2026-)`; a completed single-year run uses `Yuri!!! on ICE (2016)`, while a completed multi-year run uses `The Apothecary Diaries (2023-2025)`. A location already named for the series, including a legacy title-only folder, is recognized—even when the handoff supplies a relative path such as `./episode.mkv`—and is routed to the year-qualified sibling instead of being nested as `Series Name/Series Name/`.

The transparent title image is fetched from Crunchyroll's public key-art endpoint. `tvshow.nfo` contains the main series description and series-level fields, while each NFO inside a season folder contains that episode's description and fields. This hierarchy is created from either a series page or an individual watch page, so a saved episode is never left without its main series metadata.

Trailer discovery runs only after the current metadata, artwork, rename, organization, subtitle, NFO, and thumbnail workflow finishes. A provider-supplied Crunchyroll trailer suppresses YouTube searching. Otherwise, the fallback requires an exact normalized series-title match, “Official Trailer” in the video title, and a verified official Crunchyroll uploader. Downloads use YouTube's embedded client so public embeddable trailers do not require browser cookies; the tool saves nothing when those checks are ambiguous and never overwrites an existing local trailer.

The episode vote tag and series breakdown tags are adjacent and ordered exactly for Jellyfin plugin consumption:

```xml
<tag>crunchyrollratings: 15.2k upvotes / 96 downvotes</tag>
<tag>crunchyrollrating: 4.8 / 5 from 52,358 ratings</tag>
<tag>crunchyrollrating5stars: 44.6k / 86%</tag>
<tag>crunchyrollrating4stars: 4.7k / 10%</tag>
<tag>crunchyrollrating3stars: 1.7k / 4%</tag>
<tag>crunchyrollrating2stars: 556 / 2%</tag>
<tag>crunchyrollrating1star: 676 / 2%</tag>
```

These are live values and can change between runs; the tag names and ordering remain fixed.

## PBS KIDS Series Mode

You can provide a PBS KIDS series page, a full-episode playlist page, or an individual episode watch page. Each form resolves the same currently available full-episode guide. The guide is only a lookup table: the tool writes episode metadata and artwork only for episodes that exist in the supplied local location.

An individual watch-page handoff is the safest route for one newly completed generic file because it identifies the exact episode. A Queue Mode folder can match multiple episodes when each filename contains an episode title, PBS KIDS video ID, legacy PBS media ID, or season/episode placement. Multiple anonymous timestamp-only files are deliberately left untouched because the provider cannot safely determine which episode belongs to which file.

The resulting Jellyfin layout is:

```text
Wild Kratts/
  tvshow.nfo
  thumb.jpg
  logo.png
  S07/
    S07E17 Wild Kratts - Duck, Duck, Loon!.mkv
    S07E17 Wild Kratts - Duck, Duck, Loon!.en.srt
    S07E17 Wild Kratts - Duck, Duck, Loon!.nfo
    S07E17 Wild Kratts - Duck, Duck, Loon!-thumb.png
```

The series NFO contains the series name and description. Episode NFOs use `<episodedetails>` and contain the episode name, placement, video type, short `outline`, longer `plot`, runtime, premiere date, PBS KIDS video ID, and legacy PBS media ID. The artwork bundle contains only the requested provider images: series card art as `thumb`, the transparent series logo as `logo.png`, and the episode image as its matching `-thumb`.

## Media Matching

Media matching is optional and off by default. With it enabled, the tool searches the folders in `media_folders` for video files whose filename or parent folder resembles the scraped title. It supports common video extensions including `.mkv`, `.mp4`, `.m4v`, `.avi`, `.mov`, `.wmv`, `.ts`, `.m2ts`, `.webm`, and `.flv`.

When a video is matched, its filename becomes the sidecar naming anchor. This keeps the NFO and artwork in step with the real media filename—a layout Jellyfin recognizes particularly well. Because matching compares title text, point it only at media roots you intend the tool to search and review your settings before enabling it.

## Output Structure and Naming

Without a local media match, the tool saves into:

```text
Output/<title>/<title>.nfo
```

For example:

```text
Output/Example Movie/Example Movie.nfo
Output/Example Movie/Example Movie-poster.jpg
Output/Example Movie/Example Movie-fanart.jpg
Output/Example Movie/Example Movie-banner.jpg
Output/Example Movie/Example Movie-landscape.jpg
Output/Example Movie/Example Movie-logo.png
Output/Example Movie/Extras/Trailers/trailer.mp4
Output/Example Movie/extrafanart/fanart-01.jpg
```

Disney+ and Paramount+ movies are the exceptions during ordinary link processing: they save under `Output/<Provider>/Movie Title (Year)/` and use `Movie Title (Year)` for their metadata, artwork, and local matched movie filename. During a Disney+ MediaFab handoff, that year-qualified movie folder is created beneath the exact supplied media location instead of the configured default output. Disney+ uses Jellyfin's native `trailers/` directory only when its public page exposes a real direct trailer.

When media matching finds a local video, the real filename replaces `<title>` in the NFO and artwork names. Available extra videos are saved under `Extras/Videos/`.

## Metadata Written to the NFO

The generated NFO has a `<movie>` root for films/one-off programmes, a `<tvshow>` root for Amazon Prime Video, Disney+, HBO Max, Paramount+, Crunchyroll, and PBS KIDS series pages, or an `<episodedetails>` root for matched episodes, and can include:

- title, original title, sort title, outline, plot, tagline, year, and date
- runtime, rating, content rating, and language
- genres, tags, countries, studios, directors, writers, credits, and cast
- provider identifiers such as Amazon, Netflix, or Disney+ IDs when exposed
- source site, detail page URL, and fetched/canonical URL
- additional provider fields as `customfield` entries

The exact fields depend on the provider and the title page.

## Platform Notes

This project was developed and tested on macOS. It uses a macOS `curl` fallback when Python's network request path fails, so the current release is documented as **macOS-only**.

Windows and Linux support are welcome future work, but they are not yet tested or documented for this project.

## Known Limitations

- Only the listed providers and URL forms are supported.
- Provider page changes can require parser updates.
- Public detail pages may expose incomplete metadata.
- Artwork, trailers, gallery images, and extras are only saved when a usable public URL is present.
- The tool does not download DRM-protected media or bypass DRM.
- This project creates local metadata bundles; it is not a general-purpose media downloader.

## Project Structure

```text
Launchers/
  media_metadata_and_extras_getter.py

Base Script/
  media_metadata_and_extras_getter_base.py

Provider Scripts/
  amazon.py
  bbc_iplayer.py
  crunchyroll.py
  disneyplus.py
  hbomax.py
  netflix.py
  paramountplus.py
  pbs_kids.py

Tests/
  test_amazon_prime.py
  test_crunchyroll.py
  test_disneyplus.py
  test_hbomax.py
  test_paramountplus.py
  test_pbs_kids.py

Settings/
  settings-default.json

My Links Txt/
  mylinks-default.txt

CHANGELOG.md
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the complete published Git history and the current unreleased work.

## Responsible Use and Accommodation Disclaimer

This tool is provided for educational, research, personal media-library organization, and accessibility or accommodation support purposes only.

It does not bypass DRM, does not obtain DRM-protected material, and does not access page information that requires a logged-in session when that information is not publicly visible to the tool.

You are responsible for how you use this project, what material you process with it, and whether your use complies with the laws, licenses, and terms that apply to you. The author is not responsible for misuse.
