# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Yodle is a CLI YouTube downloader for downloading videos, music (MP3), and channel thumbnails. Downloads are saved to `~/Yodle` by default, or to the path set via the `YODLE_OUTPUT_DIR` environment variable.

## Quick Start

```bash
# Run with uv (recommended - handles dependencies automatically)
uv run yodle.py

# Or run directly if dependencies are installed
python yodle.py
```

Running with no URLs (and no `-a` file) prints help and exits.

## Requirements

- Python 3.11+
- ffmpeg (must be on system PATH): `brew install ffmpeg`
- Dependencies (managed by uv via `pyproject.toml` and `uv.lock`):
  ```bash
  pip install yt-dlp mutagen pydub pillow requests browser-cookie3 python-dotenv
  ```

## yodle.py - Unified CLI Downloader

Single-file application. Dependencies live in `pyproject.toml` (managed by uv); there is no PEP 723 inline metadata. The console script `yodle` is also exposed via `pyproject.toml`.

### Features
- **Video**: Downloads in best H.264/HEVC quality
- **Music**: Downloads as MP3 with embedded ID3 tags and album art; quality via `--audio-quality`, optional loudness normalization via `--normalize`
- **Both**: Downloads video and music versions
- **Thumbnails**: Downloads all thumbnails from a YouTube channel (original + resized)
- **Time limits**: `--limit DURATION` truncates each download (e.g. `--limit 59m`)
- **Batch pacing**: random 1–15 min pause between downloads in multi-download runs (batches, playlists)

### CLI Flags

| Flag | Values | Default | Purpose |
|------|--------|---------|---------|
| `urls` | one or more YouTube URLs | — (urls or `-a` required to run) | What to download |
| `-a, --batch-file` | path to URL list file | unset | Read URLs from file, one per line (`#` comments, blanks skipped); combined with inline `urls` |
| `-t, --type` | `video`, `music`, `both`, `thumbnails` | `both` | Download type |
| `--video-format` | `mp4`, `mkv`, `webm` | `mp4` | Video container |
| `--audio-format` | `mp3`, `m4a` | `mp3` | Audio format |
| `--limit` | `90`, `90s`, `59m`, `2h`, `1:30:00` | unset (full download) | Max duration per video; no-op with `-t thumbnails` |
| `--audio-quality` | `0`-`10` (VBR, 0=best), `11`-`320` (kbps) | `0` | Music encoder quality; no-op with `-t video/thumbnails` |
| `--normalize` | flag | off | Loudness-normalize music to -14 LUFS (two-pass ffmpeg loudnorm) |
| `-b, --browser` | `none`, `chrome`, `firefox` | unset | Extract browser cookies for private/age-restricted videos |
| `--cookies-file` | path | unset | Use an existing Netscape cookies.txt |

Environment: `YODLE_OUTPUT_DIR` (also loadable from a project-root `.env`) sets the output directory.

## Architecture

### Key Classes in yodle.py
- `CookieManager`: Extracts cookies from Chrome/Firefox to `~/.config/yt-dlp/cookies.txt`
- `UpdateChecker`: Queries PyPI for yt-dlp updates (currently unused by the CLI — dead code left in place)
- `VideoDownloader`: Downloads video with FFmpegMetadata post-processor
- `MusicDownloader`: Downloads bestaudio, converts via yt-dlp FFmpegExtractAudio, embeds ID3 tags with mutagen
- `ThumbnailDownloader`: Async downloads of channel thumbnails with resize
- `DownloadManager`: Orchestrates all download types, handles playlists
- `run_download()` / `main()`: argparse CLI entry points

### Technical Details
- **Player clients**: `YDL_COMMON_OPTS` sets only `remote_components: ["ejs:github"]` — the EJS challenge solver is fetched at runtime (needs Deno) to work around YouTube signature/`n`-parameter challenges that cause 403 errors. `player_client` is deliberately **not pinned**: yt-dlp 2026.08.19 removed `android_vr` from its defaults (its HTTPS formats now require a GVS PO token and 403 without one — yt-dlp/yt-dlp#17456) and defaults to `visionos`+`web`, which serves the full DASH audio set (opus 251). Re-adding a pin degrades music to itag 18 (44k AAC) and reintroduces the 403s.
- **Time limits**: `--limit` is parsed by `parse_duration()` and injected as yt-dlp `download_ranges` opts, so only the requested range is fetched. Video also gets `force_keyframes_at_cuts` (frame-accurate re-encode at the cut); music does **not** — forcing keyframes would make yt-dlp's ranged FFmpeg download drop `-c copy`, causing a double lossy transcode. `_apply_limit_opts(opts, limit_seconds, force_keyframes=...)` controls this.
- **Music quality**: `FFmpegExtractAudio` gets `preferredquality` from `--audio-quality` (default `0` = best VBR). Optional `--normalize` runs a Yodle-side two-pass ffmpeg `loudnorm` pass (-14 LUFS, linear mode) after download, before ID3 tagging. m4a `postprocessor_args` must stay dict-form scoped to `embedthumbnail+ffmpeg` — list-form args leak into every ffmpeg postprocessor and break stream copies. For m4a, `FFmpegMetadata` must run **before** `EmbedThumbnail`: the metadata pass's `-vn` would otherwise drop the cover art (mp3 order is the reverse and stays that way).
- **Playlists**: Detected by `playlist` or `list=` in URL; auto-expands to individual videos
- **Channels**: Detected by `/@`, `/channel/`, `/c/`, or `/user/` in URL
- **Batch pacing**: `DownloadManager.download()` gates every fetch after the first behind `_pause_between_downloads()` — `random.randint(PAUSE_MIN_SECONDS, PAUSE_MAX_SECONDS)` (60–900s = 1–15 min) + `time.sleep`. Applies across batch files, multiple URLs, and playlist entries; skipped URLs don't count. This keeps back-to-back requests from tripping YouTube's risk-flagging (403 "high risk"). Tests patch `time.sleep`/`random.randint` — any test driving 2+ fetches through a real `DownloadManager` must patch `time.sleep` too.

## Output Structure

```
~/Yodle/                              # Default output directory
├── Video_Title-[video_id].mp4
├── Video_Title-[video_id].png
├── Video_Title.mp3
├── Video_Title.png
├── Playlist_Name/
│   ├── Video1-[id].mp4
│   ├── Video1-[id].png
│   ├── Video1.mp3
│   └── Video1.png
└── Thumbnails/
    └── Channel_Name/
        ├── original/
        │   └── video_id.png
        └── resized_512/
            └── video_id.png
```

To use a custom output location, set the environment variable before running:

```bash
export YODLE_OUTPUT_DIR="/path/to/your/output"
uv run yodle.py
```

**Note**: Thumbnails are automatically downloaded and saved as PNG files alongside video and music downloads. Music files also have thumbnails embedded in ID3 tags for music player compatibility.

## Tests

```bash
uv run --with-requirements requirements-test.txt pytest
```

The suite lives in `tests/` (pytest, config in `pytest.ini`). Network-dependent smoke tests are marked and skipped by default.

## Legacy CLI Scripts (in archive/)

These scripts are preserved for reference but superseded by yodle.py:

| Script | Purpose |
|--------|---------|
| `video_dl.py` | CLI video downloader |
| `music_dl_updated.py` | CLI music downloader (M4A) |
| `download_music.py` | CLI music downloader (MP3) |
| `thumbnail_downloader.py` | CLI channel thumbnail downloader |
| `music_dl.py` | Simple M4A downloader |
| `music_mp3_dl.py` | Simple MP3 downloader |
| `music-downloader.py` | Older music downloader |

## Troubleshooting

### ffmpeg not found
**Solution**: Install ffmpeg on your system PATH
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Verify
ffmpeg -version
```

### Cookie extraction fails
**Causes**: Browser not installed, browser still running, or incorrect selection

**Solution**:
- Close all browser instances completely before extraction
- Try the alternative browser (Chrome vs Firefox)
- Use `--cookies-file` to point to an existing cookies.txt file
- For public videos, omit `-b` (or use `-b none`)

### Using custom cookies file
**To use an existing cookies.txt file**:
1. Pass `--cookies-file /path/to/cookies.txt` (Netscape format)
2. Downloads will use this file for authentication

**Common locations**:
- `~/.config/yt-dlp/cookies.txt` (default yt-dlp location)
- Custom exported cookies from browser extensions

### Private/age-restricted videos fail
**Solution**:
1. Pass `-b chrome` or `-b firefox`
2. Ensure you're logged into YouTube in that browser
3. Close browser completely before downloading

### Playlist not detected
**Issue**: Videos download to root directory instead of playlist folder

**Solution**: Ensure URL contains `list=` parameter:
- Correct: `https://youtube.com/playlist?list=PLxxx`
- Incorrect: `https://youtube.com/watch?v=xxx` (single video)

## Important Notes

- Quote URLs in zsh: `uv run yodle.py 'https://youtube.com/watch?v=...'`
- For private/age-restricted videos, select your browser with `-b`
- Channel thumbnail mode expects a channel URL (e.g., `https://youtube.com/@channelname`)
- Downloads saved to: `~/Yodle/` by default, or to `$YODLE_OUTPUT_DIR` if set
