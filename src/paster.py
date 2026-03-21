"""Paste text at cursor position on macOS."""
import subprocess


def get_frontmost_app() -> str:
    """Get the name of the frontmost application."""
    script = 'tell application "System Events" to get name of first application process whose frontmost is true'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "Unknown"


def paste_text(target_app: str | None = None) -> bool:
    """
    Paste clipboard text at current cursor position.

    If target_app is provided, activate it first to improve focus reliability.
    Returns True when AppleScript executed successfully.
    """
    target_app = (target_app or "").strip()
    activate_block = ""
    if target_app and target_app != "Unknown":
        activate_block = f'''
    tell application "{_escape_applescript(target_app)}" to activate
    delay 0.05
'''

    script = f'''
{activate_block}
    tell application "System Events"
        keystroke "v" using command down
    end tell
'''
    ok, _ = _run_applescript(script, timeout=5)
    if ok:
        return True

    # Fallback: try plain Cmd+V without app activation.
    fallback = '''
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''
    ok, _ = _run_applescript(fallback, timeout=5)
    return ok


def copy_text_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard without restoring previous clipboard."""
    script = f'''
    set the clipboard to "{_escape_applescript(text)}"
    '''
    ok, _ = _run_applescript(script, timeout=5)
    return ok


def insert_newline():
    """Insert a newline at cursor."""
    script = '''
    tell application "System Events"
        key code 36
    end tell
    '''
    _run_applescript(script, timeout=5)


def undo_last_action():
    """Undo the previous action (Cmd+Z)."""
    script = '''
    tell application "System Events"
        keystroke "z" using command down
    end tell
    '''
    _run_applescript(script, timeout=5)


def delete_previous_chars(count: int = 1):
    """Delete characters using Backspace."""
    if count < 1:
        return
    script = f'''
    tell application "System Events"
        repeat {int(count)} times
            key code 51
        end repeat
    end tell
    '''
    _run_applescript(script, timeout=5)


def _run_applescript(script: str, timeout: float = 5) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:
        return False, str(exc)

    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def _escape_applescript(text: str) -> str:
    """Escape special characters for AppleScript string."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
