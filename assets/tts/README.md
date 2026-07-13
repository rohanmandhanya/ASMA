This directory holds the Piper voice model (`en_GB-alan-medium.onnx` + `.onnx.json`), downloaded on demand and never committed (see `.gitignore`) — same convention as Playwright's browser binaries.

To synthesize real audio locally (`DRY_RUN=false`):

```bash
uv run python -m piper.download_voices en_GB-alan-medium --download-dir assets/tts
```

GitHub Actions runs this same command automatically (see `.github/workflows/*.yml`), cached between runs by voice name.

**macOS note**: the `piper-tts` PyPI wheel for macOS has a known packaging bug (hardcoded build-machine path to its bundled espeak-ng phoneme data) that breaks real synthesis on Mac entirely — confirmed by direct testing. The Linux wheel (what the actual GitHub Actions runners use) does not have this bug — confirmed by running the identical synthesis call inside a `python:3.12-slim` container. `DRY_RUN=true` (the default) never touches Piper at all, so this only affects manually testing real audio output locally on a Mac, not production.
