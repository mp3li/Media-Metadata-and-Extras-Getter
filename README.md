<h1 align="center">Media Metadata and Extras Getter</h1>

<p align="center">
  A macOS Python tool that turns supported public film and video detail pages into local metadata bundles, prepared for Jellyfin while remaining useful for any media-library workflow that uses standard NFO files and local artwork.
</p>

<p align="center">
  <img alt="Status" src="https://img.shields.io/badge/Status-In_Active_Development-660000?style=flat-square&labelColor=04040c" />
  <img alt="Interface" src="https://img.shields.io/badge/Interface-Terminal-660000?style=flat-square&labelColor=04040c" />
  <img alt="Metadata" src="https://img.shields.io/badge/Metadata-Jellyfin_Style_NFO-660000?style=flat-square&labelColor=04040c" />
  <img alt="Providers" src="https://img.shields.io/badge/Providers-Amazon%2C_Netflix%2C_Disney%2B%2C_BBC%2C_Paramount%2B_%26_Crunchyroll-660000?style=flat-square&labelColor=04040c" />
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
- [BBC Series Mode](#bbc-series-mode)
- [Crunchyroll Series Mode](#crunchyroll-series-mode)
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

Media Metadata and Extras Getter gathers information that supported public detail pages expose and saves it as a local metadata bundle: an NFO file plus available artwork, trailers, gallery images, and extra videos. It currently supports public detail pages from Amazon Prime Video, Netflix, Disney+, BBC iPlayer, Paramount+, and Crunchyroll.

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

- Amazon Prime Video detail pages on `amazon.com`
- Netflix title pages
- Disney+ browse entity pages
- BBC iPlayer episode pages, including episodes in a series and one-off programmes such as films or plays
- Paramount+ show, season, episode, movie, and public clip pages
- Crunchyroll series and episode/watch pages

Unsupported providers do not fall back to generic scraping. The tool prints:

```text
Unfortunately this tool does not cover that provider at this time. Please make an Issue on Github for a Feature Request.
```

## Provider Coverage

Coverage depends on what the provider exposes in the public page data for each individual title. A missing field means the page did not provide a usable value; the tool does not invent one.

### Amazon Prime Video

- title, plot, year, runtime, content rating, genres, studio, directors, producers, and cast when exposed
- Amazon identifier when available
- poster and wide artwork
- a direct trailer only when a usable direct media URL is exposed

### Netflix

- title, plot, year, runtime, content rating, genres, tags, cast, and starring information when exposed
- Netflix title identifier
- poster and wide artwork
- a direct trailer only when a usable direct media URL is exposed

### Disney+

- title, short and longer descriptions, year, runtime, content rating, genres, directors, cast, and category when exposed
- Disney+ entity identifier
- poster, wide artwork, and logo artwork when exposed
- a public play link when it is exposed; a saved trailer still depends on that link resolving to a downloadable direct file

### BBC iPlayer

- title, full/medium/short/programme synopses, first broadcast, release date, duration, BBC channel, category, version, availability, and public BBC identifiers when exposed
- poster, promotional wide image, and promotional image with logo when exposed
- the complete visible episode-card metadata for the selected series: each episode's title, short synopsis, duration, availability, BBC episode ID, plus the available series/collection selector entries
- a proper Jellyfin-style `<episodedetails>` NFO for series episodes, including `showtitle`, `season`, and `episode`; one-off programmes continue to use a `<movie>` NFO
- BBC provides media playback through its own service. This tool only retrieves public page metadata and directly exposed artwork; it is not a BBC downloader.

### Paramount+

- show title, description, genre, year, season count, TV rating, brand, Paramount+ show ID, public episode URLs, and every public season/episode guide entry
- episode title, season/episode number, synopsis, date, duration where Paramount+ exposes it, public episode ID, and available episode artwork
- show portrait, wide hero artwork, social artwork, and title logo; for locally matched episodes, all artwork uses that exact video filename as its base, including the full-resolution episode `-thumb.jpg`. Paramount+ does not expose separate season-poster artwork for this show page
- movie pages add feature-film synopsis, runtime, rating, genre, cast, movie ID, title/logo/hero/brand artwork, and their autoplaying public preview.
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

## Requirements

### Core requirements

These requirements cover every provider and the complete baseline metadata workflow:

- **macOS** — this first release is supported and tested on macOS only.
- **Python 3** — the launcher runs with `python3`.
- **Internet access** — the tool fetches supported detail pages and any available local-metadata assets.
- **A supported public detail-page link** — use a page from one of the providers listed above, not a playback, manifest, or direct-stream URL.

The project uses Python's standard library. No package installation is required for the documented baseline workflow.

### Optional Crunchyroll YouTube-trailer requirements

These are needed only when Crunchyroll supplies no direct trailer and the provider finds an exact official Crunchyroll YouTube fallback:

- **yt-dlp** — retrieves the verified public trailer.
- **FFmpeg** — merges the selected H.264 video and AAC audio into `trailers/trailer.mp4`.
- **A yt-dlp-supported JavaScript runtime** — Deno is used automatically by yt-dlp; installed Node, QuickJS, or Bun runtimes are enabled by the tool.

These optional programs are not checked at startup and are never invoked for another provider. If any one is missing, outdated, or unable to download the trailer, only that optional Crunchyroll trailer is skipped. Crunchyroll metadata, NFOs, artwork, renaming, subtitles, season organization, and all other providers continue normally.

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

For a Paramount+ episode URL, a matching generic capture is renamed with the public episode placement. For example, the episode page for `Welcome to Republic City` changes `master_2026-07-24_23-29-44.mp4` to:

```text
S01E01 The Legend of Korra - Welcome to Republic City.mp4
```

Use an individual Paramount+ episode URL when naming a generic capture: a show link intentionally lists every episode and a timestamp-only filename does not identify which one was captured. The series guide is used to match episode files that actually exist in your local media folders; it does not create metadata or artwork for missing episodes.

For a local Paramount+ episode, the tool matches common placement forms without requiring the show title: `S01E01`, `S1 E1`, `Season 1 Episode 1`, `Series 1 Episode 1`, `1x01`, and `01-01`. Every saved NFO and image uses that exact local video filename as its base: `Video.mkv`, `Video.nfo`, `Video-poster.jpg`, `Video-fanart.jpg`, `Video-banner.jpg`, `Video-landscape.jpg`, `Video-logo.png`, `Video-thumb.jpg`, and filename-based `extrafanart/` artwork. It leaves videos, subtitles, and existing folder names untouched. A timestamp-only `master_...` file remains intentionally unmatched by a show link; use that episode's individual Paramount+ URL when you want to rename it.

```json
"paramountplus_series_metadata_enabled": true
```

Set this to `false` to keep Paramount+ show pages in their ordinary single-page metadata mode.

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

### Paramount+ movie folders

Paramount+ movie pages use a provider and movie-title folder, with the title and year as the filename base:

```text
Output/Paramount+/Avatar Aang - The Last Airbender (2026)/
  Avatar Aang - The Last Airbender (2026).nfo
  Avatar Aang - The Last Airbender (2026)-poster.jpg
  Extras/
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

Paramount+ movies are the exception: they save in `Output/Paramount+/Movie Title (Year)/` and use `Movie Title (Year)` for their metadata, artwork, and local matched movie filename.

When media matching finds a local video, the real filename replaces `<title>` in the NFO and artwork names. Available extra videos are saved under `Extras/Videos/`.

## Metadata Written to the NFO

The generated NFO has a `<movie>` root for films/one-off programmes, a `<tvshow>` root for Crunchyroll series pages, or an `<episodedetails>` root for matched episodes, and can include:

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
  netflix.py
  paramountplus.py

Tests/
  test_crunchyroll.py

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
