"""P1 «Инициатива» — журнал ЛОГИЧЕСКИХ попыток и трасса одной попытки.

Рекомпоновка страницы «Модули → Инициатива» (вкладки «Публикации» и
«Диагностика») требует одного чтения на два экрана: список попыток с
фильтрами/пагинацией и детальную трассу РОВНО одной попытки. Раньше такого
чтения не было: карточка мемов показывала последние 20 строк журнала, а
воронка текстовой инициативы — 5 последних решений (обрезано, без
пагинации).

Прецедент зоны — `web/api/mechanism_diagnostics.py`: аддитивный роутер,
`web/api/routes.py` не меняется (byte-freeze `ROUTES_SHA256_F11` в силе),
новых хранилищ/счётчиков нет. Модуль ТОЛЬКО читает уже существующие
источники и ничего не пишет, не считает собственных квот и не подменяет
причины:

* ``meme_initiative_attempt`` (SQLite-журнал квоты мема) — строки этапов;
  логическая попытка = все строки одного ``job_id`` (это и есть «точная
  цепочка событий»: выжимка → прикол → картинка → публикация);
* ``mca_events`` — решения/отправки/ошибки текстовой инициативы
  (``initiative_decided``, ``initiative_recheck_passed``,
  ``initiative_writer_unavailable``, ``delivery_unknown`` и любые будущие
  ``publication_*`` / ``initiative_publication_*``: фильтр по префиксу,
  поэтому новые коды публикационной семантики видны без правки этого файла);
* ``mca_bot_outputs`` — фактическая доставка (истина о том, что сообщение
  реально ушло: ``tg_message_id``, ``sent_at``, ``delivery_status``).

Принципы (те же, что у соседней диагностики):
* ``delivered`` = ``true|false|null``: ``null`` — «неизвестно», а не «нет»;
* пустая стадия не превращается в строку: attempt без строк не рисуется;
* **ни одно событие не удаляет попытку**: незнакомое публикационное имя
  сохраняет строку и показывается как ``other`` с сырым именем и ``outcome``
  (новый код P0 виден кодом, а не стирает запись);
* **режим попытки** (``mode``) берётся из ЗАПИСИ попытки — ``mode`` в detail
  JSON терминальной строки журнала мема либо ``events[].mode``; поздний
  publication-факт остаётся лишь фолбэком для старых строк (у раннего отказа
  публикационных фактов нет вовсе);
* **историческая строка без родителя** (пустой ``job_id``/``trace_id``) не
  склеивается ни с чем и помечается ``incomplete_historical: true``;
* наружу уходят коды/числа/ID; сырого текста чата в ответе нет — только
  факты этапов уже обрезаны ``compact_facts`` на стороне пайплайна;
* ничего не бросает: нет БД/таблиц → ``available=false`` + причина.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from web.api.deps import get_tma_user
from web.api.routes import _chat_id_or_none, _require_chat_access

logger = logging.getLogger(__name__)

initiative_publications_router = APIRouter()

#: Сколько строк журнала мема читаем за один запрос (bounded чтение).
MAX_ATTEMPT_ROWS = 600
#: Сколько событий текстовой инициативы читаем за один запрос.
MAX_TEXT_EVENTS = 400
#: Сколько доставленных выводов читаем за один запрос.
MAX_OUTPUTS = 300
#: Предел строк ответа на страницу.
DEFAULT_LIMIT = 40
MAX_LIMIT = 100
#: Сколько событий отдаём в трассе одной попытки.
TRACE_EVENTS_LIMIT = 60

KIND_TEXT = "text_initiative"
KIND_MEME = "meme"
KINDS = (KIND_TEXT, KIND_MEME)
TEXT_OUTPUT_KIND = "initiative_reply"
MEME_OUTPUT_KIND = "meme_initiative"
#: Терминальные/публикационные события текстовой инициативы.
TEXT_EVENT_NAMES = (
    "initiative_decided",
    "initiative_recheck_passed",
    "initiative_writer_unavailable",
    "initiative_sent",
    # P0 (`fix/p0-publication-stale`): координация публикаций текста пишет
    # собственные события с префиксом `initiative_publication_*` — без них
    # конфликты не попадали ни в список, ни в фильтр причины.
    "initiative_publication_conflict",
    "initiative_publication_claim",
    # «Доставка не подтверждена и не опровергнута» — отдельный честный исход.
    # Без этого имени строка не попадала даже в выборку: оно не подпадает ни
    # под один префикс.
    "delivery_unknown",
)
#: Префиксы публикационных событий (P0-семантика): читаем по префиксу, чтобы
#: новые коды не требовали правки этого файла.
PUBLICATION_PREFIXES = ("publication_", "initiative_publication_")

#: Виды публикационных событий: что именно они доказывают.
#: `sent` — единственный факт отправки; `cancelled`/`failed` — терминальный
#: отказ; `deferred` — отложено координацией (НЕ ошибка); `unknown` — доставка
#: не подтверждена и не опровергнута; `requested` — только заявка на бронь.
EVENT_SENT = "sent"
EVENT_CANCELLED = "cancelled"
EVENT_FAILED = "failed"
EVENT_DEFERRED = "deferred"
EVENT_UNKNOWN = "unknown"
EVENT_REQUESTED = "requested"
EVENT_OTHER = "other"
EVENT_INFO = "info"
#: Терминальные виды: последний по времени побеждает решение. `other` тоже
#: публикационное событие (пусть и незнакомое) — но он НЕ стирает строку и не
#: выдаёт себя за известный исход: см. `_kind_outcome`.
TERMINAL_EVENT_KINDS = (EVENT_SENT, EVENT_CANCELLED, EVENT_FAILED,
                        EVENT_DEFERRED, EVENT_UNKNOWN, EVENT_OTHER)

#: Причины координации публикаций (P0): незнакомое ИМЯ события с такой
#: причиной — это отложенная отправка, а не «неизвестно что».
COORDINATION_REASONS = ("publication_conflict", "publication_in_flight",
                        "publication_deferred_conflict")

OUTCOME_PUBLISHED = "published"
OUTCOME_DEFERRED = "deferred"
OUTCOME_UNKNOWN = "delivery_unknown"
OUTCOME_OTHER = "other"

#: S4-TRACE (§P0IM-PB-COUNT / §P0IM-BAN-CONFLATE): этапы журнала мема, по
#: которым считаются РАЗНЫЕ величины воронки. Выжимка и прикол — ровно два
#: LLM-вызова одной попытки; `image_generation` — запрос к Image API.
#: Значения сверяются с `meme_initiative.STAGE_*` тестом, чтобы словарь не
#: разъехался; импорт на уровне модуля дал бы цикл.
LLM_STAGE_NAMES = ("summary", "joke")
IMAGE_STAGE_NAME = "image_generation"
PUBLISH_STAGE_NAME = "publish"
#: Исход ПРОЙДЕННОГО этапа: `_finish` пишет `passed` всем не-терминальным
#: строкам. Нужен, чтобы «сгенерировано» опиралось на пройденную генерацию
#: изображения, а не на сам факт наличия строки этапа.
STAGE_OUTCOME_PASSED = "passed"
#: Причина терминального отказа ГЕНЕРАЦИИ изображения
#: (`meme_initiative.SKIP_IMAGE_FAILED`). Такой отказ тоже оставляет строку
#: этапа `image_generation`, но картинки не создал: «дошёл до провайдера» ≠
#: «получил изображение».
IMAGE_FAILED_REASON = "image_generation_failed"

#: Почему у шага нет длительности: журнал мема пишет ОДНУ метку времени
#: попытки (время старта) во все строки этапов, поэтому измеренной
#: длительности шага в записи нет. Это не «0 мс» и не «мгновенно».
STEP_TIMING_NOT_RECORDED = "step_timing_not_recorded"
DURATION_NOT_RECORDED = "duration_not_recorded"
#: Почему у шага нет фактической модели/провайдера/слота: запись этапа их не
#: хранит (R0: текст модели не пишется). Значение НЕ подставляется из текущих
#: настроек — настройка не доказывает, чем шёл прошлый вызов.
LLM_NOT_RECORDED_STAGE = "not_recorded_in_stage_record"
LLM_NOT_RECORDED_EVENT = "not_recorded_in_event_record"
#: Ключи записи, в которых модель/провайдер/слот МОГЛИ БЫ лежать. Читаются
#: как есть: появится записанное значение — оно и уедет в ответ.
LLM_RECORD_KEYS = ("provider", "model", "slot")

#: §P0IM-PB-ACCESS: полный текст запросов НЕ хранится в журнале попытки.
#: Единственный существующий носитель — bounded-кольцо композера
#: (`prompt_composer.provider_calls`): последние 24 записи на чат, память
#: процесса (рестарт/вытеснение теряет текст). Нового хранилища нет.
FULL_TEXT_NOT_RECORDED = "full_text_not_recorded"
FULL_TEXT_RING_MISS = "not_recorded"
FULL_TEXT_RING_LIMIT = 24
FULL_TEXT_STORAGE = (
    "Полный текст запроса не хранится в журнале попытки. Он доступен только "
    "в существующем Inspector из in-memory кольца композера "
    "(prompt_composer.provider_calls): последние 24 вызова на чат, до "
    "перезапуска процесса или вытеснения записью.")
FULL_TEXT_STEPS = (("summary", "meme_summary"), ("joke", "meme_joke"))


def _full_text_evidence(chat_id: int, job_id: str, historical: bool) -> dict:
    """Где искать полный текст шагов попытки — существующий Inspector.

    Ничего не создаёт: проверяет ТО ЖЕ кольцо `provider_calls`, которое
    отдаёт `GET /speech/inspector` (RBAC/masking — у него). Нет записи —
    честная причина (`not_recorded`/`full_text_not_recorded`), а не
    подстановка текущих настроек и не выдуманный correlation_id.
    """
    ref = _str(job_id).strip()
    calls: list[dict] = []
    if not historical and ref:
        try:
            from services import prompt_composer as composer
            calls = composer.provider_calls(chat_id=int(chat_id),
                                            limit=FULL_TEXT_RING_LIMIT)
        except Exception:
            logger.warning("[ini-pub] provider ring read failed", exc_info=True)
            calls = []
    recorded = {_str(c.get("correlation_id")) for c in calls
                if isinstance(c, dict)}
    steps: list[dict] = []
    for step, suffix in FULL_TEXT_STEPS:
        correlation = (ref + "#" + suffix) if ref and not historical else ""
        present = bool(correlation and correlation in recorded)
        reason = ""
        reason_detail = ""
        if historical:
            reason = FULL_TEXT_NOT_RECORDED
            reason_detail = "historical_row_without_correlation_id"
        elif not correlation:
            reason = FULL_TEXT_NOT_RECORDED
            reason_detail = "correlation_id_not_recorded"
        elif not present:
            reason = FULL_TEXT_RING_MISS
            reason_detail = "provider_ring_miss"
        steps.append({
            "step": step,
            "correlation_id": correlation,
            "recorded": present,
            "reason": reason,
            "reason_detail": reason_detail,
        })
    return {
        "available": any(item["recorded"] for item in steps),
        "storage": FULL_TEXT_STORAGE,
        "ring_limit": FULL_TEXT_RING_LIMIT,
        "ring_scope": "process_lifetime",
        "inspector": "/api/speech/inspector",
        "inspector_rbac": "can_edit_inspector",
        "steps": steps,
    }

#: Имя события → вид. Незнакомое `publication_*`/`initiative_publication_*`
#: классифицируется по `outcome` (см. `_publication_kind`), поэтому новые
#: коды P0 видны без правки списка.
_PUBLICATION_NAME_KINDS = {
    "publication_sent": EVENT_SENT,
    "initiative_sent": EVENT_SENT,
    "publication_cancelled": EVENT_CANCELLED,
    "publication_failed": EVENT_FAILED,
    "publication_deferred_conflict": EVENT_DEFERRED,
    "initiative_publication_conflict": EVENT_DEFERRED,
    "delivery_unknown": EVENT_UNKNOWN,
    "publication_requested": EVENT_REQUESTED,
    "initiative_publication_claim": EVENT_REQUESTED,
}


def _now() -> int:
    return int(time.time())


def _int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _str(value) -> str:
    return "" if value is None else str(value)


def _llm_fields(record: dict | None, reason_code: str) -> dict:
    """Фактические провайдер/модель/слот — РОВНО то, что лежит в записи.

    Запись этапа сегодня модели не хранит (R0: текст модели не пишется), поэтому
    честный ответ — ``null`` с причиной, а не значение из текущих настроек:
    настройка не доказывает, чем шёл уже состоявшийся вызов. Если запись (или
    вложенный ``llm``) всё же несёт такие ключи, они уезжают как есть.
    """
    data = record if isinstance(record, dict) else {}
    nested = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    out = {"provider": None, "model": None, "slot": None,
           "recorded_keys": [], "reason": ""}
    for key in LLM_RECORD_KEYS:
        value = data.get(key)
        if value is None:
            value = nested.get(key)
        text = _str(value).strip()
        if text:
            out[key] = text
            out["recorded_keys"].append(key)
    if not out["recorded_keys"]:
        out["reason"] = str(reason_code or "")
    return out


def _count_stage_names() -> dict:
    """Имена этапов для счётчиков — из словаря механизма (откат безопасен)."""
    try:
        from services import meme_initiative as mi
    except Exception:                        # pragma: no cover - defensive
        return {"llm": tuple(LLM_STAGE_NAMES), "image": IMAGE_STAGE_NAME,
                "publish": PUBLISH_STAGE_NAME}
    return {
        "llm": (mi.STAGE_SUMMARY, mi.STAGE_JOKE),
        "image": mi.STAGE_IMAGE,
        "publish": mi.STAGE_PUBLISH,
    }


def _step_timing(job_id) -> dict:
    """Длительность и ID запроса шага — из существующей записи, без догадок.

    Журнал мема пишет во все строки этапов ОДНУ метку времени (старт попытки) и
    не хранит длительность шага: поэтому ``duration_ms = null`` с причиной, а не
    ``0``. ID запроса записи есть — это ``job_id`` попытки (тот же родитель, по
    которому сходятся строки).
    """
    ref = _str(job_id).strip()
    return {
        "duration_ms": None,
        "duration_reason": STEP_TIMING_NOT_RECORDED,
        "request_id": ref,
        "request_id_source": "journal_job_id" if ref else "not_recorded",
    }


def _reason_label(code: str) -> str:
    """Русский ярлык причины — из ОБЩЕГО словаря инициативы."""
    try:
        from services import initiative_observer as obs
        return obs.reason_label(code)
    except Exception:
        return str(code or "")


def _event_names_sql(names: tuple) -> tuple[str, list]:
    if not names:
        return "", []
    parts = ["event_name IN (" + ",".join("?" * len(names)) + ")"]
    params: list = [*names]
    for prefix in PUBLICATION_PREFIXES:
        parts.append("event_name LIKE ?")
        params.append(prefix + "%")
    return " AND (" + " OR ".join(parts) + ")", params


def _is_publication_event(name: str) -> bool:
    text = _str(name)
    return any(text.startswith(prefix) for prefix in PUBLICATION_PREFIXES)


def _publication_kind(name: str, outcome: str, reason: str = "") -> str:
    """Вид публикационного события: имя важнее, `outcome` — уточнение.

    Незнакомое имя (новый код P0) НЕ теряется и НЕ стирает строку:
    * известный `outcome` (`success`/`cancelled`/`deferred`/`unknown`…) —
      берём его;
    * незнакомый `outcome`, но причина координации — это отложенная отправка;
    * иначе — `other`: строка остаётся, а сырое имя/`outcome` показываются
      как есть (новый код виден кодом, а не исчезает из журнала).
    """
    text = _str(name)
    known = _PUBLICATION_NAME_KINDS.get(text)
    if known:
        return known
    raw = _str(outcome).lower()
    if raw in ("success", "sent", "published", "delivered", "ok"):
        return EVENT_SENT
    if raw in ("cancelled", "canceled", "failed", "blocked", "expired"):
        return EVENT_CANCELLED
    if raw == "deferred":
        return EVENT_DEFERRED
    if raw in ("unknown", "delivery_unknown"):
        return EVENT_UNKNOWN
    # Незнакомое ИМЯ при незнакомом outcome: честная попытка узнать
    # координацию по причине (иначе — `other`, но строка сохраняется).
    code = _str(reason)
    if code in COORDINATION_REASONS or "conflict" in code:
        return EVENT_DEFERRED
    if text.endswith("_conflict") or text.endswith("_deferred"):
        return EVENT_DEFERRED
    return EVENT_OTHER


def _kind_outcome(kind: str, reason_code: str) -> tuple[str, str]:
    """Вид события → (outcome строки, reason_code).

    Для `other` outcome НИКОГДА не пустой: строка с незнакомым событием
    остаётся видимой (пустой outcome раньше выбрасывал попытку целиком).
    """
    if kind == EVENT_SENT:
        return OUTCOME_PUBLISHED, _str(reason_code)
    if kind == EVENT_DEFERRED:
        return OUTCOME_DEFERRED, _str(reason_code)
    if kind == EVENT_UNKNOWN:
        return OUTCOME_UNKNOWN, _str(reason_code)
    if kind == EVENT_CANCELLED:
        return "cancelled", _str(reason_code)
    if kind == EVENT_FAILED:
        return "failed", _str(reason_code)
    if kind == EVENT_OTHER:
        return OUTCOME_OTHER, _str(reason_code)
    return "", _str(reason_code)


async def _db(request: Request):
    from services import lore_runtime
    return lore_runtime.get_lore_db()


def _event_chain(facts: dict) -> list[dict]:
    """§1.3-цепочка попытки мема (`facts.events`, P0) — как есть, без правок.

    Форма записи (P0): ``name``, ``at``, ``run_id``, ``mode``, ``source``,
    ``reason``, ``detail`` (``"deferred|<detail>"`` для отложенных), ``after``,
    опционально ``delivered``. Ничего не пересчитываем: это журнал пайплайна.
    """
    raw = facts.get("events") if isinstance(facts, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append({
            "event_name": _str(item.get("name")),
            "ts": _int(item.get("at")),
            "outcome": _str(item.get("reason")) or _str(item.get("name")),
            "reason_code": _str(item.get("reason")),
            "reason_label": (_reason_label(_str(item.get("reason")))
                             if item.get("reason") else ""),
            "stage": _str(item.get("source")) or "attempt",
            "detail": _str(item.get("detail")),
            "delivered": (None if item.get("delivered") is None
                          else bool(item.get("delivered"))),
            "after": _str(item.get("after")),
            "level": "",
            "error_type": "",
        })
    return out


def _event_chain_reasons(facts: dict) -> list[str]:
    """Все причины и имена публикационных событий цепочки (для фильтра)."""
    out: list[str] = []
    for item in _event_chain(facts):
        for code in (item.get("reason_code"), item.get("event_name")):
            text = _str(code)
            if not text or text in out:
                continue
            if ("publication_" in text
                    or text in _PUBLICATION_NAME_KINDS
                    or text in ("delivery_unknown",)):
                out.append(text)
    return out


def _event_chain_has_deferred(facts: dict) -> bool:
    for item in _event_chain(facts):
        if (_PUBLICATION_NAME_KINDS.get(item.get("event_name")) == EVENT_DEFERRED
                or _str(item.get("detail")).startswith("deferred")):
            return True
    return False


async def _meme_attempt_rows(db, chat_id: int) -> tuple[list[dict], str]:
    """Строки журнала мема (этапы) — существующим ledger'ом, без SQL здесь."""
    try:
        from services import meme_initiative as mi
        ledger = mi.open_ledger(db)
    except Exception:
        logger.warning("[ini-pub] meme ledger open failed", exc_info=True)
        return [], "ledger_open_failed"
    if ledger is None:
        return [], "ledger_absent"
    try:
        if not ledger.table_present():
            return [], "schema_absent"
    except Exception:
        return [], "schema_unreadable"
    try:
        rows = ledger.attempts(int(chat_id), limit=MAX_ATTEMPT_ROWS)
    except Exception:
        logger.warning("[ini-pub] meme attempts read failed", exc_info=True)
        return [], "read_failed"
    return [dict(r) for r in rows or ()], ""


def _terminal_facts(items: list[dict]) -> dict:
    """Факты ТЕРМИНАЛЬНОЙ строки группы (последней по порядку этапов)."""
    try:
        from services import meme_initiative as mi
        stage_order = {name: idx for idx, name in enumerate(mi.STAGES)}
    except Exception:                       # pragma: no cover - defensive
        stage_order = {}
        mi = None                            # noqa: F841
    terminal = max(
        items,
        key=lambda row: (stage_order.get(_str(row.get("stage")),
                                         len(stage_order)),
                         _int(row.get("ts"))))
    try:
        from services import meme_initiative as mi
        return mi.parse_attempt_facts(terminal)
    except Exception:
        return {}


def _attempt_mode(items: list[dict]) -> str:
    """Режим попытки — ТОЛЬКО из терминальной строки (§3).

    У этапа «прикол» ключ `mode` занят бюджетом длины (`auto`/`fixed`), поэтому
    ранние строки группы режимом попытки не считаются: значение берётся из
    `attempt_mode`/`mode` терминальной строки, затем из её цепочки событий.
    """
    try:
        from services import meme_initiative as mi
    except Exception:                        # pragma: no cover - defensive
        return ""
    facts = _terminal_facts(items)
    mode = mi.attempt_mode_of(facts)
    if mode:
        return mode
    for item in facts.get("events") or ():
        if not isinstance(item, dict):
            continue
        raw = _str(item.get("mode"))
        if raw == "manual":
            return "manual"
        if raw in ("automatic", "auto"):
            return "auto"
    return ""


def _meme_attempts_grouped(rows: list[dict]) -> list[dict]:
    """Строки этапов → логические попытки (одна попытка = один ``job_id``)."""
    try:
        from services import meme_initiative as mi
        stage_order = {name: idx for idx, name in enumerate(mi.STAGES)}
    except Exception:                       # pragma: no cover - defensive
        stage_order = {}
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = _str(row.get("job_id")) or ("row:" + _str(row.get("attempt_id")))
        groups.setdefault(key, []).append(row)
    out: list[dict] = []
    for job_id, items in groups.items():
        def _order(row):
            stage = _str(row.get("stage"))
            return (stage_order.get(stage, len(stage_order) + 1),
                    _int(row.get("ts")))
        items.sort(key=_order)
        terminal = items[-1]
        chain = []
        published = False
        message_id = None
        manual = False
        reason_codes: list[str] = []
        events: list[dict] = []
        deferred_seen = False
        for row in items:
            facts = {}
            try:
                from services import meme_initiative as mi
                facts = mi.parse_attempt_facts(row)
            except Exception:
                facts = {}
            outcome = _str(row.get("outcome"))
            row_reason = _str(row.get("reason_code"))
            if outcome == OUTCOME_PUBLISHED:
                published = True
            for code in ([row_reason] + _event_chain_reasons(facts)):
                if code and code not in reason_codes:
                    reason_codes.append(code)
            if _event_chain_has_deferred(facts):
                deferred_seen = True
            events.extend(_event_chain(facts))
            pub_facts = facts.get("publish")
            if not isinstance(pub_facts, dict):
                pub_facts = facts.get("publication")
            if isinstance(pub_facts, dict):
                if pub_facts.get("manual") is True:
                    manual = True
                output = pub_facts.get("output")
                if isinstance(output, dict) and output.get("tg_message_id"):
                    message_id = _int(output.get("tg_message_id"), 0) or None
            chain.append({
                "stage": _str(row.get("stage")),
                "ts": _int(row.get("ts")),
                "outcome": outcome,
                "reason_code": row_reason,
                "facts": facts,
            })
        reason_code = _str(terminal.get("reason_code"))
        outcome = _str(terminal.get("outcome"))
        # Отложенный реальным конфликтом координации мем — НЕ ошибка: пока
        # нет терминального `sent`, он читается как «отложено». Терминальный
        # `published` (доставка после ожидания) остаётся публикацией.
        if (not published and deferred_seen
                and outcome in ("skipped", "blocked", "failed")
                and (not reason_code
                     or "conflict" in reason_code
                     or "deferred" in reason_code
                     or reason_code in ("in_flight", "publication_in_flight"))):
            outcome = OUTCOME_DEFERRED
        historical = job_id.startswith("row:")
        # §P0IM-BAN-CONFLATE (корректива Reviewer): «сгенерировано» — только
        # ДОКАЗАННАЯ картинка, а не факт достижения этапа `publish`.
        # Историческая строка `publish`/`skipped` без картинки (пустой родитель)
        # раньше считалась сгенерированной. Признак берётся из цепочки ЭТОЙ
        # попытки: пройденный этап `image_generation` (его пишет только
        # генерация, дошедшая до провайдера) И терминальный исход НЕ является
        # отказом генерации (`failed` + `image_generation_failed` — такой отказ
        # тоже оставляет строку этапа, но картинку не создал). Отложенная
        # реальным конфликтом публикация при готовой картинке остаётся
        # сгенерированной.
        image_ready = bool(
            any(step["stage"] == IMAGE_STAGE_NAME
                and step["outcome"] == STAGE_OUTCOME_PASSED
                for step in chain)
            and not (outcome == "failed"
                     and reason_code == IMAGE_FAILED_REASON)
        )
        # §3: режим — только из терминальной строки; поздний publication-факт
        # остаётся фолбэком для строк, записанных до появления `attempt_mode`.
        mode = _attempt_mode(items) or ("manual" if manual else "auto")
        out.append({
            "attempt_id": "meme:" + job_id,
            "kind": KIND_MEME,
            "job_id": job_id if not historical else "",
            "mode": mode,
            # §3: строка без родителя НЕ склеивается с другими и честно
            # помечается исторической — иначе две старые строки выглядели как
            # две «нормальные» попытки `row:old-0`/`row:old-1`.
            "incomplete_historical": historical,
            "ts": max((_int(r.get("ts")) for r in items), default=0),
            "stage": _str(terminal.get("stage")),
            "outcome": outcome,
            "reason_code": reason_code,
            "reason_label": _reason_label(reason_code) if reason_code else "",
            "delivered": (True if published
                          else (None if outcome in (OUTCOME_DEFERRED,
                                                    OUTCOME_UNKNOWN)
                                else False)),
            # §P0IM-BAN-CONFLATE: доказана ли картинка у ЭТОЙ попытки. Именно
            # это число (а не наличие этапа `publish`) суммирует `_rows`.
            "generated": image_ready,
            "message_id": message_id,
            "chain_len": len(chain),
            # S4-TRACE (§P0IM-PB-ROW): компактная последовательность этапов
            # ЭТОЙ попытки — из тех же строк журнала, без второго запроса.
            # Ошибка остаётся видимой в КОНКРЕТНОМ шаге строки списка.
            "stages": [
                {"stage": row["stage"], "outcome": row["outcome"],
                 "reason_code": row["reason_code"], "at": row["ts"]}
                for row in chain
            ],
            "reason_codes": reason_codes,
            "events_len": len(events),
            "window_messages": (
                _int(terminal.get("window_messages"), 0) or None),
            "limit_source": _str(terminal.get("limit_source")),
            "limit_value": (None if terminal.get("limit_value") is None
                            else _int(terminal.get("limit_value"))),
        })
    return out


async def _text_events(db, chat_id: int, since_ts: int) -> list[dict]:
    sql = "SELECT * FROM mca_events WHERE ts >= ? AND chat_id = ?"
    params: list = [int(since_ts), int(chat_id)]
    extra, extra_params = _event_names_sql(TEXT_EVENT_NAMES)
    sql += extra
    params.extend(extra_params)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(MAX_TEXT_EVENTS)
    try:
        cursor = await db.db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall() or ()]
    except Exception:
        logger.warning("[ini-pub] text events read failed", exc_info=True)
        return []


async def _delivered_outputs(db, chat_id: int, since_ts: int) -> list[dict]:
    sql = ("SELECT output_id, chat_id, tg_message_id, sent_at, correlation_id, "
           "delivery_status, output_kind FROM mca_bot_outputs "
           "WHERE sent_at >= ? AND chat_id = ? AND output_kind IN (?, ?) "
           "ORDER BY sent_at DESC LIMIT ?")
    params: list = [int(since_ts), int(chat_id), TEXT_OUTPUT_KIND,
                    MEME_OUTPUT_KIND, MAX_OUTPUTS]
    try:
        cursor = await db.db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall() or ()]
    except Exception:
        logger.warning("[ini-pub] outputs read failed", exc_info=True)
        return []


def _sum_reason_codes(acc: dict, code: str) -> None:
    """Накопитель причин попытки (для фильтра по причине и подсказок UI)."""
    text = _str(code)
    if not text:
        return
    codes = acc.setdefault("reason_codes", [])
    if text not in codes:
        codes.append(text)


def _text_attempts(events: list[dict], outputs: list[dict]) -> list[dict]:
    """События текста + ledger доставки → логические попытки (без дублей).

    Одна строка = один ``trace_id``. События обрабатываются в ХРОНОЛОГИЧЕСКОМ
    порядке, и **последнее реальное публикационное событие главнее решения**:
    оптимистичное «решение принято» не перетирает более позднюю отмену
    отправки (``publication_stale``) и не выдаёт себя за доставку. Обратный
    случай (решение «пропуск», затем ``publication_sent`` + запись в ledger)
    читается как «опубликовано», а не «пропуск с delivered=true».
    """
    by_corr: dict[str, dict] = {}
    for row in outputs:
        if _str(row.get("output_kind")) != TEXT_OUTPUT_KIND:
            continue
        corr = _str(row.get("correlation_id"))
        if corr:
            by_corr[corr] = row

    ordered = sorted(events, key=lambda r: (_int(r.get("ts")), _int(r.get("id"))))
    attempts: dict[str, dict] = {}
    for row in ordered:
        name = _str(row.get("event_name"))
        corr = _str(row.get("trace_id"))
        key = "text:" + (corr or _str(row.get("id")))
        ts = _int(row.get("ts"))
        reason = _str(row.get("reason_code"))
        is_decision = name == "initiative_decided"
        is_publication = (_is_publication_event(name)
                          or name in ("initiative_sent", "delivery_unknown"))
        kind = (_publication_kind(name, row.get("outcome"), reason)
                if is_publication else "")
        if not is_decision and not is_publication:
            # Писательские/перепроверочные события — только в трассу.
            acc = attempts.get(key)
            if acc is not None:
                acc["chain_len"] += 1
            continue
        acc = attempts.get(key)
        if acc is None:
            acc = {
                "attempt_id": key,
                "kind": KIND_TEXT,
                "job_id": corr,
                # §3: пустой trace_id — историческая строка без родителя.
                "incomplete_historical": not bool(corr),
                "mode": "auto",
                "ts": ts,
                "stage": (_str(row.get("stage"))
                          or ("decision" if is_decision else name)),
                "outcome": "",
                "reason_code": "",
                "reason_label": "",
                "delivered": None,
                "message_id": None,
                "chain_len": 0,
                "window_messages": None,
                "limit_source": "",
                "limit_value": None,
                "reason_codes": [],
                "other_events": [],
                "stages": [],
            }
            attempts[key] = acc
        acc["chain_len"] += 1
        acc["ts"] = max(_int(acc.get("ts")), ts)
        _sum_reason_codes(acc, reason)
        # S4-TRACE: компактная последовательность шагов ЭТОЙ попытки из тех же
        # событий (`initiative_decided` / публикационные) — без второго запроса
        # и без выдуманных этапов: только то, что реально записано.
        step = {
            "stage": _str(row.get("stage")) or name,
            "outcome": _str(row.get("outcome")) or (name if is_decision else ""),
            "reason_code": reason,
            "at": ts,
        }
        acc.setdefault("stages", []).append(step)
        if kind == EVENT_REQUESTED:
            # Заявка на бронь: строка попытки не создаётся, но в трассу и в
            # набор причин (для фильтра) она входит.
            continue
        if is_decision:
            # Решение описывает намерение, а не факт отправки: оно задаёт
            # исход только пока нет терминального публикационного факта.
            if not acc.get("_terminal"):
                acc["outcome"] = _str(row.get("outcome")) or "decided"
                acc["reason_code"] = reason
                acc["reason_label"] = _reason_label(reason) if reason else ""
                acc["delivered"] = (True if (corr and corr in by_corr)
                                    else False)
                acc["stage"] = acc["stage"] or "decision"
            continue
        # Публикационное событие: последнее по времени — истина об отправке.
        outcome, code = _kind_outcome(kind, reason)
        acc["_terminal"] = True
        acc["outcome"] = outcome
        acc["reason_code"] = code
        acc["reason_label"] = _reason_label(code) if code else ""
        acc["stage"] = _str(row.get("stage")) or name
        if kind == EVENT_SENT:
            acc["delivered"] = True
        elif kind in (EVENT_CANCELLED, EVENT_FAILED):
            acc["delivered"] = False
        else:
            acc["delivered"] = None
        if kind == EVENT_OTHER:
            # Незнакомое событие: строка сохранена и честно подписана сырым
            # именем/`outcome` — новый код P0 виден, а не стирает попытку.
            others = acc.setdefault("other_events", [])
            if len(others) < 5:
                others.append({"name": name,
                               "outcome": _str(row.get("outcome")),
                               "reason": reason})
            _sum_reason_codes(acc, name)

    # Доставки без события решения и без публикационного события — тоже
    # реальные публикации, не теряем.
    for corr, row in by_corr.items():
        key = "text:" + corr
        acc = attempts.get(key)
        if acc is not None:
            acc["delivered"] = True
            acc["message_id"] = _int(row.get("tg_message_id"), 0) or None
            if not acc.get("_terminal"):
                acc["outcome"] = OUTCOME_PUBLISHED
                acc["reason_code"] = ""
                acc["reason_label"] = ""
            continue
        attempts[key] = {
            "attempt_id": key,
            "kind": KIND_TEXT,
            "job_id": corr,
            "incomplete_historical": not bool(corr),
            "mode": "auto",
            "ts": _int(row.get("sent_at")),
            "stage": "send",
            "outcome": OUTCOME_PUBLISHED,
            "reason_code": "",
            "reason_label": "",
            "delivered": True,
            "message_id": _int(row.get("tg_message_id"), 0) or None,
            "chain_len": 1,
            "window_messages": None,
            "limit_source": "",
            "limit_value": None,
            "reason_codes": [],
            "stages": [{"stage": "send", "outcome": OUTCOME_PUBLISHED,
                        "reason_code": "", "at": _int(row.get("sent_at"))}],
        }

    out: list[dict] = []
    for acc in attempts.values():
        if not acc.get("outcome"):
            # Строка без исхода (только информативные события) не рисуется:
            # пустая деталь не должна становиться записью журнала.
            continue
        acc.pop("_terminal", None)
        out.append(acc)
    return out


@initiative_publications_router.get("/initiative/publications")
async def list_publications(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
    days: int = Query(default=7, ge=0, le=90),
    kind: str = Query(default="all"),
    mode: str = Query(default="all"),
    outcome: str = Query(default="all"),
    reason: str = Query(default="", max_length=64),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Логические попытки публикации (текст и мемы) одним списком.

    Фильтры серверные (период/тип/режим/исход/причина), пагинация — по
    смещению уже слитого списка. Пустые стадии не превращаются в строки:
    журнал мема без строк не даёт attempt вовсе.
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    await _require_chat_access(request, user, chat_id)
    now = _now()
    since = 0 if int(days or 0) <= 0 else now - int(days) * 86400
    db = await _db(request)
    notes: list[str] = []
    rows: list[dict] = []
    if db is None:
        notes.append("db_unavailable")
    else:
        meme_rows, meme_note = await _meme_attempt_rows(db, int(chat_id))
        if meme_note:
            notes.append("meme:" + meme_note)
        rows.extend(_meme_attempts_grouped(meme_rows))
        events = await _text_events(db, int(chat_id), since)
        outputs = await _delivered_outputs(db, int(chat_id), since)
        rows.extend(_text_attempts(events, outputs))
    rows = [r for r in rows if r["ts"] >= since]
    if kind and kind != "all":
        rows = [r for r in rows if r["kind"] == kind]
    if mode and mode != "all":
        rows = [r for r in rows if r["mode"] == mode]
    if outcome and outcome != "all":
        rows = [r for r in rows if r["outcome"] == outcome]
    reason_text = _str(reason).strip().lower()
    if reason_text:
        # Фильтр по причине смотрит и на ТЕКУЩУЮ причину строки, и на причины
        # всей цепочки (отложенный конфликт, а затем доставка — строка должна
        # находиться по коду конфликта, хоть её исход уже `published`).
        rows = [r for r in rows
                if reason_text in r["reason_code"].lower()
                or reason_text in _str(r.get("reason_label")).lower()
                or any(reason_text in _str(code).lower()
                       for code in (r.get("reason_codes") or []))]
    rows.sort(key=lambda r: (-_int(r["ts"]), r["attempt_id"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    next_offset = offset + len(page) if offset + len(page) < total else None
    # Счётчики — РАЗНЫЕ факты воронки, а не одно число: «проверено» (все
    # попытки в окне) ≠ «решено» (есть записанный исход) ≠ «сгенерировано»
    # (у попытки ДОКАЗАНА картинка — этап `image_generation`, а не достижение
    # `publish`) ≠ «опубликовано» ≠ «доставлено» (есть message_id) ≠ «ожидает»
    # (исход deferred). Окно называется явно, чтобы число нельзя было прочитать
    # как «за всё время». `llm_calls`/`images` — вызовы, записанные этапами
    # ТОГО ЖЕ окна (выжимка+прикол и Image API, §P0IM-PB-COUNT).
    stage_names = _count_stage_names()
    decided = sum(1 for r in rows if _str(r.get("outcome")))
    delivered = sum(1 for r in rows if r.get("delivered") is True)
    pending = sum(1 for r in rows if r.get("outcome") == OUTCOME_DEFERRED)
    delivery_unknown = sum(1 for r in rows
                           if r.get("delivered") is None
                           and r.get("outcome") != OUTCOME_DEFERRED)
    llm_calls = 0
    images = 0
    generated = 0
    for row in rows:
        names = [_str(s.get("stage")) for s in (row.get("stages") or ())
                 if isinstance(s, dict)]
        llm_calls += sum(1 for name in names if name in stage_names["llm"])
        images += sum(1 for name in names if name == stage_names["image"])
        # §P0IM-BAN-CONFLATE: считаем ТОЛЬКО доказанную картинку, которую
        # вычислил группировщик по цепочке этапов. Наличие `publish` —
        # недостаточное условие (историческая строка `publish`/`skipped`).
        if row.get("generated") is True:
            generated += 1
    return {
        "schema_version": 1,
        "generated_at": now,
        "chat_id": _int(chat_id),
        "available": db is not None,
        "notes": notes,
        "window": {"days": int(days), "since": int(since), "until": int(now)},
        "filters": {"days": int(days), "kind": kind, "mode": mode,
                    "outcome": outcome, "reason": _str(reason)},
        "counts": {
            "total": total,
            "checked": total,
            "decided": decided,
            "generated": generated,
            "text": sum(1 for r in rows if r["kind"] == KIND_TEXT),
            "meme": sum(1 for r in rows if r["kind"] == KIND_MEME),
            "published": sum(1 for r in rows
                             if r["outcome"] == OUTCOME_PUBLISHED),
            "delivered": delivered,
            "pending": pending,
            "delivery_unknown": delivery_unknown,
            "not_delivered": sum(1 for r in rows if r["delivered"] is False),
            "deferred": pending,
            "unknown": sum(1 for r in rows
                           if r["outcome"] == OUTCOME_UNKNOWN),
            "llm_calls": llm_calls,
            "images": images,
        },
        "rows": page,
        "next_offset": next_offset,
    }


def _event_public(row: dict) -> dict:
    """R17-safe поля события (без сырых текстов/секретов)."""
    duration = (None if row.get("duration_ms") is None
                else _int(row.get("duration_ms")))
    trace_id = _str(row.get("trace_id")).strip()
    return {
        "id": _int(row.get("id")),
        "ts": _int(row.get("ts")),
        "event_name": _str(row.get("event_name")),
        "stage": _str(row.get("stage")),
        "outcome": _str(row.get("outcome")),
        "reason_code": _str(row.get("reason_code")),
        "reason_label": (_reason_label(_str(row.get("reason_code")))
                         if row.get("reason_code") else ""),
        "level": _str(row.get("level")),
        "duration_ms": duration,
        # §P0IM-PB-STEP: «длительность не измерена» — отдельная причина, а не 0.
        "duration_reason": ("" if duration is not None
                            else DURATION_NOT_RECORDED),
        # ID запроса шага — записанный `trace_id` события (родитель попытки).
        "request_id": trace_id,
        "request_id_source": ("event_trace_id" if trace_id
                              else "not_recorded"),
        # §P0IM-PB-LLM: запись события модель/провайдера/слот не хранит.
        "llm": _llm_fields(row, LLM_NOT_RECORDED_EVENT),
        "error_type": _error_type(row.get("error_json")),
    }


def _error_type(raw) -> str:
    text = _str(raw).strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return ""
    if isinstance(data, dict):
        return _str(data.get("type") or data.get("error_type") or "")
    return ""


@initiative_publications_router.get("/initiative/publications/detail")
async def publication_detail(
    request: Request,
    user: Annotated[WebAppUser, Depends(get_tma_user)],
    x_chat_id: Annotated[str | None, Header()] = None,
    attempt_id: str = Query(default="", max_length=200),
):
    """Трасса РОВНО одной попытки (вкладка «Диагностика»).

    Мем: все строки этапов этого ``job_id`` (факты этапов как есть — их
    обрезает пайплайн). Текст: события по ``trace_id`` (решение, отправка,
    перепроверка, будущие ``publication_*``) + факт доставки из ledger.
    """
    chat_id = _chat_id_or_none(x_chat_id)
    if chat_id is None:
        raise HTTPException(status_code=422, detail="нужен X-Chat-Id")
    await _require_chat_access(request, user, chat_id)
    key = _str(attempt_id).strip()
    if not key:
        raise HTTPException(status_code=422, detail="нужен attempt_id")
    db = await _db(request)
    if db is None:
        return {"schema_version": 1, "available": False,
                "notes": ["db_unavailable"], "attempt": None, "chain": [],
                "events": [], "delivery": None}
    if key.startswith("meme:"):
        job_id = key[len("meme:"):]
        rows, note = await _meme_attempt_rows(db, int(chat_id))
        if job_id.startswith("row:"):
            # Историческая строка без родителя: её ключ — `attempt_id`, а не
            # `job_id` (склеивать такие строки по времени запрещено).
            ident = job_id[len("row:"):]
            rows = [r for r in rows if _str(r.get("attempt_id")) == ident]
        else:
            rows = [r for r in rows if _str(r.get("job_id")) == job_id]
        attempts = {a["attempt_id"]: a for a in _meme_attempts_grouped(rows)}
        attempt = attempts.get(key)
        detail = _meme_attempts_grouped(rows)
        chain = []
        for row in rows:
            try:
                from services import meme_initiative as mi
                facts = mi.parse_attempt_facts(row)
            except Exception:
                facts = {}
            chain.append({
                "stage": _str(row.get("stage")),
                "ts": _int(row.get("ts")),
                "outcome": _str(row.get("outcome")),
                "reason_code": _str(row.get("reason_code")),
                "reason_label": (_reason_label(_str(row.get("reason_code")))
                                 if row.get("reason_code") else ""),
                "facts": facts,
                "limit_source": _str(row.get("limit_source")),
                "limit_value": (None if row.get("limit_value") is None
                                else _int(row.get("limit_value"))),
                "window_messages": (None if row.get("window_messages") is None
                                    else _int(row.get("window_messages"))),
                # §P0IM-PB-STEP: длительность шага и ID запроса. Длительность
                # в журнале не измеряется (одна метка времени попытки) — честный
                # null с причиной; ID запроса берётся из записи (`job_id`).
                **_step_timing(row.get("job_id")),
                # §P0IM-PB-LLM: чем реально шёл шаг — только из записи.
                "llm": _llm_fields(facts, LLM_NOT_RECORDED_STAGE),
            })
        chain.sort(key=lambda r: (r["ts"], r["stage"]))
        # §1.3-цепочка событий попытки (P0) — из фактов этапов, как записано
        # пайплайном: время, run id (source), причина, detail, delivered,
        # ссылка на предыдущий этап. Именно она показывает
        # `publication_deferred_conflict` / `publication_cancelled` и т.п.
        events: list[dict] = []
        for entry in chain:
            for item in _event_chain(entry.get("facts") or {}):
                events.append(item)
        events.sort(key=lambda e: e["ts"])
        for ev in events:
            ev["id"] = None
        return {
            "schema_version": 1,
            "available": True,
            "notes": [note] if note else [],
            "attempt": attempt,
            "chain": chain,
            "events": events,
            # §P0IM-PB-ACCESS: где искать полный текст (существующий Inspector),
            # политика хранения названа явно; отсутствие — not_recorded.
            "full_text": _full_text_evidence(
                int(chat_id), job_id, job_id.startswith("row:")),
            "delivery": {
                "delivered": (None if attempt is None else attempt["delivered"]),
                "message_id": (None if attempt is None
                               else attempt["message_id"]),
            },
        }
    if key.startswith("text:"):
        corr = key[len("text:"):]
        events: list[dict] = []
        if corr:
            since = _now() - 30 * 86400
            sql = ("SELECT * FROM mca_events WHERE ts >= ? AND chat_id = ? "
                   "AND (trace_id = ? OR entity_ids LIKE ?) "
                   "ORDER BY ts ASC LIMIT ?")
            try:
                cursor = await db.db.execute(
                    sql, (int(since), int(chat_id), corr, "%" + corr + "%",
                          TRACE_EVENTS_LIMIT))
                events = [_event_public(dict(r))
                          for r in await cursor.fetchall() or ()]
            except Exception:
                logger.warning("[ini-pub] trace read failed", exc_info=True)
        delivery = None
        if corr:
            try:
                cursor = await db.db.execute(
                    "SELECT tg_message_id, sent_at, delivery_status, "
                    "output_kind FROM mca_bot_outputs "
                    "WHERE chat_id = ? AND correlation_id = ? "
                    "ORDER BY sent_at DESC LIMIT 1", (int(chat_id), corr))
                row = await cursor.fetchone()
                if row is not None:
                    row = dict(row)
                    delivery = {
                        "delivered": True,
                        "message_id": _int(row.get("tg_message_id"), 0) or None,
                        "sent_at": _int(row.get("sent_at")),
                        "delivery_status": _str(row.get("delivery_status")),
                        "output_kind": _str(row.get("output_kind")),
                    }
            except Exception:
                logger.warning("[ini-pub] delivery read failed", exc_info=True)
        attempt = {
            "attempt_id": key,
            "kind": KIND_TEXT,
            "job_id": corr,
            "mode": "auto",
            "ts": (events[0]["ts"] if events else 0),
            "stage": (events[-1]["stage"] if events else ""),
            "outcome": (events[-1]["outcome"] if events else ""),
            "reason_code": (events[-1]["reason_code"] if events else ""),
            "delivered": (None if delivery is None else True),
            "message_id": (None if delivery is None else delivery["message_id"]),
        }
        return {
            "schema_version": 1,
            "available": True,
            "notes": [] if events else ["trace_empty"],
            "attempt": attempt,
            "chain": [],
            "events": events,
            # У текстовой трассы полного текста шага нет: кольцо ключуется
            # корреляцией мем-этапов, поэтому честный None (не новый store).
            "full_text": None,
            "delivery": delivery,
        }
    raise HTTPException(status_code=422, detail="неизвестный attempt_id")
