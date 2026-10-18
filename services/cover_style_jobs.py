"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D8/D9; spec §3.3/
§3.11/§3.13/§42–§48/§49–§52/§68–§70/§92) — Cover Style durable job + fail-soft
ladder + observability.

Durable job **REUSE** существующей инфраструктуры MCA (второй очереди НЕТ,
§42/Q6): `task_jobs` (v14) через `TaskJobStore`, `mca_pipeline_runs` (v19) +
`mca_events` (v15) через `mca_trace`/`mca_events`. State machine §42 маппится на
`task_jobs.status/reason_code/checkpoint_ref`; provider `task_id` (async) —
в payload/снимке состояния.

Style stage (§3.2/§23): нормализующий edit поверх готовой base cover —
capability-gated (§38), НЕ перегенерирует base при падении (§49).
Fail-soft ladder (§4/§49–§52): `styled → base(style_failed) → Rich без обложки
(base_failed) → plain(rich_failed)`.

R17: лог-поля — только whitelist (`prompt length/hash`, counts, длительности,
provider/model, task id); API key/полный prompt/raw Summary/приватные URL не
логируются.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field

from config.settings import settings
from services import cover_style_assets as assets
from services import cover_style_registry as registry
from services import image_capabilities as cap
from services import image_prompt_compiler as compiler
# ASAP 5 (SERIALIZE-1/D7–D9): единая сборка cover-промптов и манифеста.
from services import cover_prompt_assembly as cpa
from services.cover_style_edit import EditResult, edit_image
from services.cover_style_pipeline import (
    KEY_STYLE_API_KEY,
    KEY_IMAGE_API_KEY,
    MODEL_MODE_CUSTOM,
    SLOT_SOURCE_CONNECTIONS_DEFAULT,
    SLOT_SOURCE_GLOBAL_IMAGE,
    SLOT_SOURCE_GLOBAL_STYLE,
    SLOT_SOURCE_PROFILE_CONNECTION,
    check_edit_allowed,
    cover_styles_enabled,
    pipeline_mode,
    resolve_effective_edit_capability,
    resolve_style_slot,
    resolve_style_slot_inherited,
    slot_capabilities,
    uses_style_stage,
)

logger = logging.getLogger(__name__)

# ── §44: события стадий ─────────────────────────────────────────────────────
COVER_PIPELINE_START = "COVER_PIPELINE_START"
COVER_BASE_SUBMITTED = "COVER_BASE_SUBMITTED"
COVER_BASE_RUNNING = "COVER_BASE_RUNNING"
COVER_BASE_SUCCEEDED = "COVER_BASE_SUCCEEDED"
COVER_BASE_FAILED = "COVER_BASE_FAILED"
# ASAP-4 волна B (spec §2 B.1, T-4415): selection snapshot на старте cover
# publication — до base generation и style edit (для medved_press видно до
# image API). R17-safe: только id/числа/enum.
COVER_STYLE_SELECTION = "COVER_STYLE_SELECTION"
COVER_STYLE_START = "COVER_STYLE_START"
COVER_STYLE_SUBMITTED = "COVER_STYLE_SUBMITTED"
COVER_STYLE_RUNNING = "COVER_STYLE_RUNNING"
COVER_STYLE_SUCCEEDED = "COVER_STYLE_SUCCEEDED"
COVER_STYLE_FAILED = "COVER_STYLE_FAILED"
# ASAP-4 волна B (spec §2 B.4, T-4419): видимый fail-open — ранний выход
# Style stage с отдельной причиной (ничего не молчит).
COVER_STYLE_SKIPPED = "COVER_STYLE_SKIPPED"
COVER_RICH_PUBLISH_START = "COVER_RICH_PUBLISH_START"
COVER_RICH_PUBLISH_SUCCEEDED = "COVER_RICH_PUBLISH_SUCCEEDED"
COVER_RICH_PUBLISH_FAILED = "COVER_RICH_PUBLISH_FAILED"
COVER_PLAIN_FALLBACK = "COVER_PLAIN_FALLBACK"
COVER_PIPELINE_DONE = "COVER_PIPELINE_DONE"

# ── §96: классификация cover-result ─────────────────────────────────────────
RESULT_STYLED = "styled"
RESULT_BASE = "base"
RESULT_NONE = "none"
RESULT_PLAIN = "plain_send_message"
REASON_STYLE_FAILED = "style_failed"
REASON_BASE_FAILED = "base_failed"
REASON_RICH_FAILED = "rich_failed"
# ── ASAP-4 волна B (spec §2 B.4, T-4419): distinct reason codes ранних
# выходов. Каждый — отдельный reason/event; `style_failed` остаётся
# umbrella'ом для provider-фейлов уже после реальной submission.
REASON_NO_STYLE = "no_style"
REASON_PROFILE_MISSING = "profile_missing"
REASON_DISABLED = "disabled"
REASON_CONNECTION_MISSING = "connection_missing"
REASON_REFERENCE_MISSING = "reference_missing"
REASON_CAPABILITY_UNKNOWN = "capability_unknown"
REASON_NOT_CONFIGURED = "not_configured"
REASON_NO_STYLE_STAGE = "style_stage_not_applicable"

# ── ASAP 8 F3 (§5.4): fail-soft публикации styled cover. Стиль, который
# не гарантирует сюжет сцены, НЕ публикуется — публикуется Base (честный
# reason вместо «красивой, но сюжетно ложной» обложки).
STYLE_PUBLISH_SKIP_OVERFLOW = "prompt_limit_exceeded"
STYLE_PUBLISH_SKIP_STORY = "story_identity_dropped"

# ── ASAP 8 v6 C03A: recovery-контур styled cover (Base опубликован,
# styled не появился / не восстанавливался). Честные reason-коды:
#   style_disabled                — стиль явно не выбран/выключен: Base
#                                   финальный ПО НАМЕРЕНИЮ (не false success
#                                   и не false style_failed);
#   semantic_preservation_failed  — детерминированный сигнал потери сюжета в
#                                   результате (провайдер ответил текстом/без
#                                   изображения вместо edit сцены);
#   invalid_image_payload         — провайдер вернул не-изображение (битые
#                                   байты); публикация сломанной обложки
#                                   запрещена (RCA R3 bonus-дефект);
#   base_asset_missing            — recovery не нашёл сохранённую Base:
#                                   повторная генерация Base запрещена (v6:
#                                   «без генерации второго Base»);
#   recovery_exhausted            — bounded retry исчерпан (честный финал).
REASON_STYLE_DISABLED = "style_disabled"
REASON_SEMANTIC_LOST = "semantic_preservation_failed"
REASON_INVALID_PAYLOAD = "invalid_image_payload"
REASON_BASE_ASSET_MISSING = "base_asset_missing"
REASON_STYLE_INPUTS_MISSING = "style_inputs_missing"
REASON_RECOVERY_EXHAUSTED = "recovery_exhausted"

# Recovery-события (§44-стиль; R17-safe поля).
COVER_STYLE_RETRY_SCHEDULED = "COVER_STYLE_RETRY_SCHEDULED"
COVER_STYLE_RECOVERED = "COVER_STYLE_RECOVERED"

# ── T-4619/T-4620 (spec §6 F.2/F.3; ADR-1028-8 D7.2): событие резолва
# Style-слота с ИСТОЧНИКОМ наследования (лестница §35 — точная причина
# видима, не generic `style_failed`).
COVER_STYLE_RESOLVE = "COVER_STYLE_RESOLVE"

# Конфигурационные/ранние причины — проходят в mca_events reason_code как
# есть (прод-факт Q14: `not_configured` больше не схлопывается в generic).
STYLE_REASON_CODES = frozenset({
    REASON_STYLE_FAILED, "edit_unsupported", REASON_NO_STYLE,
    REASON_PROFILE_MISSING, REASON_DISABLED, REASON_CONNECTION_MISSING,
    REASON_REFERENCE_MISSING, REASON_CAPABILITY_UNKNOWN,
    REASON_NOT_CONFIGURED, REASON_NO_STYLE_STAGE,
    "prompt_limit_exceeded", "route_unverified",
    # ASAP 4.4 (§2, T-4875): 400-too-long без числа и его bounded retry.
    "prompt_limit_unknown", "prompt_limit_unknown_after_retry",
    # ASAP 8 F3 (§5.4): fail-soft — story identity потерян при компиляции.
    STYLE_PUBLISH_SKIP_STORY,
    # ASAP 8 v6 C03A: recovery-контур и честные исходы styled.
    REASON_STYLE_DISABLED, REASON_SEMANTIC_LOST, REASON_INVALID_PAYLOAD,
    REASON_BASE_ASSET_MISSING, REASON_STYLE_INPUTS_MISSING,
    REASON_RECOVERY_EXHAUSTED,
    "style_stage_error",
})


def style_reason_code(reason: str) -> str:
    """mca_events `reason_code` без generic-схлопывания (§2 B.4).

    Конфигурационные/ранние причины — как есть; provider-фейлы после
    реальной submission (timeout/network/http_*) — umbrella `style_failed`
    (точная причина видна в `reason=` лога и meta.fail_reason).
    """
    reason = str(reason or "")
    return reason if reason in STYLE_REASON_CODES else REASON_STYLE_FAILED


# §43: человекочитаемые причины (run detail/Analytics; Wave E подключит UI).
REASON_DETAILS_RU = {
    REASON_NO_STYLE: "стиль не выбран («Без дополнительного стиля»)",
    REASON_PROFILE_MISSING: "профиль стиля не найден",
    REASON_DISABLED: "профиль стиля отключён",
    "edit_unsupported": ("модель не умеет редактировать готовые изображения"),
    REASON_CONNECTION_MISSING: ("подключение модели не найдено "
                                "(удалено или недоступно)"),
    REASON_REFERENCE_MISSING: ("референсы стиля недоступны "
                               "(нет в реестре/файл отсутствует/повреждён)"),
    REASON_CAPABILITY_UNKNOWN: ("возможности модели не определены "
                                "(capability source неизвестен)"),
    REASON_NOT_CONFIGURED: ("не настроены адрес/модель обработки "
                            "(Connections layer)"),
    REASON_NO_STYLE_STAGE: ("режим профиля без Style-стадии"),
    "prompt_limit_exceeded": ("инструкция стиля превышает лимит модели — "
                              "применена базовая обложка"),
    "prompt_limit_unknown": ("провайдер отклонил промпт как слишком длинный, "
                             "точный лимит не сообщён — применена базовая "
                             "обложка"),
    "prompt_limit_unknown_after_retry": ("промпт отклонён как слишком "
                                         "длинный даже после сокращения — "
                                         "применена базовая обложка"),
    "route_unverified": ("маршрут редактирования модели не подтверждён — "
                         "применена базовая обложка"),
    STYLE_PUBLISH_SKIP_STORY: ("промпт стиля не гарантирует сохранение "
                               "сюжета сцены — применена базовая обложка"),
    # ASAP 8 v6 C03A: recovery-контур и честные исходы styled.
    REASON_STYLE_DISABLED: ("стиль не выбран или выключен — базовая обложка "
                            "опубликована по намерению"),
    REASON_SEMANTIC_LOST: ("результат обработки не сохранил сюжет сцены — "
                           "применена базовая обложка"),
    REASON_INVALID_PAYLOAD: ("провайдер вернул некорректное изображение — "
                             "применена базовая обложка"),
    REASON_BASE_ASSET_MISSING: ("сохранённая базовая обложка недоступна — "
                                "восстановление стиля невозможно без "
                                "повторной генерации Base (запрещено)"),
    REASON_STYLE_INPUTS_MISSING: ("durable-компоненты промпта стиля "
                                  "(Base-манифест run) недоступны — "
                                  "восстановление невозможно без повторной "
                                  "сборки (запрещено)"),
    REASON_RECOVERY_EXHAUSTED: ("повторные попытки восстановления стиля "
                                "исчерпаны — применена базовая обложка"),
    "style_stage_error": ("стадия стиля прервана ошибкой — "
                          "применена базовая обложка"),
    REASON_STYLE_FAILED: ("обработка стилем не завершилась "
                          "(ошибка провайдера)"),
}


def reason_detail_ru(reason: str) -> str:
    """Человекочитаемая причина по reason-коду (§43; R17-safe — только коды)."""
    return REASON_DETAILS_RU.get(str(reason or ""), "")


def style_skip_status(reason: str) -> str:
    """§43: формулировка run detail «Обработка стилем — не выполнена…»."""
    detail = reason_detail_ru(reason)
    if not detail:
        return ""
    return "Обработка стилем — не выполнена. Причина: %s." % detail


# ── ASAP 8 v6 C03A: recovery-контур styled cover ────────────────────────────

def recovery_enabled() -> bool:
    """Kill-switch recovery-контура (`COVER_STYLE_RECOVERY_ENABLED`, env-only,
    default ON). OFF — прежнее поведение: style-фейл терминален, рестарт
    посреди стиля оставляет зомби-строку (v6 C03A кейсы 2/3 нарушены)."""
    try:
        return bool(getattr(settings, "COVER_STYLE_RECOVERY_ENABLED", True))
    except Exception:
        return True


def recovery_max_attempts() -> int:
    """Bounded retry: максимальное число recovery-попыток на job
    (`COVER_STYLE_RECOVERY_MAX_ATTEMPTS`, default 2; ≥0). Начальная
    инлайн-попытка публикации НЕ считается."""
    try:
        raw = getattr(settings, "COVER_STYLE_RECOVERY_MAX_ATTEMPTS", 2)
        return max(0, int(raw))
    except Exception:
        return 2


# Постоянные (не повторяемые автоматически) причины: конфигурация/контракт —
# повторная попытка даст тот же исход (v6: «классификация permanent/transient»).
_PERMANENT_STYLE_REASONS = frozenset({
    REASON_NO_STYLE, REASON_PROFILE_MISSING, REASON_DISABLED,
    REASON_CONNECTION_MISSING, REASON_REFERENCE_MISSING,
    REASON_CAPABILITY_UNKNOWN, REASON_NOT_CONFIGURED, REASON_NO_STYLE_STAGE,
    "edit_unsupported", "route_unverified",
    STYLE_PUBLISH_SKIP_OVERFLOW, STYLE_PUBLISH_SKIP_STORY,
    "prompt_limit", "prompt_limit_unknown", "prompt_limit_unknown_after_retry",
    REASON_SEMANTIC_LOST, REASON_INVALID_PAYLOAD, REASON_BASE_ASSET_MISSING,
    REASON_STYLE_INPUTS_MISSING, REASON_RECOVERY_EXHAUSTED,
    REASON_STYLE_DISABLED,
    "bad_request", "unauthorized", "forbidden", "payment_required",
    "not_found", "invalid_request_error", "content_policy_violation",
})

# Подстроки временных причин (provider timeout/network/5xx/limit-pressure).
_TRANSIENT_STYLE_MARKERS = (
    "timeout", "deadline", "network", "temp_write_failed", "server_error",
    "unavailable", "rate_limit", "429", "http_5", "reset", "reconnect",
    "cancelled",
)


def classify_style_failure(reason: str) -> str:
    """Классификация причины style-фейла: ``transient`` | ``permanent``.

    Точные permanent-коды проверяются первыми (`connection_missing` содержит
    «conn», но постоянна); затем подстроки transient-класса; неизвестная
    причина → permanent (bounded by default: слепой retry неизвестного
    опаснее честного финала — причина видна в Inspector).
    """
    reason = str(reason or "").strip().lower()
    if not reason:
        return "permanent"
    if reason in _PERMANENT_STYLE_REASONS:
        return "permanent"
    if reason.startswith("http_4") or reason in ("400", "401", "403", "404",
                                                 "422"):
        return "permanent"
    if any(marker in reason for marker in _TRANSIENT_STYLE_MARKERS):
        return "transient"
    return "permanent"


def recovery_backoff_seconds(retry_count: int) -> int:
    """Backoff перед следующей recovery-попыткой (bounded 5–60 мин)."""
    return min(300 * (2 ** max(0, int(retry_count) - 1)), 3600)


def recovery_dir():
    """Managed-каталог durable cover-артефактов recovery-контура
    (env `COVER_STYLE_RECOVERY_DIR`, default `var/cover_style_recovery`).

    Отдельно от `cover_style_assets` (регистр референсов/seed — R18 не
    задеваем); файлы run-артефактов prune'ятся bounded (см.
    `persist_style_artifact`)."""
    import pathlib
    raw = os.getenv("COVER_STYLE_RECOVERY_DIR", "").strip()
    if raw:
        return pathlib.Path(raw)
    return pathlib.Path(__file__).resolve().parents[1] / "var" / \
        "cover_style_recovery"


def _recovery_prune(directory, keep: int = 200) -> None:
    """Bounded retention recovery-артефактов: новейшие `keep` файлов живут,
    более старые удаляются (иначе каждый styled-успех рос бы неограниченно)."""
    try:
        entries = [p for p in directory.iterdir() if p.is_file()]
    except OSError:
        return
    if len(entries) <= keep:
        return
    try:
        entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in entries[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def persist_style_artifact(run_id: str, src_path: str | None,
                           kind: str) -> str | None:
    """Сохранить cover-артефакт run'а (base/styled) в recovery-каталог.

    Base сохраняется ДО style-вызова (restart-mid-style обязан найти её),
    styled — при успехе (связь «run ↔ финальный styled-артефакт» переживает
    удаление temp-файла публикацией). Имя детерминировано от run_id
    (R17-safe: без chat-данных в имени). None — источник не читается."""
    if not src_path or not str(run_id or "").strip():
        return None
    try:
        with open(src_path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    name = hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:20]
    target = recovery_dir() / ("%s_%s.jpg" % (name, "styled" if kind ==
                                              "styled" else "base"))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or kind == "styled":
            # base — идемпотентная запись (перезапуск не перезатирает);
            # styled — последняя успешная попытка win (retry обновляет).
            target.write_bytes(data)
        _recovery_prune(target.parent)
    except OSError:
        logger.warning("[cover_style_jobs] recovery artifact write failed",
                       exc_info=True)
        return None
    return str(target)


def set_styled_status(state, *, status: str, reason: str | None = None,
                       route: str | None = None,
                       attempt: int | None = None) -> None:
    """Честный styled-статус в durable state + манифест (Inspector читает
    `state.prompt_manifest` через `load_run_cover_prompts`)."""
    if state is None:
        return
    state.styled_status = status
    state.styled_fail_reason = reason
    if route is not None:
        state.styled_route = route
    manifest = state.prompt_manifest
    if isinstance(manifest, dict):
        manifest["styled_status"] = {
            "status": status,
            "reason": reason,
            "route": route,
            "attempt": int(attempt if attempt is not None
                           else (state.retry_count or 0)),
        }

# ── §48/§75: человекочитаемые RU-статусы ────────────────────────────────────
RU_STYLE_FAILED = ("Обработка стилем не завершилась вовремя. "
                   "Использована базовая обложка.")
RU_BASE_FAILED = ("Базовая обложка не получилась. Статья отправлена без "
                  "изображения.")
RU_RICH_FAILED = ("Не удалось отправить оформленную статью. "
                  "Публикуем обычным сообщением.")

# ── §42: conceptual state machine ───────────────────────────────────────────
STATE_CREATED = "CREATED"
STATE_BASE_SUBMITTED = "BASE_SUBMITTED"
STATE_BASE_RUNNING = "BASE_RUNNING"
STATE_BASE_SUCCEEDED = "BASE_SUCCEEDED"
STATE_BASE_FAILED = "BASE_FAILED"
STATE_STYLE_SUBMITTED = "STYLE_SUBMITTED"
STATE_STYLE_RUNNING = "STYLE_RUNNING"
STATE_STYLE_SUCCEEDED = "STYLE_SUCCEEDED"
STATE_STYLE_FAILED = "STYLE_FAILED"
STATE_PUBLISH_RICH = "PUBLISH_RICH"
STATE_PUBLISH_PLAIN = "PUBLISH_PLAIN"
# ASAP 4.3 (§2.2, T-4842): стадия записи атомарной preview pair (между
# успешным style edit и терминальным completed). Аддитивно к §42.
STATE_SAVING_PREVIEW = "SAVING_PREVIEW"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"

# Маппинг state → task_jobs.status (§42).
TASK_STATUS_BY_STATE = {
    STATE_CREATED: "queued",
    STATE_BASE_SUBMITTED: "running",
    STATE_BASE_RUNNING: "running",
    STATE_BASE_SUCCEEDED: "running",
    STATE_BASE_FAILED: "running",
    STATE_STYLE_SUBMITTED: "running",
    STATE_STYLE_RUNNING: "running",
    STATE_STYLE_SUCCEEDED: "running",
    STATE_STYLE_FAILED: "running",
    STATE_PUBLISH_RICH: "running",
    STATE_PUBLISH_PLAIN: "running",
    STATE_SAVING_PREVIEW: "running",
    STATE_DONE: "completed",
    STATE_FAILED: "failed",
}

MODE_PRODUCTION = "production"
MODE_PREVIEW = "preview"

# ── §45: whitelist безопасных лог-полей ─────────────────────────────────────
SAFE_LOG_FIELDS = frozenset({
    "run_id", "job_id", "style_id", "style_revision", "issue_number",
    "connection_id", "provider", "model", "prompt_len", "prompt_hash",
    "reference_count", "duration_ms", "latency_ms", "provider_task_id",
    "status", "fallback", "fallback_mode", "outcome", "reason", "attempt",
    "async_used", "reference_paths", "mode", "resolve_source",
    # ASAP-4 волна B (spec §2 B.1/B.4/B.5, T-4415/T-4418/T-4419): snapshot,
    # integrity-метрики и prompt diagnostics — только id/числа/enum (R17).
    "selection_source", "enabled", "pipeline_mode", "capability_state",
    "reference_bytes_total", "instruction_chars", "brief_chars",
    "compiled_chars", "limit_unit", "issue_present",
    # ASAP 4.4 (§2, T-4873/T-4874): effective route/источник capability —
    # enum/числа (R17-safe).
    "edit_route", "limit_source", "limit_source_taxonomy", "capability_source",
    "limit_value",
})

# F-N3 (ASAP 4.4, owner acceptance §3/§9): R17-safe extras, которые
# `emit_cover_event` дополнительно кладёт в `usage_json` MCA-события — Run
# Inspector читает structured-события (не human-логи §61.12). Только
# id/числа/enum (подмножество SAFE_LOG_FIELDS); тексты/секреты не входят.
_INSPECTOR_USAGE_FIELDS = frozenset({
    "style_id", "style_revision", "issue_number", "selection_source",
    "resolve_source", "prompt_len", "compiled_chars", "limit_value",
    "limit_unit", "limit_source", "limit_source_taxonomy",
    "capability_source", "capability_state", "instruction_chars",
    "brief_chars", "reference_count", "reference_bytes_total",
    "issue_present", "fallback", "mode", "pipeline_mode", "enabled",
    "async_used", "edit_route",
})


def _pg():
    """PgDatabase из runtime-кэша (fail-open → None)."""
    try:
        from services import hot_config as hot
        cache = hot.get_config_cache()
        if cache is None:
            return None
        return getattr(cache, "pg", None)
    except Exception:
        return None


def _pool(pg=None):
    obj = pg if pg is not None else _pg()
    return getattr(obj, "pool", None) if obj is not None else None


def rich_degraded_enabled() -> bool:
    """§50/§51: разрешён degraded-режим «Rich без обложки» (env-only, default ON)."""
    try:
        return bool(getattr(settings, "COVER_RICH_DEGRADED_ENABLED", True))
    except Exception:
        return True


def snapshot_enabled() -> bool:
    """ASAP-4 волна B (spec §2/§8.2, ADR-1028-7 D6): kill-switch
    `COVER_STYLE_SNAPSHOT_ENABLED` (env-only, default ON).

    ON — selection snapshot + SELECTION event + видимый fail-open (distinct
    reason codes, SKIPPED events, provenance при всех исходах, issue counter
    только на реальные submissions). OFF — бит-в-бит прежний контур волны
    EXTRA/ASAP-3.2: без snapshot/SELECTION, тихие ранние выходы, прежний
    порядок вызовов (parity-тест)."""
    try:
        return bool(getattr(settings, "COVER_STYLE_SNAPSHOT_ENABLED", True))
    except Exception:
        return True


def prompt_hash(text: str) -> str:
    """Короткий R17-safe хэш промпта (для логов; §45)."""
    return hashlib.sha256(
        str(text or "").encode("utf-8")).hexdigest()[:16]


def safe_log_fields(**fields) -> dict:
    """Оставить только whitelisted поля (§45)."""
    return {k: v for k, v in fields.items()
            if k in SAFE_LOG_FIELDS and v is not None}


def emit_cover_event(event: str, *, outcome: str = "success",
                     level: int = logging.INFO, run_id: str | None = None,
                     job_id: str | None = None, chat_id: int | None = None,
                     model: str | None = None, provider: str | None = None,
                     duration_ms: int | None = None,
                     attempt: int | None = None,
                     reason_code: str | None = None,
                     status: str | None = None, **extra) -> None:
    """Стадийное событие §44: grep-able лог + best-effort MCA-эмиссия.

    Лог — R17-safe (whitelist §45). MCA-эмиссия fail-open: если контракт
    события отклонит поле — оно просто не попадает в событие.
    """
    fields = safe_log_fields(**extra)
    parts = ["%s=%s" % (k, v) for k, v in fields.items()]
    parts.append("status=%s" % (status or outcome))
    if chat_id is not None:
        parts.append("chat_id=%s" % chat_id)
    line = "%s | %s" % (event, " | ".join(parts))
    if level >= logging.ERROR:
        logger.error(line)
    elif level >= logging.WARNING:
        logger.warning(line)
    else:
        logger.info(line)
    # F-N3: extras → `usage_json` MCA-события (structured Inspector source;
    # `build_event` отбрасывает незаявленные ключи-колонки — без этого route/
    # compiled/source оставались только в log-line).
    usage = {k: v for k, v in fields.items()
             if k in _INSPECTOR_USAGE_FIELDS and v is not None}
    try:
        from services import mca_trace as trace
        outcome_map = {"success": "success", "failed": "failed",
                       "start": "start", "skipped": "skipped",
                       "pending_external": "pending_external"}
        trace.emit_stage(
            event, outcome=outcome_map.get(outcome, "success"),
            level=("ERROR" if level >= logging.ERROR else
                   "WARN" if level >= logging.WARNING else "INFO"),
            component="cover", stage=status or outcome,
            model=model, provider=provider, duration_ms=duration_ms,
            attempt=attempt, reason_code=reason_code,
            usage_json=usage or None,
            **trace.span_fields(run_id=run_id, pipeline_type="summary.cover",
                                job_id=job_id))
    except Exception:
        return


# ── §47/§96: классификация + timeline ───────────────────────────────────────

def classify_cover_result(*, published_channel: str, cover_outcome: str,
                          cover_reason: str = "") -> dict:
    """Классифицировать результат публикации по §96 (для логов/UI).

    `cover_outcome` ∈ {styled, base, none}; `published_channel` ∈ {rich,
    plain}; `cover_reason` ∈ {"", style_failed, base_failed}.
    """
    if published_channel == "plain":
        return {"cover_result": RESULT_NONE, "publication": RESULT_PLAIN,
                "reason": REASON_RICH_FAILED, "fallback": "rich_failed"}
    if cover_outcome == RESULT_STYLED:
        return {"cover_result": RESULT_STYLED, "publication": "rich",
                "reason": "", "fallback": None}
    if cover_outcome == RESULT_BASE:
        return {"cover_result": RESULT_BASE, "publication": "rich",
                "reason": cover_reason or REASON_STYLE_FAILED,
                "fallback": cover_reason or REASON_STYLE_FAILED}
    return {"cover_result": RESULT_NONE, "publication": "rich",
            "reason": cover_reason or REASON_BASE_FAILED,
            "fallback": cover_reason or REASON_BASE_FAILED}


def build_timeline(*, text_ms=None, base_ms=None, style_ms=None,
                   rich_ms=None, base_ok=True, style_enabled=False,
                   style_ok=False, rich_ok=True) -> list[dict]:
    """Таймлайн §47 (для analytics/UI) — только факты, без выдуманных чисел."""
    def step(name, ok, ms):
        row = {"name": name, "ok": bool(ok)}
        if ms is not None:
            row["duration_ms"] = int(ms)
        return row

    rows = [step("Текст саммари", True, text_ms)]
    rows.append(step("Базовая обложка", base_ok, base_ms))
    if style_enabled:
        rows.append(step("Обработка стилем", style_ok, style_ms))
    rows.append(step("Публикация", rich_ok, rich_ms))
    return rows


def ru_status_for(outcome: str) -> str:
    """RU-статус пользователю по исходу (§48/§75)."""
    return {
        RESULT_BASE: RU_STYLE_FAILED,
        RESULT_NONE: RU_BASE_FAILED,
        RESULT_PLAIN: RU_RICH_FAILED,
    }.get(outcome, "")


# ── §68/§92: process-local latency/cost observability ───────────────────────

_LATENCY: dict[str, list[dict]] = {}
_COSTS: dict[str, dict] = {}


def _metrics_enabled() -> bool:
    try:
        return bool(getattr(settings, "COVER_STYLE_METRICS_ENABLED", True))
    except Exception:
        return True


def record_latency(model: str, stage: str, latency_ms: int, *,
                   timeout: bool = False, retry: bool = False,
                   provider_fallback: bool = False) -> None:
    """Записать наблюдение latency (§68). UNKNOWN ≠ 0: 0 ms — валидное значение."""
    if not _metrics_enabled():
        return
    key = "%s|%s" % (stage, model or "unknown")
    _LATENCY.setdefault(key, []).append({
        "ms": max(0, int(latency_ms or 0)),
        "timeout": bool(timeout), "retry": bool(retry),
        "provider_fallback": bool(provider_fallback)})


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def latency_stats() -> dict:
    """p50/p95/max/timeout/retry/provider-fallback по model/stage (§68)."""
    out: dict[str, dict] = {}
    for key, rows in _LATENCY.items():
        values = [r["ms"] for r in rows]
        out[key] = {
            "count": len(rows), "p50": _percentile(values, 50),
            "p95": _percentile(values, 95), "max": max(values) if values else 0,
            "timeout_count": sum(1 for r in rows if r["timeout"]),
            "retry_count": sum(1 for r in rows if r["retry"]),
            "provider_fallback_count": sum(
                1 for r in rows if r["provider_fallback"]),
        }
    return out


def record_cost(stage: str, cost_usd: float | None, *,
                mode: str = MODE_PRODUCTION) -> None:
    """Раздельно base/style/preview cost (§92); preview маркируется (§67)."""
    if not _metrics_enabled():
        return
    if cost_usd is None:
        return                          # UNKNOWN ≠ 0: не выдумываем стоимость
    bucket = _COSTS.setdefault(stage, {"production": 0.0, "preview": 0.0,
                                       "known": False})
    bucket[mode if mode in ("production", "preview") else "production"] \
        += float(cost_usd)
    bucket["known"] = True


def cost_summary() -> dict:
    """Свод cost по стадиям (§92): preview не смешивается с production."""
    return {stage: dict(vals) for stage, vals in _COSTS.items()}


def reset_metrics() -> None:
    """Сброс process-local метрик (тесты/диагностика)."""
    _LATENCY.clear()
    _COSTS.clear()


# ── §42/§43: durable job state (REUSE task_jobs/mca_pipeline_runs) ──────────

@dataclass
class CoverJobState:
    """Снимок состояния cover-джобы (персистится в checkpoint_ref/payload).

    Позволяет пережить restart: при асинхронном провайдере `provider_task_id`
    сохраняется, чтобы после рестарта продолжить polling и **не** создать
    новый платный task (§43).
    """

    state: str = STATE_CREATED
    provider_task_id: str | None = None
    style_id: str | None = None
    issue_number: int | None = None
    stages: list = field(default_factory=list)
    # ASAP 4.3 (§2.2, T-4842): безопасные diagnostics preview-джобы для
    # status-endpoint (без prompt/ключей) + provenance preview pair (§4).
    provider: str | None = None
    model: str | None = None
    mode: str | None = None
    base_asset_id: str | None = None
    preview_before_asset_id: str | None = None
    preview_after_asset_id: str | None = None
    preview_revision: int | None = None
    machine_reason: str | None = None
    human_message: str | None = None
    prompt_diagnostics: dict | None = None
    # ASAP 4.4 (§RC-D/T-4870): draft snapshot Test Style (style-affecting поля,
    # которые видел editor) + его fingerprint для promote (§RC-E/T-4872).
    # Snapshot — не профиль: в DB не сохраняется, живёт в durable job state.
    draft_snapshot: dict | None = None
    draft_fingerprint: str | None = None
    # ASAP 5 (D7/T-5249): CoverPromptManifest — фактические sent prompt'ы
    # (обе attempts) + компоненты. Полный prompt живёт ТОЛЬКО здесь (durable
    # job evidence, bounded retention вместе с task_jobs); наружу — только
    # admin-authorized API через cpa.manifest_public (fail-closed).
    prompt_manifest: dict | None = None
    # ── ASAP 8 v6 C03A: recovery-контур styled cover ──
    # Durable путь сохранённой Base (recovery-артефакт run'а): вторая попытка
    # style использует ЕЁ — повторная генерация Base запрещена (v6 кейс 2/3).
    base_asset_path: str | None = None
    # Durable styled-артефакт успешной (в т.ч. восстановленной) обработки.
    styled_asset_path: str | None = None
    # Честный styled-статус для Inspector:
    # styled | failed | retry_scheduled | base_fallback | None.
    styled_status: str | None = None
    styled_fail_reason: str | None = None
    styled_route: str | None = None
    # B04.5: честный статус доставки восстановленного styled
    # (not_attempted_policy_off | replaced | rich_message_edit_unsupported |
    # publication_reference_missing); None — recovery не завершался.
    telegram_delivery: str | None = None
    # Счётчик recovery-попыток (bounded; начальная инлайн-попытка не считается).
    retry_count: int = 0

    def mark(self, state: str, *, provider_task_id: str | None = None,
             note: str | None = None) -> None:
        self.state = state
        if provider_task_id is not None:
            self.provider_task_id = provider_task_id
        entry = {"state": state, "at": int(time.time())}
        if note:
            entry["note"] = note
        self.stages.append(entry)
        if len(self.stages) > 32:
            del self.stages[:-32]

    @property
    def task_status(self) -> str:
        return TASK_STATUS_BY_STATE.get(self.state, "running")

    def to_json(self) -> str:
        return json.dumps({
            "state": self.state, "provider_task_id": self.provider_task_id,
            "style_id": self.style_id, "issue_number": self.issue_number,
            "provider": self.provider, "model": self.model, "mode": self.mode,
            "base_asset_id": self.base_asset_id,
            "preview_before_asset_id": self.preview_before_asset_id,
            "preview_after_asset_id": self.preview_after_asset_id,
            "preview_revision": self.preview_revision,
            "machine_reason": self.machine_reason,
            "human_message": self.human_message,
            "prompt_diagnostics": self.prompt_diagnostics,
            "draft_snapshot": self.draft_snapshot,
            "draft_fingerprint": self.draft_fingerprint,
            "prompt_manifest": self.prompt_manifest,
            # ASAP 8 v6 C03A: recovery-поля (additive, backward-compatible).
            "base_asset_path": self.base_asset_path,
            "styled_asset_path": self.styled_asset_path,
            "styled_status": self.styled_status,
            "styled_fail_reason": self.styled_fail_reason,
            "styled_route": self.styled_route,
            "telegram_delivery": self.telegram_delivery,
            "retry_count": int(self.retry_count or 0),
            "stages": self.stages[-32:]}, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | None) -> "CoverJobState":
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(
            state=str(data.get("state") or STATE_CREATED),
            provider_task_id=data.get("provider_task_id"),
            style_id=data.get("style_id"),
            issue_number=data.get("issue_number"),
            provider=data.get("provider"),
            model=data.get("model"),
            mode=data.get("mode"),
            base_asset_id=data.get("base_asset_id"),
            preview_before_asset_id=data.get("preview_before_asset_id"),
            preview_after_asset_id=data.get("preview_after_asset_id"),
            preview_revision=data.get("preview_revision"),
            machine_reason=data.get("machine_reason"),
            human_message=data.get("human_message"),
            prompt_diagnostics=(data.get("prompt_diagnostics")
                                if isinstance(data.get("prompt_diagnostics"),
                                              dict) else None),
            draft_snapshot=(data.get("draft_snapshot")
                            if isinstance(data.get("draft_snapshot"),
                                          dict) else None),
            draft_fingerprint=data.get("draft_fingerprint"),
            prompt_manifest=(data.get("prompt_manifest")
                             if isinstance(data.get("prompt_manifest"),
                                           dict) else None),
            base_asset_path=data.get("base_asset_path"),
            styled_asset_path=data.get("styled_asset_path"),
            styled_status=data.get("styled_status"),
            styled_fail_reason=data.get("styled_fail_reason"),
            styled_route=data.get("styled_route"),
            telegram_delivery=data.get("telegram_delivery"),
            retry_count=int(data.get("retry_count") or 0),
            stages=list(data.get("stages") or []))


async def start_cover_job(db, *, chat_id: int, correlation_id: str | None = None,
                          payload: dict | None = None,
                          job_id: str | None = None,
                          coalesce_key: str | None = None,
                          kind: str = "cover_style") -> str | None:
    """Создать durable cover-джобу в существующей очереди (REUSE, §42).

    При `coalesce_key` возвращается `job_id` уже активной (queued/running)
    джобы — singleflight/restart-resume (§42/§43); новый платный task не
    создаётся повторно.
    """
    if db is None:
        return None
    jid = job_id or ("cov_" + uuid.uuid4().hex)
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return await store.enqueue(
            owner="summary", kind=kind, coalesce_key=coalesce_key,
            payload=json.dumps({"chat_id": chat_id,
                                "correlation_id": correlation_id,
                                **(payload or {})}, ensure_ascii=False),
            job_id=jid)
    except Exception:
        logger.warning("[cover_style_jobs] durable job start failed",
                       exc_info=True)
        return None


async def finish_cover_job(db, job_id: str | None, *, outcome: str,
                           reason_code: str | None = None,
                           checkpoint: CoverJobState | None = None) -> bool:
    """Терминальный исход durable cover-джобы (§42/§43)."""
    if db is None or not job_id:
        return False
    status = "completed" if outcome in (STATE_DONE, RESULT_STYLED,
                                        RESULT_BASE) else "failed"
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return await store.finish(
            job_id, status=status, reason_code=reason_code,
            result_ref=(checkpoint.to_json() if checkpoint else None))
    except Exception:
        logger.warning("[cover_style_jobs] durable job finish failed",
                       exc_info=True)
        return False


async def save_cover_state(db, job_id: str | None,
                           state: CoverJobState) -> bool:
    """Сохранить снимок состояния (restart recovery, §43)."""
    if db is None or not job_id:
        return False
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        return bool(await store.save_checkpoint(
            job_id, cursor_token=state.to_json(), processed=len(state.stages),
            checkpoint_ref=state.state))
    except Exception:
        logger.warning("[cover_style_jobs] durable state save failed",
                       exc_info=True)
        return False


async def load_cover_state(db, job_id: str | None) -> CoverJobState | None:
    """Восстановить снимок состояния из `task_jobs` (None — нет/битый, §43)."""
    if db is None or not job_id:
        return None
    try:
        from services.task_supervisor import TaskJobStore
        store = TaskJobStore(db)
        checkpoint = await store.get_checkpoint(job_id)
    except Exception:
        return None
    if not checkpoint:
        return None
    raw = checkpoint.get("cursor")
    if not raw:
        return None
    return CoverJobState.from_json(raw)


async def get_cover_job(db, job_id: str | None) -> dict | None:
    """Строка durable cover-джобы из `task_jobs` (None — нет/PG недоступен)."""
    if db is None or not job_id:
        return None
    try:
        from services.task_supervisor import TaskJobStore
        return await TaskJobStore(db).get(job_id)
    except Exception:
        return None


async def requeue_cover_job(db, job_id: str | None, *,
                            reason_code: str | None = None) -> bool:
    """Вернуть терминальную cover-джобу в `queued` (новый цикл Test Style,
    §2.3/T-4843): та же строка — без второй очереди и дублей."""
    if db is None or not job_id:
        return False
    try:
        from services.task_supervisor import TaskJobStore
        return bool(await TaskJobStore(db).requeue(
            job_id, reason_code=reason_code))
    except Exception:
        return False


def cover_job_key(*, summary_run_id: str | None,
                  style_id: str | None) -> str:
    """Детерминированный `job_id` cover-джобы run+style (§42/§43).

    Один и тот же Summary-run + style → один durable job (restart-resume),
    а не новая строка/повторный платный task.
    """
    raw = "%s|%s" % (summary_run_id or "", style_id or "")
    return "cov_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


async def begin_cover_job(db, *, chat_id: int,
                          correlation_id: str | None = None,
                          style_id: str | None = None,
                          summary_run_id: str | None = None,
                          payload: dict | None = None,
                          kind: str = "cover_style",
                          initial_state: str = STATE_BASE_SUCCEEDED,
                          ) -> tuple[str | None, CoverJobState]:
    """Создать/переиспользовать durable cover-джобу (§42/§43).

    Возвращает `(job_id, state)`. При рестарте существующая джоба находится
    по детерминированному `job_id`/`coalesce_key`, а состояние (включая
    `provider_task_id`) восстанавливается из `task_jobs` — новый платный
    task **не** создаётся (§43, DoD-25).

    `initial_state` (ASAP 4.3, T-4842): production-путь стартует с
    `BASE_SUCCEEDED` (base уже готова до Style-джобы); Test Style preview —
    с `CREATED` (base генерируется внутри джобы).
    """
    if db is None:
        return None, CoverJobState(style_id=style_id)
    coalesce = ("cover_style:%s" % summary_run_id) if summary_run_id else None
    jid = cover_job_key(summary_run_id=summary_run_id, style_id=style_id)
    started = await start_cover_job(
        db, chat_id=chat_id, correlation_id=correlation_id,
        payload={"style_id": style_id, **(payload or {})},
        job_id=jid, coalesce_key=coalesce, kind=kind)
    state = await load_cover_state(db, started) if started else None
    if state is None:
        state = CoverJobState(style_id=style_id)
        # Base-стадия уже успешна к моменту запуска Style-джобы (§3.2/§49).
        state.mark(initial_state)
    return started, state


async def _persist_state(db, job_id: str | None,
                         state: CoverJobState | None) -> bool:
    if db is None or not job_id or state is None:
        return False
    return await save_cover_state(db, job_id, state)


# ── ASAP 5 (D7/T-5249): durable персист Base-манифеста ──────────────────────

BASE_JOB_PREFIX = "covbase_"


def base_manifest_job_key(summary_run_id: str | None) -> str:
    """Детерминированный job_id Base-манифеста run'а (restart-safe: одна
    строка task_jobs на Summary run, повторный прогон — no-op)."""
    raw = str(summary_run_id or "")
    return BASE_JOB_PREFIX + hashlib.sha256(
        raw.encode("utf-8")).hexdigest()[:24]


async def record_base_cover_manifest(db, *, summary_run_id: str | None,
                                     chat_id: int | None = None,
                                     manifest: dict | None) -> bool:
    """Персист Base CoverPromptManifest в существующем job-evidence (D7).

    Носитель — `task_jobs` (kind=cover_base, payload/checkpoint как у Style
    Edit, retention bounded вместе с ним); полный prompt в generic log НЕ
    попадает. Fail-open: нет БД/run_id — False (обложка не ломается)."""
    if db is None or not summary_run_id or not isinstance(manifest, dict):
        return False
    jid = base_manifest_job_key(summary_run_id)
    try:
        started = await start_cover_job(
            db, chat_id=int(chat_id or 0), correlation_id=str(summary_run_id),
            payload={"kind": "cover_base"}, job_id=jid,
            coalesce_key="cover_base:%s" % summary_run_id,
            kind="cover_base")
        if not started:
            return False
        state = await load_cover_state(db, started)
        if state is None:
            state = CoverJobState()
        state.prompt_manifest = manifest
        await _persist_state(db, started, state)
        await finish_cover_job(db, started, outcome=RESULT_BASE)
        return True
    except Exception:
        logger.warning("[cover_style_jobs] base manifest persist failed",
                       exc_info=True)
        return False


async def load_base_cover_manifest(db, summary_run_id: str | None) -> dict | None:
    """Прочитать Base-манифест run'а (None — нет/битый). Полный prompt
    отдаётся только admin-authorized вызывающим (ср. cpa.manifest_public)."""
    if db is None or not summary_run_id:
        return None
    state = await load_cover_state(db, base_manifest_job_key(summary_run_id))
    if state is None:
        return None
    return state.prompt_manifest


# ── profile/selection helpers ───────────────────────────────────────────────

async def resolve_selected_style_id(chat_id: int) -> str:
    from services.cover_style_pipeline import resolve_selected_style_id as _r
    return await _r(chat_id)


async def load_profile(pg, style_id: str) -> dict | None:
    return await registry.get_profile_with_refs(pg, style_id)


async def load_selected_profile(chat_id: int, pg=None) -> dict | None:
    """Профиль выбранного per-chat стиля (или None → `Без дополнительного стиля`)."""
    style_id = await resolve_selected_style_id(chat_id)
    if not style_id:
        return None
    obj = pg if pg is not None else _pg()
    if _pool(obj) is None:
        return None
    return await registry.get_profile_with_refs(obj, style_id)


# ── ASAP-4 волна B: selection snapshot (spec §2 B.1, T-4415, ADR-1028-7 D6) ──

KEY_SELECTED_STYLE_PARAM = "prompts.summary_cover_style_id"


async def _selection_source(chat_id: int) -> str:
    """Источник выбора (§36): `chat` (per-chat override) | `global` | `none`.

    Зеркалит резолв `resolve_selected_style_id` (override чата → global),
    не вычисляя значение вторично из другого источника.
    """
    try:
        from services import chat_params as cp
        cache = cp.get_chat_params_cache()
        root = await cache.get_chat_params(chat_id) if cache else {}
        override = str((root.get("overrides") or {}).get(
            KEY_SELECTED_STYLE_PARAM) or "").strip()
        if override:
            return "chat"
        from services import hot_config as hot
        if str(hot.get(KEY_SELECTED_STYLE_PARAM, "") or "").strip():
            return "global"
    except Exception:
        return "none"
    return "none"


async def resolve_selection(chat_id: int, pg=None) -> dict:
    """ЕДИНАЯ точка резолва стиля на run (§36, R4-B-001).

    В начале cover publication фиксируется snapshot:
    `chat_id / selected_style_id / style_revision / selection_source
    (chat|global|none) / enabled / pipeline_mode` + профиль (internal carry,
    в событие не попадает). Повторная резолюция style ID в конце run
    запрещена — Style stage работает по этому снимку.
    """
    style_id = await resolve_selected_style_id(chat_id)
    source = "none"
    profile = None
    if style_id:
        source = await _selection_source(chat_id)
        obj = pg if pg is not None else _pg()
        if _pool(obj) is not None:
            try:
                profile = await registry.get_profile_with_refs(obj, style_id)
            except Exception:
                profile = None
    return {
        "chat_id": chat_id,
        "selected_style_id": style_id or None,
        "style_revision": (profile or {}).get("revision"),
        "selection_source": source,
        "enabled": bool((profile or {}).get("enabled")),
        "pipeline_mode": pipeline_mode(profile),
        "_profile": profile,
    }


def emit_style_selection(snapshot: dict, *, run_id: str | None = None) -> None:
    """`COVER_STYLE_SELECTION` (§37, R4-B-002): до base generation/style edit.

    R17-safe: только chat_id/id/revision/enum/bool. Для выбранного
    `medved_press` выбор виден до первого image API-вызова.
    """
    emit_cover_event(
        COVER_STYLE_SELECTION, outcome="start", run_id=run_id,
        chat_id=(snapshot or {}).get("chat_id"),
        style_id=(snapshot or {}).get("selected_style_id"),
        style_revision=(snapshot or {}).get("style_revision"),
        selection_source=(snapshot or {}).get("selection_source"),
        enabled=(snapshot or {}).get("enabled"),
        pipeline_mode=(snapshot or {}).get("pipeline_mode"))


async def selection_stage(chat_id: int, *, run_id: str | None = None,
                          pg=None) -> dict | None:
    """Snapshot + SELECTION event на старте cover publication (fail-open).

    Kill-switch OFF (или резолв недоступен) → None — вызывающий идёт по
    прежнему тихому контуру (бит-в-бит).
    """
    if not snapshot_enabled():
        return None
    try:
        snapshot = await resolve_selection(chat_id, pg=pg)
    except Exception:
        return None
    try:
        emit_style_selection(snapshot, run_id=run_id)
    except Exception:
        pass
    return snapshot


async def profile_for_snapshot(snapshot: dict,
                               pg=None) -> tuple[dict | None, str]:
    """Профиль из snapshot'а + причина раннего выхода ("" — причины нет).

    Раздельные причины (§2 B.4): `no_style` (ничего не выбран) /
    `profile_missing` (выбранный профиль удалён/PG недоступен) /
    `disabled` (профиль выключен). Режим без Style-стадии — НЕ fail: виден
    в SELECTION event (`pipeline_mode`).
    """
    snapshot = snapshot or {}
    style_id = str(snapshot.get("selected_style_id") or "").strip()
    if not style_id:
        return None, REASON_NO_STYLE
    profile = snapshot.get("_profile")
    if profile is None:
        obj = pg if pg is not None else _pg()
        if _pool(obj) is not None:
            try:
                profile = await registry.get_profile_with_refs(obj, style_id)
            except Exception:
                profile = None
    if profile is None:
        return None, REASON_PROFILE_MISSING
    if not profile.get("enabled"):
        return None, REASON_DISABLED
    return profile, ""


async def report_style_skip(snapshot: dict, *, summary_run_id: str | None,
                            reason: str,
                            base_asset_id: str | None = None) -> None:
    """Видимый fail-open (§42–§44, T-4419): SKIPPED event + provenance.

    Публикация не ломается (base уходит как есть), но причина видна:
    отдельный `COVER_STYLE_SKIPPED` с reason + human-перевод в логе.
    Потеря ВЫБРАННОГО стиля (profile_missing/disabled) — WARNING;
    `no_style` (ничего не выбрано — штатная конфигурация, источник виден в
    COVER_STYLE_SELECTION `selection_source=none`) — INFO без спама.
    Provenance base_fallback — только при выбранном стиле; issue counter
    НЕ расходуется (submission не было)."""
    snapshot = snapshot or {}
    detail = reason_detail_ru(reason)
    level = logging.INFO if reason == REASON_NO_STYLE else logging.WARNING
    emit_cover_event(
        COVER_STYLE_SKIPPED, outcome="skipped", level=level,
        run_id=summary_run_id, chat_id=snapshot.get("chat_id"),
        style_id=snapshot.get("selected_style_id"),
        style_revision=snapshot.get("style_revision"),
        reason=reason, reason_code=style_reason_code(reason),
        fallback=(REASON_STYLE_FAILED
                  if snapshot.get("selected_style_id") else None))
    if detail:
        (logger.warning if level >= logging.WARNING else logger.info)(
            "summary cover: style not applied | chat_id=%s | reason=%s | "
            "detail=%s", snapshot.get("chat_id"), reason, detail)
    if not snapshot.get("selected_style_id"):
        return
    await _record_provenance(
        _pg(), {
            "style_id": snapshot.get("selected_style_id"),
            "style_revision": snapshot.get("style_revision"),
            "issue_number": None,
            "base_asset_id": base_asset_id, "final_asset_id": None,
            "provider": "", "model": "",
        }, summary_run_id=summary_run_id, job_id=None, snapshot=None,
        status=registry.PROVENANCE_BASE, fallback_mode=reason,
        mode=MODE_PRODUCTION)


async def record_no_cover_provenance(snapshot: dict, *,
                                     summary_run_id: str | None) -> None:
    """§44: provenance `no_cover` — base generation не удалась (видимый исход).

    Только при выбранном стиле (есть что записать); fail-open.
    """
    snapshot = snapshot or {}
    if not snapshot.get("selected_style_id"):
        return
    await _record_provenance(
        _pg(), {
            "style_id": snapshot.get("selected_style_id"),
            "style_revision": snapshot.get("style_revision"),
            "issue_number": None,
            "base_asset_id": None, "final_asset_id": None,
            "provider": "", "model": "",
        }, summary_run_id=summary_run_id, job_id=None, snapshot=None,
        status=registry.PROVENANCE_NONE, fallback_mode=REASON_BASE_FAILED,
        mode=MODE_PRODUCTION)


async def _resolve_reference_paths(pg, profile: dict) -> list[str]:
    paths: list[str] = []
    obj = pg if pg is not None else _pg()
    for ref in (profile.get("references") or []):
        asset_id = ref.get("asset_id")
        if not asset_id or obj is None:
            continue
        try:
            asset = await registry.get_asset(obj, asset_id)
        except Exception:
            asset = None
        if not asset:
            continue
        disk_path = asset.get("disk_path")
        if disk_path and os.path.exists(str(disk_path)):
            paths.append(str(disk_path))
    return paths


# ── ASAP-4 волна B: reference integrity (spec §2 B.4 §45, T-4418, R4-B-010) ──

_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", {"image/png"}),
    (b"\xff\xd8", {"image/jpeg"}),
    (b"RIFF", {"image/webp"}),      # + "WEBP" по offset 8
)


def _image_signature_ok(head: bytes, mime: str) -> bool:
    """Магические байты соответствуют заявленному MIME (§45 «изображение
    читаемо»; R17-safe — проверяются байты, контент не логируется)."""
    if mime == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    for signature, mimes in _IMAGE_SIGNATURES:
        if head.startswith(signature) and mime in mimes:
            return True
    return False


async def _resolve_reference_details(pg, profile: dict) -> list[dict]:
    """Целостность референсов (§45): DB-row / файл / MIME / читаемость / байты.

    Возвращает по записи на каждый референс профиля (R17-safe: asset_id +
    булевы + размер, без контента). `path` — только у готовых к отправке.
    """
    obj = pg if pg is not None else _pg()
    details: list[dict] = []
    for ref in (profile.get("references") or []):
        entry = {"asset_id": ref.get("asset_id"), "db_row": False,
                 "file": False, "mime_ok": False, "readable": False,
                 "bytes": 0, "path": None}
        asset_id = ref.get("asset_id")
        if asset_id and obj is not None:
            try:
                asset = await registry.get_asset(obj, asset_id)
            except Exception:
                asset = None
            if asset:
                entry["db_row"] = True
                entry["mime_ok"] = str(asset.get("mime") or "") \
                    in assets.ALLOWED_MIME
                disk_path = asset.get("disk_path")
                if disk_path and os.path.exists(str(disk_path)):
                    entry["file"] = True
                    try:
                        with open(disk_path, "rb") as handle:
                            head = handle.read(16)
                        entry["bytes"] = os.path.getsize(disk_path)
                        entry["readable"] = _image_signature_ok(
                            head, str(asset.get("mime") or ""))
                        if entry["readable"]:
                            entry["path"] = str(disk_path)
                    except OSError:
                        entry["readable"] = False
        details.append(entry)
    return details


async def profile_diagnostics(pg, profile: dict, *,
                              connection: dict | None = None) -> dict:
    """Чек-лист полей профиля §41 (T-4418, R4-B-006) — R17-safe.

    profile_id/revision/enabled/pipeline_mode/connection/provider/model/
    capability image_edit/reference count/file readable/instruction/counter.
    Секретов нет (api_key не читается вовсе — только наличие записи
    подключения резолвится выше по `connection_status`).
    """
    profile = profile or {}
    # ASAP 4.4 (§2/T-4873): diagnostics/Inspector — тот же effective resolver,
    # что UI meta/production (лестница §35), а не отдельный sync-контур.
    resolved = await resolve_effective_edit_capability(
        profile=profile, connection=connection, pg=pg,
        operation=cap.OPERATION_EDIT)
    slot = resolved["slot"]
    caps = resolved["capabilities"]
    refs = await _resolve_reference_details(pg, profile)
    return {
        "profile_id": profile.get("profile_id"),
        "revision": profile.get("revision"),
        "enabled": bool(profile.get("enabled")),
        "pipeline_mode": pipeline_mode(profile),
        "connection_id": slot.get("connection_id"),
        "connection_configured": bool(slot.get("configured")),
        "custom_unresolved": bool(slot.get("custom_unresolved")),
        "provider": slot.get("provider") or "",
        "model": slot.get("model") or "",
        "resolve_source": resolved.get("resolve_source") or "",
        "edit_route": resolved.get("route") or "",
        "capability_image_edit": caps.image_edit,
        "capability_source": caps.source,
        "limit_source": caps.prompt_limit.source,
        "limit_source_taxonomy": cap.prompt_limit_source_taxonomy(
            caps.prompt_limit.source),
        "limit_value": caps.prompt_limit.value if caps.prompt_limit.known
        else None,
        "references": {
            "configured": len(profile.get("references") or []),
            "ready": sum(1 for d in refs if d.get("readable")),
            "bytes_total": sum(d.get("bytes") or 0 for d in refs),
            "details": refs,
        },
        "instruction_chars": len(str(profile.get("instruction") or "")),
        "counter_enabled": bool(profile.get("counter_enabled")),
        "counter_value": profile.get("counter_value"),
    }


# ── prompt compilation (§19–§21) ────────────────────────────────────────────

def style_reference_text(profile: dict) -> str:
    """P2-текст описаний референсов (§19; единый источник для compile/manifest)."""
    refs = profile.get("references") or []
    if not refs:
        return ""
    return "; ".join(
        "%s: %s" % (r.get("label") or "reference",
                    r.get("description") or "")
        for r in refs)


# ══ ASAP 8 v6.3 B04: компактный EDIT-контракт (не GENERATE) ══════════════════
# Источник сцены в image-to-image — Base bitmap (+ референс логотипа).
# story_scene/summary ПОВТОРНО в текст не переносится (дефект 1133/800);
# сцена в тексте максимум ОДИН раз (опциональный короткий anchor); один язык
# (язык инструкции профиля); semantic dedupe компонентов; preflight
# chars/tokens в единицах capability с configurable headroom; overflow →
# платный вызов НЕ делается.

def style_edit_headroom_chars() -> int:
    """B04.3: configurable headroom preflight (env
    `COVER_STYLE_EDIT_HEADROOM_CHARS`, default 0) — запас на gateway/transport
    wrapper. НЕ искусственное увеличение лимита: вычитается из известного,
    неизвестный лимит headroom не меняет."""
    raw = os.getenv("COVER_STYLE_EDIT_HEADROOM_CHARS", "").strip()
    try:
        value = int(raw) if raw else 0
    except ValueError:
        return 0
    return max(0, min(value, 400))


# Компактные компоненты EDIT: канон в `cover_prompt_assembly` (единый
# источник для compile/манифеста); здесь — совместимые алиасы.
edit_preservation_text = cpa.edit_preservation_text
edit_runtime_invariants_text = cpa.edit_runtime_invariants_text
edit_reference_roles_text = cpa.edit_reference_roles_text
edit_content_language = cpa.edit_content_language


def scene_anchor_policy() -> str:
    """B04.3: политика scene anchor (env `COVER_STYLE_EDIT_SCENE_ANCHOR`:
    ``auto`` | ``on`` | ``off``, default ``auto``).

    ``auto`` — короткий anchor только для компактного сюжета (≤240 симв.:
    маленький сюжет, который модель склонна игнорировать); ``on`` — пробовать
    всегда (первое предложение, ограничение длины сохраняется); ``off`` —
    никогда. В любом режиме anchor проходит dedupe и preflight вместимости."""
    raw = os.getenv("COVER_STYLE_EDIT_SCENE_ANCHOR", "auto").strip().lower()
    return raw if raw in ("auto", "on", "off") else "auto"


_SCENE_ANCHOR_MAX_SOURCE = 240
_SCENE_ANCHOR_MAX_CHARS = 200


def scene_anchor_candidate(story_scene: str) -> tuple[str, str]:
    """Кандидат scene anchor: первое предложение сюжета, ограниченное
    `_SCENE_ANCHOR_MAX_CHARS`. Возвращает ``(anchor, skip_reason)``:
    anchor пуст → skip_reason объясняет почему (``empty``/``policy_off``/
    ``scene_too_long``/``cut``)."""
    scene = " ".join(str(story_scene or "").split())
    if not scene:
        return "", "empty"
    policy = scene_anchor_policy()
    if policy == "off":
        return "", "policy_off"
    if policy == "auto" and len(scene) > _SCENE_ANCHOR_MAX_SOURCE:
        # Длинная сцена выражена самой Base bitmap; повтор в тексте —
        # тот самый дефект B04 (не компакт).
        return "", "scene_too_long"
    match = re.search(r"^(.+?[.!?])(?:\s|$)", scene)
    anchor = (match.group(1) if match else scene).strip()
    if len(anchor) > _SCENE_ANCHOR_MAX_CHARS:
        anchor = anchor[:_SCENE_ANCHOR_MAX_CHARS].rsplit(" ", 1)[0].strip()
    if not anchor:
        return "", "empty"
    return anchor, ""


_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WS_RUN_RE = re.compile(r"\s+")

# Стоп-слова (функциональная лексика не несёт смысла для сравнения).
_STOP_TOKENS = frozenset({
    "и", "а", "но", "не", "ни", "на", "в", "во", "с", "со", "по", "у", "за",
    "для", "же", "бы", "ли", "уже", "еще", "ещё", "которые", "который",
    "которая", "которое", "это", "этот", "эта", "there", "and", "the", "of",
    "to", "in", "on", "with", "please", "пожалуйста",
})

_RU_SUFFIXES = ("ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими",
                "ых", "их", "ах", "ях", "ов", "ев", "ам", "ям", "ой", "ей",
                "ый", "ий", "ая", "яя", "ое", "ее", "ые", "ие", "ую", "юю",
                "ом", "ем", "ы", "и", "а", "я", "е", "у", "ю", "ь")


def _stem(token: str) -> str:
    """Наивный морфологический хвост: снимает 1–3 флексии (RU) — dedupe
    сравнивает смысловые основы, а не поверхностные формы."""
    if len(token) <= 4:
        return token
    for _ in range(3):
        for suffix in _RU_SUFFIXES:
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                token = token[:len(token) - len(suffix)]
                break
        else:
            break
    return token


def _norm_sentence(text: str) -> tuple[str, frozenset[str]]:
    low = _WS_RUN_RE.sub(" ", str(text or "").lower().replace("ё", "е"))
    low = re.sub(r"[^\w\s]", " ", low).strip()
    return low, frozenset(low.split())


def _content_tokens(text: str) -> frozenset[str]:
    """Смысловые токены: стоп-слова сняты, основы простефлены."""
    _norm, toks = _norm_sentence(text)
    return frozenset(_stem(t) for t in toks
                     if t not in _STOP_TOKENS and len(t) >= 2)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Overlap-коэффициент |∩|/min — устойчив к короткому предложению
    внутри длинного (вежливые обороты, порядок слов)."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


_NEAR_DUP_JACCARD = 0.8
_NEAR_DUP_OVERLAP = 0.75


def _is_near_duplicate(toks_a: frozenset[str], toks_b: frozenset[str]) -> bool:
    toks_a = {t for t in toks_a if t not in _STOP_TOKENS}
    toks_b = {t for t in toks_b if t not in _STOP_TOKENS}
    content_a = frozenset(_stem(t) for t in toks_a)
    content_b = frozenset(_stem(t) for t in toks_b)
    if not content_a or not content_b:
        return False
    return (_jaccard(content_a, content_b) >= _NEAR_DUP_JACCARD
            or _overlap(content_a, content_b) >= _NEAR_DUP_OVERLAP)


def normalize_style_edit_components(
        components: list, *, issue_display: str = "") -> tuple[list, list[dict]]:
    """B04.3 нормализатор «style-edit prompt components».

    Semantic dedupe НА УРОВНЕ ПРЕДЛОЖЕНИЙ (не слепая подстрока): точные и
    near-дубли (Jaccard ≥ 0.8 по токенам) снимаются у НИЗКОПРИОРИТЕТНОЙ
    компоненты. Protected-токены (номер выпуска, бренд-токены референсов:
    «PERMsoc один раз, выпуск один раз») живут в тексте один раз — ПОВТОРНОЕ
    появление снимается, если предложение почти не добавляет нового смысла
    (легитимная новая инструкция с брендом сохраняется). Вход:
    ``[(label, text, priority)]`` в порядке приоритета. Выход:
    ``(normalized [(label, text, priority)], dropped [{label, reason}])``.
    Детерминировано, 0 LLM, 0 сети.
    """
    seen: list[tuple[str, frozenset[str], str]] = []
    seen_union: set[str] = set()
    emitted_protected: set[str] = set()
    dropped: list[dict] = []
    out: list[tuple[str, str, int]] = []
    _issue_norm, issue_tokens = _norm_sentence(issue_display)
    # Protected: токены выпуска + бренд-токены labels референсов (логотип).
    protected = {t for t in issue_tokens if len(t) >= 4}
    protected |= _brand_tokens_of_components(components)
    for label, text, priority in components:
        raw = _WS_RUN_RE.sub(" ", str(text or "")).strip()
        if not raw:
            continue
        kept_sentences: list[str] = []
        for sentence in _SENT_SPLIT_RE.split(raw):
            s = sentence.strip()
            if not s:
                continue
            norm, toks = _norm_sentence(s)
            dup_reason = ""
            for seen_norm, seen_toks, owner in seen:
                if norm == seen_norm:
                    dup_reason = "duplicate_of:%s" % owner
                    break
                if _is_near_duplicate(toks, seen_toks):
                    dup_reason = "near_duplicate_of:%s" % owner
                    break
            if not dup_reason:
                hits = toks & protected
                if hits and hits & emitted_protected:
                    # Повтор protected-сущности: снять, если предложение
                    # почти целиком состоит из уже сказанного.
                    new_tokens = toks - seen_union
                    if len(new_tokens) <= max(1, len(toks) // 3):
                        dup_reason = "protected_repeat"
            if dup_reason:
                dropped.append({"label": label, "reason": dup_reason})
                continue
            seen.append((norm, toks, label))
            seen_union |= toks
            emitted_protected |= (toks & protected)
            kept_sentences.append(s)
        if kept_sentences:
            out.append((label, " ".join(kept_sentences), priority))
    return out, dropped


def _brand_tokens_of_components(components: list) -> set[str]:
    """Бренд-токены: слова ≥5 символов из labels референсов (компонента
    ``references`` перечисляет labels дословно). Латиница/кириллица."""
    tokens: set[str] = set()
    for label, text, _p in components:
        if label != "references":
            continue
        for token in re.findall(r"[a-zA-Zа-яА-ЯёЁ]{5,}", str(text or "")):
            tokens.add(token.lower().replace("ё", "е"))
    return tokens


def compile_style_edit_components(profile: dict, *, issue_display: str,
                                  story_scene: str = "") -> list:
    """B04.1/B04.2: сырые компоненты EDIT-инструкции (image-to-image).

    Источник сцены — Base bitmap: story_scene/summary в текст НЕ переносится
    (кроме опционального короткого scene anchor); «что изменить» — инструкция
    профиля; «что оставить» — компактный preservation; роль референсов —
    графический образец. Pure text-to-image (base cover) здесь НЕ смешан —
    у него свой сборщик `cover_prompt_assembly`."""
    instruction = str(profile.get("instruction") or "").strip()
    lang = edit_content_language(instruction)
    refs = profile.get("references") or []
    anchor, _anchor_skip = scene_anchor_candidate(story_scene)
    components: list[tuple[str, str, int]] = [
        ("content_preservation", edit_preservation_text(lang), compiler.P0),
        ("runtime_invariants",
         edit_runtime_invariants_text(issue_display, lang), compiler.P0),
    ]
    if instruction:
        components.append(("style_instruction", instruction, compiler.P1))
    if anchor:
        components.append(("scene_anchor", anchor, compiler.P1))
    if refs:
        components.append(("references",
                           edit_reference_roles_text(refs, lang), compiler.P2))
    return components


def _headroom_caps(capabilities):
    """Копия capabilities с лимитом минус headroom (B04.3 preflight)."""
    headroom = style_edit_headroom_chars()
    if headroom <= 0 or capabilities is None:
        return capabilities, headroom
    limit = capabilities.prompt_limit
    if not limit.known or limit.value is None:
        return capabilities, headroom
    value = max(1, int(limit.value) - headroom)
    adjusted = dataclasses.replace(
        capabilities, prompt_limit=dataclasses.replace(
            limit, value=value))
    return adjusted, headroom


def compile_style_prompt(profile: dict, *, issue_display: str,
                         capabilities, base_style_prompt: str = "",
                         brief=None, story_scene: str = "",
                         retry_core: bool = False
                         ) -> compiler.CompiledPrompt:
    """Собрать compact EDIT prompt Style Edit (ASAP 8 v6.3 B04; замена
    v6-контракта «полный story identity в P1-ядре»).

    EDIT-контракт (image-to-image, источник сцены — Base bitmap):

      P0 «что оставить» — компактный preservation на языке контента;
      P0 runtime-инварианты — выпуск один раз, без дублей;
      P1 «что изменить» — инструкция профиля (стиль не добавляет событий —
        смысл зафиксирован в preservation-компоненте);
      P1 scene anchor — ОПЦИОНАЛЬНЫЙ короткий якорь сюжета (policy §см.
        `scene_anchor_policy`), проходит semantic dedupe;
      P2 роль референсов — логотип/брендинг как графический образец;
      P3 base_style_prompt — эффект base-стиля запечён в input image.

    story_scene/summary ПОЛНОСТЬЮ в текст не переносится (B04.1: дефект
    1133/800); нормализатор снимает семантические дубли предложений ДО
    fit-механики; preflight — units capability минус headroom; overflow →
    честный ``prompt_limit_exceeded`` без платного вызова (§5.4).

    `retry_core=True` (unknown-limit retry): компактное mandatory-ядро
    preservation → runtime → identity floor инструкции → ref roles; story
    floor из ядра изъят (сюжет гарантирован Base bitmap, не текстом).

    Dynamic-атрибут ``edit_report`` (dict) — normalized/preflight отчёт для
    Inspector/preview (original/deduped/final, dropped+why, язык, anchor).
    """
    raw_components = compile_style_edit_components(
        profile, issue_display=issue_display, story_scene=story_scene)
    original_text = " ".join(str(t or "") for _l, t, _p in raw_components
                             if str(t or "").strip())
    norm_components, dedupe_dropped = normalize_style_edit_components(
        raw_components, issue_display=issue_display)
    deduped_text = " ".join(str(t or "") for _l, t, _p in norm_components)
    anchor, anchor_skip = scene_anchor_candidate(story_scene)
    edit_report: dict = {
        "language": edit_content_language(
            str(profile.get("instruction") or "")),
        "original_chars": len(original_text),
        "deduped_chars": len(deduped_text),
        "dedupe_dropped": [dict(d) for d in dedupe_dropped],
        "scene_anchor": {
            "included": bool(anchor), "chars": len(anchor),
            "skip_reason": anchor_skip,
        },
        "headroom_chars": 0,
        "summary_retransferred": False,
    }
    if retry_core:
        # Unknown-limit retry: компактное mandatory-ядро (прежде — story
        # floor; B04: сюжет в Base bitmap, текстовое ядро без сюжета).
        instruction = str(profile.get("instruction") or "")
        parts = [
            edit_preservation_text(edit_report["language"]),
            edit_runtime_invariants_text(issue_display,
                                         edit_report["language"]),
            cpa.profile_identity_floor(instruction),
            cpa.reference_roles_text(profile.get("references") or []),
        ]
        prompt = " ".join(p for p in parts if p)
        dropped: list[str] = []
        sent_floor = cpa.profile_identity_floor(instruction)
        if instruction.strip() and sent_floor != instruction.strip():
            dropped.append("style_instruction_tail")
        if base_style_prompt:
            dropped.append("base_style_prompt")
        if style_reference_text(profile) and \
                style_reference_text(profile) not in prompt:
            dropped.append("references_descriptions")
        edit_report["final_chars"] = len(prompt)
        edit_report["dropped"] = list(dropped)
        compiled = compiler.CompiledPrompt(
            prompt=prompt,
            static_len=len(prompt), reserve_len=0, scene_allowance=0,
            limit=None, unit="unknown", dropped=dropped,
            original_len=len(prompt), resolved_limit=None, exceeded=False,
            reason="semantic_squeeze",
            components={
                "content_preservation": len(parts[0] if parts else ""),
                "runtime_invariants": len(parts[1] if len(parts) > 1 else ""),
                "style_instruction": len(sent_floor) if instruction else 0,
                "base_style_prompt": 0,
                "references": len(cpa.reference_roles_text(
                    profile.get("references") or [])),
                "cover_brief": 0,
            })
        compiled.edit_report = edit_report
        return compiled
    caps_eff, headroom = _headroom_caps(capabilities)
    edit_report["headroom_chars"] = headroom
    components = [compiler.PromptComponent(text, priority=priority,
                                           label=label)
                  for label, text, priority in norm_components]
    if base_style_prompt:
        components.append(compiler.PromptComponent(
            base_style_prompt, priority=compiler.P3, label="base_style_prompt"))
    compiled = compiler.compile_prompt(components, capabilities=caps_eff)
    edit_report["final_chars"] = len(compiled.prompt)
    edit_report["dropped"] = [
        {"label": label, "reason": "overflow"}
        for label in (compiled.dropped or [])
    ]
    compiled.edit_report = edit_report
    return compiled


def style_edit_preview_report(profile: dict, *, issue_display: str,
                              capabilities, base_style_prompt: str = "",
                              story_scene: str = "",
                              image_input: dict | None = None,
                              limit_source: str = "",
                              route: str = "",
                              model: str = "",
                              provider: str = "") -> dict:
    """B04.4: preview компилирует ТОТ ЖЕ маршрут, что production
    (`compile_style_prompt`), с настоящими Base/style/refs/issue/capabilities,
    и отдаёт полный отчёт компиляции БЕЗ test-контекста и БЕЗ платного
    вызова: image input, model/route, limit source, язык, original/deduped/
    final chars, dropped+why, точный финальный prompt. ``limited_preview``
    — честный маркер ограниченности (провайдер не вызывался)."""
    compiled = compile_style_prompt(
        profile, issue_display=issue_display, capabilities=capabilities,
        base_style_prompt=base_style_prompt, story_scene=story_scene)
    report = dict(getattr(compiled, "edit_report", {}) or {})
    report.update({
        "limited_preview": True,
        "image_input_used": dict(image_input or {}),
        "model": str(model or ""),
        "provider": str(provider or ""),
        "route": str(route or ""),
        "limit_source": str(limit_source or ""),
        "limit_value": (capabilities.prompt_limit.value
                        if capabilities is not None and
                        capabilities.prompt_limit.known else None),
        "limit_unit": (capabilities.prompt_limit.unit
                       if capabilities is not None else "unknown"),
        "exceeded": bool(compiled.exceeded),
        "overflow_reason": compiled.reason or "",
        "final_prompt": compiled.prompt,
        "final_prompt_chars": len(compiled.prompt),
    })
    return report


# ── B04.6: bounded scene verification (preview/canary) ──────────────────────

SCENE_VERIFY_OFF = "off"
SCENE_VERIFY_PREVIEW = "preview"
SCENE_VERIFY_ALL = "all"


def scene_verify_mode() -> str:
    """B04.6 политика image-comparison проверки сюжета (env
    `COVER_STYLE_SCENE_VERIFY`: ``preview`` | ``off`` | ``all``;
    НЕ задано → ``preview``): bounded сравнение Base vs styled на
    preview/canary прогонах; НЕ на каждый прод-вызов (бюджет)."""
    raw = os.getenv("COVER_STYLE_SCENE_VERIFY",
                    SCENE_VERIFY_PREVIEW).strip().lower()
    return raw if raw in (SCENE_VERIFY_OFF, SCENE_VERIFY_PREVIEW,
                          SCENE_VERIFY_ALL) else SCENE_VERIFY_PREVIEW


def scene_verify_env_explicit() -> bool:
    """Активация: verification выполняется только при ЯВНО заданном env
    (прозрачная политика включения — каждый preview-вызов это платный
    compare-запрос; молчаливых платных вызовов нет). Инъекция verifier
    (тесты/канарейка) активна независимо."""
    return bool(os.getenv("COVER_STYLE_SCENE_VERIFY", "").strip())


_SCENE_VERIFY_TIMEOUT = 60.0
_SCENE_VERIFY_PROMPT = (
    "Compare the two images. Image 1 is the original cover, image 2 is the "
    "styled version. Answer ONLY with compact JSON: {\"scene_preserved\": "
    "true|false, \"people_same\": true|false, \"event_same\": true|false, "
    "\"composition_same\": true|false, \"note\": \"<=120 chars\"}. "
    "scene_preserved=false only if people, pose, event or composition were "
    "replaced, not for style differences.")


def _scene_verify_payload(base_b64: str, styled_b64: str) -> dict:
    return {
        "model": "",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": "data:image/jpeg;base64," + base_b64}},
                {"type": "image_url",
                 "image_url": {"url": "data:image/jpeg;base64," + styled_b64}},
                {"type": "text", "text": _SCENE_VERIFY_PROMPT},
            ],
        }],
        "temperature": 0,
    }


def _data_url_b64(path: str) -> tuple[str | None, str]:
    """(b64, mime) локального файла; None — файл не читается."""
    import base64
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp"}.get(
        os.path.splitext(str(path))[1].lower(), "image/jpeg")
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None, mime
    return base64.b64encode(data).decode("ascii"), mime


async def _default_scene_verifier(base_path: str, styled_path: str
                                  ) -> tuple[str, str]:
    """Один bounded compare-вызов через действующий image-анализ маршрут
    (mca_vision.resolve_route). Любая ошибка → честный ``unknown``.

    P0 (recon D2/D14): ключ берётся ТОЛЬКО общим резолвером
    `mca_vision.api_key_for` (ключ по профилю endpoint'а — основной ключ не
    уходит на чужой endpoint), URL собирается `mca_vision.chat_completions_url`
    (без двойного `/chat/completions`), неподдерживаемый тип API не
    отправляется."""
    try:
        from services import mca_vision
        route = mca_vision.resolve_route()
    except Exception:
        return "unknown", "route_unavailable"
    if not mca_vision.api_type_supported(route):
        return "unknown", "api_type_unsupported"
    key = mca_vision.api_key_for(route)
    if not key:
        return "unknown", "key_missing"
    base_b64, base_mime = _data_url_b64(base_path)
    styled_b64, styled_mime = _data_url_b64(styled_path)
    if not base_b64 or not styled_b64:
        return "unknown", "image_unreadable"
    payload = _scene_verify_payload(base_b64, styled_b64)
    payload["model"] = route.model
    endpoint = mca_vision.chat_completions_url(route.base_url)
    headers = {"Authorization": "Bearer %s" % key}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_SCENE_VERIFY_TIMEOUT) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        text = str(((body.get("choices") or [{}])[0].get("message") or {})
                   .get("content") or "")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return "unknown", "unparsable_answer"
        verdict = json.loads(match.group(0))
    except Exception as exc:            # network/timeout/parse — fail-open
        return "unknown", type(exc).__name__
    preserved = verdict.get("scene_preserved")
    if preserved is True:
        return "pass", ""
    if preserved is False:
        return "replaced", str(verdict.get("note") or "")[:120]
    return "unknown", "missing_verdict"


async def verify_scene_preserved(base_path: str, styled_path: str, *,
                                 verifier=None) -> dict:
    """B04.6: bounded semantic-сравнение Base и styled (люди/поза/событие/
    композиция). Возвращает ``{"scene_preserved": "pass"|"replaced"|"unknown",
    "detail": str}``; verifier — инъекция для тестов. Магические байты —
    НЕ семантика (format_valid отдельно, `_styled_payload_signal`)."""
    if verifier is None:
        verifier = _default_scene_verifier
    try:
        verdict, detail = await verifier(base_path, styled_path)
    except Exception as exc:            # pragma: no cover - защитная ветка
        return {"scene_preserved": "unknown", "detail": type(exc).__name__}
    verdict = str(verdict or "unknown")
    if verdict not in ("pass", "replaced", "unknown"):
        verdict = "unknown"
    return {"scene_preserved": verdict, "detail": str(detail or "")[:120]}


def scene_verification_due(mode: str, *, verifier=None) -> bool:
    """Прозрачная политика: verification запускается на preview-прогонах
    (mode=preview) либо на всех прогонах при ``all``; требует ЯВНОГО env
    `COVER_STYLE_SCENE_VERIFY` (платный compare-вызов — сознательное
    включение). Инъекция verifier (тесты/канарейка) снимает требование env,
    но НЕ политику режима: прод без ``all`` сравнение не запускает."""
    policy = scene_verify_mode()
    if policy == SCENE_VERIFY_OFF:
        return False
    if policy == SCENE_VERIFY_ALL:
        return True
    if str(mode) != MODE_PREVIEW:
        return False
    return scene_verify_env_explicit() or verifier is not None


# ── B04.5: идемпотентная замена изображения существующего выпуска ───────────

TELEGRAM_REPLACE_ENABLED_ENV = "COVER_STYLE_TELEGRAM_REPLACE_ENABLED"
DELIVERY_NOT_ATTEMPTED = "not_attempted_policy_off"
DELIVERY_REPLACED = "replaced"
DELIVERY_UNSUPPORTED = "rich_message_edit_unsupported"
DELIVERY_NO_REFERENCE = "publication_reference_missing"


def telegram_replace_enabled() -> bool:
    """B04.5 политика замены изображения опубликованного выпуска (env
    `COVER_STYLE_TELEGRAM_REPLACE_ENABLED`, default OFF). OFF — честный
    статус доставки (артефакт восстановлен, Telegram НЕ дёргается), без
    тихого «recovered как доставленный». Решение зафиксировано явно."""
    raw = os.getenv(TELEGRAM_REPLACE_ENABLED_ENV, "").strip().lower()
    return raw in ("1", "true", "yes", "on")


async def lookup_published_message_id(db, run_id: str | None,
                                      chat_id: int | None) -> int | None:
    """message_id опубликованного саммари run'а из durable-события
    `SUMMARY_RUN_DONE` (usage_json.message_id, §109). None — ссылки нет
    (честная причина замены, не слепой edit)."""
    if db is None or not str(run_id or "").strip():
        return None
    rid = str(run_id).strip()
    queries = (
        ("SELECT usage_json FROM mca_events WHERE event_name = ? "
         "AND pipeline_run_id = ? ORDER BY id DESC LIMIT 1",
         ("SUMMARY_RUN_DONE", rid)),
        ("SELECT usage_json FROM mca_events WHERE event_name = ? "
         "AND chat_id = ? ORDER BY id DESC LIMIT 1",
         ("SUMMARY_RUN_DONE", chat_id)),
    )
    for sql, args in queries:
        try:
            cursor = await db.db.execute(sql, args)
            row = await cursor.fetchone()
        except Exception:
            continue
        if row is None:
            continue
        try:
            usage = json.loads(dict(row).get("usage_json") or "{}")
        except (ValueError, TypeError):
            continue
        message_id = (usage or {}).get("message_id")
        try:
            return int(message_id) if message_id is not None else None
        except (TypeError, ValueError):
            continue
    return None


async def replace_published_cover_image(bot, *, chat_id: int,
                                        message_id: int, styled_path: str
                                        ) -> tuple[bool, str]:
    """Идемпотентная замена изображения СУЩЕСТВУЮЩЕГО выпуска (B04.5):
    `editMessageMedia` с новым InputMediaPhoto; caption/article/номер не
    затрагиваются (меняется только media). Telegram Bot API (aiogram 3.29)
    editRichMessage НЕ предоставляет — rich-публикация отвечает 400; исход
    классифицируется честно (``rich_message_edit_unsupported``), дубликат
    публикации НЕ создаётся. Возвращает ``(delivered, delivery_status)``."""
    if bot is None:
        return False, DELIVERY_NO_REFERENCE
    try:
        with open(styled_path, "rb") as handle:
            data = handle.read()
    except OSError:
        return False, DELIVERY_NO_REFERENCE
    if not data:
        return False, DELIVERY_NO_REFERENCE
    from aiogram.types import BufferedInputFile, InputMediaPhoto
    media = InputMediaPhoto(
        media=BufferedInputFile(data, filename="summary_cover_styled.jpg"))
    try:
        await bot.edit_message_media(chat_id=chat_id, message_id=message_id,
                                     media=media)
        return True, DELIVERY_REPLACED
    except Exception as exc:
        name = type(exc).__name__
        text = str(exc).lower()
        if "telegram" in name.lower() or "bad request" in text or \
                "can't be edited" in text or "no media" in text:
            return False, DELIVERY_UNSUPPORTED
        return False, DELIVERY_UNSUPPORTED


def _story_identity_text(story_scene: str, brief) -> str:
    """STORY_IDENTITY-текст (ASAP 8 F3 §5.2): сцена base cover + компактный
    контекст финального Summary (CoverBrief). Whitespace-нормализация —
    детерминированный floor-containment для fail-soft (§5.4) и манифеста.

    B04 v6.3: в EDIT-маршруте полный текст БОЛЬШЕ не является обязательным
    ядром (источник сцены — Base bitmap); helper остаётся для манифеста
    (компоненты STORY_SCENE/SUMMARY_CONTEXT durable Base-run) и диагностики."""
    scene = " ".join(str(story_scene or "").split())
    brief_text = " ".join(str(brief.render() if brief is not None
                              else "").split())
    return " ".join(p for p in (scene, brief_text) if p)


def style_publish_skip_reason(compiled, *, story_text: str = "") -> str | None:
    """B04 v6.3 (замена ASAP 8 F3 §5.4 для EDIT-маршрута): детерминированный
    preflight-сигнал из результата компиляции (НЕ LLM-суждение).

    ``prompt_limit_exceeded`` — нормализованный EDIT-payload не влезает в
    resolved limit минус headroom: платный вызов НЕ делается, публикуется
    Base (честная причина).

    ``story_identity_dropped`` больше НЕ триггерится компиляцией: в
    image-to-image сюжет гарантирован передаваемой Base bitmap, повторный
    перенос story_scene/summary в текст — сам дефект B04. Semantic-
    сохранность результата проверяет bounded image-comparison
    (``verify_scene_preserved``, preview/canary — B04.6), а не текстовый
    floor. ``None`` — payload прошёл preflight."""
    if getattr(compiled, "exceeded", False):
        return STYLE_PUBLISH_SKIP_OVERFLOW
    return None


def _prompt_breakdown(compiled) -> dict:
    """§9 (T-4849): Style/Context/Refs/System из component-lens компилятора.

    ASAP 8 F3: System включает новый P0-компонент CONTENT_PRESERVATION."""
    lens = dict(getattr(compiled, "components", {}) or {})
    style = int(lens.get("style_instruction", 0)) \
        + int(lens.get("base_style_prompt", 0))
    return {
        "style_chars": style,
        "context_chars": int(lens.get("cover_brief", 0)),
        "refs_chars": int(lens.get("references", 0)),
        "system_chars": int(lens.get("runtime_invariants", 0))
        + int(lens.get("content_preservation", 0)),
    }


# ── heartbeat (§46) ─────────────────────────────────────────────────────────

def heartbeat_interval() -> float:
    try:
        value = float(getattr(settings, "COVER_STYLE_HEARTBEAT_SECONDS", 30.0))
    except (TypeError, ValueError):
        value = 30.0
    return max(5.0, min(value, 120.0))


async def _run_with_heartbeat(factory, *, interval: float, event: str,
                              run_id: str | None, job_id: str | None,
                              model: str, provider: str,
                              on_beat=None) -> None:
    """Дождаться корутины, логируя heartbeat раз в `interval` (§46, без спама).

    C03A: `on_beat` — асинхронный колбэк живости владельца durable-джобы
    (`task_jobs.heartbeat_at`): без него `recover_stale`/watchdog видят
    только mca_events и реапают живую долгую style-стадию."""
    task = asyncio.ensure_future(factory())
    started = time.monotonic()
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if task in done:
                return task.result()
            if on_beat is not None:
                try:
                    await on_beat()
                except Exception:      # pragma: no cover - fail-open
                    pass
            emit_cover_event(
                event, outcome="pending_external", run_id=run_id,
                job_id=job_id, model=model, provider=provider,
                duration_ms=int((time.monotonic() - started) * 1000),
                status=event.replace("COVER_", "").lower())
    except asyncio.CancelledError:
        task.cancel()
        raise


def _asset_id_of(path: str | None) -> str | None:
    """Content-addressed `asset_id` изображения (§30): sha256 → `cas_<hex[:32]>`.

    Не пишет файл/PG (bounded, §2.1 — cover-байты транзиентны): даёт стабильный
    идентификатор для provenance `base_asset_id`/`final_asset_id`.
    """
    if not path:
        return None
    try:
        from services.cover_style_assets import asset_id_for
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return asset_id_for(digest.hexdigest())
    except OSError:
        return None


def _write_temp_image(content: bytes) -> str | None:
    try:
        fd, path = tempfile.mkstemp(prefix="covstyle_", suffix=".jpg")
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        return path
    except Exception:
        logger.warning("[cover_style_jobs] temp write failed — fail-open")
        return None


def _styled_payload_signal(content: bytes) -> tuple[bool, str]:
    """C03A (кейс 5): детерминированная проверка результата edit.

    (True, "")            — магические байты валидного изображения;
    (False, semantic_preservation_failed) — декодируемый текст вместо
                            изображения: модель подменила edit сцены
                            текстовым ответом, сюжет сохранён быть не может;
    (False, invalid_image_payload) — бинарный мусор/битая кодировка.
    R17: контент не логируется, только классификация."""
    data = bytes(content or b"")
    head = data[:16]
    if head.startswith(b"\xff\xd8") or head.startswith(b"\x89PNG\r\n\x1a\n"):
        return True, ""
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True, ""
    probe = data[:2048]
    try:
        text = probe.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return False, REASON_INVALID_PAYLOAD
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
    if probe and printable / len(text) >= 0.9:
        return False, REASON_SEMANTIC_LOST
    return False, REASON_INVALID_PAYLOAD


def _resolve_api_key() -> str:
    try:
        from services import hot_config as hot
        value = hot.get(KEY_STYLE_API_KEY, getattr(
            settings, "IMAGE_STYLE_API_KEY", ""))
    except Exception:
        value = getattr(settings, "IMAGE_STYLE_API_KEY", "")
    return str(value or "")


manifest_public = cpa.manifest_public  # ASAP 5 (D7): fail-closed view (admin-only)


async def load_run_cover_prompts(db, run_id: str | None) -> dict:
    """ASAP 7 F8 (§2.5): production-читатель exact-промптов run'а.

    Возвращает ``{"base": manifest|None, "style": manifest|None,
    "cover_prompts_status": {"base": <code>, "style": <code>}}`` —
    Base-манифест (``load_base_cover_manifest``, task_jobs kind=cover_base)
    и Style-манифест production Style-Edit (state.prompt_manifest durable
    cover-джобы, поиск по ``coalesce_key='cover_style:<run_id>'`` — тот же
    путь, что `_cover_job_fallback`). ТОЛЬКО чтение durable-артефактов;
    поведение записи не меняется.

    ASAP 8 F4 (§4.2): ``cover_prompts_status`` — явная причина отсутствия
    манифеста (C6, §28.8 — блок не прячется молча):
      ``ok``                  — манифест найден;
      ``base_manifest_missing`` — modern-run без Base-манифеста;
      ``style_job_not_linked``  — Base есть, Style-джобы для run нет;
      ``style_job_failed``      — Style-джоба есть, манифеста в state нет;
      ``legacy_run``            — нет ни Base-манифеста, ни Style-джобы
                                  (прогон до эпохи манифестов или run
                                  отсутствует — по этим артефактам
                                  неразличимо, честный общий код).

    R17: полные тексты отдаются только global-admin вызывающему
    (``web/api/analytics.py``, ``?include_prompt=true``); generic-логи и
    ответы без include_prompt этот хелпер не касается. Fail-open: нет
    БД/run_id — None-поля без status-кодов (нечего определять),
    исключений не бросает."""
    if db is None or not str(run_id or "").strip():
        return {"base": None, "style": None}
    rid = str(run_id).strip()
    try:
        base = await load_base_cover_manifest(db, rid)
    except Exception:
        logger.warning("[cover_style_jobs] base manifest read failed",
                       exc_info=True)
        base = None
    style = None
    style_job_linked = False
    try:
        cursor = await db.db.execute(
            "SELECT payload FROM task_jobs WHERE coalesce_key = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            ("cover_style:%s" % rid,))
        row = await cursor.fetchone()
        if row is not None:
            style_job_linked = True
            raw = dict(row).get("payload")
            payload = {}
            try:
                payload = json.loads(raw) if raw else {}
            except (ValueError, TypeError):
                payload = {}
            cursor_token = (payload.get("cursor")
                            if isinstance(payload, dict) else None)
            state = CoverJobState.from_json(
                cursor_token if isinstance(cursor_token, str) else None)
            if state is not None:
                style = state.prompt_manifest
    except Exception:
        logger.warning("[cover_style_jobs] style manifest read failed",
                       exc_info=True)
        style = None
    # ASAP 8 F4 (§4.2): reason-модель отсутствия манифестов (C6).
    if base is None and style is None and not style_job_linked:
        status = {"base": "legacy_run", "style": "legacy_run"}
    else:
        status = {
            "base": "ok" if base is not None else "base_manifest_missing",
            "style": ("ok" if style is not None
                      else ("style_job_failed" if style_job_linked
                            else "style_job_not_linked")),
        }
    return {"base": base, "style": style, "cover_prompts_status": status}


# ── Style stage (§3.2/§23/§38/§49) ──────────────────────────────────────────

def _manifest_mark_outcome(manifest: dict | None, *, applied: bool,
                           reason: str = "") -> None:
    """Финализировать исход ПОСЛЕДНЕЙ attempt (после результата provider'а).

    Манифест строится сразу после retry-блока (персист-точки state ниже),
    исход дописывается в тот же dict — durable-персист забирает финал."""
    if not isinstance(manifest, dict) or not manifest.get("attempts"):
        return
    last = max(int(a.get("attempt") or 0) for a in manifest["attempts"])
    for att in manifest["attempts"]:
        if int(att.get("attempt") or 0) == last:
            att["outcome"] = "ok" if applied else "failed"
            if not applied and reason:
                att["reason"] = str(reason)


def _build_style_manifest(*, profile: dict, issue_display: str,
                          base_style_prompt: str, brief_text: str,
                          scene_text: str, sent_prompts: list,
                          meta: dict, caps) -> dict | None:
    """D7/T-5249: CoverPromptManifest Style Edit по факту отправки.

    ``sent_prompts`` — фактически отправленные строки (attempt 1 + retry);
    полный prompt живёт только в манифесте (durable job evidence), в
    generic log/events не попадает. R17: тексты компонентов — chat data,
    наружу только через cpa.manifest_public (fail-closed, admin-only)."""
    if not sent_prompts:
        return None
    applied = bool(meta.get("applied"))
    fail_reason = str(meta.get("fail_reason") or "")
    limit_known = None
    limit_source = "unknown"
    limit_unit_raw = "unknown"
    resolved_limit = None
    if caps is not None:
        pl = getattr(caps, "prompt_limit", None)
        limit_known = bool(getattr(pl, "known", False))
        limit_source = str(getattr(pl, "source", "") or "unknown")
        limit_unit_raw = str(getattr(pl, "unit", "") or "unknown")
        if limit_known:
            resolved_limit = getattr(pl, "value", None)
    attempts = []
    last = sent_prompts[-1][0]
    retry_reason = ""
    if len(sent_prompts) > 1:
        retry_reason = ("prompt_limit_unknown"
                        if meta.get("prompt_limit_unknown_retry")
                        else "prompt_limit")
    for num, text in sent_prompts:
        if num == last:
            outcome = "ok" if applied else "failed"
            reason = "" if applied else fail_reason
        else:
            outcome = "retry_superseded"
            reason = retry_reason
        attempts.append({"attempt": int(num), "prompt": str(text or ""),
                         "outcome": outcome, "reason": reason})
    final_prompt = str(sent_prompts[-1][1] or "")
    limit_unit = (str(resolved_limit) if resolved_limit is not None
                  else "unknown") + ":" + limit_unit_raw
    # B04 v6.3: P0-тексты фактически на языке контента EDIT-сборки —
    # манифест описывает отправленное, а не канон-EN (см. cpa docstring).
    lang = edit_content_language(str(profile.get("instruction") or ""))
    return cpa.build_style_manifest(
        issue_display=issue_display,
        instruction=str(profile.get("instruction") or ""),
        base_style_prompt=base_style_prompt,
        refs_text=style_reference_text(profile),
        ref_roles_text=cpa.reference_roles_text(
            profile.get("references") or []),
        story_scene=scene_text,
        context_text=brief_text,
        final_prompt=final_prompt,
        provider=str(meta.get("provider") or ""),
        model=str(meta.get("model") or ""),
        route=str(meta.get("edit_route") or ""),
        operation=("preview" if meta.get("mode") == MODE_PREVIEW else "edit"),
        resolved_limit=resolved_limit,
        limit_unit=limit_unit,
        limit_source=limit_source,
        attempts=attempts,
        preservation_sent=edit_preservation_text(lang),
        runtime_sent=edit_runtime_invariants_text(issue_display, lang))


async def run_style_job(*, chat_id: int, base_image_path: str | None,
                        profile: dict | None, summary_run_id: str | None,
                        correlation_id: str | None = None,
                        job_id: str | None = None, pg=None, db=None,
                        capabilities=None, discovery: dict | None = None,
                        endpoints: dict | None = None,
                        reference_paths: list | None = None,
                        edit_call=None, mode: str = MODE_PRODUCTION,
                        state: CoverJobState | None = None,
                        summary_text: str | None = None,
                        base_style_prompt: str | None = None,
                        story_scene: str | None = None,
                        manifest_out: dict | None = None,
                        heartbeat=None, scene_verifier=None) -> dict:
    """Выполнить Style Edit поверх готовой base cover (нормализатор, §23).

    Возвращает meta-словарь. При любом сбое `applied=False`,
    `reason="style_failed"` — вызывающий публикует **сохранённую base cover**
    (base НЕ перегенерируется, §49).

    §19/§21: prompt собирается из base style prompt + dynamic cover brief
    (компактный сюжет), инструкции профиля, runtime-номера выпуска и
    описаний референсов — `compile_style_prompt`.

    ASAP 5 (D8/T-5251): `summary_text` — ФИНАЛЬНЫЙ approved Summary
    (SUMMARY_CONTEXT: title + главные события; больше не 300-char seed),
    `story_scene` — сцена base cover (STORY_SCENE). `manifest_out` —
    опциональный dict вызывающего, куда кладётся фактический
    CoverPromptManifest (T-5249); durable-персист — в `state`.

    ASAP-4 волна B (spec §2 B.4/B.5, T-4418/T-4419; `snapshot_enabled()`):
    ON — pre-execution конфигурационные фейлы (`connection_missing`/
    `edit_unsupported`/`not_configured`/`reference_missing`) выходят РАНЬШЕ
    assignment'а номера выпуска (counter не расходуется на не-submission),
    reference integrity §45 + метрики, prompt diagnostics §46; mca_events
    `reason_code` не схлопывается в generic `style_failed`. OFF — прежний
    порядок и прежние события бит-в-бит (parity-тест).

    ASAP 8 v6 C03A: `heartbeat` — async-колбэк живости durable-джобы
    (`task_jobs.heartbeat_at`, recover_stale не реапает живую стадию);
    результат провайдера проходит детерминированную payload-валидацию
    (не-изображение → `semantic_preservation_failed`/`invalid_image_payload`,
    fail-soft Base вместо публикации сломанной обложки).

    ASAP 8 v6.3 B04: компактный EDIT-контракт (story/summary в текст не
    переносятся — источник сцены Base bitmap; semantic dedupe; preflight
    headroom). `scene_verifier` — инъекция bounded image-comparison
    (B04.6); формат (`format_valid`) и семантика (`scene_preserved`) —
    разные сигнала Inspector'а; подмена сюжета на preview/canary — НЕ
    успешный styled (fail-soft Base)."""
    started = time.monotonic()
    _wb = snapshot_enabled()
    # §43 restart-resume: восстановить state из durable `task_jobs`, если он не
    # передан вызывающим (process-local состояние сброшено рестартом).
    if state is None and db is not None and job_id:
        state = await load_cover_state(db, job_id)
    if state is not None and state.state == STATE_DONE:
        # Полностью завершённая (опубликованная) джоба — новый заход, не resume.
        state = CoverJobState(style_id=state.style_id)
    meta = {
        "applied": False, "styled_path": None, "outcome": RESULT_BASE,
        "reason": "", "fail_reason": "", "message": "",
        "style_id": (profile or {}).get("profile_id"),
        "style_revision": (profile or {}).get("revision"),
        "issue_number": None, "provider": "", "model": "",
        "duration_ms": 0, "cost_usd": None, "provider_task_id": None,
        "async_used": False, "mode": mode,
        "base_asset_id": None, "final_asset_id": None,
        # Wave B (аддитивные диагностические ключи; None/OFF — не заполнено).
        "capability_state": None, "reference_bytes_total": 0,
        "reference_details": None, "prompt_diagnostics": None,
    }
    if not cover_styles_enabled():
        meta["reason"] = "cover_styles_disabled"
        meta["outcome"] = RESULT_BASE
        return meta
    if not profile:
        meta["reason"] = "no_style"
        meta["outcome"] = RESULT_BASE
        return meta
    if not base_image_path:
        meta["reason"] = REASON_BASE_FAILED
        meta["outcome"] = RESULT_NONE
        return meta

    # ── ASAP-3.2 (§103–§105, D14): connection_id — настоящий FK; запись
    # подключения (base_url/api_key) резолвится из реестра Connections.
    _connection = None
    obj0 = pg if pg is not None else _pg()
    if profile and profile.get("model_mode") == MODEL_MODE_CUSTOM \
            and str(profile.get("connection_id") or "").strip() \
            and obj0 is not None:
        try:
            _connection = await registry.get_connection(
                obj0, str(profile.get("connection_id")).strip())
        except Exception:
            _connection = None
    # T-4619 (spec §6 F.2; ADR-1028-8 D7.2): лестница наследования §35.
    # Явно настроенный слот/подключение — байт-в-бит (регресс); пустой
    # глобальный слот при «По умолчанию (глобальная настройка)» →
    # Connections default → global default image provider+model.
    # Kill-switch OFF → resolve_style_slot (байт-в-бит 2.58.46).
    slot = await resolve_style_slot_inherited(
        profile=profile, connection=_connection, pg=obj0)
    _inherit_conn = slot.pop("_connection", None)
    if _inherit_conn is not None:
        _connection = _inherit_conn
    _resolve_source = str(slot.get("resolve_source")
                          or SLOT_SOURCE_GLOBAL_STYLE)
    slot.pop("resolve_source", None)
    if _wb and slot.get("custom_unresolved"):
        # §40/B.4: профиль указывает на подключение, записи которого нет
        # (удалено/PG недоступен) — ранний выход с честной причиной;
        # default-слот молча не подставляется (edit уходит не на ту точку).
        return await _style_failed(
            meta, state, reason=REASON_CONNECTION_MISSING,
            message=("Подключение модели не найдено. Проверьте «Настроить "
                     "подключения →» в профиле стиля."),
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            started=started, db=db)
    # §104: пер-подключение api_key (профиль секретов не хранит);
    # default-слот → прежний ключ `keys.image_style_api_key`; наследованный
    # global-image слот (T-4619 leg 3c) → ключ глобального image-провайдера
    # `keys.image_api_key` (тот же провайдер, что сгенерировал base cover).
    def _resolve_api_key() -> str:
        if _connection is not None:
            return str(_connection.get("api_key") or "")
        if _resolve_source == SLOT_SOURCE_GLOBAL_IMAGE:
            try:
                from services import hot_config as hot
                value = hot.get(KEY_IMAGE_API_KEY, getattr(
                    settings, "IMAGE_API_KEY", ""))
            except Exception:
                value = getattr(settings, "IMAGE_API_KEY", "")
            return str(value or "")
        try:
            from services import hot_config as hot
            value = hot.get(KEY_STYLE_API_KEY, getattr(
                settings, "IMAGE_STYLE_API_KEY", ""))
        except Exception:
            value = getattr(settings, "IMAGE_STYLE_API_KEY", "")
        return str(value or "")
    meta["provider"] = slot.get("provider") or ""
    meta["model"] = slot.get("model") or ""
    meta["resolve_source"] = _resolve_source
    # ASAP 4.4 (§2/T-4873): route — тем же резолвером, что UI meta/budget
    # (единый provider+base_url+model+route+operation); fail-open → "".
    edit_route = ""
    if slot.get("configured"):
        try:
            from services import cover_style_edit as _edit_mod
            edit_route = str(await _edit_mod.resolve_edit_route(
                slot.get("base_url") or "", slot.get("model") or "") or "")
        except Exception:
            edit_route = ""
    meta["edit_route"] = edit_route
    # T-4619/T-4620: `COVER_STYLE_RESOLVE` — источник резолва слота
    # (лестница §35: profile_connection/connections_default/global_image/
    # global_style_slot); R17-safe (id/enum/bool).
    emit_cover_event(
        COVER_STYLE_RESOLVE, outcome="start", run_id=correlation_id,
        job_id=job_id, chat_id=chat_id, model=meta["model"],
        provider=meta["provider"], style_id=meta["style_id"],
        connection_id=slot.get("connection_id"),
        resolve_source=_resolve_source,
        configured=bool(slot.get("configured")))
    emit_cover_event(COVER_STYLE_START, outcome="start", run_id=correlation_id,
                     job_id=job_id, chat_id=chat_id, model=meta["model"],
                     provider=meta["provider"], style_id=meta["style_id"],
                     style_revision=meta["style_revision"])
    if state is not None:
        # ASAP 4.3 (§2.2): безопасные provider/model для status-endpoint
        # preview-джобы (persist вместе со stage-переходом).
        state.provider = meta["provider"] or None
        state.model = meta["model"] or None
        state.mode = mode
        state.mark(STATE_STYLE_SUBMITTED)
        await _persist_state(db, job_id, state)

    caps = capabilities
    if caps is None:
        # T-4619: capabilities резолвятся по ФИНАЛЬНОМУ (унаследованному)
        # слоту, а не по базовому глобальному (registry §36 — единый
        # резолвер; для базового слота результат идентичен прежнему).
        # ASAP 4.4 (§2/T-4873): route входит в capability key — тот же, что
        # в UI (один источник истины).
        caps = cap.resolve_capabilities(
            slot.get("provider") or "", slot.get("base_url") or "",
            slot.get("model") or "", discovery=discovery, endpoints=endpoints,
            route=edit_route or None,
            # ASAP 4.3 (§7, T-4847): capability per operation (style stage —
            # image_edit), manual override — высший приоритет.
            operation=cap.OPERATION_EDIT)
    meta["capability_state"] = getattr(caps, "image_edit", None)
    allowed, message = check_edit_allowed(profile=profile, capabilities=caps)
    if not allowed:
        # §38: модель без image_edit — API не вызывается, base публикуется.
        return await _style_failed(
            meta, state, reason="edit_unsupported", message=message,
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            started=started, db=db)

    obj = pg if pg is not None else _pg()
    ref_details = None
    reference_bytes_total = 0
    if _wb:
        # §B.5 (T-4419): pre-execution конфигурационные проверки — ДО
        # assignment'а выпуска (counter расходуется только на submission).
        if not slot.get("configured"):
            # Прод-факт Q14: `not_configured` за 72 мс — без edit API;
            # честный reason без расхода нумерации (§45 owner'а).
            return await _style_failed(
                meta, state, reason=REASON_NOT_CONFIGURED,
                message=("Модель обработки не настроена. Откройте «Настроить "
                         "подключения →» и выберите модель с поддержкой "
                         "edit."),
                run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                started=started, db=db)
        if reference_paths is None:
            # §45 (T-4418): DB-row/file/MIME/readable до edit; метрики
            # `reference_count`/`reference_bytes_total` — без контента.
            ref_details = await _resolve_reference_details(obj, profile)
            reference_paths = [d["path"] for d in ref_details
                               if d.get("path") and d.get("readable")]
            reference_bytes_total = sum(d.get("bytes") or 0
                                        for d in ref_details)
            if (profile.get("references") or []) and not reference_paths:
                return await _style_failed(
                    meta, state, reason=REASON_REFERENCE_MISSING,
                    message=("Референсы стиля недоступны. Загрузите референс "
                             "заново."),
                    run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                    started=started, db=db)
    meta["reference_bytes_total"] = reference_bytes_total
    meta["reference_details"] = ref_details
    ref_paths = reference_paths

    # §27/§28: pin номера выпуска к Summary run (production).
    issue_no = None
    if mode == MODE_PRODUCTION and profile.get("counter_enabled") \
            and summary_run_id and obj is not None:
        try:
            issue_no = await registry.resolve_issue_number(
                obj, profile["profile_id"], summary_run_id)
        except Exception:
            issue_no = None
    meta["issue_number"] = issue_no
    counter_format = profile.get("counter_format") or registry.SEEDED_COUNTER_FORMAT
    # §RC-C/T-4869: preview (и production без назначенного номера) показывают
    # текущий next_issue_number; counter при этом не расходуется.
    issue_display = (registry.format_issue(counter_format, issue_no)
                     if issue_no is not None
                     else registry.preview_issue_display(
                         counter_format, registry.next_issue_number(profile)))
    if not _wb:
        # OFF (legacy): прежний порядок — refs резолвятся после issue.
        ref_paths = reference_paths
        if ref_paths is None:
            ref_paths = await _resolve_reference_paths(obj, profile)
    snapshot = registry.build_revision_snapshot(
        profile, issue_number=issue_no, capabilities=caps.as_dict(),
        slot=slot)
    # §21 + ASAP 5 (D8/T-5251): сюжетная часть = STORY_SCENE (сцена base
    # cover) + SUMMARY_CONTEXT (CoverBrief от ФИНАЛЬНОГО approved Summary —
    # больше не 300-char seed; 0 LLM).
    # B04 v6.3: в EDIT-маршруте scene/summary в текст НЕ переносятся —
    # источник сцены Base bitmap; тексты остаются durable-входами манифеста
    # и диагностикой (scene_anchor решает, нужен ли короткий якорь).
    brief = compiler.brief_from_text(summary_text)
    scene_text = str(story_scene or "").strip()
    brief_text = brief.render() if brief is not None else ""
    budget_text = " ".join(p for p in (scene_text, brief_text) if p)
    story_text = _story_identity_text(scene_text, brief)
    meta["base_asset_id"] = _asset_id_of(base_image_path)
    compiled = compile_style_prompt(
        profile, issue_display=issue_display, capabilities=caps,
        base_style_prompt=base_style_prompt or "", brief=brief,
        story_scene=scene_text)
    edit_report = dict(getattr(compiled, "edit_report", {}) or {})
    # D7 attempts[]: фактически отправленные строки (attempt 1 + retry).
    sent_prompts: list = [(1, compiled.prompt)]
    if _wb:
        # §46 (T-4418): prompt compilation diagnostics (safe-числа/флаги).
        meta["prompt_diagnostics"] = {
            "instruction_chars": len(str(profile.get("instruction") or "")),
            "brief_chars": len(budget_text),
            "story_chars": len(scene_text),
            "issue_present": bool(issue_display in compiled.prompt),
            "references_count": len(ref_paths),
            "compiled_chars": len(compiled.prompt),
            # T-4816: Inspector `Original N / Resolved limit M / Compiled K`.
            "original_chars": int(compiled.original_len or 0),
            "resolved_limit": compiled.resolved_limit,
            "original_style_prompt_chars": len(str(
                base_style_prompt or "")),
            "exceeded": bool(compiled.exceeded),
            "overflow_reason": compiled.reason or "",
            "limit_unit": (str(compiled.limit) if compiled.limit is not None
                           else "unknown") + ":" + str(compiled.unit),
            "dropped_sections": list(compiled.dropped),
            # B04 v6.3: компактный EDIT-отчёт (Inspector B04.3/B04.4).
            "content_language": edit_report.get("language") or "",
            "image_input_used": {
                "base": bool(base_image_path),
                "references": len(ref_paths),
            },
            "edit_original_chars": edit_report.get("original_chars") or 0,
            "edit_deduped_chars": edit_report.get("deduped_chars") or 0,
            "edit_headroom_chars": edit_report.get("headroom_chars") or 0,
            "edit_scene_anchor": dict(edit_report.get("scene_anchor") or {}),
            "edit_dropped_detail": list(
                edit_report.get("dedupe_dropped") or []),
            "summary_retransferred": bool(
                edit_report.get("summary_retransferred")),
            # ASAP 4.3 (§9, T-4849): breakdown Style/Context/Refs/System из
            # фактически собранных компонент (units compiled prompt).
            **_prompt_breakdown(compiled),
            # ASAP 4.4 (§2, T-4873/T-4874): effective route + источник
            # capability/лимита для Inspector (R17-safe: enum/число).
            "edit_route": edit_route,
            "capability_source": caps.source,
            "limit_source": caps.prompt_limit.source,
            "limit_source_taxonomy": cap.prompt_limit_source_taxonomy(
                caps.prompt_limit.source),
            "limit_value": (caps.prompt_limit.value
                            if caps.prompt_limit.known else None),
        }
        if state is not None:
            # F-N3: durable prompt-факты для Inspector (числа/enum; события
            # могут быть прунированы) — сохраняются вместе со stage-переходом.
            state.prompt_diagnostics = dict(meta["prompt_diagnostics"])
    if _wb:
        # §46: безопасные diagnostics в событии (числа/флаги, R17-safe).
        diag = meta.get("prompt_diagnostics") or {}
        emit_cover_event(
            COVER_STYLE_SUBMITTED, outcome="start", run_id=correlation_id,
            job_id=job_id, chat_id=chat_id, model=meta["model"],
            provider=meta["provider"], prompt_len=len(compiled.prompt),
            prompt_hash=prompt_hash(compiled.prompt),
            reference_count=len(ref_paths), issue_number=issue_no,
            reference_bytes_total=reference_bytes_total,
            capability_state=meta.get("capability_state"),
            instruction_chars=diag.get("instruction_chars"),
            brief_chars=diag.get("brief_chars"),
            compiled_chars=diag.get("compiled_chars"),
            limit_unit=diag.get("limit_unit"),
            issue_present=diag.get("issue_present"),
            edit_route=diag.get("edit_route"),
            limit_source=diag.get("limit_source"),
            limit_source_taxonomy=diag.get("limit_source_taxonomy"),
            capability_source=diag.get("capability_source"),
            fallback=(",".join(compiled.dropped)
                      if compiled.dropped else None))
    else:
        emit_cover_event(
            COVER_STYLE_SUBMITTED, outcome="start", run_id=correlation_id,
            job_id=job_id, chat_id=chat_id, model=meta["model"],
            provider=meta["provider"], prompt_len=len(compiled.prompt),
            prompt_hash=prompt_hash(compiled.prompt),
            reference_count=len(ref_paths), issue_number=issue_no,
            fallback=(",".join(compiled.dropped)
                      if compiled.dropped else None))

    # ── T-4815 + B04 v6.3 (§5.4-замена): fail-soft публикации styled cover.
    # Детерминированный preflight из результата компиляции: нормализованный
    # EDIT-payload не влезает в resolved limit минус headroom
    # (prompt_limit_exceeded) — styled НЕ публикуется и платный edit-call
    # НЕ вызывается, публикуется сохранённая Base; манифест помечает
    # style_publish_skipped{reason}. Textual story-floor-отказ изъят
    # (B04.1: сюжет в Base bitmap); semantic-сохранность результата —
    # bounded image-comparison (B04.6). ────────────────────────────────
    skip_reason = style_publish_skip_reason(compiled, story_text=story_text)
    if skip_reason:
        meta["prompt_diagnostics"] = {
            **(meta.get("prompt_diagnostics") or {}),
            "overflow_reason": skip_reason,
            "preflight": "normalized_edit_payload_over_limit",
        }
        # F3: dropped[] меняет исход публикации — манифест строится и для
        # skip-исхода (durable evidence для Inspector; прежде overflow
        # возвращался вовсе без манифеста).
        meta["fail_reason"] = skip_reason
        manifest = _build_style_manifest(
            profile=profile, issue_display=issue_display,
            base_style_prompt=base_style_prompt or "", brief_text=brief_text,
            scene_text=scene_text, sent_prompts=sent_prompts,
            meta=meta, caps=caps)
        if manifest is not None:
            manifest["style_publish_skipped"] = {"reason": skip_reason}
            _manifest_mark_outcome(manifest, applied=False,
                                   reason=skip_reason)
            if state is not None:
                state.prompt_manifest = manifest
            if manifest_out is not None:
                manifest_out["prompt_manifest"] = manifest
            meta["prompt_manifest_hash"] = manifest.get("prompt_hash") or ""
            meta["prompt_manifest_chars"] = manifest.get("final_chars") or 0
        meta["style_publish_skipped"] = {"reason": skip_reason}
        emit_cover_event(
            COVER_STYLE_FAILED, outcome="failed", level=logging.WARNING,
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            model=meta["model"], provider=meta["provider"],
            reason="prompt_limit_exceeded", reason_code="prompt_limit_exceeded",
            style_id=meta["style_id"], issue_number=issue_no)
        return await _style_failed(
            meta, state, reason="prompt_limit_exceeded",
            message="Стиль не применён: инструкция превышает лимит модели.",
            run_id=correlation_id, job_id=job_id, chat_id=chat_id,
            started=started, db=db)

    caller = edit_call
    if caller is None:
        caller = edit_image
    # §23 (T-4199): stage-aware key политики — preview и edit имеют разные
    # latency-распределения. Тестовые double `edit_call` могут не принимать
    # kwargs `operation`/`route` → совместимость через inspect (аддитивно).
    edit_operation = ("preview" if mode == MODE_PREVIEW else "edit")
    try:
        import inspect as _inspect
        _params = _inspect.signature(caller).parameters
        accepts_operation = "operation" in _params
        accepts_route = "route" in _params
    except (TypeError, ValueError):
        accepts_operation = False
        accepts_route = False

    def _call(prompt_text=None):
        use_prompt = compiled.prompt if prompt_text is None else prompt_text
        extra: dict = {}
        if accepts_operation:
            extra["operation"] = edit_operation
        if accepts_route:
            # ASAP 4.4 (§2/T-4873): тот же resolved route, что показывает UI.
            extra["route"] = edit_route or None
        return caller(use_prompt,
                      base_image_path=base_image_path,
                      reference_paths=ref_paths,
                      base_url=slot.get("base_url"),
                      model=slot.get("model"), api_key=_resolve_api_key(),
                      capabilities=caps, chat_id=chat_id,
                      correlation_id=correlation_id,
                      existing_task_id=(state.provider_task_id
                                        if state else None),
                      **extra)

    try:
        result = await _run_with_heartbeat(
            _call, interval=heartbeat_interval(), event=COVER_STYLE_RUNNING,
            run_id=correlation_id, job_id=job_id, model=meta["model"],
            provider=meta["provider"], on_beat=heartbeat)
    except Exception as exc:
        result = EditResult(ok=False, reason=type(exc).__name__,
                            model=meta["model"], provider=meta["provider"])
    if not isinstance(result, EditResult):        # защита от моков-заглушек
        result = EditResult(ok=bool(getattr(result, "ok", False)),
                            content=getattr(result, "content", None),
                            reason=str(getattr(result, "reason", "error")),
                            task_id=getattr(result, "task_id", None),
                            async_used=bool(getattr(result, "async_used", False)),
                            latency_ms=int(getattr(result, "latency_ms", 0)),
                            meta=dict(getattr(result, "meta", {}) or {}))
    # ── T-4814/T-4875: provider limit → cache/recompile → РОВНО ОДИН bounded
    # retry на весь style stage. Известный N (`prompt_limit`): recompile под
    # лимит; unknown (`prompt_limit_unknown`, 400-too-long без числа):
    # semantic compiler сбрасывает P2/P3, сохраняя P0/P1 инварианты. Второй
    # paid call уходит ТОЛЬКО если prompt реально стал короче (ASAP 4.3
    # §7.1/§8 T-4848); скрытого multi-paid loop нет.
    result_meta = dict(getattr(result, "meta", {}) or {})
    if not result.ok and result.reason in ("prompt_limit",
                                           "prompt_limit_unknown"):
        try:
            if result.reason == "prompt_limit" and result_meta.get(
                    "prompt_limit"):
                if cap.dynamic_prompt_limit_enabled():
                    pl = result_meta["prompt_limit"]
                    cap.record_runtime_limit(
                        meta.get("provider") or "", slot.get("base_url") or "",
                        meta.get("model") or "",
                        result_meta.get("route"), int(pl.get("value") or 0),
                        str(pl.get("unit") or "chars"))
                    caps_retry = cap.resolve_capabilities(
                        meta.get("provider") or "", slot.get("base_url") or "",
                        meta.get("model") or "",
                        route=result_meta.get("route"),
                        operation=edit_operation)
                    recompiled = compile_style_prompt(
                        profile, issue_display=issue_display,
                        capabilities=caps_retry,
                        base_style_prompt=base_style_prompt or "",
                        brief=brief, story_scene=scene_text)
                    shorter = len(recompiled.prompt) < len(compiled.prompt)
                    retry_ok = (not getattr(recompiled, "exceeded", False)
                                and shorter)
                    meta["prompt_limit_retry"] = {
                        "resolved_limit": pl.get("value"),
                        "unit": pl.get("unit"),
                        "recompiled_chars": len(recompiled.prompt),
                        "retry_sent": bool(retry_ok),
                    }
                    if not retry_ok:
                        # Bounded retry: exceeded/не короче → второй paid call не
                        # отправляется; честная причина в diagnostics.
                        meta["prompt_limit_retry"]["skipped"] = (
                            "exceeded" if getattr(recompiled, "exceeded", False)
                            else "not_shorter")
                        meta["prompt_diagnostics"] = {
                            **(meta.get("prompt_diagnostics") or {}),
                            "overflow_reason": "prompt_limit_exceeded",
                        }
                        result = EditResult(ok=False, reason="prompt_limit",
                                            model=meta["model"],
                                            provider=meta["provider"],
                                            meta=result.meta)
                    else:
                        sent_prompts.append((2, recompiled.prompt))
                        emit_cover_event(
                            COVER_STYLE_SUBMITTED, outcome="retry",
                            run_id=correlation_id, job_id=job_id,
                            chat_id=chat_id, model=meta["model"],
                            provider=meta["provider"],
                            prompt_len=len(recompiled.prompt),
                            prompt_hash=prompt_hash(recompiled.prompt),
                            resolved_limit=pl.get("value"),
                            retry_reason="prompt_limit")
                        try:
                            result = await _run_with_heartbeat(
                                lambda: _call(recompiled.prompt),
                                interval=heartbeat_interval(),
                                event=COVER_STYLE_RUNNING,
                                run_id=correlation_id, job_id=job_id,
                                model=meta["model"], provider=meta["provider"],
                                on_beat=heartbeat)
                        except Exception as exc:
                            result = EditResult(
                                ok=False, reason=type(exc).__name__,
                                model=meta["model"], provider=meta["provider"])
            elif result.reason == "prompt_limit_unknown":
                # T-4875 + ASAP 5 (D9/T-5251): без числа — bounded semantic
                # squeeze до mandatory-ядра (runtime полностью + story-minimum
                # 160 chars/100% + profile identity ≥50% + mandatory reference
                # roles). Прежний `minimal=True` (потеря сюжета) ЗАПРЕЩЁН.
                recompiled = compile_style_prompt(
                    profile, issue_display=issue_display,
                    capabilities=caps, base_style_prompt=base_style_prompt
                    or "", brief=brief, story_scene=scene_text,
                    retry_core=True)
                shorter = len(recompiled.prompt) < len(compiled.prompt)
                retry_info = {
                    "mode": "semantic_squeeze",
                    "original_chars": len(compiled.prompt),
                    "recompiled_chars": len(recompiled.prompt),
                    "story_min_chars": len(cpa.story_floor_text(budget_text)),
                    "retry_sent": bool(shorter),
                }
                if not shorter:
                    # Идентичный/не короче — resend запрещён (деньги впустую).
                    retry_info["skipped"] = "not_shorter"
                else:
                    sent_prompts.append((2, recompiled.prompt))
                    emit_cover_event(
                        COVER_STYLE_SUBMITTED, outcome="retry",
                        run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                        model=meta["model"], provider=meta["provider"],
                        prompt_len=len(recompiled.prompt),
                        prompt_hash=prompt_hash(recompiled.prompt),
                        retry_reason="prompt_limit_unknown")
                    try:
                        result = await _run_with_heartbeat(
                            lambda: _call(recompiled.prompt),
                            interval=heartbeat_interval(),
                            event=COVER_STYLE_RUNNING, run_id=correlation_id,
                            job_id=job_id,
                            model=meta["model"], provider=meta["provider"],
                            on_beat=heartbeat)
                    except Exception as exc:
                        result = EditResult(
                            ok=False, reason=type(exc).__name__,
                            model=meta["model"], provider=meta["provider"])
                    if result.ok:
                        # Успешный adaptive retry → route-specific
                        # learned_safe_ceiling (source runtime_safe; НЕ
                        # выдаётся за exact provider max).
                        # ASAP 7 B5: only_raise — ceiling не ракетится вниз
                        # от длины сжатого retry-промпта (хронический
                        # squeeze story запрещён); bound виден в diagnostics.
                        ceiling = len(recompiled.prompt)
                        retry_info["learned_safe_ceiling"] = ceiling
                        retry_info["ceiling_source"] = "runtime_safe"
                        retry_info["ceiling_bound"] = "only_raise"
                        if cap.dynamic_prompt_limit_enabled():
                            cap.record_runtime_safe_ceiling(
                                meta.get("provider") or "",
                                slot.get("base_url") or "",
                                meta.get("model") or "",
                                result_meta.get("route") or edit_route or None,
                                ceiling, cap.UNIT_CHARS, only_raise=True)
                    elif result.reason in ("prompt_limit_unknown",
                                           "prompt_limit"):
                        # Повторный too-long после сокращения — честная
                        # причина, без generic bad_request и без второго retry.
                        result = EditResult(
                            ok=False,
                            reason="prompt_limit_unknown_after_retry",
                            model=meta["model"], provider=meta["provider"],
                            meta=dict(getattr(result, "meta", {}) or {}))
                meta["prompt_limit_unknown_retry"] = retry_info
        except Exception:
            logger.debug("[cover_style_jobs] prompt-limit retry failed",
                         exc_info=True)

    # ── ASAP 5 (D7/T-5249): CoverPromptManifest — фактические sent prompt'ы
    # обеих attempts. Полный prompt живёт в durable state (task_jobs payload);
    # в generic log/events НЕ попадает (SAFE_LOG_FIELDS не расширялись).
    manifest = _build_style_manifest(
        profile=profile, issue_display=issue_display,
        base_style_prompt=base_style_prompt or "", brief_text=brief_text,
        scene_text=scene_text, sent_prompts=sent_prompts,
        meta=meta, caps=caps)
    if manifest is not None:
        if state is not None:
            state.prompt_manifest = manifest
        if manifest_out is not None:
            manifest_out["prompt_manifest"] = manifest
        meta["prompt_manifest_hash"] = manifest.get("prompt_hash") or ""
        meta["prompt_manifest_chars"] = manifest.get("final_chars") or 0
    meta["provider_task_id"] = result.task_id
    meta["async_used"] = bool(result.async_used)
    record_latency(meta["model"], "style_edit", result.latency_ms,
                   timeout=(result.reason == "timeout"),
                   retry=False,
                   provider_fallback=False)
    if state is not None and result.task_id:
        state.provider_task_id = result.task_id
        # §43: provider task_id персистится немедленно — рестарт возобновит
        # polling этой же задачи и не создаст новый платный task.
        state.mark(STATE_STYLE_RUNNING, provider_task_id=result.task_id)
        await _persist_state(db, job_id, state)

    if result.ok and result.content:
        # ── ASAP 8 v6 C03A (кейс 5) + B04.6 v6.3: детерминированная
        # payload-валидация результата edit. 2xx с НЕ-изображением — это НЕ
        # успех: провайдер, ответивший текстом (отказ/подмена сцены),
        # теряет сюжет проверяемо → `semantic_preservation_failed`; битые
        # бинарные байты → `invalid_image_payload`. Magic bytes — ТОЛЬКО
        # формат (format_valid), не семантика; semantic-сохранность —
        # bounded image-comparison (scene_preserved) по прозрачной
        # политике (`scene_verify_mode`): preview/canary — да, каждый
        # прод-вызов — нет (бюджет). Оба фейла — fail-soft Base, платного
        # повтора нет. ────────────────────────────────────────────────────
        format_valid, format_reason = _styled_payload_signal(result.content)
        if not format_valid:
            meta["semantic_verification"] = {
                "format_valid": False,
                "scene_preserved": "unknown",
                "detail": format_reason,
                "policy": scene_verify_mode(),
            }
            meta["fail_reason"] = format_reason
            _manifest_mark_outcome(manifest, applied=False,
                                   reason=format_reason)
            if isinstance(manifest, dict):
                manifest["semantic_verification"] = dict(
                    meta["semantic_verification"])
            await _record_provenance(
                obj, meta, summary_run_id=summary_run_id, job_id=job_id,
                snapshot=snapshot, status=registry.PROVENANCE_BASE,
                fallback_mode=format_reason, mode=mode)
            return await _style_failed(
                meta, state, reason=format_reason,
                message=reason_detail_ru(format_reason),
                run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                started=started, db=db)
        path = _write_temp_image(result.content)
        scene_check: dict = {"scene_preserved": "unknown",
                             "detail": "policy_off",
                             "policy": scene_verify_mode()}
        if path is not None and scene_verification_due(
                mode, verifier=scene_verifier) and base_image_path:
            scene_check = await verify_scene_preserved(
                base_image_path, path, verifier=scene_verifier)
            scene_check["policy"] = scene_verify_mode()
        elif path is not None and not scene_verify_env_explicit():
            scene_check = {"scene_preserved": "unknown",
                           "detail": "verification_env_not_set",
                           "policy": scene_verify_mode()}
        elif path is not None:
            scene_check = {"scene_preserved": "unknown",
                           "detail": "production_budget_policy",
                           "policy": scene_verify_mode()}
        if scene_check.get("scene_preserved") == "replaced":
            # B04.6: необоснованная подмена сюжета — НЕ успешный styled;
            # публикация сюжетно ложной обложки запрещена (fail-soft Base).
            meta["semantic_verification"] = {
                "format_valid": True,
                **scene_check,
            }
            meta["fail_reason"] = REASON_SEMANTIC_LOST
            _manifest_mark_outcome(manifest, applied=False,
                                   reason=REASON_SEMANTIC_LOST)
            if isinstance(manifest, dict):
                manifest["semantic_verification"] = dict(
                    meta["semantic_verification"])
            await _record_provenance(
                obj, meta, summary_run_id=summary_run_id, job_id=job_id,
                snapshot=snapshot, status=registry.PROVENANCE_BASE,
                fallback_mode=REASON_SEMANTIC_LOST, mode=mode)
            return await _style_failed(
                meta, state, reason=REASON_SEMANTIC_LOST,
                message=reason_detail_ru(REASON_SEMANTIC_LOST),
                run_id=correlation_id, job_id=job_id, chat_id=chat_id,
                started=started, db=db)
        if path is not None:
            meta.update(applied=True, styled_path=path, outcome=RESULT_STYLED,
                        reason="", duration_ms=_elapsed(started),
                        final_asset_id=_asset_id_of(path))
            # B04.6: format_valid и scene_preserved — РАЗНЫЕ сигнала;
            # «unknown» честен (не молчаливое true).
            meta["semantic_verification"] = {
                "format_valid": True,
                **scene_check,
            }
            if mode == MODE_PRODUCTION:
                # Durable styled-артефакт run'а (переживает удаление
                # temp-файла публикацией; recovery/retry переиспользует).
                saved = persist_style_artifact(
                    str(summary_run_id or ""), path, "styled")
                if saved:
                    meta["styled_asset_path"] = saved
            _manifest_mark_outcome(manifest, applied=True)
            if isinstance(manifest, dict):
                manifest["semantic_verification"] = dict(
                    meta["semantic_verification"])
                # C03A: styled-статус в самом манифесте (Inspector читает
                # state.prompt_manifest через load_run_cover_prompts).
                manifest["styled_status"] = {
                    "status": "styled", "reason": None,
                    "route": meta.get("edit_route"), "attempt": 0}
            if state is not None:
                state.mark(STATE_STYLE_SUCCEEDED,
                           provider_task_id=result.task_id)
                state.styled_status = RESULT_STYLED
                state.styled_fail_reason = None
                if meta.get("styled_asset_path"):
                    state.styled_asset_path = meta["styled_asset_path"]
                await _persist_state(db, job_id, state)
            emit_cover_event(
                COVER_STYLE_SUCCEEDED, outcome="success", run_id=correlation_id,
                job_id=job_id, chat_id=chat_id, model=meta["model"],
                provider=meta["provider"], duration_ms=meta["duration_ms"],
                provider_task_id=result.task_id, async_used=result.async_used,
                style_id=meta["style_id"], style_revision=meta["style_revision"],
                issue_number=issue_no)
            await _record_provenance(
                obj, meta, summary_run_id=summary_run_id, job_id=job_id,
                snapshot=snapshot, status=registry.PROVENANCE_STYLED,
                fallback_mode="", mode=mode)
            return meta
        result = EditResult(ok=False, reason="temp_write_failed",
                            model=meta["model"], provider=meta["provider"])

    meta["fail_reason"] = result.reason
    _manifest_mark_outcome(manifest, applied=False, reason=result.reason)
    await _record_provenance(
        obj, meta, summary_run_id=summary_run_id, job_id=job_id,
        snapshot=snapshot, status=registry.PROVENANCE_BASE,
        fallback_mode=REASON_STYLE_FAILED, mode=mode)
    return await _style_failed(
        meta, state, reason=result.reason, message="",
        run_id=correlation_id, job_id=job_id, chat_id=chat_id,
        started=started, db=db)


async def _style_failed(meta: dict, state, *, reason: str, message: str,
                        run_id, job_id, chat_id, started, db=None) -> dict:
    meta.update(applied=False, styled_path=None, outcome=RESULT_BASE,
                reason=REASON_STYLE_FAILED, fail_reason=reason,
                message=message, duration_ms=_elapsed(started))
    # C03A: честный styled-статус прямо в meta (публикующий владелец может
    # уточнить его на retry_scheduled — recovery-бюджет/классификация).
    meta["styled_status"] = "failed"
    meta["styled_fail_reason"] = reason
    if state is not None:
        state.mark(STATE_STYLE_FAILED, note=reason)
        set_styled_status(state, status="failed", reason=reason,
                           route=meta.get("edit_route"))
        await _persist_state(db, job_id, state)
    if snapshot_enabled():
        # ASAP-4 волна B (§2 B.4): mca_events reason_code перестаёт
        # схлопывать конкретную причину в generic `style_failed`
        # (прод-факт Q14: `not_configured` был невидим в Analytics).
        code = style_reason_code(reason)
    else:
        code = (reason if reason in ("style_failed", "edit_unsupported")
                else REASON_STYLE_FAILED)
    emit_cover_event(
        COVER_STYLE_FAILED, outcome="failed", level=logging.WARNING,
        run_id=run_id, job_id=job_id, chat_id=chat_id, model=meta["model"],
        provider=meta["provider"], duration_ms=meta["duration_ms"],
        reason=reason, fallback=REASON_STYLE_FAILED,
        reason_code=code,
        style_id=meta["style_id"], issue_number=meta.get("issue_number"))
    return meta


async def _record_provenance(pg, meta, *, summary_run_id, job_id, snapshot,
                             status, fallback_mode, mode) -> None:
    if pg is None:
        return
    try:
        await registry.record_provenance(pg, {
            "summary_run_id": summary_run_id, "job_id": job_id,
            "style_id": meta.get("style_id"),
            "style_revision": meta.get("style_revision"),
            "issue_number": meta.get("issue_number"),
            "base_asset_id": meta.get("base_asset_id"),
            "final_asset_id": meta.get("final_asset_id"),
            "provider": meta.get("provider"), "model": meta.get("model"),
            "connection_id": (snapshot or {}).get("connection_id"),
            "reference_asset_ids": (snapshot or {}).get("reference_asset_ids"),
            "status": status, "fallback_mode": fallback_mode, "mode": mode,
        })
    except Exception:
        logger.debug("[cover_style_jobs] provenance record failed",
                     exc_info=True)


async def run_style_preview(*, profile: dict, base_image_path: str,
                            reference_paths: list | None = None, pg=None,
                            capabilities=None, discovery: dict | None = None,
                            endpoints: dict | None = None, edit_call=None,
                            db=None, job_id: str | None = None,
                            state: CoverJobState | None = None,
                            correlation_id: str | None = None) -> dict:
    """`Протестировать стиль` (§65/§66/§67): ТОЛЬКО Style Edit job.

    Не создаёт Summary, не расходует production counter (mode=preview),
    логируется с `mode=preview` (не смешивается со статистикой production).

    ASAP 4.3 (T-4843): preview идёт через тот же durable-контур, что
    production — `db`/`job_id`/`state` прокидываются в `run_style_job`
    (прежде helpers были no-op из-за отсутствия db/job_id).
    """
    meta = await run_style_job(
        chat_id=0, base_image_path=base_image_path, profile=profile,
        summary_run_id=None, correlation_id=correlation_id, pg=pg,
        db=db, job_id=job_id, state=state,
        capabilities=capabilities, discovery=discovery, endpoints=endpoints,
        reference_paths=reference_paths, edit_call=edit_call, mode=MODE_PREVIEW)
    meta["preview_issue"] = registry.preview_issue_display(
        (profile or {}).get("counter_format")
        or registry.SEEDED_COUNTER_FORMAT,
        registry.next_issue_number(profile))
    return meta


# ── ASAP 8 v6 C03A: recovery-контур styled cover (кейсы 2/3) ────────────────
# Механизм (ADR в plans/features/asap8-v6-remediation/c03a-report.md):
#   * публикация остаётся inline (второй очереди НЕТ — §42/Q6), но durable
#     job помечается running+heartbeat на время style-вызова, а Base
#     сохраняется в recovery-каталог ДО вызова — рестарт посреди стиля
#     оставляет возобновляемое состояние, а не зомби;
#   * recovery-в sweeps (`recover_cover_style_jobs`) дообрабатывает:
#     - `interrupted`/stale-`queued` (restart mid-style),
#     - `completed` с STYLE_FAILED и transient-причиной (style упал, Base
#       опубликован) — вторая попытка использует СОХРАНЁННУЮ Base (не
#       генерирует вторую), тот же issue-номер (pin run+profile),
#       idempotent publication: Telegram НЕ вызывается — восстановленный
#       styled связывается с тем же run (артефакт+manifest+provenance),
#       дублей публикации нет;
#   * bounded: max_attempts на job + backoff + batch limit; permanent-причины
#     не зацикливаются (честный failed + причина в Inspector).

_RECOVERY_LOCK: asyncio.Lock | None = None
_RECOVERY_KICK_TASK: asyncio.Task | None = None

# B04.5: runtime-держатель бота для explicit Telegram-замены (по умолчанию
# recovery Telegram НЕ вызывает — `telegram_replace_enabled`).
_COVER_BOT_HOLDER: dict = {"bot": None}


def bind_cover_runtime(bot) -> None:
    """DI-точка бота для B04.5-замены изображения выпуска. Вызывается
    composition root'ом; recovery сам бот не достаёт."""
    _COVER_BOT_HOLDER["bot"] = bot


async def _recovery_style_inputs(db, run_id: str) -> dict | None:
    """Компиляционные входы для recovery-попытки — из durable Base-манифеста
    run'а (компоненты STORY_SCENE/SUMMARY_CONTEXT/BASE_STYLE хранят
    sent_text). None — манифеста нет (честный отказ, не слепой retry)."""
    try:
        manifest = await load_base_cover_manifest(db, run_id)
    except Exception:
        return None
    if not isinstance(manifest, dict):
        return None
    comps = {}
    for comp in (manifest.get("components") or []):
        if isinstance(comp, dict) and comp.get("key"):
            comps[str(comp["key"])] = comp
    def _txt(key: str) -> str:
        comp = comps.get(key) or {}
        return str(comp.get("sent_text") or comp.get("original_text") or "")
    story = _txt("STORY_SCENE")
    if not story:
        return None
    context = _txt("SUMMARY_CONTEXT")
    return {
        "story_scene": story,
        "summary_text": context or story,
        "base_style_prompt": _txt("BASE_STYLE"),
    }


async def _recover_one_cover_style_job(db, row: dict, *, pg=None,
                                       edit_call=None,
                                       now: int | None = None) -> dict | None:
    """Дообработать одну cover_style-джобу (см. `recover_cover_style_jobs`)."""
    from services.task_supervisor import TaskJobStore
    store = TaskJobStore(db)
    job_id = str(row.get("job_id") or "")
    payload: dict = {}
    try:
        payload = json.loads(row.get("payload") or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except (ValueError, TypeError):
        payload = {}
    cursor = payload.get("cursor")
    state = CoverJobState.from_json(cursor if isinstance(cursor, str) else "")
    if state is None or not state.style_id or state.state == STATE_DONE:
        return None                       # не наша/завершённая — пропустить
    # REV-WAVE-B F1 (Critical): УЖЕ УСПЕШНЫЙ styled recovery не перезапускает.
    # Production-инлайн ставит task_jobs='completed' (finish_cover_job c
    # RESULT_STYLED), а cursor навсегда остаётся STATE_STYLE_SUCCEEDED /
    # styled_status='styled' — DONE ставит только preview-путь
    # (cover_style_preview). Без этой ветки sweep ретраил платный edit и
    # финализировал успешную джобу как failed/recovery_exhausted.
    # Идемпотентность: 0 edit-вызовов, статус/manifest не изменяются.
    # Legacy-успехи (cursor без base_asset_path, но со styled-результатом)
    # защищены той же веткой (styled_status='styled' или
    # STATE_STYLE_SUCCEEDED).
    if row.get("status") == "completed" and (
            state.state == STATE_STYLE_SUCCEEDED
            or state.styled_status == RESULT_STYLED):
        return None
    run_id = str(payload.get("correlation_id")
                 or row.get("coalesce_key") or "").strip()
    run_id = run_id.replace("cover_style:", "", 1) if run_id else ""
    chat_id = int(payload.get("chat_id") or 0)
    obj = pg if pg is not None else _pg()

    def _finish_failed(reason: str) -> dict:
        state.styled_status = "failed"
        state.styled_fail_reason = reason
        set_styled_status(state, status="failed", reason=reason,
                           attempt=state.retry_count)
        return {"job_id": job_id, "action": "failed", "reason": reason}

    # Bounded retry: бюджет исчерпан → честный терминальный failed.
    if state.retry_count >= recovery_max_attempts():
        await save_cover_state(db, job_id, state)
        await store.finish(job_id, status="failed",
                           reason_code=REASON_RECOVERY_EXHAUSTED)
        emit_cover_event(
            COVER_STYLE_RETRY_SCHEDULED, outcome="failed",
            level=logging.WARNING, run_id=run_id or None, job_id=job_id,
            chat_id=chat_id or None, reason_code=REASON_RECOVERY_EXHAUSTED,
            reason=REASON_RECOVERY_EXHAUSTED, attempt=state.retry_count,
            status="recovery_exhausted")
        result = _finish_failed(REASON_RECOVERY_EXHAUSTED)
        await save_cover_state(db, job_id, state)
        return result

    # Permanent-причина style-фейла (completed после публикации Base) —
    # повторять вслепую запрещено: тот же исход.
    last_fail = str(state.styled_fail_reason
                    or row.get("reason_code") or "")
    if row.get("status") == "completed" and last_fail \
            and classify_style_failure(last_fail) != "transient":
        return None

    # ── Ресурсы recovery: Base/profile/inputs. Что-то недоступно → честный
    # permanent-финал (вторая генерация Base запрещена v6). ────────────────
    base_path = state.base_asset_path
    if not base_path or not os.path.exists(str(base_path)):
        await save_cover_state(db, job_id, state)
        await store.finish(job_id, status="failed",
                           reason_code=REASON_BASE_ASSET_MISSING)
        emit_cover_event(
            COVER_STYLE_RETRY_SCHEDULED, outcome="failed",
            level=logging.WARNING, run_id=run_id or None, job_id=job_id,
            chat_id=chat_id or None, reason_code=REASON_BASE_ASSET_MISSING,
            reason=REASON_BASE_ASSET_MISSING, attempt=state.retry_count,
            status="recovery_failed")
        result = _finish_failed(REASON_BASE_ASSET_MISSING)
        await save_cover_state(db, job_id, state)
        return result
    profile = None
    if obj is not None:
        try:
            profile = await registry.get_profile_with_refs(obj, state.style_id)
        except Exception:
            profile = None
    if not profile or not profile.get("enabled"):
        await save_cover_state(db, job_id, state)
        await store.finish(job_id, status="failed",
                           reason_code=REASON_PROFILE_MISSING)
        result = _finish_failed(REASON_PROFILE_MISSING)
        await save_cover_state(db, job_id, state)
        return result
    inputs = await _recovery_style_inputs(db, run_id)
    if inputs is None:
        await save_cover_state(db, job_id, state)
        await store.finish(job_id, status="failed",
                           reason_code=REASON_STYLE_INPUTS_MISSING)
        result = _finish_failed(REASON_STYLE_INPUTS_MISSING)
        await save_cover_state(db, job_id, state)
        return result

    # ── Возобновляемая попытка: queued/running владение + heartbeat. ──────
    state.retry_count = int(state.retry_count or 0) + 1
    state.styled_status = "retry_scheduled"
    await save_cover_state(db, job_id, state)
    await requeue_cover_job(db, job_id, reason_code="style_recovery")
    await store.mark_running(job_id)

    async def _beat():
        await store.heartbeat(job_id)

    meta = await run_style_job(
        chat_id=chat_id, base_image_path=str(base_path), profile=profile,
        summary_run_id=run_id or None, correlation_id=run_id or None,
        db=db, job_id=job_id, state=state, pg=obj, edit_call=edit_call,
        mode=MODE_PRODUCTION, heartbeat=_beat, **inputs)
    if meta.get("styled_path"):
        # ── B04.5: ЯВНОЕ решение доставки восстановленного styled. ─────────
        # Политика `telegram_replace_enabled` (env
        # COVER_STYLE_TELEGRAM_REPLACE_ENABLED, default OFF): OFF — артефакт
        # восстановлен и связан с run (manifest+provenance), Telegram НЕ
        # вызывается и исход помечен `not_attempted_policy_off` — НЕ тихий
        # «recovered=доставлен». ON — идемпотентная замена media
        # существующего выпуска (editMessageMedia): unsupported/нет ссылки —
        # честный статус, дубль-публикация запрещена.
        delivery_status = DELIVERY_NOT_ATTEMPTED
        delivery_detail = "policy_off"
        if telegram_replace_enabled():
            bot_obj = _COVER_BOT_HOLDER.get("bot")
            message_id = await lookup_published_message_id(
                db, run_id, chat_id)
            if bot_obj is None or message_id is None or not chat_id:
                delivery_status = DELIVERY_NO_REFERENCE
                delivery_detail = "bot_or_message_reference_missing"
            else:
                ok_delivered, delivery_status = (
                    await replace_published_cover_image(
                        bot_obj, chat_id=chat_id, message_id=message_id,
                        styled_path=str(meta.get("styled_path"))))
                delivery_detail = delivery_status
        set_styled_status(state, status="styled", reason=None,
                           route=meta.get("edit_route"),
                           attempt=state.retry_count)
        state.telegram_delivery = delivery_status
        await save_cover_state(db, job_id, state)
        await finish_cover_job(db, job_id, outcome=RESULT_STYLED,
                               reason_code=None, checkpoint=state)
        emit_cover_event(
            COVER_STYLE_RECOVERED, outcome="success", run_id=run_id or None,
            job_id=job_id, chat_id=chat_id or None, model=meta.get("model"),
            provider=meta.get("provider"), attempt=state.retry_count,
            style_id=meta.get("style_id"), status="styled_recovered",
            telegram_delivery=delivery_status)
        return {"job_id": job_id, "action": "recovered", "reason": "",
                "attempt": state.retry_count,
                "telegram_delivery": delivery_status,
                "delivery_detail": delivery_detail}
    reason = str(meta.get("fail_reason") or "style_failed")
    cls = classify_style_failure(reason)
    if cls == "transient" and state.retry_count < recovery_max_attempts():
        set_styled_status(state, status="retry_scheduled", reason=reason,
                           route=meta.get("edit_route"),
                           attempt=state.retry_count)
        await save_cover_state(db, job_id, state)
        try:
            ts = int(now if now is not None else time.time())
            await store.set_next_retry(
                job_id, ts + recovery_backoff_seconds(state.retry_count),
                reason_code=reason)
        except Exception:
            pass
        emit_cover_event(
            COVER_STYLE_RETRY_SCHEDULED, outcome="skipped",
            level=logging.WARNING, run_id=run_id or None, job_id=job_id,
            chat_id=chat_id or None, reason_code=reason, reason=reason,
            attempt=state.retry_count, status="retry_scheduled")
        return {"job_id": job_id, "action": "scheduled", "reason": reason,
                "attempt": state.retry_count}
    set_styled_status(state, status="failed", reason=reason,
                       route=meta.get("edit_route"),
                       attempt=state.retry_count)
    await save_cover_state(db, job_id, state)
    await store.finish(job_id, status="failed", reason_code=reason)
    emit_cover_event(
        COVER_STYLE_RETRY_SCHEDULED, outcome="failed", level=logging.WARNING,
        run_id=run_id or None, job_id=job_id, chat_id=chat_id or None,
        reason_code=reason, reason=reason, attempt=state.retry_count,
        status="recovery_failed")
    return {"job_id": job_id, "action": "failed", "reason": reason,
            "attempt": state.retry_count}


async def recover_cover_style_jobs(db, *, pg=None, edit_call=None,
                                   limit: int = 1,
                                   now: int | None = None) -> list[dict]:
    """Recovery-проход durable cover_style-джоб (v6 C03A кейсы 2/3).

    Кандидаты: ``interrupted`` (restart mid-style — ставится recover_stale),
    stale ``queued`` (зомби прежних деплоев, R2) и ``completed`` с
    STYLE_FAILED в checkpoint (style упал, Base опубликован — bounded retry
    transient-причин). ``running`` не трогается: это живая инлайн-стадия
    (heartbeat) или зона `recover_stale` (fencing).

    Каждая попытка: сохранённая Base (никогда не вторая генерация), тот же
    issue-номер (pin run+profile), recompiled-промпт из durable-компонент
    Base-манифеста (детерминированный компилятор), идемпотентная
    публикация: Telegram НЕ вызывается, styled связывается с run как
    артефакт+manifest+provenance. Возвращает список действий."""
    if db is None or not recovery_enabled():
        return []
    global _RECOVERY_LOCK
    if _RECOVERY_LOCK is None:
        _RECOVERY_LOCK = asyncio.Lock()
    if _RECOVERY_LOCK.locked():
        return []                         # параллельный sweep уже работает
    async with _RECOVERY_LOCK:
        ts = int(now if now is not None else time.time())
        stale_cutoff = ts - max(60, stale_window_seconds())
        try:
            cursor = await db.db.execute(
                "SELECT * FROM task_jobs WHERE kind = ? AND ("
                "status = 'interrupted' OR "
                "(status = 'queued' AND updated_at < ?) OR "
                "(status = 'completed' AND (next_retry_at IS NULL OR "
                "next_retry_at <= ?)) "
                ") AND (next_retry_at IS NULL OR next_retry_at <= ?) "
                "ORDER BY updated_at ASC LIMIT 25",
                ("cover_style", stale_cutoff, ts, ts))
            rows = [dict(r) for r in await cursor.fetchall()]
        except Exception:
            logger.warning("[cover_style_jobs] recovery select failed",
                           exc_info=True)
            return []
        out: list[dict] = []
        for row in rows:
            if len(out) >= max(1, int(limit)):
                break
            try:
                action = await _recover_one_cover_style_job(
                    db, row, pg=pg, edit_call=edit_call, now=ts)
            except Exception:
                logger.warning("[cover_style_jobs] recovery attempt failed "
                               "| job_id=%s", row.get("job_id"),
                               exc_info=True)
                continue
            if action is not None:
                out.append(action)
        return out


def stale_window_seconds() -> int:
    """Окно stale для queued-зомби (сек): heartbeat-watchdog stale."""
    try:
        from services import mca_gates
        return int(mca_gates.job_stale_seconds())
    except Exception:
        return 600


def kick_cover_style_recovery(db) -> int:
    """Неблокирующий запуск recovery-прохода (watchdog sweep/startup).

    Возвращает 1 — проход запланирован (background task), 0 — уже идёт или
    выключен. Ошибки прохода не всплывают в sweep (fail-open)."""
    global _RECOVERY_KICK_TASK
    if db is None or not recovery_enabled():
        return 0
    task = _RECOVERY_KICK_TASK
    if task is not None and not task.done():
        return 0

    async def _run():
        try:
            await recover_cover_style_jobs(db)
        except Exception:
            logger.warning("[cover_style_jobs] recovery kick failed",
                           exc_info=True)

    try:
        _RECOVERY_KICK_TASK = asyncio.ensure_future(_run())
    except RuntimeError:                  # нет running loop — fail-open
        return 0
    return 1


def _elapsed(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


__all__ = [
    "COVER_PIPELINE_START", "COVER_BASE_SUBMITTED", "COVER_BASE_RUNNING",
    "COVER_BASE_SUCCEEDED", "COVER_BASE_FAILED", "COVER_STYLE_SELECTION",
    "COVER_STYLE_SKIPPED", "COVER_STYLE_START", "COVER_STYLE_RESOLVE",
    "COVER_STYLE_SUBMITTED", "COVER_STYLE_RUNNING", "COVER_STYLE_SUCCEEDED",
    "COVER_STYLE_FAILED", "COVER_RICH_PUBLISH_START",
    "COVER_RICH_PUBLISH_SUCCEEDED", "COVER_RICH_PUBLISH_FAILED",
    "COVER_PLAIN_FALLBACK", "COVER_PIPELINE_DONE", "RESULT_STYLED",
    "RESULT_BASE", "RESULT_NONE", "RESULT_PLAIN", "REASON_STYLE_FAILED",
    "REASON_BASE_FAILED", "REASON_RICH_FAILED", "REASON_NO_STYLE",
    "REASON_PROFILE_MISSING", "REASON_DISABLED", "REASON_CONNECTION_MISSING",
    "REASON_REFERENCE_MISSING", "REASON_CAPABILITY_UNKNOWN",
    "REASON_NOT_CONFIGURED", "REASON_NO_STYLE_STAGE", "RU_STYLE_FAILED",
    "RU_BASE_FAILED", "RU_RICH_FAILED", "CoverJobState", "start_cover_job",
    "finish_cover_job", "save_cover_state", "load_cover_state",
    "get_cover_job", "requeue_cover_job",
    "begin_cover_job", "cover_job_key", "run_style_job",
    "run_style_preview", "classify_cover_result", "build_timeline",
    "record_latency", "latency_stats", "record_cost", "cost_summary",
    "reset_metrics", "emit_cover_event", "prompt_hash", "compile_style_prompt",
    # ASAP 5 (D7-D9): манифест/сборка/персист
    "record_base_cover_manifest", "load_base_cover_manifest",
    "base_manifest_job_key", "manifest_public",
    "load_run_cover_prompts",
    "style_reference_text",
    "style_publish_skip_reason", "STYLE_PUBLISH_SKIP_OVERFLOW",
    "STYLE_PUBLISH_SKIP_STORY",
    "snapshot_enabled", "resolve_selection", "emit_style_selection",
    "selection_stage", "profile_for_snapshot", "report_style_skip",
    "record_no_cover_provenance", "style_reason_code", "reason_detail_ru",
    "style_skip_status", "profile_diagnostics", "resolve_selected_style_id",
    # ASAP 8 v6 C03A: recovery-контур styled cover
    "REASON_STYLE_DISABLED", "REASON_SEMANTIC_LOST", "REASON_INVALID_PAYLOAD",
    "REASON_BASE_ASSET_MISSING", "REASON_STYLE_INPUTS_MISSING",
    "REASON_RECOVERY_EXHAUSTED",
    "COVER_STYLE_RETRY_SCHEDULED", "COVER_STYLE_RECOVERED",
    "recovery_enabled", "recovery_max_attempts", "classify_style_failure",
    "recovery_backoff_seconds", "recovery_dir", "persist_style_artifact",
    "recover_cover_style_jobs", "kick_cover_style_recovery",
    "set_styled_status",
    # ASAP 8 v6.3 B04: компактный EDIT-контракт + control сюжета + доставка.
    "compile_style_edit_components", "normalize_style_edit_components",
    "style_edit_headroom_chars", "edit_content_language",
    "scene_anchor_policy", "scene_anchor_candidate", "scene_verify_mode",
    "scene_verification_due", "verify_scene_preserved",
    "style_edit_preview_report", "bind_cover_runtime",
    "replace_published_cover_image", "lookup_published_message_id",
    "telegram_replace_enabled",
]
