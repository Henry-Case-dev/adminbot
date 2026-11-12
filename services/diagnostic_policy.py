"""SELF-DIAG-01 D2 — политика доступа к диагностическим возможностям.

Один авторитетный слой решений для всех входов (owner amendment 2026-11-09):
«чекап», `get_bot_health`, `read_source_code`, `inspect_runtime`, обычный Tool
Calling, API и админ-интерфейс. Второй ACL не создаётся: роль владельца и
чат-срез берутся из существующего `services.roles.access_for`, статус
`chat_admin` — онлайн-проверкой Bot API (`services.telegram_role_check`),
матрица/перекрытия — существующий слой прав (`services.access`: таблица
`param_permissions` + `chat_params.perm_overrides`).

Решение вычисляется по контракту ТЗ §7.4:
    (authenticated_actor, chat_scope, resource_class, resource_scope,
     action, destination) → allow | deny | unverified + машинный reason_code.

Ключевые инварианты:
  * principal берётся ТОЛЬКО из Telegram-update (`telegram_id`, `chat_id`),
    не из аргументов инструмента и не из текста запроса — «я админ» и
    `user_id` в tool args ничего не повышают;
  * `SECRET_VALUE` — абсолютный, ненастраиваемый запрет для всех ролей,
    включая владельца (значение не покидает backend);
  * `PROMPT_CONTENT` участнику не выдаётся никогда; админу этого чата —
    по явному запросу, в том числе прямо в группе;
  * решение LLM не принимает: модель только выражает запрос/ресурс;
  * отзыв прав действует на уже запущенные проверки: `recheck_gate` перед
    возвратом защищённого результата и `publish` перед публикацией;
  * аудит хранит роли/решения/effective-state без секретов и без полного
    текста защищённых промптов.
"""
from __future__ import annotations

import collections
import dataclasses
import datetime
import logging
import uuid

from services import output_projection as projection
from services import telegram_role_check as role_check

logger = logging.getLogger(__name__)

# ── Классы данных (ТЗ §7.2) ────────────────────────────────────────────────

PUBLIC_TECH = "PUBLIC_TECH"
CHAT_SCOPED = "CHAT_SCOPED"
PROMPT_CONTENT = "PROMPT_CONTENT"
OTHER_CHAT_DATA = "OTHER_CHAT_DATA"
SECRET_VALUE = "SECRET_VALUE"

DATA_CLASSES: tuple[str, ...] = (PUBLIC_TECH, CHAT_SCOPED, PROMPT_CONTENT,
                                 OTHER_CHAT_DATA, SECRET_VALUE)

DATA_CLASS_TITLES_RU: dict[str, str] = {
    PUBLIC_TECH: "Публичная техническая информация",
    CHAT_SCOPED: "Данные текущего чата",
    PROMPT_CONTENT: "Содержимое промптов",
    OTHER_CHAT_DATA: "Данные другого чата",
    SECRET_VALUE: "Секретные значения",
}

# ── Роли ───────────────────────────────────────────────────────────────────

ROLE_MEMBER = "member"
ROLE_CHAT_ADMIN = "chat_admin"
ROLE_PROJECT_OWNER = "project_owner"

ROLE_TITLES_RU: dict[str, str] = {
    ROLE_MEMBER: "Участник",
    ROLE_CHAT_ADMIN: "Админ этого чата",
    ROLE_PROJECT_OWNER: "Владелец бота",
}

#: Роль актора → строка настраиваемой матрицы (домен `services.access`).
MATRIX_ROLE_OF_ACTOR: dict[str, str] = {
    ROLE_MEMBER: "user",
    ROLE_CHAT_ADMIN: "local_admin",
    ROLE_PROJECT_OWNER: "global_admin",
}

#: Проверки личности/полномочий.
VERIFIED_OWNER = "verified_owner"
VERIFIED_ADMIN = "verified_admin"
VERIFIED_MEMBER = "verified_member"
VERIFICATION_NOT_REQUIRED = "not_required"
AUTH_UNVERIFIED = "unverified"

# ── Эффекты/причины ────────────────────────────────────────────────────────

EFFECT_ALLOW = "allow"
EFFECT_DENY = "deny"
EFFECT_UNVERIFIED = "unverified"

SOURCE_HARD_RULE = "hard_rule"
SOURCE_CLASS_DEFAULT = "class_default"
SOURCE_GLOBAL_OVERRIDE = "global_override"
SOURCE_CHAT_OVERRIDE = "chat_override"
SOURCE_IMPLICIT_OWNER = "implicit_owner"

# reason codes (машинные, стабильные)
R_ALLOW_PUBLIC = "allowed_public_class_default"
R_ALLOW_OWNER = "allowed_project_owner"
R_ALLOW_CHAT_ADMIN = "allowed_chat_admin_default"
R_ALLOW_GLOBAL_OVERRIDE = "allowed_by_global_override"
R_ALLOW_CHAT_OVERRIDE = "allowed_by_chat_override"
R_DENY_CLASS_DEFAULT = "denied_by_class_default"
R_DENY_GLOBAL_OVERRIDE = "denied_by_global_override"
R_DENY_CHAT_OVERRIDE = "denied_by_chat_override"
R_DENY_PROMPT_MEMBER = "denied_prompt_content_member"
R_DENY_SECRET = "denied_secret_value_never"
R_DENY_AUTH_UNVERIFIED = "denied_auth_unverified"
R_DENY_OTHER_CHAT = "denied_other_chat_scope"
R_DENY_ACTION_UNSUPPORTED = "denied_action_not_supported"
R_DENY_UNKNOWN_CAPABILITY = "denied_unknown_capability"
R_DENY_NO_IDENTITY = "denied_anonymous_sender"
#: Слой прав недоступен: проверить запрет нельзя → данные не выдаются.
R_DENY_POLICY_UNAVAILABLE = "denied_policy_unavailable"


@dataclasses.dataclass(frozen=True)
class Capability:
    """Диагностическая возможность (категория матрицы админки)."""

    id: str
    title_ru: str
    data_class: str
    actions: tuple[str, ...]
    description_ru: str
    tool_names: tuple[str, ...] = ()


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "bot_server_state", "Состояние бота и сервера", PUBLIC_TECH,
        ("view", "run"),
        "Здоровье сервиса, версии, аптайм, состояние модулей",
        ("get_bot_health",)),
    Capability(
        "detailed_metrics", "Подробные метрики", PUBLIC_TECH, ("view", "run"),
        "CPU/RAM/disk, размеры БД, счётчики запросов и очередей"),
    Capability(
        "logs_traceback", "Логи и traceback", PUBLIC_TECH, ("view", "run"),
        "Строки журнала и трассировки ошибок (после удаления секретов)"),
    Capability(
        "source_code", "Исходный код и GitHub", PUBLIC_TECH, ("view", "run"),
        "Публичный код проекта и идентичность репозитория",
        ("read_source_code",)),
    Capability(
        "commit_history", "История коммитов", PUBLIC_TECH, ("view",),
        "Коммиты и релизная история публичного репозитория"),
    Capability(
        "non_secret_config", "Конфигурация без секретов", PUBLIC_TECH,
        ("view",),
        "Названия настроек и их состояние; значения секретов не выдаются"),
    Capability(
        "memory_analytics", "Память и служебная аналитика", CHAT_SCOPED,
        ("view", "run"),
        "Метрики памяти и служебная аналитика в границах текущего чата"),
    Capability(
        "prompts", "Промпты", PROMPT_CONTENT, ("view", "edit"),
        "Действующие промпты этого чата; чтение и редактирование раздельны",
        # SELF-DIAG-01 D5/D6 (`SD1-D5-02`, `SD1-AMX-04`): защищённый
        # серверный readback — тот же инструмент, что исполняет
        # `ToolRouter.dispatch`; отдельных ACL нет.
        ("prompt_readback",)),
    Capability(
        "deep_diagnostics", "Глубокая диагностика", CHAT_SCOPED,
        ("view", "run"),
        "Углублённые проверки runtime в границах текущего чата",
        ("inspect_runtime",)),
)

CAPABILITY_MAP: dict[str, Capability] = {c.id: c for c in CAPABILITIES}

#: Инструмент → диагностическая возможность (единая карта, не эвристика по
#: словам запроса). Немаркированные инструменты политикой не гейтятся.
TOOL_CAPABILITIES: dict[str, str] = {
    tool: capability.id
    for capability in CAPABILITIES
    for tool in capability.tool_names
}

#: SELF-DIAG-01 D6 (`SD1-D5-02`, blocker «real dispatch»): действие инструмента
#: в матрице возможности. По умолчанию — `run`; `prompt_readback` — это
#: ЧТЕНИЕ защищённого артефакта, и у возможности `prompts` есть ровно
#: `view/edit`. Без этой карты tool-гейт спрашивал `prompts.run`, которого не
#: существует, и разрешённый readback всегда получал
#: `denied_action_not_supported`. Сам handler всё равно перепроверяет доступ
#: через `open_gate("prompts", "view")` — второго ACL нет.
TOOL_ACTIONS: dict[str, str] = {
    "prompt_readback": "view",
}

#: Классы, для которых нужна онлайн-проверка админства Telegram.
PROTECTED_CLASSES: frozenset[str] = frozenset({PROMPT_CONTENT,
                                               OTHER_CHAT_DATA})


# ── Актёр и решение ────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class Actor:
    """Аутентифицированный субъект запроса (только из Telegram-update)."""

    telegram_id: int | None
    chat_id: int | None
    role: str
    verification: str
    reason_code: str
    telegram_status: str = ""

    @property
    def matrix_role(self) -> str:
        return MATRIX_ROLE_OF_ACTOR.get(self.role, "user")

    @property
    def is_owner(self) -> bool:
        return self.role == ROLE_PROJECT_OWNER

    @property
    def is_chat_admin(self) -> bool:
        return self.role == ROLE_CHAT_ADMIN

    @property
    def verified(self) -> bool:
        return self.verification in (VERIFIED_OWNER, VERIFIED_ADMIN,
                                     VERIFIED_MEMBER,
                                     VERIFICATION_NOT_REQUIRED)


@dataclasses.dataclass(frozen=True)
class Decision:
    """Результат вычисления прав: allow | deny | unverified."""

    effect: str
    reason_code: str
    message_ru: str
    capability: str
    action: str
    data_class: str
    role: str
    matrix_role: str
    source: str
    actor: Actor

    @property
    def allowed(self) -> bool:
        return self.effect == EFFECT_ALLOW

    @property
    def protected(self) -> bool:
        return self.data_class in PROTECTED_CLASSES

    def as_dict(self) -> dict:
        return {
            "effect": self.effect,
            "reason_code": self.reason_code,
            "message": self.message_ru,
            "capability": self.capability,
            "action": self.action,
            "data_class": self.data_class,
            "role": self.role,
            "role_title": ROLE_TITLES_RU.get(self.role, self.role),
            "matrix_role": self.matrix_role,
            "source": self.source,
            "verification": self.actor.verification,
        }


# ── Аудит ──────────────────────────────────────────────────────────────────

_AUDIT_MAX = 500
_audit_log: collections.deque[dict] = collections.deque(maxlen=_AUDIT_MAX)
_policy_generation = 0

#: Белый список полей аудита: только скаляры/счётчики/роли. Никакого
#: свободного текста пользователя и значений секретов.
_AUDIT_FIELDS: tuple[str, ...] = (
    "event", "request_id", "actor_id", "chat_id", "capability", "action",
    "role", "verification", "effect", "reason_code", "source", "tool",
    "destination", "scope", "changed_by", "key", "before", "after",
    "prompt_id", "prompt_revision", "prompt_chars", "prompt_digest",
    "disclosure_actor", "redaction_status", "redacted", "tool_names",
    "generation", "actor_role", "target_telegram_id", "rule",
)


def _audit(event: str, **fields) -> dict:
    record = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": event,
        "generation": _policy_generation,
    }
    for key in _AUDIT_FIELDS:
        if key in fields:
            record[key] = fields[key]
    _audit_log.append(record)
    logger.info("[diag-audit] %s", _audit_summary(record))
    return record


def _audit_summary(record: dict) -> str:
    parts = []
    for key in ("event", "actor_id", "chat_id", "capability", "action", "role",
                "effect", "reason_code", "source", "tool", "changed_by",
                "target_telegram_id"):
        if key in record and record[key] not in (None, ""):
            parts.append(f"{key}={record[key]}")
    return " ".join(parts)


def audit_snapshot(limit: int = 100) -> list[dict]:
    """Последние записи аудита (копии) для админки. Без защищённых данных."""
    items = list(_audit_log)[-max(1, int(limit)):]
    return [dict(item) for item in items]


def reset_audit() -> None:
    """Очистка журнала (тесты/ручной сброс наблюдаемости)."""
    _audit_log.clear()


def policy_generation() -> int:
    """Поколение политики: растёт при каждом изменении матрицы/прав."""
    return _policy_generation


def notify_policy_change(*, changed_by: int | None, capability: str | None,
                         before=None, after=None, scope: str = "global") -> int:
    """Явное изменение политики: поколение + сброс кэша слоя прав + аудит."""
    global _policy_generation
    _policy_generation += 1
    try:
        from services import access as access_srv
        access_srv.reset_param_permissions_cache()
    except Exception:                                  # pragma: no cover
        logger.warning("[diag-policy] сброс кэша прав не удался", exc_info=True)
    _audit("policy_change", changed_by=changed_by, capability=capability,
           before=before, after=after, scope=scope,
           generation=_policy_generation)
    return _policy_generation


# ── Разрешение актора ──────────────────────────────────────────────────────

async def resolve_actor(telegram_id: int | None, chat_id: int | None, *,
                        cache=None, bot=None, check_admin: bool = False,
                        fresh_telegram: bool = False) -> Actor:
    """Определить роль актора: project_owner > chat_admin > member.

    `project_owner` — настроенный numeric Telegram ID существующего контура
    владельца (`services.roles.access_for` → global_admin), а не «первый в
    списке админов Telegram».
    """
    if telegram_id is None:
        return Actor(None, chat_id, ROLE_MEMBER, AUTH_UNVERIFIED,
                     R_DENY_NO_IDENTITY)

    from services import roles as roles_srv
    try:
        ctx = await roles_srv.access_for(int(telegram_id), chat_id, cache=cache)
    except Exception:                                  # pragma: no cover
        logger.warning("[diag-policy] access_for недоступен | user=%s",
                       telegram_id, exc_info=True)
        ctx = None
    if ctx is not None and ctx.is_global_admin:
        return Actor(int(telegram_id), chat_id, ROLE_PROJECT_OWNER,
                     VERIFIED_OWNER, R_ALLOW_OWNER)

    if not check_admin:
        # Публичные классы не зависят от админства: сеть не нужна.
        return Actor(int(telegram_id), chat_id, ROLE_MEMBER,
                     VERIFICATION_NOT_REQUIRED, R_ALLOW_PUBLIC)

    check = await role_check.check_chat_admin(
        bot, chat_id, telegram_id, fresh=fresh_telegram)
    _audit("role_check", actor_id=int(telegram_id), chat_id=chat_id,
           role=role_check.STATUS_CHAT_ADMIN if check.is_admin
           else check.status,
           verification=(VERIFIED_ADMIN if check.is_admin
                         else VERIFIED_MEMBER if check.verified
                         else AUTH_UNVERIFIED),
           reason_code=check.reason, source=check.source)
    if check.status == role_check.STATUS_CHAT_ADMIN:
        return Actor(int(telegram_id), chat_id, ROLE_CHAT_ADMIN,
                     VERIFIED_ADMIN, R_ALLOW_CHAT_ADMIN, check.telegram_status)
    if check.status == role_check.STATUS_MEMBER:
        return Actor(int(telegram_id), chat_id, ROLE_MEMBER,
                     VERIFIED_MEMBER, R_DENY_CLASS_DEFAULT,
                     check.telegram_status)
    return Actor(int(telegram_id), chat_id, ROLE_MEMBER, AUTH_UNVERIFIED,
                 R_DENY_AUTH_UNVERIFIED, check.telegram_status)


# ── Матрица: дефолт класса, перекрытия, эффективное состояние ──────────────

def default_diag_matrix(capability: Capability) -> dict[str, list[str]]:
    """Дефолт матрицы роль×действие для возможности (ТЗ §7.2 таблица)."""
    empty = {"view_roles": [], "run_roles": [], "edit_roles": []}
    if capability.data_class in (PUBLIC_TECH, CHAT_SCOPED):
        view = ["user", "local_admin"]
        run = ["user", "local_admin"] if "run" in capability.actions else []
        return {"view_roles": view, "run_roles": run, "edit_roles": []}
    if capability.data_class == PROMPT_CONTENT:
        # Участник не получает промпты никогда (жёсткое правило ниже).
        return {"view_roles": ["local_admin"], "run_roles": [],
                "edit_roles": []}
    return empty


def effective_diag_matrix(capability: Capability,
                          global_override: dict | None = None,
                          chat_override: dict | None = None) -> dict:
    """Дефолт ⊕ глобальное перекрытие ⊕ чат-перекрытие (замена массивов)."""
    from services import access as access_srv
    matrix = default_diag_matrix(capability)
    for override in (global_override, chat_override):
        if not isinstance(override, dict) or not override:
            continue
        matrix = access_srv.normalize_diag_matrix(override, matrix)
    return matrix


def _matrix_source(global_override: dict | None,
                   chat_override: dict | None) -> str:
    if isinstance(chat_override, dict) and chat_override:
        return SOURCE_CHAT_OVERRIDE
    if isinstance(global_override, dict) and global_override:
        return SOURCE_GLOBAL_OVERRIDE
    return SOURCE_CLASS_DEFAULT


# ── Вычисление решения ─────────────────────────────────────────────────────

async def evaluate(capability_id: str, action: str, actor: Actor, *,
                   pg=None, cache=None, chat_id: int | None = None,
                   resource_chat_id: int | None = None,
                   global_overrides: dict | None = None,
                   chat_overrides: dict | None = None) -> Decision:
    """Вычислить решение по контракту (актор, скоуп, класс, действие)."""
    capability = CAPABILITY_MAP.get(capability_id)
    if capability is None:
        return _decision(EFFECT_DENY, R_DENY_UNKNOWN_CAPABILITY, actor,
                         capability_id, action, "")

    if action not in capability.actions:
        return _decision(EFFECT_DENY, R_DENY_ACTION_UNSUPPORTED, actor,
                         capability_id, action, capability.data_class)

    # 1. Абсолютные запреты (не настраиваются тумблерами).
    if capability.data_class == SECRET_VALUE:
        return _decision(EFFECT_DENY, R_DENY_SECRET, actor, capability_id,
                         action, capability.data_class,
                         source=SOURCE_HARD_RULE)
    if capability.data_class == PROMPT_CONTENT and actor.role == ROLE_MEMBER \
            and actor.verification != AUTH_UNVERIFIED:
        return _decision(EFFECT_DENY, R_DENY_PROMPT_MEMBER, actor,
                         capability_id, action, capability.data_class,
                         source=SOURCE_HARD_RULE)
    if capability.data_class in PROTECTED_CLASSES \
            and actor.telegram_id is None:
        return _decision(EFFECT_DENY, R_DENY_NO_IDENTITY, actor,
                         capability_id, action, capability.data_class,
                         source=SOURCE_HARD_RULE)
    if capability.data_class in PROTECTED_CLASSES \
            and actor.verification == AUTH_UNVERIFIED:
        return _decision(EFFECT_UNVERIFIED, R_DENY_AUTH_UNVERIFIED, actor,
                         capability_id, action, capability.data_class,
                         source=SOURCE_HARD_RULE)
    if capability.data_class == OTHER_CHAT_DATA:
        same_scope = (resource_chat_id is None
                      or (actor.chat_id is not None
                          and int(resource_chat_id) == int(actor.chat_id)))
        if not (actor.is_owner and same_scope):
            return _decision(EFFECT_DENY, R_DENY_OTHER_CHAT, actor,
                             capability_id, action, capability.data_class,
                             source=SOURCE_HARD_RULE)

    # 2. Матрица (дефолт ⊕ перекрытия) — уже существующий слой прав.
    if global_overrides is None and pg is not None:
        from services import access as access_srv
        global_overrides = await access_srv.diag_global_overrides(pg)
    if chat_overrides is None and chat_id is not None and pg is not None:
        from services import access as access_srv
        chat_overrides = await access_srv.diag_chat_overrides(chat_id, pg=pg)

    cap_global = (global_overrides or {}).get(capability_id)
    cap_chat = (chat_overrides or {}).get(capability_id)
    matrix = effective_diag_matrix(capability, cap_global, cap_chat)
    source = _matrix_source(cap_global, cap_chat)

    # Владелец — неявное разрешение (кроме разобранных жёстких запретов).
    if actor.is_owner:
        return _decision(EFFECT_ALLOW, R_ALLOW_OWNER, actor, capability_id,
                         action, capability.data_class,
                         source=SOURCE_IMPLICIT_OWNER)

    field = _action_field(action)
    allowed = actor.matrix_role in matrix.get(field, [])
    if allowed:
        reason = (R_ALLOW_CHAT_OVERRIDE if source == SOURCE_CHAT_OVERRIDE
                  else (R_ALLOW_GLOBAL_OVERRIDE
                        if source == SOURCE_GLOBAL_OVERRIDE
                        else R_ALLOW_CHAT_ADMIN if actor.is_chat_admin
                        else R_ALLOW_PUBLIC))
        return _decision(EFFECT_ALLOW, reason, actor, capability_id, action,
                         capability.data_class, source=source)

    reason = {
        SOURCE_CHAT_OVERRIDE: R_DENY_CHAT_OVERRIDE,
        SOURCE_GLOBAL_OVERRIDE: R_DENY_GLOBAL_OVERRIDE,
    }.get(source, R_DENY_CLASS_DEFAULT)
    return _decision(EFFECT_DENY, reason, actor, capability_id, action,
                     capability.data_class, source=source)


def _action_field(action: str) -> str:
    from services import access as access_srv
    return access_srv.DIAG_ACTION_FIELD.get(action, "view_roles")


#: Строки матрицы, различия между которыми требуют живой проверки личности.
_MATRIX_ROLE_USER = "user"
_MATRIX_ROLE_LOCAL_ADMIN = "local_admin"


async def _policy_overrides(*, pg=None, chat_id: int | None = None,
                            ) -> tuple[dict, dict]:
    """Перекрытия матрицы (глобальные + чат) — один чтение на решение."""
    from services import access as access_srv
    global_overrides: dict = {}
    chat_overrides: dict = {}
    if pg is not None:
        global_overrides = await access_srv.diag_global_overrides(pg)
        if chat_id is not None:
            chat_overrides = await access_srv.diag_chat_overrides(chat_id,
                                                                  pg=pg)
    return global_overrides or {}, chat_overrides or {}


def _needs_chat_admin_identity(requirements: tuple[tuple[str, str], ...],
                               global_overrides: dict,
                               chat_overrides: dict) -> bool:
    """Нужна ли живая проверка «админ именно этого чата».

    Проверка нужна там, где решение РАЗЛИЧАЕТ участника и админа чата: то
    есть в эффективной матрице `local_admin` разрешён, а `user` — нет. Это
    выполняется для всех классов данных, а не только для PROMPT_CONTENT:
    настраиваемая строка `local_admin` обязана работать в любом классе.
    """
    for capability_id, action in requirements:
        capability = CAPABILITY_MAP.get(capability_id)
        if capability is None or action not in capability.actions:
            continue
        matrix = effective_diag_matrix(
            capability, global_overrides.get(capability_id),
            chat_overrides.get(capability_id))
        roles = matrix.get(_action_field(action)) or []
        if _MATRIX_ROLE_LOCAL_ADMIN in roles \
                and _MATRIX_ROLE_USER not in roles:
            return True
    return False


async def _resolve_actor_for(requirements: tuple[tuple[str, str], ...], *,
                             telegram_id: int | None, chat_id: int | None,
                             cache=None, bot=None, pg=None,
                             fresh_telegram: bool = False,
                             ) -> tuple[Actor, dict, dict]:
    """Актор с учётом эффективной матрицы + прочитанные перекрытия."""
    global_overrides, chat_overrides = await _policy_overrides(
        pg=pg, chat_id=chat_id)
    caps = [CAPABILITY_MAP.get(capability) for capability, _act in requirements]
    protected = any(c is not None and c.data_class in PROTECTED_CLASSES
                    for c in caps)
    check_admin = protected or _needs_chat_admin_identity(
        requirements, global_overrides, chat_overrides)
    actor = await resolve_actor(telegram_id, chat_id, cache=cache, bot=bot,
                                check_admin=check_admin,
                                fresh_telegram=fresh_telegram)
    return actor, global_overrides, chat_overrides


def _decision(effect: str, reason: str, actor: Actor, capability: str,
              action: str, data_class: str, *, source: str = SOURCE_HARD_RULE,
              ) -> Decision:
    return Decision(
        effect=effect,
        reason_code=reason,
        message_ru=explain_reason(reason, actor=actor,
                                  data_class=data_class, action=action),
        capability=capability,
        action=action,
        data_class=data_class,
        role=actor.role,
        matrix_role=actor.matrix_role,
        source=source,
        actor=actor,
    )


_EXPLANATIONS: dict[str, str] = {
    R_ALLOW_PUBLIC: ("Техническая информация этого класса открыта участникам: "
                     "это не секрет и не данные другого чата."),
    R_ALLOW_CHAT_ADMIN: ("Админ этого чата подтверждён Telegram и получает "
                         "доступ к данным, относящимся к его чату."),
    R_ALLOW_OWNER: ("Владелец бота подтверждён по настроенному Telegram ID; "
                    "для него действуют только абсолютные запреты."),
    R_ALLOW_GLOBAL_OVERRIDE: "Доступ выдан настройкой матрицы доступов.",
    R_ALLOW_CHAT_OVERRIDE: "Доступ выдан настройкой матрицы для этого чата.",
    R_DENY_CLASS_DEFAULT: ("Роль не входит в список разрешённых для этой "
                           "возможности по правилу класса данных."),
    R_DENY_GLOBAL_OVERRIDE: "Доступ закрыт настройкой матрицы доступов.",
    R_DENY_CHAT_OVERRIDE: "Доступ закрыт настройкой матрицы для этого чата.",
    R_DENY_PROMPT_MEMBER: ("Текст промптов доступен только администратору "
                           "этого чата по явному запросу; участникам он не "
                           "выдаётся."),
    R_DENY_SECRET: ("Значения секретов (ключи, токены, пароли, приватные "
                    "ключи) не выдаются никому, включая владельца. Видны "
                    "только наличие и статус настройки."),
    R_DENY_AUTH_UNVERIFIED: ("Не удалось проверить полномочия через Telegram "
                             "(бот не администратор группы или ошибка API). "
                             "Защищённые данные не выдаются; публичная "
                             "диагностика остаётся доступной."),
    R_DENY_OTHER_CHAT: ("Это данные другого чата: доступ к ним не возникает "
                        "автоматически, даже по точному имени."),
    R_DENY_ACTION_UNSUPPORTED: "Такое действие для возможности не предусмотрено.",
    R_DENY_UNKNOWN_CAPABILITY: "Неизвестная диагностическая возможность.",
    R_DENY_NO_IDENTITY: ("Отправителя нельзя достоверно определить "
                         "(анонимный админ/сообщение канала), поэтому "
                         "защищённые данные не выдаются."),
    R_DENY_POLICY_UNAVAILABLE: ("Слой прав недоступен, поэтому проверить "
                                "разрешение нельзя: диагностические данные "
                                "не выдаются."),
}


def explain_reason(reason_code: str, *, actor: Actor | None = None,
                   data_class: str = "", action: str = "") -> str:
    text = _EXPLANATIONS.get(reason_code, "Решение принято политикой доступа.")
    if data_class:
        title = DATA_CLASS_TITLES_RU.get(data_class)
        if title and reason_code in (R_ALLOW_PUBLIC, R_DENY_CLASS_DEFAULT):
            return f"{text} Класс данных: «{title}»."
    return text


# ── Публичный вход: решение + аудит ───────────────────────────────────────

async def decide(capability_id: str, action: str, *, telegram_id: int | None,
                 chat_id: int | None, cache=None, bot=None, pg=None,
                 fresh_telegram: bool = False,
                 destination: str = "reply",
                 request_id: str | None = None,
                 resource_chat_id: int | None = None) -> Decision:
    """Полный путь «актор → матрица → решение» с записью в аудит.

    Живая проверка Telegram выполняется не только для protected-классов, но
    и везде, где эффективная матрица различает `user` и `local_admin`:
    иначе настраиваемая строка «админ этого чата» не работала бы в
    публичных/чатовых классах.
    """
    requirements = ((capability_id, action),)
    actor, global_overrides, chat_overrides = await _resolve_actor_for(
        requirements, telegram_id=telegram_id, chat_id=chat_id, cache=cache,
        bot=bot, pg=pg, fresh_telegram=fresh_telegram)
    decision = await evaluate(capability_id, action, actor, pg=pg,
                              cache=cache, chat_id=chat_id,
                              resource_chat_id=resource_chat_id,
                              global_overrides=global_overrides,
                              chat_overrides=chat_overrides)
    _audit("decision", request_id=request_id, actor_id=actor.telegram_id,
           chat_id=chat_id, capability=capability_id, action=action,
           role=actor.role, verification=actor.verification,
           effect=decision.effect, reason_code=decision.reason_code,
           source=decision.source, destination=destination)
    if decision.effect != EFFECT_ALLOW:
        _audit("denial", request_id=request_id, actor_id=actor.telegram_id,
               chat_id=chat_id, capability=capability_id, action=action,
               role=actor.role, effect=decision.effect,
               reason_code=decision.reason_code, source=decision.source,
               destination=destination)
    return decision


async def check_tool_call(tool_name: str, *, telegram_id: int | None,
                          chat_id: int | None, cache=None, bot=None, pg=None,
                          request_id: str | None = None,
                          destination: str = "tool",
                          fresh_telegram: bool = False) -> Decision | None:
    """Проверка инструмента перед выполнением и перед возвратом результата.

    `None` — инструмент не диагностический (политика его не гейтит).
    `fresh_telegram=True` на перепроверке: отзыв админства действует на уже
    запущенный вызов, поэтому кэш Telegram не используется.
    """
    capability_id = TOOL_CAPABILITIES.get(tool_name)
    if capability_id is None:
        return None
    action = TOOL_ACTIONS.get(tool_name, "run")
    decision = await decide(capability_id, action, telegram_id=telegram_id,
                            chat_id=chat_id, cache=cache, bot=bot, pg=pg,
                            request_id=request_id, destination=destination,
                            fresh_telegram=fresh_telegram)
    _audit("diag_call", tool=tool_name, request_id=request_id,
           actor_id=telegram_id, chat_id=chat_id,
           capability=capability_id, action=action, role=decision.role,
           effect=decision.effect, reason_code=decision.reason_code,
           source=decision.source, destination=destination)
    return decision


def denial_message(decision: Decision, *, tool_name: str | None = None) -> str:
    """Короткий отказ для чата: без фрагментов защищённых данных."""
    prefix = f"ОШИБКА {tool_name}: " if tool_name else "Отказано: "
    return f"{prefix}{decision.message_ru} [{decision.reason_code}]"


def policy_unavailable_denial(capability_id: str, action: str, *,
                              chat_id: int | None = None) -> Decision:
    """Отказ, когда слой прав недоступен: проверить запрет нельзя.

    Fail-closed: вызывающий обязан НЕ выдавать диагностические данные
    (публикация/сырой вывод), а не продолжать «как будто разрешено».
    """
    capability = CAPABILITY_MAP.get(capability_id)
    actor = Actor(None, chat_id, ROLE_MEMBER, AUTH_UNVERIFIED,
                  R_DENY_POLICY_UNAVAILABLE)
    return _decision(EFFECT_DENY, R_DENY_POLICY_UNAVAILABLE, actor,
                     capability_id, action,
                     capability.data_class if capability else "")


# ── Шлюз с перепроверкой перед возвратом/публикацией ──────────────────────

def audit_prompt_disclosure(*, request_id: str | None, actor_id: int | None,
                            chat_id: int | None, prompt_id: str,
                            revision: str | int | None,
                            destination: str = "group") -> None:
    """Безопасная запись раскрытия промпта (ТЗ §7.2): без текста промпта.

    Вызывается путём readback (D5) сразу после успешной авторизованной
    выдачи: фиксируются `disclosure_actor`, `chat_id`, `prompt_id`,
    `revision`, `destination`.
    """
    _audit("prompt_disclosure", request_id=request_id, actor_id=actor_id,
           disclosure_actor=actor_id, chat_id=chat_id, capability="prompts",
           prompt_id=str(prompt_id), prompt_revision=revision,
           destination=destination, effect=EFFECT_ALLOW)


@dataclasses.dataclass
class DiagnosticGate:
    """Открытое разрешение на проверку (с точкой перепроверки).

    `requirements` — все возможности, которые нужны для публикации
    результата (например, чекап = «состояние бота» + «право видеть логи»).
    Перепроверка перед публикацией обязана подтвердить каждую из них.
    """

    request_id: str
    capability: str
    action: str
    actor: Actor
    decision: Decision
    destination: str
    opened_at: str
    generation: int
    requirements: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "capability": self.capability,
            "action": self.action,
            "requirements": [list(item) for item in self.requirements],
            "role": self.actor.role,
            "chat_id": self.actor.chat_id,
            "destination": self.destination,
            "opened_at": self.opened_at,
            "policy_generation": self.generation,
        }


@dataclasses.dataclass(frozen=True)
class Publication:
    """Итог доставки защищённого результата."""

    allowed: bool
    text: str
    decision: Decision
    redaction: projection.RedactionReport

    @property
    def status(self) -> str:
        if not self.allowed:
            return "denied" if not self.decision.allowed else "blocked"
        return self.redaction.status


async def open_gate(capability_id: str, action: str, *,
                    telegram_id: int | None, chat_id: int | None,
                    cache=None, bot=None, pg=None,
                    destination: str = "reply",
                    also: tuple[tuple[str, str], ...] = ()) -> DiagnosticGate:
    """Открыть разрешение: решение фиксируется до чтения ресурса.

    `also` — дополнительные требования к тому же результату (например,
    право видеть логи для чекапа). Любое нарушение → решающее `deny`.
    """
    request_id = uuid.uuid4().hex
    requirements = ((capability_id, action),) + tuple(also)
    actor, global_overrides, chat_overrides = await _resolve_actor_for(
        requirements, telegram_id=telegram_id, chat_id=chat_id, cache=cache,
        bot=bot, pg=pg)
    decisions = [
        await evaluate(cap, act, actor, pg=pg, cache=cache, chat_id=chat_id,
                       global_overrides=global_overrides,
                       chat_overrides=chat_overrides)
        for cap, act in requirements
    ]
    decision = next((d for d in decisions if not d.allowed), decisions[0])
    _audit("gate_open", request_id=request_id, actor_id=telegram_id,
           chat_id=chat_id, capability=decision.capability,
           action=decision.action, role=actor.role,
           verification=actor.verification, effect=decision.effect,
           reason_code=decision.reason_code, source=decision.source,
           destination=destination, generation=_policy_generation)
    return DiagnosticGate(
        request_id=request_id,
        capability=capability_id,
        action=action,
        actor=actor,
        decision=decision,
        destination=destination,
        opened_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        generation=_policy_generation,
        requirements=requirements,
    )


async def recheck_gate(gate: DiagnosticGate, *, cache=None, bot=None, pg=None,
                       fresh_telegram: bool = True) -> Decision:
    """Перепроверить решение ПЕРЕД возвратом защищённого результата.

    Отзыв прав (смена админства в Telegram, изменение матрицы, revocation)
    действует на уже запущенную проверку: решение пересчитывается заново по
    актуальным источникам, без опоры на старый TTL. Живая проверка Telegram
    выполняется и здесь — в том числе для публичных/чатовых классов, если
    эффективная матрица различает `user` и `local_admin`.
    """
    requirements = gate.requirements or ((gate.capability, gate.action),)
    actor, global_overrides, chat_overrides = await _resolve_actor_for(
        requirements, telegram_id=gate.actor.telegram_id,
        chat_id=gate.actor.chat_id, cache=cache, bot=bot, pg=pg,
        fresh_telegram=fresh_telegram)
    decisions = [
        await evaluate(cap, act, actor, pg=pg, cache=cache,
                       chat_id=gate.actor.chat_id,
                       global_overrides=global_overrides,
                       chat_overrides=chat_overrides)
        for cap, act in requirements
    ]
    decision = next((d for d in decisions if not d.allowed), decisions[0])
    event = "gate_recheck"
    if gate.decision.effect == EFFECT_ALLOW \
            and decision.effect != EFFECT_ALLOW:
        event = "revocation_detected"
    _audit(event, request_id=gate.request_id, actor_id=actor.telegram_id,
           chat_id=gate.actor.chat_id, capability=decision.capability,
           action=decision.action, role=actor.role,
           verification=actor.verification, effect=decision.effect,
           reason_code=decision.reason_code, source=decision.source,
           destination=gate.destination)
    return decision


async def publish(gate: DiagnosticGate, text: str, *, cache=None, bot=None,
                  pg=None, kind: str = "final",
                  secrets: dict[str, str] | None = None,
                  fresh_telegram: bool = True) -> Publication:
    """Финальная проверка перед доставкой: права + удаление секретов.

    Порядок: перепроверка прав (revocation) → структурная санитизация →
    доставка. Если права отозваны — текст не публикуется вообще.
    """
    decision = await recheck_gate(gate, cache=cache, bot=bot, pg=pg,
                                  fresh_telegram=fresh_telegram)
    if decision.effect != EFFECT_ALLOW:
        return Publication(False, "",
                           decision,
                           projection.RedactionReport(
                               projection.STATUS_BLOCKED, 0, (),
                               "revoked_before_publication"))
    if secrets is None:
        secrets = await projection.known_secret_values_async(
            cache=cache, pg=pg, chat_id=gate.actor.chat_id)
    result = projection.sanitize(text, kind=kind, secrets=secrets)
    _audit("publication", request_id=gate.request_id,
           actor_id=gate.actor.telegram_id, chat_id=gate.actor.chat_id,
           capability=gate.capability, action=gate.action,
           role=decision.role, effect=decision.effect,
           reason_code=decision.reason_code, destination=gate.destination,
           redaction_status=result.report.status,
           redacted=result.report.redacted)
    return Publication(result.allowed, result.text, decision, result.report)


# ── Матрица/объяснения для админки ────────────────────────────────────────

def roles_legend() -> list[dict]:
    """Роли матрицы: участник, админ чата, владелец (неявный)."""
    return [
        {"id": "user", "title": "Участник",
         "note": "Любой участник текущего чата или личного диалога"},
        {"id": "local_admin", "title": "Админ этого чата",
         "note": "Подтверждается Telegram getChatMember (administrator/creator)"},
        {"id": "global_admin", "title": "Владелец бота",
         "note": "Неявно всегда (настроенный numeric Telegram ID)",
         "implicit": True},
    ]


def capabilities_public() -> list[dict]:
    """Каталог возможностей (без решений) для админки."""
    return [
        {
            "id": c.id,
            "title": c.title_ru,
            "data_class": c.data_class,
            "data_class_title": DATA_CLASS_TITLES_RU.get(c.data_class,
                                                         c.data_class),
            "actions": list(c.actions),
            "description": c.description_ru,
            "tool_names": list(c.tool_names),
            "secret_class": c.data_class == SECRET_VALUE,
        }
        for c in CAPABILITIES
    ]


async def matrix_snapshot(*, pg=None, chat_id: int | None = None) -> dict:
    """Матрица с наследованием: дефолт ⊕ глобальное ⊕ чат-перекрытие."""
    from services import access as access_srv
    global_ov = await access_srv.diag_global_overrides(pg) if pg is not None else {}
    chat_ov = (await access_srv.diag_chat_overrides(chat_id, pg=pg)
               if chat_id is not None and pg is not None else {})
    items = {}
    for capability in CAPABILITIES:
        g = global_ov.get(capability.id)
        c = chat_ov.get(capability.id)
        default = default_diag_matrix(capability)
        effective = effective_diag_matrix(capability, g, c)
        items[capability.id] = {
            "title": capability.title_ru,
            "description": capability.description_ru,
            "data_class": capability.data_class,
            "data_class_title": DATA_CLASS_TITLES_RU.get(capability.data_class),
            "actions": list(capability.actions),
            "tool_names": list(capability.tool_names),
            "default": default,
            "global_override": g or None,
            "chat_override": c or None,
            "effective": effective,
            "source": _matrix_source(g, c),
            "configurable": capability.data_class != SECRET_VALUE,
            "hard_rules": _hard_rules(capability),
        }
    return {
        "items": items,
        "roles": roles_legend(),
        "actions": list(access_srv.DIAG_ACTIONS),
        "chat_id": chat_id,
        "generation": _policy_generation,
        "secret_policy": {
            "effect": EFFECT_DENY,
            "configurable": False,
            "note": ("Значения секретов не выдаются никому, включая владельца; "
                     "настройки показывают только наличие и статус."),
        },
        "chat_admin_verification": {
            "source": "telegram_get_chat_member",
            "statuses": sorted(role_check.ADMIN_STATUSES),
            "note": ("Статус администратора проверяется онлайн по числовому "
                     "Telegram ID; имя, username и пересланные сообщения "
                     "не учитываются."),
        },
    }


def _hard_rules(capability: Capability) -> list[dict]:
    rules: list[dict] = []
    if capability.data_class == SECRET_VALUE:
        rules.append({"rule": R_DENY_SECRET,
                      "message": _EXPLANATIONS[R_DENY_SECRET]})
    if capability.data_class == PROMPT_CONTENT:
        rules.append({"rule": R_DENY_PROMPT_MEMBER,
                      "message": _EXPLANATIONS[R_DENY_PROMPT_MEMBER]})
    if capability.data_class == OTHER_CHAT_DATA:
        rules.append({"rule": R_DENY_OTHER_CHAT,
                      "message": _EXPLANATIONS[R_DENY_OTHER_CHAT]})
    return rules


async def explain_for(telegram_id: int | None, chat_id: int | None, *,
                      cache=None, bot=None, pg=None,
                      capability: str | None = None,
                      fresh_telegram: bool = False) -> dict:
    """Почему конкретному пользователю разрешено/отказано (для админки)."""
    targets = ([CAPABILITY_MAP[capability]] if capability in CAPABILITY_MAP
               else list(CAPABILITIES))
    requirements = tuple((cap.id, act) for cap in targets for act in cap.actions)
    actor, global_overrides, chat_overrides = await _resolve_actor_for(
        requirements, telegram_id=telegram_id, chat_id=chat_id, cache=cache,
        bot=bot, pg=pg, fresh_telegram=fresh_telegram)
    decisions = []
    for cap in targets:
        per_action = []
        for action in cap.actions:
            decision = await evaluate(cap.id, action, actor, pg=pg,
                                      cache=cache, chat_id=chat_id,
                                      global_overrides=global_overrides,
                                      chat_overrides=chat_overrides)
            per_action.append(decision.as_dict())
        decisions.append({
            "capability": cap.id,
            "title": cap.title_ru,
            "data_class": cap.data_class,
            "actions": per_action,
        })
    return {
        "telegram_id": telegram_id,
        "chat_id": chat_id,
        "role": actor.role,
        "role_title": ROLE_TITLES_RU.get(actor.role, actor.role),
        "verification": actor.verification,
        "telegram_status": actor.telegram_status,
        "decisions": decisions,
        "generation": _policy_generation,
    }


def effective_state() -> dict:
    """Текущее состояние политики процесса (для аудита/диагностики)."""
    return {
        "generation": _policy_generation,
        "capabilities": [c.id for c in CAPABILITIES],
        "secret_class_denied_always": True,
        "chat_admin_source": "telegram_get_chat_member",
        "audit_records": len(_audit_log),
        "audit_limit": _AUDIT_MAX,
    }
