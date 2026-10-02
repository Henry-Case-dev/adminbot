"""mca-22-attribution-memory-coherence (round 10.27, ADR-1028-6) — Builder
покрытие: инфраструктура санкций и контракты C1–C8.

Покрытие:
  * DDL v22 (spec §4.1): `mca_bot_outputs` + 3 индекса, аддитивно/
    идемпотентно (повтор initialize — no-op), user_version 22.
  * Санкции: ровно 4 kill-switch (env-only, default ON, KILL_SWITCHES),
    reason_code +12, Δ каталога = 0 (param_catalog не расширяется).
  * C1: CanonicalMessage projection (полный набор роль/время-колонок,
    unknown=None), rendering ролей (reply ≠ quote ≠ forward), batched
    (без N+1), ingestion-фикс quote_author_id (модульный контракт).
  * C2: ledger record/read (append-only, delivered only), SourceRef
    entity_id `bot_output:<id>`, self_referential политика.
  * C3: quote resolver лестница 1–7 (native reply / TG metadata / thread /
    ledger / bounded history / unresolved; ambiguous; sender ≠ автор).
  * C4: ClaimEnvelope speech acts + negation guard (truth-set D),
    speaker≠subject (C/L), coreference (I), producer-validator.
  * C5: person-edge validator (bare edge → legacy_unverified + weight-cap),
    RetrievalCandidate metadata, identity-prior (truth-set K).
  * C7: update dedup identity (truth-set M/N), duplicate guard bounded 1
    + exemptions (§18), lineage snapshot (без raw content).
  * OFF-паритет: все новые ветки закрыты гейтами (пер-гейт проверки).

R17: в тестах числа/коды; секретов нет.
"""
import asyncio
import hashlib
import time

import pytest

from config.settings import settings
from services import mca_events
from services import mca_gates
from services import bot_output_ledger
from services import canonical_messages
from services import claim_envelope
from services import graphrag_provenance
from services import quote_resolver as qr
from services import response_freshness as fresh
from services.smart_cache import SmartCache
from services.database import (
    DatabaseService,
    _SCHEMA_VERSION_BOT_OUTPUTS,
    _SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE,
)

CHAT = -100900


async def _db(tmp_path, name="mca22.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _add_msg(db, chat_id, user_id, text, ts, tg_message_id=None,
                   reply_to_id=None, quote_text=None, quote_author_id=None,
                   reply_to_author_id=None, forward_author_id=None,
                   author_name="") -> int:
    from services import message_identity
    return await message_identity.save_live_message(
        db, chat_id=chat_id, user_id=user_id, text=text,
        timestamp=ts, sent_at=ts, ingested_at=ts,
        author_name=author_name, tg_message_id=tg_message_id,
        reply_to_id=reply_to_id, reply_to_author_id=reply_to_author_id,
        quote_text=quote_text, quote_author_id=quote_author_id,
        forward_author_id=forward_author_id)


async def _count(db, sql, params=()) -> int:
    cursor = await db.db.execute(sql, params)
    row = await cursor.fetchone()
    return int(row[0] or 0) if row is not None else 0


# ── Санкции: DDL v22 / рубильники / reason_code / каталог ──────────────────

class TestSanctions:
    @pytest.mark.asyncio
    async def test_v22_migration_creates_ledger(self, tmp_path):
        db = await _db(tmp_path, "v22a.db")
        assert await db._table_exists("mca_bot_outputs")
        cursor = await db.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        # v22 применён (шаг реестра); хвост реестра — v23 (asap-4,
        # ADR-1028-7) — фронтир user_version >= 22.
        assert int(row[0]) >= _SCHEMA_VERSION_BOT_OUTPUTS == 22
        assert int(row[0]) == _SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE
        # 3 индекса
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND "
            "tbl_name='mca_bot_outputs'")
        names = {r["name"] for r in await cursor.fetchall()}
        assert {"idx_mca_bot_outputs_chat_tg", "idx_mca_bot_outputs_hash",
                "idx_mca_bot_outputs_corr"} <= names

    @pytest.mark.asyncio
    async def test_v22_migration_idempotent(self, tmp_path):
        db = await _db(tmp_path, "v22b.db")
        await db.initialize()      # повторный прогон — no-op
        assert await db._table_exists("mca_bot_outputs")
        cursor = await db.db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
        # v22 применён идемпотентно; хвост реестра — v23 (asap-4).
        assert int(row[0]) >= 22
        assert int(row[0]) == _SCHEMA_VERSION_EMBEDDING_CONTROL_PLANE
        assert await _count(db, "SELECT COUNT(*) FROM mca_bot_outputs") == 0

    @pytest.mark.asyncio
    async def test_v22_legacy_tables_untouched(self, tmp_path):
        db = await _db(tmp_path, "v22c.db")
        # существующие таблицы не тронуты; append-only ledger пуст
        assert await db._table_exists("smart_messages")
        assert await db._table_exists("bot_replies")
        assert await db._table_exists("mca_events")
        assert await _count(db, "SELECT COUNT(*) FROM mca_bot_outputs") == 0

    def test_exactly_four_kill_switches(self):
        new_switches = [k for k in mca_gates.KILL_SWITCHES
                        if k.startswith(("MCA_CANONICAL_", "MCA_BOT_OUTPUT_",
                                         "MCA_CORRECTION_",
                                         "MCA_RESPONSE_"))]
        assert sorted(new_switches) == sorted([
            "MCA_CANONICAL_ATTRIBUTION_ENABLED",
            "MCA_BOT_OUTPUT_LEDGER_ENABLED",
            "MCA_CORRECTION_REVALIDATION_ENABLED",
            "MCA_RESPONSE_FRESHNESS_GUARD_ENABLED"])
        for name in new_switches:
            default, parity = mca_gates.KILL_SWITCHES[name]
            assert default is True
            assert parity           # OFF-паритет описан

    def test_reason_codes_plus12(self):
        expected = {
            "direct_update_dedup_hit", "direct_final_replay_blocked",
            "direct_fresh_generation", "direct_freshness_retry",
            "direct_intermediate_cache_hit", "quote_resolved",
            "quote_ambiguous", "quote_unresolved",
            "subject_unresolved_skipped", "correction_revalidation_queued",
            "bot_output_recorded", "bot_output_undelivered_skipped",
        }
        assert expected <= mca_events.REASON_CODES

    def test_catalog_delta_zero(self):
        # Δ каталога = 0 (F8 NOT_APPLICABLE): новые настройки env-only,
        # param_catalog их не содержит.
        try:
            from services.param_catalog import PARAM_DEFS
        except Exception:
            from services import param_catalog
            names = {str(getattr(v, "key", ""))
                     for v in getattr(param_catalog, "_PARAMS", [])}
        else:
            names = {d.key for d in PARAM_DEFS}
        forbidden = {
            "MCA_CANONICAL_ATTRIBUTION_ENABLED",
            "MCA_BOT_OUTPUT_LEDGER_ENABLED",
            "MCA_CORRECTION_REVALIDATION_ENABLED",
            "MCA_RESPONSE_FRESHNESS_GUARD_ENABLED",
        }
        assert not (forbidden & names)

    def test_correction_gate_inert_when_canonical_off(self, monkeypatch):
        # инертность: canonical OFF ⇒ correction недостижим (spec §4.2)
        monkeypatch.setattr(mca_gates, "canonical_attribution_enabled",
                            lambda: False)
        assert mca_gates.correction_revalidation_enabled() is False
        monkeypatch.setattr(mca_gates, "canonical_attribution_enabled",
                            lambda: True)
        assert mca_gates.correction_revalidation_enabled() is True


# ── C1: canonical envelope projection ───────────────────────────────────────

class TestCanonicalEnvelope:
    @pytest.mark.asyncio
    async def test_projection_full_roles(self, tmp_path):
        db = await _db(tmp_path, "c1a.db")
        now = int(time.time())
        await _add_msg(db, CHAT, 2, "сообщение Б", now - 60,
                       tg_message_id=101, author_name="Б")
        await _add_msg(db, CHAT, 1, "сообщение А с цитатой", now,
                       tg_message_id=102, reply_to_id=101,
                       reply_to_author_id=2, quote_text="сообщение Б",
                       quote_author_id=2, author_name="А",
                       forward_author_id=None)
        msgs = await canonical_messages.get_canonical_messages(
            db, CHAT, since_ts=now - 3600, limit=10)
        assert len(msgs) == 2
        by_tg = {m.tg_message_id: m for m in msgs}
        a = by_tg[102]
        assert a.speaker_entity_id == 1
        assert a.reply_to_speaker_entity_id == 2      # роли не потеряны
        assert a.quote_speaker_entity_id == 2
        assert a.quote_text == "сообщение Б"
        assert a.quote_source_ref == "tg:101"         # batch-карта
        assert a.revision == 1
        assert a.sent_at is not None and a.ingested_at is not None
        assert a.message_ref == "tg:102"
        roles = a.roles()
        assert roles["author"] == 1
        assert roles["quoted_author"] == 2
        assert roles["reply_addressee"] == 2

    @pytest.mark.asyncio
    async def test_projection_unknown_honest(self, tmp_path):
        db = await _db(tmp_path, "c1b.db")
        now = int(time.time())
        await _add_msg(db, CHAT, 5, "просто текст", now, tg_message_id=7)
        msgs = await canonical_messages.get_canonical_messages(
            db, CHAT, since_ts=now - 60, limit=5)
        m = msgs[0]
        assert m.quote_speaker_entity_id is None      # unknown не выдуман
        assert m.reply_to_speaker_entity_id is None
        assert m.forward_speaker_entity_id is None
        assert m.edited_at is None

    @pytest.mark.asyncio
    async def test_projection_refs_batch(self, tmp_path):
        db = await _db(tmp_path, "c1c.db")
        now = int(time.time())
        await _add_msg(db, CHAT, 3, "раз", now, tg_message_id=11)
        await _add_msg(db, CHAT, 4, "два", now, tg_message_id=12)
        got = await canonical_messages.get_canonical_messages_by_refs(
            db, CHAT, [11, 12, 99])
        assert set(got) == {11, 12}

    @pytest.mark.asyncio
    async def test_projection_gate_off_empty(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "c1d.db")
        now = int(time.time())
        await _add_msg(db, CHAT, 3, "текст", now, tg_message_id=21)
        monkeypatch.setattr(mca_gates, "canonical_attribution_enabled",
                            lambda: False)
        msgs = await canonical_messages.get_canonical_messages(
            db, CHAT, since_ts=now - 60, limit=5)
        assert msgs == []                              # OFF: не используется
        got = await canonical_messages.get_canonical_messages_by_refs(
            db, CHAT, [21])
        assert got == {}

    def test_render_roles_distinguishable(self):
        from services.canonical_messages import CanonicalMessage
        msg = CanonicalMessage(
            message_ref="tg:5", source_ref_id=None, row_id=1, chat_id=CHAT,
            tg_message_id=5, revision=1, source_kind="live",
            speaker_entity_id=1, speaker_display_name="Аня",
            sent_at=1790000000, ingested_at=1790000001, edited_at=None,
            reply_to_message_ref="tg:4", reply_to_speaker_entity_id=2,
            quote_text="мнение Б", quote_source_ref="tg:4",
            quote_speaker_entity_id=2,
            forward_source="Канал X", forward_speaker_entity_id=9,
            is_forward=True, thread_id=None, media_type="text",
            media_ref=None, content_hash=None, message_state="active",
            raw_text="что скажешь?", caption=None)
        out = canonical_messages.format_canonical_envelope(msg)
        # reply ≠ quote ≠ forward различимы; цитата — НЕ слова автора
        assert "в ответ: 2" in out
        assert "> мнение Б (автор цитаты: 2)" in out
        assert "Переслано: Канал X (автор: 9)" in out
        assert "Аня" in out and "что скажешь?" in out


# ── C2: Own Output Ledger ───────────────────────────────────────────────────

class TestBotOutputLedger:
    @pytest.mark.asyncio
    async def test_record_delivered_and_read(self, tmp_path):
        db = await _db(tmp_path, "c2a.db")
        oid = await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=555, text="ответ бота",
            bot_user_id=42, output_kind="direct_reply",
            correlation_id="corr-1", source_feature="direct_chat")
        assert oid is not None
        rec = await db.get_bot_output_by_tg(CHAT, 555)
        assert rec is not None
        assert rec["content_text"] == "ответ бота"
        assert rec["delivery_status"] == "delivered"
        assert rec["correlation_id"] == "corr-1"
        # стабильный content_hash
        assert rec["content_hash"] == hashlib.sha256(
            "ответ бота\x00".encode()).hexdigest()
        # SourceRef entity_id контракт
        assert bot_output_ledger.bot_output_source_ref_id(
            oid) == f"bot_output:{oid}"

    @pytest.mark.asyncio
    async def test_ledger_gate_off_no_write(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "c2b.db")
        monkeypatch.setattr(mca_gates, "bot_output_ledger_enabled",
                            lambda: False)
        oid = await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=556, text="не пишем")
        assert oid is None
        assert await _count(db, "SELECT COUNT(*) FROM mca_bot_outputs") == 0
        assert await bot_output_ledger.resolve_bot_output_by_tg(
            db, CHAT, 556) is None

    @pytest.mark.asyncio
    async def test_ledger_exact_match_priority5(self, tmp_path):
        db = await _db(tmp_path, "c2c.db")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=700,
            text="уникальный текст бота", bot_user_id=42)
        hit = await bot_output_ledger.find_bot_output_by_text(
            db, CHAT, "уникальный текст бота")
        assert hit is not None and hit["tg_message_id"] == 700
        as_msg = bot_output_ledger.bot_output_as_message_dict(hit)
        assert as_msg["self_referential"] is True     # никогда не proof
        # fuzzy НЕ матчится (content_hash exact)
        miss = await bot_output_ledger.find_bot_output_by_text(
            db, CHAT, "уникальный текст бота, но другой")
        assert miss is None

    @pytest.mark.asyncio
    async def test_ledger_revision_append_only(self, tmp_path):
        db = await _db(tmp_path, "c2d.db")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=800, text="версия 1")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=800, text="версия 2",
            revision_no=2)
        rows = await db.list_recent_bot_outputs(CHAT, kinds=("direct_reply",))
        texts = {r["content_text"] for r in rows}
        assert texts == {"версия 1", "версия 2"}       # append-only
        rec = await db.get_bot_output_by_tg(CHAT, 800)
        assert rec["revision_no"] == 2                 # последняя revision

    def test_self_referential_origin_policy(self):
        from services.provenance import BOT_ORIGINS, is_self_referential_origin
        assert "bot_direct_reply" in BOT_ORIGINS
        assert is_self_referential_origin("bot_direct_reply") is True
        # bot output — не independent proof внешнего факта
        links = [{"link_type": "supports", "verification": "verified",
                  "independence": "independent", "source_ref_id": 1},
                 {"link_type": "supports", "verification": "verified",
                  "independence": "independent", "source_ref_id": 1}]
        assert graphrag_provenance.independent_roots_count(links) == 1


# ── C3: Quote Resolver (лестница 1–7) ───────────────────────────────────────

class TestQuoteResolver:
    @pytest.mark.asyncio
    async def test_priority1_native_reply(self, tmp_path):
        db = await _db(tmp_path, "c3a.db")
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            reply_to_tg_message_id=321, reply_to_speaker_entity_id=7,
            bot_user_id=42)
        assert res.status == qr.QUOTE_RESOLVED
        assert res.priority == 1
        assert res.quote_source_ref == "tg:321"
        assert res.quote_speaker_entity_id == 7
        assert res.quote_speaker_is_bot is False

    @pytest.mark.asyncio
    async def test_priority2_tg_quote_metadata(self, tmp_path):
        db = await _db(tmp_path, "c3b.db")
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            tg_quote_text="фрагмент", tg_quote_author_id=9, bot_user_id=42)
        assert res.status == qr.QUOTE_RESOLVED
        assert res.priority == 2
        assert res.quote_speaker_entity_id == 9

    @pytest.mark.asyncio
    async def test_priority4_thread_exact(self, tmp_path):
        db = await _db(tmp_path, "c3c.db")
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            quote_text="Лёха вчера сменил работу и рад",
            thread_texts=[("Кто-то сказал: Лёха вчера сменил работу и рад",
                           5)], bot_user_id=42)
        assert res.status == qr.QUOTE_RESOLVED
        assert res.priority == 4
        assert res.quote_speaker_entity_id == 5

    @pytest.mark.asyncio
    async def test_thread_self_restatement_ambiguous(self, tmp_path):
        db = await _db(tmp_path, "c3d.db")
        # совпадение с собственной репликой sender'а — НЕ доказательство
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            quote_text="я всегда говорил что погода хромает",
            thread_texts=[("я всегда говорил что погода хромает", 1)],
            bot_user_id=42)
        assert res.status == qr.QUOTE_AMBIGUOUS
        assert res.reason_code == "quote_ambiguous"

    @pytest.mark.asyncio
    async def test_thread_two_authors_ambiguous(self, tmp_path):
        db = await _db(tmp_path, "c3e.db")
        common = "просто обычная бытовая фраза про погоду"
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1, quote_text=common,
            thread_texts=[(common, 2), (common, 3)], bot_user_id=42)
        assert res.status == qr.QUOTE_AMBIGUOUS

    @pytest.mark.asyncio
    async def test_priority5_bot_output_ledger(self, tmp_path):
        db = await _db(tmp_path, "c3f.db")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=901,
            text="я раньше отвечал вот такой точной фразой", bot_user_id=42)
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            quote_text="я раньше отвечал вот такой точной фразой",
            bot_user_id=42)
        assert res.status == qr.QUOTE_RESOLVED
        assert res.priority == 5
        assert res.self_output is True
        assert res.quote_speaker_is_bot is True
        assert res.quote_source_ref.startswith("bot_output:")

    @pytest.mark.asyncio
    async def test_priority5_unavailable_when_ledger_off(self, tmp_path,
                                                         monkeypatch):
        db = await _db(tmp_path, "c3g.db")
        await bot_output_ledger.record_delivered_output(
            db, chat_id=CHAT, tg_message_id=902,
            text="фраза бота для off-теста", bot_user_id=42)
        monkeypatch.setattr(mca_gates, "bot_output_ledger_enabled",
                            lambda: False)
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            quote_text="фраза бота для off-теста", bot_user_id=42)
        # лестница падает ниже 5 (6/7), ledger-хит недоступен
        assert res.priority != qr.PRIORITY_BOT_OUTPUT_LEDGER
        assert res.self_output is False

    @pytest.mark.asyncio
    async def test_priority6_bounded_history(self, tmp_path):
        db = await _db(tmp_path, "c3h.db")
        now = int(time.time())
        await _add_msg(db, CHAT, 6, "Борис однажды сказал про мосты города",
                       now - 30, tg_message_id=61)
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            quote_text="Борис однажды сказал про мосты города",
            bot_user_id=42)
        assert res.status == qr.QUOTE_RESOLVED
        assert res.priority == 6
        assert res.quote_speaker_entity_id == 6

    @pytest.mark.asyncio
    async def test_priority7_unresolved_and_sender_never_default(
            tmp_path):
        db = None
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1, quote_text=None,
            bot_user_id=42)
        assert res.status == qr.QUOTE_UNRESOLVED
        assert res.priority == 7
        assert res.quote_speaker_entity_id is None   # sender НЕ назначен

    @pytest.mark.asyncio
    async def test_gate_off_unresolved(self, tmp_path, monkeypatch):
        db = await _db(tmp_path, "c3i.db")
        monkeypatch.setattr(mca_gates, "canonical_attribution_enabled",
                            lambda: False)
        res = await qr.resolve_quote(
            db, chat_id=CHAT, sender_entity_id=1,
            reply_to_tg_message_id=1, reply_to_speaker_entity_id=2,
            bot_user_id=42)
        assert res.status == qr.QUOTE_UNRESOLVED      # паритет baseline


# ── C4: Claim Envelope / speech acts / speaker ≠ subject / coreference ─────

class TestClaimEnvelope:
    def test_truthset_d_negation_guard(self):
        env = claim_envelope.build_envelope(
            speaker_entity_id=1, subject_entity_id=1,
            claim_text="Я не говорил, что увольняюсь с работы")
        assert env.speech_act == claim_envelope.SPEECH_ACT_DENY
        assert env.negated is True
        outcome, reason = claim_envelope.validate_personal_write(env)
        assert outcome == claim_envelope.OUTCOME_REJECTED
        assert reason == "negation_guard"

    def test_truthset_c_speaker_not_subject(self):
        # «Вася: Лёха сменил работу» — speaker=Вася, subject=Лёха
        env = claim_envelope.build_envelope(
            speaker_entity_id=1, subject_entity_id=2,
            claim_text="Лёха сменил работу",
            attribution_method="third_party")
        assert env.speaker_entity_id == 1
        assert env.subject_entity_id == 2
        assert env.speech_act == claim_envelope.SPEECH_ACT_ASSERT
        outcome, _ = claim_envelope.validate_personal_write(env)
        assert outcome == claim_envelope.OUTCOME_TENTATIVE   # attributed

    def test_subject_fallback_to_sender_forbidden(self):
        env = claim_envelope.build_envelope(
            speaker_entity_id=1, subject_entity_id=None,
            claim_text="кто-то там что-то сделал",
            attribution_method="third_party")
        outcome, reason = claim_envelope.validate_personal_write(env)
        assert outcome == claim_envelope.OUTCOME_UNRESOLVED
        assert reason == "subject_unresolved_skipped"

    def test_truthset_l_third_party_not_self_report(self):
        third = claim_envelope.build_envelope(
            speaker_entity_id=1, subject_entity_id=2,
            claim_text="Митя купил собаку", attribution_method="third_party",
            verification="tentative")
        self_rep = claim_envelope.build_envelope(
            speaker_entity_id=2, subject_entity_id=2,
            claim_text="я купил собаку", attribution_method="self_report")
        o3, _ = claim_envelope.validate_personal_write(third)
        o2, _ = claim_envelope.validate_personal_write(self_rep)
        assert o3 == claim_envelope.OUTCOME_TENTATIVE
        assert o2 == claim_envelope.OUTCOME_ACCEPTED   # разные классы

    def test_gated_speech_acts(self):
        for text in ("Кто съел мой бутерброд?",
                     "Может быть он уже дома",
                     "Бот, напиши стих про осень",
                     "лол это конечно шутка про кота"):
            env = claim_envelope.build_envelope(
                speaker_entity_id=1, subject_entity_id=1, claim_text=text)
            outcome, reason = claim_envelope.validate_personal_write(env)
            assert outcome == claim_envelope.OUTCOME_REJECTED, text
            assert reason.startswith("gated_speech_act")

    def test_truthset_i_coreference_no_merge(self):
        # same display name — две личности НЕ сливаются
        res = claim_envelope.resolve_coreference(
            "Саша", speaker_entity_id=1,
            candidate_names=[("Саша", 10), ("Саша", 11)])
        assert res == ("unresolved", None)
        # уникальное имя резолвится
        res2 = claim_envelope.resolve_coreference(
            "Лёха", speaker_entity_id=1,
            candidate_names=[("Лёха", 5)])
        assert res2 == ("resolved", 5)
        # местоимение без контекста — unresolved
        res3 = claim_envelope.resolve_coreference(
            "он", speaker_entity_id=1)
        assert res3 == ("unresolved", None)
        # «я» → speaker; «ты» → reply-адресат
        assert claim_envelope.resolve_coreference(
            "я устал", speaker_entity_id=1) == ("resolved", 1)
        assert claim_envelope.resolve_coreference(
            "ты прав", speaker_entity_id=1,
            reply_target_entity_id=7) == ("resolved", 7)

    def test_checks_json_reuse_provenance_keys(self):
        env = claim_envelope.build_envelope(
            speaker_entity_id=1, subject_entity_id=2,
            claim_text="цитирую: погода хорошая",
            quoted_source_ref="tg:44")
        js = claim_envelope.checks_json_for(env)
        assert js is not None
        import json as _json
        data = _json.loads(js)
        assert set(data) <= set(__import__(
            "services.provenance", fromlist=["CHECK_KEYS"]).CHECK_KEYS)

    def test_validator_outcomes_closed_set(self):
        assert claim_envelope.VALIDATOR_OUTCOMES == frozenset({
            "accepted", "tentative", "unresolved", "rejected"})


# ── C5: GraphRAG provenance enforcement + retrieval attribution ────────────

class TestGraphRagProvenance:
    def test_bare_edge_not_confident(self):
        v = graphrag_provenance.validate_person_edge_write(
            speaker_entity_id=None, subject_entity_id=None,
            source_ref_id=None, revision=None)
        assert v.allowed is True                      # не удаляем (§9)
        assert v.confidence == graphrag_provenance.EDGE_LEGACY_UNVERIFIED
        assert v.weight_cap is not None and v.weight_cap < 1.0
        assert v.reason_code == "subject_unresolved_skipped"

    def test_full_provenance_confident(self):
        v = graphrag_provenance.validate_person_edge_write(
            speaker_entity_id=1, subject_entity_id=2, source_ref_id=77,
            revision=1, event_time=1790000000)
        assert v.allowed and v.confidence == graphrag_provenance.EDGE_CONFIDENT
        assert v.weight_cap is None

    def test_legacy_fact_classification(self):
        legacy = {"subject_ref_id": None, "speaker_author_id": None}
        partial = {"subject_ref_id": 3, "speaker_author_id": None}
        full = {"subject_ref_id": 3, "speaker_author_id": 5,
                "status": "confirmed"}
        assert graphrag_provenance.classify_fact_provenance(
            legacy) == graphrag_provenance.EDGE_LEGACY_UNVERIFIED
        assert graphrag_provenance.classify_fact_provenance(
            partial) == graphrag_provenance.EDGE_TENTATIVE
        assert graphrag_provenance.classify_fact_provenance(
            full) == graphrag_provenance.EDGE_CONFIDENT

    def test_gate_off_baseline_semantics(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "canonical_attribution_enabled",
                            lambda: False)
        v = graphrag_provenance.validate_person_edge_write(
            speaker_entity_id=None, subject_entity_id=None)
        assert v.confidence == graphrag_provenance.EDGE_CONFIDENT  # паритет
        assert graphrag_provenance.plan_correction(
            message_text="ты меня перепутал").triggered is False

    def test_retrieval_candidate_metadata_fields(self):
        from services.mca_retrieval_context import RetrievalCandidate
        c = RetrievalCandidate(
            id="fact:1", entity_type="graph_fact", entity_id="1",
            subject_entity_id=2, speaker_entity_id=3,
            assertion_kind="biographical", attribution_method="third_party",
            verification="verified", origin_type="chat_history",
            contradiction_status="none", provenance_backed=True)
        assert c.subject_entity_id == 2 and c.speaker_entity_id == 3
        assert c.provenance_backed is True

    def test_truthset_k_identity_prior(self):
        from services.mca_retrieval_context import (
            RetrievalCandidate, apply_identity_prior)
        wrong = RetrievalCandidate(
            id="fact:wrong", entity_type="graph_fact", entity_id="w",
            score=100.0, channel="vector", subject_entity_id=999,
            provenance_backed=True)     # vector hit ПРО ДРУГОГО человека
        right = RetrievalCandidate(
            id="fact:right", entity_type="graph_fact", entity_id="r",
            score=60.0, channel="lexical", subject_entity_id=2,
            provenance_backed=True)     # exact subject
        out = apply_identity_prior([wrong, right], subject_entity_ids=(2,))
        assert out[0].id == "fact:right"     # similarity не побеждает identity
        # legacy без provenance — weak hint (штраф)
        legacy = RetrievalCandidate(
            id="fact:legacy", entity_type="graph_fact", entity_id="l",
            score=60.0, channel="lexical", subject_entity_id=2,
            provenance_backed=False)
        out2 = apply_identity_prior([legacy, right], subject_entity_ids=(2,))
        assert out2[0].id == "fact:right"


# ── C7: Freshness — update dedup / duplicate guard / lineage ───────────────

class _FakeCache:
    """Маркер-хранилище с честным TTL (fix round-1 M-1): store хранит
    (payload, monotonic-отметку); чтение проверяет возраст против TTL,
    переданного вызывающим (`UPDATE_DEDUP_TTL_SECONDS`)."""

    def __init__(self):
        self.store: dict[str, tuple[str, float]] = {}
        self.ttls: list[int] = []
        self.now = 1000.0

    async def get_update_marker(self, key, *, ttl_seconds):
        entry = self.store.get(key)
        if entry is None:
            return None
        payload, ts = entry
        if (self.now - ts) > ttl_seconds:
            del self.store[key]
            return None
        return payload

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.ttls.append(int(ttl_seconds))
        self.store[key] = (payload, self.now)

    # legacy-методы сознательно НЕ реализуются: update-dedup больше
    # не должен их читать (иначе тест замаскировал бы дефект M-1).


class TestFreshness:
    @pytest.mark.asyncio
    async def test_truthset_n_same_update_idempotent(self):
        cache = _FakeCache()
        first = await fresh.check_update_seen(cache, CHAT, 5001, revision=1)
        assert first is False
        await fresh.mark_update_seen(cache, CHAT, 5001, revision=1)
        second = await fresh.check_update_seen(cache, CHAT, 5001, revision=1)
        assert second is True            # тот же update → 0 LLM/0 reply

    @pytest.mark.asyncio
    async def test_truthset_m_same_text_new_message_fresh(self):
        cache = _FakeCache()
        await fresh.mark_update_seen(cache, CHAT, 6001, revision=1)
        # другой tg_message_id, тот же текст → fresh processing (identity,
        # НЕ текст — ключ)
        other = await fresh.check_update_seen(cache, CHAT, 6002, revision=1)
        assert other is False

    @pytest.mark.asyncio
    async def test_update_dedup_key_identity_not_text(self):
        k1 = fresh.update_dedup_key(CHAT, 1)
        k2 = fresh.update_dedup_key(CHAT, 2)
        k3 = fresh.update_dedup_key(CHAT, 1, revision=2)
        assert len({k1, k2, k3}) == 3    # identity+revision, не текст
        assert fresh.update_dedup_key(CHAT, None) is None

    @pytest.mark.asyncio
    async def test_dedup_gate_off(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "response_freshness_guard_enabled",
                            lambda: False)
        cache = _FakeCache()
        await fresh.mark_update_seen(cache, CHAT, 7001, revision=1)
        assert await fresh.check_update_seen(cache, CHAT, 7001) is False
        # паритет: маркера нет вовсе
        assert cache.store == {}

    # ── fix round-1 (M-1): TTL 24 h + развязка с legacy-флагами ────────────

    @pytest.mark.asyncio
    async def test_update_marker_ttl_is_sancoed_24h(self):
        # spec §3-C7/§4.2: TTL ≈ 24 h — константа wired в mark/check.
        assert fresh.UPDATE_DEDUP_TTL_SECONDS == 24 * 3600
        cache = _FakeCache()
        await fresh.mark_update_seen(cache, CHAT, 7101, revision=1)
        assert cache.ttls and cache.ttls[0] == 24 * 3600

    def test_sweep_ttl_constant_matches_freshness(self):
        # drift-guard: чистка smart_cache не выметает 24h-маркеры раньше.
        from services import smart_cache as sc
        assert sc._UPDATE_MARKER_SWEEP_TTL == fresh.UPDATE_DEDUP_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_marker_outlives_legacy_chat_dedup_ttl(self):
        # Маркер жив ≫300 с (legacy CHAT_DEDUP_TTL_SECONDS): 301 с → seen.
        cache = _FakeCache()
        await fresh.mark_update_seen(cache, CHAT, 7201, revision=1)
        cache.now += 301                  # > legacy TTL 300 с
        assert await fresh.check_update_seen(cache, CHAT, 7201) is True
        cache.now += 24 * 3600            # > 24 h TTL → fresh
        assert await fresh.check_update_seen(cache, CHAT, 7201) is False

    @pytest.mark.asyncio
    async def test_chat_dedup_flag_off_does_not_kill_update_dedup(
            self, tmp_path):
        # Counterexample #2 ревью: CHAT_DEDUP_ENABLED=OFF (UI-флаг legacy
        # text-дедупа) и SMART_CACHE_ENABLED=OFF НЕ должны молча убивать
        # update-dedup MCA-22 (fix round-1 M-1: развязка флагов).
        from services import hot_config as hot

        class _HotCache:
            def __init__(self, values):
                self._values = values

            def get(self, key, default=None):
                return self._values.get(key, default)

        hot.set_config_cache(_HotCache({
            "flags.chat_dedup_enabled": False,
            "flags.smart_cache_enabled": False,
        }))
        try:
            cache = SmartCache(str(tmp_path / "upd_dedup.db"))
            try:
                await fresh.mark_update_seen(cache, CHAT, 7301, revision=1,
                                             user_id=77)
                assert await fresh.check_update_seen(
                    cache, CHAT, 7301, revision=1, user_id=77) is True
                # другой update → fresh
                assert await fresh.check_update_seen(
                    cache, CHAT, 7302, revision=1, user_id=77) is False
            finally:
                await cache.close()
        finally:
            hot.set_config_cache(None)

    def test_truthset_o_duplicate_guard_bounded(self):
        v = fresh.evaluate_duplicate(
            "Привет, как дела сегодня", "привет, как дела сегодня",
            new_tg_message_id=8001)
        assert v.duplicate is True and v.regeneration_allowed is True
        # ровно ОДНА попытка: повторное совпадение → отправить + metric
        v2 = fresh.evaluate_duplicate(
            "Привет, как дела сегодня", "привет, как дела сегодня",
            new_tg_message_id=8001, regeneration_already_used=True)
        assert v2.duplicate is True
        assert v2.regeneration_allowed is False
        assert v2.reason_code == "duplicate_sent_after_retry"

    def test_duplicate_guard_exemptions(self):
        assert fresh.evaluate_duplicate(
            "/status 42", "/status 42", new_tg_message_id=1).exempt is True
        assert fresh.evaluate_duplicate(
            "ok", "ok", new_tg_message_id=1).exempt is True
        assert fresh.evaluate_duplicate(
            "a" * 700, "a" * 700, new_tg_message_id=1).exempt is True
        assert fresh.evaluate_duplicate(
            "```python\nprint(1)\n```", "```python\nprint(1)\n```",
            new_tg_message_id=1).exempt is True
        # детерминированный хеш/ID
        assert fresh.evaluate_duplicate(
            "deadbeef" * 4, "deadbeef" * 4, new_tg_message_id=1
        ).exempt is True

    def test_no_duplicate_no_block(self):
        v = fresh.evaluate_duplicate("ответ один", "совсем другой ответ",
                                     new_tg_message_id=9)
        assert v.duplicate is False

    def test_lineage_snapshot_r17_safe(self):
        snap = fresh.build_lineage_snapshot(
            reply_message_id=11, trigger_message_id=22, parent_message_id=33,
            context_version="abc", model="m1", provider="p1",
            generation_attempt=2, freshness_retry=True,
            source_refs_used=("tg:1", "fact:2"))
        assert snap["generation_attempt"] == 2
        assert snap["freshness_retry"] is True
        # нет raw content: только ID/коды/версии
        assert all(k != "text" for k in snap)

    def test_paraphrase_postprocessor_not_created(self):
        # §18: запрещён отдельный paraphrase-postprocessor — модуль не
        # содержит функций перефразирования.
        assert not any("paraphrase" in n for n in dir(fresh))


# ── C8: Correction plan ─────────────────────────────────────────────────────

class TestCorrectionPath:
    def test_truthset_e_correction_triggers(self):
        plan = graphrag_provenance.plan_correction(
            message_text="Это говорил Вася, а не я")
        assert plan.triggered is True
        assert plan.evidence_link_type == "contradicts"
        assert plan.verification == "tentative"
        assert plan.conflict_status == "conflicting"
        assert plan.reason_code == "correction_revalidation_queued"

    def test_correction_self_authored_phrase(self):
        assert graphrag_provenance.plan_correction(
            message_text="ты сам это написал вообще-то").triggered is True
        assert graphrag_provenance.plan_correction(
            message_text="ты меня с ним перепутал").triggered is True
        assert graphrag_provenance.plan_correction(
            message_text="это старая информация").triggered is True

    def test_normal_dialog_no_correction(self):
        plan = graphrag_provenance.plan_correction(
            message_text="привет, как погода в городе")
        assert plan.triggered is False

    def test_correction_gate_off(self, monkeypatch):
        monkeypatch.setattr(mca_gates, "correction_revalidation_enabled",
                            lambda: False)
        plan = graphrag_provenance.plan_correction(
            message_text="ты меня перепутал")
        assert plan.triggered is False      # обычный диалог (паритет)
