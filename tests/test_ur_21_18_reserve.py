"""UR-21.18 (model-aware Direct reserve) + UR-RES-03 (read-only anti-cycle).

Дискриминирующие проверки замороженного контракта Architect `710f8e223`:
только `direct.primary`/`direct.fallback` считают резерв от физического
`max_output` модели; ratio остаётся fallback-путём; Summary/intel не
меняются. UR-RES-03 добавляет read-only `repetition` в существующую
diagnostics и одно production-событие, не меняя лимиты.

Строки остаются PENDING до независимого ревью; VERIFIED здесь не заявляется.
"""
import pytest

import services.auto_budget as ab
import services.direct_chat_service as dcs
import services.model_capacity as mc
from services import direct_context_composer as comp
from services import hot_config as hot
from services import style_policy as sp
from tests.test_direct_chat import FakeMemory, _make_service, _message
from tests.test_ur_c_3_real_fts import (
    ADDRESSEE, BOT_UID, CHAT, _db, _global_parts, _row, _stub_episodes,
)
from tests.test_ur_d_writer import _MetadataLLM, _completion

pytestmark = [pytest.mark.asap3, pytest.mark.asap31, pytest.mark.asap32]

BASE_URL = "https://nano-gpt.com/api/v1"
MODEL = "deepseek-chat"


@pytest.fixture(autouse=True)
def _clean_capacity(monkeypatch):
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    hot.set_config_cache(None)

    async def _no_network(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _no_network)
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    hot.set_config_cache(None)
    sp.reset_repetition_state()


def _catalog(monkeypatch, *, context_length=131072, max_output=8192):
    async def _json(url, *, headers=None):
        return {"data": [{"id": MODEL, "context_length": context_length,
                          "max_output_tokens": max_output}]}

    monkeypatch.setattr(mc, "_http_get_json", _json)
    mc.invalidate_capacity_cache()


def _ratio(monkeypatch, value):
    def _get(key, default=None):
        if key == "limits.chat_budget_reserve_ratio":
            return value
        return default

    monkeypatch.setattr(hot, "get", _get)


# ── UR-21.18: формула, cap, fallback, switch OFF ────────────────────────────

@pytest.mark.asyncio
async def test_capability_reserve_and_source(monkeypatch):
    _catalog(monkeypatch)
    _ratio(monkeypatch, 0.5)
    result = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        mandatory_tokens=1000, reserve_target_tokens=4096)
    assert result.output_reserve == 4352          # 4096 + 256
    assert result.output_reserve_source == "model_capability"
    assert result.model_max_output_tokens == 8192
    assert result.reserve_target_tokens == 4096
    fields = result.as_event_fields()
    assert fields["output_reserve_source"] == "model_capability"
    assert fields["model_max_output_tokens"] == 8192
    assert fields["reserve_target_tokens"] == 4096


@pytest.mark.asyncio
async def test_capability_reserve_ignores_ratio_value(monkeypatch):
    """При известном max_output доля не участвует в резерве."""
    _catalog(monkeypatch)
    _ratio(monkeypatch, 0.02)
    low = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        reserve_target_tokens=4096)
    _ratio(monkeypatch, 0.5)
    high = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        reserve_target_tokens=4096)
    assert low.output_reserve == high.output_reserve == 4352
    assert low.output_reserve_source == high.output_reserve_source == \
        "model_capability"


@pytest.mark.asyncio
async def test_reserve_is_capped_by_model_max(monkeypatch):
    _catalog(monkeypatch, max_output=2048)
    result = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        reserve_target_tokens=4096)
    assert result.output_reserve == 2048
    assert result.output_reserve <= (result.model_max_output_tokens or 0)
    assert result.output_reserve_source == "model_capability"


@pytest.mark.asyncio
async def test_caller_max_tokens_still_wins(monkeypatch):
    _catalog(monkeypatch)
    result = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        max_output_tokens=2048, reserve_target_tokens=4096)
    assert result.output_reserve == 2048
    assert result.output_reserve_source == "caller_max_output"
    assert result.reserve_target_tokens is None


@pytest.mark.asyncio
async def test_unknown_model_max_falls_back_to_ratio(monkeypatch):
    """Нет max-output metadata → прежняя ratio-формула (13107)."""
    _ratio(monkeypatch, 0.10)
    result = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        mandatory_tokens=12400, reserve_target_tokens=4096)
    assert result.output_reserve == 13107
    assert result.output_reserve_source == "ratio_fallback"
    assert result.model_max_output_tokens is None


@pytest.mark.asyncio
async def test_switch_off_restores_ratio_with_known_max(monkeypatch):
    _catalog(monkeypatch)
    monkeypatch.setattr(type(ab.settings),
                        "DIRECT_RESERVE_MODEL_AWARE_ENABLED", False,
                        raising=False)
    result = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        reserve_target_tokens=4096)
    assert result.output_reserve == 13107
    assert result.output_reserve_source == "ratio_fallback"
    # metadata остаётся наблюдаемой; OFF меняет только формулу.
    assert result.model_max_output_tokens == 8192


@pytest.mark.asyncio
async def test_summary_reserves_are_not_model_aware(monkeypatch):
    _catalog(monkeypatch)
    l1 = await ab.resolve_stage_budget(
        "summary.l1", base_url=BASE_URL, model=MODEL, mandatory_tokens=1085)
    l2 = await ab.resolve_stage_budget(
        "summary.l2", base_url=BASE_URL, model=MODEL, mandatory_tokens=900)
    assert l1.output_reserve == 4000
    assert l2.output_reserve == 6000
    assert l1.output_reserve_source == "stage_env"
    assert l2.output_reserve_source == "stage_env"


@pytest.mark.asyncio
@pytest.mark.parametrize("window", [16384, 131072, 1048576])
@pytest.mark.parametrize("ceiling", [4096, 16384])
async def test_reserve_covers_declared_output_ceiling(
        monkeypatch, window, ceiling):
    _catalog(monkeypatch, context_length=window,
             max_output=max(ceiling, 8192))
    result = await ab.resolve_stage_budget(
        "direct.primary", base_url=BASE_URL, model=MODEL,
        reserve_target_tokens=ceiling)
    assert result.model_max_output_tokens is not None
    assert result.model_max_output_tokens >= ceiling
    assert result.output_reserve >= ceiling, result


@pytest.mark.asyncio
async def test_auto_context_budget_event_exposes_reserve_source(
        monkeypatch, caplog):
    _catalog(monkeypatch)
    with caplog.at_level("INFO", logger="services.agentic_events"):
        await ab.resolve_stage_budget(
            "direct.primary", base_url=BASE_URL, model=MODEL,
            reserve_target_tokens=4096)
    message = next((r.getMessage() for r in caplog.records
                    if "event=AUTO_CONTEXT_BUDGET" in r.getMessage()), "")
    assert "output_reserve_source=model_capability" in message
    assert "model_max_output_tokens=8192" in message
    assert "reserve_target_tokens=4096" in message


# ── UR-21.18: реальный call site + оба DTO/диагностика ──────────────────────

@pytest.mark.asyncio
async def test_direct_call_site_carries_target_and_source(
        tmp_path, monkeypatch):
    _catalog(monkeypatch)
    monkeypatch.setattr(type(ab.settings),
                        "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS", 4096,
                        raising=False)
    comp.reset_diagnostics()
    sp.reset_repetition_state()
    db = await _db(tmp_path, "ur2118.db")
    try:
        window = [_row(i, text=f"свежая реплика {i}")
                  for i in range(1, 4)]
        llm = _MetadataLLM([_completion("ok")], model=MODEL,
                           base_url=BASE_URL)
        llm._fallback_model = "gpt-4"
        llm._fallback_base_url = BASE_URL
        svc = _make_service(memory=FakeMemory(window=window), db=db,
                            llm=llm, bot_id=BOT_UID)
        _stub_episodes(svc, monkeypatch, rows=[])

        async def _external(chat_id, model_window,
                            extra_prompt_blocks=()):
            return 0, 0, "test-estimate"

        monkeypatch.setattr(svc, "_estimate_external_payload_tokens",
                            _external)

        calls: list = []
        real_budget = ab.resolve_stage_budget

        async def _spy(stage, **kwargs):
            calls.append((stage, kwargs.get("reserve_target_tokens")))
            return await real_budget(stage, **kwargs)

        monkeypatch.setattr(dcs._auto_budget, "resolve_stage_budget", _spy)

        emitted: list = []
        real_emit = comp.emit_context_capacity

        def _emit(**kwargs):
            emitted.append(kwargs)
            return real_emit(**kwargs)

        monkeypatch.setattr(dcs._composer, "emit_context_capacity", _emit)
        sp.record_bot_output(CHAT, "фраза для антицикла")

        out: dict = {}
        await svc._compose_user_content(
            chat_id=CHAT, message=_message(text="вопрос", message_id=700),
            blocks=[], chain=[], window=window, roster=[], suffix_map={},
            global_parts=_global_parts(tail_rows=window),
            target_name="Аня", target_user_id=ADDRESSEE,
            trigger_message_id=700, out_excluded=None,
            live_selection=False, out_prepared=out)

        assert ("direct.primary", 4096) in calls, calls
        assert ("direct.fallback", 4096) in calls, calls

        diag = comp.get_diagnostics(CHAT)
        assert diag is not None
        assert diag["output_reserve"] == 4352
        assert diag["output_reserve_source"] == "model_capability"
        assert diag["model_max_output_tokens"] == 8192
        assert diag["reserve_target_tokens"] == 4096
        assert diag["repetition"] == {
            "window": 1, "cap": sp.REPEAT_WINDOW_MAX,
            "ttl_seconds": sp.REPEAT_TTL_SECONDS, "ngram_n": sp.NGRAM_N,
            "source": "style_policy.repeat_window"}
        assert "hashes" not in diag["repetition"]

        budget = out["primary"].budget
        assert budget["output_reserve_source"] == "model_capability"
        assert budget["model_max_output_tokens"] == 8192
        assert budget["reserve_target_tokens"] == 4096

        assert emitted, "CONTEXT_CAPACITY не эмитирован"
        last = emitted[-1]
        assert last["output_reserve_source"] == "model_capability"
        assert last["model_max_output_tokens"] == 8192
        assert last["reserve_target_tokens"] == 4096
        assert last["repetition"]["cap"] == sp.REPEAT_WINDOW_MAX
    finally:
        comp.reset_diagnostics()
        sp.reset_repetition_state()
        await db.close()


# ── UR-RES-03: read-only repetition в diagnostics и production-событии ─────

def test_repetition_diagnostics_is_read_only_numbers():
    sp.reset_repetition_state()
    sp.record_bot_output(CHAT, "фраза для наблюдения")
    data = comp.repetition_diagnostics(CHAT)
    assert data == {
        "window": 1, "cap": sp.REPEAT_WINDOW_MAX,
        "ttl_seconds": sp.REPEAT_TTL_SECONDS, "ngram_n": sp.NGRAM_N,
        "source": "style_policy.repeat_window"}
    assert "hashes" not in data
    assert "фраза" not in str(data)
    sp.reset_repetition_state()


def test_context_capacity_event_carries_repetition(caplog):
    sp.reset_repetition_state()
    sp.record_bot_output(CHAT, "фраза для наблюдения")
    repetition = comp.repetition_diagnostics(CHAT)
    with caplog.at_level("INFO", logger="services.agentic_events"):
        comp.emit_context_capacity(
            model=MODEL, window=131072, window_source="provider_catalog",
            external_tokens=1000, output_reserve=4352,
            available_context=110000, budget=110000, policy_mode="dynamic",
            summary_revision="1:2", summary_watermark=0,
            summary_lag_messages=0, summary_age=0,
            output_reserve_source="model_capability",
            model_max_output_tokens=8192, reserve_target_tokens=4096,
            repetition=repetition)
    message = next((r.getMessage() for r in caplog.records
                    if "event=CONTEXT_CAPACITY" in r.getMessage()), "")
    assert "output_reserve_source=model_capability" in message
    assert "model_max_output_tokens=8192" in message
    assert "reserve_target_tokens=4096" in message
    assert f"repetition_window={repetition['window']}" in message
    assert f"repetition_cap={sp.REPEAT_WINDOW_MAX}" in message
    assert f"repetition_ttl_seconds={sp.REPEAT_TTL_SECONDS}" in message
    assert f"repetition_ngram_n={sp.NGRAM_N}" in message
    assert "repetition_source=style_policy.repeat_window" in message
    assert "фраза" not in message
    sp.reset_repetition_state()


def test_param_catalog_marks_reserve_ratio_as_fallback_legacy():
    from services import param_catalog as pc
    meta = pc.effective_meta("limits.chat_budget_reserve_ratio")
    assert meta["status"] == "legacy"
    assert meta["active_consumer"] == "services.auto_budget (fallback)"
    assert meta["reason_inactive"]
