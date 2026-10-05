"""mca-10b (`mca-10b-random-applications`, ADR-1028-17 D1–D9, spec §1–§7) —
тонкий контракт применений случайности + фасад над политикой 10a.

Границы (вторые механизмы запрещены; GEN-R3/R19):
  * контракт: dataclasses `ExplorationRequest`/`ExplorationResult` +
    lifecycle/purpose-константы; ЕДИНСТВЕННЫЙ источник draw — политика/
    источник mca-10a (`RandomSourceService.choose`/`draw_index`/
    `draw_probability`), второй RandomSource/координатор/очередь не
    создаются; отдельной таблицы Request/Result НЕТ (журнал — `mca_events`,
    durable-состояние фоновых jobs — `task_jobs` mca-01, conversation-исходы
    — read-only `random_metadata` v22);
  * retrieval — ТОЛЬКО через `retrieve()` (L-MCA07-5); второй комбинированный
    поиск запрещён; прямой запрос истории — обычный поиск (`direct_request`
    — недопустимое измерение, `INELIGIBLE_MEASUREMENTS` 10a);
  * «выбор ≠ вердикт»: случайность выбирает материал/форму/период/объект/
    пару — не истину/вердикт/адресата/факты;
  * результаты фоновых исследований → память/очередь кандидатов инициативы
    (`mca_intents`), НЕ Telegram (единственный транспорт — координатор);
  * «выбор ≠ публикация»: `selected` — ещё не отправлено; lifecycle
    `candidate→selected→checking→accepted/rejected/deferred/failed` +
    финал `used_in_reply|stored_only|not_used`;
  * рекурсия exploration→exploration запрещена: фоновый hook вызывается
    ТОЛЬКО по завершении обычного пакета сна; exploration-job не считается
    пакетом и новых лотерей не запускает; рестарт не повторяет job
    (unique coalesce-ключ `(chat_id, package_run_id, type)` в `task_jobs`);
  * R17: в событиях/журнале только ID/коды/числа/refs — без сырого текста/
    секретов/CoT;
  * OFF-паритет: `MCA_RANDOM_USES_ENABLED=false` или `random.uses.X=false`
    → путь не выполняется, поведение 2.58.60 бит-в-бит, честный
    `disabled`/`not_run`.

`ui_replay` — НЕ purpose: маркер read-only-режима витрины (повтор показывает
записанное, новых чисел не запрашивает). `ui_visualization` — настройка
`random.uses.*`, не purpose.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from config.settings import settings
from services import mca_events, mca_gates

logger = logging.getLogger(__name__)

# ── контракт §14.5 (D1/D2) ──────────────────────────────────────────────────

POLICY_VERSION_10B = "mca10b-v1"

# Purposes — ровно санкционированное расширение закрытого набора 10a
# (ADR-1028-17 D2/AM-1); карта purpose→probability — ОДНА, в доме 10a
# (`mca_random_source.EXPLORATION_PROBABILITY_KEYS`), здесь не форкуется.
PURPOSE_CONVERSATION_VARIANT = "conversation_variant"
PURPOSE_MEMORY_RECALL = "memory_recall"
PURPOSE_ARCHIVE_SAMPLE = "archive_sample"
PURPOSE_BELIEF_REVIEW = "belief_review"
PURPOSE_ASSOCIATION_PAIR = "association_pair"
PURPOSES_10B = frozenset({
    PURPOSE_CONVERSATION_VARIANT, PURPOSE_MEMORY_RECALL,
    PURPOSE_ARCHIVE_SAMPLE, PURPOSE_BELIEF_REVIEW,
    PURPOSE_ASSOCIATION_PAIR,
})

# `ui_replay` — read-only-маркер витрины (НЕ purpose; `choose()` отвергает
# его как неизвестный purpose — существующая проверка 10a).
UI_REPLAY_MARKER = "ui_replay"

# Настройки-разрешения применений (`random.uses.*`, §12/D13; pg-ключи в
# существующей группе `memory_random`; каталог +6 — блок E, рантайм читает
# через существующий read-path с fail-open дефолтом True). Игровой stub
# §14.12 в список НЕ входит.
USE_CONVERSATION_VARIANT = "conversation_variant"
USE_MEMORY_RECALL = "memory_recall"
USE_ARCHIVE_SAMPLE = "archive_sample"
USE_BELIEF_REVIEW = "belief_review"
USE_ASSOCIATION_PAIR = "association_pair"
USE_UI_VISUALIZATION = "ui_visualization"
USES = frozenset({
    USE_CONVERSATION_VARIANT, USE_MEMORY_RECALL, USE_ARCHIVE_SAMPLE,
    USE_BELIEF_REVIEW, USE_ASSOCIATION_PAIR, USE_UI_VISUALIZATION,
})
USE_SETTING_KEYS = {use: f"memory.random_uses_{use}" for use in USES}

# Lifecycle (D5): selected ≠ истина/публикация; повторную выборку после
# неудачного варианта не крутить (primary или молчание + причина).
LIFE_CANDIDATE = "candidate"
LIFE_SELECTED = "selected"
LIFE_CHECKING = "checking"
LIFE_ACCEPTED = "accepted"
LIFE_REJECTED = "rejected"
LIFE_DEFERRED = "deferred"
LIFE_FAILED = "failed"
LIFECYCLE_STAGES = frozenset({
    LIFE_CANDIDATE, LIFE_SELECTED, LIFE_CHECKING, LIFE_ACCEPTED,
    LIFE_REJECTED, LIFE_DEFERRED, LIFE_FAILED,
})
FINAL_USED_IN_REPLY = "used_in_reply"
FINAL_STORED_ONLY = "stored_only"
FINAL_NOT_USED = "not_used"
FINAL_OUTCOMES = frozenset({FINAL_USED_IN_REPLY, FINAL_STORED_ONLY,
                            FINAL_NOT_USED})

# Исходы ExplorationResult (контрактные, не reason-коды).
OUTCOME_EXPLORED = "explored"
OUTCOME_PRIMARY = "primary"
OUTCOME_NO_ALTERNATIVE = "no_eligible_alternative"
OUTCOME_DISABLED = "disabled"
OUTCOME_NOT_RUN = "not_run"
OUTCOME_DEFERRED = "deferred"


@dataclass(frozen=True)
class ExplorationRequest:
    """Запрос применения случайности (spec §1; R17-safe: ID/коды/числа)."""

    operation_id: str
    chat_id: int
    purpose: str
    context_version: str | None = None
    candidate_ids: tuple = ()
    candidate_versions: dict = field(default_factory=dict)
    primary_id: str | None = None
    eligible_ids: tuple = ()
    excluded: tuple = ()          # ((candidate_id, reason_code), …)
    probability: float | None = None
    policy_version: str = POLICY_VERSION_10B
    requested_source: str | None = None
    measurement: str | None = None
    replay: bool = False          # `ui_replay`: только чтение записанного


@dataclass(frozen=True)
class ExplorationResult:
    """Результат применения (spec §1; выбор ≠ публикация)."""

    request: ExplorationRequest
    selected: Any = None
    actual_source: str | None = None
    draw_ids: tuple = ()
    fallback_reason: str | None = None
    explanation: str | None = None
    outcome: str = OUTCOME_NOT_RUN
    lifecycle: str = LIFE_CANDIDATE
    final_outcome: str | None = None   # used_in_reply|stored_only|not_used
    deferred: bool = False

    def to_random_metadata(self) -> dict | None:
        """Read-only копия для `CoordinatorDecision.random_metadata` (v22;
        закрытые ключи — существующая санитизация mca-09)."""
        from services.direct_chat_service import _sanitize_random_metadata
        return _sanitize_random_metadata({
            "policy_version": self.request.policy_version,
            "requested_source": self.request.requested_source,
            "actual_source": self.actual_source,
            "draw_ids": list(self.draw_ids),
            "probability": self.request.probability,
            "fallback_reason": self.fallback_reason,
            "deferred": self.deferred,
        })


# ── журнал (единый emit_mca_event; notable-only; R17-safe) ──────────────────

def _emit(event_name: str, *, outcome: str, level: str = mca_events.LEVEL_INFO,
          reason_code: str | None = None, stage: str | None = None,
          **fields) -> None:
    try:
        mca_events.emit_mca_event(
            event_name, outcome=outcome, level=level, component="random",
            reason_code=reason_code, stage=stage, **fields)
    except Exception:      # pragma: no cover - fail-open
        return


def _short(value, limit: int = 64) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def journal_exploration(result: ExplorationResult, *,
                        pipeline_run_id: str | None = None) -> None:
    """Одное notable-событие применения (кандидаты/выбор/причины —
    entity_ids; воспроизводимо вместе с draw-журналом 10a)."""
    req = result.request
    entity = {
        "operation_id": _short(req.operation_id),
        "purpose": _short(req.purpose),
        "policy_version": _short(req.policy_version),
        "primary": _short(req.primary_id),
        "eligible": [_short(c) for c in req.eligible_ids][:50],
        "outcome": result.outcome,
        "selected": _short(getattr(result.selected, "candidate_id",
                                   result.selected) if result.selected
                           is not None else None),
    }
    form = getattr(result.selected, "intent", None) if result.selected \
        is not None else None
    if form:
        # Форма участия (T-5059/D10): выбранная форма видна в раскрытии
        # (R17-safe: enum-имя, без сырого текста).
        entity["form"] = _short(form, 32)
    if result.actual_source:
        # D11: метка фактического источника (ANU/PRNG) для витрины.
        entity["actual_source"] = _short(result.actual_source, 32)
    if req.candidate_versions:
        entity["versions"] = {str(k)[:64]: int(v) for k, v in
                              list(req.candidate_versions.items())[:50]
                              if isinstance(v, int)}
    if req.excluded:
        entity["excluded"] = [[_short(cid), _short(rc, 48)]
                              for cid, rc in req.excluded[:50]]
    if req.context_version:
        entity["context_version"] = _short(req.context_version, 120)
    _emit("random_uses",
          outcome=(mca_events.OUTCOME_SILENT
                   if result.outcome in (OUTCOME_DISABLED, OUTCOME_NOT_RUN,
                                         OUTCOME_NO_ALTERNATIVE,
                                         OUTCOME_DEFERRED)
                   else mca_events.OUTCOME_SUCCESS),
          level=(mca_events.LEVEL_WARN
                 if result.outcome in (OUTCOME_DISABLED, OUTCOME_DEFERRED)
                 else mca_events.LEVEL_INFO),
          reason_code=_reason_for(result), stage=_short(req.purpose, 48),
          chat_id=int(req.chat_id),
          pipeline_run_id=pipeline_run_id, entity_ids=entity)


def _reason_for(result: ExplorationResult) -> str | None:
    if result.outcome == OUTCOME_DISABLED:
        return "disabled"
    if result.outcome == OUTCOME_NO_ALTERNATIVE:
        return "no_eligible_alternative"
    if result.outcome == OUTCOME_DEFERRED:
        return "random_fallback"
    if result.outcome == OUTCOME_NOT_RUN:
        return "exploration_not_used"
    return None


# ── разрешения применений (T-5054; D13) ─────────────────────────────────────

async def _read_use_setting(key: str, chat_id, default):
    """Единственный read-path настроек (`worker_settings.resolve_setting`);
    fail-open: ошибка → дефолт. Каталог (блок E) регистрирует те же ключи —
    рантайм не меняется."""
    try:
        from services.worker_settings import resolve_setting
        return await resolve_setting(key, chat_id=chat_id, default=default)
    except Exception:
        return default


async def use_enabled(db, use: str, chat_id=None) -> bool:
    """Разрешение применения `random.uses.X` (per-chat override — chat_params;
    выключение одного не ломает остальные, R5e)."""
    if use not in USES:
        return False
    raw = await _read_use_setting(USE_SETTING_KEYS[use], chat_id, True)
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "on", "yes", "да")
    return bool(raw)


def master_enabled() -> bool:
    """Master kill-switch `MCA_RANDOM_USES_ENABLED` (env-only, default ON)."""
    return mca_gates.random_uses_enabled()


async def exploration_allowed(db, purpose: str, chat_id=None) -> tuple[bool,
                                                                       str | None]:
    """Эффективное разрешение = master AND `random.uses.<purpose>` AND
    существующие K1/K4 (probability-ветки). Возвращает (allowed, причина)."""
    if not master_enabled():
        return False, "disabled"
    if str(purpose or "") not in PURPOSES_10B:
        # `ui_replay`/`ui_visualization` и прочие неизвестные — не purposes.
        return False, "no_eligible_alternative"
    if not await use_enabled(db, str(purpose), chat_id):
        return False, "disabled"
    if not (mca_gates.random_source_enabled()
            and mca_gates.random_exploration_enabled()):
        return False, "disabled"
    return True, None


def reset_delivery_pendings() -> None:
    """Очистить реестр `delivery_unknown` (тесты/смена чата)."""
    _DELIVERY_UNKNOWN.clear()


# ── источник draw (один — 10a; DI для тестов) ───────────────────────────────

def get_source(db=None):
    """Единственный источник случайности (10a reuse; без второго сервиса)."""
    from services import mca_random_source
    return mca_random_source.get_service(db)


# ── T-5052: один выбор в разговоре (D3) ─────────────────────────────────────

def _candidate_id(item) -> str:
    return str(getattr(item, "candidate_id", None) or id(item))


def _candidate_version(item) -> int | None:
    value = getattr(item, "candidate_version", None)
    return int(value) if isinstance(value, int) else None


def _is_story_candidate(item) -> bool:
    """Memory-история (§4): кандидат с эпизодными refs (episode:<id>)."""
    for ref in tuple(getattr(item, "source_refs", ()) or ()):
        if str(ref).startswith("episode:"):
            return True
    return bool(tuple(getattr(item, "episode_ids", ()) or ()))


async def choose_conversation_alternative(db, *, chat_id: int,
                                          operation_id: str = "",
                                          primary=None, pool=(),
                                          context_version: str | None = None,
                                          requested_source: str | None = None,
                                          source=None):
    """РОВНО одна probability-проверка на conversation operation (A29/D3).

    Общий пул целостных альтернативных кандидатов (варианты из памяти +
    формы участия; LLM ради набора не вызывается — только уже найденные
    материалы). При успехе — ровно один альтернативный кандидат; если это
    memory-история — один дополнительный РАВНОМЕРНЫЙ draw среди одинаково
    допустимых историй (purpose=`memory_recall`; draw корректной выборки,
    НЕ вторая probability-проверка и не «перекрутка»).

    Возвращает `(choice | None, ExplorationResult)`; `choice=None` →
    вызывающий идёт по primary-пути как в 2.58.60 (OFF/пустой пул —
    нормальный исход без draw). Уместность/проверка перед отправкой —
    у потребителя, политика их не подменяет."""
    allowed, reason = await exploration_allowed(
        db, PURPOSE_CONVERSATION_VARIANT, chat_id)
    # T-5061 (D12): сквозной trace run на operation (fail-open; OFF → None).
    # Master OFF → НИКАКИХ событий/trace (бит-в-бит 2.58.60).
    pipeline_run_id = (await trace_start(db, chat_id=int(chat_id))
                       if master_enabled() else None)
    alternatives = [c for c in (pool or ())
                    if primary is None or not _same(c, primary)]
    admissible = [c for c in alternatives if getattr(c, "admissible", True)]
    excluded = tuple(
        (_candidate_id(c),
         (tuple(getattr(c, "reason_codes", ()) or ()) or
          ("no_eligible_alternative",))[0])
        for c in alternatives if not getattr(c, "admissible", True))
    request = ExplorationRequest(
        operation_id=_short(operation_id) or uuid.uuid4().hex[:16],
        chat_id=int(chat_id), purpose=PURPOSE_CONVERSATION_VARIANT,
        context_version=_short(context_version, 120),
        candidate_ids=tuple(_candidate_id(c) for c in alternatives),
        candidate_versions={_candidate_id(c): _candidate_version(c)
                            for c in alternatives
                            if _candidate_version(c) is not None},
        primary_id=_short(_candidate_id(primary)) if primary is not None
        else None,
        eligible_ids=tuple(_candidate_id(c) for c in admissible),
        excluded=excluded, policy_version=POLICY_VERSION_10B,
        requested_source=_short(requested_source, 120))
    if not allowed:
        result = ExplorationResult(
            request=request, selected=primary, outcome=OUTCOME_DISABLED,
            explanation=reason)
        if master_enabled():
            # per-use OFF или K1/K4 OFF — честное событие (без draw).
            journal_exploration(result, pipeline_run_id=pipeline_run_id)
        await trace_finish(db, pipeline_run_id, outcome="succeeded",
                           reason_code="disabled")
        return None, result
    if not admissible:
        # Пустой пул → primary + `no_eligible_alternative`, БЕЗ draw (§3.4).
        result = ExplorationResult(
            request=request, selected=primary,
            outcome=OUTCOME_NO_ALTERNATIVE,
            explanation="empty_pool")
        journal_exploration(result, pipeline_run_id=pipeline_run_id)
        await trace_finish(db, pipeline_run_id, outcome="succeeded",
                           reason_code="no_eligible_alternative")
        return None, result
    src = source or get_source(db)
    choose_kwargs: dict = dict(chat_id=chat_id,
                               purpose=PURPOSE_CONVERSATION_VARIANT,
                               policy_version=POLICY_VERSION_10B)
    if _choose_supports_requested(src):
        choose_kwargs["requested_source"] = requested_source
    policy_choice = await src.choose(primary, admissible, **choose_kwargs)
    selected = policy_choice.selected
    draw_ids = tuple(policy_choice.draw_ids or ())
    outcome = (OUTCOME_EXPLORED if policy_choice.explored
               else (OUTCOME_DISABLED
                     if policy_choice.reason == "disabled"
                     else (OUTCOME_DEFERRED if policy_choice.deferred
                           else OUTCOME_PRIMARY)))
    if policy_choice.explored and selected is not None and \
            _is_story_candidate(selected):
        # Один дополнительный draw равномерного выбора среди одинаково
        # допустимых историй (purpose=memory_recall); n=1 расхода нет.
        stories = [c for c in admissible if _is_story_candidate(c)]
        if len(stories) > 1:
            recall_draw = await src.draw_index(
                len(stories), chat_id=chat_id,
                purpose=PURPOSE_MEMORY_RECALL,
                policy_version=POLICY_VERSION_10B,
                candidates=[_candidate_id(c) for c in stories])
            if recall_draw is not None and not recall_draw.deferred and \
                    recall_draw.index is not None:
                idx = max(0, min(int(recall_draw.index), len(stories) - 1))
                selected = stories[idx]
                if recall_draw.draw_id:
                    draw_ids = draw_ids + (recall_draw.draw_id,)
            elif recall_draw is not None and recall_draw.deferred:
                # Честный отказ draw → выбранный политикой кандидат
                # сохраняется; повторную выборку не крутим (D5).
                pass
    result = ExplorationResult(
        request=request, selected=selected,
        actual_source=policy_choice.source, draw_ids=draw_ids,
        fallback_reason=policy_choice.fallback_reason,
        explanation=policy_choice.reason, outcome=outcome,
        lifecycle=(LIFE_SELECTED if policy_choice.explored
                   else LIFE_CANDIDATE),
        deferred=bool(policy_choice.deferred))
    journal_exploration(result, pipeline_run_id=pipeline_run_id)
    await trace_finish(
        db, pipeline_run_id,
        outcome=("succeeded" if outcome in (OUTCOME_EXPLORED, OUTCOME_PRIMARY)
                 else "partial"),
        reason_code=(policy_choice.reason or None))
    return policy_choice, result


def _choose_supports_requested(source) -> bool:
    import inspect
    try:
        return "requested_source" in inspect.signature(
            source.choose).parameters
    except (TypeError, ValueError):      # pragma: no cover
        return False


def _same(a, b) -> bool:
    """Дешёвое сравнение кандидатов: явные candidate_id совпадают → один
    кандидат; иначе identity (прецедент 10a `_same_candidate`)."""
    if a is b:
        return True
    if a is None or b is None:
        return False
    id_a, id_b = _candidate_id(a), _candidate_id(b)
    explicit = hasattr(a, "candidate_id") and hasattr(b, "candidate_id")
    return explicit and id_a == id_b


# ── T-5053: одно фоновое направление + lifecycle (D4/D5) ────────────────────

# Уникальный ключ job (THR-3): `(chat_id, package_run_id, type)`; partial
# UNIQUE-индекс coalesce_key v14 — рестарт не дублирует.
def exploration_job_key(chat_id: int, package_run_id: str, job_type: str
                        ) -> str:
    return (f"exploration:{int(chat_id)}:"
            f"{_short(package_run_id, 48) or 'run'}:{str(job_type)}")


EXPLORATION_JOB_KIND_PREFIX = "exploration."


@dataclass
class BackgroundTypeSpec:
    """Спецификация фонового типа (реестр; тип равномерно из ДОСТУПНЫХ;
    недоступные — с причиной `exploration_type_unavailable`)."""

    use: str
    available: Callable            # async (db) -> bool
    select_and_enqueue: Callable   # async (db, source, *, package_run_id) -> dict


def exploration_job_kind(job_type: str) -> str:
    """Отдельный kind — основной archive worker его НИКОГДА не выбирает
    (FIFO-приоритет основного прохода by construction, A31/R7d)."""
    return EXPLORATION_JOB_KIND_PREFIX + str(job_type)


def background_types() -> dict:
    """Реестр типов (лениво; T-5057/T-5058 регистрируют свои доступность/
    выбор-и-постановку тем же контрактом — вторых механизмов не появляется)."""
    global _BACKGROUND_TYPES
    if _BACKGROUND_TYPES is None:
        _BACKGROUND_TYPES = {
            PURPOSE_ARCHIVE_SAMPLE: BackgroundTypeSpec(
                use=USE_ARCHIVE_SAMPLE,
                available=_archive_sample_available,
                select_and_enqueue=_archive_sample_select_and_enqueue),
            PURPOSE_BELIEF_REVIEW: BackgroundTypeSpec(
                use=USE_BELIEF_REVIEW,
                available=_belief_review_available,
                select_and_enqueue=_belief_review_select_and_enqueue),
            PURPOSE_ASSOCIATION_PAIR: BackgroundTypeSpec(
                use=USE_ASSOCIATION_PAIR,
                available=_association_pair_available,
                select_and_enqueue=_association_pair_select_and_enqueue),
        }
    return _BACKGROUND_TYPES


_BACKGROUND_TYPES: dict | None = None


async def after_sleep_direction(db, *, package_run_id: str = "",
                                source=None, memory=None) -> dict:
    """Точка «одного выбора направления» после обычного пакета сна (D4).

    МАКСИМУМ 1 доп. job: доступные типы (разрешение + доступность контура) →
    одна probability-проверка существующей точки `sleep_exploration_probability`
    (purpose `sleep_after_consolidation` — существующий purpose существующего
    ключа, новых чисел нет) → равномерный draw типа → постановка ОДНОГО job
    с уникальным ключом. Недоступные типы — с причиной
    `exploration_type_unavailable`. Завершение job не запускает новую
    лотерею (hook вызывается только здесь, из завершения обычного сна)."""
    src = source or get_source(db)
    run_id = _short(package_run_id, 48) or uuid.uuid4().hex[:16]
    entity: dict = {"package_run_id": run_id}
    if not master_enabled():
        return {"status": "disabled"}
    # T-5061 (D12): сквозной run направления/выбора (fail-open; OFF → None).
    pipeline_run_id = await trace_start(db)
    entity["pipeline_run_id"] = pipeline_run_id
    types = background_types()
    available: list[str] = []
    unavailable: list[str] = []
    for name, spec in types.items():
        if not await use_enabled(db, spec.use):
            continue          # per-use разрешение OFF — тип вне пула (R5e)
        try:
            ok = bool(await spec.available(db))
        except Exception:
            logger.warning("[mca10b] availability check failed | type=%s",
                           name, exc_info=True)
            ok = False
        if ok:
            available.append(name)
        else:
            unavailable.append(name)
    entity["available"] = sorted(available)
    entity["unavailable"] = sorted(unavailable)
    if unavailable:
        # Недоступные — с честной причиной (не молчаливый пропуск).
        _emit("random_uses_background", outcome=mca_events.OUTCOME_SKIPPED,
              reason_code="exploration_type_unavailable", stage="direction",
              pipeline_run_id=pipeline_run_id, entity_ids=entity)
    if not available:
        if not unavailable:
            await trace_finish(db, pipeline_run_id, outcome="succeeded",
                               reason_code="exploration_not_used")
            return {"status": "not_run", "reason": "no_types"}
        await trace_finish(db, pipeline_run_id, outcome="succeeded",
                           reason_code="exploration_type_unavailable")
        return {"status": "not_run", "reason": "exploration_type_unavailable",
                "unavailable": sorted(unavailable)}
    # Активный exploration-job того же прогона → не дублируем (рестарт).
    if await _active_exploration_job(db, run_id):
        return {"status": "coalesced"}
    # Одна probability-проверка существующей после-сонной точки.
    probability = await _sleep_probability()
    prob_draw = await src.draw_probability(
        purpose="sleep_after_consolidation",
        policy_version=POLICY_VERSION_10B, probability=probability)
    if prob_draw is None or prob_draw.deferred or prob_draw.value is None:
        await trace_finish(db, pipeline_run_id, outcome="partial",
                           reason_code="random_fallback")
        return {"status": "deferred",
                "reason": (prob_draw.reason if prob_draw is not None
                           else "provider_unavailable")}
    entity["probability"] = probability
    if float(prob_draw.value) >= probability:
        # Порог не пройден — обычный исход без job.
        _emit("random_uses_background", outcome=mca_events.OUTCOME_SKIPPED,
              reason_code="exploration_not_used", stage="direction",
              pipeline_run_id=pipeline_run_id, entity_ids=entity)
        await trace_finish(db, pipeline_run_id, outcome="succeeded",
                           reason_code="exploration_not_used")
        return {"status": "not_run", "reason": "probability_miss"}
    if prob_draw.draw_id:
        entity["probability_draw_id"] = _short(prob_draw.draw_id)
    type_draw = await src.draw_index(
        len(available), purpose="sleep_after_consolidation",
        policy_version=POLICY_VERSION_10B,
        candidates=sorted(available))
    if type_draw is None or type_draw.deferred or type_draw.index is None:
        await trace_finish(db, pipeline_run_id, outcome="partial",
                           reason_code="random_fallback")
        return {"status": "deferred",
                "reason": (type_draw.reason if type_draw is not None
                           else "provider_unavailable")}
    job_type = sorted(available)[max(0, int(type_draw.index))]
    entity["type"] = job_type
    if type_draw.draw_id:
        entity["type_draw_id"] = _short(type_draw.draw_id)
    spec = types[job_type]
    try:
        outcome = await spec.select_and_enqueue(db, src, package_run_id=run_id,
                                                memory=memory)
    except Exception:
        logger.warning("[mca10b] select_and_enqueue failed | type=%s",
                       job_type, exc_info=True)
        _emit("random_uses_background", outcome=mca_events.OUTCOME_FAILED,
              reason_code="exploration_failed", stage="direction",
              pipeline_run_id=pipeline_run_id, entity_ids=entity)
        await trace_finish(db, pipeline_run_id, outcome="failed",
                           reason_code="exploration_failed")
        return {"status": "failed", "type": job_type}
    entity.update({k: v for k, v in (outcome or {}).items()
                   if isinstance(v, (str, int, float, bool))})
    # Rework F-1 (reviewer): честный исход постановки — ветвление по
    # статусу выбора. selected → accepted/enqueued; not_run/deferred →
    # skipped с конкретной причиной (причина выбора остаётся в entity),
    # БЕЗ перезаписи в enqueued; trace_finish на КАЖДОМ пути (§11/§14.5:
    # showcase показывает реальный исход, run не остаётся running/stalled).
    selection_status = str((outcome or {}).get("status") or "")
    if selection_status == "selected":
        _emit("random_uses_background", outcome=mca_events.OUTCOME_SUCCESS,
              reason_code="exploration_accepted", stage="direction",
              pipeline_run_id=pipeline_run_id, entity_ids=entity)
        await trace_finish(db, pipeline_run_id, outcome="succeeded",
                           reason_code="exploration_accepted")
        merged = dict(outcome or {})
        merged.update({"status": "enqueued", "type": job_type,
                       "pipeline_run_id": pipeline_run_id})
        return merged
    if selection_status == "deferred":
        _emit("random_uses_background", outcome=mca_events.OUTCOME_SKIPPED,
              reason_code="exploration_deferred", stage="direction",
              pipeline_run_id=pipeline_run_id, entity_ids=entity)
        await trace_finish(db, pipeline_run_id, outcome="partial",
                           reason_code="exploration_deferred")
        merged = dict(outcome or {})
        merged.update({"type": job_type,
                       "pipeline_run_id": pipeline_run_id})
        return merged
    # not_run / неизвестный статус — честный пропуск (job не ставился).
    _emit("random_uses_background", outcome=mca_events.OUTCOME_SKIPPED,
          reason_code="exploration_not_used", stage="direction",
          pipeline_run_id=pipeline_run_id, entity_ids=entity)
    await trace_finish(db, pipeline_run_id, outcome="succeeded",
                       reason_code="exploration_not_used")
    merged = dict(outcome or {})
    merged.update({"type": job_type, "pipeline_run_id": pipeline_run_id})
    return merged


async def _sleep_probability() -> float:
    """Порог существующей после-сонной точки (`memory.random_sleep_
    exploration_probability`; read-path 10a, fail-open 0.05)."""
    from services import mca_random_source
    return await mca_random_source.get_service().exploration_probability(
        "sleep_after_consolidation")


async def _active_exploration_job(db, package_run_id: str) -> dict | None:
    cursor = await db.db.execute(
        "SELECT job_id, kind, coalesce_key FROM task_jobs WHERE "
        "kind LIKE 'exploration.%' AND status IN ('queued','running') AND "
        "coalesce_key LIKE ? LIMIT 1",
        (f"%:{_short(package_run_id, 48) or ''}:%",))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def record_lifecycle(db, job_id: str, *, stage: str, reason_code: str,
                           entity: dict | None = None,
                           pipeline_run_id: str | None = None) -> None:
    """Переход lifecycle → единое событие (D5; `selected` ≠ публикация)."""
    _emit("random_uses_lifecycle",
          outcome=(mca_events.OUTCOME_SUCCESS if stage in (LIFE_ACCEPTED,)
                   else (mca_events.OUTCOME_FAILED
                         if stage in (LIFE_FAILED, LIFE_REJECTED)
                         else mca_events.OUTCOME_SILENT)),
          level=(mca_events.LEVEL_WARN if stage in (LIFE_FAILED,
                                                    LIFE_DEFERRED)
                 else mca_events.LEVEL_INFO),
          reason_code=reason_code, stage=_short(stage, 48),
          job_id=_short(job_id, 64),
          pipeline_run_id=pipeline_run_id,
          entity_ids=entity or {})


# ── T-5056: archive_sample (D7) — существующий resumable worker ─────────────

COVERAGE_PERIOD_MONTHS = "YYYY-MM"     # стартовое разбиение (spec §5)
_ARCHIVE_PERIODS_MAX = 240             # bounded (2M строк → ≤240 месяцев)
_ARCHIVE_EPISODES_SCAN_CAP = 2000      # bounded скан message_keys
_ARCHIVE_RANGE_MESSAGES_MAX = 400      # поддиапазон одного job (bounded)
_FULLY_COVERED_SHARE = 0.999           # «всё покрыто»


def _period_of(ts: int) -> str:
    return time.strftime("%Y-%m", time.gmtime(int(ts or 0)))


async def _archive_sample_available(db) -> bool:
    """Доступность контура: существующий archive-контур (smart_messages) с
    непустыми периодами хотя бы одного чата-кандидата. Ошибка → False."""
    try:
        cursor = await db.db.execute(
            "SELECT 1 FROM smart_messages WHERE chat_id IS NOT NULL LIMIT 1")
        return await cursor.fetchone() is not None
    except Exception:
        return False


async def compute_chat_coverage(db, chat_id: int) -> list[dict]:
    """Карта покрытия чата по календарным месяцам (bounded; «нет истории» ≠
    «не обработано»): msgs_total — сообщения периода; verified_unique —
    уникальные message-ключи периода, покрытые эпизодами; episodes — число
    эпизодов периода. Без random OFFSET (keyset/агрегаты)."""
    cursor = await db.db.execute(
        "SELECT CAST(strftime('%Y-%m', timestamp, 'unixepoch') AS TEXT) AS p, "
        "COUNT(*) AS n, MIN(id) AS min_id, MAX(id) AS max_id "
        "FROM smart_messages WHERE chat_id = ? GROUP BY p ORDER BY p "
        "LIMIT ?", (int(chat_id), _ARCHIVE_PERIODS_MAX))
    rows = [dict(r) for r in await cursor.fetchall()]
    covered: dict[str, set] = {}
    episode_counts: dict[str, int] = {}
    cursor = await db.db.execute(
        "SELECT event_start_ts, message_keys_json FROM mca_episodes "
        "WHERE chat_id = ? LIMIT ?",
        (int(chat_id), _ARCHIVE_EPISODES_SCAN_CAP))
    for row in await cursor.fetchall():
        keys_raw = row["message_keys_json"] or "[]"
        try:
            keys = json.loads(keys_raw)
        except (ValueError, TypeError):
            keys = []
        period = _period_of(row["event_start_ts"]
                            or row["discovered_at"] or 0)
        bucket = covered.setdefault(period, set())
        for key in keys if isinstance(keys, list) else []:
            if key:
                bucket.add(str(key))
        episode_counts[period] = episode_counts.get(period, 0) + 1
    coverage: list[dict] = []
    for row in rows:
        period = str(row.get("p") or "")
        total = int(row.get("n") or 0)
        if total <= 0:
            continue
        unique_covered = len(covered.get(period, ()))
        coverage.append({
            "chat_id": int(chat_id), "period": period,
            "msgs_total": total,
            "verified_unique": min(unique_covered, total),
            "episodes": int(episode_counts.get(period, 0)),
            "min_id": int(row.get("min_id") or 0),
            "max_id": int(row.get("max_id") or 0),
            "share": (min(unique_covered, total) / total) if total else 0.0,
        })
    return coverage


async def merge_coverage(db, chat_id: int, period: str, *, msgs_total: int,
                         verified_unique: int, episodes: int,
                         extractor_version: str = "") -> None:
    """Покрытие ОБЪЕДИНЯЕТСЯ (upsert без затирания большего значения)."""
    now = int(time.time())

    async def _body(conn):
        await conn.execute(
            "INSERT INTO mca_archive_coverage (chat_id, period, msgs_total, "
            "verified_unique, episodes, last_explored_at, extractor_version, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(chat_id, period) "
            "DO UPDATE SET msgs_total = excluded.msgs_total, "
            "verified_unique = MAX(mca_archive_coverage.verified_unique, "
            "excluded.verified_unique), episodes = "
            "MAX(mca_archive_coverage.episodes, excluded.episodes), "
            "last_explored_at = excluded.last_explored_at, "
            "extractor_version = excluded.extractor_version, "
            "updated_at = excluded.updated_at",
            (int(chat_id), str(period), int(msgs_total),
             int(verified_unique), int(episodes), now,
             str(extractor_version or ""), now))
        return 1

    await db.write_transaction(_body, op_name="mca10b_coverage_merge")


async def select_archive_sample(db, source, *, package_run_id: str = "",
                                chat_ids=(), extractor_version: str = "") \
        -> dict:
    """Выбор материала archive_sample (D7): непустые периоды → нижняя группа
    по доле `verified_unique/msgs_total` → РАВНОМЕРНЫЙ draw периода
    (purpose=`archive_sample`) → непроверенный поддиапазон ПО СТАБИЛЬНЫМ ID
    (первый непокрытый блок; random OFFSET по всей таблице ЗАПРЕЩЁН),
    исключая диапазоны, занятые активными jobs. «Всё покрыто» → job только
    по причине пересмотра/новой версии экстрактора."""
    run_id = _short(package_run_id, 48) or uuid.uuid4().hex[:16]
    periods: list[dict] = []
    for chat_id in (chat_ids or ()):
        try:
            periods.extend(await compute_chat_coverage(db, int(chat_id)))
        except Exception:
            logger.warning("[mca10b] coverage failed | chat=%s", chat_id,
                           exc_info=True)
    if not periods:
        return {"status": "not_run", "reason": "no_periods"}
    min_share = min(p["share"] for p in periods)
    if min_share >= _FULLY_COVERED_SHARE:
        # «Всё покрыто» — дополнительное изучение только по установленной
        # причине (пересмотр/новая версия экстрактора); без причины job не
        # создаётся и draw НЕ расходуется (THR-13; §5/D7).
        if not extractor_version or not await _any_version_differs(
                db, periods, extractor_version):
            return {"status": "not_run", "reason": "fully_covered"}
    lowest = [p for p in periods if p["share"] <= min_share + 1e-9]
    draw = await source.draw_index(
        len(lowest), purpose=PURPOSE_ARCHIVE_SAMPLE,
        policy_version=POLICY_VERSION_10B,
        candidates=[f"{p['chat_id']}:{p['period']}" for p in lowest])
    if draw is None or draw.deferred or draw.index is None:
        return {"status": "deferred",
                "reason": (draw.reason if draw is not None
                           else "provider_unavailable")}
    pick = lowest[max(0, int(draw.index))]
    rng = await _uncovered_range(db, pick["chat_id"], pick["period"],
                                 pick["min_id"], pick["max_id"],
                                 extractor_version=str(extractor_version or ""))
    if rng is None:
        # Весь период занят/покрыт эпизодами в ID-пространстве — честный
        # пропуск (пустой результат отмечает диапазон проверенным — R7c —
        # на этапе исполнения).
        return {"status": "not_run", "reason": "range_occupied",
                "period": pick["period"]}
    id_from, id_to = rng
    return {"status": "selected", "chat_id": pick["chat_id"],
            "period": pick["period"], "id_from": id_from, "id_to": id_to,
            "coverage": {k: pick[k] for k in ("msgs_total", "verified_unique",
                                              "episodes", "share")},
            "draw_id": draw.draw_id, "package_run_id": run_id,
            "reason": "lowest_coverage", "additional_research": True,
            "extractor_version": str(extractor_version or "")}


async def _any_version_differs(db, periods, extractor_version: str) -> bool:
    """Причина «пересмотр/новая версия»: хотя бы один период выполнен
    версией, отличной от запрошенной (bounded по чатам)."""
    chat_ids = list({int(p["chat_id"]) for p in periods})[:8]
    for chat_id in chat_ids:
        cursor = await db.db.execute(
            "SELECT DISTINCT extraction_version FROM mca_episodes "
            "WHERE chat_id = ? LIMIT ?", (chat_id, _ARCHIVE_PERIODS_MAX))
        for row in await cursor.fetchall():
            if str(row["extraction_version"] or "") != \
                    str(extractor_version):
                return True
    return False


async def _extractor_version_changed(db, chat_id: int, period: str,
                                     extractor_version: str) -> bool:
    """Причина «пересмотр/новая версия» для одного периода: запрошенная
    версия отличается от версий, ФАКТИЧЕСКИ выполнивших период (эпизоды
    периода и/или карта покрытия). Совместимая версия причины не создаёт."""
    cursor = await db.db.execute(
        "SELECT DISTINCT extraction_version FROM mca_episodes "
        "WHERE chat_id = ? AND CAST(strftime('%Y-%m', event_start_ts, "
        "'unixepoch') AS TEXT) = ? LIMIT ?",
        (int(chat_id), str(period), _ARCHIVE_PERIODS_MAX))
    versions = {str(r["extraction_version"] or "") for r in
                await cursor.fetchall()}
    if versions and str(extractor_version) not in versions:
        return True
    cursor = await db.db.execute(
        "SELECT extractor_version FROM mca_archive_coverage "
        "WHERE chat_id = ? AND period = ?", (int(chat_id), str(period)))
    row = await cursor.fetchone()
    if row is not None and str(row["extractor_version"] or "") != \
            str(extractor_version):
        return True
    return False


async def _uncovered_range(db, chat_id: int, period: str, min_id: int,
                           max_id: int,
                           extractor_version: str = "") -> tuple[int, int] | None:
    """Непроверенный поддиапазон по стабильным ID: первый блок сообщений
    периода, не покрытый эпизодами СОВМЕСТИМОЙ версии экстрактора (пропуск —
    только подтверждённо выполненных совместимой версией участков, §5/D7;
    новая версия экстрактора → покрытое переисследуется). Random OFFSET не
    используется; диапазоны, занятые АКТИВНЫМИ jobs ТОГО ЖЕ чата,
    исключаются (coalesce/unique v14); чужие чаты не блокируют."""
    cursor = await db.db.execute(
        "SELECT job_id FROM task_jobs WHERE kind LIKE 'exploration.%' "
        "AND status IN ('queued','running') AND coalesce_key LIKE ? "
        "LIMIT 1", (f"exploration:{int(chat_id)}:%",))
    if await cursor.fetchone() is not None:
        return None          # чат занят активным exploration-job
    cursor = await db.db.execute(
        "SELECT id, timestamp FROM smart_messages WHERE chat_id = ? AND id >= ? "
        "AND id <= ? ORDER BY id ASC LIMIT ?",
        (int(chat_id), int(min_id), int(max_id),
         _ARCHIVE_RANGE_MESSAGES_MAX))
    rows = [dict(r) for r in await cursor.fetchall()]
    if not rows:
        return None
    covered = await _covered_message_keys(db, chat_id,
                                          extractor_version=extractor_version)
    for row in rows:
        key = f"{int(chat_id)}:{int(row['id'])}"
        if key not in covered:
            return int(row["id"]), int(rows[-1]["id"])
    return None


async def _covered_message_keys(db, chat_id: int,
                                extractor_version: str = "") -> set:
    """Ключи сообщений, покрытые эпизодами СОВМЕСТИМОЙ версии (пустая
    запрошенная версия → совместимо всё — поведение совместимости)."""
    cursor = await db.db.execute(
        "SELECT message_keys_json, extraction_version FROM mca_episodes "
        "WHERE chat_id = ? LIMIT ?",
        (int(chat_id), _ARCHIVE_EPISODES_SCAN_CAP))
    keys: set = set()
    for row in await cursor.fetchall():
        if str(extractor_version or "") and \
                str(row["extraction_version"] or "") != \
                str(extractor_version):
            continue          # выполнено другой версией — НЕ пропуск
        try:
            raw = json.loads(row["message_keys_json"] or "[]")
        except (ValueError, TypeError):
            continue
        for key in raw if isinstance(raw, list) else []:
            if key:
                keys.add(str(key))
    return keys


async def _archive_sample_select_and_enqueue(db, source, *,
                                             package_run_id: str = "",
                                             memory=None) -> dict:
    """Выбор периода/диапазона + постановка ОДНОГО durable job (уникальный
    ключ `(chat_id, package_run_id, type)` — рестарт не дублирует, THR-3).
    Metadata: причина/диапазон/покрытие/флаг «дополнительное исследование».
    Основной cursor НЕ двигается: job — отдельный kind со своим checkpoint."""
    from services.task_supervisor import TaskJobStore
    run_id = _short(package_run_id, 48) or uuid.uuid4().hex[:16]
    # Рестарт/повтор вызова с тем же прогоном → существующий активный job
    # (coalesce/unique v14), новой лотереи/selection нет.
    existing = await _active_job_for_run(db, run_id,
                                         PURPOSE_ARCHIVE_SAMPLE)
    if existing is not None:
        return {"status": "selected", "job_id": existing, "reused": True,
                "package_run_id": run_id}
    chats = await _candidate_chat_ids(db)
    selection = await select_archive_sample(
        db, source, package_run_id=run_id, chat_ids=chats,
        extractor_version="")
    if selection.get("status") != "selected":
        return selection
    chat_id = int(selection["chat_id"])
    store = TaskJobStore(db)
    payload = json.dumps({
        "type": PURPOSE_ARCHIVE_SAMPLE,
        "chat_id": chat_id,
        "period": selection["period"],
        "id_from": int(selection["id_from"]),
        "id_to": int(selection["id_to"]),
        "coverage": selection.get("coverage") or {},
        "reason": selection.get("reason") or "lowest_coverage",
        "additional_research": True,
        "extractor_version": selection.get("extractor_version") or "",
        "package_run_id": selection.get("package_run_id") or "",
        "draw_id": selection.get("draw_id") or "",
        "cursor_id": 0,
        "counters": {"processed": 0, "episodes": 0, "empty_scans": 0},
    }, ensure_ascii=False)
    job_id = await store.enqueue(
        owner="random.uses",
        kind=exploration_job_kind(PURPOSE_ARCHIVE_SAMPLE),
        coalesce_key=exploration_job_key(
            chat_id, selection.get("package_run_id") or "",
            PURPOSE_ARCHIVE_SAMPLE),
        payload=payload, max_attempts=1)
    return {"status": "selected", "job_id": job_id,
            "period": selection["period"],
            "range": [selection["id_from"], selection["id_to"]],
            "chat_id": chat_id}


async def _active_job_for_run(db, package_run_id: str, job_type: str) -> str | None:
    """Активный (queued/running) exploration-job данного прогона и типа —
    рестарт возвращает его job_id без повторного выбора (THR-3)."""
    cursor = await db.db.execute(
        "SELECT job_id FROM task_jobs WHERE kind = ? AND "
        "coalesce_key LIKE ? AND status IN ('queued','running') "
        "ORDER BY created_at DESC LIMIT 1",
        (exploration_job_kind(job_type),
         f"%:{_short(package_run_id, 48) or ''}:{job_type}"))
    row = await cursor.fetchone()
    return str(row["job_id"]) if row is not None else None


# Rework F-2 (reviewer): orphaned `queued` exploration-job вечен — executor
# выбирает только свои jobs, `recover_stale` чистит только `running`, и
# зависший queued-job НАВСЕГДА блокирует busy-check чата (`_uncovered_range`
# → None). Честное закрытие past-run queued-jobs: `cancelled` +
# `exploration_deferred` (ничего не исполнялось) + lifecycle-событие →
# release. Bounded: возраст + cap за проход; ТЕКУЩИЙ прогон не трогается.
_STALE_QUEUED_EXPLORE_MAX_AGE = 3600     # bounded: час (1 спящий цикл ≪)
_STALE_QUEUED_EXPLORE_CLOSE_CAP = 8      # bounded за проход


async def close_stale_queued_explorations(db, *,
                                          current_package_run_id: str = "",
                                          now: int | None = None,
                                          max_age_seconds: int =
                                          _STALE_QUEUED_EXPLORE_MAX_AGE
                                          ) -> int:
    """Закрыть зависшие queued exploration-jobs ПРОШЛЫХ прогонов (не
    текущего `current_package_run_id`, возраст > `max_age_seconds`) —
    честный терминальный исход `cancelled`/`exploration_deferred` +
    lifecycle-событие; busy-check чата освобождается. Bounded cap;
    fail-open по каждой записи. Возвращает число закрытых."""
    from services.task_supervisor import TaskJobStore
    moment = int(now if now is not None else time.time())
    cutoff = moment - max(0, int(max_age_seconds))
    current_token = f":{_short(current_package_run_id, 48) or ''}:"
    cursor = await db.db.execute(
        "SELECT job_id, coalesce_key FROM task_jobs WHERE kind LIKE ? "
        "AND status = 'queued' AND created_at <= ? AND "
        "instr(coalesce_key, ?) = 0 ORDER BY created_at ASC LIMIT ?",
        (EXPLORATION_JOB_KIND_PREFIX + "%", cutoff, current_token,
         _STALE_QUEUED_EXPLORE_CLOSE_CAP))
    rows = [dict(r) for r in await cursor.fetchall()]
    if not rows:
        return 0
    store = TaskJobStore(db)
    closed = 0
    for row in rows:
        job_id = str(row["job_id"])
        try:
            if not await store.finish(job_id, status="cancelled",
                                      reason_code="exploration_deferred"):
                continue
        except Exception:
            logger.warning("[mca10b] stale exploration close failed | "
                           "job=%s", job_id, exc_info=True)
            continue
        closed += 1
        await record_lifecycle(db, job_id, stage=LIFE_DEFERRED,
                               reason_code="exploration_deferred",
                               entity={"stale_queued": True,
                                       "coalesce_key":
                                       _short(row["coalesce_key"], 96)})
    return closed


async def _candidate_chat_ids(db, limit: int = 8) -> list[int]:
    """Кандидаты-чаты для выборки (bounded; чаты с непустым архивом)."""
    cursor = await db.db.execute(
        "SELECT DISTINCT chat_id FROM smart_messages "
        "WHERE chat_id IS NOT NULL LIMIT ?", (max(1, int(limit)),))
    return [int(r["chat_id"]) for r in await cursor.fetchall()]


async def execute_archive_sample_job(db, job_id: str, llm=None,
                                     pipeline_run_id: str | None = None) -> str:
    """Исполнение exploration-job отдельным шагом (не основным worker'ом).

    Существующий EpisodeService.process_batch (без нового сканера/второй
    очереди); checkpoint в payload самого job; основной cursor/backfill
    НЕ трогается. Пустой результат → диапазон отмечается проверенным
    (R7c, coverage merged). Lifecycle: checking→accepted/stored_only |
    rejected/not_used | failed. НОВЫХ exploration-jobs не создаёт
    (без рекурсии, THR-2)."""
    from services.task_supervisor import TaskJobStore
    from services.mca_episodes import EpisodeService
    store = TaskJobStore(db)
    cursor = await db.db.execute(
        "SELECT payload, coalesce_key FROM task_jobs WHERE job_id = ?",
        (job_id,))
    row = await cursor.fetchone()
    if row is None:
        return "missing"
    try:
        payload = json.loads(row["payload"] or "{}")
    except (ValueError, TypeError):
        payload = {}
    if not await store.mark_running(job_id):
        return "already_running"
    await record_lifecycle(db, job_id, stage=LIFE_CHECKING,
                           reason_code="exploration_accepted",
                           pipeline_run_id=pipeline_run_id,
                           entity={"type": PURPOSE_ARCHIVE_SAMPLE})
    chat_id = int(payload.get("chat_id") or 0)
    id_from = int(payload.get("id_from") or 0)
    id_to = int(payload.get("id_to") or 0)
    period = str(payload.get("period") or "")
    try:
        cursor = await db.db.execute(
            "SELECT id, chat_id, user_id, text, reply_to_id, timestamp, "
            "tg_message_id FROM smart_messages WHERE chat_id = ? AND id >= ? "
            "AND id <= ? ORDER BY id ASC LIMIT ?",
            (chat_id, id_from, id_to, _ARCHIVE_RANGE_MESSAGES_MAX))
        portion = [dict(r) for r in await cursor.fetchall()]
        episodes_written = 0
        if portion:
            service = EpisodeService(db, llm)
            counters = await service.process_batch(chat_id, portion) or {}
            episodes_written = int(counters.get("episodes")
                                   or counters.get("linked") or 0)
    except Exception:
        logger.warning("[mca10b] archive_sample job failed | job=%s", job_id,
                       exc_info=True)
        await store.finish(job_id, status="failed",
                           reason_code="exploration_failed")
        await record_lifecycle(db, job_id, stage=LIFE_FAILED,
                               reason_code="exploration_failed",
                               pipeline_run_id=pipeline_run_id,
                               entity={"type": PURPOSE_ARCHIVE_SAMPLE})
        await trace_finish(db, pipeline_run_id, outcome="failed",
                           reason_code="exploration_failed")
        return "failed"
    coverage = payload.get("coverage") or {}
    verified_before = int(coverage.get("verified_unique") or 0)
    verified_now = verified_before + (len(portion) if portion else 0)
    await merge_coverage(
        db, chat_id, period,
        msgs_total=int(coverage.get("msgs_total") or 0),
        verified_unique=verified_now,
        episodes=int(coverage.get("episodes") or 0) + episodes_written,
        extractor_version=str(payload.get("extractor_version") or ""))
    await store.finish(job_id, status="succeeded",
                       reason_code="exploration_stored_only")
    # Исходы → память (эпизоды); Telegram НЕ затрагивается (CA-10B-3);
    # координатор решает сам, использовать ли материал.
    await record_lifecycle(
        db, job_id, stage=LIFE_ACCEPTED,
        reason_code=("exploration_accepted" if episodes_written
                     else "exploration_not_used"),
        pipeline_run_id=pipeline_run_id,
        entity={"type": PURPOSE_ARCHIVE_SAMPLE, "episodes": episodes_written,
                "messages": len(portion), "period": _short(period, 16),
                "final": FINAL_STORED_ONLY if episodes_written
                else FINAL_NOT_USED})
    await trace_finish(db, pipeline_run_id, outcome="succeeded",
                       reason_code="exploration_stored_only")
    return "succeeded"


# ── T-5057: belief_review (D8) — DreamWorker/ProvenanceRepository reuse ─────
# База — существующий контур mca-06: активные beliefs = `graph_facts`
# (origin='derived_belief', kind='belief'; `db.list_confirmed_beliefs`),
# книга отзывов — v30 `mca_belief_reviews` (durable `material_refs_hash` —
# защита от колебаний THR-8), пересмотр — существующий write-путь
# `db.set_belief_status`/`db.mark_belief_superseded` (коды mca-06;
# новых на пересмотр нет), детекция дрейфа — REUSE
# `mca_dream_evidence` (маркеры/`topic_overlap`/applicability AM-5).
# ОБЯЗАТЕЛЬНАЯ перепроверка изменённых источников — существующая обычная
# очередь (`mca_dream_evidence.RevisionQueue`) — вне random, без изменений
# (CA-10B-6). Ядро личности (mca-18) в наборе отсутствует СТРУКТУРНО:
# выборка читает только derived `graph_facts`, write-пути к ядру из
# сна не существует (граница AM-3 `mca_dream_evidence`).
# «Выбор ≠ вердикт»: случайность выбирает ОБЪЕКТ; вердикт —
# детерминированная оценка материалов; ищутся И подтверждения, И
# опровержения; отсутствие найденного контрпримера уверенность НЕ
# повышает (никаких бустов weight/last_confirmed_at/счётчиков).

BELIEF_REVIEW_OUTCOMES = frozenset({
    "kept", "narrowed", "split", "disputed", "replaced"})
_BELIEF_FACTS_SCAN_CAP = 500          # bounded скан фактов чата
_BELIEF_OVERLAP_MIN = 2               # смысловая связка (токены)
_BELIEF_REFUTATION_OVERLAP_MIN = 1    # связка контрпримера с убеждением


async def _belief_review_available(db) -> bool:
    """Доступность контура: существующий DreamWorker-слой beliefs
    (kind='belief', status='confirmed') непуст. Ошибка → False."""
    try:
        return bool(await db.list_confirmed_beliefs(limit=1))
    except Exception:
        return False


def belief_material_refs_hash(belief_id, refs) -> str:
    """Durable отпечаток материалов отзыва (THR-8): sha1 по отсортированным
    R17-safe refs (`belief:<id>`, `fact:<id>`). Те же материалы без новых
    обстоятельств → verdict не меняется (защита от колебаний)."""
    import hashlib
    canon = "|".join(sorted(str(r) for r in
                            (["belief:" + str(belief_id)] + list(refs or ()))))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:32]


async def _belief_last_review(db, belief_id: str) -> dict | None:
    cursor = await db.db.execute(
        "SELECT review_id, reviewed_at, material_refs_hash, outcome, "
        "reason_code FROM mca_belief_reviews WHERE belief_id = ? "
        "ORDER BY reviewed_at DESC LIMIT 1", (str(belief_id),))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def _protected_belief_texts(db, chat_id: int) -> set:
    """Тексты, защищённые владельцем (`protected_facts`, §3.4.8) —
    overrides уважаются: защищённое убеждение random-review не выбирает."""
    try:
        cursor = await db.db.execute(
            "SELECT fact FROM protected_facts WHERE chat_id = ? AND "
            "user_name IS NULL LIMIT ?", (int(chat_id),
                                          _BELIEF_FACTS_SCAN_CAP))
        return {str(r["fact"] or "") for r in await cursor.fetchall()}
    except Exception:
        return set()


async def select_belief_review(db, source, *, package_run_id: str = "") -> dict:
    """Выбор ОБЪЕКТА review (D8): активные убеждения с самым старым
    `last_reviewed_at` (по книге v30; NULL = никогда — старшая группа),
    исключая уже ожидающие обязательную перепроверку (in-memory очередь
    `mca_dream_evidence.get_revision_queue`) и защищённые владельцем
    (`protected_facts`); РАВНОМЕРНЫЙ draw внутри старшей группы
    (purpose=`belief_review`). Один draw; «всё равно что» — не так:
    недоступные/исключённые — с причиной."""
    from services.mca_dream_evidence import get_revision_queue
    run_id = _short(package_run_id, 48) or uuid.uuid4().hex[:16]
    beliefs = await db.list_confirmed_beliefs(limit=1000)
    if not beliefs:
        return {"status": "not_run", "reason": "no_beliefs"}
    pending = set()
    try:
        queue = get_revision_queue()
        for _, _, key in queue._items:
            text = str(key)
            for row in beliefs:
                if text.endswith(str(row["id"])) or str(row["id"]) in text:
                    pending.add(str(row["id"]))
    except Exception:
        pending = set()
    eligible: list[dict] = []
    excluded: list[tuple] = []
    protected_cache: dict[int, set] = {}
    for row in beliefs:
        bid = str(row["id"])
        chat_id = int(row.get("chat_id") or 0)
        last = await _belief_last_review(db, bid)
        row["_last_reviewed_at"] = (last or {}).get("reviewed_at")
        if bid in pending:
            excluded.append((bid, "no_eligible_alternative"))
            continue
        protected = protected_cache.setdefault(
            chat_id, await _protected_belief_texts(db, chat_id))
        if str(row.get("fact") or "") in protected:
            excluded.append((bid, "no_eligible_alternative"))
            continue
        eligible.append(row)
    if not eligible:
        return {"status": "not_run", "reason": "no_eligible_alternative",
                "excluded": excluded[:50], "package_run_id": run_id}
    oldest = min((r["_last_reviewed_at"] or 0) for r in eligible)
    tier = [r for r in eligible
            if (r["_last_reviewed_at"] or 0) == oldest]
    draw = await source.draw_index(
        len(tier), purpose=PURPOSE_BELIEF_REVIEW,
        policy_version=POLICY_VERSION_10B,
        candidates=[str(r["id"]) for r in tier])
    if draw is None or draw.deferred or draw.index is None:
        return {"status": "deferred",
                "reason": (draw.reason if draw is not None
                           else "provider_unavailable")}
    pick = tier[max(0, int(draw.index))]
    return {"status": "selected",
            "belief_id": str(pick["id"]), "chat_id": int(pick["chat_id"] or 0),
            "last_reviewed_at": pick["_last_reviewed_at"],
            "draw_id": draw.draw_id, "package_run_id": run_id,
            "excluded": excluded[:50]}


async def _belief_review_select_and_enqueue(db, source, *,
                                            package_run_id: str = "",
                                            memory=None) -> dict:
    """Выбор объекта + постановка ОДНОГО durable job (уникальный ключ
    `(chat_id, package_run_id, type)` — рестарт не дублирует, THR-3)."""
    from services.task_supervisor import TaskJobStore
    run_id = _short(package_run_id, 48) or uuid.uuid4().hex[:16]
    existing = await _active_job_for_run(db, run_id, PURPOSE_BELIEF_REVIEW)
    if existing is not None:
        return {"status": "selected", "job_id": existing, "reused": True,
                "package_run_id": run_id}
    selection = await select_belief_review(db, source, package_run_id=run_id)
    if selection.get("status") != "selected":
        return selection
    chat_id = int(selection["chat_id"] or 0)
    store = TaskJobStore(db)
    payload = json.dumps({
        "type": PURPOSE_BELIEF_REVIEW,
        "belief_id": str(selection["belief_id"]),
        "chat_id": chat_id,
        "package_run_id": selection.get("package_run_id") or run_id,
        "draw_id": selection.get("draw_id") or "",
        "last_reviewed_at": selection.get("last_reviewed_at"),
    }, ensure_ascii=False)
    job_id = await store.enqueue(
        owner="random.uses",
        kind=exploration_job_kind(PURPOSE_BELIEF_REVIEW),
        coalesce_key=exploration_job_key(
            chat_id, selection.get("package_run_id") or run_id,
            PURPOSE_BELIEF_REVIEW),
        payload=payload, max_attempts=1)
    return {"status": "selected", "job_id": job_id,
            "belief_id": str(selection["belief_id"]), "chat_id": chat_id}


async def _record_belief_review(db, *, belief_id: str, chat_id: int,
                                outcome: str, material_hash: str,
                                grounds: list, reason_code: str | None,
                                job_id: str) -> None:
    """Книга отзывов (v30 `mca_belief_reviews`) через общий write-механизм."""
    now = int(time.time())

    async def _body(conn):
        await conn.execute(
            "INSERT INTO mca_belief_reviews (review_id, belief_id, chat_id, "
            "reviewed_at, material_refs_hash, outcome, grounds_json, "
            "reason_code, job_id) VALUES (?,?,?,?,?,?,?,?,?)",
            ("brv" + uuid.uuid4().hex[:13], str(belief_id), int(chat_id),
             now, str(material_hash), str(outcome),
             json.dumps([str(g) for g in grounds][:50], ensure_ascii=False),
             reason_code, _short(job_id, 64)))
        return 1

    await db.write_transaction(_body, op_name="mca10b_belief_review")


async def execute_belief_review_job(db, job_id: str,
                                    pipeline_run_id: str | None = None) -> str:
    """Исполнение review (A32/D8): материалы убеждения → И подтверждения,
    И опровержения (детекция дрейфа REUSE `mca_dream_evidence`) →
    ДЕТЕРМИНИРОВАННЫЙ вердикт (случайность объект не вердикт выбирала).
    Исходы kept/narrowed/split/disputed; `replaced` — только существующим
    supersede-путём mca-06 (без LLM-пересмотра в этом шаге не создаётся).
    Отсутствие контрпримера НЕ усиливает убеждение; одинаковые материалы →
    kept + `belief_review_unchanged`, версия/вес/счётчики НЕ трогаются.
    Событие «Убеждение проверено/уточнено» — существующая лента снов
    (`memory_dream_log`) + единый журнал."""
    from services.task_supervisor import TaskJobStore
    from services.mca_dream_evidence import (CONTRADICTION_MARKERS,
                                             build_applicability,
                                             merge_applicability,
                                             topic_overlap)
    from services.database import parse_belief_meta
    store = TaskJobStore(db)
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE job_id = ?", (job_id,))
    row = await cursor.fetchone()
    if row is None:
        return "missing"
    try:
        payload = json.loads(row["payload"] or "{}")
    except (ValueError, TypeError):
        payload = {}
    if not await store.mark_running(job_id):
        return "already_running"
    belief_id = str(payload.get("belief_id") or "")
    chat_id = int(payload.get("chat_id") or 0)
    await record_lifecycle(db, job_id, stage=LIFE_CHECKING,
                           reason_code="exploration_accepted",
                           pipeline_run_id=pipeline_run_id,
                           entity={"type": PURPOSE_BELIEF_REVIEW,
                                   "belief_id": _short(belief_id)})
    cursor = await db.db.execute(
        "SELECT id, chat_id, fact, status, weight, last_confirmed_at, "
        "created_at, belief_meta FROM graph_facts WHERE id = ? AND "
        "kind = 'belief'", (int(belief_id) if str(belief_id).isdigit()
                            else -1,))
    belief = await cursor.fetchone()
    if belief is None:
        await store.finish(job_id, status="failed",
                           reason_code="exploration_failed")
        await record_lifecycle(db, job_id, stage=LIFE_FAILED,
                               reason_code="exploration_failed",
                               pipeline_run_id=pipeline_run_id,
                               entity={"type": PURPOSE_BELIEF_REVIEW,
                                       "belief_id": _short(belief_id)})
        await trace_finish(db, pipeline_run_id, outcome="failed",
                           reason_code="exploration_failed")
        return "failed"
    belief = dict(belief)
    text = str(belief.get("fact") or "")
    # Материалы: подтверждения И опровержения — факты чата (kind='fact',
    # confirmed, без self-origin — существующий список `mca-06`).
    cursor = await db.db.execute(
        "SELECT id, fact, message_timestamp FROM graph_facts "
        "WHERE chat_id = ? AND kind = 'fact' AND status = 'confirmed' "
        "AND origin != 'bot_self_reply' "
        "AND (expires_at IS NULL OR expires_at > ?) ORDER BY id ASC "
        "LIMIT ?", (chat_id, int(time.time()), _BELIEF_FACTS_SCAN_CAP))
    facts = [dict(r) for r in await cursor.fetchall()]
    confirms: list[dict] = []
    refutes: list[dict] = []
    for fact in facts:
        ftext = str(fact.get("fact") or "")
        overlap = topic_overlap(text, ftext)
        if overlap < _BELIEF_REFUTATION_OVERLAP_MIN:
            continue
        marked = any(marker in ftext.casefold()
                     for marker in CONTRADICTION_MARKERS)
        if marked:
            refutes.append(fact)
        elif overlap >= _BELIEF_OVERLAP_MIN:
            confirms.append(fact)
    grounds = (["belief:" + belief_id]
               + [f"fact:{r['id']}" for r in confirms[:20]]
               + [f"fact:{r['id']}" for r in refutes[:20]])
    material_hash = belief_material_refs_hash(belief_id, grounds)
    # Защита от колебаний (THR-8): те же материалы + статус не менялся →
    # kept (`belief_review_unchanged`), убеждение НЕ переписывается.
    last = await _belief_last_review(db, belief_id)
    if last is not None and str(last.get("material_refs_hash") or "") == \
            material_hash and str(belief.get("status") or "") == "confirmed":
        outcome, reason_code = "kept", "belief_review_unchanged"
    elif refutes and confirms:
        # Обе группы: убеждение верно для раннего периода и оспорено позже —
        # разделить периоды (applicability AM-5, без DDL).
        outcome, reason_code = "split", None
        ref_ts = max(int(r.get("message_timestamp") or 0) for r in refutes)
        created = int(belief.get("created_at") or 0)
        meta = parse_belief_meta(belief.get("belief_meta"))
        merged = merge_applicability(meta, applicability=build_applicability(
            scope=None, valid_from=created or None, valid_to=ref_ts or None,
            narrowed=True))
        await db.set_belief_status(int(belief_id), "confirmed",
                                   belief_meta_patch=merged)
    elif refutes:
        newest = max(int(r.get("message_timestamp") or 0) for r in refutes)
        created = int(belief.get("created_at") or 0)
        if newest and created and newest > created:
            # Новое обстоятельство после возникновения — сузить
            # применимость (вывод сужается, не отвергается — §5.3/D8).
            outcome, reason_code = "narrowed", None
            meta = parse_belief_meta(belief.get("belief_meta"))
            merged = merge_applicability(
                meta, applicability=build_applicability(
                    scope=None, valid_from=created or None,
                    valid_to=newest, narrowed=True))
            await db.set_belief_status(int(belief_id), "confirmed",
                                       belief_meta_patch=merged)
        else:
            # Старые «противоречия» без временного порядка — пометить
            # спорным (без отвержения и без правки текста).
            outcome, reason_code = "disputed", None
            await db.set_belief_status(
                int(belief_id), "confirmed",
                belief_meta_patch={"disputed": True,
                                   "disputed_at": int(time.time())})
    else:
        # Подтверждения и/или тишина: уверенность НЕ повышается —
        # weight/last_confirmed_at/счётчики не трогаются (A32/D8).
        outcome, reason_code = "kept", None
    await _record_belief_review(
        db, belief_id=belief_id, chat_id=chat_id, outcome=outcome,
        material_hash=material_hash, grounds=grounds,
        reason_code=reason_code, job_id=job_id)
    # Событие «Убеждение проверено/уточнено» — существующая лента убеждений
    # (memory_dream_log) + единый журнал (до/после = текст до; исход).
    try:
        await db.log_dream_event(
            chat_id, int(time.time()), kind="belief_review",
            belief_id=int(belief_id) if str(belief_id).isdigit() else None,
            status=outcome)
    except Exception:
        logger.warning("[mca10b] belief feed event failed — fail-open",
                       exc_info=True)
    await store.finish(job_id, status="succeeded",
                       reason_code=(reason_code or "exploration_stored_only"))
    await record_lifecycle(
        db, job_id, stage=LIFE_ACCEPTED,
        reason_code=(reason_code or "exploration_stored_only"),
        pipeline_run_id=pipeline_run_id,
        entity={"type": PURPOSE_BELIEF_REVIEW, "belief_id": _short(belief_id),
                "outcome": outcome, "confirms": len(confirms),
                "refutes": len(refutes), "final": FINAL_STORED_ONLY})
    await trace_finish(db, pipeline_run_id, outcome="succeeded",
                       reason_code=(reason_code or "exploration_stored_only"))
    return "succeeded"


# ── T-5058: association_pair (D9) — EpisodeService + v30 mca_associations ───
# Конечный набор пар (cap ≤ 8, НЕ декартов перебор): сторона A — актуальный
# эпизод контекста сна (canonical ID), сторона B — из retrieval-пула
# СТРОГО через `retrieve()` (L-MCA07-5); разные canonical event ID;
# тематическая связь (token overlap REUSE `mca_dream_evidence.topic_overlap`);
# подтверждённые источники (обе стороны — реальные строки `mca_episodes`).
# Association — ОТДЕЛЬНЫЙ тип производной интерпретации (v30
# `mca_associations`; версии сторон = `updated_at` эпизода; статусы
# candidate/accepted/rejected/stale): не досье, не усиливает убеждения,
# `continuation` НЕ автосклеивает истории (правила EpisodeService mca-05
# единственные — CA-10B-7). Изменение любой стороны → stale (по версиям,
# ленивая инвалидация при выборе). Rejected = кэш попытки по версиям.
# Принятая — статус `accepted` для обычного координатора; ПРЯМОЙ ОТПРАВКИ
# НЕТ (CA-10B-3/THR-10). Атрибуция упомянувших outputs — v22 без изменений.

ASSOCIATION_LINK_TYPES = frozenset({
    "analogy", "motif", "contrast", "continuation", "insufficient"})
_ASSOCIATION_PAIRS_CAP = 8            # конечный набор (не декартов перебор)
_ASSOCIATION_OVERLAP_MIN = 1          # тематическая связь пары
_ASSOCIATIONS_SCAN_CAP = 200          # bounded скан активных строк


async def _association_pair_available(db) -> bool:
    """Доступность контура: есть эпизоды (стороны пар) хотя бы одного чата."""
    try:
        cursor = await db.db.execute(
            "SELECT 1 FROM mca_episodes LIMIT 1")
        return await cursor.fetchone() is not None
    except Exception:
        return False


async def episode_version(db, episode_id: str) -> int | None:
    """Версия стороны (deterministic): `updated_at` строки эпизода; правка
    источника (recheck/переизвлечение) поднимает `updated_at` → stale."""
    try:
        cursor = await db.db.execute(
            "SELECT updated_at FROM mca_episodes WHERE episode_id = ?",
            (str(episode_id),))
        row = await cursor.fetchone()
        return int(row["updated_at"]) if row is not None else None
    except Exception:
        return None


async def mark_associations_stale(db, episode_id: str,
                                  current_version: int | None = None) -> int:
    """Инвалидация по версиям (R9d/A33): строки candidate/accepted, у
    которых сохранённая версия стороны ≠ текущей → status='stale' +
    событие `association_stale` (причина санкционированная)."""
    if current_version is None:
        current_version = await episode_version(db, episode_id)
    if current_version is None:
        return 0
    stale: list[str] = []
    cursor = await db.db.execute(
        "SELECT association_id, a_event_id, a_version, b_event_id, "
        "b_version FROM mca_associations WHERE status IN "
        "('candidate','accepted') AND (a_event_id = ? OR b_event_id = ?) "
        "LIMIT ?", (str(episode_id), str(episode_id),
                    _ASSOCIATIONS_SCAN_CAP))
    for row in await cursor.fetchall():
        version = (int(row["a_version"]) if str(row["a_event_id"]) ==
                   str(episode_id) else int(row["b_version"]))
        if version != int(current_version):
            stale.append(str(row["association_id"]))
    if not stale:
        return 0

    async def _body(conn):
        total = 0
        for aid in stale:
            cursor = await conn.execute(
                "UPDATE mca_associations SET status = 'stale', "
                "updated_at = ? WHERE association_id = ? AND status IN "
                "('candidate','accepted')",
                (int(time.time()), aid))
            total += max(0, int(cursor.rowcount or 0))
        return total

    updated = int(await db.write_transaction(_body,
                                             op_name="mca10b_assoc_stale"))
    for aid in stale:
        _emit("random_uses_lifecycle", outcome=mca_events.OUTCOME_SILENT,
              reason_code="association_stale", stage="stale",
              entity_ids={"association_id": _short(aid),
                          "episode_id": _short(episode_id)})
    return updated


async def association_pairs(db, memory, *, chat_id: int,
                            context_episode_id: str, top_k: int = 8) -> dict:
    """КОНЕЧНЫЙ набор пар (cap ≤ 8; не декартов перебор): сторона B — из
    retrieval-пула через `retrieve()`; тематическая связь; разные canonical
    event ID; rejected-кэш по версиям повторно не предлагается; стороны
    сначала invalidируются по версиям (stale)."""
    from services.mca_dream_evidence import topic_overlap
    repo = EpisodeRepositoryShim(db)
    a_row = await repo.get_episode(str(context_episode_id))
    if a_row is None:
        return {"pairs": [], "excluded": [("a", "no_eligible_alternative")]}
    await mark_associations_stale(db, str(context_episode_id))
    a_text = " ".join(str(a_row.get(k) or "")
                      for k in ("title", "summary"))
    a_canonical = await _canonical_episode_id(repo, str(context_episode_id))
    a_version = await episode_version(db, str(context_episode_id))
    from services.mca_retrieval_context import (RetrievalRequest, retrieve)
    request = RetrievalRequest(chat_id=int(chat_id),
                               query=a_text[:400] or "context",
                               mode="history", top_k=max(4, int(top_k)))
    result = await retrieve(db, memory, request)
    pairs: list[dict] = []
    excluded: list[tuple] = []
    if result.status == "ok":
        seen_b: set = set()
        for cand in sorted(result.candidates,
                           key=lambda c: float(c.score or 0.0),
                           reverse=True):
            if cand.entity_type != "episode" or len(pairs) >= \
                    _ASSOCIATION_PAIRS_CAP:
                continue
            b_canonical = await _canonical_episode_id(repo,
                                                      str(cand.entity_id))
            if b_canonical is None or b_canonical == a_canonical:
                # Разные canonical event ID обязательны (дубли события
                # «связи» не дают — A33/THR-9).
                if b_canonical == a_canonical:
                    excluded.append((b_canonical, "no_eligible_alternative"))
                continue
            if b_canonical in seen_b:
                continue
            b_row = await repo.get_episode(b_canonical)
            if b_row is None:
                # Подтверждённые источники: обе стороны резолвятся.
                excluded.append((b_canonical, "no_eligible_alternative"))
                continue
            b_text = " ".join(str(b_row.get(k) or "")
                              for k in ("title", "summary"))
            if topic_overlap(a_text, b_text) < _ASSOCIATION_OVERLAP_MIN:
                excluded.append((b_canonical, "no_relevant_memory"))
                continue
            b_version = await episode_version(db, b_canonical)
            if await _association_cached(db, a_canonical, a_version,
                                         b_canonical, b_version):
                # Rejected-пара на тех же версиях повторно не выбирается.
                excluded.append((b_canonical, "no_eligible_alternative"))
                continue
            seen_b.add(b_canonical)
            pairs.append({
                "a_event_id": a_canonical, "a_version": a_version,
                "b_event_id": b_canonical, "b_version": b_version,
                "score": float(cand.score or 0.0)})
    return {"pairs": pairs, "excluded": excluded, "a": a_canonical}


class EpisodeRepositoryShim:
    """Тонкий доступ к EpisodeRepository (mca-05) без создания второго
    механизма: только существующие чтения `get_episode`/`redirect_target`."""

    def __init__(self, db) -> None:
        from services.mca_episodes import EpisodeRepository
        self._repo = EpisodeRepository(db)

    async def get_episode(self, episode_id: str):
        return await self._repo.get_episode(episode_id)

    async def redirect_target(self, kind: str, old_id: str):
        return await self._repo.redirect_target(kind, old_id)


async def _association_cached(db, a_id, a_version, b_id, b_version) -> bool:
    """Кэш попытки: та же пара на ТЕХ ЖЕ версиях уже есть (candidate/
    accepted/rejected) → повторно не выбираем (stale-строки — можно)."""
    cursor = await db.db.execute(
        "SELECT 1 FROM mca_associations WHERE a_event_id = ? AND "
        "b_event_id = ? AND a_version = ? AND b_version = ? AND "
        "status != 'stale' LIMIT 1",
        (str(a_id), str(b_id), int(a_version or 0), int(b_version or 0)))
    return await cursor.fetchone() is not None


async def _association_pair_select_and_enqueue(
        db, source, *, package_run_id: str = "", memory=None) -> dict:
    """Построение конечного набора пар + ОДИН draw + ОДИН durable job."""
    from services.task_supervisor import TaskJobStore
    run_id = _short(package_run_id, 48) or uuid.uuid4().hex[:16]
    existing = await _active_job_for_run(db, run_id, PURPOSE_ASSOCIATION_PAIR)
    if existing is not None:
        return {"status": "selected", "job_id": existing, "reused": True,
                "package_run_id": run_id}
    chat_id, a_id = await _sleep_context_episode(db)
    if a_id is None:
        return {"status": "not_run", "reason": "no_context_episode"}
    built = await association_pairs(db, memory, chat_id=chat_id,
                                    context_episode_id=a_id)
    pairs = built.get("pairs") or []
    if not pairs:
        return {"status": "not_run",
                "reason": "no_eligible_alternative",
                "excluded": built.get("excluded", [])[:50]}
    draw = await source.draw_index(
        len(pairs), purpose=PURPOSE_ASSOCIATION_PAIR,
        policy_version=POLICY_VERSION_10B,
        candidates=[f"{p['a_event_id']}~{p['b_event_id']}" for p in pairs])
    if draw is None or draw.deferred or draw.index is None:
        return {"status": "deferred",
                "reason": (draw.reason if draw is not None
                           else "provider_unavailable")}
    pick = pairs[max(0, int(draw.index))]
    store = TaskJobStore(db)
    payload = json.dumps({
        "type": PURPOSE_ASSOCIATION_PAIR,
        "chat_id": int(chat_id),
        "a_event_id": pick["a_event_id"],
        "a_version": int(pick["a_version"] or 0),
        "b_event_id": pick["b_event_id"],
        "b_version": int(pick["b_version"] or 0),
        "package_run_id": run_id, "draw_id": draw.draw_id or "",
    }, ensure_ascii=False)
    job_id = await store.enqueue(
        owner="random.uses",
        kind=exploration_job_kind(PURPOSE_ASSOCIATION_PAIR),
        coalesce_key=exploration_job_key(
            int(chat_id), run_id, PURPOSE_ASSOCIATION_PAIR),
        payload=payload, max_attempts=1)
    return {"status": "selected", "job_id": job_id, "chat_id": int(chat_id),
            "pair": [pick["a_event_id"], pick["b_event_id"]]}


async def _sleep_context_episode(db, limit: int = 8) -> tuple[int, str | None]:
    """Актуальная тема/эпизод контекста сна: самый свежий эпизод
    (max `updated_at`) среди bounded-набора чатов с эпизодами."""
    cursor = await db.db.execute(
        "SELECT chat_id, episode_id FROM mca_episodes "
        "ORDER BY updated_at DESC, episode_id LIMIT ?",
        (max(1, int(limit)),))
    row = await cursor.fetchone()
    if row is None:
        return 0, None
    return int(row["chat_id"]), str(row["episode_id"])


async def upsert_association(db, *, chat_id: int, link_type: str,
                             a_event_id: str, a_version: int,
                             b_event_id: str, b_version: int,
                             status: str, basis: str | None,
                             job_id: str) -> str:
    """Association — доменная запись v30 `mca_associations` (R17: ID/коды/
    версии; basis — короткое R17-safe основание классификации). Status
    candidate — транзиент той же транзакции; финал accepted/rejected."""

    def _canon(text: str) -> str:
        cleaned = " ".join(str(text or "").split())
        return cleaned[:200] if cleaned else ""

    association_id = "assoc" + uuid.uuid4().hex[:13]
    now = int(time.time())

    async def _body(conn):
        await conn.execute(
            "INSERT INTO mca_associations (association_id, chat_id, "
            "link_type, a_event_id, a_version, b_event_id, b_version, "
            "status, basis, job_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (association_id, int(chat_id), str(link_type), str(a_event_id),
             int(a_version or 0), str(b_event_id), int(b_version or 0),
             "candidate", _canon(basis), _short(job_id, 64), now, now))
        cursor = await conn.execute(
            "UPDATE mca_associations SET status = ?, updated_at = ? "
            "WHERE association_id = ?", (str(status), now, association_id))
        return max(1, int(cursor.rowcount or 0))

    await db.write_transaction(_body, op_name="mca10b_assoc_upsert")
    return association_id


async def execute_association_pair_job(db, job_id: str, llm=None,
                                       pipeline_run_id: str | None = None
                                       ) -> str:
    """Классификация связи пары — LLM (НЕ random; D9). Без LLM — честный
    deferred (ничего не выдумывается, fail-closed как у mca-05).
    `insufficient`/нечитаемый ответ → rejected (кэш по версиям).
    Валидный тип → accepted (кандидат координатору; БЕЗ отправки;
    `continuation` истории НЕ склеивает — правила EpisodeService одни)."""
    from services.task_supervisor import TaskJobStore
    store = TaskJobStore(db)
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE job_id = ?", (job_id,))
    row = await cursor.fetchone()
    if row is None:
        return "missing"
    try:
        payload = json.loads(row["payload"] or "{}")
    except (ValueError, TypeError):
        payload = {}
    if not await store.mark_running(job_id):
        return "already_running"
    chat_id = int(payload.get("chat_id") or 0)
    a_id = str(payload.get("a_event_id") or "")
    b_id = str(payload.get("b_event_id") or "")
    a_version = int(payload.get("a_version") or 0)
    b_version = int(payload.get("b_version") or 0)
    await record_lifecycle(db, job_id, stage=LIFE_CHECKING,
                           reason_code="exploration_accepted",
                           pipeline_run_id=pipeline_run_id,
                           entity={"type": PURPOSE_ASSOCIATION_PAIR,
                                   "pair": [_short(a_id), _short(b_id)]})
    # Редакция источника до исполнения → stale (по версиям, R9d).
    await mark_associations_stale(db, a_id, await episode_version(db, a_id))
    await mark_associations_stale(db, b_id, await episode_version(db, b_id))
    if await episode_version(db, a_id) != a_version or \
            await episode_version(db, b_id) != b_version:
        await store.finish(job_id, status="failed",
                           reason_code="association_stale")
        await record_lifecycle(db, job_id, stage=LIFE_REJECTED,
                               reason_code="association_stale",
                               pipeline_run_id=pipeline_run_id,
                               entity={"type": PURPOSE_ASSOCIATION_PAIR,
                                       "pair": [_short(a_id), _short(b_id)]})
        await trace_finish(db, pipeline_run_id, outcome="partial",
                           reason_code="association_stale")
        return "stale"
    if llm is None:
        # Честный defer: классификация без LLM не выдумывается.
        await store.finish(job_id, status="failed",
                           reason_code="exploration_deferred")
        await record_lifecycle(db, job_id, stage=LIFE_DEFERRED,
                               reason_code="exploration_deferred",
                               pipeline_run_id=pipeline_run_id,
                               entity={"type": PURPOSE_ASSOCIATION_PAIR})
        await trace_finish(db, pipeline_run_id, outcome="partial",
                           reason_code="exploration_deferred")
        return "deferred"
    repo = EpisodeRepositoryShim(db)
    a_row = await repo.get_episode(a_id)
    b_row = await repo.get_episode(b_id)
    if a_row is None or b_row is None:
        await store.finish(job_id, status="failed",
                           reason_code="exploration_failed")
        await record_lifecycle(db, job_id, stage=LIFE_FAILED,
                               reason_code="exploration_failed",
                               pipeline_run_id=pipeline_run_id,
                               entity={"type": PURPOSE_ASSOCIATION_PAIR})
        await trace_finish(db, pipeline_run_id, outcome="failed",
                           reason_code="exploration_failed")
        return "failed"
    prompt = (
        "Определи связь между двумя историями. Ответь СТРОГО JSON: "
        '{"link_type":"analogy|motif|contrast|continuation|insufficient",'
        '"basis":"<короткое основание>"}\n'
        "История A: " + str(a_row.get("summary") or a_row.get("title") or "")
        [:400] + "\nИстория B: "
        + str(b_row.get("summary") or b_row.get("title") or "")[:400])
    classification: dict = {}
    try:
        raw = await llm.generate(
            [{"role": "user", "content": prompt}], temperature=0.0,
            chat_id=chat_id)
        raw_text = raw if isinstance(raw, str) else \
            (getattr(raw, "text", "") or "")
        classification = json.loads(str(raw_text).strip().strip("`") or "{}")
    except Exception:
        logger.warning("[mca10b] association classification failed | job=%s",
                       job_id, exc_info=True)
        classification = {}
    link_type = str(classification.get("link_type") or "").strip()
    basis = str(classification.get("basis") or "").strip()
    if link_type not in (ASSOCIATION_LINK_TYPES - {"insufficient"}):
        # Недостаточно данных / нечитаемый класс → rejected = кэш попытки
        # по версиям (та же пара повторно не выбирается).
        if link_type != "insufficient":
            link_type = "insufficient"
        await upsert_association(
            db, chat_id=chat_id, link_type="insufficient", a_event_id=a_id,
            a_version=a_version, b_event_id=b_id, b_version=b_version,
            status="rejected", basis=basis or None, job_id=job_id)
        await store.finish(job_id, status="succeeded",
                           reason_code="exploration_not_used")
        await record_lifecycle(
            db, job_id, stage=LIFE_REJECTED,
            reason_code="exploration_not_used",
            pipeline_run_id=pipeline_run_id,
            entity={"type": PURPOSE_ASSOCIATION_PAIR,
                    "association": "rejected",
                    "pair": [_short(a_id), _short(b_id)],
                    "final": FINAL_NOT_USED})
        await trace_finish(db, pipeline_run_id, outcome="succeeded",
                           reason_code="exploration_not_used")
        return "rejected"
    association_id = await upsert_association(
        db, chat_id=chat_id, link_type=link_type, a_event_id=a_id,
        a_version=a_version, b_event_id=b_id, b_version=b_version,
        status="accepted", basis=basis or None, job_id=job_id)
    # Принятая ассоциация — КАНДИДАТ обычному координатору (статус
    # accepted в v30-таблице + событие); НИКАКОЙ отправки (CA-10B-3);
    # `continuation` историй не склеивает (правила EpisodeService одни).
    await store.finish(job_id, status="succeeded",
                       reason_code="exploration_stored_only")
    await record_lifecycle(
        db, job_id, stage=LIFE_ACCEPTED,
        reason_code="exploration_stored_only",
        pipeline_run_id=pipeline_run_id,
        entity={"type": PURPOSE_ASSOCIATION_PAIR,
                "association_id": _short(association_id),
                "link_type": _short(link_type, 24),
                "pair": [_short(a_id), _short(b_id)],
                "final": FINAL_STORED_ONLY})
    await trace_finish(db, pipeline_run_id, outcome="succeeded",
                       reason_code="exploration_stored_only")
    return "accepted"


# ── T-5059: conversation_variant — формы участия (D10) ──────────────────────
# Формы — обычные DecisionCandidate-семантики в ОБЩЕМ пуле §14.5 (одна
# probability-проверка на решение уже гарантирована процедурой D3; отдельного
# «стилевого броска» нет — R10d). `reply/react/silent/tool` mca-09 сохраняются
# (read-only reuse `COMMUNICATIVE_INTENTS`, CA-10B-1; второй action-schema
# нет). Непригодные формы в допущенные не входят (напр. шутка при
# direct/техническом запросе — A34/R10b); форма НЕ меняет факты/адресата/
# действующие стилевые запреты; в чат — только естественная реплика без
# меток; в раскрытии решения — выбранная форма + исключённые с причинами
# (candidate_actions/`random_uses`-журнал).

FORM_INTENTS = ("observation", "question", "opinion", "joke", "recall",
                "silence")

_FORM_GOALS = {
    "observation": ("короткое наблюдение по теме", "short"),
    "question": ("уточняющий вопрос по теме", "short"),
    "opinion": ("собственное мнение по теме", "medium"),
    "joke": ("лёгкая шутка по теме", "short"),
    "recall": ("уместное воспоминание", "medium"),
    "silence": ("осознанное молчание", "short"),
}


@dataclass
class ConversationFormCandidate:
    """Кандидат-форма участия (§14.10/D10; семантика кандидата mca-09 —
    НЕ новая action-schema). `goal/length/subject/style` — смысл для
    потребителя (не wire); в журнал идёт только `candidate_id`/intent."""

    intent: str
    goal: str = ""
    desired_length: str = "short"
    subject: str = ""
    source_refs: tuple = ()
    style_constraints: tuple = ()
    admissible: bool = True
    excluded_reason: str | None = None
    candidate_version: int = 1

    @property
    def candidate_id(self) -> str:
        return f"form:{self.intent}"

    @property
    def action(self) -> str:
        return "silent" if self.intent == "silence" else "reply"

    @property
    def reason_codes(self) -> tuple:
        return () if self.admissible else ("no_eligible_alternative",)

    @property
    def episode_ids(self) -> tuple:
        return episode_ids_of(self)

    def to_decision_candidate(self):
        """Read-only конверсия в контракт mca-09 (второй схемы нет)."""
        from services.direct_chat_service import DecisionCandidate
        return DecisionCandidate(
            candidate_id=self.candidate_id, action=self.action,
            reason_code=("default" if self.admissible
                         else "no_eligible_alternative"),
            source="random", communicative_intent=self.intent,
            source_refs=tuple(self.source_refs),
            admissible=self.admissible,
            reason_codes=self.reason_codes)


def build_conversation_form_candidates(
        *, direct_request: bool = False, technical_request: bool = False,
        has_story: bool = False, topic: str = "") -> list:
    """Допустимые формы участия для текущего решения (D10/R10b):
    * шутка НЕ попадает в пул при direct/техническом запросе;
    * воспоминание требует источников-историй (`has_story`);
    * молчание — легитимная форма;
    * форма не меняет факты/адресата/стилевые запреты (только intent).
    LLM ради набора не вызывается; неуместные формы сохраняются с
    `admissible=False` + причиной (why-why-not раскрытие)."""
    topic = str(topic or "").strip()
    forms: list[ConversationFormCandidate] = []
    for intent in FORM_INTENTS:
        goal, length = _FORM_GOALS.get(intent, ("ответ по теме", "short"))
        form = ConversationFormCandidate(
            intent=intent, goal=goal, desired_length=length,
            subject=topic, source_refs=(), admissible=True)
        if intent == "joke" and (direct_request or technical_request):
            # Непригодная форма вне допущенных (A34/R10b) — но видна в
            # раскрытии с причиной.
            form.admissible = False
            form.excluded_reason = "no_eligible_alternative"
        if intent == "recall" and not has_story:
            form.admissible = False
            form.excluded_reason = "no_eligible_alternative"
        forms.append(form)
    return forms


def is_repeated_phrase(text: str, recent_own_phrases, *,
                       min_tokens: int = 2) -> bool:
    """Повторяющаяся фраза = повтор (bounded скан недавних своих реплик;
    БЕЗ постоянного жёсткого запрета слов — окно задаёт вызывающий)."""
    try:
        from services.mca_dream_evidence import topic_overlap
    except Exception:      # pragma: no cover
        return False
    probe = str(text or "").strip()
    if not probe:
        return False
    for prev in (recent_own_phrases or ()):
        prev_text = str(prev or "").strip()
        if not prev_text:
            continue
        if probe.casefold() == prev_text.casefold():
            return True
        if topic_overlap(probe, prev_text) >= min_tokens:
            return True
    return False


# ── T-5055: memory_recall (D6) — retrieval строго через `retrieve()` ────────

# Порог допуска к разговору ПРИВЯЗАН к версии ранжирования (не универсальный
# cosine; §99.4). Неизвестная версия ранжирования → никого не допускаем
# (fail-closed, честно).
RANKING_ADMIT_SHARE = {"mca07-retrieval-1": 0.5}

# `delivery_unknown` (существующий код): подавляет НЕМЕДЛЕННЫЙ повторный
# выбор той же истории до разрешения статуса (A21-семантика). Bounded
# in-memory (сессия; рестарт снимает окно — доставка сессии тоже умерла).
_DELIVERY_UNKNOWN: dict[str, float] = {}
_DELIVERY_UNKNOWN_TTL = 3600.0
_DELIVERY_UNKNOWN_MAX = 64


def note_delivery_unknown(episode_id: str) -> None:
    now = time.monotonic()
    if len(_DELIVERY_UNKNOWN) >= _DELIVERY_UNKNOWN_MAX:
        for key in list(_DELIVERY_UNKNOWN)[:len(_DELIVERY_UNKNOWN)
                                           - _DELIVERY_UNKNOWN_MAX + 1]:
            _DELIVERY_UNKNOWN.pop(key, None)
    _DELIVERY_UNKNOWN[str(episode_id)] = now


def delivery_pending(episode_id: str) -> bool:
    stamp = _DELIVERY_UNKNOWN.get(str(episode_id))
    if stamp is None:
        return False
    if time.monotonic() - stamp > _DELIVERY_UNKNOWN_TTL:
        _DELIVERY_UNKNOWN.pop(str(episode_id), None)
        return False
    return True


@dataclass
class MemoryRecallCandidate:
    """Кандидат-история (§4; admission — к версии ранжирования)."""

    episode_id: str
    chat_id: int
    title: str = ""
    score: float = 0.0
    admitted: bool = False
    ranking_version: str = ""
    canonical_id: str = ""
    last_used_in_chat_at: float | None = None
    last_retrieved_at: float | None = None
    excluded_reason: str | None = None

    @property
    def candidate_id(self) -> str:
        return f"episode:{self.canonical_id or self.episode_id}"

    @property
    def source_refs(self) -> tuple:
        return (self.candidate_id,)


async def select_memory_recall_candidates(db, memory, *, chat_id: int,
                                          query: str, top_k: int = 8,
                                          mode: str = "history") -> dict:
    """Кандидаты-истории ТОЛЬКО через `retrieve()` (L-MCA07-5): сначала
    релевантность, затем разнообразие; dedup по canonical event ID
    (переформулировка = повтор); допуск — порог, привязанный к версии
    ранжирования; `last_retrieved_at` проставляется всем retrieved
    (поиск ≠ рассказ), `last_used_in_chat_at` — ТОЛЬКО после подтверждённой
    доставки. Прямой запрос истории — обычный поиск БЕЗ exploration."""
    from services.mca_retrieval_context import (RetrievalRequest, retrieve)
    request = RetrievalRequest(chat_id=int(chat_id), query=str(query or ""),
                               mode=mode, top_k=max(4, int(top_k)))
    result = await retrieve(db, memory, request)
    ranking_version = str(request.policy_version)
    admit_share = RANKING_ADMIT_SHARE.get(ranking_version)
    stories: list[MemoryRecallCandidate] = []
    seen_canonical: dict[str, MemoryRecallCandidate] = {}
    excluded: list[tuple] = []
    if result.status != "ok":
        return {"candidates": [], "excluded": [("retrieval", "retrieval_empty")],
                "ranking_version": ranking_version, "status": result.status}
    ranked = sorted(result.candidates, key=lambda c: float(c.score or 0.0),
                    reverse=True)
    best_score = float(ranked[0].score or 0.0) if ranked else 0.0
    from services.mca_episodes import EpisodeRepository
    repo = EpisodeRepository(db)
    for cand in ranked:
        if cand.entity_type != "episode":
            continue
        canonical = await _canonical_episode_id(repo, cand.entity_id)
        if canonical is None:
            continue
        if canonical in seen_canonical:
            # Переформулировка того же события — повтор (canonical ID).
            excluded.append((canonical, "no_eligible_alternative"))
            continue
        row = await _episode_usage_row(db, canonical)
        item = MemoryRecallCandidate(
            episode_id=str(cand.entity_id), chat_id=int(chat_id),
            score=float(cand.score or 0.0), ranking_version=ranking_version,
            canonical_id=canonical,
            last_used_in_chat_at=(row or {}).get("last_used_in_chat_at"),
            last_retrieved_at=(row or {}).get("last_retrieved_at"))
        if admit_share is None:
            item.excluded_reason = "insufficient_evidence"
            excluded.append((canonical, "insufficient_evidence"))
        elif best_score <= 0 or item.score < admit_share * best_score:
            # Релевантность прежде разнообразия: нерелевантная старая
            # ИСКЛЮЧЕНА (A30/R6a).
            item.excluded_reason = "no_relevant_memory"
            item.admitted = False
            excluded.append((canonical, "no_relevant_memory"))
        elif delivery_pending(canonical):
            item.excluded_reason = "delivery_unknown"
            excluded.append((canonical, "delivery_unknown"))
        else:
            item.admitted = True
        seen_canonical[canonical] = item
        stories.append(item)
    # Разнообразие после релевантности: ротация по давности использования —
    # предпочтение давно не использовавшимся (среди одинаково допустимых).
    admitted = [s for s in stories if s.admitted]
    admitted.sort(key=lambda s: (s.last_used_in_chat_at is not None,
                                 s.last_used_in_chat_at or 0.0,
                                 -s.score))
    await mark_episodes_retrieved(db, [s.canonical_id for s in stories],
                                  chat_id=chat_id)
    # Событие выбора (§4; R17-safe): выбранная история/давность/альтернативы/
    # причины исключения повторов — notable-only, единый журнал.
    if admitted:
        reason = None
    elif stories:
        reason = "no_relevant_memory"
    else:
        reason = "exploration_not_used"
    _emit("random_uses",
          outcome=(mca_events.OUTCOME_SUCCESS if admitted
                   else mca_events.OUTCOME_SKIPPED),
          level=(mca_events.LEVEL_WARN if not admitted
                 else mca_events.LEVEL_INFO),
          reason_code=reason,
          stage=PURPOSE_MEMORY_RECALL,
          entity_ids={
              "ranking_version": _short(ranking_version, 48),
              "selected": _short(admitted[0].canonical_id)
              if admitted else None,
              "last_used_in_chat_at": (admitted[0].last_used_in_chat_at
                                       if admitted else None),
              "candidates": [_short(s.canonical_id)
                             for s in stories][:50],
              "excluded": [[_short(cid), _short(rc, 48)]
                           for cid, rc in excluded][:50],
              "chat_id": int(chat_id)})
    return {"candidates": admitted, "all": stories,
            "excluded": tuple(excluded), "ranking_version": ranking_version,
            "status": result.status}


async def _canonical_episode_id(repo, episode_id: str) -> str | None:
    """Canonical event ID: redirect-резолв фасадом (перефраз = тот же ID)."""
    current = str(episode_id or "").strip()
    seen = 0
    while current and seen < 4:
        target = await repo.redirect_target("episode", current)
        if not target:
            return current
        current = str(target)
        seen += 1
    return current or None


async def _episode_usage_row(db, episode_id: str) -> dict | None:
    cursor = await db.db.execute(
        "SELECT last_retrieved_at, last_used_in_chat_at FROM mca_episodes "
        "WHERE episode_id = ?", (str(episode_id),))
    row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def mark_episodes_retrieved(db, episode_ids, *, chat_id=None) -> int:
    """`last_retrieved_at` — любой retrieval, включая поиск во сне (сон ≠
    рассказ). Только UPDATE добавленной колонки; НИ ОДНОГО touch контента."""
    ids = [str(e) for e in (episode_ids or ()) if str(e or "").strip()]
    if not ids:
        return 0
    now = time.time()

    async def _body(conn):
        total = 0
        for episode_id in ids[:_ARCHIVE_EPISODES_SCAN_CAP]:
            cursor = await conn.execute(
                "UPDATE mca_episodes SET last_retrieved_at = ? "
                "WHERE episode_id = ?", (now, episode_id))
            total += max(0, int(cursor.rowcount or 0))
        return total

    return int(await db.write_transaction(_body,
                                          op_name="mca10b_mark_retrieved"))


async def mark_episodes_used_in_chat(db, episode_ids, *,
                                     chat_id=None) -> int:
    """`last_used_in_chat_at` — ТОЛЬКО подтверждённая доставка в чат (R6d).
    Вызывает потребитель после фактической отправки; до неё колонка NULL."""
    ids = [str(e) for e in (episode_ids or ()) if str(e or "").strip()]
    if not ids:
        return 0
    now = time.time()

    async def _body(conn):
        total = 0
        for episode_id in ids[:_ARCHIVE_EPISODES_SCAN_CAP]:
            cursor = await conn.execute(
                "UPDATE mca_episodes SET last_used_in_chat_at = ? "
                "WHERE episode_id = ?", (now, episode_id))
            total += max(0, int(cursor.rowcount or 0))
        return total

    return int(await db.write_transaction(_body,
                                          op_name="mca10b_mark_used"))


def episode_ids_of(candidate) -> tuple:
    """Canonical episode-ID кандидата (DecisionCandidate/InitiativeCandidate/
    MemoryRecallCandidate): refs `episode:<id>` — R17-safe токены."""
    ids: list[str] = []
    for ref in tuple(getattr(candidate, "source_refs", ()) or ()):
        text = str(ref)
        if text.startswith("episode:") and len(text) > 8:
            ids.append(text[len("episode:"):])
    for direct in tuple(getattr(candidate, "episode_ids", ()) or ()):
        if str(direct).strip():
            ids.append(str(direct).strip())
    return tuple(dict.fromkeys(ids))


# ── T-5061: trace `mca_pipeline_runs` (D12; сквозной выбор→проверка→исход) ──

async def trace_start(db, *, chat_id=None, job_id=None):
    """Открыть run `random.uses` v1 (fail-open; OFF-гейт внутри `mca_trace`
    `job_lifecycle_enabled`). Возвращает pipeline_run_id | None."""
    try:
        from services import mca_trace
        return await mca_trace.start_run(
            db, pipeline_type="random.uses", version="1",
            job_id=job_id, chat_id=chat_id)
    except Exception:      # pragma: no cover - fail-open
        return None


async def trace_finish(db, run_id, *, outcome: str,
                       reason_code: str | None = None) -> None:
    """Закрыть run честным итогом (fail-open; `not_run` — если не дошло)."""
    if not run_id:
        return
    try:
        from services import mca_trace
        await mca_trace.finish_run(db, run_id, outcome=outcome,
                                   reason_code=reason_code)
    except Exception:      # pragma: no cover - fail-open
        return
