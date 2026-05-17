# Yodle Test Strategy & Implementation Plan

## Executive Summary

This document provides a comprehensive test strategy for `yodle.py`, balancing thorough coverage with practical maintainability. The strategy prioritizes testing business logic and critical paths while avoiding testing framework internals or implementation details.

**Test Coverage Target**: 80%+ for critical business logic
**Framework**: pytest with pytest-asyncio, pytest-mock
**Test Execution Time Target**: <5s for unit tests, <30s for integration tests

---

## Test Pyramid Distribution

```
    /\
   /  \  E2E Tests (10%)
  /    \  - 1-2 real download tests with short CC videos
 /------\
/        \ Integration Tests (20%)
/----------\ - Component interaction tests with mocked downloads
/            \ Unit Tests (70%)
               - Pure functions, class methods, edge cases
```

**Rationale**:
- Unit tests are fast, reliable, and easy to maintain
- Integration tests verify component interactions without network dependencies
- Minimal E2E tests to validate real-world scenarios (rate-limited to avoid API abuse)

---

## Risk Assessment & Test Priorities

### HIGH RISK (Must have comprehensive tests)
1. **File operations**: Sanitization, path handling, file cleanup
2. **Cookie extraction**: Browser-specific logic, Netscape format validation
3. **Download orchestration**: Playlist expansion, type routing, error handling
4. **M4A to MP3 conversion**: Data integrity, ID3 tag embedding
5. **Threading/Queue communication**: Race conditions, message ordering

### MEDIUM RISK (Should have targeted tests)
1. **URL parsing**: Playlist/channel detection
2. **Version comparison**: Update detection logic
3. **Progress callbacks**: Percentage calculation, data extraction
4. **Async thumbnail downloads**: Concurrency, timeout handling

### LOW RISK (Can skip or minimal tests)
1. **Tkinter GUI components**: Manual testing preferred
2. **yt-dlp internals**: Already tested by yt-dlp project
3. **Third-party library wrappers**: Trust library tests

---

## Test File Structure

```
tests/
├── __init__.py
├── conftest.py                    # Shared fixtures and configuration
├── test_utilities.py              # Unit tests for utility functions
├── test_cookie_manager.py         # CookieManager class tests
├── test_update_checker.py         # UpdateChecker class tests
├── test_video_downloader.py       # VideoDownloader class tests
├── test_music_downloader.py       # MusicDownloader class tests
├── test_thumbnail_downloader.py   # ThumbnailDownloader class tests
├── test_download_manager.py       # DownloadManager orchestration tests
├── test_integration.py            # End-to-end integration tests
└── fixtures/
    ├── sample_metadata.json       # Mock yt-dlp responses
    ├── test_audio.m4a             # Tiny audio file for conversion tests
    └── test_thumbnail.png         # Small image for resize tests
```

---

## Unit Tests - Detailed Test Cases

### 1. test_utilities.py

#### test_sanitize_filename()
**Purpose**: Ensure filenames are safe across filesystems

**Test Cases**:
```python
# Normal cases
assert sanitize_filename("Simple Title") == "Simple_Title"
assert sanitize_filename("Multiple   Spaces") == "Multiple_Spaces"

# Special characters
assert sanitize_filename("Video: Part 1 / 2") == "Video_Part_1_2"
assert sanitize_filename("100% Complete!") == "100_Complete"
assert sanitize_filename("Artist - Song (Official)") == "Artist_Song_Official"

# Unicode handling
assert sanitize_filename("Español ñ Ü") == "Espaol__"
assert sanitize_filename("日本語タイトル") == ""  # No valid chars
assert sanitize_filename("Café Münchën") == "Caf_Mnchen"

# Edge cases
assert sanitize_filename("") == ""
assert sanitize_filename("   ") == ""
assert sanitize_filename("___test___") == "test"
assert sanitize_filename("...dots...") == "dots"
assert sanitize_filename("a" * 300) == "a" * 300  # Length handling

# Platform-specific forbidden chars
assert sanitize_filename("file<>name") == "filename"
assert sanitize_filename("C:\\Windows\\file") == "CWindowsfile"
assert sanitize_filename("file|name:test") == "filenametest"
```

**Mocking**: None needed (pure function)

---

#### test_is_playlist()
**Purpose**: Correctly identify playlist URLs

**Test Cases**:
```python
# Positive cases
assert is_playlist("https://youtube.com/playlist?list=PLxxx")
assert is_playlist("https://youtube.com/watch?v=xxx&list=PLyyy")
assert is_playlist("https://music.youtube.com/playlist?list=xxx")

# Negative cases
assert not is_playlist("https://youtube.com/watch?v=dQw4w9WgXcQ")
assert not is_playlist("https://youtube.com/@channel")
assert not is_playlist("https://youtube.com/channel/UCxxx")

# Edge cases
assert not is_playlist("")
assert not is_playlist("not-a-url")
assert is_playlist("playlist?v=xxx")  # Substring match
```

**Mocking**: None needed

---

#### test_is_channel()
**Purpose**: Correctly identify channel URLs

**Test Cases**:
```python
# Positive cases - all channel URL formats
assert is_channel("https://youtube.com/@channelname")
assert is_channel("https://youtube.com/channel/UCxxx")
assert is_channel("https://youtube.com/c/CustomName")
assert is_channel("https://youtube.com/user/username")

# Negative cases
assert not is_channel("https://youtube.com/watch?v=xxx")
assert not is_channel("https://youtube.com/playlist?list=xxx")
assert not is_channel("")

# Edge cases
assert is_channel("/@channelname")  # Substring match
```

**Mocking**: None needed

---

#### test_check_ffmpeg()
**Purpose**: Verify ffmpeg availability detection

**Test Cases**:
```python
def test_check_ffmpeg_installed(mocker):
    """Test when ffmpeg is available."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = None  # Success
    assert check_ffmpeg() is True
    mock_run.assert_called_once_with(
        ["ffmpeg", "-version"],
        capture_output=True,
        check=True
    )

def test_check_ffmpeg_missing(mocker):
    """Test when ffmpeg is not installed."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.side_effect = FileNotFoundError()
    assert check_ffmpeg() is False

def test_check_ffmpeg_error(mocker):
    """Test when ffmpeg command fails."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
    assert check_ffmpeg() is False
```

**Mocking**: subprocess.run

---

### 2. test_cookie_manager.py

#### test_get_cookies_path()
**Purpose**: Verify cookie path creation

**Test Cases**:
```python
def test_get_cookies_path_creates_directory(tmp_path, mocker):
    """Test that parent directory is created."""
    mock_home = tmp_path / "home"
    mocker.patch("pathlib.Path.home", return_value=mock_home)

    path = CookieManager.get_cookies_path()

    assert path.parent.exists()
    assert path == mock_home / ".config" / "yt-dlp" / "cookies.txt"

def test_get_cookies_path_idempotent(tmp_path, mocker):
    """Test multiple calls don't error."""
    mock_home = tmp_path / "home"
    mocker.patch("pathlib.Path.home", return_value=mock_home)

    path1 = CookieManager.get_cookies_path()
    path2 = CookieManager.get_cookies_path()

    assert path1 == path2
```

**Mocking**: pathlib.Path.home

---

#### test_extract_cookies()
**Purpose**: Test cookie extraction from browsers

**Test Cases**:
```python
def test_extract_cookies_chrome_success(tmp_path, mocker):
    """Test successful Chrome cookie extraction."""
    cookies_path = tmp_path / "cookies.txt"
    mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

    # Mock browsercookie.chrome()
    mock_cookie = mocker.Mock()
    mock_cookie.domain = ".youtube.com"
    mock_cookie.path = "/"
    mock_cookie.secure = True
    mock_cookie.expires = 1234567890
    mock_cookie.name = "CONSENT"
    mock_cookie.value = "YES+1"

    mock_chrome = mocker.patch("browsercookie.chrome")
    mock_chrome.return_value = [mock_cookie]

    result = CookieManager.extract_cookies("chrome")

    assert result == cookies_path
    assert cookies_path.exists()

    # Verify Netscape format
    content = cookies_path.read_text()
    assert "# Netscape HTTP Cookie File" in content
    assert ".youtube.com" in content
    assert "CONSENT" in content

def test_extract_cookies_firefox_success(tmp_path, mocker):
    """Test successful Firefox cookie extraction."""
    cookies_path = tmp_path / "cookies.txt"
    mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

    mock_cookie = mocker.Mock()
    mock_cookie.domain = ".google.com"
    mock_cookie.path = "/"
    mock_cookie.secure = False
    mock_cookie.expires = None  # Session cookie
    mock_cookie.name = "SID"
    mock_cookie.value = "xxx"

    mock_firefox = mocker.patch("browsercookie.firefox")
    mock_firefox.return_value = [mock_cookie]

    result = CookieManager.extract_cookies("firefox")

    assert result == cookies_path
    content = cookies_path.read_text()
    assert "FALSE" in content  # Not secure
    assert "\t0\t" in content  # No expiration

def test_extract_cookies_unsupported_browser(tmp_path, mocker):
    """Test unsupported browser returns None."""
    mocker.patch.object(CookieManager, "get_cookies_path", return_value=tmp_path / "cookies.txt")

    result = CookieManager.extract_cookies("safari")

    assert result is None

def test_extract_cookies_extraction_error(tmp_path, mocker):
    """Test error handling during extraction."""
    cookies_path = tmp_path / "cookies.txt"
    mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

    mock_chrome = mocker.patch("browsercookie.chrome")
    mock_chrome.side_effect = Exception("Browser locked")

    result = CookieManager.extract_cookies("chrome")

    assert result is None
    assert not cookies_path.exists()  # Cleanup on error

def test_extract_cookies_filters_non_youtube(tmp_path, mocker):
    """Test that non-YouTube cookies are filtered out."""
    cookies_path = tmp_path / "cookies.txt"
    mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

    youtube_cookie = mocker.Mock(domain=".youtube.com", name="YT", value="1")
    other_cookie = mocker.Mock(domain=".example.com", name="TEST", value="2")

    mock_chrome = mocker.patch("browsercookie.chrome")
    mock_chrome.return_value = [youtube_cookie, other_cookie]

    CookieManager.extract_cookies("chrome")

    content = cookies_path.read_text()
    assert "youtube.com" in content
    assert "example.com" not in content
```

**Mocking**: browsercookie.chrome/firefox, pathlib.Path.home

---

#### test_cleanup()
**Purpose**: Test cookie file cleanup

**Test Cases**:
```python
def test_cleanup_removes_cookies(tmp_path, mocker):
    """Test cleanup removes existing cookie file."""
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("test cookies")

    mocker.patch("yodle.COOKIES_PATH", cookies_path)

    CookieManager.cleanup()

    assert not cookies_path.exists()

def test_cleanup_no_error_if_missing(tmp_path, mocker):
    """Test cleanup succeeds if file doesn't exist."""
    cookies_path = tmp_path / "cookies.txt"
    mocker.patch("yodle.COOKIES_PATH", cookies_path)

    CookieManager.cleanup()  # Should not raise
```

**Mocking**: yodle.COOKIES_PATH

---

### 3. test_update_checker.py

#### test_get_current_version()
**Purpose**: Verify version retrieval

**Test Cases**:
```python
def test_get_current_version(mocker):
    """Test getting installed yt-dlp version."""
    mock_yt_dlp = mocker.Mock()
    mock_yt_dlp.version.__version__ = "2024.12.01"
    mocker.patch.dict("sys.modules", {"yt_dlp": mock_yt_dlp})

    checker = UpdateChecker()
    version = checker.get_current_version()

    assert version == "2024.12.01"
```

**Mocking**: yt_dlp module

---

#### test_check_for_updates()
**Purpose**: Test update detection logic

**Test Cases**:
```python
def test_check_for_updates_available(mocker):
    """Test when update is available."""
    checker = UpdateChecker()
    mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")

    mock_response = mocker.Mock()
    mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
    mock_response.raise_for_status = mocker.Mock()

    mocker.patch("requests.get", return_value=mock_response)

    update_available, current, latest = checker.check_for_updates()

    assert update_available is True
    assert current == "2024.01.01"
    assert latest == "2024.12.01"

def test_check_for_updates_none_available(mocker):
    """Test when already up-to-date."""
    checker = UpdateChecker()
    mocker.patch.object(checker, "get_current_version", return_value="2024.12.01")

    mock_response = mocker.Mock()
    mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
    mock_response.raise_for_status = mocker.Mock()

    mocker.patch("requests.get", return_value=mock_response)

    update_available, current, latest = checker.check_for_updates()

    assert update_available is False
    assert current == "2024.12.01"
    assert latest == "2024.12.01"

def test_check_for_updates_newer_installed(mocker):
    """Test when local version is newer (dev version)."""
    checker = UpdateChecker()
    mocker.patch.object(checker, "get_current_version", return_value="2025.01.01")

    mock_response = mocker.Mock()
    mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
    mock_response.raise_for_status = mocker.Mock()

    mocker.patch("requests.get", return_value=mock_response)

    update_available, current, latest = checker.check_for_updates()

    assert update_available is False

def test_check_for_updates_network_error(mocker):
    """Test graceful handling of network errors."""
    checker = UpdateChecker()
    mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")
    mocker.patch("requests.get", side_effect=requests.RequestException())

    update_available, current, latest = checker.check_for_updates()

    assert update_available is False
    assert current == ""
    assert latest == ""

def test_check_for_updates_timeout(mocker):
    """Test timeout handling."""
    checker = UpdateChecker()
    mocker.patch("requests.get", side_effect=requests.Timeout())

    update_available, current, latest = checker.check_for_updates()

    assert update_available is False
```

**Mocking**: requests.get, yt_dlp.version

---

### 4. test_video_downloader.py

#### test_get_opts()
**Purpose**: Verify yt-dlp options configuration

**Test Cases**:
```python
def test_get_opts_basic(tmp_path):
    """Test basic options without cookies."""
    downloader = VideoDownloader()
    opts = downloader._get_opts(tmp_path)

    assert opts['format'] == '(bv*[vcodec~="^((he|a)vc|h26[45])"]+ba) / (bv*+ba/b)'
    assert tmp_path.name in opts['outtmpl']
    assert 'postprocessors' in opts
    assert opts['extractor_args']['youtube']['player_client'] == ['android']
    assert 'cookiefile' not in opts

def test_get_opts_with_cookies(tmp_path):
    """Test options with cookie file."""
    cookies_path = tmp_path / "cookies.txt"
    cookies_path.write_text("# cookies")

    downloader = VideoDownloader(cookies_path=cookies_path)
    opts = downloader._get_opts(tmp_path)

    assert opts['cookiefile'] == str(cookies_path)

def test_get_opts_with_progress_callback(tmp_path):
    """Test options with progress callback."""
    callback = lambda p, e: None
    downloader = VideoDownloader(progress_callback=callback)
    opts = downloader._get_opts(tmp_path)

    assert 'progress_hooks' in opts
    assert len(opts['progress_hooks']) == 1
```

**Mocking**: None needed

---

#### test_progress_hook()
**Purpose**: Test progress percentage extraction

**Test Cases**:
```python
def test_progress_hook_downloads(mocker):
    """Test progress callback during download."""
    callback = mocker.Mock()
    downloader = VideoDownloader(progress_callback=callback)

    downloader._progress_hook({
        'status': 'downloading',
        '_percent_str': '  75.5%  ',
        '_eta_str': '00:30'
    })

    callback.assert_called_once_with(75.5, '00:30')

def test_progress_hook_no_callback():
    """Test hook without callback doesn't error."""
    downloader = VideoDownloader()
    downloader._progress_hook({'status': 'downloading'})  # Should not raise

def test_progress_hook_invalid_percent(mocker):
    """Test handling of invalid percentage."""
    callback = mocker.Mock()
    downloader = VideoDownloader(progress_callback=callback)

    downloader._progress_hook({
        'status': 'downloading',
        '_percent_str': 'invalid'
    })

    callback.assert_not_called()

def test_progress_hook_finished_status(mocker):
    """Test hook ignores non-downloading status."""
    callback = mocker.Mock()
    downloader = VideoDownloader(progress_callback=callback)

    downloader._progress_hook({'status': 'finished'})

    callback.assert_not_called()
```

**Mocking**: progress_callback

---

#### test_download()
**Purpose**: Test video download orchestration

**Test Cases**:
```python
def test_download_success(tmp_path, mocker):
    """Test successful video download."""
    downloader = VideoDownloader()

    # Mock YoutubeDL
    mock_info = {
        'title': 'Test Video',
        'id': 'abc123',
        'ext': 'mp4'
    }

    mock_ydl = mocker.Mock()
    mock_ydl.extract_info.return_value = mock_info
    mock_ydl.__enter__ = mocker.Mock(return_value=mock_ydl)
    mock_ydl.__exit__ = mocker.Mock(return_value=False)

    mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

    # Create expected output file
    expected_file = tmp_path / "Test_Video-[abc123].mp4"
    expected_file.write_text("video data")

    result = downloader.download("https://youtube.com/watch?v=abc123", tmp_path)

    assert result.success is True
    assert result.title == "Test Video"
    assert result.download_type == "video"
    assert expected_file.name in result.output_path

def test_download_creates_directory(tmp_path, mocker):
    """Test output directory is created."""
    downloader = VideoDownloader()

    mock_ydl = mocker.Mock()
    mock_ydl.extract_info.return_value = {'title': 'Test', 'id': '123'}
    mock_ydl.__enter__ = mocker.Mock(return_value=mock_ydl)
    mock_ydl.__exit__ = mocker.Mock(return_value=False)

    mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

    output_dir = tmp_path / "new" / "path"
    downloader.download("https://youtube.com/watch?v=123", output_dir)

    assert output_dir.exists()

def test_download_error_handling(tmp_path, mocker):
    """Test error handling during download."""
    downloader = VideoDownloader()

    mock_ydl = mocker.Mock()
    mock_ydl.extract_info.side_effect = Exception("Network error")
    mock_ydl.__enter__ = mocker.Mock(return_value=mock_ydl)
    mock_ydl.__exit__ = mocker.Mock(return_value=False)

    mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

    result = downloader.download("https://youtube.com/watch?v=123", tmp_path)

    assert result.success is False
    assert "Network error" in result.error
    assert result.download_type == "video"
```

**Mocking**: YoutubeDL, file creation

---

### 5. test_music_downloader.py

#### test_convert_to_mp3()
**Purpose**: Test M4A to MP3 conversion

**Test Cases**:
```python
def test_convert_to_mp3_success(tmp_path, mocker):
    """Test successful M4A to MP3 conversion."""
    m4a_path = tmp_path / "test.m4a"
    mp3_path = tmp_path / "test.mp3"

    # Mock AudioSegment
    mock_audio = mocker.Mock()
    mock_from_file = mocker.patch("yodle.AudioSegment.from_file", return_value=mock_audio)

    # Create dummy M4A file
    m4a_path.write_bytes(b"fake m4a data")

    # Mock mutagen embedding
    mocker.patch("yodle.MUTAGEN_AVAILABLE", True)
    mock_embed = mocker.patch.object(MusicDownloader, "_embed_id3_tags")

    downloader = MusicDownloader()
    info = {'title': 'Test Song', 'uploader': 'Artist'}

    result = downloader._convert_to_mp3(m4a_path, info)

    assert result == mp3_path
    mock_audio.export.assert_called_once_with(str(mp3_path), format="mp3", bitrate="192k")
    mock_embed.assert_called_once()
    assert not m4a_path.exists()  # Original removed

def test_convert_to_mp3_no_mutagen(tmp_path, mocker):
    """Test conversion without mutagen available."""
    m4a_path = tmp_path / "test.m4a"
    m4a_path.write_bytes(b"data")

    mock_audio = mocker.Mock()
    mocker.patch("yodle.AudioSegment.from_file", return_value=mock_audio)
    mocker.patch("yodle.MUTAGEN_AVAILABLE", False)

    downloader = MusicDownloader()
    result = downloader._convert_to_mp3(m4a_path, {})

    assert result is not None
    assert result.suffix == ".mp3"

def test_convert_to_mp3_conversion_error(tmp_path, mocker):
    """Test error handling during conversion."""
    m4a_path = tmp_path / "test.m4a"
    m4a_path.write_bytes(b"data")

    mocker.patch("yodle.AudioSegment.from_file", side_effect=Exception("Codec error"))

    downloader = MusicDownloader()
    result = downloader._convert_to_mp3(m4a_path, {})

    assert result == m4a_path  # Returns original on error
    assert m4a_path.exists()
```

**Mocking**: AudioSegment, mutagen

---

#### test_embed_id3_tags()
**Purpose**: Test ID3 metadata embedding

**Test Cases**:
```python
def test_embed_id3_tags_complete_info(tmp_path, mocker):
    """Test embedding with complete metadata."""
    mp3_path = tmp_path / "test.mp3"
    mp3_path.write_bytes(b"fake mp3")

    # Mock MP3 and ID3
    mock_audio = mocker.Mock()
    mock_mp3_class = mocker.patch("yodle.MP3", return_value=mock_audio)

    info = {
        'title': 'Song Title',
        'uploader': 'Artist Name',
        'upload_date': '20240315'
    }

    downloader = MusicDownloader()
    downloader._embed_id3_tags(mp3_path, info)

    # Verify tags were set
    assert mock_audio["TIT2"] is not None
    assert mock_audio["TPE1"] is not None
    assert mock_audio["TDRC"] is not None
    mock_audio.save.assert_called_once()

def test_embed_id3_tags_with_thumbnail(tmp_path, mocker):
    """Test embedding with album art."""
    mp3_path = tmp_path / "test.mp3"
    thumbnail_path = tmp_path / "test.png"

    mp3_path.write_bytes(b"mp3")
    thumbnail_path.write_bytes(b"PNG image data")

    mock_audio = mocker.Mock()
    mocker.patch("yodle.MP3", return_value=mock_audio)

    downloader = MusicDownloader()
    downloader._embed_id3_tags(mp3_path, {'title': 'Test'})

    # Verify APIC tag was added
    assert mock_audio["APIC"] is not None

def test_embed_id3_tags_minimal_info(tmp_path, mocker):
    """Test embedding with minimal metadata."""
    mp3_path = tmp_path / "test.mp3"
    mp3_path.write_bytes(b"mp3")

    mock_audio = mocker.Mock()
    mocker.patch("yodle.MP3", return_value=mock_audio)

    downloader = MusicDownloader()
    downloader._embed_id3_tags(mp3_path, {})  # Empty info

    # Should still save with defaults
    mock_audio.save.assert_called_once()
```

**Mocking**: MP3, ID3 classes

---

### 6. test_thumbnail_downloader.py

#### test_resize_image()
**Purpose**: Test image resizing logic

**Test Cases**:
```python
def test_resize_image_large(mocker):
    """Test resizing image larger than max width."""
    mock_img = mocker.Mock()
    mock_img.size = (1920, 1080)

    mock_resized = mocker.Mock()
    mock_img.resize.return_value = mock_resized

    downloader = ThumbnailDownloader()
    result = downloader._resize_image(mock_img, max_width=512)

    # Verify resize called with correct dimensions
    mock_img.resize.assert_called_once_with((512, 288), mocker.ANY)
    assert result == mock_resized

def test_resize_image_already_small(mocker):
    """Test image already smaller than max width."""
    mock_img = mocker.Mock()
    mock_img.size = (256, 256)

    downloader = ThumbnailDownloader()
    result = downloader._resize_image(mock_img, max_width=512)

    assert result == mock_img
    mock_img.resize.assert_not_called()

def test_resize_image_maintains_aspect_ratio(mocker):
    """Test aspect ratio is maintained."""
    mock_img = mocker.Mock()
    mock_img.size = (1600, 900)  # 16:9

    downloader = ThumbnailDownloader()
    downloader._resize_image(mock_img, max_width=800)

    # Should call resize with (800, 450) to maintain 16:9
    call_args = mock_img.resize.call_args[0][0]
    assert call_args == (800, 450)
```

**Mocking**: PIL.Image

---

#### test_download_thumbnail()
**Purpose**: Test single thumbnail download

**Test Cases**:
```python
@pytest.mark.asyncio
async def test_download_thumbnail_success(tmp_path, mocker):
    """Test successful thumbnail download."""
    output_dir = tmp_path / "channel"

    # Mock image download
    mock_urlretrieve = mocker.patch("urllib.request.urlretrieve")

    # Mock PIL Image
    mock_img = mocker.Mock()
    mock_img.__enter__ = mocker.Mock(return_value=mock_img)
    mock_img.__exit__ = mocker.Mock(return_value=False)
    mocker.patch("yodle.Image.open", return_value=mock_img)

    downloader = ThumbnailDownloader()
    result = await downloader.download_thumbnail(
        "https://example.com/thumb.jpg",
        output_dir,
        "video123"
    )

    assert result is True
    assert (output_dir / "original" / "video123.png").exists()
    assert (output_dir / "resized_512" / "video123.png").exists()

@pytest.mark.asyncio
async def test_download_thumbnail_timeout(tmp_path, mocker):
    """Test timeout handling."""
    output_dir = tmp_path / "channel"

    async def slow_download(*args):
        await asyncio.sleep(100)

    mocker.patch("urllib.request.urlretrieve", side_effect=slow_download)

    downloader = ThumbnailDownloader()
    result = await downloader.download_thumbnail(
        "https://example.com/thumb.jpg",
        output_dir,
        "video123",
        timeout=0.1
    )

    assert result is False

@pytest.mark.asyncio
async def test_download_thumbnail_error(tmp_path, mocker):
    """Test error handling."""
    mocker.patch("urllib.request.urlretrieve", side_effect=Exception("Network error"))

    downloader = ThumbnailDownloader()
    result = await downloader.download_thumbnail(
        "https://example.com/thumb.jpg",
        tmp_path,
        "video123"
    )

    assert result is False
```

**Mocking**: urllib.request.urlretrieve, PIL.Image

---

### 7. test_download_manager.py

#### test_get_playlist_info()
**Purpose**: Test playlist expansion

**Test Cases**:
```python
def test_get_playlist_info_success(mocker):
    """Test extracting playlist information."""
    mock_ydl = mocker.Mock()
    mock_ydl.extract_info.return_value = {
        'title': 'My Playlist',
        'entries': [
            {'id': 'vid1', 'title': 'Video 1'},
            {'id': 'vid2', 'title': 'Video 2'},
        ]
    }
    mock_ydl.__enter__ = mocker.Mock(return_value=mock_ydl)
    mock_ydl.__exit__ = mocker.Mock(return_value=False)

    mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

    manager = DownloadManager(Path("/tmp"))
    title, videos = manager._get_playlist_info("https://youtube.com/playlist?list=PLxxx")

    assert title == "My_Playlist"
    assert len(videos) == 2
    assert videos[0]['url'] == "https://www.youtube.com/watch?v=vid1"

def test_get_playlist_info_filters_none_entries(mocker):
    """Test filtering out None entries."""
    mock_ydl = mocker.Mock()
    mock_ydl.extract_info.return_value = {
        'title': 'Playlist',
        'entries': [
            {'id': 'vid1', 'title': 'Video 1'},
            None,  # Deleted video
            {'id': 'vid2', 'title': 'Video 2'},
        ]
    }
    mock_ydl.__enter__ = mocker.Mock(return_value=mock_ydl)
    mock_ydl.__exit__ = mocker.Mock(return_value=False)

    mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

    manager = DownloadManager(Path("/tmp"))
    title, videos = manager._get_playlist_info("url")

    assert len(videos) == 2
```

**Mocking**: YoutubeDL

---

#### test_download()
**Purpose**: Test download orchestration

**Test Cases**:
```python
def test_download_single_video(tmp_path, mocker):
    """Test downloading single video."""
    manager = DownloadManager(tmp_path)

    mock_download = mocker.patch.object(
        manager.video_downloader,
        'download',
        return_value=DownloadResult(
            success=True,
            url="https://youtube.com/watch?v=123",
            title="Test Video",
            download_type="video"
        )
    )

    results = manager.download(["https://youtube.com/watch?v=123"], "video")

    assert len(results) == 1
    assert results[0].success is True
    mock_download.assert_called_once()

def test_download_both_video_and_music(tmp_path, mocker):
    """Test downloading both formats."""
    manager = DownloadManager(tmp_path)

    mocker.patch.object(
        manager.video_downloader,
        'download',
        return_value=DownloadResult(success=True, url="url", download_type="video")
    )
    mocker.patch.object(
        manager.music_downloader,
        'download',
        return_value=DownloadResult(success=True, url="url", download_type="music")
    )

    results = manager.download(["https://youtube.com/watch?v=123"], "both")

    assert len(results) == 2
    assert results[0].download_type == "video"
    assert results[1].download_type == "music"

def test_download_playlist_expands(tmp_path, mocker):
    """Test playlist URLs are expanded."""
    manager = DownloadManager(tmp_path)

    mocker.patch.object(
        manager,
        '_get_playlist_info',
        return_value=("Playlist", [
            {'url': 'https://youtube.com/watch?v=1', 'title': 'Video 1'},
            {'url': 'https://youtube.com/watch?v=2', 'title': 'Video 2'},
        ])
    )

    mock_download_single = mocker.patch.object(manager, '_download_single', return_value=[])

    manager.download(["https://youtube.com/playlist?list=PLxxx"], "video")

    assert mock_download_single.call_count == 2

def test_download_channel_for_thumbnails(tmp_path, mocker):
    """Test channel URL for thumbnail download."""
    manager = DownloadManager(tmp_path)

    mock_thumb_dl = mocker.patch.object(
        manager.thumbnail_downloader,
        'download',
        return_value=DownloadResult(success=True, url="url", download_type="thumbnails")
    )

    results = manager.download(["https://youtube.com/@channel"], "thumbnails")

    assert len(results) == 1
    mock_thumb_dl.assert_called_once()

def test_download_non_channel_for_thumbnails_fails(tmp_path, mocker):
    """Test non-channel URL for thumbnails returns error."""
    manager = DownloadManager(tmp_path)

    results = manager.download(["https://youtube.com/watch?v=123"], "thumbnails")

    assert len(results) == 1
    assert results[0].success is False
    assert "Not a channel URL" in results[0].error

def test_download_skips_empty_urls(tmp_path):
    """Test empty URLs are skipped."""
    manager = DownloadManager(tmp_path)

    results = manager.download(["", "  ", "\n"], "video")

    assert len(results) == 0
```

**Mocking**: Downloader classes, playlist info extraction

---

## Integration Tests - test_integration.py

### Purpose
Verify component interactions and end-to-end workflows without hitting real YouTube servers (except for one smoke test).

### Test Cases

```python
def test_full_music_pipeline_mocked(tmp_path, mocker):
    """Test complete music download, conversion, and tagging pipeline."""
    # Mock yt-dlp to return fake M4A
    mock_ydl = mocker.Mock()
    mock_ydl.extract_info.return_value = {
        'title': 'Test Song',
        'id': 'abc123',
        'uploader': 'Artist',
        'upload_date': '20240101'
    }
    mock_ydl.__enter__ = mocker.Mock(return_value=mock_ydl)
    mock_ydl.__exit__ = mocker.Mock(return_value=False)
    mocker.patch("yodle.YoutubeDL", return_value=mock_ydl)

    # Create fake M4A file
    m4a_path = tmp_path / "Test_Song.m4a"
    m4a_path.write_bytes(b"fake m4a audio data")

    # Mock audio conversion
    mock_audio = mocker.Mock()
    mocker.patch("yodle.AudioSegment.from_file", return_value=mock_audio)

    # Mock mutagen
    mocker.patch("yodle.MUTAGEN_AVAILABLE", True)
    mock_mp3 = mocker.Mock()
    mocker.patch("yodle.MP3", return_value=mock_mp3)

    # Execute download
    downloader = MusicDownloader()
    result = downloader.download("https://youtube.com/watch?v=abc123", tmp_path)

    # Verify pipeline
    assert result.success is True
    mock_audio.export.assert_called_once()  # Conversion happened
    mock_mp3.save.assert_called_once()  # Tags saved

def test_cookie_extraction_integration(tmp_path, mocker):
    """Test cookie extraction and use in download."""
    # Mock browser cookies
    mock_cookie = mocker.Mock()
    mock_cookie.domain = ".youtube.com"
    mock_cookie.name = "CONSENT"
    mock_cookie.value = "YES+1"
    mocker.patch("browsercookie.chrome", return_value=[mock_cookie])

    cookies_path = tmp_path / "cookies.txt"
    mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

    # Extract cookies
    extracted = CookieManager.extract_cookies("chrome")
    assert extracted == cookies_path

    # Use in downloader
    downloader = VideoDownloader(cookies_path=extracted)
    opts = downloader._get_opts(tmp_path)

    assert opts['cookiefile'] == str(cookies_path)

def test_playlist_download_flow(tmp_path, mocker):
    """Test playlist detection, expansion, and batch download."""
    # Mock playlist info
    mocker.patch("yodle.is_playlist", return_value=True)

    manager = DownloadManager(tmp_path)
    mocker.patch.object(
        manager,
        '_get_playlist_info',
        return_value=("My Playlist", [
            {'url': 'https://youtube.com/watch?v=1', 'title': 'Song 1'},
            {'url': 'https://youtube.com/watch?v=2', 'title': 'Song 2'},
        ])
    )

    # Mock individual downloads
    download_results = []
    def mock_download_single(url, dl_type, output_dir):
        result = DownloadResult(
            success=True,
            url=url,
            title=f"Title for {url}",
            download_type=dl_type
        )
        download_results.append(result)
        return [result]

    mocker.patch.object(manager, '_download_single', side_effect=mock_download_single)

    # Execute
    results = manager.download(["https://youtube.com/playlist?list=PLxxx"], "music")

    # Verify
    assert len(results) == 2
    assert all(r.success for r in results)

@pytest.mark.integration
@pytest.mark.slow
def test_real_video_download_smoke_test(tmp_path):
    """
    Smoke test with real Creative Commons video.

    Uses: "Creative Commons - Elephants Dream" (short clip)
    URL: https://www.youtube.com/watch?v=TLkA0RELQ1g
    License: Creative Commons Attribution 3.0
    Duration: ~1 minute

    This test is marked as @slow and should be run separately.
    """
    # Skip if running in CI without network
    pytest.importorskip("requests")

    downloader = VideoDownloader()
    result = downloader.download(
        "https://www.youtube.com/watch?v=TLkA0RELQ1g",
        tmp_path
    )

    # Verify download succeeded
    assert result.success is True
    assert result.title is not None

    # Verify file was created
    downloaded_files = list(tmp_path.glob("*.mp4"))
    assert len(downloaded_files) > 0
    assert downloaded_files[0].stat().st_size > 0
```

**Mocking Strategy**: Mock external dependencies (yt-dlp, network) but allow internal components to interact.

---

## GUI Tests - Limited Scope

### Rationale for Minimal GUI Testing
Tkinter GUI testing is **brittle, slow, and requires display server access**. The cost-benefit ratio is poor because:

1. **Threading complexity**: GUI runs on main thread, downloads on worker thread
2. **Platform-specific**: Different behavior on macOS/Linux/Windows
3. **Headless CI issues**: Requires Xvfb or similar display mocking
4. **Better alternatives**: Manual testing with real user flows

### Recommended GUI Testing Approach
**Manual test protocol** instead of automated tests:

```markdown
## Manual GUI Test Checklist

### Startup
- [ ] Window opens with correct title and size
- [ ] Update banner appears if yt-dlp is outdated
- [ ] No errors in console logs

### URL Input
- [ ] Single URL downloads correctly
- [ ] Multiple URLs (one per line) all process
- [ ] Empty input shows warning

### Download Types
- [ ] Video-only download creates .mp4 file
- [ ] Music-only download creates .mp3 file
- [ ] Both downloads creates both files
- [ ] Thumbnails mode works with channel URL
- [ ] Thumbnails mode rejects non-channel URL

### Cookie Selection
- [ ] None: download works for public videos
- [ ] Chrome: cookies extracted and used
- [ ] Firefox: cookies extracted and used

### Progress & Status
- [ ] Progress bar updates during download
- [ ] Status log shows timestamps
- [ ] Completion message appears

### Error Handling
- [ ] Invalid URL shows error in log
- [ ] Network error doesn't crash app
- [ ] Missing ffmpeg shows error dialog
```

### Limited Automated GUI Tests

Only test **queue communication** (core risk area):

```python
def test_gui_queue_processing(mocker):
    """Test message queue processing between threads."""
    app = YodleGUI()

    # Send progress message
    app.message_queue.put(("progress", (50.0, "01:00")))
    app._process_queue()

    assert app.progress_var.get() == 50.0
    assert "50%" in app.progress_label.cget("text")

def test_gui_queue_log_message(mocker):
    """Test log message processing."""
    app = YodleGUI()

    app.message_queue.put(("log", "Test message"))
    app._process_queue()

    log_content = app.log_text.get("1.0", "end")
    assert "Test message" in log_content

def test_gui_download_complete_updates_ui(mocker):
    """Test UI updates on download completion."""
    app = YodleGUI()
    app.is_downloading = True

    results = [
        DownloadResult(success=True, url="url1", download_type="video"),
        DownloadResult(success=False, url="url2", error="Error", download_type="video")
    ]

    app._download_complete(results)

    assert app.is_downloading is False
    assert app.download_btn.cget("text") == "DOWNLOAD"
    assert app.progress_var.get() == 100
```

**Mocking**: Minimal - test actual queue and variable objects.

---

## Test Fixtures - conftest.py

### Shared Fixtures

```python
import pytest
from pathlib import Path
from unittest.mock import Mock

@pytest.fixture
def tmp_output_dir(tmp_path):
    """Temporary output directory for downloads."""
    output_dir = tmp_path / "yodle_output"
    output_dir.mkdir()
    return output_dir

@pytest.fixture
def mock_yt_dlp_info():
    """Mock yt-dlp info dictionary."""
    return {
        'title': 'Test Video',
        'id': 'abc123',
        'uploader': 'Test Channel',
        'upload_date': '20240101',
        'ext': 'mp4',
        'thumbnail': 'https://example.com/thumb.jpg'
    }

@pytest.fixture
def mock_youtube_cookie():
    """Mock browser cookie object."""
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
    """Mock progress callback function."""
    return Mock()

@pytest.fixture
def sample_m4a_file(tmp_path):
    """Minimal valid M4A file for conversion tests."""
    # Create minimal M4A header
    m4a_path = tmp_path / "sample.m4a"
    m4a_path.write_bytes(b"fake m4a audio data")
    return m4a_path

@pytest.fixture
def sample_thumbnail(tmp_path):
    """Small PNG thumbnail for resize tests."""
    from PIL import Image

    thumb_path = tmp_path / "thumb.png"
    img = Image.new('RGB', (1920, 1080), color='red')
    img.save(thumb_path)
    return thumb_path

@pytest.fixture(autouse=True)
def cleanup_temp_files():
    """Cleanup temporary files after each test."""
    yield
    # Cleanup logic if needed

@pytest.fixture
def mock_ffmpeg_available(mocker):
    """Mock ffmpeg as available."""
    mocker.patch("yodle.check_ffmpeg", return_value=True)
```

### Pytest Configuration

```python
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests as integration tests",
    "gui: marks tests that require display server"
]
addopts = [
    "-v",
    "-ra",
    "--strict-markers",
    "--tb=short",
    "--cov=yodle",
    "--cov-report=term-missing",
    "--cov-report=html"
]
testpaths = ["tests"]
```

---

## Mocking Strategy Summary

### What to Mock

| Component | Mock? | Reason |
|-----------|-------|--------|
| YoutubeDL | YES | Avoid network calls, control responses |
| browsercookie | YES | Avoid reading actual browser DBs |
| requests.get | YES | PyPI API calls are external |
| subprocess.run | YES | ffmpeg checks don't need real binary |
| AudioSegment | YES | Audio conversion is slow |
| PIL.Image | PARTIAL | Mock network downloads, test resize logic |
| File I/O | NO | Use tmp_path for real file operations |
| Path operations | NO | Test actual path logic |
| queue.Queue | NO | Test actual queue behavior |

### Mocking Tools

- **pytest-mock**: Unified mocking interface (`mocker` fixture)
- **unittest.mock**: `Mock`, `MagicMock`, `patch`
- **responses** (optional): HTTP request mocking for requests library

---

## Test Execution Strategy

### Local Development

```bash
# Run all fast tests (default)
pytest

# Run all tests including slow integration
pytest -m ""

# Run only unit tests
pytest tests/test_utilities.py tests/test_cookie_manager.py

# Run with coverage
pytest --cov=yodle --cov-report=html

# Run specific test
pytest tests/test_utilities.py::test_sanitize_filename

# Watch mode during development
pytest-watch
```

### CI/CD Pipeline

```yaml
# .github/workflows/test.yml (GitHub Actions example)
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install ffmpeg
        run: sudo apt-get install -y ffmpeg

      - name: Install dependencies
        run: |
          pip install pytest pytest-mock pytest-asyncio pytest-cov
          pip install -r requirements.txt

      - name: Run fast tests
        run: pytest -m "not slow" --cov=yodle --cov-report=xml

      - name: Run integration tests (scheduled)
        if: github.event_name == 'schedule'
        run: pytest -m integration

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

### Test Timing Budgets

- **Unit tests**: Each test <100ms, total suite <5s
- **Integration tests**: Each test <5s, total suite <30s
- **E2E tests**: Each test <60s, run only on-demand

---

## Coverage Goals

### Coverage Targets by Component

| Component | Line Coverage | Branch Coverage |
|-----------|---------------|-----------------|
| Utility functions | 100% | 100% |
| CookieManager | 90% | 85% |
| UpdateChecker | 85% | 80% |
| VideoDownloader | 80% | 75% |
| MusicDownloader | 85% | 80% |
| ThumbnailDownloader | 80% | 75% |
| DownloadManager | 85% | 80% |
| YodleGUI | 40% | 30% (manual testing) |
| **Overall** | **80%** | **75%** |

### What NOT to Test

1. **Tkinter internals**: `tk.Tk()`, widget creation
2. **yt-dlp download logic**: Trust the library
3. **ffmpeg encoding**: Trust the tool
4. **Browser DB structure**: browsercookie responsibility
5. **Network protocols**: HTTP/HTTPS handling

---

## Test Anti-Patterns to Avoid

### DON'T Test Implementation Details

```python
# BAD: Testing internal variable names
def test_downloader_has_cookies_path():
    downloader = VideoDownloader()
    assert hasattr(downloader, 'cookies_path')  # Brittle!

# GOOD: Testing behavior
def test_downloader_uses_cookies_when_provided(tmp_path):
    cookies_path = tmp_path / "cookies.txt"
    downloader = VideoDownloader(cookies_path=cookies_path)
    opts = downloader._get_opts(tmp_path)
    assert opts['cookiefile'] == str(cookies_path)
```

### DON'T Over-Mock

```python
# BAD: Mocking everything
def test_sanitize_filename(mocker):
    mocker.patch("re.sub", return_value="mocked")
    result = sanitize_filename("test")
    assert result == "mocked"  # Not testing real logic!

# GOOD: Test actual function
def test_sanitize_filename():
    result = sanitize_filename("Test: Video / Part 1")
    assert result == "Test_Video_Part_1"
```

### DON'T Write Flaky Tests

```python
# BAD: Timing-dependent test
def test_download_speed():
    start = time.time()
    download()
    assert time.time() - start < 1.0  # Flaky!

# GOOD: Test completion, not speed
def test_download_completes(mocker):
    mock_ydl = mocker.Mock()
    mock_ydl.extract_info.return_value = {'title': 'Test'}
    result = downloader.download(url)
    assert result.success is True
```

---

## Maintenance Guidelines

### When to Update Tests

1. **Bug fixes**: Add regression test BEFORE fixing
2. **New features**: Write tests alongside implementation
3. **Refactoring**: Update tests to match new interfaces
4. **Dependencies**: Update mocks when library APIs change

### Test Smells to Watch For

- **Identical setup** in multiple tests → Extract to fixture
- **Tests pass when code is broken** → Over-mocking
- **Tests fail randomly** → Timing issues, shared state
- **Tests take >10s** → Mock expensive operations
- **Tests need manual updates** → Testing implementation details

### Test Review Checklist

- [ ] Tests are isolated (no shared state)
- [ ] Tests have descriptive names
- [ ] Tests test one thing each
- [ ] Mocks are minimal and necessary
- [ ] Edge cases are covered
- [ ] Error paths are tested
- [ ] Tests run fast (<100ms each for unit tests)
- [ ] Tests are deterministic (no randomness)

---

## Next Steps

### Implementation Order

1. **Setup** (15 min)
   - Create `tests/` directory structure
   - Write `conftest.py` with base fixtures
   - Configure pytest in `pyproject.toml`

2. **Unit Tests - Utilities** (30 min)
   - `test_utilities.py` (sanitize, is_playlist, is_channel, check_ffmpeg)
   - Start with simplest pure functions

3. **Unit Tests - CookieManager** (45 min)
   - `test_cookie_manager.py`
   - Mock browsercookie library

4. **Unit Tests - UpdateChecker** (30 min)
   - `test_update_checker.py`
   - Mock requests.get

5. **Unit Tests - Downloaders** (2 hours)
   - `test_video_downloader.py`
   - `test_music_downloader.py`
   - `test_thumbnail_downloader.py`
   - Mock YoutubeDL, AudioSegment, PIL

6. **Unit Tests - DownloadManager** (1 hour)
   - `test_download_manager.py`
   - Integration of downloader classes

7. **Integration Tests** (1 hour)
   - `test_integration.py`
   - End-to-end mocked workflows

8. **CI Setup** (30 min)
   - GitHub Actions workflow
   - Coverage reporting

**Total Estimated Time**: 6-7 hours

---

## Conclusion

This test strategy prioritizes:

1. **Fast, reliable unit tests** (70% of effort) for business logic
2. **Targeted integration tests** (20% of effort) for component interaction
3. **Minimal E2E tests** (10% of effort) for smoke testing
4. **Manual GUI testing** instead of brittle automated GUI tests

The strategy balances comprehensive coverage (80%+ for critical code) with maintainability, ensuring tests provide value without becoming a burden. By mocking external dependencies and testing behavior over implementation, tests remain resilient to refactoring.

**Key Success Metrics**:
- Test suite runs in <5s for fast feedback
- Coverage >80% for critical business logic
- Zero flaky tests
- Tests serve as living documentation
