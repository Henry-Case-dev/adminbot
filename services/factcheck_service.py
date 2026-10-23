"""Epic 33/46 — FactCheckService: пайплайн фактчека (R33-3, Sections 42.6/55.5).

check_claim: SearchAggregator.search → FACTCHECK_SYSTEM_PROMPT (подстановка
{max_symbols} через .replace) → build_user_content → LLMClient.generate →
cleanup_llm_text (R33-7, ВСЕГДА). Ошибки поиска/LLM пробрасываются в хендлер
(AllSearchEnginesFailedException / LLMError) — фразы выбирает хендлер.

Epic 46 (55.5): после aggregator.search() — fire_and_forget-хук
memorize_facts(chat_id, results, "search_fact") + гибридный RAG префиксом
user-контента. memory=None / chat_id=None → ровно старое поведение.

Раунд 10.20 (БЛОК 6.2, ADR-1020-5 п.1, T-1907): Full Tool Access — аддитивный
kwarg `tool_router` (DI из bot.py, только kwargs). Если роутер задан и есть
`chat_id`, вердикт считается существующим циклом `tool_loop.chat_with_tools`
(tool-сет `dig_into_lore` + `compile_lore_story` + `execute_web_search`), а не
одиночным `llm.generate`. Пайплайн «claim → вердикт» сохраняется: tool-loop —
обёртка ВОКРУГ `llm.generate`, второго синтеза нет. Роутер не задан
(старые вызовы/тесты) → ровно прежний одиночный вызов (R16-аддитивность).
"""
import dataclasses
import datetime
import json
import logging
import time

from config.settings import settings
from services import hot_config as hot
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    FACTCHECK_SYSTEM_PROMPT,
    FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
    PREV_FACTCHECK_VERBALIZER_R1023,
)
from services.grounding_validator import (
    collect_allowed_anchors,
    strip_phantom_tags,
)
from services.llm_client import LLMBadResponseError, LLMClient, LLMError
from services import anticliche_cache
from services import mca_gates
from services import usage_events
from services.prompt_composer import speech_owner_block
from services.negative_constraints import (
    NumericContract,
    channel_enabled_rules,
    verbalize_validated,
)
from services.prompt_style_blocks import (
    compose_verbalizer_system,
    resolve_prompt,
)
from services.reply_postprocess import strip_reasoning_tags
from services.search_aggregator import SearchAggregator, AllSearchEnginesFailedException
from services import temporal_factcheck as tf
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, fire_and_forget
from services.summary_xml import escape_xml_text
from services.smartmodule_utils import strip_lore_html
from services.system2_handoff import (
    normalize_response_mode,
    parse_factcheck_analysis,
    stage2_payload,
)
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, resolve_lore_compiler_flag
from services.tool_schemas import factcheck_tools

logger = logging.getLogger(__name__)


def _metatext_retry_reason():
    """CFG-07D.5: callable причины смысловой метаречи для bounded retry
    Вербализатора — ТОЛЬКО в контуре pipeline v2 (тот же рубильник, что
    диспетчеризует handler/оркестратор: hot ``flags.factcheck_pipeline_v2``
    → env). OFF (default) → ``None``: контракт не активен, поведение
    байт-в-байт прежнее (OFF-паритет). Никогда не бросает."""
    try:
        from services.factcheck_orchestrator import pipeline_v2_enabled
        if not pipeline_v2_enabled():
            return None
    except Exception:      # pragma: no cover — fail-soft OFF
        return None
    try:
        from services.public_speech_guard import metatext_retry_reason
        return metatext_retry_reason
    except Exception:      # pragma: no cover — guard не роняет Writer
        return None


def _emit_factcheck(outcome: str, *, level: str = "INFO", **fields):
    """MCA-17 (`factcheck.run`): fail-open эмиссия (REUSE mca-13).

    Это событие ВЕРДИКТ-пайплайна (`check_claim`, process `factcheck.run`);
    события mca-20 temporal-пайплайна (`factcheck_temporal`,
    `check_claim_envelope`) — отдельный контур и здесь НЕ дублируются.
    R17: только chat_id/коды/длительность — claim-текст не переносится."""
    try:
        from services.mca_events import emit_mca_event
        emit_mca_event("factcheck_run", outcome=outcome, level=level,
                       component="factcheck", **fields)
    except Exception:      # контракт не рвёт вердикт
        pass


def _temporal_max_evidence() -> int:
    """mca-20: потолок evidence-строк прогона (env-лимит gates, D16)."""
    try:
        from services import mca_gates
        return mca_gates.temporal_max_evidence_per_run()
    except Exception:      # pragma: no cover
        return 20


def _fmt_evidence_date(published_at) -> str:
    """D10/§18G.5: unix ts → ISO-дата для evidence-секции; None →
    'unknown' (честно; never now())."""
    if not published_at:
        return "unknown"
    try:
        return datetime.datetime.fromtimestamp(
            int(published_at), datetime.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return "unknown"


# ── CFG-06 W5: человекочитаемый дайджест вердикта для вербализатора ─────────
# (06A.5: enum-статусы/precision/as_of больше не попадают в payload
# вербализатора — только человеческие формулировки; «unknown» → слова).

_HUMAN_FACTUAL_VERDICT = {
    "supported": "утверждение подтверждается доступными данными",
    "refuted": "доступные данные утверждение не подтверждают",
    "mixed": "данные противоречивы — утверждение верно лишь частично",
}


def _human_factual_verdict(factual: str | None) -> str:
    return _HUMAN_FACTUAL_VERDICT.get(
        str(factual or ""), "данных недостаточно для уверенного вывода")


_HUMAN_TEMPORAL_STATUS = {
    "current": "данные актуальны",
    "outdated": "данные устарели",
    "old_but_valid": "данные старые, но к утверждению остаются применимы",
    "misleading_reuse": "старые данные поданы как свежие",
}


def _human_temporal_status(status: str | None) -> str:
    return _HUMAN_TEMPORAL_STATUS.get(
        str(status or ""), "свежесть данных определить не удалось")


def _human_evaluated_period(period: dict | None) -> str:
    """Даты периода проверки по-человечески; дат нет → '' (ключ в payload
    не попадает, никакого «unknown»/precision в тексте)."""
    def _fmt(ts):
        if not ts:
            return None
        try:
            return datetime.datetime.fromtimestamp(
                int(ts), datetime.timezone.utc).strftime("%d.%m.%Y")
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    p = period or {}
    p_from, p_to = _fmt(p.get("from")), _fmt(p.get("to"))
    if p_from and p_to and p_from != p_to:
        return f"с {p_from} по {p_to}"
    if p_from:
        return f"на {p_from}"
    return ""


# ── P0-FACTCHECK (owner 24.10.2026 §3.3/§3.5/§3.6): материал изображения ──────
# Текст с картинки приходит в анализ ЧЕРЕЗ СУЩЕСТВУЮЩИЙ Vision-контур
# (`mca_vision.render_media_context_async`: OCR + визуальное описание уже
# сохранённого анализа). Новый OCR/vision-пайплайн не создаётся; если анализ
# ещё не готов — честная пометка `image_not_analyzed`, подпись сохраняется.

@dataclasses.dataclass(frozen=True)
class ClaimMediaMaterial:
    """Что дало изображение целевого сообщения (для анализа и честности)."""
    text_suffix: str = ""             # блок для claim/envelope (пусто — нет)
    image_present: bool = False
    image_analyzed: bool = False
    image_not_analyzed: bool = False
    ocr_chars: int = 0
    caption: str = ""

    def notice(self) -> str:
        """Человеческое ограничение (никогда не выдумывает распознавание)."""
        if self.image_not_analyzed:
            return ("На изображении мог быть текст, но распознавание ещё не "
                    "готово — проверен только текст сообщения.")
        return ""


async def load_claim_media(db, chat_id: int | None,
                           tg_message_id: int | None, *,
                           render_async=None,
                           max_chars: int = 2000) -> ClaimMediaMaterial:
    """OCR-текст изображения целевого сообщения (REUSE mca_vision).

    Возвращает контракт «что попало в анализ»: ``text_suffix`` уходит в
    claim/envelope (=> в поисковые запросы и в промпт аналитика), а
    ``image_not_analyzed`` — честная пометка, когда изображение есть, но
    распознавания ещё нет. Fail-open: любая ошибка → пустой материал
    (прежнее поведение без изображения)."""
    if db is None or not chat_id or not tg_message_id:
        return ClaimMediaMaterial()
    if render_async is None:
        try:
            from services import mca_vision
            render_async = mca_vision.render_media_context_async
        except Exception:          # pragma: no cover — vision выключен
            return ClaimMediaMaterial()
    try:
        media = await render_async(db, chat_id=int(chat_id),
                                   tg_message_id=int(tg_message_id))
    except Exception:
        logger.warning("[factcheck] media context read failed — caption only",
                       exc_info=True)
        return ClaimMediaMaterial()
    if not media:
        return ClaimMediaMaterial()
    caption = str(media.get("caption") or "").strip()
    ocr_texts = [str(t).strip() for t in (media.get("untrusted_ocr_texts")
                                          or ()) if str(t or "").strip()]
    ocr_text = "\n".join(ocr_texts).strip()[:max_chars]
    if not ocr_text:
        return ClaimMediaMaterial(image_present=True, image_not_analyzed=True,
                                  caption=caption)
    suffix = ("Текст с изображения (OCR, не слова автора):\n"
              + ocr_text)
    return ClaimMediaMaterial(text_suffix=suffix, image_present=True,
                              image_analyzed=True, ocr_chars=len(ocr_text),
                              caption=caption)


# ── P0-FACTCHECK (§3.6): классы исхода retrieval — сбой ≠ «нет данных» ───────

RETRIEVAL_OK = "ok"
RETRIEVAL_NOT_RUN = "not_run"
RETRIEVAL_BUDGET = "budget_exhausted"
RETRIEVAL_SEARCH_FAILED = "search_failed"
RETRIEVAL_PROCESSING_FAILED = "processing_failed"
RETRIEVAL_INSUFFICIENT = "insufficient_evidence"

#: Класс → существующий reason-код реестра (новые коды не выдумываются:
#: `verdict_from_payload` пропускает только REASON_CODES).
_RETRIEVAL_REASON = {
    RETRIEVAL_BUDGET: "deadline_exceeded",
    RETRIEVAL_SEARCH_FAILED: "provider_unavailable",
    RETRIEVAL_PROCESSING_FAILED: "source_missing",
    RETRIEVAL_INSUFFICIENT: "insufficient_evidence",
}

#: Класс → человеческая оговорка (в uncertainty; НЕ выдуманный вердикт).
_RETRIEVAL_CAVEAT = {
    RETRIEVAL_BUDGET: ("поиск прерван по лимиту времени — проверены не все "
                       "запросы"),
    RETRIEVAL_SEARCH_FAILED: ("поисковые сервисы не ответили — это "
                              "технический сбой, а не отсутствие фактов"),
    RETRIEVAL_PROCESSING_FAILED: ("поиск дал материалы, но пригодных для "
                                  "проверки выдержек из них не получено"),
}

#: Класс → что честно сказать вербализатору (замена «данных недостаточно»).
_RETRIEVAL_SITUATION = {
    RETRIEVAL_BUDGET: ("проверка не завершена: истёк лимит времени на поиск"),
    RETRIEVAL_SEARCH_FAILED: ("проверка не завершена: поисковые сервисы "
                              "оказались недоступны"),
    RETRIEVAL_PROCESSING_FAILED: ("поиск выполнен, но найденные материалы не "
                                  "удалось превратить в проверяемые выдержки"),
}


def classify_retrieval(retrieval) -> str:
    """RetrievalOutcome → класс исхода (P0-FACTCHECK §3.6).

    ``None`` → not_run (внутренний поиск ветки, прежний контракт). Есть
    evidence → ok. Нет evidence, но метрики говорят о технической причине —
    бюджет/недоступность провайдеров/потеря обработки; иначе — реальная
    недостаточность доказательств. Детерминированно, без новых вызовов."""
    if retrieval is None:
        return RETRIEVAL_NOT_RUN
    try:
        if getattr(getattr(retrieval, "evidence_map", None), "refs", ()):
            return RETRIEVAL_OK
        attempted = int(getattr(retrieval, "queries_attempted", 0) or 0)
        used = int(getattr(retrieval, "queries_used", 0) or 0)
        failures = int(getattr(retrieval, "provider_failures", 0) or 0)
        if getattr(retrieval, "budget_exhausted", False) and used == 0:
            return RETRIEVAL_BUDGET
        if used == 0 and (attempted > 0 or failures > 0):
            return RETRIEVAL_SEARCH_FAILED
        if used > 0:
            return RETRIEVAL_PROCESSING_FAILED
    except Exception:          # pragma: no cover — метрики не рвут вердикт
        return RETRIEVAL_NOT_RUN
    return RETRIEVAL_INSUFFICIENT


def _server_parts(envelope, evidence) -> tuple:
    """FC-PERCLAIM (§3.5): части из СЕРВЕРНОЙ декомпозиции, когда модель их
    не дала. Вердикт части — не выше insufficient_evidence (положительный
    без доказательства запрещён); evidence привязывается к части по
    содержательному перекрытию, а не «ко всему прогону»."""
    try:
        from services import temporal_factcheck as tf
        parts = list(tf.decompose_claim(envelope))[:4]
    except Exception:
        return ()
    if len(parts) < 2:
        return ()
    try:
        from services.factcheck_planner import _claim_terms
    except Exception:          # pragma: no cover
        def _claim_terms(text, limit=8):
            return [w for w in str(text or "").lower().split()
                    if len(w) > 3][:limit]

    ref_ids = [str(r.get("evidence_id")) for r in (evidence or ())
               if r.get("evidence_id")]
    support_by_id = {str(r.get("evidence_id")): str(r.get("support") or "")
                     for r in (evidence or ()) if r.get("evidence_id")}
    result: list[dict] = []
    for part in parts:
        terms = _claim_terms(part.text, limit=10)
        scored: list[tuple[int, str]] = []
        for ref_id in ref_ids:
            haystack = support_by_id.get(ref_id, "").lower()
            score = sum(1 for t in terms if t in haystack)
            if score > 0:
                scored.append((score, ref_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        result.append({
            "part_id": part.part_id,
            "text": part.text,
            "factual_verdict": "insufficient_evidence",
            "evidence_refs": [rid for _s, rid in scored[:2]],
        })
    return tuple(result)


class FactCheckService:
    """Фактчек: поиск фактов по целевому тексту → LLM-вердикт → cleanup."""

    def __init__(self, aggregator: SearchAggregator, llm: LLMClient,
                 memory: MemoryManager | None = None,
                 tool_router=None) -> None:
        self.aggregator = aggregator
        self.llm = llm
        self.memory = memory
        # T-1907: DI ToolRouter (None → прежнее поведение без тулов).
        self.tool_router = tool_router

    async def check_claim(
        self,
        target_text: str,
        user_hint: str | None = None,
        forward_source: str | None = None,
        chat_id: int | None = None,
        chat_context: str | None = None,
        search_results: str | None = None,
    ) -> str:
        """MCA-17 (`factcheck.run`): терминал verify — success/failed +
        reason из словаря §17.2, затем делегация в пайплайн 10.22.

        ``search_results`` (CFG-06 W6, 06C.8): готовая выдача единого
        retrieval-контура v2 — внутренний поиск агрегатора пропускается
        (один поиск на прогон). None → прежний путь байт-в-байт."""
        started = time.monotonic()

        def duration_ms() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            result = await self._check_claim_pipeline(
                target_text, user_hint=user_hint,
                forward_source=forward_source, chat_id=chat_id,
                chat_context=chat_context, search_results=search_results)
        except AllSearchEnginesFailedException:
            _emit_factcheck("failed", level="WARN", chat_id=chat_id,
                            reason_code="provider_unavailable",
                            duration_ms=duration_ms())
            raise
        except LLMError:
            # LLMError-семейство (таймаут/лимит/пустой ответ) — недоступность
            # модели, а не движков поиска.
            _emit_factcheck("failed", level="WARN", chat_id=chat_id,
                            reason_code="model_unavailable",
                            duration_ms=duration_ms())
            raise
        except Exception:
            # Вне классифицированных семейств — честный failed без
            # выдуманного reason-кода.
            _emit_factcheck("failed", level="WARN", chat_id=chat_id,
                            duration_ms=duration_ms())
            raise
        _emit_factcheck("success", chat_id=chat_id,
                        duration_ms=duration_ms())
        return result

    async def _check_claim_pipeline(
        self,
        target_text: str,
        user_hint: str | None = None,
        forward_source: str | None = None,
        chat_id: int | None = None,
        chat_context: str | None = None,
        search_results: str | None = None,
    ) -> str:
        """Фактчек-пайплайн (10.22, ADR-1022-3): агрегатор → (System 2:
        Аналитик JSON → Вербализатор) либо одиночный путь 10.21.

        * ``SYSTEM2_FACTCHECK_ENABLED`` ON → два физических вызова; при
          невалидном JSON/провале Stage-2/исчерпании validator-loop — fallback
          на одиночный путь (пользователь ВСЕГДА получает ответ).
        * OFF → байт-в-байт 10.21 (один вызов `self.llm.generate`/tool-loop).
        * ``search_results`` (W6): готовая выдача единого retrieval-контура
          v2 → агрегатор не вызывается; None → прежний поиск байт-в-байт.
        Raises: AllSearchEnginesFailedException (поиск) / LLMError (LLM)."""
        # F7 (ADR-1023-7 D4): один сквозной id на вердикт фактчека.
        correlation_id = usage_events.new_correlation_id()
        # T-619: лимит и промпт — горячие точки (ConfigCache с settings-фолбеком)
        max_symbols = hot.get("limits.factcheck_max_symbols",
                              settings.FACTCHECK_MAX_SYMBOLS)
        # SOUL-1 (W1 fix-pass, BLOCKER-2): единый резолвер реестра —
        # persisted-значение канона проходит провенанс/вычистку legacy-речи.
        system_prompt = resolve_prompt("prompts.factcheck_system_prompt",
                                       FACTCHECK_SYSTEM_PROMPT)
        if search_results is None:
            results = await self.aggregator.search(target_text, max_symbols)
        else:
            results = str(search_results)
        if self.memory is not None and chat_id is not None:
            fire_and_forget(
                self.memory.memorize_facts(chat_id, results, "search_fact"), "factcheck")
            # 10.20 (БЛОК 2.6, ADR-1020-2): ASC-хронология перед рендером.
            rag = await self.memory.get_rag_context(
                chat_id, target_text, sort_by_timestamp=True)
        else:
            rag = ""
        user = self.build_user_content(target_text, user_hint, forward_source,
                                       results, chat_context=chat_context)
        if rag:
            user = f"{rag}\n\n{user}"
        if getattr(settings, "SYSTEM2_FACTCHECK_ENABLED", True):
            two_call = await self._check_claim_two_call(
                target_text, user, rag, results, chat_id, max_symbols,
                correlation_id)
            if two_call is not None:
                return two_call
            logger.info(
                "factcheck system2: fallback на одиночный путь 10.21 | chat=%s",
                chat_id)
        # ── Одиночный путь 10.21 (kill-switch / fallback) ──
        # UNIFIED-CORE (P0, 20.10.2026): одиночный путь — тоже пользовательская
        # вербализация: после жанрового канона идут ТЕ ЖЕ Core + Expression
        # (GLOBAL/per-chat, hot-apply); конфиг-слой недоступен → блок пуст
        # (байт-паритет прежней сборки).
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        owner_block = await speech_owner_block(chat_id)
        if owner_block:
            system = f"{system}\n\n{owner_block}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw, used_tools = await self._invoke_llm(
            messages, target_text, chat_id, correlation_id=correlation_id,
            step="single")
        return self._finalize(raw, used_tools, rag, results)

    async def _check_claim_two_call(
        self, target_text: str, user: str, rag: str, results: str,
        chat_id: int | None, max_symbols: int,
        correlation_id: str | None = None,
    ) -> str | None:
        """System 2 фактчека. ``None`` → вызывающий уходит на 10.21."""
        analyst_messages = [
            {"role": "system", "content": resolve_prompt(
                "prompts.factcheck_analyst_system_prompt",
                FACTCHECK_ANALYST_SYSTEM_PROMPT)},
            {"role": "user", "content": user},
        ]
        try:
            raw_analyst, used_tools = await self._invoke_llm(
                analyst_messages, target_text, chat_id,
                correlation_id=correlation_id, step="stage1")
        except Exception as exc:                # таймаут/ошибка Stage-1 → 10.21
            logger.info(
                "factcheck system2: stage1 failed — fallback | chat=%s | "
                "error=%s", chat_id, type(exc).__name__)
            return None
        tool_context = str(getattr(raw_analyst, "tool_context", "") or "")
        anchors = collect_allowed_anchors(
            self._trusted_text(rag, results, tool_context))
        analyst_text = strip_reasoning_tags(str(raw_analyst))
        analyst_text, _gstats = strip_phantom_tags(analyst_text, anchors)
        data = parse_factcheck_analysis(analyst_text)
        if data is None:
            logger.info(
                "factcheck system2: невалидный JSON аналитика — fallback | "
                "chat=%s", chat_id)
            return None
        response_mode = normalize_response_mode(data.get("response_mode"))
        modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True)
        verbalizer_template = (
            resolve_prompt("prompts.factcheck_verbalizer_system_prompt",
                           FACTCHECK_VERBALIZER_SYSTEM_PROMPT)
            if modes_on else PREV_FACTCHECK_VERBALIZER_R1023)
        verbalizer_base = verbalizer_template.replace(
            "{max_symbols}", str(max_symbols))
        # UNIFIED-CORE (P0, 20.10.2026): Вербализатор — пользовательская
        # вербализация фактчека → Core + Expression владельца (критерии §5:
        # один Core везде; жанровые исключения сняты; объективность, ссылки
        # и структура жанра остаются в каноне). Блок идёт ПОСЛЕ режимного/
        # канального (character_block — последний part; MCA-08 шов).
        owner_block = await speech_owner_block(chat_id)
        # Review iter1 (H2): у фактчека нет safe-HTML-доставки → text-only
        # plain-блок (без требования `<b>`, без HTML-тегов вовсе).
        verbalizer_system = (compose_verbalizer_system(
            verbalizer_base, response_mode, "plain",
            character_block=owner_block)
            if modes_on else
            (f"{verbalizer_base}\n\n{owner_block}" if owner_block
             else verbalizer_base))
        base_messages = [
            {"role": "system", "content": verbalizer_system},
            {"role": "user",
             # spec F3 §3.1: служебный response_mode в Stage-2 не утекает.
             "content": "АНАЛИЗ (JSON):\n" + json.dumps(
                 stage2_payload(data), ensure_ascii=False)},
        ]

        async def _generate(messages):
            return await self.llm.generate(
                messages, module="factcheck", step="stage2",
                correlation_id=correlation_id)

        # F3 (ADR-1023-3): plain-канал → guard от таблиц (без запрета буллитов,
        # буллиты в фактческе жанром не запрещены).
        enabled_rules = (channel_enabled_rules("plain", response_mode)
                         if modes_on else None)
        # MCA-15 (T-4931, D5; K2): числа в стат-контексте — только из
        # измерений ЭТОГО хода (per-turn реестр). Нет измерений → пустой
        # контракт: незаземлённое число не публикуется (оговорка/снятие).
        numeric_contract = None
        if mca_gates.numeric_claim_guard_enabled():
            try:
                from services import chat_statistics as _cs
                claims: list = []
                for result in (getattr(raw_analyst, "metric_results", None)
                               or []):
                    claims.extend(_cs.claims_for_result(result))
                numeric_contract = NumericContract(claims=tuple(claims))
            except Exception:
                numeric_contract = None
        text, stats = await verbalize_validated(
            _generate, base_messages, max_retries=2,
            enabled_rules=enabled_rules,
            dynamic_rules=anticliche_cache.get_rules() or None,
            numeric_contract=numeric_contract,
            metatext_reason=_metatext_retry_reason())
        logger.info(
            "factcheck system2 verbalizer | chat=%s | mode=%s | attempts=%d "
            "| retries=%d | hits=%d | fallback=%s", chat_id, response_mode,
            stats.get("attempts", 0), stats.get("retries", 0),
            len(stats.get("hits") or []), bool(stats.get("fallback")))
        if stats.get("fallback"):
            return None
        return self._finalize_text(text, used_tools, tool_context, rag, results)

    async def _invoke_llm(self, messages, target_text, chat_id, *,
                          correlation_id: str | None = None,
                          step: str = "single"):
        """Один LLM-вызов: tool-loop (при `tool_router` + `chat_id`) или plain.

        F7 (ADR-1023-7 D4): `correlation_id`/`step` — аддитивная телеметрия
        (когда тулов нет, вызов идёт с переданным `step`)."""
        started = time.monotonic()
        used_tools = False
        if self.tool_router is not None and chat_id is not None:
            lore_enabled = await resolve_lore_compiler_flag(chat_id)
            tools = factcheck_tools(bool(lore_enabled))
            ctx = ToolContext(chat_id, target_text,
                              lore_verbatim_instruction=False,
                              correlation_id=correlation_id)
            raw = await chat_with_tools(
                self.llm, messages, tools=tools,
                router=self.tool_router, ctx=ctx, chat_id=chat_id,
                module="factcheck", correlation_id=correlation_id)
            used_tools = True
            # MCA-15 (T-4931, D5): per-turn MetricResult-реестр хода —
            # numeric-гард фактчек-ответа (без второго измерения/судьи).
            try:
                raw.metric_results = list(
                    getattr(ctx, "metric_results", []) or [])
            except Exception:      # str-результат без атрибутов — не гард
                pass
            logger.info(
                "factcheck tool-loop OK | chat=%s | tools=%d | out_chars=%d "
                "| latency_ms=%.0f", chat_id, len(tools), len(raw),
                (time.monotonic() - started) * 1000.0,
            )
        else:
            raw = await self.llm.generate(
                messages, module="factcheck", step=step,
                correlation_id=correlation_id)
            logger.info(
                "factcheck LLM OK | out_chars=%d | latency_ms=%.0f",
                len(raw), (time.monotonic() - started) * 1000.0,
            )
        return raw, used_tools

    @staticmethod
    def _trusted_text(rag, results, tool_context) -> str:
        """Доверенные источники grounding-якорей (S10.21-5: без claim/hint).

        10.23 (F2, ADR-1023-2, R1023F2-04/12): ``chat_context`` (включая
        ``<reply_chains>``) НАМЕРЕННО не принимается — это контекст «не
        доказательства», и его таймстампы (``ДД.ММ.ГГГГ``) не должны
        становиться grounding-якорями и «заземлять» фантомные ``[ММ.ГГГГ]``
        теги. Якоря — только из доказательств: RAG, поисковая выдача,
        tool-контекст. Параметр убран, чтобы исключение нельзя было случайно
        откатить «для симметрии»."""
        parts = [str(rag or ""), str(results or "")]
        if tool_context:
            parts.append(str(tool_context))
        return "\n".join(parts)

    def _finalize(self, raw, used_tools, rag, results) -> str:
        tool_context = str(getattr(raw, "tool_context", "") or "")
        return self._finalize_text(str(raw), used_tools, tool_context,
                                   rag, results)

    def _finalize_text(self, text, used_tools, tool_context, rag, results) -> str:
        """cleanup → grounding-strip → HTML-strip → пустой ответ.

        Review iter1 (H2): whitelist-HTML-теги (`<b>` и пр.) срезаются ВСЕГДА,
        а не только при тулах — фактчек-канал не рендерит HTML, сырой тег
        пользователю показывать нельзя.
        """
        anchors = collect_allowed_anchors(
            self._trusted_text(rag, results, tool_context))
        out = cleanup_llm_text(text)
        out, gstats = strip_phantom_tags(out, anchors)
        if gstats.stripped_phantom or gstats.stripped_bare:
            logger.info(
                "factcheck grounding | stripped_phantom=%d | stripped_bare=%d "
                "| kept=%d",
                gstats.stripped_phantom, gstats.stripped_bare, gstats.kept,
            )
        out = strip_lore_html(out)
        if not out.strip():
            raise LLMBadResponseError("factcheck: empty answer")
        return out

    @staticmethod
    def build_user_content(
        target_text: str,
        user_hint: str | None,
        forward_source: str | None,
        search_results: str,
        chat_context: str | None = None,
    ) -> str:
        """Контекст пользователя (42.6 + Epic 65):
        # <claim>…</claim>  — всегда (ПЕРВЫМ — SIGIR'26: улики по краям промпта)
        #   с атрибутом is_forward/forward_source при репосте
        # <chat_context …>…</chat_context> — Epic 65: болтовня чата вокруг цели,
        #   маркирована НЕ-доказательства (NAACL'22/MAD2: контекст помогает);
        # <user_hint>…</user_hint> — только если user_hint задан
        # <search_results>…</search_results> — всегда (ПОСЛЕДНИМ)
        # Все значения — через escape_xml_text (services/summary_xml.py)"""
        claim_text = escape_xml_text(target_text)
        if forward_source:
            claim = (
                f'<claim is_forward="true" '
                f'forward_source="{escape_xml_text(forward_source, quote=True)}">'
                f"{claim_text}</claim>"
            )
        else:
            claim = f"<claim>{claim_text}</claim>"
        parts = [claim]
        if chat_context:
            parts.append(chat_context)       # готовый <chat_context> из chat_context.py
        if user_hint:
            parts.append(f"<user_hint>{escape_xml_text(user_hint)}</user_hint>")
        parts.append(f"<search_results>{escape_xml_text(search_results)}</search_results>")
        return "\n\n".join(parts)

    # ── MCA-20 (ADR-1028-20 D1/D11, round 10.44): envelope-пайплайн ────────
    # ЕДИНЫЙ сервис фактчека (не второй пайплайн, CA-20-1): аналитик →
    # validator/verbalizer и ВСЕ fallback-пути читают один
    # TemporalClaimEnvelope; стадии — data-only БЕЗ инструментов
    # (рекурсивный fact_check невозможен по построению — CA-20-12);
    # BehaviorFrame/стилизация применяются только после TemporalVerdict
    # (CA-20-13). OFF-путь `check_claim` не тронут (бит-в-бит d298f1f).

    async def check_claim_envelope(
        self,
        envelope: tf.TemporalClaimEnvelope,
        *,
        chat_context: str | None = None,
        stage_trace: tf.StageTrace | None = None,
        retrieval=None,
    ) -> tf.TemporalRunResult:
        """Сквозной пайплайн `temporal.factcheck` (8 стадий, D15).

        ``retrieval`` (FC-UNIFY, owner 21.10.2026 §3.2): выдача единого
        retrieval-контура v2 (factcheck_planner.RetrievalOutcome) — внутренний
        temporal-поиск не дублируется (один поиск на прогон); evidence
        строится из структурных строк планировщика (включая primary-выдержки
        SafeFetcher). None → прежний внутренний поиск (теперь тоже смысловые
        запросы, FC-SEMQUERY).

        Raises: LLMBadResponseError (пустой ответ вербализатора на всех
        ветках) — вызывающий решает показ ошибки; поиск НИКОГДА не даёт
        refuted (F-1/TH-5: недоступность → honest insufficient_evidence)."""
        trace = stage_trace or tf.StageTrace()
        env = envelope
        trace.add("target_resolve", "success"
                  if env.target_tg_message_id is not None else "skipped")
        # origin/date_resolve: даты уже в envelope (каскад D5); unknown —
        # честный исход, не ошибка.
        trace.add("origin_date_resolve", "success",
                  reason=None if env.date_source != "unknown"
                  else "temporal_date_unknown")
        tf.stage_event("origin_date_resolve", "success", chat_id=env.chat_id,
                       reason_code=env.date_source == "unknown"
                       and "temporal_date_unknown" or None)

        # claim_decompose (D8): части с собственными периодами; числа —
        # REUSE mca-15 (NumericClaim-совместимые словари).
        parts = tf.decompose_claim(env)
        trace.add("claim_decompose", "success")
        tf.stage_event("claim_decompose", "success", chat_id=env.chat_id)

        # temporal_search (D8/FC-UNIFY): выдача ЕДИНОГО retrieval-контура v2,
        # когда план выполнен оркестратором (один поиск на прогон); None →
        # внутренний fallback — теперь тоже СМЫСЛОВЫЕ запросы по частям
        # (FC-SEMQUERY), а не слайс начала публикации. Отказ движков →
        # honest verdict, не исключение до пользователя (F-1).
        plan_results = ""
        if retrieval is not None:
            plan_results = str(getattr(retrieval, "search_text", "") or "")
        results_parts: list[str] = []
        search_reason = None
        if plan_results.strip():
            results = plan_results
            trace.add("temporal_search", "success", reason="unified_retrieval")
            tf.stage_event("temporal_search", "success",
                           reason_code="unified_retrieval",
                           chat_id=env.chat_id)
        else:
            queries = tf.search_queries_for(parts, env)
            from services.search_aggregator import content_terms
            for q in queries:
                try:
                    if hasattr(self.aggregator, "search_relevant"):
                        # FC-EVIDQ: нерелевантная выдача уровня → следующий
                        # провайдер каскада (внутри агрегатора)
                        chunk = await self.aggregator.search_relevant(
                            q, 2500, relevance_terms=content_terms(q,
                                                                   limit=10))
                    else:
                        chunk = await self.aggregator.search(q, 2500)
                except AllSearchEnginesFailedException:
                    search_reason = "temporal_insufficient_evidence"
                    continue
                except Exception:
                    search_reason = "temporal_insufficient_evidence"
                    continue
                if chunk and str(chunk).strip():
                    results_parts.append(str(chunk))
            results = "\n\n".join(results_parts)
            trace.add("temporal_search",
                      "success" if results else "skipped",
                      reason=search_reason)
            tf.stage_event("temporal_search",
                           "success" if results else "skipped",
                           reason_code=search_reason, chat_id=env.chat_id)

        # evidence_validate (D9): evidence-контракт из выдачи (стабильные
        # ID ev-N); FC-UNIFY: структурные строки единого контура (включая
        # primary-выдержки SafeFetcher с уже извлечёнными датами) вместо
        # повторного разбора текста. D10/§18G.1: попытка fetch/parse даты
        # публикации оставшихся web-evidence (bounded, fail-open) — parse
        # failure не прерывает pipeline и не подставляет now().
        # Пусто → insufficient_evidence (no-false-acceptance).
        retrieval_refs = ()
        if retrieval is not None:
            retrieval_refs = tuple(
                getattr(getattr(retrieval, "evidence_map", None),
                        "refs", ()) or ())
        if retrieval_refs:
            evidence = tf.evidence_rows_from_refs(
                retrieval_refs, fallback_results=results,
                max_rows=_temporal_max_evidence())
        else:
            evidence = tf.evidence_rows_from_results(
                results, max_rows=_temporal_max_evidence())
        date_summary = None
        if evidence and tf.evidence_date_fetch_enabled():
            try:
                evidence, date_summary = await tf.enrich_evidence_dates(
                    evidence)
            except Exception:
                logger.warning("[factcheck] evidence date enrich failed — "
                               "honest unknown", exc_info=True)
                date_summary = None
        trace.add("evidence_validate", "success" if evidence else "skipped",
                  reason=None if evidence else "temporal_insufficient_evidence")
        tf.stage_event("evidence_validate",
                       "success" if evidence else "skipped",
                       reason_code=None if evidence
                       else "temporal_insufficient_evidence",
                       chat_id=env.chat_id)

        correlation_id = usage_events.new_correlation_id()
        fallback_used = False
        verdict_reason = search_reason
        # P0-FACTCHECK (§3.6): технический класс исхода retrieval. Раньше
        # бюджет/недоступность провайдеров/потеря обработки не читались и
        # любой пустой evidence давал «недостаточно доказательств».
        retrieval_state = classify_retrieval(retrieval) if not evidence \
            else RETRIEVAL_OK
        if retrieval_state in _RETRIEVAL_REASON:
            verdict_reason = _RETRIEVAL_REASON[retrieval_state]

        # verdict (D10/D11): data-only JSON-стадия; невалидный JSON →
        # fallback-попытка; обе мимо → честный degraded-вердикт с датами.
        # §18G.3: evidence_refs модели валидируются по current-run
        # allowlist стабильных ID (ev-N) — произвольный service text
        # evidence сам по себе не становится.
        user_payload = self._temporal_user_payload(env, parts, evidence,
                                                   chat_context)
        allowed_refs = ({str(r.get("evidence_id")) for r in evidence
                         if r.get("evidence_id")}
                        if evidence else None)
        # TH-5/CA-20-10 (no-false-acceptance): движки недоступны/пусто →
        # insufficient_evidence СЕРВЕРНО, verdict модели не проходит.
        # Причина при этом честная: сбой/бюджет/обработка ≠ «нет фактов».
        if not evidence:
            raw_payload = {"factual_verdict": "insufficient_evidence",
                           "temporal_status": "unknown",
                           "reason": verdict_reason
                           or "temporal_insufficient_evidence"}
        else:
            raw_payload = await self._temporal_verdict_json(
                tf.TEMPORAL_ANALYST_SYSTEM, user_payload, env,
                correlation_id, step="temporal_verdict")
            if raw_payload is None:
                fallback_used = True
                verdict_reason = "temporal_fallback_mode"
                raw_payload = await self._temporal_verdict_json(
                    tf._TEMPORAL_FALLBACK_SYSTEM, user_payload, env,
                    correlation_id, step="temporal_fallback")
            if raw_payload is None:
                fallback_used = True
                raw_payload = {}
        verdict = tf.verdict_from_payload(raw_payload, env,
                                          fallback_reason=verdict_reason,
                                          allowed_refs=allowed_refs)

        # validator (spec D11/TH-2, CoVe REUSE): bounded data-only
        # перепроверка evidence↔claim — ровно ОДИН вызов, только при
        # аналитик-вердикте ({} после обеих мимо-попыток валидировать
        # нечего). Согласие/мусор → вердикт стоит; disagree проходит
        # ТОЛЬКО через серверный guard (tf.apply_validator). Отказ/невалидный
        # JSON → СУЩЕСТВУЮЩИЙ fallback-путь с существующим reason-кодом
        # (честная деградация, не тихая). Стадия реестра не меняется:
        # исход фиксируется дополнительной записью "verdict" в трассе.
        validator_outcome = None
        if evidence and raw_payload:
            v_payload = await self._temporal_verdict_json(
                tf.TEMPORAL_VALIDATOR_SYSTEM,
                self._temporal_validator_payload(env, verdict, evidence),
                env, correlation_id, step="temporal_validator")
            if v_payload is not None:
                verdict, corrected = tf.apply_validator(verdict, v_payload,
                                                        env)
                validator_outcome = "corrected" if corrected else "validated"
            else:
                validator_outcome = "failed"
                if not fallback_used:
                    # Существующий fallback-путь (общий слот ≤1 попытки):
                    # валидация не удалась → строгий повтор аналитика;
                    # обе мимо → честный degraded-вердикт.
                    # REV-P1 (§18G.3): allowlist обязателен и здесь —
                    # fallback-промпт может вернуть refs, они фильтруются
                    # тем же current-run allowlist (ev-N), что и у аналитика.
                    fallback_used = True
                    verdict_reason = "temporal_fallback_mode"
                    retry = await self._temporal_verdict_json(
                        tf._TEMPORAL_FALLBACK_SYSTEM, user_payload, env,
                        correlation_id, step="temporal_fallback")
                    verdict = tf.verdict_from_payload(
                        retry or {}, env, fallback_reason=verdict_reason,
                        allowed_refs=allowed_refs)

        trace.add("verdict", "success",
                  reason=verdict.reason or verdict_reason)
        if validator_outcome:
            trace.add("verdict", validator_outcome,
                      reason="temporal_fallback_mode"
                      if validator_outcome == "failed" else None)
        # D10/§18G.4: временная недостаточность (даты оригинала неизвестны И
        # даты публикаций evidence не разпознаны) → bounded uncertainty,
        # НЕ forced certainty (вердикт не повышается и не понижается).
        if evidence and env.date_source == "unknown" and not any(
                r.get("date_parse_status") == "parsed" for r in evidence):
            uncertainty = dict(verdict.uncertainty or {})
            uncertainty.setdefault(
                "dates_unresolved",
                "дата публикации оригинала не определена — временная оценка "
                "ограничена")
            verdict = dataclasses.replace(verdict, uncertainty=uncertainty)
        # P0-FACTCHECK (§3.5): части есть даже без разбора модели — из
        # СЕРВЕРНОЙ декомпозиции, с вердиктом не выше insufficient и
        # привязкой evidence к части (в durable evidence раньше было
        # claim_part=null у всех строк). Положительный вердикт части без
        # доказательства запрещён.
        if not verdict.parts:
            server_parts = _server_parts(env, evidence)
            if server_parts:
                verdict = dataclasses.replace(verdict, parts=server_parts)
        # P0-FACTCHECK (§3.6): технический класс пишется в оговорки, чтобы
        # пользователь и вербализатор не читали «сбой» как «фактов нет».
        caveat = _RETRIEVAL_CAVEAT.get(retrieval_state)
        if caveat:
            uncertainty = dict(verdict.uncertainty or {})
            uncertainty["retrieval_state"] = caveat
            verdict = dataclasses.replace(verdict, uncertainty=uncertainty)
        tf.stage_event("verdict", "success", reason_code=verdict.reason,
                       chat_id=env.chat_id)

        # verbalize (D11/CA-20-13): стилизация ПОСЛЕ вердикта; даты/
        # оговорки — обязательная часть payload каждой стадии; все ветки
        # (включая fallback) получают один envelope.
        verdict_text = await self._temporal_verbalize(
            env, verdict, fallback_used, correlation_id,
            retrieval_state=retrieval_state)
        trace.add("verbalize", "success" if verdict_text else "skipped",
                  reason=None if verdict_text else "temporal_fallback_mode")

        if not verdict_text:
            verdict_text = self._temporal_fallback_text(
                env, verdict, retrieval_state=retrieval_state)

        return tf.TemporalRunResult(
            envelope=env, verdict=verdict, verdict_text=verdict_text,
            evidence_rows=evidence, stage_trace=trace.as_list(),
            fallback_used=fallback_used, cache_hit=False)

    def _temporal_user_payload(
        self, env: tf.TemporalClaimEnvelope, parts, evidence,
        chat_context: str | None,
    ) -> str:
        """User-content вердиктной стадии: <claim> + <temporal_context>
        (даты/периоды/режим — серверные метаданные, D2) + <evidence> +
        <chat_context> (НЕ доказательства — подпись как в legacy)."""
        sections = [
            "<claim>" + escape_xml_text(env.claim_text) + "</claim>",
            "<temporal_context>" + escape_xml_text(json.dumps({
                "date_source": env.date_source,
                "original_published_at": env.original_published_at,
                "repost_received_at": env.repost_received_at,
                "claim_period": [env.claim_period_from,
                                 env.claim_period_to,
                                 env.claim_period_precision],
                "date_uncertainty": env.date_uncertainty,
                "assessment_mode": env.requested_mode,
                "analysis_as_of": env.analysis_as_of,
            }, ensure_ascii=False)) + "</temporal_context>",
        ]
        if parts:
            sections.append("<claim_parts>" + escape_xml_text(json.dumps(
                [{"part_id": p.part_id, "text": p.text,
                  "period": [p.period_from, p.period_to]}
                 for p in parts], ensure_ascii=False)) + "</claim_parts>")
        if evidence:
            # §18G.3/§18G.5: каждая выдержка — со стабильным ID и датой
            # публикации (unknown — честно); model evidence_refs ссылаются
            # только на эти ID (allowlist проверяется сервером).
            sections.append("<evidence>" + escape_xml_text("\n\n".join(
                "[%s] published: %s%s\n%s" % (
                    r.get("evidence_id") or "?",
                    _fmt_evidence_date(r.get("published_at")),
                    (" (%s)" % r["published_at_source"])
                    if r.get("published_at_source") else "",
                    r["support"])
                for r in evidence)) + "</evidence>")
        if chat_context:
            sections.append(chat_context)
        return "\n\n".join(sections)

    def _temporal_validator_payload(
        self, env: tf.TemporalClaimEnvelope, verdict: tf.TemporalVerdict,
        evidence,
    ) -> str:
        """User-content validator-стадии (D11/TH-2, data-only): утверждение +
        серверный контекст + черновой вердикт + выдержки. Untrusted-evidence
        остаётся ДАННЫМИ: экранирование то же, что у аналитика, контейнер
        <search_results> не разрывается содержимым сниппетов."""
        sections = [
            "<claim>" + escape_xml_text(env.claim_text) + "</claim>",
            "<temporal_context>" + escape_xml_text(json.dumps({
                "date_source": env.date_source,
                "original_published_at": env.original_published_at,
                "claim_period": [env.claim_period_from,
                                 env.claim_period_to,
                                 env.claim_period_precision],
                "assessment_mode": env.requested_mode,
            }, ensure_ascii=False)) + "</temporal_context>",
            "<verdict_draft>" + escape_xml_text(json.dumps({
                "factual_verdict": verdict.factual_verdict,
                "temporal_status": verdict.temporal_status,
                "evaluated_period": verdict.evaluated_period,
                "assessment_mode": verdict.assessment_mode,
            }, ensure_ascii=False)) + "</verdict_draft>",
            "<evidence>" + escape_xml_text("\n\n".join(
                "[%s] published: %s\n%s" % (
                    r.get("evidence_id") or "?",
                    _fmt_evidence_date(r.get("published_at")),
                    r["support"])
                for r in evidence)) + "</evidence>",
        ]
        return "\n\n".join(sections)

    async def _temporal_verdict_json(
        self, system: str, user_payload: str, env,
        correlation_id: str | None, *, step: str,
    ) -> dict | None:
        """Один data-only LLM-вызов вердиктной стадии → dict|None."""
        from services.system2_handoff import parse_json_object
        try:
            raw = await self.llm.generate(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user_payload}],
                module="factcheck", step=step,
                correlation_id=correlation_id)
        except Exception:
            return None
        payload = parse_json_object(str(raw))
        return payload if isinstance(payload, dict) else None

    async def _temporal_verbalize(
        self, env: tf.TemporalClaimEnvelope, verdict: tf.TemporalVerdict,
        fallback_used: bool, correlation_id: str | None,
        *, retrieval_state: str | None = None,
    ) -> str:
        """Вербализатор (REUSE существующего контракта фактчека): verdict →
        текст с СОХРАНЕНИЕМ существенных дат/оговорок (SC-R3c). Любой сбой
        → '' (вызывающий берёт детерминированный fallback-текст)."""
        max_symbols = hot.get("limits.factcheck_max_symbols",
                              settings.FACTCHECK_MAX_SYMBOLS)
        try:
            from services.factcheck_prompts import (
                FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
            )
            base = resolve_prompt(
                "prompts.factcheck_verbalizer_system_prompt",
                FACTCHECK_VERBALIZER_SYSTEM_PROMPT).replace(
                "{max_symbols}", str(max_symbols))
        except Exception:
            base = ("Перескажи проверку фактов кратко и по-человечески. "
                    "СОХРАНИ существенные даты и оговорки; не выдумывай "
                    "дат и фактов; недостаток данных честно называй.")
        # CFG-06 W5 (06A.5/06B, утечка «период проверки (unknown)»):
        # style_note с техполями удалён; вербализатор получает
        # человекочитаемый дайджест вердикта, сырые служебные поля
        # (enum-статусы, precision, as_of, тех-ключи uncertainty) — мимо
        # payload («unknown» → человеческие слова). Раскладка остального
        # текста (обёртка сообщений, порядок человекочитаемых ключей,
        # fallback_note) сохранена — байт-защита тестом W5.
        payload = {
            "verdict": _human_factual_verdict(verdict.factual_verdict),
            "freshness": _human_temporal_status(verdict.temporal_status),
        }
        period_phrase = _human_evaluated_period(verdict.evaluated_period)
        if period_phrase:
            payload["period"] = period_phrase
        caveats = [str(v).strip()
                   for v in (verdict.uncertainty or {}).values()
                   if str(v or "").strip()]
        if caveats:
            payload["caveats"] = caveats
        payload["parts"] = list(verdict.parts)
        payload["claim"] = env.claim_text
        situation = _RETRIEVAL_SITUATION.get(str(retrieval_state or ""))
        if situation:
            # §3.6: вербализатор не должен называть сбой «отсутствием фактов».
            payload["situation"] = situation
        if fallback_used:
            payload["fallback_note"] = (
                "структурированный анализ не удался — не утверждай больше, "
                "чем следует из данных")
        # UNIFIED-CORE (P0, владелец 20.10.2026): временной вербализатор —
        # пользовательская речь → тот же штатный шов, что Stage-2/одиночный
        # путь: Core + Expression владельца ПОСЛЕДНИМ блоком system (характер
        # по настройкам владельца; блок пуст → сборка байт-в-байт прежняя).
        owner_block = await speech_owner_block(getattr(env, "chat_id", None))
        system = f"{base}\n\n{owner_block}" if owner_block else base
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "ВЕРДИКТ (JSON):\n" + json.dumps(
                payload, ensure_ascii=False)},
        ]

        async def _generate(msgs):
            return await self.llm.generate(
                msgs, module="factcheck", step="temporal_verbalize",
                correlation_id=correlation_id)

        try:
            text, _stats = await verbalize_validated(
                _generate, messages, max_retries=1,
                dynamic_rules=anticliche_cache.get_rules() or None,
                metatext_reason=_metatext_retry_reason())
        except Exception:
            return ""
        try:
            out = cleanup_llm_text(strip_reasoning_tags(str(text)))
        except Exception:
            return ""
        return out.strip()

    @staticmethod
    def _temporal_fallback_text(env: tf.TemporalClaimEnvelope,
                                verdict: tf.TemporalVerdict,
                                *, retrieval_state: str | None = None) -> str:
        """Детерминированный честный текст (все ветки получают даты, D11):
        краткая дата/неопределённость без технической схемы (D15).

        P0-FACTCHECK (§3.6): технический сбой не маскируется под «мало
        данных» — фраза прямо называет причину (бюджет/недоступность/
        непригодные выдержки)."""
        import datetime as _dt

        def _fmt(ts):
            if not ts:
                return None
            try:
                return _dt.datetime.fromtimestamp(
                    int(ts), _dt.timezone.utc).strftime("%d.%m.%Y")
            except (ValueError, OverflowError, OSError):
                return None

        openers = {
            RETRIEVAL_BUDGET:
                "Проверку не удалось довести до конца: истёк лимит времени "
                "на поиск. Это не значит, что утверждение опровергнуто.",
            RETRIEVAL_SEARCH_FAILED:
                "Проверку не удалось выполнить: поисковые сервисы не "
                "ответили. Это технический сбой, а не отсутствие фактов.",
            RETRIEVAL_PROCESSING_FAILED:
                "Материалы найти удалось, но пригодных для проверки "
                "выдержек из них получить не вышло.",
        }
        pieces = [openers.get(str(retrieval_state or ""),
                              "Недостаточно данных для полной проверки "
                              "утверждения.")]
        orig = _fmt(env.original_published_at)
        if env.date_source in ("telegram_origin", "telegram_message") and orig:
            kind = "оригинала" if env.date_source == "telegram_origin" \
                else "сообщения"
            pieces.append(f"Дата {kind}: {orig}.")
        period = verdict.evaluated_period or {}
        p_from, p_to = _fmt(period.get("from")), _fmt(period.get("to"))
        if p_from and p_to and p_from != p_to:
            pieces.append(f"Проверялось на период {p_from}—{p_to}.")
        elif p_from:
            pieces.append(f"Проверялось на период {p_from}.")
        if verdict.temporal_status == "old_but_valid":
            pieces.append("Возраст публикации сам по себе не делает "
                          "утверждение ложным.")
        return " ".join(pieces)
