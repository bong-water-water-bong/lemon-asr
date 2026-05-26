"""Tests for the faster-whisper OpenAI-compatible FastAPI server.

All tests use ``httpx.AsyncClient`` with ``ASGITransport`` against the app
in-process — no real network, no real Whisper model. Model loading is
mocked so tests run fast and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@dataclass
class _FakeSegment:
    id: int = 0
    seek: int = 0
    start: float = 0.0
    end: float = 2.5
    text: str = "this is a test transcript"
    tokens: list[int] = ()
    temperature: float = 1.0
    avg_logprob: float = -0.3
    compression_ratio: float = 1.2
    no_speech_prob: float = 0.01
    words: list[Any] = ()


@dataclass
class _FakeInfo:
    language: str = "en"
    language_probability: float = 0.99
    duration: float = 2.5
    duration_after_vad: float = 2.5
    all_language_probs: list[tuple[str, float]] = ()


def _fake_transcribe(*args: Any, **kwargs: Any) -> tuple[list[_FakeSegment], _FakeInfo]:
    return ([_FakeSegment()], _FakeInfo())


@pytest.fixture
def server():
    from lemon_asr import server as _server

    return _server


@pytest.fixture
async def client(server: Any) -> Any:
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _post_transcription(
    client: AsyncClient,
    content: bytes = b"fake audio",
    filename: str = "test.wav",
    response_format: str = "json",
    **form_fields: Any,
) -> Any:
    files = {"file": (filename, content, "audio/wav")}
    data: dict[str, Any] = {"response_format": response_format}
    data.update(**form_fields)
    resp = await client.post("/v1/audio/transcriptions", data=data, files=files)
    return resp


# ---------------------------------------------------------------------------
# Endpoint smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("faster_whisper.WhisperModel")
async def test_health_endpoint(mock_whisper: MagicMock, server: Any, client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert "model" in payload


@pytest.mark.asyncio
@patch("faster_whisper.WhisperModel")
async def test_v1_health_endpoint(mock_whisper: MagicMock, server: Any, client: AsyncClient) -> None:
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
@patch("faster_whisper.WhisperModel")
async def test_list_models(mock_whisper: MagicMock, server: Any, client: AsyncClient) -> None:
    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["object"] == "list"
    assert len(payload["data"]) == 1
    assert payload["data"][0]["id"] == "large-v3-turbo"


# ---------------------------------------------------------------------------
# response_format validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_format_json(client: AsyncClient, server: Any) -> None:
    server._model = MagicMock()
    server._model.transcribe = _fake_transcribe
    resp = await _post_transcription(client, response_format="json")
    assert resp.status_code == 200
    payload = resp.json()
    assert "text" in payload
    assert payload["language"] == "en"


@pytest.mark.asyncio
async def test_response_format_text(client: AsyncClient, server: Any) -> None:
    server._model = MagicMock()
    server._model.transcribe = _fake_transcribe
    resp = await _post_transcription(client, response_format="text")
    assert resp.status_code == 200
    assert resp.text.strip() == "this is a test transcript"


@pytest.mark.asyncio
async def test_response_format_srt(client: AsyncClient, server: Any) -> None:
    server._model = MagicMock()
    server._model.transcribe = _fake_transcribe
    resp = await _post_transcription(client, response_format="srt")
    assert resp.status_code == 200
    assert "00:00:00,000 --> 00:00:02,500" in resp.text


@pytest.mark.asyncio
async def test_response_format_vtt(client: AsyncClient, server: Any) -> None:
    server._model = MagicMock()
    server._model.transcribe = _fake_transcribe
    resp = await _post_transcription(client, response_format="vtt")
    assert resp.status_code == 200
    assert resp.text.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in resp.text


@pytest.mark.asyncio
async def test_response_format_verbose_json(client: AsyncClient, server: Any) -> None:
    server._model = MagicMock()
    server._model.transcribe = _fake_transcribe
    resp = await _post_transcription(client, response_format="verbose_json")
    assert resp.status_code == 200
    payload = resp.json()
    assert "segments" in payload
    assert "duration" in payload
    assert len(payload["segments"]) == 1
    assert payload["segments"][0]["text"] == "this is a test transcript"


@pytest.mark.asyncio
@patch("faster_whisper.WhisperModel")
async def test_response_format_invalid(
    mock_whisper: MagicMock, server: Any, client: AsyncClient
) -> None:
    resp = await _post_transcription(client, response_format="xml")
    assert resp.status_code == 400
    payload = resp.json()
    assert "Invalid response_format" in payload.get("detail", "")


# ---------------------------------------------------------------------------
# File-size cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("faster_whisper.WhisperModel")
async def test_file_too_large(
    mock_whisper: MagicMock, server: Any, client: AsyncClient
) -> None:
    server.MAX_UPLOAD_BYTES = 10
    resp = await _post_transcription(client, content=b"x" * 100)
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Model-not-loaded (503)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_not_loaded_returns_503(client: AsyncClient, server: Any) -> None:
    server._model = None
    resp = await _post_transcription(client)
    assert resp.status_code == 503
    assert "not loaded" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Edge-trim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edge_trim_removes_low_confidence_edges(
    client: AsyncClient, server: Any
) -> None:
    junk = _FakeSegment(id=0, start=0.0, end=0.5, text="um",
                         avg_logprob=-3.0, no_speech_prob=0.9)
    junk2 = _FakeSegment(id=1, start=0.5, end=1.0, text="uh",
                          avg_logprob=-2.5, no_speech_prob=0.8)
    good = _FakeSegment(id=2, start=1.0, end=2.5, text="real speech",
                        avg_logprob=-0.2, no_speech_prob=0.01)
    trailing = _FakeSegment(id=3, start=2.5, end=3.0, text="yeah",
                             avg_logprob=-2.0, no_speech_prob=0.7)
    info = _FakeInfo(duration=3.0)

    def _trimmed_transcribe(*args: Any, **kwargs: Any) -> tuple[list[_FakeSegment], _FakeInfo]:
        return ([junk, junk2, good, trailing], info)

    server._model = MagicMock()
    server._model.transcribe = _trimmed_transcribe

    resp = await _post_transcription(client)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["text"] == "real speech"


# ---------------------------------------------------------------------------
# Env-var helpers
# ---------------------------------------------------------------------------


def test_env_str_default(server: Any):
    assert server._env_str("FW_NONEXISTENT_XYZ", "fallback") == "fallback"


def test_env_int_default(server: Any):
    assert server._env_int("FW_NONEXISTENT_XYZ", 42) == 42


def test_env_float_default(server: Any):
    assert server._env_float("FW_NONEXISTENT_XYZ", 3.14) == pytest.approx(3.14)


def test_env_bool_false_by_default(server: Any):
    assert server._env_bool("FW_NONEXISTENT_XYZ", False) is False


def test_env_bool_true_values(server: Any, monkeypatch: Any):
    for val in ("1", "true", "TRUE", "yes", "YES"):
        monkeypatch.setenv("_TEST_BOOL", val)
        assert server._env_bool("_TEST_BOOL", False) is True

    monkeypatch.setenv("_TEST_BOOL", "0")
    assert server._env_bool("_TEST_BOOL", False) is False


# ---------------------------------------------------------------------------
# Response format exact-match guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("faster_whisper.WhisperModel")
async def test_response_format_case_sensitive(
    mock_whisper: MagicMock, server: Any, client: AsyncClient
) -> None:
    resp = await _post_transcription(client, response_format="JSON")
    assert resp.status_code == 400


@pytest.mark.asyncio
@patch("faster_whisper.WhisperModel")
async def test_response_format_unrecognised(
    mock_whisper: MagicMock, server: Any, client: AsyncClient
) -> None:
    resp = await _post_transcription(client, response_format="raw")
    assert resp.status_code == 400
