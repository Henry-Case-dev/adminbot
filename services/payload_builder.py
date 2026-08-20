"""Epic 51 — payload-билдер (R51-2, Section 59.3, D211).

`build_messages(system, user_blocks)` гарантирует канон порядка payload:
System Prompt на индексе 0, user-блоки через "\n\n" в заданном порядке.
Применяется ТОЛЬКО к DirectChat (58.9) + guard-тест system@0 для остальных
сервисов (R51-4в: `messages[0]["role"] == "system"` — уже выполняется).
Существующие каноны/теги/тексты НЕ переписываются (вопрос 13).
"""
from typing import Any


def build_messages(system: str, user_blocks: list[str]) -> list[dict[str, str]]:
    """Канон: [{"role": "system", "content": system},
    {"role": "user", "content": "\\n\\n".join(user_blocks)}].

    Статичное (system/алиасы/RAG) — вверх, динамика — вниз: порядок блоков
    задаёт вызывающий (58.9: [map, RAG_Memory, Target_User, Global_Context,
    Conversation_Thread]).
    """
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_blocks)},
    ]
