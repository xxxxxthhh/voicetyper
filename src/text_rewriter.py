"""Optional AI rewriting pass for punctuation and sentence segmentation."""
import re
import httpx

from src.config import (
    GROQ_API_KEY,
    AI_REWRITE_ENABLED,
    AI_REWRITE_MODELS,
    AI_REWRITE_TIMEOUT_SECS,
    AI_REWRITE_MAX_CHARS,
)
from src.text_formatter import STYLE_CODE

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_CONTENT_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


class TextRewriter:
    """Best-effort rewriting layer; never blocks core typing flow."""

    def __init__(self):
        self.enabled = bool(AI_REWRITE_ENABLED and GROQ_API_KEY)
        self._models = AI_REWRITE_MODELS
        self._max_chars = AI_REWRITE_MAX_CHARS
        self._client = (
            httpx.Client(timeout=AI_REWRITE_TIMEOUT_SECS) if self.enabled else None
        )

    def rewrite(self, text: str, style: str) -> str:
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

        prompt = _build_prompt(style)
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}

        for model in self._models:
            payload = {
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
            }
            try:
                resp = self._client.post(
                    _GROQ_CHAT_URL,
                    headers=headers,
                    json=payload,
                )
            except httpx.RequestError:
                continue

            if resp.status_code != 200:
                continue

            try:
                data = resp.json()
                out = data["choices"][0]["message"]["content"].strip()
            except Exception:
                continue

            out = _cleanup_output(out)
            if not out:
                continue
            if _looks_too_different(text, out):
                continue
            return out

        return text

    def close(self):
        if self._client:
            self._client.close()


def _build_prompt(style: str) -> str:
    return (
        "你是听写文本后处理器。"
        "任务: 只补充标点、断句、大小写和中英文空格。"
        "硬性约束: 不改写词语顺序，不做同义替换，不新增信息，不删除信息。"
        "保留原语言和专有名词(例如 API、Terminal、VPS、产品名)。"
        "若出现明显停顿语义，请拆成较短句，避免整段只有句末一个标点。"
        f"当前风格={style}。"
        "只输出最终文本，不要解释，不要加引号。"
    )


def _cleanup_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        lines = text.splitlines()
        if lines and lines[0].lower() in {"text", "markdown", "plain"}:
            lines = lines[1:]
        text = "\n".join(lines).strip()
    return text.strip().strip('"').strip()


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
