"""Epic 33 — FactCheck handler (R33-3, D106/D107, Section 42.7.1).

Роутер 0c (после 0b summary, ДО 0:admin). Observer-стиль (прецедент 0a
summary_observer): не-триггер → return UNHANDLED (пропагация живёт), любой
ответ → консьюм. Триггер: reply/репост, текст вызова начинается со слова
«фактчек» (регистронезависимо, граница слова — «фактчекинг» НЕ матчится).

Reply-таргеты (контракт R33-3): вердикт, 5.3 (пустой контекст), 5.4b
(ошибка поиска), 5.5 (ошибка LLM) → reply на target.message_id (ЦЕЛЕВОЕ);
троттлинг 5.1 → reply на message.message_id (ВЫЗОВ, D107). Кулдаун
FACTCHECK_COOLDOWN_SECONDS per (chat, user), независимый (CooldownTracker).
"""
import logging
import random
import re

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from handlers.summary import _extract_forward_source
from handlers.voice_transcription import _is_transcription_target
from services import hot_config as hot
from services.chat_params import get_chat_param as _cp_g
from services.llm_client import LLMBadResponseError, LLMError
from services.media_group_buffer import get_media_group_caption
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.search_aggregator import AllSearchEnginesFailedException
from services.smart_cache import get_smart_cache
from services.smartmodule_concurrency import (
    get_smartmodule_concurrency_pool,
    smartmodule_wait_seconds,
)
from services.smartmodule_phrases import (
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    LLM_ERROR_PHRASES,
    SMARTMODULE_BUSY_PHRASES,
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.typing_manager import typing_active

logger = logging.getLogger(__name__)

factcheck_router = Router(name="factcheck")


def _temporal_on() -> bool:
    """MCA-20 K1 (мастер-рубильник envelope-пайплайна, default ON)."""
    try:
        from services import mca_gates
        return bool(mca_gates.temporal_factcheck_enabled())
    except Exception:      # pragma: no cover - гейт не бросает
        return False


async def _factcheck_temporal(message: types.Message, bot: Bot,
                              target: types.Message, target_text: str,
                              user_hint: str | None,
                              forward_source: str | None) -> None:
    """MCA-20 ON-путь (D3/D9/D12): один resolver → TemporalClaimEnvelope →
    составной кеш-ключ `factcheck_temporal` (авто-bypass при unknown origin)
    → envelope-пайплайн единого сервиса. Ответ — reply на ЦЕЛЕВОЕ (5.3/5.4b/
    5.5-контракт legacy сохранён)."""
    from services import mca_gates, temporal_factcheck as tf

    chat_id = message.chat.id
    kind = "reply" if target is not message else "command"
    ref = tf.InputRef(
        kind=kind, chat_id=chat_id,
        target_tg_message_id=target.message_id,
        trigger_tg_message_id=message.message_id,
        hint=user_hint)
    try:
        default_mode = await _cp_g(
            chat_id, "temporal.default_mode",
            getattr(settings, "TEMPORAL_DEFAULT_MODE", "contextual"))
    except Exception:
        default_mode = getattr(settings, "TEMPORAL_DEFAULT_MODE", "contextual")

    envelope, reject_reason = await tf.build_envelope(
        _db, ref, default_mode=str(default_mode or "contextual"))
    cache = get_smart_cache()
    scope = f"chat:{chat_id}"
    cache_key = None
    cached = None
    if envelope is not None:
        # D12: ключ построим? unknown origin → None = авто-bypass (вычислять
        # без кеширования готовых вердиктов, reason temporal_cache_disabled).
        cache_key = tf.build_temporal_cache_key(envelope, scope=scope)
        if cache_key is None:
            tf.stage_event("target_resolve", "skipped",
                           reason_code="temporal_cache_disabled",
                           chat_id=chat_id)
        elif mca_gates.temporal_factcheck_cache_enabled():
            _key, _bucket, cached = await tf.read_temporal_cache(
                cache, envelope, scope=scope)
        if cached is not None:
            # CA-20-9: hit хранит СВОЙ as_of — сегодняшнюю дату не подставляем.
            await _reply(bot, chat_id, str(cached.get("text") or ""),
                         target.message_id)
            logger.info("[factcheck] temporal cache hit | chat=%s | as_of=%s",
                        chat_id, cached.get("as_of"))
            try:
                cached_verdict = tf.verdict_from_payload({
                    "factual_verdict": cached.get("factual_verdict"),
                    "temporal_status": cached.get("temporal_status"),
                }, envelope)
                await tf.record_temporal_run(
                    _db, tf.TemporalRunResult(
                        envelope=envelope, verdict=cached_verdict,
                        verdict_text=str(cached.get("text") or "")),
                    scope=scope, cache_hit=True)
            except Exception:
                logger.debug("[factcheck] cache-hit run record failed",
                             exc_info=True)
            return
    else:
        # D2: невалидный target → отказ временного контура БЕЗ выдуманных
        # подстановок; пользователь получает ответ через легаси-вычисление,
        # но результат НЕ кешируется (нет корректного контекста — TH-4).
        logger.info("[factcheck] temporal envelope rejected | chat=%s | "
                    "reason=%s", chat_id, reject_reason)
        tf.stage_event("target_resolve", "failed", reason_code=reject_reason,
                       chat_id=chat_id)
        cache_key = None

    # Раунд N (T-841): слот пула per-chat перед LLM (паритет legacy-пути).
    pool = get_smartmodule_concurrency_pool()
    permit = await pool.try_acquire(chat_id,
                                    timeout=smartmodule_wait_seconds())
    if permit is None:
        logger.warning("[factcheck] concurrency slot timeout | chat=%s",
                       chat_id)
        await _reply(bot, chat_id, random.choice(SMARTMODULE_BUSY_PHRASES),
                     message.message_id)
        return
    try:
        async with typing_active(bot, chat_id):
            chat_context = await _fetch_chat_context(
                chat_id,
                hot.get("limits.factcheck_context_before",
                        settings.FACTCHECK_CONTEXT_BEFORE),
                hot.get("limits.factcheck_context_after",
                        settings.FACTCHECK_CONTEXT_AFTER),
                target_tg_message_id=target.message_id,
                trigger_message_id=message.message_id)
            if envelope is not None:
                run = await _service.check_claim_envelope(
                    envelope, chat_context=chat_context or None)
                verdict_text = run.verdict_text
                # D12: запись вердикт-кеша — только при построимом ключе и
                # K3 ON; unknown origin → авто-bypass (без кеширования).
                if cache_key is not None \
                        and mca_gates.temporal_factcheck_cache_enabled():
                    await tf.write_temporal_cache(
                        cache, envelope, scope=scope, text=verdict_text,
                        verdict=run.verdict)
                run_id = await tf.record_temporal_run(
                    _db, run, scope=scope, cache_hit=False)
                tf.stage_event("deliver", "success", chat_id=chat_id,
                               pipeline_run_id=run_id)
                if run.fallback_used:
                    tf.stage_event("verdict", "skipped",
                                   reason_code="temporal_fallback_mode",
                                   chat_id=chat_id, pipeline_run_id=run_id)
            else:
                # envelope_rejected: честное вычисление без кеша (легаси
                # сервис, временные метаданные не подставляются).
                verdict = await _service.check_claim(
                    target_text, user_hint, forward_source, chat_id=chat_id,
                    chat_context=chat_context or None)
                verdict_text = verdict
            await send_chunked_reply(bot, chat_id, verdict_text,
                                     target.message_id)
        logger.info("[factcheck] temporal verdict sent | chat=%s", chat_id)
    except LLMBadResponseError as exc:
        logger.warning("[factcheck] temporal empty answer — silence | "
                       "chat=%s | error=%s", chat_id, exc)
        await react_moai(bot, chat_id, target.message_id)
    except AllSearchEnginesFailedException:
        logger.exception("[factcheck] temporal search failed | chat=%s",
                         chat_id)
        await _reply(bot, chat_id, random.choice(FACTCHECK_ERROR_PHRASES),
                     target.message_id)
    except LLMError as exc:
        logger.warning("[factcheck] temporal LLM failed | chat=%s | error=%s",
                       chat_id, exc)
        await _reply(bot, chat_id, random.choice(LLM_ERROR_PHRASES),
                     target.message_id)
    except Exception:
        logger.exception("[factcheck] temporal unexpected error | chat=%s",
                         chat_id)
        await _reply(bot, chat_id, random.choice(LLM_ERROR_PHRASES),
                     target.message_id)
    finally:
        permit.release()


async def _fetch_chat_context(chat_id: int, before: int, after: int,
                              target_tg_message_id=None,
                              trigger_message_id=None) -> str:
    """Epic 65 + 10.23 (F2, ADR-1023-2): двунаправленное окно фактчека —
    ``before`` сообщений старше целевого + якорь + ``after`` новее (ASC),
    плюс программный граф реплаев вокруг якоря.

    Fail-open: ЛЮБАЯ ошибка (БД/цепочка/рендер) → '' (R1023F2-03: рендер
    внутри общего try — прежнее поведение без контекста); цепочка — отдельный
    под-блок «не доказательства»."""
    from services.chat_context import build_chat_context     # локальный импорт — без циклов
    if _db is None:
        return ""
    b, a = _clamp_window(before, after)
    if b <= 0 and a <= 0:
        return ""
    try:
        rows = await _db.get_messages_around(
            chat_id, target_tg_message_id, b, a)
        reply_chains = await _build_reply_chains(chat_id, target_tg_message_id)
        # Rework R1 (H-2): прод-шов renderer'а D9 (гейт внутри — OFF →
        # байт-в-байт прежний контекст).
        return await build_chat_context(
            _db, rows, chat_id=chat_id,
            trigger_message_id=trigger_message_id,
            reply_chains=reply_chains,
            anchor_message_id=target_tg_message_id)
    except Exception:
        logger.warning("[factcheck] chat context build failed | chat=%s",
                       chat_id, exc_info=True)
        return ""


def _clamp_window(before, after) -> tuple[int, int]:
    """Границы окна: неотрицательные int, сумма ``before + after`` ≤
    FACTCHECK_CONTEXT_TOTAL_CAP (жёсткий код-кап, ADR-1023-2; при переполнении
    срезаем ``after``). Якорь БД добавляет сверх капа (R1023F2-06: фактический
    максимум строк = cap + 1)."""
    cap = int(getattr(settings, "FACTCHECK_CONTEXT_TOTAL_CAP", 40) or 40)
    try:
        b = max(0, int(before or 0))
        a = max(0, int(after or 0))
    except (TypeError, ValueError):
        return 0, 0
    if b > cap:
        b = cap
    if b + a > cap:
        a = max(0, cap - b)
    return b, a


async def _build_reply_chains(chat_id: int, target_tg_message_id) -> str:
    """Цепочка реплаев для якоря общим util (F2). Fail-open → '' (нет цепочки/
    ошибка БД → под-блок опускается, прежнее поведение).

    R1023F2-02: глубина резолвится per-chat (``get_chat_param``) — тот же
    контракт, что в ``direct_chat_service`` (паритет с direct, ADR-1023-2)."""
    if _db is None or target_tg_message_id in (None, "", 0):
        return ""
    from services.thread_chain import (          # локальный импорт — без циклов
        collect_thread_chain,
        render_reply_chains,
    )
    try:
        depth = await _cp_g(
            chat_id, "limits.chat_thread_max_depth",
            hot.get("limits.chat_thread_max_depth",
                    settings.CHAT_THREAD_MAX_DEPTH))
        chain = await collect_thread_chain(
            _db, chat_id, int(target_tg_message_id), int(depth or 0))
        return render_reply_chains(chain)
    except Exception:
        logger.warning("[factcheck] reply chain build failed | chat=%s",
                       chat_id, exc_info=True)
        return ""

_service = None                                   # FactCheckService (DI)
_db = None                                        # Database (Epic 65: chat_context DI)
_cooldown = CooldownTracker(settings.FACTCHECK_COOLDOWN_SECONDS)

_FACTCHECK_TRIGGER_RE = re.compile(r"^фактчек\b", re.IGNORECASE)   # слово целиком («фактчекинг» НЕ матчится)
_HINT_LEAD_RE = re.compile(r"^[\s,:;]+")


def setup_factcheck(service, db=None) -> None:
    """DI: FactCheckService. Вызывается из bot.py on_startup (42.8).
    Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED → персистентный кулдаун
    (throttle_state, scope='factcheck'). Epic 65: db → окно chat_context."""
    global _service, _cooldown, _db
    _service = service
    _db = db
    _cooldown = make_cooldown(
        "factcheck", settings.FACTCHECK_COOLDOWN_SECONDS, db)


def _parse_trigger(message: types.Message) -> tuple[types.Message | None, str | None]:
    """→ (target, user_hint) или (None, None) если не триггер.
    target = message.reply_to_message (основной кейс);
             или message (репост-вариант: forward_origin есть, триггер в caption/text)."""
    text = (message.text or message.caption or "").lstrip()
    match = _FACTCHECK_TRIGGER_RE.match(text)
    if not match:
        return None, None
    target = message.reply_to_message
    if target is None and getattr(message, "forward_origin", None) is not None:
        target = message
    if target is None:
        return None, None                    # текст есть, но нет цели → НЕ триггер
    hint = _HINT_LEAD_RE.sub("", text[match.end():]).strip() or None
    return target, hint


def _extract_target_text(message: types.Message, target: types.Message) -> str | None:
    """Текст целевого сообщения. Приоритет: text/caption → буфер альбома (R36-1) → None (5.3).
    Репост-вариант (target is message): caption несёт триггер — берём только text,
    если он НЕ триггер; иначе None → 5.3 (D121: репост-вариант не меняется)."""
    if target is not message:
        direct = (target.text or target.caption or "").strip()
        if direct:
            return direct
        mgid = getattr(target, "media_group_id", None)   # getattr: MagicMock-safe в тестах
        if mgid:
            caption = get_media_group_caption(mgid)      # caption с 1-го фото альбома
            if caption:
                return caption
        return None
    raw = (target.text or "").strip()
    return raw if raw and not _FACTCHECK_TRIGGER_RE.match(raw) else None


# ── Epic 72 (74.C.3, D275): фактчек на расшифровку ───────────────────

_TRANSCRIPTION_CLAIM_RE = re.compile(r"🗣:\s?(.*)", re.DOTALL)


def _transcription_claim_text(target: types.Message) -> str | None:
    """Чистый клейм из текста расшифровки — всё после анкера «🗣:».
    Telegram хранит .text БЕЗ html-разметки и уже декодированным
    (&lt; → < при отправке), поэтому unescape не нужен. Нет анкера → None."""
    m = _TRANSCRIPTION_CLAIM_RE.search(target.text or "")
    claim = m.group(1).strip() if m else ""
    return claim or None


async def _transcription_forward_author(chat_id: int,
                                        target: types.Message) -> str | None:
    """Epic 72 (74.C.3, D275): автор оригинального голосового из smart_messages
    (цепочка расшифровка→reply_to_message). Приоритет forward_source →
    author_name. Fail-open: нет DI/нет цепочки/нет записи/ошибка БД → None
    (= клейм без атрибуции, прежнее поведение)."""
    orig_id = getattr(getattr(target, "reply_to_message", None),
                      "message_id", None)
    if _db is None or orig_id is None:
        return None
    try:
        row = await _db.get_smart_message_by_tg_id(chat_id, orig_id)
    except Exception:
        logger.warning("[factcheck] transcription author lookup failed",
                       exc_info=True)
        return None
    if row is None:
        return None
    try:
        return row["forward_source"] or row["author_name"] or None
    except (KeyError, IndexError, TypeError):
        return None


@factcheck_router.message()
async def factcheck_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or bot is None:
        return UNHANDLED
    # Раунд 10.6 (T-1201/A1): master-флаг модуля (default ON).
    if not hot.get("flags.factcheck_enabled", settings.FACTCHECK_ENABLED):
        return UNHANDLED
    user_id = message.from_user.id if message.from_user else 0
    target, user_hint = _parse_trigger(message)
    if target is None:
        return UNHANDLED                       # не триггер → пропагация живёт
    logger.info("[factcheck] triggered | chat=%s user=%s", message.chat.id, user_id)
    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.factcheck_cooldown_seconds",
                                        settings.FACTCHECK_COOLDOWN_SECONDS))
    remaining = await cooldown_remaining(_cooldown, message.chat.id, user_id)
    if remaining > 0:                          # 5.1 → РЕПЛАЙ НА ВЫЗОВ (message.message_id)
        await _reply(bot, message.chat.id, throttle_phrase(remaining), message.message_id)
        return                                # консьюм (D107: троттлинг — на вызов)
    await cooldown_touch(_cooldown, message.chat.id, user_id)  # слот сразу (42.4)
    target_text = _extract_target_text(message, target)
    if not target_text:                        # 5.3 → РЕПЛАЙ НА ЦЕЛЕВОЕ, БЕЗ поиска
        await _reply(bot, message.chat.id, random.choice(FACTCHECK_EMPTY_CONTEXT_PHRASES),
                     target.message_id)
        return
    forward_source = None
    if getattr(target, "forward_origin", None) is not None:
        forward_source = _extract_forward_source(target.forward_origin)  # reuse handlers/summary.py
    # Epic 72 (74.C.3, D275): реплай на расшифровку → клейм адресуем автору
    # исходного ГС; явный user-forward цели имеет приоритет (не регрессируем
    # существующий репост-вариант). Fail-open: записи нет → без атрибуции.
    if forward_source is None and _is_transcription_target(target):
        claim = _transcription_claim_text(target)
        if claim:
            target_text = claim
        author = await _transcription_forward_author(message.chat.id, target)
        if author:
            forward_source = author
    # Epic 51 (59.2, D210): Exact Match Cache — ДО ресурсоёмких ступеней
    # (поиск/LLM). Хит → reply на ТЕКУЩЕЕ сообщение, БЕЗ вызовов.
    # MCA-20 (ADR-1028-20 D3/D9, round 10.44): K1 ON → единый resolver + один
    # envelope-пайплайн + кеш slug `factcheck_temporal` (составной ключ);
    # OFF → легаси-путь ниже БИТ-В-БИТ (легаси slug `factcheck`, d298f1f).
    if _temporal_on():
        await _factcheck_temporal(message, bot, target, target_text,
                                  user_hint, forward_source)
        return
    cache = get_smart_cache()
    cache_key = cache.build_key("factcheck", target_text)
    cached = await cache.get(cache_key)
    if cached is not None:
        await _reply(bot, message.chat.id, cached, message.message_id)
        logger.info("[factcheck] cache hit | chat=%s", message.chat.id)
        return
    # Раунд N (T-841): слот пула per-chat перед LLM-вызовом check_claim
    # (cache-hit и пустой-контекст выше — быстрые пути БЕЗ пула). Таймаут →
    # SMARTMODULE_BUSY_PHRASES (реплай на ВЫЗОВ, как 5.1).
    pool = get_smartmodule_concurrency_pool()
    permit = await pool.try_acquire(message.chat.id,
                                    timeout=smartmodule_wait_seconds())
    if permit is None:
        logger.warning("[factcheck] concurrency slot timeout | chat=%s",
                       message.chat.id)
        await _reply(bot, message.chat.id,
                     random.choice(SMARTMODULE_BUSY_PHRASES),
                     message.message_id)
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» от контекста в ИИ до отправки.
        async with typing_active(bot, message.chat.id):
            chat_context = await _fetch_chat_context(
                message.chat.id,
                hot.get("limits.factcheck_context_before",
                        settings.FACTCHECK_CONTEXT_BEFORE),
                hot.get("limits.factcheck_context_after",
                        settings.FACTCHECK_CONTEXT_AFTER),
                target_tg_message_id=target.message_id,
                trigger_message_id=message.message_id)
            verdict = await _service.check_claim(
                target_text, user_hint, forward_source, chat_id=message.chat.id,
                chat_context=chat_context or None,
            )
            await send_chunked_reply(bot, message.chat.id, verdict, target.message_id)
        await cache.set(cache_key, verdict)      # только успешная генерация (59.2)
        logger.info("[factcheck] verdict sent | chat=%s", message.chat.id)
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[factcheck] empty answer — silence | chat=%s | error=%s",
                       message.chat.id, exc)
        await react_moai(bot, message.chat.id, target.message_id)
    except AllSearchEnginesFailedException:
        logger.exception("[factcheck] search failed | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(FACTCHECK_ERROR_PHRASES),  # 5.4b → ЦЕЛЕВОЕ
                     target.message_id)
    except LLMError as exc:
        logger.warning("[factcheck] LLM failed | chat=%s | error=%s",   # Epic 47 (D190): WARNING без traceback
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),       # 5.5 → ЦЕЛЕВОЕ
                     target.message_id)
    except Exception:
        logger.exception("[factcheck] unexpected error | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(LLM_ERROR_PHRASES),       # 5.5 → ЦЕЛЕВОЕ
                     target.message_id)
    finally:
        permit.release()
