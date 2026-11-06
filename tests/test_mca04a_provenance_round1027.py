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

MEMORY-03 (C-2) — доказательства ребра (edge-evidence) на существующем
механизме `mca_source_refs`/`mca_evidence_links`:
  * `graph_edge`/`entity` адресуемы как предмет SourceRef, ревизия — константа
    `'stable'` (один SourceRef на ребро, R-13);
  * факт-write path регистрирует то же основание и для созданного ребра;
  * `mentions`/`cooccurrence`/`legacy_unknown` не подтверждают ребро (R-11) и
    не понижают ребро с проверенным корнем (R-12);
  * собственный вывод бота не подтверждает ребро (R-3), счётчик независимых
    корней — один на проект (данные и контракт не расходятся);
  * повторная обработка/инкремент веса не создают второй SourceRef;
  * транзитивность не выводится (R-5).
"""
import asyncio
import json

import pytest

from config.settings import Settings
from services import mca_events
from services import provenance as prov
from services import graphrag_provenance as grp
from services import relation_evidence as rel
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
        # MCA-07 (v18) → mca-17a (v19) → mca-04b (v20, ADR-1027-9) — head
        # продолжает реестр; v17-объекты сохранены при любом хвосте.
        assert _target_version() >= 19
        cur = await d.db.execute("PRAGMA user_version")
        assert (await cur.fetchone())[0] >= 19
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
        assert (await cur.fetchone())[0] >= 19   # реестр ≥ v19 (v20 — mca-04b)
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


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY-03 (C-2) — ребро, подтверждённое независимыми источниками
# ═══════════════════════════════════════════════════════════════════════════

async def _pair(d, *, chat=CHAT, subject="вася", target="петя",
                relation="спорил с", fact_text="вася спорил с петей",
                origin="chat_history", tg=None, with_fact=True,
                attribution_method=None, forward_from=""):
    """nodes + факт + ребро (как fact-write path: сначала факт, затем ребро)."""
    sid = await d.upsert_node(chat, subject, "fact", origin=origin)
    oid = await d.upsert_node(chat, target, "fact", origin=origin)
    fid = None
    if with_fact:
        fid = await d.insert_graph_fact(
            chat, fact_text, origin, None, tg_message_id=tg,
            forward_from=forward_from,
            attribution_method=attribution_method)
    await d.upsert_edge(sid, oid, relation, origin=origin, fact_id=fid)
    cursor = await d.db.execute(
        "SELECT id FROM edges WHERE chat_id = ? AND source_id = ? "
        "AND target_id = ? AND relation_type = ?", (chat, sid, oid, relation))
    eid = int((await cursor.fetchone())["id"])
    return sid, oid, fid, eid


async def _msg_ref(d, entity_id, *, chat=CHAT, tg=None):
    return await prov.resolve_source_ref(
        d, prov.message_source_ref(chat_id=chat, entity_id=str(entity_id),
                                   tg_message_id=tg))


async def _bump_edge_weight(d, eid):
    cursor = await d.db.execute(
        "SELECT source_id, target_id, relation_type, fact_id FROM edges "
        "WHERE id = ?", (int(eid),))
    row = await cursor.fetchone()
    await d.upsert_edge(row["source_id"], row["target_id"],
                        row["relation_type"], weight_increment=1,
                        fact_id=row["fact_id"])


async def _count_edge_refs(d, chat=CHAT, edge_id=None):
    sql = ("SELECT COUNT(*) FROM mca_source_refs WHERE store='sqlite' "
           "AND entity_type='graph_edge'")
    params: list = []
    if edge_id is not None:
        sql += " AND entity_id = ?"
        params.append(str(int(edge_id)))
    if chat is not None:
        sql += " AND COALESCE(chat_id, -1) = ?"
        params.append(int(chat))
    cursor = await d.db.execute(sql, params)
    return int((await cursor.fetchone())[0])


class TestEdgeEvidenceAddressing:
    @pytest.mark.asyncio
    async def test_graph_edge_and_entity_are_addressable_subjects(self, tmp_path):
        """§2.5: ребро/узел — предмет SourceRef; ревизия константна (R-13)."""
        assert {"graph_edge", "entity"} <= prov.ENTITY_TYPES
        edge_ref = prov.graph_edge_source_ref(CHAT, 7)
        node_ref = prov.node_source_ref(CHAT, 3)
        edge_ref.validate()
        node_ref.validate()
        assert edge_ref.entity_type == "graph_edge"
        assert node_ref.entity_type == "entity"
        assert edge_ref.revision == "stable" == node_ref.revision
        # повтор того же адреса — тот же dedup-key (никакой «новой ревизии»)
        assert (prov.graph_edge_source_ref(CHAT, 7).dedup_key
                == edge_ref.dedup_key)
        # другой чат — другой адрес: scope ребра не склеивается
        assert prov.graph_edge_source_ref(-5, 7).dedup_key != edge_ref.dedup_key

        d = await _fresh(tmp_path, "mem03_addr.db")
        try:
            first = await rel.resolve_edge_ref(d, CHAT, 7)
            second = await rel.resolve_edge_ref(d, CHAT, 7)
            assert first is not None and first == second
            assert await _count_edge_refs(d, edge_id=7) == 1
        finally:
            await d.close()


class TestEdgeEvidenceFromFactWrite:
    @pytest.mark.asyncio
    async def test_fact_write_path_attaches_edge_evidence(self, tmp_path):
        """MEM-03.2: у ребра то же основание, что у факта (без новых таблиц)."""
        d = await _fresh(tmp_path, "mem03_write.db")
        try:
            # Реальная атрибуция прямого утверждения автора (self_report):
            # именно она разрешает независимый корень (§2.3).
            _sid, _oid, fid, eid = await _pair(
                d, tg=101, attribution_method="self_report")
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="chat_history",
                attribution_method="self_report", tg_message_id=101)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 1
            assert (evidence["contract_independent_support"]
                    == evidence["independent_support"])
            assert evidence["status"] == "confirmed"
            assert len(evidence["sources"]) == 1
            source = evidence["sources"][0]
            assert source["origin_class"] == "explicit_direct"
            assert source["counts_as_independent"] is True
            assert source["link_type"] in ("derived_from", "supports")
            # ребро остаётся одной строкой edges с совместимым fact_id
            cursor = await d.db.execute(
                "SELECT fact_id FROM edges WHERE id = ?", (eid,))
            assert (await cursor.fetchone())["fact_id"] == fid
            links = await rel.edge_links(d, CHAT, eid)
            assert len(links) == 1 and links[0]["verification"] == "verified"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_fact_without_attribution_is_not_confirmed(self, tmp_path):
        """F1/§2.2: нет сигналов авторства → legacy_unknown, не подтверждение."""
        d = await _fresh(tmp_path, "mem03_noattr.db")
        try:
            _sid, _oid, fid, eid = await _pair(d, tg=111)   # ни perspective, ни method
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="chat_history",
                tg_message_id=111)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 0
            assert evidence["contract_independent_support"] == 0
            assert evidence["status"] == "unverified"
            source = evidence["sources"][0]
            assert source["origin_class"] == "legacy_unknown"
            assert source["counts_as_independent"] is False
            assert source["verification"] != "verified"
            assert source["independence"] != "independent"
            links = await rel.edge_links(d, CHAT, eid)
            assert links[0]["method"] != "direct_reference"
            assert links[0]["verification"] != "verified"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_perspective_other_is_reported_not_direct(self, tmp_path):
        """F1/§2.2: `perspective='other'` — пересказ о другом, не автор."""
        d = await _fresh(tmp_path, "mem03_other.db")
        try:
            _sid, _oid, fid, eid = await _pair(d, tg=121)
            await d.db.execute(
                "UPDATE graph_facts SET perspective = 'other' WHERE id = ?",
                (fid,))
            await d.db.commit()
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="chat_history",
                tg_message_id=121)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 0
            assert evidence["status"] != "confirmed"
            assert evidence["sources"][0]["origin_class"] == \
                "reported_third_party"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_world_knowledge_is_not_independent_root(self, tmp_path):
        """F1/§2.2: `world_knowledge` — утверждение о мире, не о человеке.

        Решение: класс `derived_with_lineage` (lineage — сообщение автора),
        запись `tentative`/`unknown` → независимым корнем не становится.
        Без адреса сообщения lineage не разрешён → `legacy_unknown`.
        """
        d = await _fresh(tmp_path, "mem03_world.db")
        try:
            _sid, _oid, fid, eid = await _pair(
                d, tg=131, attribution_method="world_knowledge",
                fact_text="ozon доставляет быстрее wildberries")
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="search_fact",
                attribution_method="world_knowledge", tg_message_id=131)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 0
            assert evidence["status"] != "confirmed"
            source = evidence["sources"][0]
            assert source["origin_class"] == "derived_with_lineage"
            assert source["counts_as_independent"] is False
            links = await rel.edge_links(d, CHAT, eid)
            assert links[0]["link_type"] == "derived_from"
            assert links[0]["verification"] != "verified"

            # lineage не разрешён (нет адреса сообщения): класс остаётся
            # `derived_with_lineage` по сигналу строки, но запись — `unknown`
            # без независимости (не выдумываем подтверждение).
            _s2, _o2, fid2, eid2 = await _pair(
                d, relation="дружит с", fact_text="ozon дружит с wb",
                tg=None, attribution_method="world_knowledge")
            await prov.record_fact_provenance(
                d, fact_id=fid2, chat_id=CHAT, origin="search_fact",
                attribution_method="world_knowledge")
            evidence2 = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid2)
            assert evidence2["independent_support"] == 0
            assert evidence2["status"] != "confirmed"
            assert evidence2["sources"][0]["counts_as_independent"] is False
            links2 = await rel.edge_links(d, CHAT, eid2)
            assert links2[0]["verification"] != "verified"
            assert links2[0]["independence"] != "independent"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_three_independent_sources_visible_on_edge_card(self, tmp_path):
        """§2.8: 3 независимых источника видны все, support=3."""
        d = await _fresh(tmp_path, "mem03_three.db")
        try:
            _sid, _oid, _fid, eid = await _pair(d)
            refs = [await _msg_ref(d, n, tg=n) for n in (201, 202, 203)]
            for ref in refs:
                await rel.attach_edge_evidence(
                    d, chat_id=CHAT, edge_id=eid, source_ref_id=ref,
                    link_type="supports", method="direct_reference",
                    verification="verified", independence="independent",
                    basis="direct reference", established_at=1000)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            shown = {s["source_ref_id"] for s in evidence["sources"]}
            assert shown == set(refs)
            assert evidence["independent_support"] == 3
            assert evidence["contract_independent_support"] == 3
            assert evidence["status"] == "confirmed"
            assert evidence["legacy_sources_count"] == 0
            # один SourceRef на ребро, N связей
            assert await _count_edge_refs(d, edge_id=eid) == 1
            view = await rel.build_relation_view(d, chat_id=CHAT, edge_id=eid)
            assert view.independent_support == 3
            assert len(view.sources) == 3
            assert view.status.value == "confirmed"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_mentions_only_never_confirmed(self, tmp_path):
        """R-11: `mentions` не подтверждает ни по весу, ни по частоте."""
        d = await _fresh(tmp_path, "mem03_mentions.db")
        try:
            _sid, _oid, _fid, eid = await _pair(d)
            for n in (301, 302):
                ref = await _msg_ref(d, n, tg=n)
                await rel.attach_edge_evidence(
                    d, chat_id=CHAT, edge_id=eid, source_ref_id=ref,
                    link_type="mentions", method="direct_reference",
                    verification="verified", independence="independent",
                    established_at=1000)
            # вес/частота не делают ребро подтверждённым (R-2/R-11)
            await _bump_edge_weight(d, eid)
            await _bump_edge_weight(d, eid)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 0
            assert evidence["mentions_only"] is True
            assert evidence["status"] == "unverified"
            assert evidence["has_unsupported_sources"] is True
            view = await rel.build_relation_view(d, chat_id=CHAT, edge_id=eid)
            assert view.independent_support == 0
            assert view.status.value != "confirmed"
            assert view.frequency > 1        # частота выросла, статус — нет
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_one_verified_root_with_two_legacy_stays_confirmed(
            self, tmp_path):
        """R-12/§2.8: legacy-основания считаются отдельно и НЕ понижают статус."""
        d = await _fresh(tmp_path, "mem03_legacy.db")
        try:
            _sid, _oid, _fid, eid = await _pair(d)
            verified = await _msg_ref(d, 401, tg=401)
            await rel.attach_edge_evidence(
                d, chat_id=CHAT, edge_id=eid, source_ref_id=verified,
                link_type="supports", method="direct_reference",
                verification="verified", independence="independent",
                basis="direct reference", established_at=1000)
            for n in (402, 403):
                ref = await _msg_ref(d, n, tg=n)
                await rel.attach_edge_evidence(
                    d, chat_id=CHAT, edge_id=eid, source_ref_id=ref,
                    link_type="derived_from", method="unknown",
                    verification="unknown", independence="unknown",
                    established_at=900)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 1
            assert evidence["legacy_sources_count"] == 2
            assert evidence["status"] == "confirmed"      # НЕ понижен
            assert len(evidence["sources"]) == 3          # все основания видны
            assert evidence["has_unsupported_sources"] is True
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_bot_self_output_never_corroborates_edge(self, tmp_path):
        """R-3: собственный вывод бота не подтверждает ребро."""
        d = await _fresh(tmp_path, "mem03_self.db")
        try:
            _sid, _oid, fid, eid = await _pair(d, tg=501)
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="bot_self_reply",
                tg_message_id=501)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert len(evidence["sources"]) == 1     # связь сохранена (аудит)
            source = evidence["sources"][0]
            assert source["independence"] == "self_referential"
            assert source["counts_as_independent"] is False
            assert evidence["independent_support"] == 0
            assert evidence["contract_independent_support"] == 0
            assert evidence["status"] != "confirmed"
            view = await rel.build_relation_view(d, chat_id=CHAT, edge_id=eid)
            assert view.status.value != "confirmed"
            # Повторный/«наивный» вызов того же писателя с сообщением человека
            # не поднимает поддержку: origin решает (R-3), а сообщение человека
            # источником реплики бота не становится.
            other_msg_row = await _insert_smart(d, text="а что коля?",
                                                tg=502)
            other = await _msg_ref(d, other_msg_row, tg=502)
            await rel.attach_fact_edge_evidence(
                d, chat_id=CHAT, fact_id=fid, source_ref_id=other,
                origin="bot_direct_reply", established_at=1000)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 0
            assert evidence["status"] != "confirmed"
            assert other not in {s["source_ref_id"]
                                 for s in evidence["sources"]}
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_repeat_processing_keeps_single_ref_and_links(self, tmp_path):
        """R-13/§2.4.1: повтор и инкремент веса не создают второй SourceRef."""
        d = await _fresh(tmp_path, "mem03_idem.db")
        try:
            # Прямое утверждение автора (`self_report`) — считаемый корень,
            # иначе проверялась бы не идемпотентность, а отсутствие основания.
            _sid, _oid, fid, eid = await _pair(
                d, tg=601, attribution_method="self_report")
            for _ in range(2):
                await prov.record_fact_provenance(
                    d, fact_id=fid, chat_id=CHAT, origin="chat_history",
                    attribution_method="self_report", tg_message_id=601)
            await _bump_edge_weight(d, eid)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert await _count_edge_refs(d, edge_id=eid) == 1
            assert len(await rel.edge_links(d, CHAT, eid)) == 1
            assert evidence["independent_support"] == 1
            assert len(evidence["sources"]) == 1
            cursor = await d.db.execute(
                "SELECT weight FROM edges WHERE id = ?", (eid,))
            assert int((await cursor.fetchone())["weight"]) == 2
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_no_transitive_edge_is_inferred(self, tmp_path):
        """R-5/MEM-03.7: A–B и B–C не дают A–C и не смешивают основания."""
        d = await _fresh(tmp_path, "mem03_trans.db")
        try:
            sid, _mid, fid_ab, eid_ab = await _pair(
                d, subject="вася", target="петя", relation="спорил с",
                fact_text="вася спорил с петей", tg=701)
            _mid2, tid, fid_bc, eid_bc = await _pair(
                d, subject="петя", target="коля", relation="дружил с",
                fact_text="петя дружил с колей", tg=702)
            await prov.record_fact_provenance(
                d, fact_id=fid_ab, chat_id=CHAT, origin="chat_history",
                tg_message_id=701)
            await prov.record_fact_provenance(
                d, fact_id=fid_bc, chat_id=CHAT, origin="chat_history",
                tg_message_id=702)
            cursor = await d.db.execute(
                "SELECT id FROM edges WHERE source_id = ? AND target_id = ?",
                (sid, tid))
            assert await cursor.fetchall() == []          # A–C не выведено
            ab = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid_ab)
            bc = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid_bc)
            assert len(ab["sources"]) == 1
            assert len(bc["sources"]) == 1
            assert ({s["source_ref_id"] for s in ab["sources"]}
                    != {s["source_ref_id"] for s in bc["sources"]})
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_verified_source_with_generic_method_stays_visible(
            self, tmp_path):
        """Считаемый корень обязан быть виден в карточке (данные == контракт)."""
        d = await _fresh(tmp_path, "mem03_method.db")
        try:
            _sid, _oid, _fid, eid = await _pair(d)
            ref = await _msg_ref(d, 451, tg=451)
            await rel.attach_edge_evidence(
                d, chat_id=CHAT, edge_id=eid, source_ref_id=ref,
                link_type="supports", method="exact_search",
                verification="verified", independence="independent",
                established_at=1000)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["unmapped_sources"] == []
            assert len(evidence["sources"]) == 1
            assert evidence["independent_support"] == 1
            assert (evidence["contract_independent_support"]
                    == evidence["independent_support"])
            view = await rel.build_relation_view(d, chat_id=CHAT, edge_id=eid)
            assert view.independent_support == 1
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_gate_off_writes_no_edge_evidence(self, tmp_path, monkeypatch):
        """§2.7: `MCA_PROVENANCE_ENABLED=OFF` — пишем/читаем как раньше."""
        monkeypatch.setattr(Settings, "MCA_PROVENANCE_ENABLED", False)
        d = await _fresh(tmp_path, "mem03_off.db")
        try:
            _sid, _oid, fid, eid = await _pair(d, tg=801)
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="chat_history",
                tg_message_id=801)
            assert await _count_edge_refs(d, chat=None) == 0
            assert await rel.edge_links(d, CHAT, eid) == []
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["sources"] == []
            assert evidence["independent_support"] == 0
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_third_party_retelling_is_not_independent_root(self, tmp_path):
        """§2.2/§2.3/MEM-03.4: пересказ третьего лица не создаёт новый корень."""
        d = await _fresh(tmp_path, "mem03_reported.db")
        try:
            _sid, _oid, fid, eid = await _pair(
                d, fact_text="сергей говорил, что вася спорил с петей",
                attribution_method="third_party", tg=901)
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="chat_history",
                attribution_method="third_party", tg_message_id=901)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["status"] != "confirmed"
            assert evidence["independent_support"] == 0
            source = evidence["sources"][0]
            assert source["origin_class"] == "reported_third_party"
            assert source["counts_as_independent"] is False
            assert source["verification"] != "verified"
            assert source["independence"] != "independent"
            links = await rel.edge_links(d, CHAT, eid)
            assert links[0]["method"] != "direct_reference"
            view = await rel.build_relation_view(d, chat_id=CHAT, edge_id=eid)
            assert view.status.value != "confirmed"
            assert view.independent_support == 0
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_two_reposts_of_one_post_do_not_double_count(self, tmp_path):
        """§2.8/R-4: два репоста одного первоисточника не дают двух корней."""
        d = await _fresh(tmp_path, "mem03_repost.db")
        try:
            _sid, _oid, fid1, eid = await _pair(
                d, fact_text="вася спорил с петей", tg=911,
                forward_from="канал X")
            fid2 = await d.insert_graph_fact(
                CHAT, "вася спорил с петей", "chat_history", None,
                tg_message_id=912, forward_from="канал X")
            await prov.record_fact_provenance(
                d, fact_id=fid1, chat_id=CHAT, origin="chat_history",
                tg_message_id=911)
            # второй репост того же первоисточника — основание ТОГО ЖЕ ребра
            await rel.attach_fact_edge_evidence(
                d, chat_id=CHAT, fact_id=fid2, edge_ids=[eid],
                established_at=1000)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] <= 1
            assert evidence["independent_support"] == 0
            assert evidence["status"] != "confirmed"
            classes = {s["origin_class"] for s in evidence["sources"]}
            assert classes == {"quote_forward"}
            assert all(not s["counts_as_independent"]
                       for s in evidence["sources"])
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_single_forward_does_not_confirm(self, tmp_path):
        """§2.8: репост сам по себе не подтверждает связь (счётчик + статус)."""
        d = await _fresh(tmp_path, "mem03_forward.db")
        try:
            _sid, _oid, fid, eid = await _pair(
                d, tg=921, forward_from="канал X")
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="chat_history",
                tg_message_id=921)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["independent_support"] == 0
            assert evidence["status"] != "confirmed"
            assert evidence["sources"][0]["origin_class"] == "quote_forward"
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_bot_origin_never_uses_human_message_as_source(self, tmp_path):
        """R-3/честная атрибуция: ответ бота не выдаётся за слова человека."""
        d = await _fresh(tmp_path, "mem03_bot_src.db")
        try:
            human_row = await _insert_smart(d, text="что нового про васю?",
                                            tg=931)
            human_ref = await _msg_ref(d, human_row, tg=931)
            _sid, _oid, fid, eid = await _pair(
                d, origin="bot_direct_reply",
                fact_text="вася спорил с петей", tg=931)
            await prov.record_fact_provenance(
                d, fact_id=fid, chat_id=CHAT, origin="bot_direct_reply",
                tg_message_id=931)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            shown = {s["source_ref_id"] for s in evidence["sources"]}
            assert human_ref not in shown          # человек не источник реплики бота
            assert evidence["independent_support"] == 0
            assert evidence["status"] != "confirmed"
            source = evidence["sources"][0]
            assert source["independence"] == "self_referential"
            assert source["kind"] == "graph_fact"
            links = await rel.edge_links(d, CHAT, eid)
            assert "бот" in (links[0]["basis"] or "").lower()
        finally:
            await d.close()

    @pytest.mark.asyncio
    async def test_bare_edge_reports_unestablished_origin(self, tmp_path):
        """R-7: ребро без основания — «Происхождение не установлено»."""
        d = await _fresh(tmp_path, "mem03_bare.db")
        try:
            _sid, _oid, _fid, eid = await _pair(d, with_fact=False)
            evidence = await rel.edge_evidence(d, chat_id=CHAT, edge_id=eid)
            assert evidence["sources"] == []
            assert evidence["bare_legacy"] is True
            assert evidence["independent_support"] == 0
            assert evidence["status"] == "unverified"
            view = await rel.build_relation_view(d, chat_id=CHAT, edge_id=eid)
            assert view.status.value == "unverified"
            assert view.explanation == "Происхождение не установлено"
            assert view.independent_support == 0
        finally:
            await d.close()


class TestOriginClassDerivation:
    """§2.2: класс происхождения выводится только из существующих сигналов."""

    def test_quote_forward_message(self):
        assert grp.classify_origin_class(
            entity_type="message",
            source_row={"is_forward": 1, "forward_source": "канал"},
            link_type="derived_from", method="direct_reference",
            verification="verified") == "quote_forward"

    def test_quote_forward_fact_uses_forward_from(self):
        assert grp.classify_origin_class(
            entity_type="graph_fact",
            source_row={"forward_from": "канал", "perspective": None},
            link_type="supports", method="direct_reference",
            verification="verified") == "quote_forward"

    def test_third_party_reported(self):
        assert grp.classify_origin_class(
            entity_type="graph_fact",
            source_row={"perspective": "third_party"},
            link_type="supports", method="direct_reference",
            verification="verified") == "reported_third_party"

    def test_self_report_is_explicit_direct(self):
        assert grp.classify_origin_class(
            entity_type="graph_fact",
            source_row={"perspective": "self",
                        "attribution_method": "self_report"},
            link_type="supports", method="direct_reference",
            verification="verified") == "explicit_direct"

    def test_lineage_channel(self):
        assert grp.classify_origin_class(
            entity_type="graph_fact",
            source_row={"provenance_channel": "dream"},
            link_type="derived_from", method="direct_reference",
            verification="verified") == "derived_with_lineage"

    def test_mentions_is_cooccurrence(self):
        assert grp.classify_origin_class(
            entity_type="message", source_row={}, link_type="mentions",
            method="direct_reference",
            verification="verified") == "cooccurrence"

    def test_no_signal_is_legacy_unknown(self):
        assert grp.classify_origin_class(
            entity_type="message", source_row={}, link_type="derived_from",
            method="unknown", verification="unknown") == "legacy_unknown"
        assert grp.classify_origin_class(
            entity_type=None, source_row=None, link_type="supports",
            method="unknown", verification="tentative") == "legacy_unknown"

    def test_verified_support_never_degrades_to_legacy(self):
        """Считаемый независимым корень не может «исчезнуть» как legacy."""
        for method in ("exact_search", "metadata", "semantic_search"):
            assert grp.classify_origin_class(
                entity_type="message", source_row={}, link_type="supports",
                method=method, verification="verified") == "explicit_direct"

    def test_class_values_match_contract_enum(self):
        from services.memory_contracts import OriginClass
        values = {c.value for c in OriginClass}
        assert {grp.ORIGIN_EXPLICIT_DIRECT, grp.ORIGIN_REPORTED_THIRD_PARTY,
                grp.ORIGIN_QUOTE_FORWARD, grp.ORIGIN_DERIVED_WITH_LINEAGE,
                grp.ORIGIN_COOCCURRENCE, grp.ORIGIN_LEGACY_UNKNOWN} == values
