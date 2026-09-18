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


def normalize_trigger_id(value):
    """Telegram-id триггера → ``int`` или ``None`` (пусто/битое/``0``).
    Единая нормализация для всех рендереров (паритет XML/plain/цепочки)."""
    if value in (None, "", 0):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_target_row(row, trigger_message_id) -> bool:
    """Строка окна — это сообщение-триггер? Сравнение по Telegram
    ``message_id`` (``tg_message_id``). ``None``/пусто/нет совпадения →
    ``False`` (маркер не ставится, никаких догадок)."""
    trigger = normalize_trigger_id(trigger_message_id)
    if trigger is None:
        return False
    try:
        return int(row_get(row, "tg_message_id")) == trigger
    except (TypeError, ValueError):
        return False


def is_target_item_id(item_id, trigger_message_id) -> bool:
    """Ход reply-цепочки — это триггер? Единый матчер для ``_chain_line``
    (item_id вида ``tg:<id>``) — тот же guard/нормализация, что у
    :func:`is_target_row` (R1023F1-06)."""
    trigger = normalize_trigger_id(trigger_message_id)
    if trigger is None:
        return False
    text = str(item_id or "")
    if not text.startswith("tg:"):
        return False
    try:
        return int(text[3:]) == trigger
    except (TypeError, ValueError):
        return False


def append_marker(body: str) -> str:
    """Дописать маркер к телу сообщения: один пробел-разделитель, без дублей.
    Пустое/пробельное тело → только маркер. Дедуп — по escape-стабильному ядру
    ``TARGET_MARKER_CORE`` (тело с ядром, но без ``<<<``, не дублируется)."""
    text = "" if body is None else str(body)
    if TARGET_MARKER_CORE in text:
        return text
    if not text.strip():
        return TARGET_MARKER
    if text.endswith((" ", "\n", "\t")):
        return text + TARGET_MARKER
    return text + " " + TARGET_MARKER
