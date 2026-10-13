"""ASAP 8 v6 C03A (P0) — recovery-контур styled cover.

Owner-симптом: «Base появляется, styled не появляется / не восстанавливается».
Покрывает обязательные кейсы v6 (plans/ASAP8_v6_delta_after_F1-F9.md §C03A)
на реальном durable-контуре (task_jobs через DatabaseService(":memory:")),
провайдер замокан (edit_call/image generation):

  1. happy path: styled привязан к тому же summary run (provenance run_id +
     base/final asset, manifest, durable styled-артефакт);
  2. Base success + style fail → Base опубликована, честный styled_status
     {reason,route,attempt}; ПОВТОРНАЯ ПОПЫТКА (recovery) восстанавливает
     styled БЕЗ второй генерации Base и БЕЗ дубля публикации;
  3. restart посреди style → durable job НЕ completed (interrupted), не
     зацикливается: permanent-классификация не ретраится, transient —
     bounded (max_attempts) с backoff;
  4. Explicit Style OFF → Base финальный по намерению: reason
     `style_disabled`, не false success / false style_failed;
  5. content-loss сигнал: текст-ответ провайдера →
     `semantic_preservation_failed` + Base; битые байты →
     `invalid_image_payload` + Base; валидное изображение → честная метка
     `semantic_verification=unverified`;
  6. regression: один style-profile на два разных сюжета не схлопывает
     story identity в generic scene (story-текст попадает в промпт);

  + watchdog-шов: sweep → kick_cover_style_recovery → зомби дообработан.

TEST-LIFECYCLE: REGRESSION owner=ASAP8-v6/C03A
TEST-LIFECYCLE: CONTRACT owner=ASAP8-v6/C03A
R17: фикстуры — синтетика (свои байты/тексты), секретов и реальных промптов
нет; полные compiled-промпты не логируются.
"""
import asyncio
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import cover_style_jobs as j
from services import cover_style_registry as registry
from services import mca_watchdog as wd
from services import summary_generator as sg
from services.cover_style_edit import EditResult
from services.image_capabilities import (
    TRUE, ImageModelCapabilities, PromptLimit,
)
from services.task_supervisor import TaskJobStore

CHAT = -100266
RID = "c03a-run-0001"

# Валидный JPEG (магия \xff\xd8\xff) — синтетический «успешный» ответ
# style-провайдера (payload-валидация обязана пропускать).
STYLE_IMG = b"\xff\xd8\xff\xe0" + b"7" * 64
BASE_PNG = b"\x89PNG\r\n\x1a\n" + b"b" * 48
# Текстовый ответ модели вместо изображения (потеря сцены проверяемо).
MODEL_TEXT = b"Sorry, I cannot edit this image. Here is a description instead."


# ── fixtures/helpers ────────────────────────────────────────────────────────

def _profile(**over):
    p = {
        "profile_id": "csp_c03a", "name": "C03A", "origin": "custom",
        "pipeline_mode": "generate_then_edit",
        "instruction": "Нормализуй обложку под издательский знак серии.",
        "counter_enabled": True, "counter_value": 0,
        "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
        "connection_id": None, "model_id": None, "revision": 1,
        "enabled": True, "references": [],
    }
    p.update(over)
    return p


def _caps():
    return ImageModelCapabilities(
        image_edit=TRUE, max_input_images=3,
        prompt_limit=PromptLimit(value=4000, unit="chars",
                                 source="internal_config"))


class _FakePg:
    pool = object()


async def _fresh_db():
    from services.database import DatabaseService
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


class _MemoryDb(SimpleNamespace):
    """FakeMemory-совместимая память с реальным db для durable-джобы."""


def _flag(monkeypatch, value):
    import config.settings as _cs
    from config.settings import Settings as _S
    for cls in {_S, type(_cs.settings), type(j.settings)}:
        monkeypatch.setattr(cls, "COVER_STYLE_SNAPSHOT_ENABLED", value,
                            raising=False)


def _sflag(monkeypatch, name, value):
    import config.settings as _cs
    from config.settings import Settings as _S
    for cls in {_S, type(_cs.settings), type(j.settings)}:
        monkeypatch.setattr(cls, name, value, raising=False)


@pytest.fixture(autouse=True)
def _c03a_env(monkeypatch, tmp_path):
    """Snapshot ON (прод-дефолт); recovery-каталог в tmp; слот сконфигурирован."""
    _flag(monkeypatch, True)
    monkeypatch.setenv("COVER_STYLE_RECOVERY_DIR", str(tmp_path / "recovery"))

    async def _slot(*, profile, connection, pg=None):
        return {"base_url": "https://edit.example/v1",
                "model": "qwen-image-edit", "provider": "edit.example",
                "connection_id": "default", "custom_unresolved": False,
                "configured": True}

    monkeypatch.setattr(j, "resolve_style_slot_inherited", _slot)
    monkeypatch.setattr(j, "cover_styles_enabled", lambda: True)
    monkeypatch.setattr(j, "_pg", lambda: _FakePg())
    yield


def _patch_selection(monkeypatch, profile, style_id="csp_c03a"):
    async def _resolve(chat_id):
        return style_id

    async def _get(pg, sid):
        return profile if sid == profile["profile_id"] else None

    monkeypatch.setattr(j, "resolve_selected_style_id", _resolve)
    monkeypatch.setattr(registry, "get_profile_with_refs", _get)


def _patch_provenance(monkeypatch):
    class _Spy:
        def __init__(self):
            self.rows = []

        async def __call__(self, pg, data):
            self.rows.append(data)
            return "covp-x"

    spy = _Spy()
    monkeypatch.setattr(registry, "record_provenance", spy)
    return spy


def _patch_issue_counter(monkeypatch):
    """Идемпотентный pin (зеркало реального PG-контракта §27: retry reuse)."""
    assigned = {}

    async def _resolve(pg, profile_id, run_id):
        key = (profile_id, run_id)
        if key not in assigned:
            assigned[key] = len(assigned) + 1
        return assigned[key]

    monkeypatch.setattr(registry, "resolve_issue_number", _resolve)
    return assigned


def _gen(monkeypatch, db, tmp_path, *, base_bytes=BASE_PNG):
    """SummaryGenerator с реальным db, замоканными image-gen/rich-отправкой."""
    from tests.test_summary_generator import FakeMemory
    from services.summary_xml import XmlGroundingBuilder

    gen = sg.SummaryGenerator(FakeMemory(), XmlGroundingBuilder(),
                              MagicMock(), AsyncMock())
    gen.memory = _MemoryDb(db=db)
    gen._resolve_cover_style_text = AsyncMock(return_value="cinematic")

    counts = {"image": 0}

    async def _img(prompt, **kw):
        counts["image"] += 1
        path = tmp_path / ("base_%d.png" % counts["image"])
        path.write_bytes(base_bytes)
        return str(path), "ok"

    monkeypatch.setattr(sg, "generate_image_verbose", _img)
    media = []
    media_bytes = []

    def _media(path, **kw):
        media.append(path)
        try:
            with open(path, "rb") as fh:
                media_bytes.append(fh.read())
        except OSError:
            media_bytes.append(None)   # temp-файл уже удалён публикацией
        return "M"

    monkeypatch.setattr(sg, "build_cover_media", _media)
    sends = {"rich": 0}

    async def _rich(bot, chat_id, text, *, media=None, cover_id=None, **kw):
        sends["rich"] += 1
        return SimpleNamespace(message_id=4321)

    monkeypatch.setattr(sg, "send_rich_message", _rich)
    monkeypatch.setattr(sg, "send_text",
                        AsyncMock(return_value=SimpleNamespace(message_id=1)))
    monkeypatch.setattr(sg, "_rich_media_supported", lambda: True)
    gen._c03a_media = media
    gen._c03a_media_bytes = media_bytes
    gen._c03a_sends = sends
    gen._c03a_image_counts = counts
    return gen


def _lines(caplog, needle):
    return [r.getMessage() for r in caplog.records if needle in r.getMessage()]


async def _job_state(db, run_id, style_id="csp_c03a"):
    jid = j.cover_job_key(summary_run_id=run_id, style_id=style_id)
    return jid, await j.load_cover_state(db, jid)


def _make_edit_script(script):
    """edit_call по сценарию: список EditResult/исключений, затем последний."""
    calls = {"prompts": [], "n": 0}

    async def _edit(prompt, **kw):
        calls["n"] += 1
        calls["prompts"].append(str(prompt))
        idx = min(calls["n"] - 1, len(script) - 1)
        item = script[idx]
        if isinstance(item, Exception):
            raise item
        return item

    _edit.calls = calls
    return _edit


def _doc():
    return {"schema_version": 1, "title": "Т",
            "paragraphs": [{"text": "Первый абзац.", "emphasis": None}]}


# ══ кейс 1: happy path — styled привязан к run ══════════════════════════════

class TestCase1HappyPath:
    @pytest.mark.asyncio
    async def test_styled_linked_to_same_run(self, monkeypatch, tmp_path,
                                             caplog):
        db = await _fresh_db()
        try:
            profile = _profile()
            _patch_selection(monkeypatch, profile)
            prov = _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            edit = _make_edit_script([
                EditResult(ok=True, content=STYLE_IMG, reason="ok",
                           latency_ms=10)])
            monkeypatch.setattr(j, "edit_image", edit)
            gen = _gen(monkeypatch, db, tmp_path)
            with caplog.at_level(logging.INFO):
                published = await gen._publish_rich_document(
                    CHAT, _doc(), "Медведь идёт по лесу.",
                    correlation_id=RID)
            assert published is True
            # styled (не Base) уехал в публикацию
            assert gen._c03a_image_counts["image"] == 1      # Base один раз
            assert edit.calls["n"] == 1
            assert gen._c03a_media and gen._c03a_media[0].endswith(".jpg")
            assert gen._c03a_media_bytes[0] == STYLE_IMG
            # привязка к тому же run: provenance styled c run/base/final
            styled_rows = [r for r in prov.rows
                           if r.get("status") == "styled"]
            assert styled_rows, prov.rows
            row = styled_rows[0]
            assert row["summary_run_id"] == RID
            assert row["job_id"] and row["job_id"].startswith("cov_")
            assert row["base_asset_id"] and row["final_asset_id"]
            assert row["final_asset_id"] != row["base_asset_id"]
            # durable styled-артефакт + честный semantic-статус
            jid, state = await _job_state(db, RID)
            assert state is not None
            assert state.styled_status == "styled"
            assert state.styled_asset_path and os.path.exists(
                state.styled_asset_path)
            prompts = await j.load_run_cover_prompts(db, RID)
            manifest = prompts["style"]
            assert manifest is not None
            assert prompts["cover_prompts_status"]["style"] == "ok"
            assert manifest["semantic_verification"]["status"] == "unverified"
            assert manifest["styled_status"]["status"] == "styled"
            # Base-манифест того же run существует (обе стадии связаны run'ом)
            assert prompts["base"] is not None
        finally:
            await db.close()


# ══ кейс 2: style fail → Base + retry восстанавливает styled ════════════════

class TestCase2RetryWithoutSecondBase:
    @pytest.mark.asyncio
    async def test_transient_fail_then_recovery_restores_styled(
            self, monkeypatch, tmp_path, caplog):
        db = await _fresh_db()
        try:
            profile = _profile()
            _patch_selection(monkeypatch, profile)
            prov = _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            edit = _make_edit_script([
                EditResult(ok=False, reason="timeout", latency_ms=5),
                EditResult(ok=True, content=STYLE_IMG, reason="ok",
                           latency_ms=10)])
            monkeypatch.setattr(j, "edit_image", edit)
            gen = _gen(monkeypatch, db, tmp_path)
            with caplog.at_level(logging.INFO):
                published = await gen._publish_rich_document(
                    CHAT, _doc(), "Медведь идёт по лесу.",
                    correlation_id=RID)
            # Base опубликована (styled нет)
            assert published is True
            assert gen._c03a_image_counts["image"] == 1      # Base ОДИН раз
            assert edit.calls["n"] == 1
            assert gen._c03a_media_bytes[0] == BASE_PNG
            sends_after_publish = gen._c03a_sends["rich"]
            # честный styled_status: transient + живой бюджет →
            # retry_scheduled {reason, route, attempt} (после исчерпания —
            # failed; причина/route/attempt видны в обоих случаях)
            jid, state = await _job_state(db, RID)
            assert state.styled_status == "retry_scheduled"
            assert state.styled_fail_reason == "timeout"
            assert state.base_asset_path and os.path.exists(
                state.base_asset_path)
            row = await TaskJobStore(db).get(jid)
            assert row["status"] == "completed"      # публикация завершена
            assert row["reason_code"] == "timeout"
            scheduled = _lines(caplog, "COVER_STYLE_RETRY_SCHEDULED")
            assert scheduled and "reason=timeout" in scheduled[0]
            base_prov = [r for r in prov.rows if r.get("status") == "base"]
            assert base_prov and base_prov[0]["summary_run_id"] == RID

            # ── ПОВТОРНАЯ ДОПУСТИМАЯ ПОПЫТКА (recovery sweep) ──
            monkeypatch.setattr(j, "edit_image", edit)  # тот же счётчик
            with caplog.at_level(logging.INFO):
                actions = await j.recover_cover_style_jobs(db, limit=1)
            assert actions and actions[0]["action"] == "recovered"
            # НЕ второй Base: генератор Base не вызывался повторно
            assert gen._c03a_image_counts["image"] == 1
            # ровно один повтор style-edit (итого 2), тот же issue-номер
            assert edit.calls["n"] == 2
            issue_token = "ВЫПУСК 1"
            assert issue_token in edit.calls["prompts"][0]
            assert issue_token in edit.calls["prompts"][1]
            # БЕЗ дубля публикации: rich-отправка не повторялась
            assert gen._c03a_sends["rich"] == sends_after_publish
            # styled восстановлен и связан с тем же run
            jid2, state2 = await _job_state(db, RID)
            assert state2.styled_status == "styled"
            assert state2.retry_count == 1
            assert state2.styled_asset_path and os.path.exists(
                state2.styled_asset_path)
            styled_after = [r for r in prov.rows
                            if r.get("status") == "styled"]
            assert styled_after \
                and styled_after[0]["summary_run_id"] == RID
            prompts = await j.load_run_cover_prompts(db, RID)
            assert prompts["style"]["styled_status"]["status"] == "styled"
            recovered = _lines(caplog, "COVER_STYLE_RECOVERED")
            assert recovered
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_permanent_fail_is_not_retried(self, monkeypatch, tmp_path):
        db = await _fresh_db()
        try:
            profile = _profile()
            _patch_selection(monkeypatch, profile)
            _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            edit = _make_edit_script([
                EditResult(ok=False, reason="edit_unsupported",
                           latency_ms=1)])
            monkeypatch.setattr(j, "edit_image", edit)
            gen = _gen(monkeypatch, db, tmp_path)
            published = await gen._publish_rich_document(
                CHAT, _doc(), "Сюжет.", correlation_id=RID)
            assert published is True
            jid, state = await _job_state(db, RID)
            # permanent (модель без edit) — честный failed, не retry_scheduled
            assert state.styled_status == "failed"
            assert state.styled_fail_reason == "edit_unsupported"
            assert state.styled_route  # route виден в Inspector-структуре
            # recovery-проход: никакого retry, edit не вызван снова
            actions = await j.recover_cover_style_jobs(db, limit=3)
            assert actions == []
            assert edit.calls["n"] == 1
        finally:
            await db.close()


# ══ REV-WAVE-B F1 (Critical): идемпотентность recovery для УЖЕ УСПЕШНЫХ ═════

class TestCaseRecoveryIdempotentSuccess:
    async def _mk_legacy_success(self, db, *, run_id, styled_status="styled",
                                 state_state=None):
        """Legacy-успех: task_jobs completed + cursor со styled-результатом,
        БЕЗ base_asset_path (старый формат durable-состояния)."""
        import json as _json
        import uuid
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        jid = "cov_c03a_legacy_%s" % uuid.uuid4().hex[:8]
        state = j.CoverJobState(style_id="csp_c03a",
                                mode=j.MODE_PRODUCTION)
        state.mark(state_state or j.STATE_STYLE_SUCCEEDED)
        state.styled_status = styled_status
        state.styled_fail_reason = None
        # base_asset_path/styled_asset_path остаются None — legacy-успех без
        # durable-артефактов; раньше первый же sweep валил его в
        # failed/base_asset_missing.
        await store.enqueue(
            owner="summary", kind="cover_style",
            coalesce_key="cover_style:%s" % run_id,
            payload=_json.dumps({"chat_id": CHAT, "correlation_id": run_id,
                                 "cursor": state.to_json()}),
            job_id=jid)
        await store.mark_running(jid)
        await store.finish(jid, status="completed", reason_code=None)
        return jid

    @pytest.mark.asyncio
    async def test_happy_path_recovery_makes_no_paid_calls(
            self, monkeypatch, tmp_path):
        """Успешный styled (production-инлайн: cursor STATE_STYLE_SUCCEEDED,
        task_jobs completed) → recovery-проходы (в т.ч. повторные — как
        watchdog каждые ~600с) НЕ делают платных edit-вызовов и не меняют
        статус/manifest. Раньше: sweep 1/2 → recovered (edit №2/№3), sweep 3 →
        ложный failed/recovery_exhausted."""
        db = await _fresh_db()
        try:
            profile = _profile()
            _patch_selection(monkeypatch, profile)
            _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            edit = _make_edit_script([
                EditResult(ok=True, content=STYLE_IMG, reason="ok",
                           latency_ms=10)])
            monkeypatch.setattr(j, "edit_image", edit)
            gen = _gen(monkeypatch, db, tmp_path)
            published = await gen._publish_rich_document(
                CHAT, _doc(), "Медведь идёт по лесу.", correlation_id=RID)
            assert published is True
            jid, state = await _job_state(db, RID)
            assert state.styled_status == "styled"
            row_before = await TaskJobStore(db).get(jid)
            assert row_before["status"] == "completed"
            manifest_before = \
                (await j.load_run_cover_prompts(db, RID))["style"]

            # Повторные recovery-проходы: ровно ничего не происходит
            for _ in range(3):
                assert await j.recover_cover_style_jobs(db, limit=3) == []
            assert edit.calls["n"] == 1            # платный вызов ОДИН (инлайн)
            row_after = await TaskJobStore(db).get(jid)
            assert row_after["status"] == "completed"
            assert row_after["reason_code"] == row_before["reason_code"]
            _, state2 = await _job_state(db, RID)
            assert state2.styled_status == "styled"
            assert state2.state == j.STATE_STYLE_SUCCEEDED
            manifest_after = \
                (await j.load_run_cover_prompts(db, RID))["style"]
            assert manifest_after == manifest_before
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_legacy_completed_styled_not_failed_by_sweep(
            self, monkeypatch, tmp_path):
        """Старые completed-строки с успешным styled (cursor без
        base_asset_path) recovery не трогает: не failed/base_asset_missing,
        0 edit-вызовов, статус остаётся completed. Оба варианта признака
        успеха: styled_status='styled' и голый STATE_STYLE_SUCCEEDED."""
        db = await _fresh_db()
        try:
            for i, (styled_status, state_state) in enumerate(
                    [("styled", None), (None, j.STATE_STYLE_SUCCEEDED)]):
                run_id = "%s-leg%d" % (RID, i)
                jid = await self._mk_legacy_success(
                    db, run_id=run_id, styled_status=styled_status,
                    state_state=state_state)
                row_before = await TaskJobStore(db).get(jid)
                assert row_before["status"] == "completed"
            actions = await j.recover_cover_style_jobs(db, limit=5)
            assert actions == []
            cursor = await db.db.execute(
                "SELECT job_id, status, reason_code FROM task_jobs "
                "WHERE kind = 'cover_style' AND status = 'failed'")
            assert await cursor.fetchall() == []    # никто не переведён в failed
        finally:
            await db.close()


# ══ кейс 3: restart посреди style → зомби дообрабатывается, bounded ═════════

class TestCase3RestartSafety:
    async def _make_zombie(self, db, tmp_path, *, run_id=RID):
        """Продукционные хелперы: job => running => (процесс умер) => stale.

        Base-манифест run создаётся как в проде (до style-стадии) — из него
        recovery восстанавливает компиляционные входы."""
        from services import cover_prompt_assembly as cpa
        base = tmp_path / "base.png"
        base.write_bytes(BASE_PNG)
        manifest = cpa.build_base_manifest(
            base_style="cinematic", story_scene="Медведь идёт по лесу.",
            summary_context="Т. Первый абзац.",
            final_prompt="MEDVED STORY. Т. Первый абзац. cinematic")
        await j.record_base_cover_manifest(db, summary_run_id=run_id,
                                           chat_id=CHAT, manifest=manifest)
        jid, state = await j.begin_cover_job(
            db, chat_id=CHAT, correlation_id=run_id, style_id="csp_c03a",
            summary_run_id=run_id, payload={"mode": "production"})
        store = TaskJobStore(db)
        await store.mark_running(jid)
        state.base_asset_path = j.persist_style_artifact(run_id, str(base),
                                                         "base")
        state.mark(j.STATE_STYLE_SUBMITTED)
        await j.save_cover_state(db, jid, state)
        # время прошло: heartbeat протух → recover_stale металл зомби
        cursor = await db.db.execute(
            "UPDATE task_jobs SET heartbeat_at = ? WHERE job_id = ?",
            (int(asyncio.get_event_loop().time()) - 10 ** 6, jid))
        await cursor.fetchone()
        return jid, store

    @pytest.mark.asyncio
    async def test_restart_mid_style_job_not_completed_then_recovered(
            self, monkeypatch, tmp_path, caplog):
        db = await _fresh_db()
        try:
            profile = _profile()
            monkeypatch.setattr(registry, "get_profile_with_refs",
                                AsyncMock(return_value=profile))
            prov = _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            jid, store = await self._make_zombie(db, tmp_path)
            # рестарт-контур: recover_stale помечает потерянного владельца
            recovered_ids = await store.recover_stale(stale_after_seconds=1)
            assert jid in recovered_ids
            row = await store.get(jid)
            # НЕ completed: durable pending не помечается успешным
            assert row["status"] == "interrupted"
            # recovery дообрабатывает с СОХРАНЁННОЙ Base
            edit = _make_edit_script([
                EditResult(ok=True, content=STYLE_IMG, reason="ok",
                           latency_ms=10)])
            monkeypatch.setattr(j, "edit_image", edit)
            actions = await j.recover_cover_style_jobs(db, limit=1)
            assert actions and actions[0]["action"] == "recovered"
            assert edit.calls["n"] == 1
            _, state = await _job_state(db, RID)
            assert state.styled_status == "styled"
            assert os.path.exists(state.base_asset_path)
            styled_rows = [r for r in prov.rows
                           if r.get("status") == "styled"]
            assert styled_rows and styled_rows[0]["summary_run_id"] == RID
            row = await store.get(jid)
            assert row["status"] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_transient_recovery_is_bounded(self, monkeypatch, tmp_path):
        db = await _fresh_db()
        try:
            profile = _profile()
            monkeypatch.setattr(registry, "get_profile_with_refs",
                                AsyncMock(return_value=profile))
            _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            jid, store = await self._make_zombie(db, tmp_path)
            await store.recover_stale(stale_after_seconds=1)
            edit = _make_edit_script([
                EditResult(ok=False, reason="timeout", latency_ms=1)])
            monkeypatch.setattr(j, "edit_image", edit)
            far_future = 4_000_000_000
            # попытка 1 → retry_scheduled (backoff)
            actions = await j.recover_cover_style_jobs(db, limit=1,
                                                       now=1000)
            assert actions and actions[0]["action"] == "scheduled"
            _, state = await _job_state(db, RID)
            assert state.retry_count == 1
            assert state.styled_status == "retry_scheduled"
            # backoff ещё не истёк → новый проход ничего не делает
            assert await j.recover_cover_style_jobs(db, limit=1, now=1500) \
                == []
            # попытка 2 (после backoff) — бюджет исчерпан → честный failed
            actions = await j.recover_cover_style_jobs(
                db, limit=1, now=far_future)
            assert actions and actions[0]["action"] == "failed"
            _, state = await _job_state(db, RID)
            assert state.styled_status == "failed"
            assert state.retry_count == j.recovery_max_attempts()
            row = await store.get(jid)
            assert row["status"] == "failed"
            # bounded: третий проход не ретраит (не зацикливается)
            assert await j.recover_cover_style_jobs(
                db, limit=1, now=far_future + 10 ** 6) == []
            assert edit.calls["n"] == j.recovery_max_attempts()
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_watchdog_sweep_kicks_recovery(self, monkeypatch, tmp_path):
        """Интеграционный шов: watchdog sweep → kick → зомби восстановлен."""
        db = await _fresh_db()
        try:
            profile = _profile()
            monkeypatch.setattr(registry, "get_profile_with_refs",
                                AsyncMock(return_value=profile))
            _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            jid, store = await self._make_zombie(db, tmp_path)
            await store.recover_stale(stale_after_seconds=1)
            edit = _make_edit_script([
                EditResult(ok=True, content=STYLE_IMG, reason="ok",
                           latency_ms=10)])
            monkeypatch.setattr(j, "edit_image", edit)
            result = await wd.sweep(db, job_store=store)
            assert result.get("cover_style_recovery_kicked") in (True, False)
            kick_task = j._RECOVERY_KICK_TASK
            assert kick_task is not None
            await kick_task
            _, state = await _job_state(db, RID)
            assert state.styled_status == "styled"
        finally:
            await db.close()


# ══ кейс 4: explicit Style OFF → Base финальный по намерению ════════════════

class TestCase4StyleDisabled:
    @pytest.mark.asyncio
    async def test_no_style_selected_reason_style_disabled(
            self, monkeypatch, tmp_path, caplog):
        db = await _fresh_db()
        try:
            _patch_selection(monkeypatch, _profile(), style_id="")
            _patch_provenance(monkeypatch)
            gen = _gen(monkeypatch, db, tmp_path)
            with caplog.at_level(logging.INFO):
                published = await gen._publish_rich_document(
                    CHAT, _doc(), "Сюжет без стиля.", correlation_id=RID)
            assert published is True
            # Base опубликован как финал
            assert gen._c03a_image_counts["image"] == 1
            assert gen._c03a_media_bytes[0] == BASE_PNG
            # run-classification: style_disabled, не false style_failed
            done = _lines(caplog, "COVER_PIPELINE_DONE")
            assert done and "fallback=style_disabled" in done[0]
            # style-джобы для run НЕТ (нет и false success)
            cursor = await db.db.execute(
                "SELECT job_id FROM task_jobs WHERE coalesce_key = ?",
                ("cover_style:%s" % RID,))
            assert await cursor.fetchone() is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_master_kill_switch_reason_style_disabled(
            self, monkeypatch, tmp_path, caplog):
        db = await _fresh_db()
        try:
            monkeypatch.setattr(j, "cover_styles_enabled", lambda: False)
            gen = _gen(monkeypatch, db, tmp_path)
            skip = {}
            meta = await gen._maybe_apply_cover_style(
                CHAT, "base.png", RID, cover_prompt="Сюжет.",
                skip_out=skip)
            assert meta is None
            assert skip["reason"] == j.REASON_STYLE_DISABLED
        finally:
            await db.close()


# ══ кейс 5: semantic content-loss / payload-валидация ═══════════════════════

class TestCase5SemanticSignal:
    @pytest.mark.asyncio
    async def test_text_response_maps_to_semantic_preservation_failed(
            self, monkeypatch, tmp_path, caplog):
        db = await _fresh_db()
        try:
            profile = _profile()
            _patch_selection(monkeypatch, profile)
            prov = _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            edit = _make_edit_script([
                EditResult(ok=True, content=MODEL_TEXT, reason="ok",
                           latency_ms=10)])
            monkeypatch.setattr(j, "edit_image", edit)
            gen = _gen(monkeypatch, db, tmp_path)
            with caplog.at_level(logging.WARNING):
                published = await gen._publish_rich_document(
                    CHAT, _doc(), "Медведь идёт по лесу.",
                    correlation_id=RID)
            # fail-soft: Base опубликована, сломанная «обложка» НЕ уехала
            assert published is True
            assert gen._c03a_media_bytes[0] == BASE_PNG
            failed = _lines(caplog, "COVER_STYLE_FAILED")
            assert failed and ("reason=semantic_preservation_failed"
                               in failed[0])
            jid, state = await _job_state(db, RID)
            assert state.styled_status == "failed"
            assert state.styled_fail_reason == \
                j.REASON_SEMANTIC_LOST
            assert state.styled_asset_path is None
            base_rows = [r for r in prov.rows if r.get("status") == "base"]
            assert base_rows
            assert base_rows[0]["fallback_mode"] == j.REASON_SEMANTIC_LOST
            # permanent → recovery не зацикливается
            actions = await j.recover_cover_style_jobs(db, limit=2)
            assert actions == []
            assert edit.calls["n"] == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_binary_garbage_maps_to_invalid_payload(
            self, monkeypatch, tmp_path):
        db = await _fresh_db()
        try:
            profile = _profile()
            _patch_selection(monkeypatch, profile)
            _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            edit = _make_edit_script([
                EditResult(ok=True, content=b"\x00\x01\x02\xfe\xff" * 20,
                           reason="ok", latency_ms=10)])
            monkeypatch.setattr(j, "edit_image", edit)
            gen = _gen(monkeypatch, db, tmp_path)
            published = await gen._publish_rich_document(
                CHAT, _doc(), "Сюжет.", correlation_id=RID)
            assert published is True
            _, state = await _job_state(db, RID)
            assert state.styled_status == "failed"
            assert state.styled_fail_reason == j.REASON_INVALID_PAYLOAD
            assert gen._c03a_media_bytes[0] == BASE_PNG
        finally:
            await db.close()

    @pytest.mark.parametrize("content,expected", [
        (b"\xff\xd8\xff\xe0" + b"0" * 16, (True, "")),
        (b"\x89PNG\r\n\x1a\n" + b"0" * 16, (True, "")),
        (b"RIFF1234WEBP" + b"0" * 16, (True, "")),
        (MODEL_TEXT, (False, j.REASON_SEMANTIC_LOST)),
        (b"\x00\x01\x02\xfe\xff" * 8, (False, j.REASON_INVALID_PAYLOAD)),
    ])
    def test_styled_payload_signal(self, content, expected):
        assert j._styled_payload_signal(content) == expected


# ══ кейс 6: два сюжета + один profile ≠ generic scene ═══════════════════════

class TestCase6StoryIdentityDistinct:
    @pytest.mark.asyncio
    async def test_two_stories_produce_distinct_story_prompts(
            self, monkeypatch, tmp_path):
        db = await _fresh_db()
        try:
            profile = _profile()
            _patch_selection(monkeypatch, profile)
            _patch_provenance(monkeypatch)
            _patch_issue_counter(monkeypatch)
            base = tmp_path / "base.png"
            base.write_bytes(BASE_PNG)
            seen = []

            async def _edit(prompt, **kw):
                seen.append(str(prompt))
                return EditResult(ok=True, content=STYLE_IMG, reason="ok",
                                  latency_ms=5)

            for story in ("Медведь ловит рыбу на пороге реки.",
                          "Медведь спит в берлоге под снегом."):
                await j.run_style_job(
                    chat_id=CHAT, base_image_path=str(base), profile=profile,
                    summary_run_id=None, capabilities=_caps(),
                    reference_paths=[], edit_call=_edit, story_scene=story,
                    summary_text=story, base_style_prompt="cinematic")
            assert len(seen) == 2
            assert seen[0] != seen[1]
            assert "Медведь ловит рыбу" in seen[0]
            assert "Медведь ловит рыбу" not in seen[1]
            assert "спит в берлоге" in seen[1]
            assert "спит в берлоге" not in seen[0]
        finally:
            await db.close()


# ══ unit: классификация и гейты recovery ════════════════════════════════════

class TestRecoveryClassification:
    @pytest.mark.parametrize("reason,expected", [
        ("timeout", "transient"),
        ("TimeoutError", "transient"),
        ("http_502", "transient"),
        ("rate_limit", "transient"),
        ("temp_write_failed", "transient"),
        ("deadline_exceeded", "transient"),
        ("connection_missing", "permanent"),
        ("edit_unsupported", "permanent"),
        ("not_configured", "permanent"),
        ("story_identity_dropped", "permanent"),
        ("prompt_limit_exceeded", "permanent"),
        ("semantic_preservation_failed", "permanent"),
        ("invalid_image_payload", "permanent"),
        ("base_asset_missing", "permanent"),
        ("http_401", "permanent"),
        ("", "permanent"),
        ("mystery_error", "permanent"),
    ])
    def test_classify(self, reason, expected):
        assert j.classify_style_failure(reason) == expected

    def test_gates(self, monkeypatch):
        _sflag(monkeypatch, "COVER_STYLE_RECOVERY_MAX_ATTEMPTS", 3)
        assert j.recovery_max_attempts() == 3
        _sflag(monkeypatch, "COVER_STYLE_RECOVERY_ENABLED", False)
        assert j.recovery_enabled() is False
        _sflag(monkeypatch, "COVER_STYLE_RECOVERY_ENABLED", True)
        assert j.recovery_enabled() is True
        # bounded backoff
        assert j.recovery_backoff_seconds(1) == 300
        assert j.recovery_backoff_seconds(2) == 600
        assert j.recovery_backoff_seconds(9) == 3600
