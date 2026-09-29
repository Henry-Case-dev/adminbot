"""MCA Wave 1 (`mca-04a-provenance-contract`, round 10.27) — контракт
происхождения памяти (ADR-1027-6 D1–D13).

Покрытие:
  * v17: 3 таблицы + 6 nullable-колонок `graph_facts` + индексы; аддитивно/
    идемпотентно; backfill — только прямые ссылки (`original` только при
    сохранённом `tg_message_id`, иначе `unknown`); старые ID/FTS сохранены;
  * SourceRef типизирован (store/entity_type/entity_id/chat/revision; opaque,
    TG только для message); EvidenceLink 5 типов + полный набор полей;
  * статусы `original/reconstructed_support/tentative/unknown` + ОТДЕЛЬНЫЕ
    conflict/freshness/coverage; self-referential ≠ подтверждение (A10);
  * семантика личного факта: subject устойчивым ID, world_knowledge/бот не
    личный факт спрашивающего (A85), self-report/третье лицо;
  * восстановление §8.2: нет ложного `original` (A09), ambiguous → tentative,
    recon_support не переименовывается, факт не удаляется (A95);
  * FIX п.1 (target=asker→субъект), п.3 (Layer B person_facts), п.5-контракт
    (row-bound валидатор + локальные evidence→SourceRef) (A86/A88);
  * kill-switch OFF = паритет baseline; события MCA-13 + reason_code.
"""
import asyncio
import json

import pytest

from config.settings import Settings
from services import mca_events
from services import provenance as prov
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.dossier_prompts import filter_layer_a_candidates
from services.lore_worker import LoreWorker
from services.summary_aliases import AliasResolver

CHAT = -1004000000001


def _target_version() -> int:
    return max(s.version for s in DatabaseService.migration_steps())


async def _fresh(tmp_path, name="mca04a.db") -> DatabaseService:
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _insert_smart(d, *, chat_id=CHAT, text, tg=None, user_id=1,
                        author_name="u", ts=1000):
    cur = await d.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
        "media_type, author_name, tg_message_id) VALUES (?,?,?,?,?,?,?)",
        (user_id, chat_id, text, ts, "text", author_name, tg))
    rid = cur.lastrowid
    if text:
        await d.db.execute(
            "INSERT INTO smart_messages_fts(rowid, text) VALUES (?, ?)",
            (rid, text))
    await d.db.commit()
    return rid


async def _fact_row(d, fact_id):
    cur = await d.db.execute(
        "SELECT id, fact, origin, target_user, status, subject_ref_id, "
        "attribution_method, assertion_kind, speaker_author_id, "
        "provenance_channel FROM graph_facts WHERE id = ?", (int(fact_id),))
    row = await cur.fetchone()
    return dict(row) if row is not None else None


async def _status_for_fact(d, chat_id, fact_id):
    ref = await prov.resolve_source_ref(
        d, prov.graph_fact_source_ref(chat_id, fact_id))
    if ref is None:
        return None
    return await prov.get_provenance_status(d, ref)


# ── T-3821: миграция v17 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_v17_registered_fresh_target(tmp_path):
    d = await _fresh(tmp_path)
    try:
        # MCA-07 (v18, ADR-1027-7 D12) поднял head до 18; v17-объекты сохранены.
        assert _target_version() == 19
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 19
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('mca_source_refs','mca_evidence_links','mca_provenance_status')")
        assert len(await cur.fetchall()) == 3
        cur = await d.db.execute("PRAGMA table_info(graph_facts)")
        cols = {r["name"] for r in await cur.fetchall()}
        assert {"subject_ref_id", "attribution_method", "assertion_kind",
                "speaker_author_id", "extractor_version",
                "provenance_channel"} <= cols
        cur = await d.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
            "('idx_mca_source_refs_dedup','idx_mca_source_refs_chat_type',"
            "'idx_mca_evidence_links_dedup','idx_mca_evidence_links_subject',"
            "'idx_mca_evidence_links_source','idx_graph_facts_subject_ref')")
        assert len(await cur.fetchall()) == 6
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v17_idempotent_noop(tmp_path):
    d = await _fresh(tmp_path, "idem.db")
    await d.close()
    d2 = DatabaseService(str(tmp_path / "idem.db"))
    await d2.initialize()
    try:
        cur = await d2.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] == 19   # MCA-07 v18 — head
        cur = await d2.db.execute("SELECT COUNT(*) FROM schema_migrations")
        first = (await cur.fetchone())[0]
        await d2.close()
        d3 = DatabaseService(str(tmp_path / "idem.db"))
        await d3.initialize()
        cur = await d3.db.execute("SELECT COUNT(*) FROM schema_migrations")
        assert (await cur.fetchone())[0] == first      # повтор — no-op
        cur = await d3.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = "
            "'mca_source_refs'")
        assert await cur.fetchone() is not None
        await d3.close()
    finally:
        pass


@pytest.mark.asyncio
async def test_v17_backfill_direct_only(tmp_path):
    """A09/SC-15: `original` только при прямом `tg_message_id`; иначе unknown;
    похожий текст НЕ создаёт ложный original; старые ID/FTS сохранены."""
    d = await _fresh(tmp_path, "backfill.db")
    try:
        chat = CHAT
        # похожее сообщение в чате (не должно использоваться backfill'ом)
        await _insert_smart(d, chat_id=chat, text="Питер", tg=888, user_id=7)
        # upgrade до v17 уже прошёл на пустой БД; снимаем v17 и повторяем.
        await d.db.executescript(
            "DELETE FROM mca_evidence_links; DELETE FROM mca_provenance_status; "
            "DELETE FROM mca_source_refs;")
        await d.db.commit()
        f_tg = await d.insert_graph_fact(
            chat, "Питер", "chat_history", None, tg_message_id=777)
        f_no = await d.insert_graph_fact(chat, "Москва", "chat_history", None)
        await d._migrate_provenance_v17_backfill()
        st_tg = await _status_for_fact(d, chat, f_tg)
        st_no = await _status_for_fact(d, chat, f_no)
        assert st_tg["origin_status"] == "original"
        assert st_no["origin_status"] == "unknown"      # нет ложного original
        assert st_no["conflict_status"] == "unknown"
        assert st_no["freshness_status"] == "unknown"
        # старые ID/FTS сохранены
        assert (await _fact_row(d, f_tg))["id"] == f_tg
        cur = await d.db.execute(
            "SELECT COUNT(*) FROM graph_facts_fts WHERE rowid = ?", (f_tg,))
        assert (await cur.fetchone())[0] == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_v17_backfill_preserves_legacy_columns(tmp_path):
    d = await _fresh(tmp_path, "legacy.db")
    try:
        chat = CHAT
        fid = await d.insert_graph_fact(
            chat, "старый факт", "chat_history", None, target_user="Иван",
            tg_message_id=5)
        await d._migrate_provenance_v17_backfill()
        row = await _fact_row(d, fid)
        assert row["target_user"] == "Иван"
        assert row["status"] == "confirmed"
    finally:
        await d.close()


# ── T-3822/T-3830: SourceRef / EvidenceLink контракт ────────────────────────

def test_source_ref_validation():
    prov.SourceRef("sqlite", "graph_fact", "1").validate()
    for bad in (
            prov.SourceRef("nope", "graph_fact", "1"),
            prov.SourceRef("sqlite", "nope", "1"),
            prov.SourceRef("sqlite", "graph_fact", ""),
            prov.SourceRef("sqlite", "graph_fact", "1", resolution="weird"),
            prov.SourceRef("sqlite", "graph_fact", "1", tg_message_id=9),
    ):
        with pytest.raises(ValueError):
            bad.validate()
    # tg_message_id допустим только для message
    prov.SourceRef("sqlite", "message", "1", tg_message_id=9).validate()


def test_entity_id_opaque_not_mixed():
    """SC-01/SC-02: entity_id локальный, ID разных пространств не сравниваются."""
    a = prov.SourceRef("sqlite", "graph_fact", "123")
    b = prov.SourceRef("postgres", "graph_fact", "123")
    c = prov.SourceRef("telegram", "user", "123")
    assert a.dedup_key != b.dedup_key and a.dedup_key != c.dedup_key
    assert a.dedup_key[:3] == ("sqlite", "graph_fact", "123")


@pytest.mark.asyncio
async def test_source_ref_get_or_create_and_link(tmp_path):
    d = await _fresh(tmp_path, "links.db")
    try:
        obj = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, 1))
        obj2 = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, 1))
        assert obj == obj2                                  # дедуп
        src = await prov.resolve_source_ref(
            d, prov.message_source_ref(chat_id=CHAT, entity_id="10",
                                       tg_message_id=77))
        assert isinstance(src, int) and src != obj
        for lt in ("derived_from", "supports", "contradicts", "mentions",
                   "supersedes"):
            await prov.add_evidence_link(d, prov.EvidenceLink(
                subject_ref_id=obj, source_ref_id=src, link_type=lt,
                method="direct_reference", verification="verified",
                independence="unknown", basis="b", established_at=1))
        links = await prov.get_evidence_links(d, obj)
        assert {l["link_type"] for l in links} == {
            "derived_from", "supports", "contradicts", "mentions", "supersedes"}
        assert all(l["extractor_version"] == prov.EXTRACTOR_VERSION
                   for l in links)
        assert all(l["basis"] == "b" for l in links)
    finally:
        await d.close()


def test_evidence_link_validation_and_checks():
    with pytest.raises(ValueError):
        prov.EvidenceLink(1, 1, "nope", "direct_reference").validate()
    with pytest.raises(ValueError):
        prov.EvidenceLink(1, 1, "supports", "nope").validate()
    checks = prov.normalize_checks({"author": "ok", "joke": "weird"})
    assert checks is not None
    decoded = json.loads(checks)
    assert decoded == {"author": "ok", "joke": "unknown"}


@pytest.mark.asyncio
async def test_a10_two_derivations_one_event(tmp_path):
    """A10: два вывода из одного события ≠ два независимых доказательства."""
    d = await _fresh(tmp_path, "a10.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="Иван любит кофе", tg=5,
                            user_id=7)
        f1 = await d.insert_graph_fact(CHAT, "Иван любит кофе",
                                       "chat_history", None, tg_message_id=5)
        f2 = await d.insert_graph_fact(CHAT, "Иван пьёт кофе",
                                       "chat_history", None, tg_message_id=5)
        r1 = await prov.record_fact_provenance(
            d, fact_id=f1, chat_id=CHAT, origin="chat_history",
            tg_message_id=5)
        r2 = await prov.record_fact_provenance(
            d, fact_id=f2, chat_id=CHAT, origin="chat_history",
            tg_message_id=5)
        assert r1["origin_status"] == r2["origin_status"] == "original"
        assert r1["source_ref_id"] == r2["source_ref_id"]      # один SourceRef
        links = (await prov.get_evidence_links(d, r1["object_ref_id"])
                 + await prov.get_evidence_links(d, r2["object_ref_id"]))
        assert prov.evidence_independent_count(links) == 1
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_bot_self_reply_not_confirmation(tmp_path):
    """A10/SC-07: ответ бота self_referential — не подтверждение."""
    d = await _fresh(tmp_path, "selfref.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="ответ бота", tg=9)
        fid = await d.insert_graph_fact(CHAT, "ответ бота", "bot_self_reply",
                                        None, tg_message_id=9)
        res = await prov.record_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, origin="bot_self_reply",
            tg_message_id=9)
        links = await prov.get_evidence_links(d, res["object_ref_id"])
        assert links[0]["independence"] == "self_referential"
        assert prov.evidence_independent_count(links) == 0
    finally:
        await d.close()


# ── T-3827: статусы и отдельные поля ────────────────────────────────────────

@pytest.mark.asyncio
async def test_statuses_are_separate_fields(tmp_path):
    d = await _fresh(tmp_path, "status.db")
    try:
        obj = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, 42))
        await prov.set_provenance_status(
            d, obj, origin_status="original", conflict_status="conflicting",
            freshness_status="stale", coverage_status="partial",
            coverage_covered=1, coverage_total=3)
        st = await prov.get_provenance_status(d, obj)
        # одно утверждение имеет источник И устарело (разные поля)
        assert st["origin_status"] == "original"
        assert st["conflict_status"] == "conflicting"
        assert st["freshness_status"] == "stale"
        assert st["coverage_status"] == "partial"
        assert st["coverage_covered"] == 1 and st["coverage_total"] == 3
        with pytest.raises(ValueError):
            await prov.set_provenance_status(d, obj, origin_status="bogus")
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_status_repeat_preserves_separate_fields(tmp_path):
    """D-MCA04A-4: повторная запись `origin_status` не затирает
    conflict/freshness/coverage (разные наблюдаемые поля, D5)."""
    d = await _fresh(tmp_path, "preserve.db")
    try:
        obj = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, 7))
        await prov.set_provenance_status(
            d, obj, origin_status="original", conflict_status="conflicting",
            freshness_status="stale", coverage_status="partial",
            coverage_covered=1, coverage_total=2)
        await prov.set_provenance_status(d, obj, origin_status="unknown")
        st = await prov.get_provenance_status(d, obj)
        assert st["origin_status"] == "unknown"
        assert st["conflict_status"] == "conflicting"    # не сброшено
        assert st["freshness_status"] == "stale"
        assert st["coverage_status"] == "partial"
        assert st["coverage_covered"] == 1 and st["coverage_total"] == 2
    finally:
        await d.close()


# ── T-3825: семантика личного факта ─────────────────────────────────────────

def test_classify_attribution_and_kind():
    assert prov.classify_attribution_method(
        origin="bot_self_reply", subject="bot", speaker=None) == "bot_self_reply"
    assert prov.classify_attribution_method(
        origin="chat_history", subject="Иван", speaker="Иван",
        participants=["Иван"]) == "self_report"
    assert prov.classify_attribution_method(
        origin="chat_history", subject="Пётр", speaker="Иван",
        participants=["Иван", "Пётр"]) == "third_party"
    assert prov.classify_attribution_method(
        origin="chat_history", subject="погода", speaker="Иван",
        participants=["Иван"]) == "world_knowledge"
    assert prov.classify_assertion_kind(
        "погода", participants=["Иван"]) == "world_knowledge"
    assert prov.classify_assertion_kind(
        "Иван", "любит кофе", participants=["Иван"]) == "preference"
    assert prov.classify_assertion_kind(
        "Иван", "живёт в Питере", participants=["Иван"]) == "biographical"


@pytest.mark.asyncio
async def test_subject_ref_stable_id_and_unresolved(tmp_path):
    d = await _fresh(tmp_path, "subject.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="привет", tg=1, user_id=555,
                            author_name="Иван")
        ref = await prov.resolve_subject_ref(d, CHAT, "Иван")
        assert ref.store == "telegram" and ref.entity_type == "user"
        assert ref.entity_id == "555" and ref.resolution == "resolved"
        miss = await prov.resolve_subject_ref(d, CHAT, "Незнакомец")
        assert miss.resolution == "unresolved"
        assert not str(miss.entity_id).isdigit()      # не выдуманный TG ID
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_same_name_not_merged(tmp_path):
    """A88/SC-11: одноимённые НЕ сливаются — при ≥2 различных `user_id`
    резолв = `unresolved` со стабильным канон-именем (без выдуманного TG ID);
    субъект-scope читатели не отдают «чужие» факты. Ловит регресс, который
    ранее легализовал слияние одноимённых."""
    d = await _fresh(tmp_path, "samename.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="a", tg=1, user_id=1,
                            author_name="Макс")
        await _insert_smart(d, chat_id=CHAT, text="b", tg=2, user_id=2,
                            author_name="Макс")
        ref = await prov.resolve_subject_ref(d, CHAT, "Макс")
        assert ref.resolution == "unresolved"          # неоднозначность
        assert ref.entity_id == "Макс"                 # стабильное имя-субъект
        assert not str(ref.entity_id).isdigit()        # не выдуманный TG ID
        ref2 = await prov.resolve_subject_ref(d, CHAT, "Макс")
        assert ref2.dedup_key == ref.dedup_key         # стабильно между вызовами
        # Факт Макса #1: субъект-scope по устойчивому ID не отдаёт его Максу #2.
        sref1 = await prov.resolve_source_ref(d, prov.user_source_ref(CHAT, 1))
        await d.insert_graph_fact(
            CHAT, "Макс любит кофе", "chat_history", None, target_user="Макс",
            subject_ref_id=sref1, attribution_method="self_report",
            assertion_kind="preference")
        import time
        now = int(time.time())
        own = await d.get_user_context_facts(CHAT, "Макс", 50, now, user_id=1)
        other = await d.get_user_context_facts(CHAT, "Макс", 50, now, user_id=2)
        assert [r["fact"] for r in own] == ["Макс любит кофе"]
        assert other == []                             # одноимённый не получил
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_self_report_uses_speaker_user_id(tmp_path):
    """B-MCA04A-1/self-report: субъект self-report — `user_id` говорящего, а
    не поиск по имени; одноимённый не получает чужой факт в subject-scope."""
    d = await _fresh(tmp_path, "selfreport_id.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="a", tg=1, user_id=1,
                            author_name="Макс")
        await _insert_smart(d, chat_id=CHAT, text="b", tg=2, user_id=2,
                            author_name="Макс")
        await d.insert_graph_fact(
            CHAT, "Макс любит кофе", "bot_direct_reply", None,
            target_user="Макс", subject="Макс", tg_message_id=2)
        svc = _make_direct(d)
        await svc._apply_fact_attribution(
            CHAT, "Макс", 0, tg_message_id=2, asker_user_id=2)
        cur = await d.db.execute(
            "SELECT subject_ref_id, speaker_author_id FROM graph_facts "
            "WHERE fact = 'Макс любит кофе'")
        row = await cur.fetchone()
        sref2 = await prov.resolve_source_ref(d, prov.user_source_ref(CHAT, 2))
        assert row["subject_ref_id"] == sref2      # говорящий #2, не #1
        assert row["speaker_author_id"] == 2
        import time
        now = int(time.time())
        own = await d.get_user_context_facts(CHAT, "Макс", 50, now, user_id=2)
        other = await d.get_user_context_facts(CHAT, "Макс", 50, now, user_id=1)
        assert [r["fact"] for r in own] == ["Макс любит кофе"]
        assert other == []
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_a85_world_knowledge_excluded_readers(tmp_path):
    """A85: общие знания не попадают в личные факты (UI/get_user_context/RAG)."""
    d = await _fresh(tmp_path, "a85.db")
    try:
        await d.insert_graph_fact(
            CHAT, "Земля вращается вокруг Солнца", "bot_direct_reply", None,
            target_user="Иван", assertion_kind="world_knowledge",
            attribution_method="world_knowledge")
        await d.insert_graph_fact(
            CHAT, "Иван любит кофе", "bot_direct_reply", None,
            target_user="Иван", assertion_kind="preference",
            attribution_method="self_report")
        import time
        now = int(time.time())
        ctx = await d.get_user_context_facts(CHAT, "Иван", 50, now)
        facts = [r["fact"] for r in ctx]
        assert "Иван любит кофе" in facts
        assert all("Солн" not in f for f in facts)
        card = await d.get_persona_card(CHAT, "Иван", 50, now)
        assert all("Солн" not in f for f in card["facts"])
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_a85_bot_self_reply_excluded(tmp_path):
    d = await _fresh(tmp_path, "a85b.db")
    try:
        await d.insert_graph_fact(
            CHAT, "бот утверждает про Ивана", "bot_self_reply", None,
            target_user="Иван")
        import time
        ctx = await d.get_user_context_facts(CHAT, "Иван", 50, int(time.time()))
        assert ctx == []
    finally:
        await d.close()


# ── T-3826: FIX п.1 — субъект-атрибуция direct-reply ────────────────────────

class _FakeMemory:
    pass


class _FakeLLM:
    async def generate(self, *a, **k):
        return "{}"


def _make_direct(d):
    return DirectChatService(_FakeMemory(), d, _FakeLLM(), AliasResolver("{}"),
                             bot_id=999)


@pytest.mark.asyncio
async def test_fix_p1_subject_attribution(tmp_path):
    """FIX п.1/SC-13: target=asker → субъект-атрибуция; world_knowledge не
    личный факт спрашивающего."""
    d = await _fresh(tmp_path, "fix1.db")
    try:
        f_wk = await d.insert_graph_fact(
            CHAT, "Земля круглая", "bot_direct_reply", None,
            target_user="Иван", subject="Земля", tg_message_id=1)
        f_self = await d.insert_graph_fact(
            CHAT, "Иван любит кофе", "bot_direct_reply", None,
            target_user="Иван", subject="Иван", tg_message_id=1)
        svc = _make_direct(d)
        await svc._apply_fact_attribution(CHAT, "Иван", 0)
        wk = await _fact_row(d, f_wk)
        sf = await _fact_row(d, f_self)
        assert wk["attribution_method"] == "world_knowledge"
        assert wk["assertion_kind"] == "world_knowledge"
        assert wk["target_user"] is None
        assert sf["attribution_method"] == "self_report"
        assert sf["assertion_kind"] in ("preference", "biographical")
    finally:
        await d.close()


# ── T-3826: FIX п.3 — Layer B person_facts независимо от портрета (A86) ─────

class _FakeStore:
    @property
    def pg(self):
        return None


@pytest.mark.asyncio
async def test_fix_p3_person_facts_saved_independent(tmp_path):
    """A86/SC-13: валидированный person_fact сохранён (subject ID + SourceRef)
    независимо от портрета; не повышен до confirmed; идемпотентен."""
    d = await _fresh(tmp_path, "fix3.db")
    try:
        worker = LoreWorker(store=_FakeStore(), db=d, llm=_FakeLLM(), bot_id=1)
        n = await worker._write_person_facts(
            CHAT, [{"target": "Иван", "kind": "person_fact",
                    "text": "живёт в Питере", "evidence": [1]}])
        assert n == 1
        cur = await d.db.execute(
            "SELECT id, status, subject_ref_id, provenance_channel "
            "FROM graph_facts WHERE fact = 'живёт в Питере'")
        rows = [dict(r) for r in await cur.fetchall()]
        assert len(rows) == 1
        assert rows[0]["status"] == "unconfirmed"
        assert rows[0]["provenance_channel"] == "dossier_layer_a"
        obj = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, rows[0]["id"]))
        st = await prov.get_provenance_status(d, obj)
        assert st is not None                            # объектный SourceRef
        # идемпотентность повторного прогона
        n2 = await worker._write_person_facts(
            CHAT, [{"target": "Иван", "kind": "person_fact",
                    "text": "живёт в Питере", "evidence": [1]}])
        assert n2 == 0
    finally:
        await d.close()


# ── T-3826: FIX п.5-контракт — row-bound валидатор (A88) ────────────────────

def test_fix_p5_filter_row_bounds():
    parsed = {"candidates": [
        {"kind": "person_fact", "target": "Иван", "text": "t",
         "evidence": [3]}]}
    out = filter_layer_a_candidates(parsed, ["Иван"], row_count=2)
    assert out["person_facts"] == []
    assert out["dropped"][0]["reason"] == "evidence_out_of_range"
    out = filter_layer_a_candidates(parsed, ["Иван"], row_count=5)
    assert len(out["person_facts"]) == 1
    out = filter_layer_a_candidates(parsed, ["Иван"], row_count=5,
                                    message_lookup=lambda n: False)
    assert out["dropped"][0]["reason"] == "evidence_missing"
    out = filter_layer_a_candidates(parsed, ["Иван"],
                                    message_lookup=lambda n: True)
    assert len(out["person_facts"]) == 1


@pytest.mark.asyncio
async def test_fix_p5_local_evidence_to_source_refs(tmp_path):
    """A88: одинаковый локальный номер в разных чанках — разные источники;
    out-of-range/чужой чат — невалидно (без выдуманного ID)."""
    d = await _fresh(tmp_path, "fix5.db")
    try:
        rows1 = [{"id": 10, "chat_id": CHAT, "tg_message_id": 1},
                 {"id": 11, "chat_id": CHAT, "tg_message_id": 2}]
        rows2 = [{"id": 12, "chat_id": CHAT, "tg_message_id": 3}]
        r1 = await prov.local_evidence_to_source_refs(
            d, chat_id=CHAT, window_rows=rows1, local_numbers=[1])
        r2 = await prov.local_evidence_to_source_refs(
            d, chat_id=CHAT, window_rows=rows2, local_numbers=[1])
        assert r1[0]["valid"] and r2[0]["valid"]
        assert r1[0]["source_ref_id"] != r2[0]["source_ref_id"]
        bad = await prov.local_evidence_to_source_refs(
            d, chat_id=CHAT, window_rows=rows1, local_numbers=[5])
        assert bad[0]["valid"] is False
        other = await prov.local_evidence_to_source_refs(
            d, chat_id=CHAT + 1, window_rows=rows1, local_numbers=[1])
        assert other[0]["valid"] is False
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_fix_p5_local_evidence_accepts_sqlite_row(tmp_path):
    """D-MCA04A-5: `local_evidence_to_source_refs` не ломается на `sqlite3.Row`
    (у Row нет `.get`) — читает поля по ключу."""
    d = await _fresh(tmp_path, "fix5row.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="msg", tg=42, user_id=5)
        cur = await d.db.execute(
            "SELECT id, chat_id, tg_message_id FROM smart_messages "
            "WHERE chat_id = ? ORDER BY id", (CHAT,))
        rows = await cur.fetchall()                      # sqlite3.Row
        out = await prov.local_evidence_to_source_refs(
            d, chat_id=CHAT, window_rows=rows, local_numbers=[1])
        assert out[0]["valid"] is True
        assert out[0]["source_ref_id"] is not None
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_fix_p5_extract_chunk_row_bound_wired(tmp_path, monkeypatch):
    """D-MCA04A-1: `_extract_chunk` прокидывает границы чанка в row-bound —
    evidence вне окна чанка отброшен, валидный сохранён."""
    import services.lore_worker as lw
    d = await _fresh(tmp_path, "wired.db")
    try:
        async def _budget_always(*a, **k):
            return True

        monkeypatch.setattr(lw, "_budget_ok", _budget_always)
        worker = LoreWorker(store=_FakeStore(), db=d, llm=_FakeLLM(), bot_id=1)

        async def _fake_call(chat_id, messages):
            return {"candidates": [
                {"kind": "person_fact", "target": "Иван", "text": "вне окна",
                 "evidence": [5]},
                {"kind": "person_fact", "target": "Иван", "text": "в окне",
                 "evidence": [2]},
            ], "discarded": []}

        worker._layer_a_call = _fake_call
        facts, memes = await worker._extract_chunk(
            CHAT, ["строка 1", "строка 2"], ["Иван"])
        assert [f["text"] for f in facts] == ["в окне"]
    finally:
        await d.close()


# ── T-3828/T-3829: восстановление (§8.2) ────────────────────────────────────

@pytest.mark.asyncio
async def test_reconstruct_exact_match_not_original(tmp_path):
    d = await _fresh(tmp_path, "recon.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="Питер", tg=1, user_id=7)
        fid = await d.insert_graph_fact(CHAT, "Питер", "chat_history", None)
        res = await prov.reconstruct_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, fact_text="Питер")
        assert res["origin_status"] == "reconstructed_support"
        assert res["method"] == "exact_search"
        st = await _status_for_fact(d, CHAT, fid)
        assert st["origin_status"] == "reconstructed_support"
        assert st["origin_status"] != "original"      # A09: нет ложного original
        # факт сохранён, ID неизменен
        assert (await _fact_row(d, fid))["id"] == fid
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_reconstruct_ambiguous_tentative(tmp_path):
    d = await _fresh(tmp_path, "recon2.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="Питер", tg=1, user_id=7)
        await _insert_smart(d, chat_id=CHAT, text="Питер", tg=2, user_id=8)
        fid = await d.insert_graph_fact(CHAT, "Питер", "chat_history", None)
        res = await prov.reconstruct_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, fact_text="Питер")
        assert res["origin_status"] == "tentative"
        st = await _status_for_fact(d, CHAT, fid)
        assert st["origin_status"] == "tentative"
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_reconstruct_no_rename_saved_source(tmp_path):
    """A09/SC-10: прямо сохранённое происхождение не переименовывается."""
    d = await _fresh(tmp_path, "recon3.db")
    try:
        await _insert_smart(d, chat_id=CHAT, text="Питер", tg=1, user_id=7)
        fid = await d.insert_graph_fact(CHAT, "Питер", "chat_history", None,
                                        tg_message_id=1)
        await prov.record_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, origin="chat_history",
            tg_message_id=1)
        st_before = await _status_for_fact(d, CHAT, fid)
        assert st_before["origin_status"] == "original"
        await prov.reconstruct_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, fact_text="Питер")
        st_after = await _status_for_fact(d, CHAT, fid)
        assert st_after["origin_status"] == "original"   # не переименован
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_reconstruction_inert_when_disabled(tmp_path, monkeypatch):
    d = await _fresh(tmp_path, "recon_off.db")
    try:
        monkeypatch.setattr(Settings, "MCA_EVIDENCE_RECONSTRUCTION_ENABLED",
                            False)
        fid = await d.insert_graph_fact(CHAT, "Питер", "chat_history", None)
        res = await prov.reconstruct_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, fact_text="Питер")
        assert res["origin_status"] == "unknown" and res["matched"] is False
    finally:
        await d.close()


# ── T-3823: producers — source_ids → derived_from ───────────────────────────

@pytest.mark.asyncio
async def test_producer_source_ids_typed(tmp_path):
    d = await _fresh(tmp_path, "producer.db")
    try:
        f1 = await d.insert_graph_fact(CHAT, "источник 1", "chat_history", None)
        f2 = await d.insert_graph_fact(CHAT, "источник 2", "chat_history", None)
        belief = await d.insert_graph_fact(
            CHAT, "убеждение", "derived_belief", None, kind="belief",
            source_ids=json.dumps([f1, f2]))
        made = await prov.record_source_ids_provenance(
            d, fact_id=belief, chat_id=CHAT, source_ids=[f1, f2])
        assert made == 2
        obj = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, belief))
        links = await prov.get_evidence_links(d, obj)
        assert len(links) == 2
        assert all(l["link_type"] == "derived_from" for l in links)
        # идемпотентность
        assert await prov.record_source_ids_provenance(
            d, fact_id=belief, chat_id=CHAT, source_ids=[f1, f2]) == 2
        assert len(await prov.get_evidence_links(d, obj)) == 2
    finally:
        await d.close()


# ── T-3830/T-3831: покрытие по утверждению (claim_key) — A95 ────────────────

@pytest.mark.asyncio
async def test_coverage_per_claim_key(tmp_path):
    """SC-09: одна подходящая фраза не подтверждает весь абзац; покрытие по
    каждому утверждению (`claim_key`) — partial при неполном покрытии."""
    d = await _fresh(tmp_path, "coverage.db")
    try:
        obj = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, 1))
        src = await prov.resolve_source_ref(
            d, prov.message_source_ref(chat_id=CHAT, entity_id="1",
                                       tg_message_id=1))
        for claim in ("claim_a", "claim_b"):
            await prov.add_evidence_link(d, prov.EvidenceLink(
                subject_ref_id=obj, source_ref_id=src, link_type="supports",
                method="exact_search", verification="verified",
                independence="independent", claim_key=claim,
                established_at=1))
        # третье утверждение не покрыто → partial (2 из 3)
        await prov.set_provenance_status(
            d, obj, origin_status="reconstructed_support",
            coverage_status="partial", coverage_covered=2, coverage_total=3)
        st = await prov.get_provenance_status(d, obj)
        assert st["coverage_status"] == "partial"
        links = await prov.get_evidence_links(d, obj)
        assert {l["claim_key"] for l in links} == {"claim_a", "claim_b"}
    finally:
        await d.close()


# ── T-3832/T-3833: события, kill-switch, R17 ────────────────────────────────

def test_provenance_reason_codes_registered():
    for code in ("provenance_linked", "provenance_unresolved", "evidence_invalid",
                 "provenance_reconstructed", "provenance_conflict"):
        assert code in mca_events.REASON_CODES


@pytest.mark.asyncio
async def test_reconstruct_emits_event(tmp_path):
    d = await _fresh(tmp_path, "event.db")
    try:
        mca_events.reset_pending()
        await _insert_smart(d, chat_id=CHAT, text="Питер", tg=1, user_id=7)
        fid = await d.insert_graph_fact(CHAT, "Питер", "chat_history", None)
        await prov.reconstruct_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, fact_text="Питер")
        assert mca_events.pending_size() >= 1
    finally:
        await d.close()
        mca_events.reset_pending()


@pytest.mark.asyncio
async def test_kill_switch_off_parity(tmp_path, monkeypatch):
    """SC-18: OFF = паритет baseline (SourceRef/links/статусы не создаются)."""
    d = await _fresh(tmp_path, "off.db")
    try:
        monkeypatch.setattr(Settings, "MCA_PROVENANCE_ENABLED", False)
        assert prov.provenance_enabled() is False
        assert prov.attribution_enabled() is False
        assert prov.reconstruction_enabled() is False
        fid = await d.insert_graph_fact(CHAT, "Питер", "chat_history", None,
                                        tg_message_id=1)
        res = await prov.record_fact_provenance(
            d, fact_id=fid, chat_id=CHAT, origin="chat_history",
            tg_message_id=1)
        assert res == {"object_ref_id": None, "source_ref_id": None,
                       "origin_status": "unknown"}
        cur = await d.db.execute("SELECT COUNT(*) FROM mca_source_refs")
        assert (await cur.fetchone())[0] == 0
        # читатели — прежнее name-scope поведение
        await d.insert_graph_fact(CHAT, "Иван любит кофе", "bot_direct_reply",
                                  None, target_user="Иван")
        import time
        ctx = await d.get_user_context_facts(CHAT, "Иван", 50, int(time.time()))
        assert [r["fact"] for r in ctx] == ["Иван любит кофе"]
    finally:
        await d.close()


@pytest.mark.asyncio
async def test_basis_r17_safe(tmp_path):
    """SC-17: basis — короткий, checks — коды (без сырого текста/CoT)."""
    d = await _fresh(tmp_path, "r17.db")
    try:
        obj = await prov.resolve_source_ref(
            d, prov.graph_fact_source_ref(CHAT, 1))
        src = await prov.resolve_source_ref(
            d, prov.message_source_ref(chat_id=CHAT, entity_id="1",
                                       tg_message_id=1))
        await prov.add_evidence_link(d, prov.EvidenceLink(
            subject_ref_id=obj, source_ref_id=src, link_type="supports",
            method="exact_search", verification="tentative",
            independence="independent",
            basis="x" * 500,
            checks={"author": "ok", "negation": "failed"}, established_at=1))
        links = await prov.get_evidence_links(d, obj)
        assert len(links[0]["basis"]) <= 160
        assert json.loads(links[0]["checks_json"])["negation"] == "failed"
    finally:
        await d.close()
