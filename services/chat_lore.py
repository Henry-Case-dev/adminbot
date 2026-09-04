"""Раунд 5 (T-733, spec 3.2.3, FR-C3): лор конференции чата 2661910336
(джаббер-конфа «с нулевых», Пермь; переезды ВК→ТГ). Инжект идемпотентный:
protected_facts (чат-уровень, user_name NULL — виден всем юзерам чата в
<protected_facts>) + graph_facts (origin='user_memory', вечно; FTS-строка
пишется insert_graph_fact; vec-строка добирается ленивым backfill при
старте). Дата: 04.09.2026.
"""
import logging
import time

from services.database import DatabaseService

logger = logging.getLogger(__name__)

CHAT_LORE_TARGET_CHAT_ID = 2661910336

# ДОСЛОВНЫЙ текст юзера (04.09.2026, раунд 5, пункт 2; spec Приложение A) —
# НЕ редактировать: один абзац, «ее» и «(тм)» как в оригинале.
CHAT_LORE_2661910336 = ("Эта конфа существует уже много лет и ее история тянется с нулевых, "
                        "начиная с джаббер конфы, она не раз переезжала, то в ВК, то в телеграм, "
                        "не раз пересоздавалась. Изначально это Пермская конфа, но исторически "
                        "сложилось что тут люди из разных городов. Изначально все начиналось со "
                        "Светы, Максима Гурьева и жаббер конфы, потом сходки соц из Светы, Сокача, "
                        "Эткина, Светочки, Даши(тм), Жени, Даши, Кирилла, Ринтаро, Коткуна, потом "
                        "Васи, Ксюши, Леры и закамские сходки, Никита из Анадыря, Саня Карсаков, "
                        "Абатур, Витя, Врач, Денис (земля ему пухом), Савы, Симкикуна, Артема и так "
                        "далее. Это очень длинный лор, это знать надо.")


async def ensure_chat_lore(db: DatabaseService) -> dict:
    """Раунд 5 (T-733): идемпотентный инжект лора чата — protected_facts
    (чат-уровень) + graph_facts (origin='user_memory', expires_at NULL,
    weight 1.0, target_user NULL; FTS-строку пишет insert_graph_fact).
    Проверка существования — по ТОЧНОМУ тексту факта. Возврат
    {"inserted": n, "skipped": n} (n — суммарные строки, 0..2). Fail-open:
    ошибка БД → WARNING + {"inserted": 0, "skipped": 0} (старт не роняем)."""
    chat_id = CHAT_LORE_TARGET_CHAT_ID
    text = CHAT_LORE_2661910336
    inserted = 0
    skipped = 0
    try:
        cursor = await db.db.execute(
            "SELECT 1 FROM protected_facts "
            "WHERE chat_id = ? AND user_name IS NULL AND fact = ? LIMIT 1",
            (chat_id, text))
        if await cursor.fetchone() is None:
            result = await db.db.execute(
                "INSERT OR IGNORE INTO protected_facts "
                "(chat_id, user_name, fact, created_at) VALUES (?, NULL, ?, ?)",
                (chat_id, text, time.time()))
            await db.db.commit()
            if result.rowcount:
                inserted += 1
            else:
                skipped += 1
        else:
            skipped += 1
        cursor = await db.db.execute(
            "SELECT 1 FROM graph_facts "
            "WHERE chat_id = ? AND fact = ? AND origin = 'user_memory' LIMIT 1",
            (chat_id, text))
        if await cursor.fetchone() is None:
            await db.insert_graph_fact(chat_id, text, "user_memory",
                                       expires_at=None, target_user=None,
                                       weight=1.0)
            inserted += 1
        else:
            skipped += 1
        logger.info("[chat_lore] ensure | chat_id=%s | inserted=%d | skipped=%d",
                    chat_id, inserted, skipped)
    except Exception:
        logger.warning("[chat_lore] ensure failed — fail-open | chat_id=%s",
                       chat_id, exc_info=True)
        return {"inserted": 0, "skipped": 0}
    return {"inserted": inserted, "skipped": skipped}
