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
        # Sync-проекция M2 (`read_override_sync`) читает тот же прогретый
        # root из `_items`; форма записи — (ts, root, updated_at).
        self._items = {int(cid): (0.0, root, self.updated_at)
                       for cid, root in self._roots.items()}

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


# ── Review 5c96a396: fallback-репак не режет блок часов (UR-25.6) ───────────


class TestFallbackAdapterClock:
    """`build_l2_fallback_adapter` при тесном окне fallback: блок
    <Chat_Time_Context> либо ЦЕЛИК с тем же as_of_utc, либо честная
    CAPACITY-пометка и блока нет; обрезок запрещён. Обычные сжимаемые
    строки (и пустая строка наследования времени) ведут себя как раньше."""

    @staticmethod
    def _clock_block() -> str:
        snap = cc.TimeSnapshot(
            as_of_utc=SUMMER,
            local_datetime=SUMMER + datetime.timedelta(hours=3),
            weekday="Среда", timezone="Europe/Moscow", utc_offset="+03:00",
            timezone_source="chat", config_version="cfg-1")
        return cc.render_chat_time_context(snap, phase=cc.PHASE_ANSWER)

    def _adapt(self, *, budget: int, parts, evidence: str = ""):
        from services.direct_execution import (
            L2_EVIDENCE_FLOOR_TOKENS, _safe_count_tokens,
            build_l2_fallback_adapter)
        system = "СИСТЕМНАЯ ИНСТРУКЦИЯ " * 120
        evidence_text = evidence if evidence else "доказательство " * 400
        floor = min(_safe_count_tokens(evidence_text),
                    L2_EVIDENCE_FLOOR_TOKENS)
        budget = max(200, budget + _safe_count_tokens(system) + floor)
        reasons: list[str] = []
        adapter = build_l2_fallback_adapter(
            system=system, parts=list(parts), evidence=evidence_text,
            query="вопрос пользователя",
            fallback_budget_tokens=budget, on_capacity_reason=reasons.append)
        adapted = adapter({"messages": [
            {"role": "system", "content": "old"},
            {"role": "user", "content": "old"}]})
        content = adapted["messages"][-1]["content"]
        return content, reasons

    def test_tight_budget_drops_block_whole_with_capacity(self):
        """Блок не влезает → нет блока вовсе + CAPACITY + reason; обрезка
        (head+tail внутри тегов) запрещена."""
        clock = self._clock_block()
        clock_tokens = __import__("services.direct_execution",
                                  fromlist=["_safe_count_tokens"]
                                  )._safe_count_tokens(clock)
        # remaining после system+evidence = clock_tokens - 3 → блок не влезает.
        content, reasons = self._adapt(budget=clock_tokens - 3,
                                       parts=[clock, "обычный текст " * 200])
        open_count = content.count("<Chat_Time_Context")
        close_count = content.count("</Chat_Time_Context>")
        assert open_count == close_count, (
            "блок часов не должен оставаться разрезанным посередине")
        if open_count == 0:
            # Честная ёмкость: блока нет, пометка есть, callback дёрнут.
            assert "[CAPACITY]" in content
            assert "fallback_clock_dropped" in reasons
            # Обрезок тоже не уехал: точного as_of из блока в payload нет.
            assert "as_of_utc: 2026-07-15T12:00:00+00:00" not in content
        else:
            # Целый блок — байт-в-байт исходный, тот же as_of_utc.
            assert content.count("<Chat_Time_Context") == 1
            start = content.find("<Chat_Time_Context")
            end = content.find("</Chat_Time_Context>", start)
            assert content[start:end + len("</Chat_Time_Context>")] == clock
        assert "обрезано под окно fallback</Chat_Time_Context" not in content

    def test_generous_budget_keeps_block_intact_same_asof(self):
        clock = self._clock_block()
        clock_tokens = __import__("services.direct_execution",
                                  fromlist=["_safe_count_tokens"]
                                  )._safe_count_tokens(clock)
        content, _reasons = self._adapt(budget=clock_tokens + 50,
                                        parts=[clock, "обычный текст " * 50])
        assert content.count("<Chat_Time_Context") == 1
        assert content.count("</Chat_Time_Context>") == 1
        assert "as_of_utc: 2026-07-15T12:00:00+00:00" in content
        assert "Europe/Moscow" in content
        assert "[CAPACITY]" not in content

    def test_plain_strings_still_compressible(self):
        """Без блока часов поведение прежнее: длинная сжимаемая строка режется
        head+tail (пустая строка наследования времени — просто не попадает
        в rest, как раньше)."""
        from services.direct_execution import _safe_count_tokens
        long_text = "пользовательский контекст " * 400
        text_tokens = _safe_count_tokens(long_text)
        content, _reasons = self._adapt(budget=text_tokens // 2,
                                        parts=[long_text])
        assert "обрезано под окно fallback" in content
        assert "<Chat_Time_Context" not in content


# ── Review 5c96a396: валидация IANA на сохранении (UR-24.4) ─────────────────


class TestChatTimezoneSaveValidation:
    """Сохранение через каталог: «Europe/Berlin» — ok; «Mars/Olympus_Mons» —
    отказ валидации (ValueError → HTTP 422 в обоих write-путях); "" —
    наследование. Read-слой при этом не менялся (мусор в хранилище →
    наследование на чтении, без fabricate)."""

    def test_catalog_rule(self):
        from services import param_catalog as pc
        assert pc.validate_value_rule("limits.chat_timezone",
                                      "Europe/Berlin") is None
        assert pc.validate_value_rule("limits.chat_timezone", "") is None
        error = pc.validate_value_rule("limits.chat_timezone",
                                       "Mars/Olympus_Mons")
        assert error and "IANA" in error and "limits.chat_timezone" in error

    def test_write_seam_rejects_non_iana(self):
        """Общий шов сохранения `_coerce_value` (global + per-chat paths):"""
        from services import param_catalog as pc
        from web.api.routes import _coerce_value
        spec = pc.get_by_pg_key("limits.chat_timezone")
        assert spec is not None
        assert _coerce_value(spec, "Europe/Berlin") == "Europe/Berlin"
        # "" — наследование, сохраняется как есть.
        assert _coerce_value(spec, "   ") == "   "
        with pytest.raises(ValueError) as excinfo:
            _coerce_value(spec, "Mars/Olympus_Mons")
        assert "IANA" in str(excinfo.value)


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


# ═══ UR-25.4: структурные относительные даты от пояса чата ═══════════════════


def _epoch(*args, tz=datetime.timezone.utc):
    return int(datetime.datetime(*args, tzinfo=tz).timestamp())


class TestRelativeLocalTime:
    @pytest.mark.asyncio
    async def test_auckland_midnight_today_yesterday_tomorrow(self, tz_env):
        """00:30 Auckland (UTC-дата — предыдущая): today/yesterday/tomorrow и
        «в 4 утра» считаются от ЛОКАЛЬНОЙ даты/пояса, не от UTC."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone":
                                    "Pacific/Auckland"})
        snap = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 7, 14, 12, 30, tzinfo=datetime.timezone.utc))
        assert snap.local_datetime.date() == datetime.date(2026, 7, 15)
        assert cc.local_date(snap) == datetime.date(2026, 7, 15)
        assert cc.local_date(snap, day_offset=-1) == datetime.date(2026, 7, 14)
        assert cc.local_date(snap, day_offset=1) == datetime.date(2026, 7, 16)
        at_four = cc.local_wall_to_utc(snap, hour=4)
        assert at_four.local.date() == datetime.date(2026, 7, 15)
        assert (at_four.local.hour, at_four.local.minute) == (4, 0)
        assert at_four.utc == datetime.datetime(
            2026, 7, 14, 16, 0, tzinfo=datetime.timezone.utc)
        # Мутация «взять UTC-дату» красная: UTC-дата — 14-е, блок — 15-е.
        assert at_four.utc.date() == datetime.date(2026, 7, 14)
        yesterday_four = cc.local_wall_to_utc(
            snap, day_offset=-1, hour=4)
        assert yesterday_four.local.date() == datetime.date(2026, 7, 14)
        assert yesterday_four.gap is False and yesterday_four.ambiguous is False

    @pytest.mark.asyncio
    async def test_berlin_gap_fold_and_kathmandu_quarter_offset(self, tz_env):
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Berlin"})
        berlin = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 3, 29, 10, 0, tzinfo=datetime.timezone.utc))
        gap = cc.local_wall_to_utc(
            berlin, day=datetime.date(2026, 3, 29), hour=2, minute=30)
        assert gap.gap is True and gap.ambiguous is False and gap.fold == 0
        assert (gap.local.hour, gap.local.minute) == (3, 0)
        assert gap.local.utcoffset() == datetime.timedelta(hours=2)
        assert gap.utc == datetime.datetime(
            2026, 3, 29, 1, 0, tzinfo=datetime.timezone.utc)
        fold = cc.local_wall_to_utc(
            berlin, day=datetime.date(2026, 10, 25), hour=2, minute=30)
        assert fold.ambiguous is True and fold.gap is False and fold.fold == 0
        assert fold.local.utcoffset() == datetime.timedelta(hours=2)
        assert fold.utc == datetime.datetime(
            2026, 10, 25, 0, 30, tzinfo=datetime.timezone.utc)
        # Полу-сдвиг: Kathmandu +05:45 — верный instant, не «UTC+5».
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Asia/Kathmandu"})
        kath = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 7, 14, 12, 0, tzinfo=datetime.timezone.utc))
        local4 = cc.local_wall_to_utc(
            kath, day=datetime.date(2026, 7, 15), hour=4, minute=0)
        assert local4.utc == datetime.datetime(
            2026, 7, 14, 22, 15, tzinfo=datetime.timezone.utc)
        assert local4.local.utcoffset() == datetime.timedelta(
            hours=5, minutes=45)
        assert local4.local.strftime("%d.%m.%Y %H:%M") == "15.07.2026 04:00"

    @pytest.mark.asyncio
    async def test_last_week_bounds_in_chat_zone(self, tz_env):
        """«на прошлой неделе» — day_offset=-7 от локальной даты; явный day
        даёт те же границы (для диапазона дат)."""
        _set_chat_override(CHAT_A, {"limits.chat_timezone":
                                    "Pacific/Auckland"})
        snap = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 7, 14, 12, 30, tzinfo=datetime.timezone.utc))
        start = cc.local_wall_to_utc(snap, day_offset=-7, hour=0)
        explicit = cc.local_wall_to_utc(
            snap, day=datetime.date(2026, 7, 8), hour=0)
        assert start == explicit
        assert start.local.date() == datetime.date(2026, 7, 8)
        assert start.utc == datetime.datetime(
            2026, 7, 7, 12, 0, tzinfo=datetime.timezone.utc)
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Asia/Kathmandu"})
        kath = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 7, 14, 12, 0, tzinfo=datetime.timezone.utc))
        kath_start = cc.local_wall_to_utc(kath, day_offset=-7, hour=0)
        assert kath_start.local.date() == datetime.date(2026, 7, 7)
        assert kath_start.utc == datetime.datetime(
            2026, 7, 6, 18, 15, tzinfo=datetime.timezone.utc)

    @pytest.mark.asyncio
    async def test_local_epoch_parity_with_tool_router(self, tz_env):
        """Единственный алгоритм: `tool_router._local_epoch` делегирует в
        ChatClock и совпадает на regular/gap/fold/полу-сдвиге."""
        from services.tool_router import _local_epoch
        for tz_name in ("Europe/Berlin", "Asia/Kathmandu"):
            _set_chat_override(CHAT_A, {"limits.chat_timezone": tz_name})
            snap = await cc.snapshot(
                CHAT_A, at_utc=datetime.datetime(
                    2026, 7, 14, 12, 0, tzinfo=datetime.timezone.utc))
            tz = zoneinfo.ZoneInfo(tz_name)
            cases = [
                (datetime.date(2026, 3, 29), 2, 30),
                (datetime.date(2026, 10, 25), 2, 30),
                (datetime.date(2026, 7, 15), 0, 0),
                (datetime.date(2026, 7, 15), 4, 0),
            ]
            for day, hour, minute in cases:
                expected = _local_epoch(day, hour, minute, tz)
                instant = cc.local_wall_to_utc(
                    snap, day=day, hour=hour, minute=minute)
                assert int(instant.utc.timestamp()) == expected, (
                    tz_name, day, hour, minute)

    @pytest.mark.asyncio
    async def test_one_resolver_with_per_chat_legacy(self, tz_env):
        """UR-25: per-chat legacy `limits.summary_timezone` — один и тот же
        пояс/источник у ChatClock (async/sync) и meme_initiative."""
        from services import meme_initiative as meme
        _set_chat_override(CHAT_A, {
            "limits.summary_timezone": "Asia/Almaty"})
        tz_env.set_global("limits.chat_timezone", "Europe/Berlin")
        tz, source, _cv = await cc.resolve_chat_timezone(CHAT_A)
        assert (tz, source) == ("Asia/Almaty", "chat_legacy")
        sync_tz, sync_source, _cv2 = cc.resolve_chat_timezone_sync(CHAT_A)
        assert (sync_tz, sync_source) == (tz, source)
        assert meme.resolve_timezone(CHAT_A) == (tz, source)


class _HistoryClockDirect:
    """Пара прогонов `_plan_direct_l1` с историей и без — discriminating
    proof UR-17.5 (блок времени не читает прошлые реплики)."""

    @staticmethod
    def _window_row(text: str) -> dict:
        return {"user_id": 10, "author_name": "вася", "text": text,
                "timestamp": 100, "media_type": "text", "reply_to_id": None,
                "tg_message_id": None}

    @classmethod
    def _block(cls, content: str) -> str:
        start = content.find("<Chat_Time_Context")
        end = content.find("</Chat_Time_Context>", start)
        assert start >= 0 and end >= 0
        return content[start:end + len("</Chat_Time_Context>")]

    @classmethod
    async def _payload(cls, service, llm, window):
        await service._plan_direct_l1(
            CHAT_A, __import__("tests.test_direct_chat",
                               fromlist=["_message"])._message(
                                   "привет", chat_id=CHAT_A),
            "привет", "corr-175", bundle=None, target_name="Вася",
            user_id=10, character_block="", lore_enabled=False,
            image_enabled=False, force_required=True, reply_bot=False)
        return llm.messages[-1]["content"]


class TestHistoryIsNotClock:
    @pytest.mark.asyncio
    async def test_past_four_am_phrase_does_not_become_current_time(
            self, tz_env, monkeypatch):
        """UR-17.5: «сейчас 4 утра»/«Новосибирск» в истории не становятся
        текущим временем: frozen 21:05 Auckland, блок одинаков с прогоном без
        этих реплик."""
        from unittest.mock import AsyncMock
        from tests.test_direct_chat import (
            FakeLLM, FakeMemory, _make_service)
        _set_chat_override(CHAT_A, {"limits.chat_timezone":
                                    "Pacific/Auckland"})
        frozen = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 7, 15, 9, 5, tzinfo=datetime.timezone.utc))

        async def _frozen_snapshot(chat_id, **kwargs):
            return frozen

        monkeypatch.setattr(cc, "snapshot", _frozen_snapshot)
        poisoned = [
            _HistoryClockDirect._window_row("сейчас 4 утра"),
            _HistoryClockDirect._window_row("я в Новосибирске, тут холодно"),
            _HistoryClockDirect._window_row("ну и шутки у тебя"),
        ]
        clean: list = []
        blocks = []
        for window in (poisoned, clean):
            llm = FakeLLM(text='{"action":"reply","confidence":0.9}')
            service = _make_service(memory=FakeMemory(window=window), llm=llm)
            monkeypatch.setattr(service, "_history_partial",
                                AsyncMock(return_value=False))
            content = await _HistoryClockDirect._payload(
                service, llm, window)
            blocks.append(_HistoryClockDirect._block(content))
        assert blocks[0] == blocks[1], (
            "блок часов обязан быть идентичен независимо от прошлых реплик")
        assert "21:05" in blocks[0]
        assert "as_of_utc: 2026-07-15T09:05:00+00:00" in blocks[0]
        assert "4 утра" not in blocks[0]
        assert "Новосибирск" not in blocks[0]
        assert 'phase="plan"' in blocks[0]


# ═══ UR-27.2: окно источников UTC + локальное представление ══════════════════


class TestSummaryWindowLocal:
    @staticmethod
    def _rows(start: datetime.datetime, end: datetime.datetime) -> list:
        return [
            {"id": 1, "user_id": 10, "author_name": "вася",
             "text": "первое", "timestamp": int(start.timestamp()),
             "media_type": "text", "reply_to_id": None,
             "tg_message_id": 11},
            {"id": 2, "user_id": 11, "author_name": "петя",
             "text": "второе", "timestamp": int(end.timestamp()),
             "media_type": "text", "reply_to_id": 1,
             "tg_message_id": 12},
        ]

    @pytest.mark.asyncio
    async def test_window_across_local_midnight_and_dst(self, tz_env):
        from services.summary_l1_clusterizer import run_l1
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Berlin"})
        berlin = zoneinfo.ZoneInfo("Europe/Berlin")
        start = datetime.datetime(2026, 10, 25, 0, 0, tzinfo=berlin)
        end = datetime.datetime(2026, 10, 25, 3, 30, tzinfo=berlin)
        captured: list[list] = []

        async def _llm_call(messages):
            captured.append(messages)
            return "{}", None

        await run_l1(rows=self._rows(start, end), chat_id=CHAT_A,
                     llm_call=_llm_call, budget=("chars", 20000))
        user = captured[0][-1]["content"]
        assert user.count("<Chat_Time_Context") == 1
        assert ("window_utc: 2026-10-24T22:00:00+00:00.."
                "2026-10-25T02:30:00+00:00") in user
        assert ("window_local: 25.10.2026 00:00 +02:00.."
                "25.10.2026 03:30 +01:00") in user
        # Каждая граница — свой offset (DST внутри окна), не «UTC+N».
        assert "UTC+" not in user.split("window_local:", 1)[1].split(
            "\n", 1)[0]

    @pytest.mark.asyncio
    async def test_refresh_after_midnight_keeps_window_bytes(self, tz_env):
        _set_chat_override(CHAT_A, {"limits.chat_timezone": "Europe/Berlin"})
        plan = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 10, 24, 23, 50, tzinfo=datetime.timezone.utc))
        window = (
            datetime.datetime(2026, 10, 24, 22, 0,
                              tzinfo=datetime.timezone.utc),
            datetime.datetime(2026, 10, 25, 2, 30,
                              tzinfo=datetime.timezone.utc))
        messages = cc.attach_time_context(
            [{"role": "system", "content": "S"},
             {"role": "user", "content": "текст окна"}],
            plan, phase=cc.PHASE_ANSWER, window=window)
        before = messages[-1]["content"]
        old_window = [line for line in before.splitlines()
                      if line.startswith(("window_utc:", "window_local:"))]
        fresh = await cc.snapshot(
            CHAT_A, at_utc=datetime.datetime(
                2026, 10, 25, 0, 3, tzinfo=datetime.timezone.utc))
        refreshed = cc.refresh_time_context(
            messages, fresh, phase=cc.PHASE_ANSWER)
        after = refreshed[-1]["content"]
        new_window = [line for line in after.splitlines()
                      if line.startswith(("window_utc:", "window_local:"))]
        assert new_window == old_window
        assert after != before
        assert "as_of_utc: 2026-10-25T00:03:00+00:00" in after
        # Вне блока — байт-в-байт прежний текст окна.
        assert "текст окна" in after
        assert after.replace(old_window[0], "").replace(
            old_window[1], "").count("window_") == 0
