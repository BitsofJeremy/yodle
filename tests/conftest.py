"""
Shared pytest fixtures and configuration for Yodle tests.

This module provides reusable fixtures for mocking external dependencies,
creating temporary files, and setting up test environments.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock


@pytest.fixture
def tmp_output_dir(tmp_path):
    """
    Temporary output directory for downloads.

    Returns:
        Path: Clean temporary directory for test outputs
    """
    output_dir = tmp_path / "yodle_output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def mock_yt_dlp_info():
    """
    Mock yt-dlp info dictionary with typical video metadata.

    Returns:
        dict: Simulated yt-dlp extract_info response
    """
    return {
        'title': 'Test Video',
        'id': 'abc123',
        'uploader': 'Test Channel',
        'upload_date': '20240101',
        'ext': 'mp4',
        'thumbnail': 'https://example.com/thumb.jpg',
        'duration': 120,
        'description': 'Test video description'
    }


@pytest.fixture
def mock_youtube_cookie():
    """
    Mock browser cookie object for YouTube.

    Returns:
        Mock: Simulated browser cookie with YouTube domain
    """
    cookie = Mock()
    cookie.domain = ".youtube.com"
    cookie.path = "/"
    cookie.secure = True
    cookie.expires = 1234567890
    cookie.name = "CONSENT"
    cookie.value = "YES+1"
    return cookie


@pytest.fixture
def mock_progress_callback():
    """
    Mock progress callback function for download tracking.

    Returns:
        Mock: Callable mock for testing progress updates
    """
    return Mock()


@pytest.fixture
def mock_log_callback():
    """
    Mock log callback function for download logging.

    Returns:
        Mock: Callable mock for testing log messages
    """
    return Mock()


@pytest.fixture
def sample_m4a_file(tmp_path):
    """
    Minimal M4A file for conversion tests.

    Note: This is fake data, not a real audio file.
    For real conversion tests, use a proper M4A file.

    Returns:
        Path: Path to fake M4A file
    """
    m4a_path = tmp_path / "sample.m4a"
    m4a_path.write_bytes(b"fake m4a audio data")
    return m4a_path


@pytest.fixture
def sample_thumbnail(tmp_path):
    """
    Small PNG thumbnail for resize tests.

    Returns:
        Path: Path to 1920x1080 red test image
    """
    from PIL import Image

    thumb_path = tmp_path / "thumb.png"
    img = Image.new('RGB', (1920, 1080), color='red')
    img.save(thumb_path)
    return thumb_path


@pytest.fixture
def mock_ffmpeg_available(mocker):
    """
    Mock ffmpeg as available on system.

    Returns:
        Mock: Mocked check_ffmpeg function returning True
    """
    return mocker.patch("yodle.check_ffmpeg", return_value=True)


@pytest.fixture
def mock_playlist_response():
    """
    Mock yt-dlp playlist response.

    Returns:
        dict: Simulated playlist extraction with multiple videos
    """
    return {
        'title': 'Test Playlist',
        'id': 'PLtest123',
        'entries': [
            {
                'id': 'video1',
                'title': 'First Video',
                'url': 'https://youtube.com/watch?v=video1'
            },
            {
                'id': 'video2',
                'title': 'Second Video',
                'url': 'https://youtube.com/watch?v=video2'
            },
            None,  # Simulates deleted video
            {
                'id': 'video3',
                'title': 'Third Video',
                'url': 'https://youtube.com/watch?v=video3'
            }
        ]
    }


@pytest.fixture
def mock_channel_response():
    """
    Mock yt-dlp channel response for thumbnail downloads.

    Returns:
        dict: Simulated channel extraction with video entries
    """
    return {
        'uploader': 'Test Channel',
        'channel_id': 'UCtest123',
        'entries': [
            {
                'id': 'vid1',
                'title': 'Video 1',
                'thumbnail': 'https://i.ytimg.com/vi/vid1/maxresdefault.jpg',
                'live_status': None
            },
            {
                'id': 'vid2',
                'title': 'Video 2',
                'thumbnail': 'https://i.ytimg.com/vi/vid2/maxresdefault.jpg',
                'live_status': None
            },
            {
                'id': 'vid3',
                'title': 'Upcoming Stream',
                'thumbnail': 'https://i.ytimg.com/vi/vid3/maxresdefault.jpg',
                'live_status': 'is_upcoming'  # Should be filtered out
            }
        ]
    }


# Pytest markers
def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "gui: marks tests that require display server"
    )
