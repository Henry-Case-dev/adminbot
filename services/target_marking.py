"""Раунд 10.23 (F1, ADR-1023-1) — маркировка целевого сообщения-команды.

Сообщение-триггер пользователя (команда / фактчек / прямой запрос) НЕ
вырезается из истории — это сломало бы таймлайн и причинно-следственные
связи. Вместо этого при рендере истории для LLM к нему дописывается
визуальный тег-указатель, а промпт Синтезатора жёстко запрещает
пересказывать помеченное сообщение как событие чата.

Оба независимых рендерера истории используют ОДИН токен:

* ``TARGET_MARKER``      — полный токен plain-рендера (сырой ``<<<``);
* ``TARGET_MARKER_CORE`` — escape-стабильное ядро (без ``<``) — якорь
  промпт-правила и паритет-теста: в XML маркер виден как
  ``&lt;&lt;&lt; [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]``, в plain — как ``<<< …``.

Сопоставление — строго по Telegram ``message_id``
(``smart_messages.tg_message_id``); ``None``/пусто/нет совпадения → маркер
не ставится (legacy-путь, рендер байт-в-байт прежний).
"""
from services.database import row_get

# Escape-стабильное ядро: не содержит ``<`` → идентично в XML и plain.
TARGET_MARKER_CORE = "[ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА]"

# Полный токен plain-рендера (точная форма ТЗ).
TARGET_MARKER = "<<< " + TARGET_MARKER_CORE

# Жёсткое правило для Stage-1 Синтезаторов (summary/direct/factcheck).
# Формулировка НЕ цитирует запретные клише дословно (grep-тест отсутствия
# тропов не должен ловить сам запрет).
TARGET_INSTRUCTION_BLOCK = (
    "ТЕКУЩАЯ КОМАНДА (СТРОГО):\n"
    "Если в истории чата есть сообщение с пометкой [ЭТО ТВОЯ ТЕКУЩАЯ КОМАНДА] "
    "(перед пометкой может стоять <<<), считай его инструкцией от "
    "пользователя. Это НЕ событие диалога: не пересказывай этот запрос как "
    "реплику чата, не упоминай его в выжимке и не разбирай как часть беседы. "
    "Просто выполни написанное."
)


def is_target_row(row, trigger_message_id) -> bool:
    """Строка окна — это сообщение-триггер? Сравнение по Telegram
    ``message_id`` (``tg_message_id``). ``None``/пусто/нет совпадения →
    ``False`` (маркер не ставится, никаких догадок)."""
    if trigger_message_id in (None, "", 0):
        return False
    tg_message_id = row_get(row, "tg_message_id")
    if tg_message_id in (None, "", 0):
        return False
    try:
        return int(tg_message_id) == int(trigger_message_id)
    except (TypeError, ValueError):
        return False


def append_marker(body: str) -> str:
    """Дописать маркер к телу сообщения: один пробел-разделитель, без дублей.
    Пустое тело → только маркер. Существующий маркер не дублируется."""
    text = "" if body is None else str(body)
    if TARGET_MARKER in text:
        return text
    if not text:
        return TARGET_MARKER
    if text.endswith((" ", "\n", "\t")):
        return text + TARGET_MARKER
    return text + " " + TARGET_MARKER
