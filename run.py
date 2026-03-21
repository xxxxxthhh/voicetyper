#!/usr/bin/env python3
"""VoiceTyper - System-wide voice input for macOS."""

from src.config import GROQ_API_KEY, CONFIG_PATH
from src.app import run

if __name__ == "__main__":
    print("🎙️ VoiceTyper starting...")
    print("   Toggle mode: Shift+Option (fixed)")
    print("   Menu bar:    Look for 🎙️ icon")
    if not GROQ_API_KEY:
        print("⚠️  GROQ_API_KEY not set.")
        print("   Option A: export GROQ_API_KEY='your-key-here'")
        print(f"   Option B: write key file at {CONFIG_PATH}")
    run()
