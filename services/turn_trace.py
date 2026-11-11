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
import re
import threading
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)

# ── события трассы (свободная ось `event_name` mca-13; один trace_id) ───────
EVENT_CONTEXT = "direct_turn_context"      # trigger/chat/clock/L1/tools
EVENT_WRITER = "direct_turn_writer"        # манифест запроса + завершение L2
EVENT_DELIVERY = "direct_turn_delivery"    # операции доставки + digest + итог
#: UR-F (unified-reply, шаг 1): ЧТО именно попало в запрос L2 — счётчики,
#: бюджет, блоки с датами/ссылками, потерянное и собственные реплики бота.
#: Эмитится `note_selection` БЕЗ in-memory `TurnTrace` (см. ниже).
EVENT_SELECTION = "direct_turn_selection"

#: Жёсткие лимиты списков события выбора (UR-F §7 R1): payload обязан
#: оставаться в пределах `usage_json`, иначе `_pack` начнёт вытеснять
#: содержательные поля. Переполнение режется ДЕТЕРМИНИРОВАННО и видно
#: (`truncated` у события или усечённый список), а не молча теряется.
SELECTION_BLOCKS_MAX = 16
SELECTION_SOURCE_IDS_MAX = 8
SELECTION_DROPPED_MAX = 8
SELECTION_SELF_OUTPUTS_MAX = 6
#: Ссылки выдачи (`source_links`) живут в отдельном JSON-слое
#: `source_ref_json`, который `mca_events` ограничивает 2000 символами.
SOURCE_LINKS_MAX = 6
SOURCE_LINK_JSON_LIMIT = 2000
#: Пределы значений allow-ветки ссылок (UR-F §3 R4).
SOURCE_URL_MAX = 300
SOURCE_TITLE_MAX = 120
#: ЕДИНСТВЕННОЕ ослабление текстовой защиты: публичный адрес выдачи.
#: Не текст чата, но длинный — поэтому `_scrub` превратил бы его в digest.
SOURCE_URL_RE = re.compile(r"^https?://\S{4,%d}$" % SOURCE_URL_MAX)

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
        "clock_ts", "clock_timezone", "clock_as_of_utc",
        "clock_config_version", "clock_timezone_source", "clock_stages",
        "reply_to_message_id", "reply_to_author_id", "source_message_ts",
        "reply_to_message_ts", "alias_source_author", "alias_reply_parent",
        "l1", "tools", "tool_rounds", "tool_degraded",
        "tool_reason", "coverage", "llm_calls", "manifest", "request",
        "completion", "semantic_rewrite_count", "raw_final_digest",
        "delivered_digest", "divergence_reason", "digest_match", "ops",
        "delivery", "author_state", "stop_reason", "stop_outcome",
        "_last_digest", "_last_chars", "_context_emitted", "_writer_emitted",
        "_delivery_emitted", "started_ts",
    )

    def __init__(self, correlation_id: str, *, chat_id=None, trigger: str = "",
                 flow: str = FLOW_DIRECT, source_message_id=None,
                 source_author_id=None, idempotency_key: str = "",
                 reply_to_message_id=None, reply_to_author_id=None,
                 source_message_ts=None, reply_to_message_ts=None,
                 alias_source_author: str = "",
                 alias_reply_parent: str = ""):
        self.correlation_id = str(correlation_id)
        self.chat_id = int(chat_id) if chat_id is not None else None
        self.trigger = _code(trigger, 32)
        self.flow = _code(flow, 16) or FLOW_DIRECT
        self.source_message_id = source_message_id
        self.source_author_id = source_author_id
        self.idempotency_key = _code(idempotency_key, 96)
        # UR-20.4 (UR-F шаг 1): источник хода и родитель ответа. Только
        # id/дата и ДВА пер-ходовых алиаса (§3): полный ростер не пишется.
        self.reply_to_message_id = reply_to_message_id
        self.reply_to_author_id = reply_to_author_id
        self.source_message_ts = source_message_ts
        # UR-20.4 (доработка шага 1): время сообщения-родителя ответа. Раньше
        # карточка показывала «в ответ на: … (сообщение N)» без времени —
        # дата родителя просто не доезжала до события.
        self.reply_to_message_ts = reply_to_message_ts
        self.alias_source_author = alias(alias_source_author)
        self.alias_reply_parent = alias(alias_reply_parent)
        # UR-C-CLOCK (UR-26.7): структурированные поля ChatClock (аддитивно).
        self.clock_timezone = ""
        self.clock_as_of_utc = ""
        self.clock_config_version = ""
        self.clock_timezone_source = ""
        self.clock = ""
        self.clock_source = ""
        self.clock_ts = None
        #: UR-20.8: стадии, реально получившие TimeContext (`l1`/`tool`/`l2`).
        self.clock_stages: list = []
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
        # UR-20.4/UR-20.8 (UR-F шаг 1, аддитивно): источник хода и родитель
        # ответа (id/дата/два алиаса) + стадии, реально получившие TimeContext.
        # Ключи появляются только при реальном значении — старая трасса не
        # получает `null`-заглушек (§2 «честная пустота»).
        for key, value in (
                ("reply_to_message_id", self.reply_to_message_id),
                ("reply_to_author_id", self.reply_to_author_id),
                ("source_message_ts", self.source_message_ts),
                ("reply_to_message_ts", self.reply_to_message_ts),
                ("alias_source_author", self.alias_source_author),
                ("alias_reply_parent", self.alias_reply_parent)):
            if value not in (None, "", 0):
                payload[key] = value
        # UR-29.3/UR-20.8 (UR-F шаг 2): структурированные поля ChatClock
        # (`note_clock` их уже принимает и хранит, но в событие они не ехали —
        # Inspector читал пустые строки). Те же правила «честной пустоты»:
        # ключ есть только при реальном значении.
        for key, value in (
                ("clock_timezone", self.clock_timezone),
                ("clock_as_of_utc", self.clock_as_of_utc),
                ("clock_config_version", self.clock_config_version),
                ("clock_timezone_source", self.clock_timezone_source)):
            if value not in (None, ""):
                payload[key] = value
        if self.clock_stages:
            payload["clock_stages"] = list(self.clock_stages)
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

#: Ключи, в которых по смыслу может оказаться текст чата/промпта. Такие
#: значения НИКОГДА не пишутся — только digest и длина (§7 приватность).
_TEXT_KEYS = frozenset({
    "text", "content", "answer", "query", "prompt", "raw", "payload",
    "note", "message", "sentence", "draft", "phrase", "reason_text",
})
#: Строка длиннее этого — не код/enum/id, а потенциальный текст: заменяется
#: digest'ом. Короткие коды (finish_reason/model/revision/op) остаются.
_MAX_FIELD_CHARS = 64
#: Форма кода/enum/id: без пробелов и произвольной пунктуации.
_CODE_RE = re.compile(r"^[A-Za-z0-9_.:/+@()\-]{1,96}$")
#: Ключи, которым разрешено остаться строкой вопреки `_MAX_FIELD_CHARS`:
#: публичный адрес выдачи (только `^https?://…`, иначе "") и заголовок
#: страницы (≤120). Единственное место, где защита от текста ослаблена
#: (UR-F §3 R4) — покрыто негативным тестом «текст чата в `source_url`».
_LINK_KEYS = frozenset({"source_url"})


def _code(value, limit: int = 32) -> str:
    """Оставить только код/enum/id; любой текст (в т.ч. без пробелов) → ''.

    Это НЕ «срез до N символов»: фраза чата, даже короткая, не является
    кодом и отбрасывается целиком."""
    text = str(value if value is not None else "").strip()
    if not text or len(text) > 96 or not _CODE_RE.match(text):
        return ""
    return text[:limit]


def alias(value) -> str:
    """Алиас участника хода (≤48): имя/ник, `@` срезается.

    UR-F §3: полный ростер `_turn_aliases_snapshot()` в трассу НЕ пишется —
    ровно два значения на ход (`alias_source_author`/`alias_reply_parent`).
    Не-строка (двойник/`MagicMock`) → "" — выдуманное значение не пишем.
    """
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    text = text.lstrip("@").strip()
    return text[:48]


def trace_code(value, limit: int = 32) -> str:
    """Публичный нормализатор кода/enum/id для трассы (тот же, что `_code`).

    Нужен продюсерам вне этого модуля (`direct_execution.source_links`),
    чтобы «что считается кодом» определялось в ОДНОМ месте."""
    return _code(value, limit)


def _scrub(value, *, key: str = ""):
    """Рекурсивно убрать текст из payload'а: text-ключи и длинные строки →
    digest + длина. Всё, что похоже на код/enum/id, остаётся как есть.

    Два ИМЕНОВАННЫХ исключения (UR-F §3, R4) — и только они:
    `source_url` (публичный адрес выдачи, строго `^https?://\\S{4,300}$`,
    иначе "") и `source_title` (≤120 символов). Любой другой ключ, включая
    `source_url` с текстом чата внутри, проходит обычную защиту."""
    if isinstance(value, dict):
        return {str(k): _scrub(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item, key=key) for item in value]
    if isinstance(value, str):
        if key in _LINK_KEYS:
            return value if SOURCE_URL_RE.match(value) else ""
        if key == "source_title":
            return value.strip()[:SOURCE_TITLE_MAX]
        if key in _TEXT_KEYS or len(value) > _MAX_FIELD_CHARS:
            return {"digest": text_digest(value), "chars": len(value)}
        return value
    return value


def _pack(payload: dict) -> dict:
    """Уложить payload в лимит `usage_json` без потери смысла полей.

    Крупные списки усекаются ДЕТЕРМИНИРОВАННО и это видно (`truncated`), а не
    молча: обрезанный JSON в `mca_events` был бы нечитаем.

    Здесь же — последний сеть против утечки текста (§7): значения
    text-подобных ключей и любые строки длиннее `_MAX_FIELD_CHARS` заменяются
    digest'ом и длиной. Полевой код обязан не передавать текст, а эта сеть
    ловит будущую регрессию, даже если она появится в новом поле."""
    data = _scrub(dict(payload))
    try:
        if len(json.dumps(data, ensure_ascii=False)) <= _PAYLOAD_LIMIT:
            return data
        # Порядок вытеснения: сначала то, что не несёт смысла при переполнении
        # (собственные реплики / потерянные блоки), затем крупные списки.
        for key in ("self_outputs", "dropped"):
            value = data.get(key)
            if isinstance(value, list) and value:
                data[key] = value[:3]
        if len(json.dumps(data, ensure_ascii=False)) <= _PAYLOAD_LIMIT:
            data["truncated"] = True
            return data
        for key in ("tools", "ops", "blocks", "revisions", "fallback_chain",
                    "source_links"):
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
        return _scrub(dict(payload))
    return data


def _emit_raw(event_name: str, *, chat_id, trace_id, stage: str,
              outcome: str, payload: dict):
    """Эмитировать событие трассы через существующий контракт mca-13.

    Отделено от `TurnTrace`, потому что часть событий (`direct_turn_selection`)
    обязана записываться и без in-memory трассы (`begin()` не состоялся)."""
    try:
        from services import mca_events as _me
        return _me.emit_mca_event(
            event_name, outcome=outcome, component="direct_chat",
            stage=stage, chat_id=chat_id, trace_id=trace_id,
            usage_json=_pack(payload))
    except Exception:      # pragma: no cover — трасса не рвёт ход
        return None


def _emit(trace: TurnTrace, event_name: str, *, stage: str, outcome: str,
          payload: dict):
    """Эмитировать событие трассы через существующий контракт mca-13."""
    return _emit_raw(event_name, chat_id=trace.chat_id,
                     trace_id=trace.correlation_id, stage=stage,
                     outcome=outcome, payload=payload)


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
          idempotency_key: str = "",
          reply_to_message_id=None, reply_to_author_id=None,
          source_message_ts=None, reply_to_message_ts=None,
          alias_source_author: str = "",
          alias_reply_parent: str = "") -> "TurnTrace | None":
    """Начать трассу хода. Нет `correlation_id` → трассы нет (fail-open)."""
    if not correlation_id:
        return None
    try:
        trace = TurnTrace(
            str(correlation_id), chat_id=chat_id, trigger=trigger, flow=flow,
            source_message_id=source_message_id,
            source_author_id=source_author_id,
            idempotency_key=idempotency_key,
            reply_to_message_id=reply_to_message_id,
            reply_to_author_id=reply_to_author_id,
            source_message_ts=source_message_ts,
            reply_to_message_ts=reply_to_message_ts,
            alias_source_author=alias_source_author,
            alias_reply_parent=alias_reply_parent)
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


def note_clock(correlation_id, *, line: str = "", source: str = "",
               timezone: str = "", as_of_utc: str = "",
               config_version: str = "", timezone_source: str = "") -> None:
    """ChatClock хода: значение + источник часов (§7).

    Строка часов генерируется кодом (`chat_clock.render_chat_time_context`,
    UR-C-CLOCK), это не текст чата; всё равно ограничиваем длину и оставляем
    только допустимые символы. UR-26.7: аддитивные структурированные поля
    (timezone/as_of_utc/config_version/timezone_source) для диагностики хода.
    """
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        clock = str(line or "").strip()
        # Часы — сгенерированный штамп: разрешаем цифры/пунктуацию/буквы,
        # но не бесконечную строку.
        trace.clock = clock[:96]
        trace.clock_source = _code(source, 64)
        trace.clock_ts = int(time.time())
        # UR-26.7 (аддитивно, только коды/числа — без текстов чата).
        if str(timezone or "").strip():
            trace.clock_timezone = _code(timezone, 64)
        if str(as_of_utc or "").strip():
            trace.clock_as_of_utc = _code(as_of_utc, 32)
        if str(config_version or "").strip():
            trace.clock_config_version = _code(config_version, 64)
        if str(timezone_source or "").strip():
            trace.clock_timezone_source = _code(timezone_source, 32)
    except Exception:      # pragma: no cover
        pass


#: Порядок стадий хода для `clock_stages` (UR-20.8): кто реально подал
#: TimeContext. Порядок канонический, чтобы одно и то же множество стадий
#: давало одинаковый payload независимо от порядка вызовов.
CLOCK_STAGE_ORDER = ("l1", "tool", "l2")


def note_clock_stage(correlation_id, stage: str) -> None:
    """Отметить стадию хода, которая РЕАЛЬНО получила TimeContext (UR-20.8).

    Вызывается там, где строка часов действительно попала в payload стадии
    (`l1` — планировщик, `tool` — tool-фаза, `l2` — Writer). Пустая строка
    часов стадию не отмечает: «часы не поданы» — факт, а не догадка.
    """
    trace = get(correlation_id)
    if trace is None or stage not in CLOCK_STAGE_ORDER:
        return
    try:
        if stage not in trace.clock_stages:
            trace.clock_stages.append(stage)
            trace.clock_stages.sort(
                key=lambda item: CLOCK_STAGE_ORDER.index(item)
                if item in CLOCK_STAGE_ORDER else len(CLOCK_STAGE_ORDER))
    except Exception:      # pragma: no cover — трасса не рвёт ход
        pass


def note_l1(correlation_id, *, action: str = "", response_act: str = "",
            structure: str = "", plan_source: str = "",
            execution_mode: str = "", override: str = "", model: str = "",
            fallback: str = "") -> None:
    """L1 action/plan этого хода (план — не авторская речь, §7).

    Значения L1 приходят из ответа модели, поэтому каждое проверяется как
    код/enum: свободный текст (даже короткий) отбрасывается."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        trace.l1 = {
            "action": _code(action, 24),
            "response_act": _code(response_act, 32),
            "structure": _code(structure, 24),
            "plan_source": _code(plan_source, 24),
            "execution_mode": _code(execution_mode, 24),
            "override": _code(override, 48),
            "model": _code(model, 64),
            "fallback": _code(fallback, 64),
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
        "tool": _code(entry.get("tool"), 40),
        "round": entry.get("round"),
        "status": _code(entry.get("status"), 32),
        "error": _code(entry.get("error_code")
                       or entry.get("error_type"), 40),
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
        trace.tool_reason = _code(reason, 40)
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
            coverage["evidence_class"] = _code(
                getattr(decision, "evidence_class", ""), 32)
            coverage["required"] = bool(getattr(decision, "required", False))
        trace.coverage = coverage
    except Exception:      # pragma: no cover — трасса не рвёт ход
        pass


# ════════════════════════════════════════════════════════════════════════════
# UR-F (шаг 1): выбор контекста хода — durable БЕЗ in-memory трассы
# ════════════════════════════════════════════════════════════════════════════

STAGE_SELECTION = "turn_selection"
_COUNT_KEYS = ("available_messages", "included_messages", "window_messages")
_BUDGET_INT_KEYS = ("window", "output_reserve", "available", "budget",
                    "payload_tokens", "fallback_window")
_BUDGET_CODE_KEYS = ("slot", "window_source", "policy_mode")


def _sel_int(value):
    """Целое из свободного значения; всё остальное → None (не выдумываем)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _sel_items(value, limit: int) -> list:
    """Bounded-список без падения на неожиданном типе."""
    try:
        return list(value or ())[:int(limit)]
    except Exception:      # pragma: no cover — защитная ветка
        return []


def _json_size(value) -> int:
    """Размер JSON в символах (лимит `usage_json` считается так же)."""
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except Exception:      # pragma: no cover — защитная ветка
        return 0


def _sel_block(item, *, cuts: dict | None = None) -> dict | None:
    """Один блок контекста: kind/role/rendered/даты/ссылки/токены (без текста).

    `role` — НЕ авторская роль участника: здесь лежит приоритет вытеснения
    piece'а в аллокации композера (`p0`…`p3`: P0 не вытесняется, P3 режется
    первым). Так Inspector видит, чем блок держался в запросе.

    `cuts` (необязательный) — сборщик фактов усечения: если id в блоке больше
    лимита, туда ставится отметка, и событие честно помечается `truncated`."""
    if not isinstance(item, dict):
        return None
    kind = _code(item.get("kind"), 32)
    if not kind:
        return None
    row: dict = {"kind": kind, "rendered": bool(item.get("rendered"))}
    role = _code(item.get("role"), 16)
    if role:
        row["role"] = role
    skip = _code(item.get("skip_reason"), 32)
    if skip:
        row["skip_reason"] = skip
    raw_ids = [_code(ref, 48) for ref in
               _sel_items(item.get("source_ids"), SELECTION_SOURCE_IDS_MAX * 4)]
    raw_ids = [ref for ref in raw_ids if ref]
    if len(raw_ids) > SELECTION_SOURCE_IDS_MAX and cuts is not None:
        cuts["source_ids"] = True
    ids = raw_ids[:SELECTION_SOURCE_IDS_MAX]
    if ids:
        row["source_ids"] = ids
    first_ts = _sel_int(item.get("first_ts"))
    last_ts = _sel_int(item.get("last_ts"))
    if first_ts:
        row["first_ts"] = first_ts
    if last_ts:
        row["last_ts"] = last_ts
    tokens = _sel_int(item.get("tokens"))
    if tokens is not None:
        row["tokens"] = tokens
    return row


def _sel_dropped(items, *, cuts: dict | None = None) -> tuple[list, int]:
    """Потерянное на аллокации: агрегат по (reason_code, kind) — ≤8 строк.

    Вход агрегируется ЦЕЛИКОМ. Возвращает `(строки, всего_потерь)`:
    счётчики сохраняются ВСЕГДА (`dropped_total`), а усечение числа строк
    видно (`cuts["dropped"]` → `truncated`), а не теряется молча."""
    grouped: dict = {}
    for item in _sel_items(items, 256):
        if not isinstance(item, dict):
            continue
        reason = _code(item.get("reason_code"), 40)
        kind = _code(item.get("kind"), 32)
        if not reason and not kind:
            continue
        count = _sel_int(item.get("count"))
        if count is None:
            count = 1
        key = (reason, kind)
        grouped[key] = grouped.get(key, 0) + max(0, count)
    rows = [{"reason_code": reason, "kind": kind, "count": count}
            for (reason, kind), count in grouped.items()]
    rows.sort(key=lambda row: (-row["count"], row["reason_code"],
                               row["kind"]))
    total = sum(row["count"] for row in rows)
    if len(rows) > SELECTION_DROPPED_MAX:
        logger.info("[turn_trace] selection dropped groups truncated | "
                    "groups=%d kept=%d", len(rows), SELECTION_DROPPED_MAX)
        rows = rows[:SELECTION_DROPPED_MAX]
        if cuts is not None:
            cuts["dropped"] = True
    return rows, total


def _sel_self_outputs(items, *, cuts: dict | None = None) -> list:
    """Свои реплики в истории хода: source_id/tg id/дата (≤6, без текста)."""
    raw = _sel_items(items, SELECTION_SELF_OUTPUTS_MAX + 8)
    rows: list = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row: dict = {}
        source_id = _code(item.get("source_id"), 48)
        if source_id:
            row["source_id"] = source_id
        tg_id = _sel_int(item.get("tg_message_id"))
        if tg_id:
            row["tg_message_id"] = tg_id
        ts = _sel_int(item.get("ts"))
        if ts:
            row["ts"] = ts
        if row:
            rows.append(row)
    if len(rows) > SELECTION_SELF_OUTPUTS_MAX:
        if cuts is not None:
            cuts["self_outputs"] = True
        rows = rows[:SELECTION_SELF_OUTPUTS_MAX]
    return rows


def _selection_payload(raw) -> dict:
    """Нормализовать payload события выбора: лимиты списков и только коды.

    Применяется ДО `_pack`, поэтому лимиты (блоки ≤16, id ≤8, потерянное ≤8,
    собственные реплики ≤6) — жёсткие, а не «сколько влезло в JSON».
    Любое срабатывание такого лимита помечается `truncated: true`, а потери
    сохраняют честный итог в `dropped_total` (даже если часть строк пришлось
    сократить). Это единственный честный способ не выдавать срез за полноту
    (UR-23.7: «неизвестно» ≠ ноль)."""
    data = raw if isinstance(raw, dict) else {}
    payload: dict = {}
    cuts: dict = {}
    counts = data.get("counts")
    if isinstance(counts, dict):
        clean = {key: _sel_int(counts.get(key)) for key in _COUNT_KEYS}
        clean = {key: value for key, value in clean.items()
                 if value is not None}
        if clean:
            payload["counts"] = clean
    budget = data.get("budget")
    if isinstance(budget, dict):
        clean_budget: dict = {}
        for key in _BUDGET_CODE_KEYS:
            code = _code(budget.get(key), 32)
            if code:
                clean_budget[key] = code
        for key in _BUDGET_INT_KEYS:
            value = _sel_int(budget.get(key))
            if key == "fallback_window":
                # Контракт типизирует поле как `int|None`: None = «fallback-
                # окна не было» — это факт, а не отсутствие данных.
                clean_budget[key] = value
                continue
            if value is not None:
                clean_budget[key] = value
        if clean_budget:
            payload["budget"] = clean_budget
    raw_blocks = [item for item in
                  _sel_items(data.get("blocks"), SELECTION_BLOCKS_MAX + 8)
                  if isinstance(item, dict)]
    if len(raw_blocks) > SELECTION_BLOCKS_MAX:
        cuts["blocks"] = True
    blocks = [row for row in
              (_sel_block(item, cuts=cuts)
               for item in raw_blocks[:SELECTION_BLOCKS_MAX])
              if row]
    if blocks:
        payload["blocks"] = blocks
    dropped, dropped_total = _sel_dropped(data.get("dropped"), cuts=cuts)
    if dropped:
        payload["dropped"] = dropped
        if dropped_total != sum(row["count"] for row in dropped):
            # Строки не покрывают все потери — итог обязателен, иначе
            # «12 → 8» читается как «потеряно 8».
            payload["dropped_total"] = dropped_total
    self_outputs = _sel_self_outputs(data.get("self_outputs"), cuts=cuts)
    if self_outputs:
        payload["self_outputs"] = self_outputs
    policy_version = _code(data.get("policy_version"), 32)
    if policy_version:
        payload["policy_version"] = policy_version
    if cuts:
        payload["truncated"] = True
    # Если payload не влезает в `usage_json`, сначала сокращаются ВТОРОСТЕПЕННЫЕ
    # списки (свои реплики → потерянное), затем блоки с КОНЦА. Списки остаются
    # списками (а не `{"count": N}` при упаковке), факт усечения помечен
    # `truncated`. Приоритет: «что видел ответ» важнее производных списков.
    if _json_size(payload) > _PAYLOAD_LIMIT \
            and len(payload.get("self_outputs") or ()) > 3:
        payload["self_outputs"] = payload["self_outputs"][:3]
        payload["truncated"] = True
    if _json_size(payload) > _PAYLOAD_LIMIT \
            and len(payload.get("dropped") or ()) > 4:
        payload["dropped"] = payload["dropped"][:4]
        payload["truncated"] = True
        if dropped_total:
            payload["dropped_total"] = dropped_total
    while len(payload.get("blocks") or ()) > 1 \
            and _json_size(payload) > _PAYLOAD_LIMIT:
        payload["blocks"] = payload["blocks"][:-1]
        payload["truncated"] = True
    return payload


def note_selection(correlation_id, *, chat_id=None, payload=None) -> None:
    """Записать ЧТО попало в запрос L2 (UR-20.5/20.6/20.7) — БЕЗ трассы в RAM.

    Отдельная от `begin()` точка эмиссии: событие обязано появиться, даже
    если in-memory `TurnTrace` не создан (`begin()` не вызывался) или уже
    вытеснен LRU. Текста чата здесь нет по построению: только счётчики,
    бюджет, kind/role/даты/ссылки блоков, потерянное и свои реплики.
    Никогда не бросает — ход важнее трассы (§7 R3)."""
    if not correlation_id:
        return
    try:
        _emit_raw(EVENT_SELECTION, chat_id=chat_id,
                  trace_id=str(correlation_id), stage=STAGE_SELECTION,
                  outcome="success", payload=_selection_payload(payload))
    except Exception:      # pragma: no cover — трасса не рвёт ход
        logger.debug("[turn_trace] selection note failed", exc_info=True)


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
                revisions[_code(key, 48) or str(key)[:48]] = _code(
                    revision, 48)
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
        writer = _code(writer_name, 24)
        profile = ""
        representation = ""
        tokens_total = 0
        if manifest is not None:
            manifest_id = _code(
                getattr(manifest, "manifest_id", ""), 40)
            writer = _code(getattr(manifest, "writer", ""), 24) or writer
            profile = _code(getattr(manifest, "profile", ""), 24)
            representation = _code(
                getattr(manifest, "context_representation", ""), 16)
            tokens_total = int(getattr(manifest, "tokens_total", 0) or 0)
            for layer in tuple(getattr(manifest, "layers", ()) or ())[:16]:
                layer_name = _code(getattr(layer, "layer", ""), 24)
                block_id = _code(getattr(layer, "block_id", ""), 32)
                built_blocks.append({
                    "block": ("%s:%s" % (layer_name, block_id)).strip(":"),
                    "rendered": bool(getattr(layer, "rendered", False)),
                    "skip": _code(getattr(layer, "skip_reason", ""), 32),
                })
            versions = dict(getattr(manifest, "versions", {}) or {})
            for key, value in list(versions.items())[:8]:
                revisions[_code(key, 48)] = _code(value, 48)
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
            "provider": _code(provider, 48),
            "model": _code(model, 64),
            "fallback_model": _code(fallback_model, 64),
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
            "finish_reason": _code(finish_reason) or "unknown",
            "finish_reason_raw": _code(
                getattr(completion, "finish_reason_raw", None), 48),
            "metadata_available": completion is not None,
            "completed": bool(getattr(continuation, "completed", True)),
            "is_truncated": bool(getattr(completion, "is_truncated", False)),
            "attempt": attempt,
            "fallback_used": bool(getattr(completion, "fallback_used", False)),
            "provider": _code(getattr(completion, "provider", ""), 48),
            "model": _code(getattr(completion, "model", ""), 64),
            "usage": {k: usage_dict[k] for k in
                      ("prompt_tokens", "completion_tokens", "total_tokens")
                      if k in usage_dict},
            "max_output_tokens_sent": getattr(
                completion, "max_output_tokens_sent", None),
            "chars": len(str(raw_text or "")),
            "raw_final_digest": trace.raw_final_digest,
            "continuation_calls": int(
                getattr(continuation, "continuation_calls", 0) or 0),
            "continuation_stop_reason": _code(
                getattr(continuation, "stop_reason", "")),
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


def note_l2_refusal(correlation_id, reason: str, *, stop_reason=None,
                    continuation_calls=None, finish_reason=None,
                    text: str = "") -> None:
    """Честный отказ L2: НЕ обычный успех (outcome=failed + причина).

    Текст отказа здесь НЕ пишется ни в каком виде (§7 приватность): только
    digest, длина и коды причины. Никаких «срезов до N символов» — срез всё
    равно остаётся текстом чата."""
    trace = get(correlation_id)
    if trace is None:
        return
    try:
        trace.raw_final_digest = text_digest(text)
        trace.completion.update({
            "refused": True,
            "refused_reason": _code(reason, 64),
            "text_source": "none",
            "chars": len(str(text or "")),
            "raw_final_digest": trace.raw_final_digest,
        })
        # Коды/числа — явным списком; произвольные поля вызывающего не
        # переносятся (нет поверхности для утечки текста).
        if stop_reason is not None:
            trace.completion["continuation_stop_reason"] = _code(stop_reason)
        if finish_reason is not None:
            trace.completion["finish_reason"] = _code(finish_reason) or "unknown"
        if continuation_calls is not None:
            try:
                trace.completion["continuation_calls"] = int(
                    continuation_calls)
            except Exception:      # pragma: no cover
                pass
        emit_writer(trace, outcome="failed")
    except Exception:      # pragma: no cover
        pass


def note_op(correlation_id, name: str, text) -> None:
    """Записать фактически применённую доставочную операцию (+digest)."""
    trace = get(correlation_id)
    if trace is None or name not in OP_NAMES:
        return
    try:
        trace._append_op(name, text)
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
            "outcome": _code(outcome, 24),
            "channel": _code(channel, 16),
            "reason": _code(reason, 64),
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
    trace.stop_outcome = _code(outcome, 24)
    trace.stop_reason = _code(reason, 64)


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
