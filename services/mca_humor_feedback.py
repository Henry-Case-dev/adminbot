"""SOUL-08 (W4) — Humor Feedback Loop как ЧАСТЬ существующего Experience.

Границы (requirements-map W4 + SOUL-AMD §9):

* **SOUL-08.0/08.1** — отдельный самодельный контур самообучения НЕ создаётся:
  всё живёт в `mca_experience` (эпизоды → feedback → уроки → применения →
  исходы) и расширяет его новыми типами evidence/feedback и контекстными
  речевыми предпочтениями.
* **SOUL-08.2** — при отправке сохраняются только bounded-метаданные:
  `chat_id`, Telegram `message_id`, reply/thread linkage, модель/версия Core,
  выбранная стратегия, ref использованных few-shot, факт отправки, канал.
  Никаких секретных промптов и сырых пользовательских текстов.
* **SOUL-08.3–08.7** — окно после ответа: явное одобрение, реакции,
  продолженные образы, семантическое продолжение метафоры, раздражение,
  просьба прекратить, коррекция адресата/факта; отсутствие ответа — **unknown**,
  активности без семантической связи — не успех.
* **SOUL-08.8** — классификация семантическая/LLM там, где уместно, с evidence
  links, provenance, confidence, timeout и bounded batch-budget; ошибка
  оценщика НЕ блокирует беседу (весь контур — асинхронный, fail-open).
* **SOUL-08.9** — консервативные вероятностные обновления с защитой от малого
  N, активности одного пользователя, бригадинга, обратной причинности и
  engagement-gaming; per-chat изоляция; низкая уверенность = гипотеза.
* **SOUL-08.10/08.11** — измеримый эффект на СЛЕДУЮЩИЙ ответ, decay/старение,
  bounded хранение, rollback/disable, видимая телеметрия; отрицательная связь
  ослабляет стратегию в контексте, а не запрещает шутить глобально.

Модуль не делает LLM-вызовов в основном пути: классификация выполняется в
существующем bounded-джобе опыта (`mca_experience_jobs`), который вызывает
чистые функции отсюда.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

logger = logging.getLogger(__name__)

POLICY_VERSION = "soul1-w4-feedback-1"
CLASSIFIER_VERSION = "soul1-w4-classifier-1"

#: Окно наблюдения после ответа (bounded; далее — unknown).
WINDOW_SECONDS = 900
#: Бюджет одного классифицирующего прохода (bounded batch-budget).
BATCH_MAX_ROWS = 4
BATCH_MAX_TOKENS = 900
BATCH_TIMEOUT_S = 45.0
#: Защита от малого N / одного пользователя / бригандинга.
MIN_INDEPENDENT_OBSERVATIONS = 3
MAX_SINGLE_USER_SHARE = 0.6
MAX_REACTORS_PER_MESSAGE = 3
MAX_WEIGHT_PER_SEND = 1.0

SEND_TASK_TYPE = "humor_send"

#: Типы сигналов (закрытый набор, SOUL-08.3–08.7).
SIGNALS: tuple[str, ...] = (
    "explicit_approval",          # явное одобрение шутки / цитирование образа
    "metaphor_continuation",      # семантическое продолжение метафоры в ветке
    "irritation",                 # явное раздражение
    "stop_request",               # просьба прекратить
    "wrong_addressee",            # коррекция неверного адресата
    "fact_correction",            # коррекция факта
    "unrelated",                  # активность без семантической связи
    "unknown",                    # нет ответа / нет оценки
)

#: Сигналы, требующие semantic-подтверждения (детерминированные маркеры —
#: только evidence, а не приговор; SOUL-08.8).
SEMANTIC_REQUIRED: tuple[str, ...] = (
    "explicit_approval", "metaphor_continuation", "irritation",
)
#: Сигналы, которые владелец подтверждает явным сообщением (права владельца).
OWNER_CONFIRMABLE: tuple[str, ...] = (
    "stop_request", "wrong_addressee", "fact_correction", "irritation",
)
#: Направление влияния: положительные усиливают, отрицательные ослабляют.
POSITIVE_SIGNALS = frozenset({"explicit_approval", "metaphor_continuation"})
NEGATIVE_SIGNALS = frozenset({"irritation", "stop_request", "wrong_addressee",
                             "fact_correction"})

# ── Детерминированные маркеры (ТОЛЬКО evidence; не единственная основа) ────
_MARKER_STOP = re.compile(
    r"(перестань|прекрати|хватит|не\s+надо)\s+(это|так|шутить|материться|"
    r"ругаться|оскорблять)", re.IGNORECASE)
_MARKER_IRRITATION = re.compile(
    r"(задолбал|достал[оа]?|бесит|раздражае|не\s+смешно|надоел)", re.IGNORECASE)
_MARKER_FACT = re.compile(
    r"(это\s+неправда|ты\s+ошиб|неверно|на\s+самом\s+деле|поправк)", re.IGNORECASE)
_MARKER_ADDRESSEE = re.compile(
    r"(я\s+не\s+(об\s+этом|про\s+это)|не\s+мне\b|это\s+было\s+не\s+мне|"
    r"отвеч(аешь|ай)\s+не\s+тому)", re.IGNORECASE)
_MARKER_APPROVAL = re.compile(
    r"(ахах|хаха|ору|в\s+голос|ржака|гениально|шикарно|плюсую|согласен,?\s+"
    r"смешно|good\s+joke)", re.IGNORECASE)

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
_TOKEN_RE_FEEDBACK = re.compile(r"[\w\-]{3,}", re.UNICODE)


def _now(ts: int | float | None = None) -> int:
    return int(ts if ts is not None else time.time())


def gate_on() -> bool:
    """Ось `HUMOR_FEEDBACK_ENABLED` (default OFF)."""
    try:
        from services import mca_gates
        return bool(mca_gates.humor_feedback_enabled())
    except Exception:                      # pragma: no cover
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 1. Bounded-метаданные отправки (SOUL-08.2)
# ═══════════════════════════════════════════════════════════════════════════

#: Ровно те поля, что требует источник (ничего лишнего; тексты не пишем).
SEND_FIELDS: tuple[str, ...] = (
    "chat_id", "message_id", "reply_to_message_id", "thread_id",
    "core_revision", "model", "strategy", "technique", "few_shot_refs",
    "channel", "delivered", "trace_id", "ts",
)


def bounded_send_metadata(**fields: Any) -> dict:
    """Только типизированные bounded-поля (R17: коды/числа/enum, без текста)."""
    out: dict[str, Any] = {}
    for name in SEND_FIELDS:
        if name not in fields:
            continue
        value = fields.get(name)
        if value is None:
            continue
        if name in ("chat_id", "message_id", "reply_to_message_id",
                    "thread_id"):
            try:
                out[name] = int(value)
            except (TypeError, ValueError):
                continue
        elif name == "delivered":
            out[name] = bool(value)
        elif name == "ts":
            out[name] = _now(value)
        elif name == "few_shot_refs":
            refs = [str(r) for r in (value or ()) if _SAFE_TOKEN.match(str(r))]
            if refs:
                out[name] = refs[:3]
        else:
            token = str(value)
            if _SAFE_TOKEN.match(token):
                out[name] = token
    return out


async def capture_send(db=None, **fields: Any) -> dict:
    """Записать bounded-метаданные отправки в существующий контур Experience.

    Возврат: ``{"captured": bool, "episode_id": str|None, "reason": str}``.
    Fail-open: сбой записи не влияет на доставку сообщения.
    """
    if not gate_on():
        return {"captured": False, "episode_id": None,
                "reason": "humor_feedback_disabled"}
    meta = bounded_send_metadata(**fields)
    if not meta.get("chat_id") or not meta.get("message_id"):
        return {"captured": False, "episode_id": None,
                "reason": "missing_send_identity"}
    try:
        from services import mca_experience as me
        from services import lore_runtime
        db = db if db is not None else lore_runtime.get_lore_db()
        if db is None or not hasattr(db, "write_transaction"):
            return {"captured": False, "episode_id": None,
                    "reason": "db_unavailable"}
        service = me.get_service(db)
        decision = {
            "strategy": str(meta.get("strategy") or "none")[:32],
            "technique": str(meta.get("technique") or "none")[:32],
            "channel": str(meta.get("channel") or "plain")[:16],
            "delivered": bool(meta.get("delivered", True)),
            "core_revision": str(meta.get("core_revision") or "")[:32],
            "model": str(meta.get("model") or "")[:32],
            "msg": int(meta.get("message_id") or 0),
            "window": int(WINDOW_SECONDS),
            "policy": POLICY_VERSION,
        }
        if meta.get("reply_to_message_id"):
            decision["reply_to"] = int(meta["reply_to_message_id"])
        if meta.get("few_shot_refs"):
            decision["few_shot"] = list(meta["few_shot_refs"])
        episode_id = await service.capture_episode(
            scope="chat", chat_id=int(meta["chat_id"]),
            task_type=SEND_TASK_TYPE,
            trace_id=str(meta.get("trace_id") or "") or None,
            operation_id=(f"humor-send:{int(meta['chat_id'])}:"
                          f"{int(meta['message_id'])}"),
            decision=decision,
            output_ref=f"tgmsg_{int(meta['message_id'])}",
            outcome_kind="unknown", outcome_source="technical",
            model_version=str(meta.get("model") or "") or None,
            ts=meta.get("ts"))
        if episode_id:
            _emit("humor_send_captured", outcome="success",
                  chat_id=int(meta["chat_id"]),
                  strategy=decision["strategy"],
                  technique=decision["technique"])
        return {"captured": bool(episode_id), "episode_id": episode_id,
                "reason": "" if episode_id else "capture_rejected"}
    except Exception:
        logger.warning("[humor-feedback] send capture failed", exc_info=True)
        return {"captured": False, "episode_id": None, "reason": "error"}


def _emit(event_name: str, *, outcome: str, reason_code: str | None = None,
          level: str | None = None, **fields: Any) -> None:
    """Notable-событие (fail-open; типизированные поля, R17-safe)."""
    try:
        from services.mca_events import LEVEL_INFO, LEVEL_WARN, emit_mca_event
        if level is None:
            level = LEVEL_WARN if outcome in ("failed", "silent") else LEVEL_INFO
        emit_mca_event(event_name, outcome=outcome, level=level,
                       component="humor", reason_code=reason_code, **fields)
    except Exception:
        return


# ═══════════════════════════════════════════════════════════════════════════
# 2. Кандидаты окна: eligibility + детерминированные evidence-маркеры
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class WindowObservation:
    """Одно наблюдение в окне после ответа (только типизированные поля).

    ``text`` живёт ТОЛЬКО в памяти для семантической классификации и никогда
    не попадает в durable-поля контура (SOUL-08.2).
    """

    send_message_id: int
    message_row_id: int
    chat_id: int
    user_id: int | None
    ts: int
    reply_to_message_id: int | None = None
    markers: tuple[str, ...] = ()
    confidence: str = "low"
    signal: str = ""
    provenance: str = ""
    reason: str = ""
    text: str = ""


def marker_codes(text: str) -> tuple[str, ...]:
    """Детерминированные evidence-маркеры (не приговор, SOUL-08.8)."""
    body = str(text or "")
    if not body.strip():
        return ()
    codes: list[str] = []
    if _MARKER_STOP.search(body):
        codes.append("marker_stop_request")
    if _MARKER_IRRITATION.search(body):
        codes.append("marker_irritation")
    if _MARKER_FACT.search(body):
        codes.append("marker_fact_correction")
    if _MARKER_ADDRESSEE.search(body):
        codes.append("marker_wrong_addressee")
    if _MARKER_APPROVAL.search(body):
        codes.append("marker_approval")
    return tuple(codes)


def window_candidates(*, send: Mapping[str, Any],
                      rows: Sequence[Mapping[str, Any]],
                      now_ts: int | float | None = None,
                      window_seconds: int = WINDOW_SECONDS
                      ) -> tuple[list[WindowObservation], list[dict]]:
    """Кандидаты окна + причины исключения (детерминированно, без LLM).

    Жёсткие правила: сигнал обязан быть ПОСЛЕ отправки и внутри окна
    (anti-reverse-causality); активность без связи с ботом (нет reply/thread)
    не является кандидатом успеха (SOUL-08.7).
    """
    now = _now(now_ts)
    send_ts = _now(send.get("ts"))
    send_msg = int(send.get("message_id") or 0)
    chat_id = int(send.get("chat_id") or 0)
    reply_to = send.get("reply_to_message_id")
    muted: set[str] = set()
    try:
        raw_muted = send.get("muted_signals")
        if isinstance(raw_muted, (list, tuple)):
            muted = {str(x) for x in raw_muted}
    except Exception:
        muted = set()
    out: list[WindowObservation] = []
    excluded: list[dict] = []
    for row in rows or ():
        row_chat = row.get("chat_id")
        if row_chat is not None and int(row_chat) != chat_id:
            excluded.append({"row": row.get("id"), "reason": "cross_chat"})
            continue
        row_ts = _now(row.get("timestamp") or row.get("ts"))
        if row_ts <= send_ts:
            excluded.append({"row": row.get("id"),
                             "reason": "reverse_causality"})
            continue
        if row_ts - send_ts > int(window_seconds):
            excluded.append({"row": row.get("id"), "reason": "out_of_window"})
            continue
        row_reply = row.get("reply_to_id")
        linked = False
        if row_reply is not None and send_msg:
            try:
                linked = int(row_reply) == send_msg
            except (TypeError, ValueError):
                linked = False
        if not linked and send.get("thread_id") is not None:
            linked = str(row.get("thread_id") or "") == str(send.get("thread_id"))
        markers = marker_codes(str(row.get("text") or ""))
        if not linked:
            # Без семантической/тредовой связи — не сигнал успеха (08.7),
            # но остаётся кандидатом семантического анализа ветки.
            excluded.append({"row": row.get("id"), "reason": "no_linkage",
                             "markers": list(markers)})
            continue
        candidate_markers = tuple(m for m in markers
                                  if m not in ("marker_approval",))
        signal_hint = ""
        if "marker_stop_request" in markers:
            signal_hint = "stop_request"
        elif "marker_wrong_addressee" in markers:
            signal_hint = "wrong_addressee"
        elif "marker_fact_correction" in markers:
            signal_hint = "fact_correction"
        elif "marker_irritation" in markers:
            signal_hint = "irritation"
        elif "marker_approval" in markers:
            signal_hint = "explicit_approval"
        if signal_hint and signal_hint in muted:
            # Владелец приостановил/отклонил этот класс сигналов.
            excluded.append({"row": row.get("id"), "reason": "signal_muted",
                             "signal": signal_hint})
            continue
        out.append(WindowObservation(
            send_message_id=send_msg,
            message_row_id=int(row.get("id") or 0),
            chat_id=chat_id,
            user_id=(int(row["user_id"]) if row.get("user_id") is not None
                     else None),
            ts=row_ts,
            reply_to_message_id=(int(row_reply)
                                 if row_reply is not None else None),
            markers=candidate_markers, confidence="low",
            signal="", provenance="linkage",
            reason="semantic_pending",
            text=str(row.get("text") or "")[:400]))
    return out, excluded


# ═══════════════════════════════════════════════════════════════════════════
# 3. Семантическая классификация (bounded; LLM зовёт джоба)
# ═══════════════════════════════════════════════════════════════════════════

#: Заводская редакция промпта классификатора (Factory Default; реестр
#: `experience.humor_window.system`).
HUMOR_WINDOW_SYSTEM_PROMPT = (
    "Ты классифицируешь реакцию чата на конкретную реплику бота. Верни "
    "ТОЛЬКО JSON-массив объектов, по одному на вход: "
    '{"i": <индекс>, "signal": "explicit_approval|metaphor_continuation|'
    'irritation|stop_request|wrong_addressee|fact_correction|unrelated|'
    'unknown", "confidence": "high|medium|low", "evidence": "<кратко, без '
    'цитат имён>", "subject_user_id": <id|0>, "addressee": "bot|other|'
    'unknown", "metaphor_continued": true|false}. '
    "Правила: ответ без семантической связи с репликой бота — unrelated; "
    "простое «ахах» без связи с приёмом — unknown; продолжение придуманного "
    "образа считать metaphor_continuation только при содержательном развитии; "
    "метафора не оценивается по совпадению слов. Не выдумывай данных."
)


def build_classify_user_prompt(observations: Sequence[Mapping[str, Any]],
                               *, send: Mapping[str, Any]) -> str:
    """bounded user-часть (≤BATCH_MAX_ROWS строк, тексты обрезаны)."""
    lines: list[str] = [
        "Реплика бота (техника, без текста): " + str(
            send.get("technique") or "none"),
    ]
    for index, obs in enumerate(list(observations)[:BATCH_MAX_ROWS]):
        text = str(obs.get("text") or "")[:400].replace("\n", " ")
        lines.append(f"[{index}] {text}")
    return "\n".join(lines)


def parse_classification(raw: Any,
                         observations: Sequence[Mapping[str, Any]]
                         ) -> list[dict]:
    """Строгий разбор ответа классификатора (fail-closed → unknown)."""
    if isinstance(raw, str):
        text = raw.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            raw = json.loads(text[start:end + 1])
        except Exception:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict] = []
    for index, item in enumerate(list(raw)[:BATCH_MAX_ROWS]):
        if not isinstance(item, Mapping):
            continue
        signal = str(item.get("signal") or "unknown")
        if signal not in SIGNALS:
            signal = "unknown"
        confidence = str(item.get("confidence") or "low")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"
        try:
            subject = int(item.get("subject_user_id") or 0)
        except (TypeError, ValueError):
            subject = 0
        if index >= len(observations):
            continue
        out.append({
            "i": index, "signal": signal, "confidence": confidence,
            "subject_user_id": subject or None,
            "addressee": str(item.get("addressee") or "unknown")[:16],
            "metaphor_continued": bool(item.get("metaphor_continued")),
            "evidence": str(item.get("evidence") or "")[:120],
            "classifier": CLASSIFIER_VERSION,
        })
    return out


def confidence_from(*, semantic: str, markers: Sequence[str],
                    authority_is_owner: bool) -> str:
    """Итоговая уверенность: семантика + evidence-маркеры + права автора."""
    if semantic == "unknown" or not semantic:
        return "low"
    if semantic in POSITIVE_SIGNALS:
        return "medium" if "marker_approval" in markers else "low"
    if authority_is_owner and any(m.startswith("marker_") for m in markers):
        return "high"
    return "medium" if markers else "low"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Консервативная оценка наблюдений (SOUL-08.9)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Observation:
    """Типизированное наблюдение уже ПОСЛЕ классификации."""

    chat_id: int
    technique: str
    signal: str
    ts: int
    send_ts: int
    send_message_id: int = 0
    user_id: int | None = None
    topic: str = ""
    confidence: str = "low"
    episode_id: str = ""
    authority_is_owner: bool = False
    reactions_distinct: int = 0
    reactions_repeated: int = 0


@dataclass(frozen=True)
class Hypothesis:
    """Гипотеза/вывод по приёму в КОНТЕКСТЕ чата (SOUL-08.9)."""

    chat_id: int
    technique: str
    direction: str               # weaken | strengthen
    observations: int = 0
    distinct_users: int = 0
    distinct_topics: int = 0
    weight: float = 0.0
    confirmed: bool = False
    guards: tuple[str, ...] = ()
    reason: str = ""
    evidence: tuple[str, ...] = ()
    #: Явное указание («перестань так писать» / просьба владельца) — это
    #: инструкция, а не статистический вывод: подтверждается правами, а не N.
    explicit: bool = False


def evaluate_observations(observations: Iterable[Observation], *,
                          min_observations: int = MIN_INDEPENDENT_OBSERVATIONS,
                          max_single_user_share: float = MAX_SINGLE_USER_SHARE,
                          window_seconds: int = WINDOW_SECONDS
                          ) -> list[Hypothesis]:
    """Консервативный вывод по группе наблюдений (чистая функция).

    Никогда не поднимает вероятность по одному наблюдению, по одному
    пользователю, по повторным реакциям одного лица, по активности вне окна
    или по сигналу раньше отправки (anti-reverse-causality).
    """
    groups: dict[tuple[int, str], list[Observation]] = {}
    for obs in observations or ():
        if str(obs.signal) not in SIGNALS:
            continue
        if str(obs.signal) == "unknown":
            continue
        groups.setdefault((int(obs.chat_id), str(obs.technique)),
                          []).append(obs)
    out: list[Hypothesis] = []
    for (chat_id, technique), items in sorted(groups.items()):
        guards: set[str] = set()
        # Классифицируем ПО СИГНАЛУ (что вообще наблюдали), затем отдельно
        # проверяем, тянет ли это обновление: так «зашумлённая» группа видна
        # как гипотеза с кодами защит, а не исчезает молча.
        positives = [o for o in items if o.signal in POSITIVE_SIGNALS]
        negatives = [o for o in items if o.signal in NEGATIVE_SIGNALS]
        worse: list[Observation] = []
        for obs in items:
            if int(obs.ts) <= int(obs.send_ts):
                guards.add("guard_reverse_causality")
                worse.append(obs)
            elif int(obs.ts) - int(obs.send_ts) > int(window_seconds):
                guards.add("guard_out_of_window")
                worse.append(obs)
            elif str(obs.confidence) == "low" and not obs.authority_is_owner:
                guards.add("guard_low_confidence")
                worse.append(obs)
            elif int(obs.reactions_distinct or 0) > MAX_REACTORS_PER_MESSAGE:
                guards.add("guard_brigading")
                worse.append(obs)
        dropped = {id(o) for o in worse}
        if not positives and not negatives:
            continue          # unknown/нет сигнала — не failure и не вывод
        direction = "strengthen" if len(positives) >= len(negatives) \
            else "weaken"
        chosen = positives if direction == "strengthen" else negatives
        usable = [o for o in chosen if id(o) not in dropped]
        episodes = {str(o.episode_id or o.send_message_id) for o in chosen}
        topics = {str(o.topic or "unknown") for o in chosen}
        users = {int(o.user_id) for o in chosen if o.user_id is not None}
        owner = any(o.authority_is_owner for o in chosen)
        if len(episodes) < int(min_observations):
            guards.add("guard_small_n")
        if len(topics) < 2:
            guards.add("guard_single_topic")
        if users:
            share = max(sum(1 for o in chosen
                            if o.user_id is not None
                            and int(o.user_id) == uid)
                        for uid in users) / max(1, len(chosen))
            if share > float(max_single_user_share) and not owner:
                guards.add("guard_single_user")
        # Engagement-gaming: вес не зависит от объёма переписки.
        weight = min(MAX_WEIGHT_PER_SEND,
                     sum(1.0 for _ in usable) / max(1, len(episodes)))
        # Явное указание (просьба прекратить/владелец) — инструкция, а не
        # статистика: применяется сразу, но остаётся обратимым и контекстным.
        explicit = any(o.signal == "stop_request" or o.authority_is_owner
                       for o in chosen) and direction == "weaken"
        if explicit:
            confirmed = True
            guards.discard("guard_small_n")
            guards.discard("guard_single_topic")
            guards.discard("guard_single_user")
            reason = "explicit_instruction"
        else:
            confirmed = bool(usable) and not guards
            reason = ("" if confirmed else (",".join(sorted(guards))
                                            or "insufficient"))
        out.append(Hypothesis(
            chat_id=chat_id, technique=technique, direction=direction,
            observations=len(chosen), distinct_users=len(users),
            distinct_topics=len(topics), weight=round(weight, 4),
            confirmed=confirmed, guards=tuple(sorted(guards)),
            reason=reason, evidence=tuple(sorted(episodes)),
            explicit=explicit))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 5. Применение: ослабление/усиление стратегии В КОНТЕКСТЕ (SOUL-08.10/11)
# ═══════════════════════════════════════════════════════════════════════════

#: Заводские тексты рекомендаций уроков живут в ЕДИНОМ каноне Experience
#: (`mca_experience.CANONICAL_RECOMMENDATIONS`): второго каталога текстов нет.
HUMOR_RULE_PREFIX = "humor_weaken_"
HUMOR_RULE_STRENGTHEN_PREFIX = "humor_strengthen_"


def humor_rule_key(technique: str, direction: str) -> str:
    prefix = (HUMOR_RULE_PREFIX if str(direction) == "weaken"
              else HUMOR_RULE_STRENGTHEN_PREFIX)
    return prefix + str(technique)


def rule_key_for(technique: str, direction: str) -> tuple[str, str]:
    """(type, rule_key) канонического урока для приёма и направления."""
    return ("social_preference", humor_rule_key(technique, direction))


def recommendation_for(technique: str, direction: str) -> str:
    """Канонический текст урока (или пусто — правило не зарегистрировано)."""
    try:
        from services import mca_experience as me
        entry = me.CANONICAL_RECOMMENDATIONS.get(
            rule_key_for(technique, direction))
        return str(entry or "")
    except Exception:                      # pragma: no cover
        return ""


def _technique_from_rule_key(rule_key: str) -> str:
    for prefix in (HUMOR_RULE_STRENGTHEN_PREFIX, HUMOR_RULE_PREFIX):
        if str(rule_key).startswith(prefix):
            return str(rule_key)[len(prefix):]
    return ""


def humor_lesson_map() -> dict[str, tuple[str, str]]:
    """Обратный индекс: канонический текст урока → (направление, приём)."""
    try:
        from services import mca_experience as me
        catalog = me.CANONICAL_RECOMMENDATIONS
    except Exception:                      # pragma: no cover
        return {}
    out: dict[str, tuple[str, str]] = {}
    for (lesson_type, rule_key), text in catalog.items():
        if str(lesson_type) != "social_preference":
            continue
        if rule_key.startswith(HUMOR_RULE_STRENGTHEN_PREFIX):
            direction = "strengthen"
        elif rule_key.startswith(HUMOR_RULE_PREFIX):
            direction = "weaken"
        else:
            continue
        technique = _technique_from_rule_key(rule_key)
        if technique:
            out[str(text)] = (direction, technique)
    return out

#: Ослабление в контексте (не глобальный запрет): пока предпочтение активно,
#: этот приём в ЭТОМ чате не применяется; с возрастом вес линейно
#: возвращается к 1.0 (decay), поэтому «ослабление» обратимо и не глобально.
WEAKEN_WEIGHT = 0.05
STRENGTHEN_WEIGHT = 1.0
#: Старение: штраф затухает за `DECAY_DAYS` без новых наблюдений.
DECAY_DAYS = 30


def rule_key_for(technique: str, direction: str) -> tuple[str, str]:
    """(type, rule_key) канонического урока для приёма и направления."""
    return ("social_preference", humor_rule_key(technique, direction))


def recommendation_for(technique: str, direction: str) -> str:
    """Канонический текст урока (или пусто — правило не зарегистрировано)."""
    try:
        from services import mca_experience as me
        entry = me.CANONICAL_RECOMMENDATIONS.get(
            rule_key_for(technique, direction))
        return str(entry or "")
    except Exception:                      # pragma: no cover
        return ""


def _technique_from_rule_key(rule_key: str) -> str:
    for prefix in (HUMOR_RULE_STRENGTHEN_PREFIX, HUMOR_RULE_PREFIX):
        if str(rule_key).startswith(prefix):
            return str(rule_key)[len(prefix):]
    return ""


def humor_lesson_map() -> dict[str, tuple[str, str]]:
    """Обратный индекс: канонический текст урока → (направление, приём)."""
    try:
        from services import mca_experience as me
        catalog = me.CANONICAL_RECOMMENDATIONS
    except Exception:                      # pragma: no cover
        return {}
    out: dict[str, tuple[str, str]] = {}
    for (lesson_type, rule_key), text in catalog.items():
        if str(lesson_type) != "social_preference":
            continue
        if rule_key.startswith(HUMOR_RULE_STRENGTHEN_PREFIX):
            direction = "strengthen"
        elif rule_key.startswith(HUMOR_RULE_PREFIX):
            direction = "weaken"
        else:
            continue
        technique = _technique_from_rule_key(rule_key)
        if technique:
            out[str(text)] = (direction, technique)
    return out


def decay_factor(last_observed_ts: int | float | None,
                 *, now_ts: int | float | None = None,
                 decay_days: int = DECAY_DAYS) -> float:
    """1.0 → свежее наблюдение; 0.0 → полностью устаревшее (SOUL-08.11)."""
    if not last_observed_ts:
        return 0.0
    age_days = max(0.0, (_now(now_ts) - float(last_observed_ts)) / 86400.0)
    if decay_days <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - age_days / float(decay_days)))


async def apply_hypothesis(db, hypothesis: Hypothesis, *,
                           episode_ids: Sequence[str] = ()) -> dict:
    """Гипотеза → урок Experience (propose → validate → activate).

    Никакой автоматической переписи Core: урок остаётся контекстным
    предпочтением чата (SOUL-08.9) и влияет только на выбор приёма/примеров.
    """
    if not gate_on():
        return {"applied": False, "reason": "humor_feedback_disabled"}
    if not hypothesis.confirmed:
        return {"applied": False, "reason": hypothesis.reason or "hypothesis",
                "guards": list(hypothesis.guards)}
    if not episode_ids:
        return {"applied": False, "reason": "no_episode_evidence"}
    lesson_type, rule_key = rule_key_for(hypothesis.technique,
                                         hypothesis.direction)
    recommendation = recommendation_for(hypothesis.technique,
                                        hypothesis.direction)
    if not recommendation:
        return {"applied": False, "reason": "no_canonical_rule"}
    try:
        from services import mca_experience as me
        lesson_service = _lesson_service(db)
        if lesson_service is None:
            return {"applied": False, "reason": "lesson_contour_unavailable"}
        proposed = await lesson_service.propose(
            type=lesson_type, scope="chat", rule_key=rule_key,
            scope_chat_id=int(hypothesis.chat_id),
            applicability="humor_technique_context",
            episode_ids=tuple(episode_ids))
        if proposed is None:
            return {"applied": False, "reason": "proposal_rejected"}
        lesson_id, version = proposed
        evidence = me.ValidationEvidence(
            kind=("humor_instruction" if hypothesis.explicit
                  else "generalization"),
            permission_granted=bool(hypothesis.explicit),
            conflict_free=True,
            independent_episode_ids=tuple(episode_ids))
        validated = await lesson_service.validate(lesson_id, version,
                                                  evidence=evidence)
        if not validated:
            return {"applied": False, "reason": "validation_failed",
                    "lesson_id": lesson_id}
        activated = await lesson_service.activate(lesson_id, version)
        _emit("humor_lesson_updated",
              outcome="success" if activated else "failed",
              chat_id=int(hypothesis.chat_id),
              reason_code=("activated" if activated else "activation_failed"),
              technique=hypothesis.technique, direction=hypothesis.direction,
              observations=hypothesis.observations,
              lesson_id=lesson_id)
        return {"applied": bool(activated), "lesson_id": lesson_id,
                "version": version, "direction": hypothesis.direction,
                "reason": "activated" if activated else "activation_failed"}
    except Exception:
        logger.warning("[humor-feedback] lesson apply failed", exc_info=True)
        return {"applied": False, "reason": "error"}


def _lesson_service(db):
    try:
        from services import mca_experience as me
        store = me.ExperienceStore(db)
        return me.LessonService(db, store)
    except Exception:
        logger.warning("[humor-feedback] lesson service unavailable",
                       exc_info=True)
        return None


async def _humor_lessons(db, chat_id: int) -> list[dict]:
    """Активные/валидированные уроки юмора ЭТОГО чата (per-chat изоляция)."""
    if not gate_on():
        return []
    mapping = humor_lesson_map()
    if not mapping:
        return []
    try:
        from services import mca_experience as me
        service = me.get_service(db)
        rows = await service.list_lessons(chat_id=int(chat_id),
                                          statuses=("active", "validated"),
                                          limit=100)
    except Exception:
        logger.warning("[humor-feedback] lessons read failed", exc_info=True)
        return []
    out: list[dict] = []
    for row in rows:
        entry = mapping.get(str(row.get("recommendation") or ""))
        if entry is None:
            continue
        direction, technique = entry
        if str(row.get("scope")) != "chat":
            continue
        if row.get("scope_chat_id") is not None \
                and int(row.get("scope_chat_id")) != int(chat_id):
            continue
        out.append({"direction": direction, "technique": technique,
                    "lesson_id": row.get("lesson_id"),
                    "version": row.get("version"),
                    "status": row.get("status"),
                    "updated_at": row.get("updated_at")})
    return out


async def strategy_weight(db, chat_id: int, technique: str, *,
                          now_ts: int | float | None = None) -> float:
    """Вес приёма в этом чате (1.0 — базовый, ≤0.05 — приём не выбирается)."""
    if not gate_on():
        return 1.0
    weight = 1.0
    for lesson in await _humor_lessons(db, chat_id):
        if str(lesson.get("technique")) != str(technique):
            continue
        decay = decay_factor(lesson.get("updated_at"), now_ts=now_ts)
        if str(lesson.get("direction")) == "weaken":
            # Старение возвращает приём к базовому весу (SOUL-08.11).
            weakened = WEAKEN_WEIGHT + (1.0 - decay) * (1.0 - WEAKEN_WEIGHT)
            weight = min(weight, round(weakened, 4))
        else:
            weight = max(weight, STRENGTHEN_WEIGHT)
    return round(float(weight), 4)


async def sample_penalties(db, chat_id: int) -> dict:
    """Штрафы для отбора примеров (ослабленные приёмы — реже)."""
    if not gate_on():
        return {}
    penalties: dict[str, float] = {}
    for lesson in await _humor_lessons(db, chat_id):
        if str(lesson.get("direction")) != "weaken":
            continue
        decay = decay_factor(lesson.get("updated_at"))
        if decay <= 0.0:
            continue
        penalties[f"technique:{lesson.get('technique')}"] = round(
            0.5 * decay, 4)
    return penalties


# ═══════════════════════════════════════════════════════════════════════════
# 6. Управление владельцем: pause / reset / approve / reject (SOUL-08.11)
# ═══════════════════════════════════════════════════════════════════════════


async def set_paused(db, chat_id: int, paused: bool) -> dict:
    """Пауза сбора сигналов для чата (данные не удаляются)."""
    if not gate_on():
        return {"ok": False, "reason": "humor_feedback_disabled"}
    try:
        from services import chat_params
        root = await chat_params.get_all_chat_params(int(chat_id))
        overrides = dict((root or {}).get("overrides") or {})
        doc = dict(overrides.get("humor.feedback") or {})
        doc["paused"] = bool(paused)
        doc["updated_at"] = _now()
        overrides["humor.feedback"] = doc
        await chat_params.set_chat_params(int(chat_id), {"overrides": overrides})
        return {"ok": True, "paused": bool(paused)}
    except Exception:
        logger.warning("[humor-feedback] pause write failed", exc_info=True)
        return {"ok": False, "reason": "write_error"}


async def is_paused(db, chat_id: int) -> bool:
    try:
        from services import chat_params
        root = await chat_params.get_all_chat_params(int(chat_id))
        doc = (root or {}).get("overrides", {}).get("humor.feedback") or {}
        return bool(doc.get("paused"))
    except Exception:
        return False


async def lesson_action(db, chat_id: int, lesson_id: str, *,
                        version: int | None = None, action: str) -> dict:
    """approve (activate) / reject (suspend) / pause контекстного предпочтения."""
    if not gate_on():
        return {"ok": False, "reason": "humor_feedback_disabled"}
    service = _lesson_service(db)
    if service is None:
        return {"ok": False, "reason": "lesson_contour_unavailable"}
    try:
        if action == "approve":
            if version is not None:
                await service.validate(lesson_id, version)
            ok = await service.activate(lesson_id, version)
        elif action in ("reject", "pause"):
            ok = await service.suspend(lesson_id, reason_code="owner_" + action,
                                       version=version)
        else:
            return {"ok": False, "reason": "unknown_action"}
        _emit("humor_lesson_owner_action",
              outcome="success" if ok else "failed",
              chat_id=int(chat_id), reason_code=action, lesson_id=lesson_id)
        return {"ok": bool(ok), "action": action}
    except Exception:
        logger.warning("[humor-feedback] lesson action failed", exc_info=True)
        return {"ok": False, "reason": "error"}


async def reset_learning(db, chat_id: int) -> dict:
    """Сброс обучения юмора в чате: предпочтения выключаются, данные целы.

    Базовые данные Experience (эпизоды/feedback/уроки) НЕ удаляются: уроки
    приостанавливаются, а документ-предпочтение помечается сброшенным.
    """
    if not gate_on():
        return {"ok": False, "reason": "humor_feedback_disabled"}
    suspended = 0
    try:
        lessons = await _humor_lessons(db, chat_id)
        service = _lesson_service(db)
        for lesson in lessons:
            if service is None:
                break
            ok = await service.suspend(lesson_id=str(lesson.get("lesson_id")),
                                       reason_code="owner_reset_learning",
                                       version=int(lesson.get("version") or 0)
                                       or None)
            suspended += 1 if ok else 0
    except Exception:
        logger.warning("[humor-feedback] reset suspend failed", exc_info=True)
    try:
        from services import chat_params
        root = await chat_params.get_all_chat_params(int(chat_id))
        overrides = dict((root or {}).get("overrides") or {})
        doc = dict(overrides.get("humor.feedback") or {})
        doc["reset_at"] = _now()
        doc["pending_hypotheses"] = []
        overrides["humor.feedback"] = doc
        await chat_params.set_chat_params(int(chat_id), {"overrides": overrides})
    except Exception:
        logger.warning("[humor-feedback] reset doc write failed", exc_info=True)
    _emit("humor_learning_reset", outcome="success", chat_id=int(chat_id),
          reason_code="owner_reset_learning", suspended=suspended)
    return {"ok": True, "suspended": suspended,
            "note": ("Предпочтения остановлены; эпизоды, сигналы и уроки "
                     "сохранены и видны в «Обучении».")}


# ═══════════════════════════════════════════════════════════════════════════
# 7. Видимая телеметрия (SOUL-08.11/14) — без сырых текстов
# ═══════════════════════════════════════════════════════════════════════════


async def telemetry(db, *, chat_id: int | None = None,
                    limit: int = 200) -> dict:
    """Счётчики сигналов/гипотез/влияний (honest zero-состояния)."""
    out: dict[str, Any] = {
        "available": False, "reason": "", "sends": 0, "signals": {},
        "confidence": {}, "unknown_windows": 0, "hypotheses": [],
        "lessons": [], "paused": False, "policy": POLICY_VERSION,
        "classifier": CLASSIFIER_VERSION, "no_data_note": (
            "Отсутствие реакций — не провал: такие окна остаются unknown."),
    }
    if not gate_on():
        out["reason"] = "humor_feedback_disabled"
        return out
    if db is None or not hasattr(db, "db"):
        out["reason"] = "db_unavailable"
        return out
    try:
        chat_filter = "" if chat_id is None else " AND chat_id = ?"
        args: tuple = (int(chat_id),) if chat_id is not None else ()
        cursor = await db.db.execute(
            "SELECT feedback_id, source_kind, authority, signal_json, ts, "
            "chat_id FROM mca_experience_feedback"
            + ("" if chat_id is None else " WHERE chat_id = ?")
            + " ORDER BY ts DESC LIMIT ?",
            (args + (int(limit),)) if args else (int(limit),))
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        logger.warning("[humor-feedback] telemetry read failed", exc_info=True)
        out["reason"] = "read_error"
        return out
    out["available"] = True
    for row in rows:
        try:
            signal = json.loads(str(row.get("signal_json") or "{}"))
        except Exception:
            signal = {}
        if str(signal.get("domain") or "") != "humor":
            continue
        kind = str(signal.get("signal") or "")
        if not kind:
            continue
        out["signals"][kind] = out["signals"].get(kind, 0) + 1
        confidence = str(signal.get("confidence") or "low")
        out["confidence"][confidence] = out["confidence"].get(confidence, 0) + 1
        if kind == "unknown":
            out["unknown_windows"] += 1
    try:
        cursor = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_experience_episodes WHERE "
            "task_type = ?" + chat_filter, (SEND_TASK_TYPE,) + args)
        row = await cursor.fetchone()
        out["sends"] = int(row["c"] or 0) if row is not None else 0
    except Exception:
        logger.warning("[humor-feedback] sends count failed", exc_info=True)
        out["sends"] = 0
    if chat_id is not None:
        out["lessons"] = [
            {"lesson_id": lesson.get("lesson_id"),
             "technique": lesson.get("technique"),
             "direction": lesson.get("direction"),
             "status": lesson.get("status"),
             "updated_at": lesson.get("updated_at"),
             "decay": round(decay_factor(lesson.get("updated_at")), 3)}
            for lesson in await _humor_lessons(db, int(chat_id))
        ]
        out["paused"] = await is_paused(db, int(chat_id))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 8. Обязательные сценарии SOUL-08.12 — честные live-маркеры
# ═══════════════════════════════════════════════════════════════════════════

#: Что именно проверяется живой канарейкой (2–3 строки на сценарий).
SCENARIO_LIVE_MARKERS: dict[str, str] = {
    "metaphor_picked_up": (
        "Дет.: подхват бюрократической метафоры в реальном чате.\n"
        "Сим.: дедуп/окно/вес стратегии.\n"
        "Live: нужен настоящий собеседник, продолжающий образ в ветке."),
    "stop_request": (
        "Дет.: просьба не повторять грубость ослабляет приём в контексте.\n"
        "Сим.: owner-confirmed сигнал → цель weaken.\n"
        "Live: нужен реальный участник, просящий прекратить."),
    "dramatic_reaction_no_joke": (
        "Дет.: бурная реакция на спор без шутки НЕ считается успехом.\n"
        "Сим.: нет сигнала шутки → unknown.\n"
        "Live: нужен реальный спор без комического приёма."),
    "nobody_comments": (
        "Дет.: отсутствие ответа — unknown, не провал.\n"
        "Сим.: пустое окно → unknown_windows.\n"
        "Live: наблюдение 24–48 ч на реальной тишине."),
    "group_talks_elsewhere": (
        "Дет.: активность группы без reply на бота — не успех.\n"
        "Сим.: no_linkage → исключение из кандидатов.\n"
        "Live: нужен реальный чат с параллельной темой."),
    "two_chats_differ": (
        "Дет.: одна шутка в двух чатах оценивается по-разному.\n"
        "Сим.: lessons per-chat изоляция.\n"
        "Live: нужны два живых чата с разной реакцией."),
    "brigading_one_person": (
        "Дет.: несколько реакций одного лица не накручивают успех.\n"
        "Сим.: guard_single_user/guard_brigading.\n"
        "Live: нужны реальные повторные реакции."),
}


def scenario_marker(name: str) -> str:
    return str(SCENARIO_LIVE_MARKERS.get(str(name), ""))


def scenario_summary() -> list[dict]:
    return [{"id": key, "live_marker": value}
            for key, value in sorted(SCENARIO_LIVE_MARKERS.items())]


# ═══════════════════════════════════════════════════════════════════════════
# 9. Вспомогательные: сигнал-документ для Experience feedback
# ═══════════════════════════════════════════════════════════════════════════


def signal_payload(*, signal: str, technique: str, confidence: str,
                   send_message_id: int, evidence: str = "",
                   markers: Sequence[str] = (), authority_is_owner: bool = False,
                   library_version: str = ""
                   ) -> dict:
    """Типизированный signal для `record_feedback` (R17: без текста)."""
    payload: dict[str, Any] = {
        "domain": "humor",
        "signal": str(signal),
        "technique": str(technique or "none")[:32],
        "confidence": str(confidence or "low")[:8],
        "send_msg": int(send_message_id or 0),
        "policy": POLICY_VERSION,
        "classifier": CLASSIFIER_VERSION,
        "authority": "owner" if authority_is_owner else "participant",
    }
    if markers:
        payload["markers"] = [str(m)[:32] for m in list(markers)[:6]]
    if library_version:
        payload["library_version"] = str(library_version)[:32]
    if evidence:
        payload["evidence_sha"] = hashlib.sha256(
            str(evidence).encode("utf-8")).hexdigest()[:12]
    return payload


# ═══════════════════════════════════════════════════════════════════════════
# 10. Проход окна внутри СУЩЕСТВУЮЩЕГО review-джоба опыта (SOUL-08.0/08.8)
# ═══════════════════════════════════════════════════════════════════════════


def _task_type_send() -> str:
    return SEND_TASK_TYPE


async def _open_sends(db, *, now: int, limit: int) -> list[dict]:
    """Отправки, чьё окно ещё актуально (bounded, только типизированные поля)."""
    cursor = await db.db.execute(
        "SELECT episode_id, chat_id, decision_json, created_at, output_ref "
        "FROM mca_experience_episodes WHERE task_type = ? "
        "AND created_at >= ? ORDER BY created_at DESC LIMIT ?",
        (_task_type_send(), int(now) - 2 * WINDOW_SECONDS, int(limit)))
    rows = [dict(r) for r in await cursor.fetchall()]
    out: list[dict] = []
    for row in rows:
        try:
            decision = json.loads(str(row.get("decision_json") or "{}"))
        except Exception:
            decision = {}
        message_id = int(decision.get("msg") or 0)
        if not message_id or not row.get("chat_id"):
            continue
        out.append({
            "episode_id": str(row.get("episode_id")),
            "chat_id": int(row["chat_id"]),
            "message_id": message_id,
            "ts": int(row.get("created_at") or 0),
            "technique": str(decision.get("technique") or "none"),
            "strategy": str(decision.get("strategy") or "none"),
            "library_version": "",
        })
    return out


async def _window_rows(db, *, chat_id: int, after_ts: int,
                       limit: int) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT id, chat_id, user_id, text, timestamp, reply_to_id "
        "FROM smart_messages WHERE chat_id = ? AND timestamp > ? "
        "ORDER BY id LIMIT ?",
        (int(chat_id), int(after_ts), int(limit)))
    return [dict(r) for r in await cursor.fetchall()]


def source_kind_for(signal: str, *, authority_is_owner: bool) -> str:
    """Класс feedback для сигнала юмора (совместим с v28-констрейнтом).

    Слабые семантические реакции → ``social_reaction`` (participant/weak);
    явные указания («перестань так писать», коррекция адресата/факта) →
    коррекция автора. Вид сигнала остаётся в типизированном ``signal_json``.
    """
    signal = str(signal or "unknown")
    if signal in ("stop_request", "wrong_addressee", "fact_correction"):
        return "owner_correction" if authority_is_owner \
            else "participant_correction"
    if authority_is_owner and signal in NEGATIVE_SIGNALS:
        return "owner_correction"
    return "social_reaction"


def _owner_marker_signal(markers: Sequence[str]) -> str:
    """Сигнал по маркеру владельца (его явная просьба авторитетна)."""
    codes = set(str(m) for m in (markers or ()))
    if "marker_stop_request" in codes:
        return "stop_request"
    if "marker_wrong_addressee" in codes:
        return "wrong_addressee"
    if "marker_fact_correction" in codes:
        return "fact_correction"
    if "marker_irritation" in codes:
        return "irritation"
    return "unknown"


def resolve_signal(*, semantic: str, markers: Sequence[str],
                   confidence: str, authority_is_owner: bool) -> str:
    """Итоговый класс сигнала: семантика + маркеры + права автора.

    Положительные сигналы (они повышают вероятность приёма) требуют
    семантического подтверждения — детерминированных фраз для этого мало
    (SOUL-08.8). Отрицательные маркеры без семантики остаются сигналом с
    низкой уверенностью: они фиксируются как evidence, но не тянут обновление
    в одиночку (guard_low_confidence в `evaluate_observations`).
    """
    semantic = str(semantic or "unknown")
    codes = set(str(m) for m in (markers or ()))
    if semantic in SIGNALS and semantic != "unknown":
        return semantic
    if not codes:
        return "unknown"
    negative = _owner_marker_signal(markers)
    if negative != "unknown":
        if authority_is_owner or str(confidence) in ("high", "medium"):
            return negative
        return "unknown"
    return "unknown"


def topic_bucket(text: str, *, buckets: int = 64) -> str:
    """Грубая тема для anti-single-topic (bounded, без сохранения текста)."""
    tokens = sorted(t for t in _TOKEN_RE_FEEDBACK.findall(str(text or "").casefold())
                    if len(t) >= 4)[:4]
    if not tokens:
        return "unknown"
    material = "|".join(tokens)
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return "topic_" + str(int.from_bytes(digest[:2], "big") % max(2, buckets))


async def _close_unknown(db, *, send: Mapping[str, Any], service,
                         reason: str = "no_signal_in_window") -> bool:
    """Окно без сигнала → `unknown` (НЕ failure, SOUL-08.6)."""
    try:
        await service.record_outcome(str(send.get("episode_id")),
                                     outcome_kind="unknown",
                                     outcome_source="social")
        feedback_id = await service.record_feedback(
            source_kind="social_reaction", chat_id=int(send.get("chat_id") or 0),
            ref_type="humor_window", ref_id=int(send.get("message_id") or 0),
            episode_id=str(send.get("episode_id")),
            ts=int(send.get("ts") or 0) + WINDOW_SECONDS,
            signal=signal_payload(
                signal="unknown", technique=str(send.get("technique") or "none"),
                confidence="low",
                send_message_id=int(send.get("message_id") or 0),
                evidence=reason))
        return bool(feedback_id)
    except Exception:
        logger.warning("[humor-feedback] window close failed", exc_info=True)
        return False


async def run_window_pass(db, *, llm=None, limit_sends: int = 3,
                          classify_budget: int = BATCH_MAX_ROWS) -> dict:
    """Один bounded проход контура (вызывается существующим джобом опыта).

    Делает: классификацию окна (семантика/LLM, один вызов на проход),
    durable запись сигналов, закрытие окон без сигнала как `unknown`,
    консервативное обновление предпочтений (уроки Experience).
    Никогда не бросает: сбой прохода оставляет беседу нетронутой.
    """
    counters = {
        "humor_sends_scanned": 0, "humor_signals": 0, "humor_unknown": 0,
        "humor_windows_closed": 0, "humor_lessons_applied": 0,
        "humor_hypotheses": 0, "humor_skipped_disabled": 0,
        "humor_evaluator_unavailable": 0, "humor_write_failures": 0,
    }
    if not gate_on():
        counters["humor_skipped_disabled"] = 1
        return counters
    if db is None or not hasattr(db, "db"):
        return counters
    now = _now()
    try:
        from services import mca_experience as me
        service = me.get_service(db)
    except Exception:
        logger.warning("[humor-feedback] experience unavailable", exc_info=True)
        return counters
    try:
        sends = await _open_sends(db, now=now, limit=int(limit_sends))
    except Exception:
        logger.warning("[humor-feedback] sends read failed", exc_info=True)
        return counters
    observations: list[Observation] = []
    for send in sends:
        counters["humor_sends_scanned"] += 1
        try:
            if await is_paused(db, send["chat_id"]):
                continue
        except Exception:
            pass
        try:
            rows = await _window_rows(db, chat_id=send["chat_id"],
                                      after_ts=send["ts"],
                                      limit=BATCH_MAX_ROWS * 2)
        except Exception:
            logger.warning("[humor-feedback] window read failed", exc_info=True)
            counters["humor_write_failures"] += 1
            continue
        candidates, _excluded = window_candidates(send=send, rows=rows,
                                                  now_ts=now)
        window_closed = (now - int(send["ts"])) >= WINDOW_SECONDS
        if not candidates:
            if window_closed and await _close_unknown(db, send=send,
                                                      service=service):
                counters["humor_windows_closed"] += 1
                counters["humor_unknown"] += 1
            continue
        verdicts = await classify_rows(candidates[:classify_budget], send=send,
                                       llm=llm)
        if verdicts is None:
            counters["humor_evaluator_unavailable"] += 1
            if window_closed and await _close_unknown(
                    db, send=send, service=service,
                    reason="evaluator_unavailable"):
                counters["humor_windows_closed"] += 1
                counters["humor_unknown"] += 1
            continue
        for obs, verdict in verdicts:
            semantic = str(verdict.get("signal") or "unknown")
            try:
                authority_owner = await _is_owner(obs.user_id)
            except Exception:
                authority_owner = False
            signal = resolve_signal(semantic=semantic, markers=obs.markers,
                                    confidence=str(verdict.get("confidence")
                                                   or "low"),
                                    authority_is_owner=authority_owner)
            if signal in OWNER_CONFIRMABLE and authority_owner and obs.markers \
                    and semantic == "unknown":
                signal = _owner_marker_signal(obs.markers)
            try:
                feedback_id = await service.record_feedback(
                    source_kind=source_kind_for(
                        signal, authority_is_owner=authority_owner),
                    chat_id=int(obs.chat_id),
                    ref_type="humor_send", ref_id=int(obs.message_row_id),
                    episode_id=str(send.get("episode_id")),
                    ts=int(obs.ts),
                    signal=signal_payload(
                        signal=signal,
                        technique=str(send.get("technique") or "none"),
                        confidence=str(verdict.get("confidence") or "low"),
                        send_message_id=int(obs.send_message_id),
                        evidence=str(verdict.get("evidence") or ""),
                        markers=list(obs.markers),
                        authority_is_owner=authority_owner))
            except Exception:
                counters["humor_write_failures"] += 1
                logger.warning("[humor-feedback] feedback write failed",
                               exc_info=True)
                continue
            if not feedback_id:
                continue
            if signal == "unknown":
                counters["humor_unknown"] += 1
                continue
            counters["humor_signals"] += 1
            confidence = confidence_from(
                semantic=signal, markers=list(obs.markers),
                authority_is_owner=authority_owner)
            observations.append(Observation(
                chat_id=int(obs.chat_id),
                technique=str(send.get("technique") or "none"),
                signal=signal, ts=int(obs.ts), send_ts=int(send["ts"]),
                send_message_id=int(obs.send_message_id),
                user_id=obs.user_id, topic=topic_bucket(obs.text),
                confidence=confidence,
                episode_id=str(send.get("episode_id")),
                authority_is_owner=authority_owner,
                reactions_distinct=1))
    if observations:
        hypotheses = evaluate_observations(observations)
        counters["humor_hypotheses"] = len(hypotheses)
        for hypothesis in hypotheses:
            if not hypothesis.confirmed:
                _emit("humor_hypothesis_pending", outcome="unknown",
                      chat_id=int(hypothesis.chat_id),
                      reason_code=hypothesis.reason,
                      technique=hypothesis.technique,
                      observations=hypothesis.observations)
                continue
            result = await apply_hypothesis(db, hypothesis,
                                            episode_ids=hypothesis.evidence)
            if result.get("applied"):
                counters["humor_lessons_applied"] += 1
    return counters


async def _is_owner(user_id: Any) -> bool:
    try:
        from config.settings import settings
        return (user_id is not None
                and int(user_id) == int(settings.ADMIN_USER_ID))
    except Exception:
        return False


async def classify_rows(candidates: Sequence[WindowObservation], *,
                        send: Mapping[str, Any], llm=None
                        ) -> list[tuple[WindowObservation, dict]] | None:
    """Семантическая классификация кандидатов (bounded; None → недоступность).

    Детерминированные маркеры НЕ являются единственной основой: они едут
    evidence-кодом, класс определяет семантика (SOUL-08.8).
    """
    items = list(candidates or ())[:BATCH_MAX_ROWS]
    if not items:
        return []
    if llm is None:
        # Оценщик недоступен: окно закрывается честным unknown (беседа не
        # блокируется); маркерные сигналы не выдумываются.
        return None
    try:
        import asyncio as _asyncio
        import uuid as _uuid
        messages = [
            {"role": "system", "content": HUMOR_WINDOW_SYSTEM_PROMPT},
            {"role": "user", "content": build_classify_user_prompt(
                [{"text": row.text} for row in items], send=send)},
        ]
        raw = await _asyncio.wait_for(
            llm.generate(messages, temperature=0.1, module="humor",
                         step="humor_window_classify",
                         correlation_id=_uuid.uuid4().hex[:16],
                         max_output_tokens=BATCH_MAX_TOKENS),
            timeout=BATCH_TIMEOUT_S)
    except Exception:
        logger.warning("[humor-feedback] classifier call failed", exc_info=True)
        return None
    parsed = parse_classification(raw, items)
    if not parsed:
        return None
    out: list[tuple[WindowObservation, dict]] = []
    for verdict in parsed:
        index = int(verdict.get("i") or 0)
        if index >= len(items):
            continue
        out.append((items[index], verdict))
    return out
