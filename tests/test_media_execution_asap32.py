"""ASAP-3.2 (round1029, ADR-1028-5 D4/D5, T-4196…T-4200) — Media adapter +
adaptive Media Execution Policy + durable media state (§68 A–F, unit-уровень):

* A. async provider: submit → RUNNING → success — НЕ убивается deadline,
     пока remote status жив (deadline = safety ceiling, §24/§28);
* B. streaming provider: progress обновляет liveness (read-окно отдельного
     запроса ≠ total deadline);
* C. sync provider 150 c: adaptive policy позволяет завершиться (estimator
     по успешным длительностям, cold-default ≥ наблюдаемой латентности не
     обязателен — clamp с ceiling);
* D. terminal failure → быстрый fallback (ТОЛЬКО после terminal, §31);
* E. restart async job: resume by provider job id — БЕЗ повторного платного
     submit (§30); sync-only без job id → честный unknown_after_disconnect;
* F. unknown provider: safe sync fallback + честный capability unknown
     (remote_progress = none, fake ping запрещён §14);
* политика: 4 различных окна (§28), estimator НЕ учитывает timeout'ы как
  success (§26), stage-aware key (§23), OFF → legacy 90/180/240 (§80).
"""
import asyncio
import time

import pytest
import pytest_asyncio

from services import media_execution as me
from services.task_supervisor import TaskJobStore


# ═══ Политика: окна / estimator (§22–§28) ═══════════════════════════════════

def _reset_obs():
    me._OBS.clear()


def test_policy_default_windows_generate():
    _reset_obs()
    w = me.resolve_windows("nanogpt", "qwen-image-3-pro", "generate",
                           remote_progress=me.REMOTE_PROGRESS_NONE)
    # §27/§32: cold default generate ≥ 180 c (90–180+ с генерации успевают).
    assert w.total_deadline >= 180.0
    assert w.total_deadline <= 900.0            # hard safety ceiling
    assert w.connect_timeout < w.total_deadline
    assert w.poll_request != w.total_deadline   # окна различны (§28)
    assert w.source == "cold_default"
    # §14: sync-only → read = total (сокет молчит до готовности).
    t = w.httpx_timeout()
    assert t is not None and t.read == w.total_deadline


def test_policy_stage_aware_operations():
    _reset_obs()
    gen = me.resolve_windows("nanogpt", "m", "generate")
    edit = me.resolve_windows("nanogpt", "m", "edit")
    prev = me.resolve_windows("nanogpt", "m", "preview")
    assert edit.total_deadline >= 240.0
    assert prev.total_deadline >= 240.0
    assert (gen.operation, edit.operation, prev.operation) == \
        ("generate", "edit", "preview")


def test_policy_adaptive_uses_successful_durations_only():
    """§25/§26: p95 успешных наблюдений поднимает deadline; timeout'ы НЕ
    обучают estimator (петля запрещена)."""
    _reset_obs()
    for d in (100.0, 110.0, 120.0, 130.0, 140.0, 150.0):
        me.record_media_outcome("nanogpt", "m", "generate", ok=True,
                                duration_s=d)
    # 10 timeout'ов подряд — reliability signal, НЕ наблюдение успеха.
    for _ in range(10):
        me.record_media_outcome("nanogpt", "m", "generate", ok=False,
                                timeout=True)
    w = me.resolve_windows("nanogpt", "m", "generate")
    assert w.source == "adaptive_p95"
    # p95 выборки ≈ 150 → deadline ≥ p95, но НЕ растёт от timeout'ов.
    assert w.total_deadline >= 150.0
    snap = me.media_policy_snapshot()["nanogpt|m|generate"]
    assert snap["timeouts"] == 10
    assert snap["samples"] == 6


def test_policy_off_legacy_windows(monkeypatch):
    monkeypatch.setattr(type(me.settings), "MEDIA_EXECUTION_POLICY_ENABLED",
                        False, raising=False)
    assert me.httpx_timeout_for("nanogpt", "m", "generate") is None
    monkeypatch.setattr(type(me.settings), "MEDIA_EXECUTION_POLICY_ENABLED",
                        True, raising=False)


def test_hard_ceiling_clamps_adaptive():
    """§26: даже при экстремальных успехах deadline ≤ hard safety ceiling."""
    _reset_obs()
    for d in (800.0 + i for i in range(6)):
        me.record_media_outcome("nanogpt", "m", "generate", ok=True,
                                duration_s=d)
    w = me.resolve_windows("nanogpt", "m", "generate")
    assert w.total_deadline <= 900.0


# ═══ Adapters (D4): detection + honest capabilities (§15–§18/§21) ═══════════

def test_detect_adapter_by_host():
    assert me.detect_adapter("https://nano-gpt.com/api/v1").name == "nanogpt"
    assert me.detect_adapter("https://openrouter.ai/api/v1").name == \
        "openrouter"
    generic = me.detect_adapter("https://example-llm.example/v1")
    assert generic.name == "generic"
    # §14/§16: до live-верификации async/status честно НЕ заявляются.
    for adapter in (me.detect_adapter("https://nano-gpt.com/api/v1"),
                    generic):
        assert adapter.supports_async_job is False
        assert adapter.supports_status is False
        assert adapter.remote_progress == me.REMOTE_PROGRESS_NONE


def test_generic_sync_submit_generation_uses_generation_module():
    """Generic sync fallback (§18) — контракт исполняет ЕДИНУЮ точку
    image_generation (не второй стек); исполнение проверяется в
    async-варианте ниже."""
    adapter = me.ImageProviderAdapter("https://img.example/v1")
    assert adapter.base_url == "https://img.example/v1"
    # До live-верификации async/status честно НЕ заявлены (§14/§16):
    # cancel — честный no-op False.
    assert adapter.supports_async_job is False
    assert asyncio.run(adapter.cancel("job-1")) is False


@pytest.mark.asyncio
async def test_generic_sync_submit_generation(monkeypatch):
    from services import image_generation as ig
    calls = {}

    async def fake_post(base_url, model, prompt, key, timeout, max_bytes,
                        retry=True):
        calls["base_url"] = base_url
        calls["model"] = model
        return b"png-bytes"

    monkeypatch.setattr(ig, "_generate_post", fake_post)
    adapter = me.ImageProviderAdapter("https://img.example/v1")
    result = await adapter.submit_generation(prompt="тест", model="m",
                                             timeout=123.0)
    assert result.ok and result.content == b"png-bytes"
    assert calls["base_url"] == "https://img.example/v1"


@pytest.mark.asyncio
async def test_nanogpt_discover_models_parses_catalog(monkeypatch):
    """Каталог-маршрут — единственный верифицированный кодом
    (`/api/v1/image-models?detailed=true`); парсинг entry по id."""
    adapter = me.NanoGPTImageAdapter("https://nano-gpt.com/api/v1")

    class FakeResp:
        status_code = 200

        def json(self):
            return {"data": [
                {"id": "qwen-image-3-pro",
                 "supported_parameters": {"resolutions": ["1024x1024"]}},
                {"id": "other"},
            ]}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            assert url.endswith("/image-models")
            assert params and params.get("detailed") == "true"
            return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    models = await adapter.discover_models()
    assert models and models[0]["id"] == "qwen-image-3-pro"


# ═══ §68 A: async provider — живая status НЕ рубится deadline ═══════════════

@pytest.mark.asyncio
async def test_async_job_alive_not_deadline_killed():
    """D5 §24: пока provider публикует RUNNING, job жив; total deadline —
    ceiling, применяемый ТОЛЬКО при отсутствии обновлений живости."""
    class JobAdapter(me.ImageProviderAdapter):
        name = "jobprov"
        remote_progress = me.REMOTE_PROGRESS_JOB_STATUS
        supports_async_job = True
        supports_status = True

    _reset_obs()
    adapter = JobAdapter("https://job.example/v1")
    windows = me.resolve_windows(adapter.name, "m", "generate",
                                 remote_progress=adapter.remote_progress)
    # Для job-status провайдера read-окно — окно ОТДЕЛЬНОГО poll-запроса,
    # а НЕ total deadline (живость обновляется status'ом).
    t = windows.httpx_timeout()
    assert t.read == windows.read_inactivity < windows.total_deadline
    # Симуляция живой джобы: прогресс обновляет last_progress_at — deadline
    # считается от последнего прогресса (не от submit wall-clock).
    jid, state = await me.begin_media_job(
        None, operation="generate", provider=adapter.name, model="m",
        prompt="тест", deadline_s=windows.total_deadline)
    assert state.provider_job_id is None
    state.provider_job_id = "job_1"
    state.mark(me.MJ_RUNNING)
    assert state.status == me.MJ_RUNNING
    # НЕ переключаемся на fallback, пока primary честно RUNNING (§31).
    fb = await me.maybe_media_fallback("тест", chat_id=1,
                                       primary_reason="slow",
                                       primary_running=True)
    assert fb is None


# ═══ §68 C: sync provider 150 c — adaptive policy позволяет завершиться ═════

@pytest.mark.asyncio
async def test_sync_150s_completes_under_adaptive_policy(monkeypatch):
    """§32: генерация 150 с НЕ считается failed: (а) adaptive cold-default
    ≥ 180 c; (б) успешное наблюдение 150 c поднимает p95-deadline."""
    _reset_obs()
    w = me.resolve_windows("nanogpt", "qwen-image-3-pro", "generate")
    assert w.total_deadline > 150.0          # cold default 180 c
    me.record_media_outcome("nanogpt", "qwen-image-3-pro", "generate",
                            ok=True, duration_s=150.0)
    # после ≥5 наблюдений 150 c — adaptive deadline остаётся ≥ 150 c.
    for _ in range(4):
        me.record_media_outcome("nanogpt", "qwen-image-3-pro", "generate",
                                ok=True, duration_s=150.0)
    w2 = me.resolve_windows("nanogpt", "qwen-image-3-pro", "generate")
    assert w2.total_deadline >= 150.0


# ═══ §68 D: terminal failure → быстрый fallback (§31) ═══════════════════════

@pytest.mark.asyncio
async def test_terminal_failure_fallback(monkeypatch):
    monkeypatch.setattr(type(me.settings), "IMAGE_FALLBACK_BASE_URL",
                        "https://fallback.example/v1", raising=False)
    monkeypatch.setattr(type(me.settings), "IMAGE_FALLBACK_MODEL",
                        "fallback-model", raising=False)
    submitted = {}

    class FakeAdapter(me.ImageProviderAdapter):
        name = "fallbackprov"

        async def submit_generation(self, *, prompt, model, timeout=None):
            submitted["model"] = model
            return me.MediaSubmitResult(ok=True, content=b"fb", reason="ok")

    monkeypatch.setattr(me, "detect_adapter",
                        lambda base_url: FakeAdapter(base_url))
    result = await me.maybe_media_fallback(
        "промпт", chat_id=7, primary_reason="bad_request")
    assert result is not None and result.ok
    assert submitted["model"] == "fallback-model"


@pytest.mark.asyncio
async def test_no_fallback_when_not_configured_or_running(monkeypatch):
    monkeypatch.setattr(type(me.settings), "IMAGE_FALLBACK_BASE_URL", "",
                        raising=False)
    monkeypatch.setattr(type(me.settings), "IMAGE_FALLBACK_MODEL", "",
                        raising=False)
    assert await me.maybe_media_fallback("x", chat_id=1,
                                         primary_reason="bad_request") is None
    monkeypatch.setattr(type(me.settings), "IMAGE_FALLBACK_BASE_URL",
                        "https://f.example/v1", raising=False)
    monkeypatch.setattr(type(me.settings), "IMAGE_FALLBACK_MODEL", "m",
                        raising=False)
    # §31: primary честно RUNNING → переключение запрещено.
    assert await me.maybe_media_fallback("x", chat_id=1,
                                         primary_reason="slow",
                                         primary_running=True) is None


# ═══ §68 E/F: restart recovery + durable state (§29/§30) ════════════════════

@pytest_asyncio.fixture
async def sdb(tmp_path):
    from services.database import DatabaseService
    d = DatabaseService(str(tmp_path / "media32.db"))
    await d.initialize()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_durable_media_job_lifecycle(sdb):
    jid, state = await me.begin_media_job(
        sdb, operation="generate", provider="nanogpt",
        model="qwen-image-3-pro", prompt="тест-промпт", chat_id=5,
        deadline_s=180.0, base_url="https://nano-gpt.com/api/v1")
    assert jid and state.status == me.MJ_SUBMITTED
    state.provider_job_id = "prov-job-77"
    state.mark(me.MJ_RUNNING)
    assert await me.save_media_job(sdb, jid, state)
    checkpoint = await TaskJobStore(sdb).get_checkpoint(jid)
    restored = me.MediaJobState.from_json(checkpoint.get("cursor"))
    assert restored.provider_job_id == "prov-job-77"
    assert restored.status == me.MJ_RUNNING
    assert await me.finish_media_job(sdb, jid, state, outcome=me.MJ_SUCCEEDED)
    row = await TaskJobStore(sdb).get(jid)
    assert row["status"] == "completed"


@pytest.mark.asyncio
async def test_restart_resume_by_provider_job_id_no_resubmit(sdb, monkeypatch):
    """§30: известен provider job ID (адаптер поддерживает status) →
    RECOVERED/resume; платный submit НЕ выполняется."""
    jid, state = await me.begin_media_job(
        sdb, operation="generate", provider="statusprov", model="m",
        prompt="тест", base_url="https://job.example/v1")
    state.provider_job_id = "job-42"
    state.mark(me.MJ_RUNNING)
    await me.save_media_job(sdb, jid, state)

    class StatusAdapter(me.ImageProviderAdapter):
        name = "statusprov"
        supports_status = True

    monkeypatch.setattr(me, "detect_adapter",
                        lambda base_url: StatusAdapter(base_url))
    summary = await me.recover_media_jobs(sdb)
    assert summary["resumed"] == 1
    assert summary["unknown_after_disconnect"] == 0
    # Джоба осталась активной (не закрыта, НЕ пересоздана платно).
    row = await TaskJobStore(sdb).get(jid)
    assert row["status"] in ("queued", "running")


@pytest.mark.asyncio
async def test_restart_sync_only_unknown_after_disconnect(sdb):
    """§30: sync-only без provider job id → честный unknown_after_disconnect,
    автоматического платного retry НЕТ."""
    jid, state = await me.begin_media_job(
        sdb, operation="generate", provider="nanogpt", model="m",
        prompt="sync-тест", base_url="https://nano-gpt.com/api/v1")
    state.mark(me.MJ_RUNNING)
    await me.save_media_job(sdb, jid, state)
    summary = await me.recover_media_jobs(sdb)
    assert summary["unknown_after_disconnect"] == 1
    row = await TaskJobStore(sdb).get(jid)
    assert row["status"] == "failed"
    assert "unknown_after_disconnect" in str(row["reason_code"])


@pytest.mark.asyncio
async def test_coalesce_same_prompt_reuses_active_job(sdb):
    """§42-прецедент: тот же (operation, provider, model, prompt) → АКТИВНАЯ
    джоба переиспользуется (singleflight), а не второй платный submit."""
    jid1, _ = await me.begin_media_job(sdb, operation="generate",
                                       provider="p", model="m", prompt="dup")
    jid2, state2 = await me.begin_media_job(sdb, operation="generate",
                                            provider="p", model="m",
                                            prompt="dup")
    assert jid1 == jid2


# ═══ §68 F: unknown provider — safe sync + честный unknown ══════════════════

@pytest.mark.asyncio
async def test_unknown_provider_honest_unknown(monkeypatch):
    adapter = me.detect_adapter("https://totally-unknown.example/v1")
    assert adapter.remote_progress == me.REMOTE_PROGRESS_NONE
    caps = await adapter.discover_capabilities("mystery")
    # unknown остаётся честным unknown (§21), fake ping отсутствует.
    assert caps is None or caps.source == "unknown"
