"""MCA-11 (round 10.37, ADR-1028-13 D5) — денежные лимиты: `enabled=false`.

Единственный механизм новых **денежных** лимитов (второго нет; token/context/
worker-бюджеты — отдельные контуры и НЕ смешиваются: см.
`services/budget_limits.py`, `auto_budget.py`, `worker_budget.py`).

Конфиг (env-only, `config/settings.py`; Δ каталога = 0):

* master ``MCA_MONEY_LIMITS_ENABLED`` — default **OFF** (owner §20.2):
  OFF → модуль не влияет ни на один вызов (поведение 2.58.56 байт-в-байт);
* per-scope ``MCA_MONEY_LIMIT_{DIRECT,AUTONOMOUS,MAINTENANCE}_USD`` —
  sentinel-семантика REUSE `budget_limits` (**не задан** → лимита нет;
  ``0`` → запрет; ``<0`` → безлимит; ``>0`` → cap USD). Числовых дефолтов
  нет — скрытого «рекомендованного бюджета» не существует.

Семантика будущего включения (реализована и инертна при OFF):

* ``check_and_reserve(scope, estimate_usd, price_known)`` — резервирование
  ожидаемой стоимости конкурентных операций (in-process, один процесс);
  при неизвестной цене резерв НЕ делается, абсолютный потолок не обещается;
  deny только при известных ``spent + reserved >= cap`` (overshoot неточной
  оценки допускается и согласуется после ответа через ``reconcile``);
* ``reconcile(actual_usd, price_known, *, scope=...)`` — согласование
  остатка: резерв операции снимается, факт (если известен) добавляется в
  spent; приоритет ``direct > autonomous > maintenance``, при исчерпании
  сначала уменьшается необязательная инициатива/фон
  (``degradation_order()``);
* лимит останавливает платные вызовы (решение ``allowed=False`` +
  reason_code ``financial_limit_reached`` — контракт ToolResult `denied`),
  но НЕ приём/сохранение исходных сообщений: intake-пути этот модуль не
  вызывают (второго intake-гейта нет);
* существующие явные финансовые настройки владельца НЕ стираются
  (unit/вызовные лимиты image/worker/chat) — показываются в
  ``effective_state()`` с отличием от валютных бюджетов; UI-рендер — mca-17c.

Потребители потребления — mca-09/10b (гейт+семантика даёт этот модуль).
R17: только числа/коды/scope; никаких промптов, текстов, ключей.
"""
from __future__ import annotations

import collections
import dataclasses
import logging
import threading

from config.settings import settings
from services import budget_limits

logger = logging.getLogger(__name__)

# ── scope'ы (закрытый набор; отдельно direct/autonomous/maintenance) ────────
SCOPE_DIRECT = "direct"
SCOPE_AUTONOMOUS = "autonomous"
SCOPE_MAINTENANCE = "maintenance"
SCOPES = (SCOPE_DIRECT, SCOPE_AUTONOMOUS, SCOPE_MAINTENANCE)

#: Приоритет: direct > autonomous > maintenance (меньше = важнее).
PRIORITY = {SCOPE_DIRECT: 0, SCOPE_AUTONOMOUS: 1, SCOPE_MAINTENANCE: 2}

#: Порядок уменьшения при исчерпании: сначала необязательная инициатива/фон.
DEGRADATION_ORDER = (SCOPE_MAINTENANCE, SCOPE_AUTONOMOUS, SCOPE_DIRECT)

REASON_FINANCIAL_LIMIT_REACHED = "financial_limit_reached"
REASON_JOB_NOT_ALLOWED = "job_not_allowed"

_SCOPE_ENV = {
    SCOPE_DIRECT: "MCA_MONEY_LIMIT_DIRECT_USD",
    SCOPE_AUTONOMOUS: "MCA_MONEY_LIMIT_AUTONOMOUS_USD",
    SCOPE_MAINTENANCE: "MCA_MONEY_LIMIT_MAINTENANCE_USD",
}

#: Существующие явные финансовые настройки владельца (НЕ стираются):
#: unit/вызовные/токенные лимиты — не валютные бюджеты; отличие показывается
#: в `effective_state()` (UI — mca-17c). Значения читаются per-call.
OWNER_SETTINGS = (
    ("IMAGE_DAILY_LIMIT_ENABLED", "unit_calls",
     "атомарный резерв дневного лимита изображений (вызовы; ON/OFF)"),
    ("WORKER_DAILY_IMAGE_CALLS_PER_CHAT", "unit_calls",
     "image-вызовы на чат в сутки"),
    ("WORKER_DAILY_IMAGE_CALLS_GLOBAL", "unit_calls",
     "image-вызовы глобально в сутки"),
    ("CHAT_GLOBAL_KEY_BUDGET_TOKENS", "tokens",
     "токены глобального ключа на чат в сутки (chat_usage)"),
    ("CHAT_GLOBAL_KEY_BUDGET_REQUESTS", "requests",
     "запросы глобального ключа на чат в сутки (chat_usage)"),
    ("WORKER_DAILY_LLM_CALLS_GLOBAL", "calls",
     "LLM-вызовы фона глобально в сутки (worker_budget)"),
    ("WORKER_DAILY_LLM_TOKENS_GLOBAL", "tokens",
     "токены фона глобально в сутки (worker_budget)"),
    ("WORKER_DAILY_LLM_CALLS_PER_CHAT", "calls",
     "LLM-вызовы фона на чат в сутки (worker_budget)"),
    ("WORKER_DAILY_LLM_TOKENS_PER_CHAT", "tokens",
     "токены фона на чат в сутки (worker_budget)"),
)

#: Отличие новых лимитов от существующих настроек владельца (контракт; UI —
#: mca-17c). Новые — валютные бюджеты по scope; старые — единицы/вызовы/токены.
OWNER_SETTINGS_NOTE = (
    "Существующие настройки владельца — unit/вызовные/токенные лимиты "
    "(image/worker/chat), не валютные бюджеты; не стираются и не "
    "переклассифицируются. Новые MCA_MONEY_LIMIT_* — только USD и только "
    "по scope direct/autonomous/maintenance (этот модуль)."
)


@dataclasses.dataclass
class ScopeLedger:
    """In-process состояние одного scope (spent/reserved/unknown-in-flight)."""

    spent_usd: float = 0.0
    reserved_usd: float = 0.0
    #: FIFO-очередь резервов (оценок) — для согласования остатка.
    reservations: collections.deque = dataclasses.field(
        default_factory=collections.deque)
    #: Операции с неизвестной ценой в полёте (резерв не делается).
    unknown_in_flight: int = 0


_LEDGERS: dict[str, ScopeLedger] = {}
_LOCK = threading.Lock()


# ── гейт/конфиг ─────────────────────────────────────────────────────────────

def enabled() -> bool:
    """K5 ``MCA_MONEY_LIMITS_ENABLED`` (env-only, default OFF; per-call)."""
    try:
        return bool(getattr(settings, "MCA_MONEY_LIMITS_ENABLED", False))
    except Exception:      # pragma: no cover - защитная ветка
        return False


def normalize_scope(scope) -> str | None:
    """Scope из закрытого набора либо None (неизвестный → явный отказ)."""
    value = str(scope or "").strip().lower()
    return value if value in SCOPES else None


def scope_limit_usd(scope: str):
    """Сырое env-значение лимита scope (None = не задан) — без дефолтов."""
    name = _SCOPE_ENV.get(str(scope or ""))
    if not name:
        return None
    try:
        return getattr(settings, name, None)
    except Exception:      # pragma: no cover - защитная ветка
        return None


def scope_state(scope: str) -> str:
    """``unset`` (не задан → лимита нет) | ``forbidden`` (0) | ``unlimited``
    (<0) | ``cap`` (>0) | ``invalid_scope``.

    Sentinel-семантика REUSE `budget_limits.budget_state`; отличие только в
    «не задан»: у денежного лимита это «лимита нет», а не «запрет»."""
    if normalize_scope(scope) is None:
        return "invalid_scope"
    raw = scope_limit_usd(scope)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "unset"
    return budget_limits.budget_state(raw)


def _as_usd(value):
    """Неотрицательный float USD либо None (bool/мусор/негатив → None)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return round(number, 6)


def _ledger(scope: str) -> ScopeLedger:
    ledger = _LEDGERS.get(scope)
    if ledger is None:
        ledger = ScopeLedger()
        _LEDGERS[scope] = ledger
    return ledger


def reset_state() -> None:
    """Сброс in-process леджеров (тесты/детерминизм; не трогает настройки)."""
    with _LOCK:
        _LEDGERS.clear()


# ── API: проверка/резерв, согласование, состояние ───────────────────────────

def _decision(*, allowed: bool, scope: str, state: str, reason: str = "",
              limit_usd=None, ledger: ScopeLedger | None = None,
              reservation_usd: float = 0.0) -> dict:
    spent = float(ledger.spent_usd) if ledger else 0.0
    reserved = float(ledger.reserved_usd) if ledger else 0.0
    unknown = int(ledger.unknown_in_flight) if ledger else 0
    return {
        "allowed": bool(allowed),
        "scope": str(scope),
        "state": str(state),
        "reason": str(reason or ""),
        "limit_usd": (float(limit_usd) if limit_usd is not None else None),
        "spent_usd": spent,
        "reserved_usd": reserved,
        "reservation_usd": float(reservation_usd or 0.0),
        "unknown_in_flight": unknown,
        # Абсолютный потолок не обещается, пока есть операции с неизвестной
        # ценой (резерв не делался).
        "ceiling_exact": unknown == 0,
    }


def check_and_reserve(scope, estimate_usd=None, price_known: bool = False
                      ) -> dict:
    """Проверить лимит scope и зарезервировать ожидаемую стоимость (D5).

    OFF (default) → всегда ``allowed=True`` (state ``off``), леджеры не
    трогаются. ON → deny только при ``forbidden`` (0) либо известных
    ``spent + reserved >= cap``; при неизвестной цене резерв не делается
    (``ceiling_exact=False``), overshoot неточной оценки допускается.
    Никогда не бросает."""
    try:
        scope_name = normalize_scope(scope)
        if not enabled():
            return _decision(allowed=True, scope=str(scope or ""),
                             state="off")
        if scope_name is None:
            return _decision(allowed=False, scope=str(scope or ""),
                             state="invalid_scope",
                             reason=REASON_JOB_NOT_ALLOWED)
        state = scope_state(scope_name)
        limit = scope_limit_usd(scope_name)
        with _LOCK:
            ledger = _ledger(scope_name)
            if state == "forbidden":
                return _decision(allowed=False, scope=scope_name,
                                 state=state,
                                 reason=REASON_FINANCIAL_LIMIT_REACHED,
                                 limit_usd=limit, ledger=ledger)
            if state == "cap" and (ledger.spent_usd + ledger.reserved_usd
                                   >= float(limit)):
                return _decision(allowed=False, scope=scope_name,
                                 state=state,
                                 reason=REASON_FINANCIAL_LIMIT_REACHED,
                                 limit_usd=limit, ledger=ledger)
            estimate = _as_usd(estimate_usd) if price_known else None
            reserved_now = 0.0
            if estimate is not None and estimate > 0:
                ledger.reserved_usd += estimate
                ledger.reservations.append(estimate)
                reserved_now = estimate
            elif not price_known:
                ledger.unknown_in_flight += 1
            return _decision(allowed=True, scope=scope_name, state=state,
                             limit_usd=limit, ledger=ledger,
                             reservation_usd=reserved_now)
    except Exception:      # pragma: no cover - защитная ветка (fail-open)
        logger.warning("[money_limits] check failed — fail-open | scope=%s",
                       scope)
        return _decision(allowed=True, scope=str(scope or ""), state="error")


def reconcile(actual_usd=None, price_known: bool = False, *,
              scope: str = SCOPE_DIRECT) -> dict:
    """Согласовать остаток после ответа (D5; overshoot неточной оценки).

    Снимает один резерв scope (FIFO), при известной цене добавляет факт в
    spent; при неизвестной — снимает unknown-in-flight. OFF → no-op
    (state ``off``). Никогда не бросает.

    ``scope`` — keyword (default direct): спецификация §6 фиксирует позиционные
    ``reconcile(actual_usd, price_known)``; scope обязателен для согласования
    трёх независимых scope'ов, поэтому добавлен keyword-параметром."""
    try:
        scope_name = normalize_scope(scope)
        if not enabled():
            return {"reconciled": False, "state": "off",
                    "scope": str(scope or ""), "released_usd": 0.0}
        if scope_name is None:
            return {"reconciled": False, "state": "invalid_scope",
                    "scope": str(scope or ""), "released_usd": 0.0,
                    "reason": REASON_JOB_NOT_ALLOWED}
        with _LOCK:
            ledger = _ledger(scope_name)
            released = 0.0
            if ledger.reservations:
                released = float(ledger.reservations.popleft())
                ledger.reserved_usd = max(0.0,
                                          ledger.reserved_usd - released)
            elif ledger.unknown_in_flight > 0:
                ledger.unknown_in_flight -= 1
            actual = _as_usd(actual_usd) if price_known else None
            if actual is not None:
                ledger.spent_usd += actual
            return {
                "reconciled": True,
                "state": scope_state(scope_name),
                "scope": scope_name,
                "released_usd": round(released, 6),
                "actual_usd": actual,
                "spent_usd": float(ledger.spent_usd),
                "reserved_usd": float(ledger.reserved_usd),
                "unknown_in_flight": int(ledger.unknown_in_flight),
                "ceiling_exact": ledger.unknown_in_flight == 0,
            }
    except Exception:      # pragma: no cover - защитная ветка (fail-open)
        logger.warning("[money_limits] reconcile failed — fail-open | scope=%s",
                       scope)
        return {"reconciled": False, "state": "error", "scope": str(scope or ""),
                "released_usd": 0.0}


def degradation_order() -> tuple:
    """Порядок уменьшения при исчерпании: maintenance → autonomous → direct
    (сначала необязательная инициатива/фон; direct — приоритет)."""
    return DEGRADATION_ORDER


def effective_state() -> dict:
    """Read-only состояние механизма + существующие настройки владельца.

    Показ отличия (UI-рендер — mca-17c): новые лимиты — валютные (USD) по
    scope; существующие — unit/вызовные/токенные и НЕ стираются."""
    scopes: dict = {}
    for scope in SCOPES:
        state = scope_state(scope)
        raw = scope_limit_usd(scope)
        ledger = _LEDGERS.get(scope)
        scopes[scope] = {
            "state": state,
            "env": _SCOPE_ENV[scope],
            "limit_usd": (float(raw) if isinstance(raw, (int, float))
                          and not isinstance(raw, bool) else None),
            "priority": PRIORITY[scope],
            "spent_usd": float(ledger.spent_usd) if ledger else 0.0,
            "reserved_usd": float(ledger.reserved_usd) if ledger else 0.0,
            "unknown_in_flight": int(ledger.unknown_in_flight)
            if ledger else 0,
        }
    owner: list[dict] = []
    for name, kind, note in OWNER_SETTINGS:
        try:
            value = getattr(settings, name, None)
        except Exception:      # pragma: no cover - защитная ветка
            value = None
        owner.append({"name": name, "kind": kind, "value": value,
                      "note": note})
    return {
        "enabled": enabled(),
        "scopes": scopes,
        "priority_order": list(SCOPES),
        "degradation_order": list(DEGRADATION_ORDER),
        "owner_settings": owner,
        "owner_settings_note": OWNER_SETTINGS_NOTE,
        "absolute_ceiling": False,
        "note": ("Денежные лимиты OFF (owner §20.2); при ON — резерв/overshoot/"
                 "reconcile, absolute ceiling не обещается при неизвестной "
                 "цене; intake не блокируется"),
    }
