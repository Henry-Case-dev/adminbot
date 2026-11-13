"""Epic 42 — CheckupService (Section 51.6): логи → LLM-отчёт → cleanup.
Epic 60 (64.5, T-466): db+memory → data-секция <memory_health> в user-контенте.
Epic 61 (64.5 хотфикс, D250/T-501): секция метрик собирается ПЕРВОЙ с
резервом длины (логи режутся до MAX_INPUT − len(секции) — метрики всегда
живы); escape РОВНО ОДИН раз на финальной обёртке <system_logs>.

SELF-DIAG-01 D6 (`SD1-D6-05`, B1): сервис не меняет промпт и не пишет его
содержимое — наружу отдаётся только машинная телеметрия ФИНАЛЬНОГО system
(source/version/hash) в per-run словарь ``telemetry`` вызывающего; хендлер
кладёт её в существующий mca-событийный контур. Общего mutable-атрибута
телеметрии нет: конкурентные чекапы разных чатов не смешиваются.
"""
import hashlib
import logging
import re
import time

from config.settings import settings
from services import hot_config as hot
from services.checkup_prompts import (
    CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM,
    CHECKUP_FALLBACK_NOTICE,
    CHECKUP_SYSTEM_PROMPT,
)
from services.llm_client import LLMBadResponseError, LLMClient
from services.memory_health import collect_metrics
from services.prompt_composer import speech_owner_block
from services.prompt_style_blocks import resolve_prompt, \
    resolve_prompt_with_source
from services.summary_cleanup import cleanup_llm_text
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)

# Epic 49 (Section 57.5, D196): C0-управляющие, кроме \n (переносы логов) и
# \t; плюс DEL (0x7f). Каждый такой символ → ровно ОДИН пробел.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Epic 61 (64.5 хотфикс, D250/T-500): потолок секции метрик ДО расчёта бюджета
# логов (крайний случай «метрики разрослись»); бюджет логов гарантированно
# ≥ CHECKUP_MAX_INPUT_SYMBOLS − (2000 + обвязка) ≈ 9970.
_METRICS_MAX_SYMBOLS = 2000


class CheckupService:
    """Канон SmartModule: system.replace({max_symbols}) → llm.generate →
    cleanup_llm_text (R33-7, ВСЕГДА) → outbound Style Policy (P0-CHECKUP,
    только пользовательская команда) → хендлер. LLMError пробрасывается.
    Epic 60 (64.5): метрики памяти подаются ДАННЫМИ в user-контент (без
    db/memory — ровно старое поведение; metrics_enabled=false — рубильник)."""

    def __init__(self, llm: LLMClient, db=None, memory=None,
                 metrics_enabled: bool = settings.CHECKUP_MEMORY_METRICS_ENABLED) -> None:
        self.llm = llm
        self.db = db
        self.memory = memory
        self.metrics_enabled = metrics_enabled

    async def checkup(self, logs_text: str, used_fallback: bool,
                      chat_id: int | None = None, *,
                      telemetry: dict | None = None,
                      tool_runtime: dict | None = None) -> str:
        """logs_text = результат fetcher.fetch(); used_fallback → скрытая
        приписка CHECKUP_FALLBACK_NOTICE в КОНЕЦ system-сообщения (51.4).

        UNIFIED-CORE (P0, 20.10.2026): ``chat_id`` (пользовательская команда
        в чате) → после канона идут Core + Expression владельца; без ``chat_id``
        (внутренний tool-loop ``get_bot_health`` — отчёт вербализует Direct
        Writer) блок не передаётся: внутренние данные остаются нейтральными.

        SELF-DIAG-01 D6 B1 (`SD1-D6-05`): ``telemetry`` — per-run словарь
        вызывающего. Сервис заполняет ЕГО, а не общий mutable-атрибут:
        одновременные чекапы разных чатов не видят чужую телеметрию. Hash
        считается по ФИНАЛЬНОМУ system (ровно те байты, что уходят в LLM).

        SELF-DIAG-01 corrective (§3 owner input): ``tool_runtime`` —
        СУЩЕСТВУЮЩИЙ tool-loop контур, подготовленный handler'ом
        (``{"router","ctx","schemas","correlation_id"}``). Передан → чекап
        идёт через ``tool_loop.chat_with_tools`` с объявленными read-only
        диагностическими инструментами; модель сама решает, читать ли код и
        runtime, а результаты возвращаются ей для синтеза. None/пустой набор
        → прежний одиночный ``generate`` (паритет и офлайн-тесты)."""
        # T-619: промпт/лимиты/флаг метрик — горячие точки (фолбек settings)
        # SOUL-1 (W1 fix-pass, BLOCKER-2): промпт — через единый резолвер реестра.
        system_prompt = resolve_prompt("prompts.checkup_system_prompt",
                                       CHECKUP_SYSTEM_PROMPT)
        # SELF-DIAG-01 D6 B1: source — существующий резолвер с провенансом
        # (`global` только при реальном PG-значении; кодовый канон — `default`).
        try:
            _effective, prompt_source = resolve_prompt_with_source(
                "prompts.checkup_system_prompt", CHECKUP_SYSTEM_PROMPT)
        except Exception:      # pragma: no cover - резолвер не бросает
            prompt_source = "default"
        max_symbols = hot.get("limits.checkup_max_symbols",
                              settings.CHECKUP_MAX_SYMBOLS)
        max_input = hot.get("limits.checkup_max_input_symbols",
                            settings.CHECKUP_MAX_INPUT_SYMBOLS)
        metrics_enabled = hot.get("flags.checkup_memory_metrics_enabled",
                                  self.metrics_enabled)
        system = system_prompt.replace("{max_symbols}", str(max_symbols))
        # UNIFIED-CORE: слои владельца речи — ДО служебной приписки
        # (CHECKUP_FALLBACK_NOTICE остаётся последним абзацем system).
        owner_block = await speech_owner_block(chat_id)
        if owner_block:
            system = f"{system}\n\n{owner_block}"
        # SELF-DIAG-01 corrective (§3): функциональная операционная директива
        # подключается только при реально переданном tool-loop; базовый
        # owner-канон/характер остаются байт-в-байт. Стоит ДО служебной
        # приписки — CHECKUP_FALLBACK_NOTICE остаётся последним абзацем.
        _tool_schemas = ()
        if isinstance(tool_runtime, dict):
            _tool_schemas = tuple(tool_runtime.get("schemas") or ())
        if _tool_schemas:
            system += "\n\n" + CHECKUP_DIAGNOSTIC_TOOLS_ADDENDUM
        if used_fallback:
            system += "\n\n" + CHECKUP_FALLBACK_NOTICE     # R42-2: ровно 1 раз
        # Epic 49 (57.5, D196): scrub C0 (гипотеза (б) — невалидные управляющие
        # символы raw-логов). Единая точка — здесь, ДО escape_xml_text.
        user_content = _CONTROL_CHARS_RE.sub(" ", logs_text)
        # Epic 61 (64.5 хотфикс, D250): метрики СНАЧАЛА + резерв длины —
        # потолок метрик ДО расчёта бюджета, затем логи режутся до
        # (CHECKUP_MAX_INPUT_SYMBOLS − len(секции)) → метрики всегда живы.
        metrics = ""
        if metrics_enabled and self.db is not None:
            try:
                metrics = await collect_metrics(self.db, self.memory)
            except Exception:
                logger.warning("[checkup] memory metrics failed", exc_info=True)
                metrics = ""
        if len(metrics) > _METRICS_MAX_SYMBOLS:
            metrics = metrics[:_METRICS_MAX_SYMBOLS]
        # БЕЗ предварительного escape (escape РОВНО ОДИН на обёртке ниже).
        metrics_section = (
            "\n\n<memory_health>\n" + metrics + "\n</memory_health>"
        ) if metrics else ""
        logs_budget = max_input - len(metrics_section)
        input_truncated = False
        if len(user_content) > logs_budget:
            logger.warning(
                "[checkup] input truncated | chars=%d -> %d",
                len(user_content), logs_budget,
            )
            user_content = user_content[:logs_budget]
            input_truncated = True
        body = user_content + metrics_section
        user = f"<system_logs>{escape_xml_text(body)}</system_logs>"
        # SELF-DIAG-01 D6 B1: телеметрия ФИНАЛЬНОГО system — сразу перед
        # вызовом LLM (после {max_symbols}/owner-block/fallback-notice).
        prompt_telemetry = self._prompt_telemetry(system, prompt_source)
        if telemetry is not None:
            telemetry.update(prompt_telemetry)
        started = time.monotonic()
        _router = (tool_runtime or {}).get("router") \
            if isinstance(tool_runtime, dict) else None
        _tool_ctx = (tool_runtime or {}).get("ctx") \
            if isinstance(tool_runtime, dict) else None
        if _tool_schemas and _router is not None and _tool_ctx is not None:
            # SELF-DIAG-01 corrective (§3): ОДИН существующий tool-loop.
            # Рантайм-факты/логи уже в сообщениях; модель решает, какие
            # инструменты вызвать; результаты возвращаются ей же.
            from services.tool_loop import chat_with_tools
            loop_result = await chat_with_tools(
                self.llm,
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
                tools=list(_tool_schemas), router=_router, ctx=_tool_ctx,
                chat_id=chat_id, module="checkup",
                correlation_id=str(
                    (tool_runtime or {}).get("correlation_id") or ""))
            raw = str(loop_result)
            if telemetry is not None:
                research_tools = [
                    str(entry.get("tool") or "")
                    for entry in (loop_result.tool_results or ())
                    if isinstance(entry, dict)]
                telemetry.update({
                    "research_rounds": int(loop_result.rounds_used or 0),
                    "research_calls": len(loop_result.tool_results or ()),
                    "research_tools": ",".join(
                        sorted({name for name in research_tools if name})),
                    "research_degraded": bool(loop_result.degraded),
                    "research_reason": str(loop_result.reason or "ok"),
                })
        else:
            raw = await self.llm.generate(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
        logger.info(
            "checkup LLM OK | out_chars=%d | latency_ms=%.0f | used_fallback=%s",
            len(raw), (time.monotonic() - started) * 1000.0, used_fallback,
        )
        if telemetry is not None:
            telemetry.update({
                "latency_ms": int((time.monotonic() - started) * 1000.0),
                "report_chars": len(raw),
                "metrics_included": bool(metrics),
                "input_truncated": bool(input_truncated),
                "used_fallback": bool(used_fallback),
                "chat_scoped": chat_id is not None,
            })
        raw = cleanup_llm_text(raw)
        if not raw.strip():
            # Epic 60 (65.1, T-469): пустой ответ → молчание + 🗿 (хендлер
            # ничего не шлёт). Ветка хендлера ДО except LLMError.
            raise LLMBadResponseError("checkup: empty answer")
        # P0-CHECKUP (24.10.2026, addendum §5): исходящий Checkup-текст
        # проходит ДЕЙСТВУЮЩИЙ outbound Style Policy (dash.hard.factory,
        # настройки чата) — тот же единственный проход, что у Direct, без
        # второго движка/regex. Только пользовательская команда (chat_id);
        # внутренний tool-loop отдаёт данные Direct Writer, который применит
        # свой outbound-проход (без двойной обработки).
        if chat_id is not None:
            raw = await self._apply_outbound_style(raw, chat_id)
        return raw

    @staticmethod
    def _prompt_telemetry(system: str, source: str) -> dict:
        """SELF-DIAG-01 D6 B1 (`SD1-D6-05`): source/version/hash ФИНАЛЬНОГО
        system-сообщения — БЕЗ текста. Hash считается по ровно тем байтам,
        которые уходят в LLM (включая `{max_symbols}`, owner-block и
        fallback-notice), поэтому сверка «до/после релиза» опирается на факт."""
        text = str(system or "")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source = str(source or "default")
        return {
            "prompt_source": source,
            "prompt_hash": digest[:16],
            "prompt_version_used": f"{source}:{digest[:12]}",
            "prompt_chars": len(text),
        }

    @staticmethod
    async def _apply_outbound_style(text: str, chat_id: int) -> str:
        """Один проход существующего Style Policy; fail-open (текст как есть)."""
        try:
            from services import style_policy as _style_policy
            outcome = await _style_policy.apply_style_policy(
                text, chat_id=int(chat_id), context="regular",
                emit_events=True, stage="checkup_pre_send")
        except Exception:      # pragma: no cover - проход не роняет отправку
            logger.warning("[checkup] style policy pass failed | chat=%s",
                           chat_id, exc_info=True)
            return text
        if outcome.applied and str(outcome.text or ""):
            return outcome.text
        return text
