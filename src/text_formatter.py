"""Post-processing for transcribed text."""
import re

STYLE_NORMAL = "normal"
STYLE_ENGLISH = "english"
STYLE_CHINESE = "chinese"
STYLE_CODE = "code"

STYLE_LABELS = {
    STYLE_NORMAL: "Normal",
    STYLE_ENGLISH: "English",
    STYLE_CHINESE: "Chinese",
    STYLE_CODE: "Code",
}

SUPPORTED_STYLES = (
    STYLE_NORMAL,
    STYLE_ENGLISH,
    STYLE_CHINESE,
    STYLE_CODE,
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TRAILING_CLOSERS = set('"\')]}）】」』》”’')


def format_text(text: str, style: str) -> str:
    """Format transcription text for paste output."""
    if style not in SUPPORTED_STYLES:
        style = STYLE_NORMAL

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = _strip_unmatched_trailing_quotes(cleaned)
    if not cleaned:
        return ""

    if style == STYLE_CODE:
        return _format_code(cleaned)
    if style == STYLE_ENGLISH:
        return _format_english(cleaned)
    if style == STYLE_CHINESE:
        return _format_chinese(cleaned)
    return _format_mixed(cleaned)


def _format_code(text: str) -> str:
    # Preserve newlines for coding dictation and only trim noisy spacing.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _format_english(text: str) -> str:
    text = _normalize_spaces(text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?])([A-Za-z])", r"\1 \2", text)
    text = _capitalize_sentences(text)
    if text and not _ends_with_terminal_punctuation(text, ".!?"):
        text = _append_terminal_punctuation(text, ".")
    return text


def _format_chinese(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    text = text.translate(
        str.maketrans({
            ",": "，",
            ".": "。",
            "?": "？",
            "!": "！",
            ":": "：",
            ";": "；",
        })
    )
    if text and not _ends_with_terminal_punctuation(text, "。！？"):
        text = _append_terminal_punctuation(text, "。")
    return text


def _format_mixed(text: str) -> str:
    text = _normalize_spaces(text)

    # Remove spaces between Chinese characters and before punctuation.
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", text)
    text = re.sub(r"([,.;:!?])([A-Za-z0-9])", r"\1 \2", text)

    if not text:
        return text

    if not _ends_with_terminal_punctuation(text, "。！？.!?"):
        if _cjk_ratio(text) >= 0.4:
            text = _append_terminal_punctuation(text, "。")
        else:
            text = _capitalize_sentences(text)
            text = _append_terminal_punctuation(text, ".")
    else:
        text = _capitalize_sentences(text)
    return text


def _normalize_spaces(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _capitalize_sentences(text: str) -> str:
    def _cap(match):
        head = match.group(1)
        ch = match.group(2)
        return f"{head}{ch.upper()}"

    text = re.sub(r"(^|[.!?]\s+)([a-z])", _cap, text)
    return text


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk_count = len(_CJK_RE.findall(text))
    return cjk_count / max(len(text), 1)


def _strip_unmatched_trailing_quotes(text: str) -> str:
    out = text.rstrip()
    out = _strip_unmatched_quote_before_terminal(out)
    while out:
        ch = out[-1]
        if ch == "”":
            if out.count("“") < out.count("”"):
                out = out[:-1].rstrip()
                out = _strip_unmatched_quote_before_terminal(out)
                continue
            break
        if ch == "’":
            if out.count("‘") < out.count("’"):
                out = out[:-1].rstrip()
                out = _strip_unmatched_quote_before_terminal(out)
                continue
            break
        if ch == '"':
            if out.count('"') % 2 == 1:
                out = out[:-1].rstrip()
                out = _strip_unmatched_quote_before_terminal(out)
                continue
            break
        break
    return out


def _strip_unmatched_quote_before_terminal(text: str) -> str:
    if len(text) < 2:
        return text
    terminal = text[-1]
    prev = text[-2]
    if terminal not in "。！？.!?":
        return text
    if prev == "”" and text.count("“") < text.count("”"):
        return text[:-2] + terminal
    if prev == "’" and text.count("‘") < text.count("’"):
        return text[:-2] + terminal
    if prev == '"' and text.count('"') % 2 == 1:
        return text[:-2] + terminal
    return text


def _ends_with_terminal_punctuation(text: str, terminals: str) -> bool:
    idx = len(text) - 1
    while idx >= 0 and (text[idx].isspace() or text[idx] in _TRAILING_CLOSERS):
        idx -= 1
    return idx >= 0 and text[idx] in terminals


def _append_terminal_punctuation(text: str, punct: str) -> str:
    insert_at = len(text)
    while insert_at > 0 and text[insert_at - 1] in _TRAILING_CLOSERS:
        insert_at -= 1
    return f"{text[:insert_at]}{punct}{text[insert_at:]}"
