"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D1/D6/D11/D12;
spec §3.5/§3.6/§3.7/§3.9/§3.12, tasks T-4151…T-4166) — Style Registry/Editor API.

Отдельный роутер (прецедент `chat_lore`/`memory_agi`/`summary_test`),
включается в ``web/app.py``. Права — глобальный админ. Все ответы R17-safe:
никаких секретов (API key только в Connections); наружу — профили, ссылки на
ассеты (по `asset_id`, не по URL провайдера), capability-метаданные.

Kill-switch ``COVER_STYLES_ENABLED`` (env-only, default ON) OFF → UI disabled
(§95): список/мутации возвращают ``disabled=true`` без ошибок.
"""
from __future__ import annotations

import logging
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services import cover_style_assets as assets
from services import cover_style_jobs as jobs
from services import cover_style_pipeline as pipeline
from services import cover_style_preview as preview_jobs
from services import cover_style_registry as registry
from services import image_capabilities as image_caps
from web.api.deps import (get_cache, requires_global_admin,
                          requires_permission, user_is_global_admin)

logger = logging.getLogger(__name__)

NO_STYLE_LABEL = "Без дополнительного стиля"
# §12/§2.3: лимит размера upload (legacy-контракт img2img — ≤4 МБ).
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
# ASAP 4.2 (D5.5, T-4819): безопасный тестовый бриф для «Проверить стиль».
# Реальная Base Cover генерируется configured provider/model; бриф нейтрален
# (без пользовательских данных/секретов) и НЕ является production-контентом.
TEST_STYLE_BRIEF = (
    "Нейтральная тестовая сцена для проверки обработки обложки: один крупный "
    "объект в центре кадра, ровный фон, мягкий свет, без текста и мелких "
    "подписей, книжная вертикальная композиция."
)
cover_styles_router = APIRouter()


def _pg(cache):
    return getattr(cache, "pg", None)


def _job_db():
    """SQLite DatabaseService для durable cover-jobs (общий runtime с ботом).

    None — runtime не установлен (тесты/стендалон): Test Style честно
    отказывает 503, а не изображает durable-прогресс без хранилища.
    """
    try:
        from services import lore_runtime
        return lore_runtime.get_lore_db()
    except Exception:
        return None


def _placeholder_payload() -> dict:
    """URL-ы Ч/Б fallback placeholders (§5): фактические имена из extra_images."""
    files = registry.placeholder_files()
    stems = list(registry.PLACEHOLDER_STEMS)
    return {
        "before_url": ("/api/cover/placeholders/%s" % files[stems[0]])
        if stems[0] in files else None,
        "after_url": ("/api/cover/placeholders/%s" % files[stems[1]])
        if len(stems) > 1 and stems[1] in files else None,
    }


def _enabled() -> bool:
    return pipeline.cover_styles_enabled()


def _emit_cover_event(event: str, *, stage: str, reason: str,
                      style_id: str | None = None,
                      asset_id: str | None = None,
                      http_status: int | None = None) -> None:
    """ASAP-3.2 (ADR-1028-5 D14, §128): management-plane события Cover
    Styles (не только runtime-генерация). Safe fields: style_id/asset_id/
    stage/reason/HTTP-класс — БЕЗ raw DB exceptions (§129: техдетали в
    логи). Fail-open: телеметрия не рвёт маршрут."""
    try:
        from services.agentic_events import emit_agentic_event
        emit_agentic_event(
            event, stage=str(stage), reason=str(reason),
            style_id=str(style_id) if style_id else None,
            asset_id=str(asset_id) if asset_id else None,
            http_status=int(http_status) if http_status else None)
    except Exception:
        pass
    logger.warning(
        "%s | stage=%s | reason=%s | style_id=%s | asset_id=%s | http=%s",
        event, stage, reason, style_id or "-", asset_id or "-",
        http_status or "-")


def _public_profile(profile: dict, refs: list | None = None, *,
                    viewer_is_admin: bool = True) -> dict:
    """R17-safe представление профиля (без секретов)."""
    refs = refs if refs is not None else profile.get("references") or []
    is_seeded = profile.get("origin") == registry.ORIGIN_SEEDED
    # ASAP 4.2 (D5.7): seeded canonical definition/references/issue/provider
    # редактирует только глобальный админ; не-админ видит/выбирает/клонирует.
    can_edit = (not is_seeded) or bool(viewer_is_admin)
    # ASAP 4.3 (§4/§5): пара показывается ТОЛЬКО если это один успешный job
    # текущей revision; seeded placeholder-указатели (preview_revision=None)
    # наружу не отдаются как реальный пример.
    pair_valid = registry.preview_pair_current(profile)
    if pair_valid:
        before_id = profile.get("preview_before_asset_id")
        after_id = profile.get("preview_after_asset_id")
    else:
        before_id = after_id = None
    preview_source = "test" if pair_valid else "example"
    return {
        "profile_id": profile.get("profile_id"),
        "name": profile.get("name"),
        "origin": profile.get("origin") or registry.ORIGIN_CUSTOM,
        "is_example": is_seeded,
        "can_edit": can_edit,
        "pipeline_mode": profile.get("pipeline_mode")
        or registry.MODE_GENERATE_THEN_EDIT,
        "instruction": profile.get("instruction") or "",
        "counter_enabled": bool(profile.get("counter_enabled")),
        # §RC-B/T-4868: публичный контракт — next = last_assigned + 1;
        # `counter_value` остаётся legacy/compat (внутренний last_assigned).
        "next_issue_number": registry.next_issue_number(profile),
        "counter_value": profile.get("counter_value"),
        "counter_format": profile.get("counter_format")
        or registry.SEEDED_COUNTER_FORMAT,
        "model_mode": profile.get("model_mode") or registry.MODEL_MODE_DEFAULT,
        "connection_id": profile.get("connection_id"),
        "model_id": profile.get("model_id"),
        "revision": profile.get("revision"),
        "enabled": bool(profile.get("enabled", True)),
        "preview_before_url": _asset_url(before_id),
        "preview_after_url": _asset_url(after_id),
        "preview_before_asset_id": before_id,
        "preview_after_asset_id": after_id,
        "preview_revision": profile.get("preview_revision"),
        "preview_job_id": (profile.get("preview_job_id") if pair_valid
                           else None),
        "preview_pair_valid": pair_valid,
        # §4 контракт дословно: status=success только у валидной пары текущей
        # revision (иначе None — «нет успешного preview»).
        "preview_status": ("success" if pair_valid else None),
        "preview_stale": registry.preview_is_stale(profile),
        "preview_source": preview_source,
        "preview_source_label": ("Результат теста" if preview_source == "test"
                                 else "Пример"),
        "reference_count": len(refs),
        "references": [_public_reference(r) for r in refs],
        # §RC-C/T-4869: подпись = текущий next_issue_number (не hardcoded 00).
        "preview_issue": registry.preview_issue_display(
            profile.get("counter_format") or registry.SEEDED_COUNTER_FORMAT,
            registry.next_issue_number(profile)),
    }


def _public_reference(ref: dict) -> dict:
    return {
        "ref_id": ref.get("ref_id"),
        "asset_id": ref.get("asset_id"),
        "label": ref.get("label") or "",
        "description": ref.get("description") or "",
        "ordering": ref.get("ordering") or 0,
        "url": _asset_url(ref.get("asset_id")),
    }


def _asset_url(asset_id) -> str | None:
    return f"/api/cover/assets/{asset_id}" if asset_id else None


def _viewer_is_admin(request: Request, user: WebAppUser) -> bool:
    """ASAP 4.2 (D5.7): глобальный админ смотрит API — seeded ему editable."""
    try:
        return user_is_global_admin(get_cache(request), user.id)
    except Exception:
        return False


def _assert_can_edit_seeded(request: Request, user: WebAppUser,
                            profile: dict | None) -> None:
    """Seeded canonical definition/refs/issue/provider — только глобальный
    админ (ASAP 4.2 D5.7, backend enforcement, не disabled-button)."""
    if profile is not None \
            and profile.get("origin") == registry.ORIGIN_SEEDED \
            and not _viewer_is_admin(request, user):
        raise HTTPException(
            status_code=403,
            detail="Встроенный стиль «Медведь Press» редактирует только "
                   "администратор. Можно скопировать стиль в свой.")


# ── list / read ─────────────────────────────────────────────────────────────

@cover_styles_router.get("/cover/styles")
async def cover_styles_list(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
    chat_id: Annotated[int | None, Query()] = None,
):
    """Список стилей (§5/§6/RU): `Без дополнительного стиля` + seeded + custom."""
    cache = get_cache(request)
    pg = _pg(cache)
    enabled = _enabled()
    is_admin = _viewer_is_admin(request, user)
    selected = ""
    if chat_id is not None and enabled:
        selected = await pipeline.resolve_selected_style_id(int(chat_id))
    profiles: list = []
    if enabled and pg is not None:
        rows = await registry.list_profiles(pg, include_disabled=True)
        if not rows and pg.pool is None:
            # §128: registry недоступен — НЕ тихий «пустой список».
            _emit_cover_event("COVER_STYLE_REGISTRY_LIST_FAILED",
                              stage="list", reason="pg_unavailable",
                              http_status=200)
        for row in rows:
            refs = await registry.list_references(pg, row["profile_id"])
            profiles.append(_public_profile(row, refs,
                                            viewer_is_admin=is_admin))
    elif enabled and pg is None:
        _emit_cover_event("COVER_STYLE_REGISTRY_LIST_FAILED",
                          stage="list", reason="pg_unavailable",
                          http_status=200)
    return {
        "enabled": enabled,
        "is_admin": is_admin,
        "no_style_label": NO_STYLE_LABEL,
        "selected_style_id": selected,
        "pipeline_modes": list(registry.PIPELINE_MODES),
        # ASAP 4.3 (§5): Ч/Б fallback placeholders — только UI; имена из
        # фактического listing `extra_images`, не DB-assets профиля.
        "placeholders": _placeholder_payload(),
        "styles": profiles,
    }


@cover_styles_router.get("/cover/styles/{style_id}")
async def cover_style_detail(
    style_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    cache = get_cache(request)
    pg = _pg(cache)
    if not _enabled():
        raise HTTPException(status_code=404, detail="cover styles disabled")
    if pg is None:
        raise HTTPException(status_code=503, detail="registry unavailable")
    profile = await registry.get_profile_with_refs(pg, style_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
    connection = await _connection_for(pg, profile)
    payload = _public_profile(
        profile, viewer_is_admin=_viewer_is_admin(request, user))
    # ASAP 4.4 (§2, T-4873): один effective resolver для UI meta/budget/
    # prompt-limit/editor — тот же provider+base_url+model+route+operation,
    # что исполняет production style stage (лестница §35).
    resolved = await _effective_capability(pg, profile, connection)
    payload["capabilities"] = _capabilities_public(resolved["capabilities"])
    payload["connection"] = pipeline.connection_status(
        profile=profile, capabilities=resolved["capabilities"],
        connection=resolved.get("connection"), slot=resolved.get("slot"))
    if resolved.get("connection") is not None:
        payload["connection_label"] = (resolved["connection"].get("label")
                                       or "")
    payload["effective"] = {
        "provider": resolved["provider"], "base_url": resolved["base_url"],
        "model": resolved["model"], "route": resolved["route"],
        "operation": resolved["operation"],
        "resolve_source": resolved["resolve_source"],
    }
    payload["budget"] = _budget(profile, resolved=resolved)
    # ASAP 4.3 (§7.2/§9) + 4.4 (§2): manual prompt-limit для UI редактора.
    payload["prompt_limit"] = _prompt_limit_state(profile, resolved=resolved)
    # ASAP-4 волна B (§41, T-4418): полный чек-лист полей профиля
    # (R17-safe: id/числа/булевы, без секретов — api_key не читается).
    try:
        payload["diagnostics"] = await jobs.profile_diagnostics(
            pg, profile, connection=connection)
    except Exception:
        payload["diagnostics"] = {}
    return payload


async def _effective_capability(pg, profile, connection, *, refresh: bool = False,
                                operation: str | None = None) -> dict:
    """ASAP 4.4 (§2/T-4873): единственный effective-резолвер для UI/API.

    Fail-open: ошибка резолва не ломает detail-ответ (conservative unknown).
    """
    try:
        return await pipeline.resolve_effective_edit_capability(
            profile=profile, pg=pg, connection=connection, refresh=refresh,
            operation=operation or image_caps.OPERATION_EDIT)
    except Exception:
        logger.debug("[cover_styles] effective capability resolve failed",
                     exc_info=True)
        return {
            "slot": {}, "connection": connection, "provider": "",
            "base_url": "", "model": "", "connection_id": None,
            "configured": False, "custom_unresolved": False,
            "resolve_source": "", "route": "",
            "operation": operation or image_caps.OPERATION_EDIT,
            "capabilities": image_caps.conservative_unknown(),
        }


def _capabilities_public(caps) -> dict:
    """R17-safe capability-представление + taxonomy источника лимита."""
    try:
        data = caps.as_dict()
        data["references_available"] = caps.references_available
        data["edit_supported"] = caps.edit_supported
        data["prompt_limit"]["source_taxonomy"] = (
            image_caps.prompt_limit_source_taxonomy(caps.prompt_limit.source))
        return data
    except Exception:
        return {}


def _budget(profile: dict, *, resolved: dict) -> dict:
    """Prompt budget (§9/§57): лимит + breakdown Style/Context/Refs/System.

    Источник — инструкция профиля и та же runtime-механика, что в
    `compile_style_prompt` (без выдуманных чисел; unknown остаётся unknown).
    Капабилити/route — из единого effective-resolver (§2/T-4873).
    """
    try:
        from services.image_prompt_compiler import (
            PromptComponent, P0, P1, P2, estimate_budget,
        )
        caps = resolved["capabilities"]
        instruction = str(profile.get("instruction") or "")
        counter_format = (profile.get("counter_format")
                          or registry.SEEDED_COUNTER_FORMAT)
        issue_display = registry.preview_issue_display(
            counter_format, registry.next_issue_number(profile))
        system_text = ("Сохрани номер выпуска «%s». Не добавляй дубликатов уже "
                       "присутствующих на обложке элементов." % issue_display)
        refs_text = "; ".join(
            "%s: %s" % (r.get("label") or "reference",
                        r.get("description") or "")
            for r in (profile.get("references") or []))
        components = {
            "style": len(instruction),
            "context": 0,
            "refs": len(refs_text),
            "system": len(system_text),
        }
        components["total"] = sum(components.values())
        data = estimate_budget(
            [PromptComponent(instruction, priority=P1)],
            capabilities=caps)
        # §9: breakdown последней сборки — по фактическим компонентам.
        data["components"] = components
        data["limit"] = (caps.prompt_limit.value
                         if caps.prompt_limit.known else None)
        data["limit_source"] = caps.prompt_limit.source
        data["limit_source_taxonomy"] = image_caps.prompt_limit_source_taxonomy(
            caps.prompt_limit.source)
        data["limit_is_exact"] = image_caps.prompt_limit_is_exact(
            data["limit_source_taxonomy"])
        data["limit_known"] = caps.prompt_limit.known
        data["route"] = resolved.get("route") or ""
        return data
    except Exception:
        return {"known": False}


def _prompt_limit_state(profile: dict, *, resolved: dict) -> dict:
    """§7.2/§9 + §2/T-4874: состояние manual-override и taxonomy лимита.

    mode=manual — ручной override имеет высший приоритет; mode=auto —
    машинный resolver. Секретов нет (число/единица/источник/route).
    """
    try:
        slot = resolved.get("slot") or {}
        caps = resolved["capabilities"]
        override = image_caps.manual_limit_entry(
            slot.get("provider") or resolved.get("provider") or "",
            slot.get("base_url") or resolved.get("base_url") or "",
            slot.get("model") or resolved.get("model") or "",
            image_caps.OPERATION_EDIT)
        taxonomy = image_caps.prompt_limit_source_taxonomy(
            caps.prompt_limit.source)
        return {
            "operation": image_caps.OPERATION_EDIT,
            "mode": "manual" if override else "auto",
            "value": caps.prompt_limit.value,
            "unit": caps.prompt_limit.unit,
            "limit_known": caps.prompt_limit.known,
            "source": caps.prompt_limit.source,
            "source_taxonomy": taxonomy,
            "limit_is_exact": image_caps.prompt_limit_is_exact(taxonomy),
            "route": resolved.get("route") or "",
            "resolve_source": resolved.get("resolve_source") or "",
            "provider": slot.get("provider") or resolved.get("provider") or "",
            "base_url": slot.get("base_url") or resolved.get("base_url") or "",
            "model": slot.get("model") or resolved.get("model") or "",
        }
    except Exception:
        return {"operation": image_caps.OPERATION_EDIT, "mode": "auto",
                "limit_known": False, "source": image_caps.SOURCE_UNKNOWN,
                "source_taxonomy": image_caps.TAXONOMY_UNKNOWN}


# ── CRUD ────────────────────────────────────────────────────────────────────

class ProfileBody(BaseModel):
    name: str
    instruction: str = ""
    pipeline_mode: str = registry.MODE_GENERATE_THEN_EDIT
    counter_enabled: bool = False
    # ASAP 4.4 (§RC-B/T-4868): новый UI работает с next_issue_number;
    # `counter_value` — legacy/compat (внутренний last_assigned, как в DB).
    next_issue_number: int | None = None
    counter_value: int = 0
    counter_format: str = registry.SEEDED_COUNTER_FORMAT
    model_mode: str = registry.MODEL_MODE_DEFAULT
    connection_id: str | None = None
    model_id: str | None = None
    enabled: bool = True


def _counter_value_from_body(body: "ProfileBody") -> int:
    """`next_issue_number` (N) → внутренний `counter_value = N - 1`.

    Legacy-клиент без `next_issue_number` шлёт `counter_value` — трактуется
    как внутренний last_assigned (1:1 к DB), без дрейфа при round-trip.
    """
    if body.next_issue_number is not None:
        if int(body.next_issue_number) < 1:
            raise HTTPException(
                status_code=422,
                detail="«Следующий номер» должен быть не меньше 1.")
        return int(body.next_issue_number) - 1
    return int(body.counter_value)


def _guard_mutable(cache):
    if not _enabled():
        raise HTTPException(status_code=404, detail="cover styles disabled")
    if _pg(cache) is None:
        raise HTTPException(status_code=503, detail="registry unavailable")


async def _promote_preview_requested(*, db, existing: dict,
                                     incoming: dict) -> bool:
    """T-4872: сохранён РОВНО протестированный draft → promote без генерации.

    Provenance не доверяет клиенту: durable preview job стиля должен быть
    completed, его snapshot fingerprint — совпадать с сохраняемыми
    style-affecting полями, а asset-id'ы — с текущей парой профиля.
    """
    if db is None or not existing:
        return False
    if not registry.preview_pair_current(existing):
        return False
    try:
        if registry.style_fingerprint(existing) == \
                registry.style_fingerprint(incoming):
            return False          # style не менялся — pair и так current
        jid = preview_jobs.preview_job_key(
            str(existing.get("profile_id") or ""))
        row = await jobs.get_cover_job(db, jid)
        if row is None or str(row.get("status") or "") != "completed":
            return False
        state = await jobs.load_cover_state(db, jid)
        if state is None or state.mode != preview_jobs.MODE_PREVIEW:
            return False
        fingerprint = state.draft_fingerprint
        if not fingerprint or fingerprint != registry.style_fingerprint(
                incoming):
            return False
        if str(state.preview_before_asset_id or "") != str(
                existing.get("preview_before_asset_id") or ""):
            return False
        if str(state.preview_after_asset_id or "") != str(
                existing.get("preview_after_asset_id") or ""):
            return False
        return True
    except Exception:
        logger.debug("[cover_styles] promote check failed", exc_info=True)
        return False


@cover_styles_router.post("/cover/styles")
async def cover_style_upsert(
    body: ProfileBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
    style_id: Annotated[str | None, Query()] = None,
):
    """Create/Update стиля (§63). Seeded canonical — только админ (D5.7)."""
    cache = get_cache(request)
    _guard_mutable(cache)
    if body.pipeline_mode not in registry.PIPELINE_MODES:
        raise HTTPException(status_code=422, detail="invalid pipeline_mode")
    existing = None
    if style_id:
        existing = await registry.get_profile(_pg(cache), style_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="style not found")
        # §135/D5.7: seeded definition/refs/issue/provider — только админ.
        _assert_can_edit_seeded(request, user, existing)
    # ── §104/§130-15: connection_id — настоящий FK к настроенному
    # подключению, НЕ raw URL. Custom-режим требует существующую запись.
    if body.model_mode == registry.MODEL_MODE_CUSTOM \
            and (body.connection_id or "").strip():
        cid = body.connection_id.strip()
        if cid.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="Base URL принадлежит «Настроить подключения →»; "
                       "в стиле выберите подключение из списка.")
        if await registry.get_connection(_pg(cache), cid) is None:
            raise HTTPException(status_code=422,
                                detail="Подключение не найдено.")
    profile = {
        "name": body.name.strip() or "Без названия",
        "instruction": body.instruction,
        "pipeline_mode": body.pipeline_mode,
        "counter_enabled": body.counter_enabled,
        "counter_value": _counter_value_from_body(body),
        "counter_format": body.counter_format
        or registry.SEEDED_COUNTER_FORMAT,
        "model_mode": body.model_mode,
        "connection_id": body.connection_id,
        "model_id": body.model_id,
        "enabled": body.enabled,
    }
    promote = False
    if style_id and existing is not None:
        # Seeded происхождение сохраняем (редактируемость не меняется, §6).
        profile["origin"] = existing.get("origin") or registry.ORIGIN_CUSTOM
        profile["profile_id"] = style_id
        profile["preview_before_asset_id"] = existing.get(
            "preview_before_asset_id")
        profile["preview_after_asset_id"] = existing.get(
            "preview_after_asset_id")
        profile["preview_revision"] = existing.get("preview_revision")
        # T-4872: exact tested draft → rebinding provenance к новой revision.
        promote = await _promote_preview_requested(
            db=_job_db(), existing=existing, incoming=profile)
    else:
        profile["origin"] = registry.ORIGIN_CUSTOM
    if not await registry.upsert_profile(_pg(cache), profile,
                                         promote_preview=promote):
        # §128/§129: management-failure событие; UI показывает человеческое
        # сообщение вместо голого «save failed».
        _emit_cover_event("COVER_STYLE_SAVE_FAILED", stage="upsert",
                          reason="registry_false",
                          style_id=profile.get("profile_id"),
                          http_status=503)
        raise HTTPException(
            status_code=503,
            detail="Не удалось сохранить стиль: хранилище стилей недоступно.")
    saved = await registry.get_profile_with_refs(_pg(cache),
                                                 profile["profile_id"])
    logger.info("COVER_STYLE_SAVED | style_id=%s | mode=%s | user=%s",
                profile["profile_id"], body.pipeline_mode, user.id)
    return _public_profile(saved or profile,
                           viewer_is_admin=_viewer_is_admin(request, user))


@cover_styles_router.post("/cover/styles/{style_id}/duplicate")
async def cover_style_duplicate(
    style_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """`Копировать` (§63) — особенно полезно для seeded-стиля.

    ASAP 4.2 (D5.7): клонирование seeded в свой custom разрешено пользователю
    с доступом — canonical definition при этом НЕ меняется (создаётся копия
    `origin=custom`).
    """
    cache = get_cache(request)
    _guard_mutable(cache)
    new_id = await registry.duplicate_profile(_pg(cache), style_id)
    if new_id is None:
        raise HTTPException(status_code=404, detail="style not found")
    saved = await registry.get_profile_with_refs(_pg(cache), new_id)
    return _public_profile(saved,
                           viewer_is_admin=_viewer_is_admin(request, user))


@cover_styles_router.delete("/cover/styles/{style_id}")
async def cover_style_delete(
    style_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """Мягкое удаление профиля (§63). Ассеты НЕ удаляются (§64).

    Seeded canonical удаляет только глобальный админ (D5.7)."""
    cache = get_cache(request)
    _guard_mutable(cache)
    profile = await registry.get_profile(_pg(cache), style_id)
    _assert_can_edit_seeded(request, user, profile)
    if not await registry.soft_delete_profile(_pg(cache), style_id):
        raise HTTPException(status_code=404, detail="style not found")
    return {"deleted": True, "profile_id": style_id}


class SelectBody(BaseModel):
    chat_id: int
    style_id: str = ""


@cover_styles_router.post("/cover/select")
async def cover_style_select(
    body: SelectBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """Per-chat выбор стиля (§55/DC-5): пусто → `Без дополнительного стиля`."""
    if not _enabled():
        raise HTTPException(status_code=404, detail="cover styles disabled")
    cache = get_cache(request)
    if _pg(cache) is None:
        raise HTTPException(status_code=503, detail="registry unavailable")
    style_id = (body.style_id or "").strip()
    if style_id:
        profile = await registry.get_profile(_pg(cache), style_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="style not found")
    try:
        from services import chat_params
        pg = _pg(cache)
        # HOTFIX 2.58.43 (prod «save failed» при выборе стиля):
        # 1) set_chat_params требует PgDatabase (pg=); без него
        #    ChatLorePgUnavailable → 503 на КАЖДЫЙ выбор (прецедент
        #    §93: не тот уровень хранилища на call-site).
        # 2) Патч — namespace `overrides`: плоский ключ set_chat_params
        #    молча выбрасывает (мержатся только namespaces §4.3), а читающий
        #    путь резолвит root["overrides"][key] (_resolve_from_root).
        # 3) Read-modify-write: namespace в set_chat_params ЗАМЕНЯЕТСЯ
        #    целиком — нельзя затереть прочие per-chat overrides чата
        #    (прецедент routes.py config-save).
        root = await chat_params.get_all_chat_params(int(body.chat_id),
                                                     pg=pg)
        if not root:
            # fail-open {} = PG-чтение не удалось — честный отказ, НЕ запись
            # пустого overrides поверх чужих данных.
            raise RuntimeError("chat profile read failed")
        overrides = dict(root.get("overrides") or {})
        if style_id:
            overrides["prompts.summary_cover_style_id"] = style_id
        else:
            # Снятие выбора → удаляем override: работает документированный
            # resolve-чейн (override чата → hot.get → дефолт, DC-5); хард-пин
            # «нет стиля» поверх глобального hot не создаём.
            overrides.pop("prompts.summary_cover_style_id", None)
        await chat_params.set_chat_params(
            int(body.chat_id), {"overrides": overrides},
            changed_by=user.id, pg=pg)
    except Exception:
        raise HTTPException(status_code=503, detail="save failed")
    return {"chat_id": body.chat_id, "style_id": style_id}


# ── references / assets ─────────────────────────────────────────────────────

class UploadBody(BaseModel):
    """JSON-base64 upload (без multipart-зависимости `python-multipart`)."""

    filename: str = "reference.png"
    content_base64: str
    label: str = ""
    description: str = ""


def _decode_upload(body: UploadBody) -> bytes:
    import base64
    try:
        raw = str(body.content_base64 or "")
        if "," in raw[:80] and raw.lstrip().startswith("data:"):
            raw = raw.split(",", 1)[1]
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(status_code=422, detail="Некорректные данные файла")
    if not data:
        raise HTTPException(status_code=422, detail="Пустой файл")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Файл слишком большой (максимум 4 МБ)")
    return data


@cover_styles_router.post("/cover/styles/{style_id}/references")
async def cover_reference_upload(
    style_id: str,
    body: UploadBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """Upload reference (§11/§12): PNG/JPEG/WebP, thumbnail, label/description."""
    cache = get_cache(request)
    _guard_mutable(cache)
    pg = _pg(cache)
    profile = await registry.get_profile(pg, style_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
    _assert_can_edit_seeded(request, user, profile)
    data = _decode_upload(body)
    meta = assets.store_file_bytes(data, filename=body.filename or "ref.png",
                                   origin="upload")
    if meta is None:
        _emit_cover_event("COVER_STYLE_REFERENCE_UPLOAD_FAILED",
                          stage="upload", reason="unsupported_format",
                          style_id=style_id, http_status=422)
        raise HTTPException(
            status_code=422, detail="Не удалось загрузить референс: "
            "поддерживаются только PNG, JPEG и WebP")
    if not await registry.upsert_asset(pg, meta):
        _emit_cover_event("COVER_STYLE_REFERENCE_UPLOAD_FAILED",
                          stage="upload", reason="asset_store_failed",
                          style_id=style_id, http_status=503)
        raise HTTPException(status_code=503, detail="asset store failed")
    refs = await registry.list_references(pg, style_id)
    ref_id = await registry.add_reference(pg, style_id, {
        "asset_id": meta["asset_id"], "label": body.label or body.filename,
        "description": body.description, "ordering": len(refs)})
    if ref_id is None:
        _emit_cover_event("COVER_STYLE_REFERENCE_UPLOAD_FAILED",
                          stage="add_reference", reason="registry_false",
                          style_id=style_id, http_status=503)
        raise HTTPException(status_code=503,
                            detail="Не удалось загрузить референс.")
    saved = await registry.get_profile_with_refs(pg, style_id)
    return _public_profile(saved)


@cover_styles_router.put("/cover/styles/{style_id}/references/{ref_id}")
async def cover_reference_replace(
    style_id: str,
    ref_id: str,
    body: UploadBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """Replace reference (§12): заменить картинку существующего референса."""
    cache = get_cache(request)
    _guard_mutable(cache)
    pg = _pg(cache)
    profile = await registry.get_profile(pg, style_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
    _assert_can_edit_seeded(request, user, profile)
    data = _decode_upload(body)
    meta = assets.store_file_bytes(data, filename=body.filename or "ref.png",
                                   origin="upload")
    if meta is None:
        raise HTTPException(
            status_code=422,
            detail="Поддерживаются только PNG, JPEG и WebP")
    if not await registry.upsert_asset(pg, meta):
        raise HTTPException(status_code=503, detail="asset store failed")
    ok = await registry.update_reference(
        pg, style_id, ref_id, asset_id=meta["asset_id"],
        label=(body.label or None), description=(body.description or None))
    if not ok:
        raise HTTPException(status_code=404, detail="reference not found")
    saved = await registry.get_profile_with_refs(pg, style_id)
    return _public_profile(saved or {"name": ""})


@cover_styles_router.delete("/cover/styles/{style_id}/references/{ref_id}")
async def cover_reference_remove(
    style_id: str,
    ref_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """Remove reference (§12): удаляется связь, ассет переиспользуем."""
    cache = get_cache(request)
    _guard_mutable(cache)
    profile = await registry.get_profile(_pg(cache), style_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
    _assert_can_edit_seeded(request, user, profile)
    if not await registry.remove_reference(_pg(cache), style_id, ref_id):
        raise HTTPException(status_code=404, detail="reference not found")
    saved = await registry.get_profile_with_refs(_pg(cache), style_id)
    return _public_profile(saved or {"name": ""},
                           viewer_is_admin=_viewer_is_admin(request, user))


@cover_styles_router.delete("/cover/assets/{asset_id}")
async def cover_asset_delete(
    asset_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    confirm: Annotated[bool, Query()] = False,
):
    """Dangling-guard (§64): используемый asset — 409 без `confirm=true`."""
    cache = get_cache(request)
    _guard_mutable(cache)
    pg = _pg(cache)
    used = await registry.references_using_asset(pg, asset_id)
    if used and not confirm:
        raise HTTPException(status_code=409, detail={
            "message": "Ассет используется стилями",
            "styles": [u.get("name") for u in used]})
    if used and confirm:
        for entry in used:
            refs = await registry.list_references(pg, entry["profile_id"])
            for ref in refs:
                if ref.get("asset_id") == asset_id:
                    await registry.remove_reference(
                        pg, entry["profile_id"], ref.get("ref_id"))
    if not await registry.soft_delete_asset(pg, asset_id):
        raise HTTPException(status_code=404, detail="asset not found")
    return {"deleted": True, "asset_id": asset_id}


@cover_styles_router.get("/cover/assets/{asset_id}")
async def cover_asset_raw(
    asset_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """Отдача thumbnail/preview (§12/§77) — путь берётся из PG-метаданных.

    ASAP-3.2 (§100/§128): DB-row есть, файла на managed disk НЕТ → явная
    integrity-ошибка (404 + событие ``COVER_STYLE_ASSET_MISSING`` с
    asset_id/файлом в диагностике), НЕ тихое «превью нет».
    """
    cache = get_cache(request)
    pg = _pg(cache)
    if pg is None:
        raise HTTPException(status_code=503, detail="registry unavailable")
    asset = await registry.get_asset(pg, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")
    import os
    disk_path = str(asset.get("disk_path") or "")
    if not disk_path or not os.path.exists(disk_path):
        # §100: integrity error — asset_id/файл в событии (R17-safe),
        # сырой диск-путь только в WARNING-лог диагностики.
        _emit_cover_event("COVER_STYLE_ASSET_MISSING", stage="asset_get",
                          reason="file_missing_from_disk",
                          asset_id=asset_id, http_status=404)
        logger.warning(
            "COVER_STYLE_ASSET_MISSING | asset_id=%s | disk_path=%s",
            asset_id, disk_path or "-")
        raise HTTPException(
            status_code=404,
            detail="Файл примера отсутствует на сервере.")
    return FileResponse(
        disk_path, media_type=asset.get("mime") or "image/png",
        headers={"Cache-Control": "private, max-age=300"})


@cover_styles_router.get("/cover/placeholders/{name}")
async def cover_placeholder_raw(
    name: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """ASAP 4.3 (§5): отдача Ч/Б UI-placeholder'а из `extra_images`.

    Только read-only fallback: файл НЕ является DB-asset профиля; имя — из
    фактического listing (path traversal невозможен: сверка с listing).
    """
    from pathlib import Path
    files = registry.placeholder_files()
    if name not in files.values():
        raise HTTPException(status_code=404, detail="placeholder not found")
    base = Path(registry._seed_dir())          # noqa: SLF001 (seed dir)
    path = base / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="placeholder not found")
    mime = assets._mime_for(path) or "image/png"      # noqa: SLF001
    return FileResponse(
        str(path), media_type=mime,
        headers={"Cache-Control": "private, max-age=300"})


# ── capabilities / connections ──────────────────────────────────────────────

@cover_styles_router.get("/cover/capabilities")
async def cover_capabilities(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
    profile_id: Annotated[str | None, Query()] = None,
    refresh: Annotated[bool, Query()] = False,
):
    """Capability UI (§37/§38/§71): edit/limits/sizes/sync/source + references.

    ASAP 4.4 (§2/T-4873): единый async effective-resolver (лестница §35),
    не отдельный sync-контур.
    """
    cache = get_cache(request)
    pg = _pg(cache)
    profile = None
    connection = None
    if profile_id and pg is not None:
        profile = await registry.get_profile_with_refs(pg, profile_id)
        connection = await _connection_for(pg, profile)
    try:
        resolved = await _effective_capability(pg, profile, connection,
                                               refresh=refresh)
        caps = resolved["capabilities"]
        data = _capabilities_public(caps)
        data["connection"] = pipeline.connection_status(
            profile=profile, capabilities=caps,
            connection=resolved.get("connection"), slot=resolved.get("slot"))
        data["route"] = resolved["route"]
        data["resolve_source"] = resolved["resolve_source"]
        data["no_edit_message"] = pipeline.NO_EDIT_MESSAGE
        return data
    except Exception:
        raise HTTPException(status_code=503, detail="capability resolve failed")


class PromptLimitBody(BaseModel):
    """§7.2: ручное ограничение промпта (MiniApp) для connection/model/op."""
    profile_id: str | None = None
    connection_id: str | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    operation: str = image_caps.OPERATION_EDIT
    mode: str = "auto"                      # auto | manual
    unit: str = image_caps.UNIT_CHARS
    value: int | None = None


async def _resolve_limit_slot(cache, body: PromptLimitBody) -> dict:
    """Резолв provider/base_url/model для override (профиль → слот).

    ASAP 4.4 (§2/T-4873): profile-only запросы резолвятся тем же §35
    inherited-контуром, что production/UI (live-фикс §7.2: seeded-профиль в
    режиме «По умолчанию» при пустом style-слоте адресует реальный edit-route
    `nano-gpt.com/qwen-image-3-pro`). Явно переданные provider/base_url/model
    (developer/tool путь) по-прежнему перекрывают слот.
    """
    pg = _pg(cache)
    profile = None
    connection = None
    if body.profile_id and pg is not None:
        profile = await registry.get_profile_with_refs(pg, body.profile_id)
        connection = await _connection_for(pg, profile)
    explicit = bool((body.provider or "").strip()
                    and (body.base_url or "").strip()
                    and (body.model or "").strip())
    route = ""
    if explicit:
        base_slot = pipeline.resolve_style_slot(profile=profile,
                                                connection=connection)
    else:
        resolved = await pipeline.resolve_effective_edit_capability(
            profile=profile, pg=pg, connection=connection,
            operation=body.operation if body.operation in (
                image_caps.OPERATION_GENERATE,
                image_caps.OPERATION_EDIT) else image_caps.OPERATION_EDIT)
        base_slot = resolved["slot"]
        route = resolved["route"]
    provider = (body.provider or base_slot.get("provider") or "").strip()
    base_url = (body.base_url or base_slot.get("base_url") or "").strip()
    model = (body.model or base_slot.get("model") or "").strip()
    if body.connection_id and pg is not None:
        conn = await registry.get_connection(pg, body.connection_id)
        if conn is not None:
            provider = str(conn.get("provider") or provider).strip()
            base_url = str(conn.get("base_url") or base_url).strip()
    return {"provider": provider, "base_url": base_url, "model": model,
            "route": route}


def _limit_taxonomy_fields(caps) -> dict:
    taxonomy = image_caps.prompt_limit_source_taxonomy(caps.prompt_limit.source)
    return {"source_taxonomy": taxonomy,
            "limit_is_exact": image_caps.prompt_limit_is_exact(taxonomy)}


@cover_styles_router.get("/cover/prompt-limit")
async def cover_prompt_limit_get(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
    profile_id: Annotated[str | None, Query()] = None,
):
    """§7.2/§9: текущее состояние лимита (auto/manual) для профиля/слота."""
    cache = get_cache(request)
    body = PromptLimitBody(profile_id=profile_id)
    operation = body.operation if body.operation in (
        image_caps.OPERATION_GENERATE, image_caps.OPERATION_EDIT) \
        else image_caps.OPERATION_EDIT
    slot = await _resolve_limit_slot(cache, body)
    entry = image_caps.manual_limit_entry(
        slot["provider"], slot["base_url"], slot["model"], operation)
    caps = image_caps.resolve_capabilities(
        slot["provider"], slot["base_url"], slot["model"],
        operation=operation, route=slot.get("route") or None)
    return {
        **slot,
        "operation": operation,
        "mode": "manual" if entry else "auto",
        "value": (entry or {}).get("value", caps.prompt_limit.value),
        "unit": (entry or {}).get("unit", caps.prompt_limit.unit),
        "limit_known": caps.prompt_limit.known,
        "source": caps.prompt_limit.source,
        **_limit_taxonomy_fields(caps),
    }


@cover_styles_router.post("/cover/prompt-limit")
async def cover_prompt_limit_set(
    body: PromptLimitBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """§7.2: сохранить/снять manual override (bot_settings, идемпотентно).

    Manual — высший приоритет; «сохранить стиль с маленьким лимитом» не
    блокируется (валидируется только собственная форма override)."""
    cache = get_cache(request)
    if _pg(cache) is None:
        raise HTTPException(status_code=503, detail="registry unavailable")
    operation = body.operation if body.operation in (
        image_caps.OPERATION_GENERATE, image_caps.OPERATION_EDIT) \
        else image_caps.OPERATION_EDIT
    slot = await _resolve_limit_slot(cache, body)
    if not slot.get("provider") and not slot.get("model"):
        raise HTTPException(status_code=422,
                            detail="Не удалось определить модель/подключение.")
    key = image_caps.manual_limit_key(
        slot["provider"], slot["base_url"], slot["model"], operation)
    table = dict(image_caps.manual_limit_map())
    if body.mode == "manual":
        try:
            value = int(body.value) if body.value is not None else 0
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            raise HTTPException(status_code=422,
                                detail="Укажите положительное значение лимита.")
        unit = body.unit if body.unit in image_caps.PROMPT_UNITS \
            else image_caps.UNIT_CHARS
        table[key] = {"value": value, "unit": unit}
    else:
        table.pop(key, None)
    try:
        await cache.set(image_caps.MANUAL_LIMIT_SETTING_KEY, table, "models")
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Не удалось сохранить ограничение промпта.")
    caps = image_caps.resolve_capabilities(
        slot["provider"], slot["base_url"], slot["model"], refresh=True,
        operation=operation, route=slot.get("route") or None)
    return {
        **slot,
        "mode": "manual" if body.mode == "manual" else "auto",
        "value": table.get(key, {}).get("value", caps.prompt_limit.value),
        "unit": table.get(key, {}).get("unit", caps.prompt_limit.unit),
        "limit_known": caps.prompt_limit.known,
        "source": caps.prompt_limit.source,
        "operation": operation,
        **_limit_taxonomy_fields(caps),
    }


async def _connection_for(pg, profile: dict | None) -> dict | None:
    """Запись Image Connection для custom-профиля (§104; None → default)."""
    if not profile or pg is None:
        return None
    if profile.get("model_mode") != registry.MODEL_MODE_CUSTOM:
        return None
    cid = str(profile.get("connection_id") or "").strip()
    if not cid:
        return None
    return await registry.get_connection(pg, cid)


@cover_styles_router.get("/cover/connections/status")
async def cover_connection_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
    profile_id: Annotated[str | None, Query()] = None,
):
    """Connection status (§73/§105): без реальной генерации; секретов нет.

    ASAP 4.4 (§2/T-4873): статус строится по тому же effective-слоту, что
    UI meta и production (иначе seeded-профиль показывает «не настроено»
    при работающем наследовании §35).
    """
    cache = get_cache(request)
    pg = _pg(cache)
    profile = None
    connection = None
    if profile_id and pg is not None:
        profile = await registry.get_profile_with_refs(pg, profile_id)
        connection = await _connection_for(pg, profile)
    resolved = await _effective_capability(pg, profile, connection)
    status = pipeline.connection_status(
        profile=profile, capabilities=resolved["capabilities"],
        connection=resolved.get("connection"), slot=resolved.get("slot"))
    if resolved.get("connection") is not None:
        status["connection_label"] = (resolved["connection"].get("label")
                                      or "")
    status["edit_message"] = pipeline.NO_EDIT_MESSAGE
    return status


# ── Connections CRUD (§104–§105, admin; секреты не возвращаются) ────────────

class ConnectionBody(BaseModel):
    connection_id: str | None = None
    label: str = ""
    provider: str = ""
    base_url: str
    api_key: str = ""


@cover_styles_router.get("/cover/connections")
async def cover_connections_list(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Список подключений (R17: api_key НЕ возвращается — только маска)."""
    cache = get_cache(request)
    pg = _pg(cache)
    rows = await registry.list_connections(pg)
    return {"connections": [registry._public_connection(r) for r in rows]}


@cover_styles_router.post("/cover/connections")
async def cover_connection_upsert(
    body: ConnectionBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Создать/обновить подключение (base_url + секрет живут ЗДЕСЬ, §104)."""
    cache = get_cache(request)
    if _pg(cache) is None:
        raise HTTPException(status_code=503, detail="registry unavailable")
    base_url = (body.base_url or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422,
                            detail="Base URL должен начинаться с http(s)://")
    data = {"connection_id": body.connection_id, "label": body.label,
            "provider": body.provider, "base_url": base_url,
            "api_key": body.api_key}
    if not await registry.upsert_connection(_pg(cache), data):
        _emit_cover_event("COVER_STYLE_SAVE_FAILED", stage="connection_upsert",
                          reason="registry_false", http_status=503)
        raise HTTPException(status_code=503,
                            detail="Не удалось сохранить подключение.")
    saved = await registry.get_connection(
        _pg(cache), data["connection_id"] or "")
    return registry._public_connection(saved or data)


@cover_styles_router.delete("/cover/connections/{connection_id}")
async def cover_connection_delete(
    connection_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    cache = get_cache(request)
    if _pg(cache) is None:
        raise HTTPException(status_code=503, detail="registry unavailable")
    if not await registry.soft_delete_connection(_pg(cache), connection_id):
        raise HTTPException(status_code=404, detail="connection not found")
    return {"deleted": True, "connection_id": connection_id}


# ── Test Style (§65–§67) ────────────────────────────────────────────────────

class StyleDraftBody(BaseModel):
    """ASAP 4.4 (T-4870, preferred-контракт): snapshot style-affecting полей
    текущего редактора. НЕ сохраняется как профиль; owner/origin/RBAC/
    references берутся из durable registry. `extra="forbid"` — клиент не
    может протащить произвольные поля."""
    model_config = {"extra": "forbid"}

    instruction: str | None = None
    pipeline_mode: str | None = None
    counter_enabled: bool | None = None
    next_issue_number: int | None = None
    counter_format: str | None = None
    model_mode: str | None = None
    connection_id: str | None = None
    model_id: str | None = None


class TestStyleBody(BaseModel):
    profile_id: str
    # ASAP 4.4 (§RC-D): draft snapshot текущего редактора (см. StyleDraftBody).
    draft: StyleDraftBody | None = None
    # ASAP 4.2: upload — ТОЛЬКО явное действие. Основной путь «Проверить стиль»
    # НЕ требует файла (base cover генерируется configured provider/model).
    filename: str = ""
    content_base64: str = ""


_MAX_DRAFT_INSTRUCTION = 20000
_MAX_DRAFT_COUNTER_FORMAT = 200


async def _validated_draft_snapshot(pg, draft: "StyleDraftBody | None"
                                    ) -> dict | None:
    """Нормализовать draft snapshot (T-4870) или 422.

    Возвращает внутреннюю форму style-affecting полей (counter_value =
    next_issue_number - 1); RBAC/owner/references сюда не попадают.
    """
    if draft is None:
        return None
    overrides = draft.model_dump(exclude_none=True)
    if not overrides:
        return {}
    if "pipeline_mode" in overrides \
            and overrides["pipeline_mode"] not in registry.PIPELINE_MODES:
        raise HTTPException(status_code=422, detail="invalid pipeline_mode")
    if "model_mode" in overrides \
            and overrides["model_mode"] not in (registry.MODEL_MODE_DEFAULT,
                                                registry.MODEL_MODE_CUSTOM):
        raise HTTPException(status_code=422, detail="invalid model_mode")
    if "next_issue_number" in overrides:
        if int(overrides["next_issue_number"]) < 1:
            raise HTTPException(
                status_code=422,
                detail="«Следующий номер» должен быть не меньше 1.")
        overrides["counter_value"] = int(overrides.pop("next_issue_number")) - 1
    if "instruction" in overrides \
            and len(str(overrides["instruction"])) > _MAX_DRAFT_INSTRUCTION:
        raise HTTPException(status_code=422,
                            detail="Инструкция слишком длинная.")
    if "counter_format" in overrides:
        if len(str(overrides["counter_format"])) > _MAX_DRAFT_COUNTER_FORMAT:
            raise HTTPException(status_code=422,
                                detail="Формат номера слишком длинный.")
        overrides["counter_format"] = str(overrides["counter_format"]) \
            or registry.SEEDED_COUNTER_FORMAT
    if "connection_id" in overrides:
        cid = str(overrides["connection_id"] or "").strip() or None
        if cid and cid.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="Base URL принадлежит «Настроить подключения →»; "
                       "в стиле выберите подключение из списка.")
        if cid and await registry.get_connection(pg, cid) is None:
            raise HTTPException(status_code=422,
                                detail="Подключение не найдено.")
        overrides["connection_id"] = cid
    if "model_id" in overrides:
        overrides["model_id"] = str(overrides["model_id"] or "").strip() or None
    return overrides


def _human_style_fail_message(meta: dict) -> str:
    """§48/§75 + D5.8: основной UI — человеческая фраза; machine reason
    остаётся в `developer_reason` (Developer details). ASAP 4.3: единая
    таблица фраз — в `services.cover_style_preview`."""
    fail = str(meta.get("fail_reason") or meta.get("reason") or "")
    return preview_jobs.preview_human_message(fail)


def _preview_source_label(profile: dict) -> str:
    return ("Результат теста"
            if registry.preview_pair_current(profile) else "Пример")


@cover_styles_router.post("/cover/test-style")
async def cover_test_style(
    body: TestStyleBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """`Проверить стиль` (§65; ASAP 4.3 §2): КОРОТКИЙ start durable preview job.

    Возвращает `{job_id, status:"queued"}` почти сразу — base generation и
    style edit выполняются фоновым backend job (никакого долгого browser
    fetch). RBAC: seeded canonical Test Style — только глобальный админ.
    Issue counter не расходуется (mode=preview), публикации нет.
    """
    import uuid
    cache = get_cache(request)
    _guard_mutable(cache)
    pg = _pg(cache)
    profile = await registry.get_profile_with_refs(pg, body.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
    # ASAP 4.2 (M-ASAP42-1, D5.7): seeded canonical Test Style — только
    # глобальный админ (backend enforcement, не только disabled-button).
    _assert_can_edit_seeded(request, user, profile)
    # T-4870: snapshot текущего редактора (style-affecting); DB-профиль не
    # перезаписывается, references/owner/RBAC — из durable registry.
    draft_snapshot = await _validated_draft_snapshot(pg, body.draft)
    effective = (registry.merge_draft_snapshot(profile, draft_snapshot)
                 if draft_snapshot is not None else profile)
    db = _job_db()
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Сервис фоновых задач недоступен. Попробуйте позже.")
    base_upload_meta = None
    if (body.content_base64 or "").strip():
        # Legacy/явный upload: файл выбрал сам пользователь; durable job
        # использует его как base без генерации.
        data = _decode_upload(UploadBody(
            filename=body.filename or "base.png",
            content_base64=body.content_base64))
        base_upload_meta = assets.store_file_bytes(
            data, filename=body.filename or "base.png",
            origin="generated_preview")
        if base_upload_meta is None:
            raise HTTPException(status_code=422,
                                detail="Неподдерживаемый формат")
        if not await registry.upsert_asset(pg, base_upload_meta):
            raise HTTPException(status_code=503, detail="asset store failed")
    correlation_id = "cover_test_" + uuid.uuid4().hex[:12]
    try:
        started = await preview_jobs.start_preview_job(
            db, profile=effective, pg=pg, correlation_id=correlation_id,
            brief=TEST_STYLE_BRIEF, base_upload_meta=base_upload_meta,
            draft_snapshot=draft_snapshot)
    except Exception:
        logger.warning("[cover_styles] preview job start failed",
                       exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Не удалось запустить проверку стиля. Попробуйте позже.")
    if not started.get("job_id"):
        raise HTTPException(
            status_code=503,
            detail="Не удалось запустить проверку стиля. Попробуйте позже.")
    return {
        "job_id": started["job_id"],
        "status": started.get("status") or "queued",
        "stage": started.get("stage") or preview_jobs.STAGE_QUEUED,
        "reused": bool(started.get("reused")),
        "message": ("Проверка уже выполняется." if started.get("reused")
                    else "Проверка запущена."),
        "preview_issue": registry.preview_issue_display(
            effective.get("counter_format") or registry.SEEDED_COUNTER_FORMAT,
            registry.next_issue_number(effective)),
    }


@cover_styles_router.get("/cover/test-style/{job_id}")
async def cover_test_style_status(
    job_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
):
    """ASAP 4.3 (§2.2): бесплатный статус durable preview job.

    Только безопасные diagnostics (stage/времена/provider/model/human+machine
    reason/URL-ы preview); API keys и полные prompt не отдаются. Повторные
    чтения не создают provider-запросов; осиротевшая активная джоба после
    рестарта best-effort возобновляется (§2.3).
    """
    cache = get_cache(request)
    if not _enabled():
        raise HTTPException(status_code=404, detail="cover styles disabled")
    db = _job_db()
    if db is None:
        raise HTTPException(status_code=503,
                            detail="Сервис фоновых задач недоступен.")
    snapshot = await preview_jobs.job_status(db, job_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        await preview_jobs.maybe_resume(db, _pg(cache), snapshot)
    except Exception:
        logger.debug("[cover_styles] preview resume check failed",
                     exc_info=True)
    # D7/T-5252/T-5253 (web-slice): CoverPromptManifest — расширение ответа
    # СУЩЕСТВУЮЩЕГО job-endpoint'а (D17: не новые роуты; routes.py пин цел).
    # Fail-closed: полный манифест (include_prompt=True) видит только
    # глобальный админ; не-админ — ничего (ключа нет), нет манифеста —
    # ключа нет (UI прячет блок, не показывает «пусто»).
    if _viewer_is_admin(request, user):
        manifest = await preview_jobs.job_manifest(db, job_id,
                                                   include_prompt=True)
        if manifest is not None:
            snapshot["prompt_manifest"] = manifest
    return snapshot
