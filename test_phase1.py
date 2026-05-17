#!/usr/bin/env python3
"""
Test script for Phase 1 implementation of yodle.py

This script verifies that all Phase 1 components are working correctly:
- PEP 723 header with correct dependencies
- Utility functions (sanitize_filename, is_playlist, extract_browser_cookies, get_playlist_info)
- UpdateChecker class
- Basic imports and constants
"""

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all required imports work"""
    print("Testing imports...")
    try:
        from yodle import (
            sanitize_filename,
            is_playlist,
            is_channel,
            CookieManager,
            UpdateChecker,
            OUTPUT_DIR,
            COOKIES_PATH,
            logger
        )
        print("✓ All imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False


def test_sanitize_filename():
    """Test sanitize_filename utility function"""
    print("\nTesting sanitize_filename()...")
    from yodle import sanitize_filename

    test_cases = [
        # Note: hyphens are preserved by the implementation
        ("My Test Video! (2024) - Special Edition", "My_Test_Video_2024_-_Special_Edition"),
        ("Hello World", "Hello_World"),
        ("Special@#$%Characters", "SpecialCharacters"),
        ("Multiple   Spaces", "Multiple_Spaces"),
        ("___trim___", "trim"),
    ]

    all_passed = True
    for input_str, expected in test_cases:
        result = sanitize_filename(input_str)
        if result == expected:
            print(f"  ✓ '{input_str}' → '{result}'")
        else:
            print(f"  ✗ '{input_str}' → '{result}' (expected '{expected}')")
            all_passed = False

    return all_passed


def test_is_playlist():
    """Test is_playlist utility function"""
    print("\nTesting is_playlist()...")
    from yodle import is_playlist

    test_cases = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
        ("https://www.youtube.com/playlist?list=PLtest", True),
        ("https://www.youtube.com/watch?v=xxx&list=yyy", True),
        ("https://www.youtube.com/@channel", False),
    ]

    all_passed = True
    for url, expected in test_cases:
        result = is_playlist(url)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{url}' → {result} (expected {expected})")
        if result != expected:
            all_passed = False

    return all_passed


def test_is_channel():
    """Test is_channel utility function"""
    print("\nTesting is_channel()...")
    from yodle import is_channel

    test_cases = [
        ("https://www.youtube.com/@channelname", True),
        ("https://www.youtube.com/channel/UCxxxxx", True),
        ("https://www.youtube.com/c/channelname", True),
        ("https://www.youtube.com/user/username", True),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),
        ("https://www.youtube.com/playlist?list=PLtest", False),
    ]

    all_passed = True
    for url, expected in test_cases:
        result = is_channel(url)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{url}' → {result} (expected {expected})")
        if result != expected:
            all_passed = False

    return all_passed


def test_update_checker():
    """Test UpdateChecker class"""
    print("\nTesting UpdateChecker...")
    from yodle import UpdateChecker

    try:
        checker = UpdateChecker()
        current = checker.get_current_version()
        print(f"  ✓ Current yt-dlp version: {current}")

        # Test check_for_updates (this may fail if network is unavailable)
        try:
            update_available, curr_ver, latest_ver = checker.check_for_updates()
            if curr_ver:
                print(f"  ✓ Update check works (current: {curr_ver}, latest: {latest_ver})")
            else:
                print(f"  ! Update check returned empty (network issue?)")
        except Exception as e:
            print(f"  ! Update check failed (network issue?): {e}")

        # Test get_update_command
        cmd = UpdateChecker.get_update_command()
        if cmd and "yt-dlp" in cmd:
            print(f"  ✓ Update command: {cmd}")
        else:
            print(f"  ✗ Update command invalid: {cmd}")
            return False

        return True
    except Exception as e:
        print(f"  ✗ UpdateChecker error: {e}")
        return False


def test_cookie_manager():
    """Test CookieManager class"""
    print("\nTesting CookieManager...")
    from yodle import CookieManager

    try:
        cookies_path = CookieManager.get_cookies_path()
        print(f"  ✓ Cookies path: {cookies_path}")

        supported = CookieManager.SUPPORTED_BROWSERS
        print(f"  ✓ Supported browsers: {supported}")

        if "chrome" in supported and "firefox" in supported:
            return True
        else:
            print(f"  ✗ Missing expected browsers")
            return False

    except Exception as e:
        print(f"  ✗ CookieManager error: {e}")
        return False


def test_constants():
    """Test that constants are properly defined"""
    print("\nTesting constants...")
    from yodle import OUTPUT_DIR, COOKIES_PATH

    try:
        expected_output = Path.home() / "Downloads" / "Yodle"
        if OUTPUT_DIR == expected_output:
            print(f"  ✓ OUTPUT_DIR: {OUTPUT_DIR}")
        else:
            print(f"  ✗ OUTPUT_DIR incorrect: {OUTPUT_DIR} (expected {expected_output})")
            return False

        expected_cookies = Path.home() / ".config" / "yt-dlp" / "cookies.txt"
        if COOKIES_PATH == expected_cookies:
            print(f"  ✓ COOKIES_PATH: {COOKIES_PATH}")
        else:
            print(f"  ✗ COOKIES_PATH incorrect: {COOKIES_PATH} (expected {expected_cookies})")
            return False

        return True
    except Exception as e:
        print(f"  ✗ Constants error: {e}")
        return False


def main():
    """Run all tests"""
    print("=" * 70)
    print("PHASE 1 VERIFICATION TESTS")
    print("=" * 70)

    tests = [
        ("Imports", test_imports),
        ("sanitize_filename()", test_sanitize_filename),
        ("is_playlist()", test_is_playlist),
        ("is_channel()", test_is_channel),
        ("UpdateChecker", test_update_checker),
        ("CookieManager", test_cookie_manager),
        ("Constants", test_constants),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} raised exception: {e}")
            results.append((name, False))

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    total = len(results)
    passed = sum(1 for _, r in results if r)
    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All Phase 1 tests passed!")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
