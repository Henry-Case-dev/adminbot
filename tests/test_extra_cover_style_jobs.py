"""EXTRA Pass 2 (extra-cover-style-pipeline, ADR-1028-4 D8/D9; spec §3.11/§39–§48/
§49–§52/§68–§70/§92) — Block F/G unit-тесты: durable job, fail-soft ladder,
edit policy, async (capability-gated), heartbeat, latency/cost, prompt compile.

Покрытие §78–§96 (runtime-часть §89/§92/§96) + §98 инварианты «long-running ≠
text-LLM timeout», «logs показывают точную стадию», «limits не hardcoded».
"""
import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import cover_style_edit as ed
from services import cover_style_jobs as j
from services import image_capabilities as cap
from services import image_prompt_compiler as compiler
from services.cover_style_edit import EditResult


def _profile(**over):
    p = {
        "profile_id": "csp_test", "name": "Test", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Сделай обложку в стиле серии, не дублируй элементы.",
        "counter_enabled": True, "counter_value": 0,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 3,
        "enabled": True,
        "references": [{"ref_id": "r1", "asset_id": "cas_x", "label": "logo",
                        "description": "издательский знак", "ordering": 0}],
        "preview_issue": "ВЫПУСК 00",
    }
    p.update(over)
    return p


class _Resp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self):
        return self._body


def _png(path):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return str(path)


# ══ §42 state machine + durable job state ═══════════════════════════════════

class TestJobState:
    def test_state_machine_maps_to_task_status(self):
        assert j.TASK_STATUS_BY_STATE[j.STATE_DONE] == "completed"
        assert j.TASK_STATUS_BY_STATE[j.STATE_FAILED] == "failed"
        for st in (j.STATE_CREATED, j.STATE_BASE_RUNNING, j.STATE_STYLE_RUNNING,
                   j.STATE_PUBLISH_RICH):
            assert j.TASK_STATUS_BY_STATE[st] in ("queued", "running")

    def test_roundtrip_preserves_provider_task(self):
        st = j.CoverJobState()
        st.mark(j.STATE_STYLE_RUNNING, provider_task_id="prov-9")
        raw = st.to_json()
        again = j.CoverJobState.from_json(raw)
        assert again.state == j.STATE_STYLE_RUNNING
        assert again.provider_task_id == "prov-9"
        assert again.task_status == "running"

    def test_from_json_bad_is_fail_open(self):
        assert j.CoverJobState.from_json("not-json").state == j.STATE_CREATED
        assert j.CoverJobState.from_json(None).state == j.STATE_CREATED


@pytest.mark.asyncio
async def test_durable_job_reuse(monkeypatch):
    """REUSE `task_jobs` (второй очереди нет, §42): enqueue/finish/checkpoint."""
    calls = {}

    class _FakeStore:
        def __init__(self, db):
            calls["db"] = db

        async def enqueue(self, **kw):
            calls["enqueue"] = kw
            return kw.get("job_id")

        async def finish(self, job_id, **kw):
            calls["finish"] = (job_id, kw)
            return True

        async def save_checkpoint(self, job_id, **kw):
            calls["checkpoint"] = (job_id, kw)
            return True

    monkeypatch.setattr("services.task_supervisor.TaskJobStore", _FakeStore)
    db = object()
    jid = await j.start_cover_job(db, chat_id=-100, correlation_id="run1",
                                  job_id="cov_x")
    assert jid == "cov_x"
    assert calls["enqueue"]["owner"] == "summary"
    assert calls["enqueue"]["kind"] == "cover_style"
    assert "run1" in calls["enqueue"]["payload"]
    state = j.CoverJobState(state=j.STATE_STYLE_RUNNING, provider_task_id="t9")
    assert await j.save_cover_state(db, jid, state) is True
    assert "t9" in calls["checkpoint"][1]["cursor_token"]
    assert await j.finish_cover_job(db, jid, outcome=j.RESULT_STYLED) is True
    assert calls["finish"][1]["status"] == "completed"
    # fail-open без db
    assert await j.start_cover_job(None, chat_id=1) is None
    assert await j.finish_cover_job(None, None, outcome="x") is False


# ══ §96/§47/§48 classification & statuses ═══════════════════════════════════

class TestClassification:
    def test_ladder_branches(self):
        styled = j.classify_cover_result(published_channel="rich",
                                         cover_outcome=j.RESULT_STYLED)
        assert styled["cover_result"] == "styled" and styled["fallback"] is None
        base = j.classify_cover_result(published_channel="rich",
                                       cover_outcome=j.RESULT_BASE,
                                       cover_reason=j.REASON_STYLE_FAILED)
        assert base["cover_result"] == "base"
        assert base["reason"] == "style_failed"
        none = j.classify_cover_result(published_channel="rich",
                                       cover_outcome=j.RESULT_NONE)
        assert none["cover_result"] == "none"
        assert none["reason"] == "base_failed"
        plain = j.classify_cover_result(published_channel="plain",
                                        cover_outcome=j.RESULT_BASE)
        assert plain["publication"] == "plain_send_message"
        assert plain["reason"] == "rich_failed"

    def test_ru_status_present(self):
        assert "базовая обложка" in j.ru_status_for(j.RESULT_BASE)
        assert "без изображения" in j.ru_status_for(j.RESULT_NONE)
        assert j.ru_status_for(j.RESULT_STYLED) == ""

    def test_timeline_marks_failures(self):
        rows = j.build_timeline(text_ms=10, base_ms=20, style_ms=30,
                                rich_ms=5, base_ok=True, style_enabled=True,
                                style_ok=False, rich_ok=True)
        names = [r["name"] for r in rows]
        assert any("стил" in n.lower() for n in names)
        style_row = [r for r in rows if "стил" in r["name"].lower()][0]
        assert style_row["ok"] is False


# ══ §68/§92 metrics ═════════════════════════════════════════════════════════

class TestMetrics:
    def test_latency_percentiles_and_flags(self):
        j.reset_metrics()
        for ms in (100, 200, 300, 400):
            j.record_latency("m1", "base", ms)
        j.record_latency("m1", "base", 500, timeout=True, retry=True,
                         provider_fallback=True)
        stats = j.latency_stats()["base|m1"]
        assert stats["count"] == 5
        assert stats["max"] == 500
        assert stats["p50"] <= stats["p95"] <= 500
        assert stats["timeout_count"] == 1
        assert stats["retry_count"] == 1
        assert stats["provider_fallback_count"] == 1

    def test_cost_preview_not_mixed_with_production(self):
        j.reset_metrics()
        j.record_cost("style_edit", 0.05, mode="production")
        j.record_cost("style_edit", 0.02, mode="preview")
        summary = j.cost_summary()["style_edit"]
        assert summary["production"] == pytest.approx(0.05)
        assert summary["preview"] == pytest.approx(0.02)
        assert summary["known"] is True

    def test_unknown_cost_not_invented(self):
        j.reset_metrics()
        j.record_cost("base", None)
        assert j.cost_summary() == {}

    def test_metrics_kill_switch(self, monkeypatch):
        j.reset_metrics()
        monkeypatch.setattr("services.cover_style_jobs._metrics_enabled", lambda: False)
        j.record_latency("m", "base", 123)
        assert j.latency_stats() == {}


# ══ §39/§41/§46/§69 image execution policy ═════════════════════════════════=

class TestEditPolicy:
    def test_timeout_not_llm_and_clamped(self, monkeypatch):
        # Legacy-путь (MEDIA_EXECUTION_POLICY_ENABLED=OFF): env-окно —
        # единственная истина, клампы [30, 900] (§69; паритет EXTRA).
        monkeypatch.setattr(Settings, "MEDIA_EXECUTION_POLICY_ENABLED",
                            False, raising=False)
        monkeypatch.setattr(Settings, "COVER_STYLE_EDIT_TIMEOUT_SECONDS", 1)
        assert ed._timeout() == 30.0         # нижний кламп
        monkeypatch.setattr(Settings, "COVER_STYLE_EDIT_TIMEOUT_SECONDS", 9999)
        assert ed._timeout() == 900.0        # верхний кламп
        monkeypatch.setattr(Settings, "COVER_STYLE_EDIT_TIMEOUT_SECONDS", 240)
        assert ed._timeout() == 240.0        # ≠ LLM timeout 120

    def test_timeout_policy_path_stage_aware(self, monkeypatch):
        # ASAP-3.2 (ADR-1028-5 D5, T-4197): policy ON → окно из
        # MediaExecutionPolicy (key provider+model+operation, §23);
        # env `COVER_STYLE_EDIT_TIMEOUT_SECONDS` — migration evidence,
        # НЕ binding (§27): policy cold default 240 в приоритете.
        monkeypatch.setattr(Settings, "MEDIA_EXECUTION_POLICY_ENABLED",
                            True, raising=False)
        monkeypatch.setattr(Settings, "COVER_STYLE_EDIT_TIMEOUT_SECONDS", 1)
        from services.media_execution import _OBS
        _OBS.clear()
        assert ed._timeout("edit", "https://img.example/v1", "m") == 240.0
        assert ed._timeout("preview", "https://img.example/v1", "m") == 240.0
        _OBS.clear()

    def test_attempts_and_backoff_clamped(self, monkeypatch):
        monkeypatch.setattr(Settings, "COVER_STYLE_EDIT_MAX_ATTEMPTS", 9)
        assert ed.max_attempts() == 3
        monkeypatch.setattr(Settings, "COVER_STYLE_EDIT_MAX_ATTEMPTS", 0)
        assert ed.max_attempts() == 1
        monkeypatch.setattr(Settings, "COVER_STYLE_EDIT_RETRY_BACKOFF_SECONDS",
                            999)
        assert ed.retry_backoff() == 60.0

    def test_heartbeat_interval_clamped(self, monkeypatch):
        monkeypatch.setattr(Settings, "COVER_STYLE_HEARTBEAT_SECONDS", 1)
        assert j.heartbeat_interval() == 5.0
        monkeypatch.setattr(Settings, "COVER_STYLE_HEARTBEAT_SECONDS", 999)
        assert j.heartbeat_interval() == 120.0

    def test_async_gating(self, monkeypatch):
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_SUBMIT_URL", "")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_STATUS_URL", "")
        assert ed._async_configured() is False
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_SUBMIT_URL",
                            "https://p/submit")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_STATUS_URL",
                            "https://p/status/{task_id}")
        assert ed._async_configured() is True
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_POLL_SECONDS", 0.01)
        assert ed.async_poll_interval() == 0.5


# ══ §3.7/§38/§40/§89 edit_image (capability-gated, sync + async) ════════════

class TestEditImage:
    @pytest.mark.asyncio
    async def test_gate_no_edit(self, tmp_path):
        base = _png(tmp_path / "b.png")
        caps = cap.ImageModelCapabilities(image_edit=cap.FALSE)
        res = await ed.edit_image("p", base_image_path=base, reference_paths=[],
                                  base_url="https://x", model="m",
                                  capabilities=caps)
        assert res.ok is False and res.reason == "edit_unsupported"

    @pytest.mark.asyncio
    async def test_not_configured(self, tmp_path):
        base = _png(tmp_path / "b.png")
        res = await ed.edit_image("p", base_image_path=base, reference_paths=[],
                                  base_url="", model="")
        assert res.ok is False and res.reason == "not_configured"

    @pytest.mark.asyncio
    async def test_sync_success_b64(self, tmp_path):
        base = _png(tmp_path / "b.png")
        payload = {"data": [{"b64_json": base64.b64encode(b"IMG").decode()}]}

        async def transport(url, body, headers, timeout):
            assert url.endswith("/images")
            assert body["input_references"]        # data-url присутствует
            return _Resp(200, payload)

        res = await ed.edit_image("p", base_image_path=base, reference_paths=[],
                                  base_url="https://api.x/v1", model="m",
                                  capabilities=cap.ImageModelCapabilities(
                                      image_edit=cap.TRUE),
                                  transport=transport)
        assert res.ok and res.content == b"IMG" and res.reason == "ok"

    @pytest.mark.asyncio
    async def test_sync_bad_request_capability_mismatch(self, tmp_path):
        base = _png(tmp_path / "b.png")

        async def transport(url, body, headers, timeout):
            return _Resp(400, {"detail": "prompt too long"})

        res = await ed.edit_image("p", base_image_path=base, reference_paths=[],
                                  base_url="https://api.x/v1", model="m",
                                  capabilities=cap.ImageModelCapabilities(
                                      image_edit=cap.TRUE),
                                  transport=transport)
        assert res.ok is False and res.reason == "bad_request"

    @pytest.mark.asyncio
    async def test_sync_timeout(self, tmp_path):
        import httpx
        base = _png(tmp_path / "b.png")

        async def transport(url, body, headers, timeout):
            raise httpx.TimeoutException("slow")

        res = await ed.edit_image("p", base_image_path=base, reference_paths=[],
                                  base_url="https://api.x/v1", model="m",
                                  capabilities=cap.ImageModelCapabilities(
                                      image_edit=cap.TRUE),
                                  transport=transport)
        assert res.ok is False and res.reason == "timeout"

    @pytest.mark.asyncio
    async def test_sync_url_download(self, tmp_path):
        base = _png(tmp_path / "b.png")

        async def transport(url, body, headers, timeout):
            return _Resp(200, {"data": [{"url": "https://cdn/x.jpg"}]})

        async def downloader(url, timeout):
            return b"DOWNLOADED"

        res = await ed.edit_image("p", base_image_path=base, reference_paths=[],
                                  base_url="https://api.x/v1", model="m",
                                  capabilities=cap.ImageModelCapabilities(
                                      image_edit=cap.TRUE),
                                  transport=transport, downloader=downloader)
        assert res.ok and res.content == b"DOWNLOADED"

    @pytest.mark.asyncio
    async def test_async_submit_poll_success(self, tmp_path, monkeypatch):
        base = _png(tmp_path / "b.png")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_SUBMIT_URL",
                            "https://p/submit")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_STATUS_URL",
                            "https://p/status/{task_id}")
        monkeypatch.setattr(ed, "async_poll_interval", lambda: 0.001)
        seen = {"submit": 0, "poll": 0}

        async def transport(url, body, headers, timeout):
            if url.endswith("/submit"):
                seen["submit"] += 1
                return _Resp(200, {"task_id": "t1"})
            seen["poll"] += 1
            return _Resp(200, {"status": "succeeded",
                               "data": [{"b64_json": base64.b64encode(
                                   b"ASYNC").decode()}]})

        res = await ed.edit_image(
            "p", base_image_path=base, reference_paths=[],
            base_url="https://api.x/v1", model="m",
            capabilities=cap.ImageModelCapabilities(image_edit=cap.TRUE,
                                                    async_jobs=True),
            transport=transport)
        assert res.ok and res.content == b"ASYNC" and res.async_used is True
        assert res.task_id == "t1"

    @pytest.mark.asyncio
    async def test_async_restart_resume_reuses_task(self, tmp_path, monkeypatch):
        base = _png(tmp_path / "b.png")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_SUBMIT_URL",
                            "https://p/submit")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_STATUS_URL",
                            "https://p/status/{task_id}")
        monkeypatch.setattr(ed, "async_poll_interval", lambda: 0.001)
        seen = {"submit": 0}

        async def transport(url, body, headers, timeout):
            if url.endswith("/submit"):
                seen["submit"] += 1
                return _Resp(200, {"task_id": "NEW"})
            return _Resp(200, {"status": "succeeded",
                               "data": [{"b64_json": base64.b64encode(
                                   b"RESUMED").decode()}]})

        res = await ed.edit_image(
            "p", base_image_path=base, reference_paths=[],
            base_url="https://api.x/v1", model="m",
            capabilities=cap.ImageModelCapabilities(image_edit=cap.TRUE,
                                                    async_jobs=True),
            transport=transport, existing_task_id="OLD")
        assert res.ok and res.reused_task is True
        assert seen["submit"] == 0            # новый платный task не создан

    @pytest.mark.asyncio
    async def test_async_deadline(self, tmp_path, monkeypatch):
        base = _png(tmp_path / "b.png")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_SUBMIT_URL",
                            "https://p/submit")
        monkeypatch.setattr(Settings, "COVER_STYLE_ASYNC_STATUS_URL",
                            "https://p/status/{task_id}")
        monkeypatch.setattr(ed, "async_poll_interval", lambda: 0.001)
        monkeypatch.setattr(ed, "_async_deadline", lambda: 0.001)

        async def transport(url, body, headers, timeout):
            if url.endswith("/submit"):
                return _Resp(200, {"task_id": "t1"})
            return _Resp(200, {"status": "running"})

        res = await ed.edit_image(
            "p", base_image_path=base, reference_paths=[],
            base_url="https://api.x/v1", model="m",
            capabilities=cap.ImageModelCapabilities(image_edit=cap.TRUE,
                                                    async_jobs=True),
            transport=transport)
        assert res.ok is False and res.reason == "deadline_exceeded"


# ══ §3.2/§19–§21/§38/§49 run_style_job ══════════════════════════════════════

class TestRunStyleJob:
    def _caps(self, **over):
        c = cap.ImageModelCapabilities(image_edit=cap.TRUE,
                                       max_input_images=3,
                                       prompt_limit=cap.PromptLimit(
                                           value=1000, unit="chars",
                                           source="internal_config"))
        for k, v in over.items():
            setattr(c, k, v)
        return c

    @pytest.mark.asyncio
    async def test_style_success(self, tmp_path):
        base = _png(tmp_path / "base.png")

        async def edit_call(prompt, **kw):
            assert "ВЫПУСК" in prompt
            return EditResult(ok=True, content=b"STYLED", reason="ok",
                              latency_ms=12)

        meta = await j.run_style_job(
            chat_id=-100, base_image_path=base, profile=_profile(),
            summary_run_id="run1", capabilities=self._caps(),
            edit_call=edit_call, reference_paths=[])
        assert meta["applied"] is True
        assert meta["outcome"] == j.RESULT_STYLED
        assert meta["styled_path"] and meta["reason"] == ""
        import os
        assert os.path.exists(meta["styled_path"])
        os.remove(meta["styled_path"])

    @pytest.mark.asyncio
    async def test_style_failure_uses_base(self, tmp_path):
        base = _png(tmp_path / "base.png")
        calls = {"n": 0}

        async def edit_call(prompt, **kw):
            calls["n"] += 1
            return EditResult(ok=False, reason="timeout")

        meta = await j.run_style_job(
            chat_id=-100, base_image_path=base, profile=_profile(),
            summary_run_id="run1", capabilities=self._caps(),
            edit_call=edit_call, reference_paths=[])
        assert meta["applied"] is False
        assert meta["outcome"] == j.RESULT_BASE
        assert meta["reason"] == j.REASON_STYLE_FAILED
        assert meta["fail_reason"] == "timeout"
        assert calls["n"] == 1                 # base НЕ перегенерируется (§49)

    @pytest.mark.asyncio
    async def test_prompt_limit_400_one_retry(self, tmp_path):
        """T-4814: machine-readable 400 prompt-limit → cache → recompile →
        РОВНО один retry (второй вызова нет)."""
        base = _png(tmp_path / "base.png")
        cap.reset_cache()
        prompts = []

        async def edit_call(prompt, **kw):
            prompts.append(prompt)
            if len(prompts) == 1:
                return EditResult(
                    ok=False, reason="prompt_limit",
                    meta={"prompt_limit": {"value": 40, "unit": "chars"},
                          "route": "image_api"})
            return EditResult(ok=True, content=b"STYLED2", reason="ok")

        meta = await j.run_style_job(
            chat_id=-100, base_image_path=base, profile=_profile(),
            summary_run_id="run1", capabilities=self._caps(),
            edit_call=edit_call, reference_paths=[])
        assert len(prompts) == 2
        assert meta["applied"] is True
        assert meta.get("prompt_limit_retry", {}).get("resolved_limit") == 40

    @pytest.mark.asyncio
    async def test_edit_unsupported(self, tmp_path):
        base = _png(tmp_path / "base.png")
        meta = await j.run_style_job(
            chat_id=-100, base_image_path=base, profile=_profile(),
            summary_run_id="run1",
            capabilities=self._caps(image_edit=cap.FALSE),
            edit_call=AsyncMock(), reference_paths=[])
        assert meta["applied"] is False
        assert meta["fail_reason"] == "edit_unsupported"
        assert "не умеет" in meta["message"]

    @pytest.mark.asyncio
    async def test_kill_switch_off(self, tmp_path, monkeypatch):
        base = _png(tmp_path / "base.png")
        monkeypatch.setattr("services.cover_style_jobs.cover_styles_enabled", lambda: False)
        meta = await j.run_style_job(
            chat_id=-100, base_image_path=base, profile=_profile(),
            summary_run_id="run1", capabilities=self._caps(),
            edit_call=AsyncMock(), reference_paths=[])
        assert meta["applied"] is False
        assert meta["reason"] == "cover_styles_disabled"

    @pytest.mark.asyncio
    async def test_no_profile_and_no_base(self, tmp_path):
        no_profile = await j.run_style_job(
            chat_id=-100, base_image_path=None, profile=None,
            summary_run_id="run1")
        assert no_profile["applied"] is False and no_profile["reason"] == "no_style"
        base = _png(tmp_path / "base.png")
        no_base = await j.run_style_job(
            chat_id=-100, base_image_path=None, profile=_profile(),
            summary_run_id="run1", capabilities=self._caps())
        assert no_base["outcome"] == j.RESULT_NONE

    @pytest.mark.asyncio
    async def test_preview_does_not_touch_counter(self, tmp_path):
        base = _png(tmp_path / "base.png")

        async def edit_call(prompt, **kw):
            return EditResult(ok=True, content=b"S", reason="ok")

        meta = await j.run_style_preview(profile=_profile(),
                                         base_image_path=base,
                                         edit_call=edit_call,
                                         reference_paths=[],
                                         capabilities=self._caps())
        assert meta["applied"] is True
        assert meta["mode"] == j.MODE_PREVIEW
        assert meta["issue_number"] is None
        assert meta["preview_issue"] == "ВЫПУСК 00"
        import os
        os.remove(meta["styled_path"])


# ══ §19–§21 prompt compilation ══════════════════════════════════════════════

class TestCompileStylePrompt:
    def test_p0_preserved_p2_dropped_first(self):
        caps = cap.ImageModelCapabilities(
            image_edit=cap.TRUE, max_input_images=3,
            prompt_limit=cap.PromptLimit(value=120, unit="chars",
                                         source="internal_config"))
        profile = _profile(instruction="A" * 60,
                           references=[{"ref_id": "r", "asset_id": "cas",
                                        "label": "logo",
                                        "description": "D" * 200}])
        compiled = j.compile_style_prompt(profile, issue_display="ВЫПУСК 7",
                                          capabilities=caps)
        assert "ВЫПУСК 7" in compiled.prompt          # P0 сохранён
        assert "references" in compiled.dropped        # P2 ушёл первым

    def test_unknown_limit_keeps_all(self):
        caps = cap.ImageModelCapabilities(image_edit=cap.TRUE)
        profile = _profile()
        compiled = j.compile_style_prompt(profile, issue_display="ВЫПУСК 1",
                                          capabilities=caps)
        assert compiled.limit is None
        assert "ВЫПУСК 1" in compiled.prompt


# ══ §45 safe log fields ═════════════════════════════════════════════════════

class TestSafeLogging:
    def test_no_secrets_in_event(self, caplog):
        import logging
        j.emit_cover_event(j.COVER_STYLE_START, outcome="start",
                           chat_id=-100, model="m", provider="p",
                           prompt_hash="deadbeef", prompt_len=10,
                           api_key="SECRET", raw_prompt="SECRET")
        text = caplog.text
        assert "SECRET" not in text
        assert j.prompt_hash("abc") == j.prompt_hash("abc")
        assert len(j.prompt_hash("abc")) == 16

    def test_rich_degraded_default_on(self):
        assert j.rich_degraded_enabled() is True


# ══ §42/§43/DoD-25 durable restart-resume + prod-wiring ═════════════════════

def _caps(**over):
    c = cap.ImageModelCapabilities(
        image_edit=cap.TRUE, max_input_images=3,
        prompt_limit=cap.PromptLimit(value=1000, unit="chars",
                                     source="internal_config"))
    for k, v in over.items():
        setattr(c, k, v)
    return c


async def _fresh_db():
    from services.database import DatabaseService
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


class TestDurableRestart:
    @pytest.mark.asyncio
    async def test_begin_reuses_existing_job_no_duplicate(self):
        db = await _fresh_db()
        try:
            jid1, state1 = await j.begin_cover_job(
                db, chat_id=-100, correlation_id="run-x", style_id="csp_test",
                summary_run_id="run-x")
            assert jid1 and jid1.startswith("cov_")
            # повторный заход того же run+style — тот же job (singleflight).
            jid2, state2 = await j.begin_cover_job(
                db, chat_id=-100, correlation_id="run-x", style_id="csp_test",
                summary_run_id="run-x")
            assert jid2 == jid1
            from services.task_supervisor import TaskJobStore
            store = TaskJobStore(db)
            active = await store.active()
            assert [r["job_id"] for r in active] == [jid1]
            # детерминированный ключ run+style
            assert j.cover_job_key(summary_run_id="run-x", style_id="csp_test") \
                == jid1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_restart_resumes_provider_task_from_task_jobs(self, tmp_path):
        """DoD-25 (SC-30/§43): рестарт посреди джобы → возобновление из
        `task_jobs`, provider task_id переиспользуется, нового платного task
        нет."""
        db = await _fresh_db()
        try:
            base = _png(tmp_path / "base.png")
            profile = _profile()
            jid, state = await j.begin_cover_job(
                db, chat_id=-100, correlation_id="run-r", style_id="csp_test",
                summary_run_id="run-r")

            # Первый заход: async-submit вернул task_id, polling истёк —
            # provider_task_id персистится в task_jobs (§43).
            async def first_call(prompt, **kw):
                return EditResult(ok=False, reason="deadline_exceeded",
                                  task_id="prov-1", async_used=True)

            meta1 = await j.run_style_job(
                chat_id=-100, base_image_path=base, profile=profile,
                summary_run_id="run-r", capabilities=_caps(),
                edit_call=first_call, reference_paths=[], db=db, job_id=jid,
                state=state)
            assert meta1["provider_task_id"] == "prov-1"
            saved = await j.load_cover_state(db, jid)
            assert saved is not None and saved.provider_task_id == "prov-1"

            # ── рестарт: process-local state сброшен (state=None) ──
            seen = {}

            async def resume_call(prompt, **kw):
                seen["existing"] = kw.get("existing_task_id")
                return EditResult(ok=True, content=b"STYLED", reason="ok",
                                  task_id="prov-1", async_used=True,
                                  reused_task=True)

            meta2 = await j.run_style_job(
                chat_id=-100, base_image_path=base, profile=profile,
                summary_run_id="run-r", capabilities=_caps(),
                edit_call=resume_call, reference_paths=[], db=db, job_id=jid,
                state=None)
            assert seen["existing"] == "prov-1"      # resume из task_jobs
            assert meta2["applied"] is True
            assert meta2["final_asset_id"]            # provenance §30
            assert meta2["base_asset_id"]

            from services.task_supervisor import TaskJobStore
            store = TaskJobStore(db)
            active = await store.active()
            assert [r["job_id"] for r in active] == [jid]   # дублей нет
            if meta2.get("styled_path"):
                import os
                os.remove(meta2["styled_path"])
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_finish_marks_job_completed(self, tmp_path):
        db = await _fresh_db()
        try:
            base = _png(tmp_path / "base.png")
            jid, state = await j.begin_cover_job(
                db, chat_id=-100, correlation_id="run-f", style_id="csp_test",
                summary_run_id="run-f")
            await j.finish_cover_job(db, jid, outcome=j.RESULT_BASE,
                                     reason_code="style_failed",
                                     checkpoint=state)
            from services.task_supervisor import TaskJobStore
            row = await TaskJobStore(db).get(jid)
            assert row["status"] == "completed"
            assert row["reason_code"] == "style_failed"
        finally:
            await db.close()


class TestProductionWiring:
    @pytest.mark.asyncio
    async def test_publish_path_uses_durable_job(self, monkeypatch):
        """H-EXTRA-1: прод-путь Summary→cover style идёт через durable job
        (db/job_id/state передаются в `run_style_job`, job создаётся и
        завершается)."""
        from types import SimpleNamespace
        from services.summary_generator import SummaryGenerator
        db = await _fresh_db()
        captured = {}

        monkeypatch.setattr(j, "cover_styles_enabled", lambda: True)
        monkeypatch.setattr(j, "resolve_selected_style_id",
                            AsyncMock(return_value="csp_test"))
        monkeypatch.setattr(j, "load_selected_profile",
                            AsyncMock(return_value=_profile()))
        monkeypatch.setattr(j, "uses_style_stage", lambda p: True)

        async def fake_run(**kw):
            captured.update(kw)
            return {"applied": False, "styled_path": None,
                    "outcome": j.RESULT_BASE, "fail_reason": "edit_unsupported",
                    "provider_task_id": None, "base_asset_id": None,
                    "final_asset_id": None}

        monkeypatch.setattr(j, "run_style_job", fake_run)
        gen = SimpleNamespace(memory=SimpleNamespace(db=db))
        meta = await SummaryGenerator._maybe_apply_cover_style(
            gen, -100, "base.png", "run-w", cover_prompt="Сюжет. Далее.",
            base_style="cinematic")
        assert meta is not None
        assert captured.get("db") is db
        assert captured.get("job_id")
        assert isinstance(captured.get("state"), j.CoverJobState)
        assert captured.get("summary_text") == "Сюжет. Далее."
        assert captured.get("base_style_prompt") == "cinematic"

        from services.task_supervisor import TaskJobStore
        row = await TaskJobStore(db).get(captured["job_id"])
        assert row is not None and row["kind"] == "cover_style"
        assert row["status"] in ("completed", "failed")
        await db.close()


class TestDynamicBrief:
    @pytest.mark.asyncio
    async def test_run_style_job_prompt_contains_brief_and_base_style(self,
                                                                      tmp_path):
        """M-EXTRA-2: dynamic CoverBrief из Summary-prose + base style prompt
        реально попадают в итоговый Style Edit prompt (§19/§21)."""
        base = _png(tmp_path / "base.png")
        seen = {}

        async def edit_call(prompt, **kw):
            seen["prompt"] = prompt
            return EditResult(ok=True, content=b"S", reason="ok")

        await j.run_style_job(
            chat_id=-100, base_image_path=base, profile=_profile(),
            summary_run_id="run-b", capabilities=_caps(),
            edit_call=edit_call, reference_paths=[],
            summary_text="Герой идёт по зимнему лесу. Его ждёт поезд.",
            base_style_prompt="photorealistic, cinematic light")
        prompt = seen["prompt"]
        assert "зимнему лесу" in prompt            # dynamic brief (§21)
        assert "photorealistic" in prompt          # base style prompt (§19)
        assert "ВЫПУСК" in prompt                  # P0 сохранён
        brief = compiler.brief_from_text("Герой идёт по зимнему лесу. Далее.")
        assert brief.render().startswith("Сюжет: Герой идёт по зимнему лесу.")

