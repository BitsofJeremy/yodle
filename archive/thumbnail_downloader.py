
import argparse
import asyncio
import os
import functools
from PIL import Image
import urllib.request
import yt_dlp

async def get_channel_info(channel_url):
    """Gets channel information using yt-dlp."""
    print("Fetching channel information...")
    loop = asyncio.get_running_loop()
    ydl_opts = {
        'quiet': True,
        'dump_single_json': True,
        'ignoreerrors': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # Run the synchronous extract_info in a separate thread
        info = await loop.run_in_executor(
            None, functools.partial(ydl.extract_info, channel_url, download=False)
        )
    print("Channel information fetched.")
    return info

def resize_image(img, max_width=512):
    """Resizes an image to a maximum width while maintaining aspect ratio."""
    width, height = img.size
    if width <= max_width:
        return img

    ratio = max_width / width
    new_height = int(height * ratio)
    return img.resize((max_width, new_height), Image.Resampling.LANCZOS)


async def download_and_convert_thumbnail(thumbnail_url, output_path, video_id, timeout=10):
    """Downloads a thumbnail, converts to PNG, and creates both original and resized versions."""
    try:
        # Create subdirectories for original and resized images
        original_dir = os.path.join(output_path, "original")
        resized_dir = os.path.join(output_path, "resized_512")
        os.makedirs(original_dir, exist_ok=True)
        os.makedirs(resized_dir, exist_ok=True)

        temp_image_path = os.path.join(output_path, f"{video_id}_temp.jpg")
        original_png_path = os.path.join(original_dir, f"{video_id}.png")
        resized_png_path = os.path.join(resized_dir, f"{video_id}.png")

        # Run the synchronous download in a separate thread with a timeout
        loop = asyncio.get_running_loop()
        await asyncio.wait_for(
            loop.run_in_executor(
                None, functools.partial(urllib.request.urlretrieve, thumbnail_url, temp_image_path)
            ),
            timeout=timeout
        )

        with Image.open(temp_image_path) as img:
            # Save original high-resolution PNG
            img.save(original_png_path, 'PNG')

            # Create and save resized version (max 512px width)
            resized_img = resize_image(img, max_width=512)
            resized_img.save(resized_png_path, 'PNG')

        os.remove(temp_image_path)
        print(f"Successfully downloaded and converted thumbnail for {video_id} (original + resized)")

    except asyncio.TimeoutError:
        print(f"Timeout error downloading thumbnail for {video_id}")
    except Exception as e:
        print(f"Error downloading/converting thumbnail for {video_id}: {e}")


async def main(channel_url):
    """Main function to download and convert thumbnails."""
    channel_info = await get_channel_info(channel_url)
    channel_name = channel_info.get('uploader', 'unknown_channel')
    output_dir = channel_name.replace(" ", "_")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Downloading thumbnails for channel: {channel_name}")
    print(f"Output directory: {output_dir}")

    entries = channel_info.get('entries', [])
    print(f"Found {len(entries)} videos.")

    tasks = []
    for entry in entries:
        if not entry:
            continue
        if entry.get('live_status') == 'is_upcoming':
            print(f"Skipping upcoming premiere: {entry.get('title')}")
            continue
        video_id = entry.get('id')
        thumbnail_url = entry.get('thumbnail')
        if video_id and thumbnail_url:
            tasks.append(download_and_convert_thumbnail(thumbnail_url, output_dir, video_id, timeout=10))

    if not tasks:
        print("No videos with thumbnails found.")
        return

    print(f"Starting download of {len(tasks)} thumbnails...")
    await asyncio.gather(*tasks)
    print("All thumbnails have been downloaded and converted.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download all thumbnails from a YouTube channel.")
    parser.add_argument("channel_url", help="The URL of the YouTube channel.")
    args = parser.parse_args()

    asyncio.run(main(args.channel_url))
