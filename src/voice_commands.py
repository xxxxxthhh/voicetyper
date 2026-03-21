"""Voice command parsing for dictation control."""
import re

from src.text_formatter import (
    STYLE_NORMAL,
    STYLE_ENGLISH,
    STYLE_CHINESE,
    STYLE_CODE,
)

CMD_NEWLINE = "newline"
CMD_UNDO = "undo"
CMD_DELETE_LAST = "delete_last"
CMD_SET_STYLE = "set_style"

_SET_STYLE_MAP = {
    "normal mode": STYLE_NORMAL,
    "normal input": STYLE_NORMAL,
    "普通模式": STYLE_NORMAL,
    "英文模式": STYLE_ENGLISH,
    "english mode": STYLE_ENGLISH,
    "英语模式": STYLE_ENGLISH,
    "中文模式": STYLE_CHINESE,
    "chinese mode": STYLE_CHINESE,
    "mandarin mode": STYLE_CHINESE,
    "代码模式": STYLE_CODE,
    "code mode": STYLE_CODE,
    "coding mode": STYLE_CODE,
}

_NEWLINE_SET = {
    "new line",
    "newline",
    "next line",
    "换行",
    "下一行",
}

_UNDO_SET = {
    "undo",
    "撤销",
}

_DELETE_LAST_SET = {
    "delete last",
    "delete that",
    "删除上一句",
    "删掉上一句",
    "删除上句",
}


def parse_voice_command(text: str) -> dict | None:
    """Parse a transcription result into a command action."""
    normalized = _normalize(text)
    if not normalized:
        return None

    if normalized in _NEWLINE_SET:
        return {"name": CMD_NEWLINE}
    if normalized in _UNDO_SET:
        return {"name": CMD_UNDO}
    if normalized in _DELETE_LAST_SET:
        return {"name": CMD_DELETE_LAST}
    if normalized in _SET_STYLE_MAP:
        return {"name": CMD_SET_STYLE, "style": _SET_STYLE_MAP[normalized]}
    return None


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[。！？!?,，；;：:\.]+$", "", text)
    return text
