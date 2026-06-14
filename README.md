# Yodle - YouTube Downloader

A powerful, all-in-one YouTube downloader CLI interfaces.

Download videos, music, and channel thumbnails with ease. Built with Python and optimized for simplicity and reliability.

> **Recent Update:** The output directory is now configurable via the `YODLE_OUTPUT_DIR` environment variable and defaults to `~/Yodle`. The previous hardcoded network mount logic has been removed.


---

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
  - [CLI Mode](#cli-mode)
- [CLI Options and Flags](#cli-options-and-flags)
- [Configuration](#configuration)
- [Architecture Overview](#architecture-overview)
- [Output Directory Structure](#output-directory-structure)
- [Troubleshooting](#troubleshooting)
- [Advanced Features](#advanced-features)

---

## Features

### Core Capabilities

- **Video Downloads**: Download in multiple formats (MP4, MKV, WebM) with best available H.264/HEVC quality
- **Music Downloads**: Extract audio and save as MP3 or M4A with full ID3 metadata and album art
- **Channel Thumbnails**: Batch download all thumbnails from a YouTube channel with original and resized versions
- **Playlist Support**: Automatically detect and expand playlists into individual downloads
- **Format Selection**: Choose output format for both video and audio

### Quality of Life

- **Browser Cookie Extraction**: Automatically extract cookies from Chrome or Firefox to access private/age-restricted videos
- **Custom Cookies Support**: Use your own cookies.txt file for authentication
- **Auto-Update Detection**: Check for yt-dlp updates at startup with one-click update command
- **Progress Tracking**: Real-time download progress with percentage and ETA
- **Thumbnail Embedding**: Automatically download and embed video thumbnails as album art in music files
- **Multi-URL Support**: Download multiple URLs in a single operation
- **Detailed Status Logging**: Timestamped logs for debugging and tracking download status

---

## Quick Start

### GUI Mode (Recommended)

```bash
# Run the GUI
uv run yodle
```

### CLI Mode

```bash
# Download a single video
uv run yodle 'https://youtube.com/watch?v=dQw4w9WgXcQ'

# Download as music (MP3)
uv run yodle -t music 'https://youtube.com/watch?v=dQw4w9WgXcQ'

# Download in different formats
uv run yodle -t both --video-format mkv --audio-format m4a 'URL'

# Multiple URLs
uv run yodle -t music 'URL1' 'URL2' 'URL3'

# With browser cookies for private videos
uv run yodle -b chrome 'https://youtube.com/watch?v=...'
```

---

## Requirements

- **Python 3.11+**
- **ffmpeg** (must be on system PATH)
- **uv** (Python package manager - download from https://docs.astral.sh/uv/getting-started/)
- **Dependencies** (managed by uv via pyproject.toml and uv.lock)

### Install Dependencies

#### Using uv (Recommended)

```bash
# Install dependencies into the project's virtual environment
uv sync

# Or just run - uv installs dependencies automatically if needed
uv run yodle
```

#### Manual Installation (without uv)

```bash
pip install yt-dlp>=2024.1.1 mutagen>=1.47.0 pydub>=0.25.1 pillow>=10.0.0 requests>=2.31.0 browser-cookie3>=0.19.1
```

### Install ffmpeg

ffmpeg is required for video/audio processing and must be available on your system PATH.

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg
```

**Windows:**
```bash
choco install ffmpeg
# or download from https://ffmpeg.org/download.html
```

**Verify Installation:**
```bash
ffmpeg -version
```

---

## Installation

### Option 1: Using uv (Recommended)

This project uses uv for modern Python project management with lock files and reproducible builds.

```bash
# Clone or download the repository
cd yodle

# Install dependencies into the project environment
uv sync

# Run the application
uv run yodle
```

The project includes:
- **pyproject.toml**: Project metadata and dependency specifications
- **uv.lock**: Lock file for reproducible dependency versions across machines
- **.venv**: Project-specific virtual environment (created by uv)

### Option 2: Traditional Python Installation

```bash
# Ensure Python 3.11+ is installed
python3 --version

# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install yt-dlp>=2024.1.1 mutagen>=1.47.0 pydub>=0.25.1 pillow>=10.0.0 requests>=2.31.0 browser-cookie3>=0.19.1

# Run the application
python3 -m yodle
```

### Option 3: Global Installation

```bash
# Copy the yodle executable to a location on your PATH
cp yodle /usr/local/bin/
chmod +x /usr/local/bin/yodle

# Run from anywhere
yodle
```

---

## Usage


---

### CLI Mode

Use the command line interface for automation, scripting, or batch operations:

```bash
# Basic usage - downloads as video (MP4) by default
uv run yodle 'https://youtube.com/watch?v=dQw4w9WgXcQ'

# Specify download type
uv run yodle -t music 'URL'
uv run yodle -t both 'URL'
uv run yodle -t thumbnails 'https://youtube.com/@channelname'

# Choose output formats
uv run yodle --video-format mkv 'URL'
uv run yodle --audio-format m4a 'URL'

# Multiple URLs at once
uv run yodle -t music 'URL1' 'URL2' 'URL3'

# With browser cookies
uv run yodle -b chrome 'URL'
uv run yodle -b firefox 'URL'

# With custom cookies file
uv run yodle --cookies-file /path/to/cookies.txt 'URL'

# Combined example
uv run yodle -t both -b chrome --video-format mkv --audio-format m4a 'URL1' 'URL2'
```

---

## CLI Options and Flags

### Positional Arguments

```
urls                  YouTube URL(s) to download (one or more)
```

**Note:** If no URLs are provided, Yodle launches in GUI mode instead.

### Options

#### `-t, --type {video,music,both,thumbnails}`
Download type specification.

- `video` - Download video only (default with URL arguments)
- `music` - Download audio only
- `both` - Download both video and audio
- `thumbnails` - Download all thumbnails from a channel

**Default:** `both`

**Examples:**
```bash
uv run yodle -t video 'URL'
uv run yodle --type music 'URL'
```

#### `--video-format {mp4,mkv,webm}`
Output format for video downloads.

- `mp4` - MPEG-4 video format (widely compatible, smaller files)
- `mkv` - Matroska format (better quality preservation, larger files)
- `webm` - WebM format (efficient compression, modern browsers)

**Default:** `mp4`

**Examples:**
```bash
uv run yodle --video-format mkv 'URL'
uv run yodle -t both --video-format webm --audio-format m4a 'URL'
```

#### `--audio-format {mp3,m4a}`
Output format for audio downloads.

- `mp3` - MPEG-3 audio format (most compatible, ID3 tags embedded)
- `m4a` - MPEG-4 audio format (better quality, fewer players support ID3)

**Default:** `mp3`

**Examples:**
```bash
uv run yodle --audio-format m4a 'URL'
uv run yodle -t music --audio-format m4a 'URL'
```

#### `-b, --browser {none,chrome,firefox}`
Extract cookies from your browser for private/age-restricted videos.

- `none` - No authentication (for public videos)
- `chrome` - Extract from Google Chrome
- `firefox` - Extract from Firefox

**Default:** Not set (uses `none` behavior)

**Important:** Close your browser completely before using this option.

**Examples:**
```bash
uv run yodle -b chrome 'URL'
uv run yodle --browser firefox 'URL'
```

#### `--cookies-file PATH`
Use a custom cookies.txt file in Netscape format.

Useful if you've exported cookies from a browser extension or prefer using an existing cookies file.

**Examples:**
```bash
uv run yodle --cookies-file ~/.config/yt-dlp/cookies.txt 'URL'
uv run yodle --cookies-file ~/Downloads/my_cookies.txt 'URL'
```

### Exit Codes

- `0` - All downloads completed successfully
- `1` - One or more downloads failed

---

## Configuration

### Output Directory

All downloaded files are saved to:

```
~/Yodle/
```

This directory is created automatically on first use. To use a custom output location, set the `YODLE_OUTPUT_DIR` environment variable before running Yodle:

```bash
export YODLE_OUTPUT_DIR="/path/to/your/output"
uv run yodle
```

Or inline:

```bash
YODLE_OUTPUT_DIR="/path/to/your/output" uv run yodle
```

### Cookies Storage

Extracted cookies are automatically saved to:

```
~/.config/yt-dlp/cookies.txt
```

This is the standard yt-dlp cookies location and is automatically used for subsequent downloads.

### Logging

Yodle outputs logs to:

- **GUI Mode**: Status Log widget in the application
- **CLI Mode**: Standard output (stdout)

**Log Level:** INFO (shows important operations and progress)

Logs include timestamps and are helpful for debugging issues.

---

## Architecture Overview

### Core Components

#### `CookieManager`
Handles extraction of authentication cookies from installed browsers.

- Supports Chrome and Firefox
- Saves cookies in Netscape HTTP cookie format
- Compatible with yt-dlp's cookie handling
- Automatically filters for YouTube/Google domains

#### `UpdateChecker`
Monitors yt-dlp version on PyPI and alerts users to updates.

- Queries PyPI API for latest version
- Compares calendar versioning (YYYY.MM.DD format)
- Provides easy-to-use update command
- Displays update notification in status log when available

#### `VideoDownloader`
Downloads YouTube videos in best available quality.

- Uses H.264/HEVC codec preference for quality/compatibility balance
- Supports MP4, MKV, and WebM output formats
- Automatically downloads and embeds video thumbnails
- Embeds video metadata (title, duration, etc.)
- Handles playlists and single videos

**Quality Strategy:**
- Prefers H.264/HEVC video codec (`bv*[vcodec~="^((he|a)vc|h26[45])"]`)
- Combines best video + best audio streams
- Falls back to highest quality available

#### `MusicDownloader`
Extracts audio from YouTube videos and converts to MP3/M4A.

- Downloads highest quality audio stream
- Extracts to M4A intermediate format
- Converts to MP3 with ID3v2 tags (when selected)
- Embeds metadata:
  - Title (TIT2)
  - Artist/Uploader (TPE1)
  - Album (TALB)
  - Year (TDRC)
  - Genre (TCON)
  - Thumbnail as cover art (APIC)
- Automatically downloads and embeds thumbnail as album art
- Preserves M4A format option for lossless audio

#### `ThumbnailDownloader`
Batch downloads all video thumbnails from a YouTube channel.

- Asynchronous downloads for speed
- Creates organized directory structure
- Saves original resolution thumbnails
- Automatically resizes to 512px width variant
- Filters out upcoming/live videos
- Returns success count and directory path

#### `DownloadManager`
Orchestrates all download operations and coordinates components.

- Routes downloads to appropriate downloader based on type
- Handles playlist expansion and directory organization
- Manages cookie authentication
- Provides progress and logging callbacks
- Supports batch operations (multiple URLs)

#### `YodleGUI`
Tkinter-based graphical user interface.

- Non-blocking downloads via threading
- Queue-based message passing between threads
- Real-time progress updates
- Timestamped status logging with update notifications
- Browser and format selection dropdowns
- Auto-extracting cookies on selection

#### `run_cli_download()`
Command-line interface entry point for scripting and automation.

- Argument parsing and validation
- Cookie handling (extraction or custom file)
- Progress callback for terminal output
- Exit codes for script integration
- Batch URL processing

### Data Flow

```
User Input
    ↓
Main Entry Point (GUI or CLI)
    ↓
Argument/Option Parsing
    ↓
Cookie Management (if needed)
    ↓
DownloadManager.download()
    ├── Playlist Detection
    │   └── Expand to individual videos
    └── Router
        ├── VideoDownloader → Video Output
        ├── MusicDownloader → Audio Output
        └── ThumbnailDownloader → Channel Thumbnails
```

---

## Output Directory Structure

### Single Video Download

```
~/Yodle/
├── Video_Title-[video_id].mp4          # Video file
└── Video_Title-[video_id].png          # Video thumbnail
```

### Single Music Download

```
~/Yodle/
├── Video_Title.mp3                     # Audio file (with ID3 tags)
├── Video_Title.m4a                     # Alternative audio format (if selected)
└── Video_Title.png                     # Thumbnail (embedded in audio tags)
```

### Playlist Download

```
~/Yodle/
└── Playlist_Name/                      # Playlist folder
    ├── Video1_Title-[id].mp4          # Video files
    ├── Video1_Title-[id].png          # Video thumbnails
    ├── Video1_Title.mp3               # Audio files
    ├── Video1_Title.png               # Audio thumbnails
    ├── Video2_Title-[id].mp4
    ├── Video2_Title-[id].png
    ├── Video2_Title.mp3
    └── Video2_Title.png
```

### Channel Thumbnail Download

```
~/Yodle/
└── Thumbnails/
    └── Channel_Name/
        ├── original/
        │   ├── video_id_1.png         # Original resolution
        │   ├── video_id_2.png
        │   └── ...
        └── resized_512/
            ├── video_id_1.png         # 512px width (aspect ratio preserved)
            ├── video_id_2.png
            └── ...
```

### File Naming

- **Videos**: `Title-[video_id].{ext}`
- **Audio**: `Title.{ext}`
- **Thumbnails**: `video_id.png`

Filenames are automatically sanitized to remove special characters and replace spaces with underscores.

---

## Troubleshooting

### FFmpeg Not Found

**Error:** `ERROR: ffmpeg not found` or `WARNING: ffmpeg not found`

**Cause:** ffmpeg is not installed or not on your system PATH.

**Solution:**

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (using Chocolatey)
choco install ffmpeg

# Verify installation
ffmpeg -version
```

After installation, restart Yodle.

---

### Cookie Extraction Fails

**Error:** `Could not extract cookies from {browser}`

**Causes:**
- Browser is currently running (locks cookie database)
- Browser not installed or not found
- Permission issues accessing browser data

**Solutions:**

1. **Close your browser completely** (all windows, not just minimize):
   ```bash
   # macOS - force quit if needed
   killall chrome   # Chrome
   killall firefox  # Firefox
   ```

2. **Try the alternative browser** (Chrome vs Firefox)

3. **Use a custom cookies file** instead:
   - Export cookies using a browser extension (e.g., "Get cookies.txt" extension)
   - Select "Custom file..." from the Browser Cookies dropdown
   - Navigate to your exported cookies.txt file

4. **For public videos, skip authentication**:
   - Select "None" from Browser Cookies dropdown
   - Proceed with download

---

### Private or Age-Restricted Videos Fail to Download

**Error:** HTTP 403 Forbidden or similar authentication error

**Causes:**
- Video requires YouTube login
- Video is age-restricted
- Video is private (but you should have access)

**Solutions:**

1. **Extract browser cookies:**
   - Ensure you're logged into YouTube in your browser
   - Close the browser completely
   - In Yodle, select your browser from the "Browser Cookies" dropdown
   - The cookies will be extracted and used for authentication

2. **Use custom cookies:**
   - Export your cookies using a browser extension
   - Select "Custom file..." and point to the exported file
   - Try the download again

3. **Check your YouTube account:**
   - Verify you have access to the video
   - Check if your YouTube account can view the video in a browser

---

### Playlist Not Recognized

**Error:** Videos download to root directory instead of playlist folder

**Cause:** URL doesn't contain playlist identifier that Yodle recognizes.

**Solution:** Ensure your URL contains one of these identifiers:
- `list=` parameter: `https://youtube.com/playlist?list=PLxxx...`
- `playlist` in URL: `https://youtube.com/playlist/...`

**Incorrect URLs (single video):**
- `https://youtube.com/watch?v=xxx` (even if from a playlist)
- `https://youtu.be/xxx`

**Correct URLs (playlist):**
- `https://youtube.com/playlist?list=PLxxx...`
- `https://youtube.com/watch?v=xxx&list=PLxxx...`

**Tip:** Get the proper playlist URL from YouTube's "Share" button when viewing a playlist.

---

### Channel Thumbnails Not Downloading

**Error:** `No videos found in channel` or `No thumbnails to download`

**Causes:**
- URL is not a valid channel URL
- Channel is private or restricted
- Channel has no videos (extremely rare)

**Solutions:**

1. **Verify it's a channel URL:**
   - Should contain `/@channelname` (new format)
   - Or `/channel/UCxxxxxxxxx` (old format)
   - Or `/c/channelname` or `/user/username` (legacy formats)

2. **Examples of valid channel URLs:**
   - `https://youtube.com/@channelname`
   - `https://youtube.com/channel/UCxxxxxxxxx`
   - `https://youtube.com/c/channelname`

3. **Check if channel is public:**
   - Try visiting the channel in your browser first
   - If you can't see videos, Yodle won't be able to either

4. **Use browser cookies for restricted channels:**
   - If you're a member or have special access, extract your browser cookies
   - Select your browser from the dropdown before downloading

---

### GUI Doesn't Respond During Download

**This is expected behavior.** The GUI is responsive only when not downloading. This prevents UI freezing.

The status log continues to update in real-time, showing download progress. Wait for the completion message.

---

### Downloads Hang or Timeout

**Error:** Download seems to hang indefinitely

**Causes:**
- Network connectivity issues
- YouTube throttling due to many requests
- Very large files taking time to download

**Solutions:**

1. **Check network connection:**
   ```bash
   ping youtube.com
   ```

2. **Try a smaller/shorter video first** to test if Yodle works

3. **Wait longer** for very large files (can take many minutes)

4. **Restart Yodle and try again**

5. **Try extracting browser cookies** - sometimes helps with throttling

---

### File Already Exists Warning

**Behavior:** Files are overwritten if they already exist in the output directory.

**Workaround:** Move or rename existing files before downloading if you want to keep them.

---

### Memory Issues with Very Large Playlists

**Error:** High memory usage or crashes when downloading large playlists

**Solution:**

Download playlists in batches. Copy 10-20 video URLs at a time instead of entire large playlists.

For very large channels (100+ videos), consider using the Thumbnails mode instead and importing into another tool.

---

## Advanced Features

### Browser Cookie Extraction

Yodle can automatically extract cookies from your web browser for downloading private, age-restricted, or member-only content.

#### How It Works

1. Yodle reads your browser's cookie database
2. Filters for YouTube/Google domains only
3. Converts to Netscape format (standard for yt-dlp)
4. Saves to `~/.config/yt-dlp/cookies.txt`
5. Uses these cookies for subsequent downloads

#### Important Notes

- **Close your browser first**: The browser locks its cookie database while running. You must completely close all windows.
- **Supported browsers**: Chrome and Firefox
- **Windows permissions**: On Windows, you may need to run as Administrator
- **Cookie expiration**: YouTube cookies expire after a period. Re-extract them if downloads start failing.

#### Usage

**GUI:**
1. Go to "Browser Cookies" dropdown
2. Select your browser (Chrome or Firefox)
3. Yodle extracts cookies automatically
4. Proceed with download

**CLI:**
```bash
uv run yodle -b chrome 'URL'
uv run yodle --browser firefox 'URL'
```

---

### Custom Cookies File

If you prefer not to grant Yodle access to your browser, use an exported cookies.txt file.

#### Export Cookies

1. **Using Browser Extension:**
   - Install "Get cookies.txt" extension (available for Chrome/Firefox)
   - Visit youtube.com while logged in
   - Click the extension icon
   - Save the exported file to your computer

2. **Format:** Must be Netscape HTTP Cookie format (standard format exported by the extension)

#### Usage

**GUI:**
1. Go to "Browser Cookies" dropdown
2. Select "Custom file..."
3. Navigate to your cookies.txt file
4. Label updates to show "Custom: filename.txt"
5. Proceed with download

**CLI:**
```bash
uv run yodle --cookies-file ~/Downloads/cookies.txt 'URL'
```

---

### Auto-Update Checking

Yodle checks PyPI for yt-dlp updates on startup.

#### How It Works

1. At startup, queries the official PyPI API
2. Compares installed version with latest available version
3. Displays update notification in the status log if update available
4. Notification includes version numbers and update command

#### Status Log Update Notification

When an update is available, a message appears in the status log:

```
[14:23:45] yt-dlp update available: 2024.01.15 → 2024.02.01
[14:23:46] Update command: uv sync --upgrade-package yt-dlp
```

#### Update yt-dlp

Run the update command manually:

```bash
# Using uv (recommended)
uv sync --upgrade-package yt-dlp

# Or using pip directly
pip install --upgrade yt-dlp
```

---

### Playlist Handling

Yodle automatically detects and expands playlists.

#### Playlist Detection

A URL is considered a playlist if it contains:
- `playlist` in the URL path
- `list=` parameter

#### Automatic Organization

Downloaded playlist items are automatically organized in a folder:

```
~/Yodle/Playlist_Name/
├── Video1_Title-[id].mp4
├── Video1_Title.mp3
├── Video2_Title-[id].mp4
├── Video2_Title.mp3
└── ...
```

#### Status Log Information

The log shows progress through the playlist:

```
[14:23:45] Processing: https://youtube.com/playlist?list=PLxxx...
[14:23:46] Playlist: My Favorite Songs (25 videos)
[14:23:47] [1/25] Beautiful Song
[14:23:52] Video saved: Beautiful Song
[14:24:15] [2/25] Another Great Song
...
```

---

### Batch URL Processing

Download multiple videos/playlists in a single operation.

#### GUI Method

Paste multiple URLs in the URL input box, one per line:

```
https://youtube.com/watch?v=xxx
https://youtube.com/watch?v=yyy
https://youtube.com/playlist?list=PLzzz
```

Click "DOWNLOAD" once - all URLs process in order.

#### CLI Method

Pass multiple URLs as arguments:

```bash
uv run yodle -t music \
  'https://youtube.com/watch?v=xxx' \
  'https://youtube.com/watch?v=yyy' \
  'https://youtube.com/playlist?list=PLzzz'
```

#### Progress Tracking

Each URL processes sequentially. The status log shows which URL is being processed and progress.

---

### Thumbnail Customization

Downloaded thumbnails have different behaviors based on download type.

#### Video Downloads

Thumbnail is saved as PNG file alongside the video:

```
~/Yodle/
├── Video_Title-[id].mp4
└── Video_Title-[id].png
```

The PNG can be imported into video editors or used as preview images.

#### Music Downloads

Thumbnail is automatically:
1. Downloaded as PNG
2. Converted to appropriate format
3. Embedded in MP3 ID3 tags (APIC frame)
4. Shown in music players that support tag display

No separate file is created (it's embedded in the audio file).

#### Channel Downloads

Two versions are created:

```
~/Yodle/Thumbnails/Channel_Name/
├── original/
│   └── video_id.png                    # Original resolution
└── resized_512/
    └── video_id.png                    # 512px width (aspect ratio preserved)
```

Use resized versions for web display or previews; original for archival or high-quality use.

---

### ID3 Tag Embedding (Music Downloads)

MP3 files automatically receive comprehensive metadata tags.

#### Embedded Tags

- **Title (TIT2)**: Video title
- **Artist (TPE1)**: Video uploader/channel name
- **Album (TALB)**: Uploader name (or "YouTube")
- **Year (TDRC)**: Upload year from upload date
- **Genre (TCON)**: "Music"
- **Cover Art (APIC)**: Thumbnail image

#### Music Player Compatibility

Most music players display these tags:
- Apple Music
- Spotify (when importing local files)
- VLC Media Player
- Foobar2000
- Music (on Windows/macOS)
- Android default music player

Album art (cover) displays in the player UI when supported.

#### Manual Tag Editing

Edit tags using dedicated tools if needed:
- **macOS**: Musicbrainz Picard, Audio Hijack
- **Windows**: MediaInfo, Mp3tag, TagScanner
- **Linux**: Picard, Ex Falso
- **Web-based**: MusicBrainz Picard (cross-platform)

---

### Format Considerations

Choose formats based on your needs:

#### Video Formats

| Format | Pros | Cons | Use Case |
|--------|------|------|----------|
| **MP4** | Best compatibility, widely supported | Slightly larger files | Default, most devices |
| **MKV** | Highest quality preservation, multiple streams | Limited player support | Archival, editing, advanced players |
| **WebM** | Smallest files, modern compression | Limited legacy device support | Streaming, web use |

#### Audio Formats

| Format | Pros | Cons | Use Case |
|--------|------|------|----------|
| **MP3** | Universal compatibility, standard, ID3 tags | Lossy compression | Music players, portability |
| **M4A** | Better quality at same bitrate, modern codec | Fewer players support, some tag loss | Music production, high-fidelity listening |

#### Recommendations

- **Most users**: Video = MP4, Audio = MP3
- **Quality-focused**: Video = MKV, Audio = M4A
- **Archival**: Video = MKV, Audio = M4A
- **Sharing/Streaming**: Video = WebM, Audio = MP3
- **Legacy devices**: Video = MP4, Audio = MP3

---

## Project Information

- **Current Version**: 1.0.0
- **Python Requirement**: 3.11+
- **License**: See LICENSE file
- **Dependencies**: yt-dlp, mutagen, pydub, pillow, requests, browser-cookie3

---

## Contributing

Found an issue? Have a feature request? Open an issue or submit a pull request on GitHub.

---

## Support

For help:
1. Check the [Troubleshooting](#troubleshooting) section above
2. Review the status log for error messages
3. Check your system setup (ffmpeg, Python version, dependencies)
4. Try with a different video (to isolate the issue)

---

## Legal Notice

Yodle is designed for downloading content you have the right to download. Respect copyright laws in your jurisdiction. Only download content with proper authorization.

---

**Enjoy downloading with Yodle!**
