This directory holds the Piper voice model (`en_GB-alan-medium.onnx` + `.onnx.json`), committed directly to git rather than downloaded at runtime.

That's a deliberate change from the original "download on demand" convention (same idea as Playwright's browser binaries): this project hit a real, confirmed Hugging Face outage (`HTTP 403` from `cas-bridge.xethub.hf.co`, HF's large-file storage backend — affecting unrelated projects too, not something specific to this repo) that took down every workflow needing real TTS, over a fixed 60MB file that never changes. Committing it once removes that dependency and the redownload latency entirely — see `video/tts.py`'s module docstring for the full story.

If you ever want to switch voices, download the new model once and replace these two files:

```bash
uv run python -m piper.download_voices <voice-name> --download-dir assets/tts
```

**macOS note**: the `piper-tts` PyPI wheel for macOS has a known packaging bug (hardcoded build-machine path to its bundled espeak-ng phoneme data) that breaks real synthesis on Mac entirely — confirmed by direct testing. The Linux wheel (what the actual GitHub Actions runners use) does not have this bug — confirmed by running the identical synthesis call inside a `python:3.12-slim` container. `DRY_RUN=true` (the default) never touches Piper at all, so this only affects manually testing real audio output locally on a Mac, not production.
