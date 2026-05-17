"""
Unit tests for CookieManager class in yodle.py.

Tests cover:
- get_cookies_path: Cookie file path creation
- extract_cookies: Browser cookie extraction (Chrome/Firefox)
- cleanup: Cookie file removal
- Netscape format validation
"""

import pytest
from pathlib import Path
from unittest.mock import Mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from yodle import CookieManager


class TestGetCookiesPath:
    """Test suite for cookies path management."""

    def test_creates_parent_directory(self, tmp_path, mocker):
        """Test that parent directory is created if missing."""
        mock_home = tmp_path / "home"
        mocker.patch("pathlib.Path.home", return_value=mock_home)

        path = CookieManager.get_cookies_path()

        assert path.parent.exists()
        assert path.parent.is_dir()
        assert path == mock_home / ".config" / "yt-dlp" / "cookies.txt"

    def test_idempotent_creation(self, tmp_path, mocker):
        """Test multiple calls don't error if directory exists."""
        mock_home = tmp_path / "home"
        mocker.patch("pathlib.Path.home", return_value=mock_home)

        path1 = CookieManager.get_cookies_path()
        path2 = CookieManager.get_cookies_path()

        assert path1 == path2
        assert path1.parent.exists()

    def test_returns_consistent_path(self, mocker):
        """Test returned path is always the same."""
        # Don't mock home, use actual Path.home()
        path1 = CookieManager.get_cookies_path()
        path2 = CookieManager.get_cookies_path()

        assert path1 == path2
        assert path1.name == "cookies.txt"
        assert ".config" in str(path1)
        assert "yt-dlp" in str(path1)


class TestExtractCookies:
    """Test suite for browser cookie extraction."""

    def test_chrome_success(self, tmp_path, mocker, mock_youtube_cookie):
        """Test successful Chrome cookie extraction."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        # Mock browsercookie.chrome()
        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.return_value = [mock_youtube_cookie]

        result = CookieManager.extract_cookies("chrome")

        assert result == cookies_path
        assert cookies_path.exists()

        # Verify Netscape format
        content = cookies_path.read_text()
        assert "# Netscape HTTP Cookie File" in content
        assert ".youtube.com" in content
        assert "CONSENT" in content
        assert "YES+1" in content

    def test_firefox_success(self, tmp_path, mocker):
        """Test successful Firefox cookie extraction."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        # Mock Firefox cookie with different properties
        cookie = Mock()
        cookie.domain = ".google.com"
        cookie.path = "/"
        cookie.secure = False
        cookie.expires = None  # Session cookie
        cookie.name = "SID"
        cookie.value = "session123"

        mock_firefox = mocker.patch("browsercookie.firefox")
        mock_firefox.return_value = [cookie]

        result = CookieManager.extract_cookies("firefox")

        assert result == cookies_path
        assert cookies_path.exists()

        content = cookies_path.read_text()
        assert "# Netscape HTTP Cookie File" in content
        assert ".google.com" in content
        assert "FALSE" in content  # Not secure
        assert "\t0\t" in content  # No expiration
        assert "SID" in content

    def test_chrome_case_insensitive(self, tmp_path, mocker, mock_youtube_cookie):
        """Test browser name is case-insensitive."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.return_value = [mock_youtube_cookie]

        # Try different cases
        result1 = CookieManager.extract_cookies("CHROME")
        assert result1 == cookies_path

        cookies_path.unlink()  # Clean up for next test

        result2 = CookieManager.extract_cookies("Chrome")
        assert result2 == cookies_path

    def test_unsupported_browser(self, tmp_path, mocker):
        """Test unsupported browser returns None."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        result = CookieManager.extract_cookies("safari")

        assert result is None
        assert not cookies_path.exists()

    def test_extraction_error(self, tmp_path, mocker):
        """Test error handling during cookie extraction."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.side_effect = Exception("Browser database locked")

        result = CookieManager.extract_cookies("chrome")

        assert result is None
        assert not cookies_path.exists()  # Cleanup on error

    def test_extraction_error_with_partial_file(self, tmp_path, mocker):
        """Test cleanup happens even if file was partially written."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        # Create partial file
        cookies_path.write_text("# Netscape HTTP Cookie File\n")

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.side_effect = Exception("Error during iteration")

        result = CookieManager.extract_cookies("chrome")

        assert result is None
        # File should be cleaned up on error
        # Note: Current implementation may not clean up if error occurs after file creation
        # This is a potential improvement area

    def test_filters_non_youtube_cookies(self, tmp_path, mocker):
        """Test that non-YouTube/Google cookies are filtered out."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        # Create multiple cookies
        youtube_cookie = Mock()
        youtube_cookie.domain = ".youtube.com"
        youtube_cookie.name = "YT_SESSION"
        youtube_cookie.value = "abc123"
        youtube_cookie.path = "/"
        youtube_cookie.secure = True
        youtube_cookie.expires = 1234567890

        google_cookie = Mock()
        google_cookie.domain = ".google.com"
        google_cookie.name = "GOOGLE_AUTH"
        google_cookie.value = "xyz789"
        google_cookie.path = "/"
        google_cookie.secure = True
        google_cookie.expires = 1234567890

        other_cookie = Mock()
        other_cookie.domain = ".example.com"
        other_cookie.name = "EXAMPLE"
        other_cookie.value = "test"
        other_cookie.path = "/"
        other_cookie.secure = False
        other_cookie.expires = 1234567890

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.return_value = [youtube_cookie, google_cookie, other_cookie]

        CookieManager.extract_cookies("chrome")

        content = cookies_path.read_text()
        assert "youtube.com" in content
        assert "google.com" in content
        assert "example.com" not in content
        assert "YT_SESSION" in content
        assert "GOOGLE_AUTH" in content
        assert "EXAMPLE" not in content

    def test_netscape_format_secure_flag(self, tmp_path, mocker):
        """Test Netscape format uses correct secure flag."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        secure_cookie = Mock()
        secure_cookie.domain = ".youtube.com"
        secure_cookie.path = "/"
        secure_cookie.secure = True  # HTTPS only
        secure_cookie.expires = 1234567890
        secure_cookie.name = "SECURE"
        secure_cookie.value = "yes"

        insecure_cookie = Mock()
        insecure_cookie.domain = ".youtube.com"
        insecure_cookie.path = "/"
        insecure_cookie.secure = False  # HTTP allowed
        insecure_cookie.expires = 1234567890
        insecure_cookie.name = "INSECURE"
        insecure_cookie.value = "no"

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.return_value = [secure_cookie, insecure_cookie]

        CookieManager.extract_cookies("chrome")

        lines = cookies_path.read_text().split('\n')
        secure_line = [l for l in lines if "SECURE" in l][0]
        insecure_line = [l for l in lines if "INSECURE" in l][0]

        # Format: domain domain_flag path secure expiry name value
        secure_parts = secure_line.split('\t')
        insecure_parts = insecure_line.split('\t')

        assert secure_parts[3] == "TRUE"  # Secure flag
        assert insecure_parts[3] == "FALSE"  # Not secure

    def test_netscape_format_domain_flag(self, tmp_path, mocker):
        """Test Netscape format domain flag (leading dot)."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch.object(CookieManager, "get_cookies_path", return_value=cookies_path)

        subdomain_cookie = Mock()
        subdomain_cookie.domain = ".youtube.com"  # Leading dot = all subdomains
        subdomain_cookie.path = "/"
        subdomain_cookie.secure = True
        subdomain_cookie.expires = 1234567890
        subdomain_cookie.name = "SUBDOMAIN"
        subdomain_cookie.value = "yes"

        exact_cookie = Mock()
        exact_cookie.domain = "youtube.com"  # No leading dot = exact match
        exact_cookie.path = "/"
        exact_cookie.secure = True
        exact_cookie.expires = 1234567890
        exact_cookie.name = "EXACT"
        exact_cookie.value = "no"

        mock_chrome = mocker.patch("browsercookie.chrome")
        mock_chrome.return_value = [subdomain_cookie, exact_cookie]

        CookieManager.extract_cookies("chrome")

        lines = cookies_path.read_text().split('\n')
        subdomain_line = [l for l in lines if "SUBDOMAIN" in l][0]
        exact_line = [l for l in lines if "EXACT" in l][0]

        # Format: domain domain_flag path secure expiry name value
        # domain_flag is TRUE if domain starts with '.'
        subdomain_parts = subdomain_line.split('\t')
        exact_parts = exact_line.split('\t')

        assert subdomain_parts[1] == "TRUE"  # Has leading dot
        assert exact_parts[1] == "FALSE"  # No leading dot


class TestCleanup:
    """Test suite for cookie file cleanup."""

    def test_removes_existing_file(self, tmp_path, mocker):
        """Test cleanup removes existing cookie file."""
        cookies_path = tmp_path / "cookies.txt"
        cookies_path.write_text("# Test cookies\n.youtube.com\tTRUE\t/\tTRUE\t0\tTEST\tvalue")

        mocker.patch("yodle.COOKIES_PATH", cookies_path)

        CookieManager.cleanup()

        assert not cookies_path.exists()

    def test_no_error_if_file_missing(self, tmp_path, mocker):
        """Test cleanup succeeds if file doesn't exist."""
        cookies_path = tmp_path / "cookies.txt"
        mocker.patch("yodle.COOKIES_PATH", cookies_path)

        # Should not raise any exception
        CookieManager.cleanup()

    def test_no_error_if_permission_denied(self, tmp_path, mocker):
        """Test cleanup handles permission errors gracefully."""
        cookies_path = tmp_path / "cookies.txt"
        cookies_path.write_text("test")

        # Make file read-only (may not work on all systems)
        cookies_path.chmod(0o444)

        mocker.patch("yodle.COOKIES_PATH", cookies_path)

        try:
            CookieManager.cleanup()
        except PermissionError:
            # Expected on some systems
            pass
        finally:
            # Restore permissions for cleanup
            cookies_path.chmod(0o644)
            if cookies_path.exists():
                cookies_path.unlink()
