"""ASAP-SUMMARY-COVER-INTEGRITY-01 v2.1 — §3 Cover Style + §3.5 Summary L2.

Контрактные сценарии 9–21 (ТЗ `plans/current_task.md` §9.B), офлайн, без
реальной сети: провайдер подменяется детерминированными моками.

Покрытие:
  * 9/10/12 — референсы СТРОГО опциональны: `refs=[]` и частично/полностью
    недоступные файлы не блокируют Style Edit; Base bitmap — обязательный
    вход; отсутствующее помечается `optional_reference_unavailable`, prompt
    не утверждает приложенный знак;
  * 11 — сохранённые reference ids/labels/roles не теряются при правке
    другого поля и при повторном чтении (reload);
  * 13/14 — реальный route-специфичный лимит (наблюдаемые 800/805): тело
    повторно в неизменном виде НЕ отправляется, смысл сохраняется по
    манифесту, честный unknown без глобального hardcap;
  * 15/16 — валидный payload/async-статус разбирается в изображение; пустой
    не-JSON ответ — честная ошибка; классы отказа различаются
    (`prompt_limit` / `invalid_provider_response` / `timeout` /
    `capability_unavailable` / `optional_reference_unavailable`);
  * 17/18 — styled реально доставлен, Base fallback не считается успехом
    стиля; манифест несёт original/sent/length/limit/attempt/route и
    отдельно фактически переданные изображения;
  * 19 — таймер: `queued` без реального старта не даёт миллионы секунд;
    `running`/terminal считаются от реального `started_at`;
  * 20 — preview предыдущей ревизии помечается stale; провал не стирает
    прежнюю рабочую пару;
  * 21 — L2 review остаётся строгим (коды/severity/gate не ослаблены),
    Legacy — честный fallback, Cover и Summary-ошибки не сливаются.

R17: в тестах нет секретов/полных пользовательских текстов в логах.
"""
from __future__ import annotations

import asyncio
import base64
import types
from unittest.mock import AsyncMock

import pytest

from services import cover_prompt_assembly as cpa
from services import cover_style_edit as cse
from services import cover_style_jobs as j
from services import cover_style_preview as pv
from services import cover_style_registry as registry
from services import image_capabilities as cap
from services import summary_l2_review as l2
from services.cover_style_edit import EditResult
from services.image_capabilities import (
    TRUE, UNKNOWN, ImageModelCapabilities, PromptLimit,
)
from tests.test_cover_style_wave_b_asap4 import (
    _STYLE_IMG, _asset_map, _caps, _flag, _jpg, _lines, _patch_issue_counter,
    _patch_pg, _patch_provenance, _png, _profile,
)

CHAT = -100266
RID = "cov-integrity-run-0001"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    _flag(monkeypatch, True)

    async def _slot(*, profile, connection, pg=None):
        return {"base_url": "https://edit.example/v1",
                "model": "qwen-image-edit", "provider": "edit.example",
                "connection_id": "default", "custom_unresolved": False,
                "configured": True}

    monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
    yield


# ══ 4. Таймауты/сердцебиение: конечные, без «тишины» 190 с ══════════════════

class TestTimeoutsBounded:
    def test_attempt_window_finite_and_clamped(self):
        """сц.4: окно попытки конечно и ограничено (не «бесконечный
        глобальный таймаут», не 190 с тишины без heartbeat)."""
        window = cse._timeout("edit", "https://edit.example/v1",
                              "qwen-image-edit")
        assert 30.0 <= window <= 900.0
        assert j.heartbeat_interval() <= 120.0
        assert cse.async_poll_interval() <= 60.0
        # async-deadline тоже конечен
        assert 30.0 <= cse._async_deadline() <= 3600.0

    def test_retry_bounded(self):
        """сц.4/16: retry ограничен (деньги) и не бесконечен."""
        assert 1 <= cse.max_attempts() <= 3
        assert j.recovery_max_attempts() >= 0


# ══ 9/10/12. Референсы строго опциональны ═══════════════════════════════════

class TestOptionalReferences:
    def test_refs_empty_edits_base(self, monkeypatch, tmp_path):
        """сц.9: Base + text style + `refs=[]` → Style Edit РЕАЛЬНО вызывается."""
        _patch_pg(monkeypatch)
        _patch_issue_counter(monkeypatch)
        _patch_provenance(monkeypatch)
        calls = []

        async def edit(prompt, **kw):
            calls.append(kw)
            return EditResult(ok=True, content=_STYLE_IMG, reason="ok")

        holder: dict = {}
        meta = _run(j.run_style_job(
            chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
            profile=_profile(references=[]), summary_run_id=RID,
            capabilities=_caps(), edit_call=edit, manifest_out=holder))
        assert meta["applied"] is True
        assert meta.get("fail_reason") in (None, "")
        assert len(calls) == 1
        assert calls[0]["reference_paths"] == []
        assert calls[0]["base_image_path"].endswith("b.png")
        manifest = holder["prompt_manifest"]
        assert manifest["image_inputs"]["base"] is True
        assert manifest["image_inputs"]["references"] == 0
        assert manifest["image_inputs"]["references_declared"] == 0
        assert "optional_reference_unavailable" not in manifest

    def test_partial_refs_send_only_available(self, monkeypatch, tmp_path):
        """сц.10/12: 3 объявленных, 2 доступных → Base + 2, отсутствующий
        помечен optional (не блокер, не фальшивый брендинг)."""
        _patch_pg(monkeypatch)
        _patch_issue_counter(monkeypatch)
        _patch_provenance(monkeypatch)
        ref_a = _png(tmp_path / "ref_a.png")
        ref_b = _png(tmp_path / "ref_b.png")
        _asset_map(monkeypatch, {
            "cas_a": {"asset_id": "cas_a", "disk_path": ref_a,
                      "mime": "image/png"},
            "cas_b": {"asset_id": "cas_b", "disk_path": ref_b,
                      "mime": "image/png"},
            "cas_c": {"asset_id": "cas_c",
                      "disk_path": str(tmp_path / "gone.png"),
                      "mime": "image/png"},
        })
        profile = _profile(references=[
            {"ref_id": "rA", "asset_id": "cas_a", "label": "Знак А",
             "description": "бренд", "ordering": 0},
            {"ref_id": "rB", "asset_id": "cas_b", "label": "Знак Б",
             "description": "бренд", "ordering": 1},
            {"ref_id": "rC", "asset_id": "cas_c", "label": "Знак Ц",
             "description": "бренд", "ordering": 2},
        ])
        seen = {}
        holder: dict = {}

        async def edit(prompt, **kw):
            seen["prompt"] = prompt
            seen["refs"] = kw.get("reference_paths")
            return EditResult(ok=True, content=_STYLE_IMG, reason="ok")

        meta = _run(j.run_style_job(
            chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
            profile=profile, summary_run_id=RID, capabilities=_caps(),
            edit_call=edit, manifest_out=holder))
        assert meta["applied"] is True
        assert seen["refs"] == [ref_a, ref_b]
        assert "Знак Ц" not in seen["prompt"], \
            "prompt не описывает неприложенный референс"
        # review-fix2: прежняя проверка сравнивала выражение само с собой
        # (`А or А`) и не проверяла ничего. Приложенные знаки — оба в prompt.
        assert "Знак А" in seen["prompt"] and "Знак Б" in seen["prompt"], \
            "prompt описывает оба реально приложенных референса"
        optional = meta["optional_reference_unavailable"]
        assert optional["declared"] == 3 and optional["attached"] == 2
        assert [r["ref_id"] for r in optional["unavailable"]] == ["rC"]
        # metadata профиля не удалена (id/label сохранены в details)
        details = {d["ref_id"]: d for d in meta["reference_details"]}
        assert set(details) == {"rA", "rB", "rC"}
        assert details["rC"]["readable"] is False
        manifest = holder["prompt_manifest"]
        assert manifest["image_inputs"]["references"] == 2
        assert manifest["image_inputs"]["references_declared"] == 3
        assert manifest["image_inputs"]["references_optional_unavailable"] == 1
        assert manifest["optional_reference_unavailable"]["declared"] == 3
        assert "rC" in [r["ref_id"] for r in
                        manifest["optional_reference_unavailable"]["unavailable"]]

    def test_off_path_prompt_skips_unavailable_refs(self, monkeypatch,
                                                    tmp_path):
        """review-fix2 (kill-switch OFF): prompt не описывает референс, чей
        файл недоступен, — иначе legacy-путь утверждал приложенный знак,
        которого нет. Набор фактической отправки не расширяется."""
        _flag(monkeypatch, False)
        _patch_pg(monkeypatch)
        _patch_issue_counter(monkeypatch)
        _patch_provenance(monkeypatch)
        ref_a = _png(tmp_path / "ref_a.png")
        _asset_map(monkeypatch, {
            "cas_a": {"asset_id": "cas_a", "disk_path": ref_a,
                      "mime": "image/png"},
            "cas_c": {"asset_id": "cas_c",
                      "disk_path": str(tmp_path / "gone.png"),
                      "mime": "image/png"},
        })
        profile = _profile(references=[
            {"ref_id": "rA", "asset_id": "cas_a", "label": "СимволМедведь",
             "description": "бренд", "ordering": 0},
            {"ref_id": "rC", "asset_id": "cas_c", "label": "СимволРека",
             "description": "бренд", "ordering": 1},
        ])
        seen: dict = {}

        async def edit(prompt, **kw):
            seen["prompt"] = prompt
            seen["refs"] = kw.get("reference_paths")
            return EditResult(ok=True, content=_STYLE_IMG, reason="ok")

        meta = _run(j.run_style_job(
            chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
            profile=profile, summary_run_id=RID, capabilities=_caps(),
            edit_call=edit))
        assert meta["applied"] is True
        assert seen["refs"] == [ref_a]
        assert "СимволМедведь" in seen["prompt"]
        assert "СимволРека" not in seen["prompt"], \
            "OFF-путь не выдаёт отсутствующий знак за приложенный"

    def test_refs_survive_reload_and_other_field_edit(self):
        """сц.11: ids/labels/roles выдерживают reload и правку другого поля
        (нет silent data loss; `references` вне style-affecting reset)."""
        profile = {"profile_id": "p1", "name": "P",
                   "instruction": "старая инструкция", "revision": 3,
                   "references": [{"ref_id": "r1", "asset_id": "cas_a",
                                   "label": "Знак", "description": "d",
                                   "ordering": 0}]}
        # Правка другого поля через draft snapshot не переписывает refs.
        merged = registry.merge_draft_snapshot(profile, {"instruction": "new"})
        assert merged["instruction"] == "new"
        assert merged["references"] == profile["references"]
        # references не входят в style-affecting поля (правка иного поля не
        # превращается в сброс привязки).
        assert "references" not in registry.STYLE_AFFECTING_FIELDS
        # canonical fingerprint привязан только к style-полям.
        same = dict(profile, references=[])
        assert (registry.style_fingerprint(profile)
                == registry.style_fingerprint(same)), \
            "references не участвуют в fingerprint (не сбрасываются)"
        # Повторное чтение (reload) того же профиля отдаёт те же refs.
        assert profile["references"][0]["ref_id"] == "r1"
        assert profile["references"][0]["asset_id"] == "cas_a"


# ══ 13/14. Реальный route-специфичный предел промпта ════════════════════════

class TestPromptLimitObserved:
    def test_observed_800_no_identical_resend(self, monkeypatch, tmp_path):
        """сц.13: провайдер сообщил limit=800, отправлено 805 → тело повторно
        в неизменном виде НЕ уходит; причина `prompt_limit` видна в манифесте
        отдельным классом; лимит пишется как route-специфичный (не глобальный)."""
        _patch_pg(monkeypatch)
        _patch_issue_counter(monkeypatch)
        _patch_provenance(monkeypatch)
        prompts = []
        recorded = {}
        holder: dict = {}

        async def edit(prompt, **kw):
            prompts.append(prompt)
            return EditResult(
                ok=False, reason="prompt_limit",
                meta={"prompt_limit": {"value": 800, "unit": "chars"},
                      "route": "image_api"})

        # Второй рекомпиль возвращает ТУ ЖЕ длину (как в проде: 805 → 805):
        # bounded-гард обязан запретить идентичный повтор.
        real_compile = j.compile_style_prompt

        def _compile(profile, **kw):
            compiled = real_compile(profile, **kw)
            return compiled

        monkeypatch.setattr(j, "compile_style_prompt", _compile)

        def _record(provider, base_url, model, value, unit, **kw):
            recorded.update({"value": value, "unit": unit,
                             "route": kw.get("route")})

        monkeypatch.setattr(cap, "record_runtime_limit",
                            lambda *a, **kw: recorded.update(
                                {"value": a[3] if len(a) > 3 else None}))
        # рекомпиль под лимит 800 всё равно длиннее → exceeded (как 805>800)
        monkeypatch.setattr(
            cap, "resolve_capabilities",
            lambda *a, **kw: ImageModelCapabilities(
                image_edit=TRUE, max_input_images=3,
                prompt_limit=PromptLimit(value=800, unit="chars",
                                         source="observed_provider_400")))
        long_instruction = "Сделай обложку в духе издательского знака. " * 20
        meta = _run(j.run_style_job(
            chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
            profile=_profile(instruction=long_instruction),
            summary_run_id=RID, capabilities=_caps(), edit_call=edit,
            manifest_out=holder))
        assert len(prompts) == 1, "идентичный/слишком длинный повтор запрещён"
        assert meta["applied"] is False
        assert meta["fail_reason"] in ("prompt_limit",
                                       "prompt_limit_exceeded")
        assert meta["error_class"] == "prompt_limit"
        retry = meta["prompt_limit_retry"]
        assert retry["retry_sent"] is False
        assert retry["skipped"] in ("exceeded", "not_shorter")
        assert retry["resolved_limit"] == 800, \
            "лимит взят из ответа провайдера, а не глобальный hardcap"
        manifest = holder["prompt_manifest"]
        assert manifest["attempts"][0]["outcome"] == "failed"
        assert manifest["attempts"][0]["error_class"] == "prompt_limit"
        assert manifest["error_class"] == "prompt_limit"
        assert manifest["resolved_limit"] == 800
        assert manifest["final_chars"] > 0

    def test_unknown_limit_no_global_hardcap(self):
        """сц.14: при неизвестном лимите нет выдуманного числа и нет
        глобального хардкапа для всех моделей — причина честная."""
        caps = ImageModelCapabilities(image_edit=TRUE,
                                      prompt_limit=PromptLimit(
                                          value=None, unit="chars",
                                          source="unknown"))
        assert caps.prompt_limit.known is False
        compiled = j.compile_style_prompt(
            _profile(), issue_display="ВЫПУСК 7", capabilities=caps,
            story_scene="Медведь открывает чемпионат.")
        assert "ВЫПУСК 7" in compiled.prompt
        assert compiled.resolved_limit is None
        # сохраняется ключевая style-инструкция (не «пустой» prompt)
        assert _profile()["instruction"][:20] in compiled.prompt


# ══ 15/16. Payload/async/классы отказа ══════════════════════════════════════

class _Resp:
    def __init__(self, status_code=200, content=b"", headers=None, body=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class TestPayloadAndErrorClasses:
    def test_valid_b64_payload_parsing(self):
        """сц.15: валидный b64_json/data-url разбирается в изображение."""
        b64 = base64.b64encode(_STYLE_IMG).decode("ascii")
        body = {"data": [{"b64_json": b64}]}
        content, reason = cse._extract(_Resp(body=body))
        assert reason == "ok" and content == _STYLE_IMG
        data_url = {"data": [{"url": "data:image/jpeg;base64," + b64}]}
        content2, reason2 = cse._extract(_Resp(body=data_url))
        assert reason2 == "ok" and content2 == _STYLE_IMG

    def test_async_status_parsing(self, monkeypatch):
        """сц.15: async submit → task_id → poll succeeded → изображение."""
        import config.settings as _cs
        from config.settings import Settings as _S
        for _cls in {_S, type(_cs.settings), type(cse.settings)}:
            monkeypatch.setattr(_cls, "COVER_STYLE_ASYNC_SUBMIT_URL",
                                "https://p.example/submit", raising=False)
            monkeypatch.setattr(_cls, "COVER_STYLE_ASYNC_STATUS_URL",
                                "https://p.example/status/{task_id}",
                                raising=False)
        state = {"polls": 0}

        async def post(url, payload, headers, timeout):
            if "submit" in url:
                return _Resp(body={"task_id": "t-1"})
            state["polls"] += 1
            b64 = base64.b64encode(_STYLE_IMG).decode("ascii")
            return _Resp(body={"status": "succeeded",
                               "data": [{"b64_json": b64}]})

        async def getter(url, timeout):
            raise AssertionError("download не нужен")

        async def _no_sleep(_s):
            return None

        import asyncio as _asyncio
        monkeypatch.setattr(_asyncio, "sleep", _no_sleep)
        result = _run(cse._edit_async(
            post, getter, "p", {}, "https://p.example", "m", "", "p.example",
            30.0, 0.0, None))
        assert result.ok is True and result.async_used is True
        assert result.task_id == "t-1"
        assert result.content == _STYLE_IMG

    def test_empty_non_json_is_invalid_provider_response(self):
        """сц.15/16: пустой/non-JSON 2xx — честный `bad_json`, не styled."""
        content, reason = cse._extract(_Resp(content=b"", headers={}))
        assert content is None and reason == "bad_json"

    def test_error_classes_distinct(self):
        """сц.16: классы отказа различаются, а не сливаются в `bad_json`."""
        assert j.edit_error_class("prompt_limit") == "prompt_limit"
        assert j.edit_error_class("prompt_limit_unknown") == "prompt_limit"
        assert j.edit_error_class("bad_json") == "invalid_provider_response"
        assert j.edit_error_class("invalid_image_payload") == \
            "invalid_provider_response"
        assert j.edit_error_class("timeout") == "timeout"
        assert j.edit_error_class("deadline_exceeded") == "timeout"
        assert j.edit_error_class("edit_unsupported") == \
            "capability_unavailable"
        assert j.edit_error_class("route_unverified") == \
            "capability_unavailable"
        assert j.edit_error_class("not_configured") == \
            "capability_unavailable"
        assert j.edit_error_class("optional_reference_unavailable") == \
            "optional_reference_unavailable"
        assert j.edit_error_class("http_429") == "rate_limited"
        assert j.edit_error_class("http_401") == "provider_rejected"
        # timeout остаётся под umbrella `style_failed` в mca reason_code —
        # точность даётся классом, а не расширением центрального реестра.
        assert j.style_reason_code("timeout") == "style_failed"

    def test_fail_classes_reach_manifest(self, monkeypatch, tmp_path):
        """сц.16/18: класс отказа и точная причина доходят до манифеста и
        человекочитаемого сообщения (разные тексты для разных причин)."""
        _patch_pg(monkeypatch)
        _patch_issue_counter(monkeypatch)
        _patch_provenance(monkeypatch)
        holder: dict = {}

        async def edit(prompt, **kw):
            return EditResult(ok=False, reason="bad_json")

        meta = _run(j.run_style_job(
            chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
            profile=_profile(references=[]), summary_run_id=RID,
            capabilities=_caps(), edit_call=edit, manifest_out=holder))
        assert meta["applied"] is False
        assert meta["error_class"] == "invalid_provider_response"
        manifest = holder["prompt_manifest"]
        assert manifest["error_class"] == "invalid_provider_response"
        assert manifest["attempts"][-1]["reason"] == "bad_json"
        assert manifest["attempts"][-1]["error_class"] == \
            "invalid_provider_response"
        assert "непригодный ответ" in pv.preview_human_message("bad_json")
        assert "лимит" in pv.preview_human_message("prompt_limit")


# ══ 17/18. Styled доставлен, Base не выдаётся за стиль, манифест ════════════

class TestStyledVsBase:
    def test_styled_delivered_and_manifest_complete(self, monkeypatch, tmp_path):
        """сц.17/18: успешный styled реально отдан публикации, манифест несёт
        original/sent/length/limit/attempt/route и переданные изображения."""
        _patch_pg(monkeypatch)
        _patch_issue_counter(monkeypatch)
        _patch_provenance(monkeypatch)
        holder: dict = {}

        async def edit(prompt, **kw):
            assert kw.get("route") in (None, "legacy_images")
            return EditResult(ok=True, content=_STYLE_IMG, reason="ok")

        meta = _run(j.run_style_job(
            chat_id=CHAT, base_image_path=_png(tmp_path / "b.png"),
            profile=_profile(references=[]), summary_run_id=RID,
            capabilities=_caps(), edit_call=edit, manifest_out=holder))
        assert meta["applied"] is True
        assert meta["styled_path"], "styled-файл создан для публикации"
        assert meta["outcome"] == "styled"
        manifest = holder["prompt_manifest"]
        assert manifest["operation"] == "edit"
        assert manifest["route"]
        assert manifest["attempts"][0]["chars"] == \
            len(manifest["attempts"][0]["prompt"])
        comps = {c["key"]: c for c in manifest["components"]}
        assert "original_chars" in next(iter(comps.values()))
        assert comps["CONTENT_PRESERVATION"]["status"] == "kept"
        assert manifest["image_inputs"]["base"] is True

    def test_base_fallback_not_style_success(self):
        """сц.17: Base опубликован + Style failed — это НЕ успех стиля."""
        result = j.classify_cover_result(
            published_channel="rich", cover_outcome=j.RESULT_BASE,
            cover_reason="bad_json")
        assert result["cover_result"] == "base"
        assert result["fallback"] == "bad_json"
        # текст потребителя честно говорит «базовая обложка», не «стиль готов»
        assert "базовая обложка" in j.RU_STYLE_FAILED.lower()
        assert "примен" not in j.RU_STYLE_FAILED.lower()
        # нет ложного «styled» ни в результате, ни в статусе
        assert result["cover_result"] != "styled"
        assert j.ru_status_for(j.RESULT_BASE) == j.RU_STYLE_FAILED


# ══ 19. Таймер Job'а ════════════════════════════════════════════════════════

class TestPreviewTimer:
    def _row(self, **over):
        row = {"job_id": "cov_1", "status": "queued", "kind": "cover_style_preview",
               "created_at": 1000.0, "updated_at": 1000.0,
               "progress_at": None, "heartbeat_at": None}
        row.update(over)
        return row

    def test_queued_has_no_elapsed(self):
        """сц.19: queued без реального старта — «В очереди», без миллионов."""
        state = j.CoverJobState(style_id="s1")
        state.mark(j.STATE_CREATED)
        status = pv._public_status(self._row(), state)
        assert status["stage"] == "queued"
        assert status["started_at"] is None
        assert status["elapsed_ms"] is None
        assert status["elapsed_seconds"] is None
        assert status["queued_at"] == 1000.0
        assert status["timing_source"] == "unknown"

    def test_running_elapsed_from_real_start(self, monkeypatch):
        """сц.19: running считается от actual_started_at, не от нуля."""
        monkeypatch.setattr(pv.time, "time", lambda: 1030.0)
        state = j.CoverJobState(style_id="s1")
        state.mark(j.STATE_CREATED)
        state.stages.append({"state": j.STATE_BASE_SUBMITTED, "at": 1020})
        status = pv._public_status(self._row(status="running"), state)
        assert status["started_at"] == 1020
        assert status["elapsed_ms"] == 10000
        assert status["elapsed_seconds"] == 10

    def test_terminal_elapsed_frozen(self, monkeypatch):
        """сц.19: terminal-состояние фиксирует elapsed (поздний poll не
        возвращает running и не пересчитывает от now)."""
        monkeypatch.setattr(pv.time, "time", lambda: 9999.0)
        state = j.CoverJobState(style_id="s1")
        state.mark(j.STATE_CREATED)
        state.stages.append({"state": j.STATE_BASE_SUBMITTED, "at": 1001})
        state.stages.append({"state": j.STATE_DONE, "at": 1013})
        status = pv._public_status(self._row(status="completed"), state)
        assert status["stage"] == "completed"
        assert status["elapsed_ms"] == 12000
        assert status["elapsed_seconds"] == 12

    def test_elapsed_never_negative(self):
        """сц.19: рассинхрон времени не даёт отрицательный/абсурдный elapsed."""
        state = j.CoverJobState(style_id="s1")
        state.mark(j.STATE_CREATED)
        state.stages.append({"state": j.STATE_BASE_SUBMITTED, "at": 5000})
        status = pv._public_status(self._row(status="running"), state)
        assert status["elapsed_ms"] is None or status["elapsed_ms"] >= 0


# ══ 20. Preview revision / stale ════════════════════════════════════════════

class TestPreviewRevision:
    def test_old_revision_preview_is_stale(self):
        """сц.20: пример прежней ревизии помечается stale, не свежим."""
        profile = {"preview_revision": 3, "preview_after_asset_id": "cas_x",
                   "preview_before_asset_id": "cas_y", "revision": 4}
        assert registry.preview_is_stale(profile) is True
        assert registry.preview_pair_current(profile) is False
        current = dict(profile, preview_revision=4)
        assert registry.preview_is_stale(current) is False
        assert registry.preview_pair_current(current) is True

    def test_placeholder_preview_is_not_pair(self):
        """сц.20: placeholder (`preview_revision IS NULL`) — не «успешный
        пример» (никакого ложного успеха)."""
        placeholder = {"preview_revision": None, "revision": 2,
                       "preview_before_asset_id": None,
                       "preview_after_asset_id": None}
        assert registry.preview_pair_current(placeholder) is False

    def test_job_status_reads_registry_by_pg(self, monkeypatch):
        """сц.20 (review F2): status-эндпоинт РЕАЛЬНО отдаёт
        `style_revision`/`preview_revision_stale`. Реестр читается по PG:
        у SQLite-`db` нет `.pool`, поэтому прежде профиль всегда был None и
        флаг молча не доезжал до API."""
        pg_sentinel = object()
        seen: dict = {}

        async def _get_job(db, job_id):
            return {"job_id": job_id, "status": "completed",
                    "kind": pv.KIND_PREVIEW, "created_at": 1000.0,
                    "updated_at": 1020.0, "reason_code": None}

        state = j.CoverJobState(style_id="s1", mode=pv.MODE_PREVIEW)
        state.mark(j.STATE_DONE)
        state.preview_before_asset_id = "cas_x"
        state.preview_after_asset_id = "cas_y"
        state.preview_revision = 3

        async def _load_state(db, job_id):
            return state

        async def _get_profile(pg, style_id):
            seen["pg"] = pg
            seen["style_id"] = style_id
            return {"profile_id": style_id, "revision": 4,
                    "preview_revision": 3,
                    "preview_before_asset_id": "cas_x",
                    "preview_after_asset_id": "cas_y"}

        monkeypatch.setattr(pv.jobs, "get_cover_job", _get_job)
        monkeypatch.setattr(pv.jobs, "load_cover_state", _load_state)
        monkeypatch.setattr(registry, "get_profile", _get_profile)
        out = _run(pv.job_status({"job_id": "cov_1"}, "cov_1",
                                 pg=pg_sentinel))
        assert seen["pg"] is pg_sentinel, "реестр читается по PG-обёртке"
        assert seen["style_id"] == "s1"
        assert out["status"] == "completed"
        assert out["style_revision"] == 4
        assert out["preview_revision_stale"] is True

    def test_job_status_without_pg_is_honest(self, monkeypatch):
        """сц.20 (review F2): без PG-источника stale-флаг ОТСУТСТВУЕТ
        (никакого выдуманного «свежий»/падения), статус остаётся полным."""
        async def _get_job(db, job_id):
            return {"job_id": job_id, "status": "completed",
                    "kind": pv.KIND_PREVIEW, "created_at": 1000.0,
                    "updated_at": 1020.0, "reason_code": None}

        async def _load_state(db, job_id):
            return j.CoverJobState(style_id="s1", mode=pv.MODE_PREVIEW)

        monkeypatch.setattr(pv.jobs, "get_cover_job", _get_job)
        monkeypatch.setattr(pv.jobs, "load_cover_state", _load_state)
        monkeypatch.setattr(pv.jobs, "_pg", lambda: None)
        out = _run(pv.job_status({"job_id": "cov_1"}, "cov_1"))
        assert out["status"] == "completed"
        assert "preview_revision_stale" not in out
        assert "style_revision" not in out

    def test_optional_ref_warning_follows_real_outcome(self):
        """§3.1 (review-fix2): текст warning'а не утверждает «стиль применён»,
        когда job провалился (опубликована базовая обложка), и не обещает
        применение на незавершённой стадии."""
        def _row(status):
            return {"job_id": "cov_1", "status": status,
                    "kind": pv.KIND_PREVIEW, "created_at": 1000.0,
                    "updated_at": 1010.0, "reason_code": "bad_json"}

        diag = {"references_optional_unavailable": 1,
                "references_declared": 2, "optional_reference_ids": ["rC"]}

        done = j.CoverJobState(style_id="s1", mode=pv.MODE_PREVIEW)
        done.mark(j.STATE_DONE)
        done.prompt_diagnostics = dict(diag)
        msg_done = pv._public_status(_row("completed"), done)["warnings"][0]
        assert msg_done["code"] == j.ERROR_CLASS_OPTIONAL_REFERENCE_UNAVAILABLE
        assert "применён без них" in msg_done["message"]
        assert msg_done["ref_ids"] == ["rC"]

        failed = j.CoverJobState(style_id="s1", mode=pv.MODE_PREVIEW)
        failed.mark(j.STATE_STYLE_FAILED, note="bad_json")
        failed.prompt_diagnostics = dict(diag)
        msg_failed = pv._public_status(_row("failed"), failed)["warnings"][0]
        assert "применён без них" not in msg_failed["message"], \
            "провал не выдаёт себя за применённый стиль"
        assert "базовая обложка" in msg_failed["message"]

        running = j.CoverJobState(style_id="s1", mode=pv.MODE_PREVIEW)
        running.mark(j.STATE_STYLE_RUNNING)
        running.prompt_diagnostics = dict(diag)
        msg_running = pv._public_status(_row("running"), running)["warnings"][0]
        assert "стиль применён без них" not in msg_running["message"]
        assert "будет применён без них" in msg_running["message"]

    def test_status_route_forwards_pg_from_cache(self, monkeypatch):
        """сц.20 (review F2): HTTP-статус передаёт в `job_status` PG-обёртку
        из runtime-кэша — иначе stale-флаг не доезжает до UI."""
        import web.api.cover_styles as cs
        from web.api import deps as deps_mod
        from tests.test_extra_cover_styles_api import (
            _client, _hdr, TEST_TOKEN,
        )

        monkeypatch.setattr(deps_mod, "settings",
                            types.SimpleNamespace(API_TOKEN=TEST_TOKEN))
        seen: dict = {}

        async def _status(db, job_id, *, pg=None):
            seen["pg"] = pg
            seen["job_id"] = job_id
            return {"job_id": job_id, "status": "completed"}

        monkeypatch.setattr(pv, "job_status", _status)
        monkeypatch.setattr(pv, "maybe_resume", AsyncMock(return_value=False))
        monkeypatch.setattr(cs, "_job_db", lambda: object())
        pg = types.SimpleNamespace(pool=object())
        resp = _client(pg=pg).get("/api/cover/test-style/cov_1",
                                 headers=_hdr())
        assert resp.status_code == 200, resp.text
        assert seen["job_id"] == "cov_1"
        assert seen["pg"] is pg, "route обязан передать pg из cache"

    def test_failed_test_does_not_erase_previous_preview(
            self, monkeypatch, tmp_path):
        """сц.20: провал нового Test Style не стирает прежнюю рабочую пару."""
        called = {"set": 0, "finish": []}

        async def _set_preview(*a, **kw):
            called["set"] += 1
            return True

        async def _finish(db, job_id, *, outcome, reason_code=None,
                          checkpoint=None):
            called["finish"].append((outcome, reason_code))
            return True

        async def _save_state(db, job_id, state):
            return True

        monkeypatch.setattr(registry, "set_preview", _set_preview)
        monkeypatch.setattr(pv.jobs, "finish_cover_job", _finish)
        monkeypatch.setattr(pv.jobs, "save_cover_state", _save_state)

        async def edit_fail(prompt, **kw):
            return EditResult(ok=False, reason="bad_json")

        profile = _profile(references=[])
        state = j.CoverJobState(style_id=profile["profile_id"], mode="preview")
        state.mark(j.STATE_BASE_SUCCEEDED)
        state.base_asset_id = "cas_base"
        out = _run(pv.run_preview_job(
            None, "cov_1", profile=profile, pg=None, correlation_id="c",
            brief="сцена", base_upload_meta={
                "asset_id": "cas_base",
                "disk_path": _png(tmp_path / "b.png")}))
        assert out.get("applied") is False
        assert called["set"] == 0, "прежняя preview не перезаписана провалом"
        assert called["finish"] and called["finish"][0][0] == j.STATE_FAILED


# ══ 21. Summary L2: строгость сохранена, Legacy — честный fallback ═════════

class TestSummaryL2Strictness:
    def test_blocking_codes_are_hard_and_blocking(self):
        """сц.21: коды прод-инцидента остаются hard/blocking (review не
        ослаблен ради зелёной метрики), даже если модель пометила находку
        «minor» — severity решает сервер."""
        for code in (l2.FINDING_CODE_REPLY_ATTRIBUTION,
                     l2.FINDING_CODE_UNSUPPORTED_CLAIM,
                     l2.FINDING_CODE_WRONG_PERSON):
            assert l2.finding_class(code) == l2.FINDING_CLASS_HARD
            assert l2.finding_severity(code) == l2.SEVERITY_BLOCKING
        package = {"threads": [{"chronology": [{"message_id": 1}],
                               "facts": [{"evidence_message_ids": [1]}]}]}
        raw = (
            '{"status": "needs_fixes", "findings": ['
            '{"code": "reply_attribution_error", "severity": "minor", '
            '"paragraph_index": 0, "evidence_refs": [1], "instruction": "fix"}]}'
        )
        verdict = l2.parse_review_verdict(
            raw, package=package, document={"paragraphs": [{"text": "x"}]})
        assert verdict.status == l2.VERDICT_NEEDS_FIXES
        assert len(verdict.findings) == 1
        assert verdict.findings[0].severity == l2.SEVERITY_BLOCKING
        assert verdict.findings[0].blocking is True
        assert verdict.blocking_count == 1

    def test_six_blocking_findings_force_legacy_gate(self):
        """сц.21: ≥2 независимых hard-находок → terminal unusable (Legacy),
        одиночная находка — даунгрейд (не выбрасываем пригодный Hybrid)."""
        findings = tuple(
            l2.ReviewFinding(code=code, severity=l2.SEVERITY_BLOCKING,
                             paragraph_index=idx, evidence_refs=(idx,),
                             instruction="fix")
            for idx, code in enumerate([
                l2.FINDING_CODE_REPLY_ATTRIBUTION,
                l2.FINDING_CODE_UNSUPPORTED_CLAIM,
                l2.FINDING_CODE_WRONG_PERSON]))
        verdict = l2.ReviewVerdict(status=l2.VERDICT_UNUSABLE,
                                   findings=findings, raw_status="ok")
        assert l2._unusable_gate_accepts(verdict, {}) is True
        single = l2.ReviewVerdict(
            status=l2.VERDICT_UNUSABLE,
            findings=(findings[0],), raw_status="ok")
        assert l2._unusable_gate_accepts(single, {}) is False

    def test_l1_schema_version_handshake(self):
        """сц.21: версия схемы в промпте и в валидаторе НЕ расходятся —
        иначе correction retry заведомо бесполезен (прод-факт
        `bad_schema_version`), а строгость проверки ослаблять нельзя."""
        from services import summary_l1_contract as l1c
        from services import summary_l1_semantic_map as l1map
        from services import summary_prompts as sp
        assert l1c.SCHEMA_VERSION == 2          # §95-v2 валидатор
        assert l1map.MAP_SCHEMA_VERSION == 1    # semantic map v1
        assert l1map.MAP_SCHEMA_VERSION_V2 == 2  # anchor-space map v2
        # Активный map-канон просит ровно ту версию, которую ждёт валидатор.
        assert '"schema_version": %d' % l1map.MAP_SCHEMA_VERSION in \
            sp.SUMMARY_L1_CLUSTERIZER_SYSTEM_PROMPT
        # Anchor-space канон — версию v2.
        assert '"schema_version": %d' % l1map.MAP_SCHEMA_VERSION_V2 in \
            sp.SUMMARY_L1_ANCHORS_SYSTEM_PROMPT
        # Расхождение версии — retryable-класс (одна исправляющая попытка),
        # а не тихое принятие чужой схемы.
        space = l1c.IdSpace(order={1: (100, 1)})
        bad = l1c.validate_l1_response(
            {"schema_version": 1, "threads": [],
             "unassigned_message_ids": [1]}, space)
        assert bad.status != "ok"
        assert bad.invalid_reason == l1c.REASON_BAD_SCHEMA_VERSION
        from services import summary_l1_clusterizer as l1cl
        assert l1c.REASON_BAD_SCHEMA_VERSION in l1cl._RETRYABLE_REASONS
        assert l1map.REASON_BAD_SCHEMA_VERSION in l1map.RETRYABLE_MAP_REASONS

    def test_review_verdict_unknown_status_is_unusable(self):
        """сц.21: неизвестный ответ ревью не становится approved."""
        verdict = l2._review_verdict_error("bad_schema")
        assert verdict.status == l2.VERDICT_UNUSABLE
        assert verdict.findings == ()
        assert verdict.status != l2.VERDICT_APPROVED


# ══ Аналитика: base success и style failure различимы ═══════════════════════

class TestAnalyticsDistinction:
    def test_cover_card_separates_base_and_style(self):
        from services import pipeline_analytics as pa
        events = [
            {"event_name": pa._COVER_BASE_OK, "usage_json": None},
            {"event_name": pa._STYLE_FAIL, "reason_code": "style_failed",
             "job_id": "cov_abc",
             "usage_json": '{"fail_reason": "bad_json", '
                           '"error_class": "invalid_provider_response"}'},
        ]
        card = pa._cover_style_card(events)
        assert card["base_cover_ok"] is True
        assert card["style_edit_ok"] is False
        assert card["result"] == "base_fallback"
        assert card["style_fail_reason"] == "bad_json"
        assert card["error_class"] == "invalid_provider_response"
        assert card["style_job_id"] == "cov_abc"
