"""Epic 85 (84.5 + дельты 84.13/84.14, T-617/T-638) — REST-эндпоинты /api/*.

Все маршруты (кроме /api/health) — за TMA-initData (get_tma_user); права —
requires_permission по 84.14.2. Коды ошибок по 84.5: 400/401/403/404/409/
422/500. Маскировка секретов (84.12.4): значение ключа категории keys без
права на КОНКРЕТНЫЙ ключ → {«configured», «last4»} — никогда в открытую.
"""
import datetime
import asyncio
import json
import logging
import time
from typing import Any, Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from aiogram.utils.web_app import WebAppUser

from config.settings import settings
from services import access as access_srv
from services import bot_persona, chat_keys, chat_params, chat_usage, param_catalog
from services import hot_config as hot
from services import roles as roles_srv
from services.config_cache import (
    ConfigCache,
    ConfigCacheUnavailableError,
    _INFO_KEY,
)
# L3-фикс: приватный реэкспорт `_GUIDE_KEY` больше не тянется через
# config_cache — импорт напрямую из модуля-владельца.
from services.info_service import GUIDE_KEY as _GUIDE_KEY
from services.debug_config import (
    build_dump,
    is_pg_only,
    resolve_param_key,
)
from services.param_catalog import (
    CATEGORIES,
    CATEGORY_CONTENT,
    CATEGORY_KEYS,
    CATEGORY_PROMPTS,
    GROUPS,
    get_by_pg_key,
    group_order,
    known_param_keys,
    known_secret_keys,
    known_sections,
    resolve_progressive_level,
)
from services.permissions import (
    ACTION_IDS,
    ACTIONS_TREE,
    Permissions,
    RoleGuardError,
    guard_last_wildcard,
    requires_permission as match_permission,
    validate_permissions,
)
from web.api.avatars import chat_display_info
from web.api.deps import (
    can_edit_param,
    can_view_key_value,
    get_cache,
    get_tma_user,
    requires_global_admin,
    requires_permission,
)

logger = logging.getLogger(__name__)

api_router = APIRouter()


def _invalidate_provider_health(keys) -> None:
    """R10.9-4 (F5 round1014): после записи конфигурации провайдеров сбросить
    кэш health (status_service._health_cache) — иначе ``/api/status`` до 60с
    отдаёт ``ok`` на старые base_url/model/key. ``keys`` — сохранённые
    pg-ключи; сброс затрагивает только ``models.*``/``keys.*``. Ошибка
    инвалидации не должна ронять успешный save (best-effort)."""
    try:
        from services.status_service import status as _status
        _status.invalidate_health_cache(keys)
    except Exception:
        logger.warning("[api] health cache invalidation failed", exc_info=True)

_RICH_TEXT_LIMIT = 32768   # лимит rich-HTML (53.3, T-447; 84.13.4)
_GUIDE_LIMIT = 65536       # F6 (10.14): лимит Markdown-гайда (spec §2.3)

_ACCESS_SECTION_TITLE = "Управление доступом"


# ── Pydantic-модели ─────────────────────────────────────────────────────────

class ConfigItemUpdate(BaseModel):
    key: str
    value: Any
    # F0.1 (ADR-1025-2 D-409-3): per-key optimistic-токен для глобального
    # пути (аддитивно; клиент может не присылать). Несовпадение при
    # совпадающем значении → revalidated; при отличающемся → 409 conflicting.
    updated_at: str | None = None


class ConfigUpdateRequest(BaseModel):
    items: list[ConfigItemUpdate]
    # Раунд 10 (F-7 §6): optimistic-метка чата при X-Chat-Id (409-протокол).
    updated_at: str | None = None


class AdminUpsert(BaseModel):
    telegram_id: int
    role_name: str


class AdminRemove(BaseModel):
    telegram_id: int


class RoleUpsert(BaseModel):
    role_name: str = Field(min_length=1, max_length=64)
    permissions: dict[str, Any] = Field(default_factory=dict)
    is_custom: bool | None = None


class RoleRename(BaseModel):
    """OD15/T-1141: переименование пользовательской роли."""
    new_name: str = Field(min_length=1, max_length=64)


class InfoUpdate(BaseModel):
    html: str


class GuideUpdate(BaseModel):
    """F6 (10.14, spec §2.3): Markdown-гайд по возможностям бота."""
    markdown: str


class ConfigChatDelete(BaseModel):
    key: str


class ChatKeyBody(BaseModel):
    key_name: str
    value: str = ""
    # F11 (10.24, ADR-1024-12 D1): опциональный scope. "auto" — без X-Chat-Id
    # и для глобального allowlist → global, иначе chat; "global" — только
    # global admin + is_global_secret; "chat" — прежний per-chat BYOK.
    scope: str = "auto"


class ChatKeyDelete(BaseModel):
    key_name: str


class ChatKeysStatus(BaseModel):
    pass


class LlmTestRequest(BaseModel):
    """Раунд 10.6 (T-1210/A4): per-block test провайдера (можно до сохранения)."""
    block: str
    base_url: str = ""
    model: str = ""
    api_key: str = ""


class ImageTestRequest(BaseModel):
    """Раунд 10.24 (F12, ADR-1024-4 D3): тест подключения image-провайдера.

    ``prompt`` пуст → нейтральный тестовый промпт на бэкенде (R17)."""
    prompt: str = ""


class RandomTestRequest(BaseModel):
    """Раунд 10.37 (MCA-10a, ADR-1028-14 D8/T-4977): проверка подключения ANU.

    ``key`` — черновой ключ из поля формы (только POST-body, не URL; пусто →
    проверяется сохранённый). Ключ не эхо-ится и не логируется (R17)."""
    key: str = Field(default="", max_length=512)


class VisionTestRequest(BaseModel):
    """MCA-19 (round 10.43, ADR-1028-19 D4/T-5103): проверка подключения
    модели распознавания изображений. ``prompt`` игнорируется (проба —
    нейтральное 1×1 PNG на бэкенде, не текст пользователя; R17)."""
    prompt: str = ""


class PersonaUpdate(BaseModel):
    """Раунд 10.14 (F2 persona-storage-core, spec §5): partial-правка персоны.

    `reset=true` → удаление per-chat override (наследование global);
    `updated_at` — optimistic-токен (409 при несовпадении)."""
    name: str | None = None
    biography: str | None = None
    system_prompt_overrides: str | None = None
    is_aware_ai: bool | None = None
    reset: bool = False
    updated_at: str | None = None


# ── helpers ─────────────────────────────────────────────────────────────────

def _coerce_value(spec, raw) -> Any:
    """Конвертация значения к типу каталога; неудача → ValueError (422)."""
    if raw is None:
        raise ValueError("value не может быть null")
    if spec.type == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in ("true", "false"):
            return raw.strip().lower() == "true"
        if isinstance(raw, int) and raw in (0, 1):
            return bool(raw)
        raise ValueError(f"ожидается bool, получено {type(raw).__name__}")
    if spec.type == "int":
        if isinstance(raw, bool):
            raise ValueError("ожидается int, получено bool")
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
            return int(raw)
        raise ValueError(f"ожидается int, получено {type(raw).__name__}")
    if spec.type == "float":
        if isinstance(raw, bool):
            raise ValueError("ожидается float, получено bool")
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return float(raw.strip())
            except ValueError:
                pass
        raise ValueError(f"ожидается float, получено {type(raw).__name__}")
    if spec.type == "json":
        if isinstance(raw, (dict, list, tuple)):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                return raw
        return raw
    if isinstance(raw, str):
        return raw
    return str(raw)


def _ensure_keyvalue_object(value, *, pg_key: str = "") -> dict:
    """F2 round1022: вход KV-редактора (`widget='keyvalue'`) — ВСЕГДА объект.

    Defense-in-depth от двойного кодирования jsonb: строка JSON распаковывается
    (до 2 уровней); если объект так и не получен — пустой объект + WARNING
    (R17: логируем только ключ/форму, без значений). Остальные `json`-виджеты
    (textarea) не затронуты — helper вызывается точечно."""
    current = value
    for _ in range(2):
        if not isinstance(current, str):
            break
        try:
            current = json.loads(current)
        except (TypeError, ValueError):
            break
    if isinstance(current, dict):
        return current
    if current not in (None, ""):
        logger.warning("[api] keyvalue-значение не объект — отдаю пустой | "
                       "key=%s | shape=%s", pg_key, type(current).__name__)
    return {}


def _chat_id_or_none(x_chat_id: str | None) -> int | None:
    """X-Chat-Id: прозрачный заголовок; мусор → 422; отсутствует → None
    (ровно старое поведение — глобальный конфиг, F-7 §6)."""
    if x_chat_id is None:
        return None
    try:
        return int(x_chat_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="X-Chat-Id — целое число")


def _mask_secret(value, telegram_id: int, pg_key: str, cache: ConfigCache) -> dict:
    """84.12.4 + ФИКС 2026-09-03: ЕДИНЫЙ контракт — секреты ВСЕГДА отдаются
    как {"configured": bool, "last4": str|None}; полное значение (даже для
    admin/wildcard) в фронт НЕ отдаём — замена только через POST /api/config."""
    if not value:
        return {"configured": False, "last4": None}
    if isinstance(value, dict) and set(value) <= {"configured", "last4"}:
        return {"configured": bool(value.get("configured")),
                "last4": value.get("last4")}
    return {"configured": True, "last4": str(value)[-4:]}


# F11 (10.24, ADR-1024-12 D1): допустимые scope безопасного эндпоинта.
_KEY_SCOPES = ("auto", "global", "chat")


def _resolve_key_scope(scope: str, chat_id: int | None, key_name: str) -> str:
    """Effective scope для `/api/config/keys/own`.

    `auto` без X-Chat-Id → global ТОЛЬКО для allowlist глобальных секретов
    (иначе chat → 422 «нужен X-Chat-Id», как раньше). Явный `chat` требует
    X-Chat-Id. Явный `global` — без X-Chat-Id (права/allowlist проверяет
    вызывающая ветка)."""
    if scope not in _KEY_SCOPES:
        raise HTTPException(status_code=422,
                            detail=f"неизвестный scope: {scope}")
    if scope == "global":
        return "global"
    if scope == "chat":
        if chat_id is None:
            raise HTTPException(status_code=422,
                                detail="scope=chat требует X-Chat-Id")
        return "chat"
    if chat_id is None and chat_keys.is_global_secret(key_name):
        return "global"
    return "chat"


async def _ctx_global_admin(cache: ConfigCache, user: WebAppUser):
    """AccessCtx для глобального пути без X-Chat-Id (F11: RBAC global-ветки)."""
    return await roles_srv.access_for(user.id, cache=cache)


# ── Health / me ─────────────────────────────────────────────────────────────

@api_router.get("/health")
async def health():
    """84.5: без auth (ngrok/мониторинг)."""
    return {"status": "ok"}


@api_router.get("/me")
async def me(request: Request, user: Annotated[WebAppUser, Depends(get_tma_user)]):
    """84.5: {telegram_id, username, first_name, last_name, photo_url,
    role_name, permissions, is_custom} (UI-полировка: + last_name/photo_url).
    Раунд 10.24 (F3, ADR-1024-13): аддитивно + `ui_flags` — доставка env-only
    kill-switch'ей во фронт без inline-скриптов (CSP). Наружу только булевы."""
    cache: ConfigCache = get_cache(request)
    role_name = cache.get_role(user.id)
    if role_name is None:
        role_name = "user"
    role = cache.roles().get(role_name)
    permissions = (role or {}).get("permissions", {})
    is_custom = bool((role or {}).get("is_custom", False))
    # F11 (10.24, ADR-1024-12; review iter2 M1): эффективный глобальный админ
    # по единому источнику `services/roles.access_for` (role_type ==
    # global_admin ИЛИ wildcard) — паритет UI с RBAC safe-эндпоинта.
    # R16: поле аддитивно, наружу только bool.
    ctx_me = await roles_srv.access_for(user.id, cache=cache)
    return {
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        # UI-полировка TMA: last_name/photo_url (WebAppUser-поля initData;
        # photo_url может быть None — фронт тогда берёт /api/avatar/user/*)
        "last_name": user.last_name,
        "photo_url": user.photo_url,
        "role_name": role_name,
        "permissions": permissions,
        "is_custom": is_custom,
        "is_global_admin": bool(ctx_me.is_global_admin),
        # ADR-1024-13: UI-флаги (R16-аддитивно, R17-безопасно — только bool).
        "ui_flags": {
            "TOKEN_FLOW_NODEFLOW_ENABLED":
                bool(settings.TOKEN_FLOW_NODEFLOW_ENABLED),
            # F5 (10.24, ADR-1024-9 D6): гейт карточки/вкладки «Генерация
            # изображений» в «Модулях» (default ON). OFF → карточка скрыта,
            # диплинк `#/mod_images` → `#/modules`; главный тумблер в UI
            # недостижим (возврат — env-флаг ON / git revert).
            "IMAGE_MODULE_CARD_ENABLED":
                bool(settings.IMAGE_MODULE_CARD_ENABLED),
            # F6 (10.24, ADR-1024-10 D5): гейт новой раскладки вкладки
            # «Промпты» (плоский grid без аккордеонов, табы режимов в
            # карточках, fallback-дропдаун один раз). default ON.
            "PROMPTS_UI_V2_ENABLED":
                bool(settings.PROMPTS_UI_V2_ENABLED),
            # F11 (10.24, ADR-1024-12 D6): гейт безопасного пути глобального
            # image-ключа. default ON; OFF → прежняя (сбойная) маршрутизация.
            "BYOK_IMAGE_KEY_ENABLED": bool(settings.BYOK_IMAGE_KEY_ENABLED),
            # F4 (10.24, ADR-1024-8 D5): гейт вертикальной кликабельной
            # «Живой ленты досье». default ON; OFF → горизонталь 42s,
            # строки некликабельны (10.20/ADR-1022-8 байт-в-байт).
            "DOSSIER_LIVE_FEED_ENABLED":
                bool(settings.DOSSIER_LIVE_FEED_ENABLED),
            # F10 (10.24, ADR-1024-11 D5): гейт реального data-binding
            # KV-редактора алиасов (deep-watch item + :key). default ON;
            # OFF → прежний (сломанный) watcher 'item.value'.
            "ALIASES_KEYSVALUE_RENDER_ENABLED":
                bool(settings.ALIASES_KEYSVALUE_RENDER_ENABLED),
            # F1 (10.25, ADR-1025-1 D5): гейт новой IA/app-shell. default ON;
            # OFF → прежний navbar (6 пунктов) байт-в-байт, без sidebar/
            # bottom-nav (возврат — env-флаг ON / git revert). ВРЕМЕННЫЙ
            # механизм отката (UPD §9.5), удаляется post-Epic-1.
            "IA_V2_ENABLED": bool(settings.IA_V2_ENABLED),
            # Хотфикс-6 (10.25, ADR-1025-12 D6): env-only флаги областей
            # A/B/C/D. R16-аддитивно, R17-безопасно (строки/числа/bool, без
            # секретов). Не UI-тумблеры каталога — Δ каталога = 0.
            "UI_GLASS_TIER_OVERRIDE":
                str(settings.UI_GLASS_TIER_OVERRIDE or "auto"),
            "UI_HEARTBEAT_CANVAS_ENABLED":
                bool(settings.UI_HEARTBEAT_CANVAS_ENABLED),
            "UI_HEADER_COMPACT_V2": bool(settings.UI_HEADER_COMPACT_V2),
            "UI_LENS_MAX_NODES": int(settings.UI_LENS_MAX_NODES),
            # Хотфикс-7 (10.25, ADR-1025-13 D5.3): три независимых env-only
            # отката областей layout/glass-shell/premium-heartbeat.
            # R16-аддитивно, R17-безопасно (только bool), Δ каталога = 0.
            "UI_SHELL_GLASS_V2": bool(settings.UI_SHELL_GLASS_V2),
            "UI_HEARTBEAT_PREMIUM": bool(settings.UI_HEARTBEAT_PREMIUM),
            "UI_SHELL_LAYOUT_V2": bool(settings.UI_SHELL_LAYOUT_V2),
            # Хотфикс-8 (10.25, ADR-1025-16 D5): shell v3 (§4, графитовый glass)
            # и aurora/mesh фон. R16-аддитивно, R17-safe (bool), Δ каталога = 0.
            "UI_SHELL_V3": bool(settings.UI_SHELL_V3),
            "UI_AURORA_BG_ENABLED": bool(settings.UI_AURORA_BG_ENABLED),
            # Хотфикс-9 (10.25, ADR-1025-17 D1/D4/D5/D6): flex-геометрия,
            # графитовый shell, Liquid Glass (vendored), Dark Aurora Flow.
            # R16-аддитивно, R17-safe (bool), Δ каталога = 0.
            "UI_SHELL_FLEX_V3": bool(settings.UI_SHELL_FLEX_V3),
            "UI_SHELL_GRAPHITE_V3": bool(settings.UI_SHELL_GRAPHITE_V3),
            "UI_LIQUID_GLASS_LIB": bool(settings.UI_LIQUID_GLASS_LIB),
            "UI_AURORA_FLOW_V2": bool(settings.UI_AURORA_FLOW_V2),
            # round 10.26 (ADR-1026-3 D2/T-3166): env-only kill-switch
            # полигонального фона (Canvas 2D + Delaunator 5.0.0). Default ON;
            # OFF → мягкий откат к Dark Aurora Flow. R16-аддитивно, R17-safe
            # (bool), Δ каталога = 0.
            "UI_POLYGON_BG_ENABLED": bool(settings.UI_POLYGON_BG_ENABLED),
            # F7 (10.25, ADR-1025-20 D7): env-only kill-switch per-chat
            # блок-гейтов «Общие реакции»/«Расписания» (default ON; OFF →
            # baseline + новые блок-тумблеры честно read-only).
            # R16-аддитивно, R17-safe (bool), Δ каталога = 0.
            "PERMSOC_BLOCK_GATES_ENABLED":
                bool(settings.PERMSOC_BLOCK_GATES_ENABLED),
            # F11 (10.25, ADR-1025-23 D6): env-only kill-switch композиции
            # витрины «Статус» (§12-сетка, Hero/метрики, сон, факты, счётчики).
            # Default ON; OFF → одноколоночный безопасный режим (не byte-identical
            # legacy-DOM; M-F11S-1) без редеплоя. R16-аддитивно, R17-safe (bool),
            # Δ каталога = 0.
            "UI_STATUS_GRID_V2": bool(settings.UI_STATUS_GRID_V2),
            # ASAP-3.1 (round 1028, ADR-1028-3): env-only kill-switch'и
            # разводки бюджетов и блока «Автобюджеты» (default ON; OFF →
            # прежняя структура байт-в-байт / блок не рендерится). R16-
            # аддитивно, R17-safe (bool), Δ каталога = 0.
            "UI_BUDGETS_SPLIT_ENABLED":
                bool(settings.UI_BUDGETS_SPLIT_ENABLED),
            "ANALYTICS_CONTEXT_BUDGETS_ENABLED":
                bool(settings.ANALYTICS_CONTEXT_BUDGETS_ENABLED),
        },
    }


# ── Config ──────────────────────────────────────────────────────────────────

@api_router.get("/config")
async def get_config(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """84.5: любая роль; секреты маскируются (84.12.4 + 2026-09-03: всегда
    {configured,last4}). Плюс title/type из param_catalog — фронту для
    рендера форм (84.7). 84.24 (02.09.2026): groups[] + group/description
    в items; сортировка (category, group.order, title_ru).
    Раунд 10 (F-7 §6): X-Chat-Id → слой чата: per-param фильтры
    (can_view_param: hidden_from_local/min-роль view; keys-секция для
    локального админа — полностью исключается), значения = chat_params
    (overrides) → глобал → дефолт; 403 «нет доступа к чату»."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    ctx = None
    chat_root: dict = {}
    db_overrides: dict = {}
    try:
        db_overrides = await access_srv.db_override_map(cache.pg)
    except Exception:
        db_overrides = {}
    if chat_id is not None:
        ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
        if not access_srv.can_access_chat(ctx, chat_id):
            raise HTTPException(status_code=403, detail="нет доступа к чату")
        chat_root = await chat_params.get_all_chat_params(chat_id)
    else:
        # F-7 §1.2-2: глобальный путь тоже требует роль-контекст — иначе
        # секрет-ключи (в т.ч. {configured,last4} global key) были видны
        # любой TMA-роли (фикс S1).
        ctx = await roles_srv.access_for(user.id, cache=cache)
    items = []
    for key, value in sorted(cache.get_all().items()):
        spec = get_by_pg_key(key)
        # F2 (10.23, ADR-1023-2): внутренние ключи (hidden) — вне UI-каталога
        # (остаются в реестре/правах; значения/миграции не затрагиваются).
        if spec is not None and spec.hidden:
            continue
        category = spec.category if spec else key.split(".")[0]
        secret = bool(spec.secret) if spec else category == CATEGORY_KEYS
        if chat_id is not None and ctx is not None:
            # F-7 §6: фильтр видимости per-chat (hidden/min-роль view);
            # keys-секция: локальному админу — полностью исключается
            if secret and not ctx.is_global_admin:
                continue
            matrix = access_srv.effective_matrix(
                key, db_overrides.get(key),
                (chat_root.get("perm_overrides") or {}).get(key))
            if not access_srv.can_view_param(ctx, matrix):
                continue
        elif ctx is not None:
            # ФИКС S1 (F-7 §1.2-2/§3.1): на ГЛОБАЛЬНОМ пути ключи-секреты
            # отдаются только глобальному админу; local/moderator/user не
            # видят глобальный ключ НИ в каком виде (в т.ч. без last4).
            if secret and not ctx.is_global_admin:
                continue
        chat_source = ""
        # F3/D-3 (ревью Батча C): значение ГЛОБАЛЬНОГО слоя до наложения
        # per-chat override — нужно тумблеру «Безлимит» для OFF-ветки
        # (пишем явные дефолты вместо DELETE, сохраняя meta; не секрет).
        global_value = None
        matrix = access_srv.effective_matrix(
            key, db_overrides.get(key),
            (chat_root.get("perm_overrides") or {}).get(key)
            if chat_id is not None else None)
        if secret:
            value = _mask_secret(value, user.id, key, cache)
        elif chat_id is not None:
            global_value = value
            overrides = chat_root.get("overrides") or {}
            if key in overrides:
                is_per_chat = bool(spec.per_chat) if spec else False
                if is_per_chat:
                    value = overrides[key]
                    chat_source = "chat"
        # F2 round1022: KV-редактор получает ВСЕГДА объект (в т.ч. при
        # двойном кодировании jsonb). Другие json-виджеты не затронуты.
        if spec is not None and spec.widget == "keyvalue" and not secret:
            value = _ensure_keyvalue_object(value, pg_key=key)
            if chat_id is not None and global_value is not None:
                global_value = _ensure_keyvalue_object(global_value, pg_key=key)
        items.append({"key": key, "value": value, "category": category,
                      "secret": secret,
                      "chat_source": chat_source,
                      "global_value": global_value,
                      "title": spec.title_ru if spec else key,
                      "type": spec.type if spec else "str",
                      # F7: updated_at из PG; in-memory/деградация — null
                      "updated_at": cache.get_updated_at(key),
                      # 84.24: группа и простое описание (для ключей без
                      # spec — пустые; фронт складывает в «Прочее»)
                      "group": spec.group if spec else "",
                      "description": spec.description if spec else "",
                      # Эпик 04.09.2026 (3.1/FR-28): виджет рендера (""
                      # дефолт | "keyvalue" — KV-редактор пар)
                      "widget": spec.widget if spec else "",
                      # Раунд 10.4 (B-7/8): опции/подписи select-виджета
                      # (None для не-select — фронт рендерит пустой список
                      # только при widget=="select")
                      "select_options": list(spec.select_options)
                      if (spec and spec.widget == "select") else None,
                      "select_labels": list(spec.select_labels)
                      if (spec and spec.widget == "select") else None,
                      # Раунд 10 (F-7 §4.4/F-11 §4.1): per-chat-граница и
                      # уровень прогрессивного раскрытия (без значений)
                      "per_chat": bool(spec.per_chat) if spec else False,
                      "progressive_level":
                          resolve_progressive_level(spec) if spec else "basic",
                      # F8 (10.23, ADR-1023-8 D3): стадия System 2
                      # (synthesizer/verbalizer/mode/None) — UI-секции карточек
                      # «Промпты»; None у прочих ключей.
                      "stage": spec.stage if spec else None,
                      # Ре-дизайн 10.2, BUG-6 (spec §3.2): флаги-роли —
                      # новая форма (view_roles/edit_roles) для роль-пикера TMA
                      "view_roles": list(matrix.get("view_roles") or []),
                      "edit_roles": list(matrix.get("edit_roles") or []),
                      "chat_updated_at": chat_root.get("meta", {}).get(
                          "updated_at") if chat_id is not None else None})
    # 84.24.3: сортировка (category, group.order, title_ru)
    items.sort(key=lambda it: (it["category"], group_order(it["group"]),
                               it["title"]))
    # 84.24.3: метаданные групп для категорий, присутствующих в items
    present = {it["category"] for it in items}
    groups = [
        {"id": g.id, "category": g.category, "title": g.title_ru,
         "description": g.description, "order": g.order}
        for g in GROUPS if g.category in present
    ]
    groups.sort(key=lambda g: g["order"])
    out = {"items": items, "groups": groups}
    # ASAP 7 (F3, §3.1): аддитивный ключ реестра модулей (ModuleSpec →
    # services/module_registry.py). Frontend обогащает/дополняет MODULES
    # при наличии записи; fallback — текущий hardcoded список (Δ риска = 0).
    try:
        from services.module_registry import registry_for_frontend
        out["modules"] = registry_for_frontend()
    except Exception:          # pragma: no cover — fail-open (fallback JS)
        out["modules"] = []
    if chat_id is not None:
        out["chat_id"] = chat_id
        out["updated_at"] = await chat_params.get_chat_updated_at(chat_id)
        out["ctx"] = {
            "role_chat": ctx.role_chat if ctx else None,
            "is_local_admin": bool(ctx and ctx.is_local_admin),
            "is_global_admin": bool(ctx and ctx.is_global_admin),
            # F-14 (§3.2): DM-скоуп (свой ЛС) — фронт включает isDmCtx
            "is_dm": bool(ctx and ctx.is_dm_owner),
        }
    return out


async def _write_chat_overrides_with_retry(
    chat_id: int,
    new_overrides: dict,
    meta: dict,
    cache: ConfigCache,
    *,
    expected_updated_at: str | None,
) -> dict:
    """P0 admin-toggle-save (28.10.2026): запись per-chat overrides с ОДНИМ
    ограниченным ретраем на ``ChatParamsConflict``.

    Root cause бага «Сохранено 0 из 1; не сохранено: тумблер конфига»
    (прод 2.58.139; исторический пример — снятая вкладка «Умный кэш»):
    optimistic-токен UI
    (``configChatUpdatedAt``) систематически устаревает — chat_params пишут
    и другие потоки (гейты модулей, speech/persona правки, вторая вкладка
    TMA на другом устройстве), а ``set_gates_opt_in`` сдвигает
    ``chat_profiles.updated_at`` вообще без NOTIFY (исправлено там же).
    Strict-409 превращал ЛЮБУЮ конкурентную мета-запись в полный провал
    сохранения тумблера; recovery в UI сравнивал значения и оставлял
    черновик dirty → повторное «Сохранить изменения» ловило 409 снова
    (токен мог быть отдан снова устаревшим из ``ChatParamsCache`` TTL 120 с).

    Семантика ретрая: перечитываем СВЕЖИЙ root (напрямую PG, мимо кэша) и
    мержим патч ПОВЕРХ него — чужие ключи не теряются (база merge свежая);
    last-writer-wins только на пересекающихся ключах (приемлемо для
    админ-UI владельца в 1-2 чатах). Первая попытка сохраняет честный
    optimistic-протокол (включая идемпотентный short-circuit D-409-1).
    Права/типизация проверены до записи и не зависят от value_overrides
    (матрица прав — perm_overrides), пере-проверка не нужна.
    Профиль чата отсутствует (current_updated_at=None; join-событие
    потеряно) → ensure дефолтного профиля, как DM-ветка F-14 выше."""
    try:
        return await chat_params.set_chat_params(
            chat_id, {"overrides": new_overrides, "meta": meta},
            changed_by=meta.get("updated_by"), pg=cache.pg,
            expected_updated_at=expected_updated_at)
    except chat_params.ChatParamsConflict as exc:
        if getattr(exc, "current_updated_at", None) is None:
            await chat_params.ensure_scope_profile(chat_id, dm=False,
                                                   pg=cache.pg)
            return await chat_params.set_chat_params(
                chat_id, {"overrides": new_overrides, "meta": meta},
                changed_by=meta.get("updated_by"), pg=cache.pg,
                expected_updated_at=None)
        fresh_root = await chat_params.get_all_chat_params(chat_id,
                                                           pg=cache.pg)
        fresh_overrides = dict(fresh_root.get("overrides") or {})
        fresh_overrides.update(new_overrides)
        fresh_meta = dict(fresh_root.get("meta") or {})
        fresh_meta["updated_by"] = meta.get("updated_by")
        return await chat_params.set_chat_params(
            chat_id, {"overrides": fresh_overrides, "meta": fresh_meta},
            changed_by=meta.get("updated_by"), pg=cache.pg,
            expected_updated_at=None)


@api_router.post("/config")
async def post_config(
    request: Request,
    payload: ConfigUpdateRequest,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """84.5: право — на КАЖДЫЙ ключ (param./key.<категория>.<ключ> покрывается
    секцией категории / конкретным правом; пустая роль → 403 на каждый ключ).

    Раунд 10 (F-7 §6): X-Chat-Id → запись в chat_params (атомарная, в ОДНУ
    операцию set_chat_params с полной валидацией ДО записи): keys.* → 422
    (это путь chat_keys, не сюда); per_chat=False → 422 «ключ нельзя
    переносить на уровень чата»; per-param min-роли (can_edit_param по
    матрице чата: local admin/moderator — per-параметры, global admin —
    всё); optimistic 409; hidden_from_local запись локальным → 403."""
    cache: ConfigCache = get_cache(request)
    if not payload.items:
        raise HTTPException(status_code=422, detail="items пуст")
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return await _post_config_global(request, payload, user)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not access_srv.can_access_chat(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    # F-14 (§3.1): первый write в DM-скоупе — ленивое создание профиля
    # (иначе set_chat_params даст мусорный 409 «профиля нет»).
    if ctx.is_dm_owner:
        await chat_params.ensure_scope_profile(chat_id, dm=True, pg=cache.pg)
    try:
        db_overrides = await access_srv.db_override_map(cache.pg)
    except Exception:
        db_overrides = {}
    root = await chat_params.get_all_chat_params(chat_id)
    # F20 (раунд 10.24, ADR-1024-21 D1/D2): два НЕЗАВИСИМЫХ namespace.
    #   perm_overrides  — матрица прав (chat-скоуп view/edit ролей ключа);
    #                     в POST используется ТОЛЬКО для effective_matrix ниже.
    #   value_overrides — ЗНАЧЕНИЯ per-chat (root["overrides"]) — база merge.
    # Смешение этих пространств и было багом: одиночный save затирал значения.
    perm_overrides = dict(root.get("perm_overrides") or {})
    value_overrides = dict(root.get("overrides") or {})
    patch_overrides = {}
    for item in payload.items:
        spec = get_by_pg_key(item.key)
        if spec is not None and spec.hidden:
            # ASAP-3.2 (§102/§124): скрытые ключи (например
            # `prompts.summary_cover_style_id` — выбор стиля) не вводятся
            # руками; один user-facing источник правды — соответствующий
            # модуль (Summary → Стили обложки / POST /api/cover/select).
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: значение задаётся в соответствующем "
                       "разделе Mini App, а не вручную")
        if spec is None or spec.category is None:
            raise HTTPException(status_code=422,
                                detail=f"неизвестный ключ: {item.key}")
        if spec.category == CATEGORY_KEYS:
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: ключ-секрет задаётся через "
                       "/api/config/keys/own (BYOK-путь)")
        if not spec.per_chat:
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: ключ нельзя переносить на уровень чата")
        matrix = access_srv.effective_matrix(
            item.key, db_overrides.get(item.key),
            perm_overrides.get(item.key))
        if not access_srv.can_edit_param(ctx, matrix):
            raise HTTPException(status_code=403,
                                detail=f"нет права на {item.key}")
        try:
            value = _coerce_value(spec, item.value)
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail=f"{item.key}: {exc}")
        # Раунд 10.4 (B-9): select-виджет — значение из набора опций
        if spec.widget == "select" and spec.select_options                 and value not in spec.select_options:
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: недопустимая опция: {value!r}")
        if spec.type == "str" and spec.category in (CATEGORY_PROMPTS,
                                                    CATEGORY_CONTENT):
            if not isinstance(value, str) or not value.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"{item.key}: промпт не может быть пустым")
        patch_overrides[item.key] = value
    if not patch_overrides:
        raise HTTPException(status_code=422, detail="items пуст")
    new_overrides = dict(value_overrides)
    new_overrides.update(patch_overrides)
    meta = dict(root.get("meta") or {})
    meta["updated_by"] = user.id
    try:
        new_root = await _write_chat_overrides_with_retry(
            chat_id, new_overrides, meta, cache,
            expected_updated_at=payload.updated_at)
    except chat_params.ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at,
                    "conflicting": getattr(exc, "conflicting", []) or [],
                    "applied": []})
    logger.info("[api] config chat updated | chat=%s | keys=%d | by=%s | "
                "revalidated=%s",
                chat_id, len(patch_overrides), user.id,
                bool(getattr(new_root, "revalidated", False)))
    snapshots = await _prompt_record_saved_snapshots(
        cache, list(patch_overrides.items()), scope="chat", chat_id=chat_id,
        actor=user.id)
    out_chat = {"updated": sorted(patch_overrides),
                "chat_id": chat_id,
                "revalidated": bool(getattr(new_root, "revalidated", False)),
                "updated_at": (getattr(new_root, "updated_at", None)
                               or await chat_params.get_chat_updated_at(chat_id))}
    if snapshots:
        out_chat["prompt_snapshots"] = snapshots
    return out_chat


@api_router.get("/config/params-meta")
async def get_params_meta(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Раунд 10 (F-7 §4.4): мета-каталог {pg_key: {per_chat,
    progressive_level, group, title, type, secret_mask}} — без значений
    секретов (для TMA-витрины и F-11 прогрессивного раскрытия).
    P0 round1028 (таксономия секретов): secret_mask строго по spec.secret —
    категория keys целиком секрет-категорией не является (keys_random:
    ровно одно секрет-поле, ANU-ключ; остальные параметры — обычные)."""
    items = {}
    for spec_key in sorted(param_catalog.REGISTRY):
        spec = param_catalog.REGISTRY[spec_key]
        if spec.category is None:
            continue
        # F2 (10.23, ADR-1023-2): скрытые (внутренние) ключи не отдаём в UI.
        if spec.hidden:
            continue
        items[spec.pg_key] = {
            "per_chat": bool(spec.per_chat),
            "progressive_level": resolve_progressive_level(spec),
            "group": spec.group,
            "title": spec.title_ru,
            "type": spec.type,
            "secret_mask": bool(spec.secret),
        }
    return {"items": items}


def _alias_diagnostics_payload(report: dict, names: dict) -> dict:
    """R17-safe срез диагностики алиасов (P0 corrective 25.10.2026, F7).

    Только счётчики/слой/факт наличия имени по каждому Telegram ID; САМИ
    значения алиасов не выходят ни в API, ни в логи (R17). Источник слоя —
    единственный владелец карты (`build_alias_resolver` → `scope_report`).
    """
    by_uid = report.get("by_uid") or {}
    return {
        "scope": report.get("scope"),
        "ok": bool(report.get("ok")),
        "global": int(report.get("global") or 0),
        "chat": int(report.get("chat") or 0),
        "inherited": int(report.get("inherited") or 0),
        "merged": int(report.get("merged") or 0),
        "invalid": list(report.get("invalid_json") or []),
        # per_uid: alias_source = слой действующего имени, name_present =
        # имя реально разрешилось (не uid). Ни имён, ни сырых значений.
        "per_uid": [
            {"user_id": int(uid),
             "alias_source": str(source),
             "name_present": bool(str(names.get(str(uid)) or "").strip())}
            for uid, source in sorted(by_uid.items(),
                                      key=lambda item: int(item[0]))
        ],
    }


@api_router.get("/direct/context-diagnostics")
async def direct_context_diagnostics(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: int = Query(...),
):
    """ASAP-3 (round 1028, ADR-1028-2 D17, §34 ТЗ): read-only диагностика
    последнего ON-прогона Direct Context Composer по чату.

    Источник — process-local snapshot (`direct_context_composer.
    get_diagnostics`): только числа/коды (R17: без private raw messages).
    Существующий RBAC-слой (доступ к чату — как GET /config с X-Chat-Id).
    Δ каталога = 0. Fail-open: прогонов не было → ``available: false``."""
    cache: ConfigCache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not access_srv.can_access_chat(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    from services import direct_context_composer as _asap3_composer
    data = _asap3_composer.get_diagnostics(chat_id)
    out: dict = {"chat_id": chat_id, "available": bool(data)}
    if data:
        out.update(data)
    out["metrics"] = _asap3_composer.direct_metrics_snapshot()
    # ASAP 8 v6 (D03/D04, §18C.6/§18C.7): R17-safe оси последнего L1-прогона
    # (configured vs applied temperature, credential source, execution_mode,
    # planner fallback reasons). Аддитивное поле; UI не меняется.
    try:
        from services import direct_l1 as _direct_l1
        out["l1"] = _direct_l1.get_l1_diagnostics(chat_id)
    except Exception:
        pass
    # P0 corrective 25.10.2026 (F7): R17-safe источник действующего имени по
    # каждому uid (слой + наличие имени), без значений алиасов.
    try:
        from services.summary_aliases import build_alias_resolver
        resolver = await build_alias_resolver(chat_id)
        out["aliases"] = _alias_diagnostics_payload(
            resolver.scope_report, resolver.aliases)
    except Exception:
        pass
    return out


@api_router.get("/config/keys/own")
async def config_keys_own(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): маски СОБСТВЕННЫХ ключей чата (R17: никогда raw).
    Права: local admin чата / global admin. F-14 (§3.2): + DM-владелец
    (BYOK своего ЛС).
    F11 (10.24, ADR-1024-12 D1): без X-Chat-Id → маски ГЛОБАЛЬНЫХ секретов
    (только global admin; raw никогда)."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        ctx = await _ctx_global_admin(cache, user)
        if not ctx.is_global_admin:
            raise HTTPException(status_code=403,
                                detail="только для глобального админа")
        masks = [chat_keys.mask_key_info(name, cache.get(name))
                 for name in sorted(chat_keys.global_secret_keys())]
        return {"keys": masks}
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    # F-14 (§3.2/§3.3): в DM-скоупе доступ ТОЛЬКО владельцу (глобальный
    # админ в ЧУЖОМ ЛС → 403); в группах — global/local admin как раньше.
    if chat_params.is_dm_scope(chat_id):
        dm_allowed = bool(ctx.is_dm_owner)
    else:
        dm_allowed = bool(ctx.is_global_admin or ctx.is_local_admin)
    if not dm_allowed:
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    return {"keys": await chat_keys.list_own_keys(cache.pg, chat_id)}


@api_router.put("/config/keys/own")
async def config_keys_own_put(
    request: Request,
    payload: ChatKeyBody,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): запись BYOK-ключа чата (insert-or-replace).
    422 key_name вне whitelist; 403 чужие права; маска в ответе (R17).
    F-14 (§3.1): DM-владелец своего ЛС + ensure_scope_profile.
    F11 (10.24, ADR-1024-12 D1/D2): `scope="global"` (или auto без X-Chat-Id
    для allowlist) → запись ГЛОБАЛЬНОГО секрета в глобальный слой, ответ —
    маска; строка в chat_keys не создаётся."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    scope = _resolve_key_scope(payload.scope, chat_id, payload.key_name)
    if scope == "global":
        ctx = await _ctx_global_admin(cache, user)
        if not ctx.is_global_admin:
            raise HTTPException(status_code=403,
                                detail="только для глобального админа")
        if not chat_keys.is_global_secret(payload.key_name):
            raise HTTPException(
                status_code=422,
                detail=f"{payload.key_name}: не глобальный секрет")
        if not cache.pg_available:
            raise HTTPException(status_code=503,
                                detail="PostgreSQL недоступен (R6)")
        old_value = cache.get(payload.key_name)
        await cache.set(payload.key_name, payload.value, CATEGORY_KEYS)
        await chat_keys.record_global_secret_audit(
            cache.pg, payload.key_name, user.id, old_value, payload.value)
        _invalidate_provider_health((payload.key_name,))
        logger.info("[api] global secret upsert | key=%s | by=%s | mode=mask",
                    payload.key_name, user.id)
        return chat_keys.mask_key_info(payload.key_name, payload.value)
    if chat_id is None:
        # scope=auto/chat без X-Chat-Id и без глобального allowlist — прежний 422.
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    # F-14 (§3.2/§3.3): в DM-скоупе доступ ТОЛЬКО владельцу (глобальный
    # админ в ЧУЖОМ ЛС → 403); в группах — global/local admin как раньше.
    if chat_params.is_dm_scope(chat_id):
        dm_allowed = bool(ctx.is_dm_owner)
    else:
        dm_allowed = bool(ctx.is_global_admin or ctx.is_local_admin)
    if not dm_allowed:
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    if ctx.is_dm_owner:
        await chat_params.ensure_scope_profile(chat_id, dm=True, pg=cache.pg)
    try:
        mask = await chat_keys.set_chat_key(cache.pg, chat_id,
                                            payload.key_name, payload.value,
                                            changed_by=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # R10.9-4: BYOK-ключ чата питает probe (_saved_api_key) → health стейл.
    _invalidate_provider_health(("keys.llm_api_key",))
    logger.info("[api] chat key upsert | chat=%s | key=%s | by=%s",
                chat_id, payload.key_name, user.id)
    return mask


@api_router.delete("/config/keys/own/{key_name}")
async def config_keys_own_delete(
    key_name: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): удаление BYOK-ключа чата.
    F-14 (§3.2): гейт + DM-владелец своего ЛС.
    F11 (10.24, ADR-1024-12 D1): без X-Chat-Id → удаление ГЛОБАЛЬНОГО секрета
    (global admin + allowlist; сброс глобального слоя + аудит)."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        ctx = await _ctx_global_admin(cache, user)
        if not ctx.is_global_admin:
            raise HTTPException(status_code=403,
                                detail="только для глобального админа")
        if not chat_keys.is_global_secret(key_name):
            raise HTTPException(status_code=422,
                                detail=f"{key_name}: не глобальный секрет")
        if not cache.pg_available:
            raise HTTPException(status_code=503,
                                detail="PostgreSQL недоступен (R6)")
        had_value = bool(cache.get(key_name))
        if had_value:
            await cache.set(key_name, "", CATEGORY_KEYS)
            await chat_keys.record_global_secret_audit(
                cache.pg, key_name, user.id, True, "")
        _invalidate_provider_health((key_name,))
        logger.info("[api] global secret delete | key=%s | by=%s | removed=%s",
                    key_name, user.id, had_value)
        return {"removed": had_value}
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    # F-14 (§3.2/§3.3): в DM-скоупе доступ ТОЛЬКО владельцу (глобальный
    # админ в ЧУЖОМ ЛС → 403); в группах — global/local admin как раньше.
    if chat_params.is_dm_scope(chat_id):
        dm_allowed = bool(ctx.is_dm_owner)
    else:
        dm_allowed = bool(ctx.is_global_admin or ctx.is_local_admin)
    if not dm_allowed:
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    try:
        removed = await chat_keys.delete_chat_key(cache.pg, chat_id,
                                                  key_name, changed_by=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # R10.9-4: удаление BYOK-ключа → probe снова смотрит глобальный/дефолт.
    _invalidate_provider_health(("keys.llm_api_key",))
    return {"removed": removed}


@api_router.get("/config/keys/status")
async def config_keys_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): статусы ключей чата. Глобальный ключ в поле
    `global` — ТОЛЬКО для global admin (локальный его НЕ видит — §1.2-2)."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not access_srv.can_access_chat(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    root = await chat_params.get_all_chat_params(chat_id)
    own = {r["key_name"]: r for r in
           await chat_keys.list_own_keys(cache.pg, chat_id)}
    allow_global = bool((root.get("keys") or {}).get("allow_global", True))
    global_key_value = cache.get_all().get("keys.llm_api_key")
    out = {
        "own": own,
        "allow_global": allow_global,
        "budgets": await chat_usage.key_status(cache.pg, chat_id),
    }
    if ctx.is_global_admin:
        out["global"] = _mask_secret(global_key_value, user.id,
                                     "keys.llm_api_key", cache)
    return out


@api_router.delete("/config/chat/{key}")
async def delete_chat_param(
    key: str,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Раунд 10 (F-7 §6): сброс override чата на глобальный
    (jsonb_remove('overrides', key)); 404 — override отсутствует;
    403 — чужие права; 409 optimistic.
    F-14 (§3.2): гейт (is_global_admin or is_local_admin or is_dm_owner) —
    DM-владелец сбрасывает ТОЛЬКО override своего ЛС; ensure профиля."""
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    # F-14 (§3.2/§3.3): в DM-скоупе доступ ТОЛЬКО владельцу (глобальный
    # админ в ЧУЖОМ ЛС → 403); в группах — global/local admin как раньше.
    if chat_params.is_dm_scope(chat_id):
        dm_allowed = bool(ctx.is_dm_owner)
    else:
        dm_allowed = bool(ctx.is_global_admin or ctx.is_local_admin)
    if not dm_allowed:
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    if ctx.is_dm_owner:
        await chat_params.ensure_scope_profile(chat_id, dm=True, pg=cache.pg)
    root = await chat_params.get_all_chat_params(chat_id, pg=cache.pg)
    overrides = dict(root.get("overrides") or {})
    if key not in overrides:
        raise HTTPException(status_code=404,
                            detail=f"нет override: {key}")
    overrides.pop(key, None)
    # D-3 (ревью Батча C): merge `meta`, НЕ затираем чужой meta (например,
    # `chat_settings_seed_version`) — иначе сид переприменит политику на рестарте.
    meta = dict(root.get("meta") or {})
    meta["updated_by"] = user.id
    try:
        await chat_params.set_chat_params(
            chat_id, {"overrides": overrides, "meta": meta},
            changed_by=user.id, pg=cache.pg)
    except chat_params.ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at,
                    "conflicting": getattr(exc, "conflicting", []) or [],
                    "applied": []})
    logger.info("[api] chat param reset | chat=%s | key=%s | by=%s",
                chat_id, key, user.id)
    return {"reset": key, "chat_id": chat_id}


# D07 (ASAP 8 v6, §9B.2/§9B.3): карта per-chat overrides для global-view.
# Читаем chat_profiles целиком (админ-масштаб — десятки чатов); RBAC-фильтр —
# в Python (chat_admins-гранты + F-14 DM-правило), каталог-фильтр — тоже.
OVERRIDES_FOR_USER_SQL = (
    "SELECT p.chat_id, p.chat_params->'overrides' AS overrides, "
    "a.role_name AS chat_role "
    "FROM chat_profiles p "
    "LEFT JOIN chat_admins a ON a.chat_id = p.chat_id AND a.telegram_id = $1 "
    "WHERE p.chat_params ? 'overrides' "
    "AND p.chat_params->'overrides' IS NOT NULL "
    "ORDER BY p.chat_id"
)


@api_router.get("/config/overrides-map")
async def config_overrides_map(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    key: Annotated[str | None, Query()] = None,
):
    """D07 (v6 §9B.2/§9B.3): карта per-chat overrides — global-view popover.

    Read-only. Для per_chat-ключей — список чатов с ЯВНЫМ override:
    {key, chat_id, chat_title, value, source:'chat', access, is_dm}.
    Без `key` — все ключи (avatar stack на карточках); с `key` — только
    этот ключ (popover конкретной карточки).

    RBAC: только чаты, доступные текущему админу — global admin → все
    группы; chat-грант local_admin/moderator → свои чаты; ЛС → только
    свои (F-14: чужие ЛС не видны никому, включая global admin).
    Plain user без админ-грантов (rank < moderator) → 403. Значения
    секретов маскируются ({configured,last4}, R17: секреты не отдаются).
    """
    cache: ConfigCache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, cache=cache)
    pool = getattr(cache.pg, "pool", None) if cache.pg is not None else None
    if pool is None:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(OVERRIDES_FOR_USER_SQL, user.id)
    except Exception:
        logger.warning("[api] overrides-map read failed", exc_info=True)
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    out: list[dict] = []
    for r in rows:
        chat_id = int(r["chat_id"])
        role = r["chat_role"]
        if chat_params.is_dm_scope(chat_id):
            # F-14: DM-скоуп — только свои ЛС; чужие ЛС не видит никто.
            if chat_id != user.id:
                continue
            access, is_dm = "dm", True
        else:
            if ctx.is_global_admin:
                access, is_dm = "global_admin", False
            elif role in (roles_srv.ROLE_LOCAL_ADMIN,
                          roles_srv.ROLE_MODERATOR):
                access, is_dm = role, False
            else:
                continue    # чужой чат без гранта — настройки не утекают
        overrides = r["overrides"]
        if isinstance(overrides, str):
            try:
                overrides = json.loads(overrides)
            except ValueError:
                continue
        if not isinstance(overrides, dict):
            continue
        title: str | None = None    # лениво: только если ключ виден
        for okey, raw in overrides.items():
            if key is not None and okey != key:
                continue
            spec = get_by_pg_key(okey)
            # Каталог-фильтр: в popover живут только per_chat-ключи;
            # легаси-мусор (не per_chat/hidden/секреты) в chat_params
            # наружу не отдаём.
            if spec is None or spec.hidden or not spec.per_chat:
                continue
            if spec.category == CATEGORY_KEYS:
                continue   # defense-in-depth: секреты через overrides не ходят
            if title is None:
                if is_dm:
                    title = "Личные сообщения"
                else:
                    try:
                        info = await chat_display_info(chat_id)
                    except Exception:
                        info = {}
                    title = info.get("title") or f"Чат {chat_id}"
            value = raw
            if spec.secret:
                value = _mask_secret(value, user.id, okey, cache)
            out.append({"key": okey, "chat_id": chat_id,
                        "chat_title": title, "value": value,
                        "source": "chat", "access": access,
                        "is_dm": is_dm})
    out.sort(key=lambda it: (it["key"], it["chat_id"]))
    # Гейт «не-админ → 403»: либо есть админ-доступ вообще (global admin /
    # moderator+ / custom с правами — can_access_chat), либо пользователь
    # видит хотя бы свой chat-grant/свои ЛС (иначе список пуст и прав нет).
    if not access_srv.can_access_chat(ctx) and not out:
        raise HTTPException(status_code=403, detail="нет доступа")
    return {"key": key, "items": out}


def _same_global_value(a, b) -> bool:
    """F0.1 (D-409-3): равенство значений глобального ключа (без секретов —
    только сравнение; наружу значения не отдаются)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if a == b:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    try:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except Exception:
        return False


async def _post_config_global(request: Request, payload: ConfigUpdateRequest,
                              user: WebAppUser) -> dict:
    """Глобальный путь (no X-Chat-Id).

    F0.1 (ADR-1025-2 D-409-3): ДВА прохода — сперва ПОЛНАЯ валидация всего
    пакета (права/типизация/опции/промпты), затем per-key optimistic-проверка
    (если клиент прислал `updated_at` для ключа) и АТОМАРНАЯ запись через
    `cache.set_many` (одна транзакция). Несовпадение версии при совпадающем
    значении → `revalidated`; при отличающемся → 409 `conflicting`."""
    cache: ConfigCache = get_cache(request)
    if not cache.pg_available:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    prepared: list[dict] = []
    # ── Проход 1: валидация ВСЕГО пакета ДО любой записи ───────────────────
    for item in payload.items:
        spec = get_by_pg_key(item.key)
        if spec is not None and spec.hidden:
            # ASAP-3.2 (§102/§124): скрытые ключи не редактируются вручную
            # (значение — через соответствующий модуль, напр.
            # POST /api/cover/select для выбора стиля).
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: значение задаётся в соответствующем "
                       "разделе Mini App, а не вручную")
        if spec is None or spec.category is None:
            raise HTTPException(status_code=422,
                                detail=f"неизвестный ключ: {item.key}")
        if spec.category == CATEGORY_KEYS:
            allowed = can_view_key_value(cache, user.id, item.key)
        else:
            allowed = can_edit_param(cache, user.id, item.key)
        if not allowed:
            raise HTTPException(status_code=403,
                                detail=f"нет права на {item.key}")
        try:
            value = _coerce_value(spec, item.value)
        except ValueError as exc:
            raise HTTPException(status_code=422,
                                detail=f"{item.key}: {exc}")
        # Раунд 10.4 (B-9): select-виджет — значение из набора опций
        if spec.widget == "select" and spec.select_options                 and value not in spec.select_options:
            raise HTTPException(
                status_code=422,
                detail=f"{item.key}: недопустимая опция: {value!r}")
        if spec.type == "str" and spec.category in (CATEGORY_PROMPTS,
                                                    CATEGORY_CONTENT):
            if not isinstance(value, str) or not value.strip():
                raise HTTPException(
                    status_code=422,
                    detail=f"{item.key}: промпт не может быть пустым")
        prepared.append({"key": item.key, "value": value,
                         "category": spec.category,
                         "token": getattr(item, "updated_at", None)})
    if not prepared:
        raise HTTPException(status_code=422, detail="items пуст")
    # ── Проход 2: per-key optimistic + атомарная запись пакета ─────────────
    to_write: list[tuple[str, object, str]] = []
    updated: list[str] = []
    conflicting: list[dict] = []
    revalidated = False
    tokens_used = False
    for entry in prepared:
        token = entry["token"]
        if token is None:
            to_write.append((entry["key"], entry["value"], entry["category"]))
            updated.append(entry["key"])
            continue
        tokens_used = True
        try:
            current_token = cache.get_updated_at(entry["key"])
        except Exception:
            current_token = None
        if current_token == token:
            to_write.append((entry["key"], entry["value"], entry["category"]))
            updated.append(entry["key"])
            continue
        # Токен устарел: D-409-1 — значение уже на сервере?
        try:
            current = cache.get(entry["key"])
        except Exception:
            current = None
        if _same_global_value(current, entry["value"]):
            revalidated = True                 # уже применено → успех
            updated.append(entry["key"])
        else:
            # M-3 (ревью, R17): для секретных ключей (keys.*) НЕ возвращаем
            # сырое серверное значение — только признак конфликта/маску.
            conflict_item = {"key": entry["key"],
                             "your_value": entry["value"]}
            if entry["category"] == CATEGORY_KEYS:
                conflict_item["server_value"] = None
                conflict_item["secret"] = True
            else:
                conflict_item["server_value"] = current
            conflicting.append(conflict_item)
    if conflicting:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "current_updated_at": None,
                    "conflicting": conflicting, "applied": []})
    if to_write:
        set_many = getattr(cache, "set_many", None)
        if set_many is not None:
            await set_many(to_write)
        else:
            # Совместимость с лёгкими кэшами-двойниками без пакета.
            for key, value, category in to_write:
                await cache.set(key, value, category)
    for key in updated:
        logger.info("[api] config updated | key=%s | by=%s", key, user.id)
    # R10.9-4 (F5 round1014): смена base_url/model/key → health переспрашивается.
    _invalidate_provider_health(updated)
    snapshots = await _prompt_record_saved_snapshots(
        cache, [(entry["key"], entry["value"]) for entry in prepared
                if entry["key"] in updated],
        scope="global", chat_id=None, actor=user.id)
    out: dict = {"updated": updated}
    if tokens_used:
        # Аддитивно (R16): поле появляется только при per-key-токенах —
        # базовая форма ответа `{"updated": [...]}` не меняется.
        out["revalidated"] = revalidated
    if snapshots:
        out["prompt_snapshots"] = snapshots
    return out


# ── Admins ──────────────────────────────────────────────────────────────────

@api_router.get("/admins")
async def get_admins(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.5 + F7: полные карточки (added_by/created_at; при деградации — null).

    10.10 (п.5, ADR-1010-3): копии строк обогащаются display_name/
    photo_file_id через global_user_display_info (bot.get_chat(user_id),
    RAM-TTL 1ч); fail-open — без бота/ошибки поля None, фронт покажет ID.
    Модель admins_full()/bot_admins не меняется, секретов не добавляем."""
    cache: ConfigCache = get_cache(request)
    rows = [dict(a) for a in cache.admins_full()]
    if rows:
        sem = asyncio.Semaphore(5)
        from web.api.avatars import global_user_display_info

        async def _enrich(row: dict) -> dict:
            async with sem:
                info = await global_user_display_info(int(row["telegram_id"]))
            row["display_name"] = info.get("display_name")
            row["photo_file_id"] = info.get("photo_file_id")
            return row

        rows = list(await asyncio.gather(*[_enrich(r) for r in rows]))
    return {"admins": rows}


@api_router.post("/admins")
async def post_admins(
    request: Request,
    payload: AdminUpsert,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.5: upsert; несуществующая роль → 422; added_by = текущий юзер."""
    cache: ConfigCache = get_cache(request)
    if payload.role_name not in cache.roles():
        raise HTTPException(status_code=422,
                            detail=f"несуществующая роль: {payload.role_name}")
    try:
        await cache.upsert_admin(payload.telegram_id, payload.role_name,
                                 added_by=user.id)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    return {"telegram_id": payload.telegram_id, "role_name": payload.role_name}


@api_router.post("/admins/remove")
async def remove_admin(
    request: Request,
    payload: AdminRemove,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.5: {removed:true}; guard'ы: последний админ в списке → 409 (F8),
    последний wildcard-админ → 409 (84.14.4)."""
    cache: ConfigCache = get_cache(request)
    target_role = cache.get_role(payload.telegram_id)
    if target_role is None:
        raise HTTPException(status_code=404, detail="админ не найден")
    if len(cache.admins()) <= 1:
        # F8: нельзя оставить систему без единого админа вообще
        raise HTTPException(
            status_code=409,
            detail="нельзя удалить последнего админа")
    target_perms = cache.get_permissions(target_role) or Permissions.from_dict({})
    if target_perms.wildcard:
        other_wildcard = any(
            tg != payload.telegram_id
            and (cache.get_permissions(cache.get_role(tg) or "") or
                 Permissions.from_dict({})).wildcard
            for tg in cache.admins()
        )
        if not other_wildcard:
            raise HTTPException(
                status_code=409,
                detail="нельзя удалить последнего админа с полным доступом")
    try:
        removed = await cache.remove_admin(payload.telegram_id)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    return {"removed": removed}


# ── Roles ───────────────────────────────────────────────────────────────────

@api_router.get("/roles")
async def get_roles(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    cache: ConfigCache = get_cache(request)
    return {
        "roles": [
            {"role_name": name, "permissions": role["permissions"],
             "is_custom": role["is_custom"],
             # OD15/T-1141: role_type нужен UI, чтобы disabled-ить
             # rename/delete встроенных ролей (superuser — тоже).
             "role_type": role.get("role_type")}
            for name, role in sorted(cache.roles().items())
        ]
    }


@api_router.post("/roles")
async def post_roles(
    request: Request,
    payload: RoleUpsert,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """84.14.4: upsert ЛЮБОЙ роли (включая системные); guard последней
    wildcard → 409; неизвестный id права → 422; is_custom — флаг
    происхождения (для новой роли из запроса/дефолт true, для существующей
    сохраняется)."""
    cache: ConfigCache = get_cache(request)
    try:
        validate_permissions(
            payload.permissions,
            known_sections=known_sections(),
            known_params=known_param_keys(),
            known_keys=known_secret_keys(),
            known_actions=ACTION_IDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    existing = cache.roles().get(payload.role_name)
    new_perms = Permissions.from_dict(payload.permissions)
    if existing is not None:
        old_perms = Permissions.from_dict(existing["permissions"])
        if old_perms.wildcard and not new_perms.wildcard:
            try:
                guard_last_wildcard(
                    {name: Permissions.from_dict(r["permissions"])
                     for name, r in cache.roles().items()},
                    payload.role_name, new_perms)
            except RoleGuardError as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc))
        is_custom = bool(existing["is_custom"])   # сервер сохраняет флаг (84.14.4)
    else:
        is_custom = payload.is_custom if payload.is_custom is not None else True

    try:
        await cache.upsert_role(payload.role_name, new_perms.to_dict(), is_custom)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    logger.info("[api] role upserted | role=%s | by=%s", payload.role_name, user.id)
    return {"role_name": payload.role_name, "permissions": new_perms.to_dict(),
            "is_custom": is_custom}


# ── OD15/T-1141 (раунд 10.5): защита ролей при rename/delete ──────────────
_SUPERUSER_ROLE_NAMES = frozenset({"admin", "global_admin", "superuser"})


def _is_superuser_role(role_name: str, role: dict | None) -> bool:
    """superuser — абсолютная защита (OD15): никогда не rename/delete."""
    if role_name in _SUPERUSER_ROLE_NAMES:
        return True
    return bool(role and role.get("role_type") == "global_admin")


def _is_builtin_role(role: dict | None) -> bool:
    """Встроенные (role_type задан) — rename/delete запрещены (OD15)."""
    return bool(role and role.get("role_type"))


@api_router.delete("/roles/{role_name}")
async def delete_role_endpoint(
    request: Request,
    role_name: str,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """OD15/T-1141: удалить пользовательскую роль. Superuser → 403;
    встроенные → 409; занятые (bot_admins) → 409; последняя wildcard → 409."""
    cache: ConfigCache = get_cache(request)
    role = cache.roles().get(role_name)
    if role is None:
        raise HTTPException(status_code=404, detail=f"роль не найдена: {role_name}")
    if _is_superuser_role(role_name, role):
        raise HTTPException(status_code=403,
                            detail="роль суперпользователя защищена")
    if _is_builtin_role(role):
        raise HTTPException(status_code=409,
                            detail="встроенную роль нельзя удалить")
    used = await cache.role_usage(role_name)
    if used:
        raise HTTPException(
            status_code=409,
            detail=f"роль назначена {used} админ(ам) — сначала переназначьте")
    try:
        guard_last_wildcard(
            {n: Permissions.from_dict(r["permissions"])
             for n, r in cache.roles().items()},
            role_name, None)
    except RoleGuardError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    try:
        removed = await cache.delete_role(role_name)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    if not removed:
        raise HTTPException(status_code=404, detail=f"роль не найдена: {role_name}")
    logger.info("[api] role deleted | role=%s | by=%s | audit=role",
                role_name, user.id)
    return {"removed": True, "role_name": role_name}


@api_router.post("/roles/{role_name}/rename")
async def rename_role_endpoint(
    request: Request,
    role_name: str,
    payload: RoleRename,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
):
    """OD15/T-1141: переименовать пользовательскую роль (каскад — в
    ConfigCache.rename_role). Superuser → 403; встроенные → 409;
    имя занято → 409."""
    cache: ConfigCache = get_cache(request)
    role = cache.roles().get(role_name)
    if role is None:
        raise HTTPException(status_code=404, detail=f"роль не найдена: {role_name}")
    if _is_superuser_role(role_name, role):
        raise HTTPException(status_code=403,
                            detail="роль суперпользователя защищена")
    if _is_builtin_role(role):
        raise HTTPException(status_code=409,
                            detail="встроенную роль нельзя переименовать")
    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="пустое новое имя")
    if new_name != role_name and new_name in cache.roles():
        raise HTTPException(status_code=409,
                            detail=f"роль уже существует: {new_name}")
    if new_name == role_name:
        return {"role_name": role_name, "old_name": role_name,
                "renamed": False}
    try:
        await cache.rename_role(role_name, new_name)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    logger.info("[api] role renamed | old=%s | new=%s | by=%s | audit=role",
                role_name, new_name, user.id)
    return {"role_name": new_name, "old_name": role_name, "renamed": True}


@api_router.get("/roles/tree")
async def get_roles_tree(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("access"))],
    role_name: str | None = Query(default=None),
):
    """84.14.4 (бэкенд-часть T-640): дерево доступных прав из param_catalog +
    ACTIONS_TREE; checked — отметки прав роли (для чекбокс-конструктора)."""
    cache: ConfigCache = get_cache(request)
    target_perms: Permissions | None = None
    if role_name:
        target_perms = cache.get_permissions(role_name)
        if target_perms is None:
            raise HTTPException(status_code=404,
                                detail=f"роль не найдена: {role_name}")

    def checked(required: str) -> bool:
        if target_perms is None:
            return False
        return match_permission(target_perms, required)

    sections = []
    for category in CATEGORIES:
        specs = param_catalog.by_category(category)
        if not specs:
            continue
        params = []
        keys = []
        for spec in sorted(specs, key=lambda s: s.pg_key):
            node = {"key": spec.pg_key, "title": spec.title_ru,
                    "type": spec.type, "secret": spec.secret,
                    "checked": checked(f"param.{spec.pg_key}")}
            if category == CATEGORY_KEYS:
                node["checked"] = checked(f"key.{spec.pg_key}")
                keys.append(node)
            else:
                params.append(node)
        sections.append({
            "id": category,
            "title": _category_title(category),
            "checked": checked(f"section.{category}"),
            "params": params,
            "keys": keys,
        })
    sections.append({
        "id": "access",
        "title": _ACCESS_SECTION_TITLE,
        "checked": checked("section.access"),
        "params": [],
        "keys": [],
    })
    actions = [
        {"id": action["id"], "title": action["title"],
         "checked": checked(f"action.{action['id']}")}
        for action in ACTIONS_TREE
    ]
    return {"sections": sections, "actions": actions}


# ── Info («Как это работает», 84.13) ────────────────────────────────────────

@api_router.get("/info")
async def get_info(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """84.13.4: публичный (TMA-auth, ЛЮБАЯ роль, без requires_permission).
    F2 10.16 (аддитивно, ADR-1016-3): + `canon_version`/`canon_current_version`/
    `canon_drift` (drift=true — текст не совпадает с код-каноном; UI-подсказка
    для force-reset). Существующие поля не меняются."""
    from services.info_service import (
        INFO_CANON_VERSION,
        canon_drift,
    )

    cache: ConfigCache = get_cache(request)
    value = cache.get(_INFO_KEY)
    if isinstance(value, dict):
        html = value.get("html", "")
        return {
            "key": _INFO_KEY,
            "html": html,
            "updated_at": value.get("updated_at"),
            "updated_by": value.get("updated_by"),
            "canon_version": value.get("canon_version"),
            "canon_current_version": INFO_CANON_VERSION,
            "canon_drift": canon_drift(html),
        }
    return {"key": _INFO_KEY, "html": value or "", "updated_at": None,
            "updated_by": None, "canon_version": None,
            "canon_current_version": INFO_CANON_VERSION,
            "canon_drift": canon_drift(value if isinstance(value, str) else None)}


@api_router.post("/info")
async def post_info(
    request: Request,
    payload: InfoUpdate,
    user: Annotated[WebAppUser, Depends(requires_permission("edit_info"))],
):
    """84.13.4: право edit_info (по сиду — только admin через wildcard);
    лимит 32768 (прецедент _RICH_TEXT_LIMIT 53.3); пусто → 422.
    F2 10.16 (ADR-1016-3 §4): запись **PG-only** через InfoService.save_text()
    (tracked `info_text.md` НЕ пишется — pull не блокируется). F18/F2:
    PG down → 503 (локально-только НЕ пишем)."""
    cache: ConfigCache = get_cache(request)
    html = payload.html
    if not html.strip():
        raise HTTPException(status_code=422, detail="html пуст")
    if len(html) > _RICH_TEXT_LIMIT:
        raise HTTPException(status_code=422,
                            detail=f"html превышает {_RICH_TEXT_LIMIT} символов")
    if not cache.pg_available:
        # F18: без PG значение не персистентно — честный 503
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    try:
        from services.info_service import InfoService
        value = await InfoService().save_text(html, updated_by=user.id, cache=cache)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    except Exception:
        logger.exception("[api] info save failed | by=%s", user.id)
        raise HTTPException(status_code=500, detail="сохранение не удалось")
    logger.info("[api] info updated | by=%s | chars=%d", user.id, len(html))
    return {"key": _INFO_KEY, "updated_at": value["updated_at"],
            "updated_by": user.id}


@api_router.post("/info/reset-canon")
async def post_info_reset_canon(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("edit_info"))],
):
    """F2 10.16 (ADR-1016-3 §3): явный force-reset «Гайда по фичам» к код-канону.
    RBAC `edit_info` (как /api/info); текущий текст бэкапится в `prev_html` +
    `prev_updated_at`, аудит — `updated_by`/`updated_at` (R16/R17).
    PG down → 503. Ответ: `{canon_version, updated_at, updated_by}`."""
    from services.info_service import InfoService

    cache: ConfigCache = get_cache(request)
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    try:
        value = await InfoService().reset_canon(updated_by=user.id, cache=cache)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    except Exception:
        logger.exception("[api] info canon reset failed | by=%s", user.id)
        raise HTTPException(status_code=500, detail="сброс к канону не удался")
    logger.info("[api] info canon reset | by=%s | version=%s",
                user.id, value.get("canon_version"))
    return {"key": _INFO_KEY, "canon_version": value.get("canon_version"),
            "updated_at": value.get("updated_at"), "updated_by": user.id}


# ── F6 (10.14): гайд по возможностям (Markdown, PG-only) ─────────────────────

@api_router.get("/info/guide")
async def get_info_guide(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """F6 (spec §2.3): TMA-auth, ЛЮБАЯ роль. PG down/нет ключа → код-канон
    (сид-файл) или пусто — fail-open, всегда 200."""
    from services.info_service import InfoService

    guide = InfoService().get_guide()
    return {"key": _GUIDE_KEY, **guide}


@api_router.get("/info/guide/backup")
async def get_info_guide_backup(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("edit_info"))],
):
    """F9 10.23 (review iter2): бэкап прежней ревизии гайда — ТОЛЬКО под RBAC
    `edit_info` (принцип наименьших привилегий: там может лежать неопубликованный
    черновик владельца). Публичный `GET /api/info/guide` бэкап НЕ отдаёт.
    Fail-open, всегда 200; нет бэкапа → оба поля None (R16/R17)."""
    from services.info_service import InfoService

    return {"key": _GUIDE_KEY, **InfoService().get_guide_backup()}


@api_router.post("/info/guide")
async def post_info_guide(
    request: Request,
    payload: GuideUpdate,
    user: Annotated[WebAppUser, Depends(requires_permission("edit_info"))],
):
    """F6 (spec §2.3): право edit_info (как /api/info); пусто → 422;
    > _GUIDE_LIMIT → 422; PG down → 503. Запись через InfoService.save_guide
    (единственная точка записи)."""
    cache: ConfigCache = get_cache(request)
    markdown = payload.markdown
    if not markdown.strip():
        raise HTTPException(status_code=422, detail="markdown пуст")
    if len(markdown) > _GUIDE_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"markdown превышает {_GUIDE_LIMIT} символов")
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    try:
        from services.info_service import InfoService
        value = await InfoService().save_guide(markdown, updated_by=user.id)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    except Exception:
        logger.exception("[api] guide save failed | by=%s", user.id)
        raise HTTPException(status_code=500, detail="сохранение не удалось")
    logger.info("[api] guide updated | by=%s | chars=%d", user.id, len(markdown))
    return {"key": _GUIDE_KEY, "updated_at": value["updated_at"],
            "updated_by": user.id}


@api_router.post("/info/guide/reset")
async def post_info_guide_reset(
    request: Request,
    user: Annotated[WebAppUser, Depends(requires_permission("edit_info"))],
):
    """F9 10.23 (ADR-1023-9 Decision 6): явный force-reset «Гайда по
    возможностям» к код-канону (сид-файл). RBAC `edit_info` (как /api/info/guide);
    прежний текст бэкапится в `prev_markdown`/`prev_updated_at`, аудит —
    `updated_by`/`updated_at` (R16/R17). PG down / нет канона → 503.
    Ответ: `{guide_version, updated_at, updated_by}`. Аддитивно (R16)."""
    from services.info_service import InfoService

    cache: ConfigCache = get_cache(request)
    if not cache.pg_available:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    try:
        value = await InfoService().reset_guide(updated_by=user.id, cache=cache)
    except ConfigCacheUnavailableError:
        raise HTTPException(status_code=503, detail="PostgreSQL недоступен (R6)")
    except Exception:
        logger.exception("[api] guide canon reset failed | by=%s", user.id)
        raise HTTPException(status_code=500, detail="сброс гайда к канону не удался")
    logger.info("[api] guide canon reset | by=%s | version=%s",
                user.id, value.get("guide_version"))
    return {"key": _GUIDE_KEY, "guide_version": value.get("guide_version"),
            "updated_at": value.get("updated_at"), "updated_by": user.id,
            "prev_markdown": value.get("prev_markdown"),
            "prev_updated_at": value.get("prev_updated_at")}


def _category_title(category: str) -> str:
    return {
        "prompts": "Промпты",
        "models": "Модели и провайдеры",
        "keys": "API-ключи",
        "limits": "Лимиты и кулдауны",
        "flags": "Флаги модулей",
        "reactions": "Реакции и персоны",
        "content": "Контент",
        "memory": "Память",
        "temporal": "Временной фактчек",
    }.get(category, category)


# ── Status (84.11.4, T-631): публично для любого валидного TMA-юзера ────────

@api_router.get("/status")
async def get_status(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Сводка bot/server/llm/uptime. БЕЗ requires_permission (84.11 —
    RBAC-исключение); ключи LLM — только configured/last4 для global admin,
    {configured} для остальных (фикс S2, F-7 §1.2-2). X-Chat-Id (опц.) —
    F-9 §6 телеметрия PERMsoc для контекста чата."""
    from services.status_service import status
    from services import roles as roles_srv
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    ctx = None
    try:
        ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    except Exception:
        ctx = None
    # MCA-10a (ADR-1028-14 D9): журнал draw блока «Источник случайности» —
    # в рамках прав на чат (RBAC-проверка существующим `can_access_chat`;
    # без доступа/контекста журнал не отдаётся, состояние источника — да).
    chat_scope_allowed = bool(
        chat_id is None or (ctx is not None
                            and access_srv.can_access_chat(ctx, chat_id)))
    return await status.build_snapshot(
        cache, ctx=ctx, chat_id=chat_id, chat_scope_allowed=chat_scope_allowed)


@api_router.get("/status/key-history")
async def get_status_key_history(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """B1/OD8 + OD12/OD19 (T-1128/T-1129/T-1140): история доступности ключей.

    Только allowlist-поля (R17/leak-safety): module_id/module_title/provider/
    model/samples[{ts,ok,http_status}] + version/generated_at. Сырые ключи,
    Authorization, base_url с credentials, last4 — НЕ отдаются.
    """
    from services.status_service import key_history
    return key_history.api_payload()


# D-5 (ревью Батча E): TTL-кэш тяжёлой диагностики медиа (COUNT + обход ФС).
_MEDIA_HEALTH_TTL = 120.0
_media_health_cache: dict = {}          # chat_id -> (db, ts, payload)


def _media_health_cached(db, chat_id):
    entry = _media_health_cache.get(chat_id)
    if entry is not None:
        c_db, ts, payload = entry
        if c_db is db and (time.monotonic() - ts) < _MEDIA_HEALTH_TTL:
            return payload
    return None


def _media_health_store(db, chat_id, payload) -> None:
    _media_health_cache[chat_id] = (db, time.monotonic(), payload)


@api_router.get("/status/media-health")
async def get_status_media_health(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """F6 (ADR-1019-5 D3, R16): рассинхрон ФС↔БД медиа-файлов.

    Аддитивный блок «Сводки»: ТОЛЬКО числа и хвосты имён (`photos/file_*.jpg`)
    — строка `<bot_id>:<token>` и абсолютные пути не отдаются (R17).
    Fail-open: нет БД/бота/ошибка → нулевые счётчики (не 500).

    D-5 (ревью Батча E): результат TTL-кэшируется (120с на chat_id), чтобы
    `COUNT(*) … media_type IN (…)` и обход диска не выполнялись на каждом
    запросе. `reliable=false`/`basis='text_scan'` — honest-контракт (D-4):
    missing/orphan — эвристика по тексту, а не точный рассинхрон."""
    from services import lore_runtime, media_integrity, web_runtime
    chat_id = _chat_id_or_none(x_chat_id)
    db = lore_runtime.get_lore_db()
    if db is None:
        return {"available": False}
    cached = _media_health_cached(db, chat_id)
    if cached is not None:
        return {"available": True, **cached}
    audit = await media_integrity.audit_media_files(
        db, web_runtime.get_web_bot(), chat_id=chat_id)
    _media_health_store(db, chat_id, audit)
    return {"available": True, **audit}


@api_router.get("/status/logs")
async def get_status_logs(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    level: str = Query(default="INFO"),
    limit: int = Query(default=200, ge=1, le=1000),
    trace_id: str | None = Query(default=None),
    chat_id: int | None = Query(default=None),
    component: str | None = Query(default=None),
    reason_code: str | None = Query(default=None),
    pipeline_run_id: str | None = Query(default=None),
):
    """Логи из ring-buffer (84.11.4): публично; секреты замаскированы уже
    в буфере (84.11.1). level: DEBUG|INFO|WARNING|ERROR|CRITICAL|ALL|
    ERROR+WARNING (F6/§3.1: ERROR+WARNING = WARNING ∪ ERROR ∪ CRITICAL;
    дефолт INFO = INFO и выше); от новых к старым.

    Раунд 10.27 (`mca-17a`, carry-over §94.5/SC-14): аддитивные фильтры
    `trace_id`/`chat_id`/`component`/`reason_code`/`pipeline_run_id`; при
    наличии фильтра отдаются связанные `mca_events` (bounded `query_events`)
    в поле `events` — переход из карточки к связанным событиям trace.
    Новых endpoint/панелей нет (REUSE существующего log viewer)."""
    from services.log_ring import get_log_ring
    ring = get_log_ring()
    entries = ring.get_entries(level=level, limit=limit)
    # F11 (H-F11S-1, §20): аддитивный `counts` — точные числа по уровням по
    # ВСЕМУ ring-буферу. Поле `count` ограничено `limit` (обратная
    # совместимость сохранена). Новых endpoint'ов/DDL/каталога нет
    # (R16-аддитивно, R17-безопасно: те же значения уровней, что и в логах).
    result = {"count": len(entries), "counts": ring.level_counts(),
              "logs": entries, "events": []}
    has_filter = any(v is not None for v in (
        trace_id, chat_id, component, reason_code, pipeline_run_id))
    if has_filter:
        # F11/RBAC: связанные `mca_events` по произвольному `chat_id` — только
        # для глобального админа (chat isolation/R17; сам log viewer остаётся
        # прежним `get_tma_user`). Не-админ получает честный пустой `events`
        # + `events_restricted=true` (без раскрытия чужих чатов).
        if not _is_global_admin(request, user):
            result["events_restricted"] = True
            return result
        from services import mca_events as _me
        from services import lore_runtime
        db = lore_runtime.get_lore_db()
        try:
            result["events"] = await _me.query_events(
                db, trace_id=trace_id, chat_id=chat_id, component=component,
                reason_code=reason_code, pipeline_run_id=pipeline_run_id,
                limit=min(int(limit), 500))
        except Exception:
            logger.warning("[status/logs] mca_events query failed — empty",
                           exc_info=True)
            result["events"] = []
    return result


def _is_global_admin(request: Request, user: WebAppUser) -> bool:
    """F11: глобальный админ (wildcard/role admin/global_admin) — REUSE логики
    `requires_global_admin`; fail-closed (ошибка → False)."""
    try:
        cache = get_cache(request)
        perms = cache.get_permissions_by_telegram_id(user.id)
        if perms is not None and getattr(perms, "wildcard", False):
            return True
        role = cache.get_role(user.id)
        if role == "admin":
            return True
        from services.roles import role_type_of
        roles = cache.roles()
        role_meta = roles.get(role) if role else None
        rt = role_type_of(role, role_meta,
                          role_meta.get("role_type") if role_meta else None)
        return rt == "global_admin"
    except Exception:
        return False


# ── Control (84.15, T-641): POST /api/control/restart|stop|start ────────────

async def _run_control(request: Request, action: str, user: WebAppUser) -> dict:
    from services.control_service import (
        ControlDebouncedError,
        ControlStartUnavailableError,
    )
    control = getattr(request.app.state, "control", None)
    if control is None:
        raise HTTPException(status_code=503, detail="control недоступен")
    try:
        return await control.request(action, user.id)
    except ControlDebouncedError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ControlStartUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@api_router.post("/control/restart", status_code=202)
async def control_restart(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.control.restart"))],
):
    return await _run_control(request, "restart", user)


@api_router.post("/control/stop", status_code=202)
async def control_stop(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.control.stop"))],
):
    return await _run_control(request, "stop", user)


@api_router.post("/control/start", status_code=202)
async def control_start(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.control.start"))],
):
    return await _run_control(request, "start", user)


# ── In-Memory State Dump (84.18.5, T-656): GET /api/debug/config ────────────

@api_router.get("/debug/config")
async def get_debug_config(
    request: Request,
    user: Annotated[WebAppUser,
                    Depends(requires_permission("action.debug.config"))],
    key: str | None = Query(default=None),
):
    """84.20.4: JSON-дамп RAM-кэша (не PostgreSQL). key принимает env-имя
    (case-insensitive), settings_field и pg-ключ — через resolve_param_key;
    неизвестный ключ → 404. Право action.debug.config; 401/403 — штатно."""
    cache: ConfigCache = get_cache(request)
    if key:
        spec = resolve_param_key(key)
        if spec is None:
            raise HTTPException(status_code=404,
                                detail=f"не найден: {key}")
        dump = build_dump(cache, key=spec.pg_key)
        item = dump["item"]
        item["name"] = spec.env_name or spec.settings_field or item["key"]
        if is_pg_only(spec):
            item["pg_only"] = True
        return {"meta": dump["meta"], "item": item}
    dump = build_dump(cache)
    for item in dump["items"]:
        spec = get_by_pg_key(item["key"])
        if spec is None:
            item["name"] = item["key"]
            continue
        item["name"] = spec.env_name or spec.settings_field or item["key"]
        if is_pg_only(spec):
            item["pg_only"] = True
    return dump


# ── Раунд 10.6 (T-1210/A4/D4): POST /api/llm/test ───────────────────────────
# Global admin, rate-limit ≥5с на (user, block), R17 (ключ не эхо/не логируется).
_LLM_TEST_MIN_INTERVAL = 5.0
# INFO/ревью: ограничиваем рост dict — записи старше TTL вычищаются.
_LLM_TEST_LAST_TTL = 3600.0
_LLM_TEST_LAST: dict[tuple[int, str], float] = {}


def reset_llm_test_rate_limit() -> None:
    """Тестовая точка сброса серверного rate-limit."""
    _LLM_TEST_LAST.clear()


def _prune_llm_test_last(now: float) -> None:
    """Удаляет устаревшие (user, block) — защита от роста словаря."""
    if len(_LLM_TEST_LAST) < 256:
        return
    stale = [k for k, ts in _LLM_TEST_LAST.items()
             if now - ts > _LLM_TEST_LAST_TTL]
    for k in stale:
        _LLM_TEST_LAST.pop(k, None)


@api_router.post("/llm/test")
async def post_llm_test(
    request: Request,
    payload: LlmTestRequest,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Тестовый запрос провайдера ПЕРЕДАННЫМИ блоком key/model/base_url.

    Всегда 200 с {ok,...} для результата провайдера (плохой key/model →
    ok=false + санитизированное error); 403 — не глобальный админ; 429 —
    повтор того же блока чаще 5 секунд (R17: ключ не возвращается).
    """
    now = time.monotonic()
    _prune_llm_test_last(now)
    rl_key = (user.id, payload.block)
    last = _LLM_TEST_LAST.get(rl_key, 0.0)
    if now - last < _LLM_TEST_MIN_INTERVAL:
        raise HTTPException(status_code=429, detail="повтор блока чаще 5 секунд")
    _LLM_TEST_LAST[rl_key] = now
    from services.llm_probe import probe_block
    return await probe_block(payload.block, payload.base_url, payload.model,
                             payload.api_key)


# ── Раунд 10.24 (F12, ADR-1024-4 D3): POST /api/images/test ─────────────────
# «Проверить подключение»: global admin шлёт тестовый промпт image-провайдеру
# и получает ProbeResult (успех или сырой безопасный текст ошибки). Rate-limit
# ≥10с на пользователя; 200 даже при неуспехе провайдера (ok=false). R17:
# ключ не эхо/не логируется (`probe` возвращает только safe_text тела).
_IMAGES_TEST_MIN_INTERVAL = 10.0
_IMAGES_TEST_LAST_TTL = 3600.0
_IMAGES_TEST_LAST: dict[int, float] = {}


def reset_images_test_rate_limit() -> None:
    """Тестовая точка сброса серверного rate-limit диагностики изображений."""
    _IMAGES_TEST_LAST.clear()


def _prune_images_test_last(now: float) -> None:
    if len(_IMAGES_TEST_LAST) < 256:
        return
    stale = [k for k, ts in _IMAGES_TEST_LAST.items()
             if now - ts > _IMAGES_TEST_LAST_TTL]
    for k in stale:
        _IMAGES_TEST_LAST.pop(k, None)


@api_router.post("/images/test")
async def post_images_test(
    payload: ImageTestRequest,
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Тестовый промпт image-провайдеру; всегда 200 с ProbeResult.

    403 — не глобальный админ; 429 — повтор чаще 10 секунд. Реальный сбой
    провайдера → ``ok=false`` + ``body_excerpt`` (R17-safe)."""
    now = time.monotonic()
    _prune_images_test_last(now)
    last = _IMAGES_TEST_LAST.get(user.id, 0.0)
    if now - last < _IMAGES_TEST_MIN_INTERVAL:
        raise HTTPException(status_code=429,
                            detail="повтор теста чаще 10 секунд")
    _IMAGES_TEST_LAST[user.id] = now
    from services.image_generation import probe
    result = await probe(prompt=payload.prompt)
    return result.as_dict()


# ── ASAP 8 F9 (§16, Y4/Y5): YouTube proxy health ────────────────────────────
# Connection test YouTube-прокси: GET — последний результат (без пробы),
# POST — живая проверка (auth-проба + yt-dlp путь + transcript-api путь).
# Оба — global-admin, fail-closed 403. В ответах ТОЛЬКО замаскированный
# endpoint (host:port) и коды классов/HTTP-статусы: логин/пароль/полный URL
# прокси НИКОГДА не возвращаются и не логируются (Y5). Rate-limit POST —
# ≥10с на пользователя (прецедент /api/images/test).
_YT_PROXY_TEST_MIN_INTERVAL = 10.0
_YT_PROXY_TEST_LAST_TTL = 3600.0
_YT_PROXY_TEST_LAST: dict[int, float] = {}


def reset_youtube_proxy_test_rate_limit() -> None:
    """Тестовая точка сброса серверного rate-limit диагностики YouTube-прокси."""
    _YT_PROXY_TEST_LAST.clear()


def _prune_youtube_proxy_test_last(now: float) -> None:
    if len(_YT_PROXY_TEST_LAST) < 256:
        return
    stale = [k for k, ts in _YT_PROXY_TEST_LAST.items()
             if now - ts > _YT_PROXY_TEST_LAST_TTL]
    for k in stale:
        _YT_PROXY_TEST_LAST.pop(k, None)


@api_router.get("/youtube/proxy/health")
async def get_youtube_proxy_health(
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Последний результат проверки YouTube-прокси (без запуска новой пробы).

    403 — не глобальный админ; никогда не проверявшаяся → {status:
    "never_run"}; секреты не возвращаются (Y5)."""
    from services.youtube_transcript_engine import proxy_health_snapshot
    snap = proxy_health_snapshot()
    if snap is None:
        return {"status": "never_run"}
    return dict(snap)


@api_router.post("/youtube/proxy/test")
async def post_youtube_proxy_test(
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """Живая проверка YouTube-прокси (auth OK/FAIL + оба движка-пути).

    Всегда 200 с результатом шагов (fail движка/прокси → status-поля, не
    HTTP-ошибка); 403 — не глобальный админ; 429 — повтор чаще 10 секунд.
    Singleflight в движке: параллельный вызов → последний результат +
    in_progress. Общий бюджет живой пробы — 90с (wait_for), сам движок
    ограничивает каждый сетевой шаг. R17/Y5: секреты не эхо/не логируются."""
    now = time.monotonic()
    _prune_youtube_proxy_test_last(now)
    last = _YT_PROXY_TEST_LAST.get(user.id, 0.0)
    if now - last < _YT_PROXY_TEST_MIN_INTERVAL:
        raise HTTPException(status_code=429,
                            detail="повтор теста чаще 10 секунд")
    _YT_PROXY_TEST_LAST[user.id] = now
    from services.youtube_transcript_engine import run_proxy_health_check_locked
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(run_proxy_health_check_locked), timeout=90.0)
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "checked_at": datetime.datetime.now(
                datetime.timezone.utc).isoformat(timespec="seconds"),
            "took_ms": int(90.0 * 1000),
        }


# ── Раунд 10.37 (MCA-10a, ADR-1028-14 D8/T-4977): POST /api/random/test ─────
# «Проверить подключение» ANU: backend-only, draft-ключ в POST-body (не URL,
# не эхо), RBAC существующих секретных прав (global admin ИЛИ право на
# `key.keys.random_quantum_api_key`). Singleflight/rate-limit — в сервисе
# (`RandomSourceService.test_connection`: общий результат на повторные клики +
# min interval провайдера). Ответ: status/latency/дата/размер партии/
# очищенная ошибка/key_present; проверочные числа зачисляются в запас.
@api_router.post("/random/test")
async def post_random_test(
    request: Request,
    payload: RandomTestRequest,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Проверка подключения квантового источника (ANU) по ключу из body."""
    cache: ConfigCache = get_cache(request)
    ctx = await _ctx_global_admin(cache, user)
    if not (ctx.is_global_admin or can_view_key_value(
            cache, user.id, "keys.random_quantum_api_key")):
        raise HTTPException(status_code=403,
                            detail="нет прав на управление ключом ANU")
    from services import lore_runtime, mca_random_source
    service = mca_random_source.get_service(lore_runtime.get_lore_db())
    result = await service.test_connection(draft_key=payload.key or None)
    return result


# ── MCA-19 (round 10.43, ADR-1028-19 D4/D15, T-5103/T-5116): /api/vision/* ──
# POST /api/vision/test — «Проверить подключение» (прецедент /api/random/test:
# backend-only, RBAC global admin ИЛИ право на keys.vision_api_key; R17:
# ключ/endpoint не эхо и не логируются; проба — сгенерированное бэкендом
# валидное изображение 512×512+, НЕ текст пользователя; P0: `visible_reason`
# + фактический провайдер/модель/тип подключения). GET /api/vision/state —
# живая effective-линия карточки + компакт «Аналитики» (стадии/очередь/
# последний анализ; без сетевых вызовов).
_VISION_TEST_MIN_INTERVAL = 10.0
_VISION_TEST_LAST_TTL = 3600.0
_VISION_TEST_LAST: dict[int, float] = {}


def reset_vision_test_rate_limit() -> None:
    """Тестовая точка сброса серверного rate-limit диагностики vision."""
    _VISION_TEST_LAST.clear()


def _prune_vision_test_last(now: float) -> None:
    if len(_VISION_TEST_LAST) < 256:
        return
    stale = [k for k, ts in _VISION_TEST_LAST.items()
             if now - ts > _VISION_TEST_LAST_TTL]
    for k in stale:
        _VISION_TEST_LAST.pop(k, None)


async def _scoped_chat_or_none(cache: ConfigCache, user: WebAppUser,
                               chat_id: int | None,
                               x_chat_id: str | None) -> int | None:
    """Контекст ЧАТА запроса: явный `chat_id` (query) или `X-Chat-Id`
    (header, его ставит `web/api()` при активном чате).

    Нет контекста → None (глобальный слой). Чужой чат (нет доступа по
    `can_access_chat`) → тоже None: per-chat данные чужого чата наружу не
    отдаются (прецедент `/api/status`). Единая реализация для
    `/api/vision/*`, `/api/experience/pipeline` (EVOL-020) — вторая копия
    проверки прав не создаётся."""
    scope_chat = chat_id if chat_id is not None \
        else _chat_id_or_none(x_chat_id)
    if scope_chat is None:
        return None
    try:
        scoped = await roles_srv.access_for(user.id, scope_chat, cache=cache)
        if scoped is not None and access_srv.can_access_chat(scoped,
                                                             scope_chat):
            return scope_chat
    except Exception:
        logger.debug("[api] chat scope resolve failed | chat=%s",
                     scope_chat, exc_info=True)
    return None


async def _vision_chat_scope(cache: ConfigCache, user: WebAppUser,
                             chat_id: int | None,
                             x_chat_id: str | None) -> int | None:
    """Контекст ЧАТА для `/api/vision/*` (FIX2 + NF-1).

    Тонкая обёртка над `_scoped_chat_or_none` (имя сохранено: его используют
    vision-эндпоинты и существующие тесты)."""
    return await _scoped_chat_or_none(cache, user, chat_id, x_chat_id)


@api_router.post("/vision/test")
async def post_vision_test(
    request: Request,
    payload: VisionTestRequest,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: int | None = Query(default=None),
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Проверка подключения модели распознавания (D4/T-5103).

    403 — нет прав; 429 — повтор чаще 10 секунд. Ответ всегда 200:
    ``ok`` + capability/image_input/reason (доказанные по пробе, НЕ по имени
    модели) + живая effective-линия (``state``) после проверки.

    NF-1 (ревью `e3fa4e97`): `state` — контекстно-корректный (та же резолюция
    скоупа, что у `GET /api/vision/state`), иначе UI перетирал им per-chat
    линию после пробы: глобально OFF + per-chat ON → кнопка «Проверить
    подключение» возвращала `vision_disabled` на ~30 с. Без контекста и для
    чужого чата — прежний глобальный слой."""
    cache: ConfigCache = get_cache(request)
    ctx = await _ctx_global_admin(cache, user)
    if not (ctx.is_global_admin or can_view_key_value(
            cache, user.id, "keys.vision_api_key")):
        raise HTTPException(status_code=403,
                            detail="нет прав на управление ключом vision")
    now = time.monotonic()
    _prune_vision_test_last(now)
    last = _VISION_TEST_LAST.get(user.id, 0.0)
    if now - last < _VISION_TEST_MIN_INTERVAL:
        raise HTTPException(status_code=429,
                            detail="повтор теста чаще 10 секунд")
    _VISION_TEST_LAST[user.id] = now
    scope_chat = await _vision_chat_scope(cache, user, chat_id, x_chat_id)
    from services import lore_runtime, mca_vision
    verdict = await mca_vision.probe_connection()
    state = await mca_vision.runtime_snapshot(lore_runtime.get_lore_db(),
                                              chat_id=scope_chat)
    return {
        "ok": bool(verdict.capability == "ok" and verdict.image_input),
        "capability": verdict.capability,
        "image_input": verdict.image_input,
        "status_code": None,          # R17: сырой статус не раскрываем
        "latency_ms": None,
        "model": state.get("model") or "",
        "reason": verdict.reason,
        "detail": (verdict.detail or ""),   # класс ошибки, без тела/ключа
        # P0 (recon D11/D12): понятная причина + фактический
        # провайдер/модель/тип — витрина UI-фазы (код остаётся в reason).
        "visible_reason": mca_vision.capability_visible_reason(
            verdict.capability, verdict.reason, verdict.detail),
        "provider": state.get("provider") or "",
        "api_type": state.get("api_type") or "",
        "source": state.get("source") or "",
        "state": state,
    }


@api_router.get("/vision/state")
async def get_vision_state(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: int | None = Query(default=None),
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Живая effective-линия карточки «Распознавание изображений» + компакт
    «Аналитики» (D15/T-5116): requested/effective с человеческой причиной,
    очередь (durable task_jobs), последний анализ, стадии `vision.media` v1.
    БЕЗ сетевых вызовов (effective — из кеша capabilities). RBAC — как у
    /api/vision/test. R17: без bytes/base64/OCR-текстов.

    FIX2 (live 2.58.91): контекст ЧАТА — `X-Chat-Id` (его ставит `web/api()`
    при активном чате) или явный `chat_id`; без них — глобальный слой, как
    было. Раньше состояние всегда считалось глобальным и в чате с включённым
    per-chat override (`flags.vision_enabled`) отдавало
    `requested=false/vision_disabled`, хотя рантайм в этом чате работает
    (`resolve_effective_state(chat)`). Чужой чат (нет доступа) → глобальный
    слой, без утечки per-chat настроек (прецедент `/api/status`)."""
    cache: ConfigCache = get_cache(request)
    ctx = await _ctx_global_admin(cache, user)
    if not (ctx.is_global_admin or can_view_key_value(
            cache, user.id, "keys.vision_api_key")):
        raise HTTPException(status_code=403,
                            detail="нет прав на управление ключом vision")
    scope_chat = await _vision_chat_scope(cache, user, chat_id, x_chat_id)
    from services import lore_runtime, mca_vision
    return await mca_vision.runtime_snapshot(lore_runtime.get_lore_db(),
                                             chat_id=scope_chat)


# ── MCA-20 (ADR-1028-20 D11/D13/T-5116-прецедент): Temporal Factcheck —
# routes +2 в СУЩЕСТВУЮЩЕМ экране «Аналитика» (без нового раздела/маршрута
# UI). RBAC — прецедент /api/random/test (global admin; runs — аналитика
# кросс-чат). R17: список БЕЗ claim/verdict-текста (компакт), полный
# контент — только в деталях под global admin; JSON-колонки отдаются
# готовыми объектами.
def _factcheck_run_json(raw: dict, *, compact: bool) -> dict:
    """Строка v33 → API-объект; JSON-колонки парсятся на сервере."""
    import json as _json

    def _j(name):
        val = raw.get(name)
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        try:
            return _json.loads(val)
        except (TypeError, ValueError):
            return None

    payload = {
        "run_id": raw.get("run_id"),
        "created_at": raw.get("created_at"),
        "chat_id": raw.get("chat_id"),
        "trigger_tg_message_id": raw.get("trigger_tg_message_id"),
        "target_tg_message_id": raw.get("target_tg_message_id"),
        "target_revision": raw.get("target_revision"),
        "source_type": raw.get("source_type"),
        "origin_type": raw.get("origin_type"),
        "repost_received_at": raw.get("repost_received_at"),
        "original_published_at": raw.get("original_published_at"),
        "original_published_precision": raw.get(
            "original_published_precision"),
        "claim_period_from": raw.get("claim_period_from"),
        "claim_period_to": raw.get("claim_period_to"),
        "date_source": raw.get("date_source"),
        "requested_mode": raw.get("requested_mode"),
        "assessment_mode": raw.get("assessment_mode"),
        "analysis_as_of": raw.get("analysis_as_of"),
        "factual_verdict": raw.get("factual_verdict"),
        "temporal_status": raw.get("temporal_status"),
        "fallback_used": bool(raw.get("fallback_used")),
        "cache_hit": bool(raw.get("cache_hit")),
        "pipeline_version": raw.get("pipeline_version"),
        "tz_resolution_version": raw.get("tz_resolution_version"),
        "reason": raw.get("reason"),
    }
    if compact:
        return payload
    payload.update({
        "claim_text": raw.get("claim_text"),
        "claim_span": _j("claim_span"),
        "attribution": _j("attribution"),
        "date_timezone": raw.get("date_timezone"),
        "date_uncertainty": _j("date_uncertainty"),
        "related_asset_id": raw.get("related_asset_id"),
        "related_analysis_revision": raw.get("related_analysis_revision"),
        "evaluated_period": _j("evaluated_period"),
        "verdict_text": raw.get("verdict_text"),
        "verdict_uncertainty": _j("verdict_uncertainty"),
        "stage_trace": _j("stage_trace") or [],
        "revision": raw.get("revision"),
    })
    return payload


def _factcheck_evidence_json(rows: list[dict]) -> list[dict]:
    import json as _json

    def _j(val):
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        try:
            return _json.loads(val)
        except (TypeError, ValueError):
            return None

    return [{
        "claim_part": r.get("claim_part"),
        "url": r.get("url"),
        "support": r.get("support"),
        "source_ref": _j(r.get("source_ref")),
        "published_at": r.get("published_at"),
        "published_at_source": r.get("published_at_source"),
        "retrieved_at": r.get("retrieved_at"),
        "temporal_relevance": r.get("temporal_relevance"),
        "relation": r.get("relation"),
        "source_kind": r.get("source_kind"),
    } for r in rows]


@api_router.get("/factcheck/temporal/runs")
async def get_factcheck_temporal_runs(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    limit: int = Query(default=20, ge=1, le=100),
    chat_id: int | None = Query(default=None),
):
    """Последние runs временного фактчека (D14/T-5143): компактный список
    (без claim/verdict-текста — R17), фильтр по чату опционален. RBAC —
    global admin (прецедент /api/random/test)."""
    from services import mca_gates, lore_runtime
    cache: ConfigCache = get_cache(request)
    ctx = await _ctx_global_admin(cache, user)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403,
                            detail="нет прав на аналитику фактчека")
    db = lore_runtime.get_lore_db()
    if db is None:
        return {"runs": []}
    rows = await db.list_factcheck_runs(
        chat_id=chat_id,
        limit=min(int(limit), mca_gates.temporal_max_runs_list()))
    return {"runs": [_factcheck_run_json(r, compact=True) for r in rows]}


@api_router.get("/factcheck/temporal/runs/{run_id}")
async def get_factcheck_temporal_run(
    request: Request,
    run_id: str,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Детали run (D14/T-5143): timeline (original/repost/claim/as_of),
    «почему выбрана эта дата» (date_source+uncertainty+каскад), evidence-
    карточки, trace стадий, версии. RBAC — global admin."""
    from services import lore_runtime
    cache: ConfigCache = get_cache(request)
    ctx = await _ctx_global_admin(cache, user)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403,
                            detail="нет прав на аналитику фактчека")
    db = lore_runtime.get_lore_db()
    if db is None:
        raise HTTPException(status_code=404, detail="run не найден")
    raw = await db.get_factcheck_run(run_id)
    if raw is None:
        raise HTTPException(status_code=404, detail="run не найден")
    evidence = await db.get_factcheck_evidence(run_id)
    return {"run": _factcheck_run_json(raw, compact=False),
            "evidence": _factcheck_evidence_json(evidence)}


# ── Раунд 10.14 (F2 persona-storage-core, spec §5): /api/persona ────────────
# Scope через X-Chat-Id (None = global). RBAC: global — global admin или
# действие edit_persona; chat — действие edit_persona или секция content.
_PERSONA_TEXT_LIMIT = 8192
_PERSONA_TRAITS_LIMIT = 50


def _persona_has_edit_action(ctx) -> bool:
    """Роль с action `edit_persona` или global admin (spec §5, H2)."""
    if bool(getattr(ctx, "is_global_admin", False)):
        return True
    perms = getattr(ctx, "effective_permissions", None)
    if perms is None:
        perms = Permissions.from_dict({})
    return match_permission(perms, "edit_persona")


def _persona_can_edit(ctx, *, is_global: bool) -> bool:
    """Право правки персоны (spec §5): global — action edit_persona/global
    admin; chat — action edit_persona или секция content."""
    if _persona_has_edit_action(ctx):
        return True
    if is_global:
        return False
    perms = getattr(ctx, "effective_permissions", None)
    if perms is None:
        perms = Permissions.from_dict({})
    return match_permission(perms, "section.content")


def _persona_can_view(ctx, *, is_global: bool, chat_id: int | None) -> bool:
    """R10.14-1: согласовано с `_persona_can_edit` — роль с action
    `edit_persona`, которая может PUT global, должна и GET global (иначе
    глобальный экран «Личность» в UI недостижим). Chat-scope — доступ к
    чату; право правки chat подразумевает просмотр."""
    if bool(getattr(ctx, "is_global_admin", False)):
        return True
    if _persona_has_edit_action(ctx):
        return True
    if is_global:
        return False
    return access_srv.can_access_chat(ctx, chat_id)


def _persona_scope_payload(chat_id: int | None, persona) -> dict:
    val = {
        "name": persona.name,
        "biography": persona.biography,
        "system_prompt_overrides": persona.overrides,
        "is_aware_ai": persona.is_aware_ai,
    }
    return {
        "scope": "global" if chat_id is None else "chat",
        "chat_id": None if chat_id is None else chat_id,
        "values": val,
        "is_global": bool(persona.is_global),
        # H1 (F2 §5): optimistic-токен строки персоны для 409-протокола.
        "updated_at": getattr(persona, "updated_at", None),
    }


def _validate_persona_payload(payload: PersonaUpdate) -> None:
    for field in ("name", "biography", "system_prompt_overrides"):
        value = getattr(payload, field)
        if value is not None and len(str(value)) > _PERSONA_TEXT_LIMIT:
            raise HTTPException(status_code=422,
                                detail=f"{field} > {_PERSONA_TEXT_LIMIT}")


async def _persona_access(request: Request, user: WebAppUser,
                          x_chat_id: str | None):
    cache: ConfigCache = get_cache(request)
    chat_id = _chat_id_or_none(x_chat_id)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    return cache, chat_id, ctx


# F8/ADR-1024-5 D3 (round 10.24): категория статуса эволюции характера для UI
# (details остаётся в traits_reason — R17-safe код причины, spec §5.1).
_TRAITS_STATUS_CATEGORY = {
    "ok": "ok",
    "error": "error",
    "never": "never",
    "no_self_facts": "empty",
    "empty": "empty",
    "duplicate": "empty",
    "budget_skip": "skip",
    "persona_disabled": "skip",
    "master_off": "skip",
    "cooldown": "skip",
    "daily_limit": "skip",
}


async def _persona_traits_meta(out: dict, *, chat_id: int | None) -> None:
    """F8/ADR-1024-5 D3: явные traits_status/traits_reason/self_facts_count.

    Причина приоритетно выводится из числа self-фактов за окно (нет →
    `no_self_facts`) и мастер-гейта `persona_enabled`; иначе — код последнего
    прогона из persona_state. Fail-open: ошибка БД → нейтральные значения,
    API не падает (не 500). Значения — R17-safe коды, не тексты."""
    try:
        health = await bot_persona.get_persona_health()
    except Exception:
        health = {}
    raw = str((health or {}).get("last_trait_status") or "never")
    self_facts_count = None
    if chat_id is not None:
        try:
            from services import lore_runtime
            from services.dream_worker import _PERSONA_SELF_LOOKBACK_DAYS
            db = lore_runtime.get_lore_db()
        except Exception:
            db = None
            _PERSONA_SELF_LOOKBACK_DAYS = 30
        if db is not None:
            try:
                now = int(time.time())
                facts = await db.get_dream_candidates(
                    int(chat_id), now, origins=("bot_self_reply",),
                    since_ts=now - _PERSONA_SELF_LOOKBACK_DAYS * 86400,
                    limit=50)
                self_facts_count = len(facts or [])
            except Exception:
                self_facts_count = None
    if out.get("dynamic_traits"):
        status, reason = "ok", "ok"
    elif not out.get("persona_enabled", True):
        status, reason = "skip", "persona_disabled"
    elif self_facts_count == 0:
        status, reason = "empty", "no_self_facts"
    else:
        status = _TRAITS_STATUS_CATEGORY.get(raw, "empty")
        reason = raw
    out["traits_status"] = status
    out["traits_reason"] = reason
    out["self_facts_count"] = self_facts_count


@api_router.get("/persona")
async def get_persona(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """GET /api/persona: эффективная личность скоупа + dynamic_traits (F4).

    Contract (spec §5): scope, chat_id, values{...}, is_global,
    persona_enabled, dynamic_traits[{ts,text,source}]. Fail-open: PG down →
    пустые значения (200), промпт жив."""
    cache, chat_id, ctx = await _persona_access(request, user, x_chat_id)
    is_global = chat_id is None
    if not _persona_can_view(ctx, is_global=is_global, chat_id=chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к персоне")
    persona = await bot_persona.resolve_bot_persona(chat_id)
    out = _persona_scope_payload(chat_id, persona)
    # R10.14-3: per-chat override флага отражается в UI-индикаторе; global
    # (chat_id is None) — hot.get (спец §4.5 chat_params только для чатов).
    enabled_default = hot.get("flags.persona_enabled", settings.PERSONA_ENABLED)
    if chat_id is None:
        out["persona_enabled"] = bool(enabled_default)
    else:
        from services.chat_params import get_chat_param
        out["persona_enabled"] = bool(await get_chat_param(
            chat_id, "flags.persona_enabled", enabled_default))
    out["dynamic_traits"] = await bot_persona.get_traits(
        _PERSONA_TRAITS_LIMIT)
    # F8/ADR-1024-5 D3 (round 10.24): статус/причина эволюции характера для
    # Empty State UI (аддитивно, R16; fail-open внутри).
    await _persona_traits_meta(out, chat_id=chat_id)
    return out


# ── mca-18 (T-5085/T-5086, ADR-1028-18 D8/D10): SelfModel в существующем
# редакторе личности — effective/наследование/пояснения трёх переключателей,
# правила (правка/пауза/источники), компакт «Что сейчас формирует характер».
# БЕЗ нового раздела/маршрута (CA-18-8); fail-open; R17 (коды/числа/refs).

_SELF_MODEL_SWITCH_EXPLANATIONS = {
    "persona_enabled":
        "Использование характера и образа в речи. OFF — без характера, "
        "но авторство, тех-ограничения и разделение участников "
        "сохраняются (не отмена авторства).",
    "is_aware_ai":
        "Самопредставление персонажа: True — знает техническую природу и "
        "может назвать её уместно; False — держится образа, без "
        "тех-самоописания без повода. Режим роли, не онтология.",
    "bot_self_awareness_enabled":
        "Рефлексия собственных ответов: извлечение сути своих реплик в "
        "память. OFF останавливает производные наблюдения, не склеивая "
        "слова пользователя и бота.",
}


async def _self_model_payload(chat_id: int | None) -> dict:
    """Компакт SelfModel для UI (fail-open; R17: ID/коды/числа/refs)."""
    out: dict = {"enabled": False, "stages": (), "widget_id": None,
                 "explanations": _SELF_MODEL_SWITCH_EXPLANATIONS}
    try:
        from services import lore_runtime, mca_gates, mca_self_model as msm
        from services import mca_process_registry as registry
        out["enabled"] = bool(mca_gates.self_model_enabled())
        out["trait_rules_enabled"] = bool(mca_gates.trait_rules_enabled())
        out["legacy_parse_enabled"] = bool(
            mca_gates.legacy_traits_migration_enabled())
        proc = registry.get_process("self.model")
        if proc is not None:
            out["stages"] = tuple(proc.stages)
            out["widget_id"] = proc.widget_id
        if not out["enabled"]:
            return out
        db = lore_runtime.get_lore_db()
        if db is None:
            out["status"] = "no_db"
            return out
        snap = await msm.resolve_self_model(db, chat_id)
        frame = msm.select_behavior(snap)
        out["version"] = snap.version
        out["frame_version"] = frame.version
        out["stale"] = snap.stale
        out["fallback"] = snap.fallback
        out["rules_status"] = snap.rules_status
        out["self_presentation_mode"] = snap.self_presentation_mode
        out["identity"] = {
            "agent_id": snap.agent_id,
            "bot_user_id": snap.bot_user_id,
            "binding": snap.identity_binding,
        }
        out["switches"] = {
            "persona_enabled": {
                "value": snap.persona_enabled.value,
                "source": snap.persona_enabled.source,
                "error": snap.persona_enabled.error},
            "is_aware_ai": {
                "value": snap.is_aware_ai.value,
                "source": snap.is_aware_ai.source,
                "error": snap.is_aware_ai.error},
            "bot_self_awareness_enabled": {
                "value": snap.bot_self_awareness.value,
                "source": snap.bot_self_awareness.source,
                "error": snap.bot_self_awareness.error},
        }
        out["active_rules"] = [
            {"id": t.rule_id, "dimension": t.dimension,
             "version": t.version, "target_value": t.target_value,
             "scope": t.scope, "included": t.included,
             "excluded_reason": t.excluded_reason}
            for t in snap.traits]
        out["applied_now"] = [
            {"id": r.rule_id, "dimension": r.dimension,
             "version": r.version, "instruction": r.instruction}
            for r in frame.applied_rules]
        out["rejected_now"] = [
            {"id": r.rule_id, "dimension": r.dimension, "reason": r.reason}
            for r in frame.rejected_rules]
        out["state"] = ({"text": snap.state.text,
                         "valid_to": snap.state.valid_to}
                        if snap.state is not None else None)
        out["positions_count"] = len(snap.positions)
        out["composition"] = {
            "base": bool(snap.name or snap.biography or snap.traits),
            "dynamics": len(snap.traits),
            "mood": snap.state is not None,
            "versions": {"snapshot": snap.version,
                         "persona": snap.persona_version},
        }
    except Exception:
        logger.warning("[mca18] self-model payload failed", exc_info=True)
        out["status"] = "error"
    return out


@api_router.get("/persona/self-model")
async def get_persona_self_model(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """GET /api/persona/self-model: компакт «Что сейчас формирует характер»
    + effective/наследование трёх переключателей + правила. Fail-open 200."""
    cache, chat_id, ctx = await _persona_access(request, user, x_chat_id)
    is_global = chat_id is None
    if not _persona_can_view(ctx, is_global=is_global, chat_id=chat_id):
        raise HTTPException(status_code=403,
                            detail="нет доступа к персоне")
    return await _self_model_payload(chat_id)


async def _self_model_db():
    from services import lore_runtime
    return lore_runtime.get_lore_db()


@api_router.post("/persona/rules/{rule_id}/pause")
async def post_persona_rule_pause(
    rule_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """POST pause: правка владельца = основание (приостановка правила;
    не удаление истории). K1 OFF → 409 (честный disabled)."""
    cache, chat_id, ctx = await _persona_access(request, user, x_chat_id)
    if not _persona_can_edit(ctx, is_global=chat_id is None):
        raise HTTPException(status_code=403, detail="нет права edit_persona")
    from services import mca_gates, mca_self_model as msm
    if not mca_gates.self_model_enabled():
        raise HTTPException(status_code=409, detail="self_model disabled")
    db = await _self_model_db()
    if db is None:
        raise HTTPException(status_code=503, detail="локальная БД недоступна")
    ok = await msm.suspend_rule(db, rule_id, reason="owner_paused",
                                scope_chat_id=chat_id)
    if not ok:
        raise HTTPException(status_code=404, detail="правило не найдено")
    return {"ok": True, "id": int(rule_id), "status": "suspended"}


@api_router.post("/persona/rules/{rule_id}/resume")
async def post_persona_rule_resume(
    rule_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """POST resume: возобновление приостановленного правила владельцем."""
    cache, chat_id, ctx = await _persona_access(request, user, x_chat_id)
    if not _persona_can_edit(ctx, is_global=chat_id is None):
        raise HTTPException(status_code=403, detail="нет права edit_persona")
    from services import mca_gates, mca_self_model as msm
    if not mca_gates.self_model_enabled():
        raise HTTPException(status_code=409, detail="self_model disabled")
    db = await _self_model_db()
    if db is None:
        raise HTTPException(status_code=503, detail="локальная БД недоступна")
    ok = await msm.reactivate_rule(db, rule_id, reason="owner_resumed",
                                   scope_chat_id=chat_id)
    if not ok:
        raise HTTPException(status_code=404,
                            detail="правило не найдено/терминально")
    return {"ok": True, "id": int(rule_id), "status": "active"}


@api_router.get("/persona/rules/{rule_id}/sources")
async def get_persona_rule_sources(
    rule_id: int,
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """GET sources: основания правила → наблюдения (клик-цепочка
    «черта → основания → примеры → результат»; R17 — refs/числа)."""
    cache, chat_id, ctx = await _persona_access(request, user, x_chat_id)
    if not _persona_can_view(ctx, is_global=chat_id is None,
                             chat_id=chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к персоне")
    from services import mca_gates, mca_self_model as msm
    if not mca_gates.self_model_enabled():
        raise HTTPException(status_code=409, detail="self_model disabled")
    db = await _self_model_db()
    if db is None:
        raise HTTPException(status_code=503, detail="локальная БД недоступна")
    out = {"rule_id": int(rule_id), "observations": []}
    rule = None
    try:
        cursor = await db.db.execute(
            "SELECT dimension, status, version, source_observation_ids "
            "FROM mca_behavior_rules WHERE id = ?", (int(rule_id),))
        rule = await cursor.fetchone()
    except Exception:
        logger.warning("[mca18] rule sources lookup failed — fail-open",
                       exc_info=True)
        return out
    if rule is None:
        raise HTTPException(status_code=404, detail="правило не найдено")
    # M-1 (rework): основания — ТОЛЬКО наблюдения ЭТОГО правила
    # (`source_observation_ids`), а не последние 200 наблюдений всем.
    try:
        obs_ids = [int(x) for x in json.loads(
            rule["source_observation_ids"] or "[]")]
    except (TypeError, ValueError):
        obs_ids = []
    obs_ids = obs_ids[:200]
    out["dimension"] = rule["dimension"]
    out["status"] = rule["status"]
    out["version"] = rule["version"]
    out["source_observation_ids"] = obs_ids
    if not obs_ids:
        return out
    marks = ",".join("?" for _ in obs_ids)
    try:
        cursor = await db.db.execute(
            "SELECT id, dimension, subject_status, observed_at, chat_id, "
            "legacy_ref, source_refs, normalized FROM mca_trait_observations "
            f"WHERE id IN ({marks}) ORDER BY id DESC LIMIT 200",
            tuple(obs_ids))
        rows = await cursor.fetchall()
    except Exception:
        rows = []
    for row in (rows or []):
        try:
            refs = tuple(json.loads(row["source_refs"] or "[]"))
        except (TypeError, ValueError):
            refs = ()
        out["observations"].append({
            "id": row["id"], "dimension": row["dimension"],
            "subject_status": row["subject_status"],
            "observed_at": row["observed_at"], "chat_id": row["chat_id"],
            "legacy_ref": row["legacy_ref"], "source_refs": refs,
            "preview_len": len(str(row["normalized"] or "")),
        })
    return out


@api_router.put("/persona")
async def put_persona(
    request: Request,
    payload: PersonaUpdate,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """PUT /api/persona: partial UPSERT (chat — после ensure_scope_profile;
    global — singleton). reset:true → DELETE override чата. 403/409/422/503."""
    cache, chat_id, ctx = await _persona_access(request, user, x_chat_id)
    is_global = chat_id is None
    if not _persona_can_edit(ctx, is_global=is_global):
        raise HTTPException(status_code=403, detail="нет права edit_persona")
    _validate_persona_payload(payload)
    if is_global and payload.reset:
        raise HTTPException(status_code=422,
                            detail="reset доступен только для чата")
    if payload.reset:
        if not cache.pg_available:
            raise HTTPException(status_code=503,
                                detail="PostgreSQL недоступен (R6)")
        try:
            removed = await bot_persona.delete_persona(chat_id)
        except bot_persona.PersonaUnavailable:
            raise HTTPException(status_code=503,
                                detail="PostgreSQL недоступен (R6)")
        if not removed:
            raise HTTPException(status_code=404,
                                detail="override персоны отсутствует")
        return {"reset": True, "chat_id": chat_id, "removed": True}
    if not cache.pg_available:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    patch = payload.model_dump(exclude={"reset", "updated_at"},
                               exclude_none=True)
    try:
        persona = await bot_persona.save_persona(
            chat_id, patch, expected_updated_at=payload.updated_at)
    except bot_persona.PersonaConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at})
    except bot_persona.PersonaUnavailable:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    logger.info("[api] persona save | scope=%s | chat=%s | by=%s",
                "global" if is_global else "chat", chat_id, user.id)
    return _persona_scope_payload(chat_id, persona)


@api_router.delete("/persona")
async def delete_persona(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """DELETE /api/persona: удаление per-chat override (наследование global).
    422 без X-Chat-Id; 403 чужие права; 404 нет строки; 503 PG down."""
    cache, chat_id, ctx = await _persona_access(request, user, x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    if not _persona_can_edit(ctx, is_global=False):
        raise HTTPException(status_code=403, detail="нет права edit_persona")
    if not cache.pg_available:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    try:
        removed = await bot_persona.delete_persona(chat_id)
    except bot_persona.PersonaUnavailable:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    if not removed:
        raise HTTPException(status_code=404,
                            detail="override персоны отсутствует")
    logger.info("[api] persona reset | chat=%s | by=%s", chat_id, user.id)
    return {"reset": True, "chat_id": chat_id, "removed": True}


@api_router.get("/persona/health")
async def get_persona_health(
    user: Annotated[WebAppUser, Depends(requires_global_admin())],
):
    """GET /api/persona/health: метрики Личности (spec §5, F4). Global admin."""
    return await bot_persona.get_persona_health()


# ═══ EVOL-017: «История версий» промптов (журнал CONTRACT 1) ════════════════
# HTTP-слой над сервисным API ``services/prompt_release_policy.py``
# (list_versions / get_revision_source / diff_revisions / activate_revision).
# Журнал — единственный источник истории; таблицы напрямую не читаются.
#
# RBAC (два слоя, честно разделённых):
#   * ПОЛНАЯ проверка — здесь, в маршрутах (async, полный AccessCtx: гранты
#     chat_admins, hidden-ключи, per-key права);
#   * sync-хук сервиса (контракт: «HTTP-слой обязан установить») — fail-closed
#     backstop: пустой actor / «пустая» роль при активации отвергаются; он НЕ
#     заменяет маршруточную проверку (chat-грант sync-недоступен).

from services import prompt_registry as prompt_reg          # noqa: E402
from services import prompt_release_policy as prompt_policy  # noqa: E402


def _prompt_journal(cache: ConfigCache):
    """Стор журнала (публичный API сервиса); точка инъекции в тестах."""
    return prompt_policy.default_journal(cache)


def _prompt_perm_hook(actor: str, action: str, ctx: dict) -> bool:
    """RBAC-хук сервисного API (устанавливается ниже, при импорте).

    Правила: пустой actor — отказ; source/diff — блок-уровень проверяет
    маршрут после резолва ревизии; вне веб-процесса (hot-кэш не установлен)
    действует прежнее сервисное правило «непустой actor»; в веб-процессе
    активация требует существующей роли у telegram-id (не «пустой» user).
    Строковые не-int акторы (сервисные вызовы с actor="owner") не сужаются.
    """
    actor_s = str(actor or "").strip()
    if not actor_s:
        return False
    if action in ("prompt.get_revision_source", "prompt.diff_revisions"):
        return True
    cache = hot.get_config_cache()
    if cache is None:
        return True
    try:
        tg_id = int(actor_s)
    except ValueError:
        return True
    if action == "prompt.activate" and not cache.get_role(tg_id):
        return False
    return True


prompt_policy.set_permission_checker(_prompt_perm_hook)


class PromptActivateRequest(BaseModel):
    """Тело POST /api/prompts/{key}/activate: выбор СОХРАНЁННОЙ версии."""
    revision_id: str


def _prompt_block_or_404(prompt_key: str):
    """config-ключ (``prompts.*``) ИЛИ block_id → spec реестра."""
    spec = prompt_reg.by_pg_key(prompt_key) or prompt_reg.block(prompt_key)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail=f"промпт вне реестра версий: {prompt_key}")
    return spec


def _prompt_value_scope(spec):
    """Кодовые блоки без ``pg_key`` не имеют переключаемого значения (§1.5).
    История и сравнение для них доступны; включение — 422 с причиной."""
    if not spec.pg_key:
        raise HTTPException(
            status_code=422,
            detail=f"{spec.block_id}: нет переключаемого значения в базе — "
                   "включение из админки недоступно, просмотр истории доступен")


def _prompt_is_hidden(spec) -> bool:
    """Скрытость — свойство каталога параметров, не реестра промптов."""
    if not getattr(spec, "pg_key", None):
        return False
    cat = get_by_pg_key(spec.pg_key)
    return bool(cat is not None and getattr(cat, "hidden", False))


def _prompt_list_scope(spec, chat_id: int | None) -> str:
    if chat_id is not None:
        return "chat"
    if getattr(spec, "scope", "") == "code":
        return "code"
    return "global"


def _prompt_reason_text(result: dict) -> str:
    """Человеческая причина гейта сервиса. Активный указатель при отказе
    не меняется — это говорит и текст."""
    reason = str(result.get("reason") or "")
    if reason in ("ok", ""):
        if result.get("outcome") == "skipped_same":
            return "Сервер подтвердил: эта версия уже активна."
        return "Сервер подтвердил включение. Активная версия обновлена."
    if reason == "revision_retired":
        return ("Снята с регистрации (retired): включение заблокировано. "
                "Просмотр и сравнение доступны. Активная версия не изменилась.")
    if reason == "schema_incompatible":
        schema = result.get("schema_compat") or "неизвестная"
        return (f"Несовместима со схемой «{schema}» (schema_incompatible): "
                "включение заблокировано. Просмотр и сравнение доступны. "
                "Безопасный путь — новая заводская поставка или новая правка, "
                "совместимая с текущей схемой. Активная версия не изменилась.")
    if reason == "revision_unknown":
        return "Такой сохранённой версии нет. Активная версия не изменилась."
    if reason == "block_not_pg_managed":
        return ("Нет переключаемого значения в базе: включение недоступно. "
                "Просмотр истории доступен. Активная версия не изменилась.")
    if reason == "journal_unavailable":
        return "Журнал версий недоступен. Активная версия не изменилась."
    return f"Включение не выполнено ({reason}). Активная версия не изменилась."


def _prompt_hidden_admin(request: Request, user: WebAppUser) -> bool:
    """Глобальный админ (для hidden-ключей; зеркало GET /config)."""
    from web.api.deps import user_is_global_admin
    return user_is_global_admin(get_cache(request), user.id)


async def _prompt_require_view(request: Request, user: WebAppUser,
                               spec, chat_id: int | None) -> None:
    """Право ПРОСМОТРА истории: hidden → global admin; chat-скоуп →
    can_access_chat (изоляция чужих чатов); global — любая роль (значения
    промптов не секреты, зеркало GET /config)."""
    cache: ConfigCache = get_cache(request)
    if _prompt_is_hidden(spec) and not _prompt_hidden_admin(request, user):
        raise HTTPException(status_code=403,
                            detail="нет доступа к этому промпту")
    if chat_id is None:
        # Глобальная история — только админ (или явное право на этот ключ).
        # Обычная роль без права на промпт сюда не проходит.
        allowed = _prompt_hidden_admin(request, user)
        if spec.pg_key and can_edit_param(cache, user.id, spec.pg_key):
            allowed = True
        if not allowed:
            raise HTTPException(status_code=403,
                                detail="нет права на историю промпта")
        return
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if not access_srv.can_access_chat(ctx, chat_id):
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    # Изоляция чатов: глобальный модератор без гранта на ЭТОТ чат не читает
    # чужой override. Глобальный админ и владелец своих ЛС — могут.
    if (not ctx.is_global_admin and not ctx.is_dm_owner
            and ctx.role_chat not in ("local_admin", "moderator")):
        raise HTTPException(status_code=403, detail="нет доступа к чату")


async def _prompt_require_edit(request: Request, user: WebAppUser,
                               spec, chat_id: int | None) -> None:
    """Право АКТИВАЦИИ (= право записи значения, как POST /api/config):
    global — can_edit_param(cache, …); chat — доступ к чату + per-param
    матрица чата. Нет права → 403 ДО вызова сервиса."""
    cache: ConfigCache = get_cache(request)
    await _prompt_require_view(request, user, spec, chat_id)
    if chat_id is None:
        if not can_edit_param(cache, user.id, spec.pg_key):
            raise HTTPException(status_code=403,
                                detail=f"нет права на {spec.pg_key}")
        return
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    try:
        db_overrides = await access_srv.db_override_map(cache.pg)
    except Exception:
        db_overrides = {}
    try:
        chat_root = await chat_params.get_all_chat_params(chat_id)
        perm_overrides = dict(chat_root.get("perm_overrides") or {})
    except Exception:
        perm_overrides = {}
    matrix = access_srv.effective_matrix(
        spec.pg_key, db_overrides.get(spec.pg_key),
        perm_overrides.get(spec.pg_key))
    if not access_srv.can_edit_param(ctx, matrix):
        raise HTTPException(status_code=403,
                            detail=f"нет права на {spec.pg_key}")


def _prompt_scope_of(chat_id: int | None) -> str:
    return "chat" if chat_id is not None else "global"


def _prompt_journal_or_none(cache: ConfigCache):
    try:
        return _prompt_journal(cache)
    except Exception:                      # pragma: no cover — журнал не роняет
        return None


async def _prompt_record_saved_snapshots(cache: ConfigCache, items,
                                         *, scope: str,
                                         chat_id: int | None,
                                         actor) -> list[dict]:
    """После успешного POST /api/config: промпт реестра получает новый
    immutable-снимок. Значение уже записал существующий путь — журнал только
    фиксирует факт. Сбой журнала не откатывает сохранение. Пустой список,
    если журнала нет (тестовый пул не asyncpg) — ответ /api/config не меняется."""
    store = _prompt_journal_or_none(cache)
    if store is None:
        return []
    recorded: list[dict] = []
    for key, value in items:
        spec = prompt_reg.by_pg_key(str(key))
        if spec is None or not spec.pg_key or not isinstance(value, str):
            continue
        try:
            result = await prompt_policy.record_manual_activation(
                spec.block_id, value, scope=scope, chat_id=chat_id,
                actor=str(actor or ""), reason="owner_edit",
                kind="manual_edit", cache=cache, store=store)
        except Exception:
            logger.warning("[api] prompt snapshot not recorded | key=%s",
                           key, exc_info=True)
            continue
        if result.get("recorded"):
            recorded.append({
                "key": spec.pg_key,
                "revision_id": result.get("revision_id") or "",
                "sha256_12": result.get("sha256_12") or "",
            })
    return recorded


async def _prompt_require_revision_view(request: Request, user: WebAppUser,
                                        cache: ConfigCache, store,
                                        revision_id: str) -> None:
    """Резолв ревизии → блок/(scope, chat) и право просмотра её текста."""
    if store is None:
        raise HTTPException(status_code=503,
                            detail="журнал версий недоступен")
    try:
        row = await store.get_revision(revision_id)
    except Exception:                      # pragma: no cover — PG-сбой
        raise HTTPException(status_code=503,
                            detail="журнал версий недоступен")
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"ревизия не найдена: {revision_id}")
    spec = prompt_reg.block(row.block_id)
    if spec is None:
        raise HTTPException(status_code=404,
                            detail=f"блок вне реестра: {row.block_id}")
    # Chat-ревизия — данные чата: чужой scope не отдаём (изоляция).
    chat_id = row.chat_id if row.scope == "chat" else None
    await _prompt_require_view(request, user, spec, chat_id)


@api_router.get("/prompts/revisions/diff")
async def get_prompt_revision_diff(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    a: str = Query(..., description="revision_id «было»"),
    b: str = Query(..., description="revision_id «стало»"),
):
    """Сравнение двух сохранённых ревизий (сервисный difflib, unified).

    RBAC: обе ревизии резолвятся в блок; просмотр — по правам на блок
    (chat-ревизия отдаётся только с доступом к её чату). 404 — неизвестная
    ревизия; 503 — журнал недоступен."""
    cache: ConfigCache = get_cache(request)
    store = _prompt_journal_or_none(cache)
    for rev_id in (a, b):
        await _prompt_require_revision_view(request, user, cache, store,
                                            rev_id)
    try:
        result = await prompt_policy.diff_revisions(a, b, cache=cache,
                                                    store=store,
                                                    actor=str(user.id))
    except prompt_policy.PromptPermissionError:
        raise HTTPException(status_code=403, detail="permission denied")
    if not result.get("known"):
        reason = result.get("reason") or "unknown"
        if reason == "journal_unavailable":
            raise HTTPException(status_code=503,
                                detail="журнал версий недоступен")
        raise HTTPException(status_code=404,
                            detail=f"ревизия не найдена: {reason}")
    logger.info("[api] prompt diff | a=%s | b=%s | by=%s", a[:20], b[:20],
                user.id)
    return result


@api_router.get("/prompts/revisions/{revision_id}/source")
async def get_prompt_revision_source(
    request: Request,
    revision_id: str,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Полный текст сохранённой ревизии (просмотр, без права активации).

    RBAC как у diff: резолв ревизии → блок + (scope, chat) → право просмотра;
    chat-ревизия чужого чата не отдаётся."""
    cache: ConfigCache = get_cache(request)
    store = _prompt_journal_or_none(cache)
    await _prompt_require_revision_view(request, user, cache, store,
                                        revision_id)
    try:
        data = await prompt_policy.get_revision_source(
            revision_id, cache=cache, store=store, actor=str(user.id))
    except prompt_policy.PromptPermissionError:
        raise HTTPException(status_code=403, detail="permission denied")
    if not data.get("known"):
        if data.get("reason") == "journal_unavailable":
            raise HTTPException(status_code=503,
                                detail="журнал версий недоступен")
        raise HTTPException(status_code=404, detail="ревизия не найдена")
    return data


async def _prompt_can_activate(request: Request, user: WebAppUser,
                               spec, chat_id: int | None) -> bool:
    """Тихая проверка права активации (для бейджа UI; 403 здесь не бросаем).
    Полная проверка всё равно выполняется в POST-маршруте."""
    try:
        await _prompt_require_edit(request, user, spec, chat_id)
    except HTTPException:
        return False
    return True


_PROMPT_FAMILY_TITLES = {
    "internal": "Внутренние инструкции",
    "message": "Сообщения",
    "style": "Стиль",
    "summary": "Саммаризация",
    "direct": "Прямой чат",
    "humor": "Юмор",
    "factcheck": "Фактчек",
    "memory": "Память",
    "response": "Ответ",
    "genre": "Жанр",
    "identity": "Личность",
    "image": "Изображения",
    "search": "Поиск",
    "youtube": "YouTube",
    "core": "Ядро",
    "experience": "Опыт",
    "checkup": "Проверка",
    "web": "Веб",
    "initiative": "Инициатива",
}


@api_router.get("/prompts/catalog")
async def get_prompt_catalog(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
):
    """Каталог всех зарегистрированных промптов (EVOL-017), без текстов.

    Только глобальный админ. Группировка по подсистемам (family). Тела,
    секреты и акторы сюда не входят — история открывается отдельным
    запросом по block_id / pg_key."""
    if not _prompt_hidden_admin(request, user):
        raise HTTPException(status_code=403,
                            detail="только для глобального админа")
    grouped: dict[str, list] = {}
    for spec in prompt_reg.all_blocks():
        purpose = str(spec.purpose or "").strip()
        if len(purpose) > 180:
            purpose = purpose[:177] + "…"
        grouped.setdefault(spec.family or "other", []).append({
            "block_id": spec.block_id,
            "pg_key": spec.pg_key or "",
            "purpose": purpose,
            "ui": spec.ui,
            "scope": spec.scope,
            "manageable": bool(spec.pg_key) and not _prompt_is_hidden(spec),
            "factory_revision": prompt_reg.factory_revision(spec.block_id),
        })
    families = []
    for fam in sorted(grouped):
        items = sorted(grouped[fam], key=lambda row: row["block_id"])
        families.append({
            "id": fam,
            "title": _PROMPT_FAMILY_TITLES.get(fam, fam),
            "prompts": items,
        })
    return {"families": families, "count": sum(len(f["prompts"])
                                               for f in families)}


@api_router.get("/prompts/{prompt_key}/versions")
async def get_prompt_versions(
    request: Request,
    prompt_key: str,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """«История версий» промпта (EVOL-017): активная ревизия, заводская,
    хронология ревизий/активаций. X-Chat-Id → chat-скоуп (изоляция по
    can_access_chat); без него — global. 404 — ключ вне реестра. Тексты по
    умолчанию не отдаются (только /source и /diff)."""
    spec = _prompt_block_or_404(prompt_key)
    chat_id = _chat_id_or_none(x_chat_id)
    await _prompt_require_view(request, user, spec, chat_id)
    cache: ConfigCache = get_cache(request)
    store = _prompt_journal_or_none(cache)
    try:
        out = await prompt_policy.list_versions(
            spec.block_id, scope=_prompt_list_scope(spec, chat_id),
            chat_id=chat_id, cache=cache, store=store, actor=str(user.id))
    except prompt_policy.PromptPermissionError:
        raise HTTPException(status_code=403, detail="permission denied")
    if not out.get("known"):
        raise HTTPException(status_code=404,
                            detail=f"промпт вне реестра версий: {prompt_key}")
    # Аддитивные поля UI-слоя (R16): scope/права/доступность журнала —
    # чтобы фронт честно показывал и состояние, и допустимые действия.
    out["prompt_key"] = spec.pg_key or ""
    out["block_id"] = spec.block_id
    out["scope"] = _prompt_list_scope(spec, chat_id)
    out["chat_id"] = chat_id
    out["journal_available"] = store is not None
    out["hidden"] = _prompt_is_hidden(spec)
    out["manageable"] = bool(spec.pg_key) and not _prompt_is_hidden(spec)
    # Сервис не отдаёт отдельный таймер активации (ActivationRow без
    # created_at). UI показывает время записи версии и не выдумывает часы.
    out["activation_time_available"] = False
    out["supported_schema_compat"] = sorted(
        prompt_policy.SUPPORTED_SCHEMA_COMPAT)
    out["can_activate"] = bool(out["manageable"]) and \
        await _prompt_can_activate(request, user, spec, chat_id)
    return out


@api_router.post("/prompts/{prompt_key}/activate")
async def post_prompt_activate(
    request: Request,
    prompt_key: str,
    payload: PromptActivateRequest,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """Активировать СОХРАНЁННУЮ версию (откат/вперёд; история не удаляется).

    Права — уровень записи значения (как POST /api/config: global —
    can_edit_param; chat — доступ + матрица чата). Гейты сервиса
    (retired/schema_compat) отдаются как 200 applied=false c причиной —
    UI показывает конкретную причину; активный указатель не меняется.
    503 — журнал/PG недоступен; 403 — нет права; 422 — пустой revision_id."""
    if not str(payload.revision_id or "").strip():
        raise HTTPException(status_code=422, detail="revision_id обязателен")
    spec = _prompt_block_or_404(prompt_key)
    _prompt_value_scope(spec)
    if _prompt_is_hidden(spec):
        raise HTTPException(
            status_code=422,
            detail=f"{spec.pg_key}: значение задаётся в соответствующем "
                   "разделе Mini App, а не вручную")
    chat_id = _chat_id_or_none(x_chat_id)
    await _prompt_require_edit(request, user, spec, chat_id)
    cache: ConfigCache = get_cache(request)
    if not cache.pg_available:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    store = _prompt_journal_or_none(cache)
    if store is None:
        raise HTTPException(status_code=503,
                            detail="журнал версий недоступен")
    try:
        result = await prompt_policy.activate_revision(
            spec.block_id, payload.revision_id,
            scope=_prompt_scope_of(chat_id), chat_id=chat_id,
            actor=str(user.id), cache=cache, store=store)
    except prompt_policy.PromptPermissionError:
        raise HTTPException(status_code=403, detail="permission denied")
    except prompt_policy.PromptJournalError:
        raise HTTPException(status_code=503,
                            detail="журнал версий недоступен (R6)")
    if result.get("reason") == "journal_unavailable":
        raise HTTPException(status_code=503,
                            detail="журнал версий недоступен")
    logger.info("[api] prompt revision activate | block=%s | scope=%s | "
                "chat=%s | rev=%s | applied=%s | outcome=%s | kind=%s | "
                "by=%s", spec.block_id, result.get("scope"),
                result.get("chat_id"),
                str(payload.revision_id)[:20], result.get("applied"),
                result.get("outcome"), result.get("activation_kind"),
                user.id)
    result = dict(result)
    result["reason_text"] = _prompt_reason_text(result)
    result["active_unchanged"] = not bool(result.get("applied"))
    return result


# ═══ EVOL-019/020/021/014 (Wave 4 UI wiring) ═══════════════════════════════
# HTTP-слой над УЖЕ принятыми сервисами; новых store/агрегаторов и второй
# конфигурации нет:
#   * EVOL-019 — `POST /api/vision/recognition-check` поверх
#     `mca_vision.recognition_check()` (структурированные состояния вместо
#     одного «ок» по HTTP 200; проверка делает ОДИН реальный запрос — платный
#     вызов, о чём ответ говорит явно через `paid_call`/`budget_note`);
#   * EVOL-020 — `GET /api/experience/pipeline` поверх
#     `experience_diagnostics` (8 стадий, реальные отметки времени, окна
#     24ч/7д/30д, причины пропусков, классификатор состояния);
#   * EVOL-021 — `GET /api/episodes/feed|recovery|{episode_id}` поверх
#     `episode_diagnostics` (смысловые эпизоды + группа восстановления +
#     карточка РОВНО выбранного эпизода разрешённого чата);
#   * EVOL-014 — `GET/POST /api/initiative/meme-settings` поверх
#     `meme_initiative` (настройки мемов, квота, аналитика, шаблон промпта).
# R17: ни ключ Vision, ни base_url, ни сырое тело провайдера в ответ не
# попадают — только классы/коды/длины; образец содержимого ограничен сервисом.

# ── EVOL-019: «Проверить распознавание» ────────────────────────────────────
# Отдельный rate-limit от `/api/vision/test`: это ДРУГОЕ действие (не
# «проверить подключение»), и общий счётчик позволил бы обойти ограничение
# чередованием кнопок. Политика та же (10 с, платный вызов).
_VISION_RECOGNITION_MIN_INTERVAL = 10.0
_VISION_RECOGNITION_LAST: dict[int, float] = {}
_VISION_RECOGNITION_TTL = 3600.0


def reset_vision_recognition_rate_limit() -> None:
    """Тестовая точка сброса серверного rate-limit проверки распознавания."""
    _VISION_RECOGNITION_LAST.clear()


def _prune_vision_recognition_last(now: float) -> None:
    if len(_VISION_RECOGNITION_LAST) < 256:
        return
    stale = [k for k, ts in _VISION_RECOGNITION_LAST.items()
             if now - ts > _VISION_RECOGNITION_TTL]
    for k in stale:
        _VISION_RECOGNITION_LAST.pop(k, None)


@api_router.post("/vision/recognition-check")
async def post_vision_recognition_check(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: int | None = Query(default=None),
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """EVOL-019: «Проверить распознавание» — структурированный результат.

    В отличие от `POST /api/vision/test` («Проверить подключение»), проверяет
    ВЕСЬ путь: конфигурация → доступность провайдера → принятие медиа →
    завершённость распознавания → полученное содержимое → производная
    готовность pipeline. HTTP 200 с не-JSON/неверной схемой/пустым
    содержимым НЕ считается работающим распознаванием — ответ приходит с
    `state` (`schema_invalid`/`content_empty`/...) и `terminal_reason`.

    Права — как у `/api/vision/test` (global admin ИЛИ право на
    `keys.vision_api_key`); 429 — повтор чаще 10 секунд; 503 — проверка
    недоступна (сервис бросил исключение). Ответ всегда 200 с честными
    полями: `config_ok`/`provider_reachable`/`media_accepted`/
    `recognition_completed`/`content_received`/`duration_ms`/`model`/
    `timestamp`/`terminal_reason`/`pipeline`/`media_coverage`/`paid_call`.
    """
    cache: ConfigCache = get_cache(request)
    ctx = await _ctx_global_admin(cache, user)
    if not (ctx.is_global_admin or can_view_key_value(
            cache, user.id, "keys.vision_api_key")):
        raise HTTPException(status_code=403,
                            detail="нет прав на управление ключом vision")
    now = time.monotonic()
    _prune_vision_recognition_last(now)
    if now - _VISION_RECOGNITION_LAST.get(user.id, 0.0) \
            < _VISION_RECOGNITION_MIN_INTERVAL:
        raise HTTPException(status_code=429,
                            detail="повтор проверки чаще 10 секунд")
    _VISION_RECOGNITION_LAST[user.id] = now
    scope_chat = await _vision_chat_scope(cache, user, chat_id, x_chat_id)
    from services import mca_vision
    try:
        result = await mca_vision.recognition_check(chat_id=scope_chat)
    except Exception:
        logger.warning("[api] vision recognition check failed", exc_info=True)
        raise HTTPException(status_code=503,
                            detail="проверка распознавания недоступна")
    out = dict(result)
    # Чат-скоуп, в котором считались модуль/типы медиа: без него UI не может
    # отличить «модуль выключен глобально» от «выключен в этом чате».
    out["chat_id"] = scope_chat
    return out


# ── EVOL-020: цепочка опыта (8 стадий) ─────────────────────────────────────

@api_router.get("/experience/pipeline")
async def get_experience_pipeline(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    chat_id: int | None = Query(default=None),
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """EVOL-020: состояние цепочки опыта по ФАКТИЧЕСКИМ отметкам.

    Источник — `services.experience_diagnostics` (те же таблицы/события, что
    у витрины «Опыт»): 8 стадий (`order`), счётчики за 24ч/7д/30д, реальные
    `last_run_at`/`last_success_at`, причины пропусков, классификатор
    (`working`/`idle`/`broken`/`disabled`/`stale`/`never_run`) и словарь
    определений. `reason_details` — причины по стадиям за 7 дней (типизированные
    события; пусто — честно пусто). Ничего не пишет, внешних вызовов нет.

    RBAC — прецедент `/api/oversight/experience/funnel`: global admin.
    `chat_id`/`X-Chat-Id` сужает срез до РАЗРЕШЁННОГО чата; чужой чат → None
    (глобальный срез, без утечки per-chat данных).
    """
    cache: ConfigCache = get_cache(request)
    ctx = await _ctx_global_admin(cache, user)
    if not ctx.is_global_admin:
        raise HTTPException(status_code=403,
                            detail="нет прав на диагностику цепочки опыта")
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    if db is None:
        raise HTTPException(status_code=503, detail="локальная БД недоступна")
    scope_chat = await _scoped_chat_or_none(cache, user, chat_id, x_chat_id)
    from services import experience_diagnostics as exp_diag
    snapshot = await exp_diag.experience_pipeline_snapshot(db,
                                                          chat_id=scope_chat)
    try:
        reasons = await exp_diag.experience_pipeline_reasons(
            db, chat_id=scope_chat)
    except Exception:
        logger.warning("[api] experience reasons failed — fail-open",
                       exc_info=True)
        reasons = {"items": [], "window_seconds": None}
    snapshot["reason_details"] = reasons.get("items") or []
    snapshot["reasons_window_seconds"] = reasons.get("window_seconds")
    return snapshot


# ── EVOL-021: смысловые эпизоды (лента/восстановление/карточка) ─────────────

async def _require_chat_access(request: Request, user: WebAppUser,
                               chat_id: int) -> None:
    """Чат-скоуп (TH-1): доступ к чату проверяется ДО чтения; чужой → 403
    без раскрытия существования (прецедент `web/api/stories.py`)."""
    cache = get_cache(request)
    try:
        ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    except Exception:
        raise HTTPException(status_code=403,
                            detail="permission denied") from None
    if not access_srv.can_access_chat(ctx, chat_id):
        raise HTTPException(status_code=403, detail="permission denied")


def _episodes_no_chat() -> dict:
    """Честное «выберите чат»: эпизоды живут в конкретном чате."""
    return {"enabled": True, "state": "no_chat", "chat_id": None,
            "generated_at": int(time.time()), "items": [],
            "requires_recovery": None, "last_build": None,
            "message": "Выберите чат — эпизоды показываются для выбранного чата"}


def _episodes_db_unavailable() -> dict:
    return {"enabled": True, "state": "unavailable", "chat_id": None,
            "generated_at": int(time.time()), "items": [],
            "requires_recovery": None, "last_build": None,
            "message": "Эпизоды недоступны: локальная БД не открыта"}


@api_router.get("/episodes/feed")
async def get_episodes_feed(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """EVOL-021: лента смысловых эпизодов разрешённого чата.

    В ленту попадают ТОЛЬКО эпизоды с восстановленным описанием (пустые
    технические записи не выдаются за «новые истории»); незавершённые
    сгруппированы в `requires_recovery` с реальной причиной и числом.
    `last_build` — последняя сборка из существующего прогресса витрины.
    Пустой архив → честный `state=empty`, без выдуманных заголовков.
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return _episodes_no_chat()
    await _require_chat_access(request, user, chat_id)
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    if db is None:
        return _episodes_db_unavailable()
    from services import episode_diagnostics as ed
    return await ed.episode_feed(db, chat_id, limit=limit)


@api_router.get("/episodes/recovery")
async def get_episodes_recovery(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """EVOL-021: группа «Требуют восстановления» (свёрнутая по умолчанию).

    Каждый элемент несёт реальную причину (`no_source_messages`/
    `no_substantive_text`/`summary_not_built`/`title_stub_only`) и статус
    (`unrecoverable`/`pending_rebuild`). Архив не удаляется, новые сюжеты
    не генерируются.
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        return {"enabled": True, "state": "no_chat", "chat_id": None,
                "generated_at": int(time.time()), "count": 0, "items": [],
                "by_reason": [], "truncated": False,
                "group": "requires_recovery",
                "group_label": "Требуют восстановления",
                "message": "Выберите чат — группа считается для выбранного чата"}
    await _require_chat_access(request, user, chat_id)
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    if db is None:
        return {"enabled": True, "state": "unavailable", "chat_id": chat_id,
                "generated_at": int(time.time()), "count": 0, "items": [],
                "by_reason": [], "truncated": False,
                "group": "requires_recovery",
                "group_label": "Требуют восстановления",
                "message": "Эпизоды недоступны: локальная БД не открыта"}
    from services import episode_diagnostics as ed
    return await ed.recovery_group(db, chat_id, limit=limit)


@api_router.get("/episodes/{episode_id}")
async def get_episode_card(
    request: Request,
    episode_id: str,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """EVOL-021: карточка РОВНО выбранного эпизода (не «общий каталог»).

    Изоляция чатов проверяется ДО чтения: эпизод чужого чата и
    несуществующий одинаково дают 404 без раскрытия существования
    (сервис тоже возвращает None при чужом `chat_id`).
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    await _require_chat_access(request, user, chat_id)
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    if db is None:
        raise HTTPException(status_code=503, detail="локальная БД недоступна")
    from services import episode_diagnostics as ed
    card = await ed.episode_card(db, chat_id, str(episode_id))
    if card is None:
        raise HTTPException(status_code=404, detail="эпизод не найден")
    return card


# ── EVOL-014: настройки мемов внутри модуля «Инициатива» ───────────────────
# Мастер модуля (`flags.initiative_enabled`) НЕ дублируется: мемы имеют свой
# ключ (`flags.meme_initiative_enabled`), отдельный от текстовой инициативы.
# Запись идёт тем же per-chat override-путём, что и остальные настройки чата
# (POST /api/config не подходит: `initiative.meme_*` — не ключи каталога).
# Тихие часы: `HH:MM-HH:MM` (пусто = не заданы). Часы строго 00–23, минуты
# 00–59 — «25:00-26:00» не время суток и отклоняется (422), а не сохраняется.
_MEME_QUIET_HOURS_RE = (
    r"^(?:(?:[01]?\d|2[0-3]):[0-5]\d-(?:[01]?\d|2[0-3]):[0-5]\d)?$"
)


class MemeSettingsUpdate(BaseModel):
    """Частичная правка настроек мемов (все поля опциональны).

    Границы совпадают с валидацией сервиса (`meme_initiative.load_settings`):
    квота `0` = выключено, окно ≥ 1, вероятность 0..1, тихие часы
    `HH:MM-HH:MM` (пусто = не заданы). `summarizer_model` пустой = наследовать
    общий суммаризатор. Мастер модуля здесь отсутствует намеренно.
    """
    enabled: bool | None = None
    window_messages: int | None = Field(default=None, ge=1, le=5000)
    daily_limit: int | None = Field(default=None, ge=0, le=50)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=604800)
    min_messages: int | None = Field(default=None, ge=0, le=500)
    trigger_probability: float | None = Field(default=None, ge=0, le=1)
    summarizer_model: str | None = Field(default=None, max_length=120)
    quiet_hours: str | None = Field(default=None, max_length=11)
    length_limit: int | None = Field(default=None, ge=0, le=8000)
    length_override: int | None = Field(default=None, ge=0, le=8000)
    updated_at: str | None = None


def _meme_payload_field_map() -> dict[str, str]:
    """Поле API → ключ параметра чата (единый источник соответствия)."""
    from services import meme_initiative as mi
    return {
        "enabled": mi.KEY_ENABLED,
        "window_messages": mi.KEY_WINDOW,
        "daily_limit": mi.KEY_DAILY_LIMIT,
        "cooldown_seconds": mi.KEY_COOLDOWN,
        "min_messages": mi.KEY_MIN_MESSAGES,
        "trigger_probability": mi.KEY_PROBABILITY,
        "summarizer_model": mi.KEY_SUMMARIZER_MODEL,
        "quiet_hours": mi.KEY_QUIET_HOURS,
        "length_limit": mi.KEY_LENGTH_ADMIN,
        "length_override": mi.KEY_LENGTH_OVERRIDE,
    }


async def _meme_settings_payload(chat_id: int, db) -> dict:
    """Полный срез настроек мемов для витрины модуля «Инициатива».

    Всё читается существующими функциями сервиса; витрина не считает
    собственных квот/счётчиков. `availability.reason` — конкретная причина
    недоступности (инициатива выключена / мемы выключены / image-провайдер не
    настроен / схема квоты отсутствует), а не общее «не работает».
    """
    from services import meme_initiative as mi
    cfg = await mi.load_settings(chat_id)
    ledger = mi.open_ledger(db) if db is not None else None
    day = mi.day_window(chat_id)
    quota = mi.quota_view(ledger, chat_id=chat_id, day=day,
                          limit=cfg.daily_limit)
    analytics = mi.analytics_snapshot(ledger, chat_id=chat_id, day=day,
                                      limit=cfg.daily_limit)
    availability = await mi.availability(chat_id, settings=cfg, ledger=ledger)
    try:
        model_chars = await mi.model_prompt_chars()
    except Exception:
        model_chars = None
    length = mi.resolve_length_limit(
        model_chars=model_chars, admin=cfg.length_admin,
        explicit=cfg.length_override, prefix=mi.MEME_IMAGE_PROMPT)
    prompts: dict[str, Any] = {}
    for name, block_id in (("image", mi.IMAGE_PROMPT_BLOCK_ID),
                           ("summary", mi.SUMMARY_PROMPT_BLOCK_ID)):
        try:
            prompts[name] = mi.active_prompt_view(block_id)
        except Exception:
            logger.debug("[api] meme prompt view failed | block=%s", block_id,
                         exc_info=True)
            prompts[name] = {"block_id": block_id, "text": "",
                             "source": "unavailable",
                             "differs_from_factory": False,
                             "factory_revision": "", "revision": 0}
    skip_reasons = dict(analytics.get("skip_reasons") or {})
    return {
        "chat_id": int(chat_id),
        "generated_at": int(time.time()),
        "settings": cfg.as_dict(),
        "availability": availability,
        "quota": quota,
        "analytics": analytics,
        "day": {"bucket": day.bucket,
                "timezone_name": day.timezone_name,
                "timezone_source": day.timezone_source,
                "next_reset": day.next_reset_iso},
        "length_limit": length.as_dict(),
        "image_prefix": mi.MEME_IMAGE_PROMPT,
        "prompts": prompts,
        "delivery": {
            "output_kind": mi.OUTPUT_KIND,
            "blocks_text_initiative": mi.blocks_text_initiative(),
            "publish_blocked_count": int(skip_reasons.get(mi.SKIP_PUBLISH, 0)),
            "skip_reasons": skip_reasons,
            "stages": list(mi.STAGES),
        },
        "schema_present": bool(ledger is not None and ledger.table_present()),
        "defaults": {
            "enabled": mi.DEFAULT_ENABLED,
            "window_messages": mi.DEFAULT_WINDOW_MESSAGES,
            "daily_limit": mi.DEFAULT_DAILY_LIMIT,
            "cooldown_seconds": mi.DEFAULT_COOLDOWN_SECONDS,
            "min_messages": mi.DEFAULT_MIN_MESSAGES,
            "trigger_probability": mi.DEFAULT_TRIGGER_PROBABILITY,
        },
        "master_key": "flags.initiative_enabled",
        "own_key": mi.KEY_ENABLED,
    }


@api_router.get("/initiative/meme-settings")
async def get_meme_settings(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """EVOL-014: настройки мемов + квота дня + аналитика по стадиям.

    Права — доступ к чату (чтение). Без `X-Chat-Id` → 422: мемы включаются
    и квотируются ПО ЧАТУ, глобального «включено для всех» здесь нет.
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    await _require_chat_access(request, user, chat_id)
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    return await _meme_settings_payload(chat_id, db)


@api_router.post("/initiative/meme-settings")
async def post_meme_settings(
    request: Request,
    payload: MemeSettingsUpdate,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
):
    """EVOL-014: правка настроек мемов (per-chat override).

    Гейт прав — прецедент `DELETE /api/config/chat/{key}`: в ЛС — владелец,
    в группе — global/local admin. Мастер модуля «Инициатива» НЕ меняется
    (ключ `flags.initiative_enabled` в этом теле отсутствует). Ответ — свежий
    срез (тот же, что GET), чтобы витрина показывала фактическое состояние,
    а не эхо запроса. 409 — оптимистичный конфликт, 422 — недопустимое
    значение, 503 — PostgreSQL недоступен.
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    cache: ConfigCache = get_cache(request)
    ctx = await roles_srv.access_for(user.id, chat_id, cache=cache)
    if chat_params.is_dm_scope(chat_id):
        allowed = bool(ctx.is_dm_owner)
    else:
        allowed = bool(ctx.is_global_admin or ctx.is_local_admin)
    if not allowed:
        raise HTTPException(status_code=403, detail="нет доступа к чату")
    if not cache.pg_available:
        raise HTTPException(status_code=503,
                            detail="PostgreSQL недоступен (R6)")
    if payload.quiet_hours is not None:
        import re as _re
        if not _re.match(_MEME_QUIET_HOURS_RE, str(payload.quiet_hours)):
            raise HTTPException(
                status_code=422,
                detail="тихие часы: формат HH:MM-HH:MM или пусто")
    field_map = _meme_payload_field_map()
    patch: dict[str, Any] = {}
    for field, key in field_map.items():
        value = getattr(payload, field)
        if value is None:
            continue
        if field in ("summarizer_model", "quiet_hours"):
            patch[key] = str(value).strip()
        elif field == "enabled":
            patch[key] = bool(value)
        elif field in ("length_limit", "length_override"):
            # 0 = «не задано» (снять ограничение), а не «нулевой потолок».
            patch[key] = int(value) if int(value) > 0 else None
        else:
            patch[key] = value
    if not patch:
        raise HTTPException(status_code=422, detail="нет изменений")
    if ctx.is_dm_owner:
        await chat_params.ensure_scope_profile(chat_id, dm=True, pg=cache.pg)
    root = await chat_params.get_all_chat_params(chat_id, pg=cache.pg)
    overrides = dict(root.get("overrides") or {})
    overrides.update(patch)
    meta = dict(root.get("meta") or {})
    meta["updated_by"] = user.id
    try:
        await _write_chat_overrides_with_retry(
            chat_id, overrides, meta, cache,
            expected_updated_at=payload.updated_at)
    except chat_params.ChatParamsConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict",
                    "current_updated_at": exc.current_updated_at,
                    "conflicting": getattr(exc, "conflicting", []) or [],
                    "applied": []})
    logger.info("[api] meme settings updated | chat=%s | keys=%s | by=%s",
                chat_id, sorted(patch), user.id)
    from services import lore_runtime
    db = lore_runtime.get_lore_db()
    return await _meme_settings_payload(chat_id, db)
