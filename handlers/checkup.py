"""Epic 42 — Checkup handler (R42-1, D162, Section 51.7).

Роутер 0g (после 0f web, под гейтом SUMMARY_ENABLED). Observer-стиль
(прецедент 0d search): не-триггер → return UNHANDLED, любой ответ → консьюм.
ВСЕ ответы (отчёт, 5.1, фолбек, dead, LLM-ошибка) — реплаем на
message.message_id (R42-1). Кулдаун per-chat (T-328-C): слот (chat_id, 0).

SELF-DIAG-01 D6 (`SD1-AC-01`, `SD1-AC-02`, `SD1-D6-07`): explicit-чекап
берёт диагностические факты у ТОГО ЖЕ `DiagnosticCollector`, что и
`inspect_runtime`/`get_bot_health` (`collect_for_checkup` → те же probes,
логи и bundle). Факты идут в user-контент ДАННЫМИ (перед логами), промпт и
характер чекапа не меняются; сбой collector'а не выключает чекап.
"""
import asyncio
import logging
import random
import re
import time
import uuid

from aiogram import Bot, Router, types
from aiogram.dispatcher.event.bases import UNHANDLED

from config.settings import settings
from services import command_prefix
from services import command_registry
from services import diagnostic_policy
from services import hot_config as hot
from services.llm_client import LLMBadResponseError, LLMError
from services.persistent_throttling import (
    cooldown_refresh,
    cooldown_remaining,
    cooldown_touch,
    make_cooldown,
)
from services.smartmodule_concurrency import (
    get_smartmodule_concurrency_pool,
    smartmodule_wait_seconds,
)
from services.smartmodule_phrases import (
    CHECKUP_DEAD_PHRASES,
    CHECKUP_FALLBACK_PHRASES,
    CHECKUP_LLM_ERROR_PHRASES,
    SMARTMODULE_BUSY_PHRASES,
)
from services.smartmodule_throttling import CooldownTracker
from services.smartmodule_utils import (
    _reply,
    react_moai,
    send_chunked_reply,
    throttle_phrase,
)
from services.system_logs_fetcher import CheckupLogsUnavailableException
from services.typing_manager import typing_active

logger = logging.getLogger(__name__)

checkup_router = Router(name="checkup")

_service = None                                   # CheckupService (DI)
_fetcher = None                                   # CheckupLogsFetcher (DI)
_diagnostics = None                               # DiagnosticCollector (DI)
_tool_router = None                               # ToolRouter (DI, SELF-DIAG §3)
_cooldown = CooldownTracker(settings.CHECKUP_COOLDOWN_SECONDS)
_CHAT_SLOT = 0                                    # per-chat кулдаун (T-328-C)

# Раунд 10.15 (F6, T-1596): ДВА пути.
# 1) bare-исключение «чекап» — как раньше (без префикса, слово целиком);
# 2) prefixed: Префикс + (ты в порядке|живой?|чекни здоровье) по остатку.
# F6-U1: legacy-фразы «живой собака», «пульс бота», «как сервак» из префиксного
# пути УДАЛЕНЫ.
_BARE_CHECKUP_RE = re.compile(
    r"(?:^|[\s\u00ab\u00bb\"'(\[\-])"
    r"чекап"
    r"(?=[\s!?.,;:\u2026\u00ab\u00bb)]*$)",
    re.IGNORECASE,
)


def _is_checkup_trigger(text: str) -> bool:
    """bare «чекап» ИЛИ префикс + канонический checkup-триггер (§5)."""
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _BARE_CHECKUP_RE.search(stripped):
        return True
    tok, body = command_prefix.split_prefix(stripped)
    if tok is None:
        return False
    return command_registry.matches_group("checkup", body)


def setup_checkup(service, fetcher, db=None, diagnostics=None) -> None:
    """DI: CheckupService + CheckupLogsFetcher. Вызывается из bot.py
    on_startup (51.9). Epic 60 (63.1): db + THROTTLE_PERSISTENT_ENABLED →
    персистентный кулдаун (throttle_state, scope='checkup').

    SELF-DIAG-01 D6: ``diagnostics`` — необязательный общий
    `DiagnosticCollector` (тот же экземпляр, что у ToolRouter); None →
    collector собирается лениво из существующих зависимостей сервиса.
    ``False`` — явный opt-out (изолированный тест/стенд: probes не
    исполняются, payload = логи, как до D6)."""
    global _service, _fetcher, _cooldown, _diagnostics
    _service = service
    _fetcher = fetcher
    _diagnostics = diagnostics
    _cooldown = make_cooldown(
        "checkup", settings.CHECKUP_COOLDOWN_SECONDS, db)


def reset_checkup_diagnostics_for_tests() -> None:
    """Тестовая изоляция DI: сбросить общий collector (не влияет на прод)."""
    global _diagnostics
    _diagnostics = None


def setup_checkup_tool_router(router) -> None:
    """DI существующего ToolRouter для исследовательского цикла чекапа.

    SELF-DIAG-01 corrective (§3): второго tool-loop/роутера нет — handler
    передаёт CheckupService тот же экземпляр, что обслуживает Direct.
    Вызывается из bot.py ПОСЛЕ сборки ToolRouter (порядок setup чекапа не
    меняется); None → прежний одиночный LLM-вызов.
    """
    global _tool_router
    _tool_router = router


def checkup_probe_deps():
    """SELF-DIAG-01 D6 B4: `ProbeDeps` из уже собранных сервисов бота.

    Используется админским снимком (`/api/status/self-diagnosis`) ТОЛЬКО для
    расчёта `configured` в каталоге probes — probes не исполняются. Набор
    зависимостей тот же, что у чекапа/`inspect_runtime` (db/memory/fetcher/
    status), поэтому «configured» отражает реальную среду, а не пустой stub.
    """
    from services.runtime_probes import ProbeDeps

    status = None
    try:
        from services.status_service import status as _status
        status = _status
    except Exception:      # pragma: no cover - защитная ветка
        status = None
    return ProbeDeps(
        db=getattr(_service, "db", None),
        memory=getattr(_service, "memory", None),
        logs_fetcher=_fetcher, status=status)


def _diagnostics_collector():
    """Один collector для explicit-чекапа (ТЗ §2.1 п.1).

    Тот же `DiagnosticCollector`, что у `inspect_runtime`/`get_bot_health`:
    ProbeDeps собираются из существующих db/memory/fetcher/status сервиса.
    None — DI отключён (явный opt-out).
    """
    global _diagnostics
    if _diagnostics is False:
        return None
    if _diagnostics is not None:
        return _diagnostics
    from services.diagnostic_collector import DiagnosticCollector
    from services.runtime_probes import ProbeLimits

    collector = DiagnosticCollector(
        deps=checkup_probe_deps(), limits=ProbeLimits.from_env())
    _diagnostics = collector
    return collector


def _decision_fields(decision) -> dict | None:
    """Решение политики → машинные поля для bundle.access (без секретов)."""
    if decision is None:
        return None
    return {
        "evaluated": True,
        "effect": getattr(decision, "effect", ""),
        "reason_code": getattr(decision, "reason_code", ""),
        "capability": getattr(decision, "capability", ""),
        "action": getattr(decision, "action", ""),
        "data_class": getattr(decision, "data_class", ""),
        "role": getattr(decision, "role", ""),
        "matrix_role": getattr(decision, "matrix_role", ""),
        "source": getattr(decision, "source", ""),
    }


async def _collect_checkup_facts(logs: str, used_fallback: bool,
                                 chat_id: int, gate, *,
                                 log_state: str = "",
                                 journal_state: str = "") -> tuple[dict, str, str]:
    """Факты того же collector'а для user-контента чекапа.

    Возвращает ``(bundle, facts_text, error)``. Любая ошибка collector'а —
    честный ``error`` и пустые facts: отчёт строится на логах, как раньше
    (`SD1-D6-09`/`SD1-D6-22`, чекап не выключается).

    SXR-H5: ``log_state``/``journal_state`` — фактический исход уже
    выполненного ``fetch()``. Collector не читает журнал второй раз.
    """
    try:
        collector = _diagnostics_collector()
        if collector is None:            # явный opt-out DI: фактов нет
            return {}, "", ""
        bundle, facts_text = await collector.collect_for_checkup(
            logs_text=logs, used_fallback=used_fallback, chat_id=chat_id,
            permission=_decision_fields(getattr(gate, "decision", None)),
            log_state=log_state, journal_state=journal_state)
        return bundle.to_dict(), str(facts_text or ""), ""
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("[checkup] diagnostics collector failed | chat=%s | "
                       "error=%s", chat_id, type(exc).__name__)
        return {}, "", type(exc).__name__


async def _build_checkup_tool_runtime(chat_id: int, actor_id, bot,
                                      correlation_id: str):
    """Существующий tool-loop для чекапа (SELF-DIAG-01 §3).

    Возвращает ``{"router","ctx","schemas","correlation_id"}`` либо ``None``:
    роутер не подключён (тест/изолированный стенд) — прежний одиночный
    LLM-вызов. Схемы — только read-only диагностические инструменты,
    объявленные СУЩЕСТВУЮЩИМ `active_tools` (env-гейты/порядок сохраняются).
    """
    if _tool_router is None:
        return None
    try:
        from services import direct_capabilities as _caps
        from services.tool_schemas import active_tools
        from services.tool_router import ToolContext

        names: list[str] = []
        for capability in ("source_code", "deep_diagnostics"):
            for tool_name in _caps.CAPABILITY_TOOLS.get(capability, ()):
                if tool_name not in names:
                    names.append(tool_name)
        schemas = _caps.schemas_for_names(
            names, active_tools(False, False))
        if not schemas:
            return None
        ctx = ToolContext(chat_id, "", bot=bot, user_id=actor_id,
                          correlation_id=correlation_id)
        # Чекап — про собственный Adminbot: структурная identity разрешена
        # заранее, но чтение кода выполняет ТОЛЬКО модель своим tool_call.
        try:
            from services import source_reader as _sr
            ctx.diagnostic_research = await asyncio.to_thread(
                _sr.resolve_self_repo_identity)
        except Exception:
            logger.warning("[checkup] self repo identity unavailable | "
                           "chat=%s", chat_id, exc_info=True)
        return {"router": _tool_router, "ctx": ctx, "schemas": schemas,
                "correlation_id": correlation_id}
    except Exception:
        logger.warning("[checkup] tool runtime unavailable | chat=%s",
                       chat_id, exc_info=True)
        return None


async def _persist_checkup_conversation(*, chat_id: int, sent_id,
                                        report: str, parent_id,
                                        correlation_id: str, bot) -> None:
    """Отчёт чекапа — полноценное сообщение разговора (SELF-DIAG-01 §4).

    Использует СУЩЕСТВУЮЩИЕ механизмы Direct: `bot_replies` (reply-цепочка)
    и durable `mca_bot_outputs` (`output_kind='checkup_report'`), чтобы L1
    продолжения видел фактически доставленный отчёт структурно, а не по
    угаданным словам. Fail-open: сбой записи не влияет на отправку.
    """
    if sent_id is None:
        return
    db = getattr(_service, "db", None)
    if db is None:
        return
    now = time.time()
    try:
        await db.upsert_bot_reply(int(chat_id), int(sent_id), str(report), now)
        await db.set_bot_reply_parent(int(chat_id), int(sent_id),
                                      parent_id, now)
    except Exception:
        logger.warning("[checkup] bot_replies persist failed | chat=%s",
                       chat_id, exc_info=True)
    try:
        from services import bot_output_ledger as _ledger
        await _ledger.record_delivered_output(
            db, chat_id=int(chat_id), tg_message_id=int(sent_id),
            text=str(report or ""),
            bot_user_id=getattr(bot, "id", None),
            output_kind="checkup_report", sent_at=int(now),
            parent_message_ref=(f"tg:{int(parent_id)}"
                                if parent_id is not None else None),
            correlation_id=correlation_id, source_feature="checkup")
    except Exception:
        logger.warning("[checkup] output ledger persist failed | chat=%s",
                       chat_id, exc_info=True)


def _identity_log_line(bundle: dict) -> str:
    """`[checkup] identity` — только машинные поля (R17, без payloads)."""
    sources = bundle.get("sources") or []
    runtime = bundle.get("runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    ok = sum(1 for src in sources
             if isinstance(src, dict) and src.get("status") == "ok")
    return (
        "[checkup] identity | runtime=%s | deployed_sha=%s | checkout_sha=%s "
        "| source_verified=%s | git_meta=%s | commits_since_deploy=%s "
        "| sources=%d/%d | status=%s" % (
            str(runtime.get("runtime_type") or "")[:24],
            str(bundle.get("runtime_sha") or "")[:12],
            str(bundle.get("git_head_sha") or "")[:12],
            bundle.get("source_verified"),
            bool(bundle.get("git_metadata_attempted")),
            bundle.get("commits_since_deploy"),
            ok, len(sources),
            str(bundle.get("status") or ""),
        ))


def emit_checkup_validation_event(*, chat_id: int | None, publication) -> None:
    """SELF-DIAG-01 D6 B3 (`SD1-D6-17`): чекап прошёл output validation.

    Отдельное событие (не `diagnostic_output_validated`), потому что чекап не
    идёт через `ToolRouter._diagnostic_output`: без него аналитика не может
    доказать, что enforcement реально применялся к доставленному отчёту.
    Пишутся только статус redaction и факт прохождения — без текста.

    B3-residual: `Publication.status` — свойство (`clean`/`partially_redacted`/
    `blocked`/`denied`), а не `.report`. Событие эмитится ТОЛЬКО для реально
    разрешённой к доставке публикации: заблокированная проверка не должна
    закрывать gap успешной доставки.
    """
    try:
        if not bool(getattr(publication, "allowed", False)):
            return
        from services import mca_events as _mca_events
        status = str(getattr(publication, "status", "") or "unknown")[:40]
        _mca_events.emit_mca_event(
            "checkup_output_validated", outcome="success",
            component="checkup", stage="final", status=status,
            chat_id=chat_id)
    except Exception:      # pragma: no cover - телеметрия fail-open
        return


def emit_checkup_event(*, outcome: str, chat_id: int | None, status: str = "",
                       duration_ms: int = 0, bundle: dict | None = None,
                       telemetry: dict | None = None) -> None:
    """SELF-DIAG-01 D6 (`SD1-D6-05`): одна терминальная запись чекапа.

    Существующий контракт `mca_events`: имя события — `checkup_triggered`,
    машинные метаданные (prompt source/version/hash, bundle delivered/
    truncated, источники) — в `source_ref_json`. Текстов промпта/отчёта нет.
    """
    try:
        from services import mca_events as _mca_events
    except Exception:      # pragma: no cover - защитная ветка
        return
    try:
        payload = dict(telemetry or {})
        if bundle:
            coverage = bundle.get("coverage")
            coverage = coverage if isinstance(coverage, dict) else {}
            payload.update({
                "bundle_delivered": True,
                "bundle_status": str(bundle.get("status") or "")[:24],
                "bundle_truncated": bool(coverage.get("truncated")),
                "sources": len(bundle.get("sources") or ()),
                "not_checked": len(bundle.get("not_checked") or ()),
            })
        else:
            payload["bundle_delivered"] = False
        _mca_events.emit_mca_event(
            "checkup_triggered", outcome=outcome,
            level=("INFO" if outcome == "success" else "WARN"),
            component="checkup", stage="final",
            status=str(status or "")[:40] or None,
            duration_ms=int(duration_ms or 0),
            chat_id=chat_id, source_ref_json=payload or None)
    except Exception:      # pragma: no cover - телеметрия fail-open
        return



def _diag_runtime():
    """(cache, pg) существующего слоя прав; недоступность — не падение."""
    try:
        cache = hot.get_config_cache()
    except Exception:
        cache = None
    pg = getattr(cache, "pg", None) if cache is not None else None
    if getattr(pg, "pool", None) is None:
        pg = None
    return cache, pg


async def _checkup_diagnostic_gate(actor_id, chat_id, bot=None):
    """Разрешение на чекап: запуск проверки + право видеть логи чата.

    Возвращает `(gate, denied_decision)`: `gate` — открытое разрешение для
    перепроверки перед публикацией; `denied_decision` — отказ политики
    (тогда отчёт не формируется и логи не читаются).

    `bot` обязателен для живой проверки админства: без него политика не
    может подтвердить строку `local_admin` и отказывает подтверждённому
    админу чата. Недоступность слоя прав — это ОТКАЗ, а не обход: без
    проверки запрет доказать нельзя, поэтому чекап не выполняется.
    """
    cache, pg = _diag_runtime()
    try:
        gate = await diagnostic_policy.open_gate(
            "bot_server_state", "run", telegram_id=actor_id,
            chat_id=chat_id, cache=cache, bot=bot, pg=pg,
            destination="checkup",
            also=(("logs_traceback", "view"),))
    except Exception:
        logger.warning("[checkup] diagnostic policy unavailable — checkup "
                       "denied | chat=%s", chat_id, exc_info=True)
        return None, diagnostic_policy.policy_unavailable_denial(
            "bot_server_state", "run", chat_id=chat_id)
    if not gate.decision.allowed:
        return gate, gate.decision
    return gate, None


@checkup_router.message()
async def checkup_handler(message: types.Message, bot: Bot = None) -> None:
    if _service is None or _fetcher is None or bot is None:
        return UNHANDLED
    # Раунд 10.6 (T-1201/A1): master-флаг модуля (default ON).
    if not hot.get("flags.checkup_enabled", settings.CHECKUP_ENABLED):
        return UNHANDLED
    text = (message.text or message.caption or "").strip()
    if not text or not _is_checkup_trigger(text):
        return UNHANDLED                       # не триггер → пропагация живёт
    user_id = message.from_user.id if message.from_user else 0
    logger.info("[checkup] triggered | chat=%s user=%s", message.chat.id, user_id)
    started = time.monotonic()
    bundle: dict = {}
    facts_error = ""
    # SELF-DIAG-01 D6 B1: per-run телеметрия чекапа — свой словарь на вызов,
    # поэтому одновременные чекапы разных чатов не смешиваются.
    run_telemetry: dict = {}
    emit_state: dict = {"outcome": "skipped", "status": ""}

    def _finish(outcome: str, status: str = "") -> None:
        emit_state["outcome"] = outcome
        emit_state["status"] = status
    # T-619: кулдаун — горячая точка (ConfigCache → settings-фолбек)
    cooldown_refresh(_cooldown, hot.get("limits.checkup_cooldown_seconds",
                                        settings.CHECKUP_COOLDOWN_SECONDS))
    remaining = await cooldown_remaining(_cooldown, message.chat.id, _CHAT_SLOT)
    if remaining > 0:                          # 5.1 → реплай на триггер
        await _reply(bot, message.chat.id, throttle_phrase(remaining),
                     message.message_id)
        emit_checkup_event(outcome="skipped", chat_id=message.chat.id,
                           status="cooldown",
                           duration_ms=int((time.monotonic() - started) * 1000))
        return
    await cooldown_touch(_cooldown, message.chat.id, _CHAT_SLOT)
    # SELF-DIAG-01 D2 (owner amendment 2026-11-09 §5): «чекап» — такой же
    # вход, как tool/API, и не является обходом политики диагностики.
    # Решение принимается ДО чтения логов; отчёт перепроверяется и
    # очищается от секретов ПЕРЕД отправкой. Промпт и характер чекапа не
    # меняются — гейт стоит только на доступе к данным.
    actor_id = message.from_user.id if message.from_user else None
    gate, denied = await _checkup_diagnostic_gate(actor_id, message.chat.id,
                                                  bot=bot)
    if denied is not None:
        logger.info("[checkup] denied by diagnostic policy | chat=%s user=%s "
                    "| reason=%s", message.chat.id, actor_id,
                    denied.reason_code)
        await _reply(bot, message.chat.id,
                     diagnostic_policy.denial_message(denied),
                     message.message_id)
        emit_checkup_event(outcome="skipped", chat_id=message.chat.id,
                           status="denied",
                           duration_ms=int((time.monotonic() - started) * 1000))
        return
    if gate is None:                       # защита от будущих правок: без
        logger.error("[checkup] no gate — report is not published | chat=%s",
                     message.chat.id)      # разрешения публикации не бывает
        emit_checkup_event(outcome="skipped", chat_id=message.chat.id,
                           status="no_gate",
                           duration_ms=int((time.monotonic() - started) * 1000))
        return
    try:
        logs, used_fallback = await _fetcher.fetch()
        # SXR-H5: фактический исход этого чтения (не догадка). Fakes/старые
        # fetcher'ы без свойства честно дают "" -> collector скажет unknown.
        log_state = str(getattr(_fetcher, "last_state", "") or "")
        journal_state = str(getattr(_fetcher, "last_journal_state", "") or "")
    except CheckupLogsUnavailableException as exc:
        # Epic 49 (D199): WARNING без traceback (ожидаемая ветка, D190-стиль)
        logger.warning("[checkup] all log sources failed | chat=%s | error=%s",
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_DEAD_PHRASES),
                     message.message_id)
        emit_checkup_event(outcome="failed", chat_id=message.chat.id,
                           status="logs_unavailable",
                           duration_ms=int((time.monotonic() - started) * 1000))
        return
    if used_fallback:                          # R42-2: фолбек-фраза ДО LLM (юзер ждёт)
        logger.warning("[checkup] fallback phrase sent | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_FALLBACK_PHRASES),
                     message.message_id)
    # Раунд N (T-841): слот пула per-chat перед LLM-вызовом checkup
    # (fetch логов выше — сетевой шаг, в пул не входит). Таймаут → busy-фраза.
    pool = get_smartmodule_concurrency_pool()
    permit = await pool.try_acquire(message.chat.id,
                                    timeout=smartmodule_wait_seconds())
    if permit is None:
        logger.warning("[checkup] concurrency slot timeout | chat=%s",
                       message.chat.id)
        await _reply(bot, message.chat.id,
                     random.choice(SMARTMODULE_BUSY_PHRASES),
                     message.message_id)
        emit_checkup_event(outcome="skipped", chat_id=message.chat.id,
                           status="busy",
                           duration_ms=int((time.monotonic() - started) * 1000))
        return
    try:
        # Epic 60 (65.7, T-475): «печатает…» вокруг _service.checkup (65.7).
        async with typing_active(bot, message.chat.id):
            # SELF-DIAG-01 D6 (`SD1-AC-02`): тот же collector, что у
            # inspect_runtime — реальные локальные логи, метрики процесса и
            # памяти, job statuses, deployed identity и ограниченная попытка
            # commit metadata. Сбой collector'а — честный partial, не отказ.
            bundle, facts_text, facts_error = await _collect_checkup_facts(
                logs, used_fallback, message.chat.id, gate,
                log_state=log_state, journal_state=journal_state)
            if bundle:
                logger.info(_identity_log_line(bundle))
            # SXR-H5: исход чтения журнала виден в существующей телеметрии
            # чекапа; текст логов сюда не попадает.
            run_telemetry["log_state"] = log_state or "unknown"
            run_telemetry["journal_state"] = journal_state or "unknown"
            payload = (facts_text + "\n" + logs) if facts_text else logs
            # SELF-DIAG-01 corrective (§3): исследовательский цикл на
            # СУЩЕСТВУЮЩЕМ ToolRouter; модель решает, читать ли код/runtime.
            correlation_id = f"checkup:{uuid.uuid4().hex}"
            tool_runtime = await _build_checkup_tool_runtime(
                message.chat.id, actor_id, bot, correlation_id)
            # UNIFIED-CORE (P0, 20.10.2026): chat_id → Core + Expression
            # владельца в канон чек-апа (пользовательский речевой маршрут).
            report = await _service.checkup(
                payload, used_fallback, chat_id=message.chat.id,
                telemetry=run_telemetry, tool_runtime=tool_runtime)
        # SELF-DIAG-01 D2: перепроверка прав ПЕРЕД публикацией (отзыв
        # действует на уже запущенную проверку) + удаление секретов.
        try:
            pub_cache, pub_pg = _diag_runtime()
            publication = await diagnostic_policy.publish(
                gate, report, cache=pub_cache, bot=bot, pg=pub_pg,
                kind="final")
        except Exception:
            logger.exception("[checkup] publication guard failed | chat=%s",
                             message.chat.id)
            _finish("failed", "publication_guard_failed")
            return
        if not publication.allowed:
            logger.info("[checkup] publication blocked | chat=%s | "
                        "reason=%s", message.chat.id,
                        publication.decision.reason_code)
            await _reply(bot, message.chat.id,
                         diagnostic_policy.denial_message(
                             publication.decision),
                         message.message_id)
            _finish("failed", "publication_blocked")
            return
        # SELF-DIAG-01 D6 B3: проверка вывода ДЛЯ ЭТОГО доставляемого отчёта
        # (наличие события = enforcement измерен; статус clean/partially_
        # redacted). Заблокированная публикация события не даёт и gap не
        # закрывает.
        emit_checkup_validation_event(chat_id=message.chat.id,
                                      publication=publication)
        report = publication.text
        sent_ids: list = []
        sent_id = await send_chunked_reply(
            bot, message.chat.id, report, message.message_id,
            sent_ids=sent_ids)
        # SELF-DIAG-01 corrective (§4): доставленный отчёт становится
        # сообщением разговора для продолжения (reply-цепочка + ledger).
        await _persist_checkup_conversation(
            chat_id=message.chat.id, sent_id=sent_id, report=report,
            parent_id=message.message_id, correlation_id=correlation_id,
            bot=bot)
        run_telemetry["report_chunks"] = len(sent_ids)
        logger.info("[checkup] report sent | chat=%s", message.chat.id)
        _finish("success", "report_sent")
    except LLMBadResponseError as exc:
        # Epic 60 (65.1, T-469): пустой ответ модели → молчание + 🗿 (НЕ R13).
        logger.warning("[checkup] empty answer — silence | chat=%s | error=%s",
                       message.chat.id, exc)
        await react_moai(bot, message.chat.id, message.message_id)
        _finish("silent", "empty_answer")
    except LLMError as exc:
        # Epic 47/49 (D190/D199): WARNING без traceback (ожидаемая ветка)
        logger.warning("[checkup] LLM failed | chat=%s | error=%s",
                       message.chat.id, exc)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_LLM_ERROR_PHRASES),
                     message.message_id)
        _finish("failed", "llm_error")
    except Exception:
        logger.exception("[checkup] unexpected error | chat=%s", message.chat.id)
        await _reply(bot, message.chat.id, random.choice(CHECKUP_LLM_ERROR_PHRASES),
                     message.message_id)
        _finish("failed", "unexpected_error")
    finally:
        telemetry = dict(run_telemetry)
        if facts_error:
            telemetry["facts_error"] = facts_error[:64]
        emit_checkup_event(
            outcome=emit_state["outcome"], chat_id=message.chat.id,
            status=emit_state["status"],
            duration_ms=int((time.monotonic() - started) * 1000),
            bundle=bundle or None, telemetry=telemetry)
        permit.release()
