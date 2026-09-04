"""Фаза 2 (T-762, F2 — часть B) — канон HISTORY_EXTRACT_PROMPT + JSON Schema.

Graph-этап истории: локальная Ollama (qwen3.5:9b) пачками по 25 сообщений
с датами/авторами извлекает ЗНАЧИМЫЕ долгоживущие факты чата. Отдельный
канон от R46-2 FACT_EXTRACT_PROMPT (summary_memory.py:79-86, байт-в-байт —
НЕ трогаем): у истории другой вход (пачка диалога, а не единый текст),
другие правила (архивариус чата, сленг/мат как есть, даты НЕ выдумывать —
message_timestamp проставит воркер от MAX(timestamp) пачки, spec Q10).

Формат выхода — JSON-массив триплетов [{subject, predicate, object,
context?}], в духе R46-2 (но без subject_type/object_type — история не
строит nodes/edges, spec 3.5: «nodes/edges НЕ создаём»). fact-строка в
graph_facts собирается воркером как в live-пути («subject predicate object»,
summary_memory.py:1325).

Стиль факт-строк — как в live graph_facts («subject predicate object»,
summary_memory.py:1325). Примеры (стилистика по канону R46-2 и данным аудита
Step 0; локальной прод-БД с graph_facts на машине части B нет — выборка 20
реальных строк из local_database.db недоступна, примеры не претендуют на
цитирование прод-фактов):
  «вася купил новые дроны в марте 2025»      — chat_history
  «славик переехал в другой город»           — chat_history
  «ozon доставляет быстрее чем wildberries»  — search_fact
  «у rtx 5090 энергопотребление 575 вт»      — web_content
  «петя — заядлый рыбак, любит зимнюю рыбалку» — user_memory
(короткие утвердительные предложения: кто/что + действие/связь + что/где/
когда; без оценок и эмоций; сленг как есть).
"""

# Максимум фактов на одну пачку (регулятор объёма промпта; жёсткий кап
# применяется и в воркере — max(1, round(batch_size × fact_density))).
HISTORY_MAX_FACTS_PER_BATCH = 8

# Максимум символов в context-поле факта (spec части B).
HISTORY_MAX_CONTEXT_CHARS = 200

# Капсы полей триплета — как в live-пути (summary_memory.py:94-96;
# _FACT_MAX_NAME_CHARS=100, _FACT_MAX_PREDICATE_CHARS=200).
HISTORY_MAX_NAME_CHARS = 100
HISTORY_MAX_PREDICATE_CHARS = 200

# ── Канон-промпт архивариуса истории (константа, версия под вход «пачка»).
# Стиль/структура — R46-2 (FACT_EXTRACT_PROMPT): сухие проверяемые факты,
# строгий JSON. Отличия истории: (1) вход — хронологическая пачка диалога
# [дата UTC] автор: текст; (2) сленг/мат/прозвища чата сохраняются как есть;
# (3) даты НЕ выдумываются и НЕ возвращаются — события формулируются как в
# исходных сообщениях, message_timestamp проставляет воркер.
HISTORY_EXTRACT_PROMPT = """СИСТЕМНАЯ РОЛЬ:
Ты — безэмоциональный архивариус истории чата (ETL-процессор). Тебе дают пачку сообщений чата (до 25, хронологически подряд, каждая строка: [дата UTC] автор: текст). Из пачки извлеки ЗНАЧИМЫЕ долгоживущие факты о людях, событиях, отношениях, договорённостях и лоре чата и верни их строго JSON-массивом триплетов.

ЧТО ИЗВЛЕКАТЬ:
- события и их результат («в марте 2025 вася купил дрон», «петя переехал в другой город»);
- лор и традиции сообщества, устойчивые прозвища, мемы-традиции, договорённости;
- отношения между людьми (дружба/конфликт/общие проекты) — только если прямо следуют из сообщений;
- сленг и мат сохраняй КАК ЕСТЬ (не цензурируй и не перефразируй в литературный стиль).

ЧТО НЕ ИЗВЛЕКАТЬ:
- сиюминутный трёп, приветствия, реакции, поздравления «с днём рождения», эмоции, оценки, оскорбления;
- информацию, которую НЕЛЬЗЯ проверить по этой пачке (догадки, общие рассуждения);
- шутки и мемы, не имеющие долгоживущей ценности.

ПРАВИЛА ФОРМУЛИРОВКИ:
- subject/object — люди, места или концепции ИМЕНАМИ из сообщений (как их называют в чате); subject и object не могут совпадать.
- predicate — краткий предикат-связь/действие в настоящем или прошедшем времени.
- context — опционально, уточнение/обстоятельства (≤200 символов); не дублируй subject/predicate/object.
- ДАТЫ НЕ ВЫДУМЫВАЙ И НЕ ВОЗВРАЩАЙ: если событие в сообщении привязано к дате — сформулируй его как в исходном сообщении («в марте 2025 …»), но НЕ добавляй даты, которых нет в пачке. Колонку-дату проставит воркер от сообщений пачки.
- Извлеки не более {max_facts} фактов на пачку (лучше меньше, но проверяемых).
- Текст факта должен быть проверяем по строкам пачки.

ВЫВОД:
Верни СТРОГО валидный JSON, ничего кроме JSON (без markdown-обёртки, без комментариев), в формате:
{{"facts": [{{"subject": "кто/что", "predicate": "что сделал/связь", "object": "с кем/чем", "context": "уточнение (необязательно)"}}]}}
Пустая пачка без значимых фактов → {{"facts": []}}."""

# JSON Schema ответа (для нативного /api/chat Ollama: format=schema;
# OpenAI-совместимый /v1/chat/completions использует response_format
# json_object + описание схемы в промпте).
HISTORY_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "minLength": 1},
                    "predicate": {"type": "string", "minLength": 1},
                    "object": {"type": "string", "minLength": 1},
                    "context": {"type": "string"},
                },
                "required": ["subject", "predicate", "object"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}

# Число символов в максимуме, отображаемых в dry-run/логах для строки пачки.
HISTORY_BATCH_LINE_MAX_CHARS = 500


def build_history_user_prompt(messages: list) -> str:
    """User-контент пачки: строки `[%Y-%m-%d %H:%M] Имя: текст` (формат как
    L1-рендер; даты UTC из unix-таймстампов сообщений). messages — список
    dict/Row с ключами timestamp/author_name/text. Пустые тексты пропускаются
    (их и так отсеивает выборка воркера — length(text) >= min_fact_chars)."""
    lines = []
    for msg in messages:
        author = (msg.get("author_name") if hasattr(msg, "get")
                  else msg["author_name"]) or ""
        text = (msg.get("text") if hasattr(msg, "get")
                else msg["text"]) or ""
        ts = msg["timestamp"] if not hasattr(msg, "get") else msg["timestamp"]
        stamp = _format_utc(ts)
        line = f"[{stamp}] {author}: {text}"
        if len(line) > HISTORY_BATCH_LINE_MAX_CHARS:
            line = line[:HISTORY_BATCH_LINE_MAX_CHARS] + "…"
        lines.append(line)
    return "\n".join(lines)


def _format_utc(ts: int) -> str:
    """%Y-%m-%d %H:%M в UTC (сообщения истории — unix UTC; экспортные даты
    уже нормализованы в unix-таймстампы без tz-смещений)."""
    import datetime
    return datetime.datetime.fromtimestamp(
        int(ts), tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
