import requests
from yt_dlp import YoutubeDL
from PIL import Image
import sys
import os
from pathlib import Path
import re
import json
import browsercookie
import subprocess
from typing import Optional

def sanitize_filename(title):
    """Convert title to safe filename with underscores"""
    clean_title = ' '.join(title.split())
    clean_title = re.sub(r'[^\w\s-]', '', clean_title)
    clean_title = clean_title.replace(' ', '_')
    clean_title = re.sub(r'_+', '_', clean_title)
    clean_title = clean_title.strip('_')
    return clean_title

def is_playlist(url):
    """Check if the URL is a playlist"""
    return 'playlist' in url or 'list=' in url

def get_cookies_path():
    """Get or create the path for the cookies file"""
    home_dir = Path.home()
    config_dir = home_dir / '.config' / 'yt-dlp'
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / 'cookies.txt'

def extract_browser_cookies(browser='chrome'):
    """Extract cookies from browser and save to netscape format for yt-dlp"""
    cookies_path = get_cookies_path()

    try:
        if browser.lower() == 'chrome':
            cj = browsercookie.chrome()
        elif browser.lower() == 'firefox':
            cj = browsercookie.firefox()
        else:
            print(f"Unsupported browser: {browser}")
            return None

        # Convert to Netscape format
        with open(cookies_path, 'w') as f:
            f.write("# Netscape HTTP Cookie File\n")
            for cookie in cj:
                if cookie.domain.endswith(('.youtube.com', '.google.com')):
                    secure = "TRUE" if cookie.secure else "FALSE"
                    http_only = "TRUE" if cookie.has_nonstandard_attr('HttpOnly') else "FALSE"
                    f.write(f"{cookie.domain}\t{'TRUE' if cookie.domain.startswith('.') else 'FALSE'}\t{cookie.path}\t"
                           f"{secure}\t{int(cookie.expires) if cookie.expires else 0}\t{cookie.name}\t{cookie.value}\n")

        print(f"Cookies extracted from {browser} and saved to {cookies_path}")
        return cookies_path
    except Exception as e:
        print(f"Error extracting cookies from {browser}: {e}")
        return None

def get_playlist_info(url, cookies_path=None):
    """Get playlist title and video URLs"""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android']
            }
        }
    }

    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    with YoutubeDL(ydl_opts) as ydl:
        try:
            result = ydl.extract_info(url, download=False)
            playlist_title = result.get('title', 'Unnamed_Playlist')
            videos = []

            entries = result.get('entries', [])
            for entry in entries:
                if entry:
                    video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                    video_title = entry.get('title', 'Unnamed_Video')
                    videos.append({'url': video_url, 'title': video_title})

            return sanitize_filename(playlist_title), videos

        except Exception as e:
            print(f"Error extracting playlist info: {e}")
            return None, None

def get_downloads_directory():
    """Get the Downloads directory with YodleMusic subfolder"""
    home_dir = Path.home()
    downloads_dir = home_dir / "Downloads" / "YodleMusic"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return downloads_dir

def create_directories(url, cookies_path=None):
    """Create appropriate directories for video or playlist"""
    downloads_dir = get_downloads_directory()
    ydl_opts = {
        'quiet': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android']
            }
        }
    }
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    with YoutubeDL(ydl_opts) as ydl:
        if is_playlist(url):
            playlist_title, videos = get_playlist_info(url, cookies_path)
            if playlist_title:
                playlist_dir = downloads_dir / sanitize_filename(playlist_title)
                playlist_dir.mkdir(exist_ok=True)
                return playlist_dir, playlist_title, videos
            return None, None, None
        else:
            info = ydl.extract_info(url, download=False)
            safe_title = sanitize_filename(info['title'])
            output_dir = downloads_dir / safe_title
            output_dir.mkdir(exist_ok=True)
            return output_dir, info['title'], None

def download_thumbnail(url, save_path):
    """Download thumbnail from URL"""
    try:
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(save_path, 'wb') as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
            return save_path
    except Exception as e:
        print(f"Error downloading thumbnail: {e}")
    return None

def save_thumbnail_png(output_dir, thumbnail_url, base_name):
    """Save thumbnail in PNG format"""
    temp_jpg = output_dir / "temp.jpg"
    png_path = output_dir / f"{base_name}.png"

    # Download jpg temporarily and convert to PNG
    if download_thumbnail(thumbnail_url, temp_jpg):
        try:
            with Image.open(temp_jpg) as img:
                img.save(png_path, 'PNG')
                print(f"Thumbnail saved as {png_path}")
            # Clean up temporary jpg
            temp_jpg.unlink()
            return png_path
        except Exception as e:
            print(f"Error converting thumbnail to PNG: {e}")
            if temp_jpg.exists():
                temp_jpg.unlink()
    return None


def download_m4a(url, output_dir, base_name, cookies_path=None):
    """Download audio in M4A format with embedded thumbnail"""
    m4a_opts = {
        'format': 'bestaudio/best',
        'writethumbnail': True,
        'outtmpl': str(output_dir / f'{base_name}.%(ext)s'),
        'extractor_args': {
            'youtube': {
                'player_client': ['android']  # Use Android client to avoid 403 errors
            }
        },
        'postprocessors': [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'},
            {'key': 'EmbedThumbnail'},
            {'key': 'FFmpegMetadata'},
            {'key': 'FFmpegEmbedSubtitle'},
        ],
        'postprocessor_args': [
            '-c:a', 'aac',
            '-metadata:s:v', 'title="Album Cover"',
            '-metadata:s:v', 'comment="Cover (Front)"'
        ]
    }

    if cookies_path and os.path.exists(cookies_path):
        m4a_opts['cookiefile'] = cookies_path

    try:
        with YoutubeDL(m4a_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            print(f"M4A download completed")
            return info
    except Exception as e:
        print(f"Error downloading audio: {e}")
        return None

def process_video(url, output_dir, cookies_path=None):
    """Process a single video"""
    try:
        ydl_opts = {
            'quiet': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android']
                }
            }
        }
        if cookies_path and os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            base_name = sanitize_filename(info['title'])

            print(f"\nProcessing: {info['title']}")

            # Download M4A file
            info = download_m4a(url, output_dir, base_name, cookies_path)

            if info:
                # Save PNG thumbnail
                save_thumbnail_png(output_dir, info['thumbnail'], base_name)

                print(f"Processing completed for: {info['title']}")

    except Exception as e:
        print(f"Error processing video {url}: {e}")

def process_playlist(url, cookies_path=None):
    """Process an entire playlist"""
    playlist_dir, playlist_title, videos = create_directories(url, cookies_path)
    if not videos:
        print("Error: Could not process playlist")
        return

    print(f"\nProcessing playlist: {playlist_title}")
    print(f"Found {len(videos)} videos")

    for i, video in enumerate(videos, 1):
        print(f"\nProcessing video {i}/{len(videos)}")
        video_dir = playlist_dir / sanitize_filename(video['title'])
        video_dir.mkdir(exist_ok=True)
        process_video(video['url'], video_dir, cookies_path)

def main(urls, browser=None):
    cookies_path = None

    # Extract cookies from browser if specified
    if browser:
        cookies_path = extract_browser_cookies(browser)

    for url in urls:
        try:
            if is_playlist(url):
                process_playlist(url, cookies_path)
            else:
                output_dir, _, _ = create_directories(url, cookies_path)
                if output_dir:
                    process_video(url, output_dir, cookies_path)

        except Exception as e:
            print(f"Error processing {url}: {e}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download YouTube videos or playlists with browser cookies")
    parser.add_argument("urls", nargs="+", help="URLs to download")
    parser.add_argument("--browser", choices=["chrome", "firefox"], help="Browser to extract cookies from")
    parser.add_argument("--cookies", help="Path to cookies file (Netscape format)")

    args = parser.parse_args()

    cookies_path = args.cookies

    # Extract cookies from browser if specified
    if args.browser and not cookies_path:
        cookies_path = extract_browser_cookies(args.browser)

    for url in args.urls:
        try:
            if is_playlist(url):
                process_playlist(url, cookies_path)
            else:
                output_dir, _, _ = create_directories(url, cookies_path)
                if output_dir:
                    process_video(url, output_dir, cookies_path)

        except Exception as e:
            print(f"Error processing {url}: {e}")
