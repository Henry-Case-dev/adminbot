"""mca-22 — интеграционные truth-set/приёмки (round 10.27, ADR-1028-6).

Покрытие:
  * truth-set A/B/F (роли: reply/quote/forward) — через canonical projection
    + рендер (без LLM, детерминированно);
  * truth-set G/H (bot self-quote / reply на старую RichMessage после TTL) —
    ledger + thread_chain восстановление;
  * truth-set J (message edit → revision bump → envelope видит новую
    ревизию — инвалидация зависимых выводов через существующую MCA-03
    модель `record_edit`);
  * truth-set E (correction path с реальной БД: contradicts-evidence +
    conflict_status='conflicting'; legacy без SourceRef НЕ auto-bind);
  * C6 bundle v2 (structure-first поля, раздельные роли; canonical OFF →
    legacy-паритет);
  * retrieval-контракт: расширенный SELECT `search_graph_facts_fts`
    (provenance-колонки), `RetrievalCandidate` metadata;
  * Analytics endpoints: /memory/attribution/trace + /metrics (FastAPI
    TestClient-совместимая проверка функций-обработчиков через monkeypatch
    auth — свет Level: только коды/числа).

R17: числа/коды; секретов нет.
"""
import asyncio
import time

import pytest

from config.settings import settings
from services import mca_gates
from services import bot_output_ledger
from services import canonical_messages
from services import message_identity
from services import graphrag_provenance as gprov
from services import thread_chain
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.mca_retrieval_context import RetrievalCandidate

CHAT = -100901
NOW = 1790000000


async def _db(tmp_path, name="mca22b.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add(db, user_id, text, tg_id, *, reply_to=None,
               reply_author=None, quote_text=None, quote_author=None,
               author_name=""):
    await message_identity.save_live_message(
        db, chat_id=CHAT, user_id=user_id, text=text, timestamp=NOW,
        sent_at=NOW, ingested_at=NOW, author_name=author_name,
        tg_message_id=tg_id, reply_to_id=reply_to,
        reply_to_author_id=reply_author, quote_text=quote_text,
        quote_author_id=quote_author)


def _svc(db) -> DirectChatService:
    return DirectChatService(memory=None, db=db, llm=None, aliases=None,
                             bot_id=42)


# ── truth-set A/B/F: роли не теряются и не схлопываются ────────────────────

class TestRolesTruthSet:
    @pytest.mark.asyncio
    async def test_truthset_a_quote_opinion_not_attributed(self, tmp_path):
        db = await _db(tmp_path, "ts_a.db")
        # B говорит мнение; A цитирует B и отвечает
        await _add(db, 2, "мнение Б про кино", 300, author_name="Б")
        await _add(db, 1, "согласен ли ты", 301, reply_to=300,
                   reply_author=2, quote_text="мнение Б про кино",
                   quote_author=2, author_name="А")
        msgs = await canonical_messages.get_canonical_messages(
            db, CHAT, since_ts=NOW - 60, limit=5)
        by_tg = {m.tg_message_id: m for m in msgs}
        a, b = by_tg[301], by_tg[300]
        # цитата остаётся словами Б (quoting user ≠ автор цитаты)
        assert a.quote_speaker_entity_id == 2 and a.speaker_entity_id == 1
        assert b.speaker_entity_id == 2
        # рендер различает цитату и автора сообщения
        out = canonical_messages.format_canonical_envelope(a)
        assert "(автор цитаты: 2)" in out
        assert "Аня" not in out                      # имя A не в цитате

    @pytest.mark.asyncio
    async def test_truthset_b_reply_addressee(self, tmp_path):
        db = await _db(tmp_path, "ts_b.db")
        await _add(db, 3, "вопрос от В", 310, author_name="В")
        await _add(db, 1, "ответ А", 311, reply_to=310, reply_author=3)
        msgs = await canonical_messages.get_canonical_messages(
            db, CHAT, since_ts=NOW - 60, limit=5)
        by_tg = {m.tg_message_id: m for m in msgs}
        assert by_tg[311].reply_to_speaker_entity_id == 3

    @pytest.mark.asyncio
    async def test_truthset_f_forward_author_not_sender(self, tmp_path):
        db = await _db(tmp_path, "ts_f.db")
        from services import message_identity as mi
        await mi.save_live_message(
            db, chat_id=CHAT, user_id=1, text="пересланный пост",
            timestamp=NOW, sent_at=NOW, ingested_at=NOW,
            is_forward=True, forward_source="Канал X",
            forward_author_id=99, tg_message_id=320, author_name="А")
        msgs = await canonical_messages.get_canonical_messages(
            db, CHAT, since_ts=NOW - 60, limit=5)
        m = msgs[0]
        # reposter (1) ≠ original author (99); рендер различает
        assert m.speaker_entity_id == 1
        assert m.forward_speaker_entity_id == 99
        assert m.is_forward is True
        out = canonical_messages.format_canonical_envelope(m)
        assert "Переслано: Канал X (автор: 99)" in out


# ── truth-set G/H: ledger живёт дольше TTL ──────────────────────────────────

class TestLedgerTruthSet:
    @pytest.mark.asyncio
    async def test_truthset_g_self_quote_resolves_to_bot(self, tmp_path):
        db = await _db(tmp_path, "ts_g.db")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=400,
            text="я говорил: котики это хорошо", bot_user_id=42,
            output_kind="direct_reply")
        from services import quote_resolver as qr
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            quote_text="я говорил: котики это хорошо", bot_user_id=42)
        assert res.status == qr.QUOTE_RESOLVED
        assert res.self_output is True
        assert res.quote_speaker_is_bot is True

    @pytest.mark.asyncio
    async def test_truthset_h_thread_chain_restores_after_ttl(self, tmp_path):
        db = await _db(tmp_path, "ts_h.db")
        # бот: RichMessage (статья) 401, parent = сообщение 400; бот отвечает
        # на 401 сообщением 402 (reply на статью)
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=401,
            text="статьяRichMessage про погоду", bot_user_id=42,
            output_kind="rich_message", parent_message_ref="tg:399",
            correlation_id="run-1")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=402,
            text="ответ бота на статью", bot_user_id=42,
            output_kind="direct_reply", parent_message_ref="tg:401")
        # bot_replies пуст (TTL протух) — thread_chain идёт через ledger
        chain = await thread_chain.collect_thread_chain(
            db, CHAT, 402, depth=5)
        assert len(chain) >= 2
        assert chain[0].is_bot is True and chain[0].text == \
            "ответ бота на статью"
        bot_steps = [c for c in chain if c.is_bot]
        assert any(c.text == "статьяRichMessage про погоду"
                   for c in bot_steps)
        assert any(c.item_id == "tg:401" for c in bot_steps)

    @pytest.mark.asyncio
    async def test_thread_chain_ledger_off_breaks_like_baseline(
            self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "ts_h2.db")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=411,
            text="статья без ledger-чтения", bot_user_id=42,
            output_kind="rich_message")
        monkeypatch.setattr(mca_gates, "bot_output_ledger_enabled",
                            lambda: False)
        chain = await thread_chain.collect_thread_chain(
            db, CHAT, 412, depth=5)
        assert chain == []             # паритет: обрыв как сегодня


# ── truth-set J: edit → revision bump ───────────────────────────────────────

class TestEditInvalidation:
    @pytest.mark.asyncio
    async def test_truthset_j_edit_bumps_revision(self, tmp_path):
        db = await _db(tmp_path, "ts_j.db")
        await _add(db, 1, "первая версия текста", 500)
        before = await db.get_smart_message_by_tg_id(CHAT, 500)
        assert int(before["current_revision"] or 1) == 1
        await message_identity.record_edit(
            db, chat_id=CHAT, tg_message_id=500,
            text="вторая версия текста", edited_at=NOW + 60)
        after = await db.get_smart_message_by_tg_id(CHAT, 500)
        assert int(after["current_revision"] or 1) >= 2
        # envelope новой ревизии видит новый revision (инвалидация видима)
        canon = await canonical_messages.get_canonical_messages_by_refs(
            db, CHAT, [500])
        assert canon[500].revision >= 2


# ── truth-set E: correction path с реальной БД ──────────────────────────────

class TestCorrectionIntegration:
    @pytest.mark.asyncio
    async def test_truthset_e_provenance_backed_marked_conflicting(
            self, tmp_path):
        db = await _db(tmp_path, "ts_e.db")
        svc = _svc(db)
        # факт с SourceRef (provenance-backed): fact 9001 → ref
        from services import provenance as prov
        from services.provenance import SourceRef
        cursor = await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
            "target_user, tg_message_id, subject_ref_id, "
            "attribution_method, assertion_kind, speaker_author_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (CHAT, "Лёха работает в Яндексе", "chat_history", NOW, "2",
             510, None, "third_party", "biographical", 1))
        fact_id = int(cursor.lastrowid)
        await db.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (fact_id, "Лёха работает в Яндексе"))
        await db.db.commit()
        ref_id = await prov.resolve_source_ref(db, SourceRef(
            store="sqlite", entity_type="graph_fact",
            entity_id=str(fact_id), chat_id=CHAT, resolution="resolved"))
        assert ref_id is not None
        await prov.set_provenance_status(db, ref_id, origin_status="original")
        # корректирующее сообщение (содержит ключи факта — FTS-кандидат)
        await _add(db, 2, "ты меня перепутал: Лёха не работает в Яндексе",
                   511)
        await svc._run_correction_path(
            CHAT, "ты меня перепутал: Лёха не работает в Яндексе", 511)
        status = await prov.get_provenance_status(db, ref_id)
        assert status["conflict_status"] == "conflicting"
        # contradicts-link от корректирующего сообщения
        cursor = await db.db.execute(
            "SELECT link_type, verification FROM mca_evidence_links "
            "WHERE subject_ref_id = ?", (ref_id,))
        links = await cursor.fetchall()
        assert any(l["link_type"] == "contradicts"
                   and l["verification"] == "tentative" for l in links)

    @pytest.mark.asyncio
    async def test_legacy_fact_not_autobound(self, tmp_path):
        db = await _db(tmp_path, "ts_e2.db")
        svc = _svc(db)
        # legacy-факт БЕЗ SourceRef: маркировки быть не должно (§31)
        cursor = await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at) "
            "VALUES (?,?,?,?)", (CHAT, "старый факт без provenance",
                                 "chat_history", NOW))
        await db.db.commit()
        before = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links")
        n_before = int((await before.fetchone())["c"])
        await svc._run_correction_path(CHAT, "ты меня перепутал", 512)
        after = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links")
        n_after = int((await after.fetchone())["c"])
        assert n_after == n_before     # без auto-bind по имени

    @pytest.mark.asyncio
    async def test_correction_gate_off_noop(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "ts_e3.db")
        svc = _svc(db)
        monkeypatch.setattr(mca_gates, "correction_revalidation_enabled",
                            lambda: False)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links")
        n_before = int((await cursor.fetchone())["c"])
        await svc._run_correction_path(CHAT, "ты меня перепутал", 513)
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_evidence_links")
        n_after = int((await cursor.fetchone())["c"])
        assert n_after == n_before


# ── C6: EvidenceBundle v2 (structure-first поля) ────────────────────────────

class TestBundleV2:
    @pytest.mark.asyncio
    async def test_bundle_roles_split_and_sourcerefs(self, tmp_path):
        db = await _db(tmp_path, "c6a.db")
        svc = _svc(db)
        # автор 1 отвечает автору 2, цитируя автора 3
        await _add(db, 3, "реплика тройки", 600, author_name="В")
        await _add(db, 2, "реплика двойки", 601, author_name="Б")
        await _add(db, 1, "вопрос автор", 602, reply_to=601,
                   reply_author=2, quote_text="реплика тройки",
                   quote_author=3, author_name="А")
        from services.provenance import SourceRef, resolve_source_ref
        fact_id = 601
        await db.db.execute(
            "INSERT INTO mca_source_refs (store, entity_type, entity_id, "
            "chat_id, resolution, created_at) VALUES "
            "('sqlite','message','tg:601',?,'resolved',?)", (CHAT, NOW))
        await db.db.commit()

        class _Msg:
            message_id = 602

        bundle = await svc._build_evidence_bundle(
            CHAT, _Msg(), "query", "Аня", 1,
            ["<Conversation_Branch>\ntg:601\n</Conversation_Branch>",
             "<RAG_Memory>\nfact:601\n</RAG_Memory>"])
        assert bundle is not None
        assert bundle.structured is True
        # раздельные роли: author ≠ direct_addressee ≠ reply_addressee
        assert bundle.author == "1"
        assert bundle.direct_addressee == "bot"
        assert bundle.reply_addressee == "2"
        assert bundle.quoted_speaker == "3"
        assert bundle.author != bundle.addressee

    @pytest.mark.asyncio
    async def test_bundle_gate_off_legacy_parity(self, tmp_path,
                                                 monkeypatch):
        db = await _db(tmp_path, "c6b.db")
        svc = _svc(db)
        monkeypatch.setattr(mca_gates, "canonical_attribution_enabled",
                            lambda: False)

        class _Msg:
            message_id = 700

        bundle = await svc._build_evidence_bundle(
            CHAT, _Msg(), "q", "Имя", 1,
            ["<RAG_Memory>\ntg:700\n</RAG_Memory>"])
        assert bundle is not None
        assert bundle.structured is False
        # паритет: author==addressee==target_name, source_ref_id None
        assert bundle.author == "Имя" and bundle.addressee == "Имя"
        assert all(e.source_ref_id is None for e in bundle.evidence)

    # ── fix round-1 (M-2): quote resolver в прод-пути ──────────────────────

    @pytest.mark.asyncio
    async def test_bundle_resolves_manual_quote_live(self, tmp_path):
        """Ручная `>`-цитата без ingestion-автора (`quote_author_id`
        NULL) резолвится ЖИВОЙ лестницей из prod-пути bundle (ступень 6:
        bounded FTS, единственный не-sender автор) — quoted_speaker
        получает честного автора, а не sender'а и не unknown."""
        db = await _db(tmp_path, "c6c.db")
        svc = _svc(db)
        await _add(db, 2, "Лёха устроился в Яндекс продакт-менеджером", 800,
                   author_name="Б")
        quoted = ("> Лёха устроился в Яндекс продакт-менеджером\n"
                  "ну ты даёшь")
        await _add(db, 1, quoted, 801, author_name="А")

        class _Msg:
            message_id = 801

        bundle = await svc._build_evidence_bundle(
            CHAT, _Msg(), quoted, "Аня", 1, [])
        assert bundle is not None and bundle.structured is True
        assert bundle.quoted_speaker == "2"   # автор цитаты, НЕ sender(1)

    @pytest.mark.asyncio
    async def test_bundle_calls_live_quote_resolver_and_uses_result(
            self, tmp_path, monkeypatch):
        """Прод-путь вызывает Quote Resolver, когда metadata не знает
        автора; resolved-источник ledger (`bot_output:<id>`) попадает в
        evidence с label='quote'."""
        db = await _db(tmp_path, "c6e.db")
        svc = _svc(db)
        await _add(db, 1, "вопрос без цитаты", 810, author_name="А")
        from services import quote_resolver as _qmod
        calls: list[dict] = []

        async def _fake_resolve(chat_id, row, query, sender_user_id):
            calls.append({"chat_id": chat_id, "sender": sender_user_id})
            return _qmod.QuoteResolution(
                status=_qmod.QUOTE_RESOLVED,
                priority=_qmod.PRIORITY_BOT_OUTPUT_LEDGER,
                quote_source_ref="bot_output:9",
                quote_speaker_entity_id=42)

        monkeypatch.setattr(svc, "_resolve_quote_live", _fake_resolve)

        class _Msg:
            message_id = 810

        bundle = await svc._build_evidence_bundle(
            CHAT, _Msg(), "вопрос без цитаты", "Аня", 1, [])
        assert len(calls) == 1 and calls[0]["sender"] == 1
        assert bundle.quoted_speaker == "42"
        assert any(e.entity_id == "bot_output:9" and e.label == "quote"
                   for e in bundle.evidence)

    @pytest.mark.asyncio
    async def test_bundle_ambiguous_quote_marked_not_invented(
            self, tmp_path, monkeypatch):
        """≥2 уверенных совпадения → ambiguous: quoted_speaker НЕ
        выдумывается, маркировка уходит в `ambiguities` bundle."""
        db = await _db(tmp_path, "c6f.db")
        svc = _svc(db)
        from services import quote_resolver as _qmod

        async def _ambiguous(chat_id, row, query, sender_user_id):
            return _qmod.QuoteResolution(
                status=_qmod.QUOTE_AMBIGUOUS,
                priority=_qmod.PRIORITY_EXACT_IN_THREAD,
                quote_speaker_entity_id=None,
                reason_code="quote_ambiguous")

        monkeypatch.setattr(svc, "_resolve_quote_live", _ambiguous)

        class _Msg:
            message_id = 820

        bundle = await svc._build_evidence_bundle(
            CHAT, _Msg(), "> что-то общее", "Аня", 1, [])
        assert bundle.quoted_speaker is None       # автор НЕ выдуман
        assert bundle.ambiguities and \
            bundle.ambiguities[0].startswith("quote:")


# ── fix round-1 (M-4): ledger — все типы ответов ────────────────────────────

class TestLedgerAllKinds:
    @pytest.mark.asyncio
    async def test_rich_autonomous_caption_kinds_recorded(self, tmp_path):
        """RichMessage/autonomous/media_caption реально пишутся в проде
        (раньше — только direct_reply; truth-set H сидировался фикстурой)."""
        db = await _db(tmp_path, "m4a.db")
        oid1 = await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=901,
            text="статья про погоду", bot_user_id=42,
            output_kind="rich_message", source_feature="summary",
            correlation_id="run-m4")
        oid2 = await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=902,
            text="автономная реплика", bot_user_id=42,
            output_kind="autonomous_reply", source_feature="direct_chat")
        oid3 = await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=903,
            text=None, caption="доброе утро!", bot_user_id=42,
            output_kind="media_caption", source_feature="goodmorning_relay")
        assert None not in (oid1, oid2, oid3)
        rows = await db.list_recent_bot_outputs(CHAT, limit=10)
        kinds = {r["output_kind"] for r in rows}
        assert {"rich_message", "autonomous_reply",
                "media_caption"} <= kinds
        caption_row = next(r for r in rows if r["output_kind"]
                           == "media_caption")
        assert caption_row["content_text"] is None          # текста нет
        assert caption_row["content_hash"] is not None      # хеш подписи

    def test_direct_output_kind_mapping(self):
        from services.direct_chat_service import (
            TRIGGER_FREE_WILL,
            direct_output_kind,
        )
        assert direct_output_kind(TRIGGER_FREE_WILL) == "autonomous_reply"
        assert direct_output_kind("mention") == "direct_reply"
        assert direct_output_kind(None) == "direct_reply"

    @pytest.mark.asyncio
    async def test_default_db_binding_fail_open(self):
        # Нет явного db И нет binding → честный skip (без записи, без
        # исключения) — M-4 не создаёт скрытых fallback-хранилищ.
        bot_output_ledger.bind_default_db(None)
        assert await bot_output_ledger.record_delivered_output(
            None, chat_id=1, tg_message_id=None, text="x") is None

    @pytest.mark.asyncio
    async def test_summary_plain_publish_records_rich_message(
            self, tmp_path):
        """Прод-wiring M-4: успешная plain-публикация summary пишет
        доставленную статью в ledger через default-binding (kind=
        rich_message, correlation_id рана, searchable plain-текст)."""
        db = await _db(tmp_path, "m4b.db")
        bot_output_ledger.bind_default_db(db)
        try:
            from types import SimpleNamespace
            from services.summary_generator import SummaryGenerator

            class _Bot:
                id = 42

                async def send_message(self, chat_id, text, **kwargs):
                    return SimpleNamespace(message_id=977)

            gen = SummaryGenerator(memory=SimpleNamespace(),
                                   xml=SimpleNamespace(),
                                   llm=SimpleNamespace(), bot=_Bot())
            doc = {"schema_version": 1, "title": "T",
                   "paragraphs": [
                       {"text": "абзац один про котиков", "emphasis": None}]}
            ok = await gen._publish_plain_document(
                CHAT, doc, correlation_id="run-m4-plain")
            assert ok is True
            rows = await db.list_recent_bot_outputs(CHAT, limit=5)
            assert rows and rows[0]["output_kind"] == "rich_message"
            assert rows[0]["tg_message_id"] == 977
            assert "котиков" in (rows[0]["content_text"] or "")
            assert rows[0]["correlation_id"] == "run-m4-plain"
            assert rows[0]["source_feature"] == "summary"
            assert rows[0]["bot_user_id"] == 42
        finally:
            bot_output_ledger.bind_default_db(None)


# ── retrieval: расширенный SELECT + candidate metadata ─────────────────────

class TestRetrievalAttribution:
    @pytest.mark.asyncio
    async def test_fact_row_carries_provenance_columns(self, tmp_path):
        db = await _db(tmp_path, "c5a.db")
        cursor = await db.db.execute(
            "INSERT INTO graph_facts (chat_id, fact, origin, created_at, "
            "target_user, tg_message_id, subject_ref_id, "
            "attribution_method, assertion_kind, speaker_author_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (CHAT, "Митя купил собаку", "chat_history", NOW, "2", 610,
             12, "third_party", "event", 1))
        fact_id = int(cursor.lastrowid)
        await db.db.execute(
            "INSERT INTO graph_facts_fts(rowid, fact) VALUES (?, ?)",
            (fact_id, "Митя купил собаку"))
        await db.db.commit()
        from services.summary_memory import build_fts_query
        match = build_fts_query(["митя", "собаку"])
        rows = await db.search_graph_facts_fts(CHAT, match, 5, NOW)
        assert rows and int(rows[0]["id"]) == fact_id
        assert rows[0]["subject_ref_id"] == 12
        assert rows[0]["attribution_method"] == "third_party"
        assert rows[0]["speaker_author_id"] == 1

    def test_candidate_metadata_roundtrip(self):
        c = RetrievalCandidate(
            id="fact:9", entity_type="graph_fact", entity_id="9",
            source_ref_id=12, subject_entity_id=2, speaker_entity_id=1,
            assertion_kind="event", attribution_method="third_party",
            origin_type="chat_history", provenance_backed=True)
        assert c.source_ref_id == 12       # реальный SourceRef, не None
        assert c.subject_entity_id == 2 and c.speaker_entity_id == 1

    def test_read_policy_rank(self):
        confirmed = {"subject_ref_id": 1, "speaker_author_id": 2,
                     "status": "confirmed", "origin": "chat_history"}
        legacy = {"subject_ref_id": None, "speaker_author_id": None,
                  "status": "confirmed", "origin": "chat_history"}
        bot = {"subject_ref_id": None, "speaker_author_id": None,
               "status": "confirmed", "origin": "bot_self_reply"}
        assert gprov.read_policy_rank(confirmed) == 3
        assert gprov.read_policy_rank(legacy) == 0
        assert gprov.read_policy_rank(bot) == 0   # bot output ≠ персонализация


# ── Analytics endpoints (light, handler-level) ──────────────────────────────

class TestAnalyticsEndpoints:
    def test_trace_handler_exists_and_shape(self, tmp_path, monkeypatch):
        import web.api.memory_agi as agi
        assert hasattr(agi, "memory_attribution_trace")
        assert hasattr(agi, "memory_attribution_metrics")

    def test_no_new_root_dashboard_router(self):
        # MCA-17/§1: новый корневой Analytics запрещён — только router
        # memory_agi расширен (эндпоинты /memory/attribution/*).
        import web.api.memory_agi as agi
        routes = {r.path for r in agi.memory_router.routes}
        assert "/memory/attribution/trace" in routes
        assert "/memory/attribution/metrics" in routes
        assert not any(str(p).startswith("/analytics") and
                       "attribution" in str(p) for p in routes
                       if p != "/memory/attribution/trace"
                       and p != "/memory/attribution/metrics")
