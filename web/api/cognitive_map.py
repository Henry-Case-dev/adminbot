"""EVOL-COG-MAP (W7-S1) — данные «Когнитивной карты» (аддитивный read-API).

Контракт: `plans/features/evol/arch/cog-map-contract.md` §2/§5 (одна страница
правды по модели данных и лимитам). Слайс S1 — только данные + клиентский
адаптер; визуальная система, карточка и мобильная композиция — S2..S4.

Что здесь есть:
  * ``GET /api/memory/cognitive-map`` — единая типизированная модель
    (узлы ``entity``/``fact``/``belief``/``paradigm``/``observation``/
    ``evolution_event`` + рёбра) поверх СУЩЕСТВУЮЩИХ источников;
  * ``build_cognitive_map(db, chat_id)`` — та же сборка без FastAPI-слоя
    (используется тестами; auth/DI остаются в эндпоинте);
  * MEM-08-S2 (аддитивно): блок ``communities`` из АКТИВНОЙ сборки сообществ
    (``memory_search.read_active_communities``) и
    ``GET /api/memory/search`` — единый поиск, который вызывает **только**
    существующий ``mca_retrieval_context.retrieve`` через
    ``memory_search.search_memory`` (своего поиска здесь нет).

Чего здесь НЕТ (сознательно, §2 «запрет второго хранилища»):
  * второго графового хранилища / новой очереди извлечения / эмбеддингов;
  * LLM-вызовов (рендер, зум, фильтры, карточка — чистый read);
  * ``services/database.py`` не меняется: топология — ``graph_snapshot``,
    остальное — bounded SQL в этом модуле (прецедент сырого SQL —
    ``memory_agi.py`` attribution trace).

Честность модели (§2.3 ТЗ, §4 контракта):
  * ``id`` — стабильный типизированный и ЧАТ-квалифицированный ключ
    (``fact:<chat>:<id>``, ``ent:<chat>:<nodes.id>``, ``obs:<chat>:<id>``,
    ``evt:<chat>:...``) — узлы разных чатов не сливаются даже при совпадении
    имени;
  * времена разделены и не смешиваются: ``occurred_at`` (когда произошло —
    ``message_timestamp``), ``observed_at`` (когда обнаружено —
    ``mca_trait_observations.observed_at``), ``saved_at`` (когда сохранено —
    ``created_at``), ``confirmed_at`` (``last_confirmed_at``),
    ``updated_at`` (только там, где запись реально обновляемая — ``edges``);
    отсутствующее поле всегда ``null``;
  * ``confidence``/``strength``/``freshness`` НЕ рассчитываются → ключей нет;
  * ``isolated: true`` — у узла нет ни одного подтверждённого ребра в payload;
    рёбра не выдумываются (только ``edges``, ``edges.fact_id``,
    ``graph_facts.supersedes``, ``graph_facts.source_ids``);
  * рёбра без ``fact_id`` честно отдают ``fact_id: null`` и
    ``justification_recorded: false`` («обоснование не записано» — текст S3).

Границы (§5 контракта, только существующие числа):
  * узлы — ``GRAPH_MAX_NODES`` (800), рёбра — ``GRAPH_MAX_EDGES`` (2400);
  * 4 когнитивных класса по ``GRAPH_SEED_NODES`` (150) = ≤600
    (факты / убеждения / парадигмы / эволюция характера — последний класс
    включает ``observation`` и ``evolution_event``);
  * топология сущностей получает остаток, но не меньше 150 сидов;
  * порядок обрезки фиксирован (класс → importance/recency → id),
    ``truncated``/``shown_of`` заполняются всегда;
  * неограниченных выборок и N+1-запросов нет: по одному запросу на класс
    (``COUNT(*) OVER ()`` даёт полный размер класса без второго прохода).

Полнота (B1 ревью W7-S1): ``truncated`` для ВСЕХ шести классов (и для рёбер)
означает ровно одно — «показано меньше, чем всего» (``total > shown``).
``truncated.nodes``/``truncated.edges`` — сводка тех же значений, поэтому
``state="ok"`` невозможно при неполной карте: снапшот, вернувший окрестность
150 сидов из 850 сущностей, даёт ``shown=152, total=850`` → ``partial``.

Состояния (§4 контракта): ``ok`` / ``partial`` (обрезано) / ``empty``
(источники прочитаны, данных нет) / ``degraded`` (часть источников НЕ
загружена — имена перечислены в ``degraded.not_loaded``, состояния
источников — ``sources[name]``: ``loaded`` | ``not_loaded``; новых
reason-кодов не вводится). ``empty`` и ``not_loaded`` различимы: нули
пришли из прочитанных источников, а не из упавшего чтения. Fail-open только
по источникам: эндпоинт отдаёт 200 с честным ``degraded``; отсутствие БД —
прежний 503 (``_db_or_503``).
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import time
from typing import Annotated, Any, Awaitable, Callable

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from services.database import parse_belief_meta
from services import memory_search
from web.api.deps import get_tma_user
from web.api.memory_agi import (
    GRAPH_MAX_EDGES,
    GRAPH_MAX_NODES,
    GRAPH_SEED_NODES,
    _db_or_503,
    _require_global_admin,
)

logger = logging.getLogger(__name__)

cognitive_map_router = APIRouter()

# Версия payload: клиентский адаптер (web/static/cognitive-map.js) сверяет её
# и не падает на незнакомой версии (только честный warning + базовые поля).
PAYLOAD_VERSION = "cog-map/1"

# §5 контракта: когнитивный класс = GRAPH_SEED_NODES, классов четыре.
COG_CLASS_LIMIT = GRAPH_SEED_NODES
COG_CLASS_COUNT = 4
ENTITY_MIN_NODES = GRAPH_SEED_NODES
# «Эволюция характера» — реальные записи изменений (§2 контракта).
_DREAM_CHANGE_KINDS = ("distilled", "resurrect", "decay_run", "deep_run")
# F3-парадигмы: graph_stats ищет их по двум вариантам JSON-сериализации.
_PARADIGM_LIKE = ('%"type":"paradigm"%', '%"type": "paradigm"%')
_TITLE_LIMIT = 90
# SQLite по умолчанию держит ≥999 параметров (3.32+ — 32766); набор сущностей
# ограничен ENTITY-кэпом, поэтому IN-список собирается одним запросом.
_MAX_NODE_PARAMS = GRAPH_MAX_NODES

_FACT_COLUMNS = (
    "id, chat_id, fact, kind, status, origin, importance, weight, "
    "created_at, message_timestamp, last_confirmed_at, tg_message_id, "
    "forward_from, supersedes, source_ids, belief_meta"
)

_EMPTY_METRICS = {"importance": None, "weight": None, "degree": None}


# ── мелкие чистые хелперы ───────────────────────────────────────────────────

def _ts(value: Any) -> int | None:
    """Epoch → int; 0/пусто/мусор → None (не выдаём «0» за дату)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _int_or_none(value: Any) -> int | None:
    """Идентификатор → int без фильтра знака (chat_id в Telegram отрицательный)."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 3)


def _scope_key(chat_id: Any) -> str:
    """Компонент ключа узла: chat_id либо ``global`` (чатовый ключ неизвестен
    или запись системная — см. `memory_dream_log.chat_id = 0`)."""
    try:
        number = int(chat_id)
    except (TypeError, ValueError):
        return "global"
    return str(number) if number != 0 else "global"


def _title(text: Any, limit: int = _TITLE_LIMIT) -> str:
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def _source_ids(raw: Any) -> list[int]:
    """JSON-список id-источников → list[int] (fail-open → [])."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    out: list[int] = []
    for item in parsed:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _meta_list(raw: Any) -> list[Any]:
    """JSON-список произвольных refs (``mca_trait_observations.source_refs``)."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    return []


def _text_epoch(value: Any) -> int | None:
    """``edges.last_updated`` ('YYYY-MM-DD HH:MM:SS', UTC) → epoch."""
    if not value:
        return None
    try:
        moment = _dt.datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return int(moment.replace(tzinfo=_dt.timezone.utc).timestamp())


def _time_block(**kwargs: int | None) -> dict:
    """Все временные поля присутствуют всегда; неизвестное — ``null``."""
    block = {"occurred_at": None, "observed_at": None, "saved_at": None,
             "confirmed_at": None, "updated_at": None}
    for key, value in kwargs.items():
        if key in block:
            block[key] = value
    return block


def _node(node_id: str, kind: str, *, chat_id: int | None, title: str,
          text: str | None, status: str | None, time_block: dict,
          provenance: dict, metrics: dict | None = None,
          refs: dict | None = None, scope: str = "chat") -> dict:
    return {
        "id": node_id,
        "kind": kind,
        "scope": scope,
        "chat_id": chat_id,
        "title": title,
        "text": text,
        "status": status,
        "isolated": True,
        "time": time_block,
        "provenance": provenance,
        "metrics": dict(metrics or _EMPTY_METRICS),
        "refs": dict(refs or {}),
    }


def _edge(edge_id: str, source: str, target: str, relation: str, *,
          chat_id: int | None, basis: str, provenance: dict,
          derived: bool) -> dict:
    return {
        "id": edge_id,
        "from": source,
        "to": target,
        "relation": relation,
        "kind": "derived" if derived else "recorded",
        "derived": derived,
        "chat_id": chat_id,
        "provenance": provenance,
        "justification_recorded": provenance.get("fact_id") is not None,
    }


def _recorded_edge_provenance(row: dict) -> dict:
    fact_id = _ts(row.get("fact_id"))
    return {
        "edge_id": int(row["id"]),
        "fact_id": fact_id,
        "origin": str(row.get("origin") or "") or None,
        "recorded_at": _ts(row.get("created_at")),
        "updated_at": _text_epoch(row.get("last_updated")),
        "weight": _ts(row.get("weight")),
        "basis": "fact_provenance" if fact_id is not None else "recorded_edge",
    }


# ── выборки (по одному bounded-запросу на класс) ────────────────────────────

async def _rows(db, sql: str, params: list) -> list[dict]:
    cursor = await db.db.execute(sql, params)
    return [dict(row) for row in await cursor.fetchall()]


async def _count(db, sql: str, params: list) -> int:
    rows = await _rows(db, sql, params)
    if not rows:
        return 0
    value = rows[0].get("c")
    return int(value) if value is not None else 0


async def _fact_class_rows(db, chat_id: int | None, *, where: str,
                           params: tuple, limit: int) -> list[dict]:
    """Класс ``graph_facts``: ``kind``/paradigm-фильтр + полный размер класса.

    ``COUNT(*) OVER ()`` считается по отфильтрованному набору ДО ``LIMIT`` —
    «показано X из Y» без второго прохода по таблице.
    """
    chat_sql = "" if chat_id is None else " AND chat_id = ?"
    chat_params: list = [] if chat_id is None else [int(chat_id)]
    sql = ("SELECT " + _FACT_COLUMNS + ", COUNT(*) OVER() AS total_all "
           "FROM graph_facts WHERE " + where + chat_sql +
           " ORDER BY importance DESC, created_at DESC, id DESC LIMIT ?")
    return await _rows(db, sql, list(params) + chat_params + [int(limit)])


async def _observation_rows(db, chat_id: int | None, limit: int) -> list[dict]:
    chat_sql = "" if chat_id is None else " WHERE chat_id = ?"
    chat_params: list = [] if chat_id is None else [int(chat_id)]
    sql = ("SELECT id, chat_id, agent_id, dimension, raw_text, source_refs, "
           "subject_status, observed_at, created_at, "
           "COUNT(*) OVER() AS total_all FROM mca_trait_observations" +
           chat_sql + " ORDER BY observed_at DESC, id DESC LIMIT ?")
    return await _rows(db, sql, chat_params + [int(limit)])


async def _dream_rows(db, chat_id: int | None, limit: int) -> list[dict]:
    kinds = ",".join("?" for _ in _DREAM_CHANGE_KINDS)
    where = "kind IN (" + kinds + ")"
    params: list = list(_DREAM_CHANGE_KINDS)
    if chat_id is not None:
        where += " AND chat_id = ?"
        params.append(int(chat_id))
    sql = ("SELECT id, chat_id, run_at, kind, cluster_id, source_ids, "
           "belief_id, status, COUNT(*) OVER() AS total_all "
           "FROM memory_dream_log WHERE " + where +
           " ORDER BY run_at DESC, id DESC LIMIT ?")
    return await _rows(db, sql, params + [int(limit)])


async def _node_chat_ids(db, node_ids: list[int]) -> dict[int, int]:
    """chat_id для узлов ``nodes`` (глобальный scope: ключ чат-квалифицирован)."""
    out: dict[int, int] = {}
    chunk = 400
    for start in range(0, len(node_ids), chunk):
        part = node_ids[start:start + chunk]
        marks = ",".join("?" for _ in part)
        cursor = await db.db.execute(
            "SELECT id, chat_id FROM nodes WHERE id IN (" + marks + ")",
            list(part))
        for row in await cursor.fetchall():
            out[int(row["id"])] = int(row["chat_id"])
    return out


async def _recorded_edges(db, chat_id: int | None,
                          node_ids: list[int]) -> list[dict]:
    """Рёбра внутри набора сущностей — с provenance (``fact_id``/``origin``).

    Набор ограничен ENTITY-кэпом (≤ ``GRAPH_MAX_NODES``), поэтому IN-список
    укладывается в лимит параметров SQLite одним запросом (N+1 нет).
    """
    if not node_ids or len(node_ids) > _MAX_NODE_PARAMS:
        return []
    marks = ",".join("?" for _ in node_ids)
    sql = ("SELECT id, chat_id, source_id, target_id, relation_type, weight, "
           "last_updated, created_at, origin, fact_id FROM edges "
           "WHERE source_id IN (" + marks + ") AND target_id IN (" + marks +
           ") AND origin != 'bot_direct_reply'")
    params: list = list(node_ids) + list(node_ids)
    if chat_id is not None:
        sql += " AND chat_id = ?"
        params.append(int(chat_id))
    sql += " ORDER BY weight DESC, id DESC LIMIT ?"
    params.append(int(GRAPH_MAX_EDGES) + 1)
    return await _rows(db, sql, params)


def _edge_scope_sql(chat_id: int | None) -> tuple[str, list]:
    if chat_id is None:
        return " AND origin != 'bot_direct_reply'", []
    return (" AND origin != 'bot_direct_reply' AND chat_id = ?",
            [int(chat_id)])


def _node_scope_sql(chat_id: int | None) -> tuple[str, list]:
    if chat_id is None:
        return "", []
    return " AND chat_id = ?", [int(chat_id)]


# ── построение узлов ────────────────────────────────────────────────────────

def _fact_node(row: dict, kind: str) -> dict:
    chat_id = int(row["chat_id"])
    row_id = int(row["id"])
    meta = parse_belief_meta(row.get("belief_meta"))
    sources = _source_ids(row.get("source_ids"))
    return _node(
        f"{kind}:{_scope_key(chat_id)}:{row_id}",
        kind,
        chat_id=chat_id,
        title=_title(row.get("fact")),
        text=str(row.get("fact") or ""),
        status=str(row.get("status") or "") or None,
        time_block=_time_block(
            occurred_at=_ts(row.get("message_timestamp")),
            saved_at=_ts(row.get("created_at")),
            confirmed_at=_ts(row.get("last_confirmed_at")),
        ),
        provenance={
            "record": "graph_facts",
            "fact_id": row_id,
            "chat_id": chat_id,
            "origin": str(row.get("origin") or "") or None,
            "message_id": _ts(row.get("tg_message_id")),
            "forward_from": str(row.get("forward_from") or "") or None,
            "version_of": _ts(row.get("supersedes")),
            "source_ids": sources,
            "belief_meta_type": (meta.get("type") if meta else None),
        },
        metrics={
            "importance": _ts(row.get("importance")),
            "weight": _float_or_none(row.get("weight")),
            "degree": None,
        },
        refs={"supersedes": _ts(row.get("supersedes")),
              "source_ids": sources},
    )


def _observation_node(row: dict) -> dict:
    chat_id = _int_or_none(row.get("chat_id"))
    row_id = int(row["id"])
    return _node(
        f"obs:{_scope_key(chat_id)}:{row_id}",
        "observation",
        chat_id=chat_id,
        scope="chat" if chat_id is not None else "global",
        title=_title(row.get("raw_text")),
        text=str(row.get("raw_text") or ""),
        status=str(row.get("subject_status") or "") or None,
        time_block=_time_block(
            observed_at=_ts(row.get("observed_at")),
            saved_at=_ts(row.get("created_at")),
        ),
        provenance={
            "record": "mca_trait_observations",
            "observation_id": row_id,
            "chat_id": chat_id,
            "agent_id": str(row.get("agent_id") or "") or None,
            "dimension": str(row.get("dimension") or "") or None,
            "source_refs": _meta_list(row.get("source_refs")),
        },
    )


def _revision_node(chat_id: int, row: dict) -> dict:
    """Реальное изменение: ``graph_facts.supersedes`` (новая версия факта)."""
    row_id = int(row["id"])
    old_id = _ts(row.get("supersedes"))
    return _node(
        f"evt:{_scope_key(chat_id)}:revision:{row_id}",
        "evolution_event",
        chat_id=chat_id,
        title=_title("Версия заменена: " + str(row.get("fact") or "")),
        text=None,
        status="superseded",
        time_block=_time_block(occurred_at=_ts(row.get("created_at")),
                              saved_at=_ts(row.get("created_at"))),
        provenance={
            "record": "graph_facts.supersedes",
            "chat_id": chat_id,
            "new_fact_id": row_id,
            "old_fact_id": old_id,
        },
        refs={"new_fact_id": row_id, "old_fact_id": old_id},
    )


def _dream_node(row: dict) -> dict:
    raw_chat_id = _int_or_none(row.get("chat_id"))
    # `memory_dream_log.chat_id = 0` — системный прогон (глобальный decay),
    # а не «чат 0»: в payload он честно глобальный, без выдуманного chat_id.
    chat_id = raw_chat_id if raw_chat_id not in (None, 0) else None
    row_id = int(row["id"])
    kind = str(row.get("kind") or "")
    return _node(
        f"evt:{_scope_key(chat_id)}:dream:{row_id}",
        "evolution_event",
        chat_id=chat_id,
        scope="chat" if chat_id is not None else "global",
        title=_title("Цикл памяти: " + kind),
        text=None,
        status=str(row.get("status") or "") or None,
        time_block=_time_block(occurred_at=_ts(row.get("run_at")),
                              saved_at=_ts(row.get("run_at"))),
        provenance={
            "record": "memory_dream_log",
            "log_id": row_id,
            "chat_id": chat_id,
            "dream_kind": kind or None,
            "cluster_id": _ts(row.get("cluster_id")),
            "belief_id": _ts(row.get("belief_id")),
            "source_ids": _source_ids(row.get("source_ids")),
        },
        refs={"belief_id": _ts(row.get("belief_id"))},
    )


# ── основная сборка ─────────────────────────────────────────────────────────

async def build_cognitive_map(db, chat_id: int | None = None, *,
                              now: int | None = None) -> dict:
    """Собрать payload Когнитивной карты из существующих источников.

    ``chat_id`` — область: конкретный чат (``scope.mode = "chat"``) либо
    ``None`` — глобальный агрегат администратора (``scope.mode = "global"``);
    узлы при этом остаются чат-квалифицированными.
    """
    chat = int(chat_id) if chat_id is not None else None
    generated_at = int(now if now is not None else time.time())
    sources: dict[str, str] = {}
    unavailable: list[str] = []

    async def _source(name: str, factory: Callable[[], Awaitable[Any]],
                      default: Any) -> Any:
        try:
            value = await factory()
        except Exception:
            logger.warning("[cognitive_map] источник %s недоступен — degraded",
                           name, exc_info=True)
            sources[name] = "not_loaded"
            unavailable.append(name)
            return default
        sources[name] = "loaded"
        return value

    # (1) Когнитивные классы: по одному bounded-запросу на класс.
    fact_rows = await _source(
        "facts",
        lambda: _fact_class_rows(db, chat, where="kind = 'fact'", params=(),
                                 limit=COG_CLASS_LIMIT + 1),
        [])
    belief_rows = await _source(
        "beliefs",
        lambda: _fact_class_rows(
            db, chat,
            where=("kind = 'belief' AND (belief_meta IS NULL OR "
                   "(belief_meta NOT LIKE ? AND belief_meta NOT LIKE ?))"),
            params=_PARADIGM_LIKE, limit=COG_CLASS_LIMIT + 1),
        [])
    paradigm_rows = await _source(
        "paradigms",
        lambda: _fact_class_rows(
            db, chat,
            where=("kind = 'belief' AND (belief_meta LIKE ? OR "
                   "belief_meta LIKE ?)"),
            params=_PARADIGM_LIKE, limit=COG_CLASS_LIMIT + 1),
        [])

    def _take(rows: list[dict], limit: int) -> tuple[list[dict], int, bool]:
        """Класс до cap: ``(строки, полный размер, обрезано)``."""
        shown = rows[:limit]
        total = 0
        if rows:
            try:
                total = int(rows[0].get("total_all") or 0)
            except (TypeError, ValueError):
                total = 0
        total = max(total, len(rows))
        return shown, total, total > len(shown)

    fact_shown, fact_total, fact_cut = _take(fact_rows, COG_CLASS_LIMIT)
    belief_shown, belief_total, belief_cut = _take(belief_rows,
                                                   COG_CLASS_LIMIT)
    paradigm_shown, paradigm_total, paradigm_cut = _take(paradigm_rows,
                                                         COG_CLASS_LIMIT)

    observation_rows = await _source(
        "observations",
        lambda: _observation_rows(db, chat, COG_CLASS_LIMIT + 1),
        [])
    dream_rows = await _source(
        "memory_cycle",
        lambda: _dream_rows(db, chat, COG_CLASS_LIMIT + 1),
        [])
    obs_total = 0
    if observation_rows:
        obs_total = max(int(observation_rows[0].get("total_all") or 0),
                        len(observation_rows))
    dream_total = 0
    if dream_rows:
        dream_total = max(int(dream_rows[0].get("total_all") or 0),
                          len(dream_rows))

    revision_total = await _source(
        "revisions",
        lambda: _count(
            db,
            "SELECT COUNT(*) AS c FROM graph_facts WHERE supersedes IS NOT "
            "NULL" + ("" if chat is None else " AND chat_id = ?"),
            [] if chat is None else [chat]),
        0)

    # (2) Топология сущностей — существующий graph_snapshot (§2 контракта).
    # Бюджет: 4 когнитивных класса ×150 = ≤600, остаток — сущностям,
    # но не меньше их 150 сидов.
    revisions_loaded = sum(1 for row in fact_shown
                           if _ts(row.get("supersedes")) is not None)
    evolution_count = min(
        len(observation_rows) + len(dream_rows) + revisions_loaded,
        COG_CLASS_LIMIT)
    cog_used = (len(fact_shown) + len(belief_shown) + len(paradigm_shown)
                + evolution_count)
    entity_cap = max(ENTITY_MIN_NODES, GRAPH_MAX_NODES - cog_used)
    snapshot = await _source(
        "graph",
        lambda: db.graph_snapshot(chat_id=chat, max_nodes=entity_cap,
                                  max_edges=GRAPH_MAX_EDGES,
                                  seed_nodes=GRAPH_SEED_NODES),
        {"nodes": [], "edges": [], "truncated": False})
    snap_nodes = list(snapshot.get("nodes") or [])

    # (3) chat_id узлов снапшота (в чатовом scope он известен заранее).
    if chat is not None:
        node_chats = {int(node["id"]): chat for node in snap_nodes}
    else:
        node_chats = await _source(
            "graph_nodes",
            lambda: _node_chat_ids(db, [int(n["id"]) for n in snap_nodes]),
            {})

    nodes: list[dict] = []
    node_index: dict[tuple, str] = {}   # (chat_id, fact_id) → id узла
    entity_index: dict[tuple, str] = {}  # (chat_id, nodes.id) → id узла
    fact_row_by_key: dict[tuple, dict] = {}

    def _register_fact(row: dict, kind: str) -> dict:
        node = _fact_node(row, kind)
        nodes.append(node)
        key = (int(row["chat_id"]), int(row["id"]))
        node_index[key] = node["id"]
        fact_row_by_key[key] = row
        return node

    for row in fact_shown:
        _register_fact(row, "fact")
    for row in belief_shown:
        _register_fact(row, "belief")
    for row in paradigm_shown:
        _register_fact(row, "paradigm")

    # Класс «эволюция характера» — реальные записи изменений, ≤150 узлов.
    evolution_candidates: list[dict] = []
    for row in observation_rows:
        evolution_candidates.append(_observation_node(row))
    for row in dream_rows:
        evolution_candidates.append(_dream_node(row))
    for row in fact_shown:
        if _ts(row.get("supersedes")) is not None:
            evolution_candidates.append(
                _revision_node(int(row["chat_id"]), row))
    evolution_candidates.sort(key=lambda n: (-(n["time"].get("occurred_at")
                                               or 0), n["id"]))
    evolution_nodes = evolution_candidates[:COG_CLASS_LIMIT]
    evolution_total = obs_total + dream_total + int(revision_total or 0)
    evolution_cut = evolution_total > len(evolution_nodes)
    nodes.extend(evolution_nodes)

    for node in snap_nodes:
        node_id = int(node["id"])
        node_chat = node_chats.get(node_id)
        entity_node = _node(
            f"ent:{_scope_key(node_chat)}:{node_id}",
            "entity",
            chat_id=node_chat,
            title=_title(node.get("label")),
            text=None,
            status=None,
            scope="chat" if node_chat is not None else "global",
            time_block=_time_block(),
            provenance={
                "record": "nodes",
                "node_id": node_id,
                "chat_id": node_chat,
                "entity_type": str(node.get("group") or "") or None,
                "degree": _ts(node.get("degree")),
            },
            metrics={"importance": None, "weight": None,
                     "degree": _ts(node.get("degree"))},
        )
        nodes.append(entity_node)
        if node_chat is not None:
            entity_index[(node_chat, node_id)] = entity_node["id"]

    node_ids = [node["id"] for node in nodes]
    known_node_ids = set(node_ids)

    # (4) Рёбра: записанные (edges) + производные по реальным ссылкам.
    edge_rows = await _source(
        "edges",
        lambda: _recorded_edges(db, chat, [int(n["id"]) for n in snap_nodes]),
        [])
    edge_total = await _source(
        "totals",
        lambda: _count(
            db,
            "SELECT COUNT(*) AS c FROM edges WHERE 1=1"
            + _edge_scope_sql(chat)[0],
            _edge_scope_sql(chat)[1]),
        0)

    edges: list[dict] = []
    seen_edges: set[tuple] = set()

    def _add_edge(edge: dict) -> None:
        key = (edge["from"], edge["to"], edge["relation"])
        if key in seen_edges:
            return
        if edge["from"] not in known_node_ids or edge["to"] not in known_node_ids:
            return
        seen_edges.add(key)
        edges.append(edge)

    recorded_cut = len(edge_rows) > GRAPH_MAX_EDGES
    for row in edge_rows[:GRAPH_MAX_EDGES]:
        edge_chat = _int_or_none(row.get("chat_id"))
        source_key = entity_index.get((edge_chat, int(row["source_id"])))
        target_key = entity_index.get((edge_chat, int(row["target_id"])))
        if not source_key or not target_key:
            continue
        edge_id = f"edge:{_scope_key(edge_chat)}:{int(row['id'])}"
        _add_edge(_edge(
            edge_id, source_key, target_key,
            str(row.get("relation_type") or ""),
            chat_id=edge_chat, basis="recorded",
            provenance=_recorded_edge_provenance(row), derived=False))

    derived_cut = False
    unresolved_refs = 0
    if len(edges) < GRAPH_MAX_EDGES:
        # derived_from по edges.fact_id: факт, породивший ребро.
        for row in edge_rows[:GRAPH_MAX_EDGES]:
            fact_id = _int_or_none(row.get("fact_id"))
            if fact_id is None:
                continue
            edge_chat = _int_or_none(row.get("chat_id"))
            fact_node = node_index.get((edge_chat, fact_id))
            source_key = entity_index.get((edge_chat, int(row["source_id"])))
            if fact_node is None or source_key is None:
                unresolved_refs += 1
                continue
            if len(edges) >= GRAPH_MAX_EDGES:
                derived_cut = True
                break
            _add_edge(_edge(
                f"derived:{_scope_key(edge_chat)}:{int(row['id'])}:fact",
                fact_node, source_key, "derived_from",
                chat_id=edge_chat, basis="edge_fact_id",
                provenance={"edge_id": int(row["id"]), "fact_id": fact_id,
                            "chat_id": edge_chat, "basis": "edge_fact_id"},
                derived=True))

    if len(edges) < GRAPH_MAX_EDGES:
        # revised_by по graph_facts.supersedes (обе версии должны быть в карте).
        for (fact_chat, fact_id), node_id in node_index.items():
            row = fact_row_by_key.get((fact_chat, fact_id))
            if row is None:
                continue
            old_id = _ts(row.get("supersedes"))
            if old_id is None:
                continue
            old_node = node_index.get((fact_chat, old_id))
            if old_node is None:
                unresolved_refs += 1
                continue
            if len(edges) >= GRAPH_MAX_EDGES:
                derived_cut = True
                break
            _add_edge(_edge(
                f"revision:{_scope_key(fact_chat)}:{fact_id}:{old_id}",
                old_node, node_id, "revised_by",
                chat_id=fact_chat, basis="supersedes",
                provenance={"chat_id": fact_chat, "old_fact_id": old_id,
                            "new_fact_id": fact_id,
                            "basis": "supersedes"},
                derived=True))

    if len(edges) < GRAPH_MAX_EDGES:
        # derived_from по graph_facts.source_ids: убеждение/парадигма ← факты.
        for (fact_chat, fact_id), node_id in node_index.items():
            row = fact_row_by_key.get((fact_chat, fact_id))
            if row is None or str(row.get("kind") or "") not in ("belief",
                                                                "paradigm"):
                continue
            for source_fact in _source_ids(row.get("source_ids")):
                source_node = node_index.get((fact_chat, source_fact))
                if source_node is None:
                    unresolved_refs += 1
                    continue
                if len(edges) >= GRAPH_MAX_EDGES:
                    derived_cut = True
                    break
                _add_edge(_edge(
                    f"derived:{_scope_key(fact_chat)}:{fact_id}:{source_fact}",
                    node_id, source_node, "derived_from",
                    chat_id=fact_chat, basis="source_ids",
                    provenance={"chat_id": fact_chat,
                                "fact_id": fact_id,
                                "source_fact_id": source_fact,
                                "basis": "source_ids"},
                    derived=True))

    # (5) Изолированность — по ПОЛНОМУ набору рёбер (до усечения по cap).
    linked: set[str] = set()
    for edge in edges:
        linked.add(edge["from"])
        linked.add(edge["to"])
    for node in nodes:
        node["isolated"] = node["id"] not in linked

    used_edges = edges[:GRAPH_MAX_EDGES]

    entity_total = await _source(
        "node_totals",
        lambda: _count(
            db,
            "SELECT COUNT(*) AS c FROM nodes WHERE "
            "entity_name IS NOT NULL AND entity_name != ''"
            + _node_scope_sql(chat)[0],
            _node_scope_sql(chat)[1]),
        0)
    shown_entities = sum(1 for n in nodes if n["kind"] == "entity")
    entity_total = max(int(entity_total or 0), shown_entities)
    node_total = (fact_total + belief_total + paradigm_total
                  + evolution_total + entity_total)
    edge_total = max(int(edge_total or 0), len(used_edges))

    obs_shown = sum(1 for n in evolution_nodes if n["kind"] == "observation")
    evt_shown = sum(1 for n in evolution_nodes
                    if n["kind"] == "evolution_event")
    evt_total = dream_total + int(revision_total or 0)

    # ОДНО правило полноты для всех шести классов: «показано меньше, чем
    # всего» — единственное, что означает `truncated`. Флаги cap-ов снизу
    # добавляются только как страховка (потеря строк без счётчика).
    by_kind = {
        "fact": {"shown": len(fact_shown), "total": fact_total,
                 "truncated": fact_cut or fact_total > len(fact_shown)},
        "belief": {"shown": len(belief_shown), "total": belief_total,
                   "truncated": belief_cut or belief_total
                   > len(belief_shown)},
        "paradigm": {"shown": len(paradigm_shown), "total": paradigm_total,
                     "truncated": paradigm_cut or paradigm_total
                     > len(paradigm_shown)},
        "observation": {"shown": obs_shown, "total": obs_total,
                        "truncated": obs_total > obs_shown},
        "evolution_event": {"shown": evt_shown, "total": evt_total,
                            "truncated": evt_total > evt_shown},
        "entity": {
            "shown": shown_entities,
            "total": entity_total,
            "truncated": (entity_total > shown_entities
                          or bool(snapshot.get("truncated")))},
    }

    # `truncated` верхнего уровня — сводка тех же значений, не отдельное
    # мнение: узлы обрезаны, если это верно хотя бы для одного класса.
    truncated_nodes = any(entry["truncated"] for entry in by_kind.values())
    truncated_edges = bool(recorded_cut or derived_cut
                           or len(edges) > GRAPH_MAX_EDGES
                           or edge_total > len(used_edges))

    if unavailable:
        state = "degraded"
    elif not nodes:
        state = "empty"
    elif truncated_nodes or truncated_edges:
        state = "partial"
    else:
        state = "ok"

    # MEM-08-S2 (§6 C-6): семантические сообщества — ТОЛЬКО активная сборка.
    # Нет таблиц / нет сборки / есть сборка — три разных честных состояния
    # (`memory_search.read_active_communities`), LOD-тайлы сюда не попадают.
    communities_source = "communities"
    if chat is not None:
        try:
            communities = await memory_search.read_active_communities(db, chat)
        except Exception:
            logger.warning("[cognitive_map] сообщества недоступны — degraded",
                           exc_info=True)
            communities = memory_search.community_read_failure()
        if communities.get("reason_code") == \
                memory_search.COMMUNITY_REASON_READ_FAILED:
            sources[communities_source] = "not_loaded"
            if communities_source not in unavailable:
                unavailable.append(communities_source)
                state = "degraded"
        else:
            sources[communities_source] = "loaded"
    else:
        # Глобальная область не имеет единственной сборки: честно сообщаем,
        # что сообщества — per chat, а не показываем чужой/выдуманный список.
        communities = await memory_search.read_active_communities(db, None)
        sources[communities_source] = "loaded"

    return {
        "version": PAYLOAD_VERSION,
        "generated_at": generated_at,
        "state": state,
        "scope": {"mode": "chat" if chat is not None else "global",
                  "chat_id": chat},
        "degraded": {"active": bool(unavailable),
                     "not_loaded": sorted(unavailable)},
        "sources": sources,
        "caps": {"nodes": GRAPH_MAX_NODES, "edges": GRAPH_MAX_EDGES,
                 "per_class": COG_CLASS_LIMIT, "classes": COG_CLASS_COUNT,
                 "entity_nodes": entity_cap},
        "shown_of": {
            "nodes": len(nodes),
            "edges": len(used_edges),
            "by_kind": by_kind,
            "totals": {"nodes": node_total, "edges": edge_total},
            "unresolved_refs": unresolved_refs,
        },
        "truncated": {
            "nodes": truncated_nodes,
            "edges": truncated_edges,
            "by_class": {
                "fact": by_kind["fact"]["truncated"],
                "belief": by_kind["belief"]["truncated"],
                "paradigm": by_kind["paradigm"]["truncated"],
                "evolution": (evolution_cut
                              or by_kind["observation"]["truncated"]
                              or by_kind["evolution_event"]["truncated"]),
                "entity": by_kind["entity"]["truncated"],
            },
        },
        "nodes": nodes,
        "edges": used_edges,
        "communities": communities,
    }


# ── эндпоинт ────────────────────────────────────────────────────────────────

@cognitive_map_router.get("/memory/cognitive-map")
async def memory_cognitive_map(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: Annotated[int | None, Query()] = None,
):
    """Когнитивная карта (W7-S1): типизированные узлы/рёбра из существующих
    источников. RBAC — как у остального Memory-API (только глобальный admin):
    изоляция чатов и глобальная область — параметром ``chat_id``.

    Fail-open по источникам (200 + ``degraded``); нет БД — 503.
    """
    _require_global_admin(request, user)
    db = _db_or_503()
    return await build_cognitive_map(db, chat_id)


@cognitive_map_router.get("/memory/search")
async def memory_search_endpoint(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    q: Annotated[str, Query()] = "",
    chat_id: Annotated[int | None, Query()] = None,
    limit: Annotated[int | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
):
    """Единый поиск по памяти (MEM-08-S2, §4.3/§4.9).

    Один backend-вход на один client input: внутри **только** существующий
    `services.mca_retrieval_context.retrieve` (никакого второго поиска).
    RBAC — как у остального Memory-API; `chat_id` — область, `None` —
    разрешённый администратору набор чатов (`scope_all`).

    Явные исходы (не подменяются друг другом): `forbidden`/`no_rights`,
    `empty`/`no_matches`, `error`/`error`, `cursor_stale` (§4.9) и
    `ok`/`candidates`. Поиск без менеджера памяти — `error`/`error` с
    `reason_code='vector_unavailable'` (гибридная возможность отсутствует,
    поэтому «нет совпадений» не утверждается). Невалидный вход — 400 с
    точным `reason_code`.
    """
    _require_global_admin(request, user)
    db = _db_or_503()
    # MEM-08-S2: гибридный поиск обязан идти с ЖИВЫМ менеджером памяти —
    # он внедряется в приложение при старте (bot.py → create_app(memory=...),
    # app.state.memory), как cache/control. Второй менеджер здесь не
    # создаётся; его отсутствие адаптер честно сообщает в ответе.
    memory = getattr(getattr(request, "app", None), "state", None)
    memory = getattr(memory, "memory", None)
    try:
        response = await memory_search.search_memory(
            db, memory, query=q, chat_id=chat_id, limit=limit, cursor=cursor)
    except memory_search.SearchRequestError as exc:
        raise HTTPException(status_code=400, detail=exc.reason_code) from None
    return response.as_dict()
