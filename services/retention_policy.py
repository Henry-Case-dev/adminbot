"""F3/F7 (10.19, ADR-1019-8 D5, ADR-1019-6 D1/D1a) — policy-слой срока
хранения импортированной истории (DB-слой и call-site — F7).

Sentinel-семейство **retention** (НЕ бюджет!): `0` = вечно → purge
импортированной истории КАТЕГОРИЧЕСКИ запрещён; `>0` = хранить N дней;
`<0`/мусор = невалидно → fallback на глобальный дефолт + WARNING.

D-5 (ревью Батча C): `imported_history_purge_allowed` — **policy-хелпер**,
DB-слой (`DatabaseService.purge_imported_history`, keyword-only) и
единственный call-site (`services/memory_maintenance.py::run_import_retention`)
реализованы в F7. Destructive-purge защищён двумя независимыми барьерами:

  * **fail-closed по недоступности chat-слоя** (D-1, ревью Батча E):
    `worker_settings.resolve_setting_with_source` отдаёт `source='error'`,
    когда chat-слой НЕ читается (нет `ChatParamsPool`/ошибка PG) — иначе
    fail-open дефолт (180) молча «разрешал» purge. `source='error'` →
    `(0, 'error')` → `allowed=False`, а `run_import_retention` отказывается
    от прогона ЦЕЛИКОМ (не строит `chat_cutoffs` из default).
  * **жёсткий deny по данным сида** (`config/chat_settings_seed.json` → `enforce`):
    chat_id с retention-`enforce` не попадает в purge даже при кривом
    резолве/недоступном сиде-рантайме (`chat_settings_seed.enforced_eternal_chat_ids_checked`).
    D-2.4 (ревью итерации 4): НЕЧИТАЕМЫЙ сид → `source='seed_unavailable'`
    → purge запрещён (fail-safe), а не молча разрешён при отключённом барьере.

Fail-**closed** (D-5): ошибка резолва → `allowed=False` (безопасный
дефолт для РАЗРУШИТЕЛЬНОЙ операции — лучше не удалять, чем удалить зря).
Невалидный override (`<0`/мусор) — не ошибка, а явный fallback на
глобальный дефолт (fail-safe).
"""
import logging

from config.settings import settings
from services import budget_limits

logger = logging.getLogger(__name__)

RETENTION_KEY = "limits.import_history_retention_days"
RETENTION_DEFAULT = settings.IMPORT_HISTORY_RETENTION_DAYS


def retention_state(days) -> str:
    """`'eternal'` (==0) | `'cap'` (>0) | `'invalid'` (<0/мусор) — реэкспорт
    единого sentinel-резолвера F3 (`budget_limits.retention_state`), чтобы
    consumers F7 не тянули два модуля."""
    return budget_limits.retention_state(days)


# D-2.1 (Medium, ревью итерации 4): нормализуем ГЛОБАЛЬНЫЙ дефолт ОДИН раз
# детерминированно. Раньше `_normalized` при `state == 'invalid'` вызывал сам
# себя с тем же `RETENTION_DEFAULT`: при `IMPORT_HISTORY_RETENTION_DAYS < 0`
# (env читается `_env_int` без clamp) это давало `RecursionError` и полностью
# ломало retention. Невалидный дефолт → безопасный cap `180` (НЕ «минус дней»).
def _fallback_for(default_value) -> int:
    """D-2.1: детерминированная нормализация заданного глобального дефолта."""
    return default_value if retention_state(default_value) != "invalid" else 180


_FALLBACK_DAYS = _fallback_for(RETENTION_DEFAULT)


def normalized_retention_default() -> int:
    """D-2.6: единый нормализованный fallback глобального дефолта для
    consumers (UI-сводка `oversight`) — один источник истины (без повторного
    `int(STORAGE_DEFAULT)` с риском label «-1 дней»)."""
    return _FALLBACK_DAYS


def _enforced_eternal_chat_ids() -> tuple[set[int], bool]:
    """`(chat_ids, seed_ok)` — chat_id с retention-`enforce` из данных сида
    (hard-deny, D-1).

    D-2.4 (Low, ревью итерации 4): нечитаемый/битый сид больше НЕ fail-open —
    `seed_ok=False` заставляет вызывающего ЗАПРЕТИТЬ purge (fail-safe),
    а не разрешить его при молча отключённом втором барьере. Разбор файла
    кэшируется в `chat_settings_seed` (mtime+size)."""
    try:
        from services import chat_settings_seed
        return chat_settings_seed.enforced_eternal_chat_ids_checked()
    except Exception:
        logger.warning("[retention] chat settings seed enforce unavailable — "
                       "purge denied (fail-safe)", exc_info=True)
        return set(), False


async def resolve_import_retention_days(chat_id: int) -> tuple[int, str]:
    """`(days, source)` — per-chat срок хранения импорта.

    Приоритет: chat → global → default (ADR-1018-7). Нормализация:
    `0` = вечно (0), `>0` = N дней, `<0`/мусор = невалидно → глобальный
    дефолт + WARNING (fail-safe). Ошибка резолва → `(0, 'error')` — «вечно»,
    безопасно для разрушительной операции. R17: только числа/источник."""
    days, source = await _resolve_days(chat_id)
    return days, source


async def _resolve_days(chat_id: int) -> tuple[int, str]:
    # Hard-deny (D-1): чат с retention-`enforce` в данных сида никогда не
    # получает «разрешение» на purge, даже если резолв fail-open отдал 180.
    enforced, seed_ok = _enforced_eternal_chat_ids()
    if not seed_ok:
        # D-2.4: сид недоступен → второй барьер отключён. Для РАЗРУШИТЕЛЬНОЙ
        # операции это значит «не удалять» (fail-safe), а не «удалять всем».
        logger.warning("[retention] seed unavailable — purge denied (fail-safe) "
                       "| chat=%s", chat_id)
        return 0, "seed_unavailable"
    if int(chat_id) in enforced:
        return 0, "seed_enforced"
    value = RETENTION_DEFAULT
    source = "default"
    try:
        from services.worker_settings import resolve_setting_with_source
        value, source = await resolve_setting_with_source(
            RETENTION_KEY, chat_id=chat_id, default=RETENTION_DEFAULT)
    except Exception:
        logger.warning("[retention] resolve failed — fail-closed (вечно) | "
                       "chat=%s", chat_id, exc_info=True)
        return 0, "error"
    if source == "error":
        # D-1: chat-слой не читается → НЕ доверяем fail-open дефолту.
        logger.warning("[retention] chat layer unavailable — fail-closed | "
                       "chat=%s", chat_id)
        return 0, "error"
    state = retention_state(value)
    if state == "invalid":
        logger.warning("[retention] invalid override — global default | "
                       "chat=%s", chat_id)
        return _normalized(RETENTION_DEFAULT, "default")
    return _normalized(value, source)


def _normalized(days, source: str) -> tuple[int, str]:
    state = retention_state(days)
    if state == "invalid":
        # D-2.1: НЕ рекурсия — детерминированный нормализованный fallback.
        return _FALLBACK_DAYS, "default"
    return (0 if state == "eternal" else int(days)), source


async def imported_history_purge_allowed(chat_id: int) -> tuple[bool, int, str]:
    """`(allowed, days, source)` для чата.

    `allowed = (days != 0)`. `days == 0` (вечно) → purge запрещён.
    Невалидный override (`<0`/мусор) → глобальный дефолт + WARNING
    (fail-safe: негатив не может означать «минус дней» и не открывает purge).
    **Ошибка/недоступность chat-слоя → fail-closed** `allowed=False`,
    `source='error'`: для разрушительной операции «не удалять» — безопасный
    дефолт (D-5/D-1)."""
    days, source = await _resolve_days(chat_id)
    return days != 0, days, source
