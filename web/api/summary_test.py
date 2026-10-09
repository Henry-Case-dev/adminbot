"""S9 round1026 (ADR-1026-8 D1/D4) — API dry-run тест-контура «Тестирование» (§113).

Отдельный роутер (прецедент chat_lore/memory_agi/analytics), включается в
``web/app.py``; ``web/api/routes.py`` — вне diff. Асинхронная модель: ``POST
/run`` создаёт задачу (``asyncio.create_task``) и сразу отдаёт 202; клиент
опрашивает ``GET /{test_id}``. Store — **in-memory** (TTL 15 мин, ≤20 записей),
**без persistence/DDL** (рестарт → результат теряется, осознанно).

Права — только глобальный админ (``requires_global_admin``); ``chat_id``
валидируется против доступных областей. R17: наружу — только числа/коды/ID и
усечённые предпросмотры уполномоченному админу; без ключей/сырых ответов/промптов
в ответе и логах (ASAP 7 F7: полный prompt обложки — ТОЛЬКО в durable
``task_jobs`` kind=cover_base ``CoverPromptManifest``, читаемом admin-путём;
ответ/логи эндпоинтов текстов промптов не содержат). Флаг
``SUMMARY_TEST_UI_ENABLED`` (env-only) OFF → 404.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config.settings import settings
from services import roles as roles_srv
from services.summary_test_run import (
    TEST_RUN_FAILED,
    empty_payload,
    error_result,
    present_result,
    run_summary_test,
)
from web.api.deps import get_cache, requires_global_admin

logger = logging.getLogger(__name__)

# ── Флаг (env-only ClassVar, D8): OFF → 404 (до auth) ──────────────────────

def _flag_enabled() -> bool:
    return bool(getattr(settings, "SUMMARY_TEST_UI_ENABLED", False))


async def _flag_guard() -> None:
    if not _flag_enabled():
        raise HTTPException(status_code=404, detail="not found")


summary_test_router = APIRouter(dependencies=[Depends(_flag_guard)])


# ── In-memory store (TTL 15 мин, ≤20, без DDL) ─────────────────────────────

class _RunEntry:
    __slots__ = ("test_id", "user_id", "chat_id", "hours", "status",
                 "created", "finished", "result", "error", "task",
                 "cover_path", "cover_status", "cover_error", "seq")

    def __init__(self, test_id: str, user_id: int, chat_id: int, hours: int,
                 seq: int = 0):
        self.test_id = test_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.hours = hours
        self.status = "running"
        self.created = time.time()
        self.finished = None
        self.result = None
        self.error = None
        self.task = None
        self.cover_path = None
        self.cover_status = "not_generated"
        self.cover_error = None
        self.seq = seq


class _RunStore:
    """In-memory store заданий тест-прогона (без persistence, D4)."""

    TTL_SECONDS = 900.0          # 15 мин
    MAX_ENTRIES = 20
    MAX_CONCURRENT = 2
    RATE_LIMIT_SECONDS = 10.0

    def __init__(self) -> None:
        self._items: dict[str, _RunEntry] = {}
        self._seq = 0

    def _purge(self) -> None:
        now = time.time()
        # L-R1026S9-3/S-R1026S9-2: активный (`running`) прогон НЕ вычищается по
        # TTL — иначе polling получает 404 и освобождается слот MAX_CONCURRENT.
        expired = [k for k, e in self._items.items()
                   if e.status != "running" and (e.finished or e.created)
                   and (now - (e.finished or e.created)) > self.TTL_SECONDS]
        for key in expired:
            self._items.pop(key, None)

    def put_running(self, test_id: str, user_id: int, chat_id: int,
                    hours: int) -> _RunEntry:
        self._purge()
        # Эвикция старейшего при переполнении (≤20 записей), но не `running`
        # (L-R1026S9-3): активный прогон не выбрасываем.
        while len(self._items) >= self.MAX_ENTRIES:
            candidates = [k for k, e in self._items.items()
                          if e.status != "running"]
            if not candidates:
                break
            oldest = min(candidates, key=lambda k: self._items[k].seq)
            self._items.pop(oldest, None)
        self._seq += 1
        entry = _RunEntry(test_id, user_id, chat_id, hours, seq=self._seq)
        self._items[test_id] = entry
        return entry

    def get(self, test_id: str) -> _RunEntry | None:
        self._purge()
        return self._items.get(str(test_id))

    def latest_for(self, user_id: int, chat_id: int) -> _RunEntry | None:
        self._purge()
        candidates = [e for e in self._items.values()
                      if e.user_id == user_id and e.chat_id == chat_id]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.seq)

    def active_for(self, user_id: int, chat_id: int) -> _RunEntry | None:
        self._purge()
        for entry in self._items.values():
            if (entry.user_id == user_id and entry.chat_id == chat_id
                    and entry.status == "running"):
                return entry
        return None

    def active_count(self) -> int:
        self._purge()
        return sum(1 for e in self._items.values() if e.status == "running")

    def last_finished_at(self, user_id: int, chat_id: int) -> float:
        self._purge()
        times = [e.finished for e in self._items.values()
                 if e.user_id == user_id and e.chat_id == chat_id
                 and e.finished]
        return max(times) if times else 0.0

    def clear(self) -> None:
        self._items.clear()


_STORE = _RunStore()


def reset_test_store() -> None:
    """Сброс in-memory store (тесты/диагностика)."""
    _STORE.clear()


# ── Вход/валидация ─────────────────────────────────────────────────────────

class RunBody(BaseModel):
    chat_id: int
    window_hours: int | None = None


class CoverBody(BaseModel):
    confirm: bool = False


def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None


def _validate_chat_id(value) -> int:
    """Валидация ``chat_id``: int ≠ 0 (Telegram supergroup id — отрицательный)."""
    try:
        chat_id = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="invalid chat_id")
    if chat_id == 0:
        raise HTTPException(status_code=422, detail="invalid chat_id")
    return chat_id


async def _chat_accessible(cache, user: WebAppUser, chat_id: int) -> bool:
    """Доступна ли область чата юзеру (reuse ``roles.access_for``).

    Глобальный админ видит все чаты; иначе нужен chat-грант. Fail-open при
    недоступности PG-ролей — сам эндпоинт уже закрыт ``requires_global_admin``.
    """
    try:
        ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    except Exception:
        return True
    if getattr(ctx, "is_global_admin", False):
        return True
    return getattr(ctx, "role_chat", None) is not None


def _result_payload(entry: _RunEntry, offset: int, limit: int) -> dict:
    # B-R1026S9-2: контракт-валидный ответ на всех путях — полные
    # metrics/artifacts/display (нет `undefined.l1` в UI при error/running).
    if entry.result is None:
        payload = empty_payload(test_id=entry.test_id, status=entry.status,
                                chat_id=entry.chat_id)
    else:
        payload = present_result(entry.result, offset=offset, limit=limit)
    payload["cover"] = {"status": entry.cover_status,
                        "error": entry.cover_error}
    return payload


# ── GET /summary/test/availability (probe для UI, D8) ──────────────────────

@summary_test_router.get("/summary/test/availability")
async def summary_test_availability(
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Probe: флаг ON + права → 200; иначе 404 (router-guard)/403. UI скрывает
    секцию при недоступности (D8). Наружу — только bool, без секретов."""
    return {"enabled": True}


# ── POST /summary/test/run ─────────────────────────────────────────────────

@summary_test_router.post("/summary/test/run", status_code=202)
async def summary_test_run(
    request: Request,
    body: RunBody,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Старт dry-run: 202 ``{test_id, status:"running"}`` (D4)."""
    cache = get_cache(request)
    chat_id = _validate_chat_id(body.chat_id)
    if not await _chat_accessible(cache, user, chat_id):
        raise HTTPException(status_code=403, detail="chat недоступен")
    if _STORE.active_for(user.id, chat_id) is not None:
        raise HTTPException(status_code=409, detail="прогон уже идёт")
    if _STORE.active_count() >= _RunStore.MAX_CONCURRENT:
        raise HTTPException(status_code=429, detail="слишком много прогонов")
    last = _STORE.last_finished_at(user.id, chat_id)
    if last and (time.time() - last) < _RunStore.RATE_LIMIT_SECONDS:
        raise HTTPException(status_code=429, detail="слишком часто")

    from services import usage_events
    test_id = usage_events.new_correlation_id()
    hours = body.window_hours
    from services.summary_test_run import resolve_window_hours
    entry = _STORE.put_running(test_id, user.id, chat_id,
                               resolve_window_hours({"hours": hours}))
    from services import web_runtime
    generator = web_runtime.get_summary_generator()
    pg_obj = getattr(cache, "pg", None)
    pg = pg_obj if getattr(pg_obj, "pool", None) is not None else None
    entry.task = asyncio.create_task(_execute(entry, generator, pg))
    logger.info(
        "SUMMARY_TEST_START | run_id=%s | chat_id=%s | hours=%s | user=%s",
        test_id, chat_id, entry.hours, user.id)
    return {"test_id": test_id, "status": "running"}


async def _execute(entry: _RunEntry, generator, pg) -> None:
    try:
        result = await run_summary_test(
            entry.chat_id, {"hours": entry.hours},
            correlation_id=entry.test_id, generator=generator, pg=pg)
        entry.result = result
        entry.status = result.status
    except Exception as exc:
        # S7 (T-3400, L-R1026S9-8): R17 — без traceback/сырых текстов; только
        # тип ошибки (маскировка/полнота деталей — на этапных событиях §109).
        logger.warning(
            "SUMMARY_TEST_RUN_FAILED | run_id=%s | chat_id=%s | error_type=%s",
            entry.test_id, entry.chat_id, type(exc).__name__)
        entry.status = "error"
        entry.error = "run_failed"
        # B-R1026S9-2: синтетический контракт-валидный error-результат с
        # диагностикой — UI показывает статус/диагностику, а не падает.
        entry.result = error_result(
            test_id=entry.test_id, chat_id=entry.chat_id,
            window={"hours": entry.hours}, status="error",
            code=TEST_RUN_FAILED, reason="run_failed")
    finally:
        entry.finished = time.time()


# ── GET /summary/test/latest ───────────────────────────────────────────────

@summary_test_router.get("/summary/test/latest")
async def summary_test_latest(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    chat_id: Annotated[int, Query()],
    offset: int = 0,
    limit: int = 50,
):
    """Последний прогон для (user, chat) — polling/возврат к результату."""
    cid = _validate_chat_id(chat_id)
    if not await _chat_accessible(get_cache(request), user, cid):
        raise HTTPException(status_code=403, detail="chat недоступен")
    entry = _STORE.latest_for(user.id, cid)
    if entry is None:
        raise HTTPException(status_code=404, detail="нет прогонов")
    return _result_payload(entry, offset, limit)


# ── GET /summary/test/{test_id} ────────────────────────────────────────────

@summary_test_router.get("/summary/test/{test_id}")
async def summary_test_status(
    test_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    offset: int = 0,
    limit: int = 50,
):
    """Статус/результат прогона (polling). 404 — задание истекло/не найдено."""
    entry = _STORE.get(test_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="задание не найдено")
    return _result_payload(entry, offset, limit)


# ── POST /summary/test/{test_id}/cover (отдельное подтверждение, D3/§4.5) ──

@summary_test_router.post("/summary/test/{test_id}/cover")
async def summary_test_cover(
    test_id: str,
    body: CoverBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Подтверждение генерации обложки (0 новых LLM-вызовов, §104 не трогаем).

    Без ``confirm:true`` — обложка не генерируется (``not_generated``). Ошибка/
    отказ → ``COVER_GENERATION_FAILED``; статья-предпросмотр сохраняется.
    """
    entry = _STORE.get(test_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="задание не найдено")
    if not body.confirm:
        entry.cover_status = "not_generated"
        return {"cover_status": "not_generated", "preview_url": None}
    if entry.cover_path:
        return {"cover_status": entry.cover_status,
                "preview_url": f"/api/summary/test/{test_id}/cover-image"}
    cover_prompt = ""
    document = {}
    if entry.result is not None:
        artifacts = entry.result.artifacts or {}
        package = artifacts.get("package") or {}
        service = (package or {}).get("service") or {}
        cover_prompt = str(service.get("cover_prompt") or "")
        doc = artifacts.get("article")
        document = doc if isinstance(doc, dict) else {}
    if not cover_prompt:
        entry.cover_status = "COVER_GENERATION_FAILED"
        entry.cover_error = "no_cover_prompt"
        return {"cover_status": entry.cover_status, "preview_url": None}
    try:
        from services import cover_prompt_assembly as _cpa
        from services import cover_style_jobs as _csj
        from services import web_runtime
        from services.image_generation import (
            generate_image_verbose,
            provider_label,
            resolve_generate_prompt_limit_async,
        )
        generator = web_runtime.get_summary_generator()
        style = ""
        resolver = getattr(generator, "_resolve_cover_style_text", None)
        if resolver is not None:
            try:
                style = await resolver(entry.chat_id)
            except Exception:
                style = ""
        # ASAP 7 F7 (§2.3/§9.2): production-сборка Base — ТОТ ЖЕ компилятор
        # compose_base_cover_prompt (STORY_SCENE → SUMMARY_CONTEXT →
        # BASE_STYLE), тот же §11-гард и резолв лимита §2.2, что в
        # summary_generator._publish_rich_document_impl. Легаци
        # compose_cover_image_prompt (2 компоненты, БЕЗ SUMMARY_CONTEXT)
        # больше не вызывается (regression B3, тесты asap7_cover_preview).
        _doc_paras = [p.get("text") for p in (document.get("paragraphs")
                                              or []) if isinstance(p, dict)]
        _guard = _cpa.cover_context_decision(
            cover_prompt, document.get("title"), _doc_paras)
        anomaly_reason = ""
        if _guard["status"] == "anomaly_recovered":
            cover_prompt = _guard["story"]
            anomaly_reason = "anomaly_recovered"
        elif _guard["status"] == "cover_context_missing" \
                and not _guard["story"]:
            # §11(3): вырожденная статья — generic-style обложка не уходит.
            entry.cover_status = "COVER_GENERATION_FAILED"
            entry.cover_error = "cover_context_missing"
            return {"cover_status": entry.cover_status, "preview_url": None}
        summary_context = _guard["ctx"]
        base_total_cap = _cpa.default_total_cap()
        total_cap = None
        limit_source = "assembly_cap"
        limit_unit = "chars"
        resolved_limit = None
        try:
            gen_limit = await resolve_generate_prompt_limit_async()
        except Exception:
            gen_limit = None
        if gen_limit is not None and gen_limit.known:
            limit_chars = _cpa.limit_to_chars(gen_limit.value,
                                              gen_limit.unit)
            if limit_chars:
                total_cap = min(base_total_cap, limit_chars)
                resolved_limit = int(gen_limit.value)
                limit_unit = str(gen_limit.unit or "chars")
                limit_source = str(getattr(gen_limit, "source", "")
                                   or "unknown")
        image_prompt = _cpa.compose_base_cover_prompt(
            style, cover_prompt, summary_context, total_cap=total_cap)
        # §2.2: shorter-retry — та же семантика, что production Base
        # (story+context сохранены, стиль сжат; ≤2 платные попытки).
        base_attempts: list = []

        def _shorter_base_prompt(_orig, value, unit):
            chars = _cpa.limit_to_chars(value, unit)
            if not chars:
                return ""
            return _cpa.compose_base_cover_prompt(
                style, cover_prompt, summary_context,
                total_cap=min(base_total_cap, chars))

        async def _remember_base_manifest(*, ok: bool,
                                          reason: str) -> None:
            # §2.3: CoverPromptManifest — durable task_jobs kind=cover_base
            # (тот же носитель/детерминированный ключ, что production);
            # final_prompt == фактически отправленный prompt. Fail-open;
            # полный prompt НЕ в лог (R17).
            try:
                if base_attempts:
                    attempts = [{k: v for k, v in att.items()
                                 if k in ("attempt", "prompt", "outcome",
                                          "reason")}
                                for att in base_attempts]
                    final_prompt = str(attempts[-1]["prompt"])
                    observed = next(
                        ((att.get("meta") or {}).get("prompt_limit")
                         for att in base_attempts
                         if (att.get("meta") or {}).get("prompt_limit")),
                        {})
                    limit_src = ("observed_provider_400" if observed
                                 else limit_source)
                    resolved = (int(observed.get("value")
                                    or resolved_limit or 0) or None)
                else:
                    attempts = None
                    final_prompt = image_prompt
                    limit_src = limit_source
                    resolved = resolved_limit
                manifest = _cpa.build_base_manifest(
                    base_style=(style or "").strip(),
                    story_scene=(cover_prompt or "").strip(),
                    summary_context=summary_context,
                    final_prompt=final_prompt, provider=provider_label(),
                    outcome=("ok" if ok else "failed"), reason=reason,
                    total_cap=total_cap, resolved_limit=resolved,
                    limit_unit=limit_unit, limit_source=limit_src,
                    attempts=attempts,
                    component_reasons=({"STORY_SCENE": anomaly_reason}
                                       if anomaly_reason else None))
                db = getattr(getattr(generator, "memory", None), "db", None)
                await _csj.record_base_cover_manifest(
                    db, summary_run_id=entry.test_id,
                    chat_id=entry.chat_id, manifest=manifest)
            except Exception:
                logger.debug("SUMMARY_TEST cover manifest persist failed",
                             exc_info=True)

        try:
            tmp_path, img_reason = await generate_image_verbose(
                image_prompt, chat_id=entry.chat_id,
                correlation_id=entry.test_id,
                shorter_prompt=_shorter_base_prompt,
                attempt_log=base_attempts)
            await _remember_base_manifest(
                ok=bool(tmp_path),
                reason=("ok" if tmp_path else str(img_reason or "")))
        except Exception as exc:
            await _remember_base_manifest(ok=False,
                                          reason=type(exc).__name__)
            raise
    except Exception as exc:
        # S7 (T-3400, L-R1026S9-8): R17 — без traceback/сырых текстов.
        logger.warning(
            "SUMMARY_TEST_COVER_FAILED | run_id=%s | chat_id=%s | error_type=%s",
            test_id, entry.chat_id, type(exc).__name__)
        entry.cover_status = "COVER_GENERATION_FAILED"
        entry.cover_error = "generation_error"
        return {"cover_status": entry.cover_status, "preview_url": None}
    if not tmp_path:
        entry.cover_status = "COVER_GENERATION_FAILED"
        entry.cover_error = str(img_reason or "image_unavailable")
        return {"cover_status": entry.cover_status, "preview_url": None}
    entry.cover_path = tmp_path
    entry.cover_status = "generated"
    logger.info("SUMMARY_TEST_COVER_OK | run_id=%s | chat_id=%s",
                test_id, entry.chat_id)
    return {"cover_status": "generated",
            "preview_url": f"/api/summary/test/{test_id}/cover-image"}


# ── GET /summary/test/{test_id}/cover-image (no-store, серверный temp) ─────

@summary_test_router.get("/summary/test/{test_id}/cover-image")
async def summary_test_cover_image(
    test_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Превью обложки (no-store). Путь клиентом не задаётся (серверный temp)."""
    entry = _STORE.get(test_id)
    if entry is None or entry.user_id != user.id or not entry.cover_path:
        raise HTTPException(status_code=404, detail="нет обложки")
    import os
    if not os.path.exists(entry.cover_path):
        raise HTTPException(status_code=404, detail="нет обложки")
    return FileResponse(
        entry.cover_path, media_type="image/png",
        headers={"Cache-Control": "no-store"})
