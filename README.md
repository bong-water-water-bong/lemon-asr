# lemon-asr

[![ci](https://github.com/bong-water-water-bong/lemon-asr/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/bong-water-water-bong/lemon-asr/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![local-first](https://img.shields.io/badge/local--first-strix%20halo-2ea44f)](#hardware)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> Local-first ASR pipeline for YouTube transcripts and arbitrary audio,
> built for the AMD Strix Halo workstation.

**→ [Project Wiki](docs/wiki/README.md)** — architecture, decisions, gotchas, and agent onboarding.

`lemon-asr` is a small, two-piece toolkit:

1. **`lemon-asr-server`** — an OpenAI-compatible
   `POST /v1/audio/transcriptions` HTTP server backed by
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Defaults
   to `large-v3-turbo` on CPU at `int8` quantization, which gives
   ~8× realtime on Strix Halo's 16-core CPU with quality
   indistinguishable from `float16` for narration-style audio.

2. **`lemon-asr-ingest`** — a stdlib-only converter that turns
   [Glasp](https://glasp.co/youtube-transcript) markdown into the same
   `txt` / `srt` / `json` layout the server emits, so transcripts land
   in a uniform directory regardless of upstream source.

A third piece — driver code that downloads audio from YouTube — lives
elsewhere (see [`docs/youtube-bot-wall.md`](docs/youtube-bot-wall.md))
because YouTube's PO-Token enforcement is a moving target and we don't
want to couple a stable transcription pipeline to a fragile scraper.

## Why this exists

The Lemonade ecosystem already ships an ASR backend in `lemond` (the
local Lemonade Server). On Strix Halo as of 2026-05-19, that backend
SEGFAULTs during model load on Vulkan — see
[`docs/lemond-whisper-segfault.md`](docs/lemond-whisper-segfault.md) for
the full repro and the local patchelf fix that gets the binary at least
launching. Until upstream fixes the crash, `lemon-asr-server` is the
working ASR drop-in for any tooling that expects an OpenAI-style
endpoint.

## Hardware

Tested on AMD Ryzen AI MAX+ 395 (Strix Halo) on Ubuntu 26.04. Should
work on any x86_64 Linux box; the CPU path has no GPU or NPU dependency.
CTranslate2 (the backend faster-whisper uses) has no ROCm support today,
so the Radeon 8060S iGPU sits idle — that's fine, 16 Zen-5 cores at
`compute_type=int8` are more than enough.

## Install

```bash
git clone https://github.com/bong-water-water-bong/lemon-asr.git
cd lemon-asr

# Full install (ingester + ASR server)
pip install -e ".[server,dev]"

# Or, ingester only — stdlib, no heavy deps
pip install -e ".[dev]"
```

You can also run the server without installing anything, using the
[PEP 723](https://peps.python.org/pep-0723/) inline metadata header:

```bash
uv run --script src/lemon_asr/server.py
```

## Usage

### Start the ASR server

```bash
lemon-asr-server
# Listens on http://127.0.0.1:8004
# Health: GET /health
# Transcribe: POST /v1/audio/transcriptions  (OpenAI Audio API shape)
```

### Transcribe a file

```bash
curl -X POST http://127.0.0.1:8004/v1/audio/transcriptions \
  -F "file=@some-audio.mp3" \
  -F "model=large-v3-turbo" \
  -F "response_format=verbose_json" \
  -F "language=en"
```

`response_format` accepts `json`, `verbose_json`, `text`, `srt`, `vtt`.

### Ingest Glasp markdown

```bash
# Default paths:
#   --incoming  /home/bcloud/Desktop/Shared AI /glasp-incoming/
#   --out-dir   /home/bcloud/Desktop/IBMTechnology-transcripts/last-6-months/transcripts/
lemon-asr-ingest

# Custom paths:
lemon-asr-ingest --incoming ./inbox --out-dir ./transcripts
```

Each successfully ingested file moves to `<incoming>/_done/`. Outputs
land as `<video_id>__<title>.{txt,srt,json}`.

## Tunable knobs (env vars)

| Env var | Default | Effect |
|---|---|---|
| `FW_MODEL` | `large-v3-turbo` | faster-whisper model identifier |
| `FW_DEVICE` | `cpu` | `cpu` / `cuda` / `auto` (no ROCm in CTranslate2 today) |
| `FW_COMPUTE_TYPE` | `int8` | `int8` / `int8_float16` / `float16` / `float32` |
| `FW_HOST` | `127.0.0.1` | bind host |
| `FW_PORT` | `8004` | bind port |
| `FW_BEAM_SIZE` | `5` | decoder beam size |
| `FW_VAD_FILTER` | off | `1` / `true` to enable Silero VAD pre-filter |
| `FW_EDGE_TRIM_LOGPROB` | `-0.5` | drop low-confidence head AND tail segs below this |
| `FW_EDGE_TRIM_MAX_WORDS` | `2` | only edge-trim segs with at most this many words |

### Edge-trim

faster-whisper occasionally emits low-confidence 1–2 word fragments at
the start (false-start audio / leading silence) and end (speaker
trailing off). The server post-processes results to drop those
fragments — sample IBM Tech audio went from 131 → 128 segments,
removing the trailing `"that."`, `"So"`, `"you"` artifacts. Disable by
setting `FW_EDGE_TRIM_LOGPROB=-10`.

## Output format

Each transcript becomes three files in `<out_dir>/`:

```
<video_id>__<sanitized-title>.txt   # plain text, one paragraph
<video_id>__<sanitized-title>.srt   # SubRip subtitles
<video_id>__<sanitized-title>.json  # {video_id, title, source, language, snippets:[{text,start,duration}]}
```

The server output also includes `avg_logprob` and `no_speech_prob` per
segment when called with `response_format=verbose_json` — useful for
post-filtering or quality dashboards.

## Quality benchmarks

On a 12.4-minute IBM Technology dialog (`HtnlUosO3XA`):

- 745.1s audio → 94s wall-clock (`compute_type=int8`, beam_size=5)
- Mean `avg_logprob` -0.10, median -0.09 (0 is theoretical max)
- 100% audio coverage, zero hallucinated boilerplate, zero loop-failures
- All major technical terms transcribed correctly (`agentic AI`,
  `CISOs`, `least privilege`, `zero trust`, `TypeScript`, `Lambda`, …)

See [`docs/quality-report.md`](docs/quality-report.md) for the full
diagnostic methodology.

## Repository layout

```
src/lemon_asr/
  __init__.py    # version, top-level package
  server.py      # FastAPI + faster-whisper OpenAI-compat server
  glasp.py       # Glasp-markdown → txt/srt/json ingester (stdlib-only)
tests/           # pytest suites
docs/            # design notes, repros, quality reports
scripts/         # operator-facing utilities (curl examples, batch drivers)
```

## License

MIT — see [LICENSE](LICENSE).
