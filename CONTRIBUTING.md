# Contributing to lemon-asr

`lemon-asr` is intentionally small. Two modules, two entry points, one
opinion: do not couple the transcription pipeline to fragile upstream
scrapers. Reading this once is enough to land good PRs.

## Ground rules

1. **The ingester is stdlib-only.** `src/lemon_asr/glasp.py` must not
   import third-party packages. It runs on machines where the ASR
   server's `[server]` extras are not installed.
2. **The server has heavy deps; they live behind the `[server]` extra.**
   Never add `faster-whisper`, `fastapi`, etc. to the top-level
   `dependencies` list in `pyproject.toml`.
3. **Tests never write to a real artifact directory.** Use `tmp_path`
   for output dirs and provably fake 11-char video IDs like
   `TESTXXXFAKE` or `XXXXXXXXXXX`. The ingester is happy to overwrite a
   real transcript if you point it at one.
4. **Edge-trim defaults are calibrated.** `FW_EDGE_TRIM_LOGPROB=-0.5`
   and `FW_EDGE_TRIM_MAX_WORDS=2` came from real-audio diagnostics. If
   you change defaults, include the calibration sample in the PR
   description.
5. **YouTube intake is out of scope.** This repo ships a transcription
   pipeline and an ingester. It does **not** ship a yt-dlp wrapper.
   See `docs/youtube-bot-wall.md` for the rationale.

## Local setup

```bash
git clone https://github.com/bong-water-water-bong/lemon-asr.git
cd lemon-asr
python -m pip install -e ".[server,dev]"

# Or, ingester-only (stdlib + dev tools):
python -m pip install -e ".[dev]"
```

Requires Python ≥ 3.11.

## Running checks

```bash
# Lint
ruff check src tests
ruff format --check src tests

# Tests
pytest

# Types (ingester only — faster-whisper has no type stubs)
mypy
```

PRs must pass all three on the CI matrix (3.11 / 3.12 / 3.13).

## Commit & review conventions

- Mirror the `lemonade-cashier` / `lemonade-store` cadence: small PRs,
  squash-merge to `main`, descriptive titles in present-tense imperative
  (`add edge-trim head pass`, not `added` or `adding`).
- After every push: CodeRabbit + Qodo bot reviews fire on PR open.
  Address all findings before merging.

## License

By contributing you agree your contributions are licensed under MIT
(see [LICENSE](LICENSE)).
