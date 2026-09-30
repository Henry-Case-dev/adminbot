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
from services import cover_style_registry as registry
from web.api.deps import (get_cache, requires_global_admin,
                          requires_permission)

logger = logging.getLogger(__name__)

NO_STYLE_LABEL = "Без дополнительного стиля"
# §12/§2.3: лимит размера upload (legacy-контракт img2img — ≤4 МБ).
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
cover_styles_router = APIRouter()


def _pg(cache):
    return getattr(cache, "pg", None)


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


def _public_profile(profile: dict, refs: list | None = None) -> dict:
    """R17-safe представление профиля (без секретов)."""
    refs = refs if refs is not None else profile.get("references") or []
    return {
        "profile_id": profile.get("profile_id"),
        "name": profile.get("name"),
        "origin": profile.get("origin") or registry.ORIGIN_CUSTOM,
        "is_example": profile.get("origin") == registry.ORIGIN_SEEDED,
        "pipeline_mode": profile.get("pipeline_mode")
        or registry.MODE_GENERATE_THEN_EDIT,
        "instruction": profile.get("instruction") or "",
        "counter_enabled": bool(profile.get("counter_enabled")),
        "counter_value": profile.get("counter_value"),
        "counter_format": profile.get("counter_format")
        or registry.SEEDED_COUNTER_FORMAT,
        "model_mode": profile.get("model_mode") or registry.MODEL_MODE_DEFAULT,
        "connection_id": profile.get("connection_id"),
        "model_id": profile.get("model_id"),
        "revision": profile.get("revision"),
        "enabled": bool(profile.get("enabled", True)),
        "preview_before_url": _asset_url(profile.get("preview_before_asset_id")),
        "preview_after_url": _asset_url(profile.get("preview_after_asset_id")),
        "preview_before_asset_id": profile.get("preview_before_asset_id"),
        "preview_after_asset_id": profile.get("preview_after_asset_id"),
        "preview_revision": profile.get("preview_revision"),
        "preview_stale": registry.preview_is_stale(profile),
        "reference_count": len(refs),
        "references": [_public_reference(r) for r in refs],
        "preview_issue": registry.preview_issue_display(
            profile.get("counter_format") or registry.SEEDED_COUNTER_FORMAT),
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
            profiles.append(_public_profile(row, refs))
    elif enabled and pg is None:
        _emit_cover_event("COVER_STYLE_REGISTRY_LIST_FAILED",
                          stage="list", reason="pg_unavailable",
                          http_status=200)
    return {
        "enabled": enabled,
        "no_style_label": NO_STYLE_LABEL,
        "selected_style_id": selected,
        "pipeline_modes": list(registry.PIPELINE_MODES),
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
    payload = _public_profile(profile)
    payload["capabilities"] = jobs_public_capabilities(
        profile, connection=connection)
    payload["connection"] = pipeline.connection_status(
        profile=profile, connection=connection)
    if connection is not None:
        payload["connection_label"] = connection.get("label") or ""
    payload["budget"] = _budget(profile)
    return payload


def jobs_public_capabilities(profile: dict, *,
                             connection: dict | None = None) -> dict:
    try:
        caps = pipeline.slot_capabilities(profile=profile,
                                          connection=connection)
        data = caps.as_dict()
        data["references_available"] = caps.references_available
        data["edit_supported"] = caps.edit_supported
        return data
    except Exception:
        return {}


def _budget(profile: dict) -> dict:
    try:
        from services import image_capabilities as cap
        caps = pipeline.slot_capabilities(profile=profile)
        from services.image_prompt_compiler import (
            PromptComponent, P1, estimate_budget,
        )
        return estimate_budget(
            [PromptComponent(profile.get("instruction") or "", priority=P1)],
            capabilities=caps)
    except Exception:
        return {"known": False}


# ── CRUD ────────────────────────────────────────────────────────────────────

class ProfileBody(BaseModel):
    name: str
    instruction: str = ""
    pipeline_mode: str = registry.MODE_GENERATE_THEN_EDIT
    counter_enabled: bool = False
    counter_value: int = 0
    counter_format: str = registry.SEEDED_COUNTER_FORMAT
    model_mode: str = registry.MODEL_MODE_DEFAULT
    connection_id: str | None = None
    model_id: str | None = None
    enabled: bool = True


def _guard_mutable(cache):
    if not _enabled():
        raise HTTPException(status_code=404, detail="cover styles disabled")
    if _pg(cache) is None:
        raise HTTPException(status_code=503, detail="registry unavailable")


@cover_styles_router.post("/cover/styles")
async def cover_style_upsert(
    body: ProfileBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
    style_id: Annotated[str | None, Query()] = None,
):
    """Create/Update custom-стиля (§63). Seeded-стиль редактируется как обычный."""
    cache = get_cache(request)
    _guard_mutable(cache)
    if body.pipeline_mode not in registry.PIPELINE_MODES:
        raise HTTPException(status_code=422, detail="invalid pipeline_mode")
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
        "counter_value": body.counter_value,
        "counter_format": body.counter_format
        or registry.SEEDED_COUNTER_FORMAT,
        "model_mode": body.model_mode,
        "connection_id": body.connection_id,
        "model_id": body.model_id,
        "enabled": body.enabled,
    }
    if style_id:
        existing = await registry.get_profile(_pg(cache), style_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="style not found")
        # Seeded происхождение сохраняем (редактируемость не меняется, §6).
        profile["origin"] = existing.get("origin") or registry.ORIGIN_CUSTOM
        profile["profile_id"] = style_id
        profile["preview_before_asset_id"] = existing.get(
            "preview_before_asset_id")
        profile["preview_after_asset_id"] = existing.get(
            "preview_after_asset_id")
        profile["preview_revision"] = existing.get("preview_revision")
    else:
        profile["origin"] = registry.ORIGIN_CUSTOM
    if not await registry.upsert_profile(_pg(cache), profile):
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
    return _public_profile(saved or profile)


@cover_styles_router.post("/cover/styles/{style_id}/duplicate")
async def cover_style_duplicate(
    style_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """`Копировать` (§63) — особенно полезно для seeded-стиля."""
    cache = get_cache(request)
    _guard_mutable(cache)
    new_id = await registry.duplicate_profile(_pg(cache), style_id)
    if new_id is None:
        raise HTTPException(status_code=404, detail="style not found")
    saved = await registry.get_profile_with_refs(_pg(cache), new_id)
    return _public_profile(saved)


@cover_styles_router.delete("/cover/styles/{style_id}")
async def cover_style_delete(
    style_id: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Мягкое удаление профиля (§63). Ассеты НЕ удаляются (§64)."""
    cache = get_cache(request)
    _guard_mutable(cache)
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
        await chat_params.set_chat_params(
            int(body.chat_id), {"prompts.summary_cover_style_id": style_id},
            changed_by=user.id)
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
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Upload reference (§11/§12): PNG/JPEG/WebP, thumbnail, label/description."""
    cache = get_cache(request)
    _guard_mutable(cache)
    pg = _pg(cache)
    profile = await registry.get_profile(pg, style_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
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
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Replace reference (§12): заменить картинку существующего референса."""
    cache = get_cache(request)
    _guard_mutable(cache)
    pg = _pg(cache)
    profile = await registry.get_profile(pg, style_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
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
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Remove reference (§12): удаляется связь, ассет переиспользуем."""
    cache = get_cache(request)
    _guard_mutable(cache)
    if not await registry.remove_reference(_pg(cache), style_id, ref_id):
        raise HTTPException(status_code=404, detail="reference not found")
    saved = await registry.get_profile_with_refs(_pg(cache), style_id)
    return _public_profile(saved or {"name": ""})


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


# ── capabilities / connections ──────────────────────────────────────────────

@cover_styles_router.get("/cover/capabilities")
async def cover_capabilities(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission('access'))],
    profile_id: Annotated[str | None, Query()] = None,
    refresh: Annotated[bool, Query()] = False,
):
    """Capability UI (§37/§38/§71): edit/limits/sizes/sync/source + references."""
    cache = get_cache(request)
    pg = _pg(cache)
    profile = None
    connection = None
    if profile_id and pg is not None:
        profile = await registry.get_profile_with_refs(pg, profile_id)
        connection = await _connection_for(pg, profile)
    try:
        caps = pipeline.slot_capabilities(profile=profile, refresh=refresh,
                                          connection=connection)
        data = caps.as_dict()
        data["references_available"] = caps.references_available
        data["edit_supported"] = caps.edit_supported
        data["connection"] = pipeline.connection_status(
            profile=profile, capabilities=caps, connection=connection)
        data["no_edit_message"] = pipeline.NO_EDIT_MESSAGE
        return data
    except Exception:
        raise HTTPException(status_code=503, detail="capability resolve failed")


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
    """Connection status (§73/§105): без реальной генерации; секретов нет."""
    cache = get_cache(request)
    pg = _pg(cache)
    profile = None
    connection = None
    if profile_id and pg is not None:
        profile = await registry.get_profile_with_refs(pg, profile_id)
        connection = await _connection_for(pg, profile)
    status = pipeline.connection_status(profile=profile, connection=connection)
    if connection is not None:
        status["connection_label"] = connection.get("label") or ""
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

class TestStyleBody(BaseModel):
    profile_id: str
    filename: str = "base.png"
    content_base64: str


@cover_styles_router.post("/cover/test-style")
async def cover_test_style(
    body: TestStyleBody,
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """`Протестировать стиль` (§65): ТОЛЬКО Style Edit job, без Summary.

    Не расходует production counter (mode=preview, §66). Результат сохраняется
    как отдельный preview-asset; логируется `mode=preview` (§67).
    """
    cache = get_cache(request)
    _guard_mutable(cache)
    pg = _pg(cache)
    profile = await registry.get_profile_with_refs(pg, body.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="style not found")
    data = _decode_upload(UploadBody(filename=body.filename,
                                     content_base64=body.content_base64))
    base_meta = assets.store_file_bytes(data, filename=body.filename or "base.png",
                                        origin="generated_preview")
    if base_meta is None:
        raise HTTPException(status_code=422, detail="Неподдерживаемый формат")
    await registry.upsert_asset(pg, base_meta)
    meta = await jobs.run_style_preview(
        profile=profile, base_image_path=base_meta["disk_path"], pg=_pg(cache))
    if not meta.get("applied"):
        # §48/§75: понятный русский статус; машинный reason — в техдеталях.
        fail = str(meta.get("fail_reason") or "")
        message = meta.get("message") or ""
        if fail == "edit_unsupported":
            message = pipeline.NO_EDIT_MESSAGE
        elif fail in ("not_configured", "no_input_images"):
            message = ("Модель обработки не настроена. Откройте «Настроить "
                       "подключения →» и выберите модель с поддержкой edit.")
        elif not message:
            message = ("Не удалось применить стиль. Проверьте подключение и "
                       "модель обработки.")
        return {
            "applied": False,
            "reason": meta.get("reason"),
            "fail_reason": fail,
            "message": message,
            "preview_issue": meta.get("preview_issue"),
        }
    stored = assets.store_file_bytes(
        open(meta["styled_path"], "rb").read(),
        filename="preview_style.jpg", origin="generated_preview")
    asset_id = None
    if stored is not None and await registry.upsert_asset(pg, stored):
        asset_id = stored["asset_id"]
    # §10/SC-24: сохранить результат Test Style как preview текущей revision.
    preview_revision = None
    if asset_id is not None:
        preview_revision = profile.get("revision")
        await registry.set_preview(
            pg, body.profile_id, after_asset_id=asset_id,
            revision=preview_revision,
            before_asset_id=base_meta["asset_id"])
    return {
        "applied": True,
        "reason": "",
        "preview_issue": meta.get("preview_issue"),
        "asset_id": asset_id,
        "url": _asset_url(asset_id),
        "preview_revision": preview_revision,
        "preview_stale": False,
        "model": meta.get("model"),
        "provider": meta.get("provider"),
        "duration_ms": meta.get("duration_ms"),
    }
