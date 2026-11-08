"""EPIC-MEMORY-COGNITIVE-02 / MEMORY-07 — семантические сообщества (C-6).

Источник: `plans/features/memory-cognitive-02/contracts.md` §0.5 (аддитивная
схема: `v43` = идентичность, `v44` = сообщества), §5.1 (`v44`: раскладка
таблиц, DDL владельца, идемпотентность и инертность) и §6 (C-6: веса рёбер,
членство, жизненный цикл сборки, чтение только `active`, стабильность
`community_id`).

Что здесь есть на этой волне:

* **DDL владельца** таблиц сообществ (`v44`): `mca_community_builds`
  (реестр сборок) и `mca_community_members` (версионное членство) плюс их
  индексы. Миграция `services/database.py::_migrate_communities_v44`
  применяет ровно эти выражения — второй копии DDL в репозитории нет.

Чего здесь осознанно НЕТ на этой волне (следующая волна MEMORY-07, она же
единственный writer этого файла):

* сборка сообществ, веса рёбер (`confirmed` 1.0 / `tentative` 0.5 /
  `legacy` 0.25 / `cooccurrence` 0.1) и `classify_fact_provenance`;
* жизненный цикл `building → active → superseded`/`failed`, стабильность
  `community_id`, `change_summary_json` при split/merge;
* регистрация job в `memory_maintenance` и active-build join в
  `mca_retrieval_context.py`.

Границы (проверяется ревью, §0.5/§6): нет второго хранилища, нет второго
поиска, нет новых колонок в `nodes`/`edges`/`graph_facts`, нет таблицы
доказательств/чекпоинтов/кэша поиска в БД, нет LLM-наименований на горячем
пути. Членство хранит только `nodes.id`; Telegram UID сюда не пишется.

Инертность: шаг `v44` применяется безусловно при старте (как `v43`) —
таблицы существуют всегда, но без гейта `MCA_MEMORY_COMMUNITIES_ENABLED`
(реестр гейтов, default **OFF**, волна 2) их никто не читает и не пишет:
миграция ничего не backfill'ит, старый код таблиц не знает. Откат —
поведенческий (гейт OFF / предыдущий релиз), `DROP` не требуется.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Аддитивные таблицы сообществ (миграция `v44`).
COMMUNITY_BUILDS_TABLE = "mca_community_builds"
COMMUNITY_MEMBERS_TABLE = "mca_community_members"
#: Стабильное имя шага миграции (книга `schema_migrations`).
COMMUNITIES_MIGRATION_STEP_NAME = "memory_communities_v44"

#: DDL владельца реестра сборок — применяет миграция `v44`
#: (`services/database.py`) и тесты. `CREATE ... IF NOT EXISTS`: повторный
#: прогон — no-op, `ALTER` не нужен, существующие таблицы не меняются
#: (§5.1). `graph_revision` — строковый снимок вычисленной ревизии на момент
#: сборки, а не ссылка на несуществующую колонку.
COMMUNITY_BUILDS_DDL_SQLITE: tuple[str, ...] = (
    f"CREATE TABLE IF NOT EXISTS {COMMUNITY_BUILDS_TABLE} ("
    "build_id            TEXT PRIMARY KEY, "
    "chat_id             INTEGER NOT NULL, "
    "algorithm           TEXT NOT NULL, "
    "algorithm_version   TEXT NOT NULL, "
    "params_json         TEXT NOT NULL DEFAULT '{}', "
    "graph_revision      TEXT NOT NULL, "
    "node_count          INTEGER NOT NULL, "
    "edge_count          INTEGER NOT NULL, "
    "prev_build_id       TEXT, "
    "change_summary_json TEXT NOT NULL DEFAULT '{}', "
    # building|active|superseded|failed
    "status              TEXT NOT NULL, "
    "started_at          INTEGER NOT NULL, "
    "finished_at         INTEGER)",
)

#: DDL владельца версионного членства — `v44`. PK запрещает дубль узла в
#: одной сборке/сообществе; канонический `nodes.id` (после redirect
#: `entity_resolver`), не Telegram UID (§6).
COMMUNITY_MEMBERS_DDL_SQLITE: tuple[str, ...] = (
    f"CREATE TABLE IF NOT EXISTS {COMMUNITY_MEMBERS_TABLE} ("
    "chat_id       INTEGER NOT NULL, "
    "build_id      TEXT NOT NULL, "
    "community_id  TEXT NOT NULL, "
    "node_id       INTEGER NOT NULL, "
    "member_weight REAL NOT NULL DEFAULT 1.0, "
    "created_at    INTEGER NOT NULL, "
    "PRIMARY KEY (chat_id, build_id, community_id, node_id))",
)

#: Индексы владельца (§5.1): реестр сборок читается по
#: `(chat_id, status, started_at DESC)`, членство — по узлу и по сообществу.
COMMUNITY_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_mca_community_builds_chat_status "
    f"ON {COMMUNITY_BUILDS_TABLE} (chat_id, status, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_mca_community_members_node "
    f"ON {COMMUNITY_MEMBERS_TABLE} (chat_id, build_id, node_id)",
    "CREATE INDEX IF NOT EXISTS idx_mca_community_members_community "
    f"ON {COMMUNITY_MEMBERS_TABLE} (chat_id, build_id, community_id)",
)

# ── закрытые строковые значения `mca_community_builds.status` (§6) ─────────
STATUS_BUILDING = "building"
STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_FAILED = "failed"

__all__ = [
    "COMMUNITY_BUILDS_TABLE",
    "COMMUNITY_MEMBERS_TABLE",
    "COMMUNITIES_MIGRATION_STEP_NAME",
    "COMMUNITY_BUILDS_DDL_SQLITE",
    "COMMUNITY_MEMBERS_DDL_SQLITE",
    "COMMUNITY_INDEX_DDL",
    "STATUS_BUILDING",
    "STATUS_ACTIVE",
    "STATUS_SUPERSEDED",
    "STATUS_FAILED",
]
