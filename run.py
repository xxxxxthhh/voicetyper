#!/usr/bin/env python3
"""VoiceTyper - System-wide voice input for macOS."""
import sys
import os

# Ensure GROQ_API_KEY is set
if not os.environ.get("GROQ_API_KEY"):
    print("❌ GROQ_API_KEY environment variable not set.")
    print("   export GROQ_API_KEY='your-key-here'")
    sys.exit(1)

from src.app import run

if __name__ == "__main__":
    print("🎙️ VoiceTyper starting...")
    print("   Toggle mode: Shift+Option (fixed)")
    print("   Menu bar:    Look for 🎙️ icon")
    run()
