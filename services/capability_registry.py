"""SOUL-1 / W10 (SOUL-AMD.5.11–5.18) — Runtime Capability Registry.

Единственный источник ТЕХНИЧЕСКОЙ истины о способностях бота в конкретном
чате. Состояние строится из РЕАЛЬНЫХ источников, а не из памяти, догадок LLM
или статического списка «я умею»:

  * tool schemas — `services/tool_schemas.py` (`TOOL_CALLING_TOOLS`,
    `active_tools()`) — «инструмент объявлен» (`declared`);
  * конфигурация — hot-слой (`hot.get`) + per-chat оверрайды
    (`chat_params.get_chat_param`) — «можно попробовать» (`tryable`);
  * права/ключи — `keys.*` (image/tavily/exa), `models.*`;
  * бюджет/квота — `services/worker_budget` (`image_calls`, sentinel-семантика
    `0`/`<0`/`>0`);
  * провайдеры/соединения — конфиг провайдера + наблюдаемые исходы вызовов
    (`record_outcome`): «вызов успешно завершён» / «доставка не прошла».

Статусы (закрытый набор, SOUL-AMD.5.12): ``ready``, ``disabled``,
``not_configured``, ``temporarily_unavailable``, ``quota_exhausted``,
``unsupported``, ``unknown``. ``ready`` — не обещание успеха: он означает
«гейты пройдены, инструмент можно пробовать».

Диагностика кешируется (TTL ``TTL_SECONDS``) и сбрасывается при изменении
конфигурации: ``invalidate`` явно, а также автоматически при подмене слоя
кэшей ИЛИ изменении значения ключа-гейта (`POST /api/config` мутирует
`ConfigCache` на месте — review-w10 F4); TTL 60 c остаётся вторым рубежом для
источников вне конфигурации (квота/доступность). Дорогих probes на каждом
сообщении нет — никаких сетевых вызовов в этом модуле вообще.

SelfModel и любой «список способностей» из промпта НЕ являются источником
истины: потребители (L1 capabilities, Writer-подсказка, UI-данные) читают
этот реестр.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Статусы (закрытый набор, SOUL-AMD.5.12) ────────────────────────────────
STATUS_READY = "ready"
STATUS_DISABLED = "disabled"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
STATUS_QUOTA_EXHAUSTED = "quota_exhausted"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UNKNOWN = "unknown"

STATUSES: tuple[str, ...] = (
    STATUS_READY, STATUS_DISABLED, STATUS_NOT_CONFIGURED,
    STATUS_TEMPORARILY_UNAVAILABLE, STATUS_QUOTA_EXHAUSTED,
    STATUS_UNSUPPORTED, STATUS_UNKNOWN,
)

# ── Исходы вызовов («вызов успешно завершён» ≠ «объявлен») ─────────────────
RESULT_UNKNOWN = "unknown"
RESULT_SUCCESS = "success"
RESULT_FAILED = "failed"
RESULT_DELIVERY_FAILED = "delivery_failed"

#: TTL кеша диагностики (SOUL-AMD.5.12: «разумный TTL», без probes).
TTL_SECONDS = 60.0
#: Окно, в котором наблюдаемый транзиентный сбой держит статус
#: ``temporarily_unavailable`` (реальный сигнал «провайдер не отвечает»).
OUTCOME_COOLDOWN_SECONDS = 120.0

_CACHE: dict[tuple[str, int | None], tuple[float, CapabilityState]] = {}
_OUTCOMES: dict[tuple[str, int | None], tuple[float, str, str]] = {}

# ── Гейты/источники по capability (реальные имена ключей) ──────────────────
IMAGE_MODULE_KEY = "flags.image_generation_module_enabled"
IMAGE_BASE_URL_KEY = "models.image_base_url"
IMAGE_MODEL_KEY = "models.image_model"
IMAGE_KEY = "keys.image_api_key"
SEARCH_KEYS = ("keys.tavily_api_key", "keys.exa_api_key")
#: env/Settings-фолбэк поисковых ключей (hot → Settings, как у search_aggregator).
_ENV_BY_SEARCH_KEY = {"keys.tavily_api_key": "TAVILY_API_KEY",
                      "keys.exa_api_key": "EXA_API_KEY"}
FACTCHECK_KEY = "flags.factcheck_enabled"
LORE_KEY = "flags.lore_compiler_enabled"
#: ADD-TR.3 п.4 (слайс ADTR-TOOLS, 19.10.2026): гейт модуля чекапа — тот же
#: ключ, что у роутера 0g (`handlers/checkup.py`) и у исполнителя
#: (`tool_router._get_bot_health`); capability «health» отражает его честно.
CHECKUP_KEY = "flags.checkup_enabled"
#: Ключи-гейты, значения которых входят в идентичность конфигурации
#: (review-w10 F4): правка через POST /api/config мутирует ConfigCache на
#: месте, поэтому одной идентичности объекта недостаточно.
_TOKEN_KEYS: tuple[str, ...] = (
    IMAGE_MODULE_KEY, IMAGE_BASE_URL_KEY, IMAGE_KEY, IMAGE_MODEL_KEY,
    FACTCHECK_KEY, LORE_KEY, CHECKUP_KEY,
) + SEARCH_KEYS


@dataclasses.dataclass(frozen=True)
class CapabilityState:
    """Состояние одной способности в одном чате (R17-safe: коды, не тексты)."""

    capability_id: str
    title: str = ""
    actions: tuple[str, ...] = ()          # что именно делает capability
    executor: str = ""                     # сервис-исполнитель
    tool_name: str = ""                    # разрешённый tool call ("" — нет тула)
    scope: str = "chat"                    # chat | global
    inputs: tuple[str, ...] = ()           # обязательные входы
    gates: tuple[str, ...] = ()            # проверенные гейты (имена ключей)
    status: str = STATUS_UNKNOWN
    reason_code: str = ""                  # код отказа/состояния (машинный)
    checked_at: str = ""                   # ISO-8601 UTC
    source: str = ""                       # runtime | cache | outcome
    declared: bool = False                 # инструмент объявлен (schema+env)
    tryable: bool = False                  # можно попробовать (гейты пройдены)
    last_result: str = RESULT_UNKNOWN      # completed-состояние вызова
    last_result_code: str = ""
    detail: str = ""                       # короткий машинный код (без секретов)

    @property
    def available(self) -> bool:
        """Инструмент можно пробовать (не «обещание успеха»)."""
        return self.status == STATUS_READY

    def as_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "title": self.title,
            "actions": list(self.actions),
            "executor": self.executor,
            "tool": self.tool_name,
            "scope": self.scope,
            "inputs": list(self.inputs),
            "gates": list(self.gates),
            "status": self.status,
            "reason_code": self.reason_code,
            "checked_at": self.checked_at,
            "source": self.source,
            "declared": self.declared,
            "tryable": self.tryable,
            "last_result": self.last_result,
            "last_result_code": self.last_result_code,
            "detail": self.detail,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _monotonic() -> float:
    return time.monotonic()


def _config_token() -> tuple:
    """Идентичность конфигурации: слои кэшей + значения ключей-гейтов.

    Дёшево (только чтение dict) и без I/O: если приложение подменило hot-кэш
    или per-chat кэш (штатный путь применения настроек), записи реестра
    перестают попадать в кеш — «сброс при изменении конфигурации» происходит
    сам, без ожидания TTL.

    Значения гейтов входят в токен сознательно (review-w10 F4): штатная запись
    настроек (`POST /api/config` → `ConfigCache.set/set_many`) мутирует кэш НА
    МЕСТЕ, поэтому одной идентичности объекта мало — иначе покрытие было бы
    только TTL 60 c. Значения используются ТОЛЬКО как ключ in-memory-кеша и
    никуда не логируются (R17)."""
    try:
        from services import chat_params
        from services import hot_config as hot
        gates = tuple((key, str(_hot_get(key, None))) for key in _TOKEN_KEYS)
        return (id(hot.get_config_cache()),
                id(chat_params.get_chat_params_cache()), gates)
    except Exception:      # pragma: no cover - защитная ветка
        return ()


# ── Кеш/инвалидация/исходы ─────────────────────────────────────────────────

def reset_cache() -> None:
    """Сбросить кеш диагностики и наблюдаемые исходы (тесты/рестарт)."""
    _CACHE.clear()
    _OUTCOMES.clear()


def invalidate(capability_id: str | None = None, chat_id: int | None = None,
               *, reason: str = "") -> int:
    """Сброс кеша при изменении конфигурации (SOUL-AMD.5.12).

    ``capability_id is None`` — все способности; ``chat_id is None`` — все
    чаты. Возвращает число выброшенных записей. Никогда не бросает."""
    try:
        if capability_id is None and chat_id is None:
            count = len(_CACHE)
            _CACHE.clear()
        else:
            keys = [k for k in _CACHE
                    if (capability_id is None or k[0] == capability_id)
                    and (chat_id is None or k[1] == chat_id)]
            for key in keys:
                _CACHE.pop(key, None)
            count = len(keys)
        if count:
            logger.info("[capability] cache invalidated | cap=%s | chat=%s | "
                        "n=%d | reason=%s", capability_id or "*",
                        chat_id if chat_id is not None else "*", count,
                        reason or "-")
        return count
    except Exception:      # pragma: no cover - защитная ветка
        return 0


#: Коды «нового вызова НЕ было» (replay по idempotency-ключу, A5/D3):
#: наблюдаемое состояние не переписывается (review-w10 F5).
REPLAY_CODES = frozenset({"already"})


def record_outcome(capability_id: str, *, chat_id: int | None = None,
                   ok: bool, code: str = "", delivery_ok: bool | None = None,
                   now: float | None = None) -> None:
    """Наблюдаемый исход вызова («вызов успешно завершён» ≠ «объявлен»).

    ``ok=False`` + транзиентный код → следующий ``resolve`` отдаёт
    ``temporarily_unavailable`` в окне ``OUTCOME_COOLDOWN_SECONDS`` (реальный
    сигнал недоступности провайдера, без сетевых проб). ``delivery_ok=False``
    при ``ok=True`` → ``RESULT_DELIVERY_FAILED`` (успех генерации ≠ доставка).

    Replay (``code='already'``, review-w10 F5): нового платного вызова НЕ было
    — состояние НЕ переписывается, иначе повтор объявлялся бы успехом и снимал
    бы наблюдаемый отказ провайдера. Никогда не бросает."""
    try:
        if str(code or "").strip().lower() in REPLAY_CODES:
            return
        if ok:
            result = (RESULT_SUCCESS if delivery_ok is not False
                      else RESULT_DELIVERY_FAILED)
        else:
            result = RESULT_FAILED
        _OUTCOMES[(str(capability_id), chat_id)] = (
            float(now if now is not None else _monotonic()), result,
            str(code or "")[:64])
        invalidate(capability_id, chat_id, reason="outcome")
    except Exception:      # pragma: no cover - защитная ветка
        pass


def _outcome(capability_id: str, chat_id: int | None,
             now: float | None = None) -> tuple[str, str]:
    """(last_result, last_result_code) по чату → глобальному слою."""
    ts = float(now if now is not None else _monotonic())
    for key in ((capability_id, chat_id), (capability_id, None)):
        entry = _OUTCOMES.get(key)
        if entry is None:
            continue
        at, result, code = entry
        if (ts - at) <= OUTCOME_COOLDOWN_SECONDS:
            return result, code
    return RESULT_UNKNOWN, ""


#: Транзиентные коды отказа: только они дают статус
#: ``temporarily_unavailable``. Конфигурационные (``unauthorized``/``forbidden``)
#: остаются делом гейтов ключа/модуля, а не «провайдер не отвечает».
_TRANSIENT_CODES = frozenset({
    "timeout", "network", "unreachable", "rate_limited", "bad_gateway",
    "unavailable", "provider_unavailable",
})


def _is_transient_code(code: str) -> bool:
    """Транзиентный ли код отказа (таймаут/сеть/429/5xx)."""
    raw = str(code or "").strip()
    if raw in _TRANSIENT_CODES:
        return True
    if raw.startswith("download_"):
        return True
    if raw.startswith("http_"):
        try:
            status = int(raw.split("_", 1)[1])
        except (IndexError, ValueError):
            return False
        return status == 429 or status >= 500
    return False


def _recent_transient_failure(capability_id: str, chat_id: int | None,
                              now: float | None = None) -> str:
    """Код наблюдаемого ТРАНЗИЕНТНОГО сбоя в окне кулдауна ("" — нет)."""
    result, code = _outcome(capability_id, chat_id, now)
    if result != RESULT_FAILED:
        return ""
    if not code:
        return "provider_unavailable"
    return code if _is_transient_code(code) else ""


# ── Разрешение конфигурации (hot → per-chat override → default) ────────────

def _hot_get(key: str, default=None):
    try:
        from services import hot_config as hot
        return hot.get(key, default)
    except Exception:      # pragma: no cover - кэш не поднят
        return default


async def _chat_value(chat_id: int | None, key: str, default=None):
    """Per-chat override → глобальный hot-слой → default (fail-open)."""
    base = _hot_get(key, default)
    if chat_id is None:
        return base
    try:
        from services.chat_params import get_chat_param
        return await get_chat_param(chat_id, key, base)
    except Exception:      # pragma: no cover - PG down → глобальный слой
        return base


async def chat_value(chat_id: int | None, key: str, default=None):
    """Публичный effective-резолв настройки чата (COR-01): та же цепочка,
    что у построителей capability (per-chat override → hot → default).

    ЕДИНСТВЕННЫЙ механизм для проверок capability И исполнения (executors):
    «проверка возможности и исполнение используют один effective-набор
    настроек чата» — провайдер исполнения совпадает с проверенным. Новых
    конфигурационных систем не создаётся."""
    return await _chat_value(chat_id, key, default)


def _tool_names(lore_enabled: bool = True,
                image_enabled: bool = False) -> set[str]:
    """Реальный анонсируемый набор имён tools (fail-open → пусто)."""
    try:
        from services.tool_schemas import active_tools
        return {t["function"]["name"] for t in
                active_tools(bool(lore_enabled), bool(image_enabled))
                if isinstance(t, dict) and t.get("function")}
    except Exception:      # pragma: no cover - защитная ветка
        return set()


def _canonical_tool_names() -> set[str]:
    """Канон схем (что вообще существует в коде, независимо от гейтов)."""
    try:
        from services.tool_schemas import TOOL_CALLING_TOOLS
        return {t["function"]["name"] for t in TOOL_CALLING_TOOLS
                if isinstance(t, dict) and t.get("function")}
    except Exception:      # pragma: no cover - защитная ветка
        return set()


def _is_unlimited(limit) -> bool:
    try:
        return int(limit) < 0
    except (TypeError, ValueError):
        return False


def _is_forbidden(limit) -> bool:
    try:
        return int(limit) == 0
    except (TypeError, ValueError):
        return False


async def _scope_usage(scope: str, metric: str) -> tuple[int, int | None]:
    """(used, limit) строки дня для scope; строки нет → ``(0, None)``.

    Нечитаемый лимит → ``None`` (вызывающий берёт лимит из ``image_limits``,
    а не отключает проверку квоты целиком)."""
    from services import worker_budget as wb
    rows = await wb.get_usage(scope=scope)
    for row in rows or ():
        if row.get("metric") != metric:
            continue
        try:
            used = int(row.get("used") or 0)
        except (TypeError, ValueError):
            used = 0
        try:
            limit = int(row.get("limit"))
        except (TypeError, ValueError):
            limit = None
        return used, limit
    return 0, None


async def _image_quota(chat_id: int | None) -> tuple[str, str]:
    """(статус_квоты, detail): '' | ``quota_exhausted``; sentinel-семантика.

    SOUL-1 W10 fix (review-w10 F3): читаются ОБА контура, в том же порядке, в
    котором их списывает реальный вызов (``worker_budget.reserve_image`` /
    ``consume``) — СНАЧАЛА shared (``global``), затем per-chat. Исчерпанный
    shared делает способность недоступной, даже если per-chat строка чистая:
    статус обязан отражать то, обо что реально споткнётся ``consume`` (иначе
    UI и гейт показывают ``ready`` при отказе по квоте)."""
    try:
        from services import worker_budget as wb
        metric = wb.METRIC_IMAGE_CALLS
        shared_used, shared_limit = await _scope_usage("global", metric)
        chat_used, chat_limit = 0, None
        if chat_id is not None:
            chat_used, chat_limit = await _scope_usage(
                f"chat:{chat_id}", metric)
        if shared_limit is None or chat_limit is None:
            # Строки дня нет (ещё не тратили) — лимиты читаем отдельно.
            _shared, _per_chat, _source = await wb.image_limits(chat_id)
            if shared_limit is None:
                shared_limit = _shared
            if chat_limit is None:
                chat_limit = _per_chat
        # (1) SHARED-контур: списывается первым (общий на все чаты).
        if _is_forbidden(shared_limit):
            return STATUS_DISABLED, "image_limit_zero"
        if not _is_unlimited(shared_limit) and shared_used >= int(shared_limit):
            return STATUS_QUOTA_EXHAUSTED, "image_shared_limit"
        if chat_id is None:
            return "", ("image_limit_unlimited"
                        if _is_unlimited(shared_limit) else "image_limit_ok")
        # (2) Per-chat контур.
        if _is_forbidden(chat_limit):
            return STATUS_DISABLED, "image_limit_zero"
        if _is_unlimited(chat_limit):
            return "", "image_limit_unlimited"
        if chat_used >= int(chat_limit):
            return STATUS_QUOTA_EXHAUSTED, "image_daily_limit"
        return "", "image_limit_ok"
    except Exception:      # pragma: no cover - fail-open: квота не блокирует
        return "", "quota_unavailable"


async def image_quota_state(chat_id: int | None) -> tuple[str, str]:
    """CFG-02B (§02B.7): публичный доступ к существующей проверке квоты.

    ``(''|'disabled'|'quota_exhausted', detail)`` — «о что реально
    споткнётся резерв». Нужен отказу по частотному лимиту: при исчерпании
    ОБОИХ лимитов сообщение обязано показать обе истинные причины и оба
    срока (второй копии правил квоты не создаётся)."""
    return await _image_quota(chat_id)


async def _build_image_generation(chat_id: int | None,
                                  now: float | None = None
                                  ) -> CapabilityState:
    """image_generation — из модуля/ключа/модели/квоты/наблюдаемых исходов."""
    from services import image_generation as ig
    canonical = _canonical_tool_names()
    declared = ig.TOOL_NAME in canonical
    gates: list[str] = [IMAGE_MODULE_KEY, IMAGE_KEY, IMAGE_MODEL_KEY,
                        "budget.image_calls"]
    base = CapabilityState(
        capability_id="image_generation",
        title="Генерация изображений",
        actions=("generate_image", "deliver_image"),
        executor="services.image_generation",
        tool_name=ig.TOOL_NAME if declared else "",
        scope="chat",
        inputs=("prompt",),
        gates=tuple(gates),
        declared=declared,
        checked_at=_now_iso(),
        source="runtime",
    )
    last_result, last_code = _outcome("image_generation", chat_id, now)

    def _state(status: str, **kw) -> CapabilityState:
        """Состояние с наблюдаемым исходом вызова (успех ≠ доставка)."""
        return dataclasses.replace(base, status=status, last_result=last_result,
                                   last_result_code=last_code, **kw)

    if not declared:
        return _state(STATUS_UNSUPPORTED, reason_code="tool_absent",
                      detail="schema_absent")
    # 1. Модуль (env-рубильник AND каталожный тумблер, per-chat).
    try:
        module_on = await ig.resolve_module_enabled(chat_id)
    except Exception:      # pragma: no cover - resolve уже fail-open
        module_on = bool(_hot_get(IMAGE_MODULE_KEY, True))
    if not module_on:
        return _state(STATUS_DISABLED, reason_code="module_disabled",
                      detail="image_module_off")
    # 2. Конфигурация провайдера (ключ + модель, per-chat → global).
    model = str(await _chat_value(
        chat_id, IMAGE_MODEL_KEY,
        _hot_get(IMAGE_MODEL_KEY, getattr(_settings(), "IMAGE_MODEL", ""))
        or "") or "").strip()
    key = str(await _chat_value(
        chat_id, IMAGE_KEY,
        _hot_get(IMAGE_KEY, getattr(_settings(), "IMAGE_API_KEY", ""))
        or "") or "").strip()
    if not key or not model:
        return _state(STATUS_NOT_CONFIGURED,
                      reason_code="image_provider_unconfigured",
                      detail=("key_absent" if not key else "model_absent"))
    # 3. Наблюдаемый транзиентный сбой провайдера (окно кулдауна).
    transient = _recent_transient_failure("image_generation", chat_id, now)
    if transient:
        return _state(STATUS_TEMPORARILY_UNAVAILABLE,
                      reason_code="provider_unavailable", source="outcome",
                      detail=transient)
    # 4. Квота/суточный лимит.
    quota_status, quota_detail = await _image_quota(chat_id)
    if quota_status == STATUS_DISABLED:
        return _state(STATUS_DISABLED, reason_code="financial_limit_disabled",
                      detail=quota_detail)
    if quota_status == STATUS_QUOTA_EXHAUSTED:
        return _state(STATUS_QUOTA_EXHAUSTED,
                      reason_code="financial_limit_reached", detail=quota_detail)
    return _state(STATUS_READY, reason_code="", tryable=True,
                  detail=quota_detail or "ready")


async def _build_image_edit(chat_id: int | None, now: float | None = None
                            ) -> CapabilityState:
    """image_edit (ASAP5 §18/§20) — редактирование существующего изображения.

    ОТДЕЛЬНАЯ способность: «недоступность одной операции не означает
    недоступности остальных» (§18). Источники ТЕ ЖЕ реальные, что у
    генерации (модуль/ключ/модель/квота/наблюдаемые исходы), плюс
    capability-цепочка ``image_capabilities`` (override/registry/кеш;
    БЕЗ сетевых вызовов — конструктор модуля не делает probes): TRUE →
    ready, FALSE → unsupported («модель не умеет edit»), UNKNOWN → честный
    ``unknown`` (не выдумываем поддержку). Никаких сетевых вызовов."""
    from services import image_generation as ig
    canonical = _canonical_tool_names()
    declared = "edit_image" in canonical
    gates: list[str] = [IMAGE_MODULE_KEY, IMAGE_KEY, IMAGE_MODEL_KEY,
                        "budget.image_calls", "image_capabilities.image_edit"]
    base = CapabilityState(
        capability_id="image_edit",
        title="Редактирование изображений",
        actions=("edit_image",),
        executor="services.media_execution",
        tool_name="edit_image" if declared else "",
        scope="chat",
        inputs=("prompt", "source_image"),
        gates=tuple(gates),
        declared=declared,
        checked_at=_now_iso(),
        source="runtime",
    )
    last_result, last_code = _outcome("image_edit", chat_id, now)

    def _state(status: str, **kw) -> CapabilityState:
        return dataclasses.replace(base, status=status, last_result=last_result,
                                   last_result_code=last_code, **kw)

    if not declared:
        return _state(STATUS_UNSUPPORTED, reason_code="tool_absent",
                      detail="schema_absent")
    try:
        module_on = await ig.resolve_module_enabled(chat_id)
    except Exception:      # pragma: no cover - resolve уже fail-open
        module_on = bool(_hot_get(IMAGE_MODULE_KEY, True))
    if not module_on:
        return _state(STATUS_DISABLED, reason_code="module_disabled",
                      detail="image_module_off")
    model = str(await _chat_value(
        chat_id, IMAGE_MODEL_KEY,
        _hot_get(IMAGE_MODEL_KEY, getattr(_settings(), "IMAGE_MODEL", ""))
        or "") or "").strip()
    key = str(await _chat_value(
        chat_id, IMAGE_KEY,
        _hot_get(IMAGE_KEY, getattr(_settings(), "IMAGE_API_KEY", ""))
        or "") or "").strip()
    if not key or not model:
        return _state(STATUS_NOT_CONFIGURED,
                      reason_code="image_provider_unconfigured",
                      detail=("key_absent" if not key else "model_absent"))
    # Provider edit-capability (image_capabilities §16: override → registry
    # → cached → conservative unknown; БЕЗ сети — discovery делает вызывающий
    # контур, не реестр). COR-01: base_url — из того же effective-набора
    # настроек чата, что model/key (один резолв и у проверки, и у исполнения),
    # а ярлык провайдера берётся из РЕЗОЛВНУТОГО base_url — проверенная
    # способность принадлежит тому провайдеру, который исполнит операцию.
    edit_known: str = ""
    try:
        from services import image_capabilities as cap
        base_url = str(await _chat_value(
            chat_id, IMAGE_BASE_URL_KEY,
            _hot_get(IMAGE_BASE_URL_KEY,
                     getattr(_settings(), "IMAGE_BASE_URL", ""))
            or "") or "").strip()
        caps = cap.resolve_capabilities(
            ig._provider_from_url(base_url), base_url,
            model, operation=cap.OPERATION_EDIT)
        edit_known = str(getattr(caps, "image_edit", "") or "")
    except Exception:      # pragma: no cover - fail-open → unknown
        edit_known = ""
    if edit_known == "no":
        return _state(STATUS_UNSUPPORTED, reason_code="edit_unsupported",
                      detail="model_cannot_edit")
    if edit_known != "yes":
        # §16 (image_capabilities): unknown остаётся честным unknown —
        # поддержка НЕ выдумывается. Статус NOT_CONFIGURED (реестровый
        # контракт: STATUS_UNKNOWN = «реестр не знает capability», а мы
        # знаем её и честно называем причину: подтверждения нет).
        return _state(STATUS_NOT_CONFIGURED,
                      reason_code="edit_capability_unknown",
                      detail="edit_capability_unknown")
    transient = _recent_transient_failure("image_edit", chat_id, now)
    if transient:
        return _state(STATUS_TEMPORARILY_UNAVAILABLE,
                      reason_code="provider_unavailable", source="outcome",
                      detail=transient)
    quota_status, quota_detail = await _image_quota(chat_id)
    if quota_status == STATUS_DISABLED:
        return _state(STATUS_DISABLED, reason_code="financial_limit_disabled",
                      detail=quota_detail)
    if quota_status == STATUS_QUOTA_EXHAUSTED:
        return _state(STATUS_QUOTA_EXHAUSTED,
                      reason_code="financial_limit_reached", detail=quota_detail)
    return _state(STATUS_READY, reason_code="", tryable=True,
                  detail=quota_detail or "ready")


async def _build_web_search(chat_id: int | None, now: float | None = None
                            ) -> CapabilityState:
    """web_search — инструмент + хотя бы один поисковый ключ (tavily/exa)."""
    names = _tool_names(lore_enabled=True)
    canonical = _canonical_tool_names()
    declared = "execute_web_search" in canonical
    base = CapabilityState(
        capability_id="web_search",
        title="Поиск в интернете",
        actions=("web_search",),
        executor="services.tool_router",
        tool_name="execute_web_search" if declared else "",
        inputs=("query",),
        gates=SEARCH_KEYS,
        declared=declared, checked_at=_now_iso(), source="runtime")
    if not declared:
        return dataclasses.replace(base, status=STATUS_UNSUPPORTED,
                                   reason_code="tool_absent")
    keys = [str(await _chat_value(
        chat_id, k, _hot_get(k, getattr(_settings(), _ENV_BY_SEARCH_KEY[k], ""))
        or "") or "").strip() for k in SEARCH_KEYS]
    if not any(keys):
        return dataclasses.replace(
            base, status=STATUS_NOT_CONFIGURED,
            reason_code="search_provider_unconfigured",
            detail="search_keys_absent")
    transient = _recent_transient_failure("web_search", chat_id, now)
    if transient:
        return dataclasses.replace(
            base, status=STATUS_TEMPORARILY_UNAVAILABLE,
            reason_code="provider_unavailable", source="outcome",
            detail=transient)
    last_result, last_code = _outcome("web_search", chat_id, now)
    return dataclasses.replace(
        base, status=STATUS_READY, tryable=True, last_result=last_result,
        last_result_code=last_code, detail="search_keys_present")


async def _build_fact_check(chat_id: int | None, now: float | None = None
                            ) -> CapabilityState:
    """fact_check — инструмент анонсируется (реальные гейты factcheck/temporal)."""
    names = _tool_names(lore_enabled=True)
    canonical = _canonical_tool_names()
    declared = "fact_check" in canonical
    base = CapabilityState(
        capability_id="fact_check",
        title="Проверка фактов",
        actions=("fact_check",),
        executor="services.factcheck_service",
        tool_name="fact_check" if declared else "",
        inputs=("claim",),
        gates=(FACTCHECK_KEY, "temporal.tool_enabled"),
        declared=declared, checked_at=_now_iso(), source="runtime")
    if not declared:
        return dataclasses.replace(base, status=STATUS_UNSUPPORTED,
                                   reason_code="tool_absent")
    if "fact_check" not in names:
        return dataclasses.replace(
            base, status=STATUS_DISABLED, reason_code="factcheck_module_disabled",
            detail="tool_not_announced")
    transient = _recent_transient_failure("fact_check", chat_id, now)
    if transient:
        return dataclasses.replace(
            base, status=STATUS_TEMPORARILY_UNAVAILABLE,
            reason_code="provider_unavailable", source="outcome",
            detail=transient)
    last_result, last_code = _outcome("fact_check", chat_id, now)
    return dataclasses.replace(base, status=STATUS_READY, tryable=True,
                               last_result=last_result,
                               last_result_code=last_code, detail="announced")


async def _build_health(chat_id: int | None, now: float | None = None
                        ) -> CapabilityState:
    """health (ADD-TR.3 п.4, слайс ADTR-TOOLS): состояние чекапа.

    Те же гейты, что у РЕАЛЬНОГО исполнения (``tool_router._get_bot_health``
    и роутера 0g): модуль ``flags.checkup_enabled`` (hot, глобальный — как в
    обработчике; per-chat слоя у чекапа нет) + факт анонса инструмента.
    Выключенный модуль → ``disabled`` с наблюдаемым
    ``checkup_module_disabled`` (Writer не обещает недоступное)."""
    canonical = _canonical_tool_names()
    declared = "get_bot_health" in canonical
    base = CapabilityState(
        capability_id="health",
        title="Чекап состояния",
        actions=("get_bot_health",),
        executor="services.tool_router",
        tool_name="get_bot_health" if declared else "",
        inputs=(),
        gates=(CHECKUP_KEY,),
        declared=declared, checked_at=_now_iso(), source="runtime")
    if not declared:
        return dataclasses.replace(base, status=STATUS_UNSUPPORTED,
                                   reason_code="tool_absent")
    if not bool(_hot_get(CHECKUP_KEY, getattr(_settings(), "CHECKUP_ENABLED",
                                              True))):
        return dataclasses.replace(
            base, status=STATUS_DISABLED,
            reason_code="checkup_module_disabled",
            detail="checkup_module_off")
    if "get_bot_health" not in _tool_names():
        return dataclasses.replace(
            base, status=STATUS_DISABLED,
            reason_code="checkup_module_disabled",
            detail="tool_not_announced")
    return dataclasses.replace(base, status=STATUS_READY, tryable=True,
                               detail="announced")


async def _build_video_summary(chat_id: int | None, now: float | None = None
                               ) -> CapabilityState:
    """video_summary — инструмент + настроенный источник медиа (cobalt)."""
    canonical = _canonical_tool_names()
    declared = "summarize_video" in canonical
    base = CapabilityState(
        capability_id="video_summary",
        title="Пересказ видео",
        actions=("summarize_video",),
        executor="services.youtube_summarizer_service",
        tool_name="summarize_video" if declared else "",
        inputs=("url",),
        gates=("COBALT_API_URL",),
        declared=declared, checked_at=_now_iso(), source="runtime")
    if not declared:
        return dataclasses.replace(base, status=STATUS_UNSUPPORTED,
                                   reason_code="tool_absent")
    source_url = str(getattr(_settings(), "COBALT_API_URL", "") or "").strip()
    if not source_url:
        return dataclasses.replace(
            base, status=STATUS_NOT_CONFIGURED,
            reason_code="media_source_unconfigured", detail="cobalt_absent")
    transient = _recent_transient_failure("video_summary", chat_id, now)
    if transient:
        return dataclasses.replace(
            base, status=STATUS_TEMPORARILY_UNAVAILABLE,
            reason_code="provider_unavailable", source="outcome",
            detail=transient)
    return dataclasses.replace(base, status=STATUS_READY, tryable=True,
                               detail="media_source_present")


async def _build_from_announced(capability_id: str, title: str, tool_name: str,
                                executor: str, actions: tuple[str, ...],
                                inputs: tuple[str, ...],
                                *, lore_enabled: bool = True,
                                now: float | None = None) -> CapabilityState:
    """Общий билдер: capability готов, если инструмент реально анонсирован."""
    canonical = _canonical_tool_names()
    declared = tool_name in canonical
    base = CapabilityState(
        capability_id=capability_id, title=title, actions=actions,
        executor=executor, tool_name=tool_name if declared else "",
        inputs=inputs, gates=(), declared=declared, checked_at=_now_iso(),
        source="runtime")
    if not declared:
        return dataclasses.replace(base, status=STATUS_UNSUPPORTED,
                                   reason_code="tool_absent")
    announced = _tool_names(lore_enabled=lore_enabled)
    if tool_name not in announced:
        return dataclasses.replace(
            base, status=STATUS_DISABLED, reason_code="module_disabled",
            detail="tool_not_announced")
    transient = _recent_transient_failure(capability_id, None, now)
    if transient:
        return dataclasses.replace(
            base, status=STATUS_TEMPORARILY_UNAVAILABLE,
            reason_code="provider_unavailable", source="outcome",
            detail=transient)
    return dataclasses.replace(base, status=STATUS_READY, tryable=True,
                               detail="announced")


def _settings():
    from config import settings
    return settings


#: Реестр билдеров: capability → как строится состояние (реальные источники).
async def resolve(capability_id: str, chat_id: int | None = None, *,
                  use_cache: bool = True, now: float | None = None
                  ) -> CapabilityState:
    """Состояние способности в чате (TTL-кеш; без сетевых проб).

    Неизвестное имя → ``unknown`` (реестр не выдумывает способностей);
    любая ошибка источника → ``unknown`` + detail, но не исключение."""
    cap = str(capability_id or "").strip()
    ts = float(now if now is not None else _monotonic())
    key = (cap, chat_id, _config_token())
    if use_cache:
        cached = _CACHE.get(key)
        if cached is not None and (ts - cached[0]) <= TTL_SECONDS:
            return dataclasses.replace(cached[1], source="cache")
    try:
        if cap == "image_generation":
            state = await _build_image_generation(chat_id, now)
        elif cap == "image_edit":
            state = await _build_image_edit(chat_id, now)
        elif cap == "web_search":
            state = await _build_web_search(chat_id, now)
        elif cap == "fact_check":
            state = await _build_fact_check(chat_id, now)
        elif cap == "health":
            state = await _build_health(chat_id, now)
        elif cap == "video_summary":
            state = await _build_video_summary(chat_id, now)
        elif cap == "chat_memory":
            state = await _build_from_announced(
                cap, "Память чата", "query_chat_memory",
                "services.tool_router", ("query_chat_memory",),
                ("query",), now=now)
        elif cap == "chat_history":
            state = await _build_from_announced(
                cap, "История чата", "get_recent_history",
                "services.tool_router", ("get_recent_history",),
                ("chat_id",), now=now)
        elif cap == "statistics":
            # MCA-15: тула нет по конструкции (дет. пре-блок) — честный
            # ``unsupported``, а не «unknown» и не выдуманный инструмент.
            state = CapabilityState(
                capability_id=cap, title="Статистика чата",
                actions=("chat_statistics",),
                executor="services.direct_chat_service", tool_name="",
                inputs=(), gates=(), status=STATUS_UNSUPPORTED,
                reason_code="no_tool", detail="deterministic_preblock",
                declared=False, checked_at=_now_iso(), source="runtime")
        elif cap == "user_memory":
            state = await _build_from_announced(
                cap, "Контекст собеседника", "get_user_context",
                "services.tool_router", ("get_user_context",),
                ("user_id",), now=now)
        elif cap == "historical_search":
            state = await _build_from_announced(
                cap, "Летопись чата", "compile_lore_story",
                "services.tool_router", ("dig_into_lore", "compile_lore_story"),
                ("topic",), lore_enabled=bool(
                    _hot_get(LORE_KEY, True)), now=now)
        elif cap == "image_understanding":
            state = await _build_from_announced(
                cap, "Распознавание изображений", "recognize_image",
                "services.tool_router", ("recognize_image",), ("image",),
                now=now)
        elif cap == "transcription":
            state = await _build_from_announced(
                cap, "Транскрибация видео", "transcribe_video",
                "services.tool_router", ("transcribe_video",), ("url",),
                now=now)
        elif cap == "media_download":
            state = await _build_from_announced(
                cap, "Скачивание медиа", "download_media",
                "services.tool_router", ("download_media",), ("url",),
                now=now)
        elif cap == "fetch_url":
            state = await _build_from_announced(
                cap, "Разбор страницы по ссылке", "fetch_article",
                "services.tool_router", ("fetch_article",), ("url",),
                now=now)
        else:
            state = CapabilityState(
                capability_id=cap, status=STATUS_UNKNOWN,
                reason_code="unknown_capability", detail="not_in_registry",
                checked_at=_now_iso(), source="runtime")
    except Exception:
        logger.warning("[capability] resolve failed | cap=%s | chat=%s",
                       cap, chat_id, exc_info=True)
        state = CapabilityState(
            capability_id=cap, status=STATUS_UNKNOWN,
            reason_code="resolve_error", detail="source_error",
            checked_at=_now_iso(), source="runtime")
    if use_cache:
        _CACHE[key] = (ts, state)
    return state


async def resolve_many(capability_ids, chat_id: int | None = None, *,
                       use_cache: bool = True) -> tuple[CapabilityState, ...]:
    """Несколько способностей за один проход (порядок входного списка)."""
    out: list[CapabilityState] = []
    for cap in (capability_ids or ()):
        out.append(await resolve(cap, chat_id, use_cache=use_cache))
    return tuple(out)


async def capability_view(chat_id: int | None = None, *,
                          capability_ids=None, use_cache: bool = True
                          ) -> list[dict]:
    """R17-safe данные для UI/Inspector (W6) и L1: список состояний.

    Источник для «Возможности бота» (SOUL-AMD.6.5): что доступно/выключено/
    сломано, почему и в каком модуле настраивается — без дублирования
    тумблеров."""
    ids = list(capability_ids or _DEFAULT_VIEW_IDS)
    states = await resolve_many(ids, chat_id, use_cache=use_cache)
    return [state.as_dict() for state in states]


_DEFAULT_VIEW_IDS: tuple[str, ...] = (
    "image_generation", "image_edit", "web_search", "fact_check",
    "video_summary", "chat_memory", "chat_history", "user_memory",
    "historical_search", "image_understanding", "transcription",
    "media_download", "fetch_url", "statistics",
)


# ── Сообщения пользователю: регистрируемые Factory Default по коду отказа ──

def message_block_id(code: str) -> str:
    """Registry ID управляемого сообщения по коду отказа."""
    return f"message.image_failure.{str(code or 'unknown').strip() or 'unknown'}"


CLARIFY_BLOCK_ID = "message.image_request.clarify"

#: §17.2-код/`reason_class` → класс шаблона (реальный код отказа, не догадка).
_FAILURE_CODE_BY_REASON: dict[str, str] = {
    "send_failed": "delivery_failed",
    "no_bot": "delivery_failed",
    "delivery_unknown": "delivery_failed",
    "budget": "quota_exhausted",
    "financial_limit_reached": "quota_exhausted",
    # CFG-02C (§02C.4, carry-over §65): отказ по SHARED (техническому) потолку
    # — тот же класс шаблона «квота», но с честной причиной в диагностике и
    # shared-строкой сброса (TZ `WORKER_BUDGET_TZ`), не «квота чата».
    "shared_budget": "quota_exhausted",
    # CFG-02B (§02B.6): отказ короткой паузы частотного лимита — отдельный
    # редактируемый текст (`message.image_failure.freq_limited`), НЕ «квота»
    # и НЕ «провайдер прилёг» (истина: слишком часто просят).
    "freq_limit": "freq_limited",
    "financial_limit_disabled": "disabled",
    "module_disabled": "disabled",
    "image_module_off": "disabled",
    "unauthorized": "not_configured",
    "forbidden": "not_configured",
    "payment_required": "not_configured",
    "provider_unconfigured": "not_configured",
    "key_absent": "not_configured",
    "model_absent": "not_configured",
    "timeout": "temporarily_unavailable",
    "network": "temporarily_unavailable",
    "unreachable": "temporarily_unavailable",
    "rate_limited": "temporarily_unavailable",
    "bad_gateway": "temporarily_unavailable",
    "unavailable": "temporarily_unavailable",
    "provider_unavailable": "temporarily_unavailable",
    "too_large": "unsupported",
    "too_many_bytes": "unsupported",
    "empty_prompt": "unsupported",
    "validation_failed": "unsupported",
    # ASAP5 §20 (edit-route): честные причины edit-пути — не «неизвестный
    # сбой» и не подмена генерацией.
    "edit_unsupported": "unsupported",
    "no_input_images": "unsupported",
    "no_source_image": "unsupported",
    "route_unverified": "temporarily_unavailable",
}


def failure_code_for_status(status: str) -> str:
    """Статус capability → класс шаблона (SOUL-AMD.5.15)."""
    from services.chat_prompts import IMAGE_FAILURE_BY_STATUS
    return IMAGE_FAILURE_BY_STATUS.get(str(status or ""), "unknown")


def failure_code_for_reason(reason: str, *, status: str = "") -> str:
    """Реальный код отказа генерации → класс шаблона.

    HTTP-классы (`http_5xx`/`http_4xx`) и транзиентные причины разводятся
    честно: 5xx/429 → временная недоступность, 401/403 → не настроено."""
    raw = str(reason or "").strip()
    if raw in _FAILURE_CODE_BY_REASON:
        return _FAILURE_CODE_BY_REASON[raw]
    if raw.startswith("http_"):
        try:
            code = int(raw.split("_", 1)[1])
        except (IndexError, ValueError):
            code = 0
        if code in (401, 402, 403):
            return "not_configured"
        if code == 429 or code >= 500:
            return "temporarily_unavailable"
        if code >= 400:
            return "unsupported"
        return "unknown"
    if raw.startswith("download_"):
        return "temporarily_unavailable"
    if status:
        return failure_code_for_status(status)
    return "unknown"


def _template_text(block_id: str, factory: str) -> tuple[str, str]:
    """(текст, источник) управляемого сообщения: PG-ревизия → factory.

    Читает effective-значение через реестр (единый путь Factory/Global
    Custom/Chat Override); ошибка реестра → заводской текст (fail-open)."""
    try:
        from services import prompt_registry as pr
        spec = pr.block(block_id)
        if spec is None or not spec.pg_key:
            return factory, "factory"
        pg_value = None
        try:
            from services import hot_config as hot
            cache = hot.get_config_cache()
            if cache is not None:
                pg_value = cache.get(spec.pg_key, None)
        except Exception:
            pg_value = None
        row = pr.effective_prompt(block_id, pg_value=pg_value)
        text = str(row.text or "").strip()
        if text:
            return text, row.factory_source
    except Exception:
        logger.warning("[capability] message resolve failed — factory | "
                       "block=%s", block_id, exc_info=True)
    return factory, "factory"


def failure_text(code: str) -> tuple[str, str, str]:
    """(текст, Registry ID, источник) по коду отказа (SOUL-AMD.5.15)."""
    from services.chat_prompts import IMAGE_FAILURE_TEMPLATES
    key = str(code or "").strip() or "unknown"
    factory = IMAGE_FAILURE_TEMPLATES.get(key)
    if factory is None:
        key = "unknown"
        factory = IMAGE_FAILURE_TEMPLATES["unknown"]
    block_id = message_block_id(key)
    text, source = _template_text(block_id, factory)
    return text, block_id, source


def status_message(state: CapabilityState) -> tuple[str, str, str]:
    """(текст, Registry ID, источник) для НЕготовой способности."""
    return failure_text(failure_code_for_status(state.status))


def failure_message_for_reason(reason: str, *, status: str = ""
                               ) -> tuple[str, str, str]:
    """(текст, Registry ID, источник) по реальному коду отказа генерации."""
    return failure_text(failure_code_for_reason(reason, status=status))


def clarify_text() -> tuple[str, str, str]:
    """(текст, Registry ID, источник) одного уточняющего вопроса (§5.9)."""
    from services.chat_prompts import IMAGE_REQUEST_CLARIFY_TEXT
    text, source = _template_text(CLARIFY_BLOCK_ID, IMAGE_REQUEST_CLARIFY_TEXT)
    return text, CLARIFY_BLOCK_ID, source


#: Человеческие формулировки для подсказки Writer'у (R17-safe, без секретов).
_STATUS_HINT: dict[str, str] = {
    STATUS_DISABLED: "модуль выключен в этом чате",
    STATUS_NOT_CONFIGURED: "инструмент не подключён (нет доступа к провайдеру)",
    STATUS_TEMPORARILY_UNAVAILABLE: "провайдер временно не отвечает",
    STATUS_QUOTA_EXHAUSTED: "суточная квота исчерпана",
    STATUS_UNSUPPORTED: "такой запрос инструмент не поддерживает",
    STATUS_UNKNOWN: "состояние инструмента неизвестно",
}


def notice_block(state: CapabilityState) -> str:
    """Правдивая подсказка Writer'у о реальном состоянии способности.

    Инжектится только когда пользователь явно поручил действие, а capability
    не готова: «не умею» без проверки и обещание недоступного запрещены
    (SOUL-AMD.5.14). Никаких секретов/приватных id (R17)."""
    if state.status == STATUS_READY:
        return ""
    hint = _STATUS_HINT.get(state.status, "состояние неизвестно")
    return ("<capability_notice status=\"%s\" capability=\"%s\">\n"
            "Инструмент %s сейчас недоступен: %s (причина: %s).\n"
            "Не обещай выполнить это действие и не выдумывай результат; если "
            "пользователь его просил - честно и коротко объясни отказ в своём "
            "голосе, без фразы «я вообще не умею».\n"
            "Эта пометка отражает состояние на момент планирования хода. Если "
            "позже в этом же ходе действие фактически выполнилось и результат "
            "отправлен - описывай фактический результат, а не отказ; "
            "недоступность одной операции не означает недоступности остальных.\n"
            "</capability_notice>") % (
        state.status, state.capability_id, state.capability_id, hint,
        state.reason_code or "unknown")


def emit_capability_event(state: CapabilityState, *, outcome: str,
                          chat_id: int | None = None, trace_id: str = "",
                          template_id: str = "") -> None:
    """Трасса «намерение → capability → check → call» (SOUL-AMD.6.5; R17).

    Тот же канал, что у терминала генерации (`mca_events`), без текстов
    промптов: коды/статусы/Registry ID шаблона."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event(
            "capability_check", outcome=outcome,
            component="capability_registry", status=state.status,
            entity_id=state.capability_id, chat_id=chat_id,
            trace_id=trace_id or None,
            reason_code=_event_reason_code(state))
        if template_id:
            emit_mca_event(
                "capability_message", outcome=outcome,
                component="capability_registry", entity_id=template_id,
                status=state.status, chat_id=chat_id,
                trace_id=trace_id or None)
    except Exception:      # pragma: no cover - телеметрия не рвёт чат
        pass


def _event_reason_code(state: CapabilityState) -> str:
    """Статус → существующий §17.2 reason_code (словарь не расширяем)."""
    return {
        STATUS_DISABLED: "financial_limit_disabled",
        STATUS_NOT_CONFIGURED: "provider_unconfigured",
        STATUS_TEMPORARILY_UNAVAILABLE: "provider_unavailable",
        STATUS_QUOTA_EXHAUSTED: "financial_limit_reached",
    }.get(state.status, "")


__all__ = [
    "CapabilityState", "STATUSES", "STATUS_READY", "STATUS_DISABLED",
    "STATUS_NOT_CONFIGURED", "STATUS_TEMPORARILY_UNAVAILABLE",
    "STATUS_QUOTA_EXHAUSTED", "STATUS_UNSUPPORTED", "STATUS_UNKNOWN",
    "RESULT_UNKNOWN", "RESULT_SUCCESS", "RESULT_FAILED",
    "RESULT_DELIVERY_FAILED", "TTL_SECONDS", "OUTCOME_COOLDOWN_SECONDS",
    "resolve", "resolve_many", "capability_view", "invalidate", "reset_cache",
    "record_outcome", "failure_text", "status_message",
    "failure_message_for_reason", "failure_code_for_reason",
    "failure_code_for_status", "clarify_text", "message_block_id",
    "CLARIFY_BLOCK_ID", "notice_block", "emit_capability_event",
    "image_quota_state",
]
