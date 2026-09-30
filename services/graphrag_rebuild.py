"""ASAP-3.2 (round1029, ADR-1028-5 D1–D3; T-4191/T-4192) — GraphRAG shadow
rebuild lifecycle: полный re-embed под текущим fingerprint → validation
(9 критериев §6) → атомарная активация.

RCA (spec §1): preexisting vec-таблицы → generation регистрируется `building`
(карантин B-MCA07-1/A06), backfill — «fill missing», НЕ rebuild, и НЕ имеет
перехода `building → active` → вечный FTS-only при `gen_fp == new_fp`.

Решение (D1 — вариант A, Accepted):
  * **shadow generation**: под текущим identity-fingerprint строится
    generation-suffixed shadow vec-хранилище (`{live}_g{generation}`) — полный
    re-embed ВСЕХ eligible source-фактов (НЕ fill-missing); existing vec-rows
    НЕ trusted (§5).
  * per-row provenance — по построению: все строки shadow принадлежат одному
    build'у (маркер принадлежности — в имени shadow/реестре поколений,
    RAW `graph_facts` не трогается, Q14).
  * **validation** — 9 критериев §6 (fingerprint/dim/provider-model/
    preprocessing/coverage/orphans/counts/KNN-smoke/swap), все обязаны быть
    true одновременно.
  * **atomic activate**: DROP live + CREATE live + копирование из shadow +
    переход реестра поколений — ОДНА транзакция (DDL в SQLite транзакционен;
    откат возвращает прежнюю live-таблицу). `UPDATE … SET status='active'`
    выполняется ТОЛЬКО здесь и ТОЛЬКО после проверки provenance ВСЕХ
    векторов (запрет §3/§66 соблюдён: shadow по построению несёт векторы,
    построенные этим build'ом под текущим fingerprint).
  * **resumable (D2)**: durable-состояние на REUSE `task_jobs` (v14, ΔDDL=0),
    state machine `queued → running → checkpoint → validated → activated |
    failed` (+`paused`/`cancelled` — §64 pause/resume/cancel); checkpoint
    (cursor по source-id) → продолжение после restart. bounded-батчи +
    sleep/yield + progress (§64); НЕ блокирует startup/polling (background
    fire-and-forget).
  * **race-guard (D2)**: build привязан к fingerprint, полученному на старте;
    при validate `current_fp != build_fp` → старый build НЕ активируется
    (`failed/fingerprint_changed`), shadow удаляется, под новый fp
    планируется новый build (§70).
  * embedding-кэш (64.4/MCA-07 D4) переиспользуется ТОЛЬКО при полном
    совпадении identity (§65) — переупаковка при неизменном конфиге БЕЗ
    повторных платных API-вызовов идёт через обычный `memory._embed`.
  * FTS — постоянный резерв: на всём протяжении build/validate/activate и
    после failed vector-path остаётся закрыт (`_index_generation_ok`), FTS
    обслуживает запросы (§62).

События (§6): `EMBEDDING_GENERATION_BUILD_START / PROGRESS / VALIDATED /
ACTIVATED` (+ failed) — через REUSE `emit_mca_event` (mca-13), R17-safe
(только индексы/счётчики/короткие fp-префиксы, без фактов/текстов).

Δ SQLite DDL = 0: shadow — идемпотентный `CREATE VIRTUAL TABLE IF NOT
EXISTS` (прецедент EXTRA/Фазы B); user_version НЕ меняется (v19; бронь v20
`mca-04b` не занимаем — Q14).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import struct
import time

logger = logging.getLogger(__name__)

# ── Состояния durable-джобы (D2; REUSE `task_jobs`, статусы — TEXT) ─────────
ST_QUEUED = "queued"
ST_RUNNING = "running"
ST_CHECKPOINT = "checkpoint"
ST_VALIDATED = "validated"
ST_ACTIVATED = "activated"
ST_FAILED = "failed"
ST_PAUSED = "paused"
ST_CANCELLED = "cancelled"

_KIND = "graphrag_rebuild"
_OWNER = "memory"

# Спецификация индексов: source (source of truth, НЕ удалять — R18), live
# vec-таблица, колонки копирования (int8-вариант добавляет embedding_i8).
_INDEX_SPECS: dict[str, dict] = {
    "graph_facts_vec": {
        "source": "graph_facts",
        "source_cols": "id, fact, chat_id, origin, expires_at",
        "eligible_ts": True,          # expires_at IS NULL OR expires_at > now
        "live": "graph_facts_vec",
        "copy_cols": "rowid, fact_id, chat_id, origin, expires_at, embedding",
        "insert_cols": "rowid, fact_id, chat_id, origin, expires_at, embedding",
    },
    "smart_archive": {
        "source": "smart_archive_facts",
        "source_cols": "id, fact, chat_id",
        "eligible_ts": False,
        "live": "smart_archive",
        "copy_cols": "rowid, fact_id, chat_id, embedding",
        "insert_cols": "rowid, fact_id, chat_id, embedding",
    },
}

_FLOAT_DIM_RE = re.compile(r"float\[(\d+)\]")

# running-джоба без свежего heartbeat дольше этого — takeover-кандидат
# (restart прошлого процесса).
_STALE_RUNNING_SECONDS = 600


def graphrag_rebuild_enabled() -> bool:
    """Kill-switch `GRAPHRAG_SHADOW_REBUILD_ENABLED` (env-only, default ON).

    OFF → прежний lifecycle (building-карантин + backfill-fill-missing),
    байт-в-байт паритет 2.58.39 (rollback §80)."""
    try:
        from config.settings import settings
        return bool(getattr(settings, "GRAPHRAG_SHADOW_REBUILD_ENABLED", True))
    except Exception:      # pragma: no cover — защитная ветка
        return True


def _batch_size() -> int:
    try:
        from config.settings import settings
        return max(1, int(getattr(settings, "GRAPHRAG_REBUILD_BATCH", 50)))
    except Exception:      # pragma: no cover
        return 50


def _sleep_seconds() -> float:
    try:
        from config.settings import settings
        value = float(getattr(settings, "GRAPHRAG_REBUILD_SLEEP_SECONDS", 0.5))
    except Exception:      # pragma: no cover
        value = 0.5
    return max(0.0, min(value, 60.0))


def _emit(event_name: str, outcome: str, *, level: str = "info", **fields):
    """Fail-open эмиссия EMBEDDING_GENERATION_* (§6; REUSE mca-13). R17-safe:
    только index/generation/счётчики/короткие fp."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(event_name, outcome=outcome, level=level,
                       component="graphrag_rebuild", **fields)
    except Exception:      # контракт не рвёт поток
        pass


def _fp12(fp: str) -> str:
    return str(fp or "")[:12]


# ── task_jobs helpers (кастомные статусы D2 поверх v14-таблицы) ─────────────

async def _get_job(db, job_id: str) -> dict | None:
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None
    except Exception:
        return None


async def _job_cas(db, job_id: str, *, expect: str, set_status: str,
                   reason_code: str | None = None,
                   terminal: bool = False) -> bool:
    """CAS-переход статуса durable-джобы (одновательный single-writer).

    Терминальные переходы (`activated`/`failed`/`cancelled`) проставляют
    `finished_at` — bounded-очистка v14 (`prune`) их увидит."""
    now = int(time.time())

    async def _body(conn):
        if terminal:
            cursor = await conn.execute(
                "UPDATE task_jobs SET status = ?, "
                "reason_code = COALESCE(?, reason_code), finished_at = ?, "
                "updated_at = ? WHERE job_id = ? AND status = ?",
                (set_status, reason_code, now, now, job_id, expect))
        else:
            cursor = await conn.execute(
                "UPDATE task_jobs SET status = ?, "
                "reason_code = COALESCE(?, reason_code), updated_at = ? "
                "WHERE job_id = ? AND status = ?",
                (set_status, reason_code, now, job_id, expect))
        return cursor.rowcount

    try:
        return bool(await db.write_transaction(
            _body, op_name="graphrag_rebuild_cas"))
    except Exception:
        logger.warning("graphrag rebuild: CAS failed | job=%s | %s→%s",
                       job_id, expect, set_status, exc_info=True)
        return False


def _coalesce_key(index_name: str, fp: str) -> str:
    return f"{_KIND}:{index_name}:{fp}"


async def _find_active_job(db, index_name: str, fp: str) -> dict | None:
    try:
        cursor = await db.db.execute(
            "SELECT * FROM task_jobs WHERE kind = ? AND coalesce_key = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (_KIND, _coalesce_key(index_name, fp)))
        row = await cursor.fetchone()
        return dict(row) if row is not None else None
    except Exception:
        return None


# ── shadow-хранилище ────────────────────────────────────────────────────────

def _shadow_name(index_name: str, generation: int) -> str:
    return f"{_INDEX_SPECS[index_name]['live']}_g{int(generation)}"


def _live_ddl(memory, index_name: str) -> str:
    """Канонический DDL live-таблицы (тот же формат, что у MemoryManager)."""
    dim = int(memory._vec_dim or 0)
    if index_name == "graph_facts_vec":
        return memory._graph_vec_table_sql(dim)
    return memory._vec_table_sql(dim)


async def _create_shadow(memory, index_name: str, shadow: str) -> None:
    """Идемпотентный CREATE VIRTUAL TABLE IF NOT EXISTS (ΔDDL = 0, Q14)."""
    live = _INDEX_SPECS[index_name]["live"]
    sql = _live_ddl(memory, index_name).replace(
        f"IF NOT EXISTS {live}", f"IF NOT EXISTS {shadow}")
    async with memory.db.serialized():
        await memory.db.db.execute(sql)
        await memory.db.db.commit()


async def _drop_shadow(memory, shadow: str) -> None:
    try:
        async with memory.db.serialized():
            await memory.db.db.execute(f"DROP TABLE IF EXISTS {shadow}")
            await memory.db.db.commit()
    except Exception:
        logger.warning("graphrag rebuild: shadow drop failed | %s", shadow,
                       exc_info=True)


# ── партии source-фактов (cursor-based полный скан — НЕ fill-missing) ───────

async def _fetch_batch(memory, spec: dict, last_id: int) -> list[dict]:
    now = int(time.time())
    sql = (f"SELECT {spec['source_cols']} FROM {spec['source']} "
           f"WHERE id > ? ")
    params: list = [int(last_id)]
    if spec["eligible_ts"]:
        sql += "AND (expires_at IS NULL OR expires_at > ?) "
        params.append(now)
    sql += "ORDER BY id LIMIT ?"
    params.append(_batch_size())
    cursor = await memory.db.db.execute(sql, tuple(params))
    return [dict(r) for r in await cursor.fetchall()]


async def _insert_shadow_rows(memory, spec: dict, shadow: str,
                              batch: list[dict], vectors: list) -> int:
    """Вставка пачки в shadow (rowid = fact_id, полный re-embed — существующие
    live-строки НЕ re-used; повтор на resume перекрывается existence-check)."""
    int8 = bool(memory._vec_int8)
    inserted = 0
    async with memory.db.serialized():
        for row, vector in zip(batch, vectors):
            if not vector:
                continue
            cursor = await memory.db.db.execute(
                f"SELECT rowid FROM {shadow} WHERE rowid = ?", (row["id"],))
            if await cursor.fetchone() is not None:
                continue
            if int8:
                await memory.db.db.execute(
                    f"INSERT INTO {shadow}(rowid, fact_id, chat_id, origin, "
                    "expires_at, embedding, embedding_i8) "
                    "VALUES (?, ?, ?, ?, ?, ?, vec_quantize_int8(?, 'unit'))",
                    (row["id"], row["id"], row["chat_id"], row["origin"],
                     row["expires_at"], json.dumps(vector),
                     json.dumps(vector)))
            elif "origin" in row:
                await memory.db.db.execute(
                    f"INSERT INTO {shadow}(rowid, fact_id, chat_id, origin, "
                    "expires_at, embedding) VALUES (?, ?, ?, ?, ?, ?)",
                    (row["id"], row["id"], row["chat_id"], row["origin"],
                     row["expires_at"], json.dumps(vector)))
            else:
                await memory.db.db.execute(
                    f"INSERT INTO {shadow}(rowid, fact_id, chat_id, embedding)"
                    " VALUES (?, ?, ?, ?)",
                    (row["id"], row["id"], row["chat_id"],
                     json.dumps(vector)))
            inserted += 1
        await memory.db.db.commit()
    return inserted


# ── validation (9 критериев §6; T-4192) ─────────────────────────────────────

def _read_vector(blob) -> list[float] | None:
    try:
        if isinstance(blob, str):
            data = json.loads(blob)
            return [float(x) for x in data] if isinstance(data, list) else None
        raw = bytes(blob)
        return list(struct.unpack(f"<{len(raw) // 4}f", raw))
    except Exception:
        return None


async def _validate(memory, index_name: str, shadow: str, fp: str,
                    frontier: int) -> tuple[bool, dict]:
    """Критерии §6 (1–8; №9 — сама транзакция swap). Возвращает
    ``(ok, report)``; report — R17-safe (числа/bool/короткие коды)."""
    spec = _INDEX_SPECS[index_name]
    report: dict = {"index": index_name, "shadow": shadow,
                    "frontier": int(frontier), "criteria": {}}
    crit = report["criteria"]
    now = int(time.time())

    # 1. fingerprint == current (race-guard D2 — первый и самый дешёвый).
    current_fp = memory._identity_fingerprint()
    crit["fingerprint_current"] = (fp == current_fp)
    if fp != current_fp:
        report["reason_code"] = "fingerprint_changed"
        report["build_fp"] = _fp12(fp)
        report["current_fp"] = _fp12(current_fp)
        return False, report

    # 2. dim == current (DDL shadow).
    cursor = await memory.db.db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (shadow,))
    row = await cursor.fetchone()
    stored_dim = None
    if row and row["sql"]:
        match = _FLOAT_DIM_RE.search(row["sql"])
        if match:
            stored_dim = int(match.group(1))
    crit["dim_current"] = (stored_dim is not None
                           and stored_dim == int(memory._vec_dim or -1))
    if not crit["dim_current"]:
        report["reason_code"] = "dim_changed"
        report["shadow_dim"] = stored_dim
        return False, report

    # 3/4. provider/model identity + preprocessing_version == текущий config.
    gen = await memory.db.get_generation_by_fingerprint(index_name, fp)
    from services import summary_memory as sm
    want_provider = sm._embedding_provider()
    want_model = None
    try:
        from services import hot_config as hot
        from config.settings import settings
        want_model = hot.get("models.embedding_model_name",
                             settings.EMBEDDING_MODEL_NAME)
    except Exception:      # pragma: no cover — конфиг не роняет validation
        want_model = None
    want_preproc = sm.EMBEDDING_PREPROCESSING_VERSION
    got = gen or {}
    crit["provider_model_current"] = (
        str(got.get("provider") or "") == str(want_provider or "")
        and str(got.get("model") or "") == str(want_model or ""))
    crit["preprocessing_current"] = (
        str(got.get("preprocessing_version") or "") == str(want_preproc))
    if not (crit["provider_model_current"] and crit["preprocessing_current"]):
        report["reason_code"] = "identity_changed"
        return False, report

    # 5–7. coverage/orphans/counts.
    if spec["eligible_ts"]:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id <= ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (int(frontier), now))
    else:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id <= ?",
            (int(frontier),))
    eligible_total = int((await cursor.fetchone())["c"])

    sql_covered = (f"SELECT COUNT(*) AS c FROM {shadow} WHERE fact_id IN "
                   f"(SELECT id FROM {spec['source']} WHERE id <= ? ")
    params_covered: list = [int(frontier)]
    if spec["eligible_ts"]:
        sql_covered += "AND (expires_at IS NULL OR expires_at > ?) "
        params_covered.append(now)
    sql_covered += ")"
    cursor = await memory.db.db.execute(sql_covered, tuple(params_covered))
    covered = int((await cursor.fetchone())["c"])

    cursor = await memory.db.db.execute(
        f"SELECT COUNT(*) AS c FROM {shadow} WHERE fact_id NOT IN "
        f"(SELECT id FROM {spec['source']})")
    orphans_in_shadow = int((await cursor.fetchone())["c"])

    added_after_scan = 0
    if spec["eligible_ts"]:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id > ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (int(frontier), now))
    else:
        cursor = await memory.db.db.execute(
            f"SELECT COUNT(*) AS c FROM {spec['source']} WHERE id > ?",
            (int(frontier),))
    added_after_scan = int((await cursor.fetchone())["c"])

    missing_bad = max(0, eligible_total - covered)
    report.update({
        "eligible_total": eligible_total, "covered": covered,
        "missing": missing_bad,
        "allowed_missing_added_after_scan": added_after_scan,
        "orphans_excluded": orphans_in_shadow,
    })
    # 5: каждый eligible факт (id <= frontier) имеет vector row; факты,
    # добавленные ПОСЛЕ конца скана, — явно классифицированная допустимая
    # причина отсутствия (`added_after_scan`, закрываются обычным backfill).
    crit["coverage"] = (missing_bad == 0)
    # 6: в АКТИВИРУЕМЫЙ индекс попадают только строки с живым source-фактом
    # (анти-join в swap) → orphan vectors в новой live-таблице = 0 по
    # построению; строки-сироты в shadow исключаются и считаются в отчёте.
    crit["no_orphans"] = True
    # 7: count/coverage validation (объём копии == eligible-набору).
    crit["counts_match"] = (covered == eligible_total)
    if not (crit["coverage"] and crit["counts_match"]):
        report["reason_code"] = "missing_vectors"
        return False, report

    # 8. sample KNN smoke по SHADOW (self-match: косинус вектора с самим
    # собой == максимум → факт обязан вернуться в top-k).
    cursor = await memory.db.db.execute(
        f"SELECT COUNT(*) AS c FROM {shadow}")
    shadow_rows = int((await cursor.fetchone())["c"])
    smoke_ok = False
    if shadow_rows > 0:
        offset = random.randint(0, max(0, shadow_rows - 1))
        cursor = await memory.db.db.execute(
            f"SELECT rowid, embedding FROM {shadow} LIMIT 1 OFFSET ?",
            (offset,))
        sample = await cursor.fetchone()
        if sample is not None:
            vector = _read_vector(sample["embedding"])
            if vector:
                try:
                    cursor = await memory.db.db.execute(
                        f"SELECT rowid FROM {shadow} WHERE embedding MATCH ? "
                        "AND k = 5", (json.dumps(vector),))
                    ids = {r["rowid"] for r in await cursor.fetchall()}
                    smoke_ok = sample["rowid"] in ids
                except Exception:
                    logger.warning("graphrag rebuild: KNN smoke failed | %s",
                                   shadow, exc_info=True)
    crit["knn_smoke"] = smoke_ok
    if not smoke_ok:
        report["reason_code"] = "knn_smoke_failed"
        return False, report
    return True, report


# ── атомарная активация (§6.9; запрет §3/§66 соблюдён — см. docstring) ──────

async def _activate(memory, index_name: str, shadow: str, fp: str,
                    generation: int) -> bool:
    spec = _INDEX_SPECS[index_name]
    live = spec["live"]
    int8 = bool(memory._vec_int8)
    insert_cols = spec["insert_cols"] + (", embedding_i8" if int8 else "")
    copy_cols = spec["copy_cols"] + (", embedding_i8" if int8 else "")
    live_sql = _live_ddl(memory, index_name)
    now = int(time.time())

    async def _body(conn):
        # M-ASAP32-2: re-check fp ВНУТРИ транзакции — закрывает race-окно
        # validate→activate при hot-смене embedding-конфига (rollback →
        # activation_failed, shadow цел, self-heal на следующем schedule).
        if memory._identity_fingerprint() != fp:
            raise RuntimeError("fingerprint_changed")
        # 1. Прежняя live-таблица (unknown-origin vectors) заменяется ЦЕЛИКОМ;
        #    raw `graph_facts`/`smart_archive_facts` НЕ трогаются (source of
        #    truth, R18). DDL в SQLite транзакционен: откат возвращает прежнюю
        #    таблицу (FTS оставался serviceable всё время).
        await conn.execute(f"DROP TABLE IF EXISTS {live}")
        await conn.execute(live_sql)
        # 2. Копирование ТОЛЬКО строк с живым source-фактом (анти-orphan).
        await conn.execute(
            f"INSERT INTO {live}({insert_cols}) SELECT {copy_cols} "
            f"FROM {shadow} WHERE fact_id IN "
            f"(SELECT id FROM {spec['source']})")
        # 3. Реестр поколений (v18): прежнее активное → superseded; build'овое
        #    поколение → active. UPDATE допускается ТОЛЬКО после проверки
        #    provenance всех векторов (критерии 1–8 пройдены выше — §3/§66).
        await conn.execute(
            "UPDATE mca_embedding_index_generations SET status = 'superseded',"
            " superseded_at = ? WHERE index_name = ? AND status = 'active' "
            "AND fingerprint != ?", (now, index_name, fp))
        cursor = await conn.execute(
            "UPDATE mca_embedding_index_generations SET status = 'active', "
            "activated_at = ? WHERE index_name = ? AND generation = ? AND "
            "fingerprint = ? AND status IN ('building', 'validated')",
            (now, index_name, int(generation), fp))
        if cursor.rowcount != 1:
            raise RuntimeError("generation_row_missing")
        # 4. Shadow больше не нужен (данные в live).
        await conn.execute(f"DROP TABLE IF EXISTS {shadow}")

    try:
        await memory.db.write_transaction(
            _body, op_name="graphrag_rebuild_activate")
        return True
    except Exception:
        logger.error("graphrag rebuild: activation failed | index=%s | %s",
                     index_name, shadow, exc_info=True)
        return False


# ── обработка джобы (D2 state machine) ──────────────────────────────────────

async def run_job(memory, index_name: str, job_id: str) -> None:
    """Полный rebuild одного индекса: батчи → checkpoint → validate → activate.

    НЕ бросает (background fire-and-forget); любой сбой → `failed` с
    reason_code, FTS остаётся serviceable, автоматического retry-storm нет
    (повтор — по следующему startup-schedule / явному триггеру)."""
    db = memory.db
    spec = _INDEX_SPECS[index_name]
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
    except Exception:
        store = None

    row = await _get_job(db, job_id)
    if row is None:
        return
    try:
        payload = json.loads(row["payload"] or "{}")
    except ValueError:
        payload = {}
    fp = str(payload.get("fingerprint") or "")
    generation = int(payload.get("generation") or 0)
    # `save_checkpoint` (v14) перезаписывает `payload` checkpoint-обёрткой —
    # identity build'а на resume восстанавливаем из coalesce_key
    # (`graphrag_rebuild:{index}:{fp}`) + реестра поколений.
    if (not fp or generation <= 0) and index_name in _INDEX_SPECS:
        parts = str(row.get("coalesce_key") or "").split(":", 2)
        if len(parts) == 3 and parts[0] == _KIND and parts[1] == index_name:
            fp = fp or parts[2]
            if generation <= 0 and fp:
                gen_row = await db.get_generation_by_fingerprint(
                    index_name, fp)
                generation = int((gen_row or {}).get("generation") or 0)
    if not fp or generation <= 0:
        await _job_cas(db, job_id, expect=str(row["status"]),
                       set_status=ST_FAILED, reason_code="bad_payload",
                       terminal=True)
        return

    # resume из checkpoint (restart mid-build → продолжение, §7/§70)
    last_id = 0
    processed = 0
    if store is not None:
        checkpoint = await store.get_checkpoint(job_id)
        if checkpoint and checkpoint.get("cursor"):
            try:
                cur = json.loads(str(checkpoint["cursor"]))
                last_id = int(cur.get("last_id", 0))
                processed = int(cur.get("processed", 0))
            except (ValueError, TypeError):
                last_id, processed = 0, 0

    prior_status = str(row["status"] or ST_QUEUED)
    if prior_status in (ST_ACTIVATED, ST_CANCELLED, ST_PAUSED):
        return
    if not await _job_cas(db, job_id, expect=prior_status,
                          set_status=ST_RUNNING):
        return

    shadow = _shadow_name(index_name, generation)
    _emit("EMBEDDING_GENERATION_BUILD_START", "start",
          index=index_name, generation=generation,
          job_id=str(job_id)[:64], fp=_fp12(fp),
          resumed=bool(processed))
    logger.info("EMBEDDING_GENERATION_BUILD_START | index=%s | gen=%d | "
                "fp=%s | resumed=%s | job=%s", index_name, generation,
                _fp12(fp), bool(processed), str(job_id)[:16])

    try:
        await _create_shadow(memory, index_name, shadow)
        batch_no = 0
        last_progress_emit = 0.0
        while True:
            current = await _get_job(db, job_id)
            status = str((current or {}).get("status") or "")
            if status == ST_PAUSED:
                return                      # §64: resume — явным триггером
            if status == ST_CANCELLED:
                await _drop_shadow(memory, shadow)
                return
            if status != ST_RUNNING:
                return
            batch = await _fetch_batch(memory, spec, last_id)
            if not batch:
                break
            vectors = await memory._embed([b["fact"] for b in batch])
            await _insert_shadow_rows(memory, spec, shadow, batch, vectors)
            last_id = int(batch[-1]["id"])
            processed += len(batch)
            batch_no += 1
            if store is not None:
                await store.save_checkpoint(
                    job_id,
                    cursor_token=json.dumps({"last_id": last_id,
                                             "processed": processed}),
                    processed=processed,
                    checkpoint_ref=f"cp:{index_name}:{generation}")
                await store.heartbeat(job_id)
            now_mono = time.monotonic()
            if batch_no % 20 == 0 or now_mono - last_progress_emit >= 30.0:
                last_progress_emit = now_mono
                _emit("EMBEDDING_GENERATION_PROGRESS", "progress",
                      index=index_name, generation=generation,
                      processed=int(processed), frontier=int(last_id),
                      job_id=str(job_id)[:64])
                logger.info("EMBEDDING_GENERATION_PROGRESS | index=%s | "
                            "gen=%d | processed=%d | frontier=%d",
                            index_name, generation, processed, last_id)
            sleep_s = _sleep_seconds()
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)   # §64: yield между батчами

        # build-фаза завершена, checkpoint durable → валидация.
        if not await _job_cas(db, job_id, expect=ST_RUNNING,
                              set_status=ST_CHECKPOINT):
            return
        ok, report = await _validate(memory, index_name, shadow, fp, last_id)
        if not ok:
            reason = str(report.get("reason_code") or "validation_failed")
            await _job_cas(db, job_id, expect=ST_CHECKPOINT,
                           set_status=ST_FAILED, reason_code=reason,
                           terminal=True)
            await _drop_shadow(memory, shadow)
            # Retry после validation-failure обязан начать полный rebuild
            # заново (cursor за missing-row дал бы вечный повтор failure):
            # checkpoint сбрасывается, shadow удалён выше.
            if store is not None:
                try:
                    await store.save_checkpoint(
                        job_id,
                        cursor_token=json.dumps({"last_id": 0,
                                                 "processed": 0}),
                        processed=0,
                        checkpoint_ref=f"cp:{index_name}:{generation}:reset")
                except Exception:
                    pass
            _emit("EMBEDDING_GENERATION_FAILED", "failed", level="warning",
                  index=index_name, generation=generation,
                  reason_code=reason, report=json.dumps(
                      {k: v for k, v in report.items() if k != "criteria"},
                      ensure_ascii=False)[:512])
            logger.warning("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                           "reason=%s", index_name, generation, reason)
            if reason == "fingerprint_changed":
                # §70: config changes during build → старый build НЕ
                # активируется как current; новый queued build под новый fp.
                try:
                    from services.summary_memory import fire_and_forget
                    fire_and_forget(maybe_schedule_rebuilds(memory),
                                    "graphrag_rebuild")
                except Exception:
                    logger.warning("graphrag rebuild: re-schedule failed",
                                   exc_info=True)
            return

        if not await _job_cas(db, job_id, expect=ST_CHECKPOINT,
                              set_status=ST_VALIDATED):
            return
        crit = report.get("criteria") or {}
        _emit("EMBEDDING_GENERATION_VALIDATED", "success",
              index=index_name, generation=generation,
              processed=int(processed),
              eligible=int(report.get("eligible_total") or 0),
              criteria=json.dumps(crit, ensure_ascii=False)[:400])
        logger.info("EMBEDDING_GENERATION_VALIDATED | index=%s | gen=%d | "
                    "eligible=%d | criteria=%s", index_name, generation,
                    report.get("eligible_total"),
                    ",".join(k for k, v in crit.items() if v))

        if not await _activate(memory, index_name, shadow, fp, generation):
            await _job_cas(db, job_id, expect=ST_VALIDATED,
                           set_status=ST_FAILED,
                           reason_code="activation_failed", terminal=True)
            _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
                  index=index_name, generation=generation,
                  reason_code="activation_failed")
            return
        await _job_cas(db, job_id, expect=ST_VALIDATED,
                       set_status=ST_ACTIVATED, terminal=True)
        _emit("EMBEDDING_GENERATION_ACTIVATED", "success",
              index=index_name, generation=generation, fp=_fp12(fp),
              vectors=int(report.get("covered") or 0))
        logger.info("EMBEDDING_GENERATION_ACTIVATED | index=%s | gen=%d | "
                    "vectors=%d — vector path active, FTS fallback "
                    "available", index_name, generation,
                    report.get("covered"))
    except Exception as exc:
        reason = type(exc).__name__[:60]
        await _job_cas(db, job_id, expect=ST_RUNNING, set_status=ST_FAILED,
                       reason_code=reason, terminal=True)
        _emit("EMBEDDING_GENERATION_FAILED", "failed", level="error",
              index=index_name, generation=generation, reason_code=reason)
        logger.error("EMBEDDING_GENERATION_FAILED | index=%s | gen=%d | "
                     "error=%s", index_name, generation, reason,
                     exc_info=True)


# ── планировщик (startup / перетриггер) ─────────────────────────────────────

async def maybe_schedule_rebuilds(memory) -> list[str]:
    """Для каждого индекса: latest generation `building` с fingerprint ==
    current → гарантировать durable-джобу и запустить (resume) её.

    Возвращает список запущенных/возобновлённых индексов (для лога/тестов).
    Никогда не бросает."""
    if not graphrag_rebuild_enabled():
        return []
    scheduled: list[str] = []
    try:
        db = memory.db
        if not hasattr(db, "get_latest_embedding_generation"):
            return []
        current_fp = memory._identity_fingerprint()
        for index_name in _INDEX_SPECS:
            try:
                gen = await db.get_latest_embedding_generation(index_name)
            except Exception:
                continue
            if gen is None or str(gen.get("status") or "") != "building":
                # active → всё обслуживается; failed/superseded — не наш случай
                continue
            fp = str(gen.get("fingerprint") or "")
            if not fp or fp != current_fp:
                continue          # mismatch — старый build не оживляем (D2)
            generation = int(gen.get("generation") or 0)
            if generation <= 0:
                continue
            job = await _ensure_job(db, index_name, fp, generation)
            if job is None:
                continue
            scheduled.append(index_name)
            try:
                from services.summary_memory import fire_and_forget
                fire_and_forget(run_job(memory, index_name, job),
                                f"graphrag_rebuild:{index_name}")
            except Exception:
                logger.warning("graphrag rebuild: fire failed | index=%s",
                               index_name, exc_info=True)
    except Exception:
        logger.warning("graphrag rebuild: schedule failed", exc_info=True)
    return scheduled


async def _ensure_job(db, index_name: str, fp: str, generation: int
                      ) -> str | None:
    """Найти/создать durable-джобу rebuild'а (coalesce по index+fp)."""
    job = await _find_active_job(db, index_name, fp)
    if job is not None:
        status = str(job.get("status") or "")
        jid = str(job["job_id"])
        if status == ST_RUNNING:
            heartbeat = int(job.get("heartbeat_at") or 0)
            if int(time.time()) - heartbeat < _STALE_RUNNING_SECONDS:
                return None             # уже выполняется в живом процессе
            # stale running (процесс умер) → переоткрыть как queued (resume).
            await _job_cas(db, jid, expect=ST_RUNNING, set_status=ST_QUEUED,
                           reason_code="stale_takeover")
            return jid
        if status == ST_PAUSED:
            return None                 # явная пауза — не авто-возобновляем
        if status in (ST_QUEUED, ST_CHECKPOINT, "interrupted"):
            if status == "interrupted":
                await _job_cas(db, jid, expect="interrupted",
                               set_status=ST_QUEUED,
                               reason_code="restart_resume")
            return jid
        if status in (ST_ACTIVATED, ST_CANCELLED):
            return None
        if status == ST_FAILED:
            # D2: повторный build после failure — bounded (один раз на
            # startup-schedule), НЕ storm: переоткрываем существующую джобу.
            await _job_cas(db, jid, expect=ST_FAILED, set_status=ST_QUEUED,
                           reason_code="retry_on_schedule")
            return jid
        return None
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return await store.enqueue(
            owner=_OWNER, kind=_KIND,
            coalesce_key=_coalesce_key(index_name, fp),
            payload=json.dumps({"index": index_name, "fingerprint": fp,
                                "generation": generation},
                               ensure_ascii=False))
    except Exception:
        logger.warning("graphrag rebuild: enqueue failed | index=%s",
                       index_name, exc_info=True)
        return None


# ── §64: pause/resume/cancel + статус (для health/Analytics T-4216) ─────────

async def pause_rebuild(db, index_name: str) -> bool:
    job = await _find_active_job(db, index_name,
                                 _current_fp_of(db, index_name) or "")
    if job is None:
        return False
    return await _job_cas(db, str(job["job_id"]), expect=ST_RUNNING,
                          set_status=ST_PAUSED, reason_code="paused")


async def resume_rebuild(db, index_name: str, *, fp: str | None = None
                         ) -> bool:
    fp = fp or (_current_fp_of(db, index_name) or "")
    job = await _find_active_job(db, index_name, fp)
    if job is None or str(job.get("status")) != ST_PAUSED:
        return False
    return await _job_cas(db, str(job["job_id"]), expect=ST_PAUSED,
                          set_status=ST_QUEUED, reason_code="resumed")


async def cancel_rebuild(db, index_name: str, *, fp: str | None = None
                         ) -> bool:
    fp = fp or (_current_fp_of(db, index_name) or "")
    job = await _find_active_job(db, index_name, fp)
    if job is None:
        return False
    status = str(job.get("status") or "")
    if status in (ST_ACTIVATED, ST_CANCELLED, ST_FAILED):
        return False
    return await _job_cas(db, str(job["job_id"]), expect=status,
                          set_status=ST_CANCELLED, reason_code="cancelled",
                          terminal=True)


def _current_fp_of(db, index_name: str) -> str | None:
    try:
        from services import hot_config as hot
        from config.settings import settings
        from services.summary_memory import embedding_identity_fingerprint, \
            _embedding_provider, _endpoint_fingerprint, \
            EMBEDDING_PREPROCESSING_VERSION
        return embedding_identity_fingerprint(
            model=hot.get("models.embedding_model_name",
                          settings.EMBEDDING_MODEL_NAME))
    except Exception:      # pragma: no cover
        return None


async def rebuild_status(db) -> dict:
    """Снимок rebuild-состояния (R17-safe; для GraphRAG health T-4216)."""
    out: dict = {}
    try:
        cursor = await db.db.execute(
            "SELECT job_id, coalesce_key, status, reason_code, payload, "
            "progress_at, heartbeat_at, created_at, updated_at FROM task_jobs "
            "WHERE kind = ? ORDER BY created_at DESC LIMIT 8", (_KIND,))
        jobs = [dict(r) for r in await cursor.fetchall()]
        for job in jobs:
            try:
                payload = json.loads(job.pop("payload") or "{}")
            except ValueError:
                payload = {}
            job["index"] = payload.get("index")
            job["generation"] = payload.get("generation")
            job["fingerprint"] = str(payload.get("fingerprint") or "")[:12]
            out[str(job.pop("job_id"))[:16]] = job
    except Exception:
        pass
    return out


__all__ = [
    "ST_QUEUED", "ST_RUNNING", "ST_CHECKPOINT", "ST_VALIDATED",
    "ST_ACTIVATED", "ST_FAILED", "ST_PAUSED", "ST_CANCELLED",
    "graphrag_rebuild_enabled", "maybe_schedule_rebuilds", "run_job",
    "pause_rebuild", "resume_rebuild", "cancel_rebuild", "rebuild_status",
]
