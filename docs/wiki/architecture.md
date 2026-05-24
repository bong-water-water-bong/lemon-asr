# Architecture

> lemon-asr is a two-piece local ASR toolkit that provides a reliable OpenAI-compatible transcription endpoint when Lemonade's built-in Whisper backend is broken, plus a Glasp-markdown ingester so transcripts from any upstream source land in a uniform directory layout.

## Overview

The project exists because `lemond` (Lemonade Server 10.x) SEGFAULTs during Whisper model load on Strix Halo due to a Vulkan driver interaction — see `docs/lemond-whisper-segfault.md` for the full repro. `lemon-asr-server` fills that gap with a stable, dependency-minimal HTTP server backed by faster-whisper running on the 16-core Zen-5 CPU. Any caller that speaks the OpenAI Audio API (including the `yt-transcript` orchestrator via `FLM_ASR_BASE_URL`) can point at it and work unchanged.

The second component, the Glasp ingester, solves a separate but related problem: transcripts obtained by copy-pasting from the Glasp YouTube Transcript tool arrive as markdown with a different structure than what the server emits. The ingester normalises them into the same `txt/srt/json` triple so downstream consumers see one canonical layout regardless of how the audio was acquired.

YouTube download tooling is explicitly kept out of this repo because YouTube's PO-Token enforcement is a moving target; the stable transcription pipeline is decoupled from the fragile scraper.

## How It Works

### Server (`server.py`)

`lemon-asr-server` is a FastAPI application launched via Uvicorn. At startup it loads a single `WhisperModel` instance (faster-whisper) with the parameters configured by env vars, then holds that instance for the lifetime of the process.

**Endpoint shape:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/audio/transcriptions` | Transcribe — OpenAI Audio API shape |
| `POST` | `/api/v1/audio/transcriptions` | Alias (for callers using the Lemonade `/api/v1` prefix) |
| `GET` | `/health` or `/v1/health` | Liveness check — returns model name, device, compute_type |
| `GET` | `/v1/models` or `/api/v1/models` | OpenAI-style model list |

**Request fields (multipart form):** `file` (audio binary), `model` (ignored — only one model loaded), `response_format` (`json` / `verbose_json` / `text` / `srt` / `vtt`), `language`, `prompt`, `temperature`.

**Port:** `8004` by default (`FW_PORT`). Bind host defaults to `127.0.0.1` (`FW_HOST`) — loopback only, not exposed on LAN.

**Concurrency:** faster-whisper's `transcribe()` is not reentrant on a single model instance, so requests are serialised with `asyncio.Lock`. Audio is written to a `tempfile` before transcription so the upload streaming does not hold the lock.

**Edge-trim post-processing:** After transcription the server walks inward from both ends of the segment list and drops any segment whose `avg_logprob` is below `FW_EDGE_TRIM_LOGPROB` (default `-0.5`) AND whose word count is at most `FW_EDGE_TRIM_MAX_WORDS` (default `2`). This removes the low-confidence 1–2 word fragments that faster-whisper emits at the start (false-start audio / leading silence) and end (speaker trailing off) of narration-style audio.

**Key env vars:**

| Var | Default | Notes |
|-----|---------|-------|
| `FW_MODEL` | `large-v3-turbo` | Model identifier passed to faster-whisper |
| `FW_DEVICE` | `cpu` | `cpu` / `cuda` / `auto` — no ROCm in CTranslate2 |
| `FW_COMPUTE_TYPE` | `int8` | Quantisation — `int8` gives ~8× realtime on Strix Halo CPU |
| `FW_PORT` | `8004` | Bind port |
| `FW_HOST` | `127.0.0.1` | Bind host |
| `FW_BEAM_SIZE` | `5` | Decoder beam width |
| `FW_VAD_FILTER` | off | Set `1` / `true` to enable Silero VAD pre-filter |
| `FW_EDGE_TRIM_LOGPROB` | `-0.5` | Drop edge segments below this confidence threshold |
| `FW_EDGE_TRIM_MAX_WORDS` | `2` | Only trim edge segments with at most this many words |

**Integration hook:** Callers that previously used Lemonade's ASR endpoint set `FLM_ASR_BASE_URL=http://127.0.0.1:8004/v1` — the path suffix and request shape are compatible.

### Glasp Ingester (`glasp.py`)

`lemon-asr-ingest` is a stdlib-only CLI (`argparse`, `json`, `re`, `shutil`, `urllib.request` — zero pip dependencies). It scans an incoming directory for `*.md` / `*.markdown` / `*.txt` files and converts each one to a `txt/srt/json` triple in the output directory.

**Pipeline per file:**

1. **Video ID extraction** (`find_video_id`): looks for a `youtube.com/watch?v=<id>` / `youtu.be/<id>` URL in the body, then the filename, then treats a filename stem starting with an 11-character base64url string as the ID (convention: `<id>__<title>.md`).
2. **Title fetch** (`fetch_title`): hits `youtube.com/oembed` with a 5-second timeout; falls back to the video ID string on any error.
3. **Segment parsing** (`parse_segments`): regex-walks the file line by line, recognising bracketed (`[M:SS]`, `[H:MM:SS]`) and bare (`M:SS text`) timestamps. Untimestamped lines that appear mid-content are appended to the previous segment. Trailing segments with a stubbed end get an estimated duration of `max(1.0, word_count / 3.0)` seconds.
4. **Output writing** (`write_outputs`): creates `<video_id>__<sanitized-title>.{txt,srt,json}` in the output directory. The JSON uses `snippets` with `{text, start, duration}` — same shape as the server's `verbose_json` segments.
5. **Move to done**: the source file is moved to `<incoming>/_done/` on success. Files that fail ID extraction or produce empty parse results are skipped and left in place; `ingest()` returns `rc=1` if any file was skipped.

**Default paths:**

| Direction | Default | Override |
|-----------|---------|---------|
| Incoming | `/home/bcloud/Desktop/Shared AI /glasp-incoming/` | `--incoming` or `LEMON_ASR_GLASP_INCOMING` |
| Output | `/home/bcloud/Desktop/IBMTechnology-transcripts/last-6-months/transcripts/` | `--out-dir` or `LEMON_ASR_OUTPUT_DIR` |

Note the trailing space in `Shared AI ` — that is the literal directory name on this machine and must be preserved.

### Output File Format

All three consumers (server `verbose_json`, server `srt`/`txt`, and the Glasp ingester) write to the same naming convention and layout:

```
<video_id>__<sanitized-title>.txt    plain text, one paragraph
<video_id>__<sanitized-title>.srt    SubRip subtitles
<video_id>__<sanitized-title>.json   {video_id, title, source, language, snippets:[{text,start,duration}]}
```

The JSON `snippets` list is the canonical machine-readable form and is what downstream indexers or search tools should consume.

## Key Decisions

- **Why faster-whisper instead of OpenAI Whisper directly**: faster-whisper wraps CTranslate2, which provides optimised CPU inference with `int8` quantisation. On Strix Halo's 16-core Zen-5 CPU this delivers ~8× realtime throughput with quality indistinguishable from `float16` for narration-style audio. The original OpenAI Whisper (PyTorch) has no equivalent CPU quantisation path.

- **Why CPU (`int8`) and not GPU**: CTranslate2 has no ROCm support as of the project's creation. The Radeon 8060S iGPU inside Strix Halo is therefore unusable for inference — but 16 Zen-5 cores at `int8` are fast enough that this is not a limitation in practice.

- **Why a standalone server instead of Lemonade's ASR backend**: Lemonade 10.x ships a Whisper ASR path in `lemond`, but on Strix Halo it SEGFAULTs during model load due to a Vulkan driver interaction (unfixed as of 10.6.0). `lemon-asr-server` is the working drop-in until upstream resolves the crash. The OpenAI Audio API shape was chosen so that any caller expecting a Lemonade-style or OpenAI-style endpoint can switch over with a single env var change (`FLM_ASR_BASE_URL`).

- **Why the Glasp ingester is stdlib-only**: The ingester's dependency footprint is deliberately kept at zero. Users who only need to convert already-downloaded Glasp markdown transcripts should not have to install FastAPI, faster-whisper, or any other heavy dependency. The install extras in `pyproject.toml` reflect this: `pip install -e "."` (no extras) gives the ingester only; `pip install -e ".[server]"` adds the ASR server deps.

- **Why YouTube download tooling lives outside this repo**: YouTube's PO-Token enforcement and bot-wall countermeasures change frequently. Coupling a stable transcription pipeline (which has no YouTube dependency) to a fragile scraper would make the whole thing unreliable. The driver code lives elsewhere; this repo only handles audio → text and Glasp markdown → canonical transcript.

- **Why edge-trimming is server-side, not post-hoc**: faster-whisper consistently emits low-confidence 1–2 word fragments at the boundaries of narration-style audio. Baking the trim into the server response means every caller gets clean output without needing to implement their own post-filter. The thresholds are tunable via env vars so the behaviour can be disabled or tightened per deployment.

## Gotchas

- **Do NOT attempt to load Whisper via Lemonade's `/api/v1/load` endpoint** — it causes a Vulkan SEGFAULT on Strix Halo that kills the `lemond` process and evicts all currently loaded LLMs. This bug is unfixed as of Lemonade 10.6.0. `lemon-asr-server` on `:8004` is the correct path. See `docs/lemond-whisper-segfault.md` for the full repro.

- **The `Shared AI ` incoming directory has a trailing space in its name.** This is the literal filesystem path: `/home/bcloud/Desktop/Shared AI /glasp-incoming/`. Shell tab-completion and path quoting will trip on this. The env var `LEMON_ASR_GLASP_INCOMING` is the clean override.

- **The asyncio lock serialises all transcription requests.** Concurrent uploads will queue, not run in parallel. This is intentional — faster-whisper's `WhisperModel` is not thread-safe — but it means high-concurrency workloads need either multiple server instances or a queuing proxy in front.

- **`tempfile` with `delete=True` is used in `server.py`, so the temp file is deleted as soon as the `with` block exits.** The transcription call and its generator consumption both happen inside the `with` block. If you refactor to yield segments lazily outside the block, the file will already be gone.

- **The Glasp ingester's `fetch_title` hits YouTube's oEmbed API at ingest time.** On a machine without internet access, or when YouTube throttles the oEmbed endpoint, the title falls back to the bare video ID. SRT and JSON output still writes correctly, but the filenames will look like `HtnlUosO3XA__HtnlUosO3XA.srt`.

- **`total_duration` measures span (last-end minus first-start), not sum of segment durations.** Gaps between segments are included in the count. This is intentional for "how long is this piece of audio?" use cases but will overcount if segments are sparse or if the source file has large silent gaps.

- **There are no tests for `server.py`.** The test suite covers `glasp.py` thoroughly but `server.py` has no pytest coverage. Manual `curl` testing is the only current validation path for the HTTP layer.

## Related

- `docs/lemond-whisper-segfault.md` — full repro and patchelf workaround for the Lemonade Vulkan crash that motivated this project
- `docs/youtube-bot-wall.md` — explains why YouTube download tooling is kept out of this repo
- `docs/quality-report.md` — benchmark methodology and results for the `large-v3-turbo` / `int8` configuration on IBM Technology audio
