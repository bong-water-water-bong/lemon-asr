# Project Wiki: lemon-asr

## Mission
Local-first ASR pipeline for YouTube transcripts and arbitrary audio, built for the AMD Strix Halo workstation. It provides a stable, OpenAI-compatible transcription endpoint as a workaround for segfaults in other backends.

## Architecture
- **lemon-asr-server:** An OpenAI-compatible `POST /v1/audio/transcriptions` HTTP server built with FastAPI and backed by `faster-whisper`.
- **lemon-asr-ingest:** A standard library-only Python tool for converting Glasp markdown transcripts into a uniform `txt`/`srt`/`json` layout.
- **Backend:** Uses CTranslate2 (via `faster-whisper`). Defaults to `large-v3-turbo` on CPU with `int8` quantization.
- **Hardware Target:** Optimized for AMD Strix Halo (16 Zen-5 cores), but works on any x86_64 Linux system.

## Agent Handoff
- **Setup:** Install with `pip install -e ".[server,dev]"`.
- **Running Server:** Start with `lemon-asr-server` (listens on `:8004`).
- **Running Ingest:** Use `lemon-asr-ingest` to process Glasp markdown files.
- **Testing:** 
  - `GET /health` for server status.
  - Manual verification via `curl` (see main README for examples).
  - Pytest suite for the ingester (`tests/`).
- **Hot Paths:** `src/lemon_asr/server.py` (FastAPI/Whisper integration) and `src/lemon_asr/glasp.py` (ingestion logic).
- **Current Priorities:** Adding `server.py` tests and fixing hardcoded local output paths.

## Decisions & Gotchas
- **CPU vs GPU:** CTranslate2 lacks ROCm support, so it runs on CPU. Strix Halo's 16 cores are sufficient for 8x realtime at `int8`.
- **Edge-Trimming:** Post-processes results to remove low-confidence fragments (false starts/trailing silence).
- **Glasp Limitations:** Ingested files have language set to `"unknown"` as Glasp metadata lacks this field.
- **Local Paths:** `LEMON_ASR_OUTPUT_DIR` currently defaults to a machine-specific path (`/home/bcloud/...`).
- **Lemond Workaround:** Created because the `lemond` whisper backend segfaulted on Vulkan for Strix Halo.
