"""Раунд 10.20 (БЛОК 7.3, spec §18.3, ADR-1020-1 п.8 / ADR-1020-7 §3, T-1923) —
тонкий Context Middleware поверх канонического `canonical_context`.

Это ОБЁРТКА, а не переписывание сборки контекста: `_build_user_content`,
порядок блоков, дедуп/реранк/MMR НЕ меняются. Middleware даёт один инвариант —
**приоритет метаданных над бюджет-капом**: ведущий `[Дата Время | Автор | ID |
Переслано: …]:`-заголовок строки неприкосновенен, режется только body.

* ``context_item(...)`` — тонкий алиас `format_context_item` (§2.2);
* ``metadata_header(text) -> (header, body)`` — разделение строки на заголовок
  и тело (реюз `canonical_context.split_context_header`);
* ``truncate_keep_header(block, limit_tokens, kind)`` — header-safe усечение,
  встроенное в `_truncate_block`/`_apply_context_budget`.

`strip_context_header` НЕ дублируется — живёт в `canonical_context` (Р5).
"""
from __future__ import annotations

from services.canonical_context import (
    format_context_item,
    split_context_header,
    strip_context_header,
)
from services.token_counter import (
    count_tokens,
    truncate_to_tokens,
    truncate_to_tokens_keep_head,
)

__all__ = [
    "context_item",
    "metadata_header",
    "truncate_keep_header",
    "split_context_header",
    "strip_context_header",
    "format_context_item",
]


def context_item(*, ts=None, author=None, item_id=None, forward_source=None,
                 text="", kind="msg", stale=False) -> str:
    """Каноническая строка контекста (алиас `format_context_item`)."""
    return format_context_item(
        ts=ts, author=author, item_id=item_id, forward_source=forward_source,
        text=text, kind=kind, stale=stale)


def metadata_header(text) -> tuple[str, str]:
    """``[header]: body`` → ``(header, body)``; нет заголовка → ``("", text)``."""
    return split_context_header(text)


def truncate_keep_header(block, limit_tokens, kind: str = "") -> str:
    """Усечь блок до ``limit_tokens``, НИКОГДА не режа ведущий `[…]`-заголовок.

    * заголовок неприкосновенен; при исчерпании body бюджет уходит в заголовок
      (блок не «исчезает из-за заголовка»);
    * тело: ``kind="global"`` — keep-head (конспект-голова держится), иначе
      keep-end (свежие строки важнее, прецедент 64.7);
    * без канонического заголовка — прежнее поведение (регресс-безопасно для
      XML-обёрнутых блоков `<Global_Context>`/`<RAG_Memory>` и прочих).
    """
    text = str(block or "")
    if limit_tokens is None:
        return text
    try:
        limit = int(limit_tokens)
    except (TypeError, ValueError):
        return text
    if limit <= 0:
        # body-бюджета нет — сохраняем хотя бы заголовок (метаданные важнее).
        header, _ = split_context_header(text)
        return header.rstrip() if header else ""
    if count_tokens(text) <= limit:
        return text
    header, body = split_context_header(text)
    if not header:
        if kind == "global":
            return truncate_to_tokens_keep_head(text, limit)
        return truncate_to_tokens(text, limit)
    header_tokens = count_tokens(header)
    if header_tokens >= limit:
        return header.rstrip()
    body_budget = limit - header_tokens
    if kind == "global":
        body_out = truncate_to_tokens_keep_head(body, body_budget)
    else:
        body_out = truncate_to_tokens(body, body_budget)
    return header + body_out
