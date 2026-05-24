# lemon-asr — Wiki

> Local-first ASR pipeline for YouTube transcripts and arbitrary audio, built for the AMD Strix Halo workstation.

## Current State

v0.1.0 scaffold — both pieces are functional:

- **`lemon-asr-server`** is working and tested in production against IBM Technology audio. Runs on `:8004`, handles `POST /v1/audio/transcriptions` with all five `response_format` values (`json`, `verbose_json`, `text`, `srt`, `vtt`), and includes edge-trim post-processing.
- **`lemon-asr-ingest`** (Glasp ingester) is working, tested via pytest, and handles the known timestamp formats from Glasp exports.
- CI runs on Python 3.11 / 3.12 / 3.13 with ruff linting and pytest.
- No test coverage for `server.py` — the HTTP layer is validated manually via `curl`.
- YouTube audio download tooling is explicitly out of scope for this repo (see `docs/youtube-bot-wall.md`).

## Start Here

- [[architecture]] — server, Glasp ingester, faster-whisper backend, fw-server integration, env vars, output format, gotchas

## Open Threads

- **No `server.py` tests.** The HTTP transcription endpoint has no pytest coverage. A test suite using `httpx` + FastAPI's `TestClient` and a short synthetic WAV fixture would close this gap.
- **`language` field is hardcoded to `"unknown"` in Glasp JSON output.** The ingester writes `"language": "unknown"` in every JSON file because Glasp markdown does not carry language metadata. The server correctly propagates `info.language` from faster-whisper, but the two output paths are inconsistent.
- **Default output path is IBM-Technology-specific.** `LEMON_ASR_OUTPUT_DIR` defaults to `/home/bcloud/Desktop/IBMTechnology-transcripts/last-6-months/transcripts/`. This is a machine-local, content-specific path baked into the source. Future work should either make the default truly generic (e.g. `~/transcripts/`) or require the env var to be set explicitly.

## Article Index

| Article | What it covers |
|---------|----------------|
| [[architecture]] | HTTP server mechanics, Glasp ingester pipeline, faster-whisper backend, env vars, output format, key design decisions, and operational gotchas |
