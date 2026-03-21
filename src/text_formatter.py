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


def format_text(text: str, style: str) -> str:
    """Format transcription text for paste output."""
    if style not in SUPPORTED_STYLES:
        style = STYLE_NORMAL

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
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
    if text and text[-1] not in ".!?":
        text += "."
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
    if text and text[-1] not in "。！？":
        text += "。"
    return text


def _format_mixed(text: str) -> str:
    text = _normalize_spaces(text)

    # Remove spaces between Chinese characters and before punctuation.
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", text)
    text = re.sub(r"([,.;:!?])([A-Za-z0-9])", r"\1 \2", text)

    if not text:
        return text

    if text[-1] not in "。！？.!?":
        if _cjk_ratio(text) >= 0.4:
            text += "。"
        else:
            text = _capitalize_sentences(text)
            text += "."
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
