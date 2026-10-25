"""CFG-06 W3 — единый оркестратор фактчека `run_factcheck` (06H, бриф §W3).

JOIN-BARRIER волна: контракты этого модуля заморожены тестами
(`tests/test_factcheck_orchestrator_cfg06.py`, CONTRACT owner=CFG-06) —
W4 (планировщик/evidence) и W5 (renderer/доставка) строят от одних и тех же
схем: FactcheckRequest → FactcheckPlan → EvidenceMap → CheckedVerdict →
FactcheckPresentation. Полное описание —
`plans/features/cfg/evidence/cfg-06/w3-schemas.md`.

Инварианты 06H:

* один вход для всех маршрутов (reply/репост/команда/Direct-tool/
  транскрипция) — handler больше не выбирает продуктовую ветку; развилка
  envelope/legacy — ВНУТРЕННЯЯ ветка плана за миграционным флагом (06H.2/5);
* ResolveTimeAndProvenance — всегда, дёшево (build_envelope, 06H.3); unknown
  даты остаются unknown без now();
* suitability gate и широкий контекст ВНУТРИ v2 подразумеваются
  (консолидация W1/W2-флагов); gate-маршруты (no_claim/ambiguous) отвечают
  короткой репликой ДО платного поиска (06B.1/06J.3);
* кеш/идемпотентность: envelope-ветка — составной ключ `factcheck_temporal`
  (as_of внутри payload, CA-20-9), legacy-ветка — slug `factcheck` (59.2:
  запись только после успешной доставки);
* egress-whitelist (06B «не выпускает служебные данные»): служебные поля
  (as_of/gate_version/reason_code/…) живут в CheckedVerdict (internal) и
  ФИЗИЧЕСКИ ОТСУТСТВУЮТ в FactcheckPresentation (egress); латиница-маркеры
  служебных полей в тексте срезаются детерминированно;
* шов UNIFIED-CORE: короткая персона-реплика получает `speech_owner_block`
  ПОСЛЕДНИМ блоком system-сообщения (как Вербализатор Stage-2, MCA-08);
* CFG-07C-G-хвост: egress-guard `public_speech_guard` на всех outbound-
  швах v2 (07C.1–.5) — busy/no_claim/ambiguous/attribution_miss/error-
  реплики и presentation-текст ДО renderer'а; honesty-классы и чистые
  тексты байт-в-байт, детерминированный срез маркеров, честный fail-soft;
* OFF (default) → handler идёт прежним путём 2.58.98 байт-в-байт.
"""
from __future__ import annotations

import dataclasses
import logging
import random
import re

from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
)
from services.smartmodule_phrases import (
    FACTCHECK_ATTRIBUTION_MISS_PHRASES,
    FACTCHECK_CLARIFY_PHRASES,
    FACTCHECK_ERROR_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
    LLM_ERROR_PHRASES,
)
from services.llm_client import LLMBadResponseError, LLMError
from services.search_aggregator import AllSearchEnginesFailedException
from services.smartmodule_concurrency import (
    get_smartmodule_concurrency_pool,
    smartmodule_wait_seconds,
)
from services.typing_manager import typing_active
from services.reply_postprocess import strip_reasoning_tags
from services.summary_cleanup import cleanup_llm_text

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "fcv4"      # fcv4: P0-FACTCHECK — per-part запросы fp3,
                               # классы исхода retrieval, image-материал,
                               # кеш старого вердикта не скрывает новую проверку

# ── Фриз-схемы (join-barrier; изменение полей = bump + review W4/W5) ────────

@dataclasses.dataclass(frozen=True)
class FactcheckRequest:
    """Единый вход (06H.2): что, где, кем вызвано."""
    chat_id: int
    trigger_tg_message_id: int | None
    target_tg_message_id: int | None
    target_text: str
    user_hint: str | None = None
    forward_source: str | None = None
    kind: str = "reply"              # reply | command | tool | ui | auto
    source_type: str = "text"
    default_mode: str = "contextual"


@dataclasses.dataclass(frozen=True)
class FactcheckPlan:
    """Внутренний план прогона: маршрут — ветка реализации, не продукт."""
    route: str                       # envelope_temporal | legacy_single
    context_mode: str                # wide_gated | narrow
    scope: str                       # none | web | chat_history | web_and_chat
    temporal_hint: bool
    cache_slug: str | None           # factcheck_temporal | factcheck | None
    fallback_allowed: bool = True
    plan_version: str = PIPELINE_VERSION


@dataclasses.dataclass(frozen=True)
class EvidenceRef:
    """Стабильная ссылка доказательства (W4/W5 потребляют; форма = ev-N)."""
    evidence_id: str
    url: str | None
    support: str
    source_kind: str = "secondary"
    published_at: int | None = None


@dataclasses.dataclass(frozen=True)
class EvidenceMap:
    """Доказательства текущего прогона; ссылки рендера — только отсюда."""
    refs: tuple[EvidenceRef, ...] = ()
    allowlist: tuple[str, ...] = ()  # стабильные ID текущего прогона

    def links(self) -> tuple[str, ...]:
        seen: list[str] = []
        for ref in self.refs:
            if ref.url and ref.url not in seen:
                seen.append(ref.url)
        return tuple(seen)


@dataclasses.dataclass(frozen=True)
class CheckedVerdict:
    """Вердикт ПЕРЕД презентацией (internal): держит служебные поля."""
    verdict_text: str
    route: str
    factual_verdict: str | None = None   # temporal-ветка; legacy → None
    temporal_status: str | None = None
    evaluated_period: dict | None = None
    uncertainty: dict | None = None
    evidence: EvidenceMap = dataclasses.field(default_factory=EvidenceMap)
    reason_code: str | None = None       # служебное: НЕ идёт в Presentation
    as_of: int | None = None             # служебное: НЕ идёт в Presentation
    gate_version: str | None = None      # служебное: НЕ идёт в Presentation
    fallback_used: bool = False
    cache_hit: bool = False
    already_delivered: bool = False      # предохранитель двойной доставки:
                                         # True → шов ниже пропускает рендер/
                                         # доставку (кеш-хит идёт общим
                                         # потоком — однократно)
    # FC-RENDER (owner 21.10.2026 §3.6, fcv3): цитаты и части для привязки
    # ссылок к утверждениям. INTERNAL (не входят в FactcheckPresentation);
    # необязательные с дефолтами — совместимость с fcv2-потребителями.
    evidence_refs: tuple = ()            # цитированные ev-N текущего прогона
    parts: tuple = ()                    # части вердикта (словари) с цитатами


@dataclasses.dataclass(frozen=True)
class FactcheckPresentation:
    """EGRESS-контракт (06B): всё, что разрешено показать/отрендерить.
    Служебных полей НЕТ по построению; W5 renderer потребляет только это."""
    text: str
    links: tuple[str, ...] = ()      # только URL из EvidenceMap текущего прогона
    reply_to_message_id: int | None = None
    parse_mode: str | None = None    # W5: renderer; W3 — plain (None)
    notice: str = ""                 # честное ограничение (не служебное)


_RETRIEVAL_NO_CITABLE_NOTICE = (
    "Первоисточники открыть не удалось — вывод сделан по выдержкам без "
    "проверяемых ссылок.")

# Служебные латиница-маркеры, которые не должны появляться в публичном тексте
# (негативный тест W3; полная фильтрация контента — renderer W5).
_EGRESS_FORBIDDEN_RE = re.compile(
    r"\b(gate_version|reason_code|temporal_status|factual_verdict|"
    r"evaluated_period|evidence_refs|as_of|plan_version)\b")


def _egress_clean(text: str) -> str:
    """Срезать служебные маркеры из публичного текста (fail-open)."""
    out = str(text or "")
    if _EGRESS_FORBIDDEN_RE.search(out):
        logger.warning("[factcheck_v2] egress: service markers stripped")
        out = _EGRESS_FORBIDDEN_RE.sub("", out)
        out = re.sub(r"\s{2,}", " ", out)
    return out.strip()


def build_presentation(verdict: CheckedVerdict, *,
                       reply_to_message_id: int | None = None,
                       notice: str = "") -> FactcheckPresentation:
    """Граница internal→egress: только whitelist-поля, только ссылки
    EvidenceMap текущего прогона. Служебные поля CheckedVerdict сюда не
    переносятся по построению; текст дополнительно чистится от маркеров."""
    text = _egress_clean(verdict.verdict_text)
    if not text:
        raise LLMBadResponseError("factcheck_v2: empty presentation")
    return FactcheckPresentation(
        text=text, links=verdict.evidence.links(),
        reply_to_message_id=reply_to_message_id, parse_mode=None,
        notice=str(notice or ""))


def pipeline_v2_enabled() -> bool:
    """W3 миграционный рубильник (default OFF → байт-паритет 2.58.98).

    Приоритет: hot ``flags.factcheck_pipeline_v2`` → env
    ``FACTCHECK_PIPELINE_V2_ENABLED`` → False. Никогда не бросает."""
    try:
        from config.settings import settings
        default = bool(getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED",
                               False))
        from services import hot_config as hot
        return bool(hot.get("flags.factcheck_pipeline_v2", default))
    except Exception:      # pragma: no cover — конфиг не должен ронять
        return False


# ── Короткая персона-реплика (шов UNIFIED-CORE) ─────────────────────────────

_SHORT_REPLY_INSTRUCTION = (
    "Ты — участник чата, которому предложили факчек. Ответь ОДНОЙ короткой "
    "репликой (1–2 предложения) по делу: попроси уточнить, какой именно "
    "тезис проверить. Без технических терминов, без reason-кодов, без "
    "markdown, без списков.")


async def persona_short_reply(service, chat_id: int, *, instruction: str,
                              situation: str,
                              fallback_phrases: tuple[str, ...]) -> str:
    """Короткий ответ в образе: канон-инструкция + `speech_owner_block`
    ПОСЛЕДНИМ блоком (тот же шов, что Вербализатор Stage-2). Любой сбой →
    готовая фраза из пула (никогда не бросает)."""
    from services.prompt_composer import speech_owner_block
    system = str(instruction or "").strip()
    try:
        owner_block = await speech_owner_block(chat_id)
    except Exception:
        owner_block = ""
    if owner_block:
        system = f"{system}\n\n{owner_block}"       # character_block — last
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": str(situation or "").strip()},
    ]
    try:
        raw = await service.llm.generate(messages, module="factcheck",
                                         step="short_reply")
        text = cleanup_llm_text(strip_reasoning_tags(str(raw))).strip()
        if text:
            text = _guard_outbound(text, where="short_reply")
        if text:
            return _egress_clean(text)
    except Exception:
        logger.info("[factcheck_v2] persona short reply failed — canned "
                    "fallback", exc_info=True)
    if fallback_phrases:
        return random.choice(tuple(fallback_phrases))
    return ""


# ── CFG-07C-G-хвост: egress-guard на outbound-швах v2 (07C.1–.5) ─────────────

def _guard_outbound(text: str, *, where: str,
                    chat_id: int | None = None) -> str:
    """public_speech_guard на одном исходящем тексте v2-контура.

    Чистые тексты и honesty-классы проходят байт-в-байт; FORBIDDEN-маркеры
    и overclaim-формулы срезаются детерминированно (факты/числа/ссылки не
    меняются). Fail-soft (как в renderer-шве): любой сбой guard'а →
    исходный текст — доставку не рвёт; вырожденный остаток → "" (шов
    подставляет честный класс)."""
    try:
        from services.public_speech_guard import guard_public_text
        res = guard_public_text(text)
    except Exception:
        logger.warning("[factcheck_v2] speech guard failed — passthrough | "
                       "seam=%s", where, exc_info=True)
        return text
    if not res.findings:
        return text
    logger.warning("[factcheck_v2] speech guard | seam=%s | findings=%s | "
                   "repaired=%s | chat=%s", where, ",".join(res.findings),
                   res.repaired, chat_id)
    try:
        from services import temporal_factcheck as tf
        tf.stage_event("egress_guard", "failed",
                       reason_code=",".join(res.findings)[:120],
                       chat_id=chat_id)
    except Exception:      # события не рвут доставку
        pass
    return res.text


def _apply_delivery_guard(presentation: FactcheckPresentation,
                          verdict: CheckedVerdict
                          ) -> tuple[FactcheckPresentation, CheckedVerdict]:
    """Guard на presentation/delivery-шве (07C.1/.4): payload после Writer
    (check_claim*/кеш-хит), ДО сериализации renderer'ом. Урезанный payload
    сохраняет enum-вердикт (реальный статус CheckedVerdict); вырожденный
    остаток → честный статус: заголовок enum или молчание с 🗿
    (LLMBadResponseError) — fail-soft не выдаёт фиктивно уверенный
    вердикт. Кеш пишет сырой текст: guard идемпотентен и применяется при
    каждой доставке."""
    guarded = _guard_outbound(presentation.text, where="delivery")
    if guarded == presentation.text:
        return presentation, verdict
    if not guarded:
        from services.factcheck_renderer import _VERDICT_HEADLINE
        headline = _VERDICT_HEADLINE.get(str(verdict.factual_verdict or ""))
        if not headline:
            raise LLMBadResponseError("factcheck_v2: verdict unguardable")
        logger.warning("[factcheck_v2] delivery unguardable — enum status "
                       "only | route=%s | enum=%s", verdict.route,
                       verdict.factual_verdict)
        verdict = dataclasses.replace(verdict, factual_verdict=None)
        guarded = headline
    return dataclasses.replace(presentation, text=guarded), verdict


# ── Оркестратор ──────────────────────────────────────────────────────────────

async def run_factcheck(req: FactcheckRequest, *, service, db, bot,
                        cache=None) -> None:
    """Единый вход W3 (06H.2): provenance → context+gate → план →
    внутренняя ветка → CheckedVerdict → Presentation → Delivery.

    Ошибки поиска/LLM обрабатываются теми же семантиками фраз, что и
    legacy-путь (5.4b/5.5/🗿); кулдаун/пул — забота вызывающего handler'а
    (как сегодня)."""
    if cache is None:
        from services.smart_cache import get_smart_cache
        cache = get_smart_cache()
    chat_id = req.chat_id
    pool = get_smartmodule_concurrency_pool()
    permit = await pool.try_acquire(chat_id, timeout=smartmodule_wait_seconds())
    if permit is None:
        from services.smartmodule_phrases import SMARTMODULE_BUSY_PHRASES
        logger.warning("[factcheck_v2] concurrency slot timeout | chat=%s",
                       chat_id)
        await _reply(bot, chat_id,
                     _guard_outbound(random.choice(SMARTMODULE_BUSY_PHRASES),
                                     where="busy", chat_id=chat_id),
                     req.trigger_tg_message_id)
        return
    try:
        async with typing_active(bot, chat_id):
            await _run_inner(req, service=service, db=db, bot=bot,
                             cache=cache)
    except LLMBadResponseError:
        logger.warning("[factcheck_v2] empty answer — silence | chat=%s",
                       chat_id)
        await react_moai(bot, chat_id, req.target_tg_message_id)
    except AllSearchEnginesFailedException:
        logger.exception("[factcheck_v2] search failed | chat=%s", chat_id)
        await _reply(bot, chat_id,
                     _guard_outbound(random.choice(FACTCHECK_ERROR_PHRASES),
                                     where="search_error", chat_id=chat_id),
                     req.target_tg_message_id)
    except LLMError as exc:
        logger.warning("[factcheck_v2] LLM failed | chat=%s | error=%s",
                       chat_id, exc)
        await _reply(bot, chat_id,
                     _guard_outbound(random.choice(LLM_ERROR_PHRASES),
                                     where="llm_error", chat_id=chat_id),
                     req.target_tg_message_id)
    except Exception:
        logger.exception("[factcheck_v2] unexpected error | chat=%s", chat_id)
        await _reply(bot, chat_id,
                     _guard_outbound(random.choice(LLM_ERROR_PHRASES),
                                     where="unexpected_error",
                                     chat_id=chat_id),
                     req.target_tg_message_id)
    finally:
        permit.release()


async def _run_inner(req: FactcheckRequest, *, service, db, bot, cache) -> None:
    from services import mca_gates
    from services import temporal_factcheck as tf
    from services import factcheck_context as fcx
    from services import factcheck_suitability as fsg

    # 0. P0-FACTCHECK MEDIA (owner 25.10.2026 §3/§4): публикация целиком —
    # durable элементы альбома (smart_messages.media_group_id) + все подписи
    # + OCR/визуальное описание изображений существующим Vision-контуром.
    # Один резолвер на оба маршрута (handler и v2): новых OCR/Vision/LLM-
    # вызовов нет; недоступность изображения — честная пометка, не «пусто».
    from services.factcheck_service import resolve_claim_publication
    publication = await resolve_claim_publication(
        db, req.chat_id, req.target_tg_message_id, base_text=req.target_text)
    media = publication.media
    claim_text = publication.text
    if media.image_present:
        logger.info("[factcheck_v2] media claim | chat=%s | analyzed=%s | "
                    "ocr_chars=%d | caption=%d | images=%d | notice=%s",
                    req.chat_id, media.image_analyzed, media.ocr_chars,
                    len(media.caption), media.image_count,
                    bool(publication.notice()))

    # 1. ResolveTimeAndProvenance — ВСЕГДА, дёшево (06H.3); unknown честно.
    envelope = None
    if db is not None and req.target_tg_message_id not in (None, "", 0):
        try:
            from services.temporal_factcheck import InputRef
            envelope, reject_reason = await tf.build_envelope(
                db, InputRef(kind=req.kind, chat_id=req.chat_id,
                             target_tg_message_id=req.target_tg_message_id,
                             trigger_tg_message_id=req.trigger_tg_message_id,
                             hint=req.user_hint,
                             # §3.3: собранный сверх сохранённой строки текст
                             # (подпись другого элемента альбома/OCR) идёт в
                             # claim только когда он реально есть — иначе
                             # прежний путь «текст из БД» байт-в-байт.
                             claim_text=(claim_text
                                         if publication.augmented else None)),
                default_mode=str(req.default_mode or "contextual"))
        except Exception:
            logger.warning("[factcheck_v2] envelope build failed", exc_info=True)
            envelope = None

    # 2. Контекст + suitability (внутри v2 подразумеваются — консолидация).
    decision, ctx = await fsg.evaluate_with_expansion(
        db, req.chat_id, claim_text=claim_text, user_hint=req.user_hint,
        target_tg_message_id=req.target_tg_message_id,
        trigger_tg_message_id=req.trigger_tg_message_id, cache=cache)
    feed = ctx.render_feed() if ctx is not None else ""

    # 3. Gate-маршруты ДО платного поиска (06B.1/06J.3).
    scope = decision.scope if decision is not None else "web"
    if decision is not None and decision.decision == fsg.DECISION_NO_CLAIM:
        text = _guard_outbound(random.choice(FACTCHECK_NO_CLAIM_PHRASES),
                               where="no_claim", chat_id=req.chat_id)
        await send_chunked_reply(bot, req.chat_id, text,
                                 req.target_tg_message_id)
        tf.stage_event("deliver", "skipped", reason_code="no_claim_after_context",
                       chat_id=req.chat_id)
        return
    if decision is not None and decision.decision == fsg.DECISION_AMBIGUOUS:
        situation = (f"Сообщение участника: «{req.target_text}». "
                     "В контексте чата несколько тем спора — уточни тезис.")
        text = await persona_short_reply(
            service, req.chat_id, instruction=_SHORT_REPLY_INSTRUCTION,
            situation=situation, fallback_phrases=FACTCHECK_CLARIFY_PHRASES)
        if text:
            await send_chunked_reply(bot, req.chat_id, text,
                                     req.target_tg_message_id)
        tf.stage_event("deliver", "skipped",
                       reason_code="ambiguous_needs_clarification",
                       chat_id=req.chat_id)
        return

    # 3b. CFG-06 06G.3 — локальный tool «кто это сказал»: атрибуционный
    # спор («X сказал Y») решается ПО ConversationContext ДО любого
    # платного поиска. Совпадения нет → честный отказ БЕЗ домыслов и
    # БЕЗ внешнего поиска (участники приватного чата в веб не утекают);
    # реплика найдена → дальше проверяется по существу ТОЛЬКО тезис
    # (privacy-клейм), атрибуция идёт в EvidenceMap (source_kind=chat).
    attribution = None
    attribution_match = None
    external_claim = claim_text
    try:
        from services import factcheck_attribution as fat
        attribution = fat.detect_attribution_claim(req.target_text)
        if (attribution is not None and fat.mention_is_participant(
                ctx, attribution.author_mention)):
            attribution_match = fat.resolve_attribution(ctx, attribution)
            if attribution_match is None:
                logger.info("[factcheck_v2] attribution miss | chat=%s",
                            req.chat_id)
                await send_chunked_reply(
                    bot, req.chat_id,
                    _guard_outbound(
                        random.choice(FACTCHECK_ATTRIBUTION_MISS_PHRASES),
                        where="attribution_miss", chat_id=req.chat_id),
                    req.target_tg_message_id)
                tf.stage_event("deliver", "skipped",
                               reason_code="attribution_not_found",
                               chat_id=req.chat_id)
                return
            external_claim = fat.external_safe_claim(req.target_text, ctx,
                                                     attribution)
            logger.info("[factcheck_v2] attribution resolved | chat=%s",
                        req.chat_id)
    except Exception:
        logger.warning("[factcheck_v2] attribution tool failed",
                       exc_info=True)
        attribution = None
        attribution_match = None
        external_claim = req.target_text

    # 4. План: маршрут — внутренняя ветка (не продуктовая развилка).
    use_envelope = envelope is not None and mca_gates.temporal_factcheck_enabled()
    plan = FactcheckPlan(
        route="envelope_temporal" if use_envelope else "legacy_single",
        context_mode="wide_gated", scope=scope,
        temporal_hint=bool(decision.temporal_hint) if decision else False,
        cache_slug="factcheck_temporal" if use_envelope else "factcheck")

    # CFG-06 W6 (06C.8): единый retrieval-контур v2 — план выполняется ДО
    # вычисления вердикта (один поиск на прогон). FC-UNIFY (owner 21.10.2026
    # §3.2): план выполняется для ОБЕИХ веток — временная проверка становится
    # частью единого фактчека (второго поискового механизма нет); выдача
    # идёт в legacy-ветку и в envelope-ветку (search_text), EvidenceMap —
    # в обе. Бюджеты: ≤3 запроса (план) + общий дедлайн контура; ошибки —
    # честный fallback на внутренний поиск ветки (search_results=None).
    from services import factcheck_planner as fsp
    # 06G.3: план строится от privacy-клейма (тезис без участников чата);
    # без атрибуционного спора external_claim == req.target_text (паритет).
    retrieval_plan = fsp.build_retrieval_plan(decision, ctx=ctx,
                                              claim_text=external_claim)
    if retrieval_plan is not None and retrieval_plan.queries:
        logger.info("[factcheck_v2] retrieval plan | chat=%s | queries=%d | "
                    "intents=%s | privacy_dropped=%d", req.chat_id,
                    len(retrieval_plan.queries),
                    ",".join(q.intent for q in retrieval_plan.queries),
                    len(retrieval_plan.dropped_privacy))
    retrieval_outcome = None
    if retrieval_plan is not None and retrieval_plan.needs_web:
        aggregator = getattr(service, "aggregator", None)
        if aggregator is not None:
            try:
                retrieval_outcome = await fsp.run_retrieval(
                    retrieval_plan, aggregator=aggregator)
            except Exception:
                logger.warning("[factcheck_v2] planner retrieval failed",
                               exc_info=True)
                retrieval_outcome = None
            _log_retrieval_metrics(req.chat_id, retrieval_outcome)

    # 5. Ветка вычисления → CheckedVerdict.
    if use_envelope:
        # 06G.3 privacy: поисковые стадии временной ветки получают тезис
        # без участников чата (frozen-replace, provenance не меняется).
        if attribution_match is not None:
            envelope = fat.with_external_claim(envelope, external_claim)
        verdict = await _run_envelope_branch(req, service, db, bot, cache,
                                             envelope, feed, tf, mca_gates,
                                             retrieval_outcome)
    else:
        search_results = (retrieval_outcome.search_text
                          if retrieval_outcome is not None
                          and retrieval_outcome.search_text else None)
        verdict = await _run_legacy_branch(req, service, cache, feed,
                                           search_results=search_results,
                                           target_text=external_claim,
                                           cache_input_text=claim_text)

    # 6. Presentation (egress-whitelist) → 7. Delivery.
    # CFG-06 W4/W6: EvidenceMap из единого контура — только когда ветка не
    # дала своих evidence (temporal-ветка несёт ev-N текущего прогона).
    if (verdict.evidence.refs == () and retrieval_outcome is not None
            and retrieval_outcome.evidence_map is not None
            and retrieval_outcome.evidence_map.refs):
        verdict = dataclasses.replace(
            verdict, evidence=retrieval_outcome.evidence_map)
        logger.info("[factcheck_v2] evidence map | chat=%s | refs=%d | "
                    "links=%d", req.chat_id,
                    len(retrieval_outcome.evidence_map.refs),
                    len(retrieval_outcome.evidence_map.links()))
    # 06G.3: атрибуционное evidence (автор/цитата/дата локальной реплики) —
    # в EvidenceMap текущего прогона (id chat-1, ссылки ev-N не сдвигаются).
    if attribution_match is not None:
        verdict = fat.attach_attribution_evidence(verdict,
                                                  attribution_match)
    _notice = publication.notice()
    if (not _notice and retrieval_outcome is not None
            and not getattr(retrieval_outcome, "refs_collected", 0)
            and getattr(retrieval_outcome, "search_text", "")
            and verdict.reason_code is None):
        # P0-FACTCHECK (§3.6): материалы найдены, но проверяемых ссылок нет —
        # вывод нельзя подавать как подтверждённый источниками. Технический
        # класс уже назван заголовком, когда reason_code есть.
        _notice = _RETRIEVAL_NO_CITABLE_NOTICE
    presentation = build_presentation(
        verdict, reply_to_message_id=req.target_tg_message_id,
        notice=_notice)
    # CFG-07C-G-хвост (07C.1): egress-guard на outbound-payload — после
    # Writer (check_claim*/кеш-хит), ДО сериализации renderer'ом. Renderer
    # при этом добавляет enum-заголовок из того же (обновлённого) вердикта,
    # поэтому фиктивно уверенного вердикта не возникает.
    presentation, verdict = _apply_delivery_guard(presentation, verdict)
    # CFG-06 W5 (06E): детерминированный renderer → Telegram-HTML
    # (bold-вердикт по enum CheckedVerdict, структура, ссылки ТОЛЬКО из
    # EvidenceMap текущего прогона); entity-safe доставка через
    # СУЩЕСТВУЮЩИЙ send_chunked_reply(parse_mode=...), plain-деградация.
    # already_delivered — предохранитель двойной доставки; кеш-хит
    # доставляется через ОБЩИЙ поток (renderer+delivery) однократно (W6).
    if not verdict.already_delivered:
        from services.factcheck_renderer import (
            deliver_factcheck,
            render_factcheck,
        )
        presentation = render_factcheck(presentation, verdict)
        await deliver_factcheck(bot, req.chat_id, presentation,
                                reply_to_message_id=(
                                    presentation.reply_to_message_id))
    # 8. Идемпотентность (59.2): legacy-кеш — после успешной доставки,
    # сырой текст вердикта (байт-паритет содержимого прод-пути).
    if verdict.route == "legacy_single" and not verdict.cache_hit:
        await write_legacy_cache(req, verdict.verdict_text, cache,
                                 text=claim_text)


async def _run_envelope_branch(req: FactcheckRequest, service, db, bot,
                               cache, envelope, feed, tf, mca_gates,
                               retrieval=None
                               ) -> CheckedVerdict:
    """Envelope-ветка: тот же составной кеш/запись run (порт из handler
    _factcheck_temporal, 06H.6 — один контракт кеша).

    FC-UNIFY (owner §3.2): ``retrieval`` — выдача ЕДИНОГО retrieval-контура
    v2 (planner CFG-06), передаётся в сервис; сервис не строит второй
    поиск. None → внутренний fallback-поиск сервиса (смысловые запросы)."""
    scope = f"chat:{req.chat_id}"
    cache_key = tf.build_temporal_cache_key(envelope, scope=scope)
    if cache_key is not None and mca_gates.temporal_factcheck_cache_enabled():
        _key, _bucket, cached = await tf.read_temporal_cache(
            cache, envelope, scope=scope)
        if cached is not None:
            cached_verdict = tf.verdict_from_payload({
                "factual_verdict": cached.get("factual_verdict"),
                "temporal_status": cached.get("temporal_status"),
            }, envelope)
            try:
                await tf.record_temporal_run(
                    db, tf.TemporalRunResult(
                        envelope=envelope, verdict=cached_verdict,
                        verdict_text=str(cached.get("text") or "")),
                    scope=scope, cache_hit=True)
            except Exception:
                logger.debug("[factcheck_v2] cache-hit run record failed",
                             exc_info=True)
            # W6: кеш-хит идёт через ЕДИНУЮ доставку (renderer/delivery
            # общий поток) — рендер детерминированно преобразует тот же
            # кешированный текст (консистентность кеша), plain-обхода нет.
            return CheckedVerdict(
                verdict_text=str(cached.get("text") or ""),
                route="envelope_temporal",
                factual_verdict=cached_verdict.factual_verdict,
                temporal_status=cached_verdict.temporal_status,
                evaluated_period=cached_verdict.evaluated_period,
                uncertainty=cached_verdict.uncertainty,
                reason_code=cached_verdict.reason,
                as_of=cached_verdict.as_of,
                cache_hit=True)
    if retrieval is not None:
        run = await service.check_claim_envelope(
            envelope, chat_context=feed or None, retrieval=retrieval)
    else:
        run = await service.check_claim_envelope(
            envelope, chat_context=feed or None)
    if cache_key is not None and mca_gates.temporal_factcheck_cache_enabled():
        await tf.write_temporal_cache(cache, envelope, scope=scope,
                                      text=run.verdict_text,
                                      verdict=run.verdict)
    await tf.record_temporal_run(db, run, scope=scope, cache_hit=False)
    refs = tuple(
        EvidenceRef(evidence_id=str(r.get("evidence_id") or ""),
                    url=r.get("url"), support=str(r.get("support") or ""),
                    source_kind=str(r.get("source_kind") or "secondary"),
                    published_at=r.get("published_at"))
        for r in (run.evidence_rows or ()))
    return CheckedVerdict(
        verdict_text=run.verdict_text, route="envelope_temporal",
        factual_verdict=run.verdict.factual_verdict,
        temporal_status=run.verdict.temporal_status,
        evaluated_period=run.verdict.evaluated_period,
        uncertainty=run.verdict.uncertainty,
        evidence=EvidenceMap(refs=refs,
                             allowlist=tuple(r.evidence_id for r in refs)),
        reason_code=run.verdict.reason, as_of=run.verdict.as_of,
        fallback_used=run.fallback_used,
        evidence_refs=tuple(run.verdict.evidence_refs or ()),
        parts=tuple(run.verdict.parts or ()))


async def _run_legacy_branch(req: FactcheckRequest, service, cache,
                             feed, *, search_results: str | None = None,
                             target_text: str | None = None,
                             cache_input_text: str | None = None
                             ) -> CheckedVerdict:
    """Legacy-ветка (fallback/откат): ТОТ ЖЕ вызов service.check_claim с теми
    же аргументами, что прод-путь 2.58.98 (байт-паритет ветки), slug
    `factcheck`, запись только после успешной вычисления (59.2).

    W6 (06C.8): ``search_results`` — выдача единого retrieval-контура v2
    (один поиск на прогон); None → внутренний поиск ветки (честный fallback),
    в этом случае план не выполнен и EvidenceMap не наполняется.
    06G.3: ``target_text`` — privacy-клейм (тезис без участников чата);
    None → req.target_text (байт-паритет неатрибуционных прогонов)."""
    cache_key = cache.build_key("factcheck",
                                _v2_cache_input(req, cache_input_text))
    cached = await cache.get(cache_key)
    if cached is not None:
        return CheckedVerdict(verdict_text=str(cached), route="legacy_single",
                              cache_hit=True)
    claim_text = str(target_text if target_text is not None
                     else req.target_text)
    verdict = await service.check_claim(
        claim_text, req.user_hint, req.forward_source,
        chat_id=req.chat_id, chat_context=feed or None,
        search_results=search_results)
    return CheckedVerdict(verdict_text=verdict, route="legacy_single")


def _v2_cache_input(req: FactcheckRequest, text: str | None = None) -> str:
    """W6: кеш legacy-ветки под версией контура v2 (`fcv4`+`fp3`, 06H.6) —
    записи прод-пути 2.58.98 и v2 не пересекаются в обе стороны; bump
    fcv3→fcv4 (P0-FACTCHECK: классы исхода/части/изображение) старые
    записи естественно выпадают. `text` — фактический материал проверки
    (claim + OCR изображения): старый вердикт по одному тексту не может
    скрыть новую проверку с распознанным изображением."""
    try:
        from services import factcheck_planner as fsp
        planner_version = fsp.PLANNER_VERSION
    except Exception:      # pragma: no cover
        planner_version = "fp0"
    claim_material = req.target_text if text is None else str(text)
    return f"fcv4\x00{PIPELINE_VERSION}\x00{planner_version}\x00{claim_material}"


async def write_legacy_cache(req: FactcheckRequest, verdict_text: str,
                             cache, *, text: str | None = None) -> bool:
    """Запись legacy-кеша после успешной доставки (59.2) — отдельный шаг
    оркестратора; ключ под версией контура v2 (см. `_v2_cache_input`)."""
    try:
        cache_key = cache.build_key("factcheck", _v2_cache_input(req, text))
        await cache.set(cache_key, verdict_text)
        return True
    except Exception:
        return False


def _log_retrieval_metrics(chat_id: int, outcome) -> None:
    """Метрики единого retrieval-контура (06G.7): attempted/used/refs/
    fetch_errors/budget — logger-дайджест + mca-событие (fail-open)."""
    if outcome is None:
        return
    logger.info(
        "[factcheck_v2] retrieval | chat=%s | attempted=%d | used=%d | "
        "refs=%d | fetch_errors=%d | provider_failures=%d | "
        "budget_exhausted=%s | version=%s",
        chat_id, outcome.queries_attempted, outcome.queries_used,
        outcome.refs_collected, outcome.fetch_errors,
        getattr(outcome, "provider_failures", 0),
        outcome.budget_exhausted, outcome.planner_version)
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "factcheck_run",
            outcome="success" if outcome.search_text else "skipped",
            level="INFO", component="factcheck.retrieval",
            queries_attempted=outcome.queries_attempted,
            queries_used=outcome.queries_used,
            refs=outcome.refs_collected,
            fetch_errors=outcome.fetch_errors,
            budget_exhausted=outcome.budget_exhausted,
            planner_version=outcome.planner_version)
    except Exception:      # события не рвут вердикт
        pass
