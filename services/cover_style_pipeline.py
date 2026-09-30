"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D3/D4/D9;
spec §3.2/§3.3/§3.9, tasks T-4116…T-4123) — Cover Style pipeline helpers.

Раздельные model slots:
  * `Base Cover Generation`  — существующие `models.image_*` (§32);
  * `Cover Style Processing` — новые `models.image_style_*`/`keys.image_style_api_key`
    (§4.1/D3).

Style Edit — **нормализатор** (не overlay, §23); capability-gated (§38): если
модель не умеет `image_edit` — API не вызывается, публикуется base (degraded).

Здесь — резолв connection/model слота, per-style override, нормализация
prompt из профиля и gate §38. Сетевой edit-вызов — Pass 2 (block F).
"""
from __future__ import annotations

import logging

from config.settings import settings
from services import hot_config as hot
from services import image_capabilities as cap

logger = logging.getLogger(__name__)

KEY_STYLE_BASE_URL = "models.image_style_base_url"
KEY_STYLE_MODEL = "models.image_style_model"
KEY_STYLE_API_KEY = "keys.image_style_api_key"
KEY_BASE_URL = "models.image_base_url"
KEY_MODEL = "models.image_model"

MODEL_MODE_DEFAULT = "default"
MODEL_MODE_CUSTOM = "custom"

# §38: понятная пользователю ошибка модели без edit.
NO_EDIT_MESSAGE = ("Эта модель не умеет редактировать готовые изображения "
                   "и не подходит для Cover Style Processing.")


def cover_styles_enabled() -> bool:
    """Kill-switch `COVER_STYLES_ENABLED` (env-only ClassVar, default ON)."""
    try:
        return bool(getattr(settings, "COVER_STYLES_ENABLED", True))
    except Exception:      # pragma: no cover - defensive
        return True


def _resolve_str(key: str, default: str = "") -> str:
    try:
        value = hot.get(key, default)
    except Exception:
        value = default
    return str(value if value not in (None, "") else default)


def resolve_style_slot(*, profile: dict | None = None) -> dict:
    """Резолв connection/model для Cover Style Processing (§31–§34).

    Per-style override (`model.custom`) → профиль; иначе глобальный default
    (`models.image_style_*`). Секреты — только здесь (Connections, R17).
    """
    base_url = _resolve_str(KEY_STYLE_BASE_URL,
                            getattr(settings, "IMAGE_STYLE_BASE_URL", ""))
    model = _resolve_str(KEY_STYLE_MODEL,
                         getattr(settings, "IMAGE_STYLE_MODEL", ""))
    connection_id = "default"
    provider = _provider_of(base_url)
    if profile and profile.get("model_mode") == MODEL_MODE_CUSTOM:
        override_url = str(profile.get("connection_id") or "").strip()
        override_model = str(profile.get("model_id") or "").strip()
        if override_url:
            base_url = override_url
            provider = _provider_of(base_url)
            connection_id = "custom"
        if override_model:
            model = override_model
    return {
        "base_url": base_url,
        "model": model,
        "provider": provider,
        "connection_id": connection_id,
        "configured": bool(base_url and model),
    }


def _provider_of(base_url: str) -> str:
    raw = str(base_url or "").strip().lower()
    if not raw:
        return ""
    try:
        from urllib.parse import urlsplit
        host = urlsplit(raw).netloc or raw
    except Exception:
        host = raw
    return host


def slot_capabilities(*, profile: dict | None = None,
                      discovery: dict | None = None,
                      endpoints: dict | None = None,
                      refresh: bool = False) -> cap.ImageModelCapabilities:
    """Capabilities выбранного Style-слота (resolver, §3.7/§71)."""
    slot = resolve_style_slot(profile=profile)
    return cap.resolve_capabilities(
        slot["provider"], slot["base_url"], slot["model"],
        discovery=discovery, endpoints=endpoints, refresh=refresh)


def check_edit_allowed(*, profile: dict | None = None,
                       capabilities: cap.ImageModelCapabilities | None = None,
                       ) -> tuple[bool, str]:
    """Gate §38: проверka `image_edit` ПЕРЕД edit-вызовом (без API-вызова).

    Возвращает `(allowed, message)`. `unknown` — НЕ блокирует (сохранение
    профиля разрешено, §58); блокируем только явное `image_edit=no`.
    """
    caps = capabilities or slot_capabilities(profile=profile)
    if caps.image_edit == cap.FALSE:
        return False, NO_EDIT_MESSAGE
    return True, ""


def normalizer_instruction(profile: dict) -> str:
    """Style Edit = нормализатор (§23): ensure/replace, без дублей.

    Возвращает инструкцию профиля как есть; семантика ensure/replace заложена
    в seeded prompt (§24). Runtime НЕ добавляет special-case по имени стиля.
    """
    return str((profile or {}).get("instruction") or "").strip()


def pipeline_mode(profile: dict | None) -> str:
    """Режим пайплайна профиля (§54); None-профиль = `Без дополнительного стиля`."""
    if not profile:
        return "none"
    return str(profile.get("pipeline_mode") or "generate_then_edit")


def uses_base_generation(profile: dict | None) -> bool:
    """Нужна ли базовая генерация (generate_only/generate_then_edit)."""
    mode = pipeline_mode(profile)
    return mode in ("none", "generate_only", "generate_then_edit")


def uses_style_stage(profile: dict | None) -> bool:
    """Нужна ли Style-стадия (только при включённом kill-switch и профиле)."""
    if not cover_styles_enabled() or not profile:
        return False
    return pipeline_mode(profile) in ("generate_then_edit", "edit_only")


# ── per-chat выбор стиля (DC-5) ─────────────────────────────────────────────

async def resolve_selected_style_id(chat_id: int) -> str:
    """per-chat выбор Style Profile (`prompts.summary_cover_style_id`, DC-5).

    Пусто → `Без дополнительного стиля`. Резолв как у base-промпта:
    override чата → `hot.get` → дефолт. Fail-open → пусто.
    """
    try:
        from services import chat_params
        raw = await chat_params.get_chat_param(
            chat_id, "prompts.summary_cover_style_id", None)
    except Exception:
        logger.warning("[cover_style] per-chat style resolve failed | chat=%s",
                       chat_id)
        raw = hot.get("prompts.summary_cover_style_id", "")
    value = str(raw or "").strip()
    return value


# ── connection validation (§73) ─────────────────────────────────────────────

def connection_status(*, profile: dict | None = None,
                      capabilities: cap.ImageModelCapabilities | None = None,
                      ) -> dict:
    """Статус подключения Style-слота для UI (§73): без реальной генерации.

    Возвращает `{configured, connected, api_key_set, edit_supported, message}`.
    API key проверяется по наличию (`keys.image_style_api_key`), НЕ логируется.
    """
    slot = resolve_style_slot(profile=profile)
    key_set = bool(_resolve_str(
        KEY_STYLE_API_KEY, getattr(settings, "IMAGE_STYLE_API_KEY", "")))
    caps = capabilities or (
        slot_capabilities(profile=profile) if slot["configured"] else None)
    edit_supported = None
    if caps is not None:
        edit_supported = caps.edit_supported
    if not slot["configured"]:
        msg = "Адрес и модель не настроены"
    elif not key_set:
        msg = "API ключ не настроен"
    else:
        msg = "Подключено"
    return {
        "configured": slot["configured"],
        "connected": bool(slot["configured"] and key_set),
        "api_key_set": key_set,
        "edit_supported": edit_supported,
        "message": msg,
    }


# ── provenance артефакта (§30) ──────────────────────────────────────────────

def build_provenance(*, summary_run_id: str | None, job_id: str | None = None,
                     style_id: str | None = None,
                     style_revision: int | None = None,
                     issue_number: int | None = None,
                     base_asset_id: str | None = None,
                     final_asset_id: str | None = None,
                     reference_asset_ids: list | None = None,
                     provider: str = "", model: str = "",
                     connection_id: str = "", status: str = "staged",
                     fallback_mode: str = "",
                     mode: str = "production") -> dict:
    """Metadata итоговой картинки (§30) для durable provenance.

    Технические имена — только для техдеталей; в PG-строку `cover_style_provenance`.
    """
    return {
        "summary_run_id": summary_run_id,
        "job_id": job_id,
        "style_id": style_id,
        "style_revision": style_revision,
        "issue_number": issue_number,
        "base_asset_id": base_asset_id,
        "final_asset_id": final_asset_id,
        "reference_asset_ids": reference_asset_ids or [],
        "provider": provider,
        "model": model,
        "connection_id": connection_id,
        "status": status,
        "fallback_mode": fallback_mode,
        "mode": mode,
    }


