"""Tests for the Glasp markdown ingester.

All tests use provably fake video IDs (e.g. ``TESTXXXFAKE``) and write
to ``tmp_path``, never to a real transcripts directory. This is enforced
by [feedback-no-real-output-paths-in-tests] — see CONTRIBUTING.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lemon_asr import glasp

FAKE_ID = "TESTXXXFAKE"
FAKE_TITLE = "Synthetic Test Episode"


def _fake_title(_video_id: str) -> str:
    """Stub that avoids hitting YouTube oEmbed during tests."""
    return FAKE_TITLE


def _glasp_md(video_id: str = FAKE_ID) -> str:
    return f"""# Test transcript
Source: https://www.youtube.com/watch?v={video_id}

[0:00] Hello and welcome.
[0:05] We're talking about agentic AI today.
[1:30] Identity is the foundation of zero trust.
[5:42] Thanks for watching.
"""


def _make_incoming(tmp_path: Path, body: str, name: str = "sample.md") -> Path:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / name).write_text(body, encoding="utf-8")
    return incoming


def test_find_video_id_from_url() -> None:
    body = "Watch: https://www.youtube.com/watch?v=" + FAKE_ID + "&t=42"
    assert glasp.find_video_id(body, "anything.md") == FAKE_ID


def test_find_video_id_from_filename() -> None:
    assert glasp.find_video_id("no url in body", f"{FAKE_ID}__some-title.md") == FAKE_ID


def test_find_video_id_returns_none_on_no_match() -> None:
    assert glasp.find_video_id("no id anywhere", "random.md") is None


def test_parse_segments_with_bracketed_timestamps() -> None:
    body = "[0:00] Hello.\n[0:05] Second line."
    segs = glasp.parse_segments(body)
    assert len(segs) == 2
    assert segs[0] == pytest.approx({"text": "Hello.", "start": 0.0, "end": 5.0}, rel=1e-3)
    assert segs[1]["text"] == "Second line."
    assert segs[1]["start"] == pytest.approx(5.0)
    # Last segment gets a stubbed end based on word count
    assert segs[1]["end"] > segs[1]["start"]


def test_parse_segments_handles_hours() -> None:
    body = "[1:23:45] After an hour and change.\n[1:24:00] Fifteen seconds later."
    segs = glasp.parse_segments(body)
    assert segs[0]["start"] == pytest.approx(1 * 3600 + 23 * 60 + 45)
    assert segs[1]["start"] == pytest.approx(1 * 3600 + 24 * 60)


def test_parse_segments_continuation_line_appended() -> None:
    body = "[0:00] First line that continues\nonto a second line.\n[0:05] Done."
    segs = glasp.parse_segments(body)
    assert segs[0]["text"] == "First line that continues onto a second line."
    assert len(segs) == 2


def test_ingest_writes_txt_srt_json_and_moves_done(tmp_path: Path) -> None:
    incoming = _make_incoming(tmp_path, _glasp_md())
    out_dir = tmp_path / "out"
    rc, paths = glasp.ingest(incoming, out_dir, fetch_title_fn=_fake_title)
    assert rc == 0
    assert {p.suffix for p in paths} == {".txt", ".srt", ".json"}
    assert all(p.parent == out_dir for p in paths)

    # JSON shape sanity
    json_path = next(p for p in paths if p.suffix == ".json")
    payload = json.loads(json_path.read_text())
    assert payload["video_id"] == FAKE_ID
    assert payload["title"] == FAKE_TITLE
    assert payload["source"] == "glasp"
    assert len(payload["snippets"]) == 4
    assert payload["snippets"][0]["text"] == "Hello and welcome."

    # Source file moved to _done
    assert not (incoming / "sample.md").exists()
    assert (incoming / "_done" / "sample.md").exists()


def test_ingest_skips_files_without_video_id(tmp_path: Path) -> None:
    incoming = _make_incoming(
        tmp_path, "transcript with no URL or ID anywhere\n[0:00] hi", "anonymous.md"
    )
    out_dir = tmp_path / "out"
    rc, paths = glasp.ingest(incoming, out_dir, fetch_title_fn=_fake_title)
    assert rc == 1
    assert paths == []
    # File NOT moved when skipped
    assert (incoming / "anonymous.md").exists()


def test_ingest_skips_files_with_no_parsed_content(tmp_path: Path) -> None:
    body = f"# Empty transcript\nhttps://www.youtube.com/watch?v={FAKE_ID}\n\n## Just headers\n"
    incoming = _make_incoming(tmp_path, body, "headers-only.md")
    out_dir = tmp_path / "out"
    rc, paths = glasp.ingest(incoming, out_dir, fetch_title_fn=_fake_title)
    assert rc == 1
    assert paths == []


def test_ingest_empty_incoming_returns_zero(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    rc, paths = glasp.ingest(incoming, tmp_path / "out", fetch_title_fn=_fake_title)
    assert rc == 0
    assert paths == []


def test_ingest_no_move_preserves_source(tmp_path: Path) -> None:
    incoming = _make_incoming(tmp_path, _glasp_md())
    out_dir = tmp_path / "out"
    rc, _ = glasp.ingest(incoming, out_dir, fetch_title_fn=_fake_title, move_done=False)
    assert rc == 0
    assert (incoming / "sample.md").exists()
    assert not (incoming / "_done").exists()


def test_srt_ts_formatting() -> None:
    assert glasp.srt_ts(0) == "00:00:00,000"
    assert glasp.srt_ts(3661.123) == "01:01:01,123"
    assert glasp.srt_ts(45.5) == "00:00:45,500"


def test_sanitize_drops_unsafe_chars() -> None:
    assert glasp.sanitize("Hello / World: A Test!") == "Hello-World-A-Test"
    assert glasp.sanitize("a" * 200).startswith("aaa")
    assert len(glasp.sanitize("a" * 200)) <= 90


def test_sanitize_returns_untitled_for_all_special_chars() -> None:
    # All-punctuation input collapses to empty after stripping dashes;
    # the "or 'untitled'" fallback must kick in so output paths are never empty.
    assert glasp.sanitize("!!!???///") == "untitled"
    assert glasp.sanitize("") == "untitled"


def test_find_video_id_from_bare_stem() -> None:
    # A file named exactly <11-char-id>.md with no URL in the body and no
    # __ separator still yields the correct video ID via the stem fallback.
    assert glasp.find_video_id("no url here", f"{FAKE_ID}.md") == FAKE_ID


def test_total_duration_empty() -> None:
    assert glasp.total_duration([]) == 0.0


def test_total_duration_single_segment() -> None:
    segs = [{"text": "Hello.", "start": 10.0, "end": 12.5}]
    assert glasp.total_duration(segs) == pytest.approx(2.5)


def test_total_duration_multiple_segments_includes_gaps() -> None:
    # Three segments: [0-5], [10-15], [20-25].  Total span = 25, not sum of durations (15).
    segs = [
        {"text": "A", "start": 0.0, "end": 5.0},
        {"text": "B", "start": 10.0, "end": 15.0},
        {"text": "C", "start": 20.0, "end": 25.0},
    ]
    assert glasp.total_duration(segs) == pytest.approx(25.0)


def test_total_duration_from_parsed_transcript() -> None:
    segs = glasp.parse_segments(_glasp_md())
    # Transcript spans [0:00] to [5:42]; total duration should be ≥ 342 s.
    assert glasp.total_duration(segs) >= 342.0
