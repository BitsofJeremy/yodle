import requests
from yt_dlp import YoutubeDL
from PIL import Image
import sys
import os
from pathlib import Path
import re

def setup_cookie_handling():
    """Setup cookie handling for authentication"""
    try:
        # Try to get cookies from browser
        cookie_file = Path("cookies.txt")
        if not cookie_file.exists():
            with YoutubeDL({'quiet': True}) as ydl:
                # Try Chrome first, then Firefox, then Safari
                browsers = ['chrome', 'firefox', 'safari']
                for browser in browsers:
                    try:
                        ydl.params = {'cookies_from_browser': browser}
                        ydl._download_cookies_from_browser()
                        print(f"Successfully extracted cookies from {browser}")
                        return str(cookie_file)
                    except Exception:
                        continue
                print("Could not extract cookies from any browser")
                return None
        return str(cookie_file)
    except Exception as e:
        print(f"Error setting up cookies: {e}")
        return None

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

def get_playlist_info(url, cookie_file=None):
    """Get playlist title and video URLs"""
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': False
    }
    
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

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

def create_directories(url, cookie_file=None):
    """Create appropriate directories for video or playlist"""
    ydl_opts = {'quiet': True}
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    with YoutubeDL(ydl_opts) as ydl:
        if is_playlist(url):
            playlist_title, videos = get_playlist_info(url, cookie_file)
            if playlist_title:
                playlist_dir = Path(playlist_title)
                playlist_dir.mkdir(exist_ok=True)
                return playlist_dir, playlist_title, videos
            return None, None, None
        else:
            info = ydl.extract_info(url, download=False)
            safe_title = sanitize_filename(info['title'])
            output_dir = Path(safe_title)
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

    if download_thumbnail(thumbnail_url, temp_jpg):
        try:
            with Image.open(temp_jpg) as img:
                img.save(png_path, 'PNG')
                print(f"Thumbnail saved as {png_path}")
            temp_jpg.unlink()
            return png_path
        except Exception as e:
            print(f"Error converting thumbnail to PNG: {e}")
            if temp_jpg.exists():
                temp_jpg.unlink()
    return None

def download_m4a(url, output_dir, base_name, cookie_file=None):
    """Download audio in M4A format with embedded thumbnail"""
    m4a_opts = {
        'format': 'bestaudio/best',
        'writethumbnail': True,
        'outtmpl': str(output_dir / f'{base_name}.%(ext)s'),
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

    if cookie_file:
        m4a_opts['cookiefile'] = cookie_file

    try:
        with YoutubeDL(m4a_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            print(f"M4A download completed")
            return info
    except Exception as e:
        print(f"Error downloading audio: {e}")
        return None

def process_video(url, output_dir, cookie_file=None):
    """Process a single video"""
    try:
        ydl_opts = {'quiet': True}
        if cookie_file:
            ydl_opts['cookiefile'] = cookie_file

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            base_name = sanitize_filename(info['title'])

            print(f"\nProcessing: {info['title']}")

            # Download M4A file
            info = download_m4a(url, output_dir, base_name, cookie_file)

            if info:
                # Save PNG thumbnail
                save_thumbnail_png(output_dir, info['thumbnail'], base_name)
                print(f"Processing completed for: {info['title']}")

    except Exception as e:
        print(f"Error processing video {url}: {e}")

def process_playlist(url, cookie_file=None):
    """Process an entire playlist"""
    playlist_dir, playlist_title, videos = create_directories(url, cookie_file)
    if not videos:
        print("Error: Could not process playlist")
        return

    print(f"\nProcessing playlist: {playlist_title}")
    print(f"Found {len(videos)} videos")

    for i, video in enumerate(videos, 1):
        print(f"\nProcessing video {i}/{len(videos)}")
        video_dir = playlist_dir / sanitize_filename(video['title'])
        video_dir.mkdir(exist_ok=True)
        process_video(video['url'], video_dir, cookie_file)

def main(urls):
    # Setup cookie handling first
    cookie_file = setup_cookie_handling()
    if cookie_file:
        print(f"Using cookies from: {cookie_file}")
    else:
        print("Warning: Proceeding without cookies - some videos may be inaccessible")

    for url in urls:
        try:
            if is_playlist(url):
                process_playlist(url, cookie_file)
            else:
                output_dir, _, _ = create_directories(url, cookie_file)
                if output_dir:
                    process_video(url, output_dir, cookie_file)

        except Exception as e:
            print(f"Error processing {url}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python script.py <URL1> [URL2] ...")
        sys.exit(1)

    main(sys.argv[1:])
