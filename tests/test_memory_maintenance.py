"""Epic 60 Фаза D (Section 66.2/66.11, T-480/T-489): MemoryMaintenanceService —
слияние повторяющихся эпизодов + периодический пересмотр фактов."""
import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from config.settings import settings
from services.database import DatabaseService
from services.memory_maintenance import (
    _MERGE_CLUSTER_SIM,
    MemoryMaintenanceService,
)
from services.summary_memory import MemoryManager


@pytest.fixture
def db():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    d = DatabaseService(":memory:")
    loop.run_until_complete(d.initialize())
    yield d
    loop.run_until_complete(d.close())
    loop.close()


def _patch_policy(monkeypatch, *, on: bool) -> None:
    """Каталоговый слой гейта MEMORY-04: резолв идёт через реальный
    `mca_gates.memory_maintenance_policy_enabled` (env AND flags.…), поэтому
    патчится только источник значения (`hot.get`), а не приватная функция."""
    import services.hot_config as hot

    real_get = hot.get

    def fake_get(key, default=None):
        if key == "flags.memory_maintenance_policy_enabled":
            return on
        return real_get(key, default)

    monkeypatch.setattr(hot, "get", fake_get)


@pytest.fixture(autouse=True)
def _policy_on_for_policy_tests(monkeypatch):
    """Тесты этого модуля проверяют НОВЫЙ путь памяти (гейт ON); OFF-паритет
    проверяется отдельным тестом, который перекрывает env+hot явно."""
    monkeypatch.setenv("MCA_MEMORY_MAINTENANCE_POLICY_ENABLED", "on")
    _patch_policy(monkeypatch, on=True)
    return True


class MergeLLM:
    """generate: канон-ответ для слияния (COMPRESS_PROMPT); embed не нужен
    (FTS-фолбек кластеризации — vec выключен)."""

    def __init__(self, response="вася спорил с петей и колей", fail=False):
        self.response = response
        self.fail = fail
        self.calls = []

    async def generate(self, messages):
        self.calls.append(messages)
        if self.fail:
            from services.llm_client import LLMError
            raise LLMError("слияние упало")
        return self.response


def _service(db, llm) -> tuple[MemoryMaintenanceService, MemoryManager]:
    memory = MemoryManager(db, llm)          # _vec_available=False → FTS-фолбек
    return MemoryMaintenanceService(db, memory, llm), memory


class TestEpisodeMerge:
    @pytest.mark.asyncio
    async def test_cluster_merge_keeps_sources_with_lineage(self, db, caplog):
        """MEM-04.3/04.5 (C-3 §3.4.1/§3.5, тест a): кластер (точный
        subject+predicate, FTS-фолбек) → производный факт ADD + lineage в обе
        стороны; НИ ОДНА исходная строка не удалена.

        Прежний `test_cluster_merged_sources_deleted_logged` требовал
        физического удаления источников (`assert ... not in facts`) — это
        прямое нарушение INV-01/INV-08 и MEM-02.6 («merge переносит наборы
        доказательств без потери ни одного fact_id»), поэтому тест переписан
        на новый контракт."""
        import logging
        from services import provenance

        first = await db.insert_graph_fact(
            -100, "вася спорил с петей", "chat_history", None)
        second = await db.insert_graph_fact(
            -100, "вася спорил с колей", "chat_history", None)
        await db.insert_graph_fact(
            -100, "озон доставляет быстрее wildberries", "search_fact", None)
        llm = MergeLLM(response="вася спорил с петей и колей")
        svc, _ = _service(db, llm)
        with caplog.at_level(logging.INFO):
            merged = await svc.merge_episodes()
        assert merged == 1
        cursor = await db.db.execute(
            "SELECT id, fact, source_ids FROM graph_facts ORDER BY id")
        rows = await cursor.fetchall()
        facts = [row["fact"] for row in rows]
        # все исходные строки живы + производный факт добавлен (чужой не тронут)
        assert facts == ["вася спорил с петей", "вася спорил с колей",
                         "озон доставляет быстрее wildberries",
                         "вася спорил с петей и колей"]
        # FTS-строки источников живы (никакого «полуудаления»)
        for source_id in (first, second):
            cursor = await db.db.execute(
                "SELECT COUNT(*) AS c FROM graph_facts_fts WHERE rowid = ?",
                (source_id,))
            assert (await cursor.fetchone())["c"] == 1
        derived = rows[-1]
        # forward: `source_ids` производного = ровно источники кластера
        assert json.loads(derived["source_ids"]) == [first, second]
        # forward: EvidenceLink `derived_from` на каждый источник
        cursor = await db.db.execute(
            "SELECT subject_ref_id, source_ref_id FROM mca_evidence_links "
            "WHERE link_type = 'derived_from'")
        links = await cursor.fetchall()
        assert len(links) == 2
        derived_ref = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(-100, derived["id"]))
        assert {link["subject_ref_id"] for link in links} == {derived_ref}
        # backward: по source-ref источника находится производный факт
        source_ref = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(-100, first))
        back = await provenance.links_derived_from_source(db, source_ref)
        assert [link["subject_ref_id"] for link in back
                if link["link_type"] == "derived_from"] == [derived_ref]
        # backward-ПОДТВЕРЖДЕНИЕ (C-3 §3.3/§3.4.1.1 п.3/п.6): ссылка
        # `supersedes` победителя на каждый поглощённый + статус источника
        cursor = await db.db.execute(
            "SELECT subject_ref_id, source_ref_id FROM mca_evidence_links "
            "WHERE link_type = 'supersedes'")
        supersedes = await cursor.fetchall()
        assert len(supersedes) == 2
        assert {link["subject_ref_id"] for link in supersedes} == {derived_ref}
        for source_id in (first, second):
            ref = await provenance.resolve_source_ref(
                db, provenance.graph_fact_source_ref(-100, source_id))
            status = await provenance.get_provenance_status(db, ref)
            assert status is not None
            assert status["freshness_status"] == "superseded"
        # однослотовый указатель строки: `graph_facts.supersedes` = первый источник
        cursor = await db.db.execute(
            "SELECT supersedes, status FROM graph_facts WHERE id = ?",
            (derived["id"],))
        derived_row = await cursor.fetchone()
        assert derived_row["supersedes"] == first
        # точный кластер — не сходство: факт подтверждён
        assert derived_row["status"] == "confirmed"
        # журнал «что во что» прежний (обратимость), но БЕЗ удаления
        cursor = await db.db.execute(
            "SELECT fact_id, fact_before, reason FROM graph_fact_compressions")
        logs = await cursor.fetchall()
        assert len(logs) == 2
        assert all(row["reason"] == "episode_merge" for row in logs)
        assert {row["fact_before"] for row in logs} == {
            "вася спорил с петей", "вася спорил с колей"}
        assert all(row["fact_id"] == derived["id"] for row in logs)
        # решение записано явным кодом (MEM-04.4)
        assert any("decision=add" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_vector_cluster_is_tentative_not_confirmed(self, db, caplog):
        """MEM-04.5/INV-06 (F2): кластер, собранный ТОЛЬКО сходством (cosine),
        даёт производный факт `unconfirmed` с lineage `tentative`; точный
        кластер — `confirmed`/`verified` (сравнение с тестом выше). Вектор-
        сервис подменён (не предмет проверки), решение и запись — реальные."""
        import logging
        from unittest.mock import AsyncMock

        from services import provenance

        first = await db.insert_graph_fact(
            -100, "дроны летали низко над полем", "web_content", None)
        second = await db.insert_graph_fact(
            -100, "дроны летали низко над лесом", "web_content", None)
        llm = MergeLLM(response="дроны летали низко над полем и лесом")
        svc, memory = _service(db, llm)
        memory._vec_available = True
        memory._embed = AsyncMock(return_value=[[0.0, 1.0], [0.0, 1.0]])
        memory._dedup_knn = AsyncMock(
            return_value=[{"fact_id": first, "distance": 0.02}])   # cosine 0.98
        with caplog.at_level(logging.INFO):
            merged = await svc.merge_episodes()
        assert merged == 1
        cursor = await db.db.execute(
            "SELECT id, status, source_ids FROM graph_facts ORDER BY id DESC LIMIT 1")
        derived = await cursor.fetchone()
        assert derived["status"] == "unconfirmed"        # сходство ≠ доказательство
        assert json.loads(derived["source_ids"]) == [first, second]
        derived_ref = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(-100, derived["id"]))
        cursor = await db.db.execute(
            "SELECT link_type, verification, independence "
            "FROM mca_evidence_links WHERE subject_ref_id = ? "
            "ORDER BY link_type", (derived_ref,))
        links = await cursor.fetchall()
        assert len(links) == 2                    # по одной ссылке на каждый источник
        assert {(r["link_type"], r["verification"], r["independence"])
                for r in links} == {("derived_from", "tentative", "unknown")}
        # сходство НЕ даёт backward-supersedes: источники не объявлены устаревшими
        for source_id in (first, second):
            ref = await provenance.resolve_source_ref(
                db, provenance.graph_fact_source_ref(-100, source_id))
            status = await provenance.get_provenance_status(db, ref)
            assert status is None or status["freshness_status"] != "superseded"
        assert any("method=vector" in r.message and "decision=add" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_gate_off_legacy_path_no_lineage_aggregate(self, db, monkeypatch):
        """F1 (C-3 §3.6): гейт OFF (реальный резолвер `mca_gates`, default OFF)
        → ТОЧНЫЙ паритет base-коммита: legacy-слияние с удалением источников,
        НИКАКОГО нового артефакта (агрегат без `source_ids`, без evidence-links).
        Проверяется через env + каталоговый слой, без патча приватной функции."""
        monkeypatch.delenv("MCA_MEMORY_MAINTENANCE_POLICY_ENABLED", raising=False)
        _patch_policy(monkeypatch, on=False)
        from services import mca_gates
        assert mca_gates.memory_maintenance_policy_env_enabled() is False
        assert await mca_gates.memory_maintenance_policy_enabled(-100) is False
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей", "chat_history", None)
        llm = MergeLLM(response="вася спорил с петей и колей")
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute(
            "SELECT fact, source_ids, supersedes FROM graph_facts ORDER BY id")
        rows = await cursor.fetchall()
        # base-паритет: осталась только слитая строка (источники удалены)
        assert [row["fact"] for row in rows] == ["вася спорил с петей и колей"]
        # нового артефакта нет: ни source_ids, ни указателя supersedes
        assert rows[0]["source_ids"] is None
        assert rows[0]["supersedes"] is None
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links")
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_absorbed_sources_are_not_merged_again(self, db):
        """MEM-04 (C-3 §3.5): производный факт — не первичный сигнал, а его
        источники уже консолидированы → повторный тик не создаёт новый агрегат
        и не вызывает LLM (идемпотентность вместо бесконечного слияния)."""
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей", "chat_history", None)
        llm = MergeLLM(response="вася спорил с петей и колей")
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 1
        assert await svc.merge_episodes() == 0
        assert len(llm.calls) == 1               # второй тик LLM не звал
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 3     # 2 источника + 1 агрегат

    @pytest.mark.asyncio
    async def test_aggregate_validity_from_all_sources(self, db):
        """C-3 §3.1/§3.7: `valid_from`/`valid_to` производного факта берутся из
        источников (min/max), когда их поддерживают ВСЕ источники."""
        for text in ("вася работал в цеху", "вася работал в порту"):
            fid = await db.insert_graph_fact(-100, text, "chat_history", None)
            await db.db.execute(
                "UPDATE graph_facts SET valid_from = 1000, valid_to = 2000 "
                "WHERE id = ?", (fid,))
        await db.db.commit()
        svc, _ = _service(db, MergeLLM(response="вася работал в цеху и порту"))
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute(
            "SELECT valid_from, valid_to FROM graph_facts ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        assert (row["valid_from"], row["valid_to"]) == (1000, 2000)

    @pytest.mark.asyncio
    async def test_aggregate_validity_unknown_stays_null(self, db):
        """C-3 §3.1: отсутствующая дата ≠ T_assertion ≠ `now` — если период
        поддерживает не каждый источник, производный факт остаётся без
        `valid_from/valid_to` (никакого `time.time()`)."""
        first = await db.insert_graph_fact(
            -100, "вася жил в сочи", "chat_history", None)
        await db.insert_graph_fact(-100, "вася жил в крыму", "chat_history", None)
        await db.db.execute(
            "UPDATE graph_facts SET valid_from = 3000 WHERE id = ?", (first,))
        await db.db.commit()
        svc, _ = _service(db, MergeLLM(response="вася жил в сочи и крыму"))
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute(
            "SELECT valid_from, valid_to FROM graph_facts ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        assert row["valid_from"] is None
        assert row["valid_to"] is None

    @pytest.mark.asyncio
    async def test_coverage_check_skips_cluster(self, db, caplog):
        """66.2: «ничего не потерялось» не прошло (токены слитого < 60%
        исходных) → пропуск кластера, исходные живут."""
        await db.insert_graph_fact(-100, "вася спорил с петей вчера вечером", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей утром рано", "chat_history", None)
        llm = MergeLLM(response="вася")
        svc, _ = _service(db, llm)
        import logging
        with caplog.at_level(logging.WARNING):
            merged = await svc.merge_episodes()
        assert merged == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2     # исходные живы
        assert any("coverage check failed" in r.message for r in caplog.records)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_fact_compressions")
        assert (await cursor.fetchone())["c"] == 0     # журнала нет

    @pytest.mark.asyncio
    async def test_llm_error_skips_run(self, db):
        """66.2: LLMError → прогон прерван, исходные живут."""
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей", "chat_history", None)
        llm = MergeLLM(fail=True)
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2

    @pytest.mark.asyncio
    async def test_protected_excluded_from_clusters(self, db):
        """65.10: защищённый факт в кластеры не попадает — слияния нет."""
        await db.insert_graph_fact(-100, "вася спорил с петей", "chat_history", None)
        await db.insert_graph_fact(-100, "вася спорил с колей", "chat_history", None)
        await db.db.execute(
            "INSERT INTO protected_facts (chat_id, user_name, fact, created_at) "
            "VALUES (-100, 'вася', 'вася спорил с петей', ?)", (time.time(),))
        await db.db.commit()
        llm = MergeLLM()
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 0
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 2
        llm.generate.assert_not_awaited() if hasattr(llm.generate, "assert_not_awaited") else None

    @pytest.mark.asyncio
    async def test_batch_budget_respected(self, db, monkeypatch):
        """66.2: GRAPH_EPISODE_MERGE_BATCH — потолок кластеров за прогон."""
        mod_clusters = 3
        for i in range(mod_clusters):
            await db.insert_graph_fact(
                -100, f"тема{i} обсуждали подробно", "chat_history", None)
            await db.insert_graph_fact(
                -100, f"тема{i} обсуждали мельком", "chat_history", None)
        llm = MergeLLM(response="тема обсуждали подробно и мельком")
        svc, _ = _service(db, llm)
        mod = __import__("dataclasses").replace(
            settings, GRAPH_EPISODE_MERGE_BATCH=1)
        monkeypatch.setattr(
            "services.memory_maintenance.settings", mod)
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute("SELECT COUNT(*) AS c FROM graph_facts")
        # 1 кластер слит: агрегат ДОБАВЛЕН, 4 исходных факта живы → 6 + 1
        # (прежнее ожидание 5 держалось на удалении источников — MEM-04.3)
        assert (await cursor.fetchone())["c"] == 7

    @pytest.mark.asyncio
    async def test_merged_fact_keeps_max_weight_and_null_expiry(self, db):
        """Слитый факт: weight = max исходных; expiry NULL если хоть один
        источник вечный; origin chat_history при наличии такого источника."""
        f1 = await db.insert_graph_fact(
            -100, "вася ходит в кино часто", "chat_history", None)
        await db.db.execute("UPDATE graph_facts SET weight = 0.9 WHERE id = ?", (f1,))
        await db.insert_graph_fact(
            -100, "вася ходит в кино редко", "search_fact", None)
        await db.db.commit()
        llm = MergeLLM(response="вася ходит в кино часто и редко")
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute(
            "SELECT weight, expires_at, origin FROM graph_facts "
            "ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        assert row["weight"] == 0.9
        assert row["expires_at"] is None
        assert row["origin"] == "chat_history"


class TestReview:
    @pytest.mark.asyncio
    async def test_exact_dups_emit_candidate_keep_all_rows(self, db):
        """MEM-04.4 (C-3 §3.4/§3.4.1.1 п.3/п.6, тест c): точные дубли — обе
        строки живы, у проигравшего `freshness_status='superseded'`, у
        победителя указатель `supersedes` и одноимённая ссылка; вес не
        меняется, журнала склейки нет, событие-кандидат — одно.

        Прежний `test_exact_dups_glued_keep_heaviest` удалял «более лёгкую»
        строку — физическое удаление памяти по сходству текста, прямо
        запрещённое MEM-04.3/04.6 и INV-01, поэтому тест переписан."""
        from services import mca_events, provenance

        keep_id = await db.insert_graph_fact(
            -100, "дроны летали низко", "web_content", None, weight=0.9)
        dup_id = await db.insert_graph_fact(
            -100, "Дроны летали низко ", "web_content", None, weight=0.3)
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT id, fact, weight FROM graph_facts ORDER BY id")
        rows = await cursor.fetchall()
        assert [row["id"] for row in rows] == [keep_id, dup_id]   # обе живы
        assert [row["weight"] for row in rows] == [0.9, 0.3]      # вес не тронут
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_fact_compressions")
        assert (await cursor.fetchone())["c"] == 0                # склейки нет
        # статус проигравшего + указатель победителя (F3)
        loser_ref = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(-100, dup_id))
        status = await provenance.get_provenance_status(db, loser_ref)
        assert status is not None
        assert status["freshness_status"] == "superseded"
        winner_ref = await provenance.resolve_source_ref(
            db, provenance.graph_fact_source_ref(-100, keep_id))
        cursor = await db.db.execute(
            "SELECT subject_ref_id FROM mca_evidence_links "
            "WHERE link_type = 'supersedes' AND source_ref_id = ?",
            (loser_ref,))
        link = await cursor.fetchone()
        assert link is not None and link["subject_ref_id"] == winner_ref
        cursor = await db.db.execute(
            "SELECT supersedes FROM graph_facts WHERE id = ?", (keep_id,))
        assert (await cursor.fetchone())["supersedes"] == dup_id
        await mca_events.flush_events(db)
        cursor = await db.db.execute(
            "SELECT stage, entity_ids FROM mca_events "
            "WHERE event_name = 'memory_dedupe_candidate'")
        events = await cursor.fetchall()
        assert len(events) == 1
        assert events[0]["stage"] == "dedupe_candidate:exact_duplicate"
        assert sorted(json.loads(events[0]["entity_ids"])) == [keep_id, dup_id]

    @pytest.mark.asyncio
    async def test_vector_similar_pair_is_only_a_candidate(self, db):
        """MEM-04.4 (C-3 §3.4, тест c): cosine 0.98 — только кандидат
        (`memory_dedupe_candidate`), НЕ склейка: ни удаления, ни замены, ни
        изменения веса. Вектор-сервис подменён (не предмет проверки), решение
        и запись — реальные."""
        from unittest.mock import AsyncMock

        from services import mca_events

        first = await db.insert_graph_fact(
            -100, "дроны летали низко над полем", "web_content", None, weight=0.9)
        second = await db.insert_graph_fact(
            -100, "дроны летали низко над лесом", "web_content", None, weight=0.3)
        svc, memory = _service(db, MergeLLM())
        memory._vec_available = True
        memory._embed = AsyncMock(return_value=[[0.0, 1.0], [0.0, 1.0]])
        memory._dedup_knn = AsyncMock(
            return_value=[{"fact_id": first, "distance": 0.02}])
        await svc.review()
        cursor = await db.db.execute(
            "SELECT id, weight FROM graph_facts ORDER BY id")
        rows = await cursor.fetchall()
        assert [row["id"] for row in rows] == [first, second]      # обе живы
        assert [row["weight"] for row in rows] == [0.9, 0.3]       # вес не тронут
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_fact_compressions")
        assert (await cursor.fetchone())["c"] == 0                 # «склейки» нет
        await mca_events.flush_events(db)
        cursor = await db.db.execute(
            "SELECT stage, entity_ids FROM mca_events "
            "WHERE event_name = 'memory_dedupe_candidate'")
        events = await cursor.fetchall()
        assert len(events) == 1
        assert events[0]["stage"] == "dedupe_candidate:vector_similar"
        assert sorted(json.loads(events[0]["entity_ids"])) == [first, second]
        # сходство НЕ даёт backward-статусов: ни supersedes, ни freshness
        from services import provenance
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links "
            "WHERE link_type = 'supersedes'")
        assert (await cursor.fetchone())["c"] == 0
        for fact_id in (first, second):
            ref = await provenance.resolve_source_ref(
                db, provenance.graph_fact_source_ref(-100, fact_id))
            status = await provenance.get_provenance_status(db, ref)
            assert status is None or status["freshness_status"] != "superseded"

    @pytest.mark.asyncio
    async def test_expired_purged_globally(self, db):
        """66.11 #2: истёкшие выбрасываются глобальным проходом (без chat_id).
        Раунд 8 (E3/T-805): слабые истёкшие факты рождаются со свежим
        last_confirmed_at (защита «недавнее подтверждение») — старим его,
        кандидатность на TTL-purge возвращается."""
        now = int(time.time())
        for chat in (-100, -200):
            fid = await db.insert_graph_fact(
                chat, f"мёртвый факт чата {chat}", "search_fact", now - 100)
            await db.db.execute(
                "UPDATE graph_facts SET last_confirmed_at = ? WHERE id = ?",
                (now - 10 * 86400, fid))
        await db.insert_graph_fact(
            -100, "живой вечный факт", "chat_history", None)
        await db.db.commit()
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts")
        assert (await cursor.fetchone())["c"] == 1

    @pytest.mark.asyncio
    async def test_unconfirmed_dropped_after_retention(self, db, monkeypatch):
        """66.11 #3: unconfirmed старше GRAPH_UNCONFIRMED_RETENTION_DAYS —
        выброс (вместе с FTS/vec-строками)."""
        now = int(time.time())
        fid = await db.insert_graph_fact(
            -100, "сомнительный факт без подтверждения", "search_fact", None,
            status="unconfirmed")
        await db.db.execute(
            "UPDATE graph_facts SET created_at = ? WHERE id = ?",
            (now - (settings.GRAPH_UNCONFIRMED_RETENTION_DAYS + 1) * 86400, fid))
        await db.db.commit()
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts WHERE id = ?", (fid,))
        assert (await cursor.fetchone())["c"] == 0
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM graph_facts_fts WHERE rowid = ?", (fid,))
        assert (await cursor.fetchone())["c"] == 0

    @pytest.mark.asyncio
    async def test_compression_log_trimmed(self, db, monkeypatch):
        """66.11 #4: graph_fact_compressions старше retention усечены."""
        old_ts = time.time() - (settings.GRAPH_COMPRESSION_LOG_RETENTION_DAYS + 1) * 86400
        await db.log_fact_compression(-100, 1, "старая запись", None, "supersede")
        await db.db.execute(
            "UPDATE graph_fact_compressions SET created_at = ? "
            "WHERE reason = 'supersede'", (old_ts,))
        await db.log_fact_compression(-100, 2, "свежая запись", None, "forget")
        await db.db.commit()
        svc, _ = _service(db, MergeLLM())
        await svc.review()
        cursor = await db.db.execute(
            "SELECT fact_before FROM graph_fact_compressions")
        rows = await cursor.fetchall()
        assert [r["fact_before"] for r in rows] == ["свежая запись"]

    @pytest.mark.asyncio
    async def test_review_never_raises_on_broken_db(self, db):
        """Пересмотр НЕ бросает (любая ошибка → WARNING)."""

        class BrokenDB(DatabaseService):
            async def find_exact_dup_groups(self, *args, **kwargs):
                raise RuntimeError("бд сломалась")

        broken = BrokenDB.__new__(BrokenDB)
        broken.__dict__.update(db.__dict__)
        broken.find_exact_dup_groups = AsyncMock(side_effect=RuntimeError("x"))
        svc, _ = _service(broken, MergeLLM())
        await svc.review()                       # не падает


class TestEpisodeMergeImportancePenalty:
    """S10.18-35 (F5, ADR-1018-5 D2/D3): эпи-мерж не «отменяет» F5-пенальти —
    кластер из мета-фактов (imp=1) даёт слитую строку imp=1, а не
    rule_importance('chat_history')=4; обычный кластер не затронут."""

    @pytest.mark.asyncio
    async def test_merge_of_metafacts_keeps_penalty(self, db):
        from services.graph_stoplist import METAFACT_PENALTY_IMPORTANCE
        for obj in ("видеосообщение", "голосовое"):
            await db.insert_graph_fact(
                -100, f"вася отправил {obj}", "chat_history", None,
                subject="вася", object=obj)               # imp=1 (F5-срез)
        llm = MergeLLM(response="вася отправил видеосообщение и голосовое")
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute(
            "SELECT importance, fact FROM graph_facts ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        assert row["fact"] == "вася отправил видеосообщение и голосовое"
        assert row["importance"] == METAFACT_PENALTY_IMPORTANCE   # 1, не 4

    @pytest.mark.asyncio
    async def test_merge_of_normal_facts_unchanged(self, db):
        for obj in ("открытку", "письмо"):
            await db.insert_graph_fact(
                -100, f"вася отправил {obj}", "chat_history", None,
                subject="вася", object=obj)               # imp=4 (rule_importance)
        llm = MergeLLM(response="вася отправил открытку и письмо")
        svc, _ = _service(db, llm)
        assert await svc.merge_episodes() == 1
        cursor = await db.db.execute(
            "SELECT importance FROM graph_facts ORDER BY id DESC LIMIT 1")
        assert (await cursor.fetchone())["importance"] == 4   # прежнее поведение
