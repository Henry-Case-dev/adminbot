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
import hashlib
import json
import logging
import random
import re
import time

from services.canonical_context import emit_speech_projection_event
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
    #: M11 (§1.5): авторство запроса — для проверки связи медиа с целью
    #: (`media_readiness`). None = неизвестно (прежнее поведение резолвера).
    requester_user_id: int | None = None
    requester_name: str = ""


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


# ── FACTCHECK-REQUEST-INTEGRITY: один предмет проверки (S13) ─────────────────
#
# Пользовательский запрос после команды «фактчек» — часть запроса, а не
# служебный комментарий. Смысл запроса определяет LLM (существующий клиент и
# реестр промптов); детерминированный код ниже ИСПОЛНЯЕТ уже принятое решение:
# сохраняет исходный материал, запрос и предмет раздельно, не приписывает
# пользовательский вопрос автору материала и не выбирает предмет по словам.
# Сценарии A–G (owner §3.3) — приёмочные случаи, но НЕ лексические правила:
# здесь нет ни одного regex/словаря для различения уточнений.
SUBJECT_VERSION = "cs1"
SUBJECT_ORIGIN_MATERIAL = "material"
SUBJECT_ORIGIN_REQUEST = "request"
SUBJECT_ORIGIN_MIXED = "mixed"

#: Служебная семантическая стадия (не речевой канон): определяет предмет
#: проверки. Код-дефолт; правка через существующий реестр промптов/hot-config.
FACTCHECK_SUBJECT_SYSTEM_PROMPT = """\
Ты — служебная стадия фактчека. Ты НЕ пишешь ответ пользователю и не
оцениваешь правдивость. Твоя единственная задача — определить точный предмет
проверки по исходному материалу и тексту, который пользователь написал после
команды «фактчек».

Пользователь ответил на сообщение и мог добавить собственный вопрос, условие
или просьбу о форме ответа. Исходный материал — то, на что он ответил; запрос
пользователя — его собственные слова. Не приписывай автору материала слова
пользователя и не добавляй тезисы, которых нет ни в материале, ни в запросе.

Верни СТРОГО один JSON-объект:
{"subject": "...", "material_part": "...", "request_part": "...",
 "form_request": "..."}

Поля:
- subject — то, что реально нужно проверить, одной-тремя фразами. Если
  проверяется исходное утверждение целиком — это формулировка утверждения.
  Если пользователь просит конкретный факт/ответ — это его вопрос. Если он
  добавляет условие к исходному тезису — предмет включает тезис и условие.
- material_part — ДОСЛОВНЫЙ фрагмент исходного материала, который входит в
  предмет (точная подстрока материала). Пусто, если предмет не включает
  утверждение автора.
- request_part — собственный вопрос/условие/ограничение пользователя, которые
  входят в предмет. Пусто, если запрос не добавляет предмет.
- form_request — просьба о форме ответа (короче, подробнее, показать
  основания, выделить часть вывода), которая НЕ меняет предмет. Пусто, если
  её нет.

Правила смысла:
- сомнение, эмоция или просьба проверить внимательнее не создают новый тезис:
  material_part — исходное утверждение (дословно), request_part пусто;
- просьба о форме ответа не становится предметом проверки;
- самостоятельный вопрос пользователя не требуется дословно искать в
  материале: он сам становится предметом, если пользователь просит установить
  факт, используя материал как контекст;
- если пользователь просит проверить и исходный тезис, и дополнительный факт,
  предмет включает оба;
- не классифицируй запрос и не возвращай категории/типы — только предмет;
- не отказывайся: если предмет — исходный материал, верни его же.

JSON — единственный вывод, без markdown и пояснений."""

_SUBJECT_MAX_CHARS = 20000


@dataclasses.dataclass(frozen=True)
class CheckSubject:
    """Предмет проверки, отделённый от материала и запроса (owner §3.2).

    ``text`` — единственный текст, который проверяют ВСЕ последующие стадии.
    ``material_text``/``request_text`` — сохранённые без содержательной
    обрезки исходный материал и запрос пользователя; ``material_part``/
    ``request_part`` — их части, вошедшие в предмет; ``form_request`` —
    пожелание к форме ответа (не предмет). ``origin`` — структурное
    происхождение предмета, не категория уточнения.
    """

    text: str
    request_text: str | None
    material_text: str
    material_part: str = ""
    request_part: str = ""
    form_request: str = ""
    origin: str = SUBJECT_ORIGIN_MATERIAL
    resolved_by: str = "material"      # material | llm | fallback
    note: str = ""
    material_author: str = ""
    request_author: str = ""
    material_tg_message_id: int | None = None
    request_tg_message_id: int | None = None
    fingerprint: str = ""
    version: str = SUBJECT_VERSION

    def as_dict(self) -> dict:
        """Служебная диагностика (без текстов — R17/приватность)."""
        return {
            "version": self.version,
            "origin": self.origin,
            "resolved_by": self.resolved_by,
            "note": self.note,
            "fingerprint": self.fingerprint,
            "material_tg_message_id": self.material_tg_message_id,
            "request_tg_message_id": self.request_tg_message_id,
            "has_request": bool(self.request_text),
            "has_material_part": bool(self.material_part),
            "has_request_part": bool(self.request_part),
            "has_form_request": bool(self.form_request),
        }


def _subject_norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def subject_fingerprint(*, text: str, request_text: str | None,
                        material_text: str,
                        material_tg_message_id: int | None) -> str:
    """Идентичность предмета (не вердикта): разные предметы → разные ключи.

    В отпечаток входят фактический предмет, запрос, применимый материал и его
    сообщение. Временной режим и ревизии evidence добавляет envelope
    (``subject_fingerprint``) — здесь их ещё нет."""
    h = hashlib.sha256()
    for chunk in (SUBJECT_VERSION, _subject_norm(text),
                  _subject_norm(request_text),
                  _subject_norm(material_text)[:2000],
                  str(material_tg_message_id or "")):
        h.update(chunk.encode("utf-8", "ignore"))
        h.update(b"\x00")
    return h.hexdigest()


def _material_subject(*, material_text: str, request_text: str | None,
                     material_author: str, request_author: str,
                     material_tg_message_id, request_tg_message_id,
                     resolved_by: str = "material", note: str = ""
                     ) -> CheckSubject:
    text = str(material_text or "").strip()
    origin = SUBJECT_ORIGIN_MATERIAL
    material_part = text
    request_part = ""
    if not text and request_text:
        text = str(request_text).strip()
        origin = SUBJECT_ORIGIN_REQUEST
        material_part = ""
        request_part = text
    return CheckSubject(
        text=text, request_text=request_text, material_text=material_text,
        material_part=material_part, request_part=request_part,
        origin=origin, resolved_by=resolved_by, note=note,
        material_author=material_author, request_author=request_author,
        material_tg_message_id=material_tg_message_id,
        request_tg_message_id=request_tg_message_id,
        fingerprint=subject_fingerprint(
            text=text, request_text=request_text,
            material_text=material_text,
            material_tg_message_id=material_tg_message_id))


def _subject_from_decision(*, material_text: str, request_text: str,
                           material_author: str, request_author: str,
                           material_tg_message_id, request_tg_message_id,
                           decision: dict) -> CheckSubject | None:
    """Структурная валидация LLM-решения; None — решение непригодно.

    Поле ``material_part`` принимается только как ДОСЛОВНЫЙ фрагмент
    материала: семантическая формулировка допустима в ``subject``, но чужие
    слова нельзя подписать автору материала. Если ``subject`` не содержит
    вошедшие части — они добавляются механически (сохранение provenance), без
    смысловой переписки."""
    subject = str(decision.get("subject") or "").strip()
    material_part = str(decision.get("material_part") or "").strip()
    request_part = str(decision.get("request_part") or "").strip()
    form_request = str(decision.get("form_request") or "").strip()
    material_text = str(material_text or "").strip()
    request_text = str(request_text or "").strip()
    note = ""
    if len(subject) > _SUBJECT_MAX_CHARS:
        subject = subject[:_SUBJECT_MAX_CHARS].strip()
    if not subject:
        return None
    if material_part and _subject_norm(material_part) not in _subject_norm(
            material_text):
        # Модель подписала автору материала фразу, которой в материале нет.
        material_part = ""
        note = "ungrounded_material_part"
    if not material_part and not request_part:
        # Решение без разметки происхождения: принять можно только предмет,
        # дословно выводимый из материала (иначе это новый тезис).
        if material_text and _subject_norm(subject) in _subject_norm(
                material_text):
            material_part = subject
        elif request_text and _subject_norm(subject) in _subject_norm(
                request_text):
            request_part = subject
        else:
            return None
    if material_part and not request_part:
        origin = SUBJECT_ORIGIN_MATERIAL
        # Без изменения предмета возвращаем материал БАЙТ-В-БАЙТ: обычный
        # фактчек и разговорный комментарий не должны менять проверяемый текст.
        text = material_text
        material_part = material_text
    elif request_part and not material_part:
        origin = SUBJECT_ORIGIN_REQUEST
        text = subject
    else:
        origin = SUBJECT_ORIGIN_MIXED
        text = subject
        if _subject_norm(material_part) not in _subject_norm(text):
            text = f"{material_part} {text}".strip()
        if request_part and _subject_norm(request_part) not in _subject_norm(
                text):
            text = f"{text} {request_part}".strip()
    return CheckSubject(
        text=text, request_text=request_text or None,
        material_text=material_text, material_part=material_part,
        request_part=request_part, form_request=form_request, origin=origin,
        resolved_by="llm", note=note, material_author=material_author,
        request_author=request_author,
        material_tg_message_id=material_tg_message_id,
        request_tg_message_id=request_tg_message_id,
        fingerprint=subject_fingerprint(
            text=text, request_text=request_text or None,
            material_text=material_text,
            material_tg_message_id=material_tg_message_id))


async def resolve_check_subject(service, *, material_text: str,
                                request_text: str | None,
                                material_author: str = "",
                                request_author: str = "",
                                material_tg_message_id: int | None = None,
                                request_tg_message_id: int | None = None,
                                chat_id: int | None = None) -> CheckSubject:
    """Один предмет проверки для всех стадий (owner §3.2/§4.1).

    Обычный вызов без текста после команды НЕ делает LLM-вызова: предмет —
    исходный материал, байт-в-байт. Содержательный текст после команды
    разрешается существующей LLM-стадией (тот же клиент/реестр промптов), а
    детерминированный код исполняет структурированное решение. Любой сбой
    решения → честный fallback на материал (запрос сохраняется целиком), а не
    «тихая» подмена предмета.

    Никогда не бросает."""
    material_text = str(material_text or "").strip()
    request_text = str(request_text or "").strip() or None
    if not request_text:
        return _material_subject(
            material_text=material_text, request_text=None,
            material_author=material_author, request_author=request_author,
            material_tg_message_id=material_tg_message_id,
            request_tg_message_id=request_tg_message_id)
    if not material_text:
        return _material_subject(
            material_text="", request_text=request_text,
            material_author=material_author, request_author=request_author,
            material_tg_message_id=material_tg_message_id,
            request_tg_message_id=request_tg_message_id,
            note="request_without_material")
    llm = getattr(service, "llm", None)
    if llm is None or not hasattr(llm, "generate"):
        return _material_subject(
            material_text=material_text, request_text=request_text,
            material_author=material_author, request_author=request_author,
            material_tg_message_id=material_tg_message_id,
            request_tg_message_id=request_tg_message_id,
            resolved_by="fallback", note="llm_unavailable")
    try:
        from services.prompt_style_blocks import resolve_prompt
        from services.summary_xml import escape_xml_text
        system = resolve_prompt("prompts.factcheck_subject_system_prompt",
                                FACTCHECK_SUBJECT_SYSTEM_PROMPT)
        user = "\n".join((
            "<original_material>" + escape_xml_text(material_text)
            + "</original_material>",
            "<material_author>" + escape_xml_text(material_author)
            + "</material_author>",
            "<user_request>" + escape_xml_text(str(request_text))
            + "</user_request>",
        ))
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        raw = await llm.generate(messages, module="factcheck",
                                 step="subject_resolve")
        from services.system2_handoff import parse_json_object
        decision = parse_json_object(str(raw))
        if not isinstance(decision, dict):
            return _material_subject(
                material_text=material_text, request_text=request_text,
                material_author=material_author, request_author=request_author,
                material_tg_message_id=material_tg_message_id,
                request_tg_message_id=request_tg_message_id,
                resolved_by="fallback", note="invalid_json")
        subject = _subject_from_decision(
            material_text=material_text, request_text=request_text,
            material_author=material_author, request_author=request_author,
            material_tg_message_id=material_tg_message_id,
            request_tg_message_id=request_tg_message_id, decision=decision)
        if subject is not None:
            logger.info("[factcheck] subject resolved | chat=%s | origin=%s | "
                        "material_part=%s | request_part=%s | form=%s",
                        chat_id, subject.origin, bool(subject.material_part),
                        bool(subject.request_part), bool(subject.form_request))
            return subject
        return _material_subject(
            material_text=material_text, request_text=request_text,
            material_author=material_author, request_author=request_author,
            material_tg_message_id=material_tg_message_id,
            request_tg_message_id=request_tg_message_id,
            resolved_by="fallback", note="unusable_decision")
    except Exception:
        logger.warning("[factcheck] subject resolve failed — material subject",
                       exc_info=True)
        return _material_subject(
            material_text=material_text, request_text=request_text,
            material_author=material_author, request_author=request_author,
            material_tg_message_id=material_tg_message_id,
            request_tg_message_id=request_tg_message_id,
            resolved_by="fallback", note="resolve_error")


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


# ── Ambiguity-ветка: детерминированный контекст кандидатов ───────────────────
# EVOL-REPLY-CONTEXT-INTEGRITY-01 (RCI-02..04): ветка ambiguous строила
# `situation` только из ``req.target_text`` и теряла уже посчитанные данные
# (`decision.claim_items`, широкий `ConversationContext`, якоря) — короткая
# реплика спрашивала «что проверить?» в пустоту, хотя тема спора была в том же
# окне контекста. Здесь сводка кандидатов собирается ДЕТЕРМИНИРОВАННО из уже
# имеющихся данных: (1) claim_items гейта, иначе (2) ограниченный список
# значимых сообщений окна. Тема НЕ выбирается и ambiguity не превращается в
# проверяемый тезис: перечень вариантов — материал для уточняющего вопроса,
# решение остаётся за человеком. Платный поиск и временные стадии сюда не
# добавляются.

_AMBIG_MAX_CANDIDATES = 3        # «несколько тем», а не простыня
_AMBIG_CANDIDATE_CHARS = 140     # одна строка кандидата
_AMBIG_MIN_TOKENS = 3            # односложные реакции («это бред») — не тезисы
_AMBIG_SUBSTANTIAL_TOKENS = 6    # развёрнутое сообщение = тема, а не реакция

# Сырой контекст/диагностика, которые не должны попасть в публичный текст,
# даже если модель вернула их в ответе (RCI-04/чистая публикация).
_RAW_CONTEXT_BLOCK_RE = re.compile(
    r"<(chat_context|system|context|facts|evidence|ocr|draft)\b[^>]*>.*?"
    r"</\1\s*>", re.IGNORECASE | re.DOTALL)
_RAW_CONTEXT_TAG_RE = re.compile(r"</?[a-zA-Z_][\w:.-]*[^<>]*>")
# Диагностика распознаётся ТОЛЬКО в форме `key=value` / `key: value`
# (`reason_code=…`, `gate_version: …`, `trace_id=…`, `as_of_utc=…`) — в том
# числе в JSON-подобной записи `"key": "value"`. Голое словарное слово внутри
# обычной фразы диагностикой не является: «По OCR текст не читается» и «Моя
# vision этого вопроса неясна» обязаны остаться нетронутыми (иначе предыдущая
# жадная версия резала маркер вместе со следующим словом).
_RAW_CONTEXT_KEYVAL_RE = re.compile(
    r"[\"']?\b(chat_context|ocr|vision|transcript|reason_code|gate_version|"
    r"trace_id|plan_version|temporal_status|as_of)[\w-]*[\"']?\s*[:=]\s*"
    r"(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,;<>]+)?\s*[,;]?",
    re.IGNORECASE)


def _strip_raw_context(text: str) -> str:
    """Срезать сырой контекст/диагностику из ответа модели (fail-open).

    Публичный текст короткой реплики не должен содержать XML-обёрток
    контекста и диагностических записей `key=value` (дамп OCR/транскрипции,
    reason-код, версия гейта, trace id, `as_of`). Обычная фраза со словарным
    словом (`OCR`, `vision`, `as_of`) не диагностика и не режется; чистый
    текст проходит байт-в-байт."""
    out = str(text or "")
    if not out:
        return ""
    had_dump = bool(_RAW_CONTEXT_BLOCK_RE.search(out)
                    or _RAW_CONTEXT_TAG_RE.search(out)
                    or _RAW_CONTEXT_KEYVAL_RE.search(out))
    if not had_dump:
        return out
    out = _RAW_CONTEXT_BLOCK_RE.sub(" ", out)
    out = _RAW_CONTEXT_TAG_RE.sub(" ", out)
    out = _RAW_CONTEXT_KEYVAL_RE.sub(" ", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    logger.warning("[factcheck_v2] short_reply: raw context stripped")
    return out


def _compact_candidate_text(text: str,
                            *,
                            limit: int = _AMBIG_CANDIDATE_CHARS) -> str:
    """Один кандидат — одна строка без XML-мусора (детерминированно)."""
    out = re.sub(r"[<>]", " ", str(text or ""))
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > limit:
        out = out[:limit].rstrip(" ,;:—-") + "…"
    return out


def _candidate_stamp(ts) -> str:
    """Стабильная дата кандидата (UTC, день-месяц): якорь, без «сейчас»."""
    try:
        value = int(ts)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    try:
        return time.strftime("%d.%m", time.gmtime(value))
    except (OSError, OverflowError, ValueError):      # pragma: no cover
        return ""


def _candidate_line(author, ts, text) -> str:
    """Строка кандидата: «автор, дата: текст» — стабильная атрибуция."""
    body = _compact_candidate_text(text)
    if not body:
        return ""
    who = ", ".join(part for part in (str(author or "").strip(),
                                      _candidate_stamp(ts)) if part)
    return f"— {who or 'участник'}: «{body}»"


def _ambiguous_window_messages(ctx) -> list:
    """Значимые сообщения окна (без цели) в детерминированном порядке.

    Приоритет: (а) сообщение, на которое отвечали (корень ветки спора),
    (б) прямой родитель цели (явная ссылка reply), (в) развёрнутый текст.
    Тай-брейк — свежесть; выдача — хронологически. Односложные реакции
    («это бред») кандидатами не становятся."""
    try:
        from services.factcheck_context import tokenize_for_relevance
    except Exception:      # pragma: no cover — токенайзер не рвёт ветку
        def tokenize_for_relevance(text):
            return str(text or "").split()
    target_tg = getattr(ctx, "target_tg_message_id", None)
    parent_tg = None
    replies: dict = {}
    for msg in ctx.messages:
        if msg.tg_message_id == target_tg:
            parent_tg = msg.reply_to_tg_id
        if msg.reply_to_tg_id not in (None, "", 0):
            replies[msg.reply_to_tg_id] = replies.get(msg.reply_to_tg_id,
                                                      0) + 1
    scored: list[tuple[float, int, object]] = []
    for idx, msg in enumerate(ctx.messages):
        if msg.tg_message_id == target_tg or not str(msg.text or "").strip():
            continue
        try:
            tokens = tokenize_for_relevance(msg.text)
        except Exception:      # pragma: no cover
            tokens = str(msg.text or "").split()
        if len(tokens) < _AMBIG_MIN_TOKENS:
            continue
        score = replies.get(msg.tg_message_id, 0) * 2.0
        if parent_tg not in (None, "", 0) and msg.tg_message_id == parent_tg:
            score += 3.0
        if len(tokens) >= _AMBIG_SUBSTANTIAL_TOKENS:
            score += 1.0
        scored.append((score, idx, msg))
    if not scored:
        return []
    scored.sort(key=lambda row: (-row[0], -row[1]))
    # Значимые (корни веток / родитель цели / развёрнутый текст) — вперёд;
    # в разреженном окне без опор добираем свежие содержательные сообщения,
    # чтобы реплика всё равно имела материал.
    primary = [row for row in scored if row[0] > 0.0]
    pool = primary if len(primary) >= 2 else scored
    chosen = sorted(pool[:_AMBIG_MAX_CANDIDATES], key=lambda row: row[1])
    return [row[2] for row in chosen]


def _ambiguous_candidates(decision, ctx) -> list[str]:
    """Строки-кандидаты для уточняющего вопроса (RCI-04), максимум 3."""
    items = tuple(getattr(decision, "claim_items", ()) or ())
    ts_by_tg: dict = {}
    if ctx is not None:
        for msg in ctx.messages:
            if msg.tg_message_id not in (None, "", 0):
                ts_by_tg[msg.tg_message_id] = msg.timestamp
    lines: list[str] = []
    seen: set[str] = set()

    def _add(author, ts, text) -> None:
        line = _candidate_line(author, ts, text)
        if not line or line in seen or len(lines) >= _AMBIG_MAX_CANDIDATES:
            return
        seen.add(line)
        lines.append(line)

    # (1) Гейт уже сопоставил анцеденты с provenance — используем их как есть.
    for item in items:
        _add(getattr(item, "author", None),
             ts_by_tg.get(getattr(item, "anchor_tg_message_id", None)),
             getattr(item, "text", ""))
    if lines or ctx is None:
        return lines
    # (2) claim_items пусты (типичный ambiguous) — значимые сообщения окна.
    for msg in _ambiguous_window_messages(ctx):
        _add(msg.author, msg.timestamp, msg.text)
    return lines


def _ambiguous_situation(req, decision, ctx) -> str:
    """Ситуация единственного ``persona_short_reply`` (RCI-04).

    Тезис пользователя + уже посчитанные кандидаты: «непонятно, к какой теме
    относится просьба». Ничего не выбирает программно; без кандидатов —
    прежняя нейтральная формулировка (паритет)."""
    head = f"Сообщение участника: «{req.target_text}». "
    try:
        lines = _ambiguous_candidates(decision, ctx)
    except Exception:      # сводка не рвёт ветку: честный прежний текст
        logger.warning("[factcheck_v2] ambiguous candidate summary failed",
                       exc_info=True)
        lines = []
    if not lines:
        return head + "В контексте чата несколько тем спора — уточни тезис."
    return (head + "В чате обсуждали несколько тем, и непонятно, к какой "
            "относится просьба проверить:\n" + "\n".join(lines) +
            "\nТему сам не выбирай: спроси, какой именно тезис проверить.")


async def persona_short_reply(service, chat_id: int, *, instruction: str,
                              situation: str,
                              fallback_phrases: tuple[str, ...]) -> str:
    """Короткий ответ в образе: канон-инструкция + слои владельца.

    ASAP-FC-VOICE-01 / A (§3 контракта): это четвёртая точка сборки речевого
    system фактчека. Слои владельца (Core/Expression/примеры/Style) приходят
    из ТОЙ ЖЕ единственной точки, что у одиночного, двухвызовного и
    временного маршрутов, - второй сборки ``speech_owner_block`` больше нет,
    поэтому двойной инъекции не бывает и байты owner-блока совпадают.

    Любой сбой → готовая фраза из пула (никогда не бросает).
    """
    from services.prompt_composer import compose_speech_system
    base = str(instruction or "").strip()
    system = base
    try:
        composed, _manifest = await compose_speech_system(
            chat_id=chat_id, writer="factcheck_short_reply",
            base_prompt=base, base_source="code", profile="speech_plain",
            channel="plain", html_safe=False, include_mode_block=False,
            identity_text="", identity_skipped="duplicate_of_persona",
            plan_skip="no_l1_plan_in_genre",
            humor_skip="genre_argued_analysis", include_speech_base=True)
        if composed:
            system = composed
    except Exception:          # pragma: no cover — реплика не рвёт доставку
        logger.warning("[factcheck_v2] short reply compose failed — база "
                       "без слоёв владельца", exc_info=True)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": str(situation or "").strip()},
    ]
    # UR-C-CLOCK (UR-26.4): короткий ответ — та же оценка временем чата,
    # что single/tool-loop/Stage-1/2/temporal: ChatClock-блок в последнем
    # user-сообщении фактического payload'а (chat_id None → блока нет,
    # честный код пропуска в событии ниже).
    try:
        if chat_id is not None:
            from services import chat_clock as _cclock
            _snap = await _cclock.snapshot(chat_id)
            messages = _cclock.attach_time_context(
                messages, _snap, phase=_cclock.PHASE_ANSWER)
    except Exception:      # pragma: no cover - fail-open honest
        logger.warning("[factcheck_v2] short reply clock unavailable — no "
                       "time block | chat=%s", chat_id, exc_info=True)
    try:
        raw = await service.llm.generate(messages, module="factcheck",
                                         step="short_reply")
        text = cleanup_llm_text(strip_reasoning_tags(str(raw))).strip()
        if text:
            # RCI-04: сырой контекст/диагностика не должны выйти в Telegram,
            # даже если модель вернула их в ответе.
            text = _strip_raw_context(text)
        if text:
            text = _guard_outbound(text, where="short_reply")
        if text:
            # UR-26.4: payload-событие короткого ответа (в образе) —
            # модель/провайдер, размер/digest, наличие ChatClock-блока.
            from services import turn_payload_events as _tpe
            _tpe.emit_stage(
                _tpe.STAGE_FC_SHORT_REPLY, outcome="success",
                chat_id=chat_id,
                model=_tpe.llm_model(getattr(service, "llm", None)),
                provider=_tpe.llm_provider(getattr(service, "llm", None)),
                finish_reason="generated", chars=len(text),
                text_digest=_tpe.text_digest(text),
                clock=_tpe.clock_meta_messages(messages, chat_id=chat_id),
                decision="short_reply:generated")
            return _egress_clean(text)
    except Exception:
        logger.info("[factcheck_v2] persona short reply failed — canned "
                    "fallback", exc_info=True)
    # UR-26.4: canned-fallback — явный код решения (не молчаливая подмена).
    from services import turn_payload_events as _tpe
    _tpe.emit_stage(
        _tpe.STAGE_FC_SHORT_REPLY, outcome="error", chat_id=chat_id,
        model=_tpe.llm_model(getattr(service, "llm", None)),
        provider=_tpe.llm_provider(getattr(service, "llm", None)),
        finish_reason="canned_fallback",
        clock=_tpe.clock_meta_messages(messages, chat_id=chat_id),
        decision="short_reply:canned_fallback")
    if fallback_phrases:
        return random.choice(tuple(fallback_phrases))
    return ""


# ── CFG-07C-G-хвост: egress-guard на outbound-швах v2 (07C.1–.5) ─────────────

def _guard_outbound(text: str, *, where: str,
                    chat_id: int | None = None) -> str:
    """public_speech_guard на одном исходящем тексте v2-контура.

    BGS-03: guard — наблюдение. Чистые тексты, honesty-классы и живые
    речевые формулы проходят байт-в-байт; находки уходят в событие
    `speech_observation` и в `egress_guard`-телеметрию, но текст не
    срезается и не подменяется. Fail-soft: любой сбой guard'а → исходный
    текст — доставку не рвёт."""
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
        # FC-OBSERVABILITY-01: в `reason_code` едет СТАБИЛЬНЫЙ код класса
        # события, а не склейка находок (та никогда не была в словаре
        # `REASON_CODES` → причина молча терялась). Конкретные находки —
        # в WARN-строке выше и в `speech_observation` (BGS-03).
        tf.stage_event("egress_guard", "failed",
                       reason_code="speech_guard_flagged",
                       chat_id=chat_id)
    except Exception:      # события не рвут доставку
        pass
    return res.text


def _apply_delivery_guard(presentation: FactcheckPresentation,
                          verdict: CheckedVerdict
                          ) -> tuple[FactcheckPresentation, CheckedVerdict]:
    """Guard на presentation/delivery-шве (07C.1/.4): payload после Writer
    (check_claim*/кеш-хит), ДО сериализации renderer'ом.

    BGS-03: guard больше не меняет текст, поэтому нормальный путь —
    байт-в-байт. Ветка деградации (enum-заголовок вместо «невыразимого»
    остатка) сохранена совместимо: она срабатывает только если будущий
    guard-контракт снова начнёт возвращать пустой текст. Кеш пишет сырой
    текст: guard идемпотентен и применяется при каждой доставке."""
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
            # S13: полный текст уточнения не обрезается 400-символьным полем
            # `question` (оно остаётся для связи с медиа); при возобновлении
            # consumer получает запрос целиком.
            context={"request_text": str(req.user_hint or "")},
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
        chat_id=chat_id,
        # BD-8 (§1.4): отложенное возобновление НЕ имеет сообщения-команды.
        # Прежнее `trigger = target` ломало семантику маркера «текущая
        # команда» и исключало из поиска не то сообщение. Честное значение —
        # «команды нет».
        trigger_tg_message_id=None,
        target_tg_message_id=target_id, target_text="",
        # S13: полный пользовательский запрос из durable-контекста (не
        # 400-символьная связка с медиа); старые намерения — прежнее поле.
        user_hint=(str((intent.get("context") or {}).get("request_text")
                       or intent.get("question") or "").strip() or None),
        kind="reply",
        requester_user_id=(int(intent["user_id"])
                           if intent.get("user_id") else None))
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
                        cache=None, publication=None,
                        subject=None) -> str:
    """Единый вход W3 (06H.2): provenance → context+gate → план →
    внутренняя ветка → CheckedVerdict → Presentation → Delivery.

    ``publication`` (EVOL-REPLY-CONTEXT-INTEGRITY-01 §1.5/§10.3, B1) — уже
    разрешённая вызывающим публикация (handler объявил цель/источник/анкор и
    выполнил contextual-подмену). ``None`` — резолвим сами (tool/deferred/
    прямой вызов), поведение байт-в-байт прежнее.

    ``subject`` (S13 FACTCHECK-REQUEST-INTEGRITY) — уже разрешённый вызывающим
    предмет проверки (``CheckSubject``). ``None`` — резолвится здесь ровно
    один раз; обычный вызов без уточнения не делает LLM-вызова.

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
                                    cache=cache, publication=publication,
                                    subject=subject)
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


def _declared_target_tg(publication, req: "FactcheckRequest") -> int | None:
    """Цель, объявленная публикацией, — та, что реально проверится.

    B1 (EVOL-REPLY-CONTEXT-INTEGRITY-01 §1.5/§10.3): при contextual-подмене это
    анкор тезиса, а не литеральное сообщение, на которое ответили. Собственный
    резолв публикации даёт ровно тот же id, поэтому поведение прочих путей
    неизменно."""
    value = getattr(publication, "target_tg_message_id", None)
    if value not in (None, "", 0):
        return value
    return req.target_tg_message_id


async def _run_inner(req: FactcheckRequest, *, service, db, bot,
                     cache, publication=None, subject=None) -> str:
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
    if publication is None:
        publication = await resolve_claim_publication(
            db, req.chat_id, req.target_tg_message_id,
            base_text=req.target_text,
            # M11 (§1.5): авторство и триггер передаются так же, как в handler.
            # Без них `media_readiness._same_author` при неизвестной личности
            # считает «свой автор», и чужое фото «уверенно» приписывается цели.
            trigger_tg_message_id=req.trigger_tg_message_id,
            requester_user_id=req.requester_user_id,
            requester_name=req.requester_name,
            target_source=("stored_reply"
                           if str(req.kind or "reply") != "command"
                           else "command_text"))
    # B1 (§1.5/§10.3): цель, объявленная публикацией, — та, что проверится.
    # При переданной публикации это может быть анкор contextual-подмены, а не
    # литеральное сообщение-цель; собственный резолв даёт ровно тот же id.
    declared_target_tg = _declared_target_tg(publication, req)
    # B1: объявленная contextual-подмена (handler или собственный резолв ниже)
    # обязывает доставлять ответ на ТРИГГЕР: цель как сообщение — анкор.
    declared_contextual = (str(getattr(publication, "target_source", "") or "")
                           == "contextual")
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

    # 1. ResolveTimeAndProvenance — дёшево (06H.3); unknown честно.
    #    M3/BD-2 (§1.5): envelope строится ПОСЛЕ разрешения цели и тезиса —
    #    поиск/план и вердикт обязаны читать один и тот же текст. Прежняя
    #    сборка ДО гейта давала вердикт по одному тексту, а поиск по другому.

    # 1a. S13 FACTCHECK-REQUEST-INTEGRITY: единый предмет проверки ДО гейта,
    #     плана и envelope. Без текста после команды LLM-вызова нет (предмет —
    #     материал байт-в-байт); с уточнением — существующая семантическая
    #     стадия, решение которой исполняет детерминированный код.
    if subject is None:
        subject = await resolve_check_subject(
            service, material_text=claim_text or req.target_text,
            request_text=req.user_hint,
            material_author=str(getattr(publication, "claim_anchor_author", "")
                                or req.forward_source or ""),
            request_author=req.requester_name,
            material_tg_message_id=declared_target_tg,
            request_tg_message_id=req.trigger_tg_message_id,
            chat_id=req.chat_id)

    # 2. Контекст + suitability (внутри v2 подразумеваются — консолидация).
    #    ASAP-FC-ADMISSION-01: явный запрос пользователя передаётся в гейт —
    #    сомнение классификатора не превращается в отказ (§2.1/§2.3).
    #    S13: контекст/verbatim-выбор собирается ПОД ПРЕДМЕТ (кэш-идентичность
    #    среза различает разные предметы), решение гейта — по материалу.
    decision, ctx = await fsg.evaluate_with_expansion(
        db, req.chat_id, claim_text=claim_text, user_hint=req.user_hint,
        target_tg_message_id=declared_target_tg,
        trigger_tg_message_id=req.trigger_tg_message_id, cache=cache,
        explicit_request=explicit_request,
        subject_text=(subject.text or None))
    target_resolved = bool(str(claim_text or "").strip())

    # 2b. ASAP-FC-ADMISSION-01 §2.2: тезис может жить в связанном материале
    #     (пересылка/цитата/caption/соседнее сообщение), а не в первой строке
    #     цели. Пустой текст цели при наличии окна — не «нечего проверять»:
    #     ищем тезис в уже собранном контексте тем же детерминированным
    #     механизмом (без нового LLM/поиска) и пересчитываем допуск.
    #     M2 (§1.5): это ЕДИНСТВЕННАЯ законная подмена цели — contextual, и
    #     она объявляется в публикации (источник/анкор/автор), а не только в
    #     логе. Условие соответствует M2: у явной цели нет ни текста, ни
    #     медиа-материала (иначе ждём/читаем изображение, см. 2c/2d ниже).
    textual_target = bool(str(publication.text or "").strip())
    media_material = bool(publication.has_image
                          or publication.media.image_present
                          or publication.media_group_id
                          or publication.media_dependency() != "none")
    contextual = False
    ctx_claim = None
    ctx_basis = ""
    if not textual_target and not media_material and ctx is not None:
        try:
            found, basis, _candidates = fsg._infer_source_claim(
                ctx, trigger_tg_message_id=req.trigger_tg_message_id,
                hint=req.user_hint,
                reply_to_tg_id=publication.reply_to_tg_id)
        except Exception:
            logger.warning("[factcheck_v2] context claim lookup failed",
                           exc_info=True)
            found, basis = None, "none"
        if found is not None:
            ctx_claim, ctx_basis = found, basis
            claim_text = str(found.text or "").strip()
            target_resolved = bool(claim_text)
            contextual = bool(claim_text)
            publication = dataclasses.replace(
                publication, text=claim_text, caption_text=claim_text,
                augmented=True, claim_origin="context_window",
                claim_anchor_tg_message_id=found.tg_message_id,
                claim_anchor_author=found.author,
                claim_anchor_source=(found.source or "window"),
                target_source="contextual",
                target_tg_message_id=found.tg_message_id,
                text_sufficient=True)
            logger.info("[factcheck_v2] claim from related material | "
                        "chat=%s | source=%s | basis=%s | anchor=%s", req.chat_id,
                        found.source, basis, found.tg_message_id)
            decision = fsg.evaluate_suitability(
                claim_text, req.user_hint, ctx,
                target_ref={"chat_id": req.chat_id,
                            "target_tg_message_id":
                                publication.target_tg_message_id,
                            "trigger_tg_message_id":
                                req.trigger_tg_message_id},
                explicit_request=explicit_request)
            # S13: материал, на который ссылается запрос, изменился (законная
            # contextual-подмена) — предмет пересобирается от НОВОГО материала,
            # а не остаётся привязанным к пустой цели.
            subject = await resolve_check_subject(
                service, material_text=claim_text,
                request_text=req.user_hint,
                material_author=str(found.author or ""),
                request_author=req.requester_name,
                material_tg_message_id=found.tg_message_id,
                request_tg_message_id=req.trigger_tg_message_id,
                chat_id=req.chat_id)

    # 1b. Envelope — ПОСЛЕ разрешения цели/тезиса (M3/BD-2): вердикт,
    #     план и поиск читают один текст; анкор Claim передаётся отдельно.
    envelope = None
    # B1: цель читается из публикации ПОСЛЕ возможной подмены (2b) — иначе
    # envelope строился бы по пустому сообщению, которое подменили.
    eff_target_tg = _declared_target_tg(publication, req)
    if db is not None and eff_target_tg not in (None, "", 0):
        try:
            from services.temporal_factcheck import InputRef
            envelope, reject_reason = await tf.build_envelope(
                db, InputRef(kind=req.kind, chat_id=req.chat_id,
                             target_tg_message_id=eff_target_tg,
                             trigger_tg_message_id=req.trigger_tg_message_id,
                             hint=req.user_hint,
                             # S13: предмет проверки — единый для envelope,
                             # декомпозиции, поиска, аналитика, validator,
                             # verbalizer и renderer. Исходный материал остаётся
                             # в material_claim_text/provenance.
                             subject=subject,
                             # §3.3/I3: в claim идёт РОВНО текст публикации —
                             # тот же, что увидит вердикт (когда публикация
                             # собрала тезис сверх сохранённой строки).
                             claim_text=(str(publication.text or "").strip()
                                         if publication.augmented else None),
                             claim_anchor_tg_message_id=getattr(
                                 publication, "claim_anchor_tg_message_id",
                                 None)),
                default_mode=str(req.default_mode or "contextual"))
        except Exception:
            logger.warning("[factcheck_v2] envelope build failed", exc_info=True)
            envelope = None
    # I3 (§1.5): расхождение текста вердикта и текста поиска — дефект, который
    # обязан быть видно, а не «нормализован» подменой.
    # I5: доставка Reply — реальный Telegram ID: при contextual-цели это
    # триггер (цель как сообщение = анкор), иначе сама цель.
    # B1: объявленная подмена (в т.ч. унаследованная от handler'а) доставляет
    # ответ на триггер, а не на пустое сообщение-цель.
    contextual_target = bool(contextual or declared_contextual)
    delivery_reply_to = (req.trigger_tg_message_id if contextual_target
                         else req.target_tg_message_id)
    _emit_target_trace(
        publication, chat_id=req.chat_id,
        trigger_tg_message_id=req.trigger_tg_message_id,
        delivery_reply_to=delivery_reply_to,
        envelope=envelope, route="orchestrator_v2",
        extra={"contextual_target": contextual_target,
               "subject_origin": str(getattr(subject, "origin", "") or ""),
               "subject_resolved_by": str(
                   getattr(subject, "resolved_by", "") or "")})

    feed = ""
    if ctx is not None:
        # §13 сц.7 / §9.5 п.2: тезис найден ПО ТЕМЕ (Reply у цели нет) —
        # окно помечает связь «↳ по теме … (не Reply)», а не выдаёт её за
        # подтверждённый Telegram Reply. Иначе — прежний сырой фид.
        projection, relations = fsg._semantic_link(ctx, ctx_claim, ctx_basis)
        feed = ctx.render_feed(projection=projection,
                               relations_by_item=relations)
        # §9.4 / §13 сц.109: метки этого фида обязаны иметь обратную карту в
        # защищённой трассе — как на остальных маршрутах
        # (`handlers/factcheck.py:428`, `factcheck_context.render_feed`-путь).
        # Без события «метка → реальный ID» ответ модели не проверяем.
        if projection is not None:
            emit_speech_projection_event(
                projection, chat_id=req.chat_id,
                message_id=req.target_tg_message_id,
                run_id=getattr(projection, "run_id", None))
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
                                 delivery_reply_to)
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
                                 delivery_reply_to)
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
                                 delivery_reply_to)
        tf.stage_event("deliver", "skipped", reason_code="no_claim_after_context",
                       chat_id=req.chat_id)
        return _finish(OUTCOME_NO_CLAIM, "v2_gate:no_claim")
    if decision is not None and decision.decision == fsg.DECISION_AMBIGUOUS:
        # RCI-04: короткая реплика получает уже посчитанный контекст
        # кандидатов (claim_items / значимые сообщения окна) — без выбора
        # темы, без поиска и без дополнительных LLM-вызовов.
        situation = _ambiguous_situation(req, decision, ctx)
        text = await persona_short_reply(
            service, req.chat_id, instruction=_SHORT_REPLY_INSTRUCTION,
            situation=situation, fallback_phrases=FACTCHECK_CLARIFY_PHRASES)
        if text and _media_unverified(publication):
            # Review-fix2 (B1): уточнение не должно скрывать, что содержимое
            # картинки не проверено.
            notice = publication.notice()
            if notice:
                text = f"{text}\n\n{notice}"
        delivered_id = None
        if text:
            delivered_id = await send_chunked_reply(bot, req.chat_id, text,
                                                    delivery_reply_to)
        # FC-OBSERVABILITY-01: короткая уточняющая реплика — такой же
        # доставленный слова бота, как вердикт: без записи в durable-ledger
        # опубликованный текст нельзя было проверить после прогона (в
        # `bot_replies` короткие gate-ответы не попадают). Пишется ТОЛЬКО
        # после подтверждённой отправки; fail-open — запись не рвёт доставку.
        if delivered_id is not None:
            from services import bot_output_ledger as _bol
            await _bol.record_factcheck_reply(
                db, chat_id=req.chat_id, tg_message_id=delivered_id,
                text=text, bot_user_id=getattr(bot, "id", None),
                parent_message_ref=(f"tg:{delivery_reply_to}"
                                    if delivery_reply_to is not None
                                    else None),
                correlation_id=pipeline_run_id)
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
                                 delivery_reply_to)
        tf.stage_event("deliver", "skipped",
                       reason_code="unsafe_or_unavailable_target",
                       chat_id=req.chat_id)
        return _finish(OUTCOME_UNAVAILABLE, "v2_gate:unavailable")

    # 3b. CFG-06 06G.3 — локальный tool «кто это сказал»: атрибуционный
    # спор («X сказал Y») решается ПО ConversationContext ДО любого
    # платного поиска. Совпадения нет → честный отказ БЕЗ домыслов;
    # реплика найдена → по существу проверяется ТОЛЬКО тезис (без обвязки
    # «X сказал»; BGS-01: имена внутри тезиса остаются в запросе),
    # атрибуция идёт в EvidenceMap (source_kind=chat).
    attribution = None
    attribution_match = None
    # S13: по существу проверяется ПРЕДМЕТ (не обязательно исходный текст);
    # атрибуционная обвязка «X сказал» по-прежнему снимается ниже только для
    # material-предмета — вопрос пользователя не переписывается.
    external_claim = (str(getattr(subject, "text", "") or "").strip()
                      or claim_text)
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
                    delivery_reply_to)
                tf.stage_event("deliver", "skipped",
                               reason_code="attribution_not_found",
                               chat_id=req.chat_id)
                return _finish(OUTCOME_NO_CLAIM, "v2_attribution:miss")
            external_claim = fat.attribution_thesis(req.target_text,
                                                    attribution)
            # S13: для material-предмета (обычный фактчек/разговорный
            # комментарий) сохраняется прежняя семантика BGS-01: проверяется
            # тезис без обвязки «X сказал». Собственный вопрос/условие
            # пользователя НЕ переписывается атрибуционным инструментом.
            if str(getattr(subject, "origin", "") or "") in (
                    "", SUBJECT_ORIGIN_MATERIAL):
                subject = dataclasses.replace(
                    subject, text=str(external_claim),
                    fingerprint=subject_fingerprint(
                        text=str(external_claim),
                        request_text=getattr(subject, "request_text", None),
                        material_text=getattr(subject, "material_text", ""),
                        material_tg_message_id=getattr(
                            subject, "material_tg_message_id", None)))
            else:
                external_claim = str(getattr(subject, "text", "")
                                     or claim_text)
            logger.info("[factcheck_v2] attribution resolved | chat=%s",
                        req.chat_id)
    except Exception:
        logger.warning("[factcheck_v2] attribution tool failed",
                       exc_info=True)
        attribution = None
        attribution_match = None
        external_claim = (str(getattr(subject, "text", "") or "").strip()
                          or claim_text)

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
    # План строится от клейма, которое проверяется по существу: для
    # атрибуционного спора это тезис без обвязки «X сказал» (BGS-01: имена
    # внутри тезиса сохраняются); без спора — сам req.target_text (паритет).
    retrieval_plan = fsp.build_retrieval_plan(
        decision, claim_text=external_claim,
        subject_origin=str(getattr(subject, "origin", "") or ""),
        subject_fingerprint=str(
            getattr(envelope, "subject_fingerprint", "")
            or getattr(subject, "fingerprint", "") or ""),
        subject_anchor_tg_message_id=getattr(
            subject, "request_tg_message_id", None),
        subject_author=str(getattr(subject, "request_author", "") or ""))
    if retrieval_plan is not None and retrieval_plan.queries:
        logger.info("[factcheck_v2] retrieval plan | chat=%s | queries=%d | "
                    "intents=%s", req.chat_id,
                    len(retrieval_plan.queries),
                    ",".join(q.intent for q in retrieval_plan.queries))
        # M6 (§1.5): каждая часть плана знает, какому сообщению/автору она
        # принадлежит (или честно не знает — тогда анкор пустой).
        anchors = tuple(getattr(retrieval_plan, "claim_anchors", ()) or ())
        if anchors:
            logger.info("[factcheck_v2] claim anchors | chat=%s | %s",
                        req.chat_id,
                        " | ".join(
                            f"{row.get('claim_id')}:"
                            f"{row.get('anchor_tg_message_id') or '-'}"
                            for row in anchors))
            try:
                from services import mca_events
                mca_events.emit_mca_event(
                    "factcheck_claim_anchors", outcome="success",
                    level="INFO", component="factcheck.claims",
                    chat_id=req.chat_id,
                    pipeline_run_id=pipeline_run_id,
                    entity_ids={"claims": [dict(row) for row in anchors]})
            except Exception:      # pragma: no cover — событие не рвёт прогон
                logger.debug("[factcheck_v2] anchors event failed")
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
        # Поисковые стадии временной ветки получают тезис клейма без обвязки
        # «X сказал» (frozen-replace, provenance не меняется; BGS-01: имена
        # внутри тезиса не вычищаются).
        if attribution_match is not None:
            envelope = fat.with_claim_thesis(envelope, external_claim)
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
            and str(getattr(verdict, "reason_code", "") or "") in
            ("", "insufficient_evidence")):
        # P0-FACTCHECK (§3.6): материалы найдены, но проверяемых ссылок нет —
        # вывод нельзя подавать как подтверждённый источниками. Технический
        # класс уже назван заголовком, когда reason_code есть.
        # ES-4 (§11.2 п.6): оговорка нужна и при `insufficient_evidence` —
        # это не техсбой, но цитируемость ограничена, и сказать об этом надо.
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
        verdict, reply_to_message_id=delivery_reply_to,
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
            visible_text,
        )
        presentation = render_factcheck(presentation, verdict)
        delivered_first_id = await deliver_factcheck(
            bot, req.chat_id, presentation,
            reply_to_message_id=(presentation.reply_to_message_id))
        # UR-23.4 (UR-C): доставленный вердикт — в тот же durable ledger
        # `mca_bot_outputs`, что и другие прямые ответы (MCA-22 C2);
        # correlation_id — pipeline_run_id прогона. Только после
        # подтверждённой отправки; в ledger идёт видимый доставленный текст
        # (plain), а не HTML-разметка чанков. Fail-open: запись не рвёт
        # доставку; verdict/content pipeline не затронут.
        if delivered_first_id is not None:
            from services import bot_output_ledger as _bol
            await _bol.record_factcheck_output(
                db, chat_id=req.chat_id, tg_message_id=delivered_first_id,
                text=(visible_text(presentation.text)
                      if presentation.parse_mode else presentation.text),
                bot_user_id=getattr(bot, "id", None),
                parent_message_ref=(f"tg:{presentation.reply_to_message_id}"
                                    if presentation.reply_to_message_id
                                    else None),
                correlation_id=pipeline_run_id)
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
        trace_id=pipeline_run_id, pipeline_run_id=pipeline_run_id,
        media_state=publication.media_dependency(),
        final_headline_code=_headline_code(verdict))
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
    06G.3/BGS-01: ``target_text`` — тезис клейма без атрибуционной обвязки
    «X сказал» (имена внутри тезиса сохраняются);
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


def _headline_code(verdict) -> str:
    """§11.3: код финального заголовка из renderer (fail-open)."""
    try:
        from services.factcheck_renderer import headline_code
        return headline_code(verdict)
    except Exception:      # pragma: no cover — трасса не рвёт доставку
        return ""


def _emit_target_trace(publication, **kwargs) -> dict:
    """§10.3: трасса цели/медиа (единая реализация — factcheck_service)."""
    from services.factcheck_service import emit_target_trace
    kwargs.setdefault("route", "orchestrator_v2")
    return emit_target_trace(publication, **kwargs)


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
        "irrelevant=%d | budget_exhausted=%s | fetch_skipped_deadline=%s | "
        "version=%s",
        chat_id, outcome.queries_attempted, outcome.queries_used,
        outcome.refs_collected, outcome.fetch_errors,
        getattr(outcome, "provider_failures", 0),
        getattr(outcome, "empty_results", 0),
        getattr(outcome, "irrelevant_results", 0),
        outcome.budget_exhausted,
        getattr(outcome, "fetch_skipped_deadline", 0),
        outcome.planner_version)
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
            planner_version=outcome.planner_version,
            entity_ids={"fetch_skipped_deadline": getattr(
                outcome, "fetch_skipped_deadline", 0)})
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
                               pipeline_run_id: str = "",
                               media_state: str = "",
                               final_headline_code: str = "") -> dict:
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
        # §11.3/§10.3: итоговый код заголовка и состояние медиа — из
        # фактического прогона (пустое значение = «не установлено»).
        "final_headline_code": str(final_headline_code or ""),
        "media_state": str(media_state or ""),
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
