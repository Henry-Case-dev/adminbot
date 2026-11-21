"""MOD-ACL-UX-01 M4C C2 — read-only read-model «Проверить доступ»/effective.

Один резолвер поверх **существующих** примитивов (второго ACL нет):
``roles.access_for(strict=True)``, ``access.can_access_chat``,
``access.effective_matrix/can_view_param/can_edit_param/eligible_type``,
``permissions.requires_permission``, ``chat_params.read_chat_params_strict``,
``access.param_permissions_snapshot``.

Ничего не пишет: ни БД, ни runtime-кэши (`param_permissions`, chat-кэш).
Web-импортов нет — HTTP-маппинг и best-effort display_name делает
`web/api/access.py`.

Семантика контракта C2 (`evidence/m4c/c2-contract-2026-11-22.md` §4):
  * preview считает РЕАЛЬНОГО актора (person+scope), не «роль-как-актор»;
  * ``decision`` — фактическое композитное решение серверных guard'ов.
    ``mixed`` используется там, где у одного ресурса расходятся разные
    guard-поверхности и это честно «частично»: `section.access` (роли —
    `access`, матрица/гранты — только global admin). Для `mixed` в остальных
    случаях нет фактического основания: например chat-edit без гранта — это
    `denied`, а не «частично» (контракт §4.5 + тест-план §7.1 п.1).
  * ``not_applicable`` — применимых guard/coverage-слоёв нет: global
    `section.chat_lore` (есть только видимость вкладки), прочие `section.*`
    в chat-скоупе (отдельного чатового ресурса нет), `key.*` в чате (BYOK).
  * Любая непрочитанная часть → ``AccessStorageUnavailable`` (503), не
    «deny» и не «default».
"""
import datetime
import logging

from services import access as access_srv
from services import chat_params
from services import roles as roles_srv
from services.param_catalog import (
    CATEGORY_KEYS,
    get_by_pg_key,
    known_param_keys,
    known_sections,
)
from services.permissions import (
    ACTION_IDS,
    Permissions,
    requires_permission as match_permission,
)

logger = logging.getLogger(__name__)

RESOLVER = (
    "roles.access_for(strict)+access.effective_matrix+"
    "permissions.requires_permission+chat_params.strict/v1"
)
NOTE = "Предварительная проверка. Права не изменены."
LAYER_ORDER = (
    "role", "global_admin_ceiling", "chat_access", "chat_grant", "chat_matrix",
    "secret_policy", "scope_capability", "config_surface",
)

_CHAT_SECTIONS = frozenset({"access", "chat_lore"})
_ALLOWED, _DENIED, _NA = "allowed", "denied", "not_applicable"


class PreviewInvalidResource(ValueError):
    """422: ресурс/операция вне канонического namespace (без «тихого allow»)."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class PreviewForbidden(PermissionError):
    """403: вызывающий не вправе смотреть этого актора/этот чат."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class PreviewChatNotFound(LookupError):
    """404: группового профиля чата нет (не «пустые права»)."""

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        super().__init__(f"профиль чата не найден: {chat_id}")


# ── helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _pool(cache):
    pg = getattr(cache, "pg", None)
    return getattr(pg, "pool", None) if pg is not None else None


def _is_global_admin_canon(ctx, cache, telegram_id: int) -> bool:
    """Канон `deps.user_is_global_admin`: wildcard / role_type global_admin /
    legacy-роль `admin`. Нужен там, где guard идёт через
    `requires_permission` (а не через `ctx.is_global_admin` персоны)."""
    if ctx.is_global_admin:
        return True
    role = cache.get_role(telegram_id) if cache is not None else None
    return role == "admin"


def _layer(layer_id: str, label: str, decision: str, *, applies_to: str,
           reason: str, required: str | None = None,
           matched: str | None = None, guard: str | None = None,
           consumers=None, hard: bool = False,
           source: str | None = None) -> dict:
    if layer_id not in LAYER_ORDER:                  # pragma: no cover — guard
        raise ValueError(f"unknown layer id: {layer_id}")
    return {
        "id": layer_id,
        "label": label,
        "decision": decision,
        "hard": bool(hard),
        "applies_to": applies_to,
        "reason": reason,
        "required": required,
        "matched": matched,
        "guard": guard,
        "consumers": list(consumers or ()),
        "source": source,
    }


def _match_detail(perms: Permissions, required: str,
                  *, by_role_type: bool = False) -> tuple[bool, str | None,
                                                           str]:
    """(allowed, matched-грант, reason) — решение общим матчером guard'ов.

    Решение — `permissions.requires_permission` (того же модуля, что
    используют `deps`/guard'ы), НЕ собственная копия. `matched`/`reason` —
    только объяснение, вычисляемое после положительного решения.
    """
    if by_role_type:
        return True, "role_type:global_admin", "role_type"
    allowed = bool(match_permission(perms, required))
    if not allowed:
        return False, None, "no_match"
    if perms.wildcard:
        return True, "wildcard", "wildcard"
    parts = required.split(".")
    ns = parts[0]
    rest = ".".join(parts[1:])
    if ns == "section":
        return True, f"section.{rest}", "section"
    if ns in ("param", "key"):
        group = perms.params if ns == "param" else perms.keys
        if rest in group:
            return True, f"{ns}.{rest}", ns
        cat = rest.split(".")[0]
        return True, f"section.{cat}", "section"
    if ns == "action":
        return True, f"action.{rest}", "action"
    # bare-формы (legacy-имена guard'ов: "access", "edit_info")
    if required in perms.actions:
        return True, f"action.{required}", "action"
    return True, f"section.{required}", "section"


def _effective_perms(ctx) -> Permissions:
    try:
        return ctx.effective_permissions
    except Exception:                                # pragma: no cover
        return Permissions.from_dict({})


def _eligible_matrix_hit(ctx, matrix: dict, field: str) -> tuple[bool, str | None]:
    """Совпал ли eligible_type(ctx) в view_roles/edit_roles (объяснение)."""
    role = access_srv.eligible_type(ctx)
    roles = access_srv._as_new_matrix(matrix).get(field) or []
    if role in roles:
        return True, f"{field}:{role}"
    return False, None


def _section_role_layers(ctx, cache, actor_id: int, sid: str,
                         scope_kind: str) -> tuple[list[dict], str]:
    """Слои для `section.<id>` (global/chat/dm) + итоговое решение."""
    perms = ctx.perms_global
    allowed, matched, reason = _match_detail(perms, f"section.{sid}")
    canon = _is_global_admin_canon(ctx, cache, actor_id)
    if not allowed and canon:
        allowed, matched, reason = True, "role_type:global_admin", "role_type"
    role_layer = _layer(
        "role", "Права роли", _ALLOWED if allowed else _DENIED,
        applies_to="ui_visibility" if sid == "chat_lore" else "coverage",
        reason=reason, required=f"section.{sid}", matched=matched,
        guard='web.api.deps.requires_permission("%s")' % sid,
        consumers=("GET /api/roles", "POST /api/roles", "GET /api/roles/tree",
                   "GET /api/admins", "POST /api/admins"),
        source="role_permissions")
    layers = [role_layer]

    if scope_kind == "global":
        if sid == "chat_lore":
            # Серверного глобального ресурса нет: секция — видимость вкладки.
            return layers, _NA
        if sid == "access":
            ceil = ctx.is_global_admin
            layers.append(_layer(
                "global_admin_ceiling", "Потолок: global admin",
                _ALLOWED if ceil else _DENIED, applies_to="guard",
                reason="role_type" if ceil else "no_match",
                required="global_admin", matched="role_type:global_admin"
                if ceil else None,
                guard="is_global_admin (inline)",
                consumers=("GET/PUT/DELETE /api/access/param_permissions",
                           "POST /api/access/chats/{id}/param_permissions/{key}",
                           "POST/DELETE /api/access/chats/{id}/admins"),
                source="role_type"))
            if allowed and ceil:
                return layers, _ALLOWED
            if not allowed and not ceil:
                return layers, _DENIED
            # role allowed, ceiling denied (custom section.access) — фактическое
            # «частично»: роли читает, матрицу/гранты — нет (S1 латентен, C3).
            return layers, "mixed"
        return layers, _ALLOWED if allowed else _DENIED

    if sid == "chat_lore":
        if scope_kind == "dm":
            layers.append(_layer(
                "chat_access", "Доступ к чату", _NA, applies_to="guard",
                reason="no_backend_guard", required="chat_admins",
                guard="web.api.chat_lore._require_chat (DM → 404)",
                consumers=("GET /api/chat_lore/*",), source="chat_admins"))
            return layers, _NA
        membership = ctx.role_chat in (roles_srv.ROLE_LOCAL_ADMIN,
                                       roles_srv.ROLE_MODERATOR)
        allowed_guard = canon or membership
        if canon:
            reason_g = "global_admin_rank"
        elif membership:
            reason_g = str(ctx.role_chat)
        else:
            reason_g = "no_grant"
        layers.append(_layer(
            "chat_access", "Доступ к чату", _ALLOWED if allowed_guard else _DENIED,
            applies_to="guard", reason=reason_g, required="chat_admins",
            matched=f"chat_admins:{ctx.role_chat}" if membership else None,
            guard="web.api.chat_lore.can_access_chat (chat_admins membership)",
            consumers=("GET /api/chat_lore/*", "POST /api/chat_lore/*"),
            hard=not allowed_guard, source="chat_admins"))
        return layers, _ALLOWED if allowed_guard else _DENIED

    # Прочие section.* в chat-скоупе: отдельного чатового ресурса нет.
    return layers, _NA


def _action_role_layers(ctx, cache, actor_id: int, action_id: str,
                        scope_kind: str) -> tuple[list[dict], str]:
    """Слои action.<id> (execute) + итоговое решение (зеркало guard'ов)."""
    perms_global = ctx.perms_global
    canon = _is_global_admin_canon(ctx, cache, actor_id)
    chat = scope_kind != "global"
    effective = _effective_perms(ctx)

    def _guard_layer(required: str, *, allowed: bool, reason: str,
                     matched: str | None, guard: str, consumers,
                     label: str = "Права роли",
                     applies_to: str = "guard") -> dict:
        return _layer("role", label, _ALLOWED if allowed else _DENIED,
                      applies_to=applies_to, reason=reason,
                      required=required, matched=matched, guard=guard,
                      consumers=consumers, source="role_permissions")

    def _persona_has_action(perms) -> tuple[bool, str | None, str]:
        if ctx.is_global_admin:
            return True, "role_type:global_admin", "role_type"
        return _match_detail(perms, "action.edit_persona")

    if action_id in ("control.restart", "control.stop", "control.start",
                     "debug.config", "edit_info"):
        required = {
            "control.restart": "action.control.restart",
            "control.stop": "action.control.stop",
            "control.start": "action.control.start",
            "debug.config": "action.debug.config",
            "edit_info": "edit_info",
        }[action_id]
        consumers = {
            "control.restart": ("POST /api/control/restart",),
            "control.stop": ("POST /api/control/stop",),
            "control.start": ("POST /api/control/start",),
            "debug.config": ("GET /api/debug/config",),
            "edit_info": ("POST /api/info", "GET/POST /api/info/guide*"),
        }[action_id]
        allowed, matched, reason = _match_detail(perms_global, required)
        if not allowed and canon:
            allowed, matched, reason = True, "role_type:global_admin", "role_type"
        layer = _guard_layer(
            required, allowed=allowed, reason=reason, matched=matched,
            guard='web.api.deps.requires_permission("%s")' % required,
            consumers=consumers)
        return [layer], _ALLOWED if allowed else _DENIED

    if action_id == "edit_persona":
        has, matched, reason = _persona_has_action(perms_global)
        if not has and chat:
            has, matched, reason = _match_detail(effective,
                                                 "action.edit_persona")
        content_allowed, content_matched, content_reason = (
            _match_detail(effective, "section.content"))
        layers = [_guard_layer(
            "action.edit_persona", allowed=has, reason=reason, matched=matched,
            guard="web.api.routes._persona_has_edit_action",
            consumers=("GET /api/persona", "PUT /api/persona"))]
        if chat:
            layers.append(_layer(
                "scope_capability", "Секция content (чат)", 
                _ALLOWED if content_allowed else _DENIED,
                applies_to="coverage", reason=content_reason,
                required="section.content", matched=content_matched,
                guard="web.api.routes._persona_can_edit(is_global=False)",
                consumers=("GET /api/persona", "PUT /api/persona"),
                source="role_permissions"))
        if has:
            return layers, _ALLOWED
        if chat and content_allowed:
            return layers, _ALLOWED
        return layers, _DENIED

    # edit_humor_library — ТОЧНОЕ зеркало web/api/speech._library_can_edit:
    #   global: admin OR edit_humor_library OR edit_persona (через _can_edit_speech);
    #   chat:   persona-edit path = edit_persona/admin OR section.content
    #           (само право edit_humor_library в chat-ветке НЕ участвует).
    if not chat:
        if ctx.is_global_admin:
            allowed, matched, reason = True, "role_type:global_admin", "role_type"
        else:
            allowed, matched, reason = _match_detail(
                perms_global, "action.edit_humor_library")
            if not allowed:
                persona, pm, _pr = _persona_has_action(perms_global)
                if persona:
                    allowed, matched, reason = True, pm, "via_persona_or_content"
    else:
        persona, pm, _pr = _persona_has_action(effective)
        content_allowed, cm, _cr = _match_detail(effective, "section.content")
        if persona:
            allowed, matched = True, pm
        elif content_allowed:
            allowed, matched = True, cm
        else:
            allowed, matched = False, None
        reason = "via_persona_or_content" if allowed else "no_match"
    layers = [_guard_layer(
        "action.edit_humor_library", allowed=allowed, reason=reason,
        matched=matched, guard="web.api.speech._library_can_edit",
        consumers=("GET /api/speech/humor", "POST /api/speech/humor/craft"))]
    if chat:
        content_allowed, content_matched, content_reason = _match_detail(
            effective, "section.content")
        layers.append(_layer(
            "scope_capability", "Секция content (чат)",
            _ALLOWED if content_allowed else _DENIED,
            applies_to="coverage", reason=content_reason,
            required="section.content", matched=content_matched,
            guard="web.api.speech._library_can_edit (chat path)",
            consumers=("GET /api/speech/humor",), source="role_permissions"))
    return layers, _ALLOWED if allowed else _DENIED


def _param_key_layers(ctx, cache, actor_id: int, parsed: dict,
                      scope_kind: str, *, chat_root: dict | None,
                      global_snapshot: dict | None) -> tuple[list[dict], str,
                                                               dict]:
    """Слои param.*/key.* + решение + overrides."""
    key = parsed["pg_key"]
    spec = parsed["spec"]
    kind = parsed["kind"]
    op = parsed["operation"]
    perms_global = ctx.perms_global
    effective = _effective_perms(ctx)
    canon = _is_global_admin_canon(ctx, cache, actor_id)
    global_row = (global_snapshot or {}).get(key)
    chat_overrides = (chat_root or {}).get("perm_overrides") or {}
    chat_row = chat_overrides.get(key)
    overrides = {
        "global": {
            "present": global_row is not None,
            "updated_at": (global_row or {}).get("updated_at"),
            "author_recorded": False,
        },
        "chat": {
            "present": chat_row is not None,
            "updated_at": parsed.get("_chat_updated_at"),
            "author_recorded": False,
        },
    }
    layers: list[dict] = []

    if kind == "key":
        if scope_kind != "global":
            layers.append(_layer(
                "scope_capability", "Ключи в чате", _NA, applies_to="guard",
                reason="keys_via_byok", required=f"key.{key}",
                guard="нет чатового ресурса ключа (BYOK /api/config/keys/own)",
                consumers=("POST /api/config/keys/own",)))
            return layers, _NA, overrides
        if op == "view":
            allowed = ctx.is_global_admin
            layers.append(_layer(
                "secret_policy", "Секреты", _ALLOWED if allowed else _DENIED,
                applies_to="guard", reason="secret_admin_only" if not allowed
                else "role_type", required=f"key.{key}",
                matched="role_type:global_admin" if allowed else None,
                guard="web.api.routes.get_config (secret mask)",
                consumers=("GET /api/config",), hard=not allowed,
                source="secret_policy"))
            return layers, _ALLOWED if allowed else _DENIED, overrides
        # edit: provider-ключи — только global admin; прочие — право key.<key>
        from services import mca_random_source
        if key in mca_random_source.PROVIDER_KEY_SETTINGS:
            allowed, matched, reason = canon, (
                "role_type:global_admin" if canon else None), (
                "role_type" if canon else "no_match")
            layers.append(_layer(
                "role", "Права роли", _ALLOWED if allowed else _DENIED,
                applies_to="guard", reason=reason, required=f"key.{key}",
                matched=matched,
                guard="web.api.routes.post_config_global (provider key)",
                consumers=("POST /api/config",), source="role_permissions"))
            return layers, _ALLOWED if allowed else _DENIED, overrides
        allowed, matched, reason = _match_detail(perms_global, f"key.{key}")
        layers.append(_layer(
            "role", "Права роли", _ALLOWED if allowed else _DENIED,
            applies_to="guard", reason=reason, required=f"key.{key}",
            matched=matched,
            guard="web.api.deps.can_view_key_value(key.%s)" % key,
            consumers=("POST /api/config",), source="role_permissions"))
        return layers, _ALLOWED if allowed else _DENIED, overrides

    # ── param.* ───────────────────────────────────────────────────────────
    if scope_kind == "global":
        if op == "view":
            layers.append(_layer(
                "role", "Права роли", _NA, applies_to="guard",
                reason="no_backend_guard", required=f"param.{key}",
                guard="web.api.deps.user_has_permission (не вызывается)",
                consumers=("GET /api/config",)))
            if spec.hidden:
                layers.append(_layer(
                    "config_surface", "Скрытый параметр", _DENIED,
                    applies_to="guard", reason="hidden_parameter",
                    required=f"param.{key}",
                    guard="web.api.routes.get_config (hidden excluded)",
                    consumers=("GET /api/config",), hard=True,
                    source="default"))
                return layers, _DENIED, overrides
            if spec.secret:
                allowed = ctx.is_global_admin
                layers.append(_layer(
                    "config_surface", "Секреты", _ALLOWED if allowed
                    else _DENIED, applies_to="guard",
                    reason="secret_admin_only" if not allowed else "role_type",
                    required=f"param.{key}",
                    matched="role_type:global_admin" if allowed else None,
                    guard="web.api.routes.get_config (secret filter)",
                    consumers=("GET /api/config",), hard=not allowed,
                    source="secret_policy"))
                return layers, _ALLOWED if allowed else _DENIED, overrides
            layers.append(_layer(
                "config_surface", "Глобальное чтение", _ALLOWED,
                applies_to="guard", reason="global_config_all",
                required=f"param.{key}", matched="global_config_all",
                guard="web.api.routes.get_config (global, non-secret)",
                consumers=("GET /api/config",), source="default"))
            return layers, _ALLOWED, overrides
        # global edit: только право param.<key> (F-C2-2: без admin-bypass)
        allowed, matched, reason = _match_detail(perms_global, f"param.{key}")
        layers.append(_layer(
            "role", "Права роли", _ALLOWED if allowed else _DENIED,
            applies_to="guard", reason=reason, required=f"param.{key}",
            matched=matched,
            guard="web.api.deps.can_edit_param(%s)" % key,
            consumers=("POST /api/config",), source="role_permissions"))
        if spec.hidden:
            layers.append(_layer(
                "config_surface", "Скрытый параметр", _DENIED,
                applies_to="guard", reason="hidden_parameter",
                required=f"param.{key}",
                guard="web.api.routes.post_config_global (hidden guard)",
                consumers=("POST /api/config",), hard=True,
                source="default"))
            return layers, _DENIED, overrides
        return layers, _ALLOWED if allowed else _DENIED, overrides

    # ── param.* в chat/dm ────────────────────────────────────────────────
    chat_channel = access_srv.can_access_chat(ctx, parsed.get("chat_id"))
    if ctx.is_global_admin:
        access_reason = "global_admin_rank"
    elif ctx.is_dm_owner:
        access_reason = "dm_owner"
    elif ctx.role_chat in (roles_srv.ROLE_LOCAL_ADMIN,
                           roles_srv.ROLE_MODERATOR):
        access_reason = str(ctx.role_chat)
    else:
        access_reason = "no_match"
    layers.append(_layer(
        "chat_access", "Доступ к чату",
        _ALLOWED if chat_channel else _DENIED, applies_to="guard",
        reason=access_reason, required=f"chat:{parsed.get('chat_id')}",
        matched="chat_access" if chat_channel else None,
        guard="access.can_access_chat(ctx, chat_id)",
        consumers=("GET /api/config", "POST /api/config"),
        hard=not chat_channel, source="chat_admins"))

    matrix = access_srv.effective_matrix(
        key, (global_row or {}).get("value"), chat_row)
    if chat_row is not None:
        matrix_source = "chat_override"
    elif global_row is not None:
        matrix_source = "global_override"
    else:
        matrix_source = "default"

    if op == "view":
        if spec.secret:
            secret_ok = ctx.is_global_admin
            layers.append(_layer(
                "secret_policy", "Секреты", _ALLOWED if secret_ok else _DENIED,
                applies_to="guard", reason="secret_admin_only"
                if not secret_ok else "role_type", required=f"param.{key}",
                matched="role_type:global_admin" if secret_ok else None,
                guard="web.api.routes.get_config (secret filter)",
                consumers=("GET /api/config",), hard=not secret_ok,
                source="secret_policy"))
        # Решение — существующий примитив (второго матчера нет); matched —
        # только объяснение, вычисленное ПОСЛЕ решения.
        view_ok = access_srv.can_view_param(ctx, matrix)
        _hit, view_matched = _eligible_matrix_hit(ctx, matrix, "view_roles")
        layers.append(_layer(
            "chat_matrix", "Матрица «Доступ к параметрам»",
            _ALLOWED if view_ok else _DENIED, applies_to="guard",
            reason=matrix_source if matrix_source != "default" else "default",
            required=f"param.{key}", matched=view_matched,
            guard="access.can_view_param(ctx, effective_matrix)",
            consumers=("GET /api/config",), source=matrix_source))
        if spec.hidden:
            layers.append(_layer(
                "config_surface", "Скрытый параметр", _DENIED,
                applies_to="guard", reason="hidden_parameter",
                required=f"param.{key}",
                guard="web.api.routes.get_config (hidden excluded)",
                consumers=("GET /api/config",), hard=True, source="default"))
            return layers, _DENIED, overrides
        # факт: chat_access hard + secret hard + matrix
        if not chat_channel:
            return layers, _DENIED, overrides
        if spec.secret and not ctx.is_global_admin:
            return layers, _DENIED, overrides
        return layers, _ALLOWED if view_ok else _DENIED, overrides

    # edit
    if spec.hidden:
        layers.append(_layer(
            "config_surface", "Скрытый параметр", _DENIED, applies_to="guard",
            reason="hidden_parameter", required=f"param.{key}",
            guard="web.api.routes.post_config (hidden guard)",
            consumers=("POST /api/config",), hard=True, source="default"))
        return layers, _DENIED, overrides
    if not spec.per_chat:
        layers.append(_layer(
            "scope_capability", "Уровень чата", _DENIED, applies_to="guard",
            reason="not_per_chat", required=f"param.{key}",
            guard="web.api.routes.post_config (per_chat guard)",
            consumers=("POST /api/config",), hard=True, source="default"))
        return layers, _DENIED, overrides
    grant_ok = bool(ctx.is_global_admin or ctx.is_dm_owner
                    or ctx.role_chat in (roles_srv.ROLE_LOCAL_ADMIN,
                                         roles_srv.ROLE_MODERATOR))
    if ctx.is_global_admin:
        grant_reason = "global_admin_rank"
    elif ctx.is_dm_owner:
        grant_reason = "dm_owner"
    elif grant_ok:
        grant_reason = str(ctx.role_chat)
    else:
        grant_reason = "no_grant"
    layers.append(_layer(
        "chat_grant", "Грант чата", _ALLOWED if grant_ok else _DENIED,
        applies_to="guard", reason=grant_reason,
        required="chat_admins", matched=f"chat_admins:{ctx.role_chat}"
        if grant_ok and ctx.role_chat else None,
        guard="access.can_edit_param (chat grant / DM owner / admin)",
        consumers=("POST /api/config",), source="chat_admins"))
    edit_ok = access_srv.can_edit_param(ctx, matrix)
    _hit, edit_matched = _eligible_matrix_hit(ctx, matrix, "edit_roles")
    layers.append(_layer(
        "chat_matrix", "Матрица «Доступ к параметрам»",
        _ALLOWED if edit_ok else _DENIED, applies_to="guard",
        reason=matrix_source, required=f"param.{key}", matched=edit_matched,
        guard="access.can_edit_param(ctx, effective_matrix)",
        consumers=("POST /api/config",), source=matrix_source))
    if not chat_channel:
        return layers, _DENIED, overrides
    if not grant_ok or not edit_ok:
        return layers, _DENIED, overrides
    return layers, _ALLOWED, overrides


def parse_resource(resource: str, operation: str, *,
                   admin_caller: bool) -> dict:
    """Валидация канонического namespace (`422`, без «тихого allow»)."""
    res = (resource or "").strip()
    if not res or "." not in res:
        raise PreviewInvalidResource(
            "unknown_resource", "ресурс в форме section.|param.|key.|action.")
    ns, rest = res.split(".", 1)
    if not rest:
        raise PreviewInvalidResource("unknown_resource", "пустой id ресурса")
    if ns == "section":
        if operation != "view":
            raise PreviewInvalidResource(
                "invalid_operation", "у section одна операция: view")
        if rest not in known_sections():
            raise PreviewInvalidResource(
                "unknown_resource", f"неизвестная секция: {rest}")
        return {"kind": "section", "namespace": f"section.{rest}",
                "section_id": rest, "operation": "view", "spec": None,
                "pg_key": None}
    if ns == "action":
        if operation != "execute":
            raise PreviewInvalidResource(
                "invalid_operation", "у action операция: execute")
        if rest not in ACTION_IDS:
            raise PreviewInvalidResource(
                "unknown_resource", f"неизвестное действие: {rest}")
        return {"kind": "action", "namespace": f"action.{rest}",
                "action_id": rest, "operation": "execute", "spec": None,
                "pg_key": None}
    if ns not in ("param", "key"):
        raise PreviewInvalidResource(
            "unknown_resource", f"неизвестный namespace: {ns}")
    spec = get_by_pg_key(rest)
    if spec is None or spec.category is None:
        raise PreviewInvalidResource(
            "unknown_resource", f"неизвестный параметр: {rest}")
    if ns == "param" and spec.category == CATEGORY_KEYS:
        raise PreviewInvalidResource(
            "use_key_namespace",
            "ключи-секреты проверяются как key.<pg_key>")
    if ns == "key" and spec.category != CATEGORY_KEYS:
        raise PreviewInvalidResource(
            "unknown_resource", "key.* — только категория keys")
    if operation not in ("view", "edit"):
        raise PreviewInvalidResource(
            "invalid_operation", "операция param/key: view|edit")
    if spec.hidden and not admin_caller:
        # hidden принимается только у global-admin-вызывающего (иначе 422).
        raise PreviewInvalidResource(
            "unknown_resource", f"неизвестный параметр: {rest}")
    return {"kind": ns, "namespace": f"{ns}.{rest}", "operation": operation,
            "spec": spec, "pg_key": spec.pg_key}


async def evaluate(*, caller_id: int, actor_id: int, chat_id: int | None,
                   resource: str, operation: str,
                   cache) -> dict:
    """Собрать read-only ответ `/api/access/effective`."""
    if chat_id is not None and int(chat_id) == 0:
        raise PreviewInvalidResource("invalid_chat_id",
                                     "chat_id=0 вне домена")
    scope_kind = "global" if chat_id is None else (
        "dm" if int(chat_id) > 0 else "chat")
    delegated = int(actor_id) != int(caller_id)

    caller_ctx = await roles_srv.access_for(
        caller_id, chat_id, cache=cache, strict=True)
    if delegated and not caller_ctx.is_global_admin:
        raise PreviewForbidden(
            "delegated_requires_global_admin",
            "проверка чужого актора — только global admin")
    if scope_kind == "dm":
        if not (int(chat_id) == int(caller_id) == int(actor_id)):
            raise PreviewForbidden("dm_owner_only",
                                   "личные сообщения — только владельцу")
    elif scope_kind == "chat":
        if not access_srv.can_access_chat(caller_ctx, chat_id):
            raise PreviewForbidden("chat_forbidden", "нет доступа к чату")

    parsed = parse_resource(resource, operation,
                            admin_caller=caller_ctx.is_global_admin)

    actor_ctx = await roles_srv.access_for(
        actor_id, chat_id if scope_kind != "global" else None,
        cache=cache, strict=True)

    profile_present = None
    chat_root = None
    chat_updated = None
    if scope_kind != "global":
        chat_root, chat_updated, profile_present = (
            await chat_params.read_chat_params_strict(
                chat_id, pg=getattr(cache, "pg", None)))
        if scope_kind == "chat" and not profile_present:
            raise PreviewChatNotFound(chat_id)

    global_snapshot = None
    if parsed["kind"] in ("param", "key"):
        global_snapshot = await access_srv.param_permissions_snapshot(
            getattr(cache, "pg", None))

    parsed["chat_id"] = chat_id
    parsed["_chat_updated_at"] = chat_updated
    if parsed["kind"] == "section":
        layers, decision = _section_role_layers(
            actor_ctx, cache, actor_id, parsed["section_id"], scope_kind)
        overrides = None
    elif parsed["kind"] == "action":
        layers, decision = _action_role_layers(
            actor_ctx, cache, actor_id, parsed["action_id"], scope_kind)
        overrides = None
    else:
        layers, decision, overrides = _param_key_layers(
            actor_ctx, cache, actor_id, parsed, scope_kind,
            chat_root=chat_root, global_snapshot=global_snapshot)

    spec = parsed.get("spec")
    admin_caller = caller_ctx.is_global_admin
    scope = {
        "kind": scope_kind,
        "chat_id": chat_id,
        "title": "Личные сообщения" if scope_kind == "dm" else None,
        "chat_role": actor_ctx.role_chat,
        "profile_present": profile_present,
    }
    actor = {
        "telegram_id": int(actor_id),
        "display_name": None,
        "role_name": cache.get_role(actor_id) if cache is not None else None,
        "role_type": actor_ctx.role_global,
        "is_global_admin": bool(actor_ctx.is_global_admin),
        "is_local_admin": bool(actor_ctx.is_local_admin),
        "rank": int(actor_ctx.rank),
        "is_dm_owner": bool(actor_ctx.is_dm_owner),
    }
    return {
        "mode": "delegated" if delegated else "self",
        "preview": True,
        "note": NOTE,
        "decision": decision,
        "evaluated_at": _now_iso(),
        "resolver": RESOLVER,
        "actor": actor,
        "scope": scope,
        "resource": {
            "namespace": parsed["namespace"],
            "kind": parsed["kind"],
            "title": spec.title_ru if (spec is not None and admin_caller) else None,
            "secret": bool(spec.secret) if (spec is not None and admin_caller)
            else None,
            "hidden": bool(spec.hidden) if (spec is not None and admin_caller)
            else None,
        },
        "operation": parsed["operation"],
        "layers": layers,
        "overrides": overrides,
    }


# ── read-only GET для чатового слоя ────────────────────────────────────────

async def chat_param_permissions(chat_id: int, *, cache) -> dict:
    """`GET /api/access/chats/{id}/param_permissions` — только чтение.

    Отдаёт только известные ключи каталога (622) из `perm_overrides`, без
    значений/промптов/last4; остальные записи считаются `filtered_out`.
    """
    root, updated_at, present = await chat_params.read_chat_params_strict(
        chat_id, pg=getattr(cache, "pg", None))
    if int(chat_id) < 0 and not present:
        raise PreviewChatNotFound(chat_id)
    raw = root.get("perm_overrides") or {}
    known = known_param_keys()
    items: dict[str, dict] = {}
    filtered = 0
    for key, value in raw.items():
        if key not in known:
            filtered += 1
            continue
        legacy = isinstance(value, dict) and not (
            "view_roles" in value or "edit_roles" in value) and any(
            field in value for field in
            ("view_min_role", "edit_min_role", "hidden_from_local"))
        normalized = access_srv.normalize_permission_override(value)
        items[key] = {
            "view_roles": list(normalized.get("view_roles") or []),
            "edit_roles": list(normalized.get("edit_roles") or []),
            "legacy": bool(legacy),
        }
    return {
        "chat_id": int(chat_id),
        "profile_present": bool(present),
        "updated_at": updated_at,
        "items": items,
        "filtered_out": filtered,
    }


CHAT_ADMINS_SQL = (
    "SELECT telegram_id, role_name, added_by, created_at "
    "FROM chat_admins WHERE chat_id = $1 ORDER BY telegram_id"
)


async def chat_admins(chat_id: int, *, cache) -> list[dict]:
    """Строки `chat_admins` для `GET /api/access/chats/{id}/admins`."""
    pool = _pool(cache)
    if pool is None:
        from services.access_errors import AccessStorageUnavailable
        raise AccessStorageUnavailable(
            "PostgreSQL недоступен (пул отсутствует): chat_admins не читается")
    if int(chat_id) < 0:
        _root, _upd, present = await chat_params.read_chat_params_strict(
            chat_id, pg=getattr(cache, "pg", None))
        if not present:
            raise PreviewChatNotFound(chat_id)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(CHAT_ADMINS_SQL, int(chat_id))
    except Exception as exc:
        from services.access_errors import AccessStorageUnavailable
        raise AccessStorageUnavailable(
            "PostgreSQL недоступен: chat_admins не читается") from exc
    out = []
    for row in rows or ():
        created = row.get("created_at")
        out.append({
            "telegram_id": row.get("telegram_id"),
            "role_name": row.get("role_name"),
            "added_by": row.get("added_by"),
            "created_at": created.isoformat()
            if hasattr(created, "isoformat") else (created or None),
            "display_name": None,
        })
    return out
