"""FCT-S4-EVIDENCE-VERDICT — надёжность и изоляция (FCT-1001, FCT-1002).

Контракт: `plans/features/fc-trust-01/requirements-map.json`
(`FCT-1001` L00191, `FCT-1002` L00194) + `s4-design.md` §4/U2 + D8.

FCT-1001 — наблюдаемое поведение:
* провайдерский fallback: 5xx/timeout одной ноги → следующая независимая нога
  обслуживает; отказавшая паркуется в существующем `credential_health`
  (`HEALTH_COOLDOWN`), успешная нога снимает парковку (healthy);
* все ноги временно недоступны (429 spend без Retry-After) → kind-парковка
  группы с `next_allowed_at`, число HTTP-вызовов ограничено размером пула,
  честный терминал (`EmbeddingGroupCoolingDown`), повтор в окне — без HTTP;
* кооперативная отмена: `run_retrieval(is_cancelled=...)` прекращает работу
  и помечает прогон `cancelled` (существующий тест S3), а отмена handler'а
  не оставляет задач и не списывает пользовательский лимит;
* single-flight: два одновременных одинаковых запроса не удваивают платный
  вызов (в т.ч. на проде-пути `THROTTLE_PERSISTENT_ENABLED=True`);
* ранний/технический отказ не расходует лимит, успешный вердикт — расходует.

FCT-1002 — одновременные проверки разных чатов:
* доказательства/роли/источники не смешиваются (кроме существующего
  service-level теста — роли и ссылки);
* кэш среза контекста разделён по чату (ключ включает chat_id; запись одного
  чата не читается другим);
* публикуемый payload содержит только whitelist-поля и ссылки ТОЛЬКО
  текущего прогона (нет ev-N/claim_id/role/execution_cause и чужих URL).

Внешние границы (провайдер embeddings, LLM, Telegram, БД-соединение) —
тестовые двойники; проверяемая логика — реальные функции/классы.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from config.settings import settings
from handlers import factcheck as hfc
from services import embedding_control_plane as ecp
from services import factcheck_context as fcx
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_renderer as fr
from services import factcheck_service as fsvc
from services import temporal_factcheck as tf
from services.database import DatabaseService
from services.embedding_control_plane import (
    AdaptiveController,
    EmbeddingExecutor,
    Priority,
    QuotaGroupRegistry,
)
from services.llm_client import LLMError, LLMRateLimitError, LLMServerError
from services.persistent_throttling import PersistentCooldownTracker
from services.smartmodule_throttling import CooldownTracker

CHAT_ID = -100777
CHAT_B = -100778
TARGET_TG = 5000
TRIGGER_TG = 5001
USER_ID = 7

PRIMARY_BASE = "https://apinet.test/v1"
FB1_BASE = "https://generativelanguage.test/v1beta/openai"
FB2_BASE = "https://google-second.test/v1beta/openai"
MODEL = "gemini-embedding-001"


# ═══ FCT-1001: fallback / parking / bounded spend ─══════════════════════════

class ProviderDouble:
    """Тестовый двойник провайдера embeddings на границе `embed_once`."""

    def __init__(self, script, dim=4):
        self._embed_model = MODEL
        self.script = list(script)
        self.calls = []
        self.dim = dim

    async def embed_once(self, texts, *, api_key, base_url=None, model=None,
                         max_retries=0, retry_statuses=()):
        self.calls.append({"key": api_key, "base_url": base_url})
        behavior = self.script.pop(0) if self.script else "ok"
        if behavior == "503":
            raise LLMServerError("LLM server error 503")
        if behavior == "spend429":
            exc = LLMRateLimitError("LLM rate limited (429)")
            exc.headers = {}
            exc.body = ('{"error": {"status": "RESOURCE_EXHAUSTED", '
                        '"message": "spend budget exceeded"}}')
            raise exc
        return [[0.1 + i * 0.01 for i in range(self.dim)] for _ in texts]

    async def embed(self, texts):        # legacy-путь без ключей не ожидается
        raise AssertionError("legacy embed path is not expected")


@pytest.fixture
def ecp_fresh(monkeypatch):
    ecp.REGISTRY = QuotaGroupRegistry()
    ecp.CONTROLLER = AdaptiveController()
    ecp.SCHEDULER = ecp.PriorityScheduler()
    ecp.EXECUTOR = None
    ecp._last_rotation_warn = 0.0
    ecp._last_primary_warn = 0.0
    ecp._last_state_log.clear()
    if hasattr(ecp, "clear_last_served_credential"):
        ecp.clear_last_served_credential()
    monkeypatch.setattr(ecp, "_TRANSPORT_BACKOFF_BASE", 0.0)
    yield ecp


def _isolate(monkeypatch, values):
    def _fake_setting(name, default=""):
        if str(name).startswith("EMBEDDING_"):
            return ""
        return default

    monkeypatch.setattr(
        ecp, "_hot_get", lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(ecp, "_settings_value", _fake_setting)
    monkeypatch.setattr(
        ecp, "_profile_hot",
        lambda key, default="": str(values.get(key, default) or "").strip())
    monkeypatch.setattr(ecp, "_settings_default", _fake_setting)
    from services import hot_config
    monkeypatch.setattr(
        hot_config, "get",
        lambda key, default=None: values.get(key, default))


def _three_legs(monkeypatch, labels=""):
    values = {
        "keys.embedding_api_key": "k-primary",
        "keys.embedding_fallback_api_key": "k-fb1",
        "keys.embedding_fallback_api_key_2": "k-fb2",
        "models.embedding_base_url": PRIMARY_BASE,
        "models.embedding_model_name": MODEL,
        "models.embedding_dim": 4,
        "models.embedding_fallback1_base_url": FB1_BASE,
        "models.embedding_fallback1_model": MODEL,
        "models.embedding_fallback2_base_url": FB2_BASE,
        "models.embedding_fallback2_model": MODEL,
        "keys.embedding_quota_group_labels": labels,
    }
    _isolate(monkeypatch, values)
    return values


@pytest.mark.asap4
class TestFCT1001ProviderFallback:
    """FCT-1001: fallback-нога обслуживает, отказавшая паркуется, успешная
    снимает парковку (существующая семантика P0-EMBED-503-FAILOVER).

    `asap4` — прод-дефолты Embedding Control Plane (group cooldown ON);
    conftest иначе выключает их для старых тестов."""

    @pytest.mark.asyncio
    async def test_failed_leg_is_parked_and_serving_leg_is_healthy(
            self, ecp_fresh, monkeypatch):
        _three_legs(monkeypatch)
        provider = ProviderDouble(["503", "ok"])
        executor = EmbeddingExecutor(provider)

        vectors = await executor.embed(["тезис"], priority=Priority.P1_WRITE)

        assert len(vectors) == 1 and len(vectors[0]) == provider.dim
        assert [c["key"] for c in provider.calls] == ["k-primary", "k-fb1"]
        assert provider.calls[0]["base_url"] == PRIMARY_BASE
        assert provider.calls[1]["base_url"] == FB1_BASE
        # отказавшая нога припаркована в СУЩЕСТВУЮЩЕМ credential_health
        assert ecp.REGISTRY.credential_health("primary") == ecp.HEALTH_COOLDOWN
        assert ecp.REGISTRY.credential_cooldown_until("primary") > 0
        # успешный лег снял парковку: healthy + следующий запрос снова к нему
        assert ecp.REGISTRY.credential_health("fallback_1") == \
            ecp.HEALTH_HEALTHY
        provider.script = ["ok"]
        await executor.embed(["ещё"], priority=Priority.P1_WRITE)
        assert provider.calls[-1]["key"] == "k-fb1"

    @pytest.mark.asyncio
    async def test_all_legs_spend_parked_is_bounded_and_honest(
            self, ecp_fresh, monkeypatch):
        """Все ноги 429 spend (без RA) → kind-парковка с cooldown; повторные
        попытки ограничены пулом; терминал честный, а не бесконечный ретрай."""
        _three_legs(
            monkeypatch,
            "primary:apinet_paid,fallback_1:google_free_1,"
            "fallback_2:google_free_2")
        provider = ProviderDouble(["spend429"] * 5)
        executor = EmbeddingExecutor(provider)

        with pytest.raises(ecp.EmbeddingGroupCoolingDown) as excinfo:
            await executor.embed(["тезис"], priority=Priority.P1_WRITE,
                                 max_wait_s=0.0)

        # ровно одна попытка на каждую независимую ногу — не спин
        assert [c["key"] for c in provider.calls] == \
            ["k-primary", "k-fb1", "k-fb2"]
        assert excinfo.value.next_allowed_at > 0
        for group in ("apinet_paid", "google_free_1", "google_free_2"):
            state = ecp.REGISTRY.group_state(group)
            assert state.state == ecp.GROUP_EXHAUSTED
            assert state.note.startswith("parked kind=")
            assert state.next_allowed_at > 0
        # в окне парковки повтор не делает HTTP (защита от расходов)
        with pytest.raises(ecp.EmbeddingGroupCoolingDown):
            await executor.embed(["тезис"], priority=Priority.P1_WRITE,
                                 max_wait_s=0.0)
        assert len(provider.calls) == 3


    @pytest.mark.asyncio
    async def test_single_leg_transport_backoff_is_bounded(
            self, ecp_fresh, monkeypatch):
        """Backoff сохранён: единственная нога, бюджет ≤4, паузы 1x/2x/4x
        (без нелинейного роста и без бесконечного ретрая)."""
        _isolate(monkeypatch, {
            "keys.embedding_api_key": "k-only",
            "models.embedding_base_url": PRIMARY_BASE,
            "models.embedding_model_name": MODEL,
            "models.embedding_dim": 4,
        })
        monkeypatch.setattr(ecp, "_TRANSPORT_BACKOFF_BASE", 0.01)
        sleeps = []
        real_sleep = asyncio.sleep

        async def _fake_sleep(delay, *args, **kwargs):
            sleeps.append(delay)
            await real_sleep(0)

        monkeypatch.setattr(ecp.asyncio, "sleep", _fake_sleep)
        provider = ProviderDouble(["503"] * 5)
        executor = EmbeddingExecutor(provider)

        with pytest.raises(ecp.EmbeddingBudgetExhausted):
            await executor.embed(["тезис"], priority=Priority.P1_WRITE)

        assert len(provider.calls) == ecp._ATTEMPT_BUDGET
        assert sleeps == [pytest.approx(0.01), pytest.approx(0.02),
                          pytest.approx(0.04)]
        assert max(sleeps) <= ecp._TRANSPORT_BACKOFF_CAP


class TestFCT1001CooperativeCancel:
    """FCT-1001: кооперативная отмена не оставляет задач и не списывает
    пользовательский лимит."""

    @pytest.fixture
    def handler_env(self, monkeypatch):
        monkeypatch.setattr(hfc, "_temporal_on", lambda: False)
        monkeypatch.setattr(hfc, "_pipeline_v2_enabled", lambda: False)
        monkeypatch.setattr(hfc, "get_smart_cache", lambda: _FakeCache())
        old_db, old_service = hfc._db, hfc._service
        old_cooldown = hfc._cooldown
        hfc._cooldown = CooldownTracker(300.0)
        yield
        hfc._db, hfc._service = old_db, old_service
        hfc._cooldown = old_cooldown

    @pytest.fixture(autouse=True)
    def gate_on(self):
        olds = (
            getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False),
            getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False),
        )
        object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", True)
        object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", True)
        yield
        object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", olds[0])
        object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                           olds[1])

    @pytest.mark.asyncio
    async def test_cancelled_check_stops_and_refunds_user_limit(
            self, handler_env):
        started = asyncio.Event()

        async def _hang(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()        # отменяется снаружи
            return "не должно дойти"

        service = _verdict_service()
        service.check_claim = _hang
        hfc._db = _FakeDB(_background())
        hfc.setup_factcheck(service)
        bot = _bot()

        task = asyncio.create_task(
            hfc.factcheck_handler(_trigger(TARGET_TG), bot=bot))
        await asyncio.wait_for(started.wait(), timeout=5)
        assert hfc._cooldown.remaining(CHAT_ID, USER_ID) > 0   # слот занят
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Отмена не доставила вердикт → пользовательский лимит не израсходован
        assert hfc._cooldown.remaining(CHAT_ID, USER_ID) == 0
        # «Вечных» задач не осталось (кроме текущей теста)
        pending = [t for t in asyncio.all_tasks() if not t.done()]
        assert pending == [asyncio.current_task()]

    @pytest.mark.asyncio
    async def test_cancel_before_slot_is_claimed_keeps_no_state(
            self, handler_env, monkeypatch):
        """Отмена до допуска (пустая цель) не создаёт и не снимает слот."""
        service = _verdict_service()
        hfc._db = None
        hfc.setup_factcheck(service)
        bot = _bot()
        empty = _msg(text=None, message_id=TARGET_TG)
        msg = _msg(text="фактчек", message_id=TRIGGER_TG,
                   reply_to_message=empty)
        hfc._cooldown._last.clear()
        await hfc.factcheck_handler(msg, bot=bot)
        assert hfc._cooldown.remaining(CHAT_ID, USER_ID) == 0


class TestFCT1001SingleFlight:
    """FCT-1001: два одновременных одинаковых запроса не удваивают платный
    вызов и расход (прод-путь персистентного кулдауна)."""

    @pytest.mark.asyncio
    async def test_persistent_tracker_does_not_double_provider_call(
            self, tmp_path, monkeypatch):
        db = DatabaseService(str(tmp_path / "fct1001.db"))
        await db.initialize()
        try:
            import services.persistent_throttling as pt
            barrier_db = _BarrierDB(db)
            monkeypatch.setattr(
                hfc, "_cooldown",
                PersistentCooldownTracker(300.0, "factcheck", barrier_db))
            monkeypatch.setattr(hfc, "_temporal_on", lambda: False)
            monkeypatch.setattr(hfc, "_pipeline_v2_enabled", lambda: False)
            monkeypatch.setattr(hfc, "get_smart_cache", lambda: _FakeCache())
            monkeypatch.setattr(
                pt.hot, "get", lambda key, default=None: default)

            started = asyncio.Event()
            release = asyncio.Event()

            async def _slow(*args, **kwargs):
                started.set()
                await release.wait()
                return "проверил: тезис не подтверждается"

            service = _verdict_service()
            from unittest.mock import AsyncMock
            service.check_claim = AsyncMock(side_effect=_slow)
            hfc._db = None
            hfc._service = service
            hfc._cooldown._cooldown = 300.0
            bot = _bot()

            first = asyncio.create_task(
                hfc.factcheck_handler(_trigger(TARGET_TG), bot=bot))
            second = asyncio.create_task(
                hfc.factcheck_handler(_trigger(TARGET_TG + 100), bot=bot))
            await asyncio.wait_for(started.wait(), timeout=5)
            release.set()
            await asyncio.gather(first, second)

            assert service.check_claim.await_count == 1
            # Второй запрос получил троттлинг-фразу, а не второй вердикт.
            assert any(
                "мин" in str(call.args[1]) or "сек" in str(call.args[1])
                for call in bot.send_message.await_args_list)
        finally:
            await db.close()


class TestFCT1001LimitAccounting:
    """FCT-1001: ранний/технический отказ не расходует лимит; вердикт — да."""

    @pytest.fixture
    def handler_env(self, monkeypatch):
        monkeypatch.setattr(hfc, "_temporal_on", lambda: False)
        monkeypatch.setattr(hfc, "_pipeline_v2_enabled", lambda: False)
        monkeypatch.setattr(hfc, "get_smart_cache", lambda: _FakeCache())
        old_db, old_service = hfc._db, hfc._service
        old_cooldown = hfc._cooldown
        hfc._cooldown = CooldownTracker(300.0)
        yield
        hfc._db, hfc._service = old_db, old_service
        hfc._cooldown = old_cooldown

    @pytest.fixture(autouse=True)
    def gate_on(self):
        olds = (
            getattr(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", False),
            getattr(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", False),
        )
        object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", True)
        object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED", True)
        yield
        object.__setattr__(settings, "FACTCHECK_WIDE_CONTEXT_ENABLED", olds[0])
        object.__setattr__(settings, "FACTCHECK_SUITABILITY_GATE_ENABLED",
                           olds[1])

    @pytest.mark.asyncio
    async def test_technical_error_refunds_and_verdict_keeps(
            self, handler_env):
        hfc._db = _FakeDB(_background())

        failing = _verdict_service()
        failing.check_claim = _raise_llm_error
        hfc.setup_factcheck(failing)
        bot = _bot()
        await hfc.factcheck_handler(_trigger(TARGET_TG), bot=bot)
        assert hfc._cooldown.remaining(CHAT_ID, USER_ID) == 0

        ok = _verdict_service()
        hfc.setup_factcheck(ok)
        hfc._cooldown._last.clear()
        await hfc.factcheck_handler(_trigger(TARGET_TG + 10), bot=bot)
        assert ok.check_claim.await_count == 1
        assert hfc._cooldown.remaining(CHAT_ID, USER_ID) > 0


# ═══ FCT-1002: изоляция одновременных проверок разных чатов ═════════════════

class TestFCT1002ChatIsolation:
    @pytest.mark.asyncio
    async def test_roles_and_sources_do_not_mix_between_chats(self):
        claim_a = "Индекс S&P 500 упал на 2,1%."
        claim_b = "Nasdaq потерял 3,4%."
        url_a, url_b = "https://example.org/a", "https://example.org/b"

        coverage_a = _coverage(
            _claim_unit(claim_a, "c1"), outcome=fsp.CLAIM_OUTCOME_CONFIRMED,
            role="supports", evidence_id="ev-a", url=url_a)
        coverage_b = _coverage(
            _claim_unit(claim_b, "c1"), outcome=fsp.CLAIM_OUTCOME_REFUTED,
            role="contradicts", evidence_id="ev-b", url=url_b)
        retrieval_a = _retrieval(coverage_a, "ev-a", url_a, claim_a)
        retrieval_b = _retrieval(coverage_b, "ev-b", url_b, claim_b)

        service_a = fsvc.FactCheckService(aggregator=None, llm=_scripted_llm({
            "factual_verdict": "supported", "temporal_status": "current",
            "parts": [{"part_id": "c1", "text": claim_a,
                       "factual_verdict": "supported",
                       "evidence_refs": ["ev-a"]}]}))
        service_b = fsvc.FactCheckService(aggregator=None, llm=_scripted_llm({
            "factual_verdict": "refuted", "temporal_status": "current",
            "parts": [{"part_id": "c1", "text": claim_b,
                       "factual_verdict": "refuted",
                       "evidence_refs": ["ev-b"]}]}))

        run_a, run_b = await asyncio.gather(
            service_a.check_claim_envelope(
                _envelope(claim_a, CHAT_ID), retrieval=retrieval_a),
            service_b.check_claim_envelope(
                _envelope(claim_b, CHAT_B), retrieval=retrieval_b))

        # роль/источник чужого чата не переворачивает вердикт
        assert run_a.verdict.factual_verdict == "supported"
        assert run_b.verdict.factual_verdict == "refuted"
        assert {r["evidence_id"] for r in run_a.evidence_rows} == {"ev-a"}
        assert {r["evidence_id"] for r in run_b.evidence_rows} == {"ev-b"}
        assert run_a.verdict.parts[0]["evidence_refs"] == ["ev-a"]
        assert run_b.verdict.parts[0]["evidence_refs"] == ["ev-b"]
        assert [r["url"] for r in run_a.evidence_rows] == [url_a]
        assert [r["url"] for r in run_b.evidence_rows] == [url_b]
        # тексты частей не смешались
        assert "S&P" in str(run_a.verdict.parts[0]["text"])
        assert "Nasdaq" not in str(run_a.verdict.parts[0]["text"])
        assert "Nasdaq" in str(run_b.verdict.parts[0]["text"])
        assert "S&P" not in str(run_b.verdict.parts[0]["text"])

    def test_slice_cache_key_is_chat_scoped_and_reused_within_chat(self):
        ctx_a = _context(CHAT_ID, text="тезис чата A")
        ctx_b = _context(CHAT_B, text="тезис чата B")
        key_a = fcx.slice_cache_key(
            ctx_a, before=10, after=10, claim_text="тезис чата A")
        key_b = fcx.slice_cache_key(
            ctx_b, before=10, after=10, claim_text="тезис чата B")
        assert key_a and key_b and key_a != key_b

    @pytest.mark.asyncio
    async def test_slice_cache_never_serves_another_chat(self):
        cache = _FakeCache()
        ctx_a = _context(CHAT_ID, text="тезис чата A")
        ctx_b = _context(CHAT_B, text="тезис чата B")
        assert await fcx.write_slice_cache(
            cache, ctx_a, before=10, after=10, claim_text="тезис чата A")
        # другой чат с тем же окном/предметом не читает чужой срез
        assert await fcx.read_slice_cache(
            cache, ctx_b, before=10, after=10,
            claim_text="тезис чата A") is None
        hit = await fcx.read_slice_cache(
            cache, ctx_a, before=10, after=10, claim_text="тезис чата A")
        assert hit is not None
        assert hit.messages == ctx_a.messages

    def test_published_payload_has_no_internal_fields_or_foreign_links(self):
        url_a, url_b = "https://a.example/x", "https://b.example/y"
        verdict_a = _checked(
            "Вывод по чату A.", "ev-a", url_a, cause="rate_limit",
            part={"part_id": "c1", "text": "Тезис A",
                  "factual_verdict": "supported", "evidence_refs": ["ev-a"]})
        verdict_b = _checked(
            "Вывод по чату B.", "ev-b", url_b, cause="provider_timeout",
            part={"part_id": "c1", "text": "Тезис B",
                  "factual_verdict": "supported", "evidence_refs": ["ev-b"]})

        rendered = {}
        for key, verdict in (("a", verdict_a), ("b", verdict_b)):
            presentation = orch.build_presentation(verdict)
            text = fr.render_factcheck(presentation, verdict).text
            rendered[key] = (fr.visible_text(text), presentation)

        visible_a, pres_a = rendered["a"]
        visible_b, pres_b = rendered["b"]
        assert pres_a.links == (url_a,)
        assert pres_b.links == (url_b,)
        # рендер печатает хост источника; чужого хоста быть не может
        assert "a.example" in visible_a and "b.example" not in visible_a
        assert "b.example" in visible_b and "a.example" not in visible_b
        # закрытые служебные поля не уходят участникам
        for token in ("ev-a", "ev-b", "claim_id", "rate_limit",
                      "provider_timeout", "supports", "contradicts"):
            assert token not in visible_a
            assert token not in visible_b


# ── общие двойники/хелперы ─────────────────────────────────────────────────

def _bot():
    from unittest.mock import AsyncMock
    bot = AsyncMock()
    return bot


class _FakeCache:
    def __init__(self):
        self.store = {}

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.store.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store[key] = payload


class _FakeDB:
    def __init__(self, rows):
        self._rows = list(rows)

    async def get_messages_around(self, chat_id, target_tg_message_id,
                                  before, after):
        return list(self._rows)

    async def get_recent_messages(self, chat_id, limit):
        return list(self._rows[-limit:]) if limit else []


def _row(i, text, *, tg=None, reply_to=None, author="Вася"):
    return {"id": 100 + i, "user_id": 1, "chat_id": CHAT_ID, "text": text,
            "reply_to_id": reply_to, "timestamp": 1000 + i,
            "media_type": "text", "author_name": author, "is_forward": False,
            "forward_source": None, "tg_message_id": tg}


def _background(count=8):
    return [_row(i, f"болтовня номер {i}", tg=6000 + i) for i in range(count)]


def _msg(text=None, caption=None, message_id=1, user_id=USER_ID,
         reply_to_message=None):
    from unittest.mock import MagicMock
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.message_id = message_id
    msg.chat = MagicMock()
    msg.chat.id = CHAT_ID
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.first_name = "Вася"
    msg.reply_to_message = reply_to_message
    msg.forward_origin = None
    msg.media_group_id = None
    msg.quote = None
    return msg


def _trigger(mid):
    claim = _msg(text="стикер со ссылкой заражает телефон", message_id=mid)
    return _msg(text="фактчек", message_id=mid + 1, reply_to_message=claim)


def _verdict_service(text="проверил: заражение через стикер не подтверждается"):
    from unittest.mock import AsyncMock, MagicMock
    service = MagicMock()
    service.check_claim = AsyncMock(return_value=text)
    service.check_claim_envelope = AsyncMock(
        side_effect=AssertionError("envelope-ветка не ожидалась"))
    service.llm = MagicMock()
    return service


async def _raise_llm_error(*args, **kwargs):
    raise LLMError("provider down")


class _BarrierConn:
    """БД-соединение с детерминированной точкой гонки на чтении слота.

    Обе одновременные проверки сначала ОБЕ читают `last_ts` (старое
    поведение remaining+touch), и только потом пишут. Реальный DatabaseService
    остаётся под прокси; добавляется лишь точка переключения задач."""

    def __init__(self, conn, waiters=2):
        self._conn = conn
        self._waiters = waiters
        self._seen = 0
        self._gate = asyncio.Event()

    async def execute(self, sql, *args, **kwargs):
        if "SELECT last_ts" in str(sql):
            self._seen += 1
            if self._seen >= self._waiters:
                self._gate.set()
            await self._gate.wait()
        return await self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _BarrierDB:
    def __init__(self, db):
        self._db = db
        self.db = _BarrierConn(db.db)

    def __getattr__(self, name):
        return getattr(self._db, name)


# ── FCT-1002 service-level helpers ─────────────────────────────────────────

def _claim_unit(text, claim_id="c1"):
    return fsp.ClaimUnit(claim_id=claim_id, text=text)


def _coverage(claim, *, outcome, role, evidence_id, url):
    evidence = fsp.ClaimEvidence(
        claim_id=claim.claim_id, evidence_id=evidence_id, url=url,
        role=role, strength="direct", opened=True, basis=("entity",),
        snippet_only=False, independent=True, published_at_source="page",
        date_status="known")
    return fsp.ClaimCoverage(
        claim=claim, search_status="source_read", status_detail="",
        outcome=outcome, reason_code="", gap_note="", evidence=(evidence,),
        citation_ids=(evidence_id,))


def _retrieval(coverage, evidence_id, url, support):
    ref = fsp.EvidenceRef(evidence_id=evidence_id, url=url, support=support,
                          claims=(coverage.claim.claim_id,))
    return fsp.RetrievalOutcome(
        evidence_map=fsp.EvidenceMap(refs=(ref,), allowlist=(evidence_id,)),
        search_text=support, queries_attempted=1, queries_used=1,
        refs_collected=1, fetch_errors=0, budget_exhausted=False,
        claims=(coverage,))


def _envelope(claim, chat_id):
    return tf.TemporalClaimEnvelope(
        claim_id="c1", chat_id=chat_id, target_tg_message_id=7712,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=7713, claim_text=claim, claim_span=None,
        source_type="text", attribution={}, origin_type=None,
        origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="", analysis_as_of=0)


class _ScriptedLLM:
    def __init__(self, verdict):
        self.verdict = verdict

    async def generate(self, messages, **kw):
        step = kw.get("step")
        if step in ("temporal_verdict", "temporal_fallback"):
            return json.dumps(self.verdict, ensure_ascii=False)
        if step == "temporal_validator":
            return json.dumps({"agree": True}, ensure_ascii=False)
        return "Краткий вывод."


def _scripted_llm(verdict):
    return _ScriptedLLM(verdict)


def _context(chat_id, *, text="тезис"):
    msg = fcx.ContextMessage(
        message_id=1, tg_message_id=100, chat_id=chat_id, author="Вася",
        timestamp=1000, reply_to_tg_id=None, is_forward=False,
        forward_source=None, text=text)
    return fcx.ConversationContext(
        chat_id=chat_id, target_tg_message_id=100, trigger_tg_message_id=101,
        messages=(msg,), window={"before": 10, "after": 10},
        newest_message_id=100)


def _checked(text, evidence_id, url, *, cause, part):
    return orch.CheckedVerdict(
        verdict_text=text, route="v2:envelope_temporal",
        factual_verdict="supported", temporal_status="current",
        evidence=orch.EvidenceMap(
            refs=(orch.EvidenceRef(evidence_id=evidence_id, url=url,
                                   support="выдержка"),),
            allowlist=(evidence_id,)),
        execution_status=orch.EXECUTION_COMPLETE, execution_cause=cause,
        evidence_refs=(evidence_id,), parts=(part,))
