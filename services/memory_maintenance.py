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
import logging
import time

from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings
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
        self._scheduler = AsyncIOScheduler(timezone=settings.SUMMARY_TIMEZONE)

    def start(self) -> None:
        if settings.GRAPH_EPISODE_MERGE_ENABLED:
            self._scheduler.add_job(
                self._tick_merge,
                IntervalTrigger(
                    days=settings.GRAPH_EPISODE_MERGE_INTERVAL_DAYS,
                    timezone=settings.SUMMARY_TIMEZONE),
                id=self.JOB_MERGE_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        if settings.GRAPH_REVIEW_ENABLED:
            self._scheduler.add_job(
                self._tick_review,
                IntervalTrigger(
                    days=settings.GRAPH_REVIEW_INTERVAL_DAYS,
                    timezone=settings.SUMMARY_TIMEZONE),
                id=self.JOB_REVIEW_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        # Epic 64: периодический WAL-checkpoint(TRUNCATE) — без него -wal
        # разрастался (наблюдалось 18 МБ при БД 43 МБ).
        if settings.DB_WAL_CHECKPOINT_ENABLED:
            self._scheduler.add_job(
                self._tick_wal_checkpoint,
                IntervalTrigger(
                    hours=settings.DB_WAL_CHECKPOINT_HOURS,
                    timezone=settings.SUMMARY_TIMEZONE),
                id=self.JOB_WAL_ID, replace_existing=True,
                max_instances=1, coalesce=True)
        if (settings.GRAPH_EPISODE_MERGE_ENABLED or settings.GRAPH_REVIEW_ENABLED
                or settings.DB_WAL_CHECKPOINT_ENABLED):
            self._scheduler.start()
            logger.info(
                "MemoryMaintenance started (merge=%s/%dd, review=%s/%dd, wal=%s/%dh)",
                settings.GRAPH_EPISODE_MERGE_ENABLED,
                settings.GRAPH_EPISODE_MERGE_INTERVAL_DAYS,
                settings.GRAPH_REVIEW_ENABLED,
                settings.GRAPH_REVIEW_INTERVAL_DAYS,
                settings.DB_WAL_CHECKPOINT_ENABLED,
                settings.DB_WAL_CHECKPOINT_HOURS)
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
        budget = settings.GRAPH_EPISODE_MERGE_BATCH
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
            cluster = cluster[:settings.GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER]
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
        cap = settings.GRAPH_EPISODE_MERGE_MAX_FACTS_PER_CLUSTER
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
        targets = {row["target_user"] for row in cluster if row["target_user"]}
        target_user = targets.pop() if len(targets) == 1 else None
        fact_id = await self.db.insert_graph_fact(
            chat_id, merged_text, origin, expiry, target_user=target_user,
            weight=weight)
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
            now, settings.GRAPH_UNCONFIRMED_RETENTION_DAYS)
        trimmed = await self.db.trim_compression_log(
            time.time(), settings.GRAPH_COMPRESSION_LOG_RETENTION_DAYS)
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
