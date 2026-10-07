"""ASAP 4.3 (T-4842–T-4844) — durable Test Style preview job runner.

`Проверить стиль` больше НЕ держит один browser↔backend HTTP-запрос: POST
создаёт/регистрирует job в СУЩЕСТВУЮЩЕЙ инфраструктуре (`task_jobs`,
`CoverJobState`, `begin_cover_job`) и запускает выполнение фоновым
asyncio-task внутри backend-процесса; UI опрашивает status-endpoint.

Контур (одна очередь, без второго framework):
    queued → base_generating → base_ready → style_editing → saving_preview
           → completed | failed

Инварианты:
* base generation + style edit исполняются ВНУТРИ durable job (§2.1/§2.3);
* повторный POST при активном job того же стиля возвращает тот же `job_id`
  (double-tap не создаёт второй платный запрос);
* status-read бесплатный: только `task_jobs` + checkpoint, без сети/provider;
* restart: `provider_task_id` лежит в checkpoint — возобновление дочитывает
  тот же provider task (`run_style_job` → `existing_task_id`), base при
  наличии durable-ассета не перегенерируется;
* success pair пишется атомарно (§4) ТОЛЬКО при успешном завершении job;
  failure не трогает текущую valid pair;
* после успеха issue counter не расходуется (mode=preview в `run_style_job`),
  публикации в Telegram нет.
"""
from __future__ import annotations

import asyncio
import json
import logging

from services import cover_style_assets as assets
from services import cover_style_jobs as jobs
from services import cover_style_pipeline as pipeline
from services import cover_style_registry as registry

logger = logging.getLogger(__name__)

KIND_PREVIEW = "cover_style_preview"
MODE_PREVIEW = "preview"

# Публичные стадии (§2.2): queued/base_generating/base_ready/style_editing/
# saving_preview/completed/failed.
STAGE_QUEUED = "queued"
STAGE_BASE_GENERATING = "base_generating"
STAGE_BASE_READY = "base_ready"
STAGE_STYLE_EDITING = "style_editing"
STAGE_SAVING_PREVIEW = "saving_preview"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"

_STATE_TO_STAGE = {
    jobs.STATE_CREATED: STAGE_QUEUED,
    jobs.STATE_BASE_SUBMITTED: STAGE_BASE_GENERATING,
    jobs.STATE_BASE_RUNNING: STAGE_BASE_GENERATING,
    jobs.STATE_BASE_SUCCEEDED: STAGE_BASE_READY,
    jobs.STATE_BASE_FAILED: STAGE_FAILED,
    jobs.STATE_STYLE_SUBMITTED: STAGE_STYLE_EDITING,
    jobs.STATE_STYLE_RUNNING: STAGE_STYLE_EDITING,
    jobs.STATE_STYLE_SUCCEEDED: STAGE_SAVING_PREVIEW,
    jobs.STATE_STYLE_FAILED: STAGE_FAILED,
    jobs.STATE_SAVING_PREVIEW: STAGE_SAVING_PREVIEW,
    jobs.STATE_PUBLISH_RICH: STAGE_SAVING_PREVIEW,
    jobs.STATE_PUBLISH_PLAIN: STAGE_SAVING_PREVIEW,
    jobs.STATE_DONE: STAGE_COMPLETED,
    jobs.STATE_FAILED: STAGE_FAILED,
}

_ACTIVE: dict[str, "asyncio.Task"] = {}
_PENDING: dict[str, dict] = {}
_START_LOCK: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _START_LOCK
    if _START_LOCK is None:
        _START_LOCK = asyncio.Lock()
    return _START_LOCK


def preview_job_key(style_id: str) -> str:
    """Детерминированный job_id preview на стиль (§2.3): один недоделанный
    Test Style на профиль; завершённый переиспользуется через requeue.

    Совпадает с id, который создаёт `begin_cover_job(summary_run_id=None)`
    (иначе lookup/requeue не находят строку — единственный источник id)."""
    return jobs.cover_job_key(summary_run_id=None, style_id=style_id)


def is_runner_active(job_id: str | None) -> bool:
    task = _ACTIVE.get(str(job_id or ""))
    if task is None:
        return False
    if task.done():
        _ACTIVE.pop(str(job_id), None)
        return False
    return True


def stage_for(job_status: str | None, state: jobs.CoverJobState | None) -> str:
    """Публичная стадия из task_jobs.status + checkpoint (§2.2)."""
    status = str(job_status or "")
    if status == "completed":
        return STAGE_COMPLETED
    if status == "failed":
        return STAGE_FAILED
    if status in ("cancelled", "interrupted"):
        return STAGE_FAILED
    if status == "queued":
        # queued до первого mark; если runner уже продвинул state — state.
        stage = _STATE_TO_STAGE.get(
            (state.state if state else jobs.STATE_CREATED), STAGE_QUEUED)
        return STAGE_QUEUED if stage == STAGE_QUEUED else stage
    return _STATE_TO_STAGE.get(
        (state.state if state else jobs.STATE_CREATED), STAGE_QUEUED)


def preview_human_message(reason: str) -> str:
    """Человеческая фраза по machine reason (§3/§11) — UI переводит сам при
    необходимости, сервер отдаёт безопасный текст."""
    reason = str(reason or "")
    if reason in ("prompt_limit", "prompt_limit_exceeded",
                  "prompt_limit_unknown"):
        return "Стиль не применён: инструкция превышает лимит модели."
    if reason == "prompt_limit_unknown_after_retry":
        return ("Стиль не применён: промпт превышает лимит модели даже "
                "после сокращения.")
    if reason == "connection_missing":
        return ("Подключение модели не найдено. Откройте «Настроить "
                "подключения →» и выберите подключение заново.")
    if reason == "edit_unsupported":
        return pipeline.NO_EDIT_MESSAGE
    if reason == "reference_missing":
        return ("Референсы стиля недоступны (файл отсутствует или "
                "повреждён). Загрузите референс заново.")
    if reason in ("not_configured", "no_input_images"):
        return ("Модель обработки не настроена. Откройте «Настроить "
                "подключения →» и выберите модель с поддержкой edit.")
    if reason == "base_generation_failed":
        return ("Не удалось сгенерировать базовую обложку. Проверьте "
                "настройки генерации изображений и попробуйте снова.")
    if reason == "preview_store_failed":
        return ("Стиль применён, но не удалось сохранить пример. "
                "Попробуйте ещё раз.")
    if reason in ("route_unverified", "provider_error", "http_400",
                  "bad_request", "no_style", "profile_missing"):
        return "Стиль не применён: провайдер отклонил запрос."
    return ("Не удалось применить стиль. Проверьте подключение и модель "
            "обработки.")


def _public_status(row: dict, state: jobs.CoverJobState | None) -> dict:
    job_id = row.get("job_id")
    status = str(row.get("status") or "")
    state = state or jobs.CoverJobState()
    reason = str(row.get("reason_code") or state.machine_reason or "")
    human = state.human_message or ""
    if status == "failed" and not human:
        human = preview_human_message(reason)
    # §4: generated-во-время-провала ассеты наружу как «новая пара» НЕ
    # отдаются — before/after видны только у успешно завершённого job.
    completed = status == "completed"
    return {
        "job_id": job_id,
        "status": status,
        "stage": stage_for(status, state),
        "started_at": row.get("created_at"),
        "last_progress_at": (row.get("progress_at")
                             or row.get("heartbeat_at")
                             or row.get("updated_at")),
        "provider": state.provider or "",
        "model": state.model or "",
        "human_message": human,
        "machine_reason": reason,
        "preview_before_url": (_asset_url(state.preview_before_asset_id)
                               if completed else None),
        "preview_after_url": (_asset_url(state.preview_after_asset_id)
                              if completed else None),
        "preview_revision": state.preview_revision if completed else None,
        "preview_job_id": job_id if completed else None,
        "preview_status": "success" if completed else None,
        "mode": MODE_PREVIEW,
        # §9 (T-4849): breakdown последней сборки (safe-числа, без prompt).
        "prompt": _prompt_public(state.prompt_diagnostics),
    }


def _prompt_public(diag: dict | None) -> dict:
    diag = diag if isinstance(diag, dict) else {}
    return {
        "style_chars": diag.get("style_chars"),
        "context_chars": diag.get("context_chars"),
        "refs_chars": diag.get("refs_chars"),
        "system_chars": diag.get("system_chars"),
        "total_chars": diag.get("compiled_chars"),
        "limit": diag.get("resolved_limit"),
        "unit": (str(diag.get("limit_unit") or "").split(":")[-1]
                 if diag.get("limit_unit") else None),
        "exceeded": bool(diag.get("exceeded")),
    }


def _asset_url(asset_id) -> str | None:
    return f"/api/cover/assets/{asset_id}" if asset_id else None


async def job_manifest(db, job_id: str, *,
                       include_prompt: bool = False) -> dict | None:
    """D7/T-5249: CoverPromptManifest durable-джобы для admin-API.

    Единая fail-closed точка чтения для preview/production/base job'ов:
    без ``include_prompt=True`` (admin-authorized вызывающий) отдаются
    только числа/enum/статусы/хэши — полные тексты не покидают durable
    job evidence. ``None`` — джобы/манифеста нет."""
    state = await jobs.load_cover_state(db, job_id)
    if state is None:
        return None
    return jobs.manifest_public(state.prompt_manifest,
                                 include_prompt=include_prompt)


async def job_status(db, job_id: str) -> dict | None:
    """Бесплатный снимок статуса (§2.3): только durable-чтение, без provider."""
    row = await jobs.get_cover_job(db, job_id)
    if row is None or str(row.get("kind") or "") != KIND_PREVIEW:
        return None
    state = await jobs.load_cover_state(db, job_id)
    return _public_status(row, state)


async def start_preview_job(db, *, profile: dict, pg, correlation_id: str,
                            brief: str,
                            base_upload_meta: dict | None = None,
                            draft_snapshot: dict | None = None) -> dict:
    """Короткий start (§2.2): {job_id, status:"queued"} без ожидания.

    Двойной тап: активный job стиля → тот же `job_id` (без второго paid
    запроса). Завершённый job переиспользуется (requeue) — одна строка
    `task_jobs` на стиль, без дублей/второй очереди.

    ASAP 4.4 (T-4870): `draft_snapshot` — нормализованные style-affecting
    поля текущего редактора (не сохраняются как профиль); job генерирует
    ровно их и хранит snapshot+fingerprint в durable state (resume тоже).
    """
    style_id = str((profile or {}).get("profile_id") or "")
    merged = (registry.merge_draft_snapshot(profile, draft_snapshot)
              if isinstance(draft_snapshot, dict) else profile)
    fingerprint = (registry.style_fingerprint(merged)
                   if isinstance(draft_snapshot, dict) else None)
    async with _lock():
        jid = preview_job_key(style_id)
        row = await jobs.get_cover_job(db, jid)
        active = bool(row and str(row.get("status")) in ("queued", "running"))
        if active and is_runner_active(jid):
            return {"job_id": jid, "status": row.get("status"),
                    "stage": stage_for(row.get("status"), None),
                    "reused": True}
        if row is not None:
            # Терминальный (или осиротевший running без runner) → новый цикл.
            await jobs.requeue_cover_job(db, jid)
            state = jobs.CoverJobState(
                style_id=style_id, mode=MODE_PREVIEW,
                provider=None, model=None)
            state.mark(jobs.STATE_CREATED)
            await jobs.save_cover_state(db, jid, state)
            started = jid
        else:
            started, state = await jobs.begin_cover_job(
                db, chat_id=0, correlation_id=correlation_id,
                style_id=style_id, summary_run_id=None,
                payload={"mode": MODE_PREVIEW, "profile_id": style_id,
                         "kind": KIND_PREVIEW},
                kind=KIND_PREVIEW,
                initial_state=jobs.STATE_CREATED)
            if started:
                await jobs.save_cover_state(db, started, state)
        if not started:
            return {}
        _spawn(db, started, profile=merged, pg=pg,
               correlation_id=correlation_id, brief=brief,
               base_upload_meta=base_upload_meta,
               draft_snapshot=draft_snapshot,
               draft_fingerprint=fingerprint)
        return {"job_id": started, "status": "queued", "stage": STAGE_QUEUED,
                "reused": False}


def _spawn(db, job_id: str, *, profile: dict, pg, correlation_id: str,
           brief: str, base_upload_meta: dict | None,
           draft_snapshot: dict | None = None,
           draft_fingerprint: str | None = None) -> None:
    args = {"profile": profile, "pg": pg, "correlation_id": correlation_id,
            "brief": brief, "base_upload_meta": base_upload_meta,
            "draft_snapshot": draft_snapshot,
            "draft_fingerprint": draft_fingerprint}
    if is_runner_active(job_id):
        # Предыдущий runner завершает терминальную запись; новый цикл
        # стартует сразу после его выхода (не теряем spawn).
        _PENDING[job_id] = args
        return
    try:
        task = asyncio.ensure_future(run_preview_job(db, job_id, **args))
    except RuntimeError:      # нет running loop (вызов вне async) — fail-open
        logger.warning("[cover_preview] no running loop — job stays queued")
        return
    _ACTIVE[job_id] = task

    def _done(t: "asyncio.Task", jid: str = job_id) -> None:
        _ACTIVE.pop(jid, None)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("[cover_preview] job crashed | job_id=%s | %s",
                           jid, type(exc).__name__)
        pending = _PENDING.pop(jid, None)
        if pending is not None:
            try:
                _spawn(db, jid, **pending)
            except Exception:
                logger.warning("[cover_preview] pending restart failed | "
                               "job_id=%s", jid, exc_info=True)
    task.add_done_callback(_done)


async def maybe_resume(db, pg, snapshot: dict | None) -> bool:
    """Дешёвая проверка resume для status-route: только активные job'ы."""
    if not snapshot:
        return False
    if str(snapshot.get("status")) not in ("queued", "running"):
        return False
    return await resume_preview_job(db, str(snapshot.get("job_id") or ""),
                                    pg=pg)


async def resume_preview_job(db, job_id: str, *, pg=None) -> bool:
    """Resume (§2.3): активная durable-джоба без живого runner (рестарт
    процесса) — поднять runner заново; provider_task_id/base_asset_id из
    checkpoint позволяют дочитать тот же provider task. Статус-чтение само
    генерацию не запускает, только best-effort resume."""
    if is_runner_active(job_id):
        return False
    row = await jobs.get_cover_job(db, job_id)
    if row is None or str(row.get("kind") or "") != KIND_PREVIEW:
        return False
    if str(row.get("status")) not in ("queued", "running"):
        return False
    state = await jobs.load_cover_state(db, job_id)
    if state is None or not state.style_id:
        await jobs.finish_cover_job(db, job_id, outcome=jobs.STATE_FAILED,
                                    reason_code="interrupted")
        return False
    profile = await registry.get_profile_with_refs(pg, state.style_id)
    if profile is None:
        await jobs.finish_cover_job(db, job_id, outcome=jobs.STATE_FAILED,
                                    reason_code="profile_missing")
        return False
    # T-4870: resume генерирует ровно тот draft, что был у editor (snapshot
    # из durable state), а не текущую DB-версию.
    snapshot = (state.draft_snapshot
                if isinstance(state.draft_snapshot, dict) else None)
    if snapshot is not None:
        profile = registry.merge_draft_snapshot(profile, snapshot)
    try:
        payload = json.loads(row.get("payload") or "{}")
    except (ValueError, TypeError):
        payload = {}
    _spawn(db, job_id, profile=profile, pg=pg,
           correlation_id=payload.get("correlation_id"),
           brief=_BRIEF_DEFAULT, base_upload_meta=None,
           draft_snapshot=snapshot,
           draft_fingerprint=state.draft_fingerprint)
    return True


# Дефолтный тестовый бриф (совпадает с web.api.cover_styles.TEST_STYLE_BRIEF):
# нейтральная сцена, без пользовательских данных/секретов.
_BRIEF_DEFAULT = (
    "Нейтральная тестовая сцена для проверки обработки обложки: один крупный "
    "объект в центре кадра, ровный фон, мягкий свет, без текста и мелких "
    "подписей, книжная вертикальная композиция."
)


async def run_preview_job(db, job_id: str, *, profile: dict, pg,
                          correlation_id: str | None, brief: str,
                          base_upload_meta: dict | None = None,
                          draft_snapshot: dict | None = None,
                          draft_fingerprint: str | None = None) -> dict:
    """Выполнить durable preview job: base → style edit → atomic pair → finish."""
    style_id = str((profile or {}).get("profile_id") or "")
    state = await jobs.load_cover_state(db, job_id)
    if state is None or state.state in (jobs.STATE_DONE, jobs.STATE_FAILED):
        state = jobs.CoverJobState(style_id=style_id, mode=MODE_PREVIEW)
        state.mark(jobs.STATE_CREATED)
    state.mode = MODE_PREVIEW
    # T-4870: snapshot текущего draft редактора — durable provenance job'а
    # (resume переиспользует его; в profile не сохраняется).
    if isinstance(draft_snapshot, dict):
        state.draft_snapshot = dict(draft_snapshot)
        state.draft_fingerprint = draft_fingerprint

    base_meta = base_upload_meta
    base_path: str | None = None
    if state.state == jobs.STATE_CREATED:
        state.mark(jobs.STATE_BASE_SUBMITTED)
        await jobs.save_cover_state(db, job_id, state)
        if base_meta is None:
            base_path, reason = await _generate_base(
                brief=brief, correlation_id=correlation_id)
            if not base_path:
                return await _fail_job(
                    db, job_id, state, reason="base_generation_failed")
            base_meta = await _store_base(pg, base_path)
        if base_meta is None:
            return await _fail_job(
                db, job_id, state, reason="base_generation_failed")
        state.base_asset_id = base_meta.get("asset_id")
        state.mark(jobs.STATE_BASE_SUCCEEDED)
        await jobs.save_cover_state(db, job_id, state)
    else:
        # Resume: не перегенерируем base, если durable-ассет на диске есть.
        base_meta = await _load_base_asset(pg, state.base_asset_id)
        if base_meta is None:
            state.mark(jobs.STATE_BASE_SUBMITTED)
            await jobs.save_cover_state(db, job_id, state)
            base_path, reason = await _generate_base(
                brief=brief, correlation_id=correlation_id)
            if not base_path:
                return await _fail_job(
                    db, job_id, state, reason="base_generation_failed")
            base_meta = await _store_base(pg, base_path)
            if base_meta is None:
                return await _fail_job(
                    db, job_id, state, reason="base_generation_failed")
            state.base_asset_id = base_meta.get("asset_id")
            state.mark(jobs.STATE_BASE_SUCCEEDED)
            await jobs.save_cover_state(db, job_id, state)
    base_path = base_path or str(base_meta.get("disk_path") or "")

    meta = await jobs.run_style_job(
        chat_id=0, base_image_path=base_path, profile=profile,
        summary_run_id=None, correlation_id=correlation_id,
        pg=pg, db=db, job_id=job_id, state=state, mode=jobs.MODE_PREVIEW)
    state.provider = meta.get("provider") or state.provider
    state.model = meta.get("model") or state.model
    if isinstance(meta.get("prompt_diagnostics"), dict):
        state.prompt_diagnostics = meta["prompt_diagnostics"]
        await jobs.save_cover_state(db, job_id, state)

    if not meta.get("styled_path"):
        reason = str(meta.get("fail_reason") or meta.get("reason")
                     or "style_failed")
        return await _fail_job(db, job_id, state, reason=reason)

    styled_bytes = _read_bytes(meta.get("styled_path"))
    stored = assets.store_file_bytes(
        styled_bytes, filename="preview_style.jpg",
        origin="generated_preview") if styled_bytes else None
    after_id = None
    if stored is not None and await registry.upsert_asset(pg, stored):
        after_id = stored["asset_id"]
    if not after_id:
        return await _fail_job(db, job_id, state,
                               reason="preview_store_failed")

    state.preview_before_asset_id = state.base_asset_id
    state.preview_after_asset_id = after_id
    state.preview_revision = profile.get("revision")
    state.human_message = "Стиль применён"
    state.machine_reason = None
    state.mark(jobs.STATE_SAVING_PREVIEW)
    await jobs.save_cover_state(db, job_id, state)

    # §4: success pair — ОДНА атомарная операция; failure сюда не доходит.
    saved = await registry.set_preview(
        pg, style_id, after_asset_id=after_id,
        revision=profile.get("revision"),
        before_asset_id=state.base_asset_id, job_id=job_id)
    if not saved:
        # Пара не записана вовсе — предыдущая pair не тронута; job failed.
        return await _fail_job(db, job_id, state,
                               reason="preview_store_failed")
    state.mark(jobs.STATE_DONE)
    await jobs.save_cover_state(db, job_id, state)
    try:
        await jobs.finish_cover_job(
            db, job_id, outcome=jobs.STATE_DONE, checkpoint=state)
    except Exception:
        logger.debug("[cover_preview] finish failed (fail-open)", exc_info=True)
    return meta


async def _fail_job(db, job_id: str, state: jobs.CoverJobState, *,
                    reason: str) -> dict:
    reason = str(reason or "style_failed")
    state.machine_reason = reason
    state.human_message = preview_human_message(reason)
    if state.state not in (jobs.STATE_DONE, jobs.STATE_FAILED):
        state.mark(jobs.STATE_FAILED, note=reason)
    await jobs.save_cover_state(db, job_id, state)
    try:
        await jobs.finish_cover_job(db, job_id, outcome=jobs.STATE_FAILED,
                                    reason_code=reason, checkpoint=state)
    except Exception:
        logger.debug("[cover_preview] fail finish failed (fail-open)",
                     exc_info=True)
    return {"applied": False, "reason": "style_failed", "fail_reason": reason,
            "message": state.human_message}


async def _generate_base(*, brief: str, correlation_id: str | None
                         ) -> tuple[str | None, str]:
    from services import image_generation
    try:
        path, reason = await image_generation.generate_image_verbose(
            brief, chat_id=None, correlation_id=correlation_id)
        return path, str(reason or "")
    except Exception:
        logger.warning("[cover_preview] base generation failed", exc_info=True)
        return None, "base_generation_exception"


async def _store_base(pg, path: str) -> dict | None:
    """Сохранить base-байты в CAS + зарегистрировать asset в PG (§4).

    Canary A fix (prod 2.58.50): без `upsert_asset` base-файл лежал на диске
    без строки `cover_style_assets`, и UI не мог получить «До»-картинку
    (`GET /cover/assets/{id}` → 404) при формально записанной паре. Пара
    валидна только если оба ассета отдаются; ошибка регистрации = failure
    job'а до записи пары (атомарный контракт §4).
    """
    data = _read_bytes(path)
    if not data:
        return None
    meta = assets.store_file_bytes(
        data, filename="test_base.png", origin="generated_preview")
    if meta is None:
        return None
    if not await registry.upsert_asset(pg, meta):
        return None
    return meta


async def _load_base_asset(pg, asset_id) -> dict | None:
    if not asset_id:
        return None
    try:
        asset = await registry.get_asset(pg, asset_id)
    except Exception:
        return None
    if not asset:
        return None
    import os
    disk = str(asset.get("disk_path") or "")
    if not disk or not os.path.exists(disk):
        return None
    return asset


def _read_bytes(path) -> bytes:
    if not path:
        return b""
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""


def reset_preview_runners() -> None:
    """Тесты/shutdown: сбросить process-local реестр runner'ов."""
    for task in list(_ACTIVE.values()):
        try:
            task.cancel()
        except Exception:
            pass
    _ACTIVE.clear()
    _PENDING.clear()


__all__ = [
    "KIND_PREVIEW", "STAGE_QUEUED", "STAGE_BASE_GENERATING",
    "STAGE_BASE_READY", "STAGE_STYLE_EDITING", "STAGE_SAVING_PREVIEW",
    "STAGE_COMPLETED", "STAGE_FAILED", "preview_job_key", "is_runner_active",
    "stage_for", "preview_human_message", "job_status", "start_preview_job",
    "resume_preview_job", "maybe_resume", "run_preview_job",
    "reset_preview_runners",
]
