#!/usr/bin/env python3
"""
Standalone YouTube Music Downloader

A script to download YouTube videos and playlists as MP3 files with embedded thumbnails.
Based on the MCP server functionality but designed for direct command-line usage.

Usage:
    python download_music.py "https://youtube.com/watch?v=..."
    python download_music.py "https://youtube.com/playlist?list=..." --browser chrome
    python download_music.py url1 url2 url3 --browser firefox

Requirements:
    pip install yt-dlp mutagen pydub pillow
    ffmpeg must be installed on system path
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

# Import from existing modules
from music_dl_updated import (
    sanitize_filename, is_playlist, extract_browser_cookies,
    get_playlist_info, download_m4a, save_thumbnail_png
)

# ID3 tagging imports for thumbnail embedding
try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TCON
    from pydub import AudioSegment
    TAGGING_AVAILABLE = True
except ImportError as e:
    TAGGING_AVAILABLE = False
    print(f"Warning: ID3 tagging not available. Install mutagen and pydub for thumbnail embedding.")
    print(f"Missing: {e}")

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("music-downloader")


def get_downloads_dir() -> Path:
    """Get the user's Downloads directory"""
    home = Path.home()
    downloads_dir = home / "Downloads" / "YodleMusic"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return downloads_dir


def convert_to_mp3_with_thumbnail(input_file: Path, thumbnail_path: Path, video_info: dict) -> Optional[Path]:
    """
    Convert audio file to MP3 and embed thumbnail with ID3 tags.

    Args:
        input_file: Path to input audio file
        thumbnail_path: Path to thumbnail image
        video_info: Video metadata from yt-dlp

    Returns:
        Path to MP3 file with embedded thumbnail or None if failed
    """
    if not TAGGING_AVAILABLE:
        logger.warning("ID3 tagging not available. Returning original file.")
        return input_file

    try:
        # Convert to MP3 using pydub
        audio = AudioSegment.from_file(str(input_file))
        mp3_path = input_file.with_suffix('.mp3')

        # Export as MP3
        audio.export(str(mp3_path), format="mp3", bitrate="192k")
        logger.info(f"Converted to MP3: {mp3_path}")

        # Add ID3 tags with thumbnail
        audio_file = MP3(str(mp3_path), ID3=ID3)

        # Add ID3v2 tag if it doesn't exist
        try:
            audio_file.add_tags()
        except Exception:
            pass  # Tags already exist

        # Set metadata
        audio_file["TIT2"] = TIT2(encoding=3, text=video_info.get('title', 'Unknown Title'))
        audio_file["TPE1"] = TPE1(encoding=3, text=video_info.get('uploader', 'Unknown Artist'))
        audio_file["TALB"] = TALB(encoding=3, text=video_info.get('uploader', 'YouTube'))
        audio_file["TDRC"] = TDRC(encoding=3, text=str(video_info.get('upload_date', '2024')[:4]))
        audio_file["TCON"] = TCON(encoding=3, text="Music")

        # Add thumbnail as album art
        if thumbnail_path.exists():
            with open(thumbnail_path, 'rb') as thumbnail_file:
                # Determine MIME type based on file extension
                mime_type = 'image/jpeg' if thumbnail_path.suffix.lower() in ['.jpg', '.jpeg'] else 'image/png'

                audio_file["APIC"] = APIC(
                    encoding=3,
                    mime=mime_type,
                    type=3,  # Cover (front)
                    desc='Cover',
                    data=thumbnail_file.read()
                )

        # Save the changes
        audio_file.save()
        logger.info(f"Added ID3 tags and thumbnail to: {mp3_path}")

        # Remove original file if different from MP3
        if input_file != mp3_path:
            input_file.unlink()

        return mp3_path

    except Exception as e:
        logger.error(f"Failed to convert to MP3 with thumbnail: {e}")
        return input_file


def download_video(url: str, output_dir: Path, cookies_path: Optional[str] = None) -> dict:
    """Download a video as MP3 with embedded thumbnail"""
    try:
        from yt_dlp import YoutubeDL

        ydl_opts = {'quiet': True}
        if cookies_path and os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            base_name = sanitize_filename(info['title'])

            logger.info(f"Processing: {info['title']}")

            # Download M4A file
            download_info = download_m4a(url, output_dir, base_name, cookies_path)

            if download_info:
                # Save PNG thumbnail
                thumbnail_path = save_thumbnail_png(output_dir, download_info['thumbnail'], base_name)

                # Find the downloaded audio file
                audio_file = None
                for ext in ['.m4a', '.mp4', '.webm']:
                    potential_file = output_dir / f"{base_name}{ext}"
                    if potential_file.exists():
                        audio_file = potential_file
                        break

                if audio_file:
                    # Convert to MP3 with embedded thumbnail
                    thumbnail_file = output_dir / f"{base_name}.png"
                    if thumbnail_file.exists():
                        logger.info("Converting to MP3 and embedding thumbnail...")
                        mp3_file = convert_to_mp3_with_thumbnail(audio_file, thumbnail_file, download_info)
                        if mp3_file:
                            audio_file = mp3_file

                    return {
                        "success": True,
                        "title": download_info['title'],
                        "file_path": str(audio_file),
                        "format": "mp3",
                        "thumbnail_embedded": True
                    }

                return {
                    "success": False,
                    "error": "Audio file not found after download",
                    "title": download_info.get('title', 'Unknown')
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to download audio",
                    "title": info.get('title', 'Unknown')
                }

    except Exception as e:
        logger.error(f"Error processing video {url}: {e}")
        return {
            "success": False,
            "error": str(e),
            "url": url
        }


def download_playlist(url: str, cookies_path: Optional[str] = None) -> dict:
    """Download an entire playlist as MP3s with embedded thumbnails"""
    downloads_dir = get_downloads_dir()

    try:
        # Get playlist info
        playlist_title, videos = get_playlist_info(url, cookies_path)

        if not videos:
            return {
                "success": False,
                "error": "Could not process playlist"
            }

        playlist_dir = downloads_dir / sanitize_filename(playlist_title)
        playlist_dir.mkdir(exist_ok=True)

        logger.info(f"Processing playlist: {playlist_title}")
        logger.info(f"Found {len(videos)} videos")

        results = []
        for i, video in enumerate(videos, 1):
            logger.info(f"Processing video {i}/{len(videos)}")
            video_dir = playlist_dir / sanitize_filename(video['title'])
            video_dir.mkdir(exist_ok=True)

            result = download_video(video['url'], video_dir, cookies_path)
            result['video_number'] = i
            result['total_videos'] = len(videos)
            results.append(result)

        return {
            "success": True,
            "playlist_title": playlist_title,
            "total_videos": len(videos),
            "results": results
        }

    except Exception as e:
        logger.error(f"Error processing playlist {url}: {e}")
        return {
            "success": False,
            "error": str(e),
            "url": url
        }


def process_urls(urls: List[str], browser: Optional[str] = None) -> None:
    """Process a list of URLs"""
    # Extract cookies from browser if specified
    cookies_path = None
    if browser:
        cookies_path = extract_browser_cookies(browser)
        if cookies_path:
            logger.info(f"Using cookies from {browser}")

    downloads_dir = get_downloads_dir()
    all_results = []

    for url in urls:
        try:
            if is_playlist(url):
                result = download_playlist(url, cookies_path)
            else:
                # Create directory for single video
                from yt_dlp import YoutubeDL
                ydl_opts = {'quiet': True}
                if cookies_path and os.path.exists(cookies_path):
                    ydl_opts['cookiefile'] = cookies_path

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    safe_title = sanitize_filename(info['title'])
                    output_dir = downloads_dir / safe_title
                    output_dir.mkdir(exist_ok=True)

                    result = download_video(url, output_dir, cookies_path)

            all_results.append({
                "url": url,
                "result": result
            })

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            all_results.append({
                "url": url,
                "result": {
                    "success": False,
                    "error": str(e)
                }
            })

    # Print summary
    print("\n" + "=" * 60)
    print(f"DOWNLOAD SUMMARY (saved to {downloads_dir})")
    print("=" * 60)

    for item in all_results:
        url = item["url"]
        result = item["result"]

        if result["success"]:
            if "playlist_title" in result:
                # Playlist result
                print(f"✓ Playlist: {result['playlist_title']}")
                print(f"  Total videos: {result['total_videos']}")
                for video_result in result["results"]:
                    status = "✓" if video_result["success"] else "✗"
                    title = video_result.get("title", "Unknown")
                    print(f"  {status} {title}")
            else:
                # Single video result
                title = result.get("title", "Unknown")
                print(f"✓ {title}")
        else:
            error = result.get("error", "Unknown error")
            print(f"✗ Failed: {url} - {error}")

    print(f"\nFiles saved to: {downloads_dir}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Download YouTube videos and playlists as MP3 files with embedded thumbnails",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python download_music.py "https://youtube.com/watch?v=dQw4w9WgXcQ"
  python download_music.py "https://youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab" --browser chrome
  python download_music.py url1 url2 url3 --browser firefox
        """
    )

    parser.add_argument(
        "urls",
        nargs="+",
        help="YouTube URLs to download (videos or playlists)"
    )

    parser.add_argument(
        "--browser",
        choices=["chrome", "firefox"],
        help="Browser to extract cookies from (optional)"
    )

    args = parser.parse_args()

    try:
        process_urls(args.urls, args.browser)
    except KeyboardInterrupt:
        logger.info("Download interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()