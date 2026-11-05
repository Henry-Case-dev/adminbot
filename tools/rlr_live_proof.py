#!/usr/bin/env python3
"""RLR-07 / R-09 live proof runner — REAL provider, no Telegram.

Назначение (только доказательство, продуктовая логика не меняется):

* гоняет НАСТОЯЩИЙ `DirectChatService.handle` / `handle_initiative` /
  `FactCheckService.check_claim` с НАСТОЯЩИМ `LLMClient` (ключи из `.env`);
* Telegram-транспорт подменён на самом последнем шаге (`bot.send_message`),
  поэтому ни одно сообщение физически не может уйти в сеть;
* снимает пер-ходовую трассу `services/turn_trace.py` двумя независимыми
  способами: (1) in-memory объект `TurnTrace`, (2) durable события
  `mca_events` через `flush_events` + `query_events(trace_id=...)`;
* независимо пересчитывает digest'ы (blake2s-8, как `turn_trace.text_digest`)
  по фактически сгенерированному и фактически «отправленному» тексту.

Наблюдатели (monkeypatch только на ЧТЕНИЕ, поведение не меняется):
`turn_trace.begin` (перехват correlation_id), `turn_trace.note_l2_completion`,
`note_l2_refusal`, `note_delivery`, `note_op`, `note_llm_call`,
`DirectChatService._plan_direct_l1` (сохранение L1-плана, чтобы увидеть
`preserve_source_facts`).

Запуск:
    py -3 tools/rlr_live_proof.py --env-file <path>/.env --out <dir> \
        [--only s1,s2] [--longform-max-tokens 120] [--log-file <path>] \
        [--watchdog <сек>]

Ничего не печатает из ключей (R17). Тексты чата в JSON не пишутся целиком:
только digest'ы, длины, короткие фрагменты и результат посимвольной сверки
«написано ↔ к отправке» (`delta_is_punctuation_only`).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_ID = -1001234567890
USER_ID = 10

#: Фактические provider-HTTP-запросы (независимо от трассы).
HTTP_CALLS: list[dict] = []
_LOG_STREAM = None


# ── инфраструктура ──────────────────────────────────────────────────────────

def _bootstrap(env_file: str | None, run_dir: str,
               log_file: str | None = None) -> None:
    """До импорта config.settings: env из .env + изоляция побочных файлов."""
    os.environ.setdefault(
        "STATUS_KEY_HISTORY_FILE", os.path.join(run_dir, "keyhist.json"))
    if env_file:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    os.chdir(REPO)
    if log_file:
        global _LOG_STREAM
        _LOG_STREAM = open(log_file, "a", encoding="utf-8")
        import logging
        logging.basicConfig(level=logging.INFO, stream=_LOG_STREAM,
                            force=True)


def _digest(text) -> str:
    src = str(text if text is not None else "")
    if not src:
        return ""
    return hashlib.blake2s(src.encode("utf-8"), digest_size=8).hexdigest()


def _excerpt(text, limit: int = 180) -> str:
    src = str(text if text is not None else "").replace("\r", " ").replace("\n", " ")
    return src[:limit] + ("…" if len(src) > limit else "")


def _tail(text, limit: int = 90) -> str:
    src = str(text if text is not None else "").replace("\r", " ").replace("\n", " ")
    return ("…" if len(src) > limit else "") + src[-limit:]


class RecordingBot:
    """Подмена Telegram-транспорта. Ничего не отправляет — только пишет."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.reactions: list[dict] = []
        self.actions = 0
        # aiogram `ChatActionSender` читает `bot.id` ДО try/except в воркере:
        # без атрибута задача индикатора умирает, а `_stop` ждёт вечно.
        self.id = 12345
        self.username = "test_bot"

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append({
            "chat_id": int(chat_id) if chat_id is not None else None,
            "text": str(text),
            "chars": len(str(text)),
            "reply_to_message_id": kwargs.get("reply_to_message_id"),
            "parse_mode": kwargs.get("parse_mode"),
            "telegram_sent": False,
        })
        return _FakeSentMessage(9000 + len(self.messages))

    async def send_chat_action(self, *args, **kwargs):
        self.actions += 1

    async def set_message_reaction(self, chat_id=None, message_id=None,
                                   reaction=None, **kwargs):
        self.reactions.append({
            "chat_id": chat_id, "message_id": message_id,
            "count": len(reaction or ()),
        })


class _FakeSentMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class Observer:
    """Пассивные перехватчики трассы (только чтение, поведение не меняется)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cid = None
        self.completions: list[dict] = []
        self.refusals: list[dict] = []
        self.deliveries: list[dict] = []
        self.ops: list[dict] = []
        self.llm_calls: list[dict] = []
        self.l1_plan = None
        self.l1_meta = None
        self._patches: list[tuple] = []

    def install(self) -> None:
        from services import turn_trace as tt

        def _wrap(mod, name, maker):
            orig = getattr(mod, name)

            def wrapper(*a, **k):
                try:
                    maker(*a, **k)
                except Exception:
                    pass
                return orig(*a, **k)
            setattr(mod, name, wrapper)
            self._patches.append((mod, name, orig))

        def _on_begin(correlation_id, *a, **k):
            if self.cid is None:
                self.cid = str(correlation_id)

        def _on_completion(correlation_id, *a, **k):
            self.completions.append({
                "correlation_id": str(correlation_id),
                "raw_text": k.get("raw_text", ""),
                "final_text": k.get("final_text", ""),
                "stats": dict(k.get("stats") or {}),
                "completion": k.get("completion"),
                "continuation": k.get("continuation"),
            })

        def _on_refusal(correlation_id, reason=None, **k):
            self.refusals.append({
                "correlation_id": str(correlation_id), "reason": reason,
                "text": k.get("text", ""),
                "stop_reason": k.get("stop_reason"),
                "finish_reason": k.get("finish_reason"),
                "continuation_calls": k.get("continuation_calls"),
            })

        def _on_delivery(correlation_id, **k):
            self.deliveries.append({
                "correlation_id": str(correlation_id),
                "outcome": k.get("outcome"),
                "payload": k.get("payload"),
                "reason": k.get("reason"),
                "channel": k.get("channel"),
            })

        def _on_op(correlation_id, name=None, text=None):
            self.ops.append({"op": str(name), "text": str(text or ""),
                             "digest": _digest(text), "chars": len(str(text or ""))})

        def _on_llm(correlation_id, kind=None, count=1):
            self.llm_calls.append({"kind": str(kind), "count": int(count)})

        _wrap(tt, "begin", _on_begin)
        _wrap(tt, "note_l2_completion", _on_completion)
        _wrap(tt, "note_l2_refusal", _on_refusal)
        _wrap(tt, "note_delivery", _on_delivery)
        _wrap(tt, "note_op", _on_op)
        _wrap(tt, "note_llm_call", _on_llm)

        import services.direct_chat_service as dcs
        orig_plan = dcs.DirectChatService._plan_direct_l1

        async def plan_wrapper(self_, *a, **k):
            result = await orig_plan(self_, *a, **k)
            try:
                if isinstance(result, tuple) and result:
                    self.l1_plan = result[0]
                    self.l1_meta = result[1] if len(result) > 1 else None
            except Exception:
                pass
            return result

        dcs.DirectChatService._plan_direct_l1 = plan_wrapper
        self._patches.append(
            (dcs.DirectChatService, "_plan_direct_l1", orig_plan))

    def uninstall(self) -> None:
        for target, name, orig in reversed(self._patches):
            setattr(target, name, orig)
        self._patches = []


# ── сборка реальных объектов ────────────────────────────────────────────────

def _real_llm(*, bad_primary: bool = False, fallback_to_main: bool = False):
    from config.settings import settings
    from services.llm_client import LLMClient

    kwargs = dict(
        embed_model=settings.EMBEDDING_MODEL_NAME,
        embed_base_url=settings.EMBEDDING_BASE_URL,
        embed_api_key=settings.EMBEDDING_API_KEY,
    )
    if bad_primary:
        # Принудительный provider-fallback: невалидный primary-адрес,
        # рабочий LLM_FALLBACK_*. Продуктовый код не меняется.
        kwargs.update(
            base_url="http://127.0.0.1:9/v1",
            api_key="invalid-primary-key",
            chat_model="invalid/primary-model",
            max_retries=0,
            timeout=5.0,
        )
        if fallback_to_main:
            # .env-фоллбек (api.deepseek.com) отвечает 401 — ключ неавторизован.
            # Чтобы проверить САМ путь фоллбека, вторая нога настраивается на
            # рабочий провайдер/модель (тот же ключ). Это не продуктовая правка:
            # клиент конструируется раннером.
            kwargs.update(
                fallback_base_url=settings.LLM_BASE_URL,
                fallback_model=settings.LLM_MODEL_NAME,
                fallback_api_key=settings.LLM_API_KEY,
            )
    else:
        kwargs.update(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            chat_model=settings.LLM_MODEL_NAME,
        )
    client = LLMClient(**kwargs)
    client.backoff_base = 0.0
    if os.environ.get("RLR_PROOF_VERBOSE") == "1":
        _instrument_llm(client)
    return client


def _log(msg: str) -> None:
    line = "[proof] %s" % msg
    print(line, file=sys.stderr, flush=True)
    if _LOG_STREAM is not None:
        print(line, file=_LOG_STREAM, flush=True)


def _instrument_llm(client) -> None:
    """Диагностика раннера: реально ушедшие HTTP-вызовы провайдера.

    Оборачиваются ТОЧКИ ОТПРАВКИ клиента (`_post_with_key` — primary,
    `_post_fallback` — fallback-нога). Это не меняет классификацию вызовов
    (`generate_with_metadata` остаётся классовым методом), но даёт раннеру
    независимый от трассы список фактических provider-запросов.
    """
    for name, channel in (("_post_with_key", "primary"),
                          ("_post_fallback", "fallback")):
        orig = getattr(client, name, None)
        if orig is None:
            continue

        def make(orig_, label):
            async def wrapper(*a, **k):
                payload = a[1] if len(a) > 1 else k.get("payload") or {}
                body = payload if isinstance(payload, dict) else {}
                started = time.monotonic()
                _log("http.%s start model=%s max_tokens=%s"
                     % (label, body.get("model"), body.get("max_tokens")))
                try:
                    result = await orig_(*a, **k)
                except Exception as exc:
                    _log("http.%s fail after %.1fs: %s"
                         % (label, time.monotonic() - started,
                            type(exc).__name__))
                    HTTP_CALLS.append({
                        "channel": label, "model": body.get("model"),
                        "max_tokens": body.get("max_tokens"),
                        "ms": int((time.monotonic() - started) * 1000),
                        "error": type(exc).__name__,
                    })
                    raise
                _log("http.%s done in %.1fs" % (label,
                                                time.monotonic() - started))
                HTTP_CALLS.append({
                    "channel": label, "model": body.get("model"),
                    "max_tokens": body.get("max_tokens"),
                    "ms": int((time.monotonic() - started) * 1000),
                    "error": None,
                })
                return result
            return wrapper
        setattr(client, name, make(orig, channel))


def _service(llm, *, search=None, db=None):
    from services.direct_chat_service import DirectChatService
    from services.summary_aliases import AliasResolver
    from services.tool_router import ToolDeps, ToolRouter
    from tests.test_direct_chat import FakeMemory

    memory = FakeMemory(window=[{
        "user_id": USER_ID, "author_name": "Вася", "text": "привет",
        "timestamp": int(time.time()) - 600, "media_type": "text",
        "reply_to_id": None, "tg_message_id": 90}])
    router = None
    if search is not None:
        router = ToolRouter(ToolDeps(search=search, memory=memory, db=db))
    return DirectChatService(
        memory, db, llm, AliasResolver('{"10": "Вася"}'),
        bot_id=12345, bot_username="test_bot", tool_router=router,
    )


async def _fresh_db():
    from services.database import DatabaseService
    db = DatabaseService(":memory:")
    await db.initialize()
    return db


def _message(text: str, message_id: int = 100):
    from tests.test_direct_chat import _message as _mk
    return _mk(text=text, message_id=message_id)


def _user():
    from tests.test_direct_chat import _user as _mk
    return _mk()


# ── снятие трассы ───────────────────────────────────────────────────────────

async def _trace_snapshot(db, cid):
    from services import mca_events, turn_trace

    events = []
    if db is not None:
        try:
            await mca_events.flush_events(db)
            rows = await mca_events.query_events(db, trace_id=cid, limit=50)
            for row in rows:
                usage = row.get("usage_json")
                if isinstance(usage, str):
                    try:
                        usage = json.loads(usage)
                    except Exception:
                        usage = {"raw_head": usage[:300]}
                elif isinstance(usage, (bytes, bytearray)):
                    try:
                        usage = json.loads(usage.decode("utf-8"))
                    except Exception:
                        usage = {"raw_head": "bytes"}
                events.append({
                    "event": row.get("event_name"),
                    "stage": row.get("stage"),
                    "outcome": row.get("outcome"),
                    "usage": usage,
                })
        except Exception as exc:
            events = [{"error": type(exc).__name__}]

    trace = turn_trace.get(cid) if cid else None
    snap = {}
    if trace is not None:
        snap = {
            "flow": trace.flow,
            "trigger": trace.trigger,
            "l1": dict(trace.l1),
            "llm_calls": dict(trace.llm_calls),
            "tools": list(trace.tools),
            "tool_rounds": trace.tool_rounds,
            "manifest": dict(trace.manifest),
            "request": dict(trace.request),
            "completion": dict(trace.completion),
            "semantic_rewrite_count": trace.semantic_rewrite_count,
            "raw_final_digest": trace.raw_final_digest,
            "delivered_digest": trace.delivered_digest,
            "digest_match": trace.digest_match,
            "divergence_reason": trace.divergence_reason,
            "ops": list(trace.ops),
            "delivery": dict(trace.delivery),
            "stop_reason": trace.stop_reason,
            "stop_outcome": trace.stop_outcome,
        }
    return snap, events


async def _drain_tasks(seconds: float = 8.0) -> int:
    pending = [t for t in asyncio.all_tasks()
               if t is not asyncio.current_task() and not t.done()]
    if not pending:
        return 0
    done, still = await asyncio.wait(pending, timeout=seconds)
    for task in still:
        task.cancel()
    return len(done)


# ── сценарии ────────────────────────────────────────────────────────────────

async def run_direct(*, text: str, search=None, bad_primary: bool = False,
                     fallback_to_main: bool = False, message_id: int = 100):
    observer = Observer()
    observer.install()
    db = await _fresh_db()
    llm = _real_llm(bad_primary=bad_primary,
                    fallback_to_main=fallback_to_main)
    bot = RecordingBot()
    service = _service(llm, search=search, db=db)
    msg = _message(text, message_id=message_id)
    error = None
    started = time.monotonic()
    HTTP_CALLS.clear()
    _log("turn start chat=%s msg=%s" % (CHAT_ID, message_id))
    try:
        await service.handle(bot, msg, _user())
    except Exception as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
    elapsed = round(time.monotonic() - started, 1)
    _log("turn finished in %.1fs (error=%s)" % (elapsed, error))
    drained = await _drain_tasks()
    _log("background tasks drained: %s" % drained)
    snap, events = await _trace_snapshot(db, observer.cid)
    _log("trace events: %d" % len(events))
    record = _record(observer, snap, events, bot, error, elapsed, drained)
    record["http_calls"] = list(HTTP_CALLS)
    observer.uninstall()
    await _close_llm(llm)
    await db.close()
    return record


async def run_initiative(*, text: str, search=None, message_id: int = 300):
    """Реальный инициативный путь: handle_initiative (L1 + L2 + style + send)."""
    from services import mca_intents
    from services.direct_chat_service import handle_initiative

    observer = Observer()
    observer.install()
    db = await _fresh_db()
    llm = _real_llm()
    bot = RecordingBot()
    service = _service(llm, search=search, db=db)
    situation = mca_intents.InitiativeSituation(
        trigger_kind="intent_due", chat_id=CHAT_ID, topic_open=True,
        relations_ok=True, requested_source="live_proof")
    opportunity = {
        "goal": text, "kind": "live_proof", "origin": "live_proof",
        "created_at": int(time.time()),
    }
    # Без кандидата координатор честно уходит в `initiative_silent`
    # (no_eligible_alternative). Кандидат — тот же тип, что отдаёт
    # Observer/память (TriggerCandidate), приоритет положительный.
    candidate = mca_intents.InitiativeCandidate(
        trigger_kind="intent_due", chat_id=CHAT_ID, kind="share",
        source="live_proof", goal=text, priority=50,
        reason_code="default")
    error = None
    status = None
    started = time.monotonic()
    _log("initiative start chat=%s" % CHAT_ID)
    try:
        result = await handle_initiative(
            bot=bot, chat_id=CHAT_ID, situation=situation,
            candidates=(candidate,), db=db, writer_service=service,
            opportunity_row=opportunity)
        status = {k: v for k, v in (result or {}).items()
                  if k in ("status", "delivery_kind", "reason_code")}
        decision = (result or {}).get("decision")
        if decision is not None:
            status["reason_codes"] = list(
                getattr(decision, "reason_codes", ()) or ())
            status["action"] = getattr(decision, "action", None)
            status["selected_candidate"] = getattr(
                decision, "selected_candidate", None)
    except Exception as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
    elapsed = round(time.monotonic() - started, 1)
    drained = await _drain_tasks()
    snap, events = await _trace_snapshot(db, observer.cid)
    record = _record(observer, snap, events, bot, error, elapsed, drained)
    record["initiative_status"] = status
    observer.uninstall()
    await _close_llm(llm)
    await db.close()
    return record


async def run_factcheck(*, claim: str):
    """Структурированный фактчек-путь (свой пайплайн, не Direct L2)."""
    from services.factcheck_service import FactCheckService
    from services.search_aggregator import SearchAggregator

    db = await _fresh_db()
    llm = _real_llm()
    aggregator = SearchAggregator()
    service = FactCheckService(aggregator, llm, memory=None)
    calls = {"n": 0}
    orig_generate = llm.generate
    orig_meta = llm.generate_with_metadata

    async def gen(*a, **k):
        calls["n"] += 1
        return await orig_generate(*a, **k)

    async def gen_meta(*a, **k):
        calls["n"] += 1
        return await orig_meta(*a, **k)

    llm.generate = gen
    llm.generate_with_metadata = gen_meta
    error = None
    result = None
    started = time.monotonic()
    try:
        result = await service.check_claim(claim, chat_id=CHAT_ID)
    except Exception as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
    elapsed = round(time.monotonic() - started, 1)
    events = []
    try:
        from services import mca_events
        await mca_events.flush_events(db)
        rows = await mca_events.query_events(db, chat_id=CHAT_ID, limit=60)
        for row in rows:
            events.append({"event": row.get("event_name"),
                           "stage": row.get("stage"),
                           "outcome": row.get("outcome"),
                           "reason_code": row.get("reason_code")})
    except Exception as exc:
        events = [{"error": type(exc).__name__}]
    await _close_llm(llm)
    await db.close()
    return {
        "scenario": "factcheck",
        "error": error,
        "elapsed_s": elapsed,
        "llm_calls_total": calls["n"],
        "result_chars": len(str(result or "")),
        "result_digest": _digest(result),
        "result_excerpt": _excerpt(result, 400),
        "result_tail": _tail(result),
        "events": events,
    }


def _record(observer, snap, events, bot, error, elapsed, drained) -> dict:
    comp = (observer.completions[-1] if observer.completions else {})
    raw_text = comp.get("raw_text", "")
    final_text = comp.get("final_text", "")
    completion = comp.get("completion")
    continuation = comp.get("continuation")
    refused = observer.refusals[-1] if observer.refusals else None
    if not raw_text and refused:
        # Отказ L2 (незаконченный ответ/пустой финал): сырой текст пришёл в
        # `note_l2_refusal`, а не в `note_l2_completion`.
        raw_text = refused.get("text") or ""
    sent = bot.messages[-1] if bot.messages else None
    sent_text = sent["text"] if sent else ""
    raw_digest = _digest(raw_text)
    sent_digest = _digest(sent_text)
    plan = observer.l1_plan
    l1_fields = {}
    for field in ("action", "response_act", "execution_mode",
                  "preserve_source_facts", "search_intent",
                  "knowledge_origin", "extent", "task_kind", "structure"):
        if plan is not None and hasattr(plan, field):
            value = getattr(plan, field)
            l1_fields[field] = value if isinstance(
                value, (bool, int, float, str)) else str(value)
    return {
        "error": error,
        "elapsed_s": elapsed,
        "correlation_id": observer.cid,
        "background_tasks_drained": drained,
        "l1_plan_fields": l1_fields,
        "llm_calls_by_class": _merged_calls(snap, observer),
        "llm_calls_observed_events": _calls_from(observer),
        "final_calls_from_writer": len(observer.completions),
        "refused": ({
            "reason": refused.get("reason"),
            "stop_reason": refused.get("stop_reason"),
            "finish_reason": refused.get("finish_reason"),
            "continuation_calls": refused.get("continuation_calls"),
            "chars": len(raw_text),
        } if refused else None),
        "semantic_rewrite_count": snap.get("semantic_rewrite_count"),
        "finish_reason": (snap.get("completion") or {}).get("finish_reason"),
        "completion": _strip_completion(snap.get("completion") or {}),
        "continuation_calls": getattr(continuation, "continuation_calls", None),
        "continuation_completed": getattr(continuation, "completed", None),
        "continuation_stop_reason": getattr(continuation, "stop_reason", None),
        "raw_final": {
            "chars": len(raw_text),
            "digest_runner": raw_digest,
            "digest_trace": snap.get("raw_final_digest"),
            "digest_agrees": (raw_digest == (snap.get("raw_final_digest") or "")
                              if raw_text else None),
            "excerpt": _excerpt(raw_text, 300),
            "tail": _tail(raw_text),
            "ends_with_sentence_punct": str(raw_text).rstrip()[-1:] in
            (".", "!", "?", "…", "»", '"', ")") if raw_text else None,
        },
        "final_after_l2_sanitize": {
            "chars": len(final_text),
            "digest_runner": _digest(final_text),
            "same_as_raw": (final_text == raw_text) if raw_text else None,
        },
        "delivered": {
            "messages": len(bot.messages),
            "chars": len(sent_text),
            "digest_runner": sent_digest,
            "digest_trace": snap.get("delivered_digest"),
            "digest_match_trace": snap.get("digest_match"),
            "written_equals_sent": (sent_text == raw_text) if raw_text else None,
            "ops_between": _ops_between(raw_text, sent_text, observer),
            "text_diff": _text_diff(raw_text, sent_text),
            "excerpt": _excerpt(sent_text, 300),
            "tail": _tail(sent_text),
        },
        "divergence_reason": snap.get("divergence_reason"),
        "ops": [{"op": op["op"], "changed": _op_changed(op, snap),
                 "chars": op.get("chars"), "digest": op.get("digest")}
                for op in (snap.get("ops") or [])],
        "delivery_outcome": (snap.get("delivery") or {}).get("outcome"),
        "stop_reason": snap.get("stop_reason"),
        "tools": snap.get("tools"),
        "tool_rounds": snap.get("tool_rounds"),
        "events": [{"event": e.get("event"), "stage": e.get("stage"),
                    "outcome": e.get("outcome")} for e in events],
        "event_payloads": events,
    }


def _strip_completion(completion: dict) -> dict:
    keep = ("finish_reason", "finish_reason_raw", "completed", "is_truncated",
            "attempt", "fallback_used", "provider", "model", "usage",
            "max_output_tokens_sent", "chars", "continuation_calls",
            "continuation_stop_reason", "text_source", "checks", "refused",
            "refused_reason", "metadata_available")
    return {k: completion.get(k) for k in keep if k in completion}


def _calls_from(observer) -> dict:
    out: dict = {}
    for item in observer.llm_calls:
        out[item["kind"]] = out.get(item["kind"], 0) + item["count"]
    return out


def _merged_calls(snap: dict, observer) -> dict:
    """Вызовы по классам: трасса + наблюдатель (без двойного счёта).

    Трасса знает только ходы с `turn_trace.begin` (Direct). Инициатива
    трассы не начинает, поэтому финальный вызов считается по фактическому
    завершению Writer'а (`note_l2_completion`), а не по `note_llm_call`.
    """
    out = dict(snap.get("llm_calls") or {})
    observed = _calls_from(observer)
    for kind, count in observed.items():
        out[kind] = max(int(out.get(kind) or 0), int(count))
    finals = len(observer.completions)
    if finals and not out.get("final"):
        out["final"] = finals
    return out


def _op_changed(op: dict, snap: dict) -> bool | None:
    for item in (snap.get("ops") or []):
        if item.get("op") == op.get("op") and item.get("digest") == op.get("digest"):
            return bool(item.get("changed"))
    return None


def _ops_between(raw_text: str, sent_text: str, observer) -> list[str]:
    """Какие операции реально стоят между авторским текстом и отправкой."""
    names = [op["op"] for op in observer.ops if op.get("text") != raw_text]
    if raw_text and sent_text and raw_text == sent_text:
        return names
    return names


def _text_diff(raw_text: str, sent_text: str, limit: int = 6) -> dict:
    """Символьное сравнение «написано» ↔ «к отправке» (не только хеши).

    Возвращает длину общего префикса/суффикса и ограниченный список отличий
    (позиция + короткие фрагменты), чтобы разрешённые операции были видны
    человеческим глазом, а не выводились из digest'а.
    """
    a, b = str(raw_text or ""), str(sent_text or "")
    if not a and not b:
        return {"equal": True, "diffs": []}
    if a == b:
        return {"equal": True, "diffs": [], "punct_only": True,
                "other_char_delta": 0}
    prefix = 0
    for x, y in zip(a, b):
        if x != y:
            break
        prefix += 1
    suffix = 0
    max_suffix = min(len(a), len(b)) - prefix
    while suffix < max_suffix:
        if a[len(a) - 1 - suffix] != b[len(b) - 1 - suffix]:
            break
        suffix += 1
    mid_a = a[prefix:len(a) - suffix]
    mid_b = b[prefix:len(b) - suffix]
    return {
        "equal": False,
        "prefix": prefix,
        "suffix": suffix,
        "removed": mid_a[:200],
        "added": mid_b[:200],
        "removed_chars": len(mid_a),
        "added_chars": len(mid_b),
        "punct_only": _punct_only(a, b),
        "other_char_delta": _non_punct_delta(a, b),
    }


#: Разрешённая пунктуационная нормализация владельца (`owner_style_punctuation`):
#: длинное тире → дефис, типографские кавычки «» → прямые. Смысл строки не
#: меняется. Короткое тире (en dash) внутри числовых диапазонов НЕ трогаем:
#: проверка должна описывать РОВНО наблюдённую операцию, а не шире неё.
_PUNCT_MAP = {"\u2014": "-", "\u00ab": '"', "\u00bb": '"'}


def _normalize_punct(text: str) -> str:
    for src, dst in _PUNCT_MAP.items():
        text = text.replace(src, dst)
    return text


def _punct_only(raw: str, sent: str) -> bool:
    return _normalize_punct(raw) == sent


def _non_punct_delta(raw: str, sent: str) -> int:
    """Сколько позиций остаётся различными ПОСЛЕ пунктуационной нормализации."""
    a, b = _normalize_punct(raw), sent
    if a == b:
        return 0
    import difflib
    delta = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            delta += max(i2 - i1, j2 - j1)
    return delta


async def _close_llm(llm) -> None:
    try:
        await llm.close()
    except Exception:
        pass


# ── main ────────────────────────────────────────────────────────────────────

SCENARIOS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7")


async def _amain(args) -> int:
    from services import mca_events, turn_trace

    if args.watchdog:
        asyncio.create_task(_watchdog(args.watchdog))

    results: dict = {"meta": {}, "scenarios": {}}
    from config.settings import settings
    results["meta"] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "repo": REPO,
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "llm_provider_host": _host(settings.LLM_BASE_URL),
        "llm_model": settings.LLM_MODEL_NAME,
        "fallback_host": _host(settings.LLM_FALLBACK_BASE_URL),
        "fallback_model": settings.LLM_FALLBACK_MODEL,
        "search_keys_configured": bool(
            getattr(settings, "TAVILY_API_KEY", "") or
            getattr(settings, "EXA_API_KEY", "")),
        "telegram_send": "stubbed (RecordingBot) — no network",
        "longform_max_output_tokens_env": os.environ.get(
            "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS", ""),
    }
    wanted = [s.strip() for s in (args.only or ",".join(SCENARIOS)).split(",")]

    def _reset():
        turn_trace.reset()
        try:
            mca_events._pending.clear()
        except Exception:
            pass

    if "s1" in wanted:
        _reset()
        print("[s1] direct without tools …", flush=True)
        results["scenarios"]["s1"] = await run_direct(
            text="Привет! Расскажи в двух-трёх предложениях, чем ты сегодня "
                 "занимался и что тебе запомнилось.",
            message_id=101)

    if "s2" in wanted:
        _reset()
        print("[s2] direct with web search …", flush=True)
        from services.search_aggregator import SearchAggregator
        results["scenarios"]["s2"] = await run_direct(
            text="Глянь в интернете, какой сейчас курс биткоина к доллару, "
                 "и скажи коротко с цифрой.",
            search=SearchAggregator(), message_id=102)

    if "s3" in wanted:
        _reset()
        print("[s3] initiative reply …", flush=True)
        results["scenarios"]["s3"] = await run_initiative(
            text="сам напиши в чат короткую живую реплику: спроси у Васи, "
                 "как прошёл его день")

    if "s4" in wanted:
        _reset()
        print("[s4] provider fallback (invalid primary) …", flush=True)
        results["scenarios"]["s4"] = await run_direct(
            text="Скажи одним предложением, что ты сегодня в порядке.",
            bad_primary=True, message_id=104)
        _reset()
        print("[s4b] provider fallback (working fallback leg) …", flush=True)
        results["scenarios"]["s4b"] = await run_direct(
            text="Скажи одним предложением, что ты сегодня в порядке.",
            bad_primary=True, fallback_to_main=True, message_id=114)

    if "s5" in wanted:
        _reset()
        print("[s5] longform answer hitting finish_reason=length …", flush=True)
        os.environ.pop("DIRECT_LONGFORM_MAX_OUTPUT_TOKENS", None)
        results["scenarios"]["s5"] = await run_direct(
            text="Напиши развёрнутый рассказ примерно на 90 слов о том, как ты "
                 "однажды утром потерял все свои ключи и искал их по всему чату.",
            message_id=105)
        results["scenarios"]["s5"]["forced"] = {
            "DIRECT_LONGFORM_MAX_OUTPUT_TOKENS": args.max_tokens}

    if "s6" in wanted:
        _reset()
        print("[s6] explicit rewrite with protected facts …", flush=True)
        results["scenarios"]["s6"] = await run_direct(
            text="Перепиши мой текст другими словами, сохранив все факты: "
                 "«Вчера в 19:40 я купил билет на поезд № 42 за 3 500 рублей "
                 "до станции Кемь и приехал в 06:15».",
            message_id=106)

    if "s7" in wanted:
        _reset()
        print("[s7] factcheck structured path …", flush=True)
        results["scenarios"]["s7"] = await run_factcheck(
            claim="Курс биткоина сегодня вырос на 12 процентов и достиг "
                  "104 500 долларов.")

    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "r09-live-proof.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print("written:", path, flush=True)
    return 0


async def _watchdog(seconds: float) -> None:
    """Диагностика: через N секунд распечатать стеки корутин и выйти."""
    await asyncio.sleep(seconds)
    for task in asyncio.all_tasks():
        if task is asyncio.current_task():
            continue
        _log("TASK %s" % task.get_name())
        coro = task.get_coro()
        seen = 0
        while coro is not None and seen < 60:
            code = getattr(coro, "cr_code", None) or getattr(
                coro, "gi_code", None)
            frame = getattr(coro, "cr_frame", None) or getattr(
                coro, "gi_frame", None)
            if code is not None:
                _log("   at %s:%s in %s" % (
                    os.path.basename(code.co_filename),
                    getattr(frame, "f_lineno", "?"), code.co_name))
            coro = getattr(coro, "cr_await", None) or getattr(
                coro, "gi_yieldfrom", None)
            seen += 1
    os._exit(2)


def _git(*args) -> str:
    import subprocess
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception:
        return ""


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        return urlsplit(str(url or "")).hostname or ""
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default=None)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--longform-max-tokens", type=int, default=0)
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--dump-after", type=float, default=0.0)
    parser.add_argument("--watchdog", type=float, default=0.0)
    args = parser.parse_args()
    if args.longform_max_tokens:
        os.environ["DIRECT_LONGFORM_MAX_OUTPUT_TOKENS"] = str(
            args.longform_max_tokens)
    if args.dump_after:
        import faulthandler
        faulthandler.dump_traceback_later(args.dump_after, repeat=True,
                                          file=sys.stderr)
    _bootstrap(args.env_file, args.out, args.log_file)
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
