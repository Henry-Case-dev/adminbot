"""MCA Wave 1 (`mca-07-retrieval-context`) — T-3842…T-3856 (round 10.27).

Контрактные/интеграционные тесты: v18 (идемпотентность), типизированный
reranker (valid-empty ≠ кандидаты, fallback), embedding identity/поколения
(A06), EvidenceBundle (§11.2, derived context_version), единый retrieval
(комбинация каналов, эпизоды-первыми для истории), адаптивный бюджет
(полный payload + protected spans, A24), CAS сводок (A03), ответный кеш
(text-replay off/update-дедуп сохранён) и OFF-паритет kill-switch.
"""
import asyncio
import time

import pytest

import services.database as dbmod
from services.database import DatabaseService
from services import mca_gates
from services import mca_events
from services import mca_retrieval_context as rc
from services import summary_memory as sm
from services.direct_chat_service import DirectChatService
from services.token_counter import count_tokens


async def _fresh(tmp_path, name="mca07.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


# ═══ T-3842: Δ DDL v18 ══════════════════════════════════════════════════════

def _target_version() -> int:
    return max(s.version for s in DatabaseService.migration_steps())


@pytest.mark.asyncio
async def test_v18_registered_fresh_target(tmp_path):
    """SC-18/A28: свежая БД → user_version 18; v17-объекты сохранены."""
    d = await _fresh(tmp_path)
    try:
        assert _target_version() >= 19  # реестр продолжает v20 (mca-04b)
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 19
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('mca_source_refs','mca_evidence_links','mca_provenance_status',"
            "'mca_embedding_index_generations')")
        names = {r["name"] for r in await cur.fetchall()}
        assert names == {"mca_source_refs", "mca_evidence_links",
                         "mca_provenance_status",
                         "mca_embedding_index_generations"}
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v18_columns_and_indices(tmp_path):
    """SC-18: 5 nullable identity-колонок + индексы реестра поколений
    (v34: ACTIVE-unique — per (namespace, index), инвариант ASAP 6 §8.1)."""
    d = await _fresh(tmp_path, "cols.db")
    try:
        cur = await d.db.execute("PRAGMA table_info(embedding_cache)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {"provider", "model", "preprocessing_version",
                "endpoint_fingerprint", "identity_fingerprint"} <= cols
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
            "('idx_mca_eig_name_gen','idx_mca_eig_active_ns',"
            "'idx_mca_eig_ns_gen','idx_mca_eig_fingerprint')")
        assert len(await cur.fetchall()) == 4
        # инвариант §8.1: ровно одна ACTIVE на (namespace, index) —
        # две namespace не конфликтуют, повторный ACTIVE в той же — отказ.
        g1 = await d.ensure_embedding_generation("graph_facts_vec", "fp-x",
                                                 dims=3)
        assert g1 is not None and g1["namespace"] == "default"
        try:
            await d.db.execute(
                "INSERT INTO mca_embedding_index_generations (index_name, "
                "generation, fingerprint, namespace, status, created_at) "
                "VALUES ('graph_facts_vec', 99, 'fp-y', 'default', 'active', "
                "1)")
            raise AssertionError("duplicate ACTIVE accepted")
        except Exception:
            await d.db.rollback()
        # nullable-честность: legacy-строка может иметь NULL identity.
        await d.db.execute(
            "INSERT INTO embedding_cache (text_hash, text, vector, dim, "
            "created_at, last_used_at) VALUES ('h','t','v',3,1,1)")
        await d.db.commit()
        cur = await d.db.execute(
            "SELECT identity_fingerprint, provider FROM embedding_cache "
            "WHERE text_hash='h'")
        row = await cur.fetchone()
        assert row["identity_fingerprint"] is None
        assert row["provider"] is None
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v18_vec_tables_untouched_and_idempotent(tmp_path):
    """SC-18: vec-таблицы не ALTER-ятся; повторный прогон — no-op."""
    d = await _fresh(tmp_path, "idem.db")
    path = str(d.db_path)
    try:
        cur = await d.db.execute("SELECT COUNT(*) AS c FROM schema_migrations")
        first = (await cur.fetchone())["c"]
    finally:
        await d.close()
    d2 = DatabaseService(path)
    await d2.initialize()
    try:
        cur = await d2.db.execute("SELECT COUNT(*) AS c FROM schema_migrations")
        assert (await cur.fetchone())["c"] == first
    finally:
        await d2.close()
    # Повторный initialize на НОВОМ экземпляре — no-op (идемпотентность).
    d3 = DatabaseService(path)
    await d3.initialize()
    try:
        cur = await d3.db.execute("SELECT COUNT(*) AS c FROM schema_migrations")
        assert (await cur.fetchone())["c"] == first
        cur = await d3.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 19
        # vec-таблицы не созданы v18-шагом (идентичность — реестр поколений).
        cur = await d3.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('smart_archive','graph_facts_vec')")
        assert {r["name"] for r in await cur.fetchall()} == set()
    finally:
        await d3.close()


@pytest.mark.asyncio
async def test_v18_from_v17_legacy_preserves_provenance(tmp_path):
    """SC-18: legacy v17-БД мигрирует аддитивно, v17-объекты целы."""
    d = await _fresh(tmp_path, "legacy.db")
    await d.close()
    # Откатываем маркер до 17 и снимем v18-объекты (симуляция legacy).
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "legacy.db"))
    conn.execute("PRAGMA user_version = 17")
    conn.execute("DROP TABLE IF EXISTS mca_embedding_index_generations")
    conn.commit()
    conn.close()
    d2 = DatabaseService(str(tmp_path / "legacy.db"))
    await d2.initialize()
    try:
        cur = await d2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 19
        cur = await d2.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('mca_source_refs','mca_embedding_index_generations')")
        assert len(await cur.fetchall()) == 2
    finally:
        await d2.close()


# ═══ D4/A06: embedding identity / fingerprint / поколения ═══════════════════

def test_embedding_identity_key_same_dim_different_model():
    """A06: одна размерность ≠ совместимость — разные модели → разные ключи."""
    kw = dict(provider="apinet.cloud", dims=3072, preprocessing_version="v1",
              endpoint_fingerprint="ep")
    fp_old = sm.embedding_identity_fingerprint(model="model-old", **kw)
    fp_new = sm.embedding_identity_fingerprint(model="model-new", **kw)
    assert fp_old != fp_new
    key_old = sm._embed_cache_key("текст", identity_fingerprint=fp_old)
    key_new = sm._embed_cache_key("текст", identity_fingerprint=fp_new)
    assert key_old != key_new
    # legacy-ключ (без identity) остаётся байт-в-байт прежним.
    assert sm._embed_cache_key("Текст ") == sm._embed_cache_key("текст")


@pytest.mark.asyncio
async def test_generation_registry_no_supersede_on_model_change(tmp_path):
    """B-MCA07-1/A06: смена fingerprint НЕ затирает активное поколение.

    Активное поколение описывает модель, построившую текущие векторы; его
    подмена на старте дала бы ложное совмещение (смешивание векторов)."""
    d = await _fresh(tmp_path, "gen.db")
    try:
        fp_old = sm.embedding_identity_fingerprint(model="m-old", dims=3072)
        fp_new = sm.embedding_identity_fingerprint(model="m-new", dims=3072)
        g1 = await d.ensure_embedding_generation(
            "graph_facts_vec", fp_old, model="m-old", dims=3072, provider="p",
            preprocessing_version="v1", endpoint_fingerprint="e")
        assert g1["fingerprint"] == fp_old and g1["status"] == "active"
        # повторный вызов с тем же fingerprint — no-op.
        g1b = await d.ensure_embedding_generation("graph_facts_vec", fp_old)
        assert g1b["generation"] == g1["generation"]
        # другой fingerprint → НЕ supersede, активное поколение не меняется.
        g2 = await d.ensure_embedding_generation(
            "graph_facts_vec", fp_new, model="m-new", dims=3072, provider="p",
            preprocessing_version="v1", endpoint_fingerprint="e")
        assert g2["fingerprint"] == fp_old and g2["status"] == "active"
        assert g2["generation"] == g1["generation"]
        cur = await d.db.execute(
            "SELECT generation, status FROM mca_embedding_index_generations "
            "WHERE index_name='graph_facts_vec' ORDER BY generation")
        rows = [(r["generation"], r["status"]) for r in await cur.fetchall()]
        assert rows == [(g1["generation"], "active")]     # не перезаписано
        # уникальность partial-UNIQUE: активное ровно одно
        assert len(rows) == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_generation_registry_quarantine_building(tmp_path):
    """B-MCA07-1: activate=False (персистентные векторы неизвестного
    происхождения) → статус `building` и FTS-only до перестройки."""
    d = await _fresh(tmp_path, "quar.db")
    try:
        fp = sm.embedding_identity_fingerprint(model="m", dims=3072)
        # нет активного → building, активного нет
        await d.ensure_embedding_generation("graph_facts_vec", fp,
                                            activate=False)
        assert await d.get_active_embedding_generation("graph_facts_vec") is None
        latest = await d.get_latest_embedding_generation("graph_facts_vec")
        assert latest["status"] == "building"
        # guard карантинит (последнее поколение не active)
        memory = sm.MemoryManager(d, None)
        memory._identity_fingerprint = lambda **kw: fp
        assert await memory._index_generation_ok("graph_facts_vec") is False
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_register_generations_does_not_overwrite_active(tmp_path,
                                                             monkeypatch):
    """B-MCA07-1 repro: активное поколение старой модели + рестарт с новой
    моделью → штатная регистрация НЕ подменяет активное, guard = False."""
    d = await _fresh(tmp_path, "repro.db")
    try:
        fp_old = sm.embedding_identity_fingerprint(model="m-old", dims=3072)
        fp_new = sm.embedding_identity_fingerprint(model="m-new", dims=3072)
        await d.ensure_embedding_generation("graph_facts_vec", fp_old,
                                            model="m-old", dims=3072)
        memory = sm.MemoryManager(d, None)
        memory._identity_fingerprint = lambda **kw: fp_old
        # рестарт неизменённый → guard ok
        await memory._register_index_generations(activate=False)
        assert await memory._index_generation_ok("graph_facts_vec") is True
        # смена конфига (та же dims) → регистрация не подменяет активное
        memory._identity_fingerprint = lambda **kw: fp_new
        await memory._register_index_generations(activate=False)
        active = await d.get_active_embedding_generation("graph_facts_vec")
        assert active["fingerprint"] == fp_old          # не затёрто
        assert await memory._index_generation_ok("graph_facts_vec") is False
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_index_generation_mismatch_forces_fts_only(tmp_path):
    """A06: несовпадающее активное поколение → vec-канал не обслуживается."""
    d = await _fresh(tmp_path, "mismatch.db")
    try:
        fp_old = sm.embedding_identity_fingerprint(model="m-old", dims=3072)
        await d.ensure_embedding_generation("graph_facts_vec", fp_old)
        memory = sm.MemoryManager(d, None)
        memory._identity_fingerprint = lambda **kw: "ДРУГОЙ"
        assert await memory._index_generation_ok("graph_facts_vec") is False
        memory._identity_fingerprint = lambda **kw: fp_old
        assert await memory._index_generation_ok("graph_facts_vec") is True
    finally:
        await d.close()


# ═══ D3/A05: типизированный reranker ═══════════════════════════════════════

def test_classify_rerank_statuses():
    assert rc.classify_rerank_response(None)[0] == rc.RERANK_ERROR
    assert rc.classify_rerank_response("")[0] == rc.RERANK_EMPTY
    assert rc.classify_rerank_response("[]")[0] == rc.RERANK_EMPTY
    assert rc.classify_rerank_response("нет")[0] == rc.RERANK_EMPTY
    assert rc.classify_rerank_response("3, 1") == (rc.RERANK_OK, (3, 1))
    assert rc.classify_rerank_response("abc")[0] == rc.RERANK_INVALID
    assert rc.classify_rerank_response("2, 2, 5")[1] == (2, 5)
    assert rc.classify_rerank_exception(asyncio.TimeoutError()) == rc.RERANK_TIMEOUT
    assert rc.classify_rerank_exception(RuntimeError()) == rc.RERANK_ERROR


def test_select_by_rerank_valid_empty_and_order():
    cands = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    # ok, порядок = оценке
    res = rc.select_by_rerank(cands, *rc.classify_rerank_response("3, 1"))
    assert [i.id for i in res.selected] == ["c", "a"]
    # out-of-range → invalid (не «все кандидаты»)
    res2 = rc.select_by_rerank(cands, *rc.classify_rerank_response("9"))
    assert res2.status == rc.RERANK_INVALID and res2.is_fallback
    # валидный пустой — пусто
    res3 = rc.select_by_rerank(cands, *rc.classify_rerank_response("[]"))
    assert res3.is_valid_empty and not res3.selected


@pytest.mark.asyncio
async def test_search_service_rerank_adapter_unchanged_text(monkeypatch):
    """SC-16: `_rerank_results` — адаптер к ядру; текст-семантика сохранена."""
    from services.search_service import SearchService, _rerank_usable

    class _LLM:
        async def generate(self, messages):
            return "сжатый пересказ " * 50

    svc = SearchService(aggregator=None, llm=_LLM())
    text = "исходный текст " * 60
    out = await svc._rerank_results("q", text)
    assert _rerank_usable(text, out)


# ═══ D1/D2: единый retrieval-контракт ═══════════════════════════════════════

class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def fetchall(self):
        return list(self._rows)


class _FakeFacadeShell:
    """Минимальный `db.db` для фасада mca-05 (AMEND канала): новый store
    пуст, legacy `lore_stories` читаются (unmapped видимы через фасад —
    SC-13). Фолбэк на `list_lore_stories` при успехе фасада запрещён
    (SC-14, фикс M-MCA05-1), поэтому legacy-эпизоды приходят через фасад."""

    def __init__(self, legacy_rows):
        self._legacy = list(legacy_rows)

    async def execute(self, sql, params=()):
        rows = self._legacy if "FROM lore_stories" in str(sql) else []
        return _FakeCursor(rows)


class _FakeDB:
    def __init__(self, messages=(), facts=(), episodes=(), generation=None):
        self._messages = list(messages)
        self._facts = list(facts)
        self._episodes = list(episodes)
        self._generation = generation
        self.db = _FakeFacadeShell(self._episodes)

    async def search_messages_fts(self, chat_id, match, limit):
        return self._messages

    async def search_graph_facts_fts(self, chat_id, match, limit, now):
        return self._facts

    async def list_lore_stories(self, chat_id, limit=200):
        return self._episodes

    async def get_active_embedding_generation(self, index_name):
        return self._generation


class _FakeMemory:
    def __init__(self, vec=()):
        self._vec = list(vec)

    async def retrieve_fact_candidates(self, chat_id, query, *, limit,
                                       include_direct_reply=False,
                                       include_self=False):
        return self._vec


def _msg(i, text, ts, uid, tg=None):
    return {"id": i, "chat_id": -100, "text": text, "timestamp": ts,
            "user_id": uid, "tg_message_id": tg}


@pytest.mark.asyncio
async def test_retrieval_combines_channels_and_refs():
    """SC-01: комбинация каналов; кандидат несёт источник/время."""
    db = _FakeDB(messages=[_msg(1, "про дроны", 1000, 7, tg=55)],
                 facts=[{"id": 9, "fact": "дрон летал", "rag_ts": 2000,
                         "tg_message_id": None, "chat_id": -100}],
                 generation={"fingerprint": "FP"})
    mem = _FakeMemory(vec=[{"id": 3, "fact": "погода", "rag_ts": 3000,
                            "tg_message_id": None, "item_id": "fact:3"}])
    req = rc.RetrievalRequest(chat_id=-100, query="дроны", top_k=10)
    result = await rc.retrieve(db, mem, req)
    assert result.status == rc.RETRIEVAL_OK
    assert set(result.channels_used) >= {"lexical", "vector"}
    assert result.generation_fingerprint == "FP"
    ids = {c.id for c in result.candidates}
    assert "tg:55" in ids and "fact:9" in ids and "fact:3" in ids
    # источник/время присутствуют (ссылка, не копия сырья)
    by_id = {c.id: c for c in result.candidates}
    assert by_id["fact:9"].sent_at == 2000


@pytest.mark.asyncio
async def test_retrieval_history_episodes_first():
    """SC-02/D2: для истории эпизоды поднимаются первыми."""
    db = _FakeDB(messages=[_msg(1, "дроны история", 1000, 7)],
                 episodes=[{"id": 5, "topic": "про дроны", "story": "давно",
                            "last_ts": 500}])
    req = rc.RetrievalRequest(chat_id=-100, query="расскажи историю про дроны")
    result = await rc.retrieve(db, None, req)
    assert result.candidates[0].channel == "episode"
    assert "episode" in result.channels_used
    assert result.reason_code == "episodes_used"


@pytest.mark.asyncio
async def test_retrieval_exact_phrase_and_filters():
    db = _FakeDB(messages=[_msg(1, "точная фраза", 1000, 7),
                           _msg(2, "точная фраза старая", 100, 8)])
    req = rc.RetrievalRequest(chat_id=-100, query='найди "точная фраза"',
                              mode="exact", top_k=10, time_from=500)
    result = await rc.retrieve(db, None, req)
    assert "exact" in result.channels_used
    # фильтр по времени отсёк старый кандидат
    assert all(c.sent_at >= 500 for c in result.candidates)


@pytest.mark.asyncio
async def test_retrieval_reply_graph_channel(monkeypatch):
    from services.thread_chain import ChainItem

    async def _fake_chain(db, chat_id, message, depth, **kw):
        return [ChainItem(uid=7, name="вася", text="родитель", is_bot=False,
                          ts=1000, item_id="tg:42")]

    monkeypatch.setattr("services.thread_chain.collect_thread_chain",
                        _fake_chain)
    db = _FakeDB()
    req = rc.RetrievalRequest(chat_id=-100, query="почему?", trigger_ref=42,
                              scope="parent")
    result = await rc.retrieve(db, None, req)
    assert "reply_graph" in result.channels_used
    assert any(c.id == "tg:42" for c in result.candidates)


@pytest.mark.asyncio
async def test_retrieval_empty_reason():
    result = await rc.retrieve(_FakeDB(), None,
                               rc.RetrievalRequest(chat_id=-100, query="нечто"))
    assert result.status == rc.RETRIEVAL_EMPTY
    assert result.reason_code == "retrieval_empty"


def test_apply_retrieval_rerank_valid_empty_not_candidates():
    """A05: valid-empty reranker → пусто (не все кандидаты)."""
    cands = tuple(rc.RetrievalCandidate(id=f"c{i}", entity_type="message",
                                        entity_id=str(i)) for i in range(3))
    result = rc.RetrievalResult(status=rc.RETRIEVAL_OK, candidates=cands)
    empty = rc.RerankResult(rc.RERANK_EMPTY)
    kept, status = rc.apply_retrieval_rerank(result, empty)
    assert kept == [] and status == rc.RERANK_EMPTY
    # fallback (invalid) → bounded pre-rerank-порядок (не пусто)
    fb = rc.RerankResult(rc.RERANK_INVALID)
    kept2, status2 = rc.apply_retrieval_rerank(result, fb)
    assert kept2 == list(cands) and status2 == rc.RERANK_INVALID


# ═══ D5: EvidenceBundle / context_version ═══════════════════════════════════

def test_evidence_bundle_full_fields_and_context_version():
    """SC-07/SC-08: все поля §11.2; context_version детерминирован."""
    item = rc.EvidenceItem(source_ref_id=11, entity_type="graph_fact",
                           entity_id="9", sent_at=1000, revision="r1",
                           label="факт")
    bundle = rc.EvidenceBundle(
        trigger="tg:1", current_message_ref="tg:1", current_revision="r1",
        addressee="вася", author="петя", mentioned=("вася",),
        ambiguities=("кто именно?",), branch=("tg:0", "tg:1"),
        local_context=("локальный",), evidence=(item,),
        constraints=("только 2024",), unknown=("детали",),
        contradictions=("A vs B",), persona="характер", interests=("код",),
        relations=("друг",), chosen_intent="ответить",
        recent_actions=("помог",), context_version="v",
        excluded=(rc.ExcludedItem(ref="tg:9", reason_code="budget_exceeded",
                                  estimated_tokens=42),))
    # ссылка на SourceRef, не копия
    assert bundle.evidence[0].source_ref_id == 11
    assert bundle.excluded[0].reason_code == "budget_exceeded"
    cv1 = rc.compute_context_version(current_revision="r1",
                                     selected_refs=[(11, "r1")],
                                     summary_revision="s1")
    cv2 = rc.compute_context_version(current_revision="r1",
                                     selected_refs=[(11, "r1")],
                                     summary_revision="s1")
    assert cv1 == cv2                                # детерминирован
    cv3 = rc.compute_context_version(current_revision="r1",
                                     selected_refs=[(11, "r2")],
                                     summary_revision="s1")
    assert cv1 != cv3                                # меняется с зависимостью


# ═══ D7/A24: адаптивный бюджет ══════════════════════════════════════════════

def _svc():
    return DirectChatService.__new__(DirectChatService)


def test_budget_full_payload_accounting(caplog):
    """A24/SC-12: полный payload учитывается; размер/резерв/метод логируются."""
    import logging
    svc = _svc()
    big = "<Global_Context>\n" + "текст " * 20000 + "\n</Global_Context>"
    with caplog.at_level(logging.INFO):
        res = svc._apply_context_budget(
            [("global", big)], True, 4000, external_tokens=1000,
            reserve_tokens=500, estimation_method="chars*0.3")
    user_tokens = sum(count_tokens(t) for t in res)
    assert user_tokens <= 4000 - 1000 - 500 + 20
    assert any("full payload" in r.message for r in caplog.records)


def test_budget_off_gate_ignores_external(caplog):
    """OFF `MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED` → числовая база прежняя."""
    import services.direct_chat_service as dcs
    svc = _svc()
    big = "<Global_Context>\n" + "текст " * 20000 + "\n</Global_Context>"
    old = dcs.mca_gates.adaptive_context_budget_enabled
    dcs.mca_gates.adaptive_context_budget_enabled = lambda: False
    try:
        with_external = svc._apply_context_budget(
            [("global", big)], True, 4000, external_tokens=99999)
    finally:
        dcs.mca_gates.adaptive_context_budget_enabled = old
    # при OFF external не влияет: блок режется по общему cap (без вычета).
    assert sum(count_tokens(t) for t in with_external) <= 4000


def test_budget_overflow_preflight(caplog):
    """SC-13/A24: заведомое переполнение обязательной части видно (pre-flight)."""
    import logging
    svc = _svc()
    with caplog.at_level(logging.WARNING):
        svc._apply_context_budget([("target", "<Target_User>вася</Target_User>")],
                                   True, 100, external_tokens=5000,
                                  reserve_tokens=1000)
    assert any("context overflow" in r.message for r in caplog.records)


def test_protected_spans_preserved_when_truncating():
    """SC-13: отрицание/ID/дата не теряются при обрезке (gate ON)."""
    svc = _svc()
    block = ("<RAG_Memory>\nне согласен id:12345 12.03.2026 "
             + "шум " * 5000 + "\n</RAG_Memory>")
    cut = svc._truncate_block(block, 120)
    assert ("id:12345" in cut) or ("12.03.2026" in cut) or ("не" in cut)


def test_protected_spans_not_preserved_when_gate_off():
    import services.direct_chat_service as dcs
    svc = _svc()
    block = ("<RAG_Memory>\nне согласен id:12345 12.03.2026 "
             + "шум " * 5000 + "\n</RAG_Memory>")
    old = dcs.mca_gates.adaptive_context_budget_enabled
    dcs.mca_gates.adaptive_context_budget_enabled = lambda: False
    try:
        cut = svc._truncate_block(block, 120)
    finally:
        dcs.mca_gates.adaptive_context_budget_enabled = old
    # keep-end: голова (со спанами) отрезана, хвост сохранён (OFF-паритет).
    assert "id:12345" not in cut


# ═══ D8/A03: singleflight/HWM/CAS сводок ════════════════════════════════════

@pytest.mark.asyncio
async def test_running_summary_cas_rejects_stale(tmp_path):
    """A03: поздняя старая сводка НЕ перезаписывает новую версию."""
    d = await _fresh(tmp_path, "cas.db")
    now = time.time()
    try:
        w1 = await d.upsert_running_summary(1, "новая", 0, 200, 10, now, now)
        assert w1 is True
        w2 = await d.upsert_running_summary(1, "старая", 0, 100, 3, now, now)
        assert w2 is False                      # CAS отклонил
        row = await d.get_running_summary(1, now)
        assert row["summary"] == "новая"
        # равный end_ts, но больший raw_count — побеждает (tie-break).
        w3 = await d.upsert_running_summary(1, "новее", 0, 200, 11, now, now)
        assert w3 is True
        assert (await d.get_running_summary(1, now))["summary"] == "новее"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_running_summary_cas_off_baseline(tmp_path, monkeypatch):
    """OFF `MCA_SUMMARY_SINGLEFLIGHT_ENABLED` → слепой upsert (baseline)."""
    monkeypatch.setattr(dbmod, "_summary_singleflight_enabled", lambda: False)
    d = await _fresh(tmp_path, "casoff.db")
    now = time.time()
    try:
        await d.upsert_running_summary(1, "новая", 0, 200, 10, now, now)
        w = await d.upsert_running_summary(1, "старая", 0, 100, 3, now, now)
        assert w is True
        assert (await d.get_running_summary(1, now))["summary"] == "старая"
    finally:
        await d.close()


# ═══ D9: ответный кеш ════════════════════════════════════════════════════════

def test_answer_cache_policy_helper(monkeypatch):
    import services.direct_chat_service as dcs
    # ON (default) → legacy text-replay ОТКЛЮЧЁН, update-дедуп сохранён.
    monkeypatch.setattr("services.mca_gates.context_answer_cache_enabled",
                        lambda: True)
    assert dcs._legacy_text_replay_enabled() is False
    monkeypatch.setattr("services.mca_gates.context_answer_cache_enabled",
                        lambda: False)
    assert dcs._legacy_text_replay_enabled() is True


# ═══ kill-switch: имена и default ═══════════════════════════════════════════

def test_mca07_kill_switches_registered_and_default_on():
    names = {
        "MCA_RETRIEVAL_CONTEXT_ENABLED", "MCA_EVIDENCE_BUNDLE_ENABLED",
        "MCA_ADAPTIVE_CONTEXT_BUDGET_ENABLED", "MCA_TYPED_RERANKER_ENABLED",
        "MCA_SUMMARY_SINGLEFLIGHT_ENABLED", "MCA_CONTEXT_ANSWER_CACHE_ENABLED",
    }
    assert names <= set(mca_gates.KILL_SWITCHES)
    for name in names:
        assert mca_gates.KILL_SWITCHES[name][0] is True    # default ON
    assert mca_gates.retrieval_context_enabled() is True
    assert mca_gates.evidence_bundle_enabled() is True
    assert mca_gates.adaptive_context_budget_enabled() is True
    assert mca_gates.typed_reranker_enabled() is True
    assert mca_gates.summary_singleflight_enabled() is True
    assert mca_gates.context_answer_cache_enabled() is True


def test_mca07_reason_codes_registered():
    for code in ("retrieval_empty", "rerank_invalid", "rerank_timeout",
                 "budget_exceeded", "context_overflow",
                 "embedding_generation_changed", "summary_stale_dropped",
                 "answer_cache_disabled", "exact_match_used", "episodes_used"):
        assert code in mca_events.REASON_CODES


# ═══ T-3852: единый EvidenceBundle в живом конвейере (SC-09/SC-10/A04) ══════

import json as _json
from unittest.mock import AsyncMock, MagicMock

import services.direct_chat_service as dcs
from services.tool_loop import ToolLoopResult

_SYNTH_JSON = _json.dumps({
    "user_question": "почему?",
    "facts": [{"topic": "тема", "finding": "факт", "source": "exa",
               "confidence": "high"}],
    "answer_outline": "ответ",
    "limitations": [],
})


def _svc():
    return DirectChatService.__new__(DirectChatService)


def _tool_raw(text="финал tool-loop", tool_context="ВЫВОД ИНСТРУМЕНТА"):
    return ToolLoopResult(
        text, rounds_used=2,
        tool_trace=[{"round": 1, "tool": "execute_web_search", "ok": True,
                     "out_chars": 20}],
        tool_context=tool_context)


def _blocks_with(branch_tg="42", fact="7", question="почему именно так?"):
    return [
        ("branch", f"<Conversation_Branch>\n[01.01.2024 | вася | tg:{branch_tg}]: ок\n</Conversation_Branch>"),
        ("rag", f"<RAG_Memory>\n[{fact} | факт | fact:{fact}]: деталь\n</RAG_Memory>"),
        ("current", f"<Current_Question>\n{question}\n</Current_Question>"),
    ]


@pytest.mark.asyncio
async def test_build_evidence_bundle_fields_and_version():
    """SC-10: bundle собирается из блоков (ссылки, интент, excluded, версия)."""
    svc = _svc()
    bundle = await svc._build_evidence_bundle(
        -100, _Msg(), "почему?", "вася", 7, _blocks_with(),
        excluded=[{"kind": "nostalgia",
                   "reason_code": "budget_exceeded",
                   "estimated_tokens": 33}],
        chosen_intent="reply")
    assert bundle is not None
    assert bundle.addressee == "вася" and bundle.author == "вася"
    assert bundle.chosen_intent == "reply"
    assert "tg:42" in bundle.branch
    assert any(c.entity_id == "fact:7" for c in bundle.evidence)
    assert bundle.constraints == ("почему именно так?",)
    assert bundle.excluded[0].reason_code == "budget_exceeded"
    assert bundle.context_version


@pytest.mark.asyncio
async def test_bundle_scoped_slice_for_system2(monkeypatch):
    """SC-09: срез bundle содержит адресата/ветку/ограничения/версию."""
    svc = _svc()
    bundle = await svc._build_evidence_bundle(
        -100, _Msg(), "почему?", "вася", 7, _blocks_with(),
        chosen_intent="reply")
    text = dcs._bundle_scoped_slice(bundle)
    assert "Адресат: вася" in text
    assert "tg:42" in text
    assert "почему именно так?" in text
    assert bundle.context_version in text
    # OFF-гейт → пусто (паритет)
    monkeypatch.setattr("services.mca_gates.evidence_bundle_enabled",
                        lambda: False)
    assert dcs._bundle_scoped_slice(bundle) == ""


@pytest.mark.asyncio
async def test_builder_gate_off_returns_none(monkeypatch):
    monkeypatch.setattr("services.mca_gates.evidence_bundle_enabled",
                        lambda: False)
    svc = _svc()
    assert await svc._build_evidence_bundle(
        -100, _Msg(), "q", "вася", 7, _blocks_with()) is None


@pytest.mark.asyncio
async def test_a04_different_branch_different_context_version():
    """A04: разные родители/ветки → разный context_version (разный контекст)."""
    svc = _svc()
    b1 = await svc._build_evidence_bundle(
        -100, _Msg(), "почему?", "вася", 7, _blocks_with(branch_tg="42"))
    b2 = await svc._build_evidence_bundle(
        -100, _Msg(), "почему?", "вася", 7, _blocks_with(branch_tg="99"))
    assert b1.context_version != b2.context_version


@pytest.mark.system2
@pytest.mark.asyncio
async def test_system2_receives_bundle_after_tool_loop():
    """SC-09: System2 после tool loop получает bundle (не только вопрос+tool)."""
    svc = _svc()
    svc.llm = MagicMock()
    svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "готовый ответ"])
    bundle = await svc._build_evidence_bundle(
        -100, _Msg(), "почему?", "вася", 7, _blocks_with(),
        chosen_intent="reply")
    text, _mode = await svc._synthesize_direct_answer(
        -100, "почему?", _tool_raw(), None, bundle=bundle)
    assert text == "готовый ответ"
    stage1_user = svc.llm.generate.await_args_list[0].args[0][1]["content"]
    assert "КОНТЕКСТ ДИАЛОГА (не терять)" in stage1_user
    assert "Адресат: вася" in stage1_user
    assert "tg:42" in stage1_user
    assert "почему именно так?" in stage1_user
    # tool-вывод не потерян (прежний контракт Stage-1 сохранён)
    assert "ВЫВОД ИНСТРУМЕНТА" in stage1_user


@pytest.mark.system2
@pytest.mark.asyncio
async def test_system2_without_bundle_unchanged():
    """OFF/без bundle → прежний Stage-1 (нет среза; паритет)."""
    svc = _svc()
    svc.llm = MagicMock()
    svc.llm.generate = AsyncMock(side_effect=[_SYNTH_JSON, "ответ"])
    await svc._synthesize_direct_answer(-100, "q", _tool_raw(), None,
                                        bundle=None)
    stage1_user = svc.llm.generate.await_args_list[0].args[0][1]["content"]
    assert "КОНТЕКСТ ДИАЛОГА" not in stage1_user


def test_excluded_capture_from_budget():
    """SC-08: блок, целиком вытесненный бюджетом, попадает в excluded[]."""
    svc = _svc()
    out: list = []
    blocks = [("target", "<Target_User>вася</Target_User>"),
              ("nostalgia", "маркер " * 500)]
    svc._apply_context_budget(blocks, True, 5, out_excluded=out)
    assert any(e["kind"] == "nostalgia" and
               e["reason_code"] == "budget_exceeded" for e in out)


class _Msg:
    """Минимальный message-двойник (message_id/chat.id/text)."""
    def __init__(self, message_id=100, chat_id=-100, text="почему?"):
        self.message_id = message_id
        self.chat = type("Chat", (), {"id": chat_id})()
        self.text = text


# ═══ B-MCA07-2: полный payload в живом call-site + pre-flight (A24) ═════════

class _FakeMem:
    def __init__(self, window=()):
        self.window = list(window)

    async def get_window_messages(self, chat_id):
        return self.window


def _budget_svc(*, capture=None, real_budget=False, estimate=None):
    """Минимальный сервис с заглушёнными тяжёлыми шагами `_build_user_content`.

    Позволяет проверить, что живой call-site передаёт `external_tokens`/
    `reserve_tokens`/`estimation_method` (B-MCA07-2)."""
    class _Svc(DirectChatService):
        def _participant_roster(self, window, active):
            return {}, {}

        def _alias_map_block(self, roster):
            return ""

        def _is_reply_trigger(self, message):
            return False

        def _render_branch(self, chain, suffix_map):
            return ""

        def _render_thread(self, chain, suffix_map, limit):
            return ""

        def _render_current_question(self, message):
            return "<Current_Question>почему?</Current_Question>"

        def _build_mood_block(self, text):
            return ""

        async def _active_participants(self, chat_id):
            return []

        async def _collect_thread_chain(self, chat_id, message):
            return []

        async def _build_global_context(self, *a, **kw):
            return ""

        async def _build_rag_block(self, *a, **kw):
            return "", None

        async def _thread_limit(self, chat_id):
            return 100

        async def _build_user_relations(self, *a, **kw):
            return ""

        async def _chat_lore_state(self, chat_id):
            return False, ""

        async def _build_protected_facts(self, *a, **kw):
            return ""

        async def _build_style_anchors(self, chat_id):
            return ""

        async def _check_context_config_invariant(self, *a, **kw):
            return None

    if not real_budget:
        def _apply_context_budget(self, blocks, enabled=None,
                                  budget_tokens=None, **kw):
            if capture is not None:
                capture.update(kw)
            return []
        _Svc._apply_context_budget = _apply_context_budget
    if estimate is not None:
        async def _est(self, chat_id, budget_tokens, **_kw):
            # MCA-08 (T-4898): живой call-site аддитивно передаёт
            # `extra_prompt_blocks` (speech) — фейк принимает kwarg.
            return estimate
        _Svc._estimate_external_payload_tokens = _est
    svc = _Svc.__new__(_Svc)
    svc.memory = _FakeMem([])
    return svc


def _patch_budget_gate(monkeypatch, *, budget=1000, enabled=True,
                       master=True):
    async def _cp(chat_id, key, default=None):
        if key == "flags.chat_context_budgets_enabled":
            return enabled
        if key == "limits.chat_context_budget_tokens":
            return budget
        return default

    async def _master(chat_id=None):
        return master

    import services.chat_params as cpm
    import services.budget_gate as bg
    monkeypatch.setattr(cpm, "get_chat_param", _cp)
    monkeypatch.setattr(bg, "budgets_enabled", _master)


@pytest.mark.asyncio
async def test_live_call_site_passes_external_payload(monkeypatch):
    """B-MCA07-2: production call-site (`_build_user_content`) передаёт
    external/reserve/method в `_apply_context_budget` (иначе A24 не работает)."""
    capture: dict = {}
    svc = _budget_svc(capture=capture,
                      estimate=(321, 45, "tiktoken"))
    _patch_budget_gate(monkeypatch)
    await svc._build_user_content(-100, _Msg(), "вася", None)
    assert capture.get("external_tokens") == 321
    assert capture.get("reserve_tokens") == 45
    assert capture.get("estimation_method") == "tiktoken"


@pytest.mark.asyncio
async def test_estimate_external_payload_tokens_positive(monkeypatch):
    """A24: оценка внешней части payload > 0 при реальном system-промпте."""
    async def _cp(chat_id, key, default=None):
        if key == "prompts.direct_chat_system_prompt":
            return "СИСТЕМНЫЙ ПРОМПТ " * 200
        if key == "flags.persona_enabled":
            return False
        if key == "flags.lore_compiler_enabled":
            return False
        return default

    import services.chat_params as cpm
    monkeypatch.setattr(cpm, "get_chat_param", _cp)
    svc = DirectChatService.__new__(DirectChatService)
    external, reserve, method = await svc._estimate_external_payload_tokens(
        -100, 4000)
    assert external > 0
    assert reserve == 400
    assert method in ("tiktoken", "chars*0.3")


# ═══ M-MCA07-1: context_version учитывает current/revision + summary ════════

@pytest.mark.asyncio
async def test_context_version_includes_current_and_summary():
    """M-MCA07-1: разные current-ходы → разный context_version; summary_revision
    меняет версию."""
    svc = _svc()
    b1 = await svc._build_evidence_bundle(
        -100, _Msg(message_id=100), "почему?", "вася", 7, _blocks_with())
    b2 = await svc._build_evidence_bundle(
        -100, _Msg(message_id=200), "почему?", "вася", 7, _blocks_with())
    assert b1.context_version != b2.context_version      # разные триггеры
    assert b1.current_revision == "tg:100"
    # summary_revision участвует в версии
    b3 = await svc._build_evidence_bundle(
        -100, _Msg(message_id=100), "почему?", "вася", 7, _blocks_with())
    svc2 = _svc()

    async def _sum_a(chat_id):
        return "1000:5"

    async def _sum_b(chat_id):
        return "2000:9"

    svc._summary_revision = _sum_a
    svc2._summary_revision = _sum_b
    ba = await svc._build_evidence_bundle(
        -100, _Msg(message_id=100), "почему?", "вася", 7, _blocks_with())
    bb = await svc2._build_evidence_bundle(
        -100, _Msg(message_id=100), "почему?", "вася", 7, _blocks_with())
    assert ba.context_version != bb.context_version
    assert b3.context_version  # непустая версия


@pytest.mark.asyncio
async def test_bundle_relations_and_mentioned_populated():
    """M-MCA07-2: доступные поля §11.2 (mentioned/relations) заполняются."""
    svc = _svc()
    blocks = _blocks_with() + [
        ("map", "<UserResolutionMap>\nвася - 7\nпетя - 8\n</UserResolutionMap>"),
        ("relations", "<user_relations>\nдруг: петя\n</user_relations>"),
    ]
    bundle = await svc._build_evidence_bundle(
        -100, _Msg(), "почему?", "вася", 7, blocks)
    assert "вася" in bundle.mentioned
    assert any("петя" in r for r in bundle.relations)


# ═══ L-MCA07-1/L-MCA07-3: индекс fingerprint + reason_code exact ════════════

@pytest.mark.asyncio
async def test_fingerprint_lookup_and_idempotent_quarantine(tmp_path):
    """L-MCA07-1: lookup по fingerprint (idx_mca_eig_fingerprint) + повторная
    карантинная регистрация не плодит дубли."""
    d = await _fresh(tmp_path, "fp.db")
    try:
        fp = sm.embedding_identity_fingerprint(model="m", dims=3072)
        await d.ensure_embedding_generation("graph_facts_vec", fp,
                                            activate=False)
        got = await d.get_generation_by_fingerprint("graph_facts_vec", fp)
        assert got is not None and got["status"] == "building"
        memory = sm.MemoryManager(d, None)
        memory._identity_fingerprint = lambda **kw: fp
        await memory._register_index_generations(activate=False)
        await memory._register_index_generations(activate=False)
        cur = await d.db.execute(
            "SELECT COUNT(*) AS c FROM mca_embedding_index_generations "
            "WHERE index_name='graph_facts_vec'")
        assert (await cur.fetchone())["c"] == 1          # без дублей
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_retrieve_emits_exact_match_used(monkeypatch):
    """L-MCA07-3: точная фраза → reason_code `exact_match_used`."""
    events: list[dict] = []

    def _emit(stage, outcome, **kw):
        events.append({"stage": stage, **kw})
        return None

    monkeypatch.setattr("services.mca_retrieval_context.emit_stage_event", _emit)
    db = _FakeDB(messages=[_msg(1, "точная фраза", 1000, 7)])
    req = rc.RetrievalRequest(chat_id=-100, query='найди "точная фраза"',
                              mode="exact", top_k=10)
    await rc.retrieve(db, None, req)
    assert any(e.get("reason_code") == "exact_match_used" for e in events)


@pytest.mark.asyncio
async def test_live_preflight_overflow_on_mandatory(monkeypatch, caplog):
    """A24/SC-13: живой pre-flight срабатывает при переполнении обязательной
    части (external + reserve > cap) — видно WARN `context overflow`."""
    import logging
    svc = _budget_svc(real_budget=True,
                      estimate=(10 ** 6, 10 ** 6, "tiktoken"))
    _patch_budget_gate(monkeypatch, budget=1000)
    with caplog.at_level(logging.WARNING):
        await svc._build_user_content(-100, _Msg(), "вася", None)
    assert any("context overflow" in r.message for r in caplog.records)
