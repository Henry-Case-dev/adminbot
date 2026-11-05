# -*- coding: utf-8 -*-
"""UNIFIED-REPLY UR-G - acceptance probes (evidence production slice).

Кроет ТОЛЬКО пробелы, не покрытые существующими сьютами UR-A..UR-F
(см. plans/features/unified-reply/evidence/ur-g-acceptance.md):

* UR-30.3 - Europe/Warsaw зима/лето, соседние чаты с разными поясами на
  одном absolute timestamp, смена пояса между ходами при неизменяемом
  plan-снапшоте, invalid IANA -> явная utc_fallback-деградация
  (ветка отсутствия tzdata - тот же кодовый путь);
* UR-30.4 (initiative-ноги) - L1 и L2 payload инициативы несут ровно один
  <Chat_Time_Context> с phase="plan"/"answer" и поясом чата
  (прямой путь/фактчек/саммари покрыты в tests/test_ur_c_clock.py);
* UR-ACC-B3 (структурная половина) - юмористическая формулировка запроса
  про актуальное публичное событие ищется: жанр/форма не входит в ось
  решения, only knowledge_origin/search_intent (BGS-01).

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-G
"""
import datetime
from zoneinfo import ZoneInfo

import pytest

import services.chat_params as chat_params
from config.settings import settings
from services import chat_clock as cc
from services import direct_l1 as _l1
from services.direct_l1 import L1Plan

pytestmark = [pytest.mark.system2]

CHAT_A = 33001
CHAT_B = 33002
CHAT_C = 33003

#: 12:00 UTC - лето северного полушария.
SUMMER = datetime.datetime(2026, 7, 15, 12, 0,
                           tzinfo=datetime.timezone.utc)
#: 12:00 UTC - зима.
WINTER = datetime.datetime(2026, 1, 15, 12, 0,
                           tzinfo=datetime.timezone.utc)
#: 20:30 UTC зимнего дня: Kathmandu уже на следующий локальный день.
WINTER_EVENING = datetime.datetime(2026, 1, 15, 20, 30,
                                   tzinfo=datetime.timezone.utc)

_PLAN_JSON = ('{"action":"reply","confidence":0.9,"extent":"auto",'
              '"tone":"inherit"}')


class FakeCache:
    """Мини-версия chat_params-кэша с per-chat overrides (по образцу
    tests/test_ur_c_clock.py::FakeCache). Держит ССЫЛКУ на roots, чтобы
    поздние _set() были видны без пересоздания кэша."""

    def __init__(self, roots_by_chat):
        self._roots = (roots_by_chat if roots_by_chat is not None
                       else {})

    async def get_chat_params(self, chat_id):
        return dict(self._roots.get(int(chat_id), {}))

    async def get_chat_params_full(self, chat_id):
        return dict(self._roots.get(int(chat_id), {})), \
            "2026-11-06T00:00:00Z"


@pytest.fixture()
def tz_overrides(monkeypatch, frozen_settings):
    """Per-chat tz overrides + полностью контролируемый global-слой
    (hot_config без глобальных значений, без GOODMORNING_TZ env, фаб-дефолт
    пустой) - по образцу tests/test_ur_c_clock.py::tz_env."""
    import services.hot_config as hot_config

    roots: dict[int, dict] = {}
    monkeypatch.setattr(chat_params, "_chat_params_cache",
                        FakeCache(roots))
    controlled: dict[str, str] = {}
    original_get = hot_config.get

    def _fake_get(key, default=None):
        if key in controlled:
            return controlled[key]
        return original_get(key, default)

    monkeypatch.setattr(hot_config, "get", _fake_get)
    monkeypatch.delenv("GOODMORNING_TZ", raising=False)
    frozen_settings("SUMMARY_TIMEZONE", "")
    frozen_settings("CHAT_TIMEZONE", "")

    def _set(chat_id, zone):
        roots[int(chat_id)] = {"overrides":
                               {"limits.chat_timezone": str(zone)}}
        return chat_id

    yield _set
    monkeypatch.setattr(chat_params, "_chat_params_cache", None)


_MISS = object()


@pytest.fixture()
def frozen_settings():
    """frozen settings через object.__setattr__ с восстановлением."""
    patched: list[tuple[str, object]] = []

    def _patch(name, value):
        patched.append((name, getattr(settings, name, _MISS)))
        object.__setattr__(settings, name, value)

    yield _patch
    for name, orig in reversed(patched):
        if orig is _MISS:
            continue
        object.__setattr__(settings, name, orig)


def _plan(**over):
    return _l1.normalize_l1_plan(dict({"action": "reply",
                                       "confidence": 0.9, **over}))


# --- UR-30.3: пробелы timezone-матрицы -------------------------------------


class TestUrGTimezoneMatrix:
    @pytest.mark.asyncio
    async def test_warsaw_winter_summer_offsets(self, tz_overrides):
        """Europe/Warsaw: зима +01:00, лето +02:00, UTC-хранение не меняется."""
        chat = tz_overrides(CHAT_A, "Europe/Warsaw")
        winter = await cc.snapshot(chat, at_utc=WINTER)
        summer = await cc.snapshot(chat, at_utc=SUMMER)
        assert (winter.timezone, winter.timezone_source) == \
            ("Europe/Warsaw", "chat")
        assert winter.utc_offset == "+01:00"
        assert winter.local_datetime.hour == 13
        assert summer.utc_offset == "+02:00"
        assert summer.local_datetime.hour == 14
        assert winter.as_of_utc == WINTER and summer.as_of_utc == SUMMER

    @pytest.mark.asyncio
    async def test_adjacent_chats_same_instant_different_local(
            self, tz_overrides):
        """Соседние чаты (Warsaw / Kathmandu / UTC) на одном instant получают
        разные корректные локальные даты/смещения - без общего расписания."""
        chat_w = tz_overrides(CHAT_A, "Europe/Warsaw")
        chat_k = tz_overrides(CHAT_B, "Asia/Kathmandu")
        chat_u = tz_overrides(CHAT_C, "UTC")
        snaps = [await cc.snapshot(c, at_utc=WINTER_EVENING)
                 for c in (chat_w, chat_k, chat_u)]
        offsets = {s.utc_offset for s in snaps}
        assert offsets == {"+01:00", "+05:45", "+00:00"}
        # 20:30 UTC зимнего дня: Kathmandu (+05:45) уже на следующий день,
        # Warsaw - нет: соседние чаты видят разную локальную дату.
        assert snaps[1].local_datetime.day != snaps[0].local_datetime.day
        assert snaps[2].timezone == "UTC"

    @pytest.mark.asyncio
    async def test_zone_change_between_turns_plan_snapshot_immutable(
            self, tz_overrides):
        """Смена пояса: новый ход - новая зона; in-flight ход остаётся на
        своём plan-снапшоте (reuse при той же минуте), история не меняется."""
        chat = tz_overrides(CHAT_A, "Europe/Warsaw")
        plan_snap = await cc.snapshot(chat, at_utc=SUMMER)
        assert plan_snap.timezone == "Europe/Warsaw"
        # Смена зоны между ходами.
        tz_overrides(CHAT_A, "Asia/Kathmandu")
        fresh = await cc.snapshot(chat, at_utc=SUMMER)
        assert fresh.timezone == "Asia/Kathmandu"
        assert fresh.utc_offset == "+05:45"
        # In-flight: та же минута - answer reuse plan-снапшота без обновления.
        answer, refreshed = await cc.ensure_answer_snapshot(
            plan_snap, chat, clock=lambda: SUMMER)
        assert refreshed is False and answer is plan_snap
        # Пересечение минуты - берётся свежая зона чата.
        later = SUMMER + datetime.timedelta(seconds=90)
        answer2, refreshed2 = await cc.ensure_answer_snapshot(
            plan_snap, chat, clock=lambda: later)
        assert refreshed2 is True
        assert answer2.timezone == "Asia/Kathmandu"

    @pytest.mark.asyncio
    async def test_invalid_iana_is_explicit_utc_fallback(self, tz_overrides):
        """Invalid IANA (и ветка отсутствия tzdata - тот же except-путь):
        явная utc_fallback-деградация с пометкой в блоке, не подмена."""
        chat = tz_overrides(CHAT_A, "Mars/Olympus_Mons")
        snap = await cc.snapshot(chat, at_utc=SUMMER)
        assert snap.timezone_source == "utc_fallback"
        assert snap.utc_offset == "+00:00"
        block = cc.render_chat_time_context(snap, phase=cc.PHASE_ANSWER)
        assert "utc_fallback" in block


# --- UR-30.4: initiative-ноги clock-wiring ---------------------------------


class _FakeLLM:
    """Мини-версия _FakeLLM (step-развилка l1_planner/l2_writer)."""

    def __init__(self, *, l1=None, l2="Готов ответ"):
        self.l1_reply = l1
        self.l2_text = l2
        self.calls = []

    async def generate(self, messages, temperature=None, chat_id=None,
                       module=None, step=None, correlation_id=None, **kwargs):
        self.calls.append({"step": step, "messages": messages})
        if step == "l1_planner":
            return self.l1_reply or _PLAN_JSON
        return self.l2_text

    def calls_of(self, step):
        return [c for c in self.calls if c["step"] == step]


class TestUrGInitiativeClockPayloads:
    @pytest.mark.asyncio
    async def test_initiative_l1_payload_has_plan_block(
            self, tz_overrides, monkeypatch):
        """Initiative L1 (общий planner) несёт ровно один
        <Chat_Time_Context phase="plan"> с поясом чата (UR-26.3)."""
        from tests.test_direct_chat import FakeMemory, _make_service
        chat = tz_overrides(CHAT_A, "Europe/Warsaw")
        llm = _FakeLLM(l1=_PLAN_JSON)
        service = _make_service(memory=FakeMemory(window=[]), llm=llm)
        monkeypatch.setattr(service, "_history_partial",
                            _async_false())
        row = {"goal": "уточнить деталь", "kind": "follow_up",
               "origin": "observer", "addressee_user_id": 10}
        await service.plan_initiative_decision(
            chat, row, correlation_id="corr-urg-init-l1")
        l1_calls = llm.calls_of("l1_planner")
        assert l1_calls, "L1-вызов не зафиксирован"
        user_content = str(l1_calls[-1]["messages"][-1]["content"])
        assert user_content.count("<Chat_Time_Context") == 1
        assert 'phase="plan"' in user_content
        assert "Europe/Warsaw" in user_content

    @pytest.mark.asyncio
    async def test_initiative_l2_payload_has_answer_block(
            self, tz_overrides):
        """Initiative L2 (общий Writer) несёт ровно один блок с
        phase="answer" (UR-26.3; wiring generate_initiative_reply)."""
        from tests.test_direct_chat import FakeMemory, _make_service
        chat = tz_overrides(CHAT_A, "Europe/Warsaw")
        rows = [{"user_id": 10, "author_name": "Аня",
                 "text": "ревью субмодуля", "timestamp": 1000,
                 "media_type": "text", "reply_to_id": None,
                 "tg_message_id": 11, "id": 1}]
        llm = _FakeLLM(l2="Ответ инициативы")
        svc = _make_service(llm=llm, memory=FakeMemory(window=rows))
        text = await svc.generate_initiative_reply(
            chat, {"goal": "сFollow up", "kind": "follow_up"},
            l1_plan=L1Plan(action="reply", extent="normal", source="llm"),
            correlation_id="corr-urg-init-l2")
        assert text == "Ответ инициативы"
        l2_calls = llm.calls_of("l2_writer")
        assert l2_calls, "Writer-вызов не зафиксирован"
        user_contents = [str(m.get("content"))
                         for m in l2_calls[-1]["messages"]
                         if m.get("role") == "user"]
        assert any(c.count("<Chat_Time_Context") == 1 for c in user_contents)
        assert any('phase="answer"' in c for c in user_contents)
        assert any("Europe/Warsaw" in c for c in user_contents)


def _async_false():
    from unittest.mock import AsyncMock
    return AsyncMock(return_value=False)


# --- UR-ACC-B3: жанр не входит в ось решения поиска ------------------------


class TestUrGB3JokeGenre:
    def test_public_event_joke_phrasing_is_searchable(self):
        """Шутка/юмористическая формулировка про актуальное публичное
        событие при open_world ищется: жанр/форма не гейтит поиск
        (ось решения - knowledge_origin/search_intent, BGS-01)."""
        from services.direct_execution import build_search_query
        plan = _plan(knowledge_origin="open_world")
        assert plan.search_intent == _l1.SEARCH_REQUIRED
        task = build_search_query(
            plan,
            query="придумай шутку про свежий запуск Starship у SpaceX")
        assert task.usable is True
        assert "starship" in task.query.lower()
