# AGENTS.md

Instructions for AI agents working in this repository. Human-facing docs live in
[README.md](README.md); deeper implementation notes for Claude Code live in
[CLAUDE.md](CLAUDE.md). When they conflict, trust the code and the tests.

## What This Is

Yodle is a single-file CLI YouTube downloader (`yodle.py`): videos, music
(mp3/m4a), and channel thumbnails. Dependencies are managed by **uv** via
`pyproject.toml` / `uv.lock`; the console script `yodle` is exposed there too.

## Setup

```bash
# Install uv if needed: https://docs.astral.sh/uv/
uv sync                              # create .venv and install deps from uv.lock

# ffmpeg must be on PATH (downloads fail without it)
ffmpeg -version || brew install ffmpeg   # macOS; use apt install ffmpeg on Debian/Ubuntu
```

Python 3.11–3.12 is required (`requires-python = ">=3.11, <3.13"`).

## Run

```bash
uv run yodle.py                      # no URLs → prints help and exits
uv run yodle -t music --limit 59m 'https://youtu.be/VIDEO_ID'
uv run yodle --help                  # full flag table
```

Quote URLs in zsh — bare `?` and `&` glob/foreground the shell.

## Test

```bash
uv run --with-requirements requirements-test.txt pytest
```

- Suite lives in `tests/` (config in `pytest.ini`); network smoke tests are
  marked and skipped by default.
- Skill-file validation tests live in `tests/skills/` and cover
  `skills/software-development/yodle/SKILL.md` (a Hermes-format install/run
  skill; copy that directory into `~/.hermes/skills/` to activate it in Hermes).
- New behavior needs a failing test first (TDD); keep the suite green.

## Architecture (map)

Key classes in `yodle.py` — grep for these names; the file is ~1000 lines:

| Class / function | Role |
|---|---|
| `CookieManager` | Extracts browser cookies to `~/.config/yt-dlp/cookies.txt` |
| `VideoDownloader` / `MusicDownloader` / `ThumbnailDownloader` | One per `-t` type |
| `DownloadManager` | Orchestrates types, expands playlists |
| `run_download()` / `main()` | argparse CLI entry points |
| `YDL_COMMON_OPTS` | yt-dlp extractor args shared by all downloaders |

Details that are easy to break — read the matching CLAUDE.md section before touching:

- **Player clients**: `YDL_COMMON_OPTS` uses `player_client: ["web", "android_vr"]`
  with `remote_components: ["ejs:github"]`. `android` is SABR-limited (no
  audio-only DASH), `web` alone gets risk-rejected. If formats vanish, re-test
  clients individually before editing code.
- **`--limit` on music must NOT set `force_keyframes_at_cuts`** — it forces
  yt-dlp's ranged FFmpeg download to drop `-c copy` → double lossy transcode.
  Video keeps it (frame-accurate cuts). See `_apply_limit_opts()`.
- **m4a postprocessor order**: `FFmpegExtractAudio` → `FFmpegMetadata` →
  `EmbedThumbnail`. The metadata pass's `-vn` would drop the cover art if
  `EmbedThumbnail` ran first. mp3 order is the reverse — don't "unify" them.
- **m4a `postprocessor_args` must stay dict-form** scoped to
  `"embedthumbnail+ffmpeg"`; list-form args leak into every ffmpeg
  postprocessor.

## Diagnosing YouTube 403s

Before blaming code: format extraction succeeding while googlevideo data
requests return 403 is YouTube **risk-flagging** the session/video (you may see
"The request was rejected because it was considered high risk").

1. Try a different, fresh video — if it works, it's not a code regression.
2. Don't hammer retries; it deepens the flag. Flags last minutes to hours.
3. Longer videos flag after 1–2 fetches; budget one fetch per video when testing.
4. Private/age-restricted content: `-b chrome` (close the browser first) or
   `--cookies-file PATH`.

## Conventions

- Output goes to `~/Yodle` by default, or `$YODLE_OUTPUT_DIR` (also readable
  from a project-root `.env`).
- Docs that must stay in sync with CLI changes: `README.md` (flag sections +
  Recent Updates) and `CLAUDE.md` (flag table + Technical Details).
- Legacy scripts in `archive/` are reference-only — don't extend them.
- Commit style: concise imperative summary (see `git log`).
