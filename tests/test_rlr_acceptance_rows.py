# -*- coding: utf-8 -*-
"""RLR-08-ROWS — остаточные строки §8 R-08, у которых не было durable-доказательства.

Источник: `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md` §8
(таблица R-08), карта `plans/features/remove-legacy-rephrasing/requirements-map.json`
и `plans/features/remove-legacy-rephrasing/route-matrix.md` §6 (что уже покрыто
`test_rlr_negative_matrix.py`, `test_rlr_length_continuation.py`,
`test_rlr_proof_restart.py` — те строки здесь НЕ дублируются).

Покрываемые строки (номер — как в §8 R-08):

* R-08.1  прямой ответ без инструментов: L1 → ровно один L2, после L2 ни
  LLM-rewrite, ни смыслового удаления;
* R-08.2  прямой ответ с поиском: tools/evidence → один L2, свободный текст
  инструмента не пересказывает второй автор;
* R-08.3  инициатива: L1 решает silent/react/reply; при reply — общий L2,
  evidence и никакой постперегенерации;
* R-08.4  `SYSTEM2_DIRECT_ENABLED=false` и технологическая деградация
  (отказ L1-планера) не активируют двойного Writer'а;
* R-08.10 stats/измерения: в Writer входят проверенные `MetricResult`,
  post-L2 не вставляет чужую фразу и не скрывает невозможность данных;
* R-08.12 фактчек многосоставного утверждения: sources→claims→verdict
  сохранены, `insufficient_evidence` не поднимается до положительного;
* R-08.13 невалидная схема: правка на machine stage (bounded repair плана)
  либо честное завершение (bounded stop оркестратора), не второй писатель;
* R-08.15 fallback модели/провайдера: та же стадия, семантически
  эквивалентный контекст с защищёнными блоками, без legacy-маршрута;
* R-08.17 длинная Telegram-реплика: chunking без обрыва/перестановки,
  авторство и ссылки целы.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ (честная граница): живой прогон на реальном
провайдере/поиске и сверка `raw_final` ↔ Telegram-payload — это R-09
(отдельная live-стадия). Здесь — РЕАЛЬНЫЕ швы продакшена на детерминированных
фейках моделей: `DirectChatService.handle` (живой pipeline L1/tools/L2),
`_l2_write_answer`, `handle_initiative`, `run_adaptive_chain`/`run_tool_phase`,
`negative_constraints.verbalize_validated`, `evidence_policy`,
`LLMClient` (реальная fallback-нога с адаптером), `ToolRouter` stats-режим на
реальном SQLite+FTS, `telegram_send`/`send_chunked_reply`. Мокаются только
I/O-края (LLM-провайдер, telegram-бот, ввод контента). Feature gates
(mca_gates/settings) не подменяются — их состояние проверяется ассертом,
чтобы «гейт случайно OFF» не выдавался за PASS.

TEST-LIFECYCLE: CONTRACT + REGRESSION owner=RLR-08-ROWS
"""
from __future__ import annotations

import json
import re
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings, resolve_legacy_rephrasing_env_flag
from services import hot_config as hot
from services import mca_events
from services import mca_gates
from services import negative_constraints as nc
from services.database import DatabaseService
from services.direct_chat_service import DirectChatService
from services.llm_client import LLMClient, LLMError
from services.tool_router import ToolDeps, ToolRouter
from tests.test_asap7_direct_l1 import _FakeLLM, _FakeRouter, _drive, _plan_json
from tests.test_direct_chat import CHAT_ID, _bot, _make_service

pytestmark = [pytest.mark.system2, pytest.mark.asap3]

#: Закрытый набор детерминированных типографических замен реального
#: style-pass (тире/кавычки). Это не смысловая правка: слова, отрицания и
#: порядок предложений не меняются.
_TYPOGRAPHIC_MAP = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"',
                                  "—": "-", "–": "-"})
_WORD_RE = re.compile(r"[а-яёa-z0-9]+")


# ── общая инфраструктура ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_hot_keys(monkeypatch):
    """Изоляция фоновых побочек: self-awareness не тратит вызовы LLM,
    межчанковый sleep реального chunking не тормозит прогон."""
    real = hot.get

    def _get(key, default=None):
        if key == "flags.bot_self_awareness_enabled":
            return False
        if key == "limits.summary_chunk_delay":
            return 0
        return real(key, default)

    monkeypatch.setattr(hot, "get", _get)


@pytest.fixture
def events(monkeypatch):
    """Наблюдаемый канал mca-13: перехват (event_name, outcome, fields)."""
    seen: list = []
    real = mca_events.emit_mca_event

    def spy(event_name, *, outcome, **fields):
        seen.append({"event_name": event_name, "outcome": outcome, **fields})
        return None

    monkeypatch.setattr(mca_events, "emit_mca_event", spy)
    try:
        yield seen
    finally:
        mca_events.emit_mca_event = real


def _delivered(svc):
    """Текст, реально ушедший в единственный шов Direct-ответа."""
    assert svc._send_direct_answer.await_count == 1, \
        svc._send_direct_answer.await_args_list
    return svc._send_direct_answer.await_args.args[2]


def _assert_as_authored(delivered: str, authored: str) -> None:
    """Тот же авторский текст: слова и отрицания целы, только типографика."""
    assert delivered in (authored, authored.translate(_TYPOGRAPHIC_MAP)), (
        f"смысловая правка готовой речи: {delivered!r} != {authored!r}")
    assert _WORD_RE.findall(delivered.casefold()) == \
        _WORD_RE.findall(authored.casefold())
    assert nc._negation_signature(delivered) == \
        nc._negation_signature(authored)


def _writer_payload(llm) -> str:
    return "".join(str(m.get("content"))
                   for m in llm.last_messages("l2_writer"))


def _no_legacy_stage(llm) -> None:
    """Ни одного шага «второго автора»/legacy-маршрута в LLM-стадиях хода."""
    stages = [str(s) for s in llm.steps()]
    forbidden = {"stage1", "stage2", "duplicate_guard_retry",
                 "freshness_retry", "form_retry", "numeric_retry",
                 "cliche_retry", "format_retry", "metatext_retry"}
    assert forbidden.isdisjoint(set(stages)), stages


# ════════════════════════════════════════════════════════════════════════════
# R-08.1 — прямой ответ без инструментов: L1 → ровно один L2
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r0801_direct_without_tools_one_l1_then_one_l2(monkeypatch):
    """L1 → один L2; после L2 нет ни LLM-rewrite, ни смыслового удаления.

    Роутер присутствует, но план `tool_policy=none`/без capabilities — это
    реальная ветка «ответ без инструментов»: tool-фаза возвращает None
    (`_l1_tool_phase` → `run_tool_phase` без схем), Writer — единственный
    автор. Считаем ФАКТИЧЕСКИЕ стадии LLM и доставленный текст.
    """
    answer = "Ну, если коротко: я бы не стал это трогать."
    router = _FakeRouter()
    llm = _FakeLLM(l1=_plan_json(), l2=answer)
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "что скажешь про этот план?", llm=llm,
        tool_router=router)
    await svc.handle(bot, msg, user)

    assert router.dispatched == [], router.dispatched      # инструментов нет
    assert llm.steps() == ["l1_planner", "l2_writer"], llm.steps()
    _assert_as_authored(_delivered(svc), answer)
    # Ни одного вызова после L2: стадий ровно две, L2 последняя.
    assert llm.steps()[-1] == "l2_writer"
    _no_legacy_stage(llm)


# ════════════════════════════════════════════════════════════════════════════
# R-08.2 — прямой ответ с поиском: evidence → один L2, без «пересказчика»
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r0802_search_evidence_then_single_l2_not_retold(monkeypatch):
    """Свободный текст инструмента — данные для Writer'а, а не черновик.

    Инструмент возвращает готовую фразу; контракт §8 R-08.2 запрещает
    публиковать её как ответ и запрещает второй литературный проход по ней.
    Проверяем: инструмент реально вызван, его текст доехал в
    `<Tool_Evidence>` с атрибуцией, а доставлен ровно текст L2 (один автор).
    """
    tool_text = "ЧЕРНОВИК ИНСТРУМЕНТА: завтра дождь, 12 градусов"
    answer = "Завтра дождь и 12 градусов — зонт не забудь."
    router = _FakeRouter(outputs={"execute_web_search": tool_text})
    llm = _FakeLLM(
        l1=_plan_json(tool_policy="auto", capabilities_needed=["web_search"]),
        l2=answer)
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "проверь в интернете погоду на завтра", llm=llm,
        tool_router=router)
    await svc.handle(bot, msg, user)

    assert [d["tool"] for d in router.dispatched] == ["execute_web_search"]
    assert llm.steps() == ["l1_planner", "l2_writer"], llm.steps()
    payload = _writer_payload(llm)
    assert "<Tool_Evidence>" in payload
    assert "[ИСТОЧНИК 1 | execute_web_search | ok | " in payload
    # Дата не выдумана: у мока выдачи даты нет — так и написано.
    assert "дата публикации не сообщается источником" in payload
    assert "завтра дождь, 12 градусов" in payload
    delivered = _delivered(svc)
    assert delivered != tool_text                  # текст тула не опубликован
    _assert_as_authored(delivered, answer)
    _no_legacy_stage(llm)


# ════════════════════════════════════════════════════════════════════════════
# R-08.3 — инициатива: silent/react/reply; reply идёт общим L2
# ════════════════════════════════════════════════════════════════════════════


async def _initiative_db(tmp_path, name):
    from services import mca_intents as mi

    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    now = int(time.time())
    intent_id = await mi.get_service(db).create_intent(
        CHAT_ID, kind="follow_up", origin="unanswered_question",
        subject_ids=("q:test",), goal="что там с релизом и погодой?",
        source_refs=("msg:11",), not_before=now - 7200,
        expires_at=now + 3 * 86400, activation_condition="time_due",
        created_at=now - 7200)
    row = await mi.get_service(db).store.get_intent(intent_id)
    return db, mi, intent_id, row


@pytest.fixture(autouse=True)
def _exploration_off(monkeypatch):
    """Детерминизм: mca-10b exploration-draw не подменяет intent-кандидата
    (легитимный прод-путь, покрыт своими тестами)."""
    import services.mca_exploration as expl

    async def _off(db, purpose, chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["silent", "react"])
async def test_r0803_initiative_silent_or_react_writes_no_text(
        tmp_path, monkeypatch, action):
    """L1 решил не отвечать текстом → ни отправки, ни L2-генерации.

    `react` без валидной цели честно завершается молчанием (реакция не
    выдумывается), но в ОБОИХ случаях второго текстового автора нет.
    """
    from services import direct_chat_service as dcs
    from services import mca_intents as mi

    db, _mi, intent_id, row = await _initiative_db(tmp_path, f"i_{action}.db")
    sent: list = []

    async def _send_text(bot, chat_id, text, *a, **kw):
        sent.append(text)

    monkeypatch.setattr("services.telegram_send.send_text", _send_text)
    llm = _FakeLLM(l1=_plan_json(action=action))
    writer = _make_service(llm=llm, tool_router=_FakeRouter())
    writer._initiative_persona_block = AsyncMock(return_value="")
    try:
        result = await dcs.handle_initiative(
            bot=_bot(), chat_id=CHAT_ID,
            situation=mi.InitiativeSituation(trigger_kind="intent_due",
                                             chat_id=CHAT_ID),
            candidates=[mi.candidate_from_trigger(
                trigger_kind="intent_due", chat_id=CHAT_ID,
                intent_id=intent_id, reason_code="default")],
            db=db, correlation_id=f"corr-r0803-{action}", writer_service=writer)
        assert result["status"] in ("silent", "reacted"), result
        assert sent == [], sent
        assert "l2_writer" not in llm.steps(), llm.steps()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_r0803_initiative_reply_uses_shared_l2_once(
        tmp_path, monkeypatch):
    """Инициатива с поиском: tools/evidence → тот же L2, без перегенерации.

    Проверяются реальные швы инициативного пути: `handle_initiative` →
    `generate_initiative_reply` → общая tool-фаза (`_FakeRouter` как I/O-край
    поиска) → `_l2_write_answer` (writer=initiative_writer) → единственная
    отправка через `telegram_send.send_text`.
    """
    from services import direct_chat_service as dcs
    from services import mca_intents as mi

    db, _mi, intent_id, _row = await _initiative_db(tmp_path, "i_reply.db")
    sent: list = []

    async def _send_text(bot, chat_id, text, *a, **kw):
        sent.append(text)
        return SimpleNamespace(message_id=8001)

    monkeypatch.setattr("services.telegram_send.send_text", _send_text)
    answer = "По релизу: сборка вышла, погода завтра дождливая."
    router = _FakeRouter(outputs={"execute_web_search": "релиз 2.58.160 вышел"})
    llm = _FakeLLM(
        l1=_plan_json(tool_policy="auto", capabilities_needed=["web_search"],
                      knowledge_origin="open_world", search_intent="required",
                      external_claims=[{"entity": "релиз", "version": "2.58.160"}]),
        l2=answer)
    writer = _make_service(llm=llm, tool_router=router)
    try:
        result = await dcs.handle_initiative(
            bot=_bot(), chat_id=CHAT_ID,
            situation=mi.InitiativeSituation(trigger_kind="intent_due",
                                             chat_id=CHAT_ID),
            candidates=[mi.candidate_from_trigger(
                trigger_kind="intent_due", chat_id=CHAT_ID,
                intent_id=intent_id, reason_code="default")],
            db=db, correlation_id="corr-r0803-reply", writer_service=writer)
        assert result["status"] == "sent", result
        # Один и тот же L2-канал: одна финальная генерация, без повтора.
        assert llm.steps().count("l2_writer") == 1, llm.steps()
        payload = _writer_payload(llm)
        assert "<Tool_Evidence>" in payload
        assert "релиз 2.58.160 вышел" in payload
        assert len(sent) == 1, sent
        _assert_as_authored(sent[0], answer)
        _no_legacy_stage(llm)
    finally:
        await db.close()


# ════════════════════════════════════════════════════════════════════════════
# R-08.4 — старый флаг и технологическая деградация не дают второго автора
# ════════════════════════════════════════════════════════════════════════════


def test_r0804_legacy_flag_resolves_false_for_any_raw_value():
    """Реальный резолв конфигурации: `SYSTEM2_DIRECT_ENABLED` всегда False.

    Ни `false`, ни `0`, ни `null`, ни `true` не могут включить старую
    архитектуру — ключ классифицирован как `deprecated_compat`.
    """
    for raw in (True, False, 0, 1, None, "true", "0", ""):
        assert resolve_legacy_rephrasing_env_flag(
            "SYSTEM2_DIRECT_ENABLED", raw) is False, raw
    assert Settings.SYSTEM2_DIRECT_ENABLED is False
    # Ключ не влияет на прочие имена (не «выключить всё»).
    assert resolve_legacy_rephrasing_env_flag("OTHER_FLAG", "true") is True


@pytest.mark.asyncio
async def test_r0804_planner_outage_keeps_single_writer(monkeypatch):
    """Деградация L1-планера: дет. fallback-план → ровно один L2.

    Технологическая деградация не меняет архитектуру: план строится
    детерминированно, Writer остаётся единственным автором, второй
    генерации/старых стадий нет. Флаг `SYSTEM2_DIRECT_ENABLED=false`
    выставлен явно (значение из конфигурации и так False).
    """
    diagnostics: list = []
    import services.direct_l1 as _l1

    real_record = _l1.record_l1_diagnostics

    def _record(chat_id, **fields):
        diagnostics.append(dict(fields))
        return real_record(chat_id, **fields)

    monkeypatch.setattr(_l1, "record_l1_diagnostics", _record)
    monkeypatch.setattr(Settings, "SYSTEM2_DIRECT_ENABLED", False)
    answer = "Отвечаю без плана: коротко и по делу."
    llm = _FakeLLM(l1_error=LLMError("planner down"), l2=answer)
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "ну что там по вчерашнему?", llm=llm,
        tool_router=_FakeRouter())
    await svc.handle(bot, msg, user)

    assert llm.steps() == ["l1_planner", "l2_writer"], llm.steps()
    _assert_as_authored(_delivered(svc), answer)
    assert any(d.get("planner_fallback_reason") == "planner_outage"
               for d in diagnostics), diagnostics
    _no_legacy_stage(llm)


# ════════════════════════════════════════════════════════════════════════════
# R-08.10 — stats/измерения: проверенные MetricResult в Writer, без post-L2
# ════════════════════════════════════════════════════════════════════════════

_STATS_ROWS = [
    (1, 10, "Олег", 100, "Вася шиз"),
    (2, 20, "Вася", 101, "Вася пришел"),
    (3, 10, "Олег", 102, "шиз шиз шиз"),
    (4, 30, "Петя", 103, "Петя дома"),
    (5, 999, "Бот", 104, "Шиз, Вася"),
    (6, 10, "Олег", 105, "ничего"),
    (7, 30, "Петя", 106, "шизофрения"),
]


async def _stats_db() -> DatabaseService:
    """Реальная SQLite+FTS: измерение считает настоящий `chat_statistics`."""
    db = DatabaseService(":memory:")
    await db.initialize()
    for row_id, uid, name, ts, text in _STATS_ROWS:
        await db.db.execute(
            "INSERT INTO smart_messages(id,user_id,chat_id,text,timestamp,"
            "author_name,is_forward,forward_source) VALUES(?,?,?,?,?,?,0,'')",
            (row_id, uid, CHAT_ID, text, ts, name))
    await db.db.executemany(
        "INSERT INTO smart_messages_fts(rowid,text) VALUES(?,?)",
        [(row[0], row[4]) for row in _STATS_ROWS])
    await db.db.commit()
    return db


async def _stats_turn(monkeypatch, *, db, llm, query="сколько раз писали про шиз?"):
    """Ход Direct, где stats-инструмент исполняется РЕАЛЬНО.

    Заменён только слой оркестрации tool-плана (какой инструмент и с какими
    аргументами вызвать — это решение модели): сам `ToolRouter.dispatch`,
    `chat_statistics.measure`, наполнение `ctx.metric_results`, упаковка
    evidence и Writer — продакшн-код.
    """
    from services import direct_execution as _dx

    router = ToolRouter(ToolDeps(search=MagicMock(), memory=MagicMock(), db=db))
    real_phase = DirectChatService._l1_tool_phase
    captured: dict = {}

    async def _phase(self, payload, tool_ctx, **kwargs):
        captured["ctx"] = tool_ctx
        out = await router.dispatch("query_chat_memory", {
            "query": "шиз", "time_range": "all",
            "stats": {"metric": "messages", "match_mode": "prefix",
                      "phrase": "шиз"}}, tool_ctx)
        captured["payload"] = out
        return _dx.ChainResult(
            out, rounds_used=1,
            tool_trace=[{"round": 1, "tool": "query_chat_memory", "ok": True}],
            evidence_sources=[_dx.EvidenceSource(
                tool="query_chat_memory", status="ok", content=out,
                total_chars=len(out), content_ref="ev:stats")],
            chain_meta={"mode": "simple_tools"})

    monkeypatch.setattr(DirectChatService, "_l1_tool_phase", _phase)
    try:
        svc, _react, bot, msg, user = _drive(
            monkeypatch, query, llm=llm, tool_router=router)
        await svc.handle(bot, msg, user)
    finally:
        monkeypatch.setattr(DirectChatService, "_l1_tool_phase", real_phase)
    return svc, captured


@pytest.mark.asyncio
async def test_r0810_metric_result_reaches_writer_and_is_delivered(
        monkeypatch, events):
    """Число Writer'а = проверенный `MetricResult`; вставки после L2 нет."""
    assert mca_gates.numeric_claim_guard_enabled() is True
    assert mca_gates.chat_statistics_enabled() is True
    db = await _stats_db()
    try:
        answer = "Про шиз писали 4 раза, если считать по совпадениям."
        llm = _FakeLLM(
            l1=_plan_json(tool_policy="auto",
                          capabilities_needed=["chat_memory"]),
            l2=answer)
        svc, captured = await _stats_turn(monkeypatch, db=db, llm=llm)

        metric = captured["ctx"].metric_results[0]
        assert metric.value == 4 and metric.unit == "messages"
        # Проверенное измерение доехало до Writer'а ДО генерации: в payload
        # есть тот же metric_id и та же человекочитаемая формулировка
        # (не «число из воздуха»).
        payload = _writer_payload(llm)
        assert metric.metric_id in payload
        assert metric.human_label in payload
        # Текст Writer'а с подтверждённым числом доставлен как написан.
        _assert_as_authored(_delivered(svc), answer)
        # Подтверждённое число не считается расхождением (наблюдения нет).
        assert not [e for e in events
                    if e["event_name"] == "numeric_claim_guard"], events
        assert llm.steps().count("l2_writer") == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_r0810_unvalidated_number_not_replaced_after_l2(
        monkeypatch, events):
    """Выдуманное число не подменяется и не вырезается после L2 — только
    честное наблюдение (никакой вставки `verified_phrase`)."""
    assert mca_gates.numeric_claim_guard_enabled() is True
    db = await _stats_db()
    try:
        answer = "Ты писал про шиз 12 345 раз, я проверял."
        llm = _FakeLLM(
            l1=_plan_json(tool_policy="auto",
                          capabilities_needed=["chat_memory"]),
            l2=answer)
        svc, captured = await _stats_turn(monkeypatch, db=db, llm=llm)

        metric = captured["ctx"].metric_results[0]
        assert metric.value == 4
        delivered = _delivered(svc)
        assert delivered == answer                  # ни вставки, ни удаления
        assert metric.verified_phrase not in delivered
        assert "12 345" in delivered
        observed = [e for e in events
                    if e["event_name"] == "numeric_claim_guard"]
        assert observed, [e["event_name"] for e in events]
        usage = observed[0]["usage_json"]
        assert observed[0]["outcome"] == "skipped"
        assert usage["corrected"] is False
        assert usage["observed"] is True
        assert llm.steps().count("l2_writer") == 1
    finally:
        await db.close()


# ════════════════════════════════════════════════════════════════════════════
# R-08.12 — фактчек многосоставного утверждения
# ════════════════════════════════════════════════════════════════════════════

_COMPOSITE = {
    "claim": "в 2025 году вышел релиз 3.0, а до этого было 40 коммитов",
    "findings": [
        {"assertion": "в 2025 году вышел релиз 3.0", "status": "true",
         "human_time": "март 2025", "author": "Вася",
         "evidence": "тег v3.0 от 12 марта"},
        {"assertion": "до релиза было 40 коммитов", "status": "unverifiable",
         "human_time": "без даты", "author": "Петя",
         "evidence": "счётчик коммитов не сохранился"},
    ],
    "verdict": "Релиз подтверждается, число коммитов проверить нельзя.",
    "response_mode": "serious",
}


def _fc_llm(generated):
    """Stage-1 отдаёт структурный JSON, дальше — ответы Writer'а."""
    texts = list(generated)
    calls: list = []

    async def _generate(messages, **_kw):
        calls.append(messages)
        index = min(len(calls) - 1, len(texts) - 1)
        return texts[index]

    llm = type("L", (), {})()
    llm.generate = _generate
    llm.calls = calls
    return llm


@pytest.mark.asyncio
async def test_r0812_composite_claim_structure_preserved_no_rewrite():
    """sources→claims→verdict сохранены; Writer-текст доставлен как написан."""
    from services.factcheck_service import FactCheckService

    aggregator = type("A", (), {})()
    results = ("см. https://example.org/release и https://example.org/commits")
    aggregator.search = AsyncMock(return_value=results)
    writer_text = ("Релиз 3.0 подтверждается тегом v3.0, а число коммитов "
                   "проверить нельзя.")
    llm = _fc_llm([json.dumps(_COMPOSITE, ensure_ascii=False), writer_text])
    service = FactCheckService(aggregator, llm)
    out = await service._check_claim_two_call(
        _COMPOSITE["claim"], "USER", "", results, CHAT_ID, 1000)

    assert out == writer_text            # никакого литературного переписывания
    assert len(llm.calls) == 2           # Stage-1 (структура) + один Writer
    # Payload Writer'а несёт ТУ ЖЕ структуру: утверждения, статусы, вердикт.
    payload = llm.calls[1][1]["content"]
    assert payload.startswith("АНАЛИЗ (JSON):")
    data = json.loads(payload.split("АНАЛИЗ (JSON):\n", 1)[1])
    assert data["claim"] == _COMPOSITE["claim"]
    assert data["verdict"] == _COMPOSITE["verdict"]
    assert [f["assertion"] for f in data["findings"]] == \
        [f["assertion"] for f in _COMPOSITE["findings"]]
    assert [f["status"] for f in data["findings"]] == ["true", "unverifiable"]


@pytest.mark.asyncio
async def test_r0812_insufficient_evidence_is_not_upgraded():
    """`insufficient_evidence` не превращается в mixed/supported.

    Проверяется реальный слой сведения покрытия частей: серверные части не
    делают общий вывод положительным, если модель сказала «данных
    недостаточно» (Reviewer F1 контракта фактчека).
    """
    from services import factcheck_service as fs
    from services import temporal_factcheck as tf
    from services.factcheck_planner import (
        CLAIM_OUTCOME_CONFIRMED,
        ClaimCoverage,
    )
    from services.factcheck_service import merge_claim_coverage

    claim = type("C", (), {"claim_id": "c1", "text": "релиз вышел",
                           "claim_type": "event"})()
    evidence = type("E", (), {"evidence_id": "ev-1", "role": "supports"})()
    # Серверное покрытие утверждает «подтверждено» (confirmed → supported),
    # но модель по существу сказала «данных недостаточно».
    coverage = [ClaimCoverage(
        claim=claim, outcome=CLAIM_OUTCOME_CONFIRMED, search_status="ok",
        status_detail="", gap_note="", citation_ids=("ev-1",),
        evidence=(evidence,))]
    verdict = tf.TemporalVerdict(
        factual_verdict="insufficient_evidence", temporal_status="unknown",
        evaluated_period={"from": None, "to": None, "precision": "unknown"},
        assessment_mode="contextual", as_of=1760900000,
        evidence_refs=("ev-1",), uncertainty={}, parts=(), reason=None)

    merged = merge_claim_coverage(verdict, coverage, (evidence,))
    assert merged.factual_verdict == "insufficient_evidence"
    assert all(str(p.get("factual_verdict")) == "insufficient_evidence"
               for p in merged.parts), merged.parts
    # И структурный отчёт (без LLM) не сглаживает вердикт.
    report = fs.deterministic_temporal_report(
        type("Env", (), {"original_published_at": None,
                         "date_source": "unknown",
                         "requested_mode": "contextual",
                         "claim_text": "релиз вышел"})(), merged)
    assert "Вердикт: данных недостаточно" in report
    assert "частично" not in report.casefold()


# ════════════════════════════════════════════════════════════════════════════
# R-08.13 — невалидная схема: machine stage или честное завершение
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r0813_invalid_plan_json_repaired_on_machine_stage(monkeypatch):
    """Невалидный JSON плана → ровно ОДИН repair на машинной стадии.

    Repair живёт в L1-планере (`direct_l1.build_repair_messages`), а не в
    литературном писателе: после починки схема валидна, Writer вызывается
    один раз.
    """
    import services.direct_l1 as _l1

    repairs: list = []
    real_build = _l1.build_repair_messages

    def _build(messages, previous_raw):
        out = real_build(messages, previous_raw)
        repairs.append({"previous": previous_raw, "messages": out})
        return out

    monkeypatch.setattr(_l1, "build_repair_messages", _build)
    answer = "Отвечаю по плану."
    llm = _FakeLLM(l1=["это не json", _plan_json()], l2=answer)
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "что там по плану?", llm=llm, tool_router=_FakeRouter())
    await svc.handle(bot, msg, user)

    assert len(repairs) == 1, repairs              # bounded: ровно один repair
    assert repairs[0]["previous"] == "это не json"
    assert _l1.REPAIR_ANNOTATION in repairs[0]["messages"][-1]["content"]
    assert llm.steps() == ["l1_planner", "l1_planner", "l2_writer"], \
        llm.steps()
    _assert_as_authored(_delivered(svc), answer)
    _no_legacy_stage(llm)


@pytest.mark.asyncio
async def test_r0813_invalid_twice_terminates_honestly_no_second_writer(
        monkeypatch):
    """Repair не удался → дет. fallback плана, честная причина, один L2."""
    import services.direct_l1 as _l1

    diagnostics: list = []
    real_record = _l1.record_l1_diagnostics

    def _record(chat_id, **fields):
        diagnostics.append(dict(fields))
        return real_record(chat_id, **fields)

    monkeypatch.setattr(_l1, "record_l1_diagnostics", _record)
    answer = "Ладно, отвечу без плана."
    llm = _FakeLLM(l1=["не json", "тоже не json"], l2=answer)
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "что там по плану?", llm=llm, tool_router=_FakeRouter())
    await svc.handle(bot, msg, user)

    assert llm.steps() == ["l1_planner", "l1_planner", "l2_writer"], \
        llm.steps()
    _assert_as_authored(_delivered(svc), answer)
    assert any(d.get("planner_fallback_reason") == "planner_outage"
               for d in diagnostics), diagnostics
    _no_legacy_stage(llm)


@pytest.mark.asyncio
async def test_r0813_invalid_orchestrator_schema_bounded_stop(monkeypatch):
    """Невалидная схема tool-call решения → bounded stop, не второй писатель.

    Реальный `run_adaptive_chain`: невалидный ответ оркестратора не
    исполняет инструмент и не пишет прозу — цепочка честно останавливается
    (`orchestrator_invalid_output`), а текст пишет единственный L2.
    """
    orchestrator_prose = "ВОТ МОЙ ОТВЕТ БЕЗ ВСЯКОГО JSON"
    answer = "Проверить не удалось, но вот что знаю."
    router = _FakeRouter()
    llm = _FakeLLM(
        # Adaptive-цепочка по памяти чата (сеть не нужна): единственный
        # LLM-шаг оркестратора получает невалидную схему решения.
        l1=_plan_json(execution_mode="adaptive_tool_chain", tool_policy="auto",
                      capabilities_needed=["chat_memory"],
                      knowledge_origin="internal_memory",
                      search_intent="not_applicable"),
        l2=answer, single=orchestrator_prose)
    captured: dict = {}
    real_phase = DirectChatService._l1_tool_phase

    async def _phase(self, payload, tool_ctx, **kwargs):
        raw = await real_phase(self, payload, tool_ctx, **kwargs)
        captured["raw"] = raw
        return raw

    monkeypatch.setattr(DirectChatService, "_l1_tool_phase", _phase)
    svc, _react, bot, msg, user = _drive(
        monkeypatch, "что мы говорили про релиз?", llm=llm,
        tool_router=router)
    await svc.handle(bot, msg, user)

    assert router.dispatched == [], router.dispatched      # ничего не вызвано
    raw = captured["raw"]
    # Честное машинное завершение: bounded stop с названной причиной.
    assert raw.reason == "orchestrator_invalid_output", raw.reason
    assert raw.chain_meta["reason"] == "orchestrator_invalid_output"
    assert raw.degraded is True
    assert llm.steps() == ["l1_planner", "orchestrator", "l2_writer"], \
        llm.steps()
    delivered = _delivered(svc)
    assert orchestrator_prose not in delivered             # оркестратор — не автор
    _assert_as_authored(delivered, answer)
    assert llm.steps().count("l2_writer") == 1
    _no_legacy_stage(llm)


# ════════════════════════════════════════════════════════════════════════════
# R-08.15 — fallback модели/провайдера: та же стадия, тот же смысл
# ════════════════════════════════════════════════════════════════════════════


def _fallback_client() -> LLMClient:
    client = LLMClient(
        base_url="https://primary.example/v1", api_key="k-primary",
        chat_model="mystery-large-1m", embed_model="text-embed",
        fallback_base_url="https://fallback.example/v1",
        fallback_api_key="k-fb", fallback_model="mystery-small-16k")
    assert client._fallback_active
    return client


class _OkResponse:
    def __init__(self, content):
        self._payload = {
            "choices": [{"message": {"content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10}}

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_r0815_provider_fallback_same_stage_protected_blocks(monkeypatch):
    """Отказ primary → fallback в ТОЙ ЖЕ стадии Writer'а.

    Реальный `LLMClient` (fallback-нога активна) + реальный
    `_l2_write_answer` с адаптером: перепакованный payload обязан сохранить
    system/роль, текущий вопрос и обязательный tool evidence; литературный
    вызов остаётся один, legacy-маршрута (`СПРАВКА (JSON)` Stage-1) нет.
    """
    import services.direct_chat_service as dcs

    client = _fallback_client()
    seen: dict = {}

    async def fail_primary(path, payload, **kwargs):
        raise LLMError("primary down")

    async def fb_retries(payload, sent=None):
        seen["fallback"] = payload
        return _OkResponse("Завтра дождь, зонт бери.")

    client._post_with_key = fail_primary
    client._fallback_with_retries = fb_retries

    stats_seen: list = []
    real_verbalize = dcs.verbalize_validated

    async def _verbalize(*args, **kwargs):
        text, stats = await real_verbalize(*args, **kwargs)
        stats_seen.append(stats)
        return text, stats

    monkeypatch.setattr(dcs, "verbalize_validated", _verbalize)

    svc = _make_service(llm=client)
    evidence = ("[ИСТОЧНИК 1 | execute_web_search | ok]\n"
                "завтра дождь, 12 градусов")
    result = await svc._l2_write_answer(
        CHAT_ID, "какая завтра погода?",
        temperature=0.5,
        plan_block="<Plan>ответить кратко</Plan>",
        user_blocks=["<Current_Question>какая завтра погода?</Current_Question>"],
        evidence=evidence,
        fallback_budget_tokens=8000)

    assert result is not None
    text, mode = result
    assert text == "Завтра дождь, зонт бери."       # fallback-нога = автор
    fb_payload = seen["fallback"]
    messages = fb_payload["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"].strip()           # роль/безопасность целы
    user_content = messages[-1]["content"]
    assert "какая завтра погода?" in user_content   # текущий вопрос защищён
    assert "<Tool_Evidence>" in user_content        # обязательный evidence цел
    assert "завтра дождь, 12 градусов" in user_content
    assert "СПРАВКА (JSON)" not in user_content     # не legacy Stage-1
    # Один литературный вызов: stats штатного verbalize_validated.
    assert len(stats_seen) == 1
    assert stats_seen[0]["attempts"] == 1
    assert stats_seen[0]["semantic_rewrite_count"] == 0


# ════════════════════════════════════════════════════════════════════════════
# R-08.17 — длинная Telegram-реплика: chunking без обрыва/перестановки
# ════════════════════════════════════════════════════════════════════════════

_LONG_LINK = "https://example.org/long-read?page=2&anchor=details"


def _long_answer() -> str:
    """Длинная реплика с авторством, цитатой и ссылкой в середине."""
    lead = ("Вася, 12.10.2026: «дочитал до конца, там всё про индексы» "
            "Это важная часть, повторю аккуратно: ")
    body = " ".join(
        f"пункт {i} про индексы, кеши и порядок обхода данных" for i in range(1, 140))
    tail = (f" Подробности тут: {_LONG_LINK} — вот и всё, что я хотел "
            f"сказать по этому поводу.")
    return lead + body + tail


@pytest.mark.asyncio
async def test_r0817_long_reply_chunked_without_loss(monkeypatch):
    """Chunking режет по границам слов: ни обрыва, ни перестановки.

    Проверяется реальный `_send_direct_answer` → `send_chunked_reply`:
    склейка фактически отправленных чанков воспроизводит текст Writer'а
    символ-в-символ (значит нет ни потерь, ни перестановки, ни разрыва
    слова), ссылка и авторство целы, второго литературного вызова нет.
    """
    answer = _long_answer()
    assert len(answer) > 5000           # гарантированно больше одного чанка
    sent: list = []

    bot = _bot()

    async def _send_message(chat_id, text, **kwargs):
        sent.append({"text": text, **kwargs})
        return SimpleNamespace(message_id=900 + len(sent))

    bot.send_message = AsyncMock(side_effect=_send_message)

    llm = _FakeLLM(l1=_plan_json(), l2=answer)
    svc, _react, _b, msg, user = _drive(
        monkeypatch, "расскажи подробно, что там было", llm=llm,
        tool_router=_FakeRouter())
    real_send = DirectChatService._send_direct_answer

    async def _send(inner_bot, chat_id, text, reply_to=None, **kwargs):
        return await real_send(inner_bot, chat_id, text, reply_to, **kwargs)

    svc._send_direct_answer = AsyncMock(side_effect=_send)
    await svc.handle(bot, msg, user)

    assert svc._send_direct_answer.await_count == 1
    assert len(sent) > 1, sent                      # реально порезано
    chunks = [c["text"] for c in sent]
    # Ни одного потерянного/переставленного символа: склейка воспроизводит
    # текст Writer'а с точностью до закрытого набора типографических замен
    # (единственный детерминированный style-pass продакшена).
    joined = " ".join(chunks)
    assert joined in (answer, answer.translate(_TYPOGRAPHIC_MAP)), joined
    assert _WORD_RE.findall(joined.casefold()) == \
        _WORD_RE.findall(answer.casefold())
    assert all(len(c) <= 4096 for c in chunks), [len(c) for c in chunks]
    # Ссылка и авторство не разрезаны.
    assert any(_LONG_LINK in c for c in chunks), chunks
    assert any("Вася, 12.10.2026" in c for c in chunks), chunks
    # reply-привязка только на первом чанке (одна логическая отправка).
    assert sent[0]["reply_to_message_id"] == msg.message_id
    assert all("reply_to_message_id" not in c or c.get("reply_to_message_id")
               is None for c in sent[1:]), sent
    assert llm.steps().count("l2_writer") == 1
