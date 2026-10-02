"""ASAP-4 волна E (T-4440–T-4445, spec §5 E.1/E.2, ADR-1028-7 D8) —
Pipeline Analytics: нормализованная модель стадий §61.11 + Run Inspector.

Единый адаптер поверх mca-17a: **вторая аналитика с собственной истиной
запрещена** (§61.11). Источники данных — ТОЛЬКО structured state:

  * durable `mca_events` (SQLite, v19-колонки) — стадийные события
    SUMMARY_* (волна E, `pipeline_events`) + COVER_* (волна B,
    `cover_style_jobs.emit_cover_event`) с `pipeline_run_id = run_id`;
  * in-memory снапшоты прогона (`execution_graph_source`, S7/S8 RunContext);

human-логи НЕ читаются (§61.12 — guard-тест T-4445).

Модель узла (§61.1–§61.3): статус ✓/⚠/✕/○/… (цвет НЕ единственный носитель —
текстовый label обязателен), причина → человеческий русский перевод, explain
1–3 строки. Health run (§61.6/§61.13) = publication_status × source_coverage:
публикация при coverage<100% — degraded (не healthy); только текстовые
бейджи («Здоров»/«С деградацией»/«Не издано»/«Не завершён»), без opaque
score. Repair ≠ fallback ≠ failure — разные состояния (§61.7).

R17: наружу только числа/коды/id/enum; без ключей/промптов/сырых текстов.
"""
from __future__ import annotations

import time
from collections import Counter

# ── каноническая топология узлов (§61.1/§60) ────────────────────────────────
NODE_SOURCE = "source"
NODE_L1 = "l1"
NODE_L2 = "l2"
NODE_L2_REVIEW = "l2_review"
NODE_LEGACY = "legacy"
NODE_STYLE_SELECTION = "style_selection"
NODE_BASE_COVER = "base_cover"
NODE_STYLE_EDIT = "style_edit"
NODE_PUBLISH = "publish"

TEXT_BRANCH = "text"
COVER_BRANCH = "cover"

# ── состояния узла (§61.2 статусы + §61.7 repair/fallback/failure) ──────────
STATE_SUCCESS = "success"       # ✓
STATE_REPAIRED = "repaired"     # ⚠ — stage сам исправил и продолжил
STATE_FALLBACK = "fallback"     # ⚠ — stage упал, резервный контур спас run
STATE_FAILED = "failed"         # ✕ — функция не выполнена downstream'ом
STATE_SKIPPED = "skipped"       # ○ — skipped by design
STATE_RUNNING = "running"       # … — выполняется
STATE_PENDING = "pending"       # ○ — ожидает (running-run хвост, §61.15)

ICONS = {
    STATE_SUCCESS: "✓", STATE_REPAIRED: "⚠", STATE_FALLBACK: "⚠",
    STATE_FAILED: "✕", STATE_SKIPPED: "○", STATE_RUNNING: "…",
    STATE_PENDING: "○",
}

# ── health run (§61.6/§61.13) — только текстовые бейджи, без score ──────────
HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_FAILED = "failed"
HEALTH_INCOMPLETE = "incomplete"
HEALTH_RUNNING = "running"
HEALTH_LABELS_RU = {
    HEALTH_HEALTHY: "Здоров",
    HEALTH_DEGRADED: "С деградацией",
    HEALTH_FAILED: "Не издано",
    HEALTH_INCOMPLETE: "Не завершён",
    HEALTH_RUNNING: "Выполняется",
}

COVERAGE_FULL_EPSILON = 99.95   # 100% минус погрешность округления float

# ── RU-переводы reason-кодов (§61.3; волны A–D) ─────────────────────────────
REASONS_RU = {
    # §61.3 — обязательные.
    "too_many_facts": ("L1 вернул больше фактов, чем текущий контракт смог "
                       "принять."),
    "quote_speaker_mismatch": ("Текст цитаты найден, но не удалось "
                               "подтвердить, что её сказал указанный "
                               "человек."),
    "rate_limit": "Провайдер временно ограничил частоту запросов.",
    "reference_missing": "Не найден обязательный файл-референс стиля.",
    # Волна C — quote-контур.
    "quote_text_not_found": "Текст цитаты не найден в исходных сообщениях.",
    "quote_speaker_unresolved": ("Не удалось определить, кто произнёс "
                                 "цитату."),
    "quote_source_ambiguous": ("Цитата соответствует нескольким сообщениям — "
                               "источник неоднозначен."),
    "quote_attribution_repaired": ("Неподтверждённая цитата безопасно "
                                   "исправлена, статья принята."),
    # Волна C — capacity/Legacy.
    "too_many_threads": "Разговор разбит на слишком много тем для одного чанка.",
    "too_many_facts_total": "Суммарно слишком много фактов для одного саммари.",
    "l1_capacity_repaired": "Переполнение фактов исправлено без потери тем.",
    "l1_capacity_sharded": "Окно разделено на несколько чанков (планировщик).",
    "legacy_full_window": "Использовано полное окно истории (без тихой обрезки).",
    "legacy_coverage_degraded": ("Часть источника не вошла в саммари — "
                                 "coverage ниже 100%."),
    # Волна D — review/revision.
    "l2_review_rejected": ("Проверка отклонила статью после повторов — "
                           "отправлена в резервный контур."),
    "l2_review_unusable": ("Ответ писателя не удалось разобрать — резервный "
                           "контур."),
    "review_degraded": ("Проверка временно недоступна — статья опубликована "
                        "без семантической проверки."),
    # Волна B — cover style.
    "no_style": "Стиль не выбран («Без дополнительного стиля»).",
    "profile_missing": "Профиль стиля не найден.",
    "disabled": "Профиль стиля отключён.",
    "edit_unsupported": "Модель не умеет редактировать готовые изображения.",
    "connection_missing": "Подключение модели не найдено (удалено или недоступно).",
    "capability_unknown": "Возможности модели не определены.",
    "not_configured": "Не настроены адрес/модель обработки (Connections layer).",
    "style_failed": "Обработка стилем не завершилась (ошибка провайдера).",
    "base_failed": "Базовая обложка не создалась.",
    "rich_failed": "Не удалось отправить оформленное сообщение.",
    "style_stage_not_applicable": "Режим профиля без стадии стиля.",
    # Волна A — embeddings.
    "paused_rate_limit": "Пауза из-за лимита провайдера (429).",
    "paused_provider": "Пауза: провайдер недоступен.",
    "auth_failed": "Доступ провайдера отклонён (ключ/права).",
    "validation_failed": "Проверка индекса не пройдена (векторы сохранены).",
    "quota_group_cooling_down": "Группа ключей охлаждается после лимита.",
    "quota_group_exhausted": "Дневная квота группы исчерпана.",
    # Общие.
    "fallback_engaged": "Основной контур не завершился — использован резервный.",
    "provider_unavailable": "Провайдер временно недоступен.",
    "provider_unconfigured": "Провайдер не настроен.",
    "timeout": "Превышено время ожидания ответа провайдера.",
    "parse_error": "Ответ модели не удалось разобрать.",
    "model_unavailable": "Модель недоступна.",
    "budget_exceeded": "Превышен бюджет вызовов/токенов.",
    "delivery_unknown": "Доставка не подтверждена.",
    "empty": "Пустой результат этапа.",
}

# ── пояснения стадий (§61.3: 1–3 короткие строки) ───────────────────────────
NODE_EXPLAIN_RU = {
    NODE_SOURCE: ("Собирает все сообщения из выбранного временного окна. "
                  "Здесь видно, сколько сообщений реально дошло до саммари."),
    NODE_L1: ("Разбирает разговор на темы, события и факты. Не пишет "
              "итоговую статью."),
    NODE_L2: ("Пишет связную статью по подготовленным фактам и проверяет "
              "атрибуцию."),
    NODE_L2_REVIEW: ("Отдельная проверка статьи: факты, имена, числа, "
                     "цитаты. До двух исправлений, затем резервный контур."),
    NODE_LEGACY: ("Резервный генератор текста. Используется, если Hybrid не "
                  "смог безопасно закончить статью."),
    NODE_STYLE_SELECTION: ("Проверяет, какой визуальный стиль выбран для "
                           "чата, ещё до генерации обложки."),
    NODE_BASE_COVER: "Создаёт обычную обложку по содержанию саммари.",
    NODE_STYLE_EDIT: ("Берёт готовую базовую обложку и применяет выбранный "
                      "визуальный стиль."),
    NODE_PUBLISH: "Собирает текст, кат и картинку в RichMessage.",
}

# ── события durable-стора → узлы ────────────────────────────────────────────
_COVER_BASE_OK = "COVER_BASE_SUCCEEDED"
_COVER_BASE_FAIL = "COVER_BASE_FAILED"
_STYLE_OK = "COVER_STYLE_SUCCEEDED"
_STYLE_FAIL = "COVER_STYLE_FAILED"
_STYLE_SKIP = "COVER_STYLE_SKIPPED"
_STYLE_START = "COVER_STYLE_START"
_SELECTION = "COVER_STYLE_SELECTION"
_RICH_OK = "COVER_RICH_PUBLISH_SUCCEEDED"
_RICH_FAIL = "COVER_RICH_PUBLISH_FAILED"
_PLAIN_FALLBACK = "COVER_PLAIN_FALLBACK"

# Причины, означающие repair (не failure) — §61.7.
_REPAIR_REASONS = frozenset({
    "quote_attribution_repaired", "l1_capacity_repaired",
    "l1_capacity_sharded",
})


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_usage(raw) -> dict:
    """usage_json (строка/None) → dict (bounded, fail-open)."""
    import json
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def reason_ru(code) -> str:
    """Человеческий перевод причины (§61.3); неизвестный код — как есть."""
    code = str(code or "").strip()
    if not code:
        return ""
    return REASONS_RU.get(code, "")


def _node(key, label, branch, state, *, reason_code=None, latency_ms=None,
          attempts=None, provider=None, model=None, counts=None,
          detail=None) -> dict:
    """Канонический узел карты пайплайна (§61.1/§61.2)."""
    reason_code = str(reason_code or "") or None
    return {
        "key": key,
        "label": label,
        "branch": branch,
        "state": state,
        "icon": ICONS.get(state, "○"),
        "status_label": _state_label(state),
        "reason_code": reason_code,
        "reason_ru": reason_ru(reason_code),
        "explain": NODE_EXPLAIN_RU.get(key, ""),
        "latency_ms": latency_ms,
        "attempts": attempts,
        "provider": provider,
        "model": model,
        "counts": counts or {},
        "detail": detail or [],
    }


def _state_label(state: str) -> str:
    return {
        STATE_SUCCESS: "успешно",
        STATE_REPAIRED: "исправлено, продолжено",
        STATE_FALLBACK: "резервный контур",
        STATE_FAILED: "не выполнено",
        STATE_SKIPPED: "пропущено",
        STATE_RUNNING: "выполняется",
        STATE_PENDING: "ожидает",
    }.get(state, state)


def _cover_label(style_id) -> str:
    return "Стиль: %s" % style_id if style_id else "Стиль"


def build_run_view(run_id, snapshot, events, *, running: bool = False) -> dict:
    """Модель одного run для UI (§61.1/§61.8/§61.9) из structured state.

    `snapshot` — in-memory снапшот прогона (или None); `events` — список
    строк `mca_events` этого run (dict). `running=True` — прогон ещё идёт:
    хвостовая топология показывается как ○ «ожидает» (§61.15).
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    by_name: dict = {}
    for ev in (events or []):
        if not isinstance(ev, dict):
            continue
        name = str(ev.get("event_name") or "")
        if not name:
            continue
        by_name.setdefault(name, []).append(ev)

    def last(name):
        rows = by_name.get(name) or []
        return rows[-1] if rows else None

    def _lat(ev):
        return _float(ev.get("duration_ms")) if ev else None

    done_row = last("SUMMARY_RUN_DONE")
    usage = _parse_usage((done_row or {}).get("usage_json"))
    nodes: list = []

    # ── ТЕКСТОВАЯ ветка ────────────────────────────────────────────────
    src_ev = last("SUMMARY_SOURCE_WINDOW")
    src_count = _int((snapshot.get("source_count")))
    src_total = _int(snapshot.get("source_total")) or src_count
    src_considered = _int(snapshot.get("source_considered")) or _int(
        usage.get("source_considered"))
    counts = {"input": _int(_parse_usage(
        (src_ev or {}).get("usage_json")).get("input_count")) or src_count}
    if src_ev is not None or src_count is not None:
        detail = []
        if src_total is not None:
            detail.append({"k": "Сообщений в источнике", "v": src_total})
        if src_considered is not None:
            detail.append({"k": "Взято в саммари", "v": src_considered})
        nodes.append(_node(
            NODE_SOURCE, "Источник", TEXT_BRANCH, STATE_SUCCESS,
            counts={k: v for k, v in counts.items() if v is not None},
            detail=detail))

    l1_ev = last("SUMMARY_L1_STAGE")
    if l1_ev is not None:
        failed = str(l1_ev.get("outcome") or "") == "failed"
        state = STATE_FAILED if failed else STATE_SUCCESS
        lu = _parse_usage(l1_ev.get("usage_json"))
        nodes.append(_node(
            NODE_L1, "L1 · Кластеризатор", TEXT_BRANCH, state,
            reason_code=l1_ev.get("reason_code"), latency_ms=_lat(l1_ev),
            counts={"out": _int(lu.get("threads"))},
            detail=[{"k": "Тем выделено", "v": lu.get("threads")}
                    if lu.get("threads") is not None else None]))
        nodes[-1]["detail"] = [d for d in nodes[-1]["detail"] if d]

    l2_ev = last("SUMMARY_L2_STAGE")
    if l2_ev is not None:
        failed = str(l2_ev.get("outcome") or "") == "failed"
        nodes.append(_node(
            NODE_L2, "L2 · Писатель", TEXT_BRANCH,
            STATE_FAILED if failed else STATE_SUCCESS,
            reason_code=l2_ev.get("reason_code"), latency_ms=_lat(l2_ev),
            model=l2_ev.get("model"), provider=l2_ev.get("provider"),
            counts={"out": _int(_parse_usage(
                l2_ev.get("usage_json")).get("output_count"))}))

    review_ev = last("SUMMARY_L2_REVIEW")
    if review_ev is not None:
        status = str(review_ev.get("status") or "")
        state = {
            "ok": STATE_SUCCESS, "repaired": STATE_REPAIRED,
            "degraded": STATE_REPAIRED, "failed": STATE_FALLBACK,
        }.get(status, STATE_SUCCESS)
        ru = _parse_usage(review_ev.get("usage_json"))
        detail = []
        if ru.get("revision_count"):
            detail.append({"k": "Итераций исправления",
                           "v": ru.get("revision_count")})
        if ru.get("revision_fixed"):
            detail.append({"k": "Исправлено ревизией",
                           "v": ru.get("revision_fixed")})
        nodes.append(_node(
            NODE_L2_REVIEW, "L2 · Проверка", TEXT_BRANCH, state,
            reason_code=review_ev.get("reason_code"),
            attempts=_int(review_ev.get("attempt")),
            detail=detail))

    legacy_ev = last("SUMMARY_LEGACY_FALLBACK")
    if legacy_ev is not None:
        lu = _parse_usage(legacy_ev.get("usage_json"))
        nodes.append(_node(
            NODE_LEGACY, "Legacy · Резервный контур", TEXT_BRANCH,
            STATE_FALLBACK, reason_code=legacy_ev.get("reason_code"),
            detail=[{"k": "Точка перехода",
                     "v": "L2" if str(lu.get("fallback_from") or "").startswith(
                         "l2") else str(lu.get("fallback_from") or "—")}
                    ]))

    # ── ВЕТКА ОБЛОЖКИ (независима от текстовой, §61.8) ─────────────────
    sel_ev = last(_SELECTION)
    style_id = (sel_ev or {}).get("style_id")
    if sel_ev is not None:
        nodes.append(_node(
            NODE_STYLE_SELECTION, "Выбор стиля", COVER_BRANCH,
            STATE_SUCCESS, detail=[
                {"k": "Выбран", "v": style_id or "нет («Без стиля»)"},
                {"k": "Источник выбора",
                 "v": str(sel_ev.get("status") or "chat")},
            ] if style_id else [
                {"k": "Выбран", "v": "нет («Без стиля»)"},
            ]))

    base_ok = last(_COVER_BASE_OK)
    base_fail = last(_COVER_BASE_FAIL)
    cover_status = snapshot.get("cover_status")
    if base_ok is not None or base_fail is not None or cover_status:
        if base_fail is not None and base_ok is None:
            state, reason = STATE_FAILED, base_fail.get("reason_code")
        elif cover_status == "unavailable" and base_ok is None:
            state, reason = STATE_FAILED, "base_failed"
        else:
            state, reason = STATE_SUCCESS, None
        nodes.append(_node(
            NODE_BASE_COVER, "Базовая обложка", COVER_BRANCH, state,
            reason_code=reason, latency_ms=_lat(base_ok or base_fail),
            model=(base_ok or base_fail or {}).get("model"),
            provider=(base_ok or base_fail or {}).get("provider")))

    style_ok = last(_STYLE_OK)
    style_fail = last(_STYLE_FAIL)
    style_skip = last(_STYLE_SKIP)
    style_start = last(_STYLE_START)
    if style_ok is not None:
        state = STATE_SUCCESS
        ev = style_ok
    elif style_fail is not None:
        state = STATE_FALLBACK       # провал стиля → base cover спас (§61.7)
        ev = style_fail
    elif style_skip is not None:
        state = STATE_SKIPPED
        ev = style_skip
    elif style_start is not None:
        state, ev = STATE_RUNNING, style_start
    else:
        state, ev = None, None
    if ev is not None and state is not None:
        nodes.append(_node(
            NODE_STYLE_EDIT, _cover_label(style_id), COVER_BRANCH, state,
            reason_code=ev.get("reason_code"), latency_ms=_lat(ev),
            attempts=_int(ev.get("attempt")), model=ev.get("model"),
            provider=ev.get("provider")))

    rich_ok = last(_RICH_OK)
    rich_fail = last(_RICH_FAIL)
    plain = last(_PLAIN_FALLBACK)
    pub_channel = snapshot.get("publish_channel")
    pub_status = snapshot.get("publish_status")
    if rich_ok is not None or rich_fail is not None or plain is not None \
            or pub_status:
        if rich_fail is not None or plain is not None:
            state = STATE_FALLBACK    # rich упал → plain спас текст (§61.7)
            reason = (rich_fail or {}).get("reason_code") or "rich_failed"
        elif pub_status == "failed":
            state, reason = STATE_FAILED, snapshot.get("reason") or "rich_failed"
        else:
            state, reason = STATE_SUCCESS, None
        nodes.append(_node(
            NODE_PUBLISH, "Публикация", COVER_BRANCH, state,
            reason_code=reason, latency_ms=_lat(rich_ok or rich_fail),
            detail=[
                {"k": "Канал", "v": "rich" if pub_channel == "rich"
                 else "plain" if pub_channel == "text" else "rich"},
                {"k": "Message id",
                 "v": _int(snapshot.get("publish_message_id"))},
            ] if pub_status else []))

    # Running-run (§61.15): хвостовая топология ○ «ожидает».
    if running:
        present = {n["key"] for n in nodes}
        tail = [NODE_L2_REVIEW, NODE_LEGACY, NODE_STYLE_SELECTION,
                NODE_BASE_COVER, NODE_STYLE_EDIT, NODE_PUBLISH]
        for key in tail:
            if key not in present:
                label = {
                    NODE_L2_REVIEW: "L2 · Проверка",
                    NODE_LEGACY: "Legacy · Резервный контур",
                    NODE_STYLE_SELECTION: "Выбор стиля",
                    NODE_BASE_COVER: "Базовая обложка",
                    NODE_STYLE_EDIT: "Стиль",
                    NODE_PUBLISH: "Публикация",
                }[key]
                nodes.append(_node(
                    key, label,
                    COVER_BRANCH if key in (NODE_STYLE_SELECTION,
                                            NODE_BASE_COVER,
                                            NODE_STYLE_EDIT, NODE_PUBLISH)
                    else TEXT_BRANCH,
                    STATE_PENDING))

    coverage = _coverage_block(snapshot, usage)
    health_code, health_ru = health_of(snapshot, usage, done_event=done_row)
    publication = _publication_block(snapshot, usage)
    return {
        "run_id": str(run_id or ""),
        "chat_id": snapshot.get("chat_id"),
        "mode": snapshot.get("mode"),
        "status": snapshot.get("status"),
        "duration_ms": _float(snapshot.get("duration_ms")),
        "package_grade": snapshot.get("package_grade"),
        "fallback": snapshot.get("fallback"),
        "pipeline_health": snapshot.get("pipeline_health"),
        "coverage": coverage,
        "publication": publication,
        "health": health_code,
        "health_label": health_ru,
        "nodes": nodes,
        "running": bool(running),
        "developer": _developer_block(snapshot, events),
    }


def _coverage_block(snapshot, usage) -> dict | None:
    """Coverage-карточка §61.6 (first-class): total/considered/percent."""
    total = _int(snapshot.get("source_total")) or _int(
        usage.get("source_total")) or _int(snapshot.get("source_count"))
    considered = _int(snapshot.get("source_considered")) or _int(
        usage.get("source_considered"))
    percent = _float(snapshot.get("source_coverage"))
    if percent is None:
        percent = _float(usage.get("coverage"))
    if percent is None and total and considered is not None:
        percent = round(considered * 100.0 / total, 1)
    if total is None and considered is None and percent is None:
        return None
    return {
        "total": total,
        "considered": considered,
        "percent": percent,
        "full": percent is None or percent >= COVERAGE_FULL_EPSILON,
    }


def _publication_block(snapshot, usage) -> dict:
    """Публикационный срез (§61.1 «Публикация: rich/plain, message id»)."""
    status = snapshot.get("publish_status") or usage.get("publication")
    channel = snapshot.get("publish_channel")
    publication = usage.get("publication")
    if publication == "rich":
        channel, status = "rich", status or "ok"
    elif publication == "text":
        channel, status = "text", status or "ok"
    elif publication == "failed":
        status = "failed"
    return {
        "status": status,
        "channel": channel,
        "message_id": _int(snapshot.get("publish_message_id"))
        or _int(usage.get("message_id")),
    }


# Статусы публикации, признаваемые health_of: snapshot `publish_status`
# (in-memory: ok/failed) И канальные статусы из durable-событий
# (`SUMMARY_RUN_DONE`.usage_json.publication: rich/text — состояние после
# рестарта/деплоя, когда in-memory снапшота нет — M-ASAP4-E1, §61.6).
_PUBLISHED_STATUSES = frozenset({
    "ok", "published_rich", "published_text", "rich", "text",
})


def health_of(snapshot, usage=None, *, done_event=None) -> tuple[str, str]:
    """Health run (§61.6/§61.13): publication_status × source_coverage.

    «RichMessage опубликован + Coverage 44.6% = degraded». Только текстовые
    бейджи, без opaque score. Возвращает (code, RU-label).

    Restart-безопасно (M-ASAP4-E1): финальный health не опирается на
    in-memory снапшот — публикация/coverage/деградация читаются из
    durable-событий: `usage` — `SUMMARY_RUN_DONE`.usage_json, `done_event` —
    строка DONE-события (status/outcome — финализация/провал прогона).
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    usage = usage if isinstance(usage, dict) else {}
    done_event = done_event if isinstance(done_event, dict) else {}
    pub = _publication_block(snapshot, usage)
    status = str(pub.get("status") or "")
    run_status = str(snapshot.get("status") or "")
    done_status = str(done_event.get("status") or "")
    if (status == "failed" or run_status == "failed"
            or done_status == "failed"
            or str(done_event.get("outcome") or "") == "failed"):
        return HEALTH_FAILED, HEALTH_LABELS_RU[HEALTH_FAILED]
    coverage = _float(snapshot.get("source_coverage"))
    if coverage is None:
        coverage = _float(usage.get("coverage"))
    pipeline_health = (str(snapshot.get("pipeline_health") or "")
                       or str(usage.get("pipeline_health") or ""))
    if status in _PUBLISHED_STATUSES:
        if coverage is not None and coverage < COVERAGE_FULL_EPSILON:
            return HEALTH_DEGRADED, HEALTH_LABELS_RU[HEALTH_DEGRADED]
        if pipeline_health == "degraded":
            return HEALTH_DEGRADED, HEALTH_LABELS_RU[HEALTH_DEGRADED]
        if usage.get("fallback") == "legacy":
            return HEALTH_DEGRADED, HEALTH_LABELS_RU[HEALTH_DEGRADED]
        return HEALTH_HEALTHY, HEALTH_LABELS_RU[HEALTH_HEALTHY]
    # Публикации не было: empty/skip/незавершённый прогон.
    return HEALTH_INCOMPLETE, HEALTH_LABELS_RU[HEALTH_INCOMPLETE]


def _developer_block(snapshot, events) -> dict:
    """Developer details (§61.9/§76: collapsible) — R17-safe только."""
    stage_events = snapshot.get("stage_events")
    rows = [dict(e) for e in (stage_events or []) if isinstance(e, dict)]
    return {
        "model": snapshot.get("model"),
        "provider": snapshot.get("provider"),
        "reason": snapshot.get("reason"),
        "stage_events": rows,
        "events_total": len(events or []),
    }


# ── список runs (§61.10) ────────────────────────────────────────────────────

def run_list_entry(done_row, *, styled: bool = False) -> dict:
    """Строка списка последних runs из SUMMARY_RUN_DONE (§61.10).

    `styled` — по событию COVER_STYLE_SUCCEEDED этого run (точная
    информация о стиле из того же durable-стора, не догадка).
    """
    row = dict(done_row)
    usage = _parse_usage(row.get("usage_json"))
    health = str(row.get("status") or "")
    coverage = _float(usage.get("coverage"))
    if health == "ok" and coverage is not None \
            and coverage < COVERAGE_FULL_EPSILON:
        health = HEALTH_DEGRADED
    elif health == "degraded":
        health = HEALTH_DEGRADED
    elif health == "failed":
        health = HEALTH_FAILED
    else:
        health = HEALTH_HEALTHY
    fallback = str(usage.get("fallback") or "none")
    text_path = "Legacy" if fallback == "legacy" else "Hybrid"
    publication = str(usage.get("publication") or "")
    if publication == "failed":
        cover_path = "без обложки"
    else:
        cover_path = "стиль" if styled else "базовая"
    return {
        "run_id": str(row.get("pipeline_run_id") or row.get("trace_id") or ""),
        "ts": _int(row.get("ts")),
        "chat_id": _int(row.get("chat_id")),
        "health": health,
        "health_label": HEALTH_LABELS_RU.get(health, health),
        "duration_ms": _float(row.get("duration_ms")),
        "source_count": _int(usage.get("source_total")),
        "path": "%s + %s" % (text_path, cover_path),
    }


# ── агрегаты 24h/7d (§61.4/§61.5) ───────────────────────────────────────────

# Событие → (группа узла, классификатор исхода).
def _classify(event_name: str, row: dict) -> tuple[str | None, str | None]:
    outcome = str(row.get("outcome") or "")
    status = str(row.get("status") or "")
    reason = str(row.get("reason_code") or "")
    if event_name == "SUMMARY_SOURCE_WINDOW":
        return NODE_SOURCE, STATE_SUCCESS
    if event_name == "SUMMARY_L1_STAGE":
        return NODE_L1, STATE_FAILED if outcome == "failed" else STATE_SUCCESS
    if event_name == "SUMMARY_L2_STAGE":
        return NODE_L2, STATE_FAILED if outcome == "failed" else STATE_SUCCESS
    if event_name == "SUMMARY_L2_REVIEW":
        if status == "failed":
            return NODE_L2_REVIEW, STATE_FALLBACK   # L2 → Legacy (§61.4)
        if status in ("repaired", "degraded") or reason in _REPAIR_REASONS:
            return NODE_L2_REVIEW, STATE_REPAIRED
        return NODE_L2_REVIEW, STATE_SUCCESS
    if event_name == "SUMMARY_LEGACY_FALLBACK":
        return NODE_LEGACY, STATE_FALLBACK
    if event_name == _COVER_BASE_OK:
        return NODE_BASE_COVER, STATE_SUCCESS
    if event_name == _COVER_BASE_FAIL:
        return NODE_BASE_COVER, STATE_FAILED
    if event_name == _STYLE_OK:
        return NODE_STYLE_EDIT, STATE_SUCCESS
    if event_name == _STYLE_FAIL:
        return NODE_STYLE_EDIT, STATE_FALLBACK
    if event_name == _STYLE_SKIP:
        return NODE_STYLE_EDIT, STATE_SKIPPED
    if event_name == _RICH_OK:
        return NODE_PUBLISH, STATE_SUCCESS
    if event_name == _RICH_FAIL or event_name == _PLAIN_FALLBACK:
        return NODE_PUBLISH, STATE_FALLBACK
    return None, None


_STAGE_TITLES = {
    NODE_SOURCE: "Источник",
    NODE_L1: "L1",
    NODE_L2: "L2",
    NODE_L2_REVIEW: "L2 Проверка",
    NODE_LEGACY: "Legacy",
    NODE_BASE_COVER: "Базовая обложка",
    NODE_STYLE_EDIT: "Style Edit",
    NODE_PUBLISH: "Публикация",
}


def _percent(part: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(part * 100.0 / total, 1)


def _percentile(sorted_values: list, q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(
        sorted_values) - 1)))))
    return float(sorted_values[idx])


def aggregate_from_rows(rows) -> dict:
    """Агрегаты по терминальным стадийным событиям окна (§61.4/§61.5).

    `rows` — строки `mca_events` (уже отфильтрованные по окну). Средние не
    скрывают аварии: per-stage % + median/p95 + top-3 причины + итоги runs.
    """
    stages: dict = {}
    totals = Counter()
    for raw in (rows or []):
        row = dict(raw) if not isinstance(raw, dict) else raw
        name = str(row.get("event_name") or "")
        if name == "SUMMARY_RUN_DONE":
            usage = _parse_usage(row.get("usage_json"))
            health = str(row.get("status") or "")
            coverage = _float(usage.get("coverage"))
            if health == "failed" or str(row.get("outcome")) == "failed":
                totals["failed"] += 1
            elif health == "degraded" or (
                    coverage is not None
                    and coverage < COVERAGE_FULL_EPSILON):
                totals["degraded"] += 1
            elif health in ("ok", ""):
                totals["healthy"] += 1
            else:
                totals["incomplete"] += 1
            totals["total"] += 1
            continue
        group, state = _classify(name, row)
        if group is None or state is None:
            continue
        bucket = stages.setdefault(group, {
            "label": _STAGE_TITLES.get(group, group),
            "success": 0, "repaired": 0, "fallback": 0, "failed": 0,
            "skipped": 0, "total": 0,
            "latencies": [], "reasons": Counter(),
        })
        bucket["total"] += 1
        if state == STATE_SUCCESS:
            bucket["success"] += 1
        elif state == STATE_REPAIRED:
            bucket["repaired"] += 1
        elif state == STATE_FALLBACK:
            bucket["fallback"] += 1
        elif state == STATE_SKIPPED:
            bucket["skipped"] += 1
        else:
            bucket["failed"] += 1
        latency = _float(row.get("duration_ms"))
        if latency is not None:
            bucket["latencies"].append(latency)
        if state in (STATE_FAILED, STATE_FALLBACK, STATE_REPAIRED) \
                and row.get("reason_code"):
            bucket["reasons"][str(row["reason_code"])] += 1

    out_stages = {}
    for key, bucket in stages.items():
        total = bucket["total"]
        latencies = sorted(bucket["latencies"])
        top = [{"code": code, "ru": reason_ru(code), "count": count}
               for code, count in bucket["reasons"].most_common(3)]
        out_stages[key] = {
            "label": bucket["label"],
            "total": total,
            "success_pct": _percent(bucket["success"], total),
            "repaired_pct": _percent(bucket["repaired"], total),
            "fallback_pct": _percent(bucket["fallback"], total),
            "failed_pct": _percent(bucket["failed"], total),
            "skipped_pct": _percent(bucket["skipped"], total),
            "median_ms": (round(latencies[len(latencies) // 2], 1)
                          if latencies else None),
            "p95_ms": (round(_percentile(latencies, 0.95), 1)
                       if len(latencies) >= 2 else None),
            "top_reasons": top,
        }
    order = [NODE_SOURCE, NODE_L1, NODE_L2, NODE_L2_REVIEW, NODE_LEGACY,
             NODE_BASE_COVER, NODE_STYLE_EDIT, NODE_PUBLISH]
    return {
        "stages": {key: out_stages[key] for key in order if key in out_stages},
        "totals": {
            "total": totals["total"],
            "healthy": totals["healthy"],
            "degraded": totals["degraded"],
            "failed": totals["failed"],
            "incomplete": totals["incomplete"],
        },
    }


WINDOW_LABELS_RU = {1: "24 часа", 7: "7 дней"}


# ── async-сборка (data access; только structured sources) ──────────────────

_INSPECTOR_EVENTS = (
    "SUMMARY_RUN_START", "SUMMARY_SOURCE_WINDOW", "SUMMARY_L1_STAGE",
    "SUMMARY_L2_STAGE", "SUMMARY_L2_REVIEW", "SUMMARY_LEGACY_FALLBACK",
    "SUMMARY_RUN_DONE",
    _SELECTION, _COVER_BASE_OK, _COVER_BASE_FAIL, _STYLE_START, _STYLE_OK,
    _STYLE_FAIL, _STYLE_SKIP, _RICH_OK, _RICH_FAIL, _PLAIN_FALLBACK,
)


def _events_gate() -> bool:
    """Kill-switch волны E: OFF → durable-события не читаются (агрегат/trace
    строится из state-проекций — spec §8.2)."""
    try:
        from services import pipeline_events
        return pipeline_events.events_enabled()
    except Exception:      # pragma: no cover
        return False


async def _fetch_events(db, run_id: str | None = None,
                        since_ts: int | None = None,
                        limit: int = 2000) -> list:
    """Стадийные события из `mca_events` (bounded; fail-open → [])."""
    if db is None:
        return []
    try:
        placeholders = ",".join("?" for _ in _INSPECTOR_EVENTS)
        sql = ("SELECT * FROM mca_events WHERE event_name IN (%s)" % placeholders)
        params: list = list(_INSPECTOR_EVENTS)
        if run_id:
            sql += " AND pipeline_run_id = ?"
            params.append(run_id)
        if since_ts is not None:
            sql += " AND ts >= ?"
            params.append(int(since_ts))
        sql += " ORDER BY ts ASC, id ASC LIMIT ?"
        params.append(max(1, min(5000, int(limit))))
        cursor = await db.db.execute(sql, tuple(params))
        return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []


def _snapshot_registry():
    try:
        from services import execution_graph_source as egs
        return egs
    except Exception:      # pragma: no cover
        return None


async def collect_run(db, run_id: str) -> dict:
    """Полная модель run (§61.9 drill-down): события + снапшот."""
    reg = _snapshot_registry()
    snapshot = reg.get_run(run_id) if reg is not None else None
    events = await _fetch_events(db, run_id=run_id) if _events_gate() else []
    running = False
    if snapshot is None and events:
        names = {str(e.get("event_name") or "") for e in events}
        running = ("SUMMARY_RUN_START" in names
                   and "SUMMARY_RUN_DONE" not in names)
    return build_run_view(run_id, snapshot, events, running=running)


async def collect_latest(db) -> dict | None:
    """Последний run (§61.4 «Последний запуск»): durable DONE + in-memory."""
    reg = _snapshot_registry()
    latest_snapshot_id = reg.latest_run_id() if reg is not None else None
    run_id = latest_snapshot_id
    done_rows = []
    if _events_gate() and db is not None:
        try:
            cursor = await db.db.execute(
                "SELECT * FROM mca_events WHERE event_name = ? "
                "ORDER BY ts DESC, id DESC LIMIT 1",
                ("SUMMARY_RUN_DONE",))
            row = await cursor.fetchone()
            if row is not None:
                done_rows = [dict(row)]
                durable_id = str(row["pipeline_run_id"]
                                 or row["trace_id"] or "")
                # in-memory свежее (текущий прогон после flush-лагa).
                if latest_snapshot_id:
                    run_id = latest_snapshot_id
                else:
                    run_id = durable_id
        except Exception:
            done_rows = []
    if not run_id:
        return None
    return await collect_run(db, run_id)


async def collect_runs_list(db, limit: int = 12) -> list:
    """Список последних runs с бейджами (§61.10): durable DONE-события.

    Стиль-путь уточняется по COVER_STYLE_SUCCEEDED тех же run_id (тот же
    durable-стор; один bounded IN-запрос, без догадок)."""
    if db is None or not _events_gate():
        return []
    try:
        cursor = await db.db.execute(
            "SELECT * FROM mca_events WHERE event_name = ? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            ("SUMMARY_RUN_DONE", max(1, min(50, int(limit)))))
        rows = [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []
    out = []
    seen = set()
    done_entries = []
    for row in rows:
        entry = run_list_entry(row)
        rid = entry["run_id"]
        if not rid or rid in seen:
            continue
        seen.add(rid)
        done_entries.append(entry)
    if not done_entries:
        return []
    styled = await _styled_run_ids(db, [e["run_id"] for e in done_entries])
    for entry in done_entries:
        if entry["run_id"] in styled:
            entry["path"] = entry["path"].replace(" + базовая", " + стиль")
        out.append(entry)
    return out


async def _styled_run_ids(db, run_ids: list) -> set:
    """run_id с успешным Style Edit (COVER_STYLE_SUCCEEDED); fail-open."""
    if db is None or not run_ids:
        return set()
    try:
        placeholders = ",".join("?" for _ in run_ids)
        cursor = await db.db.execute(
            "SELECT DISTINCT pipeline_run_id FROM mca_events WHERE "
            "event_name = 'COVER_STYLE_SUCCEEDED' AND pipeline_run_id IN "
            "(%s)" % placeholders, tuple(run_ids))
        return {str(r["pipeline_run_id"]) for r in await cursor.fetchall()}
    except Exception:
        return set()


async def collect_aggregate(db, days: int) -> dict:
    """Агрегаты окна (§61.4/§61.5) из тех же событий, что Last Run (§61.11).

    Kill-switch OFF → state-проекции недоступны для исторических окон —
    честный пустой результат (не нули-«здоровье»).
    """
    empty = {"stages": {}, "totals": {"total": 0, "healthy": 0,
                                      "degraded": 0, "failed": 0,
                                      "incomplete": 0},
             "window": {"days": int(days),
                        "label": WINDOW_LABELS_RU.get(days, "%d дней" % days)},
             "available": False}
    if db is None or not _events_gate():
        return empty
    since = int(time.time()) - int(days) * 86400
    rows = await _fetch_events(db, since_ts=since, limit=5000)
    if not rows:
        return empty
    result = aggregate_from_rows(rows)
    result["window"] = empty["window"]
    result["available"] = True
    return result


__all__ = [
    "NODE_SOURCE", "NODE_L1", "NODE_L2", "NODE_L2_REVIEW", "NODE_LEGACY",
    "NODE_STYLE_SELECTION", "NODE_BASE_COVER", "NODE_STYLE_EDIT",
    "NODE_PUBLISH", "TEXT_BRANCH", "COVER_BRANCH",
    "STATE_SUCCESS", "STATE_REPAIRED", "STATE_FALLBACK", "STATE_FAILED",
    "STATE_SKIPPED", "STATE_RUNNING", "STATE_PENDING", "ICONS",
    "HEALTH_HEALTHY", "HEALTH_DEGRADED", "HEALTH_FAILED",
    "HEALTH_INCOMPLETE", "HEALTH_RUNNING", "HEALTH_LABELS_RU",
    "REASONS_RU", "NODE_EXPLAIN_RU", "COVERAGE_FULL_EPSILON",
    "reason_ru", "build_run_view", "health_of", "run_list_entry",
    "aggregate_from_rows", "collect_run", "collect_latest",
    "collect_runs_list", "collect_aggregate", "WINDOW_LABELS_RU",
]
