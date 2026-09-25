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

import argparse
import asyncio
import functools
import json
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
from dotenv import load_dotenv
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TCON
from PIL import Image
from pydub import AudioSegment
import requests
import yt_dlp
from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func

# Load environment variables from .env file (e.g., YODLE_OUTPUT_DIR)
load_dotenv()

# =============================================================================
# CONSTANTS & CONFIGURATION
# =============================================================================

VERSION = "1.0.0"
OUTPUT_DIR = Path(os.environ.get("YODLE_OUTPUT_DIR", Path.home() / "Yodle"))
COOKIES_PATH = Path.home() / ".config" / "yt-dlp" / "cookies.txt"

# Common yt-dlp options applied to all extractors.
# remote_components downloads the EJS challenge solver script at runtime,
# which Deno needs to crack YouTube's JS signature/n challenges.
# player_client is deliberately NOT pinned: yt-dlp 2026.08.19 removed
# android_vr from its defaults (its HTTPS formats now need a GVS PO token
# and 403 without one — yt-dlp/yt-dlp#17456) and now defaults to
# visionos+web, which serves the full DASH audio set (opus 251). Pinning
# here degraded music to itag 18 and re-introduced the 403s.
YDL_COMMON_OPTS = {
    "remote_components": ["ejs:github"],
}

# EBU R128 loudness targets for --normalize (ffmpeg loudnorm)
LOUDNORM_I = "-14"    # target integrated loudness (LUFS; streaming standard)
LOUDNORM_TP = "-1.5"  # true-peak ceiling (dBTP)
LOUDNORM_LRA = "11"   # target loudness range (LU)

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


_DURATION_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}
_DURATION_ERROR = (
    "invalid --limit value {value!r}: expected DURATION as seconds (90, 90s), "
    "minutes (59m), hours (2h), or H:MM:SS (1:30:00); must be positive"
)


def parse_duration(value: str) -> int:
    """Parse a --limit duration string into positive seconds.

    Accepted forms: plain seconds ("90"), unit suffix ("90s", "59m", "2h"),
    or zero-padded clock form ("1:30:00"). Raises argparse.ArgumentTypeError
    on anything else.
    """
    value = value.strip().lower()
    seconds: Optional[int] = None

    match = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)", value)
    if match:
        hours, minutes, secs = (int(part) for part in match.groups())
        seconds = hours * 3600 + minutes * 60 + secs
    else:
        match = re.fullmatch(r"(\d+)([smh]?)", value)
        if match:
            seconds = int(match.group(1)) * _DURATION_UNITS[match.group(2)]

    if not seconds:
        # Covers None (no grammar match), 0, and "0s"/"0m"/"0h"
        raise argparse.ArgumentTypeError(_DURATION_ERROR.format(value=value))
    return seconds


_AUDIO_QUALITY_ERROR = (
    "invalid --audio-quality value {value!r}: expected an integer — "
    "0-10 for VBR quality (0 = best, 10 = worst), or 11-320 for "
    "bitrate in kbps (e.g. 192, 320)"
)


def parse_audio_quality(value: str) -> int:
    """Parse --audio-quality into yt-dlp FFmpegExtractAudio 'preferredquality'.

    0-10 selects VBR quality (0 = best: mp3 V0 / aac -q:a 4);
    11-320 selects a target bitrate in kbps. Raises
    argparse.ArgumentTypeError on anything else.
    """
    value = value.strip()
    if not re.fullmatch(r"\d{1,3}", value) or int(value) > 320:
        raise argparse.ArgumentTypeError(
            _AUDIO_QUALITY_ERROR.format(value=value)
        )
    return int(value)


def _apply_limit_opts(
    opts: dict,
    limit_seconds: Optional[int],
    *,
    force_keyframes: bool = True,
) -> dict:
    """Add yt-dlp download-range opts so only the first N seconds is fetched.

    force_keyframes=True requests a re-encode at the cut for frame-accurate
    VIDEO cuts. Music passes force_keyframes=False: audio has no keyframes,
    and forcing them makes yt-dlp's ranged FFmpeg download omit '-c copy',
    re-encoding the audio during download AND again in FFmpegExtractAudio
    (a double lossy transcode).
    """
    if limit_seconds is not None:
        opts["download_ranges"] = download_range_func(None, [(0, limit_seconds)])
        if force_keyframes:
            opts["force_keyframes_at_cuts"] = True
    return opts


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
        limit_seconds: Optional[int] = None,
    ):
        self.cookies_path = cookies_path
        self.progress_callback = progress_callback
        self.output_format = output_format.lower()
        self.limit_seconds = limit_seconds

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

        return _apply_limit_opts(opts, self.limit_seconds)

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

    FORMAT_STRING = "bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio/best"

    def __init__(
        self,
        cookies_path: Optional[Path] = None,
        progress_callback: Optional[Callable] = None,
        output_format: str = "mp3",
        limit_seconds: Optional[int] = None,
        audio_quality: int = 0,
        normalize: bool = False,
    ):
        self.cookies_path = cookies_path
        self.progress_callback = progress_callback
        self.output_format = output_format.lower()
        self.limit_seconds = limit_seconds
        self.audio_quality = audio_quality
        self.normalize = normalize

    def _get_opts(self, output_dir: Path) -> dict:
        """Get yt-dlp options for music download."""
        opts = {
            **YDL_COMMON_OPTS,
            "format": self.FORMAT_STRING,
            "writethumbnail": True,
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "retries": 3,
        }

        quality = str(self.audio_quality)
        if self.output_format == "mp3":
            # Extract directly to MP3 using FFmpeg
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": quality},
                {"key": "EmbedThumbnail"},
                {"key": "FFmpegMetadata"},
            ]
        else:
            # Keep as M4A with embedded thumbnail.
            # FFmpegMetadata must run BEFORE EmbedThumbnail: its m4a output
            # args include '-vn', which drops the cover that EmbedThumbnail
            # writes (mutagen 'covr'). Metadata first, cover last = survives.
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a",
                 "preferredquality": quality},
                {"key": "FFmpegMetadata"},
                {"key": "EmbedThumbnail"},
            ]
            # Scope cover-art metadata to EmbedThumbnail's ffmpeg invocation only.
            # List-form postprocessor_args are appended to EVERY ffmpeg PP's output
            # args; the old "-c:a aac" landed after FFmpegMetadata's "-acodec copy"
            # (forcing a second AAC encode) and after ExtractAudio's lossless copy
            # path. Key "embedthumbnail+ffmpeg" matches only FFmpegEmbedThumbnailPP
            # runs via ffmpeg (yt-dlp builds root_key = f"{pp_key}+{exe}").
            opts["postprocessor_args"] = {
                "embedthumbnail+ffmpeg": [
                    "-metadata:s:v", "title=Album Cover",
                    "-metadata:s:v", "comment=Cover (Front)",
                ],
            }

        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)

        if self.progress_callback:
            opts["progress_hooks"] = [self._progress_hook]

        return _apply_limit_opts(
            opts, self.limit_seconds, force_keyframes=False
        )

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

    def _quality_encode_args(self) -> List[str]:
        """Encoder args for the normalization re-encode, mirroring yt-dlp's
        FFmpegExtractAudioPP._quality_args scaling: mp3 VBR 0=V0 best;
        aac VBR 0 -> -q:a 4 (best); values >10 are bitrates for both."""
        q = self.audio_quality
        if q > 10:
            return ["-b:a", f"{q}k"]
        if self.output_format == "mp3":
            return ["-c:a", "libmp3lame", "-q:a", f"{q}"]
        return ["-c:a", "aac", "-q:a", f"{4 - 0.39 * q:.2f}"]  # 4=best, 0.1=worst

    def _normalize_loudness(self, audio_path: Path) -> bool:
        """Two-pass EBU R128 loudness normalization to -14 LUFS, in place.

        Pass 1 measures with loudnorm print_format=json; pass 2 applies the
        measured values in linear mode (static gain — no pumping on music).
        On any failure the original file is kept and False is returned.
        """
        measure_cmd = [
            "ffmpeg", "-hide_banner", "-nostats",
            "-i", str(audio_path),
            "-map", "0:a:0",
            "-af", (f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}"
                    f":LRA={LOUDNORM_LRA}:print_format=json"),
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(measure_cmd, capture_output=True, text=True)
            blocks = re.findall(r"\{.*?\}", proc.stderr or "", re.DOTALL)
            if proc.returncode != 0 or not blocks:
                raise RuntimeError("no loudnorm measurement data")
            m = json.loads(blocks[-1])
            measured = (
                f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                f":measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}"
                f":offset={m['target_offset']}"
            )
        except (OSError, RuntimeError, ValueError, KeyError) as e:
            logger.warning(
                f"Loudness measurement failed ({e}); keeping original: {audio_path.name}"
            )
            return False

        tmp_path = audio_path.with_name(f"{audio_path.stem}.norm{audio_path.suffix}")
        apply_cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", str(audio_path),
            "-map", "0:a:0", "-map", "0:v?", "-c:v", "copy",  # keep embedded cover art
            "-af", (f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
                    f"{measured}:linear=true"),
            *self._quality_encode_args(),
            str(tmp_path),
        ]
        try:
            proc = subprocess.run(apply_cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not tmp_path.exists():
                raise RuntimeError(
                    (proc.stderr or "").strip().splitlines()[-1]
                    if proc.stderr else "no output produced"
                )
            os.replace(tmp_path, audio_path)
            logger.info(f"Loudness normalized to {LOUDNORM_I} LUFS: {audio_path.name}")
            return True
        except (OSError, RuntimeError) as e:
            logger.warning(
                f"Loudness normalization failed ({e}); keeping original: {audio_path.name}"
            )
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

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
                    if self.normalize:
                        # Failure keeps the original file; tags go on after
                        self._normalize_loudness(audio_path)
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
        limit_seconds: Optional[int] = None,
        audio_quality: int = 0,
        normalize: bool = False,
    ):
        self.output_dir = output_dir
        self.cookies_path = cookies_path
        self.progress_callback = progress_callback
        self.log_callback = log_callback

        self.video_downloader = VideoDownloader(
            cookies_path, progress_callback, video_format,
            limit_seconds=limit_seconds,
        )
        self.music_downloader = MusicDownloader(
            cookies_path, progress_callback, audio_format,
            limit_seconds=limit_seconds,
            audio_quality=audio_quality,
            normalize=normalize,
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
        limit_seconds=args.limit,
        audio_quality=args.audio_quality,
        normalize=args.normalize,
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

  # Download only the first 90 seconds
  uv run yodle --limit 90s 'https://youtube.com/watch?v=...'

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
        "--audio-quality",
        type=parse_audio_quality,
        default=0,
        metavar="QUALITY",
        help=(
            "Music encoder quality: 0-10 = VBR quality (0 = best), "
            "11-320 = bitrate in kbps (e.g. 320). Default: 0. "
            "No-op with -t video/thumbnails."
        ),
    )

    parser.add_argument(
        "--normalize",
        action="store_true",
        help=(
            "Loudness-normalize music downloads to -14 LUFS (EBU R128, two-pass "
            "ffmpeg loudnorm; adds one extra encode pass). "
            "Default: off. No-op with -t video/thumbnails."
        ),
    )

    parser.add_argument(
        "--limit",
        type=parse_duration,
        default=None,
        metavar="DURATION",
        help=(
            "Download at most DURATION per video (90, 90s, 59m, 2h, or 1:30:00). "
            "Default: full download. No-op with -t thumbnails."
        ),
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
