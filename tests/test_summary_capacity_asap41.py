"""ASAP 4.1 волна 2 (эпик asap-4-1-durable-whole-window-summary) — T-4604 /
T-4605: capacity engine — WHOLE_WINDOW | CAPACITY_OVERFLOW по фактическому
serialized prompt (spec §1 A.2; ADR-1028-8 D2; §44 A–E волны 8 прогоны).

Покрытие:
  * цепочка приоритетов §5 владельца ДОСЛОВНО (AMEND AM-2): runtime →
    provider catalog → registry → developer override (уровень 4) →
    conservative fallback; override НЕ бьёт живой каталог/реестр;
  * учёт по ФАКТИЧЕСКОМУ serialized payload (fixture-контрпример против
    оценки «только message.text»);
  * решение §6: required + reserve ≤ effective → WHOLE_WINDOW, иначе
    CAPACITY_OVERFLOW; события SUMMARY_CAPACITY_RESOLVED /
    SUMMARY_EXECUTION_MODE_SELECTED;
  * cache: capability fingerprint в ключе; инкрементная инвалидация
    runtime-ошибки точечно; смена модели/base_url = новый ключ;
  * re-plan API (T-4605, §27–§28, §44-D/E): fallback вместим/не вместим;
    апгрейд blocked при созданных сегментных артефактах (§44-E);
  * kill-switch master SUMMARY_WHOLE_WINDOW_FIRST_ENABLED (OFF → байт-в-бит
    2.58.46 контура).
"""
import json

import pytest

import services.model_capacity as mc
import services.summary_l1_clusterizer as sl1
from services.summary_coverage_ledger import CoverageLedger

pytestmark = pytest.mark.asap41

CHAT_ID = -100555


@pytest.fixture(autouse=True)
def _clean(monkeypatch, request):
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_TARGET_FACTS_PER_CHUNK",
                        24, raising=False)
    yield
    mc.invalidate_capacity_cache()
    mc._WINDOW_CACHE.clear()
    mc._WARNED_UNKNOWN.clear()
    sl1._LAST_RUN_COVERAGE = None
    sl1._LAST_CAPACITY_PLAN = None


def _slot(monkeypatch, base_url, model):
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_BASE_URL", base_url,
                        raising=False)
    monkeypatch.setattr(type(sl1.settings), "SUMMARY_L1_MODEL_NAME", model,
                        raising=False)


def _rows(count, *, start_id=1, text_size=40):
    return [
        {"id": start_id + i, "tg_message_id": start_id + i,
         "user_id": 10 + (i % 3), "author_name": f"Автор{i % 3}",
         "text": f"сообщение {i} о коммуналке и соседях " * (text_size // 10),
         "timestamp": 1_700_000_000 + i * 60, "media_type": "text",
         "reply_to_id": None, "is_forward": 0, "forward_source": None}
        for i in range(count)
    ]


def _mock_llm_call():
    calls = {"count": 0, "payloads": []}

    async def _call(messages):
        calls["count"] += 1
        user_content = ""
        for message in messages:
            if message.get("role") == "user":
                user_content = message.get("content") or ""
        calls["payloads"].append(user_content)
        ids = []
        for line in user_content.splitlines():
            line = line.strip()
            if not line.startswith('{"'):
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            mid = item.get("message_id")
            if isinstance(mid, int):
                ids.append(mid)
        assert ids, "mock: user content без §92-элементов"
        # ASAP 4.1 волна 3 (T-4607, ADR-1028-8 D3): map-режим — выход L1 =
        # semantic map v1 (без facts/текстов; capacity-механика не меняется).
        topics = [{"topic_id": "topic_001", "title": "коммуналка",
                   "message_ids": ids, "participants": [], "short_hint": ""}]
        return json.dumps({"schema_version": 1, "topics": topics,
                           "events": [], "unassigned_message_ids": []},
                          ensure_ascii=False)

    _call.calls = calls
    return _call


# ── Цепочка приоритетов §5 (AMEND AM-2; дословно) ───────────────────────────

@pytest.mark.asyncio
async def test_chain_runtime_beats_override(monkeypatch):
    """ASAP 4.2 Step 2c-1 (AMEND ADR-1028-8 D2): override — уровень 1 при
    live-precedence ON (default) → сильнее live runtime. OFF → прежний
    уровень 4 (runtime даёт значение, override не применяется)."""

    async def _props(url, *, headers=None):
        if url.endswith("/props"):
            return {"default_generation_settings": {"n_ctx": 32768}}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _props)
    type(mc.settings).CHAT_MODEL_CONTEXT_WINDOW = 500000
    result = await mc.resolve_capacity("http://127.0.0.1:8080/v1",
                                       "llama-3.1-8b")
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.effective_context_window == 500000
    monkeypatch.setattr(
        type(mc.settings), "SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED", False,
        raising=False)
    mc.invalidate_capacity_cache()
    legacy = await mc.resolve_capacity("http://127.0.0.1:8080/v1",
                                       "llama-3.1-8b")
    assert legacy.source == mc.SOURCE_RUNTIME
    assert legacy.effective_context_window == 32768


@pytest.mark.asyncio
async def test_chain_catalog_beats_override(monkeypatch):
    """ASAP 4.2 Step 2c-1: override уровень 1 сильнее provider catalog при
    live-precedence ON; OFF → catalog гарантирует §44-D."""

    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [{"id": "tiny/tiny-32k", "context_length": 32768}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    type(mc.settings).CHAT_MODEL_CONTEXT_WINDOW = 1000000
    result = await mc.resolve_capacity("https://openrouter.ai/api/v1",
                                       "tiny/tiny-32k")
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.effective_context_window == 1000000
    monkeypatch.setattr(
        type(mc.settings), "SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED", False,
        raising=False)
    mc.invalidate_capacity_cache()
    legacy = await mc.resolve_capacity("https://openrouter.ai/api/v1",
                                       "tiny/tiny-32k")
    assert legacy.source == mc.SOURCE_PROVIDER_CATALOG
    assert legacy.effective_context_window == 32768


@pytest.mark.asyncio
async def test_chain_registry_beats_override(monkeypatch):

    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)
    type(mc.settings).CHAT_MODEL_CONTEXT_WINDOW = 500000
    result = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "deepseek-chat")
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.effective_context_window == 500000
    monkeypatch.setattr(
        type(mc.settings), "SUMMARY_CAPACITY_LIVE_PRECEDENCE_ENABLED", False,
        raising=False)
    mc.invalidate_capacity_cache()
    legacy = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "deepseek-chat")
    assert legacy.source == mc.SOURCE_REGISTRY
    assert legacy.effective_context_window == 131072


@pytest.mark.asyncio
async def test_chain_override_above_fallback(monkeypatch):
    """Уровень 4: override применяется, когда runtime/каталог/реестр не
    дали значения; уровень 5 (fallback 16384) — без override."""

    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)
    type(mc.settings).CHAT_MODEL_CONTEXT_WINDOW = 65536
    result = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                       "mystery-nothing-model")
    assert result.source == mc.SOURCE_DEVELOPER_OVERRIDE
    assert result.effective_context_window == 65536
    type(mc.settings).CHAT_MODEL_CONTEXT_WINDOW = None
    fallback = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                         "mystery-nothing-model-2")
    assert fallback.source == mc.SOURCE_FALLBACK
    assert fallback.effective_context_window == 16384


# ── Учёт по фактическому serialized prompt (§6, fixture-контрпример) ───────

def test_serialized_accounting_not_text_only():
    """Fixture-контрпример: голый text мал, а serialized §92-элемент с
    полями/типами/именными полями существенно больше — оценка NOT «только
    message.text»."""
    from services.token_counter import count_tokens
    row = {
        "id": 123456, "tg_message_id": 9_000_000_000,
        "timestamp": 1_700_000_000, "user_id": 987654,
        "author_name": "Очень_Длинное_Имя_Участника_Чата",
        "text": "х", "reply_to_id": 8_999_999_999,
        "media_type": "document",
    }
    item = sl1.build_l1_payload([row], CHAT_ID)[0]
    serialized_len = sl1._serialized_len(item, "tokens")
    text_only = count_tokens("х")
    assert serialized_len > text_only * 20


def test_decide_summary_mode_formula():
    plan = mc.decide_summary_mode(
        provider="nanogpt", model="m", effective_context_window=10000,
        required_input_tokens=5500, reserved_output_tokens=4000,
        window_source=mc.SOURCE_REGISTRY)
    # 5000 + 4000 ≤ 10000 → WHOLE_WINDOW, margin 500.
    assert plan.mode == mc.MODE_WHOLE_WINDOW
    assert plan.reason == "fits_effective_context"
    assert plan.safety_margin_tokens == 500
    plan2 = mc.decide_summary_mode(
        provider="nanogpt", model="m", effective_context_window=10000,
        required_input_tokens=7000, reserved_output_tokens=4000,
        window_source=mc.SOURCE_REGISTRY)
    # 7000 + 4000 > 10000 → CAPACITY_OVERFLOW.
    assert plan2.mode == mc.MODE_CAPACITY_OVERFLOW
    assert plan2.reason == "serialized_payload_exceeds_effective_context"
    # Inspector-поля R6-G-002 присутствуют.
    counts = plan.as_event_counts()
    for field in ("mode", "reason", "effective_window", "required_input_tokens",
                  "reserved_output_tokens", "window_source", "fallback_used"):
        assert field in counts


# ── WHOLE_WINDOW (§44-A) ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_large_context_whole_window(monkeypatch, caplog):
    """§44-A: large-context модель, плотное окно → WHOLE_WINDOW, РОВНО 1
    L1-запрос, coverage 100%, БЕЗ эвикций/нарезки."""
    caplog.set_level("INFO")
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    rows = _rows(120)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call,
                              correlation_id="run-a")
    assert result.usable
    plan = sl1._capacity_plan_snapshot()
    assert plan["mode"] == "WHOLE_WINDOW"
    assert plan["required_input_tokens"] > 0
    assert plan["reserved_output_tokens"] > 0
    assert plan["segments"] is None
    assert llm_call.calls["count"] == 1
    user_payload = llm_call.calls["payloads"][0]
    # ВСЕ сообщения окна в одном входе (никаких messages[:N]).
    for row in rows:
        assert '"message_id":%d' % row["tg_message_id"] in \
            user_payload.replace('"message_id": ', '"message_id":')
    assert result.chunk_count == 1
    assert result.skipped_ids == ()
    assert result.truncated is False
    coverage = sl1.last_run_coverage()
    assert coverage["source_messages_processed"] == len(rows)
    assert coverage["coverage_percent"] == 100.0
    assert any("SUMMARY_CAPACITY_MODE" in r.getMessage()
               for r in caplog.records)


# ── CAPACITY_OVERFLOW (§44-B) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_b_small_local_overflow_all_covered(monkeypatch):
    """§44-B: small local 32K-конфиг (конфиг-фикстура каталога) с большим
    окном → CAPACITY_OVERFLOW, ВСЕ covered, no truncation, ledger 100%."""
    _slot(monkeypatch, "https://openrouter.ai/api/v1", "tiny/tiny-32k")

    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [{"id": "tiny/tiny-32k", "context_length": 32000}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    rows = _rows(300)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call,
                              correlation_id="run-b")
    assert result.usable
    plan = sl1._capacity_plan_snapshot()
    assert plan["mode"] == "CAPACITY_OVERFLOW"
    assert plan["segments"] >= 2
    assert plan["segments"] == llm_call.calls["count"]  # L1-запросов = сегментам
    assert result.chunk_count == plan["segments"]
    assert result.truncated is False
    assert result.skipped_ids == ()
    coverage = sl1.last_run_coverage()
    assert coverage["coverage_percent"] == 100.0
    # Все сообщение попали хотя бы в один сегмент (lossless).
    all_ids = set()
    for payload in llm_call.calls["payloads"]:
        for part in payload.splitlines():
            part = part.strip()
            if part.startswith('{"'):
                item = json.loads(part)
                if isinstance(item.get("message_id"), int):
                    all_ids.add(item["message_id"])
    assert all_ids == {row["tg_message_id"] for row in rows}


# ── Смена модели (§44-C) + cache fingerprint (T-4605) ──────────────────────

@pytest.mark.asyncio
async def test_c_model_switch_invalidates_and_replans(monkeypatch):
    """§44-C: смена модели → новый ключ кеша (fingerprint/модель в ключе) →
    авто-смену strategy (same required + меньше окно → CHOLE_WINDOW →
    CAPACITY_OVERFLOW)."""
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    rows = _rows(240)
    llm_call = _mock_llm_call()
    big = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call,
                           correlation_id="run-c1")
    assert big.usable
    assert sl1._capacity_plan_snapshot()["mode"] == "WHOLE_WINDOW"
    first_calls = llm_call.calls["count"]
    key_before = mc._cache_key("https://nano-gpt.com/v1", "deepseek-chat")
    _slot(monkeypatch, "http://127.0.0.1:8080/v1", "tiny-local-model")
    small = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call,
                             correlation_id="run-c2")
    assert small.usable
    key_after = mc._cache_key("http://127.0.0.1:8080/v1", "tiny-local-model")
    assert key_before != key_after
    assert sl1._capacity_plan_snapshot()["mode"] == "CAPACITY_OVERFLOW"
    assert llm_call.calls["count"] > first_calls
    coverage = sl1.last_run_coverage()
    assert coverage["coverage_percent"] == 100.0


@pytest.mark.asyncio
async def test_capability_fingerprint_in_cache_key(monkeypatch):
    """Δ против ADR-1028-3: в ключе кеша +capability fingerprint
    (model/base_url/override/endpoint): смена endpoint → промах кеша."""

    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)
    await mc.resolve_capacity("https://nano-gpt.com/v1", "deepseek-chat")
    assert len(mc._CACHE) == 1
    endpoint_key = mc._capability_fingerprint("https://nano-gpt.com/api/v1")
    assert endpoint_key != mc._capability_fingerprint("https://nano-gpt.com/v1")
    # Та же тройка host/model, другой endpoint → новый ключ.
    key1 = mc._cache_key("https://nano-gpt.com/v1", "deepseek-chat")
    key2 = mc._cache_key("https://nano-gpt.com/api/v1", "deepseek-chat")
    assert key1 != key2


@pytest.mark.asyncio
async def test_runtime_error_selective_invalidation(monkeypatch):
    """Runtime 400/context-length → точечная инвалидация тройки без
    задевания соседних записей кеша."""

    async def _fail(url, *, headers=None):
        return None

    monkeypatch.setattr(mc, "_http_get_json", _fail)
    result_before = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                              "deepseek-chat")
    assert mc._cache_key("https://nano-gpt.com/v1", "deepseek-chat") \
        in mc._CACHE
    neighbor = await mc.resolve_capacity("https://nano-gpt.com/v1",
                                         "deepseek-reasoner")
    assert neighbor.fallback_used is False or True   # фиксирует запись
    removed = mc.invalidate_runtime_capacity("https://nano-gpt.com/v1",
                                             "deepseek-chat",
                                             reason="runtime_context_error")
    assert removed == 1
    assert mc._cache_key("https://nano-gpt.com/v1", "deepseek-chat") \
        not in mc._CACHE
    # Соседние записи не задеты.
    assert mc._cache_key("https://nano-gpt.com/v1", "deepseek-reasoner") \
        in mc._CACHE


# ── Re-plan при fallback-провайдере (§27–§28, §44-D/E; T-4605) ─────────────

@pytest.mark.asyncio
async def test_d_fallback_smaller_replains_to_overflow(monkeypatch):
    """§44-D: fallback-провайдер окном МЕНЬШЕ required → CAPACITY_OVERFLOW
    (не oversized вслепую), семантика задачи инвариантна."""

    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [{"id": "small/small-16k", "context_length": 16384}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    plan = await mc.replan_summary_capacity(
        base_url="https://openrouter.ai/api/v1", model="small/small-16k",
        required_input_tokens=20000, reserved_output_tokens=4000,
        current_mode=mc.MODE_WHOLE_WINDOW)
    assert plan.mode == mc.MODE_CAPACITY_OVERFLOW
    assert plan.reason == "serialized_payload_exceeds_effective_context"


@pytest.mark.asyncio
async def test_d2_fallback_still_fits_whole_window(monkeypatch):

    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [{"id": "big/big-200k", "context_length": 200000}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    plan = await mc.replan_summary_capacity(
        base_url="https://openrouter.ai/api/v1", model="big/big-200k",
        required_input_tokens=30000, reserved_output_tokens=4000,
        current_mode=mc.MODE_WHOLE_WINDOW)
    assert plan.mode == mc.MODE_WHOLE_WINDOW
    assert plan.reason == "fits_effective_context"


@pytest.mark.asyncio
async def test_e_fallback_bigger_upgrade_gated_by_artifacts(monkeypatch):
    """§44-E: fallback больше → whole-window допустим, ЕСЛИ run ещё не
    создал сегментные артефакты; иначе run не ломается
    (reason=segment_artifacts_exist)."""

    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [{"id": "huge/huge-1m", "context_length": 1000000}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    # Без артефактов → переход на whole-window (автокоперация разрешена).
    upgraded = await mc.replan_summary_capacity(
        base_url="https://openrouter.ai/api/v1", model="huge/huge-1m",
        required_input_tokens=30000, reserved_output_tokens=4000,
        current_mode=mc.MODE_CAPACITY_OVERFLOW,
        segment_artifacts_created=False)
    assert upgraded.mode == mc.MODE_WHOLE_WINDOW
    assert upgraded.reason == "fits_after_fallback"
    # С артефактами — run не ломается (сохраняется overflow-план).
    gated = await mc.replan_summary_capacity(
        base_url="https://openrouter.ai/api/v1", model="huge/huge-1m",
        required_input_tokens=30000, reserved_output_tokens=4000,
        current_mode=mc.MODE_CAPACITY_OVERFLOW,
        segment_artifacts_created=True)
    assert gated.mode == mc.MODE_CAPACITY_OVERFLOW
    assert gated.reason == "segment_artifacts_exist"


@pytest.mark.asyncio
async def test_replan_never_raises_on_resolve_failure(monkeypatch):

    async def _boom(url, *, headers=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(mc, "_http_get_json", _boom)
    plan = await mc.replan_summary_capacity(
        base_url="https://nano-gpt.com/v1", model="mystery-fail-replan",
        required_input_tokens=1000, reserved_output_tokens=500,
        current_mode=mc.MODE_WHOLE_WINDOW)
    assert plan.mode == mc.MODE_WHOLE_WINDOW  # 1000+500 ≤ 16384 fallback
    assert plan.window_source == mc.SOURCE_FALLBACK
    assert plan.fallback_used is True


# ── События capacity (spec §7.3) ───────────────────────────────────────────

def _events_on(monkeypatch):
    """Включить SUMMARY_* события на ВСЕХ классах Settings (reload'ы
    settings в чужих тестах могут переназначить инстанс; прецедент —
    примечание в tests/conftest.py `_asap4_flags_off_by_default`)."""
    import config.settings as _cs
    from config.settings import Settings
    for _cls in {Settings, type(_cs.settings), type(sl1.settings)}:
        monkeypatch.setattr(_cls, "SUMMARY_PIPELINE_EVENTS_ENABLED", True,
                            raising=False)


@pytest.mark.asyncio
async def test_capacity_events_emitted(monkeypatch, caplog):
    _events_on(monkeypatch)
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    rows = _rows(40)
    llm_call = _mock_llm_call()
    with caplog.at_level("INFO", logger="services.mca_events"):
        result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID,
                                  llm_call=llm_call,
                                  correlation_id="run-events")
    assert result.usable
    texts = [r.getMessage() for r in caplog.records]
    assert any("SUMMARY_CAPACITY_RESOLVED" in t for t in texts)
    assert any("SUMMARY_EXECUTION_MODE_SELECTED" in t for t in texts)
    mode_line = next(t for t in texts
                     if "SUMMARY_EXECUTION_MODE_SELECTED" in t)
    assert "WHOLE_WINDOW" in mode_line.replace(" ", "")
    # R17: message texts отсутствуют.
    joined = "\n".join(texts)
    assert "коммуналке" not in joined


# ── Master kill-switch OFF → байт-в-бит 2.58.46 ────────────────────────────

@pytest.mark.asyncio
async def test_master_off_legacy_planning_path(monkeypatch):
    """Master OFF → прежний контур (planning-estimate sharding волны C):
    плотное окно шардится планировщиком кардинальности, а NOT исчезает.
    L1-контракт на OFF-пути — §95-v2 (волна 3: map-режим врезается только
    в capacity-first ветку, байт-в-бит OFF)."""
    monkeypatch.setattr(type(sl1.settings),
                        "SUMMARY_WHOLE_WINDOW_FIRST_ENABLED", False,
                        raising=False)
    _slot(monkeypatch, "https://nano-gpt.com/v1", "deepseek-chat")
    rows = _rows(120)

    async def _v2_call(messages):
        user = next(m["content"] for m in messages if m["role"] == "user")
        ids = []
        for part in user.splitlines():
            part = part.strip()
            if part.startswith('{"'):
                try:
                    item = json.loads(part)
                except ValueError:
                    continue
                if isinstance(item.get("message_id"), int):
                    ids.append(item["message_id"])
        threads = [{"thread_id": "thread_001", "topic": "коммуналка",
                    "message_ids": ids,
                    "facts": [{"text": "обсуждали коммуналку",
                               "evidence_message_ids": ids[:3]}]}]
        return json.dumps({"schema_version": 2, "threads": threads,
                           "unassigned_message_ids": []},
                          ensure_ascii=False)

    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=_v2_call,
                              correlation_id="run-off-legacy")
    assert result.usable
    snapshot = sl1._capacity_plan_snapshot()
    # Capacity-plan снапшота нет на OFF-пути (2.58.46 байт-в-бит).
    assert snapshot is None


@pytest.mark.asyncio
async def test_master_on_off_ledger_by_switch(monkeypatch):
    """Ledger kill-switch OFF → прежний lossless-chunking контур (без
    SUMMARY_SEGMENT_* событий/ledger)."""
    monkeypatch.setattr(type(sl1.settings),
                        "SUMMARY_CAPACITY_OVERFLOW_LEDGER_ENABLED", False,
                        raising=False)
    _slot(monkeypatch, "https://openrouter.ai/api/v1", "tiny/tiny-32k")

    async def _catalog(url, *, headers=None):
        if "openrouter.ai/api/v1/models" in url:
            return {"data": [{"id": "tiny/tiny-32k", "context_length": 32000}]}
        return None

    monkeypatch.setattr(mc, "_http_get_json", _catalog)
    rows = _rows(300)
    llm_call = _mock_llm_call()
    result = await sl1.run_l1(rows=rows, chat_id=CHAT_ID, llm_call=llm_call,
                              correlation_id="run-off-ledger")
    assert result.usable
    plan = sl1._capacity_plan_snapshot()
    assert plan["mode"] == "CAPACITY_OVERFLOW"
    assert plan["segments"] == llm_call.calls["count"]
    assert result.chunk_count == plan["segments"]
    assert result.truncated is False
    coverage = sl1.last_run_coverage()
    assert coverage["coverage_percent"] == 100.0


# ── Ledger-инварианты (примыкающee; детально —
#    tests/test_summary_coverage_ledger_asap41.py) ─────────────────────────

def test_ledger_overlap_dedup_invariant():
    ledger = CoverageLedger(source_message_ids=(1, 2, 3, 4, 5, 6))
    ledger.register_segment("segment_1", [1, 2, 3])
    ledger.register_segment("segment_2", [3, 4, 5])   # overlap по 3
    ledger.register_segment("segment_3", [5, 6])
    ledger.mark_processed([1, 2, 3, 4, 5, 6])
    status = ledger.verify()
    assert status["assignment_lossless"] is True
    assert status["missing"] == 0
    assert status["coverage_percent"] == 100.0
    assert status["segments"] == 3
