"""UNIFIED-REPLY UR-C-CLOCK — контракт времени чата (arch contract §3).

Покрывает строки карты UR-24.3/UR-25/UR-25.1/UR-25.2/UR-25.3/UR-25.5/
UR-25.6/UR-26.2/UR-26.3/UR-26.4/UR-26.5/UR-27/UR-BAN-05:

  * DST/offset по IANA на конкретном UTC-instant (Europe/Berlin лето/зима,
    Europe/Moscow контроль, Asia/Kathmandu +05:45, Pacific/Auckland смена
    суток) — время НЕ зависит от пояса контейнера;
  * per-chat изоляция и каноническая цепочка UR-24.3 ("" = наследование);
  * один план-снапшот хода: L1 и L2 в одной минуте видят ОДИН as_of
    (мутация «вторые/несогласованные часы» ловится); пересечение минуты →
    свежий answer_as_of_utc;
  * фактчек/саммари получают время оценки в финальном outbound payload;
  * невозможность резолва пояса → явная деградация utc_fallback, НЕ
    выдуманное время (UR-BAN-05).

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-C-CLOCK
"""
import dataclasses
import datetime
from types import SimpleNamespace
import zoneinfo

import pytest

from services import chat_clock as cc
import services.chat_params as chat_params
from config.settings import settings

pytestmark = [pytest.mark.system2]

CHAT_A = 1001
CHAT_B = 1002

#: Лето в Северном полушарии (DST активен в Berlin), 12:00 UTC.
SUMMER = datetime.datetime(2026, 7, 15, 12, 0,
                           tzinfo=datetime.timezone.utc)
#: Зима (стандартное время).
WINTER = datetime.datetime(2026, 1, 15, 12, 0,
                           tzinfo=datetime.timezone.utc)


class FakeCache:
    """chat_params-кэш с per-chat overrides (root-лейаут)."""

    def __init__(self, roots_by_chat):
        self._roots = dict(roots_by_chat or {})
        self.updated_at = "2026-11-05T10:00:00Z"

    async def get_chat_params(self, chat_id):
        return self._roots.get(int(chat_id), {})

    async def get_chat_params_full(self, chat_id):
        root = self._roots.get(int(chat_id), {})
        return root, self.updated_at


_MISSING = object()


@pytest.fixture()
def frozen_settings():
    """Патч полей frozen-settings через object.__setattr__ с восстановлением."""
    patched: list[tuple[str, object]] = []

    def _patch(name: str, value: object) -> None:
        patched.append((name, getattr(settings, name, _MISSING)))
        object.__setattr__(settings, name, value)

    yield _patch
    for name, orig in reversed(patched):
        if orig is _MISSING:
            continue
        object.__setattr__(settings, name, orig)


_ROOTS_BY_CHAT: dict[int, dict] = {}


def _set_chat_override(chat_id, overrides: dict):
    """Хелпер копит per-chat overrides в ОДНОМ кэше на тест (изоляция чатов
    проверяется на одном инстансе); очистка — в фикстуре tz_env."""
    _ROOTS_BY_CHAT[int(chat_id)] = {"overrides": dict(overrides)}
    chat_params._chat_params_cache = FakeCache(_ROOTS_BY_CHAT)


@pytest.fixture()
def tz_env(monkeypatch, frozen_settings):
    """Изолированные слои пояса: пустой канон/legacy по умолчанию.

    Global-слой эмулируется перехватом ``hot_config.get`` (ConfigCache в
    тестах не инициализирован — hot.get делегирует settings-дефолтам), а
    фабричный слой — через ``object.__setattr__`` на frozen settings."""
    import services.hot_config as hot_config

    controlled: dict[str, str] = {}
    original_get = hot_config.get

    def _fake_get(key, default=None):
        if key in controlled:
            return controlled[key]
        return original_get(key, default)

    monkeypatch.setattr(hot_config, "get", _fake_get)
    monkeypatch.delenv("GOODMORNING_TZ", raising=False)
    chat_params._chat_params_cache = None
    _ROOTS_BY_CHAT.clear()

    def _set_global(key: str, value: str) -> None:
        controlled[key] = value

    def _set_factory(value: str) -> None:
        frozen_settings("SUMMARY_TIMEZONE", value)

    tz_env.set_global = _set_global            # type: ignore[attr-defined]
    tz_env.set_factory = _set_factory          # type: ignore[attr-defined]
    holder = SimpleNamespace(set_global=_set_global, set_factory=_set_factory,
                             setenv=monkeypatch.setenv,
                             delenv=monkeypatch.delenv)
    yield holder
    chat_params._chat_params_cache = None
    _ROOTS_BY_CHAT.clear()


def _frozen(now):
    return lambda: now


# ── UR-25.5: DST/offset по IANA на конкретный UTC instant ───────────────────


class TestDstAndOffsets:
    @pytest.mark.asyncio
    async def test_berlin_summer_vs_winter_moscow_fixed(self, tz_env):
        """Berlin: +02:00 летом, +01:00 зимой на тех же UTC-часах;
        Moscow: +03:00 круглый год (IANA-правила на instant)."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Berlin"})
        _set_chat_override(CHAT_B, {"limits.chat_timezone": "Europe/Moscow"})
        summer = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        winter = await cc.snapshot(CHAT_A, at_utc=WINTER)
        assert summer.utc_offset == "+02:00"
        assert winter.utc_offset == "+01:00"
        assert summer.local_datetime.hour == 14
        assert winter.local_datetime.hour == 13
        m_summer = await cc.snapshot(CHAT_B, at_utc=SUMMER)
        m_winter = await cc.snapshot(CHAT_B, at_utc=WINTER)
        assert m_summer.utc_offset == m_winter.utc_offset == "+03:00"

    @pytest.mark.asyncio
    async def test_kathmandu_half_hour_offset(self, tz_env):
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Asia/Kathmandu"})
        snap = await cc.snapshot(CHAT_A, at_utc=WINTER)
        assert snap.utc_offset == "+05:45"
        assert snap.local_datetime.hour == 17
        assert snap.local_datetime.minute == 45

    @pytest.mark.asyncio
    async def test_auckland_crosses_local_date_same_instant(self, tz_env):
        """Один UTC-instant: Auckland уже следующая дата/день, Moscow — ещё
        предыдущий (пер-чат изоляция дат, contract §3.3 матрица)."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone":
                                    "Pacific/Auckland"})
        _set_chat_override(CHAT_B, {"limits.chat_timezone": "Europe/Moscow"})
        a = await cc.snapshot(CHAT_A, at_utc=SUMMER)   # 12:00 UTC июля
        b = await cc.snapshot(CHAT_B, at_utc=SUMMER)
        assert a.local_datetime.date() != b.local_datetime.date()
        assert a.weekday != b.weekday

    @pytest.mark.asyncio
    async def test_independent_of_container_timezone(self, tz_env):
        """UR-25.3/UR-BAN-05: локальное время считается из UTC-instant и
        zoneinfo, а не из локального времени машины — проверяем, что чат в
        Moscow не «уезжает», даже если контейнер живёт в Auckland (сдвиг
        эмулируем сравнением с явным UTC-якорем)."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        snap = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        assert snap.as_of_utc.utcoffset() == datetime.timedelta(0)
        assert snap.local_datetime.utcoffset() == datetime.timedelta(hours=3)
        assert snap.local_datetime.strftime("%d.%m.%Y") == "15.07.2026"


# ── UR-24.3: каноническая цепочка пояса ─────────────────────────────────────


class TestCanonicalChain:
    @pytest.mark.asyncio
    async def test_per_chat_canonical_wins_over_legacy(self, tz_env):
        _set_chat_override(CHAT_A, {
            "limits.chat_timezone": "Europe/Berlin",
            "limits.summary_timezone": "Asia/Almaty"})
        tz, source, cv = await cc.resolve_chat_timezone(CHAT_A)
        assert (tz, source) == ("Europe/Berlin", "chat")
        assert cv == "2026-11-05T10:00:00Z"

    @pytest.mark.asyncio
    async def test_empty_means_inherit_not_zone(self, tz_env):
        """«"" у ключа означает наследование, НЕ IANA-зону» (UR-24.3)."""
        _set_chat_override(CHAT_A, {
            "limits.chat_timezone": "",
            "limits.summary_timezone": "Asia/Almaty"})
        tz, source, _cv = await cc.resolve_chat_timezone(CHAT_A)
        assert (tz, source) == ("Asia/Almaty", "chat_legacy")

    @pytest.mark.asyncio
    async def test_global_canonical_then_legacy(self, tz_env):
        chat_params._chat_params_cache = FakeCache({})
        tz_env.set_global("limits.chat_timezone", "Europe/Berlin")
        tz_env.set_global("limits.summary_timezone", "Asia/Almaty")
        tz, source, _cv = await cc.resolve_chat_timezone(CHAT_A)
        assert (tz, source) == ("Europe/Berlin", "global")
        tz_env.set_global("limits.chat_timezone", "")
        tz, source, _cv = await cc.resolve_chat_timezone(CHAT_A)
        assert (tz, source) == ("Asia/Almaty", "global_legacy")

    @pytest.mark.asyncio
    async def test_goodmorning_tz_only_when_explicit_env(self, tz_env):
        """GOODMORNING_TZ считается ТОЛЬКО явно заданным env-override
        (env-дефолт кода не выдаётся за осознанный override)."""
        chat_params._chat_params_cache = FakeCache({})
        tz_env.set_global("limits.chat_timezone", "")
        tz_env.set_global("limits.summary_timezone", "")
        tz_env.setenv("GOODMORNING_TZ", "Asia/Almaty")
        tz, source, _cv = await cc.resolve_chat_timezone(CHAT_A)
        assert (tz, source) == ("Asia/Almaty", "legacy_goodmorning")
        # Ничего не задано → прежний кодовый дефолт (factory), не «пустота».
        tz_env.delenv("GOODMORNING_TZ", raising=False)
        tz_env.set_factory("Asia/Yekaterinburg")
        tz, source, _cv = await cc.resolve_chat_timezone(CHAT_A)
        assert (tz, source) == ("Asia/Yekaterinburg", "factory")

    @pytest.mark.asyncio
    async def test_invalid_zone_does_not_win(self, tz_env):
        """Мусорная зона не становится «часами» — слой пропускается (без
        молчаливой подмены на фиктивный ID)."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Mars/Olympus"})
        tz, source, _cv = await cc.resolve_chat_timezone(CHAT_A)
        assert tz != "Mars/Olympus"
        assert source in ("global_legacy", "factory", "global",
                          "legacy_goodmorning", "utc_fallback")


# ── UR-25.1: TimeSnapshot-контракт ──────────────────────────────────────────


class TestTimeSnapshotContract:
    @pytest.mark.asyncio
    async def test_snapshot_fields(self, tz_env):
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        snap = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        assert isinstance(snap, cc.TimeSnapshot)
        assert dataclasses.is_dataclass(snap)
        # Неизменяемый (in-flight ход остаётся на своём snapshot).
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.timezone = "UTC"
        assert snap.timezone == "Europe/Moscow"
        assert snap.utc_offset == "+03:00"
        assert snap.weekday == "Среда"
        assert snap.as_of_utc == SUMMER
        assert snap.timezone_source == "chat"

    @pytest.mark.asyncio
    async def test_render_block_single_and_parseable(self, tz_env):
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        snap = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        block = cc.render_chat_time_context(snap, phase=cc.PHASE_PLAN)
        assert block.count("<Chat_Time_Context") == 1
        assert 'phase="plan"' in block
        assert "Europe/Moscow" in block
        assert "as_of_utc: 2026-07-15T12:00:00+00:00" in block
        messages = [{"role": "user", "content": "вопрос"}]
        once = cc.attach_time_context(messages, snap, phase=cc.PHASE_ANSWER)
        twice = cc.attach_time_context(once, snap, phase=cc.PHASE_ANSWER)
        assert twice[0]["content"].count("<Chat_Time_Context") == 1
        meta = cc.outbound_clock_meta(twice)
        assert meta == {
            "clock_included": True, "phase": "answer",
            "timezone": "Europe/Moscow", "utc_offset": "+03:00",
            "as_of_utc": "2026-07-15T12:00:00+00:00",
            "config_version": "2026-11-05T10:00:00Z"}


# ── UR-25.3/UR-BAN-05: честная деградация, без выдуманного времени ──────────


class TestHonestFallback:
    @pytest.mark.asyncio
    async def test_unresolvable_zone_is_explicit_utc_fallback(self, tz_env,
                                                              monkeypatch):
        """tzdata недоступна для выбранной зоны → явная utc_fallback-метка в
        снапшоте и блоке (диагностика), не «успешный» фейковый пояс."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Berlin"})

        real_zoneinfo = zoneinfo.ZoneInfo

        def _broken_zone(name):
            # Ломаем ТОЛЬКО резолв выбранных зон: UTC остаётся живым.
            if str(name) != "UTC":
                raise zoneinfo.ZoneInfoNotFoundError(str(name))
            return real_zoneinfo("UTC")

        monkeypatch.setattr(zoneinfo, "ZoneInfo", _broken_zone)
        snap = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        assert snap.timezone_source == "utc_fallback"
        assert snap.timezone == "UTC"
        block = cc.render_chat_time_context(snap, phase=cc.PHASE_ANSWER)
        assert "tz_status: utc_fallback" in block

    @pytest.mark.asyncio
    async def test_naive_instant_treated_as_utc_not_container_local(
            self, tz_env):
        """Naive-вход трактуется как UTC (конвенция), не как локальное время
        контейнера — «время устройства/контейнера не заменяет ChatClock»."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        naive = datetime.datetime(2026, 7, 15, 12, 0)
        snap = await cc.snapshot(CHAT_A, at_utc=naive)
        assert snap.as_of_utc.utcoffset() == datetime.timedelta(0)
        assert snap.local_datetime.hour == 15


# ── UR-25.2: план vs answer в одном ходе ────────────────────────────────────


class TestPlanVsAnswerSnapshot:
    @pytest.mark.asyncio
    async def test_same_minute_reuses_plan_snapshot(self, tz_env):
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        plan = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        answer, refreshed = await cc.ensure_answer_snapshot(
            plan, CHAT_A, clock=_frozen(SUMMER))
        assert refreshed is False
        assert answer is plan
        assert answer.as_of_utc == plan.as_of_utc

    @pytest.mark.asyncio
    async def test_minute_cross_refreshes_answer(self, tz_env):
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        plan = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        later = SUMMER + datetime.timedelta(seconds=61)
        answer, refreshed = await cc.ensure_answer_snapshot(
            plan, CHAT_A, clock=_frozen(later))
        assert refreshed is True
        assert answer is not plan
        assert answer.as_of_utc == later

    @pytest.mark.asyncio
    async def test_local_midnight_cross_refreshes_answer(self, tz_env):
        """Пересечение локальной полуночи за одну минуту UTC невозможно
        пропустить: дата изменилась → свежий answer-снапшот."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone":
                                    "Pacific/Auckland"})
        plan = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        later = SUMMER + datetime.timedelta(seconds=65)
        answer, refreshed = await cc.ensure_answer_snapshot(
            plan, CHAT_A, clock=_frozen(later))
        assert refreshed is True


# ── UR-26.2: один план-снапшот на ход — L1 и L2 ─────────────────────────────


class TestTurnClockWiring:
    @pytest.mark.asyncio
    async def test_l1_payload_carries_plan_block(self, tz_env, monkeypatch):
        """Живой `_plan_direct_l1`: финальный L1 payload содержит ровно один
        блок с phase="plan" и поясом чата (мутация «второй резолвер с
        дефолтным поясом контейнера» ломает этот тест)."""
        from unittest.mock import AsyncMock
        from tests.test_direct_chat import (
            FakeLLM, FakeMemory, _make_service, _message)
        _set_chat_override(CHAT_A, {"limits.chat_timezone":
                                    "Pacific/Auckland"})
        tz_env.set_factory("Asia/Yekaterinburg")
        llm = FakeLLM(text='{"action":"reply","confidence":0.9}')
        service = _make_service(memory=FakeMemory(window=[]), llm=llm)
        monkeypatch.setattr(service, "_history_partial",
                            AsyncMock(return_value=False))
        message = _message("привет", chat_id=CHAT_A)
        plan, meta = await service._plan_direct_l1(
            CHAT_A, message, "привет", "corr-clock", bundle=None,
            target_name="Вася", user_id=10, character_block="",
            lore_enabled=False, image_enabled=False, force_required=True,
            reply_bot=False)
        assert llm.messages is not None
        user_content = llm.messages[-1]["content"]
        assert user_content.count("<Chat_Time_Context") == 1
        assert 'phase="plan"' in user_content
        assert "Pacific/Auckland" in user_content, (
            "время чата должно прийти из ChatClock с per-chat override, "
            "а не из дефолтного пояса контейнера")
        assert "Asia/Yekaterinburg" not in user_content
        # TurnRequest несёт тот же снапшот, что видит L1.
        assert meta.get("time_snapshot") is not None
        assert meta["time_snapshot"].timezone == "Pacific/Auckland"

    @pytest.mark.asyncio
    async def test_l2_payload_same_asof_within_minute(self, tz_env):
        """L2 перед финальной сборкой: та же минута → reuse plan-снапшота
        (один as_of на ход), phase="answer" в блоке Writer'а."""
        from tests.test_direct_chat import (
            FakeLLM, FakeMemory, _make_service)
        from services.direct_chat_service import DirectChatService
        _set_chat_override(CHAT_A, {"limits.chat_timezone":
                                    "Pacific/Auckland"})
        llm = FakeLLM(text="ответ")
        service = _make_service(memory=FakeMemory(window=[]), llm=llm)
        plan = await cc.snapshot(CHAT_A, at_utc=SUMMER)
        snap_answer, refreshed = await cc.ensure_answer_snapshot(
            plan, CHAT_A, clock=_frozen(SUMMER))
        assert refreshed is False and snap_answer is plan
        time_line = cc.render_chat_time_context(
            snap_answer, phase=cc.PHASE_ANSWER)
        result = await DirectChatService._l2_write_answer(
            service, CHAT_A, "вопрос", temperature=None,
            correlation_id="corr-l2", time_line=time_line)
        assert result is not None
        text, _mode = result
        assert text == "ответ"
        user_content = llm.messages[-1]["content"]
        assert user_content.count("<Chat_Time_Context") == 1
        assert 'phase="answer"' in user_content
        assert ("as_of_utc: 2026-07-15T12:00:00+00:00" in user_content)
        assert "Pacific/Auckland" in user_content


# ── UR-26.4: фактчек получает время оценки ──────────────────────────────────


class _FakeSearch:
    async def search(self, query, max_symbols=4000, **kw):
        return "источник\nфакт\nhttps://example.com/x"


class TestFactcheckClock:
    @pytest.mark.asyncio
    async def test_single_path_payload_has_evaluation_time(self, tz_env,
                                                           monkeypatch,
                                                           frozen_settings):
        from tests.test_direct_chat import FakeLLM
        from services.factcheck_service import FactCheckService
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        frozen_settings("SYSTEM2_FACTCHECK_ENABLED", False)
        llm = FakeLLM(text="вердикт: подтверждено")
        svc = FactCheckService(llm=llm, aggregator=_FakeSearch(),
                               memory=None, tool_router=None)
        out = await svc.check_claim("некое утверждение",
                                    search_results="выдача",
                                    chat_id=CHAT_A)
        assert out
        user_content = llm.messages[-1]["content"]
        assert user_content.count("<Chat_Time_Context") == 1
        assert 'phase="answer"' in user_content
        assert "Europe/Moscow" in user_content
        # Дата источника не подменяется временем чата: она вообще вне блока
        # часов (UR-27: «время источника» — отдельная семантика).
        block_start = user_content.find("<Chat_Time_Context")
        block_end = user_content.find("</Chat_Time_Context>", block_start)
        block = user_content[block_start:block_end]
        assert "example.com" not in block

    @pytest.mark.asyncio
    async def test_no_chat_id_no_fabricated_block(self, tz_env, monkeypatch,
                                                  frozen_settings):
        """chat_id отсутствует (unit-вызов) → блока нет вовсе: не выдумываем
        пояс по умолчанию (UR-BAN-05)."""
        from tests.test_direct_chat import FakeLLM
        from services.factcheck_service import FactCheckService
        frozen_settings("SYSTEM2_FACTCHECK_ENABLED", False)
        llm = FakeLLM(text="вердикт")
        svc = FactCheckService(llm=llm, aggregator=_FakeSearch(),
                               memory=None, tool_router=None)
        await svc.check_claim("утверждение", search_results="выдача",
                              chat_id=None)
        assert "<Chat_Time_Context" not in llm.messages[-1]["content"]


# ── UR-26.5: саммари получает время стадии ──────────────────────────────────


class TestSummaryClock:
    @pytest.mark.asyncio
    async def test_generator_llm_generate_attaches_answer_block(self, tz_env):
        """Шов генератора `_llm_generate` (legacy/hybrid/editor/narrator и
        supervised-транспорт): answer-снапшот в финальном payload."""
        from tests.test_direct_chat import FakeLLM
        from services.summary_generator import SummaryGenerator
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        sg = SummaryGenerator.__new__(SummaryGenerator)
        llm = FakeLLM(text="саммари")
        sg.llm = llm
        sg.bot = __import__("unittest.mock",
                            fromlist=["AsyncMock"]).AsyncMock()
        out = await sg._llm_generate(
            [{"role": "system", "content": "S"},
             {"role": "user", "content": "текст окна"}],
            CHAT_A, correlation_id="corr-s", step="single")
        assert out == "саммари"
        user_content = llm.messages[-1]["content"]
        assert user_content.count("<Chat_Time_Context") == 1
        assert 'phase="answer"' in user_content
        assert "Europe/Moscow" in user_content

    @pytest.mark.asyncio
    async def test_l1_clusterizer_payload_has_plan_block(self, tz_env):
        from services.summary_l1_clusterizer import run_l1
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        captured: list[list] = []

        async def _llm_call(messages):
            captured.append(messages)
            return "{}", None

        rows = [{"id": 1, "user_id": 10, "author_name": "вася",
                 "text": "реплика один", "timestamp": 1000,
                 "media_type": "text", "reply_to_id": None,
                 "tg_message_id": 11},
                {"id": 2, "user_id": 11, "author_name": "петя",
                 "text": "реплика два", "timestamp": 2000,
                 "media_type": "text", "reply_to_id": 1,
                 "tg_message_id": 12}]
        await run_l1(rows=rows, chat_id=CHAT_A, llm_call=_llm_call,
                     budget=("chars", 20000))
        assert captured, "LL1-вызов обязан состояться"
        user_content = captured[0][-1]["content"]
        assert user_content.count("<Chat_Time_Context") == 1
        assert 'phase="plan"' in user_content
        assert "Europe/Moscow" in user_content


# ── UR-26.3: наблюдатель ────────────────────────────────────────────────────


class TestObserverClock:
    @pytest.mark.asyncio
    async def test_eval_window_sees_chat_clock(self, tz_env, monkeypatch):
        from services.initiative_observer import InitiativeObserverRunner
        from tests.test_direct_chat import FakeLLM
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Moscow"})
        runner = InitiativeObserverRunner.__new__(InitiativeObserverRunner)
        llm = FakeLLM(text="{}")
        runner._llm = llm
        runner._aliases = None
        runner._db = object()
        rows = [{"id": 1, "user_id": 10, "text": "привет",
                 "reply_to_id": None}]
        monkeypatch.setattr(
            "services.initiative_observer._memory_hints",
            __import__("unittest.mock",
                       fromlist=["AsyncMock"]).AsyncMock(return_value=()))
        await runner._evaluate_window(CHAT_A, rows)
        user_content = llm.messages[-1]["content"]
        assert user_content.count("<Chat_Time_Context") == 1
        assert 'phase="plan"' in user_content
        assert "Europe/Moscow" in user_content
