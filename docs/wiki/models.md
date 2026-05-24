# Models & Configuration

> Which ASR models run on lemon-asr, their performance characteristics, and how to switch them.

## Default Model
**`large-v3-turbo`** — Whisper Large v3 Turbo, CTranslate2 int8 on CPU.

| Metric | Value |
|--------|-------|
| Realtime factor | ~8× (4-min audio in ~30s on Strix Halo 16-core) |
| Memory | ~1.5 GB RAM |
| Languages | Multilingual (99 languages) |
| Word timestamps | Yes |
| Backend | CTranslate2 via faster-whisper |

## Model Config (`fw_server.py`)
```python
MODEL_SIZE = os.getenv("ASR_MODEL", "large-v3-turbo")
DEVICE = os.getenv("ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "int8")
```

Override at startup:
```bash
ASR_MODEL=medium ASR_DEVICE=cpu lemon-asr-server
```

## Why Not NPU / Whisper-cpp?
Lemonade's built-in Whisper-Large-v3-Turbo on the Strix Halo XDNA2 NPU (via FastFlowLM) has a known SEGFAULT on load. `lemon-asr-server` is the stable fallback. Do not attempt to load Whisper via `POST /api/v1/load` on the Strix Halo — it will evict all other LLMs.

## Glasp Ingester
The `lemon-asr-ingest` command processes Glasp markdown transcripts (exported from the Glasp browser extension) into `txt/srt/json` triple format. It does not call the ASR server — it parses already-transcribed text.

Input: Glasp `.md` file  
Output: `<title>.txt`, `<title>.srt`, `<title>.json` in the output directory

## Related
- [[README]] — mission and agent handoff
- [[architecture]] — system design
