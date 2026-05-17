# Yodle Test Suite

Comprehensive test suite for the Yodle YouTube downloader, following the testing pyramid principle with unit, integration, and end-to-end tests.

## Quick Start

### Installation

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Or with uv
uv pip install -r requirements-test.txt
```

### Running Tests

```bash
# Run all tests (fast tests only)
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_utilities.py

# Run specific test
pytest tests/test_utilities.py::TestSanitizeFilename::test_simple_title

# Run with coverage report
pytest --cov=yodle --cov-report=html

# Run tests in parallel (faster)
pytest -n auto
```

### Test Categories

```bash
# Run only fast unit tests (default)
pytest -m "not slow"

# Run integration tests
pytest -m integration

# Run slow tests (includes real downloads)
pytest -m slow

# Run everything including slow tests
pytest -m ""
```

## Test Structure

```
tests/
├── README.md                    # This file
├── __init__.py                  # Package marker
├── conftest.py                  # Shared fixtures
├── test_utilities.py            # Utility function tests
├── test_cookie_manager.py       # Cookie extraction tests
├── test_update_checker.py       # Update checking tests
├── test_integration.py          # Integration tests
└── fixtures/                    # Test data (future)
```

## Test Coverage

### Current Test Files

| File | Purpose | Test Count | Coverage Target |
|------|---------|------------|-----------------|
| `test_utilities.py` | Utility functions | 30+ | 100% |
| `test_cookie_manager.py` | Cookie extraction | 15+ | 90% |
| `test_update_checker.py` | Update checking | 12+ | 85% |
| `test_integration.py` | End-to-end flows | 10+ | 80% |

### Coverage Goals

- **Overall**: 80%+ line coverage
- **Utility functions**: 100% coverage
- **Business logic**: 85%+ coverage
- **GUI components**: 40% coverage (mostly manual testing)

## Writing Tests

### Test Organization

Tests follow the Arrange-Act-Assert pattern:

```python
def test_sanitize_filename():
    # Arrange: Set up test data
    input_title = "Video: Part 1 / 2"

    # Act: Execute the function
    result = sanitize_filename(input_title)

    # Assert: Verify the result
    assert result == "Video_Part_1_2"
```

### Using Fixtures

Shared fixtures are defined in `conftest.py`:

```python
def test_with_temp_dir(tmp_output_dir):
    """tmp_output_dir is a fixture from conftest.py"""
    file_path = tmp_output_dir / "test.txt"
    file_path.write_text("test")
    assert file_path.exists()

def test_with_mock_data(mock_yt_dlp_info):
    """mock_yt_dlp_info is a fixture with video metadata"""
    assert mock_yt_dlp_info['title'] == 'Test Video'
```

### Mocking External Dependencies

Use `pytest-mock` for clean mocking:

```python
def test_with_mocked_network(mocker):
    """mocker is provided by pytest-mock"""
    mock_response = mocker.Mock()
    mock_response.json.return_value = {"version": "2024.12.01"}

    mocker.patch("requests.get", return_value=mock_response)

    # Now requests.get will return our mock
    result = some_function_that_uses_requests()
    assert result is not None
```

### Testing Async Code

Use `pytest-asyncio` for async tests:

```python
import pytest

@pytest.mark.asyncio
async def test_async_download(tmp_path):
    """Test async thumbnail download"""
    downloader = ThumbnailDownloader()
    result = await downloader.download_thumbnail(url, tmp_path, "video_id")
    assert result is True
```

## Common Test Patterns

### Testing File Operations

```python
def test_file_creation(tmp_path):
    """Use pytest's tmp_path fixture for file tests"""
    output_file = tmp_path / "output.txt"
    write_file(output_file, "content")

    assert output_file.exists()
    assert output_file.read_text() == "content"
```

### Testing Error Handling

```python
def test_handles_network_error(mocker):
    """Test error handling with mocked exceptions"""
    mocker.patch("requests.get", side_effect=requests.RequestException())

    result = function_that_makes_request()

    # Should handle error gracefully
    assert result.success is False
    assert "error" in result.error.lower()
```

### Testing Progress Callbacks

```python
def test_progress_callback(mocker):
    """Test progress callback is invoked"""
    callback = mocker.Mock()
    downloader = VideoDownloader(progress_callback=callback)

    # Simulate progress
    downloader._progress_hook({
        'status': 'downloading',
        '_percent_str': '50%'
    })

    callback.assert_called_once_with(50.0, mocker.ANY)
```

## Test Anti-Patterns to Avoid

### DON'T Test Implementation Details

```python
# BAD - tests internal variable names
def test_has_attribute():
    obj = SomeClass()
    assert hasattr(obj, '_internal_var')  # Brittle!

# GOOD - tests behavior
def test_behavior():
    obj = SomeClass()
    result = obj.public_method()
    assert result == expected_value
```

### DON'T Over-Mock

```python
# BAD - mocking everything
def test_overmocked(mocker):
    mocker.patch("re.sub", return_value="mocked")
    result = sanitize_filename("test")
    # Not testing real logic!

# GOOD - test actual function
def test_real_logic():
    result = sanitize_filename("Test: Video")
    assert result == "Test_Video"
```

### DON'T Write Flaky Tests

```python
# BAD - timing dependent
def test_speed():
    start = time.time()
    download()
    assert time.time() - start < 1.0  # May fail randomly!

# GOOD - test completion
def test_completes():
    result = download()
    assert result.success is True
```

## Debugging Tests

### Run Single Test with Debugging

```bash
# Run with Python debugger
pytest --pdb tests/test_utilities.py::test_sanitize_filename

# Drop into debugger on failure
pytest --pdb -x

# Show print statements
pytest -s

# Show local variables on failure
pytest -l
```

### Using VS Code Debugger

Add to `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Python: Pytest Current File",
            "type": "python",
            "request": "launch",
            "module": "pytest",
            "args": ["${file}", "-v", "-s"],
            "console": "integratedTerminal"
        }
    ]
}
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install ffmpeg
        run: sudo apt-get install -y ffmpeg

      - name: Install dependencies
        run: pip install -r requirements-test.txt

      - name: Run tests
        run: pytest --cov=yodle --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## Coverage Reports

### Generate HTML Coverage Report

```bash
# Generate coverage report
pytest --cov=yodle --cov-report=html

# Open in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Terminal Coverage Report

```bash
# Show coverage in terminal
pytest --cov=yodle --cov-report=term-missing

# Example output:
# Name                     Stmts   Miss  Cover   Missing
# ------------------------------------------------------
# yodle.py                   450     45    90%   123-145, 234-256
# tests/conftest.py           45      0   100%
# tests/test_utilities.py    120      0   100%
```

## Performance Testing

### Measure Test Execution Time

```bash
# Show slowest tests
pytest --durations=10

# Profile test execution
pytest --profile

# Set timeout for tests
pytest --timeout=30
```

## Test Maintenance

### Keep Tests Fast

- Unit tests should run in <100ms each
- Integration tests should run in <5s each
- Total test suite should complete in <30s
- Use mocks to avoid network calls
- Use `tmp_path` for file operations

### Keep Tests Independent

- Each test should be able to run alone
- No shared state between tests
- Use fixtures for setup/teardown
- Don't rely on test execution order

### Keep Tests Readable

- Use descriptive test names
- Follow Arrange-Act-Assert pattern
- Add docstrings to complex tests
- Keep assertions simple and focused

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest-Mock Documentation](https://pytest-mock.readthedocs.io/)
- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)
- [Test-Driven Development](https://testdriven.io/)

## Contributing Tests

When adding new features to Yodle:

1. Write tests BEFORE implementing the feature (TDD)
2. Ensure all tests pass: `pytest`
3. Check coverage: `pytest --cov=yodle`
4. Run slow tests: `pytest -m slow`
5. Update this README if adding new test files

## Questions?

See the main [TEST_STRATEGY.md](/TEST_STRATEGY.md) for detailed testing strategy and architecture decisions.
