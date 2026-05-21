"""Convert Glasp YouTube-transcript markdown into our txt/srt/json layout.

Workflow:
  1. Visit https://glasp.co/youtube-transcript
  2. Paste a YouTube URL, hit transcribe.
  3. Copy the full transcript (or download as markdown).
  4. Save it into the configured incoming directory. Filename can be
     anything; the script tries to find the YouTube URL or 11-char video
     ID inside the file. If neither is present, name the file
     ``<video_id>.md`` or ``<video_id>__<title>.md`` and the script will
     use the filename.
  5. Run::

        lemon-asr-ingest --incoming /path/to/incoming --out-dir /path/to/output

     Each successfully ingested file is moved to ``<incoming>/_done/``.

Accepted timestamp shapes per line:
  [H:MM:SS] text                 (or [M:SS])
  [HH:MM:SS]    text
  M:SS text                       (no brackets, leading time)
  text                            (no timestamp — duration stubbed to 0)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.request
from collections.abc import Iterable
from pathlib import Path

DEFAULT_INCOMING = Path(
    os.environ.get("LEMON_ASR_GLASP_INCOMING") or "/home/bcloud/Desktop/Shared AI /glasp-incoming"
)
DEFAULT_OUTPUT_DIR = Path(
    os.environ.get("LEMON_ASR_OUTPUT_DIR")
    or "/home/bcloud/Desktop/IBMTechnology-transcripts/last-6-months/transcripts"
)

VIDEO_ID_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|\bv=)([A-Za-z0-9_-]{11})")
ID_PATTERN_RE = re.compile(r"[A-Za-z0-9_-]{11}")
TIMING_LINE_RE = re.compile(r"^\s*\[?\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*\]?\s+(.*\S)\s*$")


def find_video_id(text: str, filename: str) -> str | None:
    """Return an 11-char YouTube video ID, or None.

    Looks first for ``youtube.com/watch?v=<id>`` / ``youtu.be/<id>`` /
    ``v=<id>`` in the body, then for the same in the filename, then for an
    11-character ID prefix on the filename stem (so files like
    ``<id>__<title>.md`` are recognized — convention from the
    transcript-output layout).
    """
    m = VIDEO_ID_RE.search(text)
    if m:
        return m.group(1)
    m = VIDEO_ID_RE.search(filename)
    if m:
        return m.group(1)
    stem = Path(filename).stem
    if len(stem) >= 11 and ID_PATTERN_RE.fullmatch(stem[:11]):
        return stem[:11]
    return None


def fetch_title(video_id: str) -> str:
    try:
        url = (
            "https://www.youtube.com/oembed?url=https%3A//www.youtube.com/watch%3Fv%3D"
            + video_id
            + "&format=json"
        )
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.load(r).get("title", video_id)
    except Exception:
        return video_id


def parse_segments(body: str) -> list[dict]:
    """Parse Glasp markdown into ``{text, start, end}`` segment dicts.

    Returns ``[]`` when the input contains no timestamped lines — that
    distinguishes a real transcript from headers-only / URL-only files
    so the ingester can skip them.
    """
    out: list[dict] = []
    last_end = 0.0
    saw_timestamp = False
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        m = TIMING_LINE_RE.match(line)
        if not m:
            if not saw_timestamp:
                # Pre-content: header, source URL, blurb, etc.
                continue
            # Mid-content untimestamped line: continuation of the previous
            # segment if it's still a stub, else a fresh stub at end-of-stream.
            if out and out[-1]["end"] == out[-1]["start"]:
                out[-1]["text"] = (out[-1]["text"] + " " + line).strip()
            else:
                out.append({"text": line, "start": last_end, "end": last_end})
            continue
        saw_timestamp = True
        h = int(m.group(1) or 0)
        mm = int(m.group(2))
        ss = int(m.group(3))
        start = h * 3600 + mm * 60 + ss
        text = m.group(4)
        # Fix previous end if it was a stub
        if out and out[-1]["end"] == out[-1]["start"] and start > out[-1]["start"]:
            out[-1]["end"] = float(start)
        out.append({"text": text, "start": float(start), "end": float(start)})
        last_end = float(start)
    # Trailing segment end: round up to start + reasonable estimate (1s per 3 words)
    for seg in out:
        if seg["end"] <= seg["start"]:
            words = max(1, len(seg["text"].split()))
            seg["end"] = seg["start"] + max(1.0, words / 3.0)
    return out


def total_duration(segments: list[dict]) -> float:
    """Return total transcript duration in seconds.

    Computed as the difference between the last segment's end and the
    first segment's start, so gaps between segments are included.
    Returns 0.0 for an empty segment list.
    """
    if not segments:
        return 0.0
    return segments[-1]["end"] - segments[0]["start"]


def sanitize(s: str) -> str:
    s = re.sub(r"[^\w.-]+", "-", s).strip("-")
    return s[:90] or "untitled"


def srt_ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_outputs(video_id: str, title: str, segments: list[dict], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{video_id}__{sanitize(title)}"
    paths: list[Path] = []

    txt_path = out_dir / f"{base}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n")
        f.write(f"# https://www.youtube.com/watch?v={video_id}\n")
        f.write("# source=glasp lang=unknown\n\n")
        for seg in segments:
            f.write(seg["text"].rstrip() + " ")
        f.write("\n")
    paths.append(txt_path)

    json_path = out_dir / f"{base}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "video_id": video_id,
                "title": title,
                "source": "glasp",
                "language": "unknown",
                "snippets": [
                    {"text": s["text"], "start": s["start"], "duration": s["end"] - s["start"]}
                    for s in segments
                ],
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    paths.append(json_path)

    srt_path = out_dir / f"{base}.srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(
                f"{i}\n{srt_ts(seg['start'])} --> {srt_ts(seg['end'])}\n{seg['text'].strip()}\n\n"
            )
    paths.append(srt_path)

    return paths


def iter_inputs(incoming: Path) -> Iterable[Path]:
    if not incoming.exists():
        return
    for p in incoming.iterdir():
        if p.is_dir():
            continue
        if p.suffix.lower() in (".md", ".markdown", ".txt"):
            yield p


def ingest(
    incoming: Path,
    out_dir: Path,
    *,
    fetch_title_fn=fetch_title,
    move_done: bool = True,
) -> tuple[int, list[Path]]:
    """Ingest every Glasp markdown in *incoming*, write to *out_dir*.

    Returns ``(rc, all_paths_written)``. ``rc`` is 0 on success, 1 on any
    skipped/malformed input. ``fetch_title_fn`` is injected so tests can
    avoid hitting YouTube oEmbed.
    """
    done_dir = incoming / "_done"
    if move_done:
        done_dir.mkdir(parents=True, exist_ok=True)

    inputs = sorted(iter_inputs(incoming))
    if not inputs:
        print(f"No inputs found in {incoming}", file=sys.stderr)
        return 0, []

    rc = 0
    all_written: list[Path] = []
    for src in inputs:
        body = src.read_text(encoding="utf-8", errors="replace")
        video_id = find_video_id(body, src.name)
        if not video_id:
            print(f"SKIP  {src.name}: no YouTube URL/ID found in body or filename", file=sys.stderr)
            rc = 1
            continue
        title = fetch_title_fn(video_id)
        segments = parse_segments(body)
        if not segments:
            print(f"SKIP  {src.name}: no transcript content parsed", file=sys.stderr)
            rc = 1
            continue
        paths = write_outputs(video_id, title, segments, out_dir)
        all_written.extend(paths)
        for p in paths:
            print(f"OK    glasp -> {p}")
        if move_done:
            dest = done_dir / src.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(src), str(dest))
    return rc, all_written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="lemon-asr-ingest",
        description="Convert Glasp YouTube-transcript markdown into txt/srt/json.",
    )
    ap.add_argument(
        "--incoming",
        type=Path,
        default=DEFAULT_INCOMING,
        help=f"Directory to scan for *.md/*.txt files (default: {DEFAULT_INCOMING})",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write txt/srt/json into (default: {DEFAULT_OUTPUT_DIR})",
    )
    ap.add_argument(
        "--no-move",
        action="store_true",
        help="Do not move ingested files to <incoming>/_done/.",
    )
    args = ap.parse_args(argv)
    rc, _ = ingest(args.incoming, args.out_dir, move_done=not args.no_move)
    return rc


if __name__ == "__main__":
    sys.exit(main())
