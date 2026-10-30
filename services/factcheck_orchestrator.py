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
* кеш/идемпотентность: P0-FACTCHECK-CORRECTIVE (§6, решение владельца
  28.10.2026) — кеш готовых вердиктов удалён в ОБОИХ ветках (envelope
  slug `factcheck_temporal` и legacy slug `factcheck`); каждое обращение —
  актуальная проверка; исторические записи прогонов и защита от двойной
  доставки (`already_delivered` + кулдаун) сохранены (§6.2);
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
    FACTCHECK_IMAGE_PENDING_AUTO_PHRASES,
    FACTCHECK_IMAGE_PENDING_PHRASES,
    FACTCHECK_MEDIA_ERROR_PHRASES,
    FACTCHECK_NO_CLAIM_PHRASES,
    FACTCHECK_TARGET_UNAVAILABLE_PHRASES,
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

# ── ASAP-FC-ADMISSION-01: исход прогона для вызывающего (handler) ────────────
# Возврат run_factcheck: нужен handler'у, чтобы НЕ расходовать полный лимит
# пользователя на ранний отказ/сбой (политика §2.4/D) и при этом сохранить
# антиспам и single-flight для реальных проверок.
OUTCOME_VERDICT = "verdict"            # вердикт доставлен — кулдаун остаётся
OUTCOME_NO_CLAIM = "no_claim"          # проверяемого ядра нет (после цели)
OUTCOME_AMBIGUOUS = "ambiguous"        # непонятно, что проверять — уточнение
OUTCOME_UNAVAILABLE = "unavailable"    # цель пуста/недоступна — честный ответ
OUTCOME_ERROR = "error"                # сбой поиска/LLM/неожиданный
OUTCOME_BUSY = "busy"                  # нет слота пула (параллельный дубль)
# ASAP-VISION-SYNC-01 §4 (медиа-барьер v2-маршрута): анализ изображения ещё не
# готов — допуск ОТЛОЖЕН (не вердикт и не «нечего проверять»). Ранний исход:
# пользовательский лимит не расходуется, запрос можно повторить.
OUTCOME_PENDING = "pending"
# Ранние исходы НЕ должны съедать пользовательский лимит (повтор обоснован).
REFUNDABLE_OUTCOMES = frozenset({OUTCOME_NO_CLAIM, OUTCOME_AMBIGUOUS,
                                 OUTCOME_UNAVAILABLE, OUTCOME_ERROR,
                                 OUTCOME_BUSY, OUTCOME_PENDING})

COOLDOWN_REFUND = "refund"
COOLDOWN_KEPT = "kept"


def cooldown_label(outcome: str) -> str:
    """ASAP-FC-ADMISSION-01 §3.E: исход кулдауна для исхода прогона.

    ``refund:<outcome>`` — ранний отказ/сбой: handler снимет слот (политика
    ``REFUNDABLE_OUTCOMES``); ``kept:<outcome>`` — доставленный вердикт
    сохраняет пользовательский лимит (антиспам/single-flight). Фактический
    результат снятия пишет handler событием ``factcheck_cooldown``
    (``refund:<outcome>`` | ``refund_failed:<outcome>`` | ``kept:<outcome>``)."""
    return (f"{COOLDOWN_REFUND}:{outcome}"
            if outcome in REFUNDABLE_OUTCOMES
            else f"{COOLDOWN_KEPT}:{outcome}")

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
    """Стабильная ссылка доказательства (W4/W5 потребляют; форма = ev-N).

    ASAP-FC-EVIDENCE-STYLE-02 §3.1/§3.3: ``claims`` — claim ID текущего
    прогона, к которым ИМЕННО относится доказательство (аддитивное поле с
    дефолтом: старая схема совместима). Доказательство без claim-привязки
    появляется только у не-claim путей (атрибуция/чат).
    """
    evidence_id: str
    url: str | None
    support: str
    source_kind: str = "secondary"
    published_at: int | None = None
    claims: tuple[str, ...] = ()
    event_at: int | None = None


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
    cache_hit: bool = False              # P0-FACTCHECK-CORRECTIVE §6: кеш
                                         # вердиктов удалён — поле оставлено
                                         # для совместимости схемы (всегда
                                         # False)
    already_delivered: bool = False      # предохранитель двойной доставки:
                                         # True → шов ниже пропускает рендер/
                                         # доставку (однократность ответа на
                                         # тот же Telegram update)
    # FC-RENDER (owner 21.10.2026 §3.6, fcv3): цитаты и части для привязки
    # ссылок к утверждениям. INTERNAL (не входят в FactcheckPresentation);
    # необязательные с дефолтами — совместимость с fcv2-потребителями.
    evidence_refs: tuple = ()            # цитированные ev-N текущего прогона
    parts: tuple = ()                    # части вердикта (словари) с цитатами
    #: ASAP-FC-EVIDENCE-STYLE-02 §3.1/§6: покрытие по claim (claim_id, статус
    #: поиска, роль/ссылки, причина пробела) — INTERNAL, в Presentation не
    #: попадает (egress-whitelist по построению).
    claims: tuple = ()


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


# ── ASAP-FC-ADMISSION-01 §E: безопасная структурированная диагностика ───────
# Только служебные поля: НИ текстов сообщений, НИ авторов, НИ ссылок. Значения
# позволяют в админке/аналитике отличить ложный отказ (admission=
# no_identifiable_claim при существующем тезисе) от честного «проверяемых
# фактов нет» и от «тезис есть, доказательств не хватило» (verdict_stage=
# insufficient_evidence).
def _emit_admission(*, chat_id: int | None, target_resolved: bool,
                    explicit_request: bool, claim_items: int,
                    admission_decision: str, reason_code: str | None,
                    pipeline_path: str, verdict_stage: str | None = None,
                    cooldown_outcome: str = "not_applicable") -> dict:
    """Одно диагностическое событие допуска (fail-open, никогда не бросает).

    ``cooldown_outcome`` — не константа: ``_finish`` передаёт детерминированную
    метку политики (``refund:<outcome>`` / ``kept:<outcome>``), поэтому поле
    отличает ранний отказ (слот вернут) от доставленного вердикта (лимит
    сохранён). Фактический результат снятия слота — событие
    ``factcheck_cooldown`` из handler'а (§3.E)."""
    fields = {
        "target_resolved": bool(target_resolved),
        "explicit_request": bool(explicit_request),
        "claim_items_count": int(claim_items or 0),
        "admission_decision": str(admission_decision or ""),
        "reason_code": str(reason_code or ""),
        "pipeline_path": str(pipeline_path or ""),
        "verdict_stage": str(verdict_stage or ""),
        "cooldown_outcome": str(cooldown_outcome or ""),
    }
    logger.info(
        "[factcheck_admission] chat=%s | target_resolved=%s | "
        "explicit_request=%s | claim_items=%s | admission=%s | reason=%s | "
        "pipeline_path=%s | verdict_stage=%s | cooldown=%s",
        chat_id, fields["target_resolved"], fields["explicit_request"],
        fields["claim_items_count"], fields["admission_decision"],
        fields["reason_code"], fields["pipeline_path"],
        fields["verdict_stage"], fields["cooldown_outcome"])
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "factcheck_admission", outcome="success", level="INFO",
            component="factcheck.admission", stage=fields["pipeline_path"],
            chat_id=chat_id, entity_ids=fields)
    except Exception:      # события не рвут прогон
        logger.debug("[factcheck_admission] event emit failed", exc_info=True)
    return fields


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

async def _apply_critique_section_setting(chat_id: int | None,
                                          verdict: CheckedVerdict,
                                          *, resolved=None
                                          ) -> CheckedVerdict:
    """EVOL §5 (W5): снять раздел «Критический разнос» при настройке OFF.

    Настройка — отдельная ось подачи ответа внутри включённого фактчека
    (``services.factcheck_service.resolve_critique_section``: chat-override →
    global → заводской дефолт ON), мастер-тумблер модуля не дублируется.
    Раздел распознаётся в тексте Writer'а и удаляется детерминированно:
    факты/источники/оговорки не меняются, «лишней секции» не остаётся.
    ``resolved`` — уже прочитанная настройка этого хода ``(enabled, source)``
    (телеметрия §6), повторного чтения не требуется.
    Любой сбой резолва/разбора → вердикт как есть (fail-open, доставку не
    рвёт).
    """
    try:
        from services.factcheck_renderer import split_critique_section
        from services.factcheck_service import resolve_critique_section
        if resolved is not None:
            enabled, source = resolved
        else:
            enabled, source = await resolve_critique_section(chat_id)
        logger.info("[factcheck_v2] critique section | chat=%s | enabled=%s | "
                    "source=%s", chat_id, enabled, source)
        if enabled:
            return verdict
        body, critique = split_critique_section(verdict.verdict_text)
        if not critique:
            return verdict
        return dataclasses.replace(verdict, verdict_text=body)
    except Exception:          # pragma: no cover — настройка не рвёт доставку
        logger.warning("[factcheck_v2] critique setting failed — passthrough",
                       exc_info=True)
        return verdict

# ── ASAP-VISION-SYNC-01 §4 (review-fix2, B1): «картинка не проверена» ───────

def _media_unverified(publication) -> bool:
    """Содержимое изображения публикации НЕ проверено.

    Терминальный отказ распознавания, сбой чтения Vision или неполный альбом —
    всё это означает «часть публикации не проверена». Один предикат на ранние
    отказы гейта: при нём нельзя отвечать «нечего проверять», нужна причина и
    честная оговорка `publication.notice()`."""
    media = getattr(publication, "media", None)
    return bool(getattr(publication, "media_unchecked", False)
                or getattr(media, "vision_failed", False)
                or getattr(publication, "album_incomplete", False))


# ── P1 (ASAP-VISION-SYNC-01 §4.6, review-fix2): отложенный фактчек ──────────
# связанного изображения не готов, запрос глубится в durable-намерение и
# возобновляется ТЕМ ЖЕ worker-sweep'ом Vision (`VisionMediaWorker.
# _maintenance_sweep` → `media_readiness.resume_deferred_requests`), а не
# «повтори через минуту» вручную. Один логический результат: намерение
# закрывается вызывающим только ПОСЛЕ доставки (CAS), повторный проход молчит.

FACTCHECK_RESUME_CONSUMER = "factcheck"

#: Рантайм-привязка (db/service/cache) для возобновления: sweep вызывает
#: обработчик из фоновой задачи, объекта handler'а там нет. Регистрируется
#: один раз в `handlers.factcheck.setup_factcheck` (прецедент `mca_vision.
#: bind_runtime`), ошибок не бросает.
_RUNTIME: dict = {}

#: Установленный нами диспетчер (для идемпотентной переустановки).
_RESUME_DISPATCH = None


def bind_runtime(*, db=None, service=None, cache=None) -> None:
    """DI для отложенного возобновления (fail-open, ничего не бросает)."""
    try:
        if db is not None:
            _RUNTIME["db"] = db
        if service is not None:
            _RUNTIME["service"] = service
        _RUNTIME["cache"] = cache
    except Exception:          # pragma: no cover — привязка не рвёт старт
        logger.debug("[factcheck_v2] runtime bind failed", exc_info=True)


async def defer_factcheck_until_media_ready(db, req: FactcheckRequest, *,
                                            publication=None) -> dict:
    """Сохранить фактчек-запрос до готовности анализа изображения.

    Одна запись на сообщение (coalesce `vision:intent:<chat>:<msg>` в
    `task_jobs`), TTL — существующая настройка распознавания. Возврат `{}` —
    намерение не создано (нет БД/цели, анализ уже готов, ошибка): ответ
    пользователю про pending уже отправлен, поведение прежнее.

    ``enqueue=False``: анализ уже поставлен резолвером публикации
    (`prepare_images_ready`) — здесь только чтение фактического состояния.
    Откладываем ТОЛЬКО реально идущую работу (``ANALYSIS_PENDING``): «анализа
    нет и задачи нет» — это не ожидание, намерение по нему висело бы мёртвым
    до TTL. Такой запрос остаётся с прежним честным «попробуй ещё раз»."""
    if db is None:
        return {}
    target_id = int(req.target_tg_message_id or req.trigger_tg_message_id or 0)
    if not target_id:
        return {}
    try:
        from services import media_readiness
        readiness = await media_readiness.prepare_media_evidence(
            db, chat_id=int(req.chat_id), message_id=target_id,
            caption=str(getattr(publication, "caption_text", "") or ""),
            query=str(req.user_hint or ""),
            consumer=FACTCHECK_RESUME_CONSUMER, wait_seconds=0.0,
            enqueue=False, force=True, allow_adjacent=True)
        if readiness is None or readiness.ready:
            return {}
        if not any(getattr(state, "analysis_status", "") ==
                   media_readiness.ANALYSIS_PENDING
                   for state in (readiness.assets or ())):
            return {}
        install_resume_dispatch()
        return await media_readiness.defer_until_ready(
            db, readiness, consumer=FACTCHECK_RESUME_CONSUMER,
            message_id=target_id, query=str(req.user_hint or ""),
            notify=False)
    except Exception:
        logger.warning("[factcheck_v2] defer registration failed | chat=%s",
                       getattr(req, "chat_id", None), exc_info=True)
        return {}


async def cancel_deferred_factcheck(db, *, chat_id: int,
                                    target_message_id: int) -> bool:
    """Снять прежнее ОТЛОЖЕННОЕ намерение фактчека (свежий запрос важнее).

    Один логический результат (§4.6): если пользователь всё-таки повторил
    просьбу, новый прогон отменит старое намерение и ответит сам — второго
    ответа из sweep'а не будет. Чужие намерения (Direct) НЕ трогаются:
    отменяется только `consumer == factcheck` для этого сообщения."""
    if db is None or not chat_id or not target_message_id:
        return False
    try:
        from services import media_readiness
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        for row in await store.active():
            if str(row.get("kind") or "") != media_readiness.PENDING_INTENT_KIND:
                continue
            payload = media_readiness._intent_payload(row)
            if str(payload.get("consumer") or "") != FACTCHECK_RESUME_CONSUMER:
                continue
            if int(payload.get("trigger_message_id") or 0) != int(
                    target_message_id):
                continue
            cancelled = await store.cancel(
                str(row.get("job_id") or ""),
                reason_code="superseded_by_new_request")
            if cancelled:
                logger.info("[factcheck_v2] deferred intent superseded | "
                            "chat=%s | target=%s", chat_id, target_message_id)
                return True
    except Exception:
        logger.warning("[factcheck_v2] deferred intent cancel failed | "
                       "chat=%s | target=%s", chat_id, target_message_id,
                       exc_info=True)
    return False


def install_resume_dispatch() -> None:
    """Научить sweep возобновлять ещё и фактчек (idempotent, fail-open).

    У `media_readiness` один слот обработчика возобновления, и его занимает
    Direct. Порядок старта (`bot.py`: `setup_factcheck` → `DirectChatService`)
    не позволяет цепляться на старте, поэтому диспетчер ставится в момент
    ФАКТИЧЕСКОГО откладывания — тогда Direct уже создан, и его обработчик
    берётся как предыдущий: чужие намерения идут ровно по прежнему пути."""
    global _RESUME_DISPATCH
    try:
        from services import media_readiness
    except Exception:          # pragma: no cover
        return
    previous = getattr(media_readiness, "_RESUME_HANDLER", None)
    if previous is _RESUME_DISPATCH and _RESUME_DISPATCH is not None:
        return

    async def _dispatch(intent, states, bot=None):
        consumer = str((intent or {}).get("consumer") or "")
        if consumer == FACTCHECK_RESUME_CONSUMER:
            return await deliver_deferred_factcheck(intent, states, bot)
        fallback = previous
        if fallback is None or fallback is _dispatch:
            fallback = getattr(media_readiness, "_RESUME_HANDLER", None)
        if fallback is None or fallback is _dispatch:
            return False
        return await fallback(intent, states, bot)

    _RESUME_DISPATCH = _dispatch
    try:
        media_readiness.set_resume_handler(_dispatch)
    except Exception:          # pragma: no cover
        logger.debug("[factcheck_v2] resume dispatch install failed",
                     exc_info=True)


async def deliver_deferred_factcheck(intent, states, bot=None) -> bool:
    """Продолжить отложенный фактчек один раз (возврат True — доставляли).

    Публикация и её материал резолвятся заново в самом прогоне (одна правда
    об OCR/причине отказа), поэтому дублирующей логики доставки нет: готовый
    анализ → обычный вердикт с честной оговоркой; терминальный отказ →
    честное «содержимое картинки не проверено» с причиной.

    Возобновление идёт через ЕДИНЫЙ оркестратор (одна реализация анализа и
    доставки) даже когда исходная просьба пришла по legacy-маршруту: в фоне
    нет aiogram-объектов исходного сообщения, поэтому переигровка хендлера
    невозможна, а второй путь доставки создал бы второй ответ."""
    if bot is None or not intent:
        return False
    db = _RUNTIME.get("db")
    service = _RUNTIME.get("service")
    chat_id = int(intent.get("chat_id") or 0)
    target_id = int(intent.get("trigger_message_id") or 0)
    if db is None or service is None or not chat_id or not target_id:
        logger.warning("[factcheck_v2] deferred resume skipped — runtime "
                       "unbound | chat=%s | target=%s", chat_id, target_id)
        return False
    req = FactcheckRequest(
        chat_id=chat_id, trigger_tg_message_id=target_id,
        target_tg_message_id=target_id, target_text="",
        user_hint=(str(intent.get("question") or "").strip() or None),
        kind="reply")
    try:
        outcome = await run_factcheck(req, service=service, db=db, bot=bot,
                                      cache=_RUNTIME.get("cache"))
    except Exception:
        logger.warning("[factcheck_v2] deferred resume failed | chat=%s | "
                       "target=%s", chat_id, target_id, exc_info=True)
        return False
    logger.info("[factcheck_v2] deferred request resumed | chat=%s | "
                "target=%s | outcome=%s | terminal=%s", chat_id, target_id,
                outcome, str(intent.get("reason_code") or "-"))
    return True


async def run_factcheck(req: FactcheckRequest, *, service, db, bot,
                        cache=None) -> str:
    """Единый вход W3 (06H.2): provenance → context+gate → план →
    внутренняя ветка → CheckedVerdict → Presentation → Delivery.

    Ошибки поиска/LLM обрабатываются теми же семантиками фраз, что и
    legacy-путь (5.4b/5.5/🗿); кулдаун/пул — забота вызывающего handler'а
    (как сегодня).

    Возврат (ASAP-FC-ADMISSION-01 §D): исход прогона (``OUTCOME_*``).
    Handler использует его, чтобы не расходовать полный пользовательский
    лимит на ранний отказ/сбой; для доставленного вердикта кулдаун остаётся
    (антиспам и single-flight сохранены). Прежние вызывающие, игнорирующие
    возврат, работают как раньше."""
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
        return OUTCOME_BUSY
    try:
        async with typing_active(bot, chat_id):
            return await _run_inner(req, service=service, db=db, bot=bot,
                                    cache=cache)
    except LLMBadResponseError:
        logger.warning("[factcheck_v2] empty answer — silence | chat=%s",
                       chat_id)
        await react_moai(bot, chat_id, req.target_tg_message_id)
        return OUTCOME_ERROR
    except AllSearchEnginesFailedException:
        logger.exception("[factcheck_v2] search failed | chat=%s", chat_id)
        await _reply(bot, chat_id,
                     _guard_outbound(random.choice(FACTCHECK_ERROR_PHRASES),
                                     where="search_error", chat_id=chat_id),
                     req.target_tg_message_id)
        return OUTCOME_ERROR
    except LLMError as exc:
        logger.warning("[factcheck_v2] LLM failed | chat=%s | error=%s",
                       chat_id, exc)
        await _reply(bot, chat_id,
                     _guard_outbound(random.choice(LLM_ERROR_PHRASES),
                                     where="llm_error", chat_id=chat_id),
                     req.target_tg_message_id)
        return OUTCOME_ERROR
    except Exception:
        logger.exception("[factcheck_v2] unexpected error | chat=%s", chat_id)
        await _reply(bot, chat_id,
                     _guard_outbound(random.choice(LLM_ERROR_PHRASES),
                                     where="unexpected_error",
                                     chat_id=chat_id),
                     req.target_tg_message_id)
        return OUTCOME_ERROR
    finally:
        permit.release()


async def _run_inner(req: FactcheckRequest, *, service, db, bot,
                     cache) -> str:
    from services import mca_gates
    from services import temporal_factcheck as tf
    from services import factcheck_context as fcx
    from services import factcheck_suitability as fsg
    from services import usage_events

    # §6 (Reviewer F4): один id прогона для LLM-логов и телеметрии покрытия.
    pipeline_run_id = usage_events.new_correlation_id()

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
    # ASAP-FC-ADMISSION-01 §2.1: ЯВНЫЙ запрос = пользователь/инструмент
    # попросил проверку (reply/command/tool/ui). Только `kind="auto"`
    # (автоматический вход без просьбы) сохраняет прежнюю строгую семантику.
    # Схема FactcheckRequest при этом НЕ меняется (join-barrier W3/W4).
    explicit_request = str(req.kind or "reply") != "auto"
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
    #    ASAP-FC-ADMISSION-01: явный запрос пользователя передаётся в гейт —
    #    сомнение классификатора не превращается в отказ (§2.1/§2.3).
    decision, ctx = await fsg.evaluate_with_expansion(
        db, req.chat_id, claim_text=claim_text, user_hint=req.user_hint,
        target_tg_message_id=req.target_tg_message_id,
        trigger_tg_message_id=req.trigger_tg_message_id, cache=cache,
        explicit_request=explicit_request)
    target_resolved = bool(str(claim_text or "").strip())

    # 2b. ASAP-FC-ADMISSION-01 §2.2: тезис может жить в связанном материале
    #     (пересылка/цитата/caption/соседнее сообщение), а не в первой строке
    #     цели. Пустой текст цели при наличии окна — не «нечего проверять»:
    #     ищем тезис в уже собранном контексте тем же детерминированным
    #     механизмом (без нового LLM/поиска) и пересчитываем допуск.
    if not target_resolved and ctx is not None:
        try:
            found = fsg.find_context_claim(
                ctx, trigger_tg_message_id=req.trigger_tg_message_id)
        except Exception:
            logger.warning("[factcheck_v2] context claim lookup failed",
                           exc_info=True)
            found = None
        if found is not None:
            claim_text = str(found.text or "").strip()
            target_resolved = bool(claim_text)
            logger.info("[factcheck_v2] claim from related material | "
                        "chat=%s | source=%s | anchor=%s", req.chat_id,
                        found.source, found.tg_message_id)
            decision = fsg.evaluate_suitability(
                claim_text, req.user_hint, ctx,
                target_ref={"chat_id": req.chat_id,
                            "target_tg_message_id": req.target_tg_message_id,
                            "trigger_tg_message_id":
                                req.trigger_tg_message_id},
                explicit_request=explicit_request)

    feed = ctx.render_feed() if ctx is not None else ""
    media_context = publication.material_context()
    if media_context:
        feed = f"{feed}\n\n{media_context}".strip()

    admission = fsg.admission_label(decision)
    claim_items = len(decision.claim_items) if decision is not None else 0

    def _finish(outcome: str, pipeline_path: str,
                verdict_stage: str | None = None) -> str:
        """Единая точка диагностики §E + исход прогона (§D)."""
        _emit_admission(
            chat_id=req.chat_id, target_resolved=target_resolved,
            explicit_request=explicit_request, claim_items=claim_items,
            admission_decision=admission,
            reason_code=(decision.reason_code if decision is not None
                         else None),
            pipeline_path=pipeline_path, verdict_stage=verdict_stage,
            cooldown_outcome=cooldown_label(outcome))
        return outcome

    # 2c. ASAP-VISION-SYNC-01 §4 (медиа-барьер v2-маршрута). Пока анализ
    #     связанного изображения не готов, предварительный `no_claim`
    #     запрещён: пустая подпись ≠ отсутствие тезиса (тезис может жить
    #     только на картинке). Гейт стоит ДО gate-маршрутов, поэтому
    #     `no_claim`/`ambiguous`/`unavailable` не могут «выиграть» у pending —
    #     НО настоящая проверка (suitability=checkable) не блокируется: барьер
    #     включается только там, где гейт собирался сказать «проверять нечего».
    #     Ответ — честное «ещё разбираю», исход — отложенный (лимит не
    #     расходуется), Vision продолжает работать (запрос durable).
    pending_dependency = publication.admission_blocked_by_pending_media()
    if pending_dependency and (
            decision is None or decision.decision != fsg.DECISION_CHECKABLE):
        # P1 (§4.6, review-fix2): «повтори через минуту» больше не единственный
        # выход. Запрос сохраняется durable (одна запись на сообщение) и
        # возобновляется тем же worker-sweep'ом Vision, когда анализ готов:
        # пользователю не нужно присылать запрос заново. Поэтому ответ
        # выбирается ПОСЛЕ регистрации намерения: зарегистрировано — честно
        # «продолжу сам», не зарегистрировано — прежнее «повтори через минуту».
        deferred = await defer_factcheck_until_media_ready(
            db, req, publication=publication)
        media_pending_text = _guard_outbound(
            random.choice(FACTCHECK_IMAGE_PENDING_AUTO_PHRASES if deferred
                          else FACTCHECK_IMAGE_PENDING_PHRASES),
            where="media_pending", chat_id=req.chat_id)
        await send_chunked_reply(bot, req.chat_id, media_pending_text,
                                 req.target_tg_message_id)
        tf.stage_event("deliver", "skipped",
                       reason_code="temporal_media_pending",
                       chat_id=req.chat_id)
        logger.info("[factcheck_v2] media pending — gate deferred | "
                    "chat=%s | dependency=%s | images=%d | pending=%d | "
                    "ocr_chars=%d | deferred=%s", req.chat_id,
                    publication.media_dependency(),
                    publication.media.image_count,
                    publication.media.pending_count,
                    publication.media.ocr_chars, bool(deferred))
        return _finish(OUTCOME_PENDING, "v2_gate:media_pending")

    # 2d. ASAP-VISION-SYNC-01 §4: терминальный отказ распознавания НЕ означает
    #     «нечего проверять». Если гейт собирался отказать (no_claim /
    #     ambiguous / unavailable / классификатор не дал решения), предварительный
    #     `no_claim` запрещён: ответ честно говорит, что содержимое картинки НЕ
    #     проверено, и называет причину. Когда тезис проверяемый — проверка идёт,
    #     а честная оговорка о непроверенной картинке добавляется к вердикту
    #     (publication.notice()).
    #     Review-fix2 (B1): барьер привязан к РЕШЕНИЮ гейта, а не к пустоте
    #     текста. Подпись «проверь скрин» — это текст, но не тезис: при
    #     непроверенной картинке отказ «нечего проверять» недопустим и в самом
    #     частом случае (цель С текстом, анализ упал / не прочитался).
    if _media_unverified(publication) and (
            decision is None or decision.decision != fsg.DECISION_CHECKABLE):
        media_unchecked_text = _guard_outbound(
            random.choice(FACTCHECK_MEDIA_ERROR_PHRASES),
            where="media_unchecked", chat_id=req.chat_id)
        notice = publication.notice()
        if notice:
            media_unchecked_text = f"{media_unchecked_text}\n\n{notice}"
        await send_chunked_reply(bot, req.chat_id, media_unchecked_text,
                                 req.target_tg_message_id)
        tf.stage_event("deliver", "skipped", reason_code="vision_failed",
                       chat_id=req.chat_id)
        logger.info("[factcheck_v2] media unchecked — no_claim forbidden | "
                    "chat=%s | reason=%s | images=%d", req.chat_id,
                    publication.media.unchecked_reason,
                    publication.media.image_count)
        return _finish(OUTCOME_UNAVAILABLE, "v2_gate:media_unchecked")

    # 3. Gate-маршруты ДО платного поиска (06B.1/06J.3).
    scope = decision.scope if decision is not None else "web"
    if decision is not None and decision.decision == fsg.DECISION_NO_CLAIM:
        # ASAP-FC-ADMISSION-01 §2.4: это именно «нет идентифицируемого
        # тезиса» (после разрешения цели и контекста), НЕ «доказательств не
        # хватило» и НЕ «непонятно, что проверять».
        # Review-fix2 (B1, страховка): если картинка непроверена, отказ не
        # выдаётся без честной оговорки о её содержимом.
        if _media_unverified(publication):
            text = _guard_outbound(random.choice(FACTCHECK_MEDIA_ERROR_PHRASES),
                                   where="no_claim_media", chat_id=req.chat_id)
            notice = publication.notice()
            if notice:
                text = f"{text}\n\n{notice}"
        else:
            text = _guard_outbound(random.choice(FACTCHECK_NO_CLAIM_PHRASES),
                                   where="no_claim", chat_id=req.chat_id)
        await send_chunked_reply(bot, req.chat_id, text,
                                 req.target_tg_message_id)
        tf.stage_event("deliver", "skipped", reason_code="no_claim_after_context",
                       chat_id=req.chat_id)
        return _finish(OUTCOME_NO_CLAIM, "v2_gate:no_claim")
    if decision is not None and decision.decision == fsg.DECISION_AMBIGUOUS:
        situation = (f"Сообщение участника: «{req.target_text}». "
                     "В контексте чата несколько тем спора — уточни тезис.")
        text = await persona_short_reply(
            service, req.chat_id, instruction=_SHORT_REPLY_INSTRUCTION,
            situation=situation, fallback_phrases=FACTCHECK_CLARIFY_PHRASES)
        if text and _media_unverified(publication):
            # Review-fix2 (B1): уточнение не должно скрывать, что содержимое
            # картинки не проверено.
            notice = publication.notice()
            if notice:
                text = f"{text}\n\n{notice}"
        if text:
            await send_chunked_reply(bot, req.chat_id, text,
                                     req.target_tg_message_id)
        tf.stage_event("deliver", "skipped",
                       reason_code="ambiguous_needs_clarification",
                       chat_id=req.chat_id)
        return _finish(OUTCOME_AMBIGUOUS, "v2_gate:ambiguous")
    if (decision is not None
            and decision.decision == fsg.DECISION_CONTEXT_UNAVAILABLE
            and not target_resolved):
        # ASAP-FC-ADMISSION-01 §2.4/§2.6: цель пуста/недоступна — честный
        # ответ о недоступной цели БЕЗ выдуманного вердикта и без платного
        # поиска (раньше здесь проваливалось в Writer с пустым тезисом).
        text = _guard_outbound(
            random.choice(FACTCHECK_TARGET_UNAVAILABLE_PHRASES),
            where="target_unavailable", chat_id=req.chat_id)
        await send_chunked_reply(bot, req.chat_id, text,
                                 req.target_tg_message_id)
        tf.stage_event("deliver", "skipped",
                       reason_code="unsafe_or_unavailable_target",
                       chat_id=req.chat_id)
        return _finish(OUTCOME_UNAVAILABLE, "v2_gate:unavailable")

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
                return _finish(OUTCOME_NO_CLAIM, "v2_attribution:miss")
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
        verdict = await _run_envelope_branch(req, service, db, bot,
                                             envelope, feed, tf, mca_gates,
                                             retrieval_outcome,
                                             run_id=pipeline_run_id)
    else:
        search_results = (retrieval_outcome.search_text
                          if retrieval_outcome is not None
                          and retrieval_outcome.search_text else None)
        verdict = await _run_legacy_branch(req, service, feed,
                                           search_results=search_results,
                                           target_text=external_claim,
                                           cache_input_text=claim_text,
                                           retrieval=retrieval_outcome)

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
    # EVOL §5 (W5): настройка «Критический разнос» (chat → global → factory,
    # default ON внутри включённого фактчека; мастер-тумблер модуля не
    # дублируется). OFF → раздел снимается ДО презентации: факты, источники и
    # оговорки остаются, лишней секции нет.
    critique_enabled: bool | None = None
    try:
        from services.factcheck_service import resolve_critique_section
        critique_enabled, _critique_source = await resolve_critique_section(
            req.chat_id)
    except Exception:          # pragma: no cover — настройка не рвёт доставку
        critique_enabled = None
    verdict = await _apply_critique_section_setting(
        req.chat_id, verdict,
        resolved=((critique_enabled, _critique_source)
                  if critique_enabled is not None else None))
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
    # P0-FACTCHECK-CORRECTIVE (§6): кеш готовых вердиктов (legacy slug
    # `factcheck`) удалён — повторная проверка всегда выполняется заново.
    # Защита от двойной доставки того же Telegram update — уже СУЩЕСТВУЮЩАЯ
    # (`already_delivered` + кулдаун handler'а), она сохранена.
    # ASAP-FC-ADMISSION-01 §2.4/§E: вердикт-слой отделён от допуска —
    # «тезис есть, доказательств не хватило» помечается
    # verdict_stage=insufficient_evidence и НЕ смешивается с no_claim.
    verdict_stage = ("insufficient_evidence"
                     if str(getattr(verdict, "factual_verdict", "") or "")
                     == "insufficient_evidence" else "verdict_issued")
    # ASAP-FC-EVIDENCE-STYLE-02 §6: трасса покрытия по claim + итог подачи
    # (какой Writer/renderer реально дошёл до отправки, включён ли разгром).
    await _emit_claim_coverage(
        chat_id=req.chat_id, outcome=retrieval_outcome, verdict=verdict,
        verbalizer_path=("envelope_temporal" if use_envelope
                         else "legacy_single"),
        renderer_path=("skipped_already_delivered"
                       if verdict.already_delivered else "telegram_html"),
        critical_section_enabled=critique_enabled,
        fallback_reason=("fallback_used" if verdict.fallback_used else ""),
        trace_id=pipeline_run_id, pipeline_run_id=pipeline_run_id)
    return _finish(OUTCOME_VERDICT, f"v2:{verdict.route}", verdict_stage)


def _accepts_run_id(fn) -> bool:
    """Принимает ли ``check_claim_envelope`` kwarg ``run_id`` (телеметрия §6).

    Прецедент — ``search_aggregator._accepts_budget``: фейки/двойники без
    нового необязательного аргумента не ломают доставку, а реальный сервис
    получает id прогона (Reviewer F4).
    """
    try:
        import inspect
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):      # pragma: no cover
        return False
    return ("run_id" in params
            or any(p.kind is inspect.Parameter.VAR_KEYWORD
                   for p in params.values()))


async def _run_envelope_branch(req: FactcheckRequest, service, db, bot,
                               envelope, feed, tf, mca_gates,
                               retrieval=None, run_id: str | None = None
                               ) -> CheckedVerdict:
    """Envelope-ветка: актуальная проверка + запись run (исторические
    записи сохраняются). Кеш готовых вердиктов удалён (P0-FACTCHECK-
    CORRECTIVE §6, решение владельца 28.10.2026): каждое обращение —
    новая проверка с доступными на этот момент сведениями.

    FC-UNIFY (owner §3.2): ``retrieval`` — выдача ЕДИНОГО retrieval-контура
    v2 (planner CFG-06), передаётся в сервис; сервис не строит второй
    поиск. None → внутренний fallback-поиск сервиса (смысловые запросы)."""
    scope = f"chat:{req.chat_id}"
    run_kwargs = {"run_id": run_id} if (
        run_id and _accepts_run_id(service.check_claim_envelope)) else {}
    if retrieval is not None:
        run = await service.check_claim_envelope(
            envelope, chat_context=feed or None, retrieval=retrieval,
            **run_kwargs)
    else:
        run = await service.check_claim_envelope(
            envelope, chat_context=feed or None, **run_kwargs)
    await tf.record_temporal_run(db, run, scope=scope, cache_hit=False)
    refs = tuple(
        EvidenceRef(evidence_id=str(r.get("evidence_id") or ""),
                    url=r.get("url"), support=str(r.get("support") or ""),
                    source_kind=str(r.get("source_kind") or "secondary"),
                    published_at=r.get("published_at"),
                    claims=((str(r.get("claim_part")),)
                            if r.get("claim_part") else ()))
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
        parts=tuple(run.verdict.parts or ()),
        claims=tuple(getattr(retrieval, "claims", ()) or ()))


async def _run_legacy_branch(req: FactcheckRequest, service,
                             feed, *, search_results: str | None = None,
                             target_text: str | None = None,
                             cache_input_text: str | None = None,
                             retrieval=None
                             ) -> CheckedVerdict:
    """Legacy-ветка (fallback/откат): ТОТ ЖЕ вызов service.check_claim с теми
    же аргументами, что прод-путь 2.58.98 (байт-паритет ветки). Кеш готовых
    вердиктов удалён (P0-FACTCHECK-CORRECTIVE §6, решение владельца
    28.10.2026): каждое обращение — актуальная проверка; исторические
    записи о выполненных проверках не затронуты (§6.2).

    W6 (06C.8): ``search_results`` — выдача единого retrieval-контура v2
    (один поиск на прогон); None → внутренний поиск ветки (честный fallback),
    в этом случае план не выполнен и EvidenceMap не наполняется.
    06G.3: ``target_text`` — privacy-клейм (тезис без участников чата);
    None → req.target_text (байт-паритет неатрибуционных прогонов).
    ASAP-FC-EVIDENCE-STYLE-02 §6: ``retrieval`` — покрытие по claim для
    телеметрии хода (публичный текст этой ветки формирует существующий
    Writer по search_results; сигнатура ``check_claim`` не меняется)."""
    claim_text = str(target_text if target_text is not None
                     else req.target_text)
    verdict = await service.check_claim(
        claim_text, req.user_hint, req.forward_source,
        chat_id=req.chat_id, chat_context=feed or None,
        search_results=search_results)
    return CheckedVerdict(
        verdict_text=verdict, route="legacy_single",
        claims=tuple(getattr(retrieval, "claims", ()) or ()))


def _log_retrieval_metrics(chat_id: int, outcome) -> None:
    """Метрики единого retrieval-контура (06G.7): attempted/used/refs/
    fetch_errors/budget + причины пустого результата (§5.1/§5.3:
    provider_failures ≠ empty_results ≠ irrelevant_results) — logger-
    дайджест + mca-событие (fail-open)."""
    if outcome is None:
        return
    logger.info(
        "[factcheck_v2] retrieval | chat=%s | attempted=%d | used=%d | "
        "refs=%d | fetch_errors=%d | provider_failures=%d | empty=%d | "
        "irrelevant=%d | budget_exhausted=%s | version=%s",
        chat_id, outcome.queries_attempted, outcome.queries_used,
        outcome.refs_collected, outcome.fetch_errors,
        getattr(outcome, "provider_failures", 0),
        getattr(outcome, "empty_results", 0),
        getattr(outcome, "irrelevant_results", 0),
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
            provider_failures=getattr(outcome, "provider_failures", 0),
            empty_results=getattr(outcome, "empty_results", 0),
            irrelevant_results=getattr(outcome, "irrelevant_results", 0),
            planner_version=outcome.planner_version)
    except Exception:      # события не рвут вердикт
        pass


# ── ASAP-FC-EVIDENCE-STYLE-02 §6: телеметрия покрытия и подачи ──────────────

async def _style_revisions(chat_id: int) -> dict:
    """Эффективные ревизии Core/Expression/Style (fail-open, без текстов)."""
    fields = {"core_revision": "", "expression_revision": "",
              "style_revision": ""}
    try:
        from services import prompt_composer as pc
        core = await pc.resolve_core_ref(int(chat_id))
        fields["core_revision"] = str(getattr(core, "revision", "") or "")
    except Exception:
        fields["core_revision"] = "unavailable"
    try:
        from services import prompt_composer as pc
        expr = await pc.resolve_expression_settings(int(chat_id))
        fields["expression_revision"] = str(getattr(expr, "revision", "") or "")
    except Exception:
        fields["expression_revision"] = "unavailable"
    try:
        from services import prompt_composer as pc
        style = await pc.resolve_style_policy_ref(int(chat_id))
        fields["style_revision"] = str(getattr(style, "revision", "") or "")
    except Exception:
        fields["style_revision"] = "unavailable"
    return fields


def _claim_telemetry_row(cov) -> dict:
    """§6 (Reviewer F4): только метаданные — id/статусы/роли/причина/цитаты.

    Ни текста тезиса, ни URL: обычные логи и событие не должны нести
    содержимое чатов и ссылки (§6: «не писать сырой текст/секретные URL»).
    """
    claim = getattr(cov, "claim", None)
    evidence = tuple(getattr(cov, "evidence", ()) or ())
    roles: dict[str, int] = {}
    for item in evidence:
        role = str(getattr(item, "role", "") or "")
        if role:
            roles[role] = roles.get(role, 0) + 1
    return {
        "claim_id": str(getattr(claim, "claim_id", "") or ""),
        "claim_type": str(getattr(claim, "claim_type", "") or ""),
        "search_status": str(getattr(cov, "search_status", "") or ""),
        "status_detail": str(getattr(cov, "status_detail", "") or ""),
        "outcome": str(getattr(cov, "outcome", "") or ""),
        "reason_code": str(getattr(cov, "reason_code", "") or ""),
        "queries_count": int(getattr(cov, "queries_count", 0) or 0),
        "candidates": int(getattr(cov, "candidates", 0) or 0),
        "opened": int(getattr(cov, "opened", 0) or 0),
        "roles": roles,
        "citation_ids": [str(x) for x in
                         (getattr(cov, "citation_ids", ()) or ())],
        "providers": [str(x) for x in
                      (getattr(cov, "provider_status", ()) or ())][:8],
    }


async def _emit_claim_coverage(*, chat_id: int, outcome, verdict,
                               verbalizer_path: str, renderer_path: str,
                               critical_section_enabled: bool | None,
                               fallback_reason: str = "",
                               trace_id: str = "",
                               pipeline_run_id: str = "") -> dict:
    """§6: одна трасса покрытия на ход — claim → запросы → провайдеры →
    кандидаты → открытые → роль/привязка → причина → показанные citation IDs,
    плюс компактный итог хода. Только метаданные: без текстов чатов, ссылок
    и секретов (Reviewer F4); ``trace_id``/``pipeline_run_id`` связывают
    событие с прогоном и его LLM-логами. Никогда не бросает."""
    coverage = tuple(getattr(outcome, "claims", ()) or ()) \
        if outcome is not None else ()
    summary = (outcome.coverage_summary() if outcome is not None
               and hasattr(outcome, "coverage_summary") else {})
    styles = await _style_revisions(chat_id)
    fields = {
        **summary,
        "verdict_route": str(getattr(verdict, "route", "") or "")
        if verdict is not None else "",
        "factual_verdict": str(getattr(verdict, "factual_verdict", "") or "")
        if verdict is not None else "",
        "reason_code": str(getattr(verdict, "reason_code", "") or "")
        if verdict is not None else "",
        "verbalizer_path": str(verbalizer_path or ""),
        "renderer_path": str(renderer_path or ""),
        "critical_section_enabled": bool(critical_section_enabled)
        if critical_section_enabled is not None else "",
        "fallback_reason": str(fallback_reason or ""),
        **styles,
    }
    try:
        logger.info(
            "[factcheck_claims] trace=%s | chat=%s | total=%s | searched=%s | "
            "direct=%s | partial=%s | deadline=%s | off_topic=%s | stale=%s | "
            "refine=%s | verbalizer=%s | renderer=%s | critical=%s | "
            "fallback=%s | core=%s | expression=%s | style=%s",
            trace_id or "-", chat_id, fields.get("total_claims"),
            fields.get("claims_searched"),
            fields.get("claims_with_direct_evidence"),
            fields.get("claims_partial"),
            fields.get("claims_unchecked_due_to_deadline"),
            fields.get("off_topic_sources_dropped"),
            fields.get("stale_sources_dropped"),
            fields.get("refine_calls"), fields["verbalizer_path"],
            fields["renderer_path"], fields["critical_section_enabled"],
            fields["fallback_reason"], fields["core_revision"],
            fields["expression_revision"], fields["style_revision"])
    except Exception:
        pass
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "factcheck_claims", outcome="success", level="INFO",
            component="factcheck.claims", chat_id=chat_id,
            trace_id=str(trace_id or "") or None,
            pipeline_run_id=str(pipeline_run_id or trace_id or "") or None,
            entity_ids={
                **summary,
                "claims": [_claim_telemetry_row(cov) for cov in coverage],
            })
    except Exception:      # события не рвут доставку
        logger.debug("[factcheck_claims] event emit failed", exc_info=True)
    return fields
