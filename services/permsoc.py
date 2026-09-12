"""Раунд 10 (permsoc-module-isolation, F-9 §2-§4) — плагин «Функции PERMsoc».

Единый плагин 5 хардкод-триггеров персон (Славик 479167456, Костя
350803143, Леха/Алан 138811255, Оля 834424825, передразнивания/mimic).
`PermsocGateFilter(module_id)` — aiogram BaseFilter: async-гейт ПО СООБЩЕНИЮ
(master-тумблер + под-флаг модуля); фильтры в декораторах — ДОВАВКА к
существующим (порядок роутеров bot.py НЕ меняется; роутеры всегда
зарегистрированы — при выключенном модуле фильтр False = тихий игнор).

Приоритеты:
  * master: chat_params.gates.permsoc (явный) → overrides['flags.permsoc_enabled']
    → hot.get('flags.permsoc_enabled', False). Дефолт FALSE (Q2-правка
    @Architect T-878: безопаснее для новых чатов; живые чаты — бэкфил Q3).
  * под-флаги: flags.olya_enabled / flags.mimic_enabled — через hot_chat
    (per-chat override поверх глобального дефолта).
  * master OFF → ВСЕ 5 модулей игнор (полное молчание); под-флаг OFF —
    точечное выключение модуля.

Fail-open (§1-6): PG/кэш недоступен → безопасный дефолт («выключено»),
модуль не стреляет случайно; повторная ошибка — WARNING, не спам.
"""
import logging

from dataclasses import dataclass

from aiogram.filters import BaseFilter
from aiogram.types import Message

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

MASTER_FLAG_KEY = "flags.permsoc_enabled"


@dataclass(frozen=True)
class PermsocModule:
    module_id: str                # 'slavik'|'kostik'|'alan'|'olya'|'mimic'
    title_ru: str
    target_user_id_key: str | None    # reactions.slavik_user_id и т.п.
    sub_flag_key: str | None          # flags.olya_enabled и т.п. (None — нет)
    user_ids: tuple[int, ...]         # хардкод-иды для аудита/телеметрии
    dependencies: tuple[str, ...] = ()

    @property
    def has_sub_flag(self) -> bool:
        return self.sub_flag_key is not None


PERMSOC_MODULES: tuple[PermsocModule, ...] = (
    PermsocModule("slavik", "Славик (приветствия, kucha-реакции, GIF)",
                  "reactions.slavik_user_id", "flags.slavik_enabled", (479167456,),
                  ("handlers/slavik.py",)),
    PermsocModule("kostik", "Костя (персона-реплики)",
                  "reactions.kostik_user_id", "flags.kostik_enabled",
                  (350803143,), ("handlers/kostik.py",)),
    # (P1-правка Builder): модуль alan управляется ТОЛЬКО master (реплики и
    # приветствие — как у slavik/kostik, «включены по умолчанию» MEMORY.md);
    # под-флаг reactions.alan_mimic_enabled остаётся ВНУТРИ common-mimic
    # (проверка per-user в handlers/common.py) — иначе прод-гейт выключил бы
    # живое приветствие Лехи (сид флага = False), несоответствие §3.7/Q2.
    PermsocModule("alan", "Леха/Алан (имитация, приветствие)",
                  "reactions.alan_user_id", None,
                  (138811255,), ("handlers/alan.py", "alan_greeting.py")),
    PermsocModule("olya", "Оля (видео-реакция)", None,
                  "flags.olya_enabled", (834424825,),
                  ("olya_relay.py", "filters/olya_video.py")),
    PermsocModule("mimic", "Передразнивания (mimic)", None,
                  "flags.mimic_enabled", (),
                  ("mimic_relay.py", "mimic_transform.py")),
)

_MODULE_BY_ID: dict[str, PermsocModule] = {
    m.module_id: m for m in PERMSOC_MODULES}

# Под-флаг-дефолты (дефолт False — как сейчас: olya/mimic off).
# Славик — дефолт True (ADR-109-4: untouched → прежнее поведение).
DEFAULT_SUB_FLAGS: dict[str, bool] = {
    "flags.slavik_enabled": True,
    # Раунд 10.12 (ADR-1012-1 D3): Костик получил независимый тумблер;
    # default True — поведение по умолчанию идентично прежнему (master ON).
    "flags.kostik_enabled": True,
    "flags.olya_enabled": False,
    "flags.mimic_enabled": False,
}


def get_module(module_id: str) -> PermsocModule | None:
    return _MODULE_BY_ID.get(module_id)


def master_flag_default() -> bool:
    """Глобальный дефолт master-флага (safety-first: False)."""
    return False


async def master_enabled(chat_id: int) -> bool:
    """Master-тумблер (Q2): gates.permsoc (явный) → override флага →
    hot.get(flags.permsoc_enabled, False). Fail-open → False."""
    try:
        from services.chat_params import get_all_chat_params
        root = await get_all_chat_params(chat_id)
        gates = root.get("gates") or {}
        if "permsoc" in gates:
            return bool(gates["permsoc"])
        overrides = root.get("overrides") or {}
        if MASTER_FLAG_KEY in overrides:
            return bool(overrides[MASTER_FLAG_KEY])
        return bool(hot.get(MASTER_FLAG_KEY, False))
    except Exception:
        logger.warning("[permsoc] master check failed — FAIL-OPEN OFF | "
                       "chat=%s", chat_id, exc_info=True)
        return False


async def permsoc_enabled(chat_id: int) -> bool:
    """Алиас master_enabled (спец-имя, F-9 §4)."""
    return await master_enabled(chat_id)


async def module_enabled(chat_id: int, module_id: str) -> bool:
    """Под-флаг модуля (Q2): нет суб-флага → True; иначе hot_chat-значение
    (per-chat override поверх глобального дефолта). Fail-open → False."""
    module = _MODULE_BY_ID.get(module_id)
    if module is None:
        return False
    if module.sub_flag_key is None:
        return True
    flag_key = module.sub_flag_key
    default = DEFAULT_SUB_FLAGS.get(flag_key, False)
    try:
        from services.chat_params import get_chat_param
        return bool(await get_chat_param(chat_id, flag_key, default))
    except Exception:
        logger.warning("[permsoc] sub-flag check failed — FAIL-OPEN OFF | "
                       "chat=%s module=%s", chat_id, module_id, exc_info=True)
        return False


class PermsocGateFilter(BaseFilter):
    """Асинхронный гейт премока (F-9 §2): модуль включён для ЭТОГО чата?

    Стоит ПЕРВЫМ фильтром в декораторах (дешёвый гейт ДО user-match);
    UserIdFilter — остаётся ВТОРЫМ (не меняем существующие вторые фильтры).
    Возвращает True/False (не UNHANDLED-паттерн)."""

    def __init__(self, module_id: str):
        self.module_id = module_id

    async def __call__(self, obj) -> bool:
        """obj — Message (обычные сообщения) или ChatMemberUpdated (join-
        ветка Алана): у обоих есть .chat."""
        chat = getattr(obj, "chat", None)
        if chat is None:
            return False                      # приватные/каналы → False
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            return False
        try:
            if not await master_enabled(chat_id):
                return False
            return await module_enabled(chat_id, self.module_id)
        except Exception:
            logger.warning(
                "[permsoc] gate failed — FAIL-OPEN OFF | chat=%s module=%s",
                chat_id, self.module_id, exc_info=True)
            return False
