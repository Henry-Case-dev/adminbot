"""UR-G acceptance tests — один ход, одна наблюдаемая цепочка стадий.

Покрывает строки карты `plans/features/unified-reply/requirements-map.json`:

* **UR-RES-01 / UR-30.2 (UR-G).** Источник (строка 29) требует, чтобы прямой
  ход и инициатива шли ОДНИМ кодом исполнения
  `L1 -> tools -> evidence -> L2 -> проверка -> речь -> отправка`; на
  фактической трассе видны одинаковые этапы, а различаются только исходные
  права говорить, форма доставки и recheck. Наблюдаемая сторона — существующая
  трасса хода (`services/turn_trace.py` → mca-13 → Inspector
  `/api/direct/turn-diagnostics`), нового стора/панели не вводится.

Тесты дискриминирующие: до фикса инициативный ход не начинал трассу хода
(`turn_trace.begin`) и не писал L1/tools/evidence, поэтому `direct_turn_context`
для `trigger=initiative` отсутствовал — тест падал на отсутствии события, а не
на формулировке.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-G
"""
import json
import time
from unittest.mock import AsyncMock

import pytest

from services import direct_chat_service as dcs
from services import mca_events
from services import turn_trace as tt
from tests.test_asap7_direct_l1 import _FakeLLM, _FakeRouter, _drive, _plan_json
from tests.test_direct_chat import CHAT_ID, FakeMemory, _bot, _make_service
from tests.test_ur_d_writer import (_candidate, _init_db, _make_intent,
                                   _situation)

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

CHAT = CHAT_ID
EVENT_CONTEXT = tt.EVENT_CONTEXT


# ── общий перехват трассы ───────────────────────────────────────────────────

@pytest.fixture()
def captured(monkeypatch):
    """Перехват существующей эмиссии mca-13 (реальный контракт выполняется:
    `built is not None` = событие принято allowlist'ами mca_events)."""
    real = mca_events.emit_mca_event
    rec: list = []

    def _rec(event_name, **kwargs):
        built = real(event_name, **kwargs)
        rec.append({"event_name": event_name, "built": built, **kwargs})
        return built

    monkeypatch.setattr(mca_events, "emit_mca_event", _rec)
    mca_events.reset_pending()
    tt.reset()
    yield rec
    mca_events.reset_pending()
    tt.reset()


@pytest.fixture(autouse=True)
def _exploration_off(monkeypatch):
    """Детерминизм инициативы: mca-10b draw не подменяет intent-кандидата."""
    import services.mca_exploration as expl

    async def _off(db, purpose, chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)


def _context_events(rec):
    return [e for e in rec if e["event_name"] == EVENT_CONTEXT]


def _payload(event):
    return event.get("usage_json") or {}


def _plan_json_with_search():
    plan = json.loads(_plan_json(capabilities_needed=["web_search"],
                                 knowledge_origin="open_world"))
    return json.dumps(plan, ensure_ascii=False)


# ── UR-RES-01: одинаковые этапы L1 -> tools -> evidence на обеих трассах ─────

async def _run_direct_turn(monkeypatch):
    """Полный прямой ход реальным pipeline (`handle`)."""
    llm = _FakeLLM(l1=_plan_json_with_search(), l2="ответ Direct")
    router = _FakeRouter(default="результат поиска про новую модель")
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "что нового в мире?", tool_router=router, llm=llm)
    await svc.handle(bot, msg, user)


async def _run_initiative_turn(tmp_path, monkeypatch, correlation_id):
    """Полный инициативный ход реальными методами сервиса
    (`plan_initiative_decision` → tool-фаза → `_l2_write_answer`), как в
    живом `handle_initiative`."""
    from types import SimpleNamespace

    llm = _FakeLLM(l1=_plan_json_with_search(), l2="ответ Initiative")
    router = _FakeRouter(default="результат поиска про релиз")
    writer = _make_service(llm=llm, memory=FakeMemory(window=[]),
                           tool_router=router)
    # Гейты evidence-политики — предмет UR-07/UR-08; здесь проверяется
    # наблюдаемость стадий, поэтому решение политики подаётся как данные,
    # а tool-фаза идёт РЕАЛЬНЫМ `run_tool_phase` с реальным роутером.
    claim = SimpleNamespace(entity="релиз", version="2.58", metric="",
                            date="", complete=True,
                            key=lambda: "релиз:2.58")
    decision = SimpleNamespace(required=True,
                               required_caps=("web_search",),
                               claims=(claim,))
    monkeypatch.setattr(writer, "_evidence_preflight",
                        AsyncMock(return_value=decision))
    monkeypatch.setattr(writer, "_evidence_reuse_pack",
                        lambda *a, **kw: None)
    monkeypatch.setattr(writer, "_emit_evidence_delivery_event",
                        lambda *a, **kw: None)
    monkeypatch.setattr(writer, "_record_evidence_delivery",
                        lambda *a, **kw: None)
    monkeypatch.setattr(writer, "_evidence_writer_note",
                        lambda *a, **kw: "")
    monkeypatch.setattr(writer, "_emit_evidence_egress_event",
                        lambda *a, **kw: None)
    monkeypatch.setattr(
        writer, "_l1_tool_subset",
        AsyncMock(return_value=(
            [{"function": {"name": "execute_web_search",
                           "description": "web"}}], [])))
    db = await _init_db(tmp_path, "ur_g_trace.db")
    try:
        intent_id, _row = await _make_intent(db)
        result = await dcs.handle_initiative(
            bot=_bot(), chat_id=CHAT, situation=_situation(),
            candidates=[_candidate(intent_id)], db=db,
            correlation_id=correlation_id, writer_service=writer,
            opportunity_row={"goal": "рассказать про релиз",
                             "kind": "follow_up",
                             "origin": "unanswered_question",
                             "created_at": 1})
        assert result["status"] == "sent", result
    finally:
        await db.close()


class TestUrRes01SameStagesOnBothTraces:
    @pytest.mark.asyncio
    async def test_direct_and_initiative_expose_same_stage_sequence(
            self, captured, monkeypatch, tmp_path):
        """Прямой ход и инициатива пишут ОДНУ цепочку стадий: L1 (action),
        tools (реальный поиск) и evidence (coverage доставленного пакета).
        Отличие — только исходный повод (`flow`/`trigger`)."""
        await _run_direct_turn(monkeypatch)
        direct_events = _context_events(captured)
        assert direct_events, "прямой ход не дал трассы хода"
        assert direct_events[-1].get("built") is not None, (
            "событие контекста прямого хода не принято mca-13")
        direct = _payload(direct_events[-1])
        assert direct["flow"] == tt.FLOW_DIRECT
        assert direct["l1"]["action"] == "reply"
        assert [t["tool"] for t in direct["tools"]], direct["tools"]
        assert direct["coverage"].get("sources", 0) >= 1

        before = len(captured)
        await _run_initiative_turn(tmp_path, monkeypatch, "corr-ur-res-01")
        initiative_events = [e for e in _context_events(captured[before:])]
        assert initiative_events, (
            "инициативный ход не дал трассы хода: этапы L1 -> tools -> "
            "evidence на нём не наблюдаемы")
        assert initiative_events[-1].get("built") is not None, (
            "терминальный контекст инициативы не принят mca-13")
        initiative = _payload(initiative_events[-1])
        # Тот же набор этапов, что у прямого хода.
        assert initiative["flow"] == tt.FLOW_INITIATIVE
        assert initiative["trigger"] == "initiative"
        assert initiative["l1"]["action"] == "reply"
        assert [t["tool"] for t in initiative["tools"]]
        assert initiative["coverage"].get("sources", 0) >= 1
        # Различается исходный повод, а не набор стадий.
        assert set(direct["l1"]) == set(initiative["l1"])
        assert {t["tool"] for t in direct["tools"]} == \
            {t["tool"] for t in initiative["tools"]}
        assert set(direct["coverage"]) <= set(initiative["coverage"])

    @pytest.mark.asyncio
    async def test_initiative_silent_still_visible_without_tools(
            self, captured, monkeypatch):
        """Ход, закончившийся на L1 (silent), тоже виден: честно нет tools,
        Writer не выдуман. Право инициативы на молчание сохранено."""
        llm = _FakeLLM(l1=_plan_json(action="silent"), l2="НЕ ДОЛЖЕН")
        service = _make_service(llm=llm, memory=FakeMemory(window=[]))
        plan = await service.plan_initiative_decision(
            CHAT, {"goal": "повод"}, correlation_id="corr-silent-trace")
        assert plan is not None and getattr(plan, "action", "") == "silent"
        events = _context_events(captured)
        assert events, "молчаливый инициативный ход не оставил трассы"
        assert events[-1].get("built") is not None, (
            "контекст молчаливого хода не принят mca-13")
        payload = _payload(events[-1])
        assert payload["l1"]["action"] == "silent"
        assert payload["tools"] == []
        assert events[-1].get("outcome") == "skipped"
        assert not [c for c in llm.calls if c.get("step") == "l2_writer"]


# ── UR-30.2: self-output на frozen UTC clock + реальный payload capture ──────

FROZEN_NOW = 1_795_632_000          # фиксированный UTC-инстант теста
YESTERDAY = FROZEN_NOW - 86_400
OTHER_CHAT = CHAT - 7


@pytest.fixture()
def frozen_utc(monkeypatch):
    """Замораживает UTC-инстант для модулей, которые штампуют `sent_at`
    (`import time; time.time()`), не трогая event-loop/таймеры процесса:
    подменяется ИМЯ `time` только в этих модулях, а `monotonic`/`sleep`
    делегируются настоящему модулю."""
    import time as _real

    class _Clock:
        def time(self):
            return float(FROZEN_NOW)

        def monotonic(self):
            return _real.monotonic()

        def sleep(self, seconds):
            return _real.sleep(seconds)

        def __getattr__(self, name):
            return getattr(_real, name)

    from services import bot_output_ledger as _bol
    from services import direct_chat_service as _dcs
    from services import summary_generator as _sum

    clock = _Clock()
    monkeypatch.setattr(_dcs, "time", clock)
    monkeypatch.setattr(_bol, "time", clock)
    monkeypatch.setattr(_sum, "time", clock)
    yield


async def _make_db(tmp_path, name="ur302.db"):
    from services.database import DatabaseService

    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


async def _ledger_rows(db, chat_id):
    cursor = await db.db.execute(
        "SELECT chat_id, tg_message_id, output_kind, source_feature, "
        "sent_at, content_text, correlation_id, delivery_status, "
        "parent_message_ref, revision_no, content_hash "
        "FROM mca_bot_outputs WHERE chat_id = ? ORDER BY output_id",
        (int(chat_id),))
    return [dict(row) for row in await cursor.fetchall()]


async def _publish_direct_turn(db, monkeypatch, *, text, answer, tg_base,
                               message_id=101, real_user_content=False,
                               chat_id=CHAT):
    """Один прямой ход реальным pipeline с РЕАЛЬНОЙ доставкой: транспорт —
    двойник Telegram, ledger/дата пишутся настоящим путём."""
    from types import SimpleNamespace

    from config.settings import Settings
    from tests.test_direct_chat import _message, _user
    class _SendBot:
        """Двойник aiogram-бота: каждое сообщение получает реальный id,
        поэтому ledger-строка адресуема и не сходится с другими маршрутами."""

        def __init__(self, first):
            self.id = 12345
            self._next = int(first)
            self.sent: list = []

        async def send_message(self, chat_id, text, **kwargs):
            mid = self._next
            self._next += 1
            self.sent.append((int(chat_id), str(text), dict(kwargs)))
            return SimpleNamespace(message_id=mid)

        async def send_chat_action(self, *a, **kw):
            return None

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", True)
    monkeypatch.setattr(Settings, "DIRECT_DECISION_MAKING_ENABLED", True)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    llm = _FakeLLM(l1=_plan_json(), l2=answer)
    svc = _make_service(db=db, tool_router=_FakeRouter(default="ok"),
                        llm=llm, memory=FakeMemory(window=[]))
    if not real_user_content:
        svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc.remember_bot_reply = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", AsyncMock())
    bot = _SendBot(tg_base)
    msg = _message(text=text, message_id=message_id, chat_id=chat_id)
    await svc.handle(bot, msg, _user())
    return llm, bot.sent


async def _publish_initiative_turn(db, monkeypatch, *, correlation_id,
                                   tg_id, send_fail=False, plan=None,
                                   target_row_id=None):
    """Инициативный ход реальным `handle_initiative` с реальной отправкой."""
    from types import SimpleNamespace

    class _Ibot:
        def __init__(self, first):
            self.id = 12345
            self._next = int(first)
            self.sent: list = []

        async def send_message(self, chat_id, text, **kwargs):
            mid = self._next
            self._next += 1
            self.sent.append((int(chat_id), str(text), dict(kwargs)))
            return SimpleNamespace(message_id=mid)

        async def send_chat_action(self, *a, **kw):
            return None

    llm = _FakeLLM(l1=_plan_json(), l2="инициативный ответ")
    writer = _make_service(llm=llm, memory=FakeMemory(window=[]))
    if plan is not None:
        async def _plan_override(chat_id, intent_row, *, correlation_id=None):
            return plan

        monkeypatch.setattr(writer, "plan_initiative_decision",
                            _plan_override)
    if send_fail:
        from services import telegram_send as _tg

        async def _send_fail(bot, chat_id, text, **kwargs):
            raise RuntimeError("telegram send failed")

        monkeypatch.setattr(_tg, "send_text", _send_fail)
    monkeypatch.setattr(writer, "_evidence_preflight",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(writer, "_evidence_reuse_pack",
                        lambda *a, **kw: None)
    # Намерение новее уже доставленного ответа (frozen clock): старый ответ
    # бота не означает «уже отвечено на этот повод» — иначе ход честно
    # закрывается как `already_answered` и доставки для ledger нет.
    from services import mca_intents as mi

    created = await mi.get_service(db).create_intent(
        CHAT, kind="follow_up", origin="unanswered_question",
        subject_ids=("q:ur302",), goal="что там с релизом?",
        source_refs=("msg:11",), not_before=FROZEN_NOW - 7200,
        expires_at=FROZEN_NOW + 3 * 86400, activation_condition="time_due",
        created_at=FROZEN_NOW + 60)
    intent_id = created[0] if isinstance(created, tuple) else created
    opportunity = {"goal": "повод", "kind": "follow_up",
                   "origin": "unanswered_question", "created_at": 1}
    if target_row_id is not None:
        opportunity["source_refs"] = (f"msg:{int(target_row_id)}",)
    result = await dcs.handle_initiative(
        bot=_Ibot(tg_id), chat_id=CHAT, situation=_situation(),
        candidates=[_candidate(intent_id)], db=db,
        correlation_id=correlation_id, writer_service=writer,
        opportunity_row=opportunity)
    return result


async def _publish_factcheck_turn(db, monkeypatch, *, verdict, tg_id):
    """Фактчек-доставка реальным handler-путём (`_factcheck_temporal`)."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from handlers import factcheck as fh
    from services import temporal_factcheck as tf
    from services.factcheck_service import ClaimPublication

    class _NullCtx:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _FcBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, **kwargs):
            self.sent.append((int(chat_id), str(text), dict(kwargs)))
            return SimpleNamespace(message_id=tg_id)

    pool = MagicMock()
    permit = MagicMock()
    permit.release = lambda: None
    pool.try_acquire = AsyncMock(return_value=permit)
    monkeypatch.setattr(fh, "get_smartmodule_concurrency_pool",
                        lambda: pool)
    monkeypatch.setattr(fh, "typing_active", lambda bot, chat: _NullCtx())
    monkeypatch.setattr(fh, "_cp_g", AsyncMock(return_value="contextual"))
    monkeypatch.setattr(tf, "build_envelope",
                        AsyncMock(return_value=(None, "test_rejected")))
    service = MagicMock()
    service.check_claim = AsyncMock(return_value=verdict)
    fh.setup_factcheck(service, db)

    def _msg(message_id):
        msg = MagicMock()
        msg.text = "фактчек"
        msg.message_id = message_id
        msg.chat = MagicMock()
        msg.chat.id = CHAT
        msg.from_user = MagicMock()
        msg.from_user.id = 7
        return msg

    target = _msg(77)
    msg = _msg(11)
    msg.reply_to_message = target
    publication = ClaimPublication(
        text="Проверяемый тезис", target_tg_message_id=77,
        target_source="explicit_reply", text_sufficient=True)
    try:
        return await fh._factcheck_temporal(
            msg, _FcBot(), target, "Проверяемый тезис", None, None,
            publication=publication, context_feed="ctx-feed")
    finally:
        fh._service = None
        fh._db = None


class TestUr302SelfOutputChain:
    @pytest.mark.asyncio
    async def test_chain_writes_one_ledger_and_payload_sees_own_words(
            self, frozen_utc, monkeypatch, tmp_path):
        """Direct → Initiative → Factcheck → Summary: каждый доставленный
        ответ попадает в ОДИН durable ledger на frozen UTC clock; собственные
        слова доступны только в своём чате, верно датируются и не становятся
        стилевыми командами (payload capture реального хода)."""
        from services import bot_output_ledger as bol
        from services import direct_context_composer as comp

        db = await _make_db(tmp_path)
        bol.bind_default_db(db)
        try:
            # (0) Реальный payload следующего хода: собственные слова доставлены
            # Writer'у с РЕАЛЬНОЙ датой отправки и остаются фактом диалога.
            # Ход идёт ПЕРВЫМ (чистый composer-контекст): строку не вытесняет
            # бюджетная аллокация последующих ходов; чат-скоуп проверяется тем
            # же ходом — слова другого чата в payload не попадают.
            import datetime as _dt

            await bol.record_delivered_output(
                db, chat_id=OTHER_CHAT, tg_message_id=801, text="вчера тут",
                bot_user_id=12345, output_kind="direct_reply",
                sent_at=YESTERDAY, correlation_id="corr-ur302-other")
            await bol.record_delivered_output(
                db, chat_id=CHAT, tg_message_id=802, text="верну вчера",
                bot_user_id=12345, output_kind="direct_reply",
                sent_at=YESTERDAY, correlation_id="corr-ur302-chat-a")
            llm0, _sent0 = await _publish_direct_turn(
                db, monkeypatch, text="Бот, напомни, что было вчера",
                answer="ответ0", tg_base=7600, message_id=90,
                real_user_content=True, chat_id=OTHER_CHAT)
            l2_payload = "".join(
                str(m.get("content"))
                for m in llm0.last_messages("l2_writer"))
            assert l2_payload, "L2 не получил payload"
            assert "вчера тут" in l2_payload
            # Дата в payload — фактическая отправка (UTC), а не «сейчас».
            stamp = _dt.datetime.fromtimestamp(
                YESTERDAY, _dt.timezone.utc).strftime("%d.%m.%Y")
            line = next(ln for ln in l2_payload.splitlines()
                        if "вчера тут" in ln)
            assert stamp in line, (stamp, line)
            # Чат-скоуп: собственные слова ДРУГОГО чата в payload не попадают.
            assert "верну вчера" not in l2_payload
            # Собственные слова — не стилевые команды: ни одного якоря
            # имитации в payload Writer'а с историей.
            assert "<Style_Anchors>" not in l2_payload
            assert "имитируй" not in l2_payload.lower()

            # (1) Direct: реальная доставка → ledger-строка в своём чате.
            _llm, sent = await _publish_direct_turn(
                db, monkeypatch, text="Бот, привет, как дела?",
                answer="ответ Direct", tg_base=7100)
            assert sent and sent[0][0] == CHAT
            rows = await _ledger_rows(db, CHAT)
            direct_rows = [r for r in rows
                           if r["content_text"] == "ответ Direct"]
            assert direct_rows, rows
            assert direct_rows[0]["output_kind"] == "direct_reply"
            assert direct_rows[0]["sent_at"] == FROZEN_NOW
            assert direct_rows[0]["delivery_status"] == "delivered"

            # (2) Initiative: тот же ledger, свой kind и correlation.
            result = await _publish_initiative_turn(
                db, monkeypatch, correlation_id="corr-ur302-init",
                tg_id=7200)
            assert result["status"] == "sent", result
            rows = await _ledger_rows(db, CHAT)
            init_rows = [r for r in rows
                         if r["output_kind"] == "initiative_reply"]
            assert init_rows, rows
            assert init_rows[0]["sent_at"] == FROZEN_NOW
            assert init_rows[0]["correlation_id"] == "corr-ur302-init"

            # (3) Factcheck: длинный вердикт доставляется чанками, а в ledger
            # остаётся ОДНА строка с полным текстом и маркером ветки.
            long_verdict = "Вердикт: тезис не подтверждён. " * 400
            outcome = await _publish_factcheck_turn(
                db, monkeypatch, verdict=long_verdict, tg_id=7300)
            assert outcome == "verdict", outcome
            rows = await _ledger_rows(db, CHAT)
            fc_rows = [r for r in rows
                       if r["source_feature"] == "factcheck"]
            assert len(fc_rows) == 1, fc_rows
            assert fc_rows[0]["content_text"] == long_verdict
            assert fc_rows[0]["sent_at"] == FROZEN_NOW
            assert fc_rows[0]["content_hash"] == bol.content_hash(
                long_verdict)
            assert fc_rows[0]["parent_message_ref"] == "tg:77"

            # (4) Summary: опубликованный саммари — тот же ledger (default-DB
            # binding, реальный `_record_published_output`).
            from services.summary_generator import SummaryGenerator
            from types import SimpleNamespace
            gen = object.__new__(SummaryGenerator)
            gen.memory = SimpleNamespace(db=db)
            gen.bot = SimpleNamespace(id=42)
            await gen._record_published_output(
                CHAT, 7400, "итог встречи: решили выпускать в пятницу",
                correlation_id="corr-ur302-summary")
            rows = await _ledger_rows(db, CHAT)
            sum_rows = [r for r in rows if r["source_feature"] == "summary"]
            assert sum_rows, rows
            assert sum_rows[0]["sent_at"] == FROZEN_NOW
            assert sum_rows[0]["content_text"].startswith("итог встречи")

            # (5) Правка собственного сообщения = новая ревизия, история
            # доступна; «последняя ревизия выигрывает» в обычном чтении.
            await db.record_bot_output(
                chat_id=CHAT, bot_user_id=42, tg_message_id=7400,
                revision_no=2, sent_at=FROZEN_NOW,
                parent_message_ref=None, output_kind="rich_message",
                content_text="итог встречи: перенесли на субботу",
                correlation_id="corr-ur302-summary",
                source_feature="summary", delivery_status="delivered")
            history = await db.get_bot_output_revisions(CHAT, 7400)
            assert [h["content_text"] for h in history] == [
                "итог встречи: решили выпускать в пятницу",
                "итог встречи: перенесли на субботу"]

            # (6) Неудавшийся send/retry — НЕ «слова бота»: строка провала не
            # попадает в историю доставленного.
            await db.record_bot_output(
                chat_id=CHAT, bot_user_id=42, tg_message_id=None,
                revision_no=1, sent_at=FROZEN_NOW, parent_message_ref=None,
                output_kind="direct_reply",
                content_text="недоставленный черновик",
                correlation_id="corr-ur302-fail",
                source_feature="direct_chat", delivery_status="failed")
            history_rows = await bol.list_bot_output_history(db, CHAT)
            texts = [r["text"] for r in history_rows]
            assert "недоставленный черновик" not in texts

            # (7) Чат-скоуп: слова бота другого чата не видны.
            other_frag = await comp.collect_self_output_fragments(
                db, chat_id=OTHER_CHAT, bot_user_id=42)
            own_frag = await comp.collect_self_output_fragments(
                db, chat_id=CHAT, bot_user_id=42)
            assert own_frag
            other_texts = {f.text for f in other_frag}
            own_texts = {f.text for f in own_frag}
            assert "ответ Direct" not in other_texts
            assert "верну вчера" not in other_texts
            assert "вчера тут" not in own_texts
            # Своя реплика — факт диалога (bot_statement, supporting), а не
            # стилевой образец/команда тона; даты — фактические отправки.
            assert all(f.kind == comp.KIND_BOT_STATEMENT for f in own_frag)
            assert all(f.authority == comp.AUTHORITY_SUPPORTING
                       for f in own_frag)
            stamps = {f.timestamp_utc for f in own_frag}
            assert FROZEN_NOW in stamps and YESTERDAY in stamps, stamps

            # (8) Вчерашняя цитата: реальная дата отправки из ledger (а не
            # «сейчас») и родитель, переживающий TTL bot_replies.
            await db.save_smart_message(
                user_id=11, chat_id=CHAT, text="я обещал вернуть вчера",
                reply_to_id=None, timestamp=YESTERDAY, media_type="text",
                author_name="Вася", message_id=700)
            await db.record_bot_output(
                chat_id=CHAT, bot_user_id=42, tg_message_id=701,
                revision_no=1, sent_at=YESTERDAY, parent_message_ref="tg:700",
                output_kind="direct_reply", content_text="верну вчера",
                correlation_id="corr-ur302-yesterday",
                source_feature="direct_chat", delivery_status="delivered")
            from services.thread_chain import collect_thread_chain

            async def _expired_parent(chat_id, tg_id):
                return None

            chain = await collect_thread_chain(
                db, CHAT, 701, depth=4, bot_parent_getter=_expired_parent)
            bot_items = [item for item in chain if item.is_bot]
            assert bot_items and bot_items[0].ts == YESTERDAY
            assert bot_items[0].reply_to_item_id == "tg:700"
        finally:
            bol.bind_default_db(None)
            await db.close()


# ── UR-RES-01/F1: доставка — обязательная терминальная стадия хода ───────────

def _trace_events(captured, correlation_id):
    return [e for e in captured
            if str(e.get("trace_id") or "") == str(correlation_id)]


def _chain_view(captured, correlation_id):
    """Проекция той же трассы ТЕМ ЖЕ кодом Inspector'а (web/api/routes).

    UR-RES-01/F2: проверяется ПРИНЯТОЕ событие mca-13 (`built is not None`),
    а не перехваченные kwargs: событие с недопустимым исходом контракт
    отбрасывает, и «зелёный» тест по kwargs скрывал бы потерю терминального
    контекста. Непринятое событие трассы — падение теста."""
    from web.api import routes as _routes

    events = _trace_events(captured, correlation_id)
    dropped = [{"event": e["event_name"], "outcome": e.get("outcome")}
               for e in events if e.get("built") is None]
    assert not dropped, (
        f"mca-13 не принял события трассы {correlation_id}: {dropped}")
    rows = [{"event_name": e["event_name"],
             "usage_json": e.get("usage_json"),
             "outcome": e.get("outcome"),
             "stage": e.get("stage"),
             "trace_id": e.get("trace_id"),
             "ts": e.get("ts") or 0}
            for e in events]
    return _routes._turn_chain_view(rows)


class TestUrRes01DeliveryStage:
    @pytest.mark.asyncio
    async def test_sent_initiative_turn_has_delivery_true(
            self, captured, monkeypatch, tmp_path):
        """Отправленный инициативный ход: контекст = success ТОЛЬКО вместе с
        реальной стадией доставки (id первого чанка, число чанков), а не
        «success, delivery: нет данных»."""
        db = await _make_db(tmp_path, "ur_g_delivery.db")
        try:
            result = await _publish_initiative_turn(
                db, monkeypatch, correlation_id="corr-f1-sent", tg_id=7800)
            assert result["status"] == "sent", result
        finally:
            await db.close()

        view = _chain_view(captured, "corr-f1-sent")
        assert view["stages"]["delivery"] is True, view
        assert view["delivery"]["outcome"] == "success", view["delivery"]
        delivery = view["delivery"]["delivery"]
        assert delivery["outcome"] == "success"
        assert delivery["tg_message_ids"] == [7800]
        assert view["stages"]["context"] is True
        assert view["context"]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_failed_send_is_not_success_without_delivery(
            self, captured, monkeypatch, tmp_path):
        """Сбой отправки: событие доставки есть, но исход не-success и не
        «нет данных»; контекст не объявляет успех заранее."""
        db = await _make_db(tmp_path, "ur_g_send_fail.db")
        try:
            result = await _publish_initiative_turn(
                db, monkeypatch, correlation_id="corr-f1-fail", tg_id=7801,
                send_fail=True)
            assert result["status"] == "error", result
        finally:
            await db.close()

        view = _chain_view(captured, "corr-f1-fail")
        assert view["stages"]["delivery"] is True, view
        # Исход события — не-success, а причина называет сбой хода; вложенный
        # payload несёт фактический исход терминальной стадии.
        assert view["delivery"]["outcome"] != "success", view["delivery"]
        assert view["delivery"]["delivery"]["reason"] == "initiative_error"
        assert view["delivery"]["delivery"]["outcome"] == "failed"
        # F-2: терминальный контекст ПЕРСИСТИТСЯ (built is not None внутри
        # `_chain_view`) и его исход — из словаря mca-13.
        assert view["stages"]["context"] is True
        assert view["context"]["outcome"] == "failed"

    @pytest.mark.asyncio
    async def test_react_branch_has_own_terminal_stage(
            self, captured, monkeypatch, tmp_path):
        """Ветка реакции — тоже доставка: успешный ход и канал `react`,
        а не заранее закрытый `skipped`."""
        from services.direct_l1 import L1Plan

        db = await _make_db(tmp_path, "ur_g_react.db")
        cursor = await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
            "media_type, author_name, is_forward, tg_message_id) "
            "VALUES (?, ?, ?, ?, 'text', 'addr', 0, ?)",
            (10, CHAT, "цель реакции", int(time.time()) - 30, 7900))
        await db.db.commit()
        target_row_id = cursor.lastrowid
        reacts: list = []

        async def _react(bot, chat_id, message_id, *, reaction=None,
                         reason_code=None):
            reacts.append((chat_id, message_id, reaction, reason_code))
            return "ok"

        monkeypatch.setattr(dcs, "react_moai", _react)
        plan = L1Plan(action="react", reaction="👍", delivery="react",
                      target_message_id=target_row_id, confidence=0.9,
                      confidence_bucket="high", source="llm")
        try:
            result = await _publish_initiative_turn(
                db, monkeypatch, correlation_id="corr-f1-react",
                tg_id=7802, plan=plan, target_row_id=target_row_id)
            assert result["status"] == "reacted", result
        finally:
            await db.close()
        assert reacts and reacts[0][1] == 7900, reacts

        view = _chain_view(captured, "corr-f1-react")
        assert view["stages"]["delivery"] is True, view
        assert view["delivery"]["outcome"] == "success"
        assert view["delivery"]["delivery"]["channel"] == "react"
        assert view["delivery"]["delivery"]["reason"] == "l1_react"
        assert view["stages"]["context"] is True
        assert view["context"]["outcome"] == "success"

    @pytest.mark.asyncio
    async def test_refused_reaction_is_not_delivery_success(
            self, captured, monkeypatch, tmp_path):
        """F-1: отказ реакции (`forbidden`/`rate_limited`/`unknown`) — не
        доставка. Успех только по `REACTION_OK`; отказ даёт честный stop с
        фактическим кодом исхода, а не `delivery:success`."""
        from services.direct_l1 import L1Plan

        db = await _make_db(tmp_path, "ur_g_react_refused.db")
        cursor = await db.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, timestamp, "
            "media_type, author_name, is_forward, tg_message_id) "
            "VALUES (?, ?, ?, ?, 'text', 'addr', 0, ?)",
            (10, CHAT, "цель реакции", int(time.time()) - 30, 7901))
        await db.db.commit()
        target_row_id = cursor.lastrowid
        reacts: list = []

        async def _react_forbidden(bot, chat_id, message_id, *, reaction=None,
                                   reason_code=None):
            reacts.append((chat_id, message_id, reaction, reason_code))
            return "forbidden"

        monkeypatch.setattr(dcs, "react_moai", _react_forbidden)
        plan = L1Plan(action="react", reaction="👍", delivery="react",
                      target_message_id=target_row_id, confidence=0.9,
                      confidence_bucket="high", source="llm")
        try:
            result = await _publish_initiative_turn(
                db, monkeypatch, correlation_id="corr-f1-react-refused",
                tg_id=7803, plan=plan, target_row_id=target_row_id)
            assert result["status"] == "silent", result
            assert result["reason_code"] == "forbidden", result
            assert result["reaction_outcome"] == "forbidden", result
        finally:
            await db.close()
        assert reacts and reacts[0][1] == 7901, reacts

        view = _chain_view(captured, "corr-f1-react-refused")
        # Доставка зафиксирована, но НЕ как успех: причина — код отказа.
        assert view["stages"]["delivery"] is True, view
        assert view["delivery"]["outcome"] != "success", view["delivery"]
        assert view["delivery"]["delivery"]["outcome"] == "silent"
        assert view["delivery"]["delivery"]["reason"] == "forbidden"
        # Контекст терминальный и принят контрактом (не потерян на отказе).
        assert view["stages"]["context"] is True
        assert view["context"]["outcome"] == "silent"
        # Ни одного заявленного успеха реакции в durable-буфере.
        assert not any(
            (e.get("usage_json") or {}).get("delivery", {}).get("outcome")
            == "success"
            for e in _trace_events(captured, "corr-f1-react-refused")), (
                "отказ реакции не имеет права давать delivery success")
