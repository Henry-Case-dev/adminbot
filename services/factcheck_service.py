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
import re
import time

from config.settings import settings
from services import hot_config as hot
# UR-C-CLOCK: единственный источник времени чата (оценка фактчека).
from services import chat_clock as _cclock
from services.factcheck_prompts import (
    FACTCHECK_ANALYST_SYSTEM_PROMPT,
    FACTCHECK_SYSTEM_PROMPT,
    FACTCHECK_VERBALIZER_SYSTEM_PROMPT,
    PREV_FACTCHECK_VERBALIZER_VOICE01,
    CRITIQUE_POLICY_FORBIDDEN,
    build_critique_section_block,
    critique_policy_for_findings,
    critique_policy_for_verdict,
    resolve_critique_directive,
)
from services.grounding_validator import (
    collect_allowed_anchors,
    strip_phantom_tags,
)
from services.llm_client import LLMBadResponseError, LLMClient, LLMError
from services.media_group_buffer import (
    get_media_group_caption,
    get_media_group_ids,
)
from services import anticliche_cache
from services import mca_gates
from services import usage_events
from services.prompt_composer import compose_speech_system
from services.negative_constraints import (
    channel_enabled_rules,
    verbalize_validated,
)
from services.prompt_style_blocks import resolve_prompt
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
# UR-26.4: payload-наблюдаемость стадий фактчека (stage1/stage2/temporal).
from services import turn_payload_events as _tpe

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# EVOL §5 (W5) — настройка «Критический разнос» (service-level)
# ═══════════════════════════════════════════════════════════════════════════

#: Горячий ключ настройки раздела «Критический разнос» публичного фактчека.
#: Это НЕ дубль мастер-тумблера модуля (``flags.factcheck_enabled``):
#: раздел живёт только внутри уже включённого фактчека и по умолчанию ON.
#: Наследование — существующий механизм настроек: chat-override → global
#: (hot/PG) → заводской дефолт. Ключ каталога/UI заводит отдельный лейн
#: настроек; рантайм читает его уже сейчас (без UI-зависимости).
CRITIQUE_SECTION_KEY = "flags.factcheck_critique_section_enabled"


def critique_section_default() -> bool:
    """Заводской дефолт настройки (ON; §5.2 «default ON внутри фактчека»)."""
    return bool(getattr(settings, "FACTCHECK_CRITIQUE_SECTION_ENABLED", True))


async def resolve_critique_section(chat_id: int | None) -> tuple[bool, str]:
    """``(включён, источник)`` настройки раздела «Критический разнос».

    ``source`` — ``chat`` (override этого чата) | ``global`` (общий слой) |
    ``factory`` (заводской дефолт): тот же словарь, что у остальных
    per-chat параметров (CFG-01 §01.1). ``chat_id=None`` → глобальный слой.
    Никогда не бросает: сбой резолва → заводской дефолт (fail-open).
    """
    default = critique_section_default()
    if chat_id is None:
        try:
            return bool(hot.get(CRITIQUE_SECTION_KEY, default)), "global"
        except Exception:      # pragma: no cover — hot-слой не роняет ответ
            return default, "factory"
    try:
        from services.chat_params import get_chat_param_sourced
        value, source = await get_chat_param_sourced(
            int(chat_id), CRITIQUE_SECTION_KEY, default)
        return bool(value), str(source or "factory")
    except Exception:          # pragma: no cover — PG down → глобальный слой
        try:
            return bool(hot.get(CRITIQUE_SECTION_KEY, default)), "global"
        except Exception:
            return default, "factory"


async def _critique_section_block(chat_id: int | None, policy: str) -> str:
    """Блок инструкции раздела для публичной Writer-фазы.

    Настройка OFF или политика ``forbidden`` → ``""`` (раздела нет; факты,
    источники и оговорки остаются). Директива — активная редакция из единого
    EVOL-реестра (``resolve_critique_directive``), не вторая копия текста.
    """
    if str(policy or "") == CRITIQUE_POLICY_FORBIDDEN:
        return ""
    enabled, _source = await resolve_critique_section(chat_id)
    if not enabled:
        return ""
    return build_critique_section_block(policy,
                                        directive=resolve_critique_directive())


async def _compose_genre_speech(chat_id: int | None, *, writer: str,
                                base_prompt: str):
    """ЕДИНАЯ сборка речевого system публичного жанра фактчека.

    ASAP-FC-VOICE-01 / A (§3 контракта): все точки сборки фактчека
    (одиночный путь, двухвызовный Stage-2, временной вербализатор и короткая
    персона-реплика) получают слои владельца из ОДНОГО владельца сборки —
    ``prompt_composer.compose_speech_system``. Ручная склейка
    ``system + "\\n\\n" + speech_owner_block`` удалена: Core/Expression
    попадают в payload ровно один раз конструктивно, а причина пропуска
    каждого слоя видна в манифесте.

    Профиль/канал: ``speech_plain`` + ``plain`` (фактчек публикуется текстом
    с экранированием), режимный блок НЕ подключается — он задавал фактчеку
    «как у Direct» длину и запрет структуры, что противоречит канону подачи.
    ``include_speech_base`` — явное сохранение прежнего слоя ``<Speech_Base>``
    (до правки его добавлял ``speech_owner_block``).

    Никогда не бросает: сбой сборки → готовый жанровый канон без слоёв
    владельца (``compose_speech_system`` возвращает базу и ``None``).
    """
    system, _manifest = await compose_speech_system(
        chat_id=chat_id, writer=writer, base_prompt=base_prompt,
        base_source="code", profile="speech_plain", channel="plain",
        html_safe=False, include_mode_block=False,
        identity_text="", identity_skipped="duplicate_of_persona",
        plan_skip="no_l1_plan_in_genre", humor_skip="genre_argued_analysis",
        include_speech_base=True)
    return system


def _with_critique_block(base: str, block: str) -> str:
    """Дописать блок раздела к жанровому канону (пустой блок → байт-паритет)."""
    if not block:
        return base
    return f"{base}\n\n{block}"


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
    """mca-20: потолок evidence-строк прогона (env-лимит gates, D16).

    S15-FC-EVIDENCE: на unified/envelope-пути этот «потолок числа строк» больше
    НЕ ограничивает доставку evidence — размер порции считает единый capacity
    resolver (см. `_evidence_delivery`). Helper сохранён для прежних вызовов и
    как аварийный degrade, когда ёмкость маршрута неизвестна.
    """
    try:
        from services import mca_gates
        return mca_gates.temporal_max_evidence_per_run()
    except Exception:      # pragma: no cover
        return 20


# ── S15-FC-EVIDENCE: доставка evidence по фактической ёмкости маршрута ──────
# Owner §7.1–7.5 (14.11.2026): 100 000 символов — размер ПОРЦИИ, а не потолок
# исследования; 20 строк/1200 символов — прежние скрытые caps, которые нельзя
# сохранять как универсальный бюджет. Размер доставки считает ЕДИНЫЙ capacity
# resolver родительского эпика (`services.model_capacity`, S4): фактическая
# модель и endpoint маршрута, proven limit → кэш каталога → unknown 1M.
# Отдельного окна 16384 в фактчеке нет. Если ёмкость маршрута неизвестна,
# доставка честно деградирует к прежней порции (gates), а не «угадывает» окно.

#: Сколько символов одной выдержки достаточно, чтобы включить её усечённой,
#: когда весь support не помещается в остаток ёмкости. Это НЕ бюджет доставки:
#: порция целиком определяется ёмкостью; константа лишь не даёт вставлять
#: обрывок в 3 символа. Остаток документа сохраняется указателем (URL+ev-id).
_EVIDENCE_MIN_TRUNCATED_CHARS = 200


@dataclasses.dataclass(frozen=True)
class RouteCapacity:
    """Ёмкость ОДНОГО фактического маршрута (модель+endpoint) для evidence.

    ``input_chars`` — сколько символов evidence допускает окно этой модели под
    merge-долю, которую родительский контракт отводит одному tool-результату.
    ``output_reserve`` — токены вывода, посчитанные ОТДЕЛЬНО (D2): они не
    превращаются в evidence-бюджет и не занижают полезный контекст. ``None``
    в ``input_chars`` означает «ёмкость неизвестна» (аварийный degrade), а не
    «нулевой бюджет».
    """

    channel: str
    model: str
    base_url: str
    window_tokens: int
    window_source: str
    input_chars: int | None
    output_reserve: int

    def as_meta(self) -> dict:
        """R17-safe снимок (без ключей/URL-путей; только host-free имя модели)."""
        return {
            "channel": self.channel,
            "model": self.model[:64],
            "window_tokens": int(self.window_tokens or 0),
            "window_source": str(self.window_source or ""),
            "evidence_budget_chars": self.input_chars,
            "output_reserve_tokens": int(self.output_reserve or 0),
        }


@dataclasses.dataclass(frozen=True)
class EvidenceDelivery:
    """Результат упаковки evidence: доставленные строки + честная граница."""

    rows: tuple[dict, ...]
    route: RouteCapacity | None
    budget_chars: int | None
    total_rows: int
    total_chars: int
    delivered_chars: int
    truncated_ids: tuple[str, ...] = ()
    remainder_ids: tuple[str, ...] = ()
    remainder_urls: tuple[tuple[str, str], ...] = ()
    #: Полные (неусечённые) строки до упаковки — для recompose под ёмкость
    #: фактически вызванного fallback-маршрута (owner §7.4). Не попадают в
    #: payload сами по себе.
    all_rows: tuple[dict, ...] = ()

    @property
    def limited(self) -> bool:
        return bool(self.truncated_ids or self.remainder_ids)

    def as_meta(self) -> dict:
        """R17-safe метаданные доставки (числа/enum/ID; без текстов чата)."""
        meta = {
            "total_rows": int(self.total_rows),
            "delivered_rows": len(self.rows),
            "total_chars": int(self.total_chars),
            "delivered_chars": int(self.delivered_chars),
            "budget_chars": self.budget_chars,
            "limited": self.limited,
            "truncated": len(self.truncated_ids),
            "remainder": len(self.remainder_ids),
        }
        if self.route is not None:
            meta["route"] = self.route.as_meta()
        return meta

    def payload_block(self) -> str:
        """`<evidence_delivery>` — машинная граница доставки для analyst/validator.

        Появляется ТОЛЬКО когда evidence реально ограничен ёмкостью маршрута:
        аналитик обязан видеть, что материалов больше, чем доставлено, и не
        выводить «доказательств нет» из искусственного предела. Текст
        источников здесь не дублируется — только ID/URL остатка."""
        if not self.limited:
            return ""
        payload = {
            "delivered": len(self.rows),
            "total": int(self.total_rows),
            "delivered_chars": int(self.delivered_chars),
            "total_chars": int(self.total_chars),
            "budget_chars": self.budget_chars,
            "truncated_ids": list(self.truncated_ids),
            "remainder_ids": [rid for rid, _url in self.remainder_urls],
            "remainder_urls": [url for _rid, url in self.remainder_urls
                               if url],
        }
        return ("<evidence_delivery>" + escape_xml_text(
            json.dumps(payload, ensure_ascii=False)) + "</evidence_delivery>")


def _client_route(llm, kind: str) -> tuple[str, str]:
    """Фактический маршрут клиента: ``(model, base_url)`` для primary/fallback.

    ``LLMClient.generate`` отправляет именно `_chat_model`/`_base_url`, а при
    fallback — `_fallback_model`/`_fallback_base_url`; поэтому ёмкость читается
    с ЭТИХ полей, а не с «главной модели» настроек. Тест-двойники без полей →
    hot/settings-значения (тот же порядок, что у клиента при инициализации)."""
    if kind == "fallback":
        model = (getattr(llm, "_fallback_model", "")
                 or hot.get("models.llm_fallback_model",
                            getattr(settings, "LLM_FALLBACK_MODEL", "")))
        base = (getattr(llm, "_fallback_base_url", "")
                or hot.get("models.llm_fallback_base_url",
                           getattr(settings, "LLM_FALLBACK_BASE_URL", "")))
    else:
        model = (getattr(llm, "_chat_model", "")
                 or hot.get("models.llm_model_name",
                            getattr(settings, "LLM_MODEL_NAME", "")))
        base = (getattr(llm, "_base_url", "")
                or hot.get("models.llm_base_url",
                           getattr(settings, "LLM_BASE_URL", "")))
    return str(model or "").strip(), str(base or "").strip()


def _route_capacity(llm, kind: str = "primary") -> RouteCapacity | None:
    """Ёмкость фактического маршрута через ЕДИНЫЙ resolver (S4), никогда не бросает.

    Окно и допустимый output считаются ОТДЕЛЬНО: окно → evidence-бюджет,
    `output_reserve_tokens` → резерв вывода (в бюджет evidence не входит).
    Модель без подтверждённого окна получает planning-оценку 1M от resolver'а
    (`unknown_fallback`), а не 16384."""
    try:
        from services import model_capacity as mc
        model, base = _client_route(llm, kind)
        window, source = mc.resolve_evidence_window_tokens(model, base)
        window = int(window or 0)
        if window <= 0:
            return RouteCapacity(kind, model, base, 0, str(source or ""),
                                 None, 0)
        budget = int(mc.evidence_window_for_tokens(window))
        reserve = int(mc.output_reserve_tokens(window))
        return RouteCapacity(kind, model, base, window, str(source or ""),
                             max(0, budget), reserve)
    except Exception:      # pragma: no cover — capacity не рвёт фактчек
        logger.warning("[factcheck] capacity resolve failed — legacy portion",
                       exc_info=True)
        return None


def _accepts_kwarg(fn, name: str) -> bool:
    """Принимает ли callable kwarg ``name`` (тест-двойники/старые клиенты).

    Нужен, чтобы S15-adept ``fallback_payload_adapter`` не ломал существующие
    подмены LLM: отсутствие параметра → прежний вызов без него."""
    try:
        import inspect
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):      # pragma: no cover — C-объекты
        return True
    if name in params:
        return True
    return any(p.kind == inspect.Parameter.VAR_KEYWORD
               for p in params.values())


def _evidence_opening_index(retrieval) -> dict[str, bool]:
    """``evidence_id → opened`` из claim coverage (FC-03.2): открывалась ли
    страница источника в этом прогоне. Snippet без открытия — не то же
    доказательство, что прочитанный документ; аналитик видит provenance."""
    opened: dict[str, bool] = {}
    for claim in tuple(getattr(retrieval, "claims", ()) or ()):
        for item in tuple(getattr(claim, "evidence", ()) or ()):
            eid = str(getattr(item, "evidence_id", "") or "")
            if not eid:
                continue
            opened[eid] = bool(opened.get(eid)) or bool(
                getattr(item, "opened", False))
    return opened


def _pack_evidence(rows, *, budget_chars: int | None,
                   route: RouteCapacity | None = None) -> EvidenceDelivery:
    """Упаковать evidence-строки в ёмкость маршрута БЕЗ скрытых caps.

    ``budget_chars=None`` — ёмкость неизвестна: отдаём строки как есть
    (аварийная деградация к прежней порции вызывающего; не «нулевой» бюджет).
    Порядок строк не меняется (он уже отражает силу привязки к claim'ам).
    Строка, не помещающаяся целиком, включается усечённой (>= минимума) с
    сохранением остатка указателем; всё, что после неё, — честно в remainder.
    """
    rows = tuple(rows or ())
    total_chars = sum(len(str(r.get("support") or "")) for r in rows)
    if budget_chars is None:
        return EvidenceDelivery(
            rows=rows, route=route, budget_chars=None,
            total_rows=len(rows), total_chars=total_chars,
            delivered_chars=total_chars, all_rows=rows)
    budget = max(0, int(budget_chars))
    delivered: list[dict] = []
    used = 0
    truncated: list[str] = []
    remainder: list[tuple[str, str]] = []
    cutting = False
    for row in rows:
        support = str(row.get("support") or "")
        eid = str(row.get("evidence_id") or "")
        url = str(row.get("url") or "")
        if not cutting:
            # overhead — заголовок строки ([ev-N] claim= published: …)
            cost = len(support) + 64
            if used + cost <= budget:
                delivered.append(row)
                used += cost
                continue
            room = budget - used - 64
            if room >= _EVIDENCE_MIN_TRUNCATED_CHARS:
                delivered.append({**row, "support": support[:room],
                                  "support_truncated": True,
                                  "support_total_chars": len(support)})
                used = budget
                truncated.append(eid)
            cutting = True
        if cutting:
            remainder.append((eid, url))
    if cutting and not remainder:
        # последняя строка была усечена — её остаток тоже должен быть виден
        remainder = [(str(delivered[-1].get("evidence_id") or ""),
                      str(delivered[-1].get("url") or ""))] \
            if delivered and delivered[-1].get("support_truncated") else []
    return EvidenceDelivery(
        rows=tuple(delivered), route=route, budget_chars=budget,
        total_rows=len(rows), total_chars=total_chars,
        delivered_chars=sum(len(str(r.get("support") or ""))
                            for r in delivered),
        truncated_ids=tuple(t for t in truncated if t),
        remainder_ids=tuple(rid for rid, _u in remainder if rid),
        remainder_urls=tuple(remainder), all_rows=rows)


def _evidence_delivery(retrieval, *, route: RouteCapacity | None,
                       fallback_results: str | None = None,
                       refs_only: bool = False) -> EvidenceDelivery:
    """Собрать evidence-строки unified-контура и доставить их по ёмкости.

    Строки строятся из СТРУКТУРНЫХ refs (FC-UNIFY: evidence только из
    проверяемых ссылок), затем:
    * support восстанавливается до полного текста ref — `temporal_factcheck`
      исторически резал его до 1200 символов, что при увеличенном
      `limits.factcheck_excerpt_chars` молча уничтожало выдержку (owner §7.3);
    * строка получает provenance (`opened`, `source_kind`, `strength`) —
      заголовок/сниппет не выдаются за прочитанный документ (owner §8.2);
    * упаковка идёт по ёмкости ФАКТИЧЕСКОГО маршрута, без потолка 20 строк.
    """
    from services import temporal_factcheck as tf
    refs = tuple(getattr(getattr(retrieval, "evidence_map", None), "refs", ())
                 or ())
    budget = route.input_chars if route is not None else None
    max_rows = len(refs) if refs else _temporal_max_evidence()
    if not refs and refs_only:
        # F2 (review r1): веб-прогон unified-контура даёт evidence ТОЛЬКО из
        # структурных refs; повторный разбор `search_text` не возвращается.
        return _pack_evidence((), budget_chars=budget, route=route)
    if not refs:
        rows = tf.evidence_rows_from_results(
            fallback_results or "", max_rows=max_rows)
        return _pack_evidence(rows, budget_chars=budget, route=route)
    rows = tf.evidence_rows_from_refs(
        refs, fallback_results=fallback_results, max_rows=max_rows)
    full_support = {str(getattr(ref, "evidence_id", "")):
                    str(getattr(ref, "support", "") or "") for ref in refs}
    opened = _evidence_opening_index(retrieval)
    strength = {}
    for claim in tuple(getattr(retrieval, "claims", ()) or ()):
        for item in tuple(getattr(claim, "evidence", ()) or ()):
            eid = str(getattr(item, "evidence_id", "") or "")
            if eid and getattr(item, "strength", ""):
                strength[eid] = str(item.strength)
    enriched = []
    for row in rows:
        eid = str(row.get("evidence_id") or "")
        support = full_support.get(eid) or str(row.get("support") or "")
        enriched.append({
            **row,
            "support": support,
            "opened": bool(opened.get(eid, False)),
            "strength": strength.get(eid, ""),
        })
    return _pack_evidence(enriched, budget_chars=budget, route=route)


def _evidence_context_note(retrieval, evidence) -> str:
    """`<analysis_context>`-факт о границе поиска для analyst'а (owner §8.2).

    Если поиск остановлен бюджетом/deadline ДО рассмотрения доступных
    источников, вывод «доказательств не существует» запрещён — даже когда
    evidence непустой. Это тот же существующий контракт `_RETRIEVAL_CAVEAT`,
    но он обязан дойти до аналитика ДО вердикта, а не только в uncertainty."""
    if retrieval is None or not evidence:
        return ""
    exhausted = bool(getattr(retrieval, "budget_exhausted", False))
    skipped = int(getattr(retrieval, "fetch_skipped_budget", 0) or 0) \
        + int(getattr(retrieval, "fetch_skipped_deadline", 0) or 0)
    if not exhausted and skipped <= 0:
        return ""
    return (
        "<analysis_context>\n"
        "Поиск остановлен ограничением бюджета/времени: часть доступных "
        "релевантных источников не проверена"
        + (f" (не открыто кандидатов: {skipped})" if skipped > 0 else "")
        + ". Это ограничение ПОИСКА, а не доказательство отсутствия фактов; "
          "не делай вывод «доказательств нет» и не выдавай первое совпадение "
          "за окончательный вердикт.\n"
          "</analysis_context>")


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
    """Что дали изображения публикации (для анализа и честности)."""
    text_suffix: str = ""             # блок для claim/envelope (пусто — нет)
    image_present: bool = False
    image_analyzed: bool = False
    image_not_analyzed: bool = False
    ocr_chars: int = 0
    caption: str = ""
    # P0-FACTCHECK media (owner 25.10.2026 §3/§4/§5/§7): альбом — несколько
    # изображений одной публикации; недоступность — технический факт, а не
    # «нет содержимого».
    vision_failed: bool = False       # чтение Vision-контура не удалось
    image_count: int = 0              # элементов с реально найденными активами
    pending_count: int = 0            # из них распознавание ещё не готово
    visual_descriptions: tuple[str, ...] = ()
    # Review fix (25.10.2026): описания — контекст, не тезис. В ``text_suffix``
    # они попадают только вместе с OCR; иначе идут отдельным блоком контекста.
    description_suffix: str = ""
    truncated: bool = False           # материал изображения обрезан по лимиту
    # ASAP-VISION-SYNC-01 §4: терминальный отказ распознавания — содержимое
    # картинки НЕ проверено (отличается от «файл недоступен» и от «нет
    # текста»); причина нормализована, а не пустая.
    image_unchecked: bool = False
    unchecked_reason: str = ""

    def notice(self) -> str:
        """Человеческое ограничение (никогда не выдумывает распознавание)."""
        parts: list[str] = []
        if self.image_unchecked:
            reason = ""
            try:
                from services import media_readiness
                reason = media_readiness.reason_text(self.unchecked_reason)
            except Exception:
                reason = self.unchecked_reason or "технический сбой"
            if self.image_count:
                parts.append("Часть изображений публикации распознать не "
                             f"удалось ({reason}) — их содержимое НЕ проверено, "
                             "проверено то, что доступно.")
            else:
                parts.append("Изображение распознать не удалось "
                             f"({reason}) — содержимое картинки НЕ проверено, "
                             "проверен только текст публикации.")
        if self.vision_failed:
            if self.image_count:
                parts.append("Не все изображения публикации удалось прочитать "
                             "(технический сбой) — проверено то, что доступно.")
            else:
                parts.append("Изображение не удалось прочитать (технический "
                             "сбой) — проверен только текст публикации.")
        if self.truncated:
            parts.append("Текст части изображений обрезан по лимиту — "
                         "проверено то, что вошло в материал.")
        if self.image_not_analyzed:
            if self.pending_count and self.pending_count < self.image_count:
                parts.append("Часть изображений публикации ещё не распознана — "
                             "учтено то, что уже прочитано.")
            else:
                parts.append("На изображении мог быть текст, но распознавание "
                             "ещё не готово — проверен только текст публикации.")
        return " ".join(parts)


_IMAGE_MEDIA_TYPES = frozenset({"photo", "sticker"})
_MAX_ALBUM_ELEMENTS = 10          # Telegram: media group ≤ 10 элементов


def _row_value(row, key):
    """Значение колонки из ``aiosqlite.Row``/dict/тестового двойника."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _row_is_image(row) -> bool:
    """Строка ``smart_messages`` — изображение для существующего Vision."""
    return str(_row_value(row, "media_type") or "") in _IMAGE_MEDIA_TYPES


def _message_image_hint(message) -> bool:
    """Есть ли в TG-сообщении изображение, пригодное Vision-контуру.

    Проверяются ТОЛЬКО реальные aiogram-атрибуты (``list[PhotoSize]``,
    документ с image-mime, статический стикер): тестовые MagicMock-двойники
    не должны притворяться фотографией, а анимации/видео — вне image-контура
    (D18, mca_vision)."""
    photo = getattr(message, "photo", None)
    if isinstance(photo, (list, tuple)):
        return bool(photo)
    document = getattr(message, "document", None)
    if document is not None:
        mime = getattr(document, "mime_type", None)
        if isinstance(mime, str) and mime.startswith("image/"):
            return True
    sticker = getattr(message, "sticker", None)
    if sticker is not None:
        return not (bool(getattr(sticker, "is_animated", False))
                    or bool(getattr(sticker, "is_video", False)))
    return False


def _descriptions_from_lines(lines) -> list[str]:
    """Визуальные описания из готового рендера (совместимость со старыми
    структурами без аддитивного ключа ``visual_descriptions``)."""
    prefix = "Визуальное описание (результат модели):"
    result: list[str] = []
    for line in lines or ():
        value = str(line or "")
        if value.startswith(prefix):
            text = value[len(prefix):].strip()
            if text:
                result.append(text)
    return result


def _labelled_block(prefix: str, index: int, multi: bool, tail: str,
                    body: str) -> str:
    number = f" {index}" if multi else ""
    return f"{prefix}{number}{tail}:\n{body}"


async def load_claim_media(db, chat_id: int | None,
                           tg_message_id: int | None, *,
                           render_async=None,
                           max_chars: int = 2000,
                           message_ids=None,
                           expected_images: int = 0,
                           media_wait_seconds: float | None = None,
                           ) -> ClaimMediaMaterial:
    """OCR/визуальное описание изображений публикации (REUSE mca_vision).

    ``message_ids`` (P0-FACTCHECK media §3) — элементы альбома: читаются ВСЕ,
    поэтому тезис получает текст каждого изображения, а не только целевого.
    ``expected_images`` — сколько элементов заведомо являются изображениями
    (TG-атрибут/``media_type``): расхождение с реально найденными активами —
    честная ТЕХНИЧЕСКАЯ недоступность (``vision_failed``), а не «нет
    изображения». Возвращает контракт «что попало в анализ»: ``text_suffix``
    уходит в claim/envelope (=> в поисковые запросы и в промпт аналитика),
    ``notice()`` — честная оговорка для ответа.

    Fail-open: любая ошибка чтения → пустой материал (прежнее поведение без
    изображения), но сам факт сбоя при наличии ожидаемого изображения
    помечается ``vision_failed``."""
    if db is None or not chat_id:
        return ClaimMediaMaterial(image_present=False,
                                  vision_failed=bool(expected_images))
    if render_async is None:
        try:
            from services import mca_vision
            render_async = mca_vision.render_media_context_async
        except Exception:          # pragma: no cover — vision выключен
            return ClaimMediaMaterial(image_present=False,
                                      vision_failed=bool(expected_images))
    ids: list[int] = []
    for value in (message_ids if message_ids is not None
                  else [tg_message_id]):
        try:
            mid = int(value)
        except (TypeError, ValueError):
            continue
        if mid and mid not in ids:
            ids.append(mid)
    rendered: list[dict] = []
    # ASAP-VISION-SYNC-01 §4 («Фактчек — специальное обязательное правило»):
    # ДО извлечения тезиса и до suitability-gate связанные изображения
    # доводятся до фактического анализа (bounded; reuse durable jobs, без
    # новых LLM-вызовов). Пока анализ идёт, «нечего проверять» запрещено:
    # ниже это честно помечается как pending, а терминальный отказ даёт
    # явную оговорку «содержимое картинки не проверено».
    readiness_by_message: dict = {}
    if ids:
        try:
            from services import media_readiness
            readiness_by_message = await media_readiness.prepare_images_ready(
                db, chat_id=int(chat_id), message_ids=ids,
                consumer="factcheck",
                wait_seconds=(media_wait_seconds
                              if media_wait_seconds is not None else None))
        except Exception:
            logger.warning("[factcheck] media readiness failed — прежний "
                           "путь | chat=%s", chat_id, exc_info=True)
            readiness_by_message = {}
    failed = 0
    for mid in ids[:_MAX_ALBUM_ELEMENTS]:
        try:
            media = await render_async(db, chat_id=int(chat_id),
                                       tg_message_id=int(mid))
        except Exception:
            failed += 1
            logger.warning("[factcheck] media context read failed — caption "
                           "only | chat=%s | tg=%s", chat_id, mid,
                           exc_info=True)
            continue
        if media:
            rendered.append(media)
    expected = max(0, int(expected_images or 0))
    if not rendered:
        # Изображения ожидались, но ни одного не прочитали — техническая
        # недоступность (а не «изображения нет»). Без ожидания — материала нет.
        return ClaimMediaMaterial(image_present=False,
                                  vision_failed=expected > 0)
    captions: list[str] = []
    ocr_blocks: list[str] = []
    desc_blocks: list[str] = []
    raw_descriptions: list[str] = []
    ocr_chars = 0
    pending = False
    pending_count = 0
    truncated = False
    multi = len(rendered) > 1
    # Review fix (25.10.2026): лимит — НА ОДИН элемент (не на всю публикацию).
    # 10 фото по ~400 симв. OCR помещаются полностью; тихой обрезки всех
    # изображений одним общим бюджетом больше нет. При превышении лимита
    # элемента — честный флаг truncated (=> оговорка в ответе).
    element_budget = max(200, int(max_chars or 2000))
    unchecked = False
    unchecked_reason = ""
    for index, media in enumerate(rendered, start=1):
        caption = str(media.get("caption") or "").strip()
        if caption and caption not in captions:
            captions.append(caption)
        lines = [str(line) for line in (media.get("lines") or ())]
        # F6 (review r1): «распознавание не готово» ≠ «на изображении нет
        # текста». Готовый анализ без текста — честный `analyzed` без ложной
        # оговорки; pending только когда строка ожидания Vision реально есть.
        if any("содержание ещё не распознано" in line for line in lines):
            pending = True
            pending_count += 1
        texts = [str(t).strip() for t in (media.get("untrusted_ocr_texts")
                                          or ()) if str(t or "").strip()]
        element_ocr: list[str] = []
        for text in texts:
            ocr_chars += len(text)
            element_ocr.append(_labelled_block(
                "Текст с изображения", index, multi,
                " (OCR, не слова автора)", text))
        element_desc: list[str] = []
        descs = [str(d).strip()
                 for d in (media.get("visual_descriptions") or ())
                 if str(d or "").strip()]
        if not descs:
            descs = _descriptions_from_lines(lines)
        for desc in descs:
            raw_descriptions.append(desc)
            element_desc.append(_labelled_block(
                "Визуальное описание изображения", index, multi,
                " (результат модели; не доказывает подлинность, дату или "
                "место)", desc))
        ocr_part = "\n\n".join(element_ocr)
        desc_part = "\n\n".join(element_desc)
        if len(ocr_part) > element_budget:
            ocr_part = ocr_part[:element_budget].rstrip()
            truncated = True
            desc_part = ""
        elif ocr_part and len(ocr_part) + len(desc_part) > element_budget:
            desc_part = desc_part[:max(0, element_budget - len(ocr_part))].rstrip()
            truncated = True
        elif not ocr_part and len(desc_part) > element_budget:
            desc_part = desc_part[:element_budget].rstrip()
            truncated = True
        if ocr_part:
            ocr_blocks.append(ocr_part)
        if desc_part:
            desc_blocks.append(desc_part)
    ocr_suffix = "\n\n".join(ocr_blocks).strip()
    desc_suffix = "\n\n".join(desc_blocks).strip()
    # ASAP-VISION-SYNC-01: фактическое состояние каждого изображения (не вывод
    # из текста рендера): pending — анализ идёт, failed — терминальный отказ
    # (содержимое картинки НЕ проверено, об этом говорит ответ).
    for state in (readiness_by_message or {}).values():
        if getattr(state, "ready", False):
            continue
        if getattr(state, "pending", False):
            if not pending:
                pending = True
                pending_count = max(pending_count, 1)
            continue
        if getattr(state, "failed", False) and not unchecked:
            unchecked = True
            unchecked_reason = str(getattr(state, "reason_code", "") or "")
    if unchecked:
        # Честная оговорка «картинку не проверили» покрывает и недоступность
        # файла — не дублируем её вторым предложением.
        vision_failed = False
    # Review fix: описание — КОНТЕКСТ, а не тезис. В claim/envelope оно идёт
    # только когда есть OCR (материал тезиса); без OCR остаётся в
    # description_suffix и передаётся модели отдельным non-evidence блоком.
    suffix = ocr_suffix
    if ocr_suffix and desc_suffix:
        suffix = f"{ocr_suffix}\n\n{desc_suffix}"
    unavailable = expected > len(rendered)
    return ClaimMediaMaterial(text_suffix=suffix, image_present=True,
                              image_analyzed=not pending,
                              image_not_analyzed=pending,
                              ocr_chars=ocr_chars,
                              caption="\n\n".join(captions),
                              vision_failed=False if unchecked else
                              (unavailable
                               or (bool(failed) and expected > 0)),
                              image_count=len(rendered),
                              pending_count=pending_count,
                              visual_descriptions=tuple(raw_descriptions),
                              description_suffix=desc_suffix,
                              truncated=truncated,
                              image_unchecked=unchecked,
                              unchecked_reason=unchecked_reason)


@dataclasses.dataclass(frozen=True)
class ClaimPublication:
    """Что удалось восстановить о публикации до фактчека (P0 media §3).

    ``text`` — тезис для пайплайна (подпись/текст публикации + материал
    изображений), ``caption_text`` — только текст публикации (без материала;
    для повторного резолва в оркестраторе v2). ``augmented`` — текст собран
    сверх целевой строки (caption другого элемента альбома или изображения):
    только тогда он передаётся в envelope как claim_text."""
    text: str = ""
    caption_text: str = ""
    media: ClaimMediaMaterial = dataclasses.field(
        default_factory=ClaimMediaMaterial)
    message_ids: tuple[int, ...] = ()
    media_group_id: str | None = None
    has_image: bool = False
    augmented: bool = False
    album_incomplete: bool = False
    forward_source: str | None = None
    reply_to_tg_id: int | None = None     # цель отвечает на это сообщение
    # ASAP-VISION-SYNC-01 F2 (review): слабая связь с изображением —
    # `media_linked_adjacent` (найдено фото рядом по автору/ветке) и
    # `media_ambiguous` (кандидатов ≥2 или чужое фото без структурной связи:
    # нужен короткий вопрос-уточнение, а не «нечего проверять»).
    media_linked_adjacent: bool = False
    media_ambiguous: bool = False
    # ── EVOL-REPLY-CONTEXT-INTEGRITY-01 §1.5 (M1/M7), §10.3: одна правда о
    # цели, происхождении тезиса и медиа-зависимости. Поля аддитивные; пустое
    # значение = «резолвер этого не устанавливал» (никаких выдуманных флагов).
    target_chat_id: int | None = None
    target_tg_message_id: int | None = None
    #: explicit_reply|stored_reply|forward|album|media|command_text|contextual|tool
    target_source: str = ""
    #: target_text|target_caption|target_media|target_transcript|command_text|
    #: context_window|adjacent_media|tool_claim|external_claim
    claim_origin: str = ""
    claim_anchor_tg_message_id: int | None = None
    claim_anchor_author: str | None = None
    claim_anchor_source: str = "literal"   # literal|reply_to|topic|quote|media
    #: у публикации есть самостоятельный проверяемый текст (§10.2)
    text_sufficient: bool = False
    association_attempted: bool = False
    association_status: str = ""      # resolved|ambiguous|missing|not_attempted
    association_reason: str = ""
    association_candidates: tuple[int, ...] = ()

    def _notice_parts(self) -> list[tuple[str, str]]:
        """(typed reason, текст) — единственный источник оговорок входа.

        §10.3/§11.3: медиа-оговорка привязана к ФАКТИЧЕСКОЙ зависимости этой
        проверки. `text_sufficient` — вторая стена к гейту `M9`: даже если
        неоднозначность как-то выставлена, при достаточном тексте картинку у
        пользователя не переспрашивают."""
        parts: list[tuple[str, str]] = []
        if self.media_ambiguous and not self.text_sufficient:
            parts.append((
                "ambiguous_no_text_claim",
                "Не понял, какое изображение проверять: рядом несколько "
                "подходящих (или чужое фото без ответа на него) — ответь на "
                "нужное фото или пришли его сюда."))
        if self.album_incomplete:
            parts.append((
                "album_incomplete",
                "Элементы альбома прочитаны не полностью — проверено то, что "
                "сохранилось."))
        media_notice = self.media.notice()
        if media_notice:
            parts.append((self._media_notice_reason(), media_notice))
        return parts

    def _media_notice_reason(self) -> str:
        """Причина медиа-оговорки из фактического состояния материала."""
        if self.media.image_unchecked:
            return "vision_unchecked"
        if self.media.vision_failed:
            return "vision_failed"
        if self.media.truncated:
            return "media_truncated"
        if self.media.image_not_analyzed:
            return "vision_pending"
        return "media_other"

    def notice(self) -> str:
        return " ".join(text for _reason, text in self._notice_parts())

    def notice_reason(self) -> str:
        """Первая фактическая причина оговорки ('' = оговорки нет)."""
        parts = self._notice_parts()
        return parts[0][0] if parts else ""

    def media_dependency_source(self) -> str:
        """Почему проверка зависит/не зависит от медиа (§10.2/§10.3).

        Значения — из фактического состояния публикации, а не из фразы
        команды: ``explicit_reply_media``, ``album``, ``linked_media``,
        ``adjacent_media_candidate``, ``text_claim_only``, ``unresolved``."""
        if self.media_group_id:
            return "linked_media" if self.media_linked_adjacent else "album"
        if self.has_image or self.media.image_present:
            return "explicit_reply_media"
        if self.association_attempted:
            return "adjacent_media_candidate"
        if self.text_sufficient:
            return "text_claim_only"
        return "unresolved"

    def target_kind(self) -> str:
        """text|media|mixed|unresolved — по фактическому состоянию входа."""
        has_media = bool(self.has_image or self.media.image_present
                         or self.media.image_unchecked
                         or self.association_status == "resolved")
        has_text = bool(str(self.text or "").strip()) and self.text_sufficient
        if has_text and has_media:
            return "mixed"
        if has_text:
            return "text"
        if has_media:
            return "media"
        return "unresolved"

    def trace_fields(self) -> dict:
        """§10.3: типизированная трасса входа — только коды/ID, без текстов."""
        return {
            "target_source": str(self.target_source or ""),
            "target_kind": self.target_kind(),
            "target_tg_message_id": self.target_tg_message_id,
            "claim_origin": str(self.claim_origin or ""),
            "claim_anchor_tg_message_id": self.claim_anchor_tg_message_id,
            "claim_anchor_source": str(self.claim_anchor_source or ""),
            "text_claim_resolved": bool(self.text_sufficient),
            "media_expected": bool(self.has_image
                                   or self.media_group_id
                                   or self.association_attempted),
            "media_dependency_source": self.media_dependency_source(),
            "association_attempted": bool(self.association_attempted),
            "association_status": str(self.association_status or ""),
            "association_reason": str(self.association_reason or ""),
            "association_candidates": len(self.association_candidates),
            "linked_media_ids": (list(self.message_ids)
                                 if (self.has_image or self.media_group_id
                                     or self.association_status == "resolved")
                                 else []),

            "media_notice_emitted": bool(self.notice_reason()),
            "media_notice_reason": self.notice_reason(),
        }


    # ASAP-VISION-SYNC-01 §4: единая точка правды о медиа-зависимости для
    # обоих маршрутов фактчека (handler и v2-оркестратор). Пока анализ
    # изображения `pending`, предварительный `no_claim` запрещён: пустая
    # подпись ≠ отсутствие проверяемого тезиса.
    @property
    def media_pending(self) -> bool:
        return bool(self.media.image_not_analyzed)

    @property
    def media_unchecked(self) -> bool:
        return bool(self.media.image_unchecked)

    def media_dependency(self) -> str:
        """`ready` | `pending` | `unchecked` | `none` (нормализованно)."""
        if self.media_pending:
            return "pending"
        if self.media_unchecked:
            return "unchecked"
        if self.has_image or self.media.image_present:
            return "ready"
        return "none"

    def admission_blocked_by_pending_media(self) -> bool:
        """True — допуск обязан отложиться (pending OCR), а не дать no_claim."""
        return self.media_pending

    def material_context(self) -> str:
        """Визуальные описания как non-evidence контекст (review fix).

        Если OCR есть, описания уже вошли в ``text`` (материал тезиса) —
        второй раз не дублируем. Если OCR нет, описание — только контекст
        изображения (результат модели, не доказательство) и в тезис не
        попадает."""
        descriptions = self.media.description_suffix
        if not self.has_image or not descriptions or self.media.text_suffix:
            return ""
        return ('<chat_context note="визуальные описания изображений — '
                'результат модели, НЕ доказательства и НЕ утверждения '
                'автора">\n' + descriptions + "\n</chat_context>")


async def resolve_claim_publication(
        db, chat_id: int | None, tg_message_id: int | None, *,
        base_text: str | None = None,
        target=None,
        use_stored_target_text: bool = True,
        render_async=None,
        max_chars: int = 2000,
        media_wait_seconds: float | None = None,
        trigger_tg_message_id: int | None = None,
        requester_user_id: int | None = None,
        requester_name: str = "",
        target_source: str | None = None,
        allow_adjacent: bool = True) -> ClaimPublication:
    """Восстановить публикацию: durable элементы альбома + изображения.

    P0-FACTCHECK media (owner 25.10.2026 §3): ответ на ЛЮБОЙ элемент
    media group обязан дать всю публикацию — все элементы и ВСЕ подписи
    (Telegram кладёт caption только на один элемент), все изображения.
    Durable источник — ``smart_messages.media_group_id``; in-memory
    ``media_group_buffer`` используется только как fast-path, когда строк
    ещё нет (рестарт/TTL/сбой записи). Соседние сообщения вне группы не
    подмешиваются: запрос строго по ``media_group_id`` в том же чате.

    ``target`` — aiogram ``Message`` (handler-путь): даёт прямой текст, признак
    изображения и ``media_group_id`` без ожидания записи. Без него (путь
    оркестратора v2) всё берётся из сохранённой строки.

    Fail-open: сбой чтения строки/группы не роняет фактчек; неполнота альбома
    помечается честно (``album_incomplete``), а не выдаётся за полный вход."""
    base = str(base_text or "").strip()
    try:
        tg_id = (int(tg_message_id)
                 if tg_message_id not in (None, "", 0) else None)
    except (TypeError, ValueError):
        tg_id = None
    target_row = None
    if db is not None and chat_id is not None and tg_id is not None:
        try:
            target_row = await db.get_smart_message_by_tg_id(
                int(chat_id), int(tg_id))
        except Exception:
            logger.warning("[factcheck] target row read failed — text only | "
                           "chat=%s | tg=%s", chat_id, tg_id, exc_info=True)
    media_group_id = None
    if target is not None:
        raw = getattr(target, "media_group_id", None)
        if isinstance(raw, str) and raw.strip():
            media_group_id = raw.strip()
    if media_group_id is None:
        raw = _row_value(target_row, "media_group_id")
        if isinstance(raw, str) and raw.strip():
            media_group_id = raw.strip()
    hint_image = _message_image_hint(target) if target is not None else False
    # Уточнение владельца 25.10.2026: ответ на ТЕКСТОВУЮ часть поста даёт тот
    # же охват, что ответ на фото. Альбом, прикреплённый ответом к этому
    # сообщению, находится по структурной связи `reply_to_id` (не по
    # соседству). Связь неоднозначна (>1 группы) → не угадываем.
    attached_via_reply = False
    if (media_group_id is None and not hint_image and db is not None
            and chat_id is not None and tg_id is not None):
        try:
            attached = list(await db.get_smart_messages_reply_to(
                int(chat_id), int(tg_id), media_only=True) or [])
        except Exception:
            attached = []
            logger.warning("[factcheck] attached album lookup failed — text "
                           "only | chat=%s | tg=%s", chat_id, tg_id,
                           exc_info=True)
        groups = {str(_row_value(row, "media_group_id") or "").strip()
                  for row in attached}
        groups.discard("")
        if len(groups) == 1:
            media_group_id = groups.pop()
            attached_via_reply = True
    album_rows: list = []
    album_incomplete = False
    known_ids: tuple[int, ...] | None = None
    if media_group_id:
        try:
            known_ids = get_media_group_ids(str(media_group_id))
        except Exception:          # pragma: no cover — буфер не бросает
            known_ids = None
    if media_group_id and db is not None and chat_id is not None:
        try:
            album_rows = list(
                await db.get_smart_messages_by_media_group(
                    int(chat_id), str(media_group_id)) or [])
        except Exception:
            album_incomplete = True
            logger.warning("[factcheck] media group read failed — partial | "
                           "chat=%s | group=%s", chat_id, media_group_id,
                           exc_info=True)
    by_id: dict[int, object] = {}
    for row in album_rows:
        try:
            row_id = int(_row_value(row, "tg_message_id"))
        except (TypeError, ValueError):
            continue
        by_id[row_id] = row
    album_rows = [by_id[key] for key in sorted(by_id)][:_MAX_ALBUM_ELEMENTS]
    # Review fix (25.10.2026): неполнота альбома — не только исключение чтения.
    # Признаки (детерминированно, без угадывания числа): цель-элемент не
    # сохранён; durable-строк меньше двух (media group в Telegram — ≥2);
    # известные из same-turn буфера id отсутствуют в durable-строках;
    # разрыв в последовательности tg_message_id (альбом отправляется пачкой,
    # id соседние; удалённый/потерянный элемент даёт разрыв). Любой признак →
    # честная оговорка, а не «полная публикация».
    durable_ids = set(by_id)
    if media_group_id and db is not None and chat_id is not None:
        if not attached_via_reply:
            # Цель — элемент группы: он обязан быть среди durable-строк.
            if tg_id is not None and tg_id not in durable_ids:
                album_incomplete = True
            if len(durable_ids) < 2:
                album_incomplete = True
        if known_ids is not None and not set(known_ids) <= durable_ids:
            album_incomplete = True
        if len(durable_ids) >= 2 and (
                max(durable_ids) - min(durable_ids) + 1 > len(durable_ids)):
            album_incomplete = True
    element_rows = list(album_rows)
    if target_row is not None and tg_id is not None and tg_id not in by_id:
        element_rows.append(target_row)
    caption_values: list[str] = []
    if base:
        caption_values.append(base)
    for row in element_rows:
        row_id = _row_value(row, "tg_message_id")
        try:
            row_id = int(row_id)
        except (TypeError, ValueError):
            row_id = None
        if row_id == tg_id and (base or not use_stored_target_text):
            # Прямой текст цели авторитетнее сохранённой копии (правки),
            # дубль в тезис не тянем. Репост-вариант (D121): caption самого
            # триггера — это команда «фактчек», а не публикация.
            continue
        value = (str(_row_value(row, "caption") or "").strip()
                 or str(_row_value(row, "text") or "").strip())
        if value and value not in caption_values:
            caption_values.append(value)
    if not caption_values and media_group_id:
        buffered = get_media_group_caption(str(media_group_id))
        if buffered:
            caption_values.append(str(buffered).strip())
    # Текст поста отдельным сообщением (уточнение 25.10): подключается по
    # структурной связи reply_to — альбом отвечает на текст публикации.
    # Это НЕ соседнее сообщение (§3.8): связь явная и одношаговая; чужие
    # подписи/тексты рядом не подмешиваются.
    parent_id = None
    for row in ([target_row] if target_row is not None else []) + element_rows:
        try:
            value = int(_row_value(row, "reply_to_id"))
        except (TypeError, ValueError):
            continue
        if value and value != tg_id:
            parent_id = value
            break
    if (parent_id is not None and media_group_id and not attached_via_reply
            and db is not None and chat_id is not None):
        try:
            parent = await db.get_smart_message_by_tg_id(
                int(chat_id), int(parent_id))
        except Exception:
            parent = None
            logger.warning("[factcheck] post text read failed — caption "
                           "only | chat=%s | tg=%s", chat_id, parent_id,
                           exc_info=True)
        if parent is not None and not _row_is_image(parent):
            parent_text = (str(_row_value(parent, "text") or "").strip()
                           or str(_row_value(parent, "caption") or "").strip())
            if parent_text and parent_text not in caption_values:
                caption_values.insert(0, parent_text)
    caption_text = "\n\n".join(value for value in caption_values if value)
    expected_ids: set[int] = set()
    if hint_image and tg_id is not None:
        expected_ids.add(int(tg_id))
    for row in element_rows:
        if not _row_is_image(row):
            continue
        try:
            expected_ids.add(int(_row_value(row, "tg_message_id")))
        except (TypeError, ValueError):
            continue
    image_ids: list[int] = []
    for row in element_rows:
        try:
            row_id = int(_row_value(row, "tg_message_id"))
        except (TypeError, ValueError):
            continue
        if row_id not in image_ids:
            image_ids.append(row_id)
    if tg_id is not None and tg_id not in image_ids:
        image_ids.append(tg_id)
    image_ids.sort()
    # ASAP-VISION-SYNC-01 F2 (review): «фото, затем отдельное „фактчек“».
    # Если у цели НЕТ собственных изображений, ищем слабую связь тем же
    # резолвером, что и остальные потребители: единственное фото ТОГО ЖЕ
    # автора рядом (чужое фото без структурной связи → честная
    # неоднозначность, а не приписывание).
    #
    # FC-MEDIA-OPTIONAL-01 §10.2 (M8): один предикат достаточности текста на
    # все маршруты. Считается один раз по тексту самой публикации (до
    # материала изображений) и используется и гейтом ниже, и трассой.
    from services.factcheck_suitability import text_target_sufficient
    text_sufficient = text_target_sufficient(caption_text or base)
    adjacent_ids: list[int] = []
    media_ambiguous = False
    association_attempted = False
    association_status = "not_attempted"
    association_reason = ""
    association_candidates: tuple[int, ...] = ()
    if (allow_adjacent and db is not None and chat_id is not None
            and not expected_ids and not hint_image):
        if text_sufficient:
            association_reason = "text_claim_sufficient"
        else:
            association_attempted = True
            anchor_id = tg_id if tg_id is not None else trigger_tg_message_id
            if anchor_id:
                try:
                    from services import media_readiness
                    resolved = await media_readiness.resolve_target_media(
                        db, chat_id=int(chat_id), message_id=int(anchor_id),
                        allow_adjacent=True,
                        author_user_id=requester_user_id,
                        author_name=str(requester_name or ""))
                except Exception:
                    resolved = {}
                    logger.warning("[factcheck] adjacent media resolve failed | "
                                   "chat=%s", chat_id, exc_info=True)
                association_status = str(
                    resolved.get("association_status") or "missing")
                association_reason = str(
                    resolved.get("association_reason")
                    or resolved.get("association_kind") or "")
                association_candidates = tuple(
                    int(v) for v in (resolved.get("source_message_ids") or ())
                    if v)[:_MAX_ALBUM_ELEMENTS]
                if association_status == "resolved":
                    adjacent_ids = list(association_candidates)
                elif association_status == "ambiguous":
                    media_ambiguous = True
                    logger.info("[factcheck] adjacent media ambiguous | "
                                "chat=%s | candidates=%s", chat_id,
                                len(association_candidates))
    if adjacent_ids:
        for extra_id in adjacent_ids:
            if extra_id not in image_ids:
                image_ids.append(extra_id)
        image_ids.sort()
        # Подпись найденного фото — часть публикации (иначе тезис потеряется).
        for extra_id in adjacent_ids:
            try:
                extra_row = await db.get_smart_message_by_tg_id(
                    int(chat_id), int(extra_id))
            except Exception:
                extra_row = None
            value = (str(_row_value(extra_row, "caption") or "").strip()
                     or str(_row_value(extra_row, "text") or "").strip())
            if value and value not in caption_values:
                caption_values.append(value)
        if caption_values:
            caption_text = "\n\n".join(v for v in caption_values if v)
    media = await load_claim_media(
        db, chat_id, tg_id, render_async=render_async, max_chars=max_chars,
        message_ids=image_ids or None, expected_images=len(expected_ids),
        media_wait_seconds=media_wait_seconds)
    has_image = hint_image or bool(expected_ids) or media.image_present
    if expected_ids and not media.image_present and not media.vision_failed:
        media = dataclasses.replace(media, vision_failed=True)
    text = caption_text
    if media.text_suffix:
        text = (f"{caption_text}\n\n{media.text_suffix}".strip()
                if caption_text else media.text_suffix)
    forward_source = None
    for row in ([target_row] if target_row is not None else []) + element_rows:
        source = str(_row_value(row, "forward_source") or "").strip()
        if not source:
            source = str(_row_value(row, "origin_display_name") or "").strip()
        if source:
            forward_source = source
            break
    reply_to_tg_id = None
    reply_obj = (getattr(target, "reply_to_message", None)
                 if target is not None else None)
    reply_value = (getattr(reply_obj, "message_id", None)
                   if reply_obj is not None else None)
    if isinstance(reply_value, int) and not isinstance(reply_value, bool):
        reply_to_tg_id = reply_value
    if reply_to_tg_id is None:
        try:
            reply_to_tg_id = int(_row_value(target_row, "reply_to_id"))
        except (TypeError, ValueError):
            reply_to_tg_id = None
    # M1/M7: цель и происхождение тезиса фиксируются из фактических данных
    # резолвера (а не пересказа). `target_source` может прийти от вызывающего
    # (handler знает вид триггера); иначе — структурный факт публикации.
    resolved_source = str(target_source or "").strip()
    if not resolved_source:
        if media_group_id:
            resolved_source = "linked_media" if attached_via_reply else "album"
        elif has_image:
            resolved_source = "media"
        elif forward_source:
            resolved_source = "forward"
        else:
            resolved_source = "explicit_reply"
    if has_image and not caption_text:
        resolved_origin = "target_media"
    elif caption_text and base:
        resolved_origin = "target_caption" if caption_text != base else "target_text"
    elif caption_text:
        resolved_origin = "target_caption"
    elif media.text_suffix:
        resolved_origin = "target_media"
    else:
        resolved_origin = ""
    return ClaimPublication(
        text=text, caption_text=caption_text, media=media,
        message_ids=tuple(image_ids), media_group_id=media_group_id,
        has_image=has_image, augmented=bool(text) and text != base,
        album_incomplete=album_incomplete, forward_source=forward_source,
        reply_to_tg_id=reply_to_tg_id,
        media_ambiguous=media_ambiguous,
        media_linked_adjacent=bool(adjacent_ids),
        target_chat_id=(int(chat_id) if chat_id not in (None, "", 0) else None),
        target_tg_message_id=tg_id,
        target_source=resolved_source,
        claim_origin=resolved_origin,
        claim_anchor_tg_message_id=tg_id,
        claim_anchor_author=str(requester_name or "") or None,
        text_sufficient=text_sufficient,
        association_attempted=association_attempted,
        association_status=association_status,
        association_reason=association_reason,
        association_candidates=association_candidates)


# ── P0-FACTCHECK (§3.6): классы исхода retrieval — сбой ≠ «нет данных» ───────

RETRIEVAL_OK = "ok"
RETRIEVAL_NOT_RUN = "not_run"
RETRIEVAL_BUDGET = "budget_exhausted"
RETRIEVAL_SEARCH_FAILED = "search_failed"
RETRIEVAL_PROCESSING_FAILED = "processing_failed"
RETRIEVAL_INSUFFICIENT = "insufficient_evidence"
# P0-FACTCHECK-CORRECTIVE (§5.1/§5.2): провайдеры ОТВЕТИЛИ, но пригодных
# материалов нет (пустая и/или нерелевантная выдача) — это НЕ «поисковики
# недоступны» и не «самих фактов нет».
RETRIEVAL_NO_RESULTS = "no_usable_results"

#: Класс → существующий reason-код реестра (новые коды не выдумываются:
#: `verdict_from_payload` пропускает только REASON_CODES).
_RETRIEVAL_REASON = {
    RETRIEVAL_BUDGET: "deadline_exceeded",
    RETRIEVAL_SEARCH_FAILED: "provider_unavailable",
    RETRIEVAL_PROCESSING_FAILED: "source_missing",
    RETRIEVAL_INSUFFICIENT: "insufficient_evidence",
    RETRIEVAL_NO_RESULTS: "insufficient_evidence",
}

#: Класс → человеческая оговорка (в uncertainty; НЕ выдуманный вердикт).
_RETRIEVAL_CAVEAT = {
    RETRIEVAL_BUDGET: ("поиск прерван по лимиту времени — проверены не все "
                       "запросы"),
    RETRIEVAL_SEARCH_FAILED: ("поисковые сервисы не ответили — это "
                              "технический сбой, а не отсутствие фактов"),
    RETRIEVAL_PROCESSING_FAILED: ("поиск дал материалы, но пригодных для "
                                  "проверки выдержек из них не получено"),
    RETRIEVAL_NO_RESULTS: ("поиск ответил, но подходящих для проверки "
                           "материалов не дал — другие подходящие источники "
                           "могли просто не попасть в выдачу"),
}

#: Класс → что честно сказать вербализатору (о состоянии ПОИСКА, не «вся
#: проверка не состоялась» — анализ без поиска продолжается, §2.4).
_RETRIEVAL_SITUATION = {
    RETRIEVAL_BUDGET: ("внешний поиск прерван по лимиту времени — проверены "
                       "не все запросы"),
    RETRIEVAL_SEARCH_FAILED: ("внешний поиск не удался: поисковые сервисы "
                              "не ответили"),
    RETRIEVAL_PROCESSING_FAILED: ("поиск дал материалы, но пригодных для "
                                  "проверки выдержек из них не получилось"),
    RETRIEVAL_NO_RESULTS: ("поиск ответил, но подходящих материалов не дал"),
}

#: P0-FACTCHECK-CORRECTIVE (§5.1): причина поиска для analyst-payload, когда
#: внешний evidence пуст (человекочитаемо, в <analysis_context>).
_RETRIEVAL_SEARCH_NOTE = {
    RETRIEVAL_BUDGET: "внешний поиск прерван по лимиту времени",
    RETRIEVAL_SEARCH_FAILED: "поисковые сервисы не ответили (технический "
                             "сбой)",
    RETRIEVAL_PROCESSING_FAILED: "материалы найдены, но пригодных для "
                                 "проверки выдержек из них не получилось",
    RETRIEVAL_NO_RESULTS: "провайдеры ответили, но подходящих материалов не "
                          "дали (пустая или нерелевантная выдача)",
    RETRIEVAL_NOT_RUN: "внешний поиск в этом прогоне не выполнялся",
    RETRIEVAL_INSUFFICIENT: "подходящих внешних материалов не найдено",
}

#: Технические reason-коды retrieval (заголовок «проверка не завершена» в
#: renderer). Содержательный вывод без поиска этот заголовок не получает.
_TECHNICAL_RETRIEVAL_REASONS = frozenset({
    "deadline_exceeded", "provider_unavailable", "source_missing",
})


def classify_retrieval(retrieval) -> str:
    """RetrievalOutcome → класс исхода (§11.2, FC-EVIDENCE-STATUS-01).

    Порядок условий заморожен контрактом (§3.3): технический статус
    объявляется ТОЛЬКО по фактическому сбою стадии, а не по отсутствию
    ссылок/релевантности.

    ``None`` → not_run (внутренний поиск ветки, прежний контракт). Есть
    evidence → ok. Дальше — по фактическим счётчикам стадии:

    бюджет без единого результата → бюджет; провайдеры ответили пустой или
    нерелевантной выдачей → «нет подходящих материалов» (НЕ «недоступны»,
    §11.2 п.4/5); запросы упали/не выполнены → «поиск недоступен» (§11.2 п.1);
    материалы были, но извлечение реально сломалось (``fetch_errors>0``) →
    технический класс чтения источника (§11.2 п.3); материалы прочитаны, но
    цитировать нечего → «недостаточно данных» + честная оговорка о
    цитируемости (§11.2 п.6). Детерминированно, без новых вызовов."""
    if retrieval is None:
        return RETRIEVAL_NOT_RUN
    try:
        if getattr(getattr(retrieval, "evidence_map", None), "refs", ()):
            return RETRIEVAL_OK
        attempted = int(getattr(retrieval, "queries_attempted", 0) or 0)
        used = int(getattr(retrieval, "queries_used", 0) or 0)
        failures = int(getattr(retrieval, "provider_failures", 0) or 0)
        empties = int(getattr(retrieval, "empty_results", 0) or 0)
        irrelevant = int(getattr(retrieval, "irrelevant_results", 0) or 0)
        fetch_errors = int(getattr(retrieval, "fetch_errors", 0) or 0)
        if getattr(retrieval, "budget_exhausted", False) and used == 0:
            return RETRIEVAL_BUDGET
        if used == 0 and (empties > 0 or irrelevant > 0):
            # §11.2 п.4/5: провайдеры ОТВЕТИЛИ — техсбоя нет
            return RETRIEVAL_NO_RESULTS
        if used == 0 and (attempted > 0 or failures > 0):
            return RETRIEVAL_SEARCH_FAILED
        if used > 0 and fetch_errors > 0:
            # §11.2 п.3: единственный законный повод сказать «материалы не
            # удалось разобрать» — реальная ошибка извлечения/парсинга.
            return RETRIEVAL_PROCESSING_FAILED
        if used > 0:
            # §11.2 п.6: материалы прочитаны, проверяемых ссылок нет.
            return RETRIEVAL_NO_RESULTS
    except Exception:          # pragma: no cover — метрики не рвут вердикт
        return RETRIEVAL_NOT_RUN
    return RETRIEVAL_INSUFFICIENT


#: §11.3: неизвестное значение не изображается нулём.
_DIAG_UNKNOWN = "н/д"


def _diag_count(value) -> int | str:
    """Счётчик из реального значения; отсутствующее — «нет данных»."""
    if value is None:
        return _DIAG_UNKNOWN
    try:
        return int(value)
    except (TypeError, ValueError):
        return _DIAG_UNKNOWN


def evidence_diagnostics(*, retrieval, retrieval_state: str,
                         evidence, verdict, delivery=None) -> dict:
    """§11.3: диагностика ОДНОГО прогона из фактических значений.

    Ничего не вычисляется «по аналогии»: если счётчика в этой ветке нет —
    пишется «нет данных», а не 0. Текстов тезиса/чатов здесь нет (§7)."""
    claims = tuple(getattr(retrieval, "claims", ()) or ())
    known = retrieval is not None
    fetch_errors = (int(getattr(retrieval, "fetch_errors", 0) or 0)
                    if known else None)
    opened = (sum(int(getattr(c, "opened", 0) or 0) for c in claims)
              if known else None)
    extract_attempts = (opened + (fetch_errors or 0)
                        if opened is not None else None)
    # Реальные счётчики стадии: один элемент `provider_status` = одна попытка
    # провайдера; `candidates` = сколько строк выдачи было получено.
    provider_attempts = (sum(len(tuple(getattr(c, "provider_status", ()) or ()))
                             for c in claims) if known else None)
    documents = (sum(int(getattr(c, "candidates", 0) or 0) for c in claims)
                 if known else None)
    citable = len([r for r in (evidence or ()) if r.get("url")])
    delivery_meta = delivery.as_meta() if delivery is not None else {}
    return {
        "source_query_count": _diag_count(
            getattr(retrieval, "queries_attempted", None) if known else None),
        "provider_attempts": _diag_count(provider_attempts),
        "provider_failures": _diag_count(
            getattr(retrieval, "provider_failures", None) if known else None),
        "documents_retrieved": _diag_count(documents),
        "queries_with_results": _diag_count(
            getattr(retrieval, "queries_used", None) if known else None),
        "extract_attempts": _diag_count(extract_attempts),
        "extract_successes": _diag_count(opened),
        "extract_failures": _diag_count(fetch_errors),
        "empty_results": _diag_count(
            getattr(retrieval, "empty_results", None) if known else None),
        "irrelevant_results": _diag_count(
            getattr(retrieval, "irrelevant_results", None) if known else None),
        "off_topic_sources_dropped": _diag_count(
            getattr(retrieval, "off_topic_sources_dropped", None)
            if known else None),
        "relevant_evidence_count": _diag_count(
            getattr(retrieval, "refs_collected", None) if known else None),
        "citable_evidence_count": citable,
        "budget_exhausted": (bool(getattr(retrieval, "budget_exhausted", False))
                             if known else _DIAG_UNKNOWN),
        "fetch_skipped_deadline": _diag_count(
            getattr(retrieval, "fetch_skipped_deadline", None)
            if known else None),
        "retrieval_class": str(retrieval_state or ""),
        "technical_reason": str(getattr(verdict, "reason", "") or ""),
        # FC-07.1 (corrective 05.11.2026): все attempted queries прогона —
        # в приватной диагностике под correlation_id события (emit_evidence_
        # diagnostics); это деперсонализированные поисковые строки, а не
        # текст приватного чата. Причины отказа кандидатов — счётчиками
        # off_topic/stale/irrelevant выше; цепочка claim_id → evidence_id →
        # verdict живёт в coverage/parts прогона (record_temporal_run).
        "attempted_queries": [
            str(q)[:160] for q in
            (tuple(getattr(retrieval, "attempted_queries", ()) or ())
             if known else ())][:16],
        # S15-FC-EVIDENCE: фактическая доставка evidence в модель — числа и
        # маршрут (R17: без текстов и ключей). divergence БД↔payload виден как
        # delivered_rows vs citable_evidence_count.
        "evidence_delivery": delivery_meta,
    }


def emit_evidence_diagnostics(*, chat_id: int | None, retrieval,
                              retrieval_state: str, evidence, verdict,
                              pipeline_run_id: str | None = None,
                              delivery=None) -> dict:
    """§11.3: одно событие диагностики на прогон (fail-open)."""
    fields = evidence_diagnostics(retrieval=retrieval,
                                  retrieval_state=retrieval_state,
                                  evidence=evidence, verdict=verdict,
                                  delivery=delivery)
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "factcheck_diagnostics",
            outcome="success" if evidence else "skipped", level="INFO",
            component="factcheck.evidence", chat_id=chat_id,
            pipeline_run_id=str(pipeline_run_id or "") or None,
            entity_ids=fields)
    except Exception:      # pragma: no cover — событие не рвёт вердикт
        logger.debug("[factcheck] diagnostics event failed", exc_info=True)
    return fields


def envelope_retrieval_state(*, evidence, retrieval, results_text: str,
                             internal_failure_cause: str | None) -> str:
    """Класс исхода retrieval на envelope-пути (единая точка, §11.2).

    Порядок заморожен контрактом §3.3: существует документированная
    evidence-карта → ok; иначе — по фактическим метрикам стадии. Отдельно
    (ES-2): «внутренний поиск что-то нашёл, ссылок нет» — это ограничение
    цитируемости, а НЕ доказанный сбой парсинга."""
    if evidence:
        return RETRIEVAL_OK
    if retrieval is not None:
        return classify_retrieval(retrieval)
    if str(results_text or "").strip():
        return RETRIEVAL_NO_RESULTS
    if internal_failure_cause in ("empty_results", "irrelevant_results"):
        return RETRIEVAL_NO_RESULTS
    if internal_failure_cause:
        return RETRIEVAL_SEARCH_FAILED
    return RETRIEVAL_NOT_RUN


def emit_target_trace(publication, *, chat_id=None, trigger_tg_message_id=None,
                      delivery_reply_to=None, envelope=None,
                      extra: dict | None = None, route: str = "",
                      component: str = "factcheck.target") -> dict:
    """§10.3/§11.3: трасса цели/медиа/claim из фактического состояния.

    Только коды и ID; текстов реплик, снимков и base64 здесь нет. Пустое
    значение означает «резолвер этого не устанавливал» — не подставляем
    правдоподобный флаг."""
    fields: dict = {}
    if publication is not None:
        try:
            fields.update(publication.trace_fields())
        except Exception:      # pragma: no cover — трасса не рвёт ответ
            logger.debug("[factcheck] trace fields failed", exc_info=True)
    fields.update({
        "route": str(route),
        "trigger_tg_message_id": trigger_tg_message_id,
        "delivery_reply_to": delivery_reply_to,
    })
    if envelope is not None and publication is not None:
        # I3 (§1.5): вердикт и поиск читают РОВНО текст публикации.
        fields["envelope_claim_matches_publication"] = bool(
            str(getattr(envelope, "claim_text", "")) == str(publication.text))
        fields["envelope_target_matches_publication"] = bool(
            getattr(envelope, "target_tg_message_id", None)
            == publication.target_tg_message_id)
        fields["claim_anchor_tg_message_id"] = getattr(
            envelope, "claim_anchor_tg_message_id", None)
    if extra:
        fields.update(extra)
    try:
        logger.info("[factcheck_target] %s | chat=%s | %s", route or "-",
                    chat_id, " | ".join(f"{key}={fields[key]}"
                                        for key in sorted(fields)))
    except Exception:          # pragma: no cover
        pass
    try:
        from services import mca_events
        mca_events.emit_mca_event(
            "factcheck_target", outcome="success", level="INFO",
            component=component, chat_id=chat_id, entity_ids=fields)
    except Exception:          # pragma: no cover — событие не рвёт ответ
        logger.debug("[factcheck] target trace event failed", exc_info=True)
    return fields


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


def _verdict_is_substantive(verdict) -> bool:
    """Содержательный вывод: положительный enum на верхнем уровне или хотя
    бы в одной части (§7.2: содержательный анализ и его отсутствие —
    разные ситуации вербализации)."""
    try:
        if verdict.factual_verdict in ("supported", "refuted", "mixed"):
            return True
        return any(isinstance(p, dict) and p.get("factual_verdict")
                   in ("supported", "refuted", "mixed")
                   for p in (verdict.parts or ()))
    except Exception:          # pragma: no cover — метаданные не рвут вердикт
        return False


# ── ASAP-FC-EVIDENCE-STYLE-02 §3/§4: покрытие ПО КАЖДОМУ claim ──────────────
# Сервер не выдумывает подтверждение: роль/итог берутся из retrieval-слоя
# (claim → привязанные EvidenceRef с ролью), модель сохраняет право не
# подтверждать часть. Задача этой стадии — не потерять подтверждённые части
# и дать КАЖДОМУ пробелу конкретную причину вместо общего «данных
# недостаточно».

#: §4: детализированный исход → человеческая формулировка (публичная речь
#: различает технический сбой, отсутствие источников и недоказанное число).
CLAIM_STATUS_HUMAN = {
    "verified": "источник подтверждает",
    "refuted": "источники утверждают обратное",
    "partial": "подтверждено частично",
    "evidence_conflicting": "источники расходятся",
    "evidence_insufficient_for_exact_number":
        "конкретное число/сумма не подтверждены",
    "no_relevant_sources": "подходящих источников не нашлось",
    "source_extract_failed": "источник не удалось открыть (технический исход)",
    "provider_error": "поиск не ответил — технический сбой",
    "deadline_exceeded": "поиск прерван по лимиту времени",
    "search_not_started": "пункт не проверялся",
    "claim_unidentified": "проверяемая часть не опознана",
}

_CLAIM_POSITIVE = ("supported", "refuted", "mixed")


def _part_text_key(text) -> str:
    """Нормализованный ключ текста части (для сопоставления с claim)."""
    return re.sub(r"\s+", " ", str(text or "").strip().lower())[:80]


def _claim_part_match(part: dict, claim) -> bool:
    part_id = str(part.get("part_id") or "")
    if part_id and part_id == str(getattr(claim, "claim_id", "")):
        return True
    key = _part_text_key(part.get("text"))
    claim_key = _part_text_key(getattr(claim, "text", ""))
    if not key or not claim_key:
        return False
    return key == claim_key or key.startswith(claim_key[:40]) \
        or claim_key.startswith(key[:40])


def claim_payload_rows(coverage) -> list[dict]:
    """Компактные строки покрытия для payload вербализатора (§5: подача)."""
    rows: list[dict] = []
    for cov in coverage or ():
        claim = getattr(cov, "claim", None)
        rows.append({
            "claim_id": str(getattr(claim, "claim_id", "") or ""),
            "text": str(getattr(claim, "text", "") or ""),
            "outcome": str(getattr(cov, "outcome", "") or ""),
            "search_status": str(getattr(cov, "search_status", "") or ""),
            "status": CLAIM_STATUS_HUMAN.get(
                str(getattr(cov, "status_detail", "") or ""), ""),
            "gap": str(getattr(cov, "gap_note", "") or ""),
            "sources": len([e for e in (getattr(cov, "evidence", ()) or ())
                            if getattr(e, "role", "") in
                            ("supports", "contradicts", "qualifies")]),
        })
    return rows


def merge_claim_coverage(verdict: tf.TemporalVerdict, coverage, evidence
                         ) -> tf.TemporalVerdict:
    """§3.1/§3.5: свести покрытие частей с вердиктом модели.

    Правила (no-false-acceptance в обе стороны):

    * подтверждённая часть остаётся подтверждённой — две проблемные части не
      превращают остальные в «данных недостаточно»;
    * часть без подтверждающего ИМЕННО её источника не может остаться
      положительной (понижение до существующего enum);
    * ссылки части ограничиваются claim-привязанными evidence текущего
      прогона (чужая ссылка не приписывается тезису);
    * каждый пробел получает конкретную причину/пояснение из retrieval-слоя;
    * Reviewer F1: если МОДЕЛЬ по существу сказала `insufficient_evidence`,
      серверные части покрытия НЕ делают вывод положительным — никакого
      апгрейда `insufficient → mixed/supported` от синтезированных частей.
    """
    parts = [dict(p) for p in (verdict.parts or ()) if isinstance(p, dict)]
    model_factual = str(verdict.factual_verdict or "")
    # Положителен ли вывод МОДЕЛИ по существу: либо верхний enum, либо хотя бы
    # одна её часть. Если нет — серверные части не делают вывод положительным.
    model_positive = model_factual in _CLAIM_POSITIVE or any(
        str(p.get("factual_verdict") or "") in _CLAIM_POSITIVE for p in parts)
    # Единственный владелец сопоставления «итог claim → существующий enum» —
    # планировщик (параллельной системы вердиктов не создаём).
    from services.factcheck_planner import CLAIM_OUTCOME_TO_VERDICT
    matched: set[int] = set()
    for cov in coverage or ():
        claim = getattr(cov, "claim", None)
        if claim is None:
            continue
        bound = [str(x) for x in (getattr(cov, "citation_ids", ()) or ())]
        # Роль ссылки важнее её наличия: «событие есть, числа нет»
        # (qualifies) не может удерживать положительный вердикт части (§3.3/§6).
        supporting = [str(getattr(e, "evidence_id", "") or "")
                      for e in (getattr(cov, "displayable_evidence", ()) or ())
                      if str(getattr(e, "role", "")) == "supports"]
        contradicting = [str(getattr(e, "evidence_id", "") or "")
                         for e in (getattr(cov, "displayable_evidence", ()) or ())
                         if str(getattr(e, "role", "")) == "contradicts"]
        index = next((i for i, part in enumerate(parts)
                      if _claim_part_match(part, claim)), None)
        detail = str(getattr(cov, "status_detail", "") or "")
        gap = str(getattr(cov, "gap_note", "") or "")
        metadata = {
            "claim_id": str(getattr(claim, "claim_id", "") or ""),
            "claim_type": str(getattr(claim, "claim_type", "") or ""),
            "search_status": str(getattr(cov, "search_status", "") or ""),
            "claim_outcome": str(getattr(cov, "outcome", "") or ""),
            "status_detail": detail,
            "gap_note": gap,
            "claim_reason": str(getattr(cov, "reason_code", "") or ""),
        }
        if index is None:
            outcome_verdict = CLAIM_OUTCOME_TO_VERDICT.get(
                str(getattr(cov, "outcome", "") or ""),
                "insufficient_evidence")
            if not model_positive and \
                    outcome_verdict in _CLAIM_POSITIVE:
                # §F1: серверная часть не поднимает общий вывод модели.
                outcome_verdict = "insufficient_evidence"
                gap = gap or ("источники по этому пункту есть, но общий "
                              "вывод проверки — недостаточно данных")
            parts.append({
                "part_id": str(getattr(claim, "claim_id", "") or ""),
                "text": str(getattr(claim, "text", "") or ""),
                "factual_verdict": outcome_verdict,
                "evidence_refs": list(bound),
                **{**metadata, "gap_note": gap}})
            continue
        matched.add(index)
        part = parts[index]
        part_refs = [str(r) for r in (part.get("evidence_refs") or ())
                     if isinstance(r, str)]
        if part_refs:
            # §3.3: часть цитирует только доказательства СВОЕГО тезиса.
            allowed = [r for r in part_refs if r in bound] or (
                [] if bound else part_refs)
            part["evidence_refs"] = allowed
        elif bound:
            part["evidence_refs"] = list(bound)
        part_verdict = str(part.get("factual_verdict") or "")
        part_ids = {str(r) for r in (part.get("evidence_refs") or ())
                    if isinstance(r, str)}
        if part_verdict == "supported":
            backed = bool(part_ids & set(supporting))
        elif part_verdict == "refuted":
            backed = bool(part_ids & set(contradicting))
        elif part_verdict == "mixed":
            backed = bool(part_ids)
        else:
            backed = True
        if not backed:
            # Исключение — помеченное основание самостоятельной проверки
            # (расчёт/логика), а не «ссылка на похожую тему».
            basis_marked = any(
                str(k).startswith("basis")
                for k in (verdict.uncertainty or {}))
            if not basis_marked:
                part["factual_verdict"] = "insufficient_evidence"
                part.setdefault(
                    "gap_note",
                    gap or "источника, подтверждающего именно этот пункт, "
                           "не нашлось")
                if not part.get("status_detail"):
                    part["status_detail"] = detail or "no_relevant_sources"
        part.update(metadata)
        if part.get("factual_verdict") == "insufficient_evidence" and not \
                part.get("gap_note"):
            part["gap_note"] = gap
    if not matched and not parts:
        return verdict
    factual = tf._aggregate_factual_verdict(verdict.factual_verdict,
                                           tuple(parts),
                                           basis_marked=any(
                                               str(k).startswith("basis")
                                               for k in (verdict.uncertainty
                                                         or {})))
    if not model_positive:
        # §F1: агрегация не поднимает вывод модели за счёт серверных частей;
        # честная неопределённость остаётся, конкретные пробелы видны в parts.
        factual = "insufficient_evidence"
    # FC-04.7 (corrective 05.11.2026): положительный/mixed вердикт без хотя
    # бы одного ПРЯМОГО подтверждающего evidence по сути запрещён. Частичный
    # случай остаётся честным insufficient_evidence с разбором в parts;
    # помеченное основание самостоятельной проверки (basis*, формальный
    # вывод) прямую ссылку заменяет.
    if factual in ("supported", "mixed") and not any(
            str(k).startswith("basis") for k in (verdict.uncertainty or {})):
        direct_exists = any(
            str(getattr(e, "role", "")) == "supports"
            for cov in coverage or ()
            for e in (getattr(cov, "displayable_evidence", ()) or ()))
        if not direct_exists:
            factual = "insufficient_evidence"
            uncertainty = dict(verdict.uncertainty or {})
            uncertainty.setdefault(
                "positive_without_direct_support",
                "прямого подтверждающего источника по существу тезиса в этом "
                "прогоне нет — подтверждённой остаётся только отмеченная "
                "часть разбора, общий вывод не поднимается")
            parts = [dict(p) for p in parts]
            return dataclasses.replace(verdict, factual_verdict=factual,
                                       parts=tuple(parts),
                                       uncertainty=uncertainty,
                                       reason=verdict.reason)
    reason = verdict.reason
    if factual in _CLAIM_POSITIVE and str(reason or "") in \
            _TECHNICAL_RETRIEVAL_REASONS:
        # Содержательный разбор частей не маскируется техническим заголовком
        # (реальная оговорка остаётся в uncertainty).
        reason = None
    return dataclasses.replace(verdict, factual_verdict=factual, parts=tuple(parts),
                               reason=reason)


def _claim_coverage_payload(coverage) -> str:
    """`<claim_coverage>` для analyst-payload (§3.1): статус каждой части ДО
    вердикта — чтобы анализ не смешивал «не проверено технически» с «нет
    данных», а спорное число разбирал отдельно от события."""
    rows = []
    for cov in coverage or ():
        claim = getattr(cov, "claim", None)
        if claim is None:
            continue
        rows.append({
            "claim_id": getattr(claim, "claim_id", ""),
            "text": getattr(claim, "text", ""),
            "claim_type": getattr(claim, "claim_type", ""),
            "timeframe": getattr(claim, "timeframe", ""),
            "search_status": getattr(cov, "search_status", ""),
            "status_detail": getattr(cov, "status_detail", ""),
            "outcome": getattr(cov, "outcome", ""),
            "gap": getattr(cov, "gap_note", ""),
            "evidence_ids": list(getattr(cov, "citation_ids", ()) or ()),
        })
    if not rows:
        return ""
    return ("<claim_coverage>" + escape_xml_text(json.dumps(
        rows, ensure_ascii=False)) + "</claim_coverage>")


def _analysis_context_for_empty_evidence(retrieval_state: str | None) -> str:
    """§2.4/§2.5: analyst-payload при пустом внешнем evidence — статус
    поиска + явное разрешение самостоятельной проверки + рамка
    происхождения вывода. Существующая схема вердикта не расширяется."""
    note = _RETRIEVAL_SEARCH_NOTE.get(
        str(retrieval_state or ""), "подходящих внешних материалов не найдено")
    return (
        "<analysis_context>\n"
        f"Внешний поиск в этом прогоне: {note}. Внешних доказательств НЕТ.\n"
        "Это НЕ запрещает анализ: утверждение можно проверять само по "
        "себе — логическая проверка (следует ли вывод из предпосылок), "
        "математическая проверка (числа, формулы, соотношения, арифметика, "
        "размерности), техническое рассуждение по известным принципам, "
        "проверка внутренней согласованности, условный вывод (при каких "
        "условиях утверждение может быть истинным), оценка правдоподобия "
        "с явным отделением от подтверждения, проверка по доступным "
        "локальным материалам (контекст беседы, история обсуждения).\n"
        "Запрещено: выдумывать источники, URL, измерения и характеристики; "
        "ссылаться на evidence-ID (в этом прогоне выдержек нет); выдавать "
        "правдоподобие или собственную память модели за проверенный факт.\n"
        "Происхождение вывода: для вывода, сделанного без внешних "
        'источников, добавь в uncertainty пометку "basis": "внутренняя '
        'проверка: <что именно — расчёт/логика/принцип>". Положительный '
        "вердикт (supported/refuted/mixed) без этой пометки понижается "
        "сервером до insufficient_evidence. Внешний факт, который нельзя "
        "проверить без поиска, — insufficient_evidence с пояснением, что "
        "удалось выяснить и какой информации не хватает.\n"
        "</analysis_context>"
    )


def _downgrade_unbacked_positive(verdict: tf.TemporalVerdict,
                                 evidence) -> tf.TemporalVerdict:
    """§2.4/§2.6 (no-false-acceptance в ОБОЕ стороны): без внешнего evidence
    положительный вердикт стоит ТОЛЬКО с явной пометкой основания
    самостоятельной проверки (uncertainty ``basis*``). «Модель вспомнила
    похожую цифру» → честная неопределённость (существующий enum); а
    правильно выполненный расчёт по заданным данным понижения НЕ получает
    (модель помечает basis — F7/F12). Части с положительным вердиктом без
    пометки понижаются тем же правилом (прецедент §3.5: положительный
    вердикт части без доказательства запрещён)."""
    if evidence or verdict.factual_verdict not in (
            "supported", "refuted", "mixed"):
        return verdict
    uncertainty = dict(verdict.uncertainty or {})
    if any(str(k).startswith("basis") for k in uncertainty):
        return verdict
    uncertainty["unbacked_positive"] = (
        "внешние доказательства в этом прогоне отсутствуют, основание "
        "самостоятельной проверки не отмечено — подтверждением такой вывод "
        "считать нельзя")
    parts = tuple(
        p if not (isinstance(p, dict) and p.get("factual_verdict")
                  in ("supported", "refuted", "mixed"))
        else {**p, "factual_verdict": "insufficient_evidence"}
        for p in (verdict.parts or ()))
    return dataclasses.replace(
        verdict, factual_verdict="insufficient_evidence",
        uncertainty=uncertainty, parts=parts)


# ═══════════════════════════════════════════════════════════════════════════
# RLR (REMOVE-LEGACY-REPHRASING R-03.4/R-06/§3.4/§8): numeric-контракт
# data-стадии фактчека.
#
# Числа финального текста обязаны происходить из СТРУКТУРНЫХ данных прогона:
# ``MetricResult``/``NumericClaim`` (измерения этого хода), структурный анализ
# (claim/findings/evidence с provenance), сам проверяемый тезис и даты
# envelope. Валидированный набор чисел явно уходит Writer'у в payload ДО
# генерации, а после генерации выполняется детерминированная (без LLM)
# сверка. Неподтверждённое число НЕ переписывается, не вырезается из фразы и
# не заменяется «проверенной формулировкой»: вместо пересказа публикуется
# структурный отчёт той же проверки (вердикт + утверждения + источники).
# Post-L2 numeric-правка (`apply_numeric_guard`/numeric-retry) в фактчеке
# поэтому не применяется (R-04.2), а честность обеспечивается до публикации.
# ═══════════════════════════════════════════════════════════════════════════

#: Токен числа: разделители тысяч, десятичная запятая/точка, диапазон/дробь.
#: Дата ("15.06.2025") остаётся одним токеном — сравнение каноническое.
NUMBER_TOKEN_RE = re.compile(r"\d+(?:[ \u00a0\u202f'.,/-]\d+)*")
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_NUMBERS_PAYLOAD_CAP = 24
_NUMERIC_REPORT_SOURCES_CAP = 3
#: Служебный код исхода: число в пересказе не подтверждено структурой.
NUMBER_UNVALIDATED = "factcheck_number_unvalidated"

#: Честная рамка структурного отчёта (публичный текст, не инструкция модели).
NUMERIC_REPORT_NOTE = (
    "Пересказ не публикую: в нём были числа, которых нет в проверенных "
    "данных. Ниже — только результат структурной проверки.")

_SYSTEM2_STATUS_WORDS = {
    "true": "подтверждается",
    "false": "не подтверждается",
    "misleading": "вводит в заблуждение",
    "unverifiable": "проверить не удалось",
}

_PART_FACTUAL_WORDS = {
    "supported": "подтверждается",
    "refuted": "не подтверждается",
    "mixed": "подтверждается частично",
    "insufficient_evidence": "данных недостаточно",
}


@dataclasses.dataclass(frozen=True)
class NumericBinding:
    """Число, привязанное к структурному источнику прогона (provenance).

    ``source``: ``measurement`` (MetricResult/NumericClaim хода), ``evidence``
    (выдержка источника), ``claim`` (проверяемый тезис), ``analysis``
    (структурный разбор), ``date`` (даты envelope), ``part`` (компонент даты).
    ``ref`` — metric_id/evidence_id/имя блока; выдуманных источников нет.
    """
    canon: str
    raw: str
    source: str
    ref: str
    unit: str = ""


def _canon_number(token) -> str:
    """Канонизация числа: пробелы/NBSP/' — разделители тысяч, ',' → '.'."""
    text = (str(token).replace(" ", "").replace("\u00a0", "")
            .replace("\u202f", "").replace("'", ""))
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    return text


def number_tokens(text) -> list[str]:
    """Все числовые токены текста в порядке появления (детерминированно)."""
    return [m.group(0) for m in NUMBER_TOKEN_RE.finditer(str(text or ""))]


def _fmt_ts_date(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(
            int(ts), datetime.timezone.utc).strftime("%d.%m.%Y")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _bind_numbers(target: dict, text, *, source: str, ref: str,
                  unit: str = "") -> None:
    """Добавить привязки чисел текста (первое вхождение держит provenance)."""
    for raw in number_tokens(text):
        canon = _canon_number(raw)
        if not canon:
            continue
        target.setdefault(canon, NumericBinding(
            canon=canon, raw=raw, source=source, ref=ref,
            unit=str(unit or "")))
        # Компоненты даты ("12.05.2021" → 12/05/2021): пересказ даты словами
        # не становится «выдуманным числом».
        for piece in re.split(r"[./:-]", raw):
            part = _canon_number(piece)
            if part and part != canon:
                target.setdefault(part, NumericBinding(
                    canon=part, raw=piece, source="part", ref=ref))


def build_numeric_contract(
    *,
    claim_text: str = "",
    writer_payload: str = "",
    metric_results=(),
    evidence_rows=(),
    temporal_context=None,
) -> tuple[NumericBinding, ...]:
    """Собрать ПРОВЕРЯЕМЫЙ набор чисел прогона (data-stage, без LLM).

    ``writer_payload`` — именно то структурное представление, которое увидит
    Writer: число, которого там нет, он не мог взять из facts-слоя.
    ``metric_results`` — per-turn реестр измерений (MetricResult → NumericClaim
    с metric_id/unit); ``evidence_rows`` — выдержки источников с evidence_id;
    ``temporal_context`` — envelope (даты публикации/заявленного периода).
    Никогда не бросает: любая ошибка источника просто не даёт привязки.
    """
    bindings: dict[str, NumericBinding] = {}
    _bind_numbers(bindings, claim_text, source="claim", ref="claim")
    _bind_numbers(bindings, writer_payload, source="analysis",
                  ref="writer_payload")
    for result in metric_results or ():
        try:
            from services import chat_statistics as _cs
            claims = _cs.claims_for_result(result)
        except Exception:      # не MetricResult/сбой реестра — нет привязки
            continue
        for claim in claims:
            value = getattr(claim, "value", None)
            if value is None:
                continue
            canon = _canon_number(value)
            if not canon:
                continue
            bindings.setdefault(canon, NumericBinding(
                canon=canon, raw=str(value), source="measurement",
                ref=str(getattr(claim, "metric_id", "") or "measurement"),
                unit=str(getattr(claim, "unit", "") or "")))
    for row in evidence_rows or ():
        if not isinstance(row, dict):
            continue
        ref = str(row.get("evidence_id") or row.get("url") or "evidence")
        _bind_numbers(bindings, row.get("support"), source="evidence",
                      ref=ref)
        date = _fmt_ts_date(row.get("published_at"))
        if date:
            _bind_numbers(bindings, date, source="date", ref=ref)
    if temporal_context is not None:
        env = temporal_context
        for ts in (getattr(env, "original_published_at", None),
                   getattr(env, "repost_received_at", None),
                   getattr(env, "claim_period_from", None),
                   getattr(env, "claim_period_to", None)):
            date = _fmt_ts_date(ts)
            if date:
                _bind_numbers(bindings, date, source="date",
                              ref="temporal_context")
    return tuple(bindings.values())


def numeric_contract_payload(bindings) -> dict:
    """Блок payload Writer'а: какие числа проверены и чем именно.

    Список — только проверяемые привязки (измерения/источники/даты), без
    тезиса и структурного разбора: у Writer'а они уже есть в самой структуре.
    Пустой список честен: измерений и датированных выдержек не было.
    """
    checked: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for binding in bindings or ():
        if binding.source not in ("measurement", "evidence", "date"):
            continue
        key = (binding.canon, binding.source, binding.ref)
        if key in seen:
            continue
        seen.add(key)
        item = {"value": binding.canon, "source": binding.source,
                "ref": binding.ref}
        if binding.unit:
            item["unit"] = binding.unit
        checked.append(item)
        if len(checked) >= _NUMBERS_PAYLOAD_CAP:
            break
    return {
        "checked": checked,
        "note": ("числа из checked проверены по структурным данным этого "
                 "прогона; остальные числа ответа не проверены"),
    }


def _number_is_bound(raw: str, allowed: frozenset[str]) -> bool:
    canon = _canon_number(raw)
    if canon in allowed:
        return True
    parts = [p for p in re.split(r"[./:-]", raw) if p.strip()]
    if len(parts) > 1:
        return all(_canon_number(p) in allowed for p in parts)
    return False


def unvalidated_numbers(text, bindings) -> tuple[str, ...]:
    """Числа текста, которых НЕТ в проверенном наборе (детерминированно)."""
    allowed = frozenset(b.canon for b in (bindings or ()))
    return tuple(raw for raw in number_tokens(text)
                 if not _number_is_bound(raw, allowed))


def report_sources_from_text(*texts, limit: int = _NUMERIC_REPORT_SOURCES_CAP
                             ) -> tuple[str, ...]:
    """URL из материалов прогона (реальная выдача; ничего не изобретаем)."""
    out: list[str] = []
    for text in texts:
        for match in _URL_IN_TEXT_RE.finditer(str(text or "")):
            url = match.group(0).rstrip(".,;:!?)]}")
            if url not in out:
                out.append(url)
            if len(out) >= limit:
                return tuple(out)
    return tuple(out)


def deterministic_analysis_report(data: dict, *, sources=()) -> str:
    """Структурный отчёт вместо пересказа (без LLM): вердикт + утверждения.

    Текст собран ТОЛЬКО из проверенной структуры Stage-1 (claim/findings) и
    ссылок фактической выдачи; числа в нём по построению привязаны к этой же
    структуре. Verdict-класс не меняется и не «сглаживается».
    """
    lines: list[str] = []
    verdict = str((data or {}).get("verdict") or "").strip()
    if verdict:
        lines.append(f"Вердикт: {verdict}")
    for item in (data or {}).get("findings") or ():
        if not isinstance(item, dict):
            continue
        assertion = str(item.get("assertion") or "").strip()
        if not assertion:
            continue
        status = _SYSTEM2_STATUS_WORDS.get(str(item.get("status") or ""), "")
        when = str(item.get("human_time") or "").strip()
        tail = f" — {status}" if status else ""
        if when and when != "без даты":
            tail += f" ({when})"
        lines.append(f"• {assertion}{tail}")
    sources = tuple(s for s in (sources or ()) if str(s or "").strip())
    if sources:
        lines.append("Источники: " + ", ".join(sources))
    else:
        lines.append("Проверяемых ссылок в этот раз получить не удалось.")
    lines.append(NUMERIC_REPORT_NOTE)
    return "\n".join(lines).strip()


def deterministic_temporal_report(env, verdict, *, evidence=(),
                                  reason_code: str | None = None) -> str:
    """Структурный отчёт temporal-ветки (без LLM): вердикт + части + даты.

    ``factual_verdict``/``temporal_status`` берутся из уже проверенного
    ``TemporalVerdict`` как есть: `insufficient_evidence` не превращается в
    `mixed`/`supported`, `refuted` не смягчается.
    """
    pieces = ["Вердикт: " + _human_factual_verdict(verdict.factual_verdict)
              + "."]
    period = _human_evaluated_period(verdict.evaluated_period)
    if period:
        pieces.append(f"Проверялось {period}.")
    orig = _fmt_ts_date(getattr(env, "original_published_at", None))
    date_source = str(getattr(env, "date_source", "") or "")
    if orig and date_source in ("telegram_origin", "telegram_message"):
        kind = "оригинала" if date_source == "telegram_origin" else "сообщения"
        pieces.append(f"Дата {kind}: {orig}.")
    part_lines: list[str] = []
    for part in (verdict.parts or ()):
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or part.get("note") or "").strip()
        if not text:
            continue
        label = _PART_FACTUAL_WORDS.get(
            str(part.get("factual_verdict") or ""), "")
        part_lines.append(f"• {text}" + (f" — {label}" if label else ""))
        if len(part_lines) >= 4:
            break
    if part_lines:
        pieces.append("Утверждения:\n" + "\n".join(part_lines))
    links = report_sources_from_text(
        *(str((row or {}).get("url") or "")
          for row in (evidence or ()) if isinstance(row, dict)))
    if links:
        pieces.append("Источники: " + ", ".join(links))
    technical = _RETRIEVAL_CAVEAT.get(str(reason_code or ""))
    if technical:
        pieces.append(technical[0].upper() + technical[1:] + ".")
    pieces.append(NUMERIC_REPORT_NOTE)
    return " ".join(pieces).strip()


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
        # UR-C-CLOCK (UR-26.4): время ОЦЕНКИ из ChatClock чата — единый
        # снапшот на проверку (single/stage1/stage2); дата публикации
        # источника остаётся отдельным полем в СВОЁМ поясе (UR-27 не
        # подменяется). chat_id None (unit-вызовы) → блок не выдаётся,
        # причина честно логируется.
        _fc_snap = None
        if chat_id is not None:
            try:
                _fc_snap = await _cclock.snapshot(chat_id)
                user = _cclock.append_time_block(
                    user, _fc_snap, phase=_cclock.PHASE_ANSWER,
                    source_label=None)
            except Exception:      # pragma: no cover - fail-open honest
                logger.warning("[factcheck] chat clock unavailable — no "
                               "time block | chat=%s", chat_id, exc_info=True)
                _fc_snap = None
        if getattr(settings, "SYSTEM2_FACTCHECK_ENABLED", True):
            two_call = await self._check_claim_two_call(
                target_text, user, rag, results, chat_id, max_symbols,
                correlation_id, time_snap=_fc_snap)
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
        # ASAP-FC-VOICE-01 / A (§3): слои владельца приходят из единственной
        # точки сборки (манифест с причиной пропуска), ручной склейки нет.
        genre_canon = system_prompt.replace("{max_symbols}", str(max_symbols))
        # EVOL §5 (W5): одиночный путь — тоже публичная Writer-фаза. Критика
        # здесь self-assessed: структуры проверенных частей нет (Writer сам и
        # аналитик), поэтому инструкция требует критиковать только уже
        # названные им ошибки и запрещает выдуманное опровержение. Политика —
        # по наличию доказательств прогона. Форма раздела снята (голос внутри
        # рассуждения), гейт политики сохранен.
        critique_block = await _critique_section_block(
            chat_id, critique_policy_for_verdict(
                factual_verdict=None,
                has_evidence=bool(str(results or "").strip())))
        genre_canon = _with_critique_block(genre_canon, critique_block)
        system = await _compose_genre_speech(
            chat_id, writer="factcheck_single", base_prompt=genre_canon)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw, used_tools = await self._invoke_llm(
            messages, target_text, chat_id, correlation_id=correlation_id,
            step="single")
        # UR-26.4: payload-событие одиночного пути 10.21 (kill-switch или
        # fallback после двухвызовного) — та же стадия stage1 с честным
        # кодом маршрута; наличие ChatClock-блока берётся из фактического
        # payload'а вызова.
        _tpe.emit_stage(
            _tpe.STAGE_FC_STAGE1, outcome="success", chat_id=chat_id,
            correlation_id=correlation_id, model=_tpe.llm_model(self.llm),
            provider=_tpe.llm_provider(self.llm),
            finish_reason="generated",
            chars=len(str(raw or "")),
            text_digest=_tpe.text_digest(str(raw or "")),
            clock=_tpe.clock_meta_messages(messages, chat_id=chat_id),
            decision=("single_path:tool_loop" if used_tools
                      else "single_path:plain"))
        return self._finalize(raw, used_tools, rag, results)

    async def _check_claim_two_call(
        self, target_text: str, user: str, rag: str, results: str,
        chat_id: int | None, max_symbols: int,
        correlation_id: str | None = None, *, time_snap=None,
    ) -> str | None:
        """System 2 фактчека. ``None`` → вызывающий уходит на 10.21.

        UR-C-CLOCK: Stage-1 получает блок времени в общем ``user``; Stage-2
        (Writer) — тот же снапшот оценки (один на проверку)."""
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
            # UR-26.4: транспортный сбой Stage-1 — явное событие с кодом
            # fallback-решения (пользователь получает ответ по 10.21 ниже).
            _tpe.emit_stage(
                _tpe.STAGE_FC_STAGE1, outcome="error", chat_id=chat_id,
                correlation_id=correlation_id,
                model=_tpe.llm_model(self.llm),
                provider=_tpe.llm_provider(self.llm),
                finish_reason=f"llm_{type(exc).__name__}",
                clock=_tpe.clock_meta_messages(
                    analyst_messages, chat_id=chat_id),
                decision="stage1_error:fallback_single")
            return None
        tool_context = str(getattr(raw_analyst, "tool_context", "") or "")
        anchors = collect_allowed_anchors(
            self._trusted_text(rag, results, tool_context))
        analyst_text = strip_reasoning_tags(str(raw_analyst))
        analyst_text, _gstats = strip_phantom_tags(analyst_text, anchors)
        data = parse_factcheck_analysis(analyst_text)
        # UR-26.4: payload-событие Stage-1 (аналитик JSON) — модель/
        # провайдер, маршрут tool-loop/plain, размер/digest ответа
        # аналитика, наличие ChatClock-блока в фактическом payload'е.
        # R17: только числа/коды/digest (без текста анализа).
        _tpe.emit_stage(
            _tpe.STAGE_FC_STAGE1,
            outcome="success" if data is not None else "error",
            chat_id=chat_id, correlation_id=correlation_id,
            model=_tpe.llm_model(self.llm),
            provider=_tpe.llm_provider(self.llm),
            finish_reason="parsed_json" if data is not None
            else "parse_invalid",
            chars=len(str(analyst_text or "")),
            text_digest=_tpe.text_digest(str(analyst_text or "")),
            clock=_tpe.clock_meta_messages(
                analyst_messages, chat_id=chat_id),
            decision=("tool_loop" if used_tools else "plain")
            + ("" if data is not None else ":parse_invalid_fallback"))
        if data is None:
            logger.info(
                "factcheck system2: невалидный JSON аналитика — fallback | "
                "chat=%s", chat_id)
            return None
        response_mode = normalize_response_mode(data.get("response_mode"))
        modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True)
        # ASAP-FC-VOICE-01 / A (§1, §6 инвариант 6): OFF → ПРЕЖНЯЯ заводская
        # редакция вербализатора (байты прода 2.58.148), режимный блок и так
        # не подключается. Активная редакция — исторический голос жанра.
        verbalizer_template = (
            resolve_prompt("prompts.factcheck_verbalizer_system_prompt",
                           FACTCHECK_VERBALIZER_SYSTEM_PROMPT)
            if modes_on else PREV_FACTCHECK_VERBALIZER_VOICE01)
        verbalizer_base = verbalizer_template.replace(
            "{max_symbols}", str(max_symbols))
        # EVOL §5 (W5): жанровая директива критики — в ТОЙ ЖЕ публичной
        # Writer-фазе (второго LLM-вызова нет). Политика считается по
        # структуре проверенных findings: все подтверждены / не проверяемы →
        # директивы нет (выдуманный разгром запрещён). ASAP-FC-VOICE-01 / A:
        # директива действует внутри рассуждения, обязательного раздела с
        # фиксированным заголовком нет.
        critique_block = await _critique_section_block(
            chat_id, critique_policy_for_findings(data.get("findings")))
        verbalizer_base = _with_critique_block(verbalizer_base,
                                               critique_block)
        # UNIFIED-CORE → ASAP-FC-VOICE-01 / A: Core/Expression/Style/примеры
        # приходят из ОДНОЙ точки сборки (manifest с причиной пропуска).
        # Ручная склейка `compose_verbalizer_system(character_block=...)`
        # удалена: иначе owner-слои попадали бы в payload дважды.
        verbalizer_system = await _compose_genre_speech(
            chat_id, writer="factcheck_verbalizer",
            base_prompt=verbalizer_base)
        # RLR R-03.4/R-06/§3.4: проверенный набор чисел строится из
        # СТРУКТУРНЫХ данных (Stage-1 facts + MetricResult этого хода) и
        # отдаётся Writer'у ЯВНО — до генерации, а не правкой после неё.
        stage2_data = stage2_payload(data)
        numeric_bindings = build_numeric_contract(
            claim_text=target_text,
            writer_payload=json.dumps(stage2_data, ensure_ascii=False),
            metric_results=getattr(raw_analyst, "metric_results", None) or ())
        stage2_data["numbers"] = numeric_contract_payload(numeric_bindings)
        if time_snap is not None:
            # UR-C-CLOCK: Stage-2 получает тот же ChatClock-снапшот оценки.
            stage2_data["server_time"] = {
                "local": "%s %s, %s" % (
                    time_snap.local_datetime.strftime("%d.%m.%Y"),
                    time_snap.local_datetime.strftime("%H:%M"),
                    time_snap.weekday),
                "tz": time_snap.timezone,
                "as_of_utc": time_snap.as_of_utc.strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00"),
            }
        base_messages = [
            {"role": "system", "content": verbalizer_system},
            {"role": "user",
             # spec F3 §3.1: служебный response_mode в Stage-2 не утекает.
             "content": "АНАЛИЗ (JSON):\n" + json.dumps(
                 stage2_data, ensure_ascii=False)},
        ]

        async def _generate(messages):
            return await self.llm.generate(
                messages, module="factcheck", step="stage2",
                correlation_id=correlation_id)

        # F3 (ADR-1023-3): plain-канал → guard от таблиц (без запрета буллитов,
        # буллиты в фактческе жанром не запрещены).
        enabled_rules = (channel_enabled_rules("plain", response_mode)
                         if modes_on else None)
        # RLR R-04.2: post-L2 numeric-правки (`numeric_contract` →
        # retry/verified_phrase/снятие части) здесь НЕТ. Числа проверяются
        # data-стадией выше и детерминированной сверкой ниже; Writer-текст
        # не переписывается.
        text, stats = await verbalize_validated(
            _generate, base_messages, max_retries=2,
            enabled_rules=enabled_rules,
            dynamic_rules=anticliche_cache.get_rules() or None,
            metatext_reason=_metatext_retry_reason())
        logger.info(
            "factcheck system2 verbalizer | chat=%s | mode=%s | attempts=%d "
            "| retries=%d | hits=%d | fallback=%s", chat_id, response_mode,
            stats.get("attempts", 0), stats.get("retries", 0),
            len(stats.get("hits") or []), bool(stats.get("fallback")))
        # UR-26.4: payload-событие Stage-2 (вербализатор) — режим ответа
        # (response_mode, в т.ч. короткие формы), попытки/ретраи, размер/
        # digest текста, наличие ChatClock-блока в payload'е (Stage-2
        # получает время оценки полем server_time из того же снапшота —
        # честный код отсутствия блока в messages при наличии снапшота).
        _tpe.emit_stage(
            _tpe.STAGE_FC_STAGE2,
            outcome="error" if stats.get("fallback") else "success",
            chat_id=chat_id, correlation_id=correlation_id,
            model=_tpe.llm_model(self.llm),
            provider=_tpe.llm_provider(self.llm),
            finish_reason=("fallback" if stats.get("fallback")
                           else "generated"),
            chars=len(str(text or "")),
            text_digest=_tpe.text_digest(str(text or "")),
            clock=_tpe.clock_meta_messages(base_messages, chat_id=chat_id),
            decision=("mode=%s;attempts=%d;retries=%d;server_time=%s"
                      % (str(response_mode or "unset"),
                         int(stats.get("attempts", 0) or 0),
                         int(stats.get("retries", 0) or 0),
                         "snapshot" if time_snap is not None else "absent")),
            attempt=max(1, int(stats.get("attempts", 1) or 1)))
        if stats.get("fallback"):
            return None
        final_text = self._finalize_text(text, used_tools, tool_context,
                                        rag, results)
        # RLR §3.4/§8: неподтверждённое число не публикуется как факт и НЕ
        # правится в предложении — вместо пересказа идёт структурный отчёт.
        unverified = unvalidated_numbers(final_text, numeric_bindings)
        if unverified:
            logger.warning(
                "factcheck numeric | chat=%s | code=%s | unverified=%d | "
                "action=structural_report", chat_id, NUMBER_UNVALIDATED,
                len(unverified))
            return deterministic_analysis_report(
                data, sources=report_sources_from_text(results, tool_context))
        return final_text

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
        run_id: str | None = None,
    ) -> tf.TemporalRunResult:
        """Сквозной пайплайн `temporal.factcheck` (8 стадий, D15).

        ``retrieval`` (FC-UNIFY, owner 21.10.2026 §3.2): выдача единого
        retrieval-контура v2 (factcheck_planner.RetrievalOutcome) — внутренний
        temporal-поиск не дублируется (один поиск на прогон); evidence
        строится из структурных строк планировщика (включая primary-выдержки
        SafeFetcher). None → прежний внутренний поиск (теперь тоже смысловые
        запросы, FC-SEMQUERY).

        Raises: LLMBadResponseError (пустой ответ вербализатора на всех
        ветках) — вызывающий решает показ ошибки. Поиск НИКОГДА не делает
        утверждение подтверждённым/опровергнутым сам по себе (F-1/TH-5);
        при пустом evidence существующий аналитик продолжает проверку
        (логика/расчёт/согласованность, §2.4), а положительный вердикт без
        внешних доказательств и без помеченного основания понижается
        сервером до honest insufficient_evidence."""
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
        # §5.1: машинная причина неудачи внутреннего поиска ветки (пустая/
        # нерелевантная выдача ≠ недоступность провайдеров)
        internal_failure_cause = None
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
                except AllSearchEnginesFailedException as exc:
                    search_reason = "temporal_insufficient_evidence"
                    internal_failure_cause = str(
                        getattr(exc, "reason", "") or "provider_error")
                    continue
                except Exception:
                    search_reason = "temporal_insufficient_evidence"
                    internal_failure_cause = "provider_error"
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
        #
        # S15-FC-EVIDENCE: доставка строк считается по ЁМКОСТИ фактического
        # маршрута (единый resolver S4), а не по прежнему потолку 20 строк;
        # support не режется историческим 1200; остаток сохраняется
        # указателями и виден аналитику (`<evidence_delivery>`).
        retrieval_refs = ()
        if retrieval is not None:
            retrieval_refs = tuple(
                getattr(getattr(retrieval, "evidence_map", None),
                        "refs", ()) or ())
        route = _route_capacity(self.llm, "primary")
        fallback_route = _route_capacity(self.llm, "fallback")
        if retrieval is not None:
            # F2 (review r1): веб-прогон даёт evidence ТОЛЬКО из структурных
            # строк плана. Прежний fallback разбирал `search_text` заново и
            # возвращал строки с url=None (прод-симптом tfr-6e0ab2db…).
            # Нет проверяемых ссылок → evidence пуст, класс
            # `processing_failed` вместо содержательного «нет данных».
            delivery = _evidence_delivery(
                retrieval, route=route, fallback_results=results,
                refs_only=True)
            evidence = delivery.rows
            if retrieval_refs and evidence:
                # §3.3: выдержка связана с claim-частью, к которой привязана
                # на retrieval-слое (иначе в хранинном evidence claim_part
                # всегда null и связь «тезис ↔ источник» теряется).
                claim_by_evidence = {
                    str(getattr(ref, "evidence_id", "")): str(
                        (getattr(ref, "claims", ()) or ("",))[0])
                    for ref in retrieval_refs
                    if (getattr(ref, "claims", ()) or ())}
                if claim_by_evidence:
                    evidence = tuple(
                        {**row, "claim_part": claim_by_evidence.get(
                            str(row.get("evidence_id")))} if claim_by_evidence.get(
                            str(row.get("evidence_id"))) else row
                        for row in evidence)
                    delivery = dataclasses.replace(delivery, rows=evidence)
        else:
            # Внутренний поиск ветки: строки без URL тоже не доказательство
            # (их нельзя открыть и проверить). Порция — по ёмкости маршрута.
            delivery = _evidence_delivery(
                retrieval, route=route, fallback_results=results)
            evidence = tuple(r for r in delivery.rows if r.get("url"))
            delivery = dataclasses.replace(delivery, rows=evidence)
        date_summary = None
        if evidence and tf.evidence_date_fetch_enabled():
            try:
                evidence, date_summary = await tf.enrich_evidence_dates(
                    evidence)
                by_id = {str(r.get("evidence_id")): r for r in evidence}
                delivery = dataclasses.replace(
                    delivery, rows=evidence,
                    all_rows=tuple(by_id.get(str(r.get("evidence_id")), r)
                                   for r in delivery.all_rows))
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

        correlation_id = str(run_id) if run_id else \
            usage_events.new_correlation_id()
        fallback_used = False
        verdict_reason = search_reason
        # P0-FACTCHECK (§3.6)/§11.2: технический класс исхода retrieval —
        # единая функция (см. `envelope_retrieval_state`), а не «нет URL →
        # поломка разбора».
        retrieval_state = envelope_retrieval_state(
            evidence=evidence, retrieval=retrieval,
            results_text=str(results or ""),
            internal_failure_cause=internal_failure_cause)
        if retrieval_state in _RETRIEVAL_REASON:
            verdict_reason = _RETRIEVAL_REASON[retrieval_state]

        # verdict (D10/D11): data-only JSON-стадия; невалидный JSON →
        # fallback-попытка; обе мимо → честный degraded-вердикт с датами.
        # §18G.3: evidence_refs модели валидируются по current-run
        # allowlist стабильных ID (ev-N) — произвольный service text
        # evidence сам по себе не становится.
        # P0-FACTCHECK-CORRECTIVE (§1/§2.4): пустой evidence больше НЕ
        # подменяет анализ серверным insufficient_evidence — СУЩЕСТВУЮЩИЙ
        # аналитический verdict-вызов выполняется всегда; при пустом
        # evidence payload получает <analysis_context> (статус поиска,
        # разрешение логической/математической проверки, рамка
        # происхождения вывода). Без доказательств положительный вердикт
        # держит только серверный guard `_downgrade_unbacked_positive`
        # (никаких «вспомнил цифру → подтверждено»).
        analysis_context = ("" if evidence
                            else _analysis_context_for_empty_evidence(
                                retrieval_state))
        if not evidence and retrieval_state == RETRIEVAL_NO_RESULTS and int(
                getattr(retrieval, "queries_used", 0) or 0) > 0:
            # §11.2 п.6/§11.3: материалы прочитаны, но цитируемых URL/выдержек
            # нет — это ограничение ССЫЛОЧНОЙ доказательности. Writer обязан
            # сказать именно это, а не «материалы не удалось разобрать».
            analysis_context += (
                "\n<analysis_context>\n"
                "Ограничение ссылочной доказательности: материалы этой выдачи "
                "прочитаны, но проверяемых URL/цитат в них не оказалось. Это "
                "НЕ технический сбой поиска; ссылки в ответе не выдумывать.\n"
                "</analysis_context>")
        # S15 (owner §8.2): остановка поиска бюджетом/deadline — ограничение
        # ПОИСКА, а не доказательство отсутствия; аналитик обязан знать это
        # ДО вердикта, даже когда часть evidence уже есть.
        budget_note = _evidence_context_note(retrieval, evidence)
        if budget_note:
            analysis_context = (analysis_context + "\n" + budget_note
                                if analysis_context else budget_note)
        # ASAP-FC-EVIDENCE-STYLE-02 §3.1: покрытие частей известно ДО вердикта
        # (retrieval уже отработал) — аналитик получает статус каждого пункта,
        # чтобы не смешивать технический сбой с «нет данных» и разбирать
        # спорное число отдельно от события.
        claim_coverage = tuple(getattr(retrieval, "claims", ()) or ()) \
            if retrieval is not None else ()

        def _analyst_payload(delivery_obj: EvidenceDelivery) -> str:
            """Payload аналитика для конкретной порции evidence (route-aware)."""
            payload = self._temporal_user_payload(
                env, parts, delivery_obj.rows, chat_context, analysis_context,
                coverage=claim_coverage, delivery=delivery_obj)
            if _temporal_snap is not None:
                payload = _cclock.append_time_block(
                    payload, _temporal_snap, phase=_cclock.PHASE_ANSWER)
            return payload

        # UR-C-CLOCK (UR-26.4): время ОЦЕНКИ (ChatClock чата) — отдельный
        # авторитетный блок; даты публикации источника остаются в
        # <temporal_context>/<evidence> в СВОЁМ поясе (UR-27), ChatClock их
        # не подменяет.
        _temporal_snap = None
        try:
            if env.chat_id is not None:
                _temporal_snap = await _cclock.snapshot(env.chat_id)
        except Exception:      # pragma: no cover - fail-open honest
            _temporal_snap = None
        user_payload = _analyst_payload(delivery)
        allowed_refs = ({str(r.get("evidence_id")) for r in evidence
                         if r.get("evidence_id")}
                        if evidence else set())

        def _route_adapter(builder):
            """Recompose под ёмкость ФАКТИЧЕСКИ вызванного fallback-маршрута.

            Owner §7.4: при переходе на fallback/другой endpoint используются
            характеристики фактического маршрута; уменьшенная порция не
            теряется молча — остаток остаётся в `<evidence_delivery>`."""
            if fallback_route is None or not delivery.all_rows:
                return None

            def _adapt(payload):
                try:
                    messages = list(payload.get("messages") or ())
                    if len(messages) < 2:
                        return payload
                    packed = _pack_evidence(
                        delivery.all_rows,
                        budget_chars=fallback_route.input_chars,
                        route=fallback_route)
                    messages[-1] = {**messages[-1],
                                    "content": builder(packed)}
                    return {**payload, "messages": messages}
                except Exception:      # pragma: no cover — fail-open
                    return payload
            return _adapt

        _analyst_adapter = _route_adapter(_analyst_payload)
        raw_payload = await self._temporal_verdict_json(
            tf.TEMPORAL_ANALYST_SYSTEM, user_payload, env,
            correlation_id, step="temporal_verdict",
            fallback_payload_adapter=_analyst_adapter)
        if raw_payload is None:
            fallback_used = True
            raw_payload = await self._temporal_verdict_json(
                tf._TEMPORAL_FALLBACK_SYSTEM, user_payload, env,
                correlation_id, step="temporal_fallback",
                fallback_payload_adapter=_analyst_adapter)
        if raw_payload is None:
            # Обе попытки мимо: честный degraded-вердикт. Техническая
            # причина retrieval (бюджет/недоступность/обработка, §5.1)
            # не маскируется fallback-кодом — режим fallback фиксируется
            # через fallback_used и trace (§5.3).
            fallback_used = True
            if verdict_reason not in _TECHNICAL_RETRIEVAL_REASONS:
                verdict_reason = "temporal_fallback_mode"
            raw_payload = {}
        verdict = tf.verdict_from_payload(raw_payload, env,
                                          fallback_reason=verdict_reason,
                                          allowed_refs=allowed_refs)
        # §2.4: положительный вердикт без внешних доказательств и без
        # помеченного основания самостоятельной проверки → честная
        # неопределённость (существующий enum, части сохраняются).
        _pre_downgrade = str(verdict.factual_verdict or "")
        verdict = _downgrade_unbacked_positive(verdict, evidence)
        _downgraded = (str(verdict.factual_verdict or "") != _pre_downgrade)
        # §7.3: содержательный вывод без поиска не помечается техническим
        # заголовком «проверка не завершена» — реальное состояние поиска
        # остаётся оговоркой в uncertainty (ниже).
        if not evidence and verdict.reason in _TECHNICAL_RETRIEVAL_REASONS \
                and _verdict_is_substantive(verdict):
            verdict = dataclasses.replace(verdict, reason=None)
        # UR-26.4: payload-событие temporal_verdict — код вердикта
        # (decision) + РАЗДЕЛЬНЫЕ маркеры времени ОЦЕНКИ (ChatClock-блок
        # payload'а, as_of_utc в clock) и дат ПУБЛИКАЦИИ источника
        # (date_source/наличие original_published_at в reason_code —
        # остаются в СВОЁМ поясе, UR-27). downgrade — явный код, не
        # молчаливая подмена. R17: digest JSON вердикта, без текстов.
        _verdict_payload_json = json.dumps(raw_payload or {},
                                           ensure_ascii=False, default=str)
        _tpe.emit_stage(
            _tpe.STAGE_FC_TEMPORAL_VERDICT,
            outcome="success" if raw_payload else "error",
            chat_id=getattr(env, "chat_id", None),
            correlation_id=correlation_id,
            model=_tpe.llm_model(self.llm),
            provider=_tpe.llm_provider(self.llm),
            finish_reason=("parsed_json" if raw_payload else "degraded")
            + ("+fallback" if fallback_used else ""),
            chars=len(_verdict_payload_json),
            text_digest=_tpe.text_digest(_verdict_payload_json),
            clock=_tpe.clock_meta_text(user_payload,
                                       chat_id=getattr(env, "chat_id",
                                                       None)),
            decision="v=%s;dg=%s;fb=%s"
            % (str(verdict.factual_verdict or "unknown")[:24],
               "unbacked_positive" if _downgraded else "none",
               "yes" if fallback_used else "no"),
            reason_code="temporal=%s;date_source=%s;pub_date=%s"
            % (str(verdict.temporal_status or "unknown")[:24],
               str(getattr(env, "date_source", "") or "unknown")[:32],
               "present" if getattr(env, "original_published_at", None)
               else "absent"))

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
            def _validator_payload(delivery_obj: EvidenceDelivery) -> str:
                content = self._temporal_validator_payload(
                    env, verdict, delivery_obj.rows, delivery=delivery_obj)
                if _temporal_snap is not None:
                    content = _cclock.append_time_block(
                        content, _temporal_snap, phase=_cclock.PHASE_ANSWER)
                return content

            _validator_content = _validator_payload(delivery)
            _validator_adapter = _route_adapter(_validator_payload)
            v_payload = await self._temporal_verdict_json(
                tf.TEMPORAL_VALIDATOR_SYSTEM,
                _validator_content,
                env, correlation_id, step="temporal_validator",
                fallback_payload_adapter=_validator_adapter)
            if v_payload is not None:
                verdict, corrected = tf.apply_validator(verdict, v_payload,
                                                        env)
                validator_outcome = "corrected" if corrected else "validated"
                # UR-26.4: исход CoVe-валидатора — явный код (согласие/
                # понижение вердикта валидатором не бывает молчаливым).
                _validator_json = json.dumps(v_payload, ensure_ascii=False,
                                             default=str)
                _tpe.emit_stage(
                    _tpe.STAGE_FC_TEMPORAL_VALIDATOR, outcome="success",
                    chat_id=getattr(env, "chat_id", None),
                    correlation_id=correlation_id,
                    model=_tpe.llm_model(self.llm),
                    provider=_tpe.llm_provider(self.llm),
                    finish_reason="corrected" if corrected
                    else "validated",
                    chars=len(_validator_json),
                    text_digest=_tpe.text_digest(_validator_json),
                    clock=_tpe.clock_meta_text(
                        _validator_content,
                        chat_id=getattr(env, "chat_id", None)),
                    decision=("validator=%s;corrected=%s"
                              % (validator_outcome, bool(corrected))),
                    attempt=1)
            else:
                validator_outcome = "failed"
                # UR-26.4: отказ/невалидный JSON валидатора — явный код
                # fallback-решения (строгий повтор аналитика ниже).
                _tpe.emit_stage(
                    _tpe.STAGE_FC_TEMPORAL_VALIDATOR, outcome="error",
                    chat_id=getattr(env, "chat_id", None),
                    correlation_id=correlation_id,
                    model=_tpe.llm_model(self.llm),
                    provider=_tpe.llm_provider(self.llm),
                    finish_reason="validator_failed",
                    clock=_tpe.clock_meta_text(
                        _validator_content,
                        chat_id=getattr(env, "chat_id", None)),
                    decision="validator=failed:fallback_retry",
                    attempt=1)
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
        #
        # F5 (review r1): синтезированные части не должны противоречить
        # положительному общему вердикту («Подтверждается» + все части
        # «данных недостаточно»). Поэтому синтез только для честного
        # insufficient_evidence; иначе разбора частей нет вовсе.
        if not verdict.parts and verdict.factual_verdict == \
                "insufficient_evidence":
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
        # ASAP-FC-EVIDENCE-STYLE-02 §3.1/§4: покрытие ПО КАЖДОЙ части —
        # подтверждённые части не растворяются в общем «данных недостаточно»,
        # каждый пробел получает конкретную причину, ссылки части — только
        # claim-привязанные evidence этого прогона.
        if claim_coverage:
            verdict = merge_claim_coverage(verdict, claim_coverage, evidence)
            tf.stage_event("claim_coverage", "success",
                           reason_code=verdict.reason, chat_id=env.chat_id)
        tf.stage_event("verdict", "success", reason_code=verdict.reason,
                       chat_id=env.chat_id)

        # verbalize (D11/CA-20-13): стилизация ПОСЛЕ вердикта; даты/
        # оговорки — обязательная часть payload каждой стадии; все ветки
        # (включая fallback) получают один envelope.
        verdict_text = await self._temporal_verbalize(
            env, verdict, fallback_used, correlation_id,
            retrieval_state=retrieval_state, coverage=claim_coverage,
            evidence=evidence, time_snap=_temporal_snap)
        trace.add("verbalize", "success" if verdict_text else "skipped",
                  reason=None if verdict_text else "temporal_fallback_mode")

        if not verdict_text:
            verdict_text = self._temporal_fallback_text(
                env, verdict, retrieval_state=retrieval_state)

        # §11.3 (FC-EVIDENCE-STATUS-01): диагностика прогона из фактических
        # счётчиков стадии — не из «нет URL». Неизвестное → «нет данных».
        emit_evidence_diagnostics(
            chat_id=env.chat_id, retrieval=retrieval,
            retrieval_state=retrieval_state, evidence=evidence,
            verdict=verdict, pipeline_run_id=correlation_id,
            delivery=delivery)

        return tf.TemporalRunResult(
            envelope=env, verdict=verdict, verdict_text=verdict_text,
            evidence_rows=evidence, stage_trace=trace.as_list(),
            fallback_used=fallback_used, cache_hit=False)

    def _temporal_user_payload(
        self, env: tf.TemporalClaimEnvelope, parts, evidence,
        chat_context: str | None, analysis_context: str = "",
        coverage=(),
        delivery: EvidenceDelivery | None = None,
    ) -> str:
        """User-content вердиктной стадии: <claim> + <temporal_context>
        (даты/периоды/режим — серверные метаданные, D2) + <evidence> +
        <chat_context> (НЕ доказательства — подпись как в legacy).
        P0-FACTCHECK-CORRECTIVE (§2.4): при пустом evidence добавляется
        <analysis_context> — статус поиска и рамка самостоятельной
        проверки (серверный текст, не доказательства).
        ASAP-FC-EVIDENCE-STYLE-02 §3.1: <claim_coverage> — что именно уже
        проверено по каждой части и чего не хватает (серверные метаданные).
        S15: <evidence_delivery> — машинная граница доставки, когда материалов
        больше, чем поместилось в ёмкость маршрута (остаток не выдумывается).
        """
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
            # §3.3: выдержка помечается claim-частью, к которой привязана.
            # S15: provenance (source_kind/opened/strength) — заголовок и
            # сниппет не выдаются за прочитанный документ (owner §8.2).
            sections.append("<evidence>" + escape_xml_text("\n\n".join(
                "[%s]%s published: %s%s%s\n%s" % (
                    r.get("evidence_id") or "?",
                    (" claim=%s" % r["claim_part"])
                    if r.get("claim_part") else "",
                    _fmt_evidence_date(r.get("published_at")),
                    (" (%s)" % r["published_at_source"])
                    if r.get("published_at_source") else "",
                    (" source=%s;opened=%s;strength=%s" % (
                        r.get("source_kind") or "unknown",
                        "yes" if r.get("opened") else "no",
                        r.get("strength") or "none")),
                    r["support"])
                for r in evidence)) + "</evidence>")
            if delivery is not None:
                block = delivery.payload_block()
                if block:
                    sections.append(block)
        coverage_section = _claim_coverage_payload(coverage)
        if coverage_section:
            sections.append(coverage_section)
        if analysis_context:
            sections.append(analysis_context)
        if chat_context:
            sections.append(chat_context)
        return "\n\n".join(sections)

    def _temporal_validator_payload(
        self, env: tf.TemporalClaimEnvelope, verdict: tf.TemporalVerdict,
        evidence,
        delivery: EvidenceDelivery | None = None,
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
        if delivery is not None:
            block = delivery.payload_block()
            if block:
                sections.append(block)
        return "\n\n".join(sections)

    async def _temporal_verdict_json(
        self, system: str, user_payload: str, env,
        correlation_id: str | None, *, step: str,
        fallback_payload_adapter=None,
    ) -> dict | None:
        """Один data-only LLM-вызов вердиктной стадии → dict|None.

        ``fallback_payload_adapter`` (S15, owner §7.4): при фактическом переходе
        клиента на fallback-модель/endpoint payload recompose'ится под ёмкость
        ЭТОГО маршрута; None → прежнее поведение (payload не меняется)."""
        from services.system2_handoff import parse_json_object
        generate = getattr(self.llm, "generate", None)
        if generate is None:
            return None
        kwargs = {"module": "factcheck", "step": step,
                  "correlation_id": correlation_id}
        if fallback_payload_adapter is not None \
                and _accepts_kwarg(generate, "fallback_payload_adapter"):
            kwargs["fallback_payload_adapter"] = fallback_payload_adapter
        try:
            raw = await generate(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user_payload}], **kwargs)
        except Exception:
            return None
        payload = parse_json_object(str(raw))
        return payload if isinstance(payload, dict) else None

    async def _temporal_verbalize(
        self, env: tf.TemporalClaimEnvelope, verdict: tf.TemporalVerdict,
        fallback_used: bool, correlation_id: str | None,
        *, retrieval_state: str | None = None, coverage=(), evidence=(),
        time_snap=None,
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
            # ASAP-FC-VOICE-01 / A (§1, §6 инвариант 6): OFF умных режимов →
            # ПРЕЖНЯЯ заводская редакция вербализатора (байты прода), иначе —
            # активная редакция голоса жанра.
            _modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED",
                                True)
            if _modes_on:
                base = resolve_prompt(
                    "prompts.factcheck_verbalizer_system_prompt",
                    FACTCHECK_VERBALIZER_SYSTEM_PROMPT)
            else:
                from services.factcheck_prompts import (
                    PREV_FACTCHECK_VERBALIZER_VOICE01 as _PREV_VOICE,
                )
                base = _PREV_VOICE
            base = base.replace("{max_symbols}", str(max_symbols))
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
        # ASAP-FC-VOICE-01 / A (§4): два необязательных смысловых поля
        # Аналитика ТОЙ ЖЕ стадии. Пустое значение в payload не появляется
        # (выдумывать поле запрещено каноном), поэтому Writer видит только
        # действительно установленный разрыв вывода и честный контрапункт.
        _gap = str(getattr(verdict, "inference_gap", "") or "").strip()
        if _gap:
            payload["inference_gap"] = _gap
        _counterpoint = str(getattr(verdict, "counterpoint", "") or "").strip()
        if _counterpoint:
            payload["counterpoint"] = _counterpoint
        payload["parts"] = list(verdict.parts)
        # §3.1/§5: покрытие частей — вербализатор пишет КОНКРЕТНЫЕ пробелы
        # (техсбой/нет источников/недоказанное число), а не общее «данных
        # недостаточно» после каждого пункта.
        claim_rows = claim_payload_rows(coverage)
        if claim_rows:
            payload["claims"] = claim_rows
        payload["claim"] = env.claim_text
        # UR-C-CLOCK (UR-26.4): вербализатор видит время ОЦЕНКИ из ChatClock
        # (человекочитаемо); даты публикации остаются в своём блоке/полях.
        if time_snap is not None:
            payload["server_time"] = {
                "local": "%s %s, %s" % (
                    time_snap.local_datetime.strftime("%d.%m.%Y"),
                    time_snap.local_datetime.strftime("%H:%M"),
                    time_snap.weekday),
                "tz": time_snap.timezone,
                "as_of_utc": time_snap.as_of_utc.strftime(
                    "%Y-%m-%dT%H:%M:%S+00:00"),
            }
        # RLR R-03.4/R-06/§3.4: проверенный набор чисел — из структурного
        # payload'а, evidence этого прогона и дат envelope; уходит Writer'у
        # ЯВНО до генерации. Post-L2 numeric-правки здесь нет.
        numeric_bindings = build_numeric_contract(
            claim_text=env.claim_text,
            writer_payload=json.dumps(payload, ensure_ascii=False),
            evidence_rows=evidence,
            temporal_context=env)
        payload["numbers"] = numeric_contract_payload(numeric_bindings)
        situation = _RETRIEVAL_SITUATION.get(str(retrieval_state or ""))
        if situation:
            # §3.6: вербализатор не должен называть сбой «отсутствием фактов».
            payload["situation"] = situation
        if fallback_used:
            payload["fallback_note"] = (
                "структурированный анализ не удался — не утверждай больше, "
                "чем следует из данных")
        # §7.2: анализ без содержания ≠ поиск без результатов. Только когда
        # содержательного анализа НЕТ — короткая честная граница вместо
        # абзацев-компенсаций. Универсального правила длины НЕ вводится:
        # содержательный ответ передаётся как есть (§7.1).
        if not _verdict_is_substantive(verdict):
            payload["limit_note"] = (
                "содержательного разбора не получилось — коротко назови "
                "фактическое ограничение и какой информации не хватает, "
                "без абзацев ради объёма и без историй про сломанные "
                "инструменты")
        # UNIFIED-CORE → ASAP-FC-VOICE-01 / A: временной вербализатор —
        # пользовательская речь → слои владельца из ЕДИНОЙ точки сборки
        # (Core/Expression/Style/примеры, причина пропуска — в манифесте).
        # Порядок слоёв прежний по смыслу: жанровый канон → Core →
        # Expression (+ её финальный контракт последним) → примеры → Style.
        # EVOL §5 (W5): та же директива критики, что на остальных публичных
        # путях (политика — по проверенному вердикту: supported/insufficient/
        # техсбой → директивы нет).
        _chat = getattr(env, "chat_id", None)
        critique_block = await _critique_section_block(
            _chat, critique_policy_for_verdict(
                factual_verdict=verdict.factual_verdict,
                parts=tuple(verdict.parts or ()),
                reason_code=verdict.reason,
                fallback_used=bool(fallback_used),
                has_evidence=bool(verdict.parts or ())))
        base = _with_critique_block(base, critique_block)
        system = await _compose_genre_speech(
            _chat, writer="factcheck_temporal_verbalizer", base_prompt=base)
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
            _tpe.emit_stage(
                _tpe.STAGE_FC_TEMPORAL_VERBALIZE, outcome="error",
                chat_id=getattr(env, "chat_id", None),
                correlation_id=correlation_id,
                model=_tpe.llm_model(self.llm),
                provider=_tpe.llm_provider(self.llm),
                finish_reason="verbalize_failed",
                clock=_tpe.clock_meta_messages(messages, chat_id=_chat),
                decision=("verbalize=failed;server_time=%s"
                          % ("snapshot" if time_snap is not None
                             else "absent")))
            return ""
        try:
            out = cleanup_llm_text(strip_reasoning_tags(str(text)))
        except Exception:
            _tpe.emit_stage(
                _tpe.STAGE_FC_TEMPORAL_VERBALIZE, outcome="error",
                chat_id=getattr(env, "chat_id", None),
                correlation_id=correlation_id,
                model=_tpe.llm_model(self.llm),
                provider=_tpe.llm_provider(self.llm),
                finish_reason="cleanup_failed",
                clock=_tpe.clock_meta_messages(messages, chat_id=_chat),
                decision=("verbalize=failed;server_time=%s"
                          % ("snapshot" if time_snap is not None
                             else "absent")))
            return ""
        out = out.strip()
        # RLR §3.4/§8: неподтверждённое число не публикуется и НЕ правится в
        # готовой фразе — вместо пересказа идёт структурный отчёт проверки
        # (тот же verdict-класс, те же источники).
        unverified = unvalidated_numbers(out, numeric_bindings)
        if unverified:
            logger.warning(
                "factcheck numeric | chat=%s | code=%s | unverified=%d | "
                "action=structural_report", getattr(env, "chat_id", None),
                NUMBER_UNVALIDATED, len(unverified))
            # UR-26.4: структурный отчёт вместо вербализации — явный код
            # решения (неподтверждённое число не правится молча).
            _tpe.emit_stage(
                _tpe.STAGE_FC_TEMPORAL_VERBALIZE, outcome="success",
                chat_id=getattr(env, "chat_id", None),
                correlation_id=correlation_id,
                model=_tpe.llm_model(self.llm),
                provider=_tpe.llm_provider(self.llm),
                finish_reason="structural_report",
                chars=len(out),
                text_digest=_tpe.text_digest(out),
                clock=_tpe.clock_meta_messages(messages, chat_id=_chat),
                decision=("verbalize=structural_report:unverified_numbers=%d"
                          ";server_time=%s"
                          % (len(unverified),
                             "snapshot" if time_snap is not None
                             else "absent")))
            return deterministic_temporal_report(
                env, verdict, evidence=evidence, reason_code=retrieval_state)
        # UR-26.4: payload-событие вербализации — размер/digest текста,
        # маркер снапшота времени оценки (server_time из ChatClock), коды
        # ретраев. Даты публикации остаются отдельными полями вердикта.
        _tpe.emit_stage(
            _tpe.STAGE_FC_TEMPORAL_VERBALIZE, outcome="success",
            chat_id=getattr(env, "chat_id", None),
            correlation_id=correlation_id,
            model=_tpe.llm_model(self.llm),
            provider=_tpe.llm_provider(self.llm),
            finish_reason="generated",
            chars=len(out),
            text_digest=_tpe.text_digest(out),
            clock=_tpe.clock_meta_messages(messages, chat_id=_chat),
            decision=("verbalize=generated;retries=%d;server_time=%s"
                      % (int((_stats or {}).get("retries", 0) or 0),
                         "snapshot" if time_snap is not None else "absent")))
        return out

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
            RETRIEVAL_NO_RESULTS:
                "Поиск ответил, но подходящих материалов не дал — поэтому "
                "вывод сделан без внешних источников.",
        }
        if _verdict_is_substantive(verdict):
            # §7: содержательный разбор не подменяется сообщением о сбое —
            # даже при отказе вербализатора разбор частей сохраняется.
            opener = ("Внешний поиск не удался, поэтому разбор сделан без "
                      "веб-источников."
                      if str(retrieval_state or "") in (
                          RETRIEVAL_BUDGET, RETRIEVAL_SEARCH_FAILED,
                          RETRIEVAL_PROCESSING_FAILED, RETRIEVAL_NO_RESULTS)
                      else "Недостаточно данных для полной проверки "
                           "утверждения.")
            pieces = [opener]
            for part in (verdict.parts or ())[:4]:
                if not isinstance(part, dict):
                    continue
                text = " ".join(str(part.get("text") or "").split())
                if not text:
                    continue
                label = {"supported": "подтверждается",
                         "refuted": "не подтверждается",
                         "mixed": "подтверждается частично",
                         "insufficient_evidence": "данных недостаточно"}.get(
                    str(part.get("factual_verdict") or ""), "")
                pieces.append(f"• {text}"
                              + (f" — {label}" if label else ""))
        else:
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
