#!/usr/bin/env python3
"""
Yodle - Unified YouTube Downloader

A GUI and CLI application for downloading YouTube videos, music (MP3/M4A),
and channel thumbnails.

Features:
- Video downloads (MP4/MKV/WebM with best H.264/HEVC quality)
- Music downloads (MP3/M4A with embedded ID3 tags and album art)
- Channel thumbnail downloads (original + resized)
- Browser cookie extraction for private/age-restricted content
- Auto-update checking for yt-dlp
- GUI and CLI modes

Requirements:
- Python 3.11+
- ffmpeg (must be on system PATH)

Usage:
    # GUI mode
    uv run yodle

    # CLI mode
    uv run yodle 'https://youtube.com/watch?v=...'
    uv run yodle -t music --audio-format m4a 'URL'
"""

import asyncio
import functools
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
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

            # Try to embed thumbnail
            thumbnail_path = mp3_path.with_suffix(".png")
            if not thumbnail_path.exists():
                thumbnail_path = mp3_path.with_suffix(".jpg")

            if thumbnail_path.exists():
                with open(thumbnail_path, "rb") as thumb_file:
                    mime = (
                        "image/png" if thumbnail_path.suffix == ".png" else "image/jpeg"
                    )
                    audio["APIC"] = APIC(
                        encoding=3,
                        mime=mime,
                        type=3,
                        desc="Cover",
                        data=thumb_file.read(),
                    )

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

                # Download and save thumbnail as PNG
                thumbnail_url = info.get("thumbnail")
                if thumbnail_url:
                    self._save_thumbnail_png(output_dir, thumbnail_url, base_name)

                # Find the downloaded file (M4A or MP3)
                ext = self.output_format.lower()
                audio_path = output_dir / f"{base_name}.{ext}"
                if not audio_path.exists():
                    # Try original title
                    audio_path = output_dir / f"{title}.{ext}"

                if audio_path.exists():
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
# GUI APPLICATION
# =============================================================================


class YodleGUI:
    """Main application GUI using Tkinter."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Yodle - YouTube Downloader")
        self.root.geometry("600x550")
        self.root.resizable(True, True)

        # State
        self.is_downloading = False
        self.message_queue = queue.Queue()
        self.update_checker = UpdateChecker()

        # Variables
        self.type_var = tk.StringVar(value="both")
        self.browser_var = tk.StringVar(value="None")
        self.progress_var = tk.DoubleVar(value=0)
        self.video_format_var = tk.StringVar(value="mp4")
        self.audio_format_var = tk.StringVar(value="mp3")

        # Build GUI
        self._setup_gui()

        # Initialize format options state
        self._update_format_options()

        # Start message processing
        self.root.after(100, self._process_queue)

        # Check for updates in background
        self._check_updates_async()

    def _setup_gui(self) -> None:
        """Initialize all GUI components."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # URL Input
        self.url_label = ttk.Label(main_frame, text="URL(s) - one per line:")
        self.url_label.pack(anchor=tk.W, pady=(10, 2))

        url_frame = ttk.Frame(main_frame)
        url_frame.pack(fill=tk.X, pady=(0, 10))

        self.url_text = tk.Text(url_frame, height=5, font=("Courier", 11))
        self.url_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        url_scroll = ttk.Scrollbar(
            url_frame, orient=tk.VERTICAL, command=self.url_text.yview
        )
        url_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.url_text.config(yscrollcommand=url_scroll.set)

        # Download Type
        type_frame = ttk.LabelFrame(main_frame, text="Download Type", padding="5")
        type_frame.pack(fill=tk.X, pady=(0, 10))

        for text, value in [
            ("Video", "video"),
            ("Music", "music"),
            ("Both", "both"),
            ("Thumbnails", "thumbnails"),
        ]:
            rb = ttk.Radiobutton(
                type_frame,
                text=text,
                value=value,
                variable=self.type_var,
                command=self._update_format_options,
            )
            rb.pack(side=tk.LEFT, padx=10)

        # Format Selection
        format_frame = ttk.Frame(main_frame)
        format_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(format_frame, text="Video Format:").pack(side=tk.LEFT)
        self.video_format_combo = ttk.Combobox(
            format_frame,
            textvariable=self.video_format_var,
            values=["mp4", "mkv", "webm"],
            state="readonly",
            width=10,
        )
        self.video_format_combo.pack(side=tk.LEFT, padx=(10, 20))

        ttk.Label(format_frame, text="Audio Format:").pack(side=tk.LEFT)
        self.audio_format_combo = ttk.Combobox(
            format_frame,
            textvariable=self.audio_format_var,
            values=["mp3", "m4a"],
            state="readonly",
            width=10,
        )
        self.audio_format_combo.pack(side=tk.LEFT, padx=(10, 0))

        # Browser Cookies
        cookie_frame = ttk.Frame(main_frame)
        cookie_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(cookie_frame, text="Browser Cookies:").pack(side=tk.LEFT)

        self.browser_combo = ttk.Combobox(
            cookie_frame,
            textvariable=self.browser_var,
            values=["None", "Chrome", "Firefox", "Custom file..."],
            state="readonly",
            width=15,
        )
        self.browser_combo.pack(side=tk.LEFT, padx=(10, 0))
        self.browser_combo.bind("<<ComboboxSelected>>", self._on_browser_selected)

        # Store custom cookies path
        self.custom_cookies_path: Optional[Path] = None

        # Output Path
        output_frame = ttk.Frame(main_frame)
        output_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(output_frame, text="Output:").pack(side=tk.LEFT)
        ttk.Label(output_frame, text=str(OUTPUT_DIR), foreground="gray").pack(
            side=tk.LEFT, padx=(10, 0)
        )

        # Progress Bar
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_bar = ttk.Progressbar(
            progress_frame, variable=self.progress_var, maximum=100
        )
        self.progress_bar.pack(fill=tk.X, side=tk.LEFT, expand=True)

        self.progress_label = ttk.Label(progress_frame, text="0%", width=6)
        self.progress_label.pack(side=tk.RIGHT, padx=(10, 0))

        # Download Button
        self.download_btn = ttk.Button(
            main_frame, text="DOWNLOAD", command=self._start_download
        )
        self.download_btn.pack(fill=tk.X, pady=(0, 10), ipady=10)

        # Status Log
        log_label = ttk.Label(main_frame, text="Status Log:")
        log_label.pack(anchor=tk.W, pady=(10, 2))

        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(
            log_frame,
            height=10,
            state=tk.DISABLED,
            font=("Courier", 10),
            background="#f5f5f5",
            foreground="#000000",
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scroll = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self.log_text.yview
        )
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)

    def _check_updates_async(self) -> None:
        """Check for updates in background thread."""

        def check():
            result = self.update_checker.check_for_updates()
            self.root.after(0, self._handle_update_result, result)

        thread = threading.Thread(target=check, daemon=True)
        thread.start()

    def _handle_update_result(self, result: Tuple[bool, str, str]) -> None:
        """Handle update check result on main thread."""
        update_available, current, latest = result
        if update_available:
            cmd = self.update_checker.get_update_command()
            self._append_log("=" * 60)
            self._append_log(f"UPDATE AVAILABLE: yt-dlp {current} → {latest}")
            self._append_log(f"To update, run: {cmd}")
            self._append_log("=" * 60)

    def _on_browser_selected(self, event) -> None:
        """Handle browser selection change."""
        if self.browser_var.get() == "Custom file...":
            from tkinter import filedialog

            file_path = filedialog.askopenfilename(
                title="Select cookies.txt file",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                initialdir=str(Path.home()),
            )
            if file_path:
                self.custom_cookies_path = Path(file_path)
                self.browser_var.set(f"Custom: {Path(file_path).name}")
            else:
                # User cancelled, reset to None
                self.browser_var.set("None")
                self.custom_cookies_path = None

    def _update_format_options(self) -> None:
        """Update format selector visibility based on download type."""
        download_type = self.type_var.get()

        # Enable/disable format selectors based on download type
        if download_type == "video":
            self.video_format_combo.config(state="readonly")
            self.audio_format_combo.config(state="disabled")
        elif download_type == "music":
            self.video_format_combo.config(state="disabled")
            self.audio_format_combo.config(state="readonly")
        elif download_type == "both":
            self.video_format_combo.config(state="readonly")
            self.audio_format_combo.config(state="readonly")
        else:  # thumbnails
            self.video_format_combo.config(state="disabled")
            self.audio_format_combo.config(state="disabled")

    def _process_queue(self) -> None:
        """Process messages from worker thread."""
        try:
            while True:
                msg_type, data = self.message_queue.get_nowait()

                if msg_type == "progress":
                    percent, eta = data
                    self.progress_var.set(percent)
                    self.progress_label.config(text=f"{percent:.0f}%")

                elif msg_type == "log":
                    self._append_log(data)

                elif msg_type == "complete":
                    self._download_complete(data)

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_queue)

    def _append_log(self, message: str) -> None:
        """Append message to log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _start_download(self) -> None:
        """Start download in background thread."""
        if self.is_downloading:
            return

        # Get URLs
        urls_text = self.url_text.get("1.0", tk.END).strip()
        if not urls_text:
            messagebox.showwarning("No URLs", "Please enter at least one URL.")
            return

        urls = [u.strip() for u in urls_text.split("\n") if u.strip()]

        # Check ffmpeg
        if not check_ffmpeg():
            messagebox.showerror(
                "Missing Dependency",
                "ffmpeg is required but not found.\n\nInstall with: brew install ffmpeg",
            )
            return

        # Start download
        self.is_downloading = True
        self.download_btn.config(text="DOWNLOADING...", state=tk.DISABLED)
        self.progress_var.set(0)

        download_type = self.type_var.get()
        browser = self.browser_var.get()

        thread = threading.Thread(
            target=self._download_worker,
            args=(urls, download_type, browser),
            daemon=True,
        )
        thread.start()

    def _download_worker(
        self, urls: List[str], download_type: str, browser: str
    ) -> None:
        """Worker function running in background thread."""
        try:
            # Extract or use custom cookies if needed
            cookies_path = None
            if browser.startswith("Custom:"):
                # Use custom cookies file
                if self.custom_cookies_path and self.custom_cookies_path.exists():
                    cookies_path = self.custom_cookies_path
                    self.message_queue.put(
                        (
                            "log",
                            f"Using custom cookies: {self.custom_cookies_path.name}",
                        )
                    )
                else:
                    self.message_queue.put(
                        ("log", "Custom cookies file not found, continuing without")
                    )
            elif browser != "None":
                # Extract cookies from browser
                self.message_queue.put(("log", f"Extracting cookies from {browser}..."))
                cookies_path = CookieManager.extract_cookies(browser.lower())
                if cookies_path:
                    self.message_queue.put(("log", "Cookies extracted successfully"))
                else:
                    self.message_queue.put(
                        ("log", "Could not extract cookies, continuing without")
                    )

            # Progress callback
            def progress_cb(percent: float, eta: str) -> None:
                self.message_queue.put(("progress", (percent, eta)))

            # Log callback
            def log_cb(message: str) -> None:
                self.message_queue.put(("log", message))

            # Download
            manager = DownloadManager(
                output_dir=OUTPUT_DIR,
                cookies_path=cookies_path,
                progress_callback=progress_cb,
                log_callback=log_cb,
                video_format=self.video_format_var.get(),
                audio_format=self.audio_format_var.get(),
            )

            results = manager.download(urls, download_type)

            self.message_queue.put(("complete", results))

        except Exception as e:
            self.message_queue.put(("log", f"Error: {e}"))
            self.message_queue.put(("complete", []))

    def _download_complete(self, results: List[DownloadResult]) -> None:
        """Handle download completion."""
        self.is_downloading = False
        self.download_btn.config(text="DOWNLOAD", state=tk.NORMAL)
        self.progress_var.set(100)
        self.progress_label.config(text="100%")

        # Summary
        success_count = sum(1 for r in results if r.success)
        fail_count = len(results) - success_count

        self._append_log(f"Complete: {success_count} succeeded, {fail_count} failed")
        self._append_log(f"Files saved to: {OUTPUT_DIR}")

        if success_count > 0:
            messagebox.showinfo(
                "Download Complete",
                f"Downloaded {success_count} item(s) to:\n{OUTPUT_DIR}",
            )

    def run(self) -> None:
        """Start the main event loop."""
        self.root.mainloop()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def run_cli_download(args):
    """Run download in CLI mode without GUI."""
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
  # GUI mode (no arguments)
  uv run yodle

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

    # If URLs provided, run in CLI mode
    if args.urls:
        run_cli_download(args)
    else:
        # No URLs provided, run GUI mode
        # Check ffmpeg at startup
        if not check_ffmpeg():
            print("WARNING: ffmpeg not found. Install with: brew install ffmpeg")
            print("Some features may not work without ffmpeg.\n")

        # Run GUI
        app = YodleGUI()
        app.run()


if __name__ == "__main__":
    main()
