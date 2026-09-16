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
import logging
import time

from config.settings import settings
from services import hot_config as hot
from services.factcheck_prompts import FACTCHECK_SYSTEM_PROMPT
from services.llm_client import LLMBadResponseError, LLMClient
from services.search_aggregator import SearchAggregator
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import MemoryManager, fire_and_forget
from services.summary_xml import escape_xml_text
from services.smartmodule_utils import strip_lore_html
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
        """Фактчек-пайплайн:
        1) results = await self.aggregator.search(target_text, max_symbols)
        2) system = FACTCHECK_SYSTEM_PROMPT.replace("{max_symbols}", str(max_symbols))
        3) user = [rag] self.build_user_content(target_text, user_hint, forward_source, results)
        4) raw = await self.llm.generate([{system}, {user}])
           (T-1907: при заданном `tool_router` + `chat_id` — вместо этого
           `chat_with_tools` с tool-сетом `factcheck_tools()`; финальный текст
           тот же)
        5) return cleanup_llm_text(raw)          # R33-7, ПОСТОЯННО
        Raises: AllSearchEnginesFailedException (поиск) / LLMError (LLM) — пробрасываются в хендлер."""
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
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        user = self.build_user_content(target_text, user_hint, forward_source,
                                       results, chat_context=chat_context)
        if rag:
            user = f"{rag}\n\n{user}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        started = time.monotonic()
        used_tools = False
        if self.tool_router is not None and chat_id is not None:
            # T-1907 (ADR-1020-5 п.1): реюз цикла обычного диалога. Лимит
            # раундов тот же (TOOL_MAX_ROUNDS=4, spec §7.1); S10.20-2: флаг
            # «Летописца» резолвится ТЕМ ЖЕ per-chat каскадом, что DirectChat
            # (override → hot → канон) — иначе OFF-глобально/ON-для-чата давал
            # «инструмент отключен» на видимом инструменте.
            lore_enabled = await resolve_lore_compiler_flag(chat_id)
            tools = factcheck_tools(bool(lore_enabled))
            # S10.20-4: фактчекеру НЕ добавляем «верни story ДОСЛОВНО» —
            # иначе вместо вердикта приходит история.
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
        raw = cleanup_llm_text(raw)
        if used_tools:
            # S10.20-4: если модель всё же вернула HTML-историю — не показываем
            # сырые теги в plain-доставке фактчека (no-op для обычного вердикта).
            raw = strip_lore_html(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿
            # (хендлер). LLMBadResponseError — подкласс LLMError, но ветка
            # хендлера идёт ДО except LLMError (R13-эталоны не тронуты).
            raise LLMBadResponseError("factcheck: empty answer")
        return raw

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
