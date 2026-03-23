"""VoiceTyper - macOS menu bar voice input app."""
import threading
import time
from pathlib import Path
import rumps
from pynput import keyboard

from src.config import (
    MODE_TOGGLE,
    AI_FIRST_ENABLED,
    DEBUG_PIPELINE_ENABLED,
    DEBUG_PIPELINE_MAX_CHARS,
    LIVE_PREVIEW_ENABLED,
    LIVE_PREVIEW_INTERVAL_SECS,
    LIVE_PREVIEW_MIN_DELTA_SECS,
    LIVE_PREVIEW_MIN_AUDIO_SECS,
    TRANSCRIBE_HARD_TIMEOUT_SECS,
    DATA_DIR,
    SAMPLE_RATE,
)
from src.recorder import Recorder
from src.audio_io import write_wav
from src.transcriber import Transcriber
from src.paster import (
    paste_text,
    copy_text_to_clipboard,
    get_frontmost_app,
    insert_newline,
    undo_last_action,
)
from src.db import init_db, save_transcription, get_recent
from src.text_formatter import (
    STYLE_NORMAL,
    STYLE_LABELS,
    SUPPORTED_STYLES,
    format_text,
)
from src.text_rewriter import TextRewriter
from src.pause_segmenter import apply_pause_segmentation, build_pause_hints
from src.visual_hud import VisualHUD
from src.voice_commands import (
    parse_voice_command,
    CMD_NEWLINE,
    CMD_UNDO,
    CMD_DELETE_LAST,
    CMD_SET_STYLE,
)


# ── Hotkey config ───────────────────────────────────────────────
# Fixed toggle hotkey: Shift + Option
SHIFT_KEYS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
ALT_KEYS = {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}


class VoiceTyperApp(rumps.App):
    def __init__(self):
        super().__init__(
            "VoiceTyper",
            icon=None,
            title="🎙️",
            quit_button=None,
        )

        self.recorder = Recorder()
        self.transcriber = Transcriber()
        self.rewriter = TextRewriter()
        self.mode = MODE_TOGGLE
        self.input_style = STYLE_NORMAL
        self._live_preview_enabled = LIVE_PREVIEW_ENABLED
        self._visual_hud_enabled = True
        self._pressed_keys: set = set()
        self._toggle_hotkey_latched = False
        self._notifications_enabled = True
        self._recording_stop_lock = threading.Lock()
        self._live_preview_stop = threading.Event()
        self._live_preview_thread: threading.Thread | None = None
        self._recording_session_id = 0
        self.visual_hud = VisualHUD(enabled=self._visual_hud_enabled)

        # Build menu
        self.mode_toggle = rumps.MenuItem(
            "Mode: Toggle (Fixed)",
            callback=None,
        )
        self.mode_toggle.set_callback(None)
        self.style_toggle = rumps.MenuItem(
            f"Style: {STYLE_LABELS[self.input_style]}",
            callback=self._cycle_style,
        )
        self.preview_toggle = rumps.MenuItem(
            f"Live Preview: {'On' if self._live_preview_enabled else 'Off'}",
            callback=self._toggle_live_preview,
        )
        self.hud_toggle = rumps.MenuItem(
            f"Visual HUD: {'On' if self._visual_hud_enabled else 'Off'}",
            callback=self._toggle_visual_hud,
        )
        self.status_item = rumps.MenuItem("Ready", callback=None)
        self.status_item.set_callback(None)

        self.menu = [
            self.status_item,
            None,  # separator
            self.mode_toggle,
            self.style_toggle,
            self.preview_toggle,
            self.hud_toggle,
            rumps.MenuItem("History (last 5)", callback=self._show_history),
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]

        # Init DB
        init_db()

        # Start hotkey listener in background
        self._start_hotkey_listener()

    def _notify(self, title: str, subtitle: str, message: str, sound: bool = False):
        """Best-effort notification that never breaks hotkey or worker threads."""
        if not self._notifications_enabled:
            return
        try:
            rumps.notification(
                title=title,
                subtitle=subtitle,
                message=message,
                sound=sound,
            )
        except Exception as exc:
            self._notifications_enabled = False
            print("[VoiceTyper] macOS notification center unavailable; continuing without alerts.")
            print(f"[VoiceTyper] Notification error: {exc}")

    def _clip_debug(self, text: str | None) -> str:
        if text is None:
            return ""
        s = str(text).replace("\n", "\\n")
        if DEBUG_PIPELINE_MAX_CHARS > 0 and len(s) > DEBUG_PIPELINE_MAX_CHARS:
            return f"{s[:DEBUG_PIPELINE_MAX_CHARS]}..."
        return s

    def _log_pipeline(
        self,
        *,
        ai_first: bool,
        ai_first_config: bool,
        rewrite_enabled: bool,
        asr_text: str,
        pause_hints: str | None,
        rewritten: str,
        final_text: str,
    ) -> None:
        if not DEBUG_PIPELINE_ENABLED:
            return
        print("[VoiceTyper][Pipeline] ---")
        print(f"[VoiceTyper][Pipeline] mode={'AI-first' if ai_first else 'Rule-first'}")
        print(
            "[VoiceTyper][Pipeline] flags : "
            f"AI_FIRST_ENABLED={ai_first_config} "
            f"AI_REWRITE_ACTIVE={rewrite_enabled}"
        )
        print(f"[VoiceTyper][Pipeline] ASR   : {self._clip_debug(asr_text)}")
        if pause_hints:
            print(f"[VoiceTyper][Pipeline] Hints : {self._clip_debug(pause_hints)}")
        print(f"[VoiceTyper][Pipeline] AI    : {self._clip_debug(rewritten)}")
        print(f"[VoiceTyper][Pipeline] Final : {self._clip_debug(final_text)}")

    # ── Hotkey listener ──────────────────────────────────────────

    def _start_hotkey_listener(self):
        listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        listener.daemon = True
        listener.start()

    def _on_key_press(self, key):
        self._pressed_keys.add(key)

        if self._is_toggle_combo_active() and not self._toggle_hotkey_latched:
            self._toggle_hotkey_latched = True
            self._toggle_recording()

    def _on_key_release(self, key):
        self._pressed_keys.discard(key)

        # Reset edge trigger after combo is released.
        if not self._is_toggle_combo_active():
            self._toggle_hotkey_latched = False

    # ── Recording control ────────────────────────────────────────

    def _toggle_recording(self):
        if self.recorder.is_recording:
            self._stop_and_transcribe()
        else:
            self._start_recording()

    def _start_recording(self):
        self.title = "🔴"
        self.status_item.title = "Recording..."
        try:
            self.recorder.start()
        except Exception as exc:
            self.title = "🎙️"
            self.status_item.title = "Ready"
            self.visual_hud.show_error("Recording failed")
            self._notify(
                title="VoiceTyper",
                subtitle="Recording failed",
                message=str(exc),
                sound=True,
            )
            return

        self._recording_session_id += 1
        self.visual_hud.show_recording()
        if self._live_preview_enabled:
            self._start_live_preview(self._recording_session_id)

        self._notify(
            title="VoiceTyper",
            subtitle="Recording started",
            message="Speak now...",
            sound=False,
        )

    def _stop_and_transcribe(self):
        with self._recording_stop_lock:
            if not self.recorder.is_recording:
                return

            self._live_preview_stop.set()
            self.title = "⏳"
            self.status_item.title = "Transcribing..."
            self.visual_hud.show_transcribing()

            # Get source app before we lose focus
            source_app = get_frontmost_app()
            duration = self.recorder.get_duration()
            audio_path = self.recorder.stop()

        if not audio_path:
            self.title = "🎙️"
            self.status_item.title = "Ready"
            self.visual_hud.hide()
            return

        # Transcribe in background to not block
        def _do_transcribe():
            try:
                result_holder: dict = {}
                error_holder: dict = {}
                done = threading.Event()

                def _call_transcribe():
                    try:
                        result_holder["result"] = self.transcriber.transcribe(audio_path)
                    except Exception as exc:
                        error_holder["error"] = exc
                    finally:
                        done.set()

                threading.Thread(target=_call_transcribe, daemon=True).start()

                if not done.wait(TRANSCRIBE_HARD_TIMEOUT_SECS):
                    message = (
                        f"[Transcription timeout: exceeded {TRANSCRIBE_HARD_TIMEOUT_SECS:.0f}s]"
                    )
                    self.status_item.title = "Error: transcription timeout"
                    self.visual_hud.show_error("Timeout")
                    self._notify(
                        title="VoiceTyper",
                        subtitle="Transcription timed out",
                        message=message,
                        sound=True,
                    )
                    return

                if "error" in error_holder:
                    raise error_holder["error"]

                result = result_holder.get("result", {"text": "", "language": None, "segments": []})
                text = result["text"]

                if text and not text.startswith("["):
                    command = parse_voice_command(text)
                    if command:
                        self._apply_voice_command(command)
                        cmd_name = command["name"]
                        self.status_item.title = f"Command: {cmd_name}"
                        self.visual_hud.show_done("Command sent")
                        self._notify(
                            title="VoiceTyper",
                            subtitle="Voice command executed",
                            message=cmd_name,
                            sound=False,
                        )
                    else:
                        segments = result.get("segments")
                        ai_first_config = AI_FIRST_ENABLED
                        rewrite_enabled = self.rewriter.enabled
                        ai_first_active = ai_first_config and rewrite_enabled
                        rewrite_input = text
                        pause_hints = None

                        if ai_first_active:
                            pause_hints = build_pause_hints(segments)
                        else:
                            rewrite_input = apply_pause_segmentation(
                                text=text,
                                segments=segments,
                                style=self.input_style,
                            )

                        rewritten = self.rewriter.rewrite(
                            rewrite_input,
                            self.input_style,
                            pause_hints=pause_hints,
                        )
                        if ai_first_active and rewritten == rewrite_input:
                            # AI no-op fallback: use pause-based deterministic punctuation.
                            rewritten = apply_pause_segmentation(
                                text=rewrite_input,
                                segments=segments,
                                style=self.input_style,
                            )
                        final_text = format_text(rewritten, self.input_style)
                        self._log_pipeline(
                            ai_first=ai_first_active,
                            ai_first_config=ai_first_config,
                            rewrite_enabled=rewrite_enabled,
                            asr_text=text,
                            pause_hints=pause_hints,
                            rewritten=rewritten,
                            final_text=final_text,
                        )
                        if not final_text:
                            self.status_item.title = "Error: empty text"
                            self.visual_hud.show_error("Empty text")
                            self._notify(
                                title="VoiceTyper",
                                subtitle="Transcription failed",
                                message="[Empty text after formatting]",
                                sound=True,
                            )
                            return

                        # Copy first, then paste back to the previously focused app.
                        copied = copy_text_to_clipboard(final_text)
                        pasted = paste_text(target_app=source_app) if copied else False
                        if copied and not pasted:
                            print(f"[VoiceTyper] Paste fallback: copied only (target_app={source_app!r})")

                        # Save to DB
                        save_transcription(
                            text=final_text,
                            language=result.get("language"),
                            duration_secs=round(duration, 1),
                            source_app=source_app,
                        )

                        if pasted:
                            self.status_item.title = f"Copied+Pasted: {final_text[:30]}..."
                            self.visual_hud.show_done("Pasted")
                        elif copied:
                            self.status_item.title = f"Copied only: {final_text[:31]}..."
                            self.visual_hud.show_done("Copied")
                        else:
                            self.status_item.title = "Error: clipboard write failed"
                            self.visual_hud.show_error("Clipboard failed")
                        self._notify(
                            title="VoiceTyper",
                            subtitle="Transcribed output ready",
                            message=final_text[:80],
                            sound=False,
                        )
                else:
                    message = text or "[Transcription returned empty text]"
                    self.status_item.title = f"Error: {message}"
                    self.visual_hud.show_error("Transcription failed")
                    self._notify(
                        title="VoiceTyper",
                        subtitle="Transcription failed",
                        message=message,
                        sound=True,
                    )
            except Exception as exc:
                message = f"[Unexpected transcription error: {exc}]"
                self.status_item.title = "Error: unexpected transcription failure"
                self.visual_hud.show_error("Transcription failed")
                self._notify(
                    title="VoiceTyper",
                    subtitle="Transcription failed",
                    message=message,
                    sound=True,
                )
            finally:
                try:
                    Path(audio_path).unlink()
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
                self.title = "🎙️"

        threading.Thread(target=_do_transcribe, daemon=True).start()

    def _start_live_preview(self, session_id: int):
        if self._live_preview_thread and self._live_preview_thread.is_alive():
            self._live_preview_stop.set()
        self._live_preview_stop = threading.Event()

        def _preview():
            preview_transcriber = Transcriber()
            last_preview_samples = 0
            try:
                while not self._live_preview_stop.is_set():
                    if not self.recorder.is_recording:
                        return
                    time.sleep(LIVE_PREVIEW_INTERVAL_SECS)
                    if self._live_preview_stop.is_set() or not self.recorder.is_recording:
                        return

                    audio = self.recorder.get_audio_snapshot()
                    if audio is None:
                        continue

                    total_samples = len(audio)
                    total_secs = total_samples / SAMPLE_RATE
                    if total_secs < LIVE_PREVIEW_MIN_AUDIO_SECS:
                        continue
                    if (total_samples - last_preview_samples) < int(
                        SAMPLE_RATE * LIVE_PREVIEW_MIN_DELTA_SECS
                    ):
                        continue
                    last_preview_samples = total_samples

                    preview_path = (
                        DATA_DIR / f"preview-{threading.get_ident()}-{int(time.time() * 1000)}.wav"
                    )
                    try:
                        write_wav(preview_path, audio, SAMPLE_RATE)
                        preview_result = preview_transcriber.transcribe(str(preview_path))
                    except Exception:
                        continue
                    finally:
                        try:
                            preview_path.unlink()
                        except FileNotFoundError:
                            pass
                        except Exception:
                            pass

                    preview_text = preview_result.get("text", "").strip()
                    if not preview_text or preview_text.startswith("["):
                        continue
                    preview_text = format_text(preview_text, self.input_style)
                    if (
                        preview_text
                        and self.recorder.is_recording
                        and session_id == self._recording_session_id
                    ):
                        self.status_item.title = f"Live: {preview_text[:40]}..."
            finally:
                preview_transcriber.close()

        self._live_preview_thread = threading.Thread(target=_preview, daemon=True)
        self._live_preview_thread.start()

    def _apply_voice_command(self, command: dict):
        name = command["name"]
        if name == CMD_NEWLINE:
            insert_newline()
            return
        if name in (CMD_UNDO, CMD_DELETE_LAST):
            undo_last_action()
            return
        if name == CMD_SET_STYLE:
            style = command.get("style")
            if style in SUPPORTED_STYLES:
                self.input_style = style
                self.style_toggle.title = f"Style: {STYLE_LABELS[self.input_style]}"

    def _is_toggle_combo_active(self) -> bool:
        has_shift = any(k in self._pressed_keys for k in SHIFT_KEYS)
        has_alt = any(k in self._pressed_keys for k in ALT_KEYS)
        return has_shift and has_alt

    # ── Menu actions ─────────────────────────────────────────────

    def _cycle_style(self, sender):
        styles = list(SUPPORTED_STYLES)
        idx = styles.index(self.input_style)
        self.input_style = styles[(idx + 1) % len(styles)]
        self.style_toggle.title = f"Style: {STYLE_LABELS[self.input_style]}"
        self._notify(
            title="VoiceTyper",
            subtitle="Input style changed",
            message=f"Style: {STYLE_LABELS[self.input_style]}",
            sound=False,
        )

    def _toggle_live_preview(self, sender):
        self._live_preview_enabled = not self._live_preview_enabled
        if self._live_preview_enabled and self.recorder.is_recording:
            self._start_live_preview(self._recording_session_id)
        elif not self._live_preview_enabled:
            self._live_preview_stop.set()
        self.preview_toggle.title = (
            f"Live Preview: {'On' if self._live_preview_enabled else 'Off'}"
        )
        self._notify(
            title="VoiceTyper",
            subtitle="Live preview updated",
            message=self.preview_toggle.title,
            sound=False,
        )

    def _toggle_visual_hud(self, sender):
        self._visual_hud_enabled = not self._visual_hud_enabled
        self.visual_hud.set_enabled(self._visual_hud_enabled)
        self.hud_toggle.title = f"Visual HUD: {'On' if self._visual_hud_enabled else 'Off'}"
        self._notify(
            title="VoiceTyper",
            subtitle="Visual HUD updated",
            message=self.hud_toggle.title,
            sound=False,
        )

    def _show_history(self, sender):
        recent = get_recent(5)
        if not recent:
            rumps.alert("No transcriptions yet.")
            return

        lines = []
        for r in recent:
            ts = r["created_at"][:16]  # trim seconds
            text = r["text"][:60]
            app = r["source_app"] or "?"
            lines.append(f"[{ts}] ({app}) {text}")

        rumps.alert(
            title="Recent Transcriptions",
            message="\n\n".join(lines),
        )

    def _quit(self, sender):
        self._live_preview_stop.set()
        self.visual_hud.close()
        self.rewriter.close()
        self.transcriber.close()
        rumps.quit_application()


def run():
    VoiceTyperApp().run()
