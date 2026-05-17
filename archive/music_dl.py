#!/bin/env python
# Requires: yt_dlp module
# Requires: ffmpeg
# Usage:
#
# python music_dl.py <URL>, ...
# 
# Example:
# 
# For ZSH on MacOS you need the quotes around the URL!
#
# python music_dl.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

import json
import sys
import os
import argparse
from pathlib import Path
import browsercookie
from yt_dlp import YoutubeDL

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
                # Filter for relevant domains if needed, yt-dlp handles this
                secure = "TRUE" if cookie.secure else "FALSE"
                # HttpOnly attribute might not be standard, check carefully
                # http_only = "TRUE" if cookie.has_nonstandard_attr('HttpOnly') else "FALSE"
                f.write(f"{cookie.domain}\t{'TRUE' if cookie.domain.startswith('.') else 'FALSE'}\t{cookie.path}\t"
                       f"{secure}\t{int(cookie.expires) if cookie.expires else 0}\t{cookie.name}\t{cookie.value}\n")

        print(f"Cookies extracted from {browser} and saved to {cookies_path}")
        return str(cookies_path)
    except Exception as e:
        print(f"Error extracting cookies from {browser}: {e}")
        # Attempt to delete potentially corrupt cookie file
        if cookies_path.exists():
            try:
                cookies_path.unlink()
                print(f"Removed potentially corrupt cookie file: {cookies_path}")
            except OSError as oe:
                print(f"Error removing cookie file: {oe}")
        return None


ydl_opts = {
    'format': 'm4a/bestaudio/best',
    'writethumbnail': True,
    'postprocessors': [
        {
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
        },
        {
            'key': 'EmbedThumbnail',
        },
        {
            'key': 'FFmpegMetadata',
        },
    ],
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download YouTube audio (M4A) with browser cookies")
    parser.add_argument("urls", nargs="+", help="URLs to download")
    parser.add_argument("--browser", choices=["chrome", "firefox"], help="Browser to extract cookies from")
    parser.add_argument("--cookies", help="Path to cookies file (Netscape format)")

    args = parser.parse_args()

    cookies_path = args.cookies

    # Extract cookies from browser if specified and no explicit path given
    if args.browser and not cookies_path:
        cookies_path = extract_browser_cookies(args.browser)

    # Add cookie file to options if available
    if cookies_path and os.path.exists(cookies_path):
        print(f"Using cookies from: {cookies_path}")
        ydl_opts['cookiefile'] = cookies_path
    elif args.browser or args.cookies:
        print("Warning: Specified cookie source not found or failed to extract. Proceeding without cookies.")
    else:
        print("No cookies specified. Proceeding without cookies.")


    with YoutubeDL(ydl_opts) as ydl:
        ydl.download(args.urls)
