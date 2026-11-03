"""EVOL-REPLY-CONTEXT-INTEGRITY-01: цель/claim, медиа-опциональность, честные
техстатусы (срезы RC-TARGET-ANCHOR, RC-MEDIA-OPTIONAL, RC-EVIDENCE-STATUS).

TEST-LIFECYCLE: CONTRACT owner=EVOL-REPLY-CONTEXT-INTEGRITY-01

Контракты (источник — plans/owner_inputs/2026-11-03-evol-reply-context-
integrity-v5.md §3, §4, §10.2–§10.3, §11.2–§11.3 и arch-контракт §1–§3):

* цель явного Reply/команды неизменяема; единственная разрешённая подмена —
  объявленная contextual-цель с анкором и автором (M1/M2/M7);
* envelope/план/поиск/вердикт читают ОДИН текст (I3/I4, BD-2);
* антецедент выбирается структурой/семантикой, а не `abs(tg−target)`,
  числом ответов или длиной; сопоставимые кандидаты → уточнение (BD-4/BD-5);
* медиа обязательно только при РЕАЛЬНОЙ зависимости: достаточный текст не
  запускает поиск соседних картинок (M8/M9/M10, §10.2);
* техстатус объявляется по фактической ошибке стадии, а не по отсутствию
  URL; «нет подходящих» ≠ «материалы не удалось разобрать» (§11.2, ES-1/ES-2).

Имена, темы и идентификаторы здесь намеренно не совпадают с примерами из ТЗ
(§13.28): проверяется поведение, а не совпадение со снимком инцидента.
"""
import dataclasses
from unittest.mock import AsyncMock, MagicMock

import pytest

from handlers import factcheck as fh
from services import factcheck_context as fcx
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_renderer as fr
from services import factcheck_service as fcs
from services import factcheck_suitability as fsg
from services import temporal_factcheck as tf
from services import thread_chain as tch
from services.smartmodule_phrases import FACTCHECK_CLARIFY_PHRASES

CHAT_ID = -1004471337
THESIS_TG = 913701          # проверяемый тезис
DECOY_TG = 913702           # близкая, но чужая реакция
TARGET_TG = 913705          # пустая/реактивная цель
TRIGGER_TG = 913706         # сообщение-команда

THESIS = ("Подрядчик занизил смету на ремонт моста через Урал: "
          "в документах стоит сумма 41.7 млн, а потрачено 96.3 млн")
DECOY = ("ну это же очевидно, у нас всегда так воруют, я сто раз писал об "
         "этом и мне никто не верил, всё разворовано и всем плевать")


# ── Двойники ────────────────────────────────────────────────────────────────

def _row(tg, *, text=None, caption=None, media_type="text", mgid=None,
         author="Ирма", reply_to_id=None, chat_id=CHAT_ID):
    return {
        "id": tg, "chat_id": chat_id, "tg_message_id": tg, "text": text,
        "caption": caption, "reply_to_id": reply_to_id,
        "timestamp": 1792400000 + tg, "media_type": media_type,
        "author_name": author, "is_forward": False, "forward_source": None,
        "media_group_id": mgid,
    }


class FakeDb:
    """Минимальный durable-слой: строки по (chat, tg) + окно wide-context."""

    def __init__(self, rows_by_tg=None, around_rows=None, origin_rows=None):
        self.rows_by_tg = {int(k): v for k, v in (rows_by_tg or {}).items()}
        self.around_rows = list(around_rows or [])
        self.origin_rows = {int(k): v
                            for k, v in (origin_rows or {}).items()}
        self.calls = []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        self.calls.append(("target", int(chat_id), int(tg)))
        return self.rows_by_tg.get(int(tg))

    async def get_smart_messages_by_media_group(self, chat_id, mgid):
        self.calls.append(("group", int(chat_id), str(mgid)))
        return [r for r in self.rows_by_tg.values()
                if str(r.get("media_group_id") or "") == str(mgid)]

    async def get_smart_messages_reply_to(self, chat_id, reply_to_id, *,
                                          media_only=False, limit=10):
        self.calls.append(("reply", int(chat_id), int(reply_to_id)))
        rows = [r for r in self.rows_by_tg.values()
                if int(r.get("reply_to_id") or 0) == int(reply_to_id)]
        if media_only:
            rows = [r for r in rows if r.get("media_group_id")]
        return rows[:int(limit)]

    async def get_messages_around(self, chat_id, target_tg_message_id,
                                  before, after):
        self.calls.append(("around", int(chat_id), target_tg_message_id))
        return list(self.around_rows)

    async def get_recent_messages(self, chat_id, limit):
        self.calls.append(("recent", int(chat_id), int(limit)))
        return list(self.around_rows[-int(limit):]) if limit else []

    async def get_smart_message_origin_block(self, chat_id, tg):
        return self.origin_rows.get(int(tg))


class _NullCache:
    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        return None


class _NullCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_msg(text=None, caption=None, message_id=1, user_id=5551,
              reply_to_message=None, forward_origin=None, media_group_id=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.first_name = "Ирма"
    msg.reply_to_message = reply_to_message
    msg.forward_origin = forward_origin
    msg.media_group_id = media_group_id
    msg.quote = None
    msg.photo = None
    msg.document = None
    msg.sticker = None
    return msg


def _analysis(*, ocr=("",), desc=()):
    return {"caption": "", "lines": [], "untrusted_ocr_texts": list(ocr),
            "visual_descriptions": list(desc)}


@pytest.fixture
def handler_env(monkeypatch):
    """Handler без сети/троттлинга (легаси-ветка)."""
    pool = MagicMock()
    permit = MagicMock()
    permit.release = lambda: None
    pool.try_acquire = AsyncMock(return_value=permit)
    monkeypatch.setattr(fh, "get_smartmodule_concurrency_pool", lambda: pool)
    monkeypatch.setattr(fh, "typing_active", lambda bot, chat: _NullCtx())
    monkeypatch.setattr(fh, "cooldown_remaining", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "cooldown_touch", AsyncMock())
    monkeypatch.setattr(fh, "_cp_g", AsyncMock(return_value="contextual"))
    monkeypatch.setattr(fh, "_fetch_context_with_gate",
                        AsyncMock(return_value=("", None)))
    monkeypatch.setattr(fh, "send_chunked_reply", AsyncMock())
    monkeypatch.setattr(fh, "_reply", AsyncMock())
    monkeypatch.setattr(fh, "react_moai", AsyncMock())
    monkeypatch.setattr(fh, "_temporal_on", lambda: False)
    monkeypatch.setattr(fh, "_pipeline_v2_enabled", lambda: False)
    monkeypatch.setattr(fh, "get_smart_cache", lambda: _NullCache())
    old_db, old_service = fh._db, fh._service
    yield fh
    fh._db, fh._service = old_db, old_service


def _service(verdict="вердикт: проверено"):
    service = MagicMock()
    service.check_claim = AsyncMock(return_value=verdict)
    return service


# ── A. Цель и Claim: одна правда о том, что проверяется ─────────────────────

@pytest.mark.asyncio
async def test_explicit_text_target_records_source_and_origin():
    """M1/M7: резолвер публикации фиксирует цель и происхождение тезиса.

    RC-DEF-TARGET, RC-DEF-CLAIM, RC-TGT-EXPLICIT-REPLY."""
    db = FakeDb(rows_by_tg={THESIS_TG: _row(THESIS_TG, text=THESIS)})
    publication = await fcs.resolve_claim_publication(
        db, CHAT_ID, THESIS_TG, base_text=THESIS, target_source="explicit_reply",
        requester_user_id=5551, requester_name="Ирма")
    assert publication.text == THESIS
    assert publication.target_tg_message_id == THESIS_TG
    assert publication.target_source == "explicit_reply"
    assert publication.claim_origin in ("target_text", "target_caption")
    assert publication.claim_anchor_tg_message_id == THESIS_TG
    assert publication.text_sufficient is True
    trace = publication.trace_fields()
    for key in ("target_kind", "target_source", "claim_origin",
                "media_expected", "media_dependency_source",
                "association_attempted", "association_status",
                "linked_media_ids", "media_notice_emitted",
                "media_notice_reason", "text_claim_resolved"):
        assert key in trace, key
    assert trace["target_kind"] == "text"
    assert trace["media_dependency_source"] == "text_claim_only"


@pytest.mark.asyncio
async def test_envelope_claim_matches_publication_and_keeps_target():
    """I3/M3: envelope собирается из ТОГО ЖЕ текста, и target не подменён.

    RC-TGT-INVARIANT, RC-TGT-NO-REWRITE, RC-CLM-PLAN-FROM-CLAIM."""
    ref = tf.InputRef(kind="reply", chat_id=CHAT_ID,
                      target_tg_message_id=THESIS_TG,
                      trigger_tg_message_id=TRIGGER_TG,
                      claim_text=THESIS,
                      claim_anchor_tg_message_id=THESIS_TG)
    origin = _row(THESIS_TG, text=THESIS)
    envelope, reject = await tf.build_envelope(
        FakeDb(origin_rows={THESIS_TG: origin}), ref)
    assert reject is None and envelope is not None
    assert envelope.claim_text == THESIS
    assert envelope.target_tg_message_id == THESIS_TG
    assert envelope.claim_anchor_tg_message_id == THESIS_TG
    # план строится по тому же тезису, что попадёт в вердикт
    decision = fsg.evaluate_suitability(
        envelope.claim_text, None, None,
        target_ref={"chat_id": CHAT_ID,
                    "target_tg_message_id": envelope.target_tg_message_id},
        allow_needs_context=False)
    plan = fsp.build_retrieval_plan(decision, ctx=None,
                                    claim_text=envelope.claim_text)
    assert plan is None or plan.claim_text == envelope.claim_text


@pytest.mark.asyncio
async def test_contextual_target_is_declared_with_anchor_and_author():
    """M2: единственная законная подмена объявлена — анкор, автор, источник.

    RC-TGT-SEM-STRUCT, RC-S009, RC-TGT-NO-FABRICATED-ID."""
    window = [
        _row(THESIS_TG, text=THESIS, author="Ирма"),
        _row(TARGET_TG, text="", author="Ким", reply_to_id=THESIS_TG),
    ]
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="")},
                around_rows=window)
    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG, reply_to_tg_id=THESIS_TG, cache=None)
    assert probe is not None and probe.claim is not None
    assert probe.claim.tg_message_id == THESIS_TG   # реальный reply-родитель
    assert probe.claim.basis == "structural"
    assert probe.claim.author == "Ирма"
    assert probe.ambiguous is False


@pytest.mark.asyncio
async def test_handler_declares_contextual_target_in_trace(handler_env,
                                                          monkeypatch):
    """BD-1/M2: подмена цели не «маскируется под расширение публикации».

    Хендлер обязан объявить contextual-цель (target_source, анкор, автор,
    claim_origin) в публикации и в трассе, а Reply отправить на триггер.

    RC-TGT-NO-REWRITE, RC-TGT-NO-FABRICATED-ID, RC-CLM-TARGETREF-CONTINUITY."""
    captured: dict = {}

    def _capture(publication, **kwargs):
        captured["publication"] = publication
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(fh, "_emit_target_trace", _capture)
    window = [
        _row(THESIS_TG, text=THESIS, author="Ирма"),
        _row(TARGET_TG, text="", author="Ким", reply_to_id=THESIS_TG),
    ]
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="",
                                            reply_to_id=THESIS_TG)},
                around_rows=window)
    service = _service()
    fh.setup_factcheck(service, db)
    bot = AsyncMock()
    await fh.factcheck_handler(
        _make_msg(text="фактчек", message_id=TRIGGER_TG,
                  reply_to_message=_make_msg(message_id=TARGET_TG)), bot=bot)

    publication = captured["publication"]
    assert publication.text == THESIS                    # проверяется тезис
    assert publication.target_source == "contextual"     # подмена объявлена
    assert publication.target_tg_message_id == THESIS_TG  # цель = реальный анкор
    assert publication.claim_origin == "context_window"
    assert publication.claim_anchor_tg_message_id == THESIS_TG
    assert publication.claim_anchor_author == "Ирма"
    assert publication.text_sufficient is True
    assert captured["delivery_reply_to"] == TRIGGER_TG   # Reply на команду
    assert service.check_claim.await_args is not None    # вердикт по тезису


@pytest.mark.asyncio
async def test_antecedent_not_chosen_by_tg_distance():
    """BD-4 (§4.3): близкое «громкое» сообщение не становится тезисом.

    RC-TGT-UNB-NOHEURISTIC, RC-TGT-SEM-STRUCT."""
    window = [
        _row(THESIS_TG, text=THESIS, author="Ирма",
             reply_to_id=913600),
        _row(DECOY_TG, text=DECOY, author="Ким"),      # ближе к цели, но чужая реакция
        _row(DECOY_TG + 1, text="ага", author="Ким", reply_to_id=DECOY_TG),
        _row(TARGET_TG, text="", author="Лея", reply_to_id=THESIS_TG),
    ]
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="")},
                around_rows=window)
    claim = fsg.find_context_claim(
        await fcx.build_wide_context(db, CHAT_ID,
                                     target_tg_message_id=TARGET_TG,
                                     trigger_tg_message_id=TRIGGER_TG,
                                     claim_text="", cache=_NullCache()),
        trigger_tg_message_id=TRIGGER_TG, reply_to_tg_id=THESIS_TG)
    assert claim is not None
    assert claim.tg_message_id == THESIS_TG
    assert claim.source == "reply_to"


@pytest.mark.asyncio
async def test_semantic_antecedent_beats_nearest_by_tg_id():
    """BD-4/M4: семантика важнее tg-близости; близость — только ничья.

    RC-TGT-UNB-NOHEURISTIC, RC-TGT-SEM-STRUCT."""
    window = [
        _row(913001, text="Смета на ремонт моста завышена вдвое",
             author="Ирма"),
        _row(913704, text="Курс валют вырос до 95 рублей за неделю",
             author="Ким"),
        _row(TARGET_TG, text="", author="Лея"),
    ]
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="")},
                around_rows=window)
    # 913704 ближе к пустой цели по tg-id, 913001 — дальше, но по теме
    assert (abs(913704 - TARGET_TG) < abs(913001 - TARGET_TG))
    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG,
        hint="смета на ремонт моста", cache=_NullCache())
    assert probe is not None and probe.claim is not None
    assert probe.claim.tg_message_id == 913001     # тема, а не ближайший id
    assert probe.claim_basis == "topic"


@pytest.mark.asyncio
async def test_two_comparable_claims_ask_for_clarification():
    """§4.3/сц.10: два сопоставимых кандидата → уточнение, не «первый».

    RC-TGT-UNB-CLARIFY, RC-TGT-SEM-AMBIG."""
    window = [
        _row(920001, text="Смета на ремонт моста завышена вдвое"),
        _row(920002, text="Смета на ремонт дороги завышена втрое"),
        _row(TARGET_TG, text="", author="Лея"),
    ]
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="")},
                around_rows=window)
    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG, cache=None)
    assert probe is not None
    assert probe.claim is None
    assert probe.ambiguous is True and len(probe.candidates) >= 2


@pytest.mark.asyncio
async def test_handler_answers_clarification_not_verdict(handler_env):
    """Сопоставимые кандидаты: короткое уточнение вместо вердикта по догадке.

    RC-TGT-UNB-CLARIFY, RC-S010."""
    window = [
        _row(920001, text="Смета на ремонт моста завышена вдвое"),
        _row(920002, text="Смета на ремонт дороги завышена втрое"),
    ]
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="")},
                around_rows=window)
    service = _service()
    fh.setup_factcheck(service, db)
    bot = AsyncMock()
    await fh.factcheck_handler(
        _make_msg(text="фактчек", message_id=TRIGGER_TG,
                  reply_to_message=_make_msg(message_id=TARGET_TG)), bot=bot)
    service.check_claim.assert_not_awaited()
    assert fh._reply.await_args.args[2] in FACTCHECK_CLARIFY_PHRASES


def test_dominant_dispute_ignores_reply_count_and_length():
    """BD-5 (§4.3): вес спора — маркеры и структура, не число ответов/длина.

    RC-TGT-UNB-NOHEURISTIC, RC-TGT-SEMANTIC-CORE."""
    from services.factcheck_context import ConversationContext
    rows = [
        _row(930001, text="Смета на ремонт моста завышена вдвое",
             author="Ирма"),
        _row(930002, text="это вброс", author="Ким",
             reply_to_id=930001),
        # длинное сообщение с большим числом ответов, но без дискуссионного
        # маркера — по запрещённому критерию оно и было бы «тезисом»
        _row(930010, text=DECOY + " " + DECOY, author="Ким"),
        _row(930011, text="согласен", author="Лея", reply_to_id=930010),
        _row(930012, text="ну да", author="Лея", reply_to_id=930010),
        _row(930013, text="ага", author="Лея", reply_to_id=930010),
        _row(930014, text="ок", author="Лея", reply_to_id=930010),
        _row(930015, text="плюс", author="Лея", reply_to_id=930010),
        _row(930016, text="верно", author="Лея", reply_to_id=930010),
        _row(TARGET_TG, text="", author="Лея"),
    ]
    messages = tuple(
        fcx.ContextMessage(
            message_id=int(r["id"]), tg_message_id=int(r["tg_message_id"]),
            chat_id=CHAT_ID, author=r["author_name"],
            timestamp=int(r["timestamp"]), reply_to_tg_id=r["reply_to_id"],
            is_forward=False, forward_source=None, text=r["text"] or "")
        for r in rows)
    ctx = ConversationContext(chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
                              trigger_tg_message_id=TRIGGER_TG,
                              messages=messages, window={})
    decision = fsg.evaluate_suitability(
        "ну и что там?", None, ctx,
        target_ref={"chat_id": CHAT_ID,
                    "target_tg_message_id": TARGET_TG})
    # Прежний вес (число ответов ×1.5 + длина) выбирал бы длинную реплику с
    # шестью ответами; по контракту это не критерий → честное уточнение.
    assert decision.decision == fsg.DECISION_AMBIGUOUS
    assert decision.reason_code == fsg._REASON_AMBIGUOUS
    assert all(item.anchor_tg_message_id != 930010
               for item in decision.claim_items)


def test_dispute_weight_has_no_reply_count_or_length_terms():
    """BD-5 (§4.3): ни число ответов, ни длина текста не меняют вес тезиса.

    RC-TGT-UNB-NOHEURISTIC, RC-TGT-SEMANTIC-CORE."""

    def _ctx(replies: int, filler: str = ""):
        rows = [
            _row(950001, text="бред, это вброс", author="Ким"),
            _row(950002, text=("неправда, ремонт дороги сдали " + filler).strip(),
                 author="Лея"),
            _row(TARGET_TG, text="", author="Лея"),
        ]
        for i in range(replies):
            rows.append(_row(950100 + i, text="согласен", author="Лея",
                             reply_to_id=950002))
        messages = tuple(
            fcx.ContextMessage(
                message_id=int(r["id"]),
                tg_message_id=int(r["tg_message_id"]), chat_id=CHAT_ID,
                author=r["author_name"], timestamp=int(r["timestamp"]),
                reply_to_tg_id=r["reply_to_id"], is_forward=False,
                forward_source=None, text=r["text"] or "")
            for r in rows)
        return fcx.ConversationContext(
            chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, messages=messages, window={})

    one = fsg._dominant_dispute(_ctx(1))
    six = fsg._dominant_dispute(_ctx(6))
    long_text = fsg._dominant_dispute(_ctx(
        1, filler="дорога объект приёмка акт сроки качество гравий асфальт"))
    assert one[0] is not None and one[0].tg_message_id == 950001
    # 6 ответов вместо одного — тот же вес: считается факт ответа, не счётчик
    assert one[1] == pytest.approx(six[1])
    assert one[2] == pytest.approx(six[2])
    # длинный текст проигравшего не двигает его вес
    assert one[1] == pytest.approx(long_text[1])
    assert one[2] == pytest.approx(long_text[2])


@pytest.mark.asyncio
async def test_v2_envelope_is_built_after_contextual_target(monkeypatch):
    """BD-2/I4: envelope собирается ПОСЛЕ выбора тезиса, поиск и вердикт — один.

    RC-CLM-TARGETREF-CONTINUITY, RC-CLM-PLAN-FROM-CLAIM, RC-S019."""
    monkeypatch.setattr(orch, "pipeline_v2_enabled", lambda: True)
    rows = [
        _row(THESIS_TG, text=THESIS, author="Ирма"),
        _row(DECOY_TG, text=DECOY, author="Ким",
             reply_to_id=THESIS_TG),
    ]
    origin = _row(THESIS_TG, text=THESIS)
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="",
                                            reply_to_id=THESIS_TG)},
                around_rows=rows,
                origin_rows={THESIS_TG: origin})
    seen = {}

    class _Service:
        async def check_claim_envelope(self, envelope, **kwargs):
            seen["envelope"] = envelope
            run = MagicMock()
            run.verdict_text = "разбор"
            run.verdict = MagicMock()
            run.verdict.factual_verdict = "insufficient_evidence"
            run.verdict.reason = None
            run.verdict.uncertainty = {}
            run.verdict.parts = ()
            run.verdict.route = "envelope_temporal"
            run.evidence_rows = ()
            run.fallback_used = False
            run.cache_hit = False
            seen["chat_context"] = kwargs.get("chat_context")
            return run

    req = orch.FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
        target_tg_message_id=TARGET_TG, target_text="", kind="reply")
    monkeypatch.setattr(tf, "record_temporal_run", AsyncMock())
    monkeypatch.setattr(orch, "deliver_factcheck", AsyncMock(), raising=False)
    outcome = await orch.run_factcheck(req, service=_Service(), db=db,
                                       bot=AsyncMock(), cache=_NullCache())
    envelope = seen.get("envelope")
    assert envelope is not None
    # вердикт читает РОВНО найденный контекстный тезис, а не пустую цель
    assert envelope.claim_text.strip() == THESIS.strip()
    assert envelope.target_tg_message_id == THESIS_TG
    assert envelope.claim_anchor_tg_message_id == THESIS_TG
    assert outcome in (orch.OUTCOME_VERDICT, orch.OUTCOME_ERROR)


@pytest.mark.asyncio
async def test_v2_passes_requester_identity_to_media_resolver(monkeypatch):
    """M11: v2 передаёт авторство/триггер в резолвер медиа.

    Без этого `media_readiness._same_author` при неизвестной личности считает
    «свой автор», и одиночное чужое фото «уверенно» приписывается цели.
    RC-MED-ALL-ROUTES, RC-MED-DATA-TRUTH."""
    from services import media_readiness as mr
    captured = {}

    async def fake_resolve(db, **kwargs):
        captured.update(kwargs)
        return {"association_status": mr.ASSOC_MISSING,
                "source_message_ids": (), "association_kind": ""}

    monkeypatch.setattr(mr, "resolve_target_media", fake_resolve)
    db = FakeDb(rows_by_tg={TARGET_TG: _row(TARGET_TG, text="")},
                around_rows=[_row(THESIS_TG, text=THESIS, author="Ирма")])
    req = orch.FactcheckRequest(
        chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
        target_tg_message_id=TARGET_TG, target_text="", kind="reply",
        requester_user_id=7777, requester_name="Ирма")
    await orch.run_factcheck(req, service=MagicMock(
        check_claim=AsyncMock(return_value="вердикт")), db=db,
        bot=AsyncMock(), cache=_NullCache())
    assert captured.get("author_user_id") == 7777
    assert captured.get("author_name") == "Ирма"
    assert captured.get("message_id") == TARGET_TG


@pytest.mark.asyncio
async def test_deferred_resume_has_no_phantom_trigger(monkeypatch):
    """BD-8: у отложенного возобновления нет сообщения-команды.

    Прежнее `trigger = target` ломало семантику маркера «текущая команда» и
    исключало из поиска не то сообщение. RC-TGT-INVARIANT, RC-S041."""
    captured = {}

    async def fake_run(req, **kwargs):
        captured["req"] = req
        return orch.OUTCOME_VERDICT

    monkeypatch.setattr(orch, "run_factcheck", fake_run)
    monkeypatch.setattr(orch, "_RUNTIME",
                        {"db": object(), "service": object(), "cache": None},
                        raising=False)
    ok = await orch.deliver_deferred_factcheck(
        {"chat_id": CHAT_ID, "trigger_message_id": TARGET_TG,
         "question": "проверь тезис"}, [], bot=AsyncMock())
    assert ok is True
    assert captured["req"].target_tg_message_id == TARGET_TG
    assert captured["req"].trigger_tg_message_id is None


@pytest.mark.asyncio
async def test_handler_v2_handoff_keeps_declared_contextual_target(
        handler_env, monkeypatch):
    """B1: маршрут handler -> v2 объявляет подмену цели и собирает envelope.

    Прежде v2 получал пару «текст тезиса + id пустой цели» и переразрешал
    публикацию по литеральной цели: трасса писала `target_source=stored_reply`,
    `claim_origin=target_text`, анкор и доставку — на пустое сообщение, а
    envelope не собирался вовсе (маршрут деградировал в legacy). Теперь цель/
    источник/анкор едут из handler'а, поэтому объявление и временной envelope
    реальны.

    RC-TGT-NO-REWRITE, RC-TGT-NO-FABRICATED-ID, RC-CLM-TARGETREF-CONTINUITY,
    RC-S024, RC-S042, RC-S052."""
    monkeypatch.setattr(fh, "_pipeline_v2_enabled", lambda: True)
    monkeypatch.setattr(tf, "record_temporal_run", AsyncMock(return_value="run-b1"))

    thesis_ts, reaction_ts = 1792000000, 1792400000
    origin_rows = {
        THESIS_TG: dict(_row(THESIS_TG, text=THESIS, author="Ирма"),
                        sent_at=thesis_ts),
        TARGET_TG: dict(_row(TARGET_TG, text="", author="Ким"),
                        sent_at=reaction_ts),
    }
    db = FakeDb(
        rows_by_tg={TARGET_TG: _row(TARGET_TG, text="",
                                    reply_to_id=THESIS_TG),
                    THESIS_TG: _row(THESIS_TG, text=THESIS, author="Ирма")},
        around_rows=[_row(THESIS_TG, text=THESIS, author="Ирма"),
                     _row(TARGET_TG, text="", author="Ким",
                          reply_to_id=THESIS_TG)],
        origin_rows=origin_rows)

    handoff = {}
    real_run = orch.run_factcheck

    async def _spy(req, **kwargs):
        handoff["req"] = req
        handoff["publication"] = kwargs.get("publication")
        return await real_run(req, **kwargs)

    monkeypatch.setattr(orch, "run_factcheck", _spy)

    trace = {}
    envelope_seen = {}

    def _capture_trace(publication, **kwargs):
        trace.update(publication.trace_fields())
        trace["delivery_reply_to"] = kwargs.get("delivery_reply_to")
        env = kwargs.get("envelope")
        trace["envelope_built"] = env is not None
        if env is not None:
            trace["envelope"] = env
        return trace

    monkeypatch.setattr(fcs, "emit_target_trace", _capture_trace)

    class _Service:
        async def check_claim_envelope(self, envelope, **kwargs):
            envelope_seen["envelope"] = envelope
            run = MagicMock()
            run.verdict_text = "разбор"
            run.verdict = MagicMock()
            run.verdict.factual_verdict = "insufficient_evidence"
            run.verdict.reason = None
            run.verdict.uncertainty = {}
            run.verdict.parts = ()
            run.verdict.route = "envelope_temporal"
            run.evidence_rows = ()
            run.fallback_used = False
            return run

        async def check_claim(self, *args, **kwargs):
            raise AssertionError("v2 прошёл legacy-путём вместо envelope")

    fh.setup_factcheck(_Service(), db)
    await fh.factcheck_handler(
        _make_msg(text="фактчек", message_id=TRIGGER_TG,
                  reply_to_message=_make_msg(message_id=TARGET_TG)),
        bot=AsyncMock())

    # 1. Передача: v2 получил уже разрешённую публикацию, а не голую цель.
    handed = handoff.get("publication")
    assert handed is not None, "handler не передал публикацию в v2"
    assert handed.target_source == "contextual"
    assert handed.target_tg_message_id == THESIS_TG
    assert handed.claim_anchor_tg_message_id == THESIS_TG

    # 2. Объявление: подмена не «маскируется» под текст пустой цели.
    assert trace["target_source"] == "contextual"
    assert trace["claim_origin"] == "context_window"
    assert trace["target_tg_message_id"] == THESIS_TG
    assert trace["claim_anchor_tg_message_id"] == THESIS_TG
    assert trace["target_tg_message_id"] != TARGET_TG
    assert trace["delivery_reply_to"] == TRIGGER_TG   # Reply на команду

    # 3. Envelope построен и читает тот же тезис с его же датой и автором.
    envelope = trace.get("envelope")
    assert trace["envelope_built"] is True
    assert envelope is not None and envelope_seen.get("envelope") is not None
    assert envelope.claim_text.strip() == THESIS.strip()
    assert envelope.target_tg_message_id == THESIS_TG
    assert envelope.claim_anchor_tg_message_id == THESIS_TG
    assert envelope.original_published_at == thesis_ts      # дата тезиса
    assert (envelope.attribution or {}).get("author") == "Ирма"


@pytest.mark.asyncio
async def test_contextual_claim_from_chain_keeps_its_own_date_and_author(
        handler_env, monkeypatch):
    """B2: тезис, найденный ТОЛЬКО через thread_chain, несёт свой id.

    Раньше `ContextClaim` для хода цепочки создавался без `tg_message_id`:
    трасса объявляла contextual-цель без анкора, а envelope строился по
    сообщению-реакции и приписывал тезису ЧУЖИЕ дату и автора (реакция
    вместо тезиса). Теперь id берётся из `item_id` хода (`tg:<id>`).

    RC-CLM-TARGETREF-CONTINUITY, RC-TGT-NO-FABRICATED-ID, RC-CLM-TARGET-AUTHOR,
    RC-S006, RC-S013, RC-S019."""
    from services.thread_chain import ChainItem

    monkeypatch.setattr(fh, "_temporal_on", lambda: True)
    monkeypatch.setattr(tf, "record_temporal_run",
                        AsyncMock(return_value="run-b2"))

    thesis_ts, reaction_ts = 1792000000, 1792400000

    async def _collect(db, chat_id, message, depth, **kwargs):
        # родитель пустой реакции доступен только цепочкой (вне окна)
        return [ChainItem(uid=5551, name="Ирма", text=THESIS, is_bot=False,
                          ts=thesis_ts, item_id=f"tg:{THESIS_TG}")]

    monkeypatch.setattr(tch, "collect_thread_chain", _collect)

    db = FakeDb(
        rows_by_tg={TARGET_TG: _row(TARGET_TG, text="",
                                    reply_to_id=THESIS_TG),
                    THESIS_TG: _row(THESIS_TG, text=THESIS, author="Ирма")},
        # окно НЕ содержит тезиса: единственный путь к нему — цепочка
        around_rows=[_row(TARGET_TG, text="", author="Ким")],
        origin_rows={
            THESIS_TG: dict(_row(THESIS_TG, text=THESIS, author="Ирма"),
                            sent_at=thesis_ts),
            TARGET_TG: dict(_row(TARGET_TG, text="", author="Ким"),
                            sent_at=reaction_ts),
        })

    captured = {}

    def _capture(publication, **kwargs):
        captured["publication"] = publication
        captured["delivery_reply_to"] = kwargs.get("delivery_reply_to")
        captured["envelope"] = kwargs.get("envelope")
        return {}

    monkeypatch.setattr(fh, "_emit_target_trace", _capture)

    class _Service:
        async def check_claim_envelope(self, envelope, **kwargs):
            captured["checked"] = envelope
            run = MagicMock()
            run.verdict_text = "разбор"
            run.verdict = MagicMock()
            run.verdict.factual_verdict = "insufficient_evidence"
            run.verdict.reason = None
            run.verdict.uncertainty = {}
            run.verdict.parts = ()
            run.verdict.route = "envelope_temporal"
            run.evidence_rows = ()
            run.fallback_used = False
            return run

    fh.setup_factcheck(_Service(), db)
    await fh.factcheck_handler(
        _make_msg(text="фактчек", message_id=TRIGGER_TG,
                  reply_to_message=_make_msg(message_id=TARGET_TG)),
        bot=AsyncMock())

    publication = captured["publication"]
    # объявленная contextual-цель без пустых полей: анкор — сам тезис
    assert publication.text.strip() == THESIS.strip()
    assert publication.target_source == "contextual"
    assert publication.target_tg_message_id == THESIS_TG
    assert publication.claim_anchor_tg_message_id == THESIS_TG
    assert publication.claim_anchor_author == "Ирма"
    assert captured["delivery_reply_to"] == TRIGGER_TG

    envelope = captured.get("envelope")
    assert envelope is not None
    assert envelope.target_tg_message_id == THESIS_TG
    assert envelope.claim_anchor_tg_message_id == THESIS_TG
    # дата и автор — у ТЕЗИСА, а не у реакции, на которую ответили
    assert envelope.original_published_at == thesis_ts
    assert envelope.original_published_at != reaction_ts
    assert (envelope.attribution or {}).get("author") == "Ирма"
    assert captured.get("checked") is envelope

    # Граница правила: у хода цепочки нет достоверного Telegram ID (`msg:` —
    # локальный id строки БД) → тезис НЕ объявляется contextual-целью вовсе.
    # Пустой/чужой анкор вместо честного «связь неизвестна» недопустим.
    async def _collect_msg_only(db, chat_id, message, depth, **kwargs):
        return [ChainItem(uid=5551, name="Ирма", text=THESIS, is_bot=False,
                          ts=thesis_ts, item_id="msg:4242")]

    monkeypatch.setattr(tch, "collect_thread_chain", _collect_msg_only)
    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG, reply_to_tg_id=THESIS_TG, cache=None)
    declared = None if probe is None else probe.claim
    # окно здесь содержит только пустую реакцию — достоверного тезиса нет
    window_ids = {TARGET_TG}
    assert declared is None or declared.tg_message_id in window_ids


# ── B. Медиа обязательно только при реальной зависимости ─────────────────────

@pytest.mark.asyncio
async def test_text_target_does_not_trigger_adjacent_media():
    """§10.2/I6: у достаточной текстовой цели соседнее фото не ищется.

    RC-MED-TEXTONLY, RC-S032, RC-MED-RELATION-NOT-PRESENCE."""
    photo_row = _row(913760, media_type="photo", author="Ким", mgid=None)
    db = FakeDb(rows_by_tg={THESIS_TG: _row(THESIS_TG, text=THESIS),
                            913760: photo_row})
    publication = await fcs.resolve_claim_publication(
        db, CHAT_ID, THESIS_TG, base_text=THESIS,
        trigger_tg_message_id=TRIGGER_TG, requester_user_id=5551,
        requester_name="Ирма", target_source="explicit_reply")
    assert publication.media_ambiguous is False
    assert publication.media_linked_adjacent is False
    assert publication.association_attempted is False
    assert publication.association_reason == "text_claim_sufficient"
    assert "изображение проверять" not in publication.notice()
    trace = publication.trace_fields()
    assert trace["media_expected"] is False
    assert trace["media_dependency_source"] == "text_claim_only"
    assert trace["media_notice_emitted"] is False


@pytest.mark.asyncio
async def test_unbound_command_still_attempts_media_association():
    """§10.2/сц.38: без текстового тезиса медиа-ассоциация запускается.

    RC-MED-UNBOUND, RC-S038, RC-MED-RELATION-NOT-PRESENCE."""
    from services import media_readiness as mr
    db = FakeDb(rows_by_tg={913770: _row(913770, text="фактчек",
                                         media_type="text", mgid=None)})
    resolved = await fcs.resolve_claim_publication(
        db, CHAT_ID, 913770, base_text="фактчек",
        trigger_tg_message_id=913770, requester_user_id=5551,
        requester_name="Ирма", target_source="command_text")
    assert resolved.text_sufficient is False
    # текста-тезиса нет → попытка связи обязана состояться и быть типизирована
    assert resolved.association_attempted is True
    assert resolved.association_status in (mr.ASSOC_RESOLVED,
                                           mr.ASSOC_MISSING,
                                           mr.ASSOC_AMBIGUOUS,
                                           "missing")
    trace = resolved.trace_fields()
    assert trace["association_attempted"] is True
    assert trace["media_dependency_source"] in ("adjacent_media_candidate",
                                                "unresolved")


def test_media_ambiguity_not_shown_over_sufficient_text():
    """M10: неоднозначность медиа не подмешивается к текстовому вердикту.

    RC-MED-NOTICE-SCOPE, RC-MED-TYPED-AMBIG."""
    publication = fcs.ClaimPublication(
        text="Смета завышена вдвое", caption_text="Смета завышена вдвое",
        text_sufficient=True, media_ambiguous=True,
        association_attempted=True, association_status="ambiguous")
    assert "изображение проверять" not in publication.notice()
    assert publication.notice_reason() == ""
    trace = publication.trace_fields()
    assert trace["media_notice_emitted"] is False

    # обратный случай: текста нет — уточнение обязано быть
    ambiguous = fcs.ClaimPublication(
        text="", text_sufficient=False, media_ambiguous=True,
        association_attempted=True, association_status="ambiguous",
        association_candidates=(913780, 913781))
    assert "изображение проверять" in ambiguous.notice()
    assert ambiguous.notice_reason() == "ambiguous_no_text_claim"


@pytest.mark.asyncio
async def test_command_with_explicit_thesis_is_not_replaced_by_photo(
        handler_env, monkeypatch):
    """§10.2/сц.33: «фактчек: правда ли …» проверяет свой тезис.

    RC-MED-TEXTCMD, RC-S033, RC-TGT-EXPLICIT-HINT."""
    thesis = "Правда ли, что сборка 4.19 вышла 12 марта 2026"
    db = FakeDb(rows_by_tg={913790: _row(913790, media_type="photo",
                                        author="Ирма", mgid=None)})
    service = _service()
    fh.setup_factcheck(service, db)
    bot = AsyncMock()
    await fh.factcheck_handler(
        _make_msg(text=f"фактчек: {thesis}", message_id=913791), bot=bot)
    assert service.check_claim.await_count == 1
    checked = service.check_claim.await_args.args[0]
    assert "сборка 4.19 вышла 12 марта 2026" in checked
    # ответ адресован самой команде (это и есть цель), а не фото
    assert handler_env.send_chunked_reply.await_args.args[3] == 913791


@pytest.mark.asyncio
async def test_album_attachment_still_counts_as_linked_media():
    """I8: сильная связь (media_group_id) не затронута гейтом текста.

    RC-MED-LINKED, RC-S043."""
    album = "grp-rcv5-913800"
    rows = {
        913800: _row(913800, media_type="photo", mgid=album),
        913801: _row(913801, media_type="photo", mgid=album,
                     caption="Смета: 41.7 млн против 96.3 млн"),
    }
    db = FakeDb(rows_by_tg=rows)
    publication = await fcs.resolve_claim_publication(
        db, CHAT_ID, 913800, base_text="",
        trigger_tg_message_id=913801, requester_user_id=5551,
        requester_name="Ирма", target_source="album")
    assert publication.media_group_id == album
    assert 913801 in publication.message_ids
    trace = publication.trace_fields()
    assert trace["media_expected"] is True
    assert trace["media_dependency_source"] in ("album", "linked_media")


# ── C. Честные техстатусы ──────────────────────────────────────────────────

def _outcome(**kwargs):
    base = {"evidence_map": None, "search_text": "", "queries_attempted": 0,
            "queries_used": 0, "refs_collected": 0, "fetch_errors": 0,
            "budget_exhausted": False}
    base.update(kwargs)
    return fsp.RetrievalOutcome(**base)


@pytest.mark.parametrize("kwargs,expected", [
    ({"queries_attempted": 3, "queries_used": 0, "provider_failures": 3},
     "provider_unavailable"),
    ({"queries_attempted": 2, "queries_used": 0, "budget_exhausted": True},
     "deadline_exceeded"),
    ({"queries_attempted": 2, "queries_used": 2,
      "search_text": "выдержки", "fetch_errors": 2}, "source_missing"),
    ({"queries_attempted": 2, "queries_used": 0, "empty_results": 2},
     "insufficient_evidence"),
    ({"queries_attempted": 2, "queries_used": 0, "irrelevant_results": 2},
     "insufficient_evidence"),
    ({"queries_attempted": 2, "queries_used": 2, "search_text": "выдержки"},
     "insufficient_evidence"),
])
def test_evidence_status_matrix_matches_real_counters(kwargs, expected):
    """§11.2: класс исхода следует из фактических счётчиков стадии.

    RC-EVS-PROVIDER-DOWN, RC-EVS-DEADLINE, RC-EVS-EXTRACT-FAILED,
    RC-EVS-EMPTY-RESULT, RC-EVS-NO-RELEVANT, RC-EVS-NO-CITABLE."""
    outcome = _outcome(**kwargs)
    klass = fcs.classify_retrieval(outcome)
    assert fcs._RETRIEVAL_REASON.get(klass) == expected


def test_internal_search_without_urls_is_not_a_parser_break():
    """ES-2/§11.2 п.6: «нашёл текст, ссылок нет» — не сбой разбора.

    RC-EVS-NO-CITABLE, RC-EVS-ONE-FACT-ONE-EXPL."""
    state = fcs.envelope_retrieval_state(
        evidence=(), retrieval=None,
        results_text="внутренний поиск вернул текст без ссылок",
        internal_failure_cause=None)
    assert state == fcs.RETRIEVAL_NO_RESULTS
    assert fcs._RETRIEVAL_REASON[state] == "insufficient_evidence"
    # настоящий технический сбой поиска по-прежнему остаётся техническим
    assert fcs.envelope_retrieval_state(
        evidence=(), retrieval=None, results_text="",
        internal_failure_cause="provider_error") == fcs.RETRIEVAL_SEARCH_FAILED
    assert fcs.envelope_retrieval_state(
        evidence=(), retrieval=None, results_text="",
        internal_failure_cause="empty_results") == fcs.RETRIEVAL_NO_RESULTS


def test_technical_headline_only_for_real_extraction_failure():
    """§11.2 п.3/5: «не удалось разобрать» — только при реальном сбое.

    RC-EVS-ONE-FACT-ONE-EXPL, RC-EVS-NO-GUESS."""
    broken = orch.CheckedVerdict(
        verdict_text="Тезис проверить не удалось.", route="envelope_temporal",
        factual_verdict="insufficient_evidence", reason_code="source_missing")
    broken_markup = fr.render_factcheck(
        orch.build_presentation(broken), broken).text
    assert "материалы не удалось разобрать" in broken_markup.lower()

    no_sources = orch.CheckedVerdict(
        verdict_text="По существу: смета завышена, но подтверждающих ссылок "
                     "нет.",
        route="envelope_temporal",
        factual_verdict="insufficient_evidence",
        reason_code="insufficient_evidence")
    plain_markup = fr.render_factcheck(
        orch.build_presentation(no_sources), no_sources).text
    assert "материалы не удалось разобрать" not in plain_markup.lower()
    assert "Недостаточно данных для проверки" in plain_markup


def test_mixed_run_headline_does_not_contradict_successful_part():
    """ES-6/§11.2 п.8: заголовок не противоречит успешной части (пиннинг).

    RC-EVS-MIXED-RUN."""
    mixed = orch.CheckedVerdict(
        verdict_text="Первая часть подтверждается, вторая не проверена.",
        route="envelope_temporal", factual_verdict="mixed",
        parts=(
            {"part_id": "p1", "text": "смета завышена", "factual_verdict":
                "supported", "evidence_refs": ["ev-1"]},
            {"part_id": "p2", "text": "подрядчик поддельный",
             "factual_verdict": "insufficient_evidence",
             "status_detail": "source_extract_failed"},
        ))
    markup = fr.render_factcheck(orch.build_presentation(mixed), mixed).text
    visible = fr.visible_text(markup).lower()
    assert "материалы не удалось разобрать" not in visible
    assert fr.headline_code(mixed) == "verdict:mixed"


def test_diagnostics_report_unknown_not_zero():
    """§11.3: неизвестный счётчик — «нет данных», не 0.

    RC-EVS-DIAG-COUNTERS."""
    unknown = fcs.evidence_diagnostics(
        retrieval=None, retrieval_state=fcs.RETRIEVAL_NOT_RUN,
        evidence=(), verdict=None)
    assert unknown["source_query_count"] == "н/д"
    assert unknown["provider_attempts"] == "н/д"
    assert unknown["documents_retrieved"] == "н/д"

    known = fcs.evidence_diagnostics(
        retrieval=_outcome(queries_attempted=4, queries_used=2,
                           refs_collected=1, fetch_errors=1,
                           search_text="выдержки",
                           budget_exhausted=True),
        retrieval_state=fcs.RETRIEVAL_PROCESSING_FAILED,
        evidence=({"evidence_id": "ev-1", "url": "https://ex.example/1"},),
        verdict=None)
    assert known["source_query_count"] == 4
    assert known["queries_with_results"] == 2
    assert known["extract_failures"] == 1
    assert known["citable_evidence_count"] == 1
    assert known["fetch_skipped_deadline"] == 0
    assert known["retrieval_class"] == fcs.RETRIEVAL_PROCESSING_FAILED


@pytest.mark.asyncio
async def test_deadline_skipped_fetch_is_counted_not_hidden(monkeypatch):
    """ES-3/§11.2 п.2: пропуск открытия источника по дедлайну фиксируется.

    RC-EVS-DEADLINE."""
    import services.factcheck_planner as _fsp
    monkeypatch.setattr(_fsp, "planner_enabled", lambda: True)
    block = ("Ремонт моста через Урал\nсмета 41.7 млн против 96.3 млн\n"
             "https://most.example/stat")
    top = ("Подрядчик занизил смету на ремонт моста через Урал: в документах "
           "стоит сумма 41.7 млн, а потрачено 96.3 млн")
    plan = fsp.build_retrieval_plan(
        fsg.evaluate_suitability(top, None, None,
                                 target_ref={"chat_id": CHAT_ID},
                                 allow_needs_context=False),
        ctx=None, claim_text=top)

    class SlowAgg:
        async def search(self, query, max_symbols, **kwargs):
            import asyncio
            await asyncio.sleep(0.05)
            return block

    fetched = []

    async def fetch_text(url, **kwargs):
        fetched.append(url)
        return block

    outcome = await fsp.run_retrieval(plan, aggregator=SlowAgg(),
                                      fetch_text=fetch_text,
                                      budget_seconds=0.02,
                                      max_rows_per_query=2)
    assert outcome.budget_exhausted is True
    assert fetched == []                       # стадия реально не выполнялась
    assert outcome.fetch_skipped_deadline >= 1
