"""VoiceTyper configuration."""
import json
import os
from pathlib import Path

# Directories
DATA_DIR = Path.home() / ".voicetyper"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "history.db"
CONFIG_PATH = DATA_DIR / "config.json"

# Audio settings
SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 1

# VAD / recording behavior
VAD_ENABLED = os.environ.get("VOICETYPER_VAD_ENABLED", "1") != "0"
VAD_RMS_THRESHOLD = float(os.environ.get("VOICETYPER_VAD_RMS_THRESHOLD", "0.012"))
VAD_SILENCE_SECS = float(os.environ.get("VOICETYPER_VAD_SILENCE_SECS", "1.1"))
VAD_MIN_RECORD_SECS = float(os.environ.get("VOICETYPER_VAD_MIN_RECORD_SECS", "0.8"))

# Live preview behavior (uses extra API calls during recording)
LIVE_PREVIEW_ENABLED = os.environ.get("VOICETYPER_LIVE_PREVIEW_ENABLED", "1") != "0"
LIVE_PREVIEW_INTERVAL_SECS = float(
    os.environ.get("VOICETYPER_LIVE_PREVIEW_INTERVAL_SECS", "2.2")
)
LIVE_PREVIEW_MIN_DELTA_SECS = float(
    os.environ.get("VOICETYPER_LIVE_PREVIEW_MIN_DELTA_SECS", "1.5")
)
LIVE_PREVIEW_MIN_AUDIO_SECS = float(
    os.environ.get("VOICETYPER_LIVE_PREVIEW_MIN_AUDIO_SECS", "1.3")
)

# Hard timeout for transcription request pipeline.
TRANSCRIBE_HARD_TIMEOUT_SECS = float(
    os.environ.get("VOICETYPER_TRANSCRIBE_HARD_TIMEOUT_SECS", "45")
)

# Optional AI rewrite (punctuation + sentence segmentation pass).
AI_REWRITE_ENABLED = os.environ.get("VOICETYPER_AI_REWRITE_ENABLED", "1") != "0"
AI_REWRITE_MODEL = os.environ.get("VOICETYPER_AI_REWRITE_MODEL", "qwen/qwen3-32b")
AI_REWRITE_MODELS = [
    m.strip()
    for m in os.environ.get(
        "VOICETYPER_AI_REWRITE_MODELS",
        "qwen/qwen3-32b,llama-3.1-8b-instant,llama-3.3-70b-versatile",
    ).split(",")
    if m.strip()
]
if not AI_REWRITE_MODELS:
    AI_REWRITE_MODELS = [AI_REWRITE_MODEL]
AI_REWRITE_TIMEOUT_SECS = float(
    os.environ.get("VOICETYPER_AI_REWRITE_TIMEOUT_SECS", "8")
)
AI_REWRITE_MAX_CHARS = int(os.environ.get("VOICETYPER_AI_REWRITE_MAX_CHARS", "700"))

# Pause-aware sentence segmentation (uses Whisper segment timing).
PAUSE_SEGMENT_ENABLED = os.environ.get("VOICETYPER_PAUSE_SEGMENT_ENABLED", "1") != "0"
PAUSE_BREAK_SECS = float(os.environ.get("VOICETYPER_PAUSE_BREAK_SECS", "0.35"))
PAUSE_STRONG_BREAK_SECS = float(
    os.environ.get("VOICETYPER_PAUSE_STRONG_BREAK_SECS", "0.75")
)
PAUSE_MIN_CHARS = int(os.environ.get("VOICETYPER_PAUSE_MIN_CHARS", "8"))
PAUSE_PROMOTE_WEAK_PUNCT = os.environ.get("VOICETYPER_PAUSE_PROMOTE_WEAK_PUNCT", "0") == "1"
PAUSE_SEGMENT_DEBUG = os.environ.get("VOICETYPER_PAUSE_SEGMENT_DEBUG", "0") == "1"

# Groq API

def _load_api_key_from_config_file() -> str:
    """Load Groq API key from ~/.voicetyper/config.json."""
    try:
        if not CONFIG_PATH.exists():
            return ""
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            return ""
        return str(cfg.get("groq_api_key", "")).strip()
    except Exception:
        return ""


GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip() or _load_api_key_from_config_file()
GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-large-v3"

# Transcription language (None = auto-detect, "zh" = Chinese, "en" = English)
# Auto-detect works well for mixed Chinese/English
LANGUAGE = None

# Recording modes
MODE_TOGGLE = "toggle"
MODE_PTT = "ptt"
DEFAULT_MODE = MODE_TOGGLE
