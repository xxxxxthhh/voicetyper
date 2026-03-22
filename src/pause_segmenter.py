"""Pause-aware punctuation insertion using Whisper segment timings."""
from __future__ import annotations

import re
import unicodedata

from src.config import (
    PAUSE_SEGMENT_ENABLED,
    PAUSE_BREAK_SECS,
    PAUSE_STRONG_BREAK_SECS,
    PAUSE_MIN_CHARS,
    PAUSE_PROMOTE_WEAK_PUNCT,
    PAUSE_SEGMENT_DEBUG,
)
from src.text_formatter import STYLE_CODE, STYLE_CHINESE, STYLE_ENGLISH

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def apply_pause_segmentation(text: str, segments: list[dict] | None, style: str) -> str:
    """Insert punctuation by pause duration while preserving lexical content."""
    if not PAUSE_SEGMENT_ENABLED:
        _debug("disabled")
        return text
    if style == STYLE_CODE:
        _debug("skip code style")
        return text
    if not text or len(text.strip()) < PAUSE_MIN_CHARS:
        _debug("text too short")
        return text
    if not segments:
        _debug("no segments")
        return text

    aligned = _align_segments_to_text(text, segments)
    _debug(f"segments={len(segments)} aligned={len(aligned)}")
    if len(aligned) < 2:
        _debug("not enough aligned boundaries")
        return text

    insert_after: dict[int, str] = {}
    replace_at: dict[int, str] = {}
    for cur, nxt in zip(aligned, aligned[1:]):
        gap = nxt["start"] - cur["end"]
        if gap < PAUSE_BREAK_SECS:
            continue

        right = nxt["start_idx"]
        left = max(cur["end_idx"], right - 1)
        if left >= right:
            continue

        strong = gap >= PAUSE_STRONG_BREAK_SECS
        punct = _select_punctuation(style, text, left, strong)
        if not punct:
            continue

        punct_positions = _punct_positions_between(text, left, right)
        if punct_positions:
            # Optional: promote weak punctuation when pause is very long.
            if strong and PAUSE_PROMOTE_WEAK_PUNCT:
                pos = _find_replaceable_weak_punct(text, punct_positions)
                if pos is not None:
                    prev = replace_at.get(pos)
                    if prev is None or _punct_priority(punct) > _punct_priority(prev):
                        replace_at[pos] = punct
            continue
        if not _can_insert_punctuation(text, left):
            continue

        prev = insert_after.get(left)
        if prev is None or _punct_priority(punct) > _punct_priority(prev):
            insert_after[left] = punct

    if not insert_after and not replace_at:
        _debug("no insertions/replacements")
        return text

    out: list[str] = []
    for idx, ch in enumerate(text):
        ch = replace_at.get(idx, ch)
        out.append(ch)
        punct = insert_after.get(idx)
        if not punct:
            continue
        if out and out[-1] == punct:
            continue
        out.append(punct)

    merged = "".join(out)
    # Collapse duplicated punctuation, e.g. ",,"
    merged = re.sub(r"([，。！？；：,.!?;:])\1{1,}", r"\1", merged)
    _debug(
        f"insertions={len(insert_after)} replacements={len(replace_at)} changed={merged != text}"
    )
    return merged


def _align_segments_to_text(text: str, segments: list[dict]) -> list[dict]:
    prepared = _prepare_segments(segments)
    if len(prepared) < 2:
        return []

    src_content = [(i, ch.casefold()) for i, ch in enumerate(text) if _is_content_char(ch)]
    if not src_content:
        return []
    src_tokens = [t for _, t in src_content]

    exact = _align_segments_exact(src_content, src_tokens, prepared)
    if len(exact) >= 2:
        return exact

    fallback = _align_segments_by_length(src_content, prepared)
    _debug(f"alignment fallback: exact={len(exact)} fallback={len(fallback)}")
    return fallback


def _prepare_segments(segments: list[dict]) -> list[dict]:
    prepared: list[dict] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        seg_text = str(seg.get("text", "")).strip()
        if not seg_text:
            continue
        seg_tokens = [ch.casefold() for ch in seg_text if _is_content_char(ch)]
        if len(seg_tokens) < 1:
            continue

        start_time = _to_float(seg.get("start"))
        end_time = _to_float(seg.get("end"))
        if start_time is None or end_time is None or end_time < start_time:
            continue
        prepared.append(
            {
                "tokens": seg_tokens,
                "start": start_time,
                "end": end_time,
            }
        )
    return prepared


def _align_segments_exact(
    src_content: list[tuple[int, str]],
    src_tokens: list[str],
    prepared: list[dict],
) -> list[dict]:
    cursor = 0
    aligned: list[dict] = []
    for seg in prepared:
        seg_tokens = seg["tokens"]
        pos = _find_subsequence(src_tokens, seg_tokens, cursor)
        if pos is None and cursor > 0:
            # Slight backtrack to tolerate small ASR chunk drift.
            pos = _find_subsequence(src_tokens, seg_tokens, max(0, cursor - 8))
        if pos is None:
            continue

        start_idx = src_content[pos][0]
        end_idx = src_content[pos + len(seg_tokens) - 1][0]
        aligned.append(
            {
                "start_idx": start_idx,
                "end_idx": end_idx,
                "start": seg["start"],
                "end": seg["end"],
            }
        )
        cursor = pos + len(seg_tokens)

    return aligned


def _align_segments_by_length(
    src_content: list[tuple[int, str]],
    prepared: list[dict],
) -> list[dict]:
    src_len = len(src_content)
    if src_len < 2:
        return []

    weights = [max(1, len(seg["tokens"])) for seg in prepared]
    total_weight = sum(weights)
    if total_weight <= 0:
        return []

    consumed = 0
    cursor = 0
    aligned: list[dict] = []
    for seg, weight in zip(prepared, weights):
        next_consumed = consumed + weight
        est_start = int(round((consumed / total_weight) * src_len))
        est_end_exclusive = int(round((next_consumed / total_weight) * src_len))
        est_end = max(est_start, est_end_exclusive - 1)

        start_pos = _snap_pos_to_token(
            src_content=src_content,
            token=seg["tokens"][0],
            center=max(cursor, min(est_start, src_len - 1)),
            min_pos=cursor,
            max_pos=src_len - 1,
        )
        if start_pos is None:
            start_pos = max(cursor, min(est_start, src_len - 1))
        if start_pos >= src_len:
            break

        end_pos = _snap_pos_to_token(
            src_content=src_content,
            token=seg["tokens"][-1],
            center=max(start_pos, min(est_end, src_len - 1)),
            min_pos=start_pos,
            max_pos=src_len - 1,
        )
        if end_pos is None:
            end_pos = max(start_pos, min(est_end, src_len - 1))

        aligned.append(
            {
                "start_idx": src_content[start_pos][0],
                "end_idx": src_content[end_pos][0],
                "start": seg["start"],
                "end": seg["end"],
            }
        )

        cursor = end_pos + 1
        consumed = next_consumed
        if cursor >= src_len:
            break
    return aligned


def _snap_pos_to_token(
    src_content: list[tuple[int, str]],
    token: str,
    center: int,
    min_pos: int,
    max_pos: int,
) -> int | None:
    if min_pos > max_pos:
        return None
    center = max(min_pos, min(center, max_pos))
    left = max(min_pos, center - 20)
    right = min(max_pos, center + 20)

    best_pos = None
    best_dist = None
    for pos in range(left, right + 1):
        if src_content[pos][1] != token:
            continue
        dist = abs(pos - center)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_pos = pos
    return best_pos


def _find_subsequence(haystack: list[str], needle: list[str], start: int) -> int | None:
    if not needle or start >= len(haystack):
        return None
    max_i = len(haystack) - len(needle)
    if max_i < start:
        return None
    first = needle[0]
    i = start
    while i <= max_i:
        if haystack[i] != first:
            i += 1
            continue
        if haystack[i : i + len(needle)] == needle:
            return i
        i += 1
    return None


def _is_content_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return bool(cat and cat[0] in {"L", "N", "M"})


def _is_punctuation_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return bool(cat and cat[0] == "P")


def _punct_positions_between(text: str, left_idx: int, right_idx: int) -> list[int]:
    if right_idx <= left_idx + 1:
        return []
    out: list[int] = []
    for i, ch in enumerate(text[left_idx + 1 : right_idx + 1], start=left_idx + 1):
        if _is_punctuation_char(ch):
            out.append(i)
    return out


def _find_replaceable_weak_punct(text: str, positions: list[int]) -> int | None:
    for idx in reversed(positions):
        ch = text[idx]
        if ch in {",", "，", ";", "；", ":", "："}:
            return idx
    return None


def _can_insert_punctuation(text: str, left_idx: int) -> bool:
    if left_idx < 0 or left_idx >= len(text):
        return False
    if _is_punctuation_char(text[left_idx]):
        return False
    if left_idx + 1 < len(text) and _is_punctuation_char(text[left_idx + 1]):
        return False
    return True


def _select_punctuation(style: str, text: str, boundary_idx: int, strong: bool) -> str:
    if style == STYLE_CHINESE:
        return "。" if strong else "，"
    if style == STYLE_ENGLISH:
        return "." if strong else ","

    # Mixed/normal mode: choose punctuation by local script context.
    left = max(0, boundary_idx - 10)
    right = min(len(text), boundary_idx + 11)
    local = text[left:right]
    has_cjk = bool(_CJK_RE.search(local))
    if has_cjk:
        return "。" if strong else "，"
    return "." if strong else ","


def _punct_priority(ch: str) -> int:
    if ch in {"。", "."}:
        return 2
    return 1


def _to_float(v) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def _debug(message: str):
    if PAUSE_SEGMENT_DEBUG:
        print(f"[PauseSeg] {message}")
