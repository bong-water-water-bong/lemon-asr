#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "faster-whisper>=1.2.0",
#     "requests>=2.32",
#     "fastapi==0.115.6",
#     "uvicorn[standard]==0.34.0",
#     "python-multipart==0.0.20",
# ]
# ///
"""
OpenAI-compatible /v1/audio/transcriptions server backed by faster-whisper.

Two ways to launch:
    # 1. No-install path — uv reads the PEP 723 header and runs in an
    #    ephemeral environment.
    uv run --script src/lemon_asr/server.py

    # 2. Installed package — `pip install ".[server]"` then:
    lemon-asr-server

Drop-in for callers expecting an OpenAI Audio API endpoint, including
the FLM_ASR_BASE_URL hook used by the yt-transcript orchestrator::

    export FLM_ASR_BASE_URL=http://127.0.0.1:8004/v1

Env vars:
    FW_MODEL          - whisper model (default: large-v3-turbo)
    FW_DEVICE         - cpu | cuda | auto  (default: cpu, since CTranslate2 has
                        no ROCm support; Strix Halo has 16 cores, plenty fast)
    FW_COMPUTE_TYPE   - int8 | int8_float16 | float16 | float32 (default: int8)
    FW_HOST           - bind host (default: 127.0.0.1)
    FW_PORT           - bind port (default: 8004)
    FW_BEAM_SIZE      - decoder beam size (default: 5)
    FW_VAD_FILTER     - "1"/"true" to enable Silero VAD (default: off)
    FW_EDGE_TRIM_LOGPROB  - drop leading AND trailing segs with avg_logprob
                            below this (default: -0.5; set to a very negative
                            number like -10 to disable)
    FW_EDGE_TRIM_MAX_WORDS - only drop edge segs with at most this many words
                            (default: 2)
"""

import asyncio
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse

MODEL_NAME = os.environ.get("FW_MODEL", "large-v3-turbo")
DEVICE = os.environ.get("FW_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("FW_COMPUTE_TYPE", "int8")
BEAM_SIZE = int(os.environ.get("FW_BEAM_SIZE", "5"))
VAD_FILTER = os.environ.get("FW_VAD_FILTER", "").lower() in ("1", "true", "yes")
EDGE_TRIM_LOGPROB = float(os.environ.get("FW_EDGE_TRIM_LOGPROB", "-0.5"))
EDGE_TRIM_MAX_WORDS = int(os.environ.get("FW_EDGE_TRIM_MAX_WORDS", "2"))
HOST = os.environ.get("FW_HOST", "127.0.0.1")
PORT = int(os.environ.get("FW_PORT", "8004"))

app = FastAPI(title="faster-whisper OpenAI shim")

# Loaded at startup; protected by a lock since faster-whisper's transcribe()
# isn't reentrant on a single model instance.
_model = None
_lock = asyncio.Lock()


@app.on_event("startup")
async def _load_model() -> None:
    global _model
    from faster_whisper import WhisperModel

    print(f"[fw-server] loading {MODEL_NAME} on {DEVICE} ({COMPUTE_TYPE})", flush=True)
    _model = WhisperModel(MODEL_NAME, device=DEVICE, compute_type=COMPUTE_TYPE)
    print("[fw-server] ready", flush=True)


@app.get("/v1/models")
@app.get("/api/v1/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "faster-whisper"}],
    }


@app.get("/health")
@app.get("/v1/health")
async def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME, "device": DEVICE, "compute_type": COMPUTE_TYPE}


@app.post("/v1/audio/transcriptions")
@app.post("/api/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model: str = Form(MODEL_NAME),  # ignored; we only have one model loaded
    response_format: str = Form("json"),
    language: str | None = Form(None),
    prompt: str | None = Form(None),
    temperature: float = Form(0.0),
):
    if _model is None:
        raise HTTPException(503, "Model not loaded yet")

    suffix = Path(file.filename or "audio").suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(await file.read())
        tmp.flush()

        async with _lock:
            # transcribe() returns a (generator, info) pair; we must consume
            # the generator while holding the lock to keep model state coherent.
            segments_gen, info = await asyncio.to_thread(
                _model.transcribe,
                tmp.name,
                language=language,
                beam_size=BEAM_SIZE,
                vad_filter=VAD_FILTER,
                temperature=temperature,
                initial_prompt=prompt,
                word_timestamps=False,
            )
            segs = await asyncio.to_thread(list, segments_gen)

    # Edge-trim: faster-whisper sometimes emits low-confidence 1-2 word
    # fragments at the start (false-start audio / leading silence) and end
    # (speaker trailing off). Walk inward from each side and drop matching
    # segments until we hit a confident or word-rich one.
    def _is_edge_junk(seg) -> bool:
        return seg.avg_logprob < EDGE_TRIM_LOGPROB and len(seg.text.split()) <= EDGE_TRIM_MAX_WORDS

    while segs and _is_edge_junk(segs[-1]):
        segs.pop()
    while segs and _is_edge_junk(segs[0]):
        segs.pop(0)

    full_text = " ".join(s.text.strip() for s in segs).strip()

    if response_format == "text":
        return PlainTextResponse(full_text + "\n")
    if response_format == "srt":
        return PlainTextResponse(_segments_to_srt(segs))
    if response_format == "vtt":
        return PlainTextResponse(_segments_to_vtt(segs))

    payload: dict = {"text": full_text, "language": info.language}
    if response_format == "verbose_json":
        payload["duration"] = float(info.duration)
        payload["segments"] = [
            {
                "id": i,
                "start": float(s.start),
                "end": float(s.end),
                "text": s.text.strip(),
                "avg_logprob": float(s.avg_logprob),
                "no_speech_prob": float(s.no_speech_prob),
                "temperature": float(s.temperature),
            }
            for i, s in enumerate(segs)
        ]
    return JSONResponse(payload)


def _ts_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(t: float) -> str:
    return _ts_srt(t).replace(",", ".")


def _segments_to_srt(segs) -> str:
    return "\n".join(
        f"{i + 1}\n{_ts_srt(s.start)} --> {_ts_srt(s.end)}\n{s.text.strip()}\n"
        for i, s in enumerate(segs)
    )


def _segments_to_vtt(segs) -> str:
    body = "\n".join(f"{_ts_vtt(s.start)} --> {_ts_vtt(s.end)}\n{s.text.strip()}\n" for s in segs)
    return "WEBVTT\n\n" + body


def main() -> None:
    """Entry point for ``lemon-asr-server`` console script and ``uv run --script``."""
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
