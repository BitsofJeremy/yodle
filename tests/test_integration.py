"""
Integration tests for yodle.py.

These tests verify component interactions and end-to-end workflows.
Most tests use mocked external dependencies to avoid network calls.

Run with: pytest tests/test_integration.py
Run slow tests: pytest tests/test_integration.py -m slow
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, Mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from yodle import (
    CookieManager,
    VideoDownloader,
    MusicDownloader,
    DownloadManager,
    DownloadResult,
    _apply_limit_opts,
    YDL_COMMON_OPTS,
)


class TestPlayerClients:
    """YDL_COMMON_OPTS must not pin player clients yt-dlp has removed.

    android_vr was removed from yt-dlp's defaults in 2026.08.19 because its
    HTTPS formats now require a GVS PO token and yield HTTP 403 without one
    (yt-dlp/yt-dlp#17456). Pinning it degrades music to itag 18 and re-introduces
    the 403s, so yodle must defer to yt-dlp's maintained defaults.
    """

    def test_no_player_client_pin(self):
        """player_client must be left unset so yt-dlp defaults apply."""
        youtube_args = YDL_COMMON_OPTS.get("extractor_args", {}).get("youtube", {})
        assert "player_client" not in youtube_args

    def test_removed_clients_never_pinned(self):
        """Guard against re-adding clients dropped from yt-dlp defaults."""
        youtube_args = YDL_COMMON_OPTS.get("extractor_args", {}).get("youtube", {})
        clients = youtube_args.get("player_client", [])
        for removed in ("android_vr", "android"):
            assert removed not in clients

    def test_ejs_remote_component_kept(self):
        """The EJS challenge solver stays — signature/n-param 403 workaround."""
        assert "ejs:github" in YDL_COMMON_OPTS["remote_components"]


class TestCookieIntegration:
    """Integration tests for cookie extraction and usage."""

    def test_cookie_extraction_and_download_integration(self, tmp_path, mocker, mock_youtube_cookie):
        """Test cookie extraction flows into downloader configuration."""
        # Setup cookie extraction
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        mock_chrome = mocker.patch("browser_cookie3.chrome")
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

        mock_chrome = mocker.patch("browser_cookie3.chrome")
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
        """Test complete music pipeline: download -> convert (in yt-dlp) -> tag."""
        # Mock yt-dlp download; conversion now happens inside yt-dlp's
        # FFmpegExtractAudio postprocessor, so simulate the produced MP3
        mock_ydl = Mock()

        def fake_extract(url, download=True):
            (tmp_path / "Test_Video.mp3").write_bytes(b"fake mp3 audio data")
            return mock_yt_dlp_info

        mock_ydl.extract_info.side_effect = fake_extract
        mock_ydl.__enter__ = Mock(return_value=mock_ydl)
        mock_ydl.__exit__ = Mock(return_value=False)
        mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

        # Avoid network call for album art
        mocker.patch.object(MusicDownloader, "_save_thumbnail_png")

        # Mock mutagen tagging (MagicMock supports item assignment for frames)
        mock_mp3 = MagicMock()
        mocker.patch("yodle.MP3", return_value=mock_mp3)

        # Execute download
        downloader = MusicDownloader()
        result = downloader.download("https://youtube.com/watch?v=abc123", tmp_path)

        # Verify pipeline executed
        assert result.success is True
        assert result.output_path.endswith(".mp3")
        mock_mp3.save.assert_called_once()  # Tags saved

    def test_music_download_survives_tagging_failure(self, tmp_path, mocker, mock_yt_dlp_info):
        """Test music download still succeeds if ID3 tagging blows up."""
        mock_ydl = Mock()

        def fake_extract(url, download=True):
            (tmp_path / "Test_Video.mp3").write_bytes(b"fake mp3")
            return mock_yt_dlp_info

        mock_ydl.extract_info.side_effect = fake_extract
        mock_ydl.__enter__ = Mock(return_value=mock_ydl)
        mock_ydl.__exit__ = Mock(return_value=False)
        mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

        mocker.patch.object(MusicDownloader, "_save_thumbnail_png")

        # Tagging raises — _embed_id3_tags must swallow it
        mocker.patch("yodle.MP3", side_effect=Exception("no ID3 header"))

        # Execute
        downloader = MusicDownloader()
        result = downloader.download("https://youtube.com/watch?v=abc123", tmp_path)

        # Should still succeed without tagging
        assert result.success is True
        assert result.output_path.endswith(".mp3")


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


class TestLimitOpts:
    """Tests for --limit download-range opts injection."""

    def test_video_no_limit_omits_range_opts(self, tmp_path):
        """Without limit_seconds, no download-range opts are set."""
        opts = VideoDownloader()._get_opts(tmp_path)
        assert "download_ranges" not in opts
        assert "force_keyframes_at_cuts" not in opts

    def test_music_no_limit_omits_range_opts(self, tmp_path):
        """Without limit_seconds, no download-range opts are set."""
        opts = MusicDownloader()._get_opts(tmp_path)
        assert "download_ranges" not in opts
        assert "force_keyframes_at_cuts" not in opts

    def test_video_with_limit_sets_range_opts(self, tmp_path):
        """With limit_seconds, download_ranges covers 0..limit with forced keyframes."""
        opts = VideoDownloader(limit_seconds=60)._get_opts(tmp_path)
        assert opts["force_keyframes_at_cuts"] is True
        assert callable(opts["download_ranges"])
        assert list(opts["download_ranges"]({"id": "x"}, Mock())) == [
            {"start_time": 0, "end_time": 60}
        ]
        # Existing opts survive injection
        assert opts["format"] == VideoDownloader.FORMAT_STRING
        assert opts["merge_output_format"] == "mp4"
        assert opts["postprocessors"] == [{"key": "FFmpegMetadata"}]

    def test_music_with_limit_sets_range_opts_without_keyframes(self, tmp_path):
        """Music gets the range opts but MUST NOT force keyframes.

        force_keyframes_at_cuts makes yt-dlp's ranged FFmpeg download omit
        '-c copy', causing a double lossy transcode (download + ExtractAudio).
        """
        opts = MusicDownloader(limit_seconds=90)._get_opts(tmp_path)
        assert "force_keyframes_at_cuts" not in opts
        assert list(opts["download_ranges"]({"id": "x"}, Mock())) == [
            {"start_time": 0, "end_time": 90}
        ]
        pp_keys = [pp["key"] for pp in opts["postprocessors"]]
        assert "FFmpegExtractAudio" in pp_keys

    def test_download_manager_forwards_limit(self, tmp_path):
        """DownloadManager forwards limit_seconds to both downloaders."""
        manager = DownloadManager(tmp_path, limit_seconds=45)
        assert manager.video_downloader.limit_seconds == 45
        assert manager.music_downloader.limit_seconds == 45

    def test_download_manager_default_limit_is_none(self, tmp_path):
        """Default DownloadManager leaves limit unset."""
        manager = DownloadManager(tmp_path)
        assert manager.video_downloader.limit_seconds is None
        assert manager.music_downloader.limit_seconds is None

    def test_apply_limit_opts_helper(self):
        """Helper is a no-op for None and injects for a value."""
        assert _apply_limit_opts({"a": 1}, None) == {"a": 1}
        opts = _apply_limit_opts({"a": 1}, 30)
        assert opts["force_keyframes_at_cuts"] is True
        assert list(opts["download_ranges"]({"id": "x"}, Mock())) == [
            {"start_time": 0, "end_time": 30}
        ]

    def test_apply_limit_opts_without_keyframes(self):
        """force_keyframes=False injects ranges but skips the keyframe opt."""
        opts = _apply_limit_opts({"a": 1}, 30, force_keyframes=False)
        assert "force_keyframes_at_cuts" not in opts
        assert list(opts["download_ranges"]({"id": "x"}, Mock())) == [
            {"start_time": 0, "end_time": 30}
        ]


class TestAudioQualityOpts:
    """Tests for --audio-quality plumbing into yt-dlp opts."""

    def test_default_quality_is_vbr_best(self, tmp_path):
        """Default opts request preferredquality '0' (VBR 0 = best) for mp3."""
        opts = MusicDownloader()._get_opts(tmp_path)
        extract = opts["postprocessors"][0]
        assert extract["key"] == "FFmpegExtractAudio"
        assert extract["preferredcodec"] == "mp3"
        assert extract["preferredquality"] == "0"

    def test_explicit_bitrate_forwarded(self, tmp_path):
        """audio_quality=320 reaches preferredquality for m4a too."""
        opts = MusicDownloader(audio_quality=320, output_format="m4a")._get_opts(tmp_path)
        extract = opts["postprocessors"][0]
        assert extract["preferredcodec"] == "m4a"
        assert extract["preferredquality"] == "320"

    def test_mp3_branch_has_no_postprocessor_args(self, tmp_path):
        """mp3 opts must not carry postprocessor_args."""
        opts = MusicDownloader()._get_opts(tmp_path)
        assert "postprocessor_args" not in opts

    def test_m4a_postprocessor_args_scoped_to_embed_thumbnail(self, tmp_path):
        """m4a cover-art args are dict-form, scoped, and contain no -c:a."""
        opts = MusicDownloader(output_format="m4a")._get_opts(tmp_path)
        ppa = opts["postprocessor_args"]
        assert isinstance(ppa, dict)
        assert set(ppa) == {"embedthumbnail+ffmpeg"}
        values = ppa["embedthumbnail+ffmpeg"]
        assert "-c:a" not in values
        assert "title=Album Cover" in values

    def test_m4a_metadata_runs_before_thumbnail_embed(self, tmp_path):
        """FFmpegMetadata must run before EmbedThumbnail for m4a.

        FFmpegMetadata's m4a output args include '-vn', which drops the
        cover that EmbedThumbnail writes (mutagen 'covr' atom). Metadata
        must write first so the cover can be embedded last and survive.
        """
        opts = MusicDownloader(output_format="m4a")._get_opts(tmp_path)
        keys = [pp["key"] for pp in opts["postprocessors"]]
        assert keys.index("FFmpegMetadata") < keys.index("EmbedThumbnail")

    def test_mp3_metadata_still_runs_after_thumbnail_embed(self, tmp_path):
        """mp3 order is unchanged: APIC survives FFmpegMetadata there."""
        opts = MusicDownloader()._get_opts(tmp_path)
        keys = [pp["key"] for pp in opts["postprocessors"]]
        assert keys.index("EmbedThumbnail") < keys.index("FFmpegMetadata")

    def test_format_prefers_opus_source(self, tmp_path):
        """Explicit format string prefers the opus DASH audio stream."""
        assert "acodec=opus" in MusicDownloader.FORMAT_STRING
        opts = MusicDownloader()._get_opts(tmp_path)
        assert opts["format"] == MusicDownloader.FORMAT_STRING

    def test_download_manager_forwards_quality_and_normalize(self, tmp_path):
        """DownloadManager forwards both new knobs; defaults preserved."""
        manager = DownloadManager(tmp_path, audio_quality=320, normalize=True)
        assert manager.music_downloader.audio_quality == 320
        assert manager.music_downloader.normalize is True

        default_manager = DownloadManager(tmp_path)
        assert default_manager.music_downloader.audio_quality == 0
        assert default_manager.music_downloader.normalize is False


class TestNormalize:
    """Tests for the --normalize loudness pass."""

    @staticmethod
    def _mock_pipeline(tmp_path, mocker, mock_yt_dlp_info, filename="Test_Video.mp3"):
        """Wire the mocked yt-dlp download pipeline; return the audio path."""
        mock_ydl = Mock()

        def fake_extract(url, download=True):
            (tmp_path / filename).write_bytes(b"fake mp3 audio data")
            return mock_yt_dlp_info

        mock_ydl.extract_info.side_effect = fake_extract
        mock_ydl.__enter__ = Mock(return_value=mock_ydl)
        mock_ydl.__exit__ = Mock(return_value=False)
        mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)
        mocker.patch.object(MusicDownloader, "_save_thumbnail_png")
        mocker.patch("yodle.MP3", return_value=MagicMock())
        return tmp_path / filename

    def test_normalize_off_by_default(self, tmp_path, mocker, mock_yt_dlp_info):
        """Default pipeline must not run the normalization pass."""
        audio_path = self._mock_pipeline(tmp_path, mocker, mock_yt_dlp_info)
        spy = mocker.patch.object(MusicDownloader, "_normalize_loudness")

        result = MusicDownloader().download("https://youtube.com/watch?v=abc", tmp_path)

        assert result.success is True
        spy.assert_not_called()
        assert audio_path.exists()

    def test_normalize_runs_when_enabled(self, tmp_path, mocker, mock_yt_dlp_info):
        """normalize=True invokes the normalization pass before tagging."""
        self._mock_pipeline(tmp_path, mocker, mock_yt_dlp_info)
        spy = mocker.patch.object(MusicDownloader, "_normalize_loudness", return_value=True)

        result = MusicDownloader(normalize=True).download(
            "https://youtube.com/watch?v=abc", tmp_path
        )

        assert result.success is True
        spy.assert_called_once()

    def test_measurement_failure_keeps_original(self, tmp_path, mocker):
        """OSError during measurement -> False, file bytes untouched."""
        audio_path = tmp_path / "track.mp3"
        audio_path.write_bytes(b"original bytes")
        mocker.patch("yodle.subprocess.run", side_effect=OSError("ffmpeg missing"))

        assert MusicDownloader()._normalize_loudness(audio_path) is False
        assert audio_path.read_bytes() == b"original bytes"
        assert not list(tmp_path.glob("*.norm.mp3"))

    def test_missing_measurement_json_keeps_original(self, tmp_path, mocker):
        """Measurement returning no JSON block -> False, file untouched."""
        import subprocess
        audio_path = tmp_path / "track.mp3"
        audio_path.write_bytes(b"original bytes")
        mocker.patch(
            "yodle.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, "", "no json here"),
        )

        assert MusicDownloader()._normalize_loudness(audio_path) is False
        assert audio_path.read_bytes() == b"original bytes"

    def test_success_reencodes_and_replaces(self, tmp_path, mocker):
        """Two-pass success: measured values applied, file replaced."""
        import json
        import subprocess
        audio_path = tmp_path / "track.mp3"
        audio_path.write_bytes(b"original bytes")

        loudnorm_json = json.dumps({
            "input_i": "-18.0", "input_tp": "-3.0", "input_lra": "7.0",
            "input_thresh": "-28.0", "target_offset": "0.5",
        })
        captured = {}

        def fake_run(cmd, capture_output=True, text=True):
            joined = " ".join(cmd)
            if "print_format=json" in joined:
                return subprocess.CompletedProcess(cmd, 0, "", loudnorm_json)
            captured["apply_cmd"] = list(cmd)
            Path(cmd[-1]).write_bytes(b"normalized bytes")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mocker.patch("yodle.subprocess.run", side_effect=fake_run)

        assert MusicDownloader()._normalize_loudness(audio_path) is True
        assert audio_path.read_bytes() == b"normalized bytes"

        apply_cmd = captured["apply_cmd"]
        joined = " ".join(apply_cmd)
        assert "measured_I=-18.0" in joined
        assert "linear=true" in joined
        assert "-map 0:v?" in joined
        assert "libmp3lame" in apply_cmd
        assert apply_cmd[-1].endswith(".norm.mp3")
