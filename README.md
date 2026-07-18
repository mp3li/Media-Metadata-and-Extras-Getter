<h1 align="center">Media Metadata and Extras Getter by mp3li</h1>

<p align="center">
  A macOS Python tool that turns supported public film and video detail pages into local metadata bundles, prepared for Jellyfin while remaining useful for any media-library workflow that uses standard NFO files and local artwork.
</p>

<p align="center">
  <img alt="Status" src="https://img.shields.io/badge/Status-In_Active_Development-660000?style=flat-square&labelColor=04040c" />
  <img alt="Interface" src="https://img.shields.io/badge/Interface-Terminal-660000?style=flat-square&labelColor=04040c" />
  <img alt="Metadata" src="https://img.shields.io/badge/Metadata-Jellyfin_Style_NFO-660000?style=flat-square&labelColor=04040c" />
  <img alt="Providers" src="https://img.shields.io/badge/Providers-Amazon_Prime_Netflix_%26_Disney%2B-660000?style=flat-square&labelColor=04040c" />
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
- [Media Matching](#media-matching)
- [Output Structure and Naming](#output-structure-and-naming)
- [Metadata Written to the NFO](#metadata-written-to-the-nfo)
- [Platform Notes](#platform-notes)
- [Known Limitations](#known-limitations)
- [Project Structure](#project-structure)
- [Responsible Use and Accommodation Disclaimer](#responsible-use-and-accommodation-disclaimer)

</details>

## About the Project

Media Metadata and Extras Getter by mp3li is for regular video media—not specifically for live performances. It gathers information that supported public detail pages expose and saves it as a local metadata bundle: an NFO file plus available artwork, trailers, gallery images, and extra videos.

The filenames and folder layout are designed to work especially well with Jellyfin's local-metadata conventions. The output is not locked to Jellyfin, though: the files stay local, use a standard XML NFO structure, and can also support your own organized media folders or other software that reads local NFO files and artwork.

The practical workflow is simple:

- paste a supported public detail-page link, or import several from a text file
- review the scraped result in manual mode
- save a metadata bundle into `Output/`, or next to a matching video file
- let the real video filename anchor sidecar names when media matching is enabled

It is intended for supported provider detail pages. It is not a video downloader, it does not accept manifest or stream URLs, and it does not scrape arbitrary sites.

## What the Tool Does

- Scrapes supported public detail pages.
- Builds a local `<movie>` NFO file with Jellyfin-friendly fields.
- Saves the source site, detail page link, and fetched/canonical source URL in the NFO.
- Downloads available poster, wide, and logo artwork.
- Saves a downloaded wide image as `fanart`, `banner`, and `landscape` artwork.
- Downloads available direct trailers, gallery images, and extra videos when the provider exposes usable direct URLs.
- Lets you process one link at a time with a preview, or automatically process many links from `mylinks.txt`.
- Can find a matching local video file and write metadata beside it.
- Can rename a matching generic `master-...` video filename when that option is explicitly enabled.

## Supported Providers

The current provider scripts support these public detail-page links:

- Amazon Prime Video detail pages on `amazon.com`
- Netflix title pages
- Disney+ browse entity pages

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

## Requirements

To run this tool as documented, you need:

- **macOS** — this first release is supported and tested on macOS only.
- **Python 3** — the launcher runs with `python3`.
- **Internet access** — the tool fetches supported detail pages and any available local-metadata assets.
- **A supported public detail-page link** — use a page from one of the providers listed above, not a playback, manifest, or direct-stream URL.

The project uses Python's standard library. No package installation is required for the documented baseline workflow.

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

When enabled, the tool may rename a matching video only if its filename has the narrow generic form `master-...`. It will not replace an existing file.

Default:

```json
"rename_generic_video_filenames": false
```

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

When media matching finds a local video, the real filename replaces `<title>` in the NFO and artwork names. Available extra videos are saved under `Extras/Videos/`.

## Metadata Written to the NFO

The generated NFO has a `<movie>` root and can include:

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
  disneyplus.py
  netflix.py

Settings/
  settings-default.json

My Links Txt/
  mylinks-default.txt
```

## Responsible Use and Accommodation Disclaimer

This tool is provided for educational, research, personal media-library organization, and accessibility or accommodation support purposes only.

It does not bypass DRM, does not obtain DRM-protected material, and does not access page information that requires a logged-in session when that information is not publicly visible to the tool.

You are responsible for how you use this project, what material you process with it, and whether your use complies with the laws, licenses, and terms that apply to you. The author is not responsible for misuse.
