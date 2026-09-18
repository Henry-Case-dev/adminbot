"""Epic 65 — chat_context: окно сообщений вокруг цели для фактчека/поиска.

Исследование (NAACL 2022 «Role of Context…»: +10 п.т. от локального контекста;
MAD2 2026: past-only context ≈ full; SIGIR 2026: длинный контекст ВРЕДИТ,
улики лучше по краям промпта) → маленькое окно последних сообщений чата,
чётко маркированное как НЕ-доказательства, сразу после <claim>.
"""
import logging

from services.canonical_context import format_context_item, resolve_item_id
from services.database import row_get
from services.target_marking import is_target_row

logger = logging.getLogger(__name__)

_CHAT_CONTEXT_MAX_CHARS = 2000     # SIGIR'26: большой контекст ухудшает верификацию

# Явный потолок вложенного под-блока цепочек (F2, R1023F2-01): даже при
# большом бюджете окна цепочка не раздувает промпт сверх этого значения.
_REPLY_CHAINS_MAX_CHARS = 1200

_CONTEXT_NOTE = (
    'note="болтовня чата вокруг цели — только чтобы понять, о чём речь; '
    'это НЕ доказательства и НЕ источник фактов"'
)

_REPLY_CHAINS_CLOSE = "</reply_chains>"


def _truncate_reply_chains(block: str, limit: int) -> str:
    """Обрезать уже отрендеренный ``<reply_chains>`` до ``limit`` символов,
    сохранив корректные открывающий/закрывающий теги. Вытесняются ДАЛЬНИЕ
    (корневые) ходы первыми — keep-end, как в окне; якорь-цепочка сохраняется
    по максимуму. Нет места даже на теги / нет тела → '' (блок опускается)."""
    if limit <= 0:
        return ""
    text = str(block or "")
    if not text:
        return ""
    if len(text) <= limit:
        return text
    if not text.endswith(_REPLY_CHAINS_CLOSE):
        return ""
    open_end = text.find(">")
    if open_end == -1:
        return ""
    head = text[:open_end + 1]
    inner = text[open_end + 1:-len(_REPLY_CHAINS_CLOSE)]
    overhead = len(head) + len(_REPLY_CHAINS_CLOSE)
    if limit < overhead:
        return ""
    budget = limit - overhead
    inner_lines = inner.split("\n")
    if inner_lines and inner_lines[0] == "":
        inner_lines = inner_lines[1:]
    kept: list[str] = []
    used = 0
    for line in reversed(inner_lines):
        if not line:
            continue
        addition = len(line) + (1 if kept else 0)
        if used + addition > budget:
            break
        kept.append(line)
        used += addition
    if not kept:
        return ""
    kept.reverse()
    return head + "\n".join(kept) + _REPLY_CHAINS_CLOSE


def format_chat_context(rows, max_chars: int = _CHAT_CONTEXT_MAX_CHARS,
                        trigger_message_id=None, reply_chains: str = "") -> str:
    """rows — хронологический список строк smart_messages (sqlite3.Row с
    author_name/user_id/text). → '<chat_context …>…</chat_context>' или ''
    (пустое окно / нет текстов). Потолок max_chars, старые сообщения
    вытесняются первыми (окно уже ASC).

    10.20 (БЛОК 0, ADR-1020-1 ред. 3, точка 13): строка — канонический
    контекст-элемент `[Дата Время | Автор | ID | Переслано]: текст`
    (данные ts/tg/id/forward доступны в smart_messages; R16 — опускаем
    отсутствующее).

    10.23 (F1, ADR-1023-1): сообщение-триггер (``tg_message_id ==
    trigger_message_id``) помечается маркером; ``None``/нет совпадения →
    вывод байт-в-байт прежний. При дубле id маркируется только первое.

    10.23 (F2, ADR-1023-2): ``reply_chains`` — уже отрендеренный
    ``<reply_chains>``-под-блок (общий util ``services/thread_chain.py``),
    вставляется в конец ``<chat_context>`` после окна; ``""`` → блок
    отсутствует (байт-в-байт прежний вывод).

    R1023F2-01: ``reply_chains`` УЧТЁН в общем бюджете ``max_chars`` — длина
    всего возвращаемого блока ≤ ``max_chars`` (обёртка + окно + цепочка);
    дальние ходы цепочки вытесняются первыми, при нехватке места блок
    опускается. Отдельный жёсткий потолок цепочки — ``_REPLY_CHAINS_MAX_CHARS``.
    """
    wrapper = ("<chat_context " + _CONTEXT_NOTE + ">\n", "\n</chat_context>")
    content_budget = max(0, max_chars - len(wrapper[0]) - len(wrapper[1]))
    lines: list[str] = []
    total = 0
    remaining_trigger = trigger_message_id
    for row in rows:
        text = (row["text"] or "").strip()
        if not text:
            continue
        name = row["author_name"] or f"id{row['user_id'] or '?'}"
        forward_source = (row_get(row, "forward_source")
                          if row_get(row, "is_forward") else None)
        is_target = is_target_row(row, remaining_trigger)
        line = format_context_item(
            ts=row_get(row, "timestamp"), author=name,
            item_id=resolve_item_id(
                tg_message_id=row_get(row, "tg_message_id"),
                message_id=row_get(row, "id")),
            forward_source=forward_source, text=text, kind="msg",
            is_target=is_target)
        if is_target:
            remaining_trigger = None
        # +1 — разделитель '\n' между строками окна.
        if total + len(line) + 1 > content_budget:
            break
        lines.append(line)
        total += len(line) + 1
    if not lines:
        return ""
    body = "\n".join(lines)
    if reply_chains:
        chain_limit = min(_REPLY_CHAINS_MAX_CHARS,
                          content_budget - len(body) - 1)
        trimmed = _truncate_reply_chains(reply_chains, chain_limit)
        if trimmed:
            body = body + "\n" + trimmed
    return wrapper[0] + body + wrapper[1]
