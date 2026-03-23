# VoiceTyper 🎙️

A lightweight macOS menu bar app for system-wide voice input.
Press a hotkey, speak, and text appears at your cursor.

## Features

- **Global hotkey** voice input from any app
- **Toggle mode only**: press once to start, press again to stop
- **Edge-triggered toggle hotkey** (prevents repeated start/stop on key repeat)
- **Live preview** during recording (menu可开关，使用额外 API 调用)
- **Groq Whisper** for fast, accurate transcription
- **AI punctuation/segmentation rewrite** with Groq chat model fallback chain
- **Auto-paste** to current cursor position
- **Clipboard-first output** (always copies text, then tries to paste into previous app)
- **On-screen visual HUD** for Recording / Transcribing / Done states (recording dot blinks)
- **Voice commands** (换行 / 撤销 / 风格切换)
- **Smart text formatting** (Normal / English / Chinese / Code)
- **SQLite history** of all transcriptions
- **Safer transcription flow** with network/JSON error handling
- **Menu bar** status indicator with recording state

## Setup

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Install portaudio (required by sounddevice)
brew install portaudio

# 3. Set your Groq API key
export GROQ_API_KEY="your-key-here"

# 4. Run
python3 run.py
```

Or store key in config file (recommended for `.app` usage):

```bash
mkdir -p ~/.voicetyper
cat > ~/.voicetyper/config.json <<'EOF'
{"groq_api_key":"gsk_xxx"}
EOF
```

## macOS Permissions

On first run, you'll need to grant:
- **Accessibility** (for global hotkeys & paste simulation)
- **Microphone** (for audio recording)

Go to System Settings → Privacy & Security → grant access to Terminal/Python.

## Hotkeys

| Action | Default Hotkey |
|--------|---------------|
| Toggle recording | `Shift+Option` |

## Menu Bar

- 🎙️ = Idle, ready
- 🔴 = Recording
- ⏳ = Transcribing
- Click for options: style switch, live preview toggle, visual HUD toggle, history, quit

## Voice Commands

When the recognized text exactly matches one of these phrases, VoiceTyper executes a command instead of pasting text:

- `new line` / `newline` / `换行` / `下一行`: insert a newline
- `undo` / `撤销`: undo previous action (`Cmd+Z`)
- `delete last` / `删除上一句`: undo previous action (`Cmd+Z`)
- `english mode` / `英文模式`: switch formatting style to English
- `chinese mode` / `中文模式`: switch formatting style to Chinese
- `code mode` / `代码模式`: switch formatting style to Code
- `normal mode` / `普通模式`: switch formatting style to Normal

## Data

All transcriptions are stored in `~/.voicetyper/history.db`.

Recorded audio is saved to unique temporary WAV files under `~/.voicetyper/` during transcription and removed automatically after processing.

## Environment Variables

```bash
# required
export GROQ_API_KEY="your-key-here"

# optional: live preview (extra API cost)
export VOICETYPER_LIVE_PREVIEW_ENABLED=1
export VOICETYPER_LIVE_PREVIEW_INTERVAL_SECS=2.2
export VOICETYPER_LIVE_PREVIEW_MIN_DELTA_SECS=1.5
export VOICETYPER_LIVE_PREVIEW_MIN_AUDIO_SECS=1.3

# optional: hard timeout safeguard for transcribing state
export VOICETYPER_TRANSCRIBE_HARD_TIMEOUT_SECS=45

# optional: AI rewrite (punctuation + segmentation)
export VOICETYPER_AI_REWRITE_ENABLED=1
export VOICETYPER_AI_REWRITE_MODELS="qwen/qwen3-32b"
export VOICETYPER_AI_REWRITE_TIMEOUT_SECS=8
export VOICETYPER_AI_REWRITE_MAX_CHARS=700
# optional: short utterances won't auto-append final period if below threshold
export VOICETYPER_AUTO_TERMINAL_MIN_CHARS=14

# optional: pause-aware segmentation (Whisper segments)
export VOICETYPER_PAUSE_SEGMENT_ENABLED=1
export VOICETYPER_PAUSE_BREAK_SECS=0.35
export VOICETYPER_PAUSE_STRONG_BREAK_SECS=0.75
export VOICETYPER_PAUSE_MIN_CHARS=8
# optional: promote weak punctuation (comma/semicolon) to stronger stop on long pause
export VOICETYPER_PAUSE_PROMOTE_WEAK_PUNCT=0
# debug pause segmentation decisions in terminal
export VOICETYPER_PAUSE_SEGMENT_DEBUG=0
```

If `GROQ_API_KEY` is not set, app falls back to:
- `~/.voicetyper/config.json` -> `{"groq_api_key":"..."}`

Custom term corrections (optional):
- `~/.voicetyper/terms.json` -> `{"飞梳":"飞书","telegarm":"telegram"}`
- Applied to both raw transcription text and AI rewrite output.

## Package as macOS App

```bash
# 1) install build tool
pip3 install py2app

# 2) clean old build
rm -rf build dist .eggs

# 3) build app
python3 setup.py py2app

# 4) ad-hoc sign (local use)
codesign --force --deep --sign - dist/VoiceTyper.app

# 5) run
open dist/VoiceTyper.app
```

Notes:
- Entry/build config is in `setup.py`.
- For menu bar behavior, `LSUIElement` is enabled in app plist.
- If app cannot capture/paste after rebuild, re-grant permissions to `dist/VoiceTyper.app`.

## Quick Test Checklist

After launch (`python3 run.py`), verify:

1. Press `Shift+Option` once to start recording, then once to stop.
2. During recording, confirm status may show `Live: ...` when live preview is enabled.
3. During transcription, icon changes to ⏳ and returns to 🎙️ afterward.
4. If transcription succeeds, status shows `Copied+Pasted: ...` (or `Copied only: ...`) and appears in history.
5. For long Chinese dictation with pauses, confirm output is segmented naturally (AI rewrite enabled).
   Pause-aware segmentation can insert comma/period before AI rewrite.
6. Say `english mode` (or `中文模式`) and verify style switches.
7. Say `new line` and `undo` to verify voice commands execute.
8. If API/network fails, app shows an error notification and stays responsive.

## Troubleshooting

- `Recording failed`: check Microphone permission for Terminal/Python in macOS Privacy & Security.
- No paste output: check Accessibility permission for Terminal/Python; text should still be in clipboard (`Cmd+V` manually).
- API usage too high: set `VOICETYPER_LIVE_PREVIEW_ENABLED=0` or increase `VOICETYPER_LIVE_PREVIEW_INTERVAL_SECS`.
- AI rewrite latency/cost too high: set `VOICETYPER_AI_REWRITE_ENABLED=0` or keep only one fast model in `VOICETYPER_AI_REWRITE_MODELS`.
- Too many auto-appended sentence endings: increase `VOICETYPER_AUTO_TERMINAL_MIN_CHARS` (e.g. `18`).
- Pause segmentation too aggressive: increase `VOICETYPER_PAUSE_BREAK_SECS` / `VOICETYPER_PAUSE_STRONG_BREAK_SECS`.
- Pause segmentation still not splitting: lower `VOICETYPER_PAUSE_BREAK_SECS` (e.g. `0.28`) and set `VOICETYPER_PAUSE_SEGMENT_DEBUG=1` to inspect applied pause boundaries.
- Prefer preserving weak punctuation (comma/dunhao): keep `VOICETYPER_PAUSE_PROMOTE_WEAK_PUNCT=0` (default).
- Wrong homophone words (e.g. 飞梳/飞书): add mapping in `~/.voicetyper/terms.json`.
- Stuck on `Transcribing...`: lower network risk by setting `VOICETYPER_TRANSCRIBE_HARD_TIMEOUT_SECS` (default 45s), app will auto-recover.
- pyenv + rumps notification error (`Info.plist` / `CFBundleIdentifier`): app now auto-falls back to no notifications, voice typing still works.
- `GROQ_API_KEY` missing: set it before running:

```bash
export GROQ_API_KEY="your-key-here"
python3 run.py
```
