"""py2app build script for VoiceTyper."""
from __future__ import annotations

import subprocess
from pathlib import Path

from setuptools import setup


APP = ["run.py"]
ROOT = Path(__file__).parent
ICON_PATH = ROOT / "assets" / "icon.icns"


def _find_portaudio_frameworks() -> list[str]:
    candidates = [
        "/opt/homebrew/lib/libportaudio.2.dylib",
        "/usr/local/lib/libportaudio.2.dylib",
        "/opt/homebrew/lib/libportaudio.dylib",
        "/usr/local/lib/libportaudio.dylib",
    ]

    try:
        prefix = (
            subprocess.check_output(["brew", "--prefix", "portaudio"], text=True)
            .strip()
        )
        if prefix:
            candidates = [
                f"{prefix}/lib/libportaudio.2.dylib",
                f"{prefix}/lib/libportaudio.dylib",
            ] + candidates
    except Exception:
        pass

    existing = []
    seen = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if Path(p).exists():
            existing.append(p)
    return existing


OPTIONS = {
    "argv_emulation": False,
    "iconfile": str(ICON_PATH) if ICON_PATH.exists() else None,
    "plist": {
        "CFBundleName": "VoiceTyper",
        "CFBundleDisplayName": "VoiceTyper",
        "CFBundleIdentifier": "com.voicetyper.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "NSMicrophoneUsageDescription": (
            "VoiceTyper needs microphone access to record your voice."
        ),
        "NSAppleEventsUsageDescription": (
            "VoiceTyper needs Apple Events permission to paste text."
        ),
    },
    "packages": [
        "src",
        "_sounddevice_data",
        "httpx",
        "httpcore",
        "anyio",
        "certifi",
        "h11",
        "idna",
        "sniffio",
        "numpy",
    ],
    "includes": [
        "rumps",
        "pynput",
        "pynput._util.darwin",
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        "sounddevice",
        "_cffi_backend",
    ],
    "excludes": [
        "tkinter",
        "unittest",
        "pydoc",
        "doctest",
    ],
    "frameworks": _find_portaudio_frameworks(),
}

# Remove None values to keep py2app options clean.
OPTIONS = {k: v for k, v in OPTIONS.items() if v is not None}

setup(
    name="VoiceTyper",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
