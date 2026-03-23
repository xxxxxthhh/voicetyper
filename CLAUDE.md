# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app
export GROQ_API_KEY="your-key-here"
python3 run.py

# Install Python dependencies
pip3 install -r requirements.txt

# Install required system library
brew install portaudio

# Build as macOS .app bundle
pip3 install py2app
rm -rf build dist .eggs
python3 setup.py py2app
codesign --force --deep --sign - dist/VoiceTyper.app
open dist/VoiceTyper.app
```

API key can also be stored in `~/.voicetyper/config.json` as `{"groq_api_key": "..."}` instead of an env var.

## Architecture

**Entry point:** `run.py` → `src/app.py:VoiceTyperApp`

`VoiceTyperApp` is a `rumps.App` subclass. It owns the menu bar icon, manages the global hotkey listener (`pynput`), and orchestrates the full recording-to-paste pipeline.

### Module responsibilities

| Module | Role |
|---|---|
| `src/config.py` | All configuration: reads env vars with defaults, loads `~/.voicetyper/config.json` |
| `src/recorder.py` | Thread-safe audio capture via `sounddevice`; handles PortAudio library resolution for bundled `.app` |
| `src/transcriber.py` | Calls Groq Whisper API (`verbose_json`) returning `{text, language, segments}` |
| `src/text_rewriter.py` | AI punctuation/segmentation rewrite via Groq chat API with safety guards |
| `src/pause_segmenter.py` | Deterministic punctuation insertion using Whisper segment timestamps |
| `src/text_formatter.py` | Final style-specific post-processing (Normal / English / Chinese / Code) |
| `src/voice_commands.py` | Detects control phrases in transcription text (newline, undo, style switch) |
| `src/paster.py` | AppleScript-based clipboard write + Cmd+V paste to frontmost app |
| `src/visual_hud.py` | PyObjC floating NSWindow HUD for Recording/Transcribing/Done states |
| `src/db.py` | SQLite history at `~/.voicetyper/history.db` |

### Text processing pipeline

Recording stops → audio saved to temp WAV under `~/.voicetyper/` → background thread:

1. **ASR**: `Transcriber.transcribe()` → raw `text` + `segments` (with timing)
2. **Voice command check**: if text matches a command phrase, execute and skip paste
3. **AI-first mode** (default, `VOICETYPER_AI_FIRST_ENABLED=1`):
   - `build_pause_hints(segments)` extracts inter-segment gaps as hints
   - `TextRewriter.rewrite(text, style, pause_hints=...)` sends to Groq chat
   - If AI returns identical text → fallback to `apply_pause_segmentation()`
4. **Rule-first mode** (fallback/alternative):
   - `apply_pause_segmentation()` inserts punctuation at pause boundaries first
   - Then `TextRewriter.rewrite()` without hints
5. `format_text(rewritten, style)` applies final style cleanup
6. `copy_text_to_clipboard()` + `paste_text(target_app)` via AppleScript

### Rewriter safety model (`src/text_rewriter.py`)

The rewriter only accepts AI output that passes safety checks:
- `_is_safe_micro_edit`: normalized lexical content must be identical (only punctuation/spaces changed)
- `_looks_too_different`: token overlap ratio check
- If strict check fails, tries `_project_punctuation_from_rewrite` (sequence-alignment-based projection)
- Falls back to original text if all models fail

### Hotkey

Fixed `Shift+Option` toggle. Edge-triggered (`_toggle_hotkey_latched`) to prevent key-repeat firing. Listener runs on a daemon thread.

### Data directory

`~/.voicetyper/` — SQLite DB, temp WAV files (auto-deleted after transcription), `config.json`, optional `terms.json` for custom term corrections.

## Key debug env vars

```bash
VOICETYPER_DEBUG_PIPELINE_ENABLED=1   # log ASR / AI rewrite / final output
VOICETYPER_REWRITER_DEBUG=1           # log per-model rewriter decisions
VOICETYPER_PAUSE_SEGMENT_DEBUG=1      # log pause boundary insertions
```
