"""Epic 42 — Checkup handler (R42-1, D162, Section 51.7).

Роутер 0g (после 0f web, под гейтом SUMMARY_ENABLED). Observer-стиль
(прецедент 0d search): не-триггер → return UNHANDLED, любой ответ → консьюм.
ВСЕ ответы (отчёт, 5.1, фолбек, dead, LLM-ошибка) — реплаем на
message.message_id (R42-1). Кулдаун per-chat (T-328-C): слот (chat_id, 0).
"""
import logging
import random
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services import command_prefix
from services import command_registry
from services import diagnostic_policy
from services import hot_config as hot
from services.llm_client import LLMBadResponseError, LLMError
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.smartmodule_concurrency import (
    get_smartmodule_concurrency_pool,
    smartmodule_wait_seconds,
)
from services.smartmodule_phrases import (
    CHECKUP_DEAD_PHRASES,
    CHECKUP_FALLBACK_PHRASES,
    CHECKUP_LLM_ERROR_PHRASES,
    SMARTMODULE_BUSY_PHRASES,
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.system_logs_fetcher import CheckupLogsUnavailableException
from services.typing_manager import typing_active

logger = logging.getLogger(__name__)

checkup_router = Router(name="checkup")

_service = None                                   # CheckupService (DI)
_fetcher = None                                   # CheckupLogsFetcher (DI)
_cooldown = CooldownTracker(settings.CHECKUP_COOLDOWN_SECONDS)
_CHAT_SLOT = 0                                    # per-chat кулдаун (T-328-C)

# Раунд 10.15 (F6, T-1596): ДВА пути.
# 1) bare-исключение «чекап» — как раньше (без префикса, слово целиком);
# 2) prefixed: Префикс + (ты в порядке|живой?|чекни здоровье) по остатку.
# F6-U1: legacy-фразы «живой собака», «пульс бота», «как сервак» из префиксного
# пути УДАЛЕНЫ.
_BARE_CHECKUP_RE = re.compile(
    r"(?:^|[\s\u00ab\u00bb\"'(\[\-])"
    r"чекап"
    r"(?=[\s!?.,;:\u2026\u00ab\u00bb)]*$)",
    re.IGNORECASE,
)


def _is_checkup_trigger(text: str) -> bool:
    """bare «чекап» ИЛИ префикс + канонический checkup-триггер (§5)."""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _BARE_CHECKUP_RE.search(stripped):
        return True
    tok, body = command_prefix.split_prefix(stripped)
    if tok is None:
        return False
    return command_registry.matches_group("checkup", body)


def setup_checkup(service, fetcher, db=None) -> None:
    """DI: CheckupService + CheckupLogsFetcher. Вызывается из bot.py
    on_startup (51.9). Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED →
    персистентный кулдаун (throttle_state, scope='checkup')."""
    global _service, _fetcher, _cooldown
    _service = service
    _fetcher = fetcher
    _cooldown = make_cooldown(
        "checkup", settings.CHECKUP_COOLDOWN_SECONDS, db)


def _diag_runtime():
    """(cache, pg) существующего слоя прав; недоступность — не падение."""
    try:
        cache = hot.get_config_cache()
    except Exception:
        cache = None
    pg = getattr(cache, "pg", None) if cache is not None else None
    if getattr(pg, "pool", None) is None:
        pg = None
    return cache, pg


async def _checkup_diagnostic_gate(actor_id, chat_id):
    """Разрешение на чекап: запуск проверки + право видеть логи чата.

    Возвращает `(gate, denied_decision)`: `gate` — открытое разрешение для
    перепроверки перед публикацией; `denied_decision` — отказ политики
    (тогда отчёт не формируется и логи не читаются).

    Недоступность слоя прав — это ОТКАЗ, а не обход: без проверки запрет
    доказать нельзя, поэтому чекап не выполняется и не публикуется.
    """
    cache, pg = _diag_runtime()
    try:
        gate = await diagnostic_policy.open_gate(
            "bot_server_state", "run", telegram_id=actor_id,
            chat_id=chat_id, cache=cache, pg=pg, destination="checkup",
            also=(("logs_traceback", "view"),))
    except Exception:
        logger.warning("[checkup] diagnostic policy unavailable — checkup "
                       "denied | chat=%s", chat_id, exc_info=True)
        return None, diagnostic_policy.policy_unavailable_denial(
            "bot_server_state", "run", chat_id=chat_id)
    if not gate.decision.allowed:
        return gate, gate.decision
    return gate, None


@checkup_router.message()
async def checkup_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or _fetcher is None or bot is None:
        return UNHANDLED
    # Раунд 10.6 (T-1201/A1): master-флаг модуля (default ON).
    if not hot.get("flags.checkup_enabled", settings.CHECKUP_ENABLED):
        return UNHANDLED
    text = (message.text or message.caption or "").strip()
    if not text or not _is_checkup_trigger(text):
        return UNHANDLED                       # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[checkup] triggered | chat=%s user=%s", message.chat.id, user_id)
    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.checkup_cooldown_seconds",
                                        settings.CHECKUP_COOLDOWN_SECONDS))
    remaining = await cooldown_remaining(_cooldown, message.chat.id, _CHAT_SLOT)
    if remaining > 0:                          # 5.1 → реплай на триггер
        await _reply(bot, message.chat.id, throttle_phrase(remaining),
                     message.message_id)
        return
    await cooldown_touch(_cooldown, message.chat.id, _CHAT_SLOT)
    # SELF-DIAG-01 D2 (owner amendment 2026-11-09 §5): «чекап» — такой же
    # вход, как tool/API, и не является обходом политики диагностики.
    # Решение принимается ДО чтения логов; отчёт перепроверяется и
    # очищается от секретов ПЕРЕД отправкой. Промпт и характер чекапа не
    # меняются — гейт стоит только на доступе к данным.
    actor_id = message.from_user.id if message.from_user else None
    gate, denied = await _checkup_diagnostic_gate(actor_id, message.chat.id)
    if denied is not None:
        logger.info("[checkup] denied by diagnostic policy | chat=%s user=%s "
                    "| reason=%s", message.chat.id, actor_id,
                    denied.reason_code)
        await _reply(bot, message.chat.id,
                     diagnostic_policy.denial_message(denied),
                     message.message_id)
        return
    if gate is None:                       # защита от будущих правок: без
        logger.error("[checkup] no gate — report is not published | chat=%s",
                     message.chat.id)      # разрешения публикации не бывает
        return
    try:
        logs, used_fallback = await _fetcher.fetch()
    except CheckupLogsUnavailableException as exc:
        # Epic 49 (D199): WARNING без traceback (ожидаемая ветка, D190-стиль)
        logger.warning("[checkup] all log sources failed | chat=%s | error=%s",
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_DEAD_PHRASES),
                     message.message_id)
        return
    if used_fallback:                          # R42-2: фолбек-фраза ДО LLM (юзер ждёт)
        logger.warning("[checkup] fallback phrase sent | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_FALLBACK_PHRASES),
                     message.message_id)
    # Раунд N (T-841): слот пула per-chat перед LLM-вызовом checkup
    # (fetch логов выше — сетевой шаг, в пул не входит). Таймаут → busy-фраза.
    pool = get_smartmodule_concurrency_pool()
    permit = await pool.try_acquire(message.chat.id,
                                    timeout=smartmodule_wait_seconds())
    if permit is None:
        logger.warning("[checkup] concurrency slot timeout | chat=%s",
                       message.chat.id)
        await _reply(bot, message.chat.id,
                     random.choice(SMARTMODULE_BUSY_PHRASES),
                     message.message_id)
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» вокруг _service.checkup (65.7).
        async with typing_active(bot, message.chat.id):
            # UNIFIED-CORE (P0, 20.10.2026): chat_id → Core + Expression
            # владельца в канон чек-апа (пользовательский речевой маршрут).
            report = await _service.checkup(logs, used_fallback,
                                            chat_id=message.chat.id)
        # SELF-DIAG-01 D2: перепроверка прав ПЕРЕД публикацией (отзыв
        # действует на уже запущенную проверку) + удаление секретов.
        try:
            pub_cache, pub_pg = _diag_runtime()
            publication = await diagnostic_policy.publish(
                gate, report, cache=pub_cache, pg=pub_pg, kind="final")
        except Exception:
            logger.exception("[checkup] publication guard failed | chat=%s",
                             message.chat.id)
            return
        if not publication.allowed:
            logger.info("[checkup] publication blocked | chat=%s | "
                        "reason=%s", message.chat.id,
                        publication.decision.reason_code)
            await _reply(bot, message.chat.id,
                         diagnostic_policy.denial_message(
                             publication.decision),
                         message.message_id)
            return
        report = publication.text
        await send_chunked_reply(bot, message.chat.id, report, message.message_id)
        logger.info("[checkup] report sent | chat=%s", message.chat.id)
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[checkup] empty answer — silence | chat=%s | error=%s",
                       message.chat.id, exc)
        await react_moai(bot, message.chat.id, message.message_id)
    except LLMError as exc:
        # Epic 47/49 (D190/D199): WARNING без traceback (ожидаемая ветка)
        logger.warning("[checkup] LLM failed | chat=%s | error=%s",
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_LLM_ERROR_PHRASES),
                     message.message_id)
    except Exception:
        logger.exception("[checkup] unexpected error | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_LLM_ERROR_PHRASES),
                     message.message_id)
    finally:
        permit.release()
