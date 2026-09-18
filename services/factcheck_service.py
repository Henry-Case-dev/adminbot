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
from services.llm_client import LLMBadResponseError, LLMClient
from services.negative_constraints import (
    channel_enabled_rules,
    verbalize_validated,
)
from services.prompt_style_blocks import compose_verbilizer_system
from services.reply_postprocess import strip_reasoning_tags
from services.search_aggregator import SearchAggregator
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, fire_and_forget
from services.summary_xml import escape_xml_text
from services.smartmodule_utils import strip_lore_html
from services.system2_handoff import parse_factcheck_analysis
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, resolve_lore_compiler_flag
from services.tool_schemas import factcheck_tools

logger = logging.getLogger(__name__)


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
    ) -> str:
        """Фактчек-пайплайн (10.22, ADR-1022-3): агрегатор → (System 2:
        Аналитик JSON → Вербализатор) либо одиночный путь 10.21.

        * ``SYSTEM2_FACTCHECK_ENABLED`` ON → два физических вызова; при
          невалидном JSON/провале Stage-2/исчерпании validator-loop — fallback
          на одиночный путь (пользователь ВСЕГДА получает ответ).
        * OFF → байт-в-байт 10.21 (один вызов `self.llm.generate`/tool-loop).
        Raises: AllSearchEnginesFailedException (поиск) / LLMError (LLM)."""
        # T-619: лимит и промпт — горячие точки (ConfigCache с settings-фолбеком)
        max_symbols = hot.get("limits.factcheck_max_symbols",
                              settings.FACTCHECK_MAX_SYMBOLS)
        system_prompt = hot.get("prompts.factcheck_system_prompt",
                                FACTCHECK_SYSTEM_PROMPT)
        results = await self.aggregator.search(target_text, max_symbols)
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
                target_text, user, rag, results, chat_id, chat_context,
                max_symbols)
            if two_call is not None:
                return two_call
            logger.info(
                "factcheck system2: fallback на одиночный путь 10.21 | chat=%s",
                chat_id)
        # ── Одиночный путь 10.21 (kill-switch / fallback) ──
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw, used_tools = await self._invoke_llm(messages, target_text, chat_id)
        return self._finalize(raw, used_tools, rag, results, chat_context)

    async def _check_claim_two_call(
        self, target_text: str, user: str, rag: str, results: str,
        chat_id: int | None, chat_context: str | None, max_symbols: int,
    ) -> str | None:
        """System 2 фактчека. ``None`` → вызывающий уходит на 10.21."""
        analyst_messages = [
            {"role": "system", "content": FACTCHECK_ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
        try:
            raw_analyst, used_tools = await self._invoke_llm(
                analyst_messages, target_text, chat_id)
        except Exception as exc:                # таймаут/ошибка Stage-1 → 10.21
            logger.info(
                "factcheck system2: stage1 failed — fallback | chat=%s | "
                "error=%s", chat_id, type(exc).__name__)
            return None
        tool_context = str(getattr(raw_analyst, "tool_context", "") or "")
        anchors = collect_allowed_anchors(
            self._trusted_text(rag, results, chat_context, tool_context))
        analyst_text = strip_reasoning_tags(str(raw_analyst))
        analyst_text, _gstats = strip_phantom_tags(analyst_text, anchors)
        data = parse_factcheck_analysis(analyst_text)
        if data is None:
            logger.info(
                "factcheck system2: невалидный JSON аналитика — fallback | "
                "chat=%s", chat_id)
            return None
        response_mode = data.get("response_mode", "serious")
        modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True)
        verbalizer_template = (
            FACTCHECK_VERBALIZER_SYSTEM_PROMPT if modes_on
            else PREV_FACTCHECK_VERBALIZER_R1023)
        verbalizer_base = verbalizer_template.replace(
            "{max_symbols}", str(max_symbols))
        verbalizer_system = (compose_verbilizer_system(
            verbalizer_base, response_mode, "plain")
            if modes_on else verbalizer_base)
        base_messages = [
            {"role": "system", "content": verbalizer_system},
            {"role": "user",
             "content": "АНАЛИЗ (JSON):\n" + json.dumps(data, ensure_ascii=False)},
        ]

        async def _generate(messages):
            return await self.llm.generate(messages)

        # F3 (ADR-1023-3): plain-канал → guard от таблиц (без запрета буллитов,
        # буллиты в фактческе жанром не запрещены).
        enabled_rules = (channel_enabled_rules("plain", response_mode)
                         if modes_on else None)
        text, stats = await verbalize_validated(
            _generate, base_messages, max_retries=2,
            enabled_rules=enabled_rules)
        logger.info(
            "factcheck system2 verbalizer | chat=%s | mode=%s | attempts=%d "
            "| retries=%d | hits=%d | fallback=%s", chat_id, response_mode,
            stats.get("attempts", 0), stats.get("retries", 0),
            len(stats.get("hits") or []), bool(stats.get("fallback")))
        if stats.get("fallback"):
            return None
        return self._finalize_text(text, used_tools, tool_context,
                                   rag, results, chat_context)

    async def _invoke_llm(self, messages, target_text, chat_id):
        """Один LLM-вызов: tool-loop (при `tool_router` + `chat_id`) или plain."""
        started = time.monotonic()
        used_tools = False
        if self.tool_router is not None and chat_id is not None:
            lore_enabled = await resolve_lore_compiler_flag(chat_id)
            tools = factcheck_tools(bool(lore_enabled))
            ctx = ToolContext(chat_id, target_text,
                              lore_verbatim_instruction=False)
            raw = await chat_with_tools(
                self.llm, messages, tools=tools,
                router=self.tool_router, ctx=ctx, chat_id=chat_id)
            used_tools = True
            logger.info(
                "factcheck tool-loop OK | chat=%s | tools=%d | out_chars=%d "
                "| latency_ms=%.0f", chat_id, len(tools), len(raw),
                (time.monotonic() - started) * 1000.0,
            )
        else:
            raw = await self.llm.generate(messages)
            logger.info(
                "factcheck LLM OK | out_chars=%d | latency_ms=%.0f",
                len(raw), (time.monotonic() - started) * 1000.0,
            )
        return raw, used_tools

    @staticmethod
    def _trusted_text(rag, results, chat_context, tool_context) -> str:
        """Доверенные источники grounding-якорей (S10.21-5: без claim/hint).

        10.23 (F2, ADR-1023-2, R1023F2-04): ``chat_context`` (включая
        ``<reply_chains>``) НАМЕРЕННО исключён — это контекст «не
        доказательства», и его таймстампы (``ДД.ММ.ГГГГ``) не должны
        становиться grounding-якорями и «заземлять» фантомные ``[ММ.ГГГГ]``
        теги. Якоря — только из доказательств: RAG, поисковая выдача,
        tool-контекст (аргумент сохранён для явности/совместимости)."""
        parts = [str(rag or ""), str(results or "")]
        if tool_context:
            parts.append(str(tool_context))
        return "\n".join(parts)

    def _finalize(self, raw, used_tools, rag, results, chat_context) -> str:
        tool_context = str(getattr(raw, "tool_context", "") or "")
        return self._finalize_text(str(raw), used_tools, tool_context,
                                   rag, results, chat_context)

    def _finalize_text(self, text, used_tools, tool_context, rag, results,
                       chat_context) -> str:
        """cleanup → grounding-strip → lore-strip → пустой ответ."""
        anchors = collect_allowed_anchors(
            self._trusted_text(rag, results, chat_context, tool_context))
        out = cleanup_llm_text(text)
        out, gstats = strip_phantom_tags(out, anchors)
        if gstats.stripped_phantom or gstats.stripped_bare:
            logger.info(
                "factcheck grounding | stripped_phantom=%d | stripped_bare=%d "
                "| kept=%d",
                gstats.stripped_phantom, gstats.stripped_bare, gstats.kept,
            )
        if used_tools:
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
