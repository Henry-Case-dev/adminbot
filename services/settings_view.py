"""SELF-DIAG-01 D2-24 (`SD1-D2-24`) — typed settings adapter.

ТЗ §9.1: «Секретный blob никогда не сериализуется в DiagnosticEvidenceBundle
или обычный ToolResult. При технической проверке возвращаются `configured`,
`effective`, `last_success`, `last_error_code`, `key_fingerprint` (только если
уже безопасно принят проектом), но не value».

Модуль — единственный адаптер между типизированным хранилищем настроек и
диагностикой:

  * имя записи, тип чувствительности и происхождение типа;
  * `configured` — есть ли действующее значение;
  * `effective` — действующее значение ТОЛЬКО для классов
    `NON_SECRET_CONFIG`/`PUBLIC_DIAGNOSTIC`; для `SECRET_VALUE` и
    `PROMPT_CONTENT` это статус-токен (`configured`/`not_configured`), а
    само значение не покидает backend;
  * `last_success`/`last_error_code` — из УЖЕ существующих наблюдаемых
    исходов (`capability_registry.capability_view`: `last_result`,
    `last_result_code`, `checked_at`); второго стора нет;
  * `key_fingerprint` — `last4` (уже принятая проектом безопасная форма,
    `output_projection.project_secret_value`), только для скалярных
    `SECRET_VALUE` длиной ≥ `MIN_FINGERPRINT_LEN`; для промптов и списков
    фингерпринт не выдаётся.

Ни сети, ни БД, ни LLM, ни записи: только чтение действующих источников.
Секретных значений модуль не возвращает по контракту (не «по фильтру»):
для защищённых классов значение не попадает в результат вообще.
"""
from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

from services import param_catalog as catalog
from services import output_projection

#: Классы, чьё значение не выдаётся диагностикой ни на одном маршруте.
PROTECTED_SENSITIVITIES: frozenset[str] = frozenset({
    catalog.SENSITIVITY_SECRET, catalog.SENSITIVITY_PROMPT_CONTENT,
})

EFFECTIVE_KIND_VALUE = "value"
EFFECTIVE_KIND_STATUS = "status"
EFFECTIVE_CONFIGURED = "configured"
EFFECTIVE_NOT_CONFIGURED = "not_configured"

FINGERPRINT_KIND_LAST4 = "last4"
FINGERPRINT_KIND_NONE = "none"

#: Минимальная длина значения, у которого вообще показываем `last4`:
#: короткие значения фингерпринтом раскрывались бы почти целиком.
MIN_FINGERPRINT_LEN = 8

SOURCE_CACHE = "pg"
SOURCE_ENV = "env"
SOURCE_SETTINGS = "settings"
SOURCE_NONE = "none"

SENSITIVITY_SOURCE_CREDENTIALS = "credential_registry"

REASON_UNCLASSIFIED = "unclassified_key"
REASON_LIST_VALUE = "list_value_no_fingerprint"
REASON_PROMPT_NO_FINGERPRINT = "prompt_content_no_fingerprint"
REASON_SHORT_VALUE = "short_value_no_fingerprint"

#: Закрытый набор полей результата (тест сверяет наличие всех).
VIEW_FIELDS: tuple[str, ...] = (
    "key", "classified", "sensitivity", "sensitivity_source", "configured",
    "effective", "effective_kind", "effective_source", "value_exposed",
    "last_success", "last_error_code", "last_checked_at", "outcome_observed",
    "key_fingerprint", "fingerprint_kind", "reason_code",
)

_CREDENTIAL_BY_PG: dict[str, output_projection.CredentialField] = {
    field.pg_key: field for field in output_projection.CREDENTIAL_FIELDS
}


# ── Действующее значение (без раскрытия) ──────────────────────────────────

def _json_safe(value: Any) -> Any:
    """Только JSON-типы: probe не должен нести bytes/объекты."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def _settings_field_for(spec, pg_key: str) -> str | None:
    if spec is not None and spec.settings_field:
        return spec.settings_field
    field = _CREDENTIAL_BY_PG.get(pg_key)
    return field.settings_field if field is not None else None


def _env_name_for(spec, pg_key: str) -> str | None:
    if spec is not None and spec.env_name:
        return spec.env_name
    field = _CREDENTIAL_BY_PG.get(pg_key)
    return field.settings_field if field is not None else None


def _resolve_value(pg_key: str, spec, cache) -> tuple[Any, str]:
    """(значение, источник): кэш настроек → env → Settings-дефолт."""
    if cache is not None:
        sentinel = object()
        try:
            raw = cache.get(pg_key, sentinel)
        except Exception:      # pragma: no cover - защитная ветка
            raw = sentinel
        if raw is not sentinel and raw is not None:
            return raw, SOURCE_CACHE
    env_name = _env_name_for(spec, pg_key)
    if env_name:
        raw = os.environ.get(env_name)
        if raw not in (None, ""):
            return raw, SOURCE_ENV
    field_name = _settings_field_for(spec, pg_key)
    if field_name:
        try:
            from config.settings import settings
            raw = getattr(settings, field_name, None)
        except Exception:      # pragma: no cover - защитная ветка
            return None, SOURCE_NONE
        if raw not in (None, ""):
            return raw, SOURCE_SETTINGS
    return None, SOURCE_NONE


def _fingerprint(value: Any, sensitivity: str) -> tuple[str | None, str, str]:
    """(`key_fingerprint`, вид, причина) — только уже безопасная форма last4."""
    if sensitivity == catalog.SENSITIVITY_PROMPT_CONTENT:
        return None, FINGERPRINT_KIND_NONE, REASON_PROMPT_NO_FINGERPRINT
    if isinstance(value, (list, tuple, set, frozenset, dict)):
        return None, FINGERPRINT_KIND_NONE, REASON_LIST_VALUE
    text = str(value or "")
    if len(text) < MIN_FINGERPRINT_LEN:
        return None, FINGERPRINT_KIND_NONE, REASON_SHORT_VALUE
    return f"…{text[-4:]}", FINGERPRINT_KIND_LAST4, ""


# ── Публичный адаптер ─────────────────────────────────────────────────────

def setting_view(pg_key: str, *, cache=None,
                 outcomes: Mapping[str, Mapping] | None = None) -> dict:
    """Безопасное типизированное представление настройки/секрета.

    `outcomes` — наблюдаемые исходы провайдеров по ключу (см.
    `capability_outcomes`), а не догадка: без записи поля остаются `None`
    с `outcome_observed=False`.
    """
    key = str(pg_key or "").strip()
    spec = catalog.get_by_pg_key(key)
    field = _CREDENTIAL_BY_PG.get(key)
    if spec is not None:
        sensitivity = spec.resolved_sensitivity
        sensitivity_source = spec.sensitivity_source
        classified = True
    elif field is not None:
        # Типизированный реестр credential-полей — часть secret store:
        # запись классифицирована как секрет, даже если каталог её не знает.
        sensitivity = catalog.SENSITIVITY_SECRET
        sensitivity_source = SENSITIVITY_SOURCE_CREDENTIALS
        classified = True
    else:
        sensitivity = catalog.SENSITIVITY_PUBLIC
        sensitivity_source = ""
        classified = False

    value, value_source = _resolve_value(key, spec, cache)
    configured = value not in (None, "", [], {})
    protected = sensitivity in PROTECTED_SENSITIVITIES

    reason = None
    if not classified:
        # Неизвестный ключ: имя и факт наличия — можно, значение — нельзя,
        # пока каталог не объявил класс.
        effective = None
        effective_kind = EFFECTIVE_KIND_STATUS
        value_exposed = False
        reason = REASON_UNCLASSIFIED
    elif protected:
        effective = (EFFECTIVE_CONFIGURED if configured
                     else EFFECTIVE_NOT_CONFIGURED)
        effective_kind = EFFECTIVE_KIND_STATUS
        value_exposed = False
    else:
        effective = _json_safe(value)
        effective_kind = EFFECTIVE_KIND_VALUE
        value_exposed = True

    outcome = dict((outcomes or {}).get(key) or {})
    if not protected:
        fingerprint, fingerprint_kind, fingerprint_reason = (
            None, FINGERPRINT_KIND_NONE, "")
    elif not configured:
        # Незаданное значение нечего фингерпринтить: причина «нет значения»,
        # а не «слишком короткое значение».
        fingerprint, fingerprint_kind, fingerprint_reason = (
            None, FINGERPRINT_KIND_NONE, "")
    else:
        fingerprint, fingerprint_kind, fingerprint_reason = _fingerprint(
            value, sensitivity)
    if reason is None and fingerprint_reason:
        reason = fingerprint_reason

    return {
        "key": key,
        "classified": bool(classified),
        "sensitivity": sensitivity,
        "sensitivity_source": sensitivity_source,
        "configured": bool(configured),
        "effective": effective,
        "effective_kind": effective_kind,
        "effective_source": value_source,
        "value_exposed": bool(value_exposed),
        "last_success": outcome.get("last_success"),
        "last_error_code": outcome.get("last_error_code"),
        "last_checked_at": outcome.get("last_checked_at"),
        "outcome_observed": bool(outcome),
        "key_fingerprint": fingerprint,
        "fingerprint_kind": fingerprint_kind,
        "reason_code": reason,
    }


def capability_outcomes(states: Iterable[Mapping] | None) -> dict[str, dict]:
    """Исходы провайдеров по pg-ключу из существующего `capability_view`.

    Источник — уже наблюдаемые `last_result`/`last_result_code`/`checked_at`
    (services.capability_registry), а не новый стор. Гейты способности — те
    же pg-ключи каталога, поэтому связь не выдумана.
    """
    outcomes: dict[str, dict] = {}
    for state in states or ():
        try:
            gates = state.get("gates") or ()
        except AttributeError:      # pragma: no cover - неверный тип элемента
            continue
        last_result = str(state.get("last_result") or "unknown")
        if last_result == "unknown":
            continue
        checked_at = state.get("checked_at")
        success = checked_at if last_result == "success" else None
        error_code = None if last_result == "success" else (
            str(state.get("last_result_code") or ""
                or state.get("reason_code") or "") or None)
        record = {
            "last_success": success,
            "last_error_code": error_code,
            "last_checked_at": checked_at,
        }
        for gate in gates:
            outcomes.setdefault(str(gate), dict(record))
    return outcomes


def secret_setting_keys() -> tuple[str, ...]:
    """Все ключи, чьи значения защищены как секрет, — из каталога и реестра."""
    keys = {spec.pg_key for spec in catalog.secret_setting_specs()}
    keys.update(_CREDENTIAL_BY_PG)
    return tuple(sorted(keys))


#: Поля компактной формы: ровно тот набор, который разрешён ТЗ §9.1 для
#: технической проверки (плюс имя, тип класса и источник действующего значения).
COMPACT_FIELDS: tuple[str, ...] = (
    "key", "sensitivity", "configured", "effective", "effective_source",
    "last_success", "last_error_code", "key_fingerprint",
)

#: Сколько секретных полей отдаётся с подробностями: budget диагностической
#: страницы (TЗ §10) не должен «съедаться» одним списком. Остальные имена
#: видны в `truncated_keys` — молчаливого усечения нет.
MAX_DETAILED_SECRETS = 20


def compact_view(view: Mapping) -> dict:
    """Подмножество типизированного представления для tool result/bundle."""
    return {name: view.get(name) for name in COMPACT_FIELDS}


def secret_status_summary(*, cache=None,
                          outcomes: Mapping[str, Mapping] | None = None,
                          views: Iterable[Mapping] | None = None,
                          max_detailed: int = MAX_DETAILED_SECRETS) -> dict:
    """Сводка состояния секретных полей без значений.

    Настроенные ключи идут с подробностями `configured/effective/
    last_success/last_error_code/key_fingerprint`; ненастроенные — только
    именами (их значения нечего проверять). Список подробностей ограничен
    `max_detailed`; остальные имена — в `truncated_keys`, то есть усечение
    наблюдаемо, а не молчаливое.
    """
    if views is None:
        views = secret_settings_view(cache=cache, outcomes=outcomes)
    views = list(views)
    configured = [view for view in views if view.get("configured")]
    limit = max(1, int(max_detailed))
    return {
        "secrets": [compact_view(view) for view in configured[:limit]],
        "not_configured": [view["key"] for view in views
                           if not view.get("configured")],
        "truncated_keys": [view["key"] for view in configured[limit:]],
        "total": len(views),
        "configured": len(configured),
        "detailed_max": limit,
        "value_exposed": False,
    }


def secret_settings_view(*, cache=None,
                         outcomes: Mapping[str, Mapping] | None = None
                         ) -> list[dict]:
    """Полный безопасный список секретных полей (in-process, не для страницы)."""
    return [setting_view(key, cache=cache, outcomes=outcomes)
            for key in secret_setting_keys()]
