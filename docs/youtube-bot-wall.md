# YouTube intake is intentionally out of scope

## What we observed (2026-05-19)

Across a ~6-hour window, YouTube tightened PO-Token enforcement to the
point that *every* `yt-dlp` player client (`tv`, `tv_simply`, `ios`,
`android_vr`, `web`, `web_safari`) bot-challenged audio requests, even
with:

- Fresh, structurally-valid session cookies (with all `__Secure-3PSID`
  family tokens present)
- A separate egress IP via SSH SOCKS5 to a Pi on the same account
- `yt-dlp 2026.03.17` on Strix Halo and `yt-dlp 2025.04.30` on the Pi
- The `bgutil-pot` POT provider installed and reachable on
  `127.0.0.1:4416`

The wall fires at the player-API-JSON step, before any URL acquisition.
Both audio-only and combined-video formats go through that gate, so
"download the full video and extract audio locally" hits the same wall.

## Why this repo doesn't ship a YouTube downloader

A YouTube downloader has to track:

- Player-client enforcement waves (months-long cadence)
- PO-Token providers (bgutil-pot, bgutils-js, native deno scripts)
- Cookie extraction (cookies.txt format, `--cookies-from-browser`, live
  browser profile paths per OS / Firefox version)
- Captcha challenges
- Account-throttle policies (per-IP and per-cookie reputation)

That's an entirely different project from "transcribe an audio file
well". Coupling them would mean every YT-side change forces a release
here, even though the transcription pipeline itself is stable.

## What we use instead

For the IBM Technology backlog that motivated this repo, we use
[Glasp](https://glasp.co/youtube-transcript) — a browser-based service
that scrapes the YouTube transcript panel via the user's authenticated
session. The user pastes each URL, copies the resulting markdown, and
drops it into the `lemon-asr-ingest` incoming directory.

For audio sources outside YouTube (recorded interviews, screen-capture
audio, internal videos), `lemon-asr-server` handles them directly:

```bash
curl -X POST http://127.0.0.1:8004/v1/audio/transcriptions \
  -F "file=@some-audio.mp3" \
  -F "response_format=verbose_json"
```

If a future PR wants to add a YouTube downloader, it should live behind
a clearly-named extra (`pip install lemon-asr[youtube]`) so the
ingester and server remain installable without dragging in the
fragile-by-design scraping surface.
