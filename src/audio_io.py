"""Audio IO helpers without external libsndfile dependency."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    """
    Write float32/float64 PCM audio to mono/stereo 16-bit WAV.

    Expected input shape:
    - (samples,) for mono
    - (samples, channels) for multi-channel
    """
    arr = np.asarray(audio)
    if arr.ndim == 1:
        channels = 1
    elif arr.ndim == 2:
        channels = arr.shape[1]
    else:
        raise ValueError(f"Unsupported audio shape: {arr.shape}")

    # Convert to signed 16-bit PCM.
    pcm = np.clip(arr, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
