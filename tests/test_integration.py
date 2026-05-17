"""
Integration tests for yodle.py.

These tests verify component interactions and end-to-end workflows.
Most tests use mocked external dependencies to avoid network calls.

Run with: pytest tests/test_integration.py
Run slow tests: pytest tests/test_integration.py -m slow
"""

import pytest
from pathlib import Path
from unittest.mock import Mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from yodle import (
    CookieManager,
    VideoDownloader,
    MusicDownloader,
    DownloadManager,
    DownloadResult
)


class TestCookieIntegration:
    """Integration tests for cookie extraction and usage."""

    def test_cookie_extraction_and_download_integration(self, tmp_path, mocker, mock_youtube_cookie):
        """Test cookie extraction flows into downloader configuration."""
        # Setup cookie extraction
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.return_value = [mock_youtube_cookie]

        # Extract cookies
        extracted_path = CookieManager.extract_cookies("chrome")
        assert extracted_path == cookies_path
        assert cookies_path.exists()

        # Use cookies in downloader
        downloader = VideoDownloader(cookies_path=extracted_path)
        opts = downloader._get_opts(tmp_path)

        # Verify cookies are used
        assert opts['cookiefile'] == str(cookies_path)
        assert Path(opts['cookiefile']).exists()

    def test_cookie_cleanup_workflow(self, tmp_path, mocker, mock_youtube_cookie):
        """Test complete cookie lifecycle: extract -> use -> cleanup."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch("yodle.COOKIES_PATH", cookies_path)
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.return_value = [mock_youtube_cookie]

        # Extract
        CookieManager.extract_cookies("chrome")
        assert cookies_path.exists()

        # Use
        downloader = VideoDownloader(cookies_path=cookies_path)
        opts = downloader._get_opts(tmp_path)
        assert 'cookiefile' in opts

        # Cleanup
        CookieManager.cleanup()
        assert not cookies_path.exists()


class TestPlaylistIntegration:
    """Integration tests for playlist handling."""

    def test_playlist_detection_and_expansion(self, tmp_path, mocker, mock_playlist_response):
        """Test playlist URL detection and video expansion."""
        # Mock playlist detection
        mocker.patch("yodle.is_playlist", return_value=True)

        # Setup manager
        manager = DownloadManager(tmp_path)

        # Mock YoutubeDL for playlist info
        mock_ydl = Mock()
        mock_ydl.extract_info.return_value = mock_playlist_response
        mock_ydl.__enter__ = Mock(return_value=mock_ydl)
        mock_ydl.__exit__ = Mock(return_value=False)
        mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

        # Get playlist info
        title, videos = manager._get_playlist_info("https://youtube.com/playlist?list=PLtest")

        # Verify expansion
        assert title == "Test_Playlist"
        assert len(videos) == 3  # 3 valid entries (1 None filtered out)
        assert all('url' in v and 'title' in v for v in videos)

    def test_playlist_download_creates_subdirectory(self, tmp_path, mocker, mock_playlist_response):
        """Test playlist downloads go into subdirectory."""
        mocker.patch("yodle.is_playlist", return_value=True)

        manager = DownloadManager(tmp_path)

        # Mock playlist info
        mocker.patch.object(
            manager,
            '_get_playlist_info',
            return_value=("My_Playlist", [
                {'url': 'https://youtube.com/watch?v=1', 'title': 'Video 1'},
            ])
        )

        # Mock download
        download_calls = []
        def mock_download_single(url, dl_type, output_dir):
            download_calls.append(output_dir)
            return [DownloadResult(success=True, url=url, download_type=dl_type)]

        mocker.patch.object(manager, '_download_single', side_effect=mock_download_single)

        # Execute
        manager.download(["https://youtube.com/playlist?list=PLxxx"], "video")

        # Verify subdirectory was used
        assert len(download_calls) == 1
        assert "My_Playlist" in str(download_calls[0])


class TestMusicPipeline:
    """Integration tests for music download pipeline."""

    def test_music_download_pipeline_mocked(self, tmp_path, mocker, mock_yt_dlp_info):
        """Test complete music pipeline: download -> convert -> tag."""
        # Mock yt-dlp download
        mock_ydl = Mock()
        mock_ydl.extract_info.return_value = mock_yt_dlp_info
        mock_ydl.__enter__ = Mock(return_value=mock_ydl)
        mock_ydl.__exit__ = Mock(return_value=False)
        mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

        # Create fake M4A file
        m4a_path = tmp_path / "Test_Video.m4a"
        m4a_path.write_bytes(b"fake m4a audio data")

        # Mock audio conversion
        mock_audio = Mock()
        mocker.patch("yodle.AudioSegment.from_file", return_value=mock_audio)

        # Mock mutagen
        mocker.patch("yodle.MUTAGEN_AVAILABLE", True)
        mock_mp3 = Mock()
        mocker.patch("yodle.MP3", return_value=mock_mp3)

        # Execute download
        downloader = MusicDownloader()
        result = downloader.download("https://youtube.com/watch?v=abc123", tmp_path)

        # Verify pipeline executed
        assert result.success is True
        mock_audio.export.assert_called_once()  # Conversion happened
        mock_mp3.save.assert_called_once()      # Tags saved

    def test_music_download_without_mutagen(self, tmp_path, mocker, mock_yt_dlp_info):
        """Test music download works without mutagen (no ID3 tags)."""
        # Mock yt-dlp
        mock_ydl = Mock()
        mock_ydl.extract_info.return_value = mock_yt_dlp_info
        mock_ydl.__enter__ = Mock(return_value=mock_ydl)
        mock_ydl.__exit__ = Mock(return_value=False)
        mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

        # Create M4A file
        m4a_path = tmp_path / "Test_Video.m4a"
        m4a_path.write_bytes(b"fake m4a")

        # Mock conversion
        mock_audio = Mock()
        mocker.patch("yodle.AudioSegment.from_file", return_value=mock_audio)

        # Mutagen not available
        mocker.patch("yodle.MUTAGEN_AVAILABLE", False)

        # Execute
        downloader = MusicDownloader()
        result = downloader.download("https://youtube.com/watch?v=abc123", tmp_path)

        # Should still succeed without tagging
        assert result.success is True
        mock_audio.export.assert_called_once()


class TestDownloadManager:
    """Integration tests for DownloadManager orchestration."""

    def test_download_both_creates_two_files(self, tmp_path, mocker):
        """Test 'both' mode downloads video and music."""
        manager = DownloadManager(tmp_path)

        # Mock downloaders
        video_result = DownloadResult(
            success=True,
            url="https://youtube.com/watch?v=123",
            title="Test",
            download_type="video"
        )
        music_result = DownloadResult(
            success=True,
            url="https://youtube.com/watch?v=123",
            title="Test",
            download_type="music"
        )

        mocker.patch.object(manager.video_downloader, 'download', return_value=video_result)
        mocker.patch.object(manager.music_downloader, 'download', return_value=music_result)

        # Execute
        results = manager.download(["https://youtube.com/watch?v=123"], "both")

        # Verify both were downloaded
        assert len(results) == 2
        assert results[0].download_type == "video"
        assert results[1].download_type == "music"

    def test_download_skips_empty_urls(self, tmp_path):
        """Test empty URLs are skipped."""
        manager = DownloadManager(tmp_path)

        results = manager.download(["", "  ", "\n", "\t"], "video")

        assert len(results) == 0

    def test_download_processes_multiple_urls(self, tmp_path, mocker):
        """Test multiple URLs are processed sequentially."""
        manager = DownloadManager(tmp_path)

        # Mock video downloader
        def mock_download(url, output_dir):
            return DownloadResult(
                success=True,
                url=url,
                title=f"Video for {url}",
                download_type="video"
            )

        mocker.patch.object(manager.video_downloader, 'download', side_effect=mock_download)

        # Execute with multiple URLs
        urls = [
            "https://youtube.com/watch?v=1",
            "https://youtube.com/watch?v=2",
            "https://youtube.com/watch?v=3"
        ]
        results = manager.download(urls, "video")

        assert len(results) == 3
        assert all(r.success for r in results)

    def test_channel_url_for_thumbnails(self, tmp_path, mocker):
        """Test channel URL routes to thumbnail downloader."""
        manager = DownloadManager(tmp_path)

        # Mock thumbnail downloader
        thumb_result = DownloadResult(
            success=True,
            url="https://youtube.com/@channel",
            title="Channel thumbnails",
            download_type="thumbnails"
        )
        mocker.patch.object(manager.thumbnail_downloader, 'download', return_value=thumb_result)

        # Execute
        results = manager.download(["https://youtube.com/@channel"], "thumbnails")

        assert len(results) == 1
        assert results[0].download_type == "thumbnails"

    def test_non_channel_url_for_thumbnails_fails(self, tmp_path):
        """Test non-channel URL for thumbnails returns error."""
        manager = DownloadManager(tmp_path)

        results = manager.download(["https://youtube.com/watch?v=123"], "thumbnails")

        assert len(results) == 1
        assert results[0].success is False
        assert "Not a channel URL" in results[0].error

    def test_progress_callback_integration(self, tmp_path, mocker):
        """Test progress callbacks flow through to downloaders."""
        progress_calls = []

        def progress_callback(percent, eta):
            progress_calls.append((percent, eta))

        manager = DownloadManager(tmp_path, progress_callback=progress_callback)

        # Verify downloaders have callback
        assert manager.video_downloader.progress_callback is not None
        assert manager.music_downloader.progress_callback is not None

    def test_log_callback_integration(self, tmp_path, mocker):
        """Test log callbacks are used."""
        log_messages = []

        def log_callback(message):
            log_messages.append(message)

        manager = DownloadManager(tmp_path, log_callback=log_callback)

        # Mock downloader
        mocker.patch.object(
            manager.video_downloader,
            'download',
            return_value=DownloadResult(success=True, url="url", download_type="video")
        )

        # Execute
        manager.download(["https://youtube.com/watch?v=123"], "video")

        # Verify log was called
        assert len(log_messages) > 0
        assert any("Processing" in msg for msg in log_messages)


@pytest.mark.slow
@pytest.mark.integration
class TestRealDownload:
    """
    Real-world integration tests with actual downloads.

    These tests are marked as slow and should be run separately.
    They use Creative Commons videos to test actual download functionality.
    """

    @pytest.mark.skip(reason="Requires network and takes time - run manually")
    def test_real_video_download_smoke_test(self, tmp_path):
        """
        Smoke test with real Creative Commons video.

        Video: "Creative Commons - What is Creative Commons?"
        URL: https://www.youtube.com/watch?v=srVJW2FdKWU
        License: Creative Commons Attribution 3.0
        Duration: ~2 minutes
        """
        downloader = VideoDownloader()
        result = downloader.download(
            "https://www.youtube.com/watch?v=srVJW2FdKWU",
            tmp_path
        )

        # Verify download succeeded
        assert result.success is True
        assert result.title is not None
        assert len(result.title) > 0

        # Verify file was created
        downloaded_files = list(tmp_path.glob("*.mp4"))
        assert len(downloaded_files) > 0
        assert downloaded_files[0].stat().st_size > 0

    @pytest.mark.skip(reason="Requires network and takes time - run manually")
    def test_real_music_download_smoke_test(self, tmp_path):
        """
        Smoke test with real Creative Commons music.

        Note: Use a short Creative Commons music video for testing.
        """
        downloader = MusicDownloader()
        result = downloader.download(
            "https://www.youtube.com/watch?v=srVJW2FdKWU",  # Same CC video
            tmp_path
        )

        # Verify download succeeded
        assert result.success is True

        # Verify MP3 was created
        mp3_files = list(tmp_path.glob("*.mp3"))
        assert len(mp3_files) > 0
        assert mp3_files[0].stat().st_size > 0
