#!/usr/bin/env python3
"""
Yodle - YouTube Downloader CLI

A CLI application for downloading YouTube videos, music (MP3/M4A),
and channel thumbnails.

Features:
- Video downloads (MP4/MKV/WebM with best H.264/HEVC quality)
- Music downloads (MP3/M4A with embedded ID3 tags and album art)
- Channel thumbnail downloads (original + resized)
- Browser cookie extraction for private/age-restricted content

Requirements:
- Python 3.11+
- ffmpeg (must be on system PATH)

Usage:
    uv run yodle 'https://youtube.com/watch?v=...'
    uv run yodle -t music --audio-format m4a 'URL'
    uv run yodle -t both --video-format mkv --audio-format m4a 'URL'
    uv run yodle -b chrome 'https://youtube.com/watch?v=...'
"""

import asyncio
import functools
import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# Third-party imports
import browser_cookie3
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TCON
from PIL import Image
from pydub import AudioSegment
import requests
import yt_dlp
from yt_dlp import YoutubeDL

# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

VERSION = "1.0.0"
OUTPUT_DIR = Path.home() / "Downloads" / "Yodle"
COOKIES_PATH = Path.home() / ".config" / "yt-dlp" / "cookies.txt"

# Common yt-dlp options applied to all extractors.
# remote_components downloads the EJS challenge solver script at runtime,
# which Deno needs to crack YouTube's JS signature/n challenges.
YDL_COMMON_OPTS = {
    "extractor_args": {"youtube": {"player_client": ["web", "android"]}},
    "remote_components": ["ejs:github"],
}

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("yodle")


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class DownloadResult:
    """Result of a single download operation."""

    success: bool
    url: str
    title: str = ""
    output_path: str = ""
    error: str = ""
    download_type: str = ""


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def sanitize_filename(title: str) -> str:
    """Convert title to safe filename with underscores."""
    clean_title = " ".join(title.split())
    clean_title = re.sub(r"[^\w\s-]", "", clean_title)
    clean_title = clean_title.replace(" ", "_")
    clean_title = re.sub(r"_+", "_", clean_title)
    clean_title = clean_title.strip("_")
    return clean_title


def is_playlist(url: str) -> bool:
    """Check if the URL is a playlist."""
    return "playlist" in url or "list=" in url


def is_channel(url: str) -> bool:
    """Check if the URL is a channel."""
    return "/@" in url or "/channel/" in url or "/c/" in url or "/user/" in url


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available on system PATH."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


# =============================================================================
# COOKIE MANAGEMENT
# =============================================================================


class CookieManager:
    """Handles browser cookie extraction."""

    SUPPORTED_BROWSERS = ["chrome", "firefox"]

    @staticmethod
    def get_cookies_path() -> Path:
        """Get or create the path for the cookies file."""
        COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        return COOKIES_PATH

    @classmethod
    def extract_cookies(cls, browser: str) -> Optional[Path]:
        """Extract cookies from browser and save to Netscape format."""
        cookies_path = cls.get_cookies_path()

        try:
            if browser.lower() == "chrome":
                cj = browser_cookie3.chrome()
            elif browser.lower() == "firefox":
                cj = browser_cookie3.firefox()
            else:
                logger.warning(f"Unsupported browser: {browser}")
                return None

            with open(cookies_path, "w") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for cookie in cj:
                    if cookie.domain.endswith((".youtube.com", ".google.com")):
                        secure = "TRUE" if cookie.secure else "FALSE"
                        f.write(
                            f"{cookie.domain}\t"
                            f"{'TRUE' if cookie.domain.startswith('.') else 'FALSE'}\t"
                            f"{cookie.path}\t"
                            f"{secure}\t"
                            f"{int(cookie.expires) if cookie.expires else 0}\t"
                            f"{cookie.name}\t"
                            f"{cookie.value}\n"
                        )

            logger.info(f"Cookies extracted from {browser}")
            return cookies_path

        except Exception as e:
            logger.error(f"Error extracting cookies from {browser}: {e}")
            if cookies_path.exists():
                try:
                    cookies_path.unlink()
                except OSError:
                    pass
            return None

    @classmethod
    def cleanup(cls) -> None:
        """Remove cookies file if it exists."""
        if COOKIES_PATH.exists():
            COOKIES_PATH.unlink()


# =============================================================================
# UPDATE CHECKER
# =============================================================================


class UpdateChecker:
    """Checks for yt-dlp updates via PyPI API."""

    PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"

    def get_current_version(self) -> str:
        """Get installed yt-dlp version."""
        import yt_dlp

        return yt_dlp.version.__version__

    def check_for_updates(self) -> Tuple[bool, str, str]:
        """
        Check PyPI for newer yt-dlp version.
        Returns: (update_available, current_version, latest_version)
        """
        try:
            current = self.get_current_version()
            response = requests.get(self.PYPI_URL, timeout=5)
            response.raise_for_status()
            latest = response.json()["info"]["version"]

            # Normalize calendar versioning (YYYY.MM.DD format) for comparison
            # Convert "2025.12.8" to "2025.12.08" for proper comparison
            def normalize_version(ver: str) -> tuple:
                """Parse YYYY.MM.DD version into comparable tuple of ints."""
                parts = ver.split(".")
                if len(parts) == 3:
                    return tuple(int(p) for p in parts)
                return (0, 0, 0)

            current_tuple = normalize_version(current)
            latest_tuple = normalize_version(latest)
            update_available = latest_tuple > current_tuple

            return (update_available, current, latest)

        except Exception as e:
            logger.warning(f"Update check failed: {e}")
            return (False, "", "")

    @staticmethod
    def get_update_command() -> str:
        """Return command to update yt-dlp in uv project."""
        return "uv sync --upgrade-package yt-dlp"


# =============================================================================
# VIDEO DOWNLOADER
# =============================================================================


class VideoDownloader:
    """Downloads videos in best available quality."""

    FORMAT_STRING = 'bestvideo[height>=2160]+bestaudio/bestvideo[height>=1440]+bestaudio/bestvideo+bestaudio/best'

    def __init__(
        self,
        cookies_path: Optional[Path] = None,
        progress_callback: Optional[Callable] = None,
        output_format: str = "mp4",
    ):
        self.cookies_path = cookies_path
        self.progress_callback = progress_callback
        self.output_format = output_format.lower()

    def _get_opts(self, output_dir: Path) -> dict:
        """Get yt-dlp options for video download."""
        opts = {
            **YDL_COMMON_OPTS,
            "format": self.FORMAT_STRING,
            "outtmpl": str(output_dir / "%(title)s-[%(id)s].%(ext)s"),
            "merge_output_format": self.output_format,
            "postprocessors": [{"key": "FFmpegMetadata"}],
            "retries": 3,
            "no_color": True,
        }

        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)

        if self.progress_callback:
            opts["progress_hooks"] = [self._progress_hook]

        return opts

    def _progress_hook(self, d: dict) -> None:
        """Progress hook for yt-dlp."""
        if d["status"] == "downloading" and self.progress_callback:
            try:
                percent = d.get("_percent_str", "0%").strip().replace("%", "")
                self.progress_callback(float(percent), d.get("_eta_str", ""))
            except (ValueError, TypeError):
                pass

    def _download_thumbnail(self, url: str, save_path: Path) -> bool:
        """Download thumbnail from URL."""
        try:
            import requests

            response = requests.get(url, stream=True, timeout=10)
            if response.status_code == 200:
                with open(save_path, "wb") as file:
                    for chunk in response.iter_content(1024):
                        file.write(chunk)
                return True
        except Exception as e:
            logger.warning(f"Thumbnail download failed: {e}")
        return False

    def _save_thumbnail_png(
        self, output_dir: Path, thumbnail_url: str, base_name: str
    ) -> Optional[Path]:
        """Download thumbnail and save as PNG."""
        temp_jpg = output_dir / "temp_thumb_video.jpg"
        png_path = output_dir / f"{base_name}.png"

        # Download as JPG temporarily
        if self._download_thumbnail(thumbnail_url, temp_jpg):
            try:
                with Image.open(temp_jpg) as img:
                    img.save(png_path, "PNG")
                    logger.info(f"Thumbnail saved: {png_path.name}")
                # Clean up temp file
                temp_jpg.unlink()
                return png_path
            except Exception as e:
                logger.warning(f"Thumbnail conversion failed: {e}")
                if temp_jpg.exists():
                    temp_jpg.unlink()
        return None

    def download(self, url: str, output_dir: Path) -> DownloadResult:
        """Download video to specified directory."""
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            opts = self._get_opts(output_dir)
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "Unknown")

                # Download and save thumbnail as PNG
                thumbnail_url = info.get("thumbnail")
                if thumbnail_url:
                    expected_name = (
                        f"{info.get('title', 'video')}-[{info.get('id', '')}]"
                    )
                    self._save_thumbnail_png(
                        output_dir, thumbnail_url, sanitize_filename(expected_name)
                    )

                # Find the downloaded file
                expected_name = f"{info.get('title', 'video')}-[{info.get('id', '')}]"
                # Check for the requested format first, then fallback to common formats
                extensions = [f".{self.output_format}"]
                if self.output_format not in ["mp4", "mkv", "webm"]:
                    extensions.extend([".mp4", ".mkv", ".webm"])
                else:
                    # Add other formats as fallbacks
                    for ext in [".mp4", ".mkv", ".webm"]:
                        if ext[1:] != self.output_format and ext not in extensions:
                            extensions.append(ext)

                for ext in extensions:
                    potential = output_dir / f"{sanitize_filename(expected_name)}{ext}"
                    if potential.exists():
                        return DownloadResult(
                            success=True,
                            url=url,
                            title=title,
                            output_path=str(potential),
                            download_type="video",
                        )

                return DownloadResult(
                    success=True,
                    url=url,
                    title=title,
                    output_path=str(output_dir),
                    download_type="video",
                )

        except Exception as e:
            logger.error(f"Video download failed: {e}")
            return DownloadResult(
                success=False, url=url, error=str(e), download_type="video"
            )


# =============================================================================
# MUSIC DOWNLOADER
# =============================================================================


class MusicDownloader:
    """Downloads audio and converts to MP3 with embedded metadata."""

    FORMAT_STRING = "bestaudio/best"

    def __init__(
        self,
        cookies_path: Optional[Path] = None,
        progress_callback: Optional[Callable] = None,
        output_format: str = "mp3",
    ):
        self.cookies_path = cookies_path
        self.progress_callback = progress_callback
        self.output_format = output_format.lower()

    def _get_opts(self, output_dir: Path) -> dict:
        """Get yt-dlp options for music download."""
        opts = {
            **YDL_COMMON_OPTS,
            "format": self.FORMAT_STRING,
            "writethumbnail": True,
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "retries": 3,
        }

        if self.output_format == "mp3":
            # Extract directly to MP3 using FFmpeg
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"},
                {"key": "EmbedThumbnail"},
                {"key": "FFmpegMetadata"},
            ]
        else:
            # Keep as M4A with embedded thumbnail
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a"},
                {"key": "EmbedThumbnail"},
                {"key": "FFmpegMetadata"},
            ]
            opts["postprocessor_args"] = [
                "-c:a",
                "aac",
                "-metadata:s:v",
                'title="Album Cover"',
                "-metadata:s:v",
                'comment="Cover (Front)"',
            ]

        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)

        if self.progress_callback:
            opts["progress_hooks"] = [self._progress_hook]

        return opts

    def _progress_hook(self, d: dict) -> None:
        """Progress hook for yt-dlp."""
        if d["status"] == "downloading" and self.progress_callback:
            try:
                percent = d.get("_percent_str", "0%").strip().replace("%", "")
                self.progress_callback(float(percent), d.get("_eta_str", ""))
            except (ValueError, TypeError):
                pass

    def _download_thumbnail(self, url: str, save_path: Path) -> bool:
        """Download thumbnail from URL."""
        try:
            import requests

            response = requests.get(url, stream=True, timeout=10)
            if response.status_code == 200:
                with open(save_path, "wb") as file:
                    for chunk in response.iter_content(1024):
                        file.write(chunk)
                return True
        except Exception as e:
            logger.warning(f"Thumbnail download failed: {e}")
        return False

    def _save_thumbnail_png(
        self, output_dir: Path, thumbnail_url: str, base_name: str
    ) -> Optional[Path]:
        """Download thumbnail and save as PNG."""
        temp_jpg = output_dir / "temp_thumb.jpg"
        png_path = output_dir / f"{base_name}.png"

        # Download as JPG temporarily
        if self._download_thumbnail(thumbnail_url, temp_jpg):
            try:
                with Image.open(temp_jpg) as img:
                    img.save(png_path, "PNG")
                    logger.info(f"Thumbnail saved: {png_path.name}")
                # Clean up temp file
                temp_jpg.unlink()
                return png_path
            except Exception as e:
                logger.warning(f"Thumbnail conversion failed: {e}")
                if temp_jpg.exists():
                    temp_jpg.unlink()
        return None

    def _embed_id3_tags(self, mp3_path: Path, info: dict) -> None:
        """Embed ID3 tags into MP3 file."""
        try:
            audio = MP3(str(mp3_path), ID3=ID3)

            try:
                audio.add_tags()
            except Exception:
                pass  # Tags may already exist

            audio["TIT2"] = TIT2(encoding=3, text=info.get("title", "Unknown"))
            audio["TPE1"] = TPE1(encoding=3, text=info.get("uploader", "Unknown"))
            audio["TALB"] = TALB(encoding=3, text=info.get("uploader", "YouTube"))

            upload_date = info.get("upload_date", "")
            if upload_date:
                audio["TDRC"] = TDRC(encoding=3, text=upload_date[:4])

            audio["TCON"] = TCON(encoding=3, text="Music")

            # Try to embed thumbnail — check multiple possible paths
            thumbnail_path = None
            for ext in (".png", ".jpg", ".webp"):
                candidate = mp3_path.with_suffix(ext)
                if candidate.exists():
                    thumbnail_path = candidate
                    break
            # Also check for yt-dlp's thumbnail filename pattern
            if not thumbnail_path:
                for ext in (".png", ".jpg", ".webp"):
                    candidate = mp3_path.parent / f"{mp3_path.stem}{ext}"
                    if candidate.exists():
                        thumbnail_path = candidate
                        break

            if thumbnail_path and thumbnail_path.exists():
                with open(thumbnail_path, "rb") as thumb_file:
                    mime = (
                        "image/png"
                        if thumbnail_path.suffix == ".png"
                        else "image/jpeg" if thumbnail_path.suffix == ".jpg"
                        else "image/webp"
                    )
                    audio["APIC"] = APIC(
                        encoding=3,
                        mime=mime,
                        type=3,
                        desc="Cover",
                        data=thumb_file.read(),
                    )
                    logger.info(f"Embedded thumbnail from: {thumbnail_path.name}")
            else:
                logger.warning(f"No thumbnail found for ID3 embedding near: {mp3_path.name}")

            audio.save()
            logger.info(f"Embedded ID3 tags in: {mp3_path.name}")

        except Exception as e:
            logger.warning(f"ID3 tagging failed: {e}")

    def download(self, url: str, output_dir: Path) -> DownloadResult:
        """Download audio and embed metadata."""
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            opts = self._get_opts(output_dir)

            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title", "Unknown")
                base_name = sanitize_filename(title)

                # Find the downloaded file (M4A or MP3)
                ext = self.output_format.lower()
                audio_path = output_dir / f"{base_name}.{ext}"
                if not audio_path.exists():
                    # Try original title
                    audio_path = output_dir / f"{title}.{ext}"
                if not audio_path.exists():
                    # Fallback: find any file with the right extension in output dir
                    for f in output_dir.glob(f"*.{ext}"):
                        audio_path = f
                        break

                # Save thumbnail using the actual audio filename stem so it matches
                thumbnail_url = info.get("thumbnail")
                if thumbnail_url and audio_path.exists():
                    self._save_thumbnail_png(output_dir, thumbnail_url, audio_path.stem)

                if audio_path.exists():
                    # Embed custom ID3 tags and thumbnail for MP3
                    if ext == "mp3":
                        self._embed_id3_tags(audio_path, info)
                    return DownloadResult(
                        success=True,
                        url=url,
                        title=title,
                        output_path=str(audio_path),
                        download_type="music",
                    )

                return DownloadResult(
                    success=True,
                    url=url,
                    title=title,
                    output_path=str(output_dir),
                    download_type="music",
                )

        except Exception as e:
            logger.error(f"Music download failed: {e}")
            return DownloadResult(
                success=False, url=url, error=str(e), download_type="music"
            )


# =============================================================================
# THUMBNAIL DOWNLOADER
# =============================================================================


class ThumbnailDownloader:
    """Downloads all thumbnails from a YouTube channel."""

    def __init__(self, progress_callback: Optional[Callable] = None):
        self.progress_callback = progress_callback

    async def get_channel_info(self, channel_url: str) -> dict:
        """Get channel information using yt-dlp."""
        loop = asyncio.get_running_loop()
        ydl_opts = {
            "quiet": True,
            "dump_single_json": True,
            "ignoreerrors": True,
            "no_warnings": True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(
                None, functools.partial(ydl.extract_info, channel_url, download=False)
            )
        return info

    def _resize_image(self, img: Image.Image, max_width: int = 512) -> Image.Image:
        """Resize image to max width while maintaining aspect ratio."""
        width, height = img.size
        if width <= max_width:
            return img

        ratio = max_width / width
        new_height = int(height * ratio)
        return img.resize((max_width, new_height), Image.Resampling.LANCZOS)

    async def download_thumbnail(
        self, thumbnail_url: str, output_dir: Path, video_id: str, timeout: int = 10
    ) -> bool:
        """Download and convert a single thumbnail."""
        try:
            import urllib.request

            original_dir = output_dir / "original"
            resized_dir = output_dir / "resized_512"
            original_dir.mkdir(parents=True, exist_ok=True)
            resized_dir.mkdir(parents=True, exist_ok=True)

            temp_path = output_dir / f"{video_id}_temp.jpg"
            original_png = original_dir / f"{video_id}.png"
            resized_png = resized_dir / f"{video_id}.png"

            loop = asyncio.get_running_loop()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    functools.partial(
                        urllib.request.urlretrieve, thumbnail_url, temp_path
                    ),
                ),
                timeout=timeout,
            )

            with Image.open(temp_path) as img:
                img.save(original_png, "PNG")
                resized = self._resize_image(img)
                resized.save(resized_png, "PNG")

            temp_path.unlink()
            return True

        except asyncio.TimeoutError:
            logger.warning(f"Timeout downloading thumbnail for {video_id}")
            return False
        except Exception as e:
            logger.warning(f"Error downloading thumbnail for {video_id}: {e}")
            return False

    async def download_all(self, channel_url: str, output_dir: Path) -> DownloadResult:
        """Download all thumbnails from a channel."""
        try:
            info = await self.get_channel_info(channel_url)
            if not info:
                return DownloadResult(
                    success=False,
                    url=channel_url,
                    error="Could not fetch channel info",
                    download_type="thumbnails",
                )

            channel_name = info.get("uploader", "unknown_channel")
            channel_dir = output_dir / "Thumbnails" / sanitize_filename(channel_name)
            channel_dir.mkdir(parents=True, exist_ok=True)

            entries = info.get("entries", [])
            if not entries:
                return DownloadResult(
                    success=False,
                    url=channel_url,
                    error="No videos found in channel",
                    download_type="thumbnails",
                )

            logger.info(f"Found {len(entries)} videos in {channel_name}")

            tasks = []
            for entry in entries:
                if not entry:
                    continue
                if entry.get("live_status") == "is_upcoming":
                    continue

                video_id = entry.get("id")
                thumbnail_url = entry.get("thumbnail")

                if video_id and thumbnail_url:
                    tasks.append(
                        self.download_thumbnail(thumbnail_url, channel_dir, video_id)
                    )

            if not tasks:
                return DownloadResult(
                    success=False,
                    url=channel_url,
                    error="No thumbnails to download",
                    download_type="thumbnails",
                )

            results = await asyncio.gather(*tasks)
            success_count = sum(1 for r in results if r)

            return DownloadResult(
                success=True,
                url=channel_url,
                title=f"{channel_name} ({success_count}/{len(tasks)} thumbnails)",
                output_path=str(channel_dir),
                download_type="thumbnails",
            )

        except Exception as e:
            logger.error(f"Thumbnail download failed: {e}")
            return DownloadResult(
                success=False, url=channel_url, error=str(e), download_type="thumbnails"
            )

    def download(self, channel_url: str, output_dir: Path) -> DownloadResult:
        """Synchronous wrapper for download_all."""
        return asyncio.run(self.download_all(channel_url, output_dir))


# =============================================================================
# DOWNLOAD MANAGER
# =============================================================================


class DownloadManager:
    """Orchestrates downloads based on user selection."""

    def __init__(
        self,
        output_dir: Path,
        cookies_path: Optional[Path] = None,
        progress_callback: Optional[Callable] = None,
        log_callback: Optional[Callable] = None,
        video_format: str = "mp4",
        audio_format: str = "mp3",
    ):
        self.output_dir = output_dir
        self.cookies_path = cookies_path
        self.progress_callback = progress_callback
        self.log_callback = log_callback

        self.video_downloader = VideoDownloader(
            cookies_path, progress_callback, video_format
        )
        self.music_downloader = MusicDownloader(
            cookies_path, progress_callback, audio_format
        )
        self.thumbnail_downloader = ThumbnailDownloader(progress_callback)

    def _log(self, message: str) -> None:
        """Log a message."""
        if self.log_callback:
            self.log_callback(message)
        logger.info(message)

    def _get_playlist_info(self, url: str) -> Tuple[str, List[dict]]:
        """Extract playlist info and video list."""
        ydl_opts = {
            **YDL_COMMON_OPTS,
            "quiet": True,
            "extract_flat": True,
        }

        if self.cookies_path and self.cookies_path.exists():
            ydl_opts["cookiefile"] = str(self.cookies_path)

        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
            playlist_title = result.get("title", "Unnamed_Playlist")

            videos = []
            for entry in result.get("entries", []):
                if entry:
                    videos.append(
                        {
                            "url": f"https://www.youtube.com/watch?v={entry['id']}",
                            "title": entry.get("title", "Unnamed"),
                        }
                    )

            return sanitize_filename(playlist_title), videos

    def download(self, urls: List[str], download_type: str) -> List[DownloadResult]:
        """
        Download multiple URLs.
        download_type: "video", "music", "both", or "thumbnails"
        """
        results = []
        self.output_dir.mkdir(parents=True, exist_ok=True)

        for url in urls:
            url = url.strip()
            if not url:
                continue

            self._log(f"Processing: {url}")

            if download_type == "thumbnails":
                if not is_channel(url):
                    self._log(f"Skipping non-channel URL: {url}")
                    results.append(
                        DownloadResult(
                            success=False,
                            url=url,
                            error="Not a channel URL. Use a YouTube channel URL for thumbnails.",
                            download_type="thumbnails",
                        )
                    )
                    continue

                result = self.thumbnail_downloader.download(url, self.output_dir)
                results.append(result)

            elif is_playlist(url):
                try:
                    playlist_title, videos = self._get_playlist_info(url)
                    self._log(f"Playlist: {playlist_title} ({len(videos)} videos)")

                    playlist_dir = self.output_dir / playlist_title

                    for i, video in enumerate(videos, 1):
                        self._log(f"[{i}/{len(videos)}] {video['title']}")
                        video_results = self._download_single(
                            video["url"], download_type, playlist_dir
                        )
                        results.extend(video_results)

                except Exception as e:
                    self._log(f"Playlist error: {e}")
                    results.append(
                        DownloadResult(
                            success=False,
                            url=url,
                            error=str(e),
                            download_type=download_type,
                        )
                    )
            else:
                video_results = self._download_single(
                    url, download_type, self.output_dir
                )
                results.extend(video_results)

        return results

    def _download_single(
        self, url: str, download_type: str, output_dir: Path
    ) -> List[DownloadResult]:
        """Download a single URL (video, music, or both)."""
        results = []

        if download_type in ("video", "both"):
            self._log("Downloading video...")
            result = self.video_downloader.download(url, output_dir)
            results.append(result)
            if result.success:
                self._log(f"Video saved: {result.title}")
            else:
                self._log(f"Video failed: {result.error}")

        if download_type in ("music", "both"):
            self._log("Downloading music...")
            result = self.music_downloader.download(url, output_dir)
            results.append(result)
            if result.success:
                self._log(f"Music saved: {result.title}")
            else:
                self._log(f"Music failed: {result.error}")

        return results


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def run_download(args):
    """Run download from CLI args."""
    # Check ffmpeg
    if not check_ffmpeg():
        print("ERROR: ffmpeg not found. Install with: brew install ffmpeg")
        sys.exit(1)

    # Handle browser cookies
    cookies_path = None
    if args.cookies_file:
        cookies_path = Path(args.cookies_file)
        if not cookies_path.exists():
            print(f"ERROR: Cookies file not found: {args.cookies_file}")
            sys.exit(1)
        print(f"Using cookies from: {args.cookies_file}")
    elif args.browser and args.browser.lower() != "none":
        print(f"Extracting cookies from {args.browser}...")
        cookies_path = CookieManager.extract_cookies(args.browser.lower())
        if cookies_path:
            print("Cookies extracted successfully")
        else:
            print("Could not extract cookies, continuing without")

    # Progress callback
    def progress_cb(percent: float, eta: str) -> None:
        print(f"\rProgress: {percent:.1f}%", end="", flush=True)

    # Log callback
    def log_cb(message: str) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    # Create download manager
    manager = DownloadManager(
        output_dir=OUTPUT_DIR,
        cookies_path=cookies_path,
        progress_callback=progress_cb,
        log_callback=log_cb,
        video_format=args.video_format,
        audio_format=args.audio_format,
    )

    # Start download
    print(f"\nDownloading {len(args.urls)} URL(s) as {args.type}...")
    results = manager.download(args.urls, args.type)

    # Print summary
    print("\n")
    success_count = sum(1 for r in results if r.success)
    fail_count = len(results) - success_count

    print(f"Complete: {success_count} succeeded, {fail_count} failed")
    print(f"Files saved to: {OUTPUT_DIR}")

    # Exit with error code if any downloads failed
    sys.exit(0 if fail_count == 0 else 1)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Yodle - YouTube Downloader",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download video as MP4
  uv run yodle 'https://youtube.com/watch?v=...'

  # Download music as MP3
  uv run yodle -t music 'https://youtube.com/watch?v=...'

  # Download both video (MKV) and music (M4A)
  uv run yodle -t both --video-format mkv --audio-format m4a 'URL'

  # Multiple URLs
  uv run yodle -t music 'URL1' 'URL2' 'URL3'

  # With browser cookies
  uv run yodle -b chrome 'https://youtube.com/watch?v=...'
        """,
    )

    parser.add_argument("urls", nargs="*", help="YouTube URL(s) to download")

    parser.add_argument(
        "-t",
        "--type",
        choices=["video", "music", "both", "thumbnails"],
        default="both",
        help="Download type (default: both)",
    )

    parser.add_argument(
        "--video-format",
        choices=["mp4", "mkv", "webm"],
        default="mp4",
        help="Video output format (default: mp4)",
    )

    parser.add_argument(
        "--audio-format",
        choices=["mp3", "m4a"],
        default="mp3",
        help="Audio output format (default: mp3)",
    )

    parser.add_argument(
        "-b",
        "--browser",
        choices=["none", "chrome", "firefox"],
        help="Extract cookies from browser for private videos",
    )

    parser.add_argument("--cookies-file", help="Path to custom cookies.txt file")

    args = parser.parse_args()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.urls:
        parser.print_help()
        sys.exit(0)

    run_download(args)


if __name__ == "__main__":
    main()
