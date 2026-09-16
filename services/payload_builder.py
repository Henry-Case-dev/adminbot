"""Epic 51 — payload-билдер (R51-2, Section 59.3, D211).

`build_messages(system, user_blocks)` гарантирует канон порядка payload:
System Prompt на индексе 0, user-блоки через "\n\n" в заданном порядке.
Применяется ТОЛЬКО к DirectChat (58.9) + guard-тест system@0 для остальных
сервисов (R51-4в: `messages[0]["role"] == "system"` — уже выполняется).
Существующие каноны/теги/тексты НЕ переписываются (вопрос 13).

Раунд 10.20 (БЛОК 5.1, О2 FINAL, ADR-1020-3): Time Injection. Параметр
`time_line` (строка `[Текущее время в чате: …]`) вставляется **первым
USER-блоком** — system-промпт остаётся статичным между запросами
(Prompt Caching не ломаем). Без `time_line` поведение байт-в-байт прежнее.
"""
from typing import Any


def build_messages(system: str, user_blocks: list[str], *,
                   time_line: str | None = None) -> list[dict[str, str]]:
    """Канон: [{"role": "system", "content": system},
    {"role": "user", "content": "\\n\\n".join(user_blocks)}].

    Статичное (system/алиасы/RAG) — вверх, динамика — вниз: порядок блоков
    задаёт вызывающий (58.9: [map, RAG_Memory, Target_User, Global_Context,
    Conversation_Thread]).

    `time_line` (10.20/О2): непустая строка времени → ПЕРВЫЙ user-блок;
    system не трогается (prompt-cache статичен байт-в-байт).
    """
    blocks: list[str] = list(user_blocks)
    if time_line:
        blocks = [time_line] + blocks
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]
