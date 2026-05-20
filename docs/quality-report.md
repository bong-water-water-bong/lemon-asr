# Quality report: faster-whisper-large-v3-turbo, CPU int8

## Sample

- **Video**: IBM Technology *Agentic Runtime Security Explained*
  (`HtnlUosO3XA`)
- **Duration**: 745.1 s (12.42 min)
- **Format**: m4a (audio-only, ~6.9 MB)
- **Config**: `compute_type=int8`, `beam_size=5`, `vad_filter=off`,
  `language=en`, `response_format=verbose_json`
- **Hardware**: AMD Ryzen AI MAX+ 395 (Strix Halo), 16-core, CPU only

## Throughput

| | value |
|---|---|
| Wall-clock | **94 s** |
| Real-time multiple | **~8×** |
| Segments | 131 (pre-trim) / 128 (after edge-trim) |

## Confidence

| Metric | Value | Interpretation |
|---|---|---|
| `avg_logprob` (mean) | -0.103 | Very high (0 is theoretical max) |
| `avg_logprob` (median) | -0.086 | |
| `no_speech_prob` (all segs) | 0.000 | Zero false-silence detection |

## Failure-mode audit

| Mode | Count | Notes |
|---|---|---|
| Boilerplate hallucinations (`"thanks for watching"`, `"subscribe"`, …) | 0 | |
| Consecutive duplicate segments (decoder loop) | 0 | |
| Edge fragments (≤2 words, `avg_logprob < -0.5`) | 3 trailing | `"that."`, `"So"`, `"you"` — all at lp=-0.87. Removed by edge-trim default. |
| Mistranscribed technical terms | 1 *suspected* | `"co-work agents"` (could be a real industry term or near-homophone for `"co-pilot"` / `"co-worker"`). Single occurrence; meaning preserved. |

## Coverage

| | value |
|---|---|
| First segment start | 0.00 s |
| Last segment end (post-trim) | 734.44 s |
| Sum of segment durations | 724.6 s (97.3% of audio) |
| Inter-segment gaps > 0.5 s | 14 (largest 5.2 s — clear topic-pivot pause) |

## Edge-trim impact

The post-process loop dropped 3 trailing fragments:

```
[734.44 → 739.80]  lp=-0.87  "that."
[739.80 → 743.80]  lp=-0.87  "So"
[743.80 → 745.80]  lp=-0.87  "you"
```

All three at the same logprob, all 1-2 words. New last segment ends at
734.44 s at `lp=-0.065`. No body content was touched.

## Repro

```bash
# Start server
lemon-asr-server

# Wait for /health
curl -s http://127.0.0.1:8004/health

# Transcribe
curl -s -X POST http://127.0.0.1:8004/v1/audio/transcriptions \
  -F "file=@HtnlUosO3XA.mp3" \
  -F "model=large-v3-turbo" \
  -F "response_format=verbose_json" \
  -F "language=en" > out.json
```

Compute diagnostics with `python scripts/quality-report.py out.json`
(if you add one — currently the report above was produced by an ad-hoc
analysis snippet, archived here as the reference methodology).
