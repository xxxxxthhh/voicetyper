"""Post-processing for transcribed text."""
import re
import unicodedata

from src.config import AUTO_TERMINAL_MIN_CHARS

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
_CLAUSE_BREAK_MARKERS = (
    "但是",
    "不过",
    "所以",
    "然后",
    "而且",
    "因为",
    "如果",
    "其实",
    "另外",
    "最后",
    "并且",
    "同时",
    "主要是",
    "就是",
    "否则",
    "此外",
)
_CHUNK_PREFERRED_ENDINGS = set("了吧啊呀呢嘛吗")
_AVOID_BREAK_BEFORE = set("这那我你他她它您")
_AVOID_BREAK_AROUND = set("之")


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
    if text and not _ends_with_terminal_punctuation(text, ".!?") and _should_auto_append_terminal(text):
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
    text = _smart_split_long_cjk_clause(text)
    if text and not _ends_with_terminal_punctuation(text, "。！？") and _should_auto_append_terminal(text):
        text = _append_terminal_punctuation(text, "。")
    return text


def _format_mixed(text: str) -> str:
    text = _normalize_spaces(text)

    # Remove spaces between Chinese characters and before punctuation.
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", text)
    text = re.sub(r"([,.;:!?])([A-Za-z0-9])", r"\1 \2", text)
    if _cjk_ratio(text) >= 0.45:
        text = text.translate(str.maketrans({",": "，", ";": "；", ":": "："}))
        text = _smart_split_long_cjk_clause(text)

    if not text:
        return text

    if not _ends_with_terminal_punctuation(text, "。！？.!?"):
        if _should_auto_append_terminal(text):
            if _cjk_ratio(text) >= 0.4:
                text = _append_terminal_punctuation(text, "。")
            else:
                text = _capitalize_sentences(text)
                text = _append_terminal_punctuation(text, ".")
        else:
            text = _capitalize_sentences(text)
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


def _should_auto_append_terminal(text: str) -> bool:
    return _content_char_count(text) >= AUTO_TERMINAL_MIN_CHARS


def _content_char_count(text: str) -> int:
    count = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if cat and cat[0] in {"L", "N", "M"}:
            count += 1
    return count


def _smart_split_long_cjk_clause(text: str) -> str:
    """
    Deterministic fallback clause splitter for long Chinese-heavy utterances.
    It prefers connector boundaries and then uses length-based fallback cuts.
    """
    if not text or _cjk_ratio(text) < 0.45:
        return text
    content_len = _content_char_count(text)
    if content_len < 24:
        return text

    connector_candidates = _connector_break_candidates(text)
    target_commas = _target_clause_commas(content_len)
    if target_commas <= 0 and connector_candidates and content_len >= 22:
        target_commas = 1
    if target_commas <= 0:
        return text

    existing_commas = sum(1 for ch in text if ch in {"，", "、"})
    need = target_commas - existing_commas
    if need <= 0:
        return text

    candidates = list(connector_candidates)
    # Length fallback is only for very long run-on utterances.
    if len(candidates) < need and content_len >= 52:
        candidates.extend(_chunk_break_candidates(text, chunk=22))
    candidates = _dedupe_preserve_order(candidates)
    if not candidates:
        return text

    existing_breaks = {i for i, ch in enumerate(text) if ch in "，、。！？,.!?;；："}
    selected: list[int] = []
    for idx in candidates:
        if len(selected) >= need:
            break
        if not _can_insert_clause_comma(text, idx):
            continue
        if not _has_min_clause_span(text, idx, existing_breaks, selected):
            continue
        selected.append(idx)

    if not selected:
        return text

    out: list[str] = []
    selected_set = set(selected)
    for i, ch in enumerate(text):
        out.append(ch)
        if i in selected_set:
            out.append("，")
    merged = "".join(out)
    merged = re.sub(r"([，、])\1{1,}", r"\1", merged)
    return merged


def _connector_break_candidates(text: str) -> list[int]:
    out: list[int] = []
    for marker in _CLAUSE_BREAK_MARKERS:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx < 0:
                break
            if idx > 0:
                out.append(idx - 1)
            start = idx + len(marker)
    return out


def _chunk_break_candidates(text: str, chunk: int) -> list[int]:
    content_idx = [i for i, ch in enumerate(text) if _is_content_char(ch)]
    if len(content_idx) <= chunk:
        return []
    out: list[int] = []
    n = chunk
    while n < len(content_idx):
        idx = content_idx[n - 1]
        out.append(_snap_chunk_boundary(text, idx))
        n += chunk
    return out


def _dedupe_preserve_order(items: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for it in items:
        if it in seen:
            continue
        seen.add(it)
        out.append(it)
    return out


def _can_insert_clause_comma(text: str, idx: int) -> bool:
    if idx < 1 or idx >= len(text) - 1:
        return False
    left = text[idx]
    right = text[idx + 1]
    if left.isspace() or right.isspace():
        return False
    if left in _TRAILING_CLOSERS:
        return False
    if left in _AVOID_BREAK_AROUND or right in _AVOID_BREAK_AROUND:
        return False
    if right in _AVOID_BREAK_BEFORE and left not in _CHUNK_PREFERRED_ENDINGS:
        return False
    if left.isascii() and left.isalnum() and right.isascii() and right.isalnum():
        return False
    if _is_punctuation(left) or _is_punctuation(right):
        return False
    return True


def _snap_chunk_boundary(text: str, center_idx: int) -> int:
    left = max(1, center_idx - 4)
    right = min(len(text) - 2, center_idx + 4)
    best = center_idx
    best_dist = None
    for idx in range(left, right + 1):
        if text[idx] not in _CHUNK_PREFERRED_ENDINGS:
            continue
        dist = abs(idx - center_idx)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best = idx
    return best


def _has_min_clause_span(
    text: str,
    idx: int,
    existing_breaks: set[int],
    selected_breaks: list[int],
) -> bool:
    # Ensure both sides have enough lexical content, to avoid over-splitting.
    all_breaks = sorted(existing_breaks | set(selected_breaks))
    prev_break = -1
    next_break = len(text)
    for b in all_breaks:
        if b < idx:
            prev_break = b
            continue
        if b > idx:
            next_break = b
            break

    left_span = _content_char_count(text[prev_break + 1 : idx + 1])
    right_span = _content_char_count(text[idx + 1 : next_break + 1])
    return left_span >= 8 and right_span >= 7


def _target_clause_commas(content_len: int) -> int:
    if content_len < 30:
        return 0
    if content_len < 48:
        return 1
    if content_len < 70:
        return 2
    return 3


def _is_content_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return bool(cat and cat[0] in {"L", "N", "M"})


def _is_punctuation(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return bool(cat and cat[0] == "P")
