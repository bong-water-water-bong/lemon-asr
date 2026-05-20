# Changelog

All notable changes to **lemon-asr** are documented here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-20

### Added

- `lemon_asr.server` — FastAPI + faster-whisper OpenAI-compat ASR
  server. Defaults to `whisper-large-v3-turbo` on CPU at
  `compute_type=int8`. Exposes `POST /v1/audio/transcriptions`,
  `GET /v1/models`, `GET /health`. Also runnable as a
  [PEP 723](https://peps.python.org/pep-0723/) `uv run --script` target
  with zero install ceremony.
- `lemon_asr.glasp` — stdlib-only Glasp markdown ingester. Reads
  `*.md` / `*.txt` from an incoming directory, extracts the YouTube
  video ID (from body URL, filename URL, or 11-char filename prefix),
  resolves the title via the YouTube oEmbed endpoint, and writes
  `<id>__<title>.{txt,srt,json}` in a uniform layout.
- **Edge-trim** — server post-processor that drops low-confidence
  (≤2-word, `avg_logprob < -0.5`) fragments at both the head and tail
  of the segment list. Defeats faster-whisper's "false-start" and
  "tail-decay" failure modes. Calibrated on a 12.4-minute IBM
  Technology sample (131 → 128 segments, removed trailing
  `"that."`/`"So"`/`"you"` at `lp = -0.87`).
- CI matrix: pytest + ruff (lint & format) + mypy on Python 3.11 /
  3.12 / 3.13.
- `docs/youtube-bot-wall.md` — rationale for keeping YouTube intake
  out of this repo.
- `docs/lemond-whisper-segfault.md` — full repro + patchelf workaround
  for the lemonade-server 10.5.1 Vulkan whisper SEGFAULT that motivated
  this project.
- `docs/quality-report.md` — diagnostic methodology and a reference
  result on the IBM Technology sample.

[Unreleased]: https://github.com/bong-water-water-bong/lemon-asr/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bong-water-water-bong/lemon-asr/releases/tag/v0.1.0
