"""Groq Whisper transcription."""
import httpx
from src.config import GROQ_API_KEY, GROQ_API_URL, WHISPER_MODEL, LANGUAGE


class Transcriber:
    """Transcribe audio files using Groq Whisper API."""

    def __init__(self):
        self._client = httpx.Client(timeout=30.0)

    def transcribe(self, audio_path: str) -> dict:
        """
        Transcribe an audio file.
        Returns: {"text": str, "language": str | None}
        """
        if not GROQ_API_KEY:
            return {"text": "[Error: GROQ_API_KEY not set]", "language": None}

        with open(audio_path, "rb") as f:
            data = {
                "model": WHISPER_MODEL,
                "response_format": "verbose_json",
            }
            if LANGUAGE:
                data["language"] = LANGUAGE

            try:
                resp = self._client.post(
                    GROQ_API_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    data=data,
                    files={"file": ("recording.wav", f, "audio/wav")},
                )
            except httpx.RequestError as exc:
                return {
                    "text": f"[Network error: {exc}]",
                    "language": None,
                }

        if resp.status_code != 200:
            return {
                "text": f"[Transcription error: {resp.status_code}]",
                "language": None,
            }

        try:
            result = resp.json()
        except ValueError:
            return {
                "text": "[Transcription error: invalid JSON response]",
                "language": None,
            }
        return {
            "text": result.get("text", "").strip(),
            "language": result.get("language"),
        }

    def close(self):
        self._client.close()
