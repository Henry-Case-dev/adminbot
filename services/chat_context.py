"""Epic 65 — chat_context: окно сообщений вокруг цели для фактчека/поиска.

Исследование (NAACL 2022 «Role of Context…»: +10 п.т. от локального контекста;
MAD2 2026: past-only context ≈ full; SIGIR 2026: длинный контекст ВРЕДИТ,
улики лучше по краям промпта) → маленькое окно последних сообщений чата,
чётко маркированное как НЕ-доказательства, сразу после <claim>.
"""
import logging

logger = logging.getLogger(__name__)

_CHAT_CONTEXT_MAX_CHARS = 2000     # SIGIR'26: большой контекст ухудшает верификацию

_CONTEXT_NOTE = (
    'note="болтовня чата вокруг цели — только чтобы понять, о чём речь; '
    'это НЕ доказательства и НЕ источник фактов"'
)


def format_chat_context(rows, max_chars: int = _CHAT_CONTEXT_MAX_CHARS) -> str:
    """rows — хронологический список строк smart_messages (sqlite3.Row с
    author_name/user_id/text). → '<chat_context …>[имя]: текст…</chat_context>'
    или '' (пустое окно / нет текстов). Потолок max_chars, старые сообщения
    вытесняются первыми (окно уже ASC)."""
    lines: list[str] = []
    total = 0
    for row in rows:
        text = (row["text"] or "").strip()
        if not text:
            continue
        name = row["author_name"] or f"id{row['user_id'] or '?'}"
        line = f"[{name}]: {text}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    if not lines:
        return ""
    return ("<chat_context " + _CONTEXT_NOTE + ">\n"
            + "\n".join(lines) + "\n</chat_context>")
