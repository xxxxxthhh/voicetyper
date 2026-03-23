"""Optional AI rewriting pass for punctuation and sentence segmentation."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from bisect import bisect_right
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from src.config import (
    GROQ_API_KEY,
    AI_REWRITE_ENABLED,
    AI_REWRITE_MODELS,
    AI_REWRITE_TIMEOUT_SECS,
    AI_REWRITE_MAX_CHARS,
    DATA_DIR,
)

_REWRITER_DEBUG = os.environ.get("VOICETYPER_REWRITER_DEBUG", "0") == "1"
from src.text_formatter import (
    STYLE_CODE,
    STYLE_NORMAL,
    STYLE_CHINESE,
    STYLE_ENGLISH,
)

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_CONTENT_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_TERMS_PATH = DATA_DIR / "terms.json"
_SENTENCE_PUNCT = set("，。！？；：,.!?;:")
_LEADING_PREFIX_PATTERNS = [
    re.compile(r"^(?:我(?:已经|刚刚)?(?:修复|修正|润色|优化)了?(?:这段)?文本[:：]\s*)"),
    re.compile(r"^(?:修复后(?:文本)?|修正后(?:文本)?|润色后(?:文本)?|优化后(?:文本)?|处理后(?:文本)?|最终文本|结果)[:：]\s*"),
    re.compile(r"^(?:以下是(?:修复后)?文本[:：]\s*)"),
    re.compile(r"^(?:fixed text|corrected text|rewritten text)[:：]\s*", re.IGNORECASE),
]


class TextRewriter:
    """Best-effort rewriting layer; never blocks core typing flow."""

    def __init__(self):
        self.enabled = bool(AI_REWRITE_ENABLED and GROQ_API_KEY)
        self._models = AI_REWRITE_MODELS
        self._max_chars = AI_REWRITE_MAX_CHARS
        self._terms = _load_terms_map(_TERMS_PATH)
        self._client = (
            httpx.Client(timeout=AI_REWRITE_TIMEOUT_SECS) if self.enabled else None
        )

    def rewrite(self, text: str, style: str, pause_hints: str | None = None) -> str:
        text = _apply_term_replacements(text, self._terms)
        if not self.enabled:
            return text
        if not text or text.startswith("["):
            return text
        if style == STYLE_CODE:
            return text
        if len(text) > self._max_chars:
            return text
        if not self._client:
            return text

        need_punct_boost = _needs_punctuation_boost(text, style)
        prompt = _build_prompt(style, has_pause_hints=bool(pause_hints))
        user_content = _build_user_content(text, pause_hints)
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}

        for model in self._models:
            payload = {
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
            }
            try:
                resp = self._client.post(
                    _GROQ_CHAT_URL,
                    headers=headers,
                    json=payload,
                )
            except httpx.RequestError as exc:
                _rdebug(f"model={model} request error: {exc}")
                continue

            if resp.status_code != 200:
                _rdebug(f"model={model} HTTP {resp.status_code}")
                continue

            try:
                data = resp.json()
                out = data["choices"][0]["message"]["content"].strip()
            except Exception as exc:
                _rdebug(f"model={model} parse error: {exc}")
                continue

            _rdebug(f"model={model} raw_out={out!r}")
            out = _cleanup_output(out)
            if not out:
                _rdebug(f"model={model} empty after cleanup")
                continue
            out = _apply_term_replacements(out, self._terms)
            # Early exit: if cleanup reduced output to identical input, this model
            # added nothing useful (e.g. only wrapped text in quotes).
            if out == text:
                _rdebug(f"model={model} output identical to input after cleanup, skipping")
                continue
            if not _is_safe_micro_edit(text, out):
                _rdebug(
                    f"model={model} safe_micro_edit FAILED "
                    f"src_norm={_normalized_content(text)!r} "
                    f"out_norm={_normalized_content(out)!r}"
                )
                # Re-clean: strip residual trailing quotes the model may have added
                out2 = _strip_residual_quotes(out)
                if out2 != out and _is_safe_micro_edit(text, out2):
                    _rdebug(f"model={model} recovered after residual quote strip")
                    out = out2
                else:
                    projected = _project_punctuation_from_rewrite(text, out)
                    if projected and projected != text:
                        # projection guarantees content unchanged; accept directly
                        _rdebug(f"model={model} using punctuation projection")
                        out = projected
                    else:
                        _rdebug(f"model={model} projection failed or no-op, skipping")
                        continue
            if _looks_too_different(text, out):
                _rdebug(f"model={model} looks_too_different, skipping")
                continue
            if need_punct_boost and _punctuation_gain(text, out) <= 0:
                _rdebug(f"model={model} need_punct_boost but no gain, skipping")
                continue
            _rdebug(f"model={model} ACCEPTED out={out!r}")
            return out

        # AI-first punctuation boost pass:
        # if the first pass keeps long run-on text unchanged,
        # do one extra AI-only pass focused on comma segmentation.
        if need_punct_boost:
            _rdebug("entering punct_boost pass")
            boost_prompt = _build_punct_boost_prompt(style, has_pause_hints=bool(pause_hints))
            for model in self._models:
                payload = {
                    "model": model,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": boost_prompt},
                        {"role": "user", "content": user_content},
                    ],
                }
                try:
                    resp = self._client.post(
                        _GROQ_CHAT_URL,
                        headers=headers,
                        json=payload,
                    )
                except httpx.RequestError as exc:
                    _rdebug(f"boost model={model} request error: {exc}")
                    continue

                if resp.status_code != 200:
                    _rdebug(f"boost model={model} HTTP {resp.status_code}")
                    continue

                try:
                    data = resp.json()
                    out = data["choices"][0]["message"]["content"].strip()
                except Exception as exc:
                    _rdebug(f"boost model={model} parse error: {exc}")
                    continue

                _rdebug(f"boost model={model} raw_out={out!r}")
                out = _cleanup_output(out)
                if not out:
                    _rdebug(f"boost model={model} empty after cleanup")
                    continue
                out = _apply_term_replacements(out, self._terms)
                if out == text:
                    _rdebug(f"boost model={model} output identical to input after cleanup, skipping")
                    continue
                if not _is_safe_micro_edit(text, out):
                    out2 = _strip_residual_quotes(out)
                    if out2 != out and _is_safe_micro_edit(text, out2):
                        out = out2
                    else:
                        projected = _project_punctuation_from_rewrite(text, out)
                        if projected and projected != text:
                            out = projected
                        else:
                            _rdebug(f"boost model={model} safe_micro_edit failed, skipping")
                            continue
                if _looks_too_different(text, out):
                    _rdebug(f"boost model={model} looks_too_different, skipping")
                    continue
                if _punctuation_gain(text, out) <= 0:
                    _rdebug(f"boost model={model} no punct gain, skipping")
                    continue
                _rdebug(f"boost model={model} ACCEPTED")
                return out

        _rdebug("all models exhausted, returning original text")
        return text

    def close(self):
        if self._client:
            self._client.close()


def _build_prompt(style: str, has_pause_hints: bool) -> str:
    style_rule = _style_rule(style)
    pause_rule = (
        "会提供停顿提示（Pause hints）时：仅作为参考，不要机械地在每个停顿处都用句号。"
        if has_pause_hints
        else ""
    )
    return (
        "你是实时听写文本修复器，只做微编辑。"
        "允许操作: 断句、标点修正、大小写修正、中英文空格修正。"
        "禁止操作: 改写词序、同义替换、增删事实、总结解释扩写。"
        "必须保留: 专有名词、产品名、命令、路径、URL、邮箱、数字、单位、英文缩写(如 API/VPS/Terminal)。"
        "必须逐字保留原文所有非标点字符（内容与顺序都一致），只允许插入或调整标点和空格。"
        "断句要求: 优先自然语义断句，短停顿优先用逗号，明确语义结束才用句号。"
        "不要把一句话机械拆成很多短句，也不要把每个停顿都变成句号。"
        "重要: 如果输入的长中文文本内部几乎没有逗号，你必须在合适的语义边界插入逗号来断句——"
        "结尾有问号或句号不代表内部已有足够的标点，绝对不要对缺少内部逗号的长文本原样返回。"
        "中文优先自然短句（建议子句约 10-28 字）；英文可修复 run-on sentence，但不改词。"
        f"{pause_rule}"
        f"风格要求: {style_rule}"
        "输出要求: 只输出最终文本，不要加引号包裹，不要解释，不要 Markdown，不要代码块。"
        "仅在内容（非标点）真的无法判断时才保持原文；有把握的标点/断句修改应当执行。"
    )


def _build_user_content(text: str, pause_hints: str | None) -> str:
    if not pause_hints:
        return text
    return (
        "[RAW_TRANSCRIPT]\n"
        f"{text}\n"
        "[/RAW_TRANSCRIPT]\n"
        "[PAUSE_HINTS]\n"
        f"{pause_hints}\n"
        "[/PAUSE_HINTS]\n"
        "请只输出修复后的文本。"
    )


def _build_punct_boost_prompt(style: str, has_pause_hints: bool) -> str:
    style_rule = _style_rule(style)
    pause_rule = (
        "若提供 Pause hints，请优先在 weak pause 处考虑逗号，在 strong pause 处考虑句号。"
        if has_pause_hints
        else ""
    )
    return (
        "你是实时听写标点修复器。只允许插入或调整标点和空格，严禁修改任何非标点字符。"
        "任务：在输入文本的语义边界处插入逗号，使长句可读。"
        "强制规则：输入文本若超过20字且内部逗号少于2个，你【必须】在至少1处语义边界插入逗号。"
        "结尾的句号/问号不算内部标点，不能作为已断句的理由。"
        "原样返回输入是错误行为——请务必做出至少一处标点改动。"
        "逗号优先；非完整独立句不用句号。"
        f"{pause_rule}"
        f"风格要求: {style_rule}"
        "输出要求: 只输出最终文本，不加任何解释。"
    )


def _style_rule(style: str) -> str:
    if style == STYLE_CHINESE:
        return "优先中文全角标点（，。！？；：）。"
    if style == STYLE_ENGLISH:
        return "优先英文半角标点，并保持英文句首大写。"
    if style == STYLE_NORMAL:
        return "按输入语言自动选择中英文标点。"
    return "按输入语言自然修复，不做风格化改写。"


def _cleanup_output(text: str) -> str:
    text = text.strip()
    # Strip <think>...</think> blocks produced by qwen3 thinking mode.
    # The actual answer follows the closing tag.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        lines = text.splitlines()
        if lines and lines[0].lower() in {"text", "markdown", "plain"}:
            lines = lines[1:]
        text = "\n".join(lines).strip()

    # Strip model-added wrappers like "我修复了文本：..."
    for _ in range(3):
        before = text
        text = text.strip().strip('"').strip("“”").strip()
        for pattern in _LEADING_PREFIX_PATTERNS:
            text = pattern.sub("", text).strip()
        if text == before:
            break

    text = text.strip().strip('"').strip('""').strip()
    text = _strip_residual_quotes(text)
    return text


def _strip_residual_quotes(text: str) -> str:
    """Remove unmatched trailing/leading Chinese quotes the model may add."""
    if not text:
        return text
    # Trailing unmatched right quotes
    while text and text[-1] in '"\u201d\u2019':
        ch = text[-1]
        if ch == '\u201d':
            if text.count('\u201c') < text.count('\u201d'):
                text = text[:-1].rstrip()
            else:
                break
        elif ch == '\u2019':
            if text.count('\u2018') < text.count('\u2019'):
                text = text[:-1].rstrip()
            else:
                break
        elif ch == '"':
            if text.count('"') % 2 == 1:
                text = text[:-1].rstrip()
            else:
                break
        else:
            break
    # Leading unmatched left quotes
    while text and text[0] in '"\u201c\u2018':
        ch = text[0]
        if ch == '\u201c':
            if text.count('\u201d') < text.count('\u201c'):
                text = text[1:].lstrip()
            else:
                break
        elif ch == '\u2018':
            if text.count('\u2019') < text.count('\u2018'):
                text = text[1:].lstrip()
            else:
                break
        elif ch == '"':
            if text.count('"') % 2 == 1:
                text = text[1:].lstrip()
            else:
                break
        else:
            break
    return text


def _is_safe_micro_edit(source: str, rewritten: str) -> bool:
    """Allow only punctuation/spacing/case edits."""
    return _normalized_content(source) == _normalized_content(rewritten)


def _normalized_content(text: str) -> str:
    """
    Keep only lexical content for strict equality checks.
    This removes punctuation/separators and ignores case.
    """
    chars: list[str] = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat and cat[0] in {"L", "N", "M"}:
            chars.append(ch.casefold())
    return "".join(chars)


def _is_content_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return bool(cat and cat[0] in {"L", "N", "M"})


def _is_transfer_punctuation(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return bool(cat and cat[0] == "P")


def _project_punctuation_from_rewrite(source: str, rewritten: str) -> str:
    """
    Transfer punctuation from model output back onto original source text.
    This keeps lexical content unchanged while preserving improved punctuation.
    """
    src_content = [(i, ch.casefold()) for i, ch in enumerate(source) if _is_content_char(ch)]
    dst_content = [(i, ch.casefold()) for i, ch in enumerate(rewritten) if _is_content_char(ch)]
    if len(src_content) < 2 or len(dst_content) < 2:
        return source

    matcher = SequenceMatcher(
        a=[c for _, c in src_content],
        b=[c for _, c in dst_content],
        autojunk=False,
    )
    mapped_dst_to_src_raw: dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        if block.size <= 0:
            continue
        for k in range(block.size):
            src_raw = src_content[block.a + k][0]
            dst_raw = dst_content[block.b + k][0]
            mapped_dst_to_src_raw[dst_raw] = src_raw

    if len(mapped_dst_to_src_raw) < 2:
        return source

    dst_mapped_positions = sorted(mapped_dst_to_src_raw.keys())
    insert_after: dict[int, list[str]] = {}

    for j, ch in enumerate(rewritten):
        if not _is_transfer_punctuation(ch):
            continue

        # Locate nearest aligned lexical chars around this punctuation.
        k = bisect_right(dst_mapped_positions, j)
        left_dst = dst_mapped_positions[k - 1] if k > 0 else None
        right_dst = dst_mapped_positions[k] if k < len(dst_mapped_positions) else None

        target_after_src: int | None = None
        if left_dst is not None and right_dst is not None:
            left_src = mapped_dst_to_src_raw[left_dst]
            right_src = mapped_dst_to_src_raw[right_dst]
            if left_src < right_src:
                target_after_src = left_src
        elif left_dst is not None:
            target_after_src = mapped_dst_to_src_raw[left_dst]
        else:
            # Ignore prefix punctuation before the first aligned lexical char.
            continue

        if target_after_src is not None:
            insert_after.setdefault(target_after_src, []).append(ch)

    if not insert_after:
        return source

    out: list[str] = []
    for i, ch in enumerate(source):
        out.append(ch)
        puncts = insert_after.get(i)
        if not puncts:
            continue
        for p in puncts:
            if not _should_append_punctuation(out, source, i, p):
                continue
            out.append(p)

    projected = "".join(out)
    projected = re.sub(r"([，。！？；：,.!?;:])\1{1,}", r"\1", projected)
    return projected


def _should_append_punctuation(current_output: list[str], source: str, src_idx: int, punct: str) -> bool:
    if not current_output:
        return True
    prev = current_output[-1]
    if _is_transfer_punctuation(prev):
        return False
    if src_idx + 1 < len(source):
        nxt = source[src_idx + 1]
        if _is_transfer_punctuation(nxt):
            return False
    return True


def _looks_too_different(source: str, rewritten: str) -> bool:
    src_tokens = _content_tokens(source)
    dst_tokens = _content_tokens(rewritten)
    if not src_tokens or not dst_tokens:
        return True

    ratio = len(dst_tokens) / max(len(src_tokens), 1)
    if ratio < 0.45 or ratio > 2.2:
        return True

    overlap = len(src_tokens & dst_tokens) / max(len(src_tokens), 1)
    return overlap < 0.5


def _content_tokens(text: str) -> set[str]:
    return {ch for ch in text if _CONTENT_RE.match(ch)}


def _needs_punctuation_boost(text: str, style: str) -> bool:
    if style in {STYLE_CODE, STYLE_ENGLISH}:
        return False
    content_len = len(_normalized_content(text))
    if content_len < 24:
        return False
    punct_count = sum(1 for ch in text if ch in _SENTENCE_PUNCT)
    return punct_count == 0 or (content_len >= 42 and punct_count < 2)


def _punctuation_gain(source: str, rewritten: str) -> int:
    src_count = sum(1 for ch in source if ch in _SENTENCE_PUNCT)
    dst_count = sum(1 for ch in rewritten if ch in _SENTENCE_PUNCT)
    return dst_count - src_count


def _rdebug(message: str) -> None:
    """Print debug messages when VOICETYPER_REWRITER_DEBUG=1."""
    if _REWRITER_DEBUG:
        print(f"[Rewriter] {message}")


def _load_terms_map(path: Path) -> dict[str, str]:
    """
    Load local term corrections from JSON:
    {"错词":"正词","飞梳":"飞书"}
    """
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        cleaned: dict[str, str] = {}
        for k, v in data.items():
            src = str(k).strip()
            dst = str(v).strip()
            if src and dst and src != dst:
                cleaned[src] = dst
        return cleaned
    except Exception:
        return {}


def _apply_term_replacements(text: str, terms: dict[str, str]) -> str:
    if not text or not terms:
        return text
    out = text
    # Replace longer keys first to avoid partial overlap issues.
    for src in sorted(terms.keys(), key=len, reverse=True):
        out = out.replace(src, terms[src])
    return out
