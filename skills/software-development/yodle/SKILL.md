---
name: yodle-install-run
description: Install, run, and test the yodle YouTube downloader.
version: 0.1.0
author: Jeremy Schroeder, Hermes Agent
license: AGPL-3.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [yodle, youtube, downloader, cli, python]
    related_skills: []
---

# Yodle Install & Run Skill

Set up the yodle repository and run its CLI, tests, and diagnostics from a
clean checkout. This skill installs dependencies, verifies ffmpeg, executes
downloads, and validates changes with the test suite. It does not troubleshoot
YouTube server-side errors beyond the triage flow in Pitfalls.

## When to Use

- User asks to install, set up, or run yodle in this repo
- User wants to download a YouTube video, track, or channel thumbnails via CLI
- User asks to run yodle's test suite or verify a code change
- User reports download failures and needs triage (403, missing formats, no ffmpeg)

Don't use for: editing yodle's source (read `CLAUDE.md` for architecture), work
in `archive/` legacy scripts, or downloads that need no yodle involvement
(just give the user a plain `yt-dlp` command).

## Prerequisites

- Python 3.11–3.12 and [uv](https://docs.astral.sh/uv/) (`terminal(command="uv --version")`)
- ffmpeg on PATH: `terminal(command="ffmpeg -version")`
  - macOS: `terminal(command="brew install ffmpeg")`
  - Debian/Ubuntu: `terminal(command="sudo apt install ffmpeg")`
- Network access for downloads and PyPI; `uv sync` resolves everything else
- Quote URLs in zsh — `?` and `&` are glob/foreground metacharacters

## How to Run

Canonical invocation from the repo root:

```bash
terminal(command="uv run yodle.py --help", timeout=120)
terminal(command="uv run yodle -t music 'https://youtu.be/VIDEO_ID'", timeout=1800)
```

`uv run yodle.py` creates `.venv` from `uv.lock` on first use. The console
script `uv run yodle` is equivalent. No URLs prints help and exits (exit 0).

## Quick Reference

```bash
uv sync                                             # install deps only
uv run yodle.py --help                              # full flag table
uv run yodle -t video 'URL'                         # mp4 (default type: both)
uv run yodle -t music --limit 59m 'URL'             # mp3, first 59 minutes
uv run yodle -t music --audio-quality 320 'URL'     # CBR 320k (default: best VBR)
uv run yodle -t music --normalize 'URL'             # loudness-match to -14 LUFS
uv run yodle -t thumbnails 'https://youtube.com/@channel'
uv run yodle -b chrome 'URL'                        # browser cookies, private/age-gated
uv run --with-requirements requirements-test.txt pytest   # test suite
YODLE_OUTPUT_DIR=/tmp/out uv run yodle -t video 'URL'     # override output dir
```

## Procedure

1. **Verify toolchain** — `terminal(command="uv --version")` and
   `terminal(command="ffmpeg -version")` both exit 0. Missing ffmpeg → install
   per Prerequisites before any download.
2. **Install dependencies** — `terminal(command="uv sync")`.
   Done when: exit 0 and `.venv/` exists.
3. **Confirm CLI loads** — `terminal(command="uv run yodle.py --help")`.
   Done when: flag table prints (includes `--limit`, `--audio-quality`,
   `--normalize`) with exit 0.
4. **Run the requested download** — quote the URL; set `YODLE_OUTPUT_DIR` if
   the user wants a non-default location (also readable from project-root
   `.env`). Done when: process exits 0 and the output file exists (default
   `~/Yodle/`).
5. **After code changes** — `terminal(command="uv run --with-requirements requirements-test.txt pytest", timeout=600)`.
   Done when: all tests pass (network smoke tests are skipped by design).

## Pitfalls

- **HTTP 403 with "request was rejected because it was considered high risk"**
  is usually YouTube risk-flagging the session, not a code bug. Triage:
  (1) try a fresh, different video — if it downloads, the code is fine;
  (2) do NOT retry in a loop, it deepens the flag (minutes to hours);
  (3) longer videos flag after 1–2 fetches — budget one fetch per video when
  testing; (4) private/age-gated → `-b chrome` with the browser closed first,
  or `--cookies-file PATH`.
- **"Requested format is not available"** — `YDL_COMMON_OPTS` pins
  `player_client: ["web", "android_vr"]`. `android` is SABR-limited and `web`
  alone gets risk-rejected. Test clients individually with
  `yt-dlp --extractor-args 'youtube:player_client=X' -F 'URL'` before editing
  the constant.
- **m4a has no cover art / audio sounds double-encoded** — postprocessor order
  and dict-scoped `postprocessor_args` are load-bearing; see `CLAUDE.md`
  Technical Details before touching `MusicDownloader`.
- **`--limit` on music must not set `force_keyframes_at_cuts`** — it would
  drop `-c copy` and double-transcode. Video keeps it for frame-accurate cuts.
- `tests/skills/test_yodle_skill.py` validates this skill file; frontmatter
  description must stay ≤60 chars ending in a period.

## Verification

- `terminal(command="uv run yodle.py --help", timeout=120)` exits 0 and lists
  the current flags (`--limit`, `--audio-quality`, `--normalize`).
- `terminal(command="uv run --with-requirements requirements-test.txt pytest -q", timeout=600)`
  exits 0 with no failures.
- A probe download lands a non-empty file in the output directory (use a short
  `--limit 10s` on a fresh video to avoid risk-flagging).
