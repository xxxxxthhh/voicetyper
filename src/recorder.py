"""Audio recording using sounddevice."""
import threading
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
from src.config import SAMPLE_RATE, CHANNELS, DATA_DIR, VAD_RMS_THRESHOLD


class Recorder:
    """Thread-safe audio recorder."""

    def __init__(self):
        self._frames: list[np.ndarray] = []
        self._recording = False
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._started_at = 0.0
        self._last_voice_at = 0.0
        self._voice_detected = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self):
        """Start recording audio."""
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._recording = True
            now = time.monotonic()
            self._started_at = now
            self._last_voice_at = now
            self._voice_detected = False
            try:
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self._stream.start()
            except Exception:
                if self._stream:
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                self._stream = None
                self._recording = False
                self._frames = []
                self._started_at = 0.0
                self._last_voice_at = 0.0
                self._voice_detected = False
                raise

    def stop(self) -> str | None:
        """Stop recording and save to file. Returns filepath or None if too short."""
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

            if not self._frames:
                self._started_at = 0.0
                self._last_voice_at = 0.0
                self._voice_detected = False
                return None

            audio = np.concatenate(self._frames, axis=0)
            duration = len(audio) / SAMPLE_RATE

            # Skip recordings shorter than 0.3s (likely accidental)
            if duration < 0.3:
                self._started_at = 0.0
                self._last_voice_at = 0.0
                self._voice_detected = False
                return None

            filename = f"recording-{threading.get_ident()}-{int(time.time() * 1000)}.wav"
            audio_path = DATA_DIR / filename
            sf.write(str(audio_path), audio, SAMPLE_RATE)
            self._started_at = 0.0
            self._last_voice_at = 0.0
            self._voice_detected = False
            return str(audio_path)

    def get_duration(self) -> float:
        """Get current recording duration in seconds."""
        with self._lock:
            if not self._frames:
                return 0.0
            total_samples = sum(len(f) for f in self._frames)
            return total_samples / SAMPLE_RATE

    def should_auto_stop(self, min_record_secs: float, silence_secs: float) -> bool:
        """Whether recording should auto-stop based on silence."""
        with self._lock:
            if not self._recording:
                return False
            duration = 0.0
            if self._frames:
                duration = sum(len(f) for f in self._frames) / SAMPLE_RATE
            if duration < min_record_secs:
                return False
            if not self._voice_detected:
                return False
            return (time.monotonic() - self._last_voice_at) >= silence_secs

    def get_audio_snapshot(self) -> np.ndarray | None:
        """Get a copy of current audio buffer for live preview."""
        with self._lock:
            if not self._frames:
                return None
            return np.concatenate([f.copy() for f in self._frames], axis=0)

    def _audio_callback(self, indata, frames, timing_info, status):
        if status:
            print(f"[Recorder] {status}")
        with self._lock:
            if not self._recording:
                return
            self._frames.append(indata.copy())
            rms = float(np.sqrt(np.mean(np.square(indata))))
            if rms >= VAD_RMS_THRESHOLD:
                self._voice_detected = True
                self._last_voice_at = time.monotonic()
