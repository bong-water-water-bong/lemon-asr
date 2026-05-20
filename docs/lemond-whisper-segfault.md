# lemond's whisper backend segfaults on Strix Halo

## TL;DR

As of `lemonade-server 10.5.1~26.04`, the bundled `whisper-server`
binary segfaults during model load on the Vulkan backend on Strix Halo
(Radeon 8060S, RADV STRIX_HALO). `lemond`'s Router masks the segfault
as a generic "process did not become ready" and **evicts every loaded
model** (LLM, vLLM, embeddings, …) on the way down, leaving you with
nothing serving. That's why this repo exists: `lemon-asr-server` is the
working ASR drop-in that doesn't touch lemond.

## Stacked bugs

There are actually two distinct bugs.

### Bug 1: RUNPATH baked to the GHA runner (PATCHABLE)

```
$ readelf -d /var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan/whisper-server | grep -i runpath
RUNPATH: /home/runner/work/whisper.cpp-builds/whisper.cpp-builds/build/src:
         /home/runner/work/whisper.cpp-builds/whisper.cpp-builds/build/ggml/src:
         /home/runner/work/whisper.cpp-builds/whisper.cpp-builds/build/ggml/src/ggml-vulkan:
```

Whoever packaged this never re-rpath'd it for end-user installation.
Without `LD_LIBRARY_PATH` injection, the binary can't find its own
`libwhisper.so.1`. lemond's `WhisperServer::load()` *does* set
`LD_LIBRARY_PATH` to the exe dir before spawning, so this bug doesn't
fully explain the failure — but it's worth fixing anyway:

```bash
sudo apt-get install -y patchelf   # not in base image
sudo cp -a /var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan/whisper-server{,.orig}
sudo patchelf --set-rpath '$ORIGIN' /var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan/whisper-server
```

`$ORIGIN` resolves at runtime to the binary's directory, so libs
alongside it become discoverable without LD_LIBRARY_PATH plumbing.

### Bug 2: Vulkan SEGFAULT during model load (NOT YET FIXED)

After the patchelf, running the binary directly with the same arguments
lemond uses:

```bash
sudo -u lemonade env LD_LIBRARY_PATH=/var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan \
  /var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan/whisper-server \
  -m <ggml-large-v3-turbo.bin> --port 18001
```

…allocates `Vulkan0 total size = 1623.92 MB` and then `SIGSEGV (core
dumped)` at the end of `whisper_model_load`. Same crash whether spawned
by lemond or directly. lemond just reports it as a generic
"process did not become ready" and then evicts every other model in
the Router's nuclear-option retry path.

## Workaround

Use `lemon-asr-server`. It runs `faster-whisper-large-v3-turbo` on CPU
via CTranslate2, no Vulkan involved, ~8× realtime on Strix Halo's
16-core CPU.

## Verification commands

```bash
# Confirm the RUNPATH patch is still in place
sudo readelf -d /var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan/whisper-server | grep -E 'RUNPATH|RPATH'
# Should show: RUNPATH: $ORIGIN

# Repro the segfault (will dump core):
sudo -u lemonade env LD_LIBRARY_PATH=/var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan \
  /var/lib/lemonade/.cache/lemonade/bin/whispercpp/vulkan/whisper-server \
  -m <ggml-large-v3-turbo path> --port 18001
```

## Side effects to remember

Failed whisper loads trigger lemond's "nuclear" eviction — you'll
need to manually `POST /api/v1/load` your LLMs back. Always check
which models lemond was serving before attempting a whisper load.
