"""RLR-06-OBSERVABILITY — трасса ОДНОГО хода по `correlation_id` (§7).

REMOVE-LEGACY-REPHRASING v2.0 (owner corrective 2026-11-05, источник
`plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md`):

* §7 — «для каждого логического хода по `correlation_id` собрать доступные в
  существующем tracing/oversight»: trigger/источник, L1 action/plan, вызовы
  инструментов с источниками/ошибками/coverage, манифест запроса L2 (блоки +
  ревизии owner-промптов, provider/model/fallback) БЕЗ полного приватного
  payload, завершение L2 (`finish_reason`, завершённость, usage, устойчивый
  digest raw final), упорядоченные доставочные операции с digest после каждой,
  `semantic_rewrite_count=0` для обычного ответа, классификация LLM-вызовов
  (planning/tool/final/continuation/provider_retry), исход доставки,
  идемпотентный ключ и фактические Telegram ID, а при расхождении
  raw_final ↔ delivered — ТОЧНАЯ разрешённая причина;
* §7 «Критично» — скрытый retry/`return draft` после неудачной проверки не
  выглядит обычным успехом (см. ``note_l2_refusal``/``text_source``);
* §7 приватность — «для защиты приватности логов достаточно digest/метаданных
  и доступа к существующему Inspector, без новой БД сырых переписок».

Границы (REUSE, вторая система запрещена):
  * точка эмиссии — существующий `services.mca_events.emit_mca_event`
    (durable `mca_events` + структурный лог, `trace_id` = `correlation_id`);
  * читается существующим Inspector'ом: `mca_events.query_events(trace_id=…)`
    и `GET /api/status/logs?trace_id=…` — `web/**` не меняется;
  * `mca_bot_outputs` (журнал доставленных ответов) не очищается и не
    отключается: трасса его не заменяет и не дублирует;
  * никакого нового хранилища и никаких сырых текстов: только digest'ы,
    длины, счётчики, enum-коды и id.

Тексты чата в БД/лог НЕ попадают: `text_digest` — blake2s (16 hex), поэтому
сравнить raw_final с доставленным можно, а прочитать приватный текст — нет.
Для расследования конкретного ответа по-прежнему используется существующий
журнал `mca_bot_outputs` (доступ по правам).

Fail-open: любая ошибка трассировки не рвёт ход (никогда не бросает).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)

# ── события трассы (свободная ось `event_name` mca-13; один trace_id) ───────
EVENT_CONTEXT = "direct_turn_context"      # trigger/chat/clock/L1/tools
EVENT_WRITER = "direct_turn_writer"        # манифест запроса + завершение L2
EVENT_DELIVERY = "direct_turn_delivery"    # операции доставки + digest + итог

#: Логическая семья хода (§7 «trigger `direct|initiative|factcheck|...`»):
#: конкретное значение матрицы триггеров едет отдельно (`trigger`), а семья —
#: здесь, чтобы фильтр по трассе не зависел от значений матрицы.
FLOW_DIRECT = "direct"

#: Классификация LLM-вызовов хода (§7: «не всё под stage2»).
CALL_PLANNING = "planning"
CALL_TOOL = "tool"
CALL_FINAL = "final"
CALL_CONTINUATION = "continuation"
CALL_PROVIDER_RETRY = "provider_retry"
CALL_KINDS = (CALL_PLANNING, CALL_TOOL, CALL_FINAL, CALL_CONTINUATION,
              CALL_PROVIDER_RETRY)

# ── имена доставочных операций (§1 «разрешённое техническое преобразование») ──
OP_L2_SCRUB = "l2_scrubber"
OP_REASONING_STRIP = "reasoning_marker_strip"
OP_MACHINE_STRIP = "machine_marker_strip"
OP_LORE_OVERRIDE = "lore_story_override"
OP_EGRESS_GUARD = "evidence_egress_guard"
OP_STYLE = "owner_style_punctuation"
OP_RICH = "rich_render"
OP_HTML = "html_escape"
OP_PLAIN = "plain_render"
OP_EGRESS_SANITIZE = "egress_sanitize"
OP_CHUNK = "telegram_chunk"
OP_NAMES = frozenset({
    OP_L2_SCRUB, OP_REASONING_STRIP, OP_MACHINE_STRIP, OP_LORE_OVERRIDE,
    OP_EGRESS_GUARD, OP_STYLE, OP_RICH, OP_HTML, OP_PLAIN, OP_EGRESS_SANITIZE,
    OP_CHUNK,
})

#: digest изменился, но ни одна разрешённая операция этого не объясняет —
#: честный красный флаг, а не «всё хорошо».
UNEXPLAINED = "unexplained_text_change"

DIGEST_CHARS = 16
_MAX_TURNS = 64
#: `usage_json` в `mca_events` обрезается на 2000 символов — держим payload
#: заведомо короче, чтобы JSON оставался разбираемым.
_PAYLOAD_LIMIT = 1800

_lock = threading.Lock()
_turns: "OrderedDict[str, TurnTrace]" = OrderedDict()


# ════════════════════════════════════════════════════════════════════════════
# digest / идемпотентный ключ
# ════════════════════════════════════════════════════════════════════════════

def text_digest(text) -> str:
    """Устойчивый digest текста (16 hex). Пустой текст → ''.

    Один и тот же текст всегда даёт один digest (в т.ч. между процессами и
    после рестарта) — значит raw_final и delivered сравнимы без хранения
    самого текста. Пустая строка — отсутствие текста, а не «пустой ответ»."""
    source = str(text if text is not None else "")
    if not source:
        return ""
    return hashlib.blake2s(source.encode("utf-8"), digest_size=8).hexdigest()


def provider_of(base_url) -> str:
    """Провайдер по адресу API (host) — R17-safe, без ключей/путей."""
    try:
        from urllib.parse import urlsplit
        host = urlsplit(str(base_url or "")).hostname or ""
        return host[:48]
    except Exception:      # pragma: no cover
        return ""


def idempotency_key(*, chat_id, tg_message_id, revision: int = 1,
                    user_id=None) -> str:
    """Ключ идентичности СОБЫТИЯ (не текста): `(chat, msg, revision, user)`.

    Тот же ключ, по которому работает `response_freshness.check_update_seen`
    (`services/response_freshness.py`); одинаковый текст двух РАЗНЫХ событий
    ключ не совпадает — §1 «не считать сохранением идемпотентности»."""
    parts = ["direct", str(int(chat_id or 0)), str(tg_message_id if
                                                  tg_message_id is not None
                                                  else "-"),
             "r%d" % int(revision or 1),
             "u%s" % (user_id if user_id is not None else "-")]
    return ":".join(parts)


# ════════════════════════════════════════════════════════════════════════════
# аккумулятор одного хода
# ════════════════════════════════════════════════════════════════════════════

class TurnTrace:
    """Накопитель трассы хода: только метаданные/digest'ы (R17).

    Живёт в памяти процесса (bounded LRU по `correlation_id`), а на стадиях
    отдаёт наружу события `mca_events` — durable-след остаётся, приватного
    текста в нём нет.
    """

    __slots__ = (
        "correlation_id", "chat_id", "trigger", "flow", "source_message_id",
        "source_author_id", "idempotency_key", "clock", "clock_source",
        "clock_ts", "l1", "tools", "tool_rounds", "tool_degraded",
        "tool_reason", "coverage", "llm_calls", "manifest", "request",
        "completion", "semantic_rewrite_count", "raw_final_digest",
        "delivered_digest", "divergence_reason", "digest_match", "ops",
        "delivery", "author_state", "stop_reason", "stop_outcome",
        "_last_digest", "_last_chars", "_context_emitted", "_writer_emitted",
        "_delivery_emitted", "started_ts",
    )

    def __init__(self, correlation_id: str, *, chat_id=None, trigger: str = "",
                 flow: str = FLOW_DIRECT, source_message_id=None,
                 source_author_id=None, idempotency_key: str = ""):
        self.correlation_id = str(correlation_id)
        self.chat_id = int(chat_id) if chat_id is not None else None
        self.trigger = str(trigger or "")
        self.flow = str(flow or FLOW_DIRECT)
        self.source_message_id = source_message_id
        self.source_author_id = source_author_id
        self.idempotency_key = str(idempotency_key or "")
        self.clock = ""
        self.clock_source = ""
        self.clock_ts = None
        self.l1: dict = {}
        self.tools: list = []
        self.tool_rounds = 0
        self.tool_degraded = False
        self.tool_reason = ""
        self.coverage: dict = {}
        self.llm_calls: dict = {}
        self.manifest: dict = {}
        self.request: dict = {}
        self.completion: dict = {}
        self.semantic_rewrite_count = 0
        self.raw_final_digest = ""
        self.delivered_digest = ""
        self.divergence_reason = ""
        self.digest_match = None
        self.ops: list = []
        self.delivery: dict = {}
        self.author_state: dict = {}
        self.stop_reason = ""
        self.stop_outcome = ""
        self._last_digest = ""
        self._last_chars = 0
        self._context_emitted = False
        self._writer_emitted = False
        self._delivery_emitted = False
        self.started_ts = int(time.time())

    # ── внутренние помощники ────────────────────────────────────────────────
    def _append_op(self, name: str, text) -> None:
        digest = text_digest(text)
        baseline = self._last_digest
        chars = len(str(text if text is not None else ""))
        self.ops.append({
            "op": str(name),
            "digest": digest,
            "chars": chars,
            # «changed» — относительно предыдущего звена цепочки; без базовой
            # точки (нет авторского текста) утверждать изменение нельзя.
            "changed": bool(baseline and digest != baseline),
        })
        self._last_digest = digest
        self._last_chars = chars

    def _append_chain_op(self, name: str, *, chunks: int | None = None) -> None:
        """Операция над ТЕМ ЖЕ текстом (нарезка/отправка): digest не меняется."""
        self.ops.append({
            "op": str(name),
            "digest": self._last_digest,
            "chars": self._last_chars,
            "changed": False,
        })
        if chunks is not None:
            self.ops[-1]["chunks"] = int(chunks)

    def _divergence(self) -> None:
        """Причина расхождения raw_final ↔ delivered (§7)."""
        if not self.raw_final_digest:
            self.digest_match = None
            self.divergence_reason = ""
            return
        self.digest_match = bool(self.delivered_digest
                                 and self.delivered_digest
                                 == self.raw_final_digest)
        if self.digest_match:
            self.divergence_reason = ""
            return
        changed = [op["op"] for op in self.ops if op.get("changed")]
        self.divergence_reason = ",".join(changed) or UNEXPLAINED

    # ── payload'ы событий ───────────────────────────────────────────────────
    def context_payload(self) -> dict:
        payload = {
            "flow": self.flow,
            "trigger": self.trigger,
            "source_message_id": self.source_message_id,
            "source_author_id": self.source_author_id,
            "chat_id": self.chat_id,
            "clock": self.clock,
            "clock_source": self.clock_source,
            "clock_ts": self.clock_ts,
            "l1": dict(self.l1),
            "tool_rounds": self.tool_rounds,
            "tool_degraded": self.tool_degraded,
            "tool_reason": self.tool_reason,
            "tools": list(self.tools),
            "coverage": dict(self.coverage),
            "llm_calls": dict(self.llm_calls),
            "idempotency_key": self.idempotency_key,
        }
        if self.stop_reason:
            payload["stop_reason"] = self.stop_reason
        return payload

    def writer_payload(self) -> dict:
        return {
            "manifest": dict(self.manifest),
            "request": dict(self.request),
            "completion": dict(self.completion),
            "semantic_rewrite_count": int(self.semantic_rewrite_count),
            "llm_calls": dict(self.llm_calls),
        }

    def delivery_payload(self) -> dict:
        return {
            "ops": [dict(op) for op in self.ops],
            "raw_final_digest": self.raw_final_digest,
            "delivered_digest": self.delivered_digest,
            "digest_match": self.digest_match,
            "divergence_reason": self.divergence_reason,
            "semantic_rewrite_count": int(self.semantic_rewrite_count),
            "llm_calls": dict(self.llm_calls),
            "delivery": dict(self.delivery),
            "idempotency_key": self.idempotency_key,
        }


# ════════════════════════════════════════════════════════════════════════════
# эмиссия (fail-open; одна точка — существующий mca_events)
# ════════════════════════════════════════════════════════════════════════════

def _pack(payload: dict) -> dict:
    """Уложить payload в лимит `usage_json` без потери смысла полей.

    Крупные списки усекаются ДЕТЕРМИНИРОВАННО и это видно (`truncated`), а не
    молча: обрезанный JSON в `mca_events` был бы нечитаем."""
    data = dict(payload)
    try:
        if len(json.dumps(data, ensure_ascii=False)) <= _PAYLOAD_LIMIT:
            return data
        for key in ("tools", "ops", "blocks", "revisions", "fallback_chain"):
            value = data.get(key)
            if isinstance(value, list) and value:
                data[key] = value[:6]
        if len(json.dumps(data, ensure_ascii=False)) > _PAYLOAD_LIMIT:
            for key in ("tools", "ops"):
                value = data.get(key)
                if isinstance(value, list):
                    data[key] = value[:2]
        if len(json.dumps(data, ensure_ascii=False)) > _PAYLOAD_LIMIT:
            for key in ("tools", "ops", "blocks", "revisions"):
                value = data.get(key)
                if isinstance(value, list):
                    data[key] = {"count": len(value)}
        data["truncated"] = True
    except Exception:      # pragma: no cover — упаковка не рвёт эмиссию
        return dict(payload)
    return data


def _emit(trace: TurnTrace, event_name: str, *, stage: str, outcome: str,
          payload: dict):
    """Эмитировать событие трассы через существующий контракт mca-13."""
    try:
        from services import mca_events as _me
        return _me.emit_mca_event(
            event_name, outcome=outcome, component="direct_chat",
            stage=stage, chat_id=trace.chat_id,
            trace_id=trace.correlation_id, usage_json=_pack(payload))
    except Exception:      # pragma: no cover — трасса не рвёт ход
        return None


def emit_context(trace: TurnTrace, *, outcome: str = "success") -> None:
    if trace is None or trace._context_emitted:
        return
    trace._context_emitted = True
    _emit(trace, EVENT_CONTEXT, stage="turn_context", outcome=outcome,
          payload=trace.context_payload())


def emit_writer(trace: TurnTrace, *, outcome: str = "success") -> None:
    if trace is None or trace._writer_emitted:
        return
    trace._writer_emitted = True
    _emit(trace, EVENT_WRITER, stage="l2_writer", outcome=outcome,
          payload=trace.writer_payload())


def emit_delivery(trace: TurnTrace, *, outcome: str = "success") -> None:
    if trace is None or trace._delivery_emitted:
        return
    trace._delivery_emitted = True
    _emit(trace, EVENT_DELIVERY, stage="delivery", outcome=outcome,
          payload=trace.delivery_payload())


# ════════════════════════════════════════════════════════════════════════════
# публичный API (все функции fail-open)
# ════════════════════════════════════════════════════════════════════════════

def begin(correlation_id, *, chat_id=None, trigger: str = "",
          flow: str = FLOW_DIRECT, source_message_id=None,
          source_author_id=None,
          idempotency_key: str = "") -> "TurnTrace | None":
    """Начать трассу хода. Нет `correlation_id` → трассы нет (fail-open)."""
    if not correlation_id:
        return None
    try:
        trace = TurnTrace(
            str(correlation_id), chat_id=chat_id, trigger=trigger, flow=flow,
            source_message_id=source_message_id,
            source_author_id=source_author_id,
            idempotency_key=idempotency_key)
        with _lock:
            _turns[str(correlation_id)] = trace
            while len(_turns) > _MAX_TURNS:
                _turns.popitem(last=False)
        return trace
    except Exception:      # pragma: no cover — трасса не рвёт ход
        return None


def get(correlation_id) -> "TurnTrace | None":
    if not correlation_id:
        return None
    with _lock:
        return _turns.get(str(correlation_id))


def author_state(correlation_id) -> dict:
    """Пер-ходовой счётчик литературных вызовов (измерение, не литерал).

    Передаётся в `negative_constraints.verbalize_validated(author_state=…)`:
    второй литературный вызов в ТОМ ЖЕ ходе делает
    `semantic_rewrite_count > 0`, даже если текст совпал."""
    trace = get(correlation_id)
    if trace is None:
        return {}
    return trace.author_state


def note_llm_call(correlation_id, kind: str, count: int = 1) -> None:
    """Учесть LLM-вызов хода по классу (planning/tool/final/…)."""
    trace = get(correlation_id)
    if trace is None or kind not in CALL_KINDS:
        return
    try:
        trace.llm_calls[str(kind)] = (int(trace.llm_calls.get(str(kind)) or 0)
                                      + max(0, int(count)))
    except Exception:      # pragma: no cover
        pass


def note_clock(correlation_id, *, line: str = "", source: str = "") -> None:
    """ChatClock хода: значение + источник часов (§7)."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        trace.clock = str(line or "")[:120]
        trace.clock_source = str(source or "")[:64]
        trace.clock_ts = int(time.time())
    except Exception:      # pragma: no cover
        pass


def note_l1(correlation_id, *, action: str = "", response_act: str = "",
            structure: str = "", plan_source: str = "", execution_mode: str = "",
            override: str = "", model: str = "", fallback: str = "") -> None:
    """L1 action/plan этого хода (план — не авторская речь, §7)."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        trace.l1 = {
            "action": str(action or ""),
            "response_act": str(response_act or ""),
            "structure": str(structure or ""),
            "plan_source": str(plan_source or ""),
            "execution_mode": str(execution_mode or ""),
            "override": str(override or ""),
            "model": str(model or "")[:64],
            "fallback": str(fallback or "")[:64],
        }
    except Exception:      # pragma: no cover
        pass


def _tool_entry(entry: dict) -> dict:
    """R17-safe срез вызова инструмента: имя/статус/ошибка/размер/источники."""
    refs = entry.get("evidence_refs") or entry.get("source_refs") or ()
    try:
        ref_count = len(refs)
    except Exception:
        ref_count = 0
    return {
        "tool": str(entry.get("tool") or "")[:40],
        "round": entry.get("round"),
        "status": str(entry.get("status") or "")[:32],
        "error": str(entry.get("error_code")
                     or entry.get("error_type") or "")[:40],
        "out_chars": int(entry.get("out_chars") or 0),
        "truncated": bool(entry.get("truncated")),
        "attempt": entry.get("attempt"),
        "refs": ref_count,
    }


def note_tools(correlation_id, *, tool_results=None, rounds: int = 0,
               degraded: bool = False, reason: str = "",
               pack=None, decision=None) -> None:
    """Вызовы инструментов + coverage доставленного evidence (§7).

    Источники/ошибки берутся из существующего envelope-журнала
    `ToolLoopResult.tool_results` (MCA-11), coverage — из пакета Writer'а.
    Текстов/URL нет: только имена, статусы, коды, размеры, число ссылок."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        trace.tool_rounds = int(rounds or 0)
        trace.tool_degraded = bool(degraded)
        trace.tool_reason = str(reason or "")[:40]
        entries = []
        for item in list(tool_results or [])[:12]:
            if isinstance(item, dict):
                entries.append(_tool_entry(item))
        trace.tools = entries
        if trace.tool_rounds:
            note_llm_call(correlation_id, CALL_TOOL, trace.tool_rounds)
        coverage: dict = {}
        sources = list(getattr(pack, "sources", None) or ())
        if sources:
            coverage["sources"] = len(sources)
            coverage["delivered"] = sum(
                1 for s in sources if getattr(s, "delivered_chars", 0))
            coverage["capacity_chars"] = int(
                getattr(pack, "capacity_chars", 0) or 0)
            coverage["delivered_chars"] = len(str(
                getattr(pack, "text", "") or ""))
            coverage["limits"] = len(
                getattr(pack, "limitations", None) or ())
        if decision is not None:
            coverage["required_claims"] = len(
                getattr(decision, "claims", None) or ())
            coverage["evidence_class"] = str(
                getattr(decision, "evidence_class", "") or "")
            coverage["required"] = bool(getattr(decision, "required", False))
        trace.coverage = coverage
    except Exception:      # pragma: no cover — трасса не рвёт ход
        pass


def _block_labels(parts) -> list:
    """Ярлыки контекстных блоков user-части БЕЗ их содержимого (§7).

    На пути без композера манифеста нет, но состав блоков известен: берём
    ведущий машинный тег (`<Current_Question>`, `<Tool_Evidence>`, …).
    Текст блока в трассу не попадает — только имя блока."""
    out: list = []
    for part in list(parts or ())[:16]:
        text = str(part or "").strip()
        if not text:
            continue
        tag = ""
        if text.startswith("<"):
            end = text.find(">")
            if 0 < end <= 48:
                tag = text[1:end].strip()
        out.append({"block": (tag or "untagged")[:48], "rendered": True,
                    "skip": ""})
    return out


def prompt_revisions(keys) -> dict:
    """Заводские ревизии запрошенных owner-промптов (без I/O, §7).

    Читается существующий реестр промптов (PVR: единый контроль версий) —
    второй реестр не создаётся. Ключ резолвится в блок (`block_for`), затем
    берётся заводская ревизия блока; нет блока → пусто (честно, без выдумки)."""
    revisions: dict = {}
    try:
        from services import prompt_registry as _pr
        for key in list(keys or ())[:8]:
            block_id = ""
            try:
                spec = _pr.block_for(str(key))
                block_id = str(getattr(spec, "block_id", "") or "")
            except Exception:      # pragma: no cover — один ключ не рвёт всё
                block_id = ""
            revision = ""
            for candidate in (block_id, str(key)):
                if not candidate:
                    continue
                try:
                    revision = _pr.factory_revision(candidate)
                except Exception:      # pragma: no cover
                    revision = ""
                if revision:
                    break
            if revision:
                revisions[str(key)[:48]] = str(revision)[:32]
    except Exception:      # pragma: no cover — реестр недоступен
        return {}
    return revisions


def note_l2_request(correlation_id, *, manifest=None, provider: str = "",
                    model: str = "", fallback_model: str = "",
                    max_output_tokens=None, composer: bool = False,
                    blocks=None, prompt_keys=None,
                    writer_name: str = "") -> None:
    """Манифест ЗАПРОСА L2: блоки + ревизии owner-промптов, provider/model.

    Полный приватный payload не сохраняется (§7): блоки описываются
    `layer:block_id` с признаком `rendered`/`skip_reason`, ревизии — их id.
    Используется существующий `PromptManifest` композера (второй манифест
    запрещён)."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        built_blocks: list = []
        revisions: dict = {}
        manifest_id = ""
        writer = str(writer_name or "")[:24]
        profile = ""
        representation = ""
        tokens_total = 0
        if manifest is not None:
            manifest_id = str(getattr(manifest, "manifest_id", "") or "")[:40]
            writer = str(getattr(manifest, "writer", "") or writer)[:24]
            profile = str(getattr(manifest, "profile", "") or "")[:24]
            representation = str(
                getattr(manifest, "context_representation", "") or "")[:16]
            tokens_total = int(getattr(manifest, "tokens_total", 0) or 0)
            for layer in tuple(getattr(manifest, "layers", ()) or ())[:16]:
                built_blocks.append({
                    "block": ("%s:%s" % (
                        str(getattr(layer, "layer", "") or "")[:24],
                        str(getattr(layer, "block_id", "") or "")[:32])),
                    "rendered": bool(getattr(layer, "rendered", False)),
                    "skip": str(getattr(layer, "skip_reason", "") or "")[:32],
                })
            versions = dict(getattr(manifest, "versions", {}) or {})
            for key, value in list(versions.items())[:8]:
                revisions[str(key)[:48]] = str(value)[:32]
        else:
            # Путь без композера: состав блоков и заводские ревизии owner-
            # промптов всё равно обязаны быть видны (§7).
            built_blocks = _block_labels(blocks)
            revisions = prompt_revisions(prompt_keys)
        trace.manifest = {
            "manifest_id": manifest_id,
            "writer": writer,
            "profile": profile,
            "composer": bool(composer),
            "context_representation": representation,
            "tokens_total": tokens_total,
            "blocks": built_blocks,
            "revisions": revisions,
        }
        trace.request = {
            "provider": str(provider or "")[:48],
            "model": str(model or "")[:64],
            "fallback_model": str(fallback_model or "")[:64],
            "max_output_tokens": (int(max_output_tokens)
                                  if max_output_tokens else None),
        }
    except Exception:      # pragma: no cover — трасса не рвёт ход
        pass


def note_l2_completion(correlation_id, *, raw_text: str = "",
                       final_text: str = "", completion=None,
                       stats: dict | None = None,
                       continuation=None) -> None:
    """Завершение L2: `finish_reason`, завершённость, usage, digest raw final.

    Заодно фиксирует цепочку ПЕРВЫХ доставочных операций: `l2_scrubber`
    (техническая санитизация внутри валидатора) с точным именем причины —
    `reasoning_marker_strip` / `machine_marker_strip` (§7 требует именно
    названия операций, а не «какая-то чистка»)."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        stats = stats or {}
        trace.raw_final_digest = text_digest(raw_text)
        trace._last_digest = trace.raw_final_digest
        # Точная атрибуция первой стадии (sanitize_outgoing = strip reasoning
        # tags → id/target-маркеры): имя операции должно называть ФАКТ.
        try:
            from services.reply_postprocess import strip_reasoning_tags
            intermediate = strip_reasoning_tags(raw_text)
        except Exception:      # pragma: no cover
            intermediate = raw_text
        if intermediate != raw_text:
            trace._append_op(OP_REASONING_STRIP, intermediate)
        if final_text != intermediate:
            trace._append_op(OP_MACHINE_STRIP, final_text)
        finish_reason = str(getattr(completion, "finish_reason", "") or "")
        attempt = int(getattr(completion, "attempt", 1) or 1)
        fallback_chain = tuple(getattr(completion, "fallback_chain", ()) or ())
        usage = getattr(completion, "usage", None)
        usage_dict = dict(usage) if isinstance(usage, dict) else {}
        trace.completion = {
            "finish_reason": finish_reason or "unknown",
            "finish_reason_raw": getattr(completion, "finish_reason_raw", None),
            "metadata_available": completion is not None,
            "completed": bool(getattr(continuation, "completed", True)),
            "is_truncated": bool(getattr(completion, "is_truncated", False)),
            "attempt": attempt,
            "fallback_used": bool(getattr(completion, "fallback_used", False)),
            "provider": str(getattr(completion, "provider", "") or "")[:48],
            "model": str(getattr(completion, "model", "") or "")[:64],
            "usage": {k: usage_dict[k] for k in
                      ("prompt_tokens", "completion_tokens", "total_tokens")
                      if k in usage_dict},
            "max_output_tokens_sent": getattr(
                completion, "max_output_tokens_sent", None),
            "chars": len(str(raw_text or "")),
            "raw_final_digest": trace.raw_final_digest,
            "continuation_calls": int(
                getattr(continuation, "continuation_calls", 0) or 0),
            "continuation_stop_reason": str(
                getattr(continuation, "stop_reason", "") or "")[:32],
            "text_source": ("source_restored" if stats.get("form_fallback")
                            else "author"),
        }
        trace.semantic_rewrite_count = int(
            stats.get("semantic_rewrite_count") or 0)
        checks = {
            "form_guard": stats.get("form_guard_reason"),
            "protected_facts_mismatch": bool(
                stats.get("protected_facts_mismatch")),
            "needs_clarification": bool(stats.get("needs_clarification")),
            "numeric_mismatch": int(stats.get("numeric_claim_mismatch") or 0),
            "cliche_observed": len(stats.get("cliche_observed") or ()),
            "format_observed": len(stats.get("format_observed") or ()),
        }
        if any(checks[k] for k in ("form_guard", "protected_facts_mismatch",
                                   "needs_clarification", "numeric_mismatch")):
            # Находка проверки видна: ответ не «прошёл проверку молча».
            trace.completion["checks"] = checks
        note_llm_call(correlation_id, CALL_FINAL)
        if trace.completion["continuation_calls"]:
            note_llm_call(correlation_id, CALL_CONTINUATION,
                          trace.completion["continuation_calls"])
        retries = max(0, attempt - 1) + len(fallback_chain)
        if retries:
            note_llm_call(correlation_id, CALL_PROVIDER_RETRY, retries)
        emit_writer(trace, outcome="success")
    except Exception:      # pragma: no cover — трасса не рвёт ход
        logger.debug("[turn_trace] completion note failed", exc_info=True)


def note_l2_refusal(correlation_id, reason: str, **fields) -> None:
    """Честный отказ L2: НЕ обычный успех (outcome=failed + причина)."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        trace.completion.update({
            "refused": True,
            "refused_reason": str(reason or "")[:64],
            "text_source": "none",
        })
        for key, value in (fields or {}).items():
            if value is None:
                continue
            trace.completion[str(key)[:32]] = (
                value if isinstance(value, (int, float, bool))
                else str(value)[:64])
        trace.raw_final_digest = text_digest(fields.get("text", ""))
        emit_writer(trace, outcome="failed")
    except Exception:      # pragma: no cover
        pass


def note_op(correlation_id, name: str, text, *, note: str = "") -> None:
    """Записать фактически применённую доставочную операцию (+digest)."""
    trace = get(correlation_id)
    if trace is None or name not in OP_NAMES:
        return
    try:
        trace._append_op(name, text)
        if note:
            trace.ops[-1]["note"] = str(note)[:32]
    except Exception:      # pragma: no cover
        pass


def note_delivery(correlation_id, *, outcome: str = "success",
                  tg_message_ids=None, chunks=None, channel: str = "",
                  reason: str = "", payload=None) -> None:
    """Итог доставки: операции, digest, идемпотентный ключ, Telegram ID."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        if payload is not None:
            trace._append_op(OP_EGRESS_SANITIZE, payload)
        if chunks is not None or tg_message_ids:
            # Chunking режет ТОТ ЖЕ текст: смысл не меняется, digest тот же.
            trace._append_chain_op(
                OP_CHUNK, chunks=int(chunks or len(list(tg_message_ids or ()))
                                     or 1))
        trace.delivered_digest = trace._last_digest
        trace._divergence()
        trace.delivery = {
            "outcome": str(outcome or "")[:24],
            "channel": str(channel or "")[:16],
            "reason": str(reason or "")[:64],
            "chat_id": trace.chat_id,
            "tg_message_ids": [int(x) for x in list(tg_message_ids or ())
                               if isinstance(x, int)][:8],
            "idempotency_key": trace.idempotency_key,
        }
        emit_delivery(trace, outcome=("success" if outcome == "success"
                                      else "skipped"))
    except Exception:      # pragma: no cover — трасса не рвёт доставку
        logger.debug("[turn_trace] delivery note failed", exc_info=True)


def note_stop(correlation_id, outcome: str, reason: str) -> None:
    """Ход закончился без доставки текста: честная причина в трассе."""
    trace = get(correlation_id)
    if trace is None:
        return
    trace.stop_outcome = str(outcome or "")[:24]
    trace.stop_reason = str(reason or "")[:64]


def close(correlation_id) -> None:
    """Закрыть трассу хода: незакрытые стадии эмитятся честным исходом.

    Если доставки не было (silence/react/image-only/ошибка), событие доставки
    всё равно появляется — с `outcome != success` и причиной, чтобы «хода не
    было видно» не превращалось в «ход прошёл успешно»."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        if not trace._context_emitted:
            emit_context(trace, outcome=("skipped" if trace.stop_outcome
                                         else "success"))
        if not trace._writer_emitted:
            # L2 не вызывался: это НЕ «успешный Writer», а отсутствие стадии.
            if trace.stop_outcome or not trace.raw_final_digest:
                emit_writer(trace, outcome="skipped")
        if not trace._delivery_emitted:
            trace._divergence()
            trace.delivery = {
                "outcome": trace.stop_outcome or "skipped",
                "reason": trace.stop_reason or "no_text_delivery",
                "chat_id": trace.chat_id,
                "tg_message_ids": [],
                "idempotency_key": trace.idempotency_key,
            }
            trace.delivered_digest = trace._last_digest
            emit_delivery(trace, outcome="skipped")
    except Exception:      # pragma: no cover — трасса не рвёт ход
        pass


def reset() -> None:
    """Сброс in-memory трасс (тесты)."""
    with _lock:
        _turns.clear()
