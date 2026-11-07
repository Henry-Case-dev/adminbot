"""MEMORY-02B: общий сценарий паритета OFF-ветки (§1.4.1/§5.1).

Модуль импортирует ТОЛЬКО существующие до слайса сервисы, поэтому одинаково
исполняется и на базовой линии (`828d1dd1`), и на текущем кандидате. Это
позволяет снять фикстуру «как было» на реальной (файловой) БД и в тесте
сравнить с ней «как стало»: OFF-гейт обязан быть байт-в-байт прежним —
те же id узлов, те же рёбра/факты.

Сценарий намеренно включает ОБЕ ветки конфликта типа (§1.2.3), чтобы
паритет проверялся не на «удобных» данных:

* узел `Озон` уже существует с `entity_type='fact'`, а триплет W2 приходит с
  `subject_type='user'` — легаси-путь молча пишет ребро в существующий узел;
* узел `Папаха` существует как `user`, а факт W1 обращается к нему как к
  `fact` — то же самое.
"""
from __future__ import annotations

import json

CHAT = -1001777000123
OTHER_CHAT = -1001777000456
UID_A = 428494
UID_B = 777

#: W2 (`_write_graph_triplets`): чистый триплет + коллизия слота имени.
TRIPLETS = (
    {"subject": "аня", "subject_type": "user",
     "predicate": "любит", "object": "ира", "object_type": "user"},
    {"subject": "озон", "subject_type": "user",
     "predicate": "упомянут", "object": "доставка", "object_type": "topic"},
)

#: W1 (`memorize_facts`): чистый durable-факт + факт в занятый слот имени.
FACT_RESPONSE = json.dumps([
    {"subject": "Папаха", "subject_type": "user",
     "predicate": "работает", "object": "на заводе", "object_type": "topic",
     "kind": "durable_fact", "source_message_ids": [11]},
    {"subject": "Дима", "subject_type": "user",
     "predicate": "живёт", "object": "в перми", "object_type": "topic",
     "kind": "durable_fact", "source_message_ids": [12]},
], ensure_ascii=False)


class BaselineLLM:
    """Заглушка LLM: отдаёт фиксированный ответ экстрактора фактов."""

    def __init__(self, response: str = FACT_RESPONSE) -> None:
        self.response = response

    async def generate(self, messages):        # noqa: D401 — форма контракта
        return self.response

    async def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


async def seed_messages(db) -> None:
    """Автор-наблюдения для uid (источник доказательства, §1.2.1)."""
    await db.db.executemany(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, is_forward, forward_source, tg_message_id, "
        "history_processed) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(UID_A, CHAT, "привет", 1, "text", "Папаха", 0, "", 1, 0),
         (UID_A, CHAT, "и снова", 2, "text", "папаха", 0, "", 2, 0),
         (UID_B, CHAT, "третье", 3, "text", "ира", 0, "", 3, 0)],
    )
    try:
        await db.db.executemany(
            "INSERT OR IGNORE INTO users_meta (chat_id, user_id) VALUES (?, ?)",
            [(CHAT, UID_A), (CHAT, UID_B)])
    except Exception:      # pragma: no cover — урезанная БД
        pass
    await db.db.commit()


async def build_scenario(db, *, llm=None) -> None:
    """Полный сценарий записи: пред-узлы → W2 → W1."""
    from services.summary_memory import MemoryManager

    # Пред-существующие узлы (не создаются слайсом, важны для коллизий типа):
    # `озон` — узел факта, `папаха` — узел темы. W2/W1 приходят с типами
    # `user`/`fact`, то есть занимают ТОТ ЖЕ слот имени (§1.2.3).
    await db.upsert_node(CHAT, "озон", "fact", origin="search_fact")
    await db.upsert_node(CHAT, "папаха", "topic")
    await seed_messages(db)

    memory = MemoryManager(db, llm or BaselineLLM())
    await memory._write_graph_triplets(CHAT, list(TRIPLETS))
    await memory.memorize_facts(CHAT, "Папаха работает на заводе. Ира живёт в "
                                      "Перми.", "chat_history",
                                tg_message_id=11, forward_from="")


async def snapshot(db) -> dict:
    """Канонический снимок записи БД без волатильных timestamp-колонок."""
    async def rows(sql):
        cursor = await db.db.execute(sql)
        return [list(row) for row in await cursor.fetchall()]

    nodes = await rows(
        "SELECT id, chat_id, entity_name, entity_type, origin, expires_at "
        "FROM nodes ORDER BY id")
    edges = await rows(
        "SELECT id, source_id, target_id, relation_type, weight, fact_id, "
        "origin, expires_at FROM edges ORDER BY id")
    facts = await rows(
        "SELECT id, chat_id, fact, origin, target_user, status, weight, "
        "subject_ref_id, kind FROM graph_facts ORDER BY id")
    try:
        identity = await rows(
            "SELECT chat_id, entity_type, member_node_id, canonical_node_id, "
            "resolution, status FROM mca_entity_canonical "
            "ORDER BY member_node_id")
    except Exception:      # pragma: no cover — БД до миграции v43
        identity = []
    return {"nodes": nodes, "edges": edges, "facts": facts,
            "identity": identity}
