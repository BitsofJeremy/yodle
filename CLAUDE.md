# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Yodle is a YouTube downloader with a GUI for downloading videos, music (MP3), and channel thumbnails. Downloads are saved to `~/Downloads/Yodle/`.

## Quick Start

```bash
# Run with uv (recommended - handles dependencies automatically)
uv run yodle.py

# Or run directly if dependencies are installed
python yodle.py
```

## Requirements

- Python 3.11+
- ffmpeg (must be on system PATH): `brew install ffmpeg`
- Dependencies (handled automatically by uv, or install manually):
  ```bash
  pip install yt-dlp mutagen pydub pillow requests browser-cookie3
  ```

## yodle.py - Unified GUI Downloader

Single-file application using PEP 723 inline script metadata. No setup required when using uv.

### Features
- **Video**: Downloads in best H.264/HEVC quality
- **Music**: Downloads as MP3 with embedded ID3 tags and album art
- **Both**: Downloads video and music versions
- **Thumbnails**: Downloads all thumbnails from a YouTube channel (original + resized)

### GUI Components
- URL input (supports multiple URLs, one per line)
- Download type selector: Video / Music / Both / Thumbnails
- Browser cookie extraction: None / Chrome / Firefox / Custom file...
- Progress bar with percentage
- Status log with timestamps

### Auto-Update
Checks for yt-dlp updates at startup and displays a notification banner if outdated.

## Architecture

### Key Classes in yodle.py
- `CookieManager`: Extracts cookies from Chrome/Firefox to `~/.config/yt-dlp/cookies.txt`
- `UpdateChecker`: Queries PyPI for yt-dlp updates
- `VideoDownloader`: Downloads video with FFmpegMetadata post-processor
- `MusicDownloader`: Downloads M4A, converts to MP3, embeds ID3 tags with mutagen
- `ThumbnailDownloader`: Async downloads of channel thumbnails with resize
- `DownloadManager`: Orchestrates all download types, handles playlists
- `YodleGUI`: Tkinter GUI with threading for non-blocking downloads

### Technical Details
- **Player client**: Uses Android client to avoid 403 errors
- **Threading**: GUI runs on main thread; downloads run on worker thread with queue-based communication
- **Playlists**: Detected by `playlist` or `list=` in URL; auto-expands to individual videos
- **Channels**: Detected by `/@`, `/channel/`, `/c/`, or `/user/` in URL

## Output Structure

```
~/Downloads/Yodle/
├── Video_Title-[video_id].mp4       # Single video
├── Video_Title-[video_id].png       # Video thumbnail (saved separately)
├── Video_Title.mp3                   # Single music
├── Video_Title.png                   # Music thumbnail (saved separately)
├── Playlist_Name/                    # Playlist downloads
│   ├── Video1-[id].mp4
│   ├── Video1-[id].png              # Video thumbnail
│   ├── Video1.mp3
│   └── Video1.png                   # Music thumbnail
└── Thumbnails/                       # Channel thumbnails
    └── Channel_Name/
        ├── original/
        │   └── video_id.png
        └── resized_512/
            └── video_id.png
```

**Note**: Thumbnails are automatically downloaded and saved as PNG files alongside video and music downloads. Music files also have thumbnails embedded in ID3 tags for music player compatibility.

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
- Use "Custom file..." to point to an existing cookies.txt file
- For public videos, use "None" option

### Using custom cookies file
**To use an existing cookies.txt file**:
1. Select "Custom file..." from the Browser Cookies dropdown
2. Navigate to your cookies.txt file (Netscape format)
3. File path will be displayed (e.g., "Custom: cookies.txt")
4. Downloads will use this file for authentication

**Common locations**:
- `~/.config/yt-dlp/cookies.txt` (default yt-dlp location)
- Custom exported cookies from browser extensions

### Private/age-restricted videos fail
**Solution**:
1. Select your browser in "Browser Cookies" dropdown
2. Ensure you're logged into YouTube in that browser
3. Close browser completely before downloading

### Playlist not detected
**Issue**: Videos download to root directory instead of playlist folder

**Solution**: Ensure URL contains `list=` parameter:
- Correct: `https://youtube.com/playlist?list=PLxxx`
- Incorrect: `https://youtube.com/watch?v=xxx` (single video)

## Important Notes

- Quote URLs in zsh: `uv run yodle.py` then paste URL in GUI
- For private/age-restricted videos, select your browser for cookie extraction
- Channel thumbnail mode expects a channel URL (e.g., `https://youtube.com/@channelname`)
- Downloads saved to: `~/Downloads/Yodle/`
