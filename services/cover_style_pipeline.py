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

# ── ASAP 4.1 волна 6 (T-4619, spec §6 F.2; ADR-1028-8 D7.2): источники
# резолва Style-слота (лестница наследования §35; событие
# COVER_STYLE_RESOLVE несёт это значение — точная причина видима).
SLOT_SOURCE_GLOBAL_STYLE = "global_style_slot"      # models.image_style_* (2.58.46)
SLOT_SOURCE_PROFILE_CONNECTION = "profile_connection"  # model_mode=custom
SLOT_SOURCE_CONNECTIONS_DEFAULT = "connections_default"  # Connections layer
SLOT_SOURCE_GLOBAL_IMAGE = "global_image_slot"      # models.image_* (глобальный
# image provider+model — «global/default image-edit provider + model» §35)


def style_global_default_enabled() -> bool:
    """Kill-switch `SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED` (env-only
    ClassVar, default ON; OFF → текущий resolver байт-в-бит 2.58.46)."""
    try:
        return bool(getattr(settings, "SUMMARY_STYLE_GLOBAL_DEFAULT_ENABLED",
                            True))
    except Exception:      # pragma: no cover - defensive
        return True


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


def resolve_style_slot(*, profile: dict | None = None,
                       connection: dict | None = None) -> dict:
    """Резолв connection/model для Cover Style Processing (§31–§34).

    ASAP-3.2 (ADR-1028-5 D14, §103–§105): Image Connection → Style
    Processing Slot → Style Profile. ``profile.connection_id`` — настоящий
    FK к настроенному подключению (НЕ raw URL); запись подключения
    (base_url/api_key) передаётся параметром ``connection`` (caller в
    async-контексте читает её из реестра). Профиль НЕ хранит секрет;
    Base URL принадлежит Connections. Per-style override (`model.custom`)
    без резолвленного подключения → честный fallback на default-слот
    (`models.image_style_*`) — сырой URL из профиля НЕ используется.
    """
    base_url = _resolve_str(KEY_STYLE_BASE_URL,
                            getattr(settings, "IMAGE_STYLE_BASE_URL", ""))
    model = _resolve_str(KEY_STYLE_MODEL,
                         getattr(settings, "IMAGE_STYLE_MODEL", ""))
    connection_id = "default"
    provider = _provider_of(base_url)
    custom_unresolved = False
    if profile and profile.get("model_mode") == MODEL_MODE_CUSTOM:
        override_id = str(profile.get("connection_id") or "").strip()
        override_model = str(profile.get("model_id") or "").strip()
        if override_id and connection is not None:
            conn_url = str(connection.get("base_url") or "").strip()
            if conn_url:
                base_url = conn_url
                provider = _provider_of(base_url)
                connection_id = override_id
            else:
                custom_unresolved = True
        elif override_id:
            # FK задан, запись недоступна (PG down/удалена) — fallback
            # на default, сырой URL из профиля не подставляется.
            custom_unresolved = True
        if override_model:
            model = override_model
    return {
        "base_url": base_url,
        "model": model,
        "provider": provider,
        "connection_id": connection_id,
        "custom_unresolved": custom_unresolved,
        "configured": bool(base_url and model),
        # T-4619 (аддитивно): источник резолва (лестница §35; виден в
        # COVER_STYLE_RESOLVE/Inspector §41).
        "resolve_source": (SLOT_SOURCE_PROFILE_CONNECTION
                           if connection_id != "default"
                           else SLOT_SOURCE_GLOBAL_STYLE),
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


# ── T-4619 (spec §6 F.2; ADR-1028-8 D7.2): лестница наследования ────────────
# Прод-инцидент §35: профиль «Модель обработки: По умолчанию (глобальная
# настройка)» + пустой глобальный слот → configured=False → «Адрес и модель
# не настроены» → style edit NOT EXECUTED → published base cover. Отдельная
# style connection НЕ обязательна: runtime обязан реально разрешить
# global/default image-edit provider + model, если модель поддерживает
# image edit.
#
# Лестница (spec §6 F.2 дословно):
#   1. per-chat override (`prompts.summary_cover_style_id`-слой) — как есть
#      (резолв профиля выше по контуру);
#   2. profile connection override (model_mode=custom, connection_id) —
#      как есть (`resolve_style_slot`);
#   3. global default image-edit slot (этот метод, только при пустом
#      глобальном слоте):
#      3a. Connections layer default-подключение, поддерживающее image_edit;
#      3b. иначе models.image_style_* (existing глобальный слот — уже
#          проверен выше; сюда попадаем при его пустоте);
#      3c. global default image provider+model (`models.image_*` — тот же
#          глобальный image-слот, что сгенерировал base cover; «Base cover:
#          success» доказывает его настроенность в прод-инциденте) —
#          capability image_edit через существующий registry (§36).
#   4. ничего не разрешилось → configured=False → честный reason
#      (`not_configured`), не «успех без стиля».

# Ключи глобального image-слота (models.image_*; image_generation.py:75-78 —
# реиспользование, второй источник не создаётся).
KEY_IMAGE_BASE_URL = "models.image_base_url"
KEY_IMAGE_MODEL = "models.image_model"
KEY_IMAGE_API_KEY = "keys.image_api_key"


async def default_edit_connection(pg) -> dict | None:
    """Connections layer default-подключение (§35 leg 3a; детерминированно).

    `cover_style_connections` не хранит model/флаг default (PG DDL —
    no-op по спеке §0.1): default = единственная не-удалённая запись;
    если несколько — самая ранняя (created_at, connection_id —
    стабильный порядок). Нет записей/PG недоступен → None."""
    try:
        from services import cover_style_registry as registry
        rows = await registry.list_connections(pg)
    except Exception:
        return None
    rows = [r for r in (rows or []) if str(r.get("base_url") or "").strip()]
    if not rows:
        return None
    rows.sort(key=lambda r: (str(r.get("created_at") or ""),
                             str(r.get("connection_id") or "")))
    return rows[0]


def _capability_supports_edit(caps) -> bool:
    """Gate §36/§58: capability image_edit — FALSE блокирует наследование;
    UNKNOWN НЕ блокирует (сохранение профиля разрешено, честная попытка
    edit'а провалится fail-soft — ladder §37 не уничтожает текст)."""
    if caps is None:
        return True              # нет данных capability — не блокируем
    return getattr(caps, "image_edit", cap.UNKNOWN) != cap.FALSE


async def _edit_capabilities_for(slot: dict):
    """Capabilities наследуемого слота через capability registry (§36;
    live-discovery авто + TTL-кеш, fail-open → conservative unknown)."""
    try:
        return await cap.resolve_capabilities_auto(
            slot.get("provider") or "", slot.get("base_url") or "",
            slot.get("model") or "")
    except Exception:
        return cap.conservative_unknown()


async def resolve_style_slot_inherited(*, profile: dict | None = None,
                                       connection: dict | None = None,
                                       pg=None) -> dict:
    """Резолв Style-слота по лестнице наследования §35 (T-4619).

    Обёртка над `resolve_style_slot` (шаги 1–2 — как есть) + шаги 3a/3c
    наследования при пустом глобальном слоте и профиле в режиме «По
    умолчанию (глобальная настройка)» (`model_mode != custom`). Явно
    настроенный слот/подключение ведут себя байт-в-бит (регресс).
    Kill-switch OFF → ровно `resolve_style_slot` (байт-в-бит)."""
    slot = resolve_style_slot(profile=profile, connection=connection)
    if slot.get("configured") or not style_global_default_enabled():
        return slot
    profile = profile or {}
    if profile.get("model_mode") == MODEL_MODE_CUSTOM:
        return slot              # custom-режим: честный custom_unresolved выше
    # ── 3a: Connections layer default-подключение ───────────────────────
    conn = await default_edit_connection(pg)
    if conn is not None:
        model = str(profile.get("model_id") or "").strip() or \
            _resolve_str(KEY_STYLE_MODEL, getattr(settings,
                                                  "IMAGE_STYLE_MODEL", ""))
        candidate = {
            "base_url": str(conn.get("base_url") or "").strip(),
            "model": model,
            "provider": _provider_of(str(conn.get("base_url") or "")),
            "connection_id": str(conn.get("connection_id") or "") or "default",
            "custom_unresolved": False,
        }
        candidate["configured"] = bool(candidate["base_url"] and model)
        if candidate["configured"]:
            caps = await _edit_capabilities_for(candidate)
            if _capability_supports_edit(caps):
                candidate["resolve_source"] = SLOT_SOURCE_CONNECTIONS_DEFAULT
                candidate["_connection"] = conn      # internal carry (не событие)
                return candidate
    # ── 3c: global default image provider+model (models.image_*) ────────
    image_base = _resolve_str(KEY_IMAGE_BASE_URL,
                              getattr(settings, "IMAGE_BASE_URL", ""))
    image_model = _resolve_str(KEY_IMAGE_MODEL,
                               getattr(settings, "IMAGE_MODEL", ""))
    if image_base and image_model:
        candidate = {
            "base_url": image_base,
            "model": image_model,
            "provider": _provider_of(image_base),
            "connection_id": "default",
            "custom_unresolved": False,
            "configured": True,
        }
        caps = await _edit_capabilities_for(candidate)
        if _capability_supports_edit(caps):
            candidate["resolve_source"] = SLOT_SOURCE_GLOBAL_IMAGE
            candidate["_connection"] = None
            return candidate
    # ── 4: честный not_configured (базовый слот как был) ────────────────
    return slot


def slot_capabilities(*, profile: dict | None = None,
                      discovery: dict | None = None,
                      endpoints: dict | None = None,
                      refresh: bool = False,
                      connection: dict | None = None) -> cap.ImageModelCapabilities:
    """Capabilities выбранного Style-слота (resolver, §3.7/§71)."""
    slot = resolve_style_slot(profile=profile, connection=connection)
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
                      connection: dict | None = None,
                      ) -> dict:
    """Статус подключения Style-слота для UI (§73): без реальной генерации.

    Возвращает `{configured, connected, api_key_set, edit_supported, message,
    connection_id, custom_unresolved}`. API key проверяется по наличию
    (пер-подключение или `keys.image_style_api_key`), НЕ логируется и НЕ
    возвращается (R17).
    """
    slot = resolve_style_slot(profile=profile, connection=connection)
    if connection is not None:
        key_set = bool(str(connection.get("api_key") or "").strip())
    else:
        key_set = bool(_resolve_str(
            KEY_STYLE_API_KEY, getattr(settings, "IMAGE_STYLE_API_KEY", "")))
    caps = capabilities or (
        slot_capabilities(profile=profile, connection=connection)
        if slot["configured"] else None)
    edit_supported = None
    if caps is not None:
        edit_supported = caps.edit_supported
    if not slot["configured"]:
        msg = "Адрес и модель не настроены"
    elif slot.get("custom_unresolved"):
        msg = "Подключение модели не найдено — используется подключение по умолчанию"
    elif not key_set:
        msg = "API ключ не настроен"
    else:
        msg = "Подключено"
    return {
        "configured": slot["configured"],
        "connected": bool(slot["configured"] and key_set),
        "api_key_set": key_set,
        "edit_supported": edit_supported,
        "connection_id": slot["connection_id"],
        "custom_unresolved": bool(slot.get("custom_unresolved")),
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


