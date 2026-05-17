"""
Unit tests for UpdateChecker class in yodle.py.

Tests cover:
- get_current_version: Retrieving installed yt-dlp version
- check_for_updates: Comparing versions against PyPI
- Version comparison logic (calendar versioning)
- Error handling for network failures
"""

import pytest
from unittest.mock import Mock
import requests

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from yodle import UpdateChecker


class TestGetCurrentVersion:
    """Test suite for getting current yt-dlp version."""

    def test_returns_version_string(self, mocker):
        """Test getting installed yt-dlp version."""
        # Mock the yt_dlp module
        mock_yt_dlp = Mock()
        mock_yt_dlp.version.__version__ = "2024.12.01"

        # Patch the import
        mocker.patch("yodle.yt_dlp", mock_yt_dlp)

        checker = UpdateChecker()
        version = checker.get_current_version()

        assert version == "2024.12.01"

    def test_handles_dev_versions(self, mocker):
        """Test handling development/pre-release versions."""
        mock_yt_dlp = Mock()
        mock_yt_dlp.version.__version__ = "2024.12.01.dev0"

        mocker.patch("yodle.yt_dlp", mock_yt_dlp)

        checker = UpdateChecker()
        version = checker.get_current_version()

        assert "dev" in version


class TestCheckForUpdates:
    """Test suite for update checking logic."""

    def test_update_available(self, mocker):
        """Test when update is available."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")

        # Mock PyPI response
        mock_response = Mock()
        mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
        mock_response.raise_for_status = Mock()

        mocker.patch("requests.get", return_value=mock_response)

        update_available, current, latest = checker.check_for_updates()

        assert update_available is True
        assert current == "2024.01.01"
        assert latest == "2024.12.01"

    def test_no_update_same_version(self, mocker):
        """Test when already up-to-date."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.12.01")

        mock_response = Mock()
        mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
        mock_response.raise_for_status = Mock()

        mocker.patch("requests.get", return_value=mock_response)

        update_available, current, latest = checker.check_for_updates()

        assert update_available is False
        assert current == "2024.12.01"
        assert latest == "2024.12.01"

    def test_no_update_newer_local(self, mocker):
        """Test when local version is newer (dev version scenario)."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2025.01.01")

        mock_response = Mock()
        mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
        mock_response.raise_for_status = Mock()

        mocker.patch("requests.get", return_value=mock_response)

        update_available, current, latest = checker.check_for_updates()

        assert update_available is False
        assert current == "2025.01.01"
        assert latest == "2024.12.01"

    def test_version_comparison_calendar_versioning(self, mocker):
        """Test calendar versioning comparison (YYYY.MM.DD format)."""
        checker = UpdateChecker()

        # Test various version comparisons
        test_cases = [
            ("2024.01.01", "2024.12.31", True),   # Update available
            ("2024.06.15", "2024.06.16", True),   # Day increment
            ("2024.11.30", "2024.12.01", True),   # Month increment
            ("2023.12.31", "2024.01.01", True),   # Year increment
            ("2024.12.01", "2024.12.01", False),  # Same version
            ("2024.12.01", "2024.11.30", False),  # Local newer
        ]

        for current, latest, expected_update in test_cases:
            mocker.patch.object(checker, "get_current_version", return_value=current)

            mock_response = Mock()
            mock_response.json.return_value = {"info": {"version": latest}}
            mock_response.raise_for_status = Mock()

            mocker.patch("requests.get", return_value=mock_response)

            update_available, _, _ = checker.check_for_updates()

            assert update_available == expected_update, \
                f"Failed: {current} vs {latest} (expected update={expected_update})"

    def test_network_error_handling(self, mocker):
        """Test graceful handling of network errors."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")
        mocker.patch("requests.get", side_effect=requests.RequestException("Network error"))

        update_available, current, latest = checker.check_for_updates()

        assert update_available is False
        assert current == ""
        assert latest == ""

    def test_timeout_handling(self, mocker):
        """Test timeout handling."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")
        mocker.patch("requests.get", side_effect=requests.Timeout("Request timed out"))

        update_available, current, latest = checker.check_for_updates()

        assert update_available is False
        assert current == ""
        assert latest == ""

    def test_invalid_json_response(self, mocker):
        """Test handling of invalid JSON response."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")

        mock_response = Mock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status = Mock()

        mocker.patch("requests.get", return_value=mock_response)

        update_available, current, latest = checker.check_for_updates()

        assert update_available is False
        assert current == ""
        assert latest == ""

    def test_http_error_handling(self, mocker):
        """Test handling of HTTP errors (404, 500, etc.)."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        mocker.patch("requests.get", return_value=mock_response)

        update_available, current, latest = checker.check_for_updates()

        assert update_available is False

    def test_pypi_url_correct(self, mocker):
        """Test that correct PyPI API endpoint is used."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")

        mock_get = mocker.patch("requests.get")
        mock_response = Mock()
        mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        checker.check_for_updates()

        # Verify correct URL was called
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert call_args[0][0] == "https://pypi.org/pypi/yt-dlp/json"
        assert call_args[1].get("timeout") == 5

    def test_timeout_parameter(self, mocker):
        """Test that timeout parameter is set correctly."""
        checker = UpdateChecker()
        mocker.patch.object(checker, "get_current_version", return_value="2024.01.01")

        mock_get = mocker.patch("requests.get")
        mock_response = Mock()
        mock_response.json.return_value = {"info": {"version": "2024.12.01"}}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        checker.check_for_updates()

        # Verify timeout was set
        call_args = mock_get.call_args
        assert call_args[1]["timeout"] == 5


class TestGetUpdateCommand:
    """Test suite for update command generation."""

    def test_returns_uv_pip_command(self):
        """Test that update command uses uv pip."""
        cmd = UpdateChecker.get_update_command()

        assert "uv pip install" in cmd
        assert "--upgrade" in cmd
        assert "yt-dlp" in cmd

    def test_command_is_static_method(self):
        """Test that get_update_command is a static method."""
        # Should work without instantiating
        cmd = UpdateChecker.get_update_command()
        assert isinstance(cmd, str)
        assert len(cmd) > 0
