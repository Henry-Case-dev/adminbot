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

_CONTEXT_NOTE = (
    'note="болтовня чата вокруг цели — только чтобы понять, о чём речь; '
    'это НЕ доказательства и НЕ источник фактов"'
)


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
    отсутствует (байт-в-байт прежний вывод)."""
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
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    if not lines:
        return ""
    body = "\n".join(lines)
    if reply_chains:
        body = body + "\n" + reply_chains
    return ("<chat_context " + _CONTEXT_NOTE + ">\n"
            + body + "\n</chat_context>")
