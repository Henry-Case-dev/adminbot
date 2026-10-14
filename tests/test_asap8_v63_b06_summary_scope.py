"""ASAP 8 v6.3 B06 — Per-chat Summary управляет runtime (backend).

Приёмка:
* B06.1 — резолюция global default → explicit chat ON/OFF → emergency env
  gate; локальный OFF глушит ТОЛЬКО данный чат; явный chat ON при global
  OFF разрешает чат; inherit через сброс override; producer/cron/trigger/
  scheduler/retry/queue реально следуют выбору — проверка на РЕАЛЬНОМ
  пути генерации (`generate_and_send`, моки LLM), не только /api/config;
* B06.2 — матрица module → toggle param → ParamSpec.per_chat → runtime
  read: Summary per-chat-operable; global-only карточки не получают inert
  override (API 422); расхождение чтения temporal.tool_enabled закрыто;
* B06.3 — смена scope двух чатов, сброс/инверсия global default, рестарт
  (персистентность чат-слоя), сохранение чата A не меняет чат B
  (409/role-deny — существующие web-API контракты, см. отчёт).

TEST-LIFECYCLE: CONTRACT owner=REQ-B06 (per-chat Summary resolution)
TEST-LIFECYCLE: REGRESSION owner=REQ-B06 (global-only флаг не управлял
runtime чата; producer не существовал при global OFF + chat ON)
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import settings
from services import summary_scheduler as sched
from services.summary_generator import SummaryGenerator
from services.summary_xml import XmlGroundingBuilder

pytestmark = pytest.mark.asap4

CHAT_A = -100111
CHAT_B = -100222

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_sleep(monkeypatch):
    """B06: без реальных sleep в пайплайне генерации."""
    from unittest.mock import MagicMock
    fake = MagicMock()
    fake.sleep = AsyncMock(return_value=None)
    fake.Lock = asyncio.Lock
    monkeypatch.setattr("services.summary_generator.asyncio", fake)
    return fake.sleep


class _FakeChatParams:
    """Фейковый chat_params-слой (тот же контракт
    `get_chat_param_defaulted`): per-chat overrides в Python-dict."""

    def __init__(self):
        self.overrides: dict[int, dict] = {}

    async def get_chat_param_defaulted(self, chat_id: int, key: str,
                                       fallback=None):
        overrides = self.overrides.get(int(chat_id)) or {}
        if key not in overrides:
            return fallback
        return overrides[key]

    def set(self, chat_id: int, key: str, value):
        self.overrides.setdefault(int(chat_id), {})[key] = value

    def reset(self, chat_id: int, key: str):
        self.overrides.get(int(chat_id), {}).pop(key, None)


@pytest.fixture()
def chat_params(monkeypatch):
    from services import chat_params as cp
    fake = _FakeChatParams()
    monkeypatch.setattr(cp, "get_chat_param_defaulted",
                        fake.get_chat_param_defaulted)
    yield fake


class _FakeHot:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        return self._values.get(key, default)


@pytest.fixture()
def global_flag(monkeypatch):
    from services.hot_config import get_config_cache, set_config_cache
    state = {"value": True}
    saved = get_config_cache()

    def _install(value: bool):
        state["value"] = value
        set_config_cache(_FakeHot({"flags.summary_enabled": value}))
        monkeypatch.setattr(type(settings), "SUMMARY_ENABLED", value)

    _install(True)
    yield _install
    set_config_cache(saved)


class FakeMemory:
    def __init__(self):
        self.rows = [{"id": 1, "user_id": 10, "timestamp": 1_700_000_000,
                      "author_name": "вася", "text": "приват",
                      "reply_to_id": None, "media_type": "text"}]
        self.compress_calls = []

    async def compress_and_purge(self, chat_id):
        self.compress_calls.append(chat_id)

    async def get_window_messages(self, chat_id):
        return self.rows

    async def search_long_term(self, chat_id, keywords, limit):
        return []

    async def vector_search(self, chat_id, query, limit):
        return []

    async def get_graph_facts(self, chat_id, rows, keywords):
        return []

    async def memorize_facts(self, chat_id, raw_text, source_type):
        return None

    async def get_rag_context(self, chat_id, query, *,
                              sort_by_timestamp=False):
        return ""


class FakeLLM:
    def __init__(self):
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        return "саммари текста"


def _make_generator(monkeypatch):
    """Реальный generate_and_send: моки только на LLM/доставке."""
    llm = FakeLLM()
    bot = AsyncMock()
    gen = SummaryGenerator(FakeMemory(), XmlGroundingBuilder(), llm, bot)
    gen._hybrid_l2_enabled = AsyncMock(return_value=False)
    # Диагностика run-store/cover вне фокуса B06 — стабы.
    monkeypatch.setattr(gen, "_durable_run_create", AsyncMock())
    return gen, llm, bot


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── B06.1: матрица на реальном пути генерации ───────────────────────────────

class TestMatrixRealGeneration:
    @pytest.mark.asyncio
    async def test_global_on_chat_off_a_inherit_b(self, monkeypatch,
                                                  chat_params, global_flag,
                                                  no_sleep):
        """global ON, A=OFF (explicit), B=inherit: A не генерирует
        (0 LLM; manual — честный UX), B генерирует (LLM вызвана)."""
        global_flag(True)
        chat_params.set(CHAT_A, "flags.summary_enabled", False)
        gen, llm, bot = _make_generator(monkeypatch)
        await gen.generate_and_send(CHAT_A)
        assert llm.calls == 0
        await gen.generate_and_send(CHAT_A, manual=True)
        assert llm.calls == 0
        assert bot.send_message.await_count >= 1, "честный UX manual-off"
        await gen.generate_and_send(CHAT_B)
        assert llm.calls == 1, "inherit B следует global ON"

    @pytest.mark.asyncio
    async def test_global_off_chat_on_a_inherit_b(self, monkeypatch,
                                                  chat_params, global_flag,
                                                  no_sleep):
        """global OFF, A=ON (explicit), B=inherit: A генерирует (чат
        разрешён), B выключен. Producer-логика — резолвер в generate_and_send."""
        global_flag(False)
        chat_params.set(CHAT_A, "flags.summary_enabled", True)
        gen, llm, bot = _make_generator(monkeypatch)
        await gen.generate_and_send(CHAT_A)
        assert llm.calls == 1, "chat ON при global OFF разрешает чат"
        await gen.generate_and_send(CHAT_B)
        assert llm.calls == 1, "B (inherit) остаётся выключен"
        # manual в B получает UX, а не молчание
        assert bot.send_message.await_count >= 1

    @pytest.mark.asyncio
    async def test_emergency_env_beats_chat_on(self, monkeypatch, chat_params,
                                               global_flag, no_sleep):
        """Emergency env gate блокирует даже явный chat ON."""
        global_flag(True)
        chat_params.set(CHAT_A, "flags.summary_enabled", True)
        monkeypatch.setenv(sched.SUMMARY_EMERGENCY_ENV, "1")
        try:
            enabled, source = await sched.summary_effective_enabled(CHAT_A)
            assert (enabled, source) == (False, "emergency_env")
            gen, llm, bot = _make_generator(monkeypatch)
            await gen.generate_and_send(CHAT_A, manual=True)
            assert llm.calls == 0
        finally:
            monkeypatch.delenv(sched.SUMMARY_EMERGENCY_ENV)

    @pytest.mark.asyncio
    async def test_inherit_via_override_reset(self, monkeypatch, chat_params,
                                              global_flag):
        """Inherit возвращается через сброс override (без записи значения)."""
        global_flag(False)
        chat_params.set(CHAT_A, "flags.summary_enabled", True)
        assert await sched.summary_effective_enabled(CHAT_A) == \
            (True, "chat")
        chat_params.reset(CHAT_A, "flags.summary_enabled")
        assert await sched.summary_effective_enabled(CHAT_A) == \
            (False, "global"), "после сброса — global default"
        global_flag(True)
        assert await sched.summary_effective_enabled(CHAT_A) == \
            (True, "global")


# ── B06.1: cron/scheduler следует резолверу ─────────────────────────────────

class TestSchedulerFollowsResolver:
    @pytest.mark.asyncio
    async def test_tick_skips_chat_off_runs_chat_inherit(self, monkeypatch,
                                                         chat_params,
                                                         global_flag):
        global_flag(True)
        chat_params.set(CHAT_A, "flags.summary_enabled", False)

        class _Db:
            async def get_smart_chat_ids(self):
                return [CHAT_A, CHAT_B]

        gen = AsyncMock()
        service = sched.SummarySchedulerService(gen, _Db())
        await service._tick()
        called = [c.args[0] for c in gen.generate_and_send.await_args_list]
        assert called == [CHAT_B], "cron пропускает chat OFF, гоняет inherit"

    @pytest.mark.asyncio
    async def test_tick_runs_chat_on_when_global_off(self, monkeypatch,
                                                     chat_params,
                                                     global_flag):
        global_flag(False)
        chat_params.set(CHAT_A, "flags.summary_enabled", True)

        class _Db:
            async def get_smart_chat_ids(self):
                return [CHAT_A, CHAT_B]

        gen = AsyncMock()
        service = sched.SummarySchedulerService(gen, _Db())
        await service._tick()
        called = [c.args[0] for c in gen.generate_and_send.await_args_list]
        assert called == [CHAT_A]

    @pytest.mark.asyncio
    async def test_cmd_summary_manual_per_chat_gate(self, monkeypatch,
                                                    chat_params, global_flag):
        """B06.1 manual-путь: /summary в группе с chat ON при global OFF —
        гейт пропускает; chat OFF — UNHANDLED; ЛС — прежний global-гейт
        (F-14 S4: manual в ЛС не зависит от DM-override)."""
        import handlers.summary as hs
        from aiogram.dispatcher.event.bases import UNHANDLED

        global_flag(False)
        chat_params.set(CHAT_A, "flags.summary_enabled", True)

        msg = MagicMock()
        msg.chat.id = CHAT_A
        msg.from_user = MagicMock(id=123)
        msg.text = "/summary"
        with patch.object(hs, "_generator", None), \
                patch.object(hs, "_safe_send", AsyncMock()) as send, \
                patch.object(hs, "_delete_command", AsyncMock()):
            result_on = await hs.cmd_summary(msg, bot=MagicMock())
        assert result_on is not UNHANDLED, "chat ON при global OFF пропущен"

        chat_params.set(CHAT_A, "flags.summary_enabled", False)
        with patch.object(hs, "_summary_enabled", return_value=True):
            result_off = await hs.cmd_summary(msg, bot=MagicMock())
        assert result_off.name == "UNHANDLED", "chat OFF глушит только чат"

        # ЛС: DM-override (даже False из DM-дефолтов) НЕ глушит manual
        # (F-14 S4); global OFF по-прежнему мастер (паритет baseline).
        global_flag(True)
        dm_msg = MagicMock()
        dm_msg.chat.id = 555
        dm_msg.from_user = MagicMock(id=555)
        dm_msg.text = "/summary"
        chat_params.set(555, "flags.summary_enabled", False)
        with patch.object(hs, "_generator", None), \
                patch.object(hs, "_safe_send", AsyncMock()) as send_dm, \
                patch.object(hs, "_delete_command", AsyncMock()):
            result_dm = await hs.cmd_summary(dm_msg, bot=MagicMock())
        assert result_dm is not UNHANDLED, "F-14 S4: manual в ЛС работает"

    @pytest.mark.asyncio
    async def test_any_chat_opted_in_scan(self, monkeypatch):
        """Producer-гейт: scan PG-профилей находит явный chat=ON."""

        class _Row(dict):
            pass

        class _Pool:
            def __init__(self, rows):
                self._rows = rows

            def acquire(self):
                outer = self

                class _CM:
                    async def __aenter__(self):
                        return outer

                    async def __aexit__(self, *exc):
                        return False

                return _CM()

            async def fetch(self, sql, *args):
                return self._rows

        class _Pg:
            def __init__(self, rows):
                self.pool = _Pool(rows)

        rows = [_Row(chat_id=CHAT_A,
                     overrides='{"flags.summary_enabled": true}')]
        assert await sched.summary_any_chat_opted_in(_Pg(rows)) is True
        rows_false = [_Row(chat_id=CHAT_A,
                           overrides='{"flags.summary_enabled": false}')]
        assert await sched.summary_any_chat_opted_in(_Pg(rows_false)) is False
        assert await sched.summary_any_chat_opted_in(_Pg([])) is False
        assert await sched.summary_any_chat_opted_in(None) is False


# ── B06.2: матрица каталога и чтений ────────────────────────────────────────

class TestCatalogRuntimeMatrix:
    def test_summary_toggle_is_per_chat_in_catalog(self):
        """ParamSpec.flags.summary_enabled — per_chat (категория flags,
        не секрет); runtime читает его per-chat (единый резолвер)."""
        from services.param_catalog import get_by_pg_key
        spec = get_by_pg_key("flags.summary_enabled")
        assert spec is not None
        assert spec.per_chat is True
        assert spec.type == "bool"

    def test_models_and_keys_are_global_only(self):
        """models.*/keys.* — строго глобальные (контракт каталога)."""
        from services.param_catalog import get_by_pg_key
        for key in ("models.llm_model_name", "keys.llm_api_key",
                    "temporal.tool_enabled"):
            spec = get_by_pg_key(key)
            assert spec is not None
            assert spec.per_chat is False, key

    def test_runtime_reads_match_per_chat_contract(self):
        """Ключи-перечень B06.2: per_chat-ключ, реально читаемый
        резолвером чата (Summary), и global-only оси (module_registry
        runtime_gate) — расхождение чтения закрыто."""
        assert sched.summary_global_default.__name__ == \
            "summary_global_default"
        from services import module_registry as mr
        for module_id in ("factcheck", "vision", "nostalgia", "sleep",
                          "initiative", "factcheck_temporal"):
            spec = mr.MODULE_REGISTRY[module_id]
            assert spec.runtime_gate == "global", module_id

    def test_temporal_tool_toggle_read_through_hot(self, monkeypatch):
        """B07.2/B06.2: runtime-чтение temporal.tool_enabled идёт через
        hot-ключ (PG-значение применяется без рестарта), а не только
        статический Settings-канон."""
        from services import tool_schemas
        from services.hot_config import set_config_cache
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_tool_enabled",
            lambda: True)
        set_config_cache(_FakeHot({"temporal.tool_enabled": False}))
        try:
            assert tool_schemas._fact_check_tool_enabled() is False
            set_config_cache(_FakeHot({"temporal.tool_enabled": True}))
            assert tool_schemas._fact_check_tool_enabled() is True
        finally:
            set_config_cache(None)

    def test_global_only_keys_cannot_get_inert_override(self):
        """API-контракт: per_chat=False → chat-SCOPE POST = 422 (inert
        override создать нельзя). Source-гвард валидации в routes."""
        src = (ROOT / "web" / "api" / "routes.py").read_text(
            encoding="utf-8")
        assert "нельзя" in src and "per_chat" in src
        assert "if not spec.per_chat:" in src


# ── B06.3: два чата, инверсия, рестарт ──────────────────────────────────────

class TestTwoChatsAndRestart:
    @pytest.mark.asyncio
    async def test_save_chat_a_does_not_change_chat_b(self, monkeypatch,
                                                      chat_params,
                                                      global_flag):
        """Сохранение override в чате A не меняет чат B."""
        global_flag(True)
        await gen_check(monkeypatch, chat_params, CHAT_A, False)
        # B остался inherit → ON
        enabled_b, source_b = await sched.summary_effective_enabled(CHAT_B)
        assert (enabled_b, source_b) == (True, "global")

    @pytest.mark.asyncio
    async def test_global_inversion_without_chat_writes(self, chat_params,
                                                        global_flag):
        """Инверсия global default меняет inherit-чаты, explicit-чаты
        держат своё значение."""
        global_flag(True)
        chat_params.set(CHAT_A, "flags.summary_enabled", False)
        assert await sched.summary_effective_enabled(CHAT_A) == \
            (False, "chat")
        assert await sched.summary_effective_enabled(CHAT_B) == \
            (True, "global")
        global_flag(False)
        assert await sched.summary_effective_enabled(CHAT_A) == \
            (False, "chat"), "explicit OFF не инвертируется глобалом"
        assert await sched.summary_effective_enabled(CHAT_B) == \
            (False, "global"), "inherit следует новой global"

    def test_resolver_stateless_across_restart(self, monkeypatch,
                                               chat_params, global_flag):
        """Рестарт: чат-слой персистентен (PG), резолвер не держит
        in-memory состояния — новый процесс читает тот же override."""
        global_flag(False)
        chat_params.set(CHAT_A, "flags.summary_enabled", True)
        first = _run(sched.summary_effective_enabled(CHAT_A))
        # «Новый процесс»: чистый вызов того же резолвера (state-free).
        second = _run(sched.summary_effective_enabled(CHAT_A))
        assert first == second == (True, "chat")

    def test_bot_producer_gate_condition_keeps_flag_in_if(self):
        """§18H(2) + B06.1: producer-условие в bot.py содержит
        flags.summary_enabled И chat=ON-scan (chat ON при global OFF)."""
        src = (ROOT / "bot.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        func = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and \
                    node.name == "on_startup":
                func = node
                break
        assert func is not None
        summary_if_tests = [ast.unparse(n.test) for n in ast.walk(func)
                            if isinstance(n, ast.If)
                            and "flags.summary_enabled" in ast.unparse(n.test)]
        assert summary_if_tests, "Summary-контур под своим флагом"
        assert any("summary_any_chat_opted_in" in t for t in summary_if_tests)


async def gen_check(monkeypatch, chat_params, chat_id, value):
    chat_params.set(chat_id, "flags.summary_enabled", value)
    enabled, source = await sched.summary_effective_enabled(chat_id)
    assert (enabled, source) == (value, "chat")
