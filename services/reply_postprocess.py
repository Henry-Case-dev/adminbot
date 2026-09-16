"""Раунд 10.20 (БЛОК 7.2b, ADR-1020-7 §2, T-1921) — единая стадия
пост-обработки ответа перед отправкой в Telegram.

Reasoning-модели кладут черновик в текстовые теги-обёртки внутри `content`
(`<reasoning>…</reasoning>`, `<thinking>…</thinking>`, `<scratchpad>…</scratchpad>`,
`<analysis>…</analysis>`, `<thought>…</thought>`). Черновик НИКОГДА не должен
уходить пользователю.

`strip_reasoning_tags` — единственная точка среза:
* регистронезависимо, многострочно (DOTALL-семантика ручного скана);
* **без тегов — no-op** (байт-в-байт, нулевой регресс);
* незакрытый тег — defensive: срез до конца текста + WARNING (R17: только
  длины, без содержимого);
* «лишний» закрывающий тег без пары также вырезается (не утекает в ответ).

Применяется в 4 путях вывода: direct (`direct_chat_service` chokepoint),
финал tool-loop (`tool_loop`), factcheck/summary — через `cleanup_llm_text`
(`summary_cleanup.cleanup_llm_text` вызывает этот модуль).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Точный список тегов-черновиков (ADR-1020-7 §2). Порядок не важен.
REASONING_TAGS: tuple[str, ...] = (
    "reasoning", "thinking", "scratchpad", "analysis", "thought",
)

_TAG_ALT = "|".join(REASONING_TAGS)
_TOKEN_RE = re.compile(
    rf"<\s*(/?)\s*(?:{_TAG_ALT})\b[^>]*>",
    re.IGNORECASE,
)


def strip_reasoning_tags(text: str) -> str:
    """Вырезать reasoning-теги (парные и незакрытые). Никогда не бросает.

    Без тегов возвращается **исходная** строка (no-op, байт-в-байт).
    """
    source = str(text or "")
    if not source or "<" not in source:
        return source
    if not _TOKEN_RE.search(source):
        return source
    out: list[str] = []
    pos = 0
    depth = 0
    for match in _TOKEN_RE.finditer(source):
        closing = bool(match.group(1))
        if closing:
            if depth > 0:
                depth -= 1
                if depth == 0:
                    pos = match.end()
            else:
                # «лишний» закрывающий тег — вырезаем, содержимое не трогаем.
                out.append(source[pos:match.start()])
                pos = match.end()
        else:
            if depth == 0:
                out.append(source[pos:match.start()])
            depth += 1
    if depth > 0:
        # Незакрытый тег-черновик: всё после него отбрасывается (R15).
        logger.warning(
            "[postprocess] unclosed reasoning tag — truncated | chars=%d",
            len(source))
        return "".join(out)
    out.append(source[pos:])
    return "".join(out)
