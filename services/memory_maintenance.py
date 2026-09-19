"""Epic 60 Фаза D (Section 66.2/66.11, T-480/T-489) — MemoryMaintenanceService.

Два фоновых джоба на ОДНОМ APScheduler (MemoryJobStore, max_instances=1,
coalesce — анти-рейс, прецедент summary_scheduler):

1. merge — слияние повторяющихся эпизодов в общие факты (66.2): KNN-кластеры
   (или точный subject+predicate при FTS-фолбеке) → LLM-слияние (COMPRESS_PROMPT,
   канон-сосед R11 — НОВЫЙ промпт НЕ вводим) → проверка «ничего не потерялось»
   (покрытие уникальных токенов ≥60%) → INSERT слитого + DELETE исходных +
   журнал graph_fact_compressions (reason='episode_merge').
   Защищённые факты (65.10) в кластеры не попадают.

2. review — периодический пересмотр (66.11): склейка точных дублей (keep самый
   тяжёлый) и vec-кластеров ≥0.95, глобальный выброс истёкших, выброс
   unconfirmed старше GRAPH_UNCONFIRMED_RETENTION_DAYS, усечение лога сжатий.
"""
import asyncio
import datetime
import json
import logging
import os
import time
from pathlib import Path

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
from services import hot_config as hot
from services import retention_policy
from services.graph_stoplist import METAFACT_PENALTY_IMPORTANCE
from services.llm_client import LLMError
from services.summary_memory import _TOKEN_RE
from services.summary_prompts import COMPRESS_PROMPT

logger = logging.getLogger(__name__)

_MERGE_COVERAGE_MIN = 0.6      # 66.2: доля уникальных токенов слитого от исходных
_MERGE_CLUSTER_SIM = 0.85      # 66.2: кластер-порог KNN-сходства (эпизоды одной темы)
_MERGE_KNN_K = 5               # соседей на кластеризацию
_REVIEW_VEC_BATCH = 100        # потолок фактов чата на vec-склейку (66.11)
_REVIEW_GLUE_SIM = 0.95        # 66.11: vec-кластеры ≥0.95 → склейка


class MemoryMaintenanceService:
    """Фоновое обслуживание памяти: слияние эпизодов (66.2) + пересмотр (66.11)."""

    JOB_MERGE_ID = "graph_episode_merge"
    JOB_REVIEW_ID = "graph_review"
    JOB_WAL_ID = "db_wal_checkpoint"   # Epic 64: удержание -wal от разрастания

    def __init__(self, db, memory, llm) -> None:
        self.db = db
        self.memory = memory
        self.llm = llm
        self._scheduler = AsyncIOScheduler(timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE))

    def start(self) -> None:
        if hot.get("flags.graph_episode_merge_enabled", settings.GRAPH_EPISODE_MERGE_ENABLED):
            self._scheduler.add_job(
                self._tick_merge,
                IntervalTrigger(
                    days=hot.get("limits.graph_episode_merge_interval_days", settings.GRAPH_EPISODE_MERGE_INTERVAL_DAYS),
                    timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)),
                id=self.JOB_MERGE_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        if hot.get("flags.graph_review_enabled", settings.GRAPH_REVIEW_ENABLED):
            self._scheduler.add_job(
                self._tick_review,
                IntervalTrigger(
                    days=hot.get("limits.graph_review_interval_days", settings.GRAPH_REVIEW_INTERVAL_DAYS),
                    timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)),
                id=self.JOB_REVIEW_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        # Epic 64: периодический WAL-checkpoint(TRUNCATE) — без него -wal
        # разрастался (наблюдалось 18 МБ при БД 43 МБ).
        if hot.get("flags.db_wal_checkpoint_enabled", settings.DB_WAL_CHECKPOINT_ENABLED):
            self._scheduler.add_job(
                self._tick_wal_checkpoint,
                IntervalTrigger(
                    hours=hot.get("limits.db_wal_checkpoint_hours", settings.DB_WAL_CHECKPOINT_HOURS),
                    timezone=hot.get("limits.summary_timezone", settings.SUMMARY_TIMEZONE)),
                id=self.JOB_WAL_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        if (hot.get("flags.graph_episode_merge_enabled", settings.GRAPH_EPISODE_MERGE_ENABLED) or hot.get("flags.graph_review_enabled", settings.GRAPH_REVIEW_ENABLED)
                or hot.get("flags.db_wal_checkpoint_enabled", settings.DB_WAL_CHECKPOINT_ENABLED)):
            self._scheduler.start()
            logger.info(
                "MemoryMaintenance started (merge=%s/%dd, review=%s/%dd, wal=%s/%dh)",
                hot.get("flags.graph_episode_merge_enabled", settings.GRAPH_EPISODE_MERGE_ENABLED),
                hot.get("limits.graph_episode_merge_interval_days", settings.GRAPH_EPISODE_MERGE_INTERVAL_DAYS),
                hot.get("flags.graph_review_enabled", settings.GRAPH_REVIEW_ENABLED),
                hot.get("limits.graph_review_interval_days", settings.GRAPH_REVIEW_INTERVAL_DAYS),
                hot.get("flags.db_wal_checkpoint_enabled", settings.DB_WAL_CHECKPOINT_ENABLED),
                hot.get("limits.db_wal_checkpoint_hours", settings.DB_WAL_CHECKPOINT_HOURS))
        else:
            logger.info("MemoryMaintenance disabled (all jobs off)")

    async def _tick_wal_checkpoint(self) -> None:
        """Epic 64: PRAGMA wal_checkpoint(TRUNCATE) — сброс -wal в основной файл."""
        try:
            cursor = await self.db.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            row = await cursor.fetchone()
            await self.db.db.commit()
            logger.info("WAL checkpoint done | busy=%s log_pages=%s checkpointed=%s",
                        row[0] if row else "?", row[1] if row else "?",
                        row[2] if row else "?")
        except Exception:
            logger.warning("WAL checkpoint failed", exc_info=True)

    async def _tick_merge(self) -> None:
        try:
            await self.merge_episodes()
        except LLMError as exc:
            # 66.2: LLMError → пропуск прогона (следующий цикл через N дней).
            logger.warning("episode merge: LLM failed — run skipped | error=%s", exc)
        except Exception:
            logger.warning("episode merge: failed", exc_info=True)

    async def _tick_review(self) -> None:
        try:
            await self.review()
        except Exception:
            logger.warning("graph review: failed", exc_info=True)

    # ── 66.2 (T-480): слияние повторяющихся эпизодов ──────────────

    async def merge_episodes(self) -> int:
        """Слияние по всем чатам; потолок GRAPH_EPISODE_MERGE_BATCH кластеров
        за прогон. Возвращает число слитых кластеров."""
        budget = hot.get("limits.graph_episode_merge_batch", settings.GRAPH_EPISODE_MERGE_BATCH)
        merged_total = 0
        for chat_id in await self.db.get_graph_chat_ids():
            if budget <= 0:
                break
            merged = await self._merge_chat(chat_id, budget)
            budget -= merged
            merged_total += merged
        if merged_total:
            logger.info("episode merge: merged=%d clusters", merged_total)
        return merged_total

    async def _merge_chat(self, chat_id: int, budget: int) -> int:
        now = int(time.time())
        rows = await self.db.get_live_graph_facts(chat_id, now)
        rows = [
            row for row in rows
            if not await self.db.is_fact_protected(chat_id, row["fact"])
        ]
        if len(rows) < 2:
            return 0
        clusters = await self._cluster_facts(chat_id, rows, now)
        merged = 0
        for cluster in clusters:
            if merged >= budget:
                break
            cluster = cluster[:hot.get("limits.graph_episode_merge_max_facts_per_cluster", settings.GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER)]
            if len(cluster) < 2:
                continue
            if await self._merge_cluster(chat_id, cluster, now):
                merged += 1
        return merged

    async def _cluster_facts(self, chat_id: int, rows: list, now: int) -> list:
        """Кластеры ≥2 похожих фактов: KNN-сходство (vec, cosine ≥
        _MERGE_CLUSTER_SIM) или точный subject+predicate (FTS-фолбек — первые
        два слова факта). Union-find; размер кластера ограничен
        GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER."""
        cap = hot.get("limits.graph_episode_merge_max_facts_per_cluster", settings.GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER)
        if self.memory._vec_available:
            pairs = []
            try:
                vectors = await self.memory._embed([row["fact"] for row in rows])
            except Exception:
                logger.warning(
                    "episode merge: embed failed — exact subject+predicate fallback")
                return self._cluster_exact(rows, cap)
            by_id = {row["id"]: row for row in rows}
            for i, row in enumerate(rows):
                near = await self.memory._dedup_knn(chat_id, vectors[i])
                for item in near[: _MERGE_KNN_K]:
                    other = by_id.get(item["fact_id"])
                    if other is None or other["id"] == row["id"]:
                        continue
                    cosine = 1.0 - item["distance"]
                    if cosine >= _MERGE_CLUSTER_SIM:
                        pairs.append((row["id"], other["id"]))
            return self._union_clusters(rows, pairs, cap)
        return self._cluster_exact(rows, cap)

    @staticmethod
    def _cluster_exact(rows: list, cap: int) -> list:
        """FTS-фолбек: точный subject+predicate — первые два слова факта."""
        groups: dict[str, list] = {}
        for row in rows:
            words = str(row["fact"]).split()
            key = " ".join(words[:2]).casefold() if len(words) >= 2 else None
            if key:
                groups.setdefault(key, []).append(row)
        return [grp[:cap] for grp in groups.values() if len(grp) >= 2]

    @staticmethod
    def _union_clusters(rows: list, pairs: list, cap: int) -> list:
        parent = {row["id"]: row["id"] for row in rows}
        size = {row["id"]: 1 for row in rows}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for a, b in pairs:
            ra, rb = find(a), find(b)
            if ra == rb:
                continue
            if size[ra] + size[rb] > cap:
                continue
            parent[rb] = ra
            size[ra] += size[rb]
        clusters: dict[int, list] = {}
        for row in rows:
            clusters.setdefault(find(row["id"]), []).append(row)
        return [grp for grp in clusters.values() if len(grp) >= 2]

    async def _merge_cluster(self, chat_id: int, cluster: list, now: int):
        """LLM-слияние (COMPRESS_PROMPT) + проверка покрытия токенов → INSERT
        слитого + DELETE исходных + журнал (reason='episode_merge').
        Покрытие не прошло → пропуск кластера (WARNING), исходные живут."""
        texts = [str(row["fact"]) for row in cluster]
        source_tokens = {token for text in texts
                         for token in _TOKEN_RE.findall(text.lower())}
        try:
            raw = await self.llm.generate([
                {"role": "system", "content": COMPRESS_PROMPT},
                {"role": "user", "content":
                    "слей эти факты в один, ничего не потеряй:\n"
                    + "\n".join(f"- {t}" for t in texts)}])
        except LLMError as exc:
            logger.warning("episode merge: LLM failed — cluster skipped | error=%s", exc)
            return None
        merged_text = str(raw or "").strip()
        if not merged_text:
            return None
        merged_tokens = set(_TOKEN_RE.findall(merged_text.lower()))
        if source_tokens and \
                len(merged_tokens) < _MERGE_COVERAGE_MIN * len(source_tokens):
            logger.warning(
                "episode merge: coverage check failed (%d%% < %d%%) — cluster "
                "skipped, sources live | chat_id=%s",
                int(100 * len(merged_tokens) / max(1, len(source_tokens))),
                int(100 * _MERGE_COVERAGE_MIN), chat_id)
            return None
        origin = ("chat_history" if any(row["origin"] == "chat_history" for row in cluster)
                  else cluster[0]["origin"])
        expiry = (None if any(row["expires_at"] is None for row in cluster)
                  else max(row["expires_at"] for row in cluster))
        weight = max(row["weight"] for row in cluster)
        # S10.18-35 (F5, ADR-1018-5 D2/D3): эпи-мерж НЕ должен «терять»
        # F5-пенальти мета-фактов. Исходные мета-факты записаны с importance=1
        # (срез по subject/object), но пере-вычисление rule_importance('chat_history')
        # дало бы слитой строке 4 → два таких факта набрали бы Σ8 ≥ гейта Сна.
        # Минимально инвазивно: если ВСЕ члены кластера имели imp<=1 → merged
        # imp=METAFACT_PENALTY_IMPORTANCE; иначе прежнее поведение (None →
        # rule_importance), существующие merge-тесты не затрагиваются.
        importance = (
            METAFACT_PENALTY_IMPORTANCE
            if all(int(row["importance"]) <= METAFACT_PENALTY_IMPORTANCE
                   for row in cluster)
            else None)
        targets = {row["target_user"] for row in cluster if row["target_user"]}
        target_user = targets.pop() if len(targets) == 1 else None
        fact_id = await self.db.insert_graph_fact(
            chat_id, merged_text, origin, expiry, target_user=target_user,
            weight=weight, importance=importance)
        if self.memory._vec_available:
            await self.memory._save_graph_fact_embedding(
                fact_id, chat_id, merged_text, origin, expiry)
        for row in cluster:
            await self.db.delete_graph_fact(row["id"])
            await self.db.log_fact_compression(
                chat_id, fact_id, row["fact"], merged_text, "episode_merge")
        logger.info(
            "episode merge: merged %d facts → fact_id=%d | chat_id=%s",
            len(cluster), fact_id, chat_id)
        return fact_id

    # ── 66.11 (T-489): периодический пересмотр ──────────────────

    async def review(self) -> None:
        """(1) склейка точных дублей (keep самый тяжёлый) и vec-кластеров
        ≥0.95; (2) выброс истёкших — глобальный проход; (3) выброс unconfirmed
        старше retention; (4) усечение лога сжатий."""
        now = int(time.time())
        for chat_id in await self.db.get_graph_chat_ids():
            groups = await self.db.find_exact_dup_groups(chat_id, now)
            for group in groups:
                keep = max(group, key=lambda r: (r["weight"], r["id"]))
                for row in group:
                    if row["id"] == keep["id"]:
                        continue
                    if await self.db.is_fact_protected(chat_id, row["fact"]):
                        continue
                    await self.db.delete_graph_fact(row["id"])
                    await self.db.log_fact_compression(
                        chat_id, keep["id"], row["fact"], keep["fact"],
                        "review_glue")
            if self.memory._vec_available:
                await self._glue_vec_dups(chat_id, now)
        expired = await self.db.purge_expired_graph_facts()
        unconfirmed = await self.db.purge_unconfirmed_graph_facts(
            now, hot.get("limits.graph_unconfirmed_retention_days", settings.GRAPH_UNCONFIRMED_RETENTION_DAYS))
        trimmed = await self.db.trim_compression_log(
            time.time(), hot.get("limits.graph_compression_log_retention_days", settings.GRAPH_COMPRESSION_LOG_RETENTION_DAYS))
        logger.info(
            "graph review: expired=%d unconfirmed=%d log_trimmed=%d",
            expired, unconfirmed, trimmed)

    async def _glue_vec_dups(self, chat_id: int, now: int) -> None:
        """66.11: vec-кластеры cosine ≥0.95 → keep самый тяжёлый. Потолок
        _REVIEW_VEC_BATCH фактов чата; защищённые не трогаем."""
        rows = await self.db.get_live_graph_facts(chat_id, now)
        rows = [
            row for row in rows[: _REVIEW_VEC_BATCH]
            if not await self.db.is_fact_protected(chat_id, row["fact"])
        ]
        if len(rows) < 2:
            return
        try:
            vectors = await self.memory._embed([row["fact"] for row in rows])
        except Exception:
            logger.warning("graph review: vec glue embed failed — skipped")
            return
        by_id = {row["id"]: row for row in rows}
        pairs = set()
        for i, row in enumerate(rows):
            near = await self.memory._dedup_knn(chat_id, vectors[i])
            for item in near[: _MERGE_KNN_K]:
                other = by_id.get(item["fact_id"])
                if other is None or other["id"] == row["id"]:
                    continue
                if 1.0 - item["distance"] >= _REVIEW_GLUE_SIM:
                    pairs.add(tuple(sorted((row["id"], other["id"]))))
        for a_id, b_id in pairs:
            a, b = by_id.get(a_id), by_id.get(b_id)
            if a is None or b is None:
                continue
            keep = max((a, b), key=lambda r: (r["weight"], r["id"]))
            drop = b if keep is a else a
            if await self.db.is_fact_protected(chat_id, drop["fact"]):
                continue
            await self.db.delete_graph_fact(drop["id"])
            await self.db.log_fact_compression(
                chat_id, keep["id"], drop["fact"], keep["fact"], "review_glue")

    async def shutdown(self) -> None:
        try:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                await asyncio.sleep(0)
            logger.info("MemoryMaintenance stopped")
        except SchedulerNotRunningError:
            logger.info("MemoryMaintenance was not running — nothing to stop")


# ── F7 (10.19, ADR-1019-6 D1/D1a/D2): retention импортированной истории ─────

_ARCHIVE_BATCH = 2000          # строк на пачку при экспорте архива
_ARCHIVE_PREFIX = "imported_history_"
# ⛔ IMMUTABLE (F9/ADR-1024-2 D2; owner UPD3 №5): файлы `imported_history_*.
# jsonl` содержат СЫРУЮ ИСТОРИЮ сообщений и НЕ являются кандидатами на
# удаление. Их не трогает ни retention диска (`services.disk_retention`:
# IMMUTABLE_PATTERNS/deny-list), ни какие-либо другие пути. Техдолг S10.19-24
# (ротация этих архивов) закрыт как Won't Fix — история хранится бессрочно.
IMMUTABLE_ARCHIVE_GLOB = "imported_history_*.jsonl"


def _flush_and_fsync(fh) -> None:
    """D-2.2 (Medium, ревью итерации 4): сбросить пользовательский буфер и
    форсировать `os.fsync` — архив ДОЛЖЕН пережить сбой питания РАНЬШЕ, чем
    SQLite-DELETE (иначе архив мог остаться только в page-cache, а DELETE
    персистироваться — необратимая потеря). Синхронно, вызывается через
    `asyncio.to_thread`, чтобы не блокировать event loop."""
    fh.flush()
    os.fsync(fh.fileno())


def _fsync_directory(directory) -> None:
    """S10.19-23 (ADR-1020-5 п.5, T-1910b): fsync КАТАЛОГА архива после
    fsync файла — только так запись ИМЕНИ нового файла в каталоге переживёт
    краш (POSIX). Best-effort: любые OSError → честный WARNING, прогон НЕ
    падает. На Windows (dev-платформа win32) каталог открыть нельзя —
    явный no-op с честным логом (R17: без путей/значений)."""
    if os.name == "nt":
        logger.info("[retention] dir fsync skipped (no-op on %s)", os.name)
        return
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(str(directory), flags)
    except OSError as exc:
        logger.warning("[retention] dir fsync unavailable | reason=%s",
                       type(exc).__name__)
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        logger.warning("[retention] dir fsync failed | reason=%s",
                       type(exc).__name__)
    finally:
        os.close(fd)


def _flush_fsync_and_dir(fh, directory) -> None:
    """D-2.2 + S10.19-23: fsync файла, затем каталога — одним
    `asyncio.to_thread`-вызовом (event loop не блокируется)."""
    _flush_and_fsync(fh)
    _fsync_directory(directory)


def auto_purge_dry_run(*, dry_run: bool, backup_confirmed: bool) -> bool:
    """Гейт деструктивного авто-крона (UPD4 п.3, D-2 High).

    Авто-крон (`summary_memory.compress_and_purge`) НЕ имеет права выполнять
    DELETE, пока оператор ЯВНО не включил apply (`dry_run=False`) **И** не
    подтвердил созданный/проверенный бэкап БД (`backup_confirmed=True`).
    Иначе — только dry-run (подсчёт) + WARNING на вызывающем. Единая точка
    правды для тестов (Δ каталога не растёт — env-флаги ClassVar)."""
    return bool(dry_run) or not bool(backup_confirmed)


async def _archive_imported_history(db, chat_cutoffs: dict[int, int],
                                    directory: Path
                                    ) -> tuple[bool, int, str, dict[int, int]]:
    """D2: экспорт выборки purge в файл ДО удаления (fail-safe).

    `{directory}/imported_history_<ts>.jsonl` — по строке JSON на запись
    (UTF-8). Возвращает `(ok, archived_rows, path, max_ids)`; любая ошибка
    записи → `ok=False` (вызывающий НЕ удаляет строки). Стриминг батчами —
    память ограничена `_ARCHIVE_BATCH`. R17-safe: файл содержит текст
    переписки, но сами логи пишут только число/путь без токенов.

    D-7 (ревью Батча E): `max_ids[chat_id]` — максимальный id, реально
    попавший в архив для чата. Purge ограничивается `id <= max_ids[chat_id]`
    (строго по зафиксированному множеству)."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("[retention] archive dir unavailable | reason=%s",
                       type(exc).__name__)
        return False, 0, "", {}
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = directory / f"{_ARCHIVE_PREFIX}{stamp}.jsonl"
    archived = 0
    max_ids: dict[int, int] = {int(c): 0 for c in chat_cutoffs}
    try:
        with open(target, "w", encoding="utf-8") as fh:
            for chat_id, cutoff in chat_cutoffs.items():
                after_id = 0
                while True:
                    rows = await db.select_imported_history(
                        int(chat_id), int(cutoff), after_id=after_id,
                        limit=_ARCHIVE_BATCH)
                    if not rows:
                        break
                    for row in rows:
                        fh.write(json.dumps(dict(row), ensure_ascii=False,
                                            default=str))
                        fh.write("\n")
                    archived += len(rows)
                    after_id = int(rows[-1]["id"])
                    max_ids[int(chat_id)] = after_id
                    if len(rows) < _ARCHIVE_BATCH:
                        break
            # D-2.2 + S10.19-23: fsync файла, затем КАТАЛОГА (имя файла
            # тоже должно пережить краш) — одним to_thread.
            await asyncio.to_thread(_flush_fsync_and_dir, fh, directory)
    except Exception:
        logger.warning("[retention] archive failed — purge skipped "
                       "(fail-safe)", exc_info=True)
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        return False, 0, str(target), {}
    return True, archived, str(target), max_ids


async def run_import_retention(db, *, dry_run: bool = False,
                               archive_dir: str | Path | None = None,
                               batch: int = 2000,
                               now: int | None = None) -> dict:
    """F7 (ADR-1019-6 D1/D1a/D2): ЕДИНСТВЕННЫЙ call-site purge импорта.

    Маппинг `chat_cutoffs` строится ТОЛЬКО из чатов, разрешённых
    `retention_policy.imported_history_purge_allowed` (чаты с retention `0=вечно` сюда не
    попадает никогда — структурный guard; дополнительно hard-deny по
    `enforce`-данным сида). `dry_run=True` → подсчёт без удаления. Иначе —
    обязательный архив в файл (`D2`, fail-safe: сбой архивации ⇒ строки не
    удаляются), затем батчевый purge.

    D-1 (Critical, ревью Батча E): если chat-слой НЕ читается (любой чат
    отдал `source='error'`) — прогон ОТМЕНЯЕТСЯ ЦЕЛИКОМ
    (`reason='chat_layer_unavailable'`), `chat_cutoffs` из fail-open
    `'default'` не строится.

    D-7: purge идёт строго по зафиксированному множеству (`id <= max_id` из
    архива); при расхождении `candidates != archived` (строки стали
    `history_processed=1` между снапшотом и удалением) — purge прерывается
    с WARNING без удаления.

    Возвращает `{chats, candidates, archived, deleted, batches, dry_run,
    reason, archive}`. Fail-open: ошибки БД → нули (не 500)."""
    now = int(time.time()) if now is None else int(now)
    out = {"chats": 0, "candidates": 0, "archived": 0, "deleted": 0,
           "batches": 0, "dry_run": bool(dry_run), "reason": "ok",
           "archive": ""}
    try:
        chat_ids = await db.get_smart_chat_ids()
    except Exception:
        logger.warning("[retention] chat list failed — fail-open",
                       exc_info=True)
        out["reason"] = "chat_list_failed"
        return out
    chat_cutoffs: dict[int, int] = {}
    layer_error = False
    for chat_id in chat_ids:
        try:
            allowed, days, source = \
                await retention_policy.imported_history_purge_allowed(chat_id)
        except Exception:
            allowed, days, source = False, 0, "error"
        if source == "error":
            # D-1: chat-слой недоступен → НЕ доверяем fail-open дефолту.
            layer_error = True
            logger.warning(
                "[retention] chat layer unavailable — run aborted "
                "(fail-closed) | chat=%s", chat_id)
            continue
        if not allowed:
            # R17: только id/источник; чаты с retention 0 (вечно) сюда попадают.
            logger.info("[retention] import purge skip | chat=%s | "
                        "reason=eternal | source=%s", chat_id, source)
            continue
        chat_cutoffs[int(chat_id)] = now - int(days) * 86400
    if layer_error:
        out["reason"] = "chat_layer_unavailable"
        return out
    if not chat_cutoffs:
        out["reason"] = "no_candidates"
        return out
    out["chats"] = len(chat_cutoffs)
    # Сначала ВСЕГДА подсчёт (dry-run-семантика): нет кандидатов — не трогаем
    # архив/диск (дешёвый выход).
    try:
        probe = await db.purge_imported_history(
            chat_cutoffs=chat_cutoffs, batch=batch, dry_run=True)
        out["candidates"] = int(probe.get("candidates") or 0)
    except Exception:
        logger.warning("[retention] candidate count failed — skip",
                       exc_info=True)
        out["reason"] = "count_failed"
        return out
    if out["candidates"] == 0:
        out["reason"] = "no_candidates"
        return out
    if dry_run:
        out["reason"] = "dry_run"
        logger.info("[retention] import dry-run | chats=%d candidates=%d",
                    len(chat_cutoffs), out["candidates"])
        return out
    directory = Path(archive_dir or hot.get(
        "reactions.memory_backup_dir", settings.MEMORY_BACKUP_DIR))
    ok, archived, path, max_ids = await _archive_imported_history(
        db, chat_cutoffs, directory)
    if not ok:
        out["reason"] = "archive_failed"
        return out
    out["archived"] = archived
    out["archive"] = path
    # D-7: сверяем «кандидаты по зафиксированным id» с архивом — расхождение
    # означает гонку с history_processed → НЕ удаляем.
    try:
        fixed = await db.purge_imported_history(
            chat_cutoffs=chat_cutoffs, batch=batch, dry_run=True,
            chat_max_ids=max_ids)
        fixed_candidates = int(fixed.get("candidates") or 0)
    except Exception:
        logger.warning("[retention] fixed-count failed — purge skipped",
                       exc_info=True)
        out["reason"] = "count_failed"
        return out
    out["candidates"] = fixed_candidates
    if fixed_candidates != archived:
        logger.warning(
            "[retention] archive/purge mismatch — purge aborted | "
            "archived=%d candidates=%d", archived, fixed_candidates)
        out["reason"] = "archive_mismatch"
        return out
    res = await db.purge_imported_history(
        chat_cutoffs=chat_cutoffs, batch=batch, dry_run=False,
        chat_max_ids=max_ids)
    out["candidates"] = int(res.get("candidates") or 0)
    out["deleted"] = int(res.get("deleted") or 0)
    out["batches"] = int(res.get("batches") or 0)
    logger.info(
        "[retention] import purge | chats=%d archived=%d deleted=%d "
        "batches=%d", out["chats"], out["archived"], out["deleted"],
        out["batches"])
    return out


# ── F4 (paradigm-thresholds-consolidation-round1021, ADR-1021-4) ──────────
# READ-ONLY аудит причин пустого мета-слоя + идемпотентная Memory
# Consolidation. Консолидация — ТОЛЬКО ручной CLI-вызов (`manage.py memory
# consolidate`), авто-крона нет. Дефолт — боевой прогон; `--dry-run` — опция.

_DREAM_LOG_KINDS = ("run", "distilled", "skipped", "error",
                    "deep_run", "deep_skip", "deep_traits")


async def collect_paradigm_audit(db) -> dict:
    """READ-ONLY аудит T-1972: где обрыв цепочки «сон → глубокий сон →
    парадигмы».

    Возвращает фактические значения флагов, счётчики `memory_dream_log` по
    kind, число парадигм/убеждений и определённую «точку обрыва» с ветвью
    spec §3.3 (A — флаги, B — пороги, C — кап). Только bounded SELECT;
    никаких мутаций. R17: счётчики и bool-флаги, без текстов."""
    out = {
        "flags": {},
        "dream_log": {},
        "last_run": {},
        "paradigms_total": 0,
        "paradigms_by_chat": {},
        "beliefs_by_status": {},
        "break_point": "unknown",
        "branch": "unknown",
    }
    from services.worker_settings import resolve_setting_cached

    flag_specs = (
        ("dream_enabled", "memory.dream_enabled", settings.DREAM_ENABLED),
        ("deep_sleep_enabled", "flags.deep_sleep_enabled",
         settings.DEEP_SLEEP_ENABLED),
        ("belief_decay_enabled", "flags.belief_decay_enabled",
         settings.BELIEF_DECAY_ENABLED),
    )
    for label, key, default in flag_specs:
        try:
            value = bool(await resolve_setting_cached(key, default=default))
        except Exception:
            value = bool(default)
        out["flags"][label] = value

    for kind in _DREAM_LOG_KINDS:
        try:
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM memory_dream_log WHERE kind = ?",
                (kind,))
            row = await cursor.fetchone()
            out["dream_log"][kind] = int(row["c"]) if row else 0
        except Exception:
            out["dream_log"][kind] = 0
    for label, kinds in (("deep_run", ("deep_run",)),
                         ("deep_skip", ("deep_skip",))):
        try:
            ts = await db.last_run_at(kinds)
        except Exception:
            ts = None
        out["last_run"][label] = ts

    try:
        out["paradigms_total"] = int(await db.count_paradigms())
    except Exception:
        out["paradigms_total"] = 0
    try:
        cursor = await db.db.execute(
            "SELECT chat_id, COUNT(*) AS c FROM graph_facts "
            "WHERE kind = 'belief' AND (belief_meta LIKE ? OR "
            "belief_meta LIKE ?) GROUP BY chat_id",
            ('%"type":"paradigm"%', '%"type": "paradigm"%'))
        out["paradigms_by_chat"] = {
            int(r["chat_id"]): int(r["c"]) for r in await cursor.fetchall()}
    except Exception:
        out["paradigms_by_chat"] = {}
    try:
        out["beliefs_by_status"] = await db.count_beliefs_by_status()
    except Exception:
        out["beliefs_by_status"] = {}

    # Точка обрыва (spec §2.2/§3.3): цепочка гейтов.
    flags = out["flags"]
    log = out["dream_log"]
    ordinary = int(log.get("run", 0)) + int(log.get("distilled", 0)) + \
        int(log.get("skipped", 0)) + int(log.get("error", 0))
    deep_attempts = int(log.get("deep_run", 0)) + int(log.get("deep_skip", 0))
    if not flags.get("dream_enabled") and not flags.get("deep_sleep_enabled"):
        out["break_point"], out["branch"] = "flags_off", "A"
    elif ordinary == 0:
        out["break_point"], out["branch"] = "no_dream_runs", "A"
    elif deep_attempts == 0:
        # Обычный сон шёл, но глубокий не запускался — триггер/флаг.
        out["break_point"], out["branch"] = "no_deep_runs", "A"
    elif out["paradigms_total"] == 0:
        out["break_point"], out["branch"] = "no_paradigms", "B"
    else:
        out["break_point"], out["branch"] = "ok", "none"
    return out


def _belief_source_ids(raw) -> list[int]:
    """`source_ids` убеждения (JSON-массив) → список int (мусор пропускаем)."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    ids: list[int] = []
    for item in data:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


async def consolidate(db, *, chat_ids=None, dry_run: bool = False,
                      limit: int = 200, min_sources: int = 2,
                      now: int | None = None, db_path=None,
                      backup_dir=None, allow_no_backup: bool = False) -> dict:
    """F4/§3.2: идемпотентная Memory Consolidation (сжатие убеждений в
    парадигмы).

    Вход — bounded-выборка убеждений чата (`belief_meta.type='belief'`),
    ранжирование по числу опор (`source_ids`). Выход — парадигмы через
    `DreamWorker._write_paradigm` с дедупом `_paradigm_dedup_keys` /
    `_deep_dedup_key`. Капы не снимаются (S10.21-1): на чат пишется не больше
    `limits.deep_sleep_max_paradigms_per_run` (иначе
    `DEEP_SLEEP_MAX_PARADIGMS`) парадигм за прогон, а выборка ограничена
    `limits.deep_sleep_top_k` (`DEEP_SLEEP_TOP_K`) — как в Deep Sleep-пасе.
    Повторный прогон — 0 записей (идемпотентность). Вызывается
    ТОЛЬКО из CLI (F5), авто-крона нет; `dry_run` ничего не пишет.

    F4 fix-round 10.21 (R1): при боевом прогоне с `db_path` — авто-бэкап ДО
    первой записи + JSONL-архив ЗАПИСЫВАЕМЫХ парадигм (страховка/откат, по
    образцу F5). `db_path`/`backup_dir` прокидывает CLI (`manage.py memory
    consolidate`).

    F4 fix-round 2 (Medium): страховка **fail-closed** — боевой прогон без
    `db_path` НЕ пишет (reason `backup_unavailable`, выход до первой записи),
    как в F5. Явный opt-in `allow_no_backup=True` возвращает прежнее
    «пишем без страховки» поведение; в прод-коде он не выставляется.

    Возврат: `{chats, scanned, candidates, written, skipped, reasons,
    archived, backup, dry_run}`."""
    from services.dream_worker import DreamWorker, _deep_dedup_key

    out = {"dry_run": bool(dry_run), "chats": 0, "scanned": 0,
           "candidates": 0, "written": 0, "skipped": 0, "reasons": {},
           "archived": 0, "backup": "", "max_paradigms": 0}

    def _reason(code: str) -> None:
        out["reasons"][code] = out["reasons"].get(code, 0) + 1

    # S10.21-1: те же капы, что у Deep Sleep-паса (`dream_worker.py`):
    # per-chat не больше MAX_PARADIGMS, выборка не шире TOP_K. Каталог/схема
    # не меняются — значения лишь читаются.
    def _cap(key: str, default) -> int:
        try:
            return max(1, int(hot.get(key, default)))
        except (TypeError, ValueError):
            return max(1, int(default))

    max_paradigms = _cap("limits.deep_sleep_max_paradigms_per_run",
                         settings.DEEP_SLEEP_MAX_PARADIGMS)
    read_cap = _cap("limits.deep_sleep_top_k", settings.DEEP_SLEEP_TOP_K)
    out["max_paradigms"] = max_paradigms
    read_limit = min(max(1, int(limit)), read_cap)
    now = int(time.time()) if now is None else int(now)
    if chat_ids is None:
        try:
            chat_ids = await db.get_graph_chat_ids()
        except Exception:
            logger.warning("[consolidate] chat list failed — fail-open",
                           exc_info=True)
            chat_ids = []
    worker = DreamWorker(db, memory=None, llm=None)
    # Пасс 1: собрать кандидатов (дедуп внутри прогона — по ключу).
    candidates: list[dict] = []
    for chat_id in chat_ids:
        out["chats"] += 1
        try:
            rows = await db.list_recent_beliefs(
                chat_id=chat_id, limit=read_limit, status="confirmed",
                belief_type="belief")
        except Exception:
            logger.warning("[consolidate] belief read failed | chat=%s",
                           chat_id, exc_info=True)
            _reason("read_error")
            out["skipped"] += 1
            continue
        out["scanned"] += len(rows)
        try:
            existing = await worker._paradigm_dedup_keys(chat_id)
        except Exception:
            existing = set()
        ranked = sorted(
            rows, key=lambda r: len(_belief_source_ids(r.get("source_ids"))),
            reverse=True)
        per_chat = 0
        for row in ranked:
            if per_chat >= max_paradigms:
                # S10.21-1: не снимаем кап MAX_PARADIGMS за один прогон.
                _reason("cap_reached")
                out["skipped"] += 1
                continue
            ids = _belief_source_ids(row.get("source_ids"))
            text = " ".join(str(row.get("fact") or "").split())
            if not text:
                _reason("empty_text")
                out["skipped"] += 1
                continue
            if len(ids) < max(1, int(min_sources)):
                _reason("below_min_sources")
                out["skipped"] += 1
                continue
            anchors = [{"fact": text, "target_user": row.get("target_user")}]
            key = _deep_dedup_key(text, anchors)
            if key in existing:
                _reason("duplicate")
                out["skipped"] += 1
                continue
            out["candidates"] += 1
            per_chat += 1
            existing.add(key)
            if dry_run:
                continue
            candidates.append({
                "chat_id": int(chat_id),
                "fact": text,
                "target_user": row.get("target_user"),
                "source_ids": row.get("source_ids"),
                "anchors": anchors,
                "key": key,
                "ids": ids,
            })
    # Страховочная сетка ДО первой записи (боевой прогон с db_path).
    if not dry_run and candidates:
        if not db_path:
            # F4 fix-round 2 (Medium): fail-closed — без пути к БД страховку
            # создать нельзя, поэтому НЕ пишем (F5-семантика). Явный opt-in
            # allow_no_backup=True оставляет прежнее поведение (тесты/утилиты).
            if not allow_no_backup:
                _reason("backup_unavailable")
                return out
            out["backup"] = ""
        else:
            # Ленивый импорт: memory_rebuild импортирует
            # `_flush_fsync_and_dir` из этого модуля (циклический импорт).
            from services.memory_rebuild import (
                _safety_backup, _archive_generated_rows,
                _resolve_backup_dir)
            ok, backup_path, reason = await _safety_backup(
                db_path, backup_dir, "consolidate")
            if not ok:
                _reason(reason)
                return out
            out["backup"] = backup_path
            ok, archived, _path = await _archive_generated_rows(
                candidates, _resolve_backup_dir(backup_dir), "consolidate")
            if not ok or archived != len(candidates):
                _reason("archive_mismatch")
                out["skipped"] += len(candidates)
                return out
            out["archived"] = archived
    # Пасс 2: запись парадигм.
    for cand in candidates:
        try:
            fact_id = await worker._write_paradigm(
                cand["chat_id"], cand["fact"], {}, cand["anchors"],
                cand["ids"], cand["key"], now)
        except Exception:
            logger.warning("[consolidate] paradigm write failed | chat=%s",
                           cand["chat_id"], exc_info=True)
            fact_id = None
        if fact_id:
            out["written"] += 1
        else:
            _reason("write_failed")
            out["skipped"] += 1
    if out["written"] or out["candidates"]:
        logger.info(
            "[consolidate] scanned=%d candidates=%d written=%d skipped=%d "
            "archived=%d dry_run=%s", out["scanned"], out["candidates"],
            out["written"], out["skipped"], out["archived"], out["dry_run"])
    return out
