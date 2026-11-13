"""F21 (раунд 10.24, ADR-1024-22) — единый master-рубильник бюджетов.

Ключ `flags.budgets_enabled` (каталоговый, default ON) выключает
enforcement бюджетов ЦЕЛИКОМ — глобально ИЛИ per-chat. OFF = лимиты не
ограничивают (direct и фон), контекст не режется; УЧЁТ статистики при этом
продолжается (счётчики пишутся всегда). OFF НЕ отменяет права доступа
(`keys.allow_global=false`), BYOK-ключи, выбор провайдера/модели.

Контракт резолва (единственная точка): `chat → global → default(True)`.

SMART-EXECUTION-RELIABILITY-01 (этап A, owner input 2026-11-14 §A1):
* достоверно прочитанное значение запоминается как **last-known-valid** для
  своего scope; ошибка чтения НЕ может незаметно превратить известный OFF в
  ON — возвращается последнее достоверное значение (`source='last_known'`,
  `stale=True`);
* если достоверного значения ещё нет, берётся глобальный слой (chat-override
  неизвестен — это явно помечается), и только затем заводской default;
  такая резолюция помечается `known=False`/`stale=True` и WARNING-логом —
  «отсутствие достоверной конфигурации» диагностируется явно, а не выдаётся
  за штатный ON;
* явно сохранённый chat-override всегда приоритетнее глобального слоя;
  пользовательские значения не перезаписываются.

R17/R18-safe: успешный резолв оставляет debug-лог `[settings] key/chat/source`
(внутри `resolve_setting_cached`), WARNING-и пишут только scope/source —
значения (в т.ч. секреты) не логируются.
"""
import logging
from dataclasses import dataclass

from config.settings import settings

logger = logging.getLogger(__name__)

# pg-ключ master-рубильника (каталог `param_catalog`, группа flags_module_budgets).
KEY_BUDGETS_ENABLED = "flags.budgets_enabled"

#: Источники резолюции (наблюдаемые; R16-аддитивно).
SOURCE_CHAT = "chat"
SOURCE_GLOBAL = "global"
SOURCE_DEFAULT = "default"
SOURCE_LAST_KNOWN = "last_known"
SOURCE_UNKNOWN = "unknown"

#: Границы last-known-valid кэша (per-process; scope = chat_id | None).
_MAX_KNOWN_SCOPES = 512


@dataclass(frozen=True)
class BudgetState:
    """Эффективное состояние master-рубильника + происхождение значения.

    ``enabled`` — итоговая резолюция (True = enforcement бюджетов включён);
    ``source`` — ``chat|global|default`` (достоверный слой),
    ``last_known`` (ошибка чтения, отдано последнее достоверное),
    ``unknown`` (достоверной конфигурации нет, использован заводской default);
    ``stale`` — значение не из свежего чтения;
    ``known`` — есть достоверная конфигурация (False = конфигурация
    недоступна; состояние видно в логах/диагностике, а не замаскировано).
    """

    enabled: bool
    source: str = SOURCE_DEFAULT
    chat_id: int | None = None
    stale: bool = False
    known: bool = True

    def as_meta(self) -> dict:
        """R17-safe снимок для телеметрии/диагностики (без значений секретов)."""
        return {
            "budgets_enabled": bool(self.enabled),
            "source": str(self.source),
            "stale": bool(self.stale),
            "known": bool(self.known),
        }


#: last-known-valid: scope → достоверное состояние (порядок вставки = LRU-ish).
_KNOWN: dict[int | None, BudgetState] = {}


def _factory_default() -> bool:
    return bool(getattr(settings, "BUDGETS_ENABLED", True))


def _remember(state: BudgetState) -> None:
    """Запомнить достоверную резолюцию scope (никогда не бросает)."""
    try:
        key = state.chat_id
        _KNOWN.pop(key, None)          # обновить порядок вставки
        _KNOWN[key] = state
        while len(_KNOWN) > _MAX_KNOWN_SCOPES:
            oldest = next(iter(_KNOWN))
            _KNOWN.pop(oldest, None)
    except Exception:       # pragma: no cover - защитная ветка
        return


def _last_known(chat_id: int | None) -> BudgetState | None:
    try:
        return _KNOWN.get(chat_id)
    except Exception:       # pragma: no cover - защитная ветка
        return None


def reset_cache() -> None:
    """Сбросить last-known-valid (тесты/переинициализация процесса)."""
    _KNOWN.clear()


def last_known_state(chat_id: int | None = None) -> BudgetState | None:
    """Последнее достоверное состояние scope (наблюдаемость; без I/O)."""
    return _last_known(chat_id)


async def _read_layers(chat_id: int | None) -> tuple[bool | None, str]:
    """Прочитать слои без подмены ошибки дефолтом.

    Возвращает ``(value | None, source)``: ``source='error'`` ⇔ достоверного
    значения нет (chat-слой недоступен/резолвер упал)."""
    from services import worker_settings
    default = _factory_default()
    try:
        value, source = await worker_settings.resolve_setting_with_source(
            KEY_BUDGETS_ENABLED, chat_id=chat_id, default=default)
    except Exception:
        logger.warning(
            "[budget_gate] master flag resolve failed | chat=%s", chat_id,
            exc_info=True)
        return None, "error"
    if source not in (SOURCE_CHAT, SOURCE_GLOBAL, SOURCE_DEFAULT):
        # 'error' = chat-слой недоступен; значение пришло из глобального слоя
        # без учёта возможного chat-override → неполная резолюция.
        return None, "error"
    if value is None:
        return None, "error"
    try:
        return bool(value), source
    except Exception:       # pragma: no cover - защитная ветка
        return None, "error"


async def resolve_budgets(chat_id: int | None = None) -> BudgetState:
    """Эффективное состояние master-рубильника (единственная точка резолва).

    Приоритет: chat override → global → `settings.BUDGETS_ENABLED`.
    Ошибка чтения: last-known-valid scope → глобальный слой (chat-override
    неизвестен, явная пометка) → заводской default (`known=False`).
    Известный OFF никогда не превращается в ON из-за технической ошибки."""
    value, source = await _read_layers(chat_id)
    if value is not None:
        state = BudgetState(enabled=bool(value), source=source, chat_id=chat_id)
        _remember(state)
        return state
    cached = _last_known(chat_id)
    if cached is not None:
        logger.warning(
            "[budget_gate] config unavailable — last-known-valid | chat=%s | "
            "enabled=%s | source=%s", chat_id, cached.enabled, cached.source)
        return BudgetState(enabled=bool(cached.enabled),
                           source=SOURCE_LAST_KNOWN, chat_id=chat_id,
                           stale=True, known=True)
    # Достоверного значения для этого scope ещё нет: глобальный слой —
    # максимально близкое к истине, но chat-override остаётся неизвестным.
    if chat_id is not None:
        global_value, global_source = await _read_layers(None)
        if global_value is not None:
            logger.warning(
                "[budget_gate] chat layer unavailable — global value used | "
                "chat=%s | enabled=%s | source=%s", chat_id, global_value,
                global_source)
            return BudgetState(enabled=bool(global_value),
                               source=str(global_source), chat_id=chat_id,
                               stale=True, known=False)
    factory = _factory_default()
    logger.warning(
        "[budget_gate] no trustworthy config — factory default used | "
        "chat=%s | enabled=%s", chat_id, factory)
    return BudgetState(enabled=factory, source=SOURCE_UNKNOWN, chat_id=chat_id,
                       stale=True, known=False)


async def budgets_enabled(chat_id: int | None = None) -> bool:
    """Master-рубильник бюджетов: True = enforcement включён, False = OFF.

    `chat_id=None` (фон-скоп `'global'`) видит только глобальный слой.
    Никогда не бросает (см. :func:`resolve_budgets` про ошибку чтения)."""
    try:
        state = await resolve_budgets(chat_id)
        return bool(state.enabled)
    except Exception:       # pragma: no cover - защитная ветка
        cached = _last_known(chat_id)
        if cached is not None:
            logger.warning(
                "[budget_gate] resolve crashed — last-known-valid | chat=%s | "
                "enabled=%s", chat_id, cached.enabled, exc_info=True)
            return bool(cached.enabled)
        # Известного состояния нет: не выдаём техническую ошибку за ON-
        # enforcement — бюджеты не ограничивают (owner §A1), состояние видно
        # по WARNING.
        logger.warning(
            "[budget_gate] resolve crashed — no known state, enforcement off "
            "| chat=%s", chat_id, exc_info=True)
        return False
