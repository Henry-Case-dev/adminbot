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
import dataclasses
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
    FACTCHECK_CONTEXT_EMPTY_PHRASES,
    FACTCHECK_CONTEXT_ERROR_PHRASES,
    FACTCHECK_EMPTY_CONTEXT_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    FACTCHECK_IMAGE_NO_CLAIM_PHRASES,
    FACTCHECK_IMAGE_PENDING_PHRASES,
    FACTCHECK_MEDIA_ERROR_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
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


def _pipeline_v2_enabled() -> bool:
    """CFG-06 W3: миграционный рубильник единого оркестратора (default OFF)."""
    try:
        from services import factcheck_orchestrator as orchestrator
        return orchestrator.pipeline_v2_enabled()
    except Exception:      # pragma: no cover — гейт не бросает
        return False


async def _factcheck_pipeline_v2(message: types.Message, bot: Bot,
                                 target: types.Message, target_text: str,
                                 user_hint: str | None,
                                 forward_source: str | None) -> None:
    """CFG-06 W3 (06H.2): все входы → один run_factcheck. Кулдаун/пустой
    таргет — выше по контракту; ошибки — те же семантики фраз внутри
    оркестратора."""
    from services import factcheck_orchestrator as orchestrator
    chat_id = message.chat.id
    try:
        default_mode = await _cp_g(
            chat_id, "temporal.default_mode",
            getattr(settings, "TEMPORAL_DEFAULT_MODE", "contextual"))
    except Exception:
        default_mode = getattr(settings, "TEMPORAL_DEFAULT_MODE", "contextual")
    kind = "reply" if target is not message else "command"
    req = orchestrator.FactcheckRequest(
        chat_id=chat_id,
        trigger_tg_message_id=message.message_id,
        target_tg_message_id=target.message_id,
        target_text=target_text, user_hint=user_hint,
        forward_source=forward_source, kind=kind,
        default_mode=str(default_mode or "contextual"))
    await orchestrator.run_factcheck(req, service=_service, db=_db, bot=bot)


async def _factcheck_temporal(message: types.Message, bot: Bot,
                              target: types.Message, target_text: str,
                              user_hint: str | None,
                              forward_source: str | None,
                              publication=None,
                              context_feed: str | None = None) -> None:
    """MCA-20 ON-путь (D3/D9): один resolver → TemporalClaimEnvelope →
    envelope-пайплайн единого сервиса. Кеш готовых вердиктов удалён
    (P0-FACTCHECK-CORRECTIVE §6): каждое обращение — актуальная проверка.
    Ответ — reply на ЦЕЛЕВОЕ (5.3/5.4b/5.5-контракт legacy сохранён).

    P0-FACTCHECK media (owner 25.10.2026 §3/§4): ``publication`` собран
    handler'ом (текст альбома + материал изображений). Собранный сверх
    сохранённой строки текст передаётся в envelope как claim_text (даты/
    origin по-прежнему из серверных метаданных); честная оговорка о
    недоступном изображении идёт в ответ, а не в тезис.

    ``context_feed`` (уточнение №2): готовый широкий фид, когда тезис найден
    в ОКРУЖЕНИИ пустой цели, — второй раз окно не собирается."""
    from services import temporal_factcheck as tf

    chat_id = message.chat.id
    kind = "reply" if target is not message else "command"
    assembled_claim = (target_text
                       if publication is not None and publication.augmented
                       else None)
    ref = tf.InputRef(
        kind=kind, chat_id=chat_id,
        target_tg_message_id=target.message_id,
        trigger_tg_message_id=message.message_id,
        hint=user_hint, claim_text=assembled_claim)
    try:
        default_mode = await _cp_g(
            chat_id, "temporal.default_mode",
            getattr(settings, "TEMPORAL_DEFAULT_MODE", "contextual"))
    except Exception:
        default_mode = getattr(settings, "TEMPORAL_DEFAULT_MODE", "contextual")

    # P0-FACTCHECK-CORRECTIVE (§6, решение владельца 28.10.2026): кеш
    # готовых вердиктов (`factcheck_temporal`) удалён — каждое обращение
    # выполняет актуальную проверку; раннее завершение на cache-hit больше
    # не существует. Исторические записи прогонов сохраняются (§6.2).
    envelope, reject_reason = await tf.build_envelope(
        _db, ref, default_mode=str(default_mode or "contextual"))
    if envelope is None:
        # D2: невалидный target → отказ временного контура БЕЗ выдуманных
        # подстановок; пользователь получает ответ через легаси-вычисление.
        logger.info("[factcheck] temporal envelope rejected | chat=%s | "
                    "reason=%s", chat_id, reject_reason)
        tf.stage_event("target_resolve", "failed", reason_code=reject_reason,
                       chat_id=chat_id)

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
            if context_feed is not None:
                chat_context, gate_decision = context_feed, None
            else:
                chat_context, gate_decision = await _fetch_context_with_gate(
                    chat_id,
                    hot.get("limits.factcheck_context_before",
                            settings.FACTCHECK_CONTEXT_BEFORE),
                    hot.get("limits.factcheck_context_after",
                            settings.FACTCHECK_CONTEXT_AFTER),
                    target_tg_message_id=target.message_id,
                    trigger_message_id=message.message_id,
                    claim_text=target_text, user_hint=user_hint)
            # Review fix: визуальные описания — контекст к существующему
            # тезису (не доказательства); в тезис они не подмешиваются.
            if publication is not None:
                media_context = publication.material_context()
                if media_context:
                    chat_context = f"{chat_context}\n\n{media_context}".strip()
            # CFG-06 W2 (06B.3/06J.3): тезиса нет после изучения контекста —
            # короткая реплика БЕЗ псевдопроверки и БЕЗ платного поиска.
            if gate_decision is not None \
                    and gate_decision.decision == "no_claim_after_context":
                await send_chunked_reply(
                    bot, chat_id, random.choice(FACTCHECK_NO_CLAIM_PHRASES),
                    target.message_id)
                return
            if envelope is not None:
                run = await _service.check_claim_envelope(
                    envelope, chat_context=chat_context or None)
                verdict_text = run.verdict_text
                # P0-FACTCHECK-CORRECTIVE (§6): кеш вердиктов удалён —
                # только историческая запись прогона (§6.2).
                run_id = await tf.record_temporal_run(
                    _db, run, scope=f"chat:{chat_id}", cache_hit=False)
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
            await send_chunked_reply(bot, chat_id,
                                     _with_publication_notice(verdict_text,
                                                              publication),
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


async def _fetch_context_with_gate(
        chat_id: int, before: int, after: int, *,
        target_tg_message_id=None, trigger_message_id=None,
        claim_text: str | None = None,
        user_hint: str | None = None):
    """Контекст + W2 suitability gate (06B.1: один гейт для обоих маршрутов).

    Гейт OFF (default) ИЛИ широкий контекст OFF → (прежний
    ``_fetch_chat_context``, None) — байт-паритет прод-пути. Гейт ON →
    протокол двух проходов (needs_context → одно ограниченное расширение,
    06J.1) на ConversationContext из W1; возврат (фид, решение)."""
    from services import factcheck_context as _fcx
    from services import factcheck_suitability as _fsg
    if not (_fcx.wide_context_enabled()
            and _fsg.suitability_gate_enabled()):
        return (await _fetch_chat_context(
            chat_id, before, after, target_tg_message_id=target_tg_message_id,
            trigger_message_id=trigger_message_id, claim_text=claim_text),
            None)
    decision, ctx = await _fsg.evaluate_with_expansion(
        _db, chat_id, claim_text=claim_text or "", user_hint=user_hint,
        target_tg_message_id=target_tg_message_id,
        trigger_tg_message_id=trigger_message_id,
        cache=get_smart_cache())
    feed = ctx.render_feed() if ctx is not None else ""
    logger.info("[factcheck] suitability gate | chat=%s | decision=%s | "
                "type=%s | scope=%s | items=%d | conf=%.2f", chat_id,
                decision.decision, decision.claim_type, decision.scope,
                len(decision.claim_items), decision.confidence)
    return feed, decision


async def _fetch_chat_context(chat_id: int, before: int, after: int,
                              target_tg_message_id=None,
                              trigger_message_id=None,
                              claim_text: str | None = None) -> str:
    """Epic 65 + 10.23 (F2, ADR-1023-2): двунаправленное окно фактчека —
    ``before`` сообщений старше целевого + якорь + ``after`` новее (ASC),
    плюс программный граф реплаев вокруг якоря.

    CFG-06 W1 (06I.2): широкий адаптивный контекст 200–500. Решение владельца
    25.10.2026 — режим включён по умолчанию (hot-ключ
    ``flags.factcheck_wide_context`` остаётся откатом без рестарта).
    Гейт ON: успешный широкий фид заменяет окно, пустой/ошибка → fail-open в
    узкое окно ниже. Пустая цель проверяет окружение ВСЕГДА (уточнение №2),
    независимо от этого гейта.

    Fail-open: ЛЮБАЯ ошибка (БД/цепочка/рендер) → '' (R1023F2-03: рендер
    внутри общего try — прежнее поведение без контекста); цепочка — отдельный
    под-блок «не доказательства»."""
    from services.chat_context import build_chat_context     # локальный импорт — без циклов
    if _db is None:
        return ""
    # CFG-06 W1: широкий срез строго за флагом (OFF → прежний путь).
    from services import factcheck_context as _fcx
    if _fcx.wide_context_enabled():
        wide = await _fcx.build_factcheck_context(
            _db, chat_id, target_tg_message_id=target_tg_message_id,
            trigger_message_id=trigger_message_id, claim_text=claim_text)
        if wide:
            return wide
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


# ── P0-FACTCHECK MEDIA (owner 25.10.2026 §3–§7): публикация целиком ─────────

def _is_irrelevant_target(text: str) -> bool:
    """Консервативно нерелевантная непустая цель (review fix 25.10.2026).

    «лол»/«ага»/эмодзи — повод проверить окружение, а не готовый тезис.
    Список филлеров узкий: всё остальное идёт прежним путём."""
    try:
        from services.factcheck_suitability import (
            is_conservatively_irrelevant,
        )
        return is_conservatively_irrelevant(text)
    except Exception:      # pragma: no cover — предикат не роняет хендлер
        return False


async def _resolve_publication(message: types.Message, target: types.Message):
    """Текст + все элементы альбома + материал изображений одной публикации.

    Базовый текст — прежний контракт ``_extract_target_text`` (text/caption →
    буфер альбома → None). Резолвер ``services.factcheck_service`` добавляет
    durable элементы группы из ``smart_messages`` (caption может быть на
    ЛЮБОМ элементе) и OCR/визуальное описание через существующий Vision-контур.

    Fail-open: любой сбой → прежний текстовый путь; честная «пустота»
    остаётся только там, где действительно нечего проверять."""
    from services.factcheck_service import (
        ClaimPublication,
        resolve_claim_publication,
    )
    base_text = _extract_target_text(message, target)
    try:
        return await resolve_claim_publication(
            _db, message.chat.id, target.message_id,
            base_text=base_text, target=target,
            # Репост-вариант (target is message): caption триггера — команда
            # «фактчек», а не текст публикации (D121 не меняется).
            use_stored_target_text=target is not message)
    except Exception:
        logger.warning("[factcheck] publication resolve failed — text only",
                       exc_info=True)
        return ClaimPublication(text=base_text or "",
                                caption_text=base_text or "")


async def _probe_context(message: types.Message, target: types.Message,
                         publication):
    """Уточнение №2: обязательная проверка окружения пустой цели.

    Широкий контекст (окно 200–300 + reply-цепочка) выполняется НЕЗАВИСИМО
    от гейта `flags.factcheck_wide_context`: флаг — откат для НЕпустых
    целей, а не причина ответить «проверять нечего». Возврат ``None`` —
    окружение собрать не удалось (техническая причина)."""
    from services.factcheck_suitability import resolve_context_claim
    try:
        cache = get_smart_cache()
    except Exception:
        cache = None
    try:
        return await resolve_context_claim(
            _db, message.chat.id,
            target_tg_message_id=target.message_id,
            trigger_tg_message_id=message.message_id,
            reply_to_tg_id=publication.reply_to_tg_id,
            cache=cache)
    except Exception:
        logger.warning("[factcheck] context probe failed | chat=%s",
                       message.chat.id, exc_info=True)
        return None


def _empty_content_phrase(publication, probe=None) -> str:
    """Почему фактчек не может идти — по фактическому состоянию входа.

    Приоритет: техническая недоступность изображения → отдельная причина;
    затем — окружение проверено и тезиса нет → честный отказ с указанием
    окна (уточнение №2). «Пустота» без проверки окружения не выдаётся."""
    media = publication.media
    if _db is None:
        # DI-off (тесты/без БД): окружения нет — прежнее поведение.
        if publication.album_incomplete:
            return random.choice(FACTCHECK_MEDIA_ERROR_PHRASES)
        if publication.has_image:
            if media.vision_failed:
                return random.choice(FACTCHECK_MEDIA_ERROR_PHRASES)
            if media.image_not_analyzed:
                return random.choice(FACTCHECK_IMAGE_PENDING_PHRASES)
            return random.choice(FACTCHECK_IMAGE_NO_CLAIM_PHRASES)
        return random.choice(FACTCHECK_EMPTY_CONTEXT_PHRASES)
    if publication.album_incomplete or (
            publication.has_image and media.vision_failed):
        # Альбом/изображение технически недоступны — причина важнее окна.
        return random.choice(FACTCHECK_MEDIA_ERROR_PHRASES)
    if publication.has_image and media.image_not_analyzed:
        return random.choice(FACTCHECK_IMAGE_PENDING_PHRASES)
    if publication.has_image:
        # Review fix: изображение разобрано, но ни подписи, ни OCR нет.
        # Описание модели — НЕ тезис; честный отказ §4/§7/§9.14 (а не
        # платная проверка собственного описания).
        return random.choice(FACTCHECK_IMAGE_NO_CLAIM_PHRASES)
    if probe is None:
        # Цель пуста, окружение прочитать не удалось — это не «фактов нет».
        return random.choice(FACTCHECK_CONTEXT_ERROR_PHRASES)
    scope = "цель с изображением" if publication.has_image else "цель"
    scope_of = "цели с изображением" if publication.has_image else "цели"
    window = max(0, int(probe.window_messages or 0))
    if window <= 0:
        return random.choice(FACTCHECK_EMPTY_CONTEXT_PHRASES)
    return random.choice(FACTCHECK_CONTEXT_EMPTY_PHRASES).format(
        scope=scope, scope_of=scope_of, window=window)


def _with_publication_notice(text: str, publication) -> str:
    """Честное ограничение входа — к готовому ответу, НЕ в тезис/поиск."""
    if publication is None:
        return text
    notice = publication.notice()
    if not notice:
        return text
    return f"{text}\n\n{notice}"


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
    # P0-FACTCHECK MEDIA (owner 25.10.2026 §3–§7): публикация целиком —
    # текст/подпись (в т.ч. с другого элемента альбома) + все изображения
    # через существующий Vision-контур. Раньше здесь был только текст, и
    # фото/альбом/пересыл без caption упирались в «проверять пустоту».
    publication = await _resolve_publication(message, target)
    target_text = publication.text
    context_feed = None
    irrelevant = bool(target_text) and _is_irrelevant_target(target_text)
    if not target_text or irrelevant:
        # Уточнения №2/№6 (owner 25.10.2026): пустая ИЛИ консервативно
        # нерелевантная цель («лол», «ага», эмодзи) — не отказ. Сначала
        # обязательный широкий контекст (цепочка ответов + окно 200–300) БЕЗ
        # учёта гейта; материал найден → фактчек идёт по нему.
        probe = await _probe_context(message, target, publication)
        if probe is not None and probe.claim is not None:
            target_text = probe.claim.text
            context_feed = probe.feed
            publication = dataclasses.replace(
                publication, text=target_text, caption_text=target_text,
                augmented=True)
            logger.info(
                "[factcheck] claim from context | chat=%s | target=%s | "
                "source=%s | anchor=%s | author=%s | window=%d | chain=%d | "
                "target_irrelevant=%s",
                message.chat.id, target.message_id, probe.claim.source,
                probe.claim.tg_message_id, probe.claim.author,
                probe.window_messages, probe.chain_len, irrelevant)
        else:
            await _reply(bot, message.chat.id,
                         _empty_content_phrase(publication, probe),
                         target.message_id)
            logger.info(
                "[factcheck] no claim in target/context | chat=%s | target=%s "
                "| group=%s | probed=%d | image=%s | vision_failed=%s | "
                "pending=%s | window=%s | chain=%s | target_irrelevant=%s",
                message.chat.id, target.message_id,
                publication.media_group_id, len(publication.message_ids),
                publication.has_image, publication.media.vision_failed,
                publication.media.image_not_analyzed,
                None if probe is None else probe.window_messages,
                None if probe is None else probe.chain_len, irrelevant)
            return
    forward_source = None
    if getattr(target, "forward_origin", None) is not None:
        forward_source = _extract_forward_source(target.forward_origin)  # reuse handlers/summary.py
    # P0-FACTCHECK media §3.7/§3.8: пересланная публикация сохраняет
    # атрибуцию, даже если forward_origin есть только у элемента с caption.
    if forward_source is None and publication.forward_source and (
            publication.augmented or publication.media_group_id):
        forward_source = publication.forward_source
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
    # P0-FACTCHECK-CORRECTIVE (§6, решение владельца 28.10.2026): legacy
    # Exact Match Cache (`factcheck`) удалён — повторный тезис запускает
    # новую актуальную проверку; защита от повторной отправки того же
    # Telegram update — кулдаун и однократная диспетчеризация aiogram.
    # MCA-20 (ADR-1028-20 D3/D9): K1 ON → единый resolver + envelope-
    # пайплайн; OFF → легаси-путь ниже (легаси вычисление, d298f1f).
    # CFG-06 W3 (06H.2): единый оркестратор run_factcheck за миграционным
    # флагом (default OFF → прежняя развилка байт-в-байт).
    if _pipeline_v2_enabled():
        # v2 сам восстанавливает публикацию (одна реализация): текстовый
        # случай получает прежний target_text (включая клейм расшифровки);
        # медиа-случай — текст публикации БЕЗ материала, чтобы оркестратор
        # не задвоил OCR/описание.
        v2_text = (publication.caption_text
                   if (publication.has_image or publication.media_group_id)
                   else target_text)
        await _factcheck_pipeline_v2(message, bot, target, v2_text,
                                     user_hint, forward_source)
        return
    if _temporal_on():
        await _factcheck_temporal(message, bot, target, target_text,
                                  user_hint, forward_source,
                                  publication=publication,
                                  context_feed=context_feed)
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
            if context_feed is not None:
                chat_context, gate_decision = context_feed, None
            else:
                chat_context, gate_decision = await _fetch_context_with_gate(
                    message.chat.id,
                    hot.get("limits.factcheck_context_before",
                            settings.FACTCHECK_CONTEXT_BEFORE),
                    hot.get("limits.factcheck_context_after",
                            settings.FACTCHECK_CONTEXT_AFTER),
                    target_tg_message_id=target.message_id,
                    trigger_message_id=message.message_id,
                    claim_text=target_text, user_hint=user_hint)
            # Review fix: описание изображения — контекст, не тезис.
            media_context = publication.material_context()
            if media_context:
                chat_context = f"{chat_context}\n\n{media_context}".strip()
            # CFG-06 W2 (06B.3/06J.3): короткая реплика без поиска —
            # без кеш-записи (идемпотентность 59.2 сохранена).
            if gate_decision is not None \
                    and gate_decision.decision == "no_claim_after_context":
                await send_chunked_reply(
                    bot, message.chat.id,
                    random.choice(FACTCHECK_NO_CLAIM_PHRASES),
                    target.message_id)
                return
            verdict = await _service.check_claim(
                target_text, user_hint, forward_source, chat_id=message.chat.id,
                chat_context=chat_context or None,
            )
            await send_chunked_reply(
                bot, message.chat.id,
                _with_publication_notice(verdict, publication),
                target.message_id)
        # P0-FACTCHECK-CORRECTIVE (§6): записи вердикт-кеша больше нет —
        # успешная генерация доставляется без кеширования (59.2-идемпотент-
        # ность одного запуска и защита от двойной отправки сохранены).
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
