# -*- coding: utf-8 -*-
"""ASAP 8 v6.3 W3-ANALYTICS — Playwright e2e (фикстурные данные): U05 + B08 UI.

Проверяется рендер web/index.html + web/app.js на РЕАЛЬНЫХ структурах
данных (не NaN/нули-от-балды; /api/* — стабы, R17: только
идентификаторы/числа):

  * U05.1: Процессы по умолчанию — человеческое имя + эффективный статус
    (работает с результатом / ошибка / не было условий / не запускался /
    выключен) + последнее действие; developer-ID/стадии/события — внутри
    закрытых «Деталей»; Запуски — human-метка типа;
  * U05.3 (7 виджетов D12 §18I.12): heatmap активности (Обзор), цикл
    памяти flow + timeline дат источников фактчека (Память и интеллект),
    маршрут обработки Sankey-lite (Запуски), waterfall latency (Модели и
    расходы), карта зависимостей (Процессы), popover overrides (Обзор);
  * B08 UI: карточка ready (synopsis + хронология refs t.me/c/«в архиве»,
    три даты, участники ≤5 + «ещё N») и insufficient («Не удалось
    восстановить сюжет: нет источников», без success-раскраски);
  * V05: 320/390 + landscape 667×375 без горизонтального переполнения;
  * скриншоты всего экрана desktop 1440 + mobile 390 → w3-evidence-analytics/.

Запуск: py -3 tools/ui_asap8_w3_analytics_e2e.py (итог: W3-ANALYTICS-E2E-OK).
TEST-LIFECYCLE: CONTRACT owner=REQ-U05/REQ-B08 (slice W3-ANALYTICS).
"""
import copy
import datetime
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (хандлер/стабы/TMA — reuse)

PORT = 8842
SHOTS = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction",
                     "w3-evidence-analytics")
NOW = 1791900000  # фиксированное «сейчас» (2026-10-15)


def _day(offset_days: int) -> str:
    d = datetime.datetime.now() - datetime.timedelta(days=offset_days)
    return d.strftime("%Y-%m-%d")


# ── /api/oversight/processes: реальная структура registry_snapshot ──
PROCESSES = {
    "available": True, "enabled": True, "count": 5,
    "processes": [
        {"process_id": "ingestion.live", "version": "1",
         "purpose": "Приём живых сообщений из чата в хранилище памяти",
         "inputs": ["telegram update"], "outputs": ["smart_messages"],
         "stages": ["receive", "identity", "persist"],
         "trigger_kind": "per_message", "schedule": "по сообщению",
         "settings_ref": ["MCA_MESSAGE_IDENTITY_ENABLED"],
         "state_source": ["smart_messages"], "recovery_ops": ["resume_stream"],
         "widget_id": "Приём/импорт/редакции",
         "stages_to_events": {"persist": "ingestion_live"},
         "instrumentation": ["persist"], "owner_feature": "mca-03",
         "event_names": ["ingestion_live"], "status": "implemented",
         "note": "mca-17: notable-only"},
        {"process_id": "summary.window", "version": "1",
         "purpose": "Накопление окна сообщений и построение running-summary",
         "inputs": ["smart_messages"], "outputs": ["chat_running_summary"],
         "stages": ["window", "summarize"], "trigger_kind": "on_write",
         "schedule": "по сообщению", "settings_ref": ["SUMMARY_ENABLED"],
         "state_source": ["smart_messages"], "recovery_ops": [],
         "widget_id": "Окно/summary", "stages_to_events": {},
         "instrumentation": [], "owner_feature": "summary",
         "event_names": [], "status": "implemented", "note": ""},
        {"process_id": "episodes.build", "version": "1",
         "purpose": "Сборка эпизодов/историй: сегментация → извлечение",
         "inputs": ["smart_messages"], "outputs": ["mca_stories"],
         "stages": ["segment", "extract", "assemble"],
         "trigger_kind": "schedule", "schedule": "периодически",
         "settings_ref": ["MCA_EPISODES_ENABLED"],
         "state_source": ["mca_episodes"], "recovery_ops": ["resume_job"],
         "widget_id": "Эпизоды/lore", "stages_to_events": {},
         "instrumentation": [], "owner_feature": "mca-05",
         "event_names": ["story_rebuilt"], "status": "implemented",
         "note": ""},
        {"process_id": "self_learning.run", "version": "1",
         "purpose": "Опыт и уроки: эпизод → review → кандидат → проверка",
         "inputs": ["mca_experience_episodes"], "outputs": ["mca_lessons"],
         "stages": ["capture", "review", "validate"],
         "trigger_kind": "schedule", "schedule": "каждые 30 мин",
         "settings_ref": ["MCA_EXPERIENCE_LESSONS_ENABLED"],
         "state_source": ["mca_lessons"], "recovery_ops": ["resume_job"],
         "widget_id": "Опыт и уроки",
         "stages_to_events": {"validate": "semantic_extract"},
         "instrumentation": ["validate"], "owner_feature": "mca-16",
         "event_names": ["semantic_extract", "detector_signal"],
         "status": "implemented", "note": ""},
        {"process_id": "random.uses", "version": "1",
         "purpose": "Применения случайности (mca-10b): разговор/воспоминание",
         "inputs": ["mca_random_draws"], "outputs": [],
         "stages": ["draw", "apply"], "trigger_kind": "on_event",
         "schedule": "по событию", "settings_ref": ["MCA_RANDOM_USES_ENABLED"],
         "state_source": ["mca_random_draws"], "recovery_ops": [],
         "widget_id": "Случайность и её применения",
         "stages_to_events": {}, "instrumentation": [], "owner_feature": "mca-10b",
         "event_names": ["random_use"], "status": "implemented", "note": ""},
        {"process_id": "sleep.deep", "version": "1",
         "purpose": "Глубокий сон: парадигмы/самоосмысление",
         "inputs": ["graph_facts"], "outputs": ["paradigms"],
         "stages": ["collect", "reflect"], "trigger_kind": "schedule",
         "schedule": "ночью", "settings_ref": ["DEEP_SLEEP_ENABLED"],
         "state_source": ["memory_dream_log"], "recovery_ops": [],
         "widget_id": "Глубокий сон/парадигмы",
         "stages_to_events": {}, "instrumentation": [], "owner_feature": "dream",
         "event_names": ["deep_sleep_run"], "status": "implemented", "note": ""},
        {"process_id": "goodmorning.run", "version": "1",
         "purpose": "Планировщик утренних сообщений",
         "inputs": [], "outputs": ["telegram send"],
         "stages": ["plan", "send"], "trigger_kind": "schedule",
         "schedule": "утро", "settings_ref": ["GOODMORNING_ENABLED"],
         "state_source": [], "recovery_ops": [],
         "widget_id": "Планировщики", "stages_to_events": {},
         "instrumentation": [], "owner_feature": "morning",
         "event_names": ["goodmorning_sent"], "status": "disabled",
         "note": ""},
    ],
    "pipelines": [],
    "coverage": {"active": 4, "implemented": 4, "disabled": 1,
                 "not_run": 0, "not_instrumented": 0},
}

# ── /api/analytics/viz/process-activity: эффективные статусы + last action ──
PROCESS_ACTIVITY = {
    "available": True, "generated_at": NOW, "events_available": True,
    "processes": [
        {"process_id": "ingestion.live", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 120, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 100, "7d": 600}},
        {"process_id": "self_learning.run", "status": "implemented",
         "effective": "error", "reason": "последний запуск с ошибкой",
         "last_ts": NOW - 600, "last_outcome": "failed",
         "last_reason": "llm_unavailable", "last_error_type": "TimeoutError",
         "counts": {"24h": 1, "7d": 3}},
        {"process_id": "random.uses", "status": "implemented",
         "effective": "no_conditions",
         "reason": "условий не было: no_trigger", "last_ts": NOW - 90000,
         "last_outcome": "skipped", "last_reason": "no_trigger",
         "last_error_type": None, "counts": {"24h": 0, "7d": 2}},
        {"process_id": "sleep.deep", "status": "implemented",
         "effective": "never_run", "reason": "запусков не было",
         "last_ts": None, "last_outcome": None, "last_reason": None,
         "last_error_type": None, "counts": {"24h": 0, "7d": 0}},
        {"process_id": "goodmorning.run", "status": "disabled",
         "effective": "off", "reason": "выключен (гейт)", "last_ts": None,
         "last_outcome": None, "last_reason": None, "last_error_type": None,
         "counts": {"24h": 0, "7d": 0}},
        # данные для flow/route на «Памяти» и «Запусках»
        {"process_id": "summary.window", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 200, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 45, "7d": 300}},
        {"process_id": "summary.hybrid", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 400, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 6, "7d": 40}},
        {"process_id": "facts.extract", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 300, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 30, "7d": 210}},
        {"process_id": "retrieval.query", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 100, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 22, "7d": 150}},
        {"process_id": "direct.reply", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 90, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 8, "7d": 60}},
        {"process_id": "intent.initiative", "status": "implemented",
         "effective": "no_conditions", "reason": "условий не было",
         "last_ts": None, "last_outcome": None, "last_reason": None,
         "last_error_type": None, "counts": {"24h": 0, "7d": 4}},
        {"process_id": "episodes.build", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 500, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 5, "7d": 30}},
        {"process_id": "lore.compile", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 550, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 4, "7d": 25}},
        {"process_id": "summary.publish", "status": "implemented",
         "effective": "error", "reason": "последний запуск с ошибкой",
         "last_ts": NOW - 700, "last_outcome": "failed",
         "last_reason": "send_failed", "last_error_type": "TelegramError",
         "counts": {"24h": 1, "7d": 2}},
        {"process_id": "sleep.dream", "status": "implemented",
         "effective": "working", "reason": "работает, есть результат",
         "last_ts": NOW - 40000, "last_outcome": "success", "last_reason": None,
         "last_error_type": None, "counts": {"24h": 1, "7d": 2}},
    ],
}

# ── /api/analytics/viz/activity: heatmap (день × час) ──
VIZ_ACTIVITY = {
    "available": True, "days": 14, "generated_at": NOW,
    "telemetry_enabled": True, "timezone": "server-local",
    "total": 57, "errors_total": 3,
    "first_ts": NOW - 3 * 86400, "last_ts": NOW - 120,
    "buckets": [
        {"d": _day(0), "h": 9, "c": 40, "errs": 1},
        {"d": _day(0), "h": 23, "c": 14, "errs": 0},
        {"d": _day(1), "h": 9, "c": 3, "errs": 2},
    ],
}
VIZ_ACTIVITY_OFF = {
    "available": False, "days": 14, "generated_at": NOW,
    "telemetry_enabled": False,
    "reason": "telemetry_off (MCA_OBSERVABILITY/TELEMETRY_STORE_ENABLED=OFF)",
}

# ── /api/analytics/pipeline/runs/latest: waterfall (F4 nodes) ──
PIPELINE_LATEST = {
    "run": {
        "run_id": "run-w3a-1", "chat_id": -1001234567890,
        "mode": "auto", "status": "done", "duration_ms": 9000,
        "health_label": "здоров", "fallback": None,
        "capacity": {"required_input_tokens": 4200,
                     "reserved_output_tokens": 900},
        "nodes": [
            {"key": "source", "label": "Источник", "branch": "text",
             "state": "success", "latency_ms": 1200},
            {"key": "l1", "label": "L1 · Карта", "branch": "text",
             "state": "success", "latency_ms": 3000},
            {"key": "l2", "label": "L2 · Писатель", "branch": "text",
             "state": "failed", "latency_ms": 800},
            {"key": "publish", "label": "Публикация", "branch": "text",
             "state": "success", "latency_ms": None},
        ],
    },
    "generated_at": NOW,
}

# ── /api/factcheck/temporal/runs: источник дат фактчека ──
TEMPORAL_RUNS = {"runs": [
    {"run_id": "tf-1", "created_at": NOW, "chat_id": -1001234567890,
     "assessment_mode": "current", "factual_verdict": "supported",
     "temporal_status": "current", "date_source": "telegram_origin",
     "original_published_at": NOW - 20 * 86400,
     "repost_received_at": NOW - 19 * 86400, "fallback_used": False,
     "cache_hit": False},
    {"run_id": "tf-2", "created_at": NOW - 3600, "chat_id": -1001234567890,
     "assessment_mode": "historical", "factual_verdict": "mixed",
     "temporal_status": "historical", "date_source": "unknown",
     "original_published_at": None, "repost_received_at": None,
     "fallback_used": False, "cache_hit": True},
]}

# ── /api/config/overrides-map (D07): popover чата ──
OVERRIDES_MAP = {"items": [
    {"key": "flags.summary_enabled", "chat_id": -1001234567890,
     "chat_title": "Audit Chat", "value": False, "source": "chat",
     "access": "global_admin", "is_dm": False},
    {"key": "memory.infinite_retention", "chat_id": -1001234567890,
     "chat_title": "Audit Chat", "value": True, "source": "chat",
     "access": "global_admin", "is_dm": False},
]}

OVERSIGHT_SUMMARY = {
    "chats": [
        {"chat_id": -1001234567890, "title": "Audit Chat", "is_active": True,
         "last_active_ts": NOW - 300, "gates_opt_in": False,
         "key_status": "own", "key_last4": "ab12", "allow_global": True,
         "admins_count": 2, "permsoc": True,
         "heavy": {"сон": True, "ностальгия": False, "авто-лор": True},
         "limits": None, "budget": None},
    ],
    "totals": {"chats": 1},
    "mca_metrics": {"available": False,
                    "incidents": {"available": False}},
}

# ── /api/oversight/runs: реальные поля строки запуска (human-метка) ──
OVERSIGHT_RUNS = {"available": True, "enabled": True, "runs": [
    {"pipeline_run_id": "run-w3a-1", "pipeline_type": "summary",
     "component": "summary", "status": "succeeded", "stalled": False,
     "stages_ok": 5, "stages_failed": 0, "events_total": 9,
     "pipeline_version": "1", "updated_ts": NOW - 60,
     "chat_id": -1001234567890},
], "next_cursor": None}

# ── /api/stories* (B08): таблица + карточки ready/insufficient ──
STORY_READY = {
    "story_id": "st-ready", "chat_id": -1001234567890,
    "title": "Спор о сроках ремонта", "summary": "Участники обсуждали сроки.",
    "content_status": "ready",
    "display_title": "Спор о сроках ремонта",
    "display_summary": "Участники обсуждали сроки ремонта и не сошлись.",
    "participants": ["7", "9", "3", "4", "5", "6", "8"],
    "primary_participants": ["7", "9", "3", "4", "5"],
    "others_count": 2,
    "claims_count": 2, "event_start_ts": NOW - 20 * 86400,
    "event_end_ts": NOW - 20 * 86400 + 3600, "discovered_at": NOW - 18 * 86400,
    "updated_at": NOW - 3600, "rebuilt_at": NOW - 3600,
    "outcome": "", "state": "open", "verification": "unknown",
    "excluded_from_retrieval": False, "expected_version": 3,
    "num_episodes": 2, "has_overrides": False,
}
STORY_INSUF = {
    "story_id": "st-insuf", "chat_id": -1001234567890,
    "title": "", "summary": "",
    "content_status": "insufficient_sources",
    "display_title": "Не удалось восстановить сюжет",
    "display_summary": "Не удалось восстановить сюжет: нет источников",
    "participants": [], "primary_participants": [], "others_count": 0,
    "claims_count": 0, "event_start_ts": None, "event_end_ts": None,
    "discovered_at": None, "updated_at": NOW - 7200,
    "rebuilt_at": NOW - 7200, "outcome": "", "state": "open",
    "verification": "unknown", "excluded_from_retrieval": False,
    "expected_version": 1, "num_episodes": 1, "has_overrides": False,
}
STORIES_TABLE = {"enabled": True, "state": "ok", "chat_id": -1001234567890,
                 "manage_enabled": True,
                 "items": [STORY_READY, STORY_INSUF],
                 "next_cursor": None, "has_more": False}
STORIES_SUMMARY = {"enabled": True, "state": "ok", "chat_id": -1001234567890,
                   "counters": {"total": 2, "new_window": 1,
                                "extended_window": 0,
                                "contradictions_window": 0,
                                "pending_verification": 1,
                                "excluded_from_retrieval": 0},
                   "window_hours": 24, "progress": {},
                   "generated_at": NOW}
STORIES_FEED = {"enabled": True, "state": "ok",
                "items": [], "has_more": False, "next_cursor": None}


def _story_card_ready() -> dict:
    return {
        "enabled": True, "state": "ok", "chat_id": -1001234567890,
        "manage_enabled": True,
        "story": {
            "story_id": "st-ready", "chat_id": -1001234567890,
            "title": "Спор о сроках ремонта",
            "summary": "Участники обсуждали сроки ремонта и не сошлись.",
            "content_status": "ready",
            "display_title": "Спор о сроках ремонта",
            "display_summary": "Участники обсуждали сроки ремонта и не сошлись.",
            "participants": ["7", "9", "3", "4", "5", "6", "8"],
            "primary_participants": ["7", "9", "3", "4", "5"],
            "others_count": 2,
            "display_names": {"6": "Аня", "7": "Олег", "9": "Мария",
                              "8": "Борис"},
            "claims": [
                {"text": "Олег назвал срок «две недели».",
                 "refs": ["-1001234567890:tg:10"]},
                {"text": "Мария ответила, что раньше было «месяц».",
                 "refs": ["-1001234567890:tg:11"]},
            ],
            "event_start_ts": NOW - 20 * 86400,
            "event_end_ts": NOW - 20 * 86400 + 3600,
            "discovered_at": NOW - 18 * 86400,
            "rebuilt_at": NOW - 3600, "updated_at": NOW - 3600,
            "outcome": "", "state": "open", "verification": "unknown",
            "open_questions": ["Кто в итоге отвечал за сроки?"],
            "excluded_from_retrieval": False, "expected_version": 3,
            "override_title": None, "override_summary": None,
            "override_outcome": None, "override_state": None,
            "override_open_questions": None,
        },
        "timeline": [
            {"ts": NOW - 20 * 86400, "episode_id": "ep-1",
             "text": "Олег назвал срок «две недели».",
             "refs": [{"message_key": "-1001234567890:tg:10",
                       "tg_message_id": 10,
                       "url": "https://t.me/c/1234567890/10"}]},
            {"ts": NOW - 20 * 86400 + 1800, "episode_id": "ep-1",
             "text": "Мария ответила, что раньше было «месяц».",
             "refs": [{"message_key": "-1001234567890:tg:11",
                       "tg_message_id": 11, "url": None}]},
        ],
        "episodes": [
            {"episode_id": "ep-1", "title": "Обсуждение сроков",
             "summary": "Два сообщения о сроках.",
             "participants": ["7", "9"], "primary_participants": ["7", "9"],
             "others_count": 0, "display_names": {"7": "Олег", "9": "Мария"},
             "claims": [], "event_start_ts": NOW - 20 * 86400,
             "event_end_ts": None, "discovered_at": NOW - 18 * 86400,
             "updated_at": NOW - 3600, "rebuilt_at": NOW - 3600,
             "outcome": "", "open_questions": [], "message_keys": 2,
             "recheck_pending": False,
             "content_status": "ready",
             "display_title": "Обсуждение сроков",
             "display_summary": "Два сообщения о сроках."},
        ],
        "versions": [],
        "contradictions": [],
        "redirected": False, "redirect_target": None,
        "original": {"state": "available",
                     "links": [{"tg_message_id": 10,
                                "url": "https://t.me/c/1234567890/10"}],
                     "message_keys": 2},
        "related_beliefs": {"available": False,
                            "reason": "direct_links_absent", "items": []},
    }


def _story_card_insuf() -> dict:
    card = {
        "enabled": True, "state": "ok", "chat_id": -1001234567890,
        "manage_enabled": True,
        "story": {
            "story_id": "st-insuf", "chat_id": -1001234567890,
            "title": "", "summary": "",
            "content_status": "insufficient_sources",
            "display_title": "Не удалось восстановить сюжет",
            "display_summary": "Не удалось восстановить сюжет: нет источников",
            "participants": [], "primary_participants": [], "others_count": 0,
            "display_names": {},
            "claims": [],
            "event_start_ts": None, "event_end_ts": None,
            "discovered_at": None, "rebuilt_at": NOW - 7200,
            "updated_at": NOW - 7200,
            "outcome": "", "state": "open", "verification": "unknown",
            "open_questions": [],
            "excluded_from_retrieval": False, "expected_version": 1,
            "override_title": None, "override_summary": None,
            "override_outcome": None, "override_state": None,
            "override_open_questions": None,
        },
        "timeline": [],
        "episodes": [],
        "versions": [],
        "contradictions": [],
        "redirected": False, "redirect_target": None,
        "original": {"state": "unavailable", "links": [],
                     "message_keys": 0},
        "related_beliefs": {"available": False,
                            "reason": "direct_links_absent", "items": []},
    }
    return card


COGNITION = {
    "dream": {"running": False, "enabled": True, "active": False,
              "last_run_at": NOW - 7200, "next_wake_at": NOW + 3600,
              "budget": {"tokens_today": 900, "tokens_limit": 2000}},
    "deep_sleep": {"running": False, "enabled": True, "active": False,
                   "last_run_at": None, "next_run_at": NOW + 7200},
    "lore": {"last_inject_at": NOW - 500},
    "stats": {"facts": 1200, "beliefs": 40, "protected_facts": 15,
              "paradigms": 4, "graph_nodes": 900, "graph_edges": 2100,
              "relation_types": 6, "memes": 7},
    "timeline": [],
    "generated_at": NOW,
}


def _start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _heat_off_ctx(route_state: dict) -> None:
    route_state["activity_off"] = True


def main() -> int:
    httpd = _start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    os.makedirs(SHOTS, exist_ok=True)
    config_payload = copy.deepcopy(M.CONFIG_STUB)
    state = {"activity_off": False}

    def _api_handler(route):
        req = route.request
        url = req.url.split("?")[0]
        if url.endswith("/api/analytics/viz/activity"):
            body = VIZ_ACTIVITY_OFF if state["activity_off"] else VIZ_ACTIVITY
        elif url.endswith("/api/analytics/viz/process-activity"):
            body = PROCESS_ACTIVITY
        elif url.endswith("/api/analytics/pipeline/runs/latest"):
            body = PIPELINE_LATEST
        elif url.endswith("/api/factcheck/temporal/runs"):
            body = TEMPORAL_RUNS
        elif url.endswith("/api/config/overrides-map"):
            body = OVERRIDES_MAP
        elif url.endswith("/api/oversight/summary"):
            body = OVERSIGHT_SUMMARY
        elif url.endswith("/api/oversight/runs"):
            body = OVERSIGHT_RUNS
        elif url.endswith("/api/memory/cognition/status"):
            body = COGNITION
        elif url.endswith("/api/memory/stats"):
            body = COGNITION["stats"]
        elif url.endswith("/api/stories/summary"):
            body = STORIES_SUMMARY
        elif url.endswith("/api/stories/feed"):
            body = STORIES_FEED
        elif url.endswith("/api/stories/st-ready"):
            body = _story_card_ready()
        elif url.endswith("/api/stories/st-insuf"):
            body = _story_card_insuf()
        elif url.endswith("/api/stories"):
            body = STORIES_TABLE
        elif url.endswith("/api/oversight/processes"):
            body = PROCESSES
        else:
            body = M._stub_for(req.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body, ensure_ascii=False))

    from playwright.sync_api import sync_playwright
    result = {"console_errors": [], "checks": {}, "screenshots": []}
    shots = result["screenshots"]

    def shot(page, name, full=True):
        path = os.path.join(SHOTS, name)
        page.screenshot(path=path, full_page=full)
        shots.append(name)

    def shot_el(page, locator, name):
        path = os.path.join(SHOTS, name)
        locator.screenshot(path=path)
        shots.append(name)

    def no_h_overflow(page) -> bool:
        return page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 1")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  reduced_motion="reduce")
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        page.goto(base, wait_until="load")
        page.wait_for_timeout(2000)
        checks = result["checks"]

        # ═══ Обзор: heatmap + popover overrides ═══
        page.evaluate("location.hash = '#/oversight'")
        page.wait_for_timeout(1500)
        checks["heatmap_rendered"] = page.locator(
            "[data-viz-heatmap] .viz-heat__row").count() == 14
        cells = page.locator("[data-viz-heatmap] .viz-heat__cell").count()
        checks["heatmap_cells_336"] = cells == 14 * 24
        checks["heatmap_max_level"] = page.locator(
            ".viz-heat__cell--l4").count() >= 1
        checks["heatmap_err_marker"] = page.locator(
            ".viz-heat__cell--err").count() >= 1
        checks["heatmap_total_honest"] = page.locator(
            "[data-viz-heatmap]").inner_text().find("всего событий: 57") >= 0
        # popover overrides: счётчик «2», открытие показывает ключи.
        ov_btn = page.locator("[data-viz-ovcell] button").first
        checks["ovpop_badge_2"] = ov_btn.inner_text().strip() == "2"
        ov_btn.click()
        page.wait_for_timeout(300)
        checks["ovpop_open"] = page.locator("[data-viz-ovpop]").is_visible()
        checks["ovpop_key_shown"] = page.locator(
            "[data-viz-ovpop]").inner_text().find("flags.summary_enabled") >= 0
        shot(page, "w3a_overview_desktop_1440.png")

        # ═══ Процессы: U05.1 (человеческое имя/эффективный статус/Детали) ═══
        page.evaluate(
            "location.hash = '#/oversight?view=processes'")
        page.wait_for_timeout(1500)
        procs_text = page.locator('[data-mca17c="processes"]').inner_text()
        checks["proc_human_name"] = procs_text.find("Приём сообщений чата") >= 0
        checks["proc_eff_working"] = procs_text.find(
            "работает с результатом") >= 0
        checks["proc_eff_error"] = procs_text.find("ошибка") >= 0
        checks["proc_eff_nocond"] = procs_text.find("не было условий") >= 0
        checks["proc_eff_never"] = procs_text.find("не запускался") >= 0
        checks["proc_eff_off"] = procs_text.find("выключен") >= 0
        checks["proc_last_action"] = procs_text.find(
            "последнее действие:") >= 0
        checks["proc_never_reason"] = procs_text.find(
            "запусков не было") >= 0
        # developer-ID по умолчанию скрыт (закрытые «Детали»).
        details_loc = page.locator("details[data-viz-details]")
        checks["proc_details_present"] = details_loc.count() >= 5
        checks["proc_pid_hidden_default"] = page.locator(
            '[data-mca17c="processes"] details[data-viz-details] code'
        ).first.is_visible() is False
        # раскрываем «Детали» конкретного процесса → process_id виден.
        det = page.locator(
            'details[data-viz-details="ingestion.live"]')
        det.locator("summary").click()
        page.wait_for_timeout(400)
        checks["proc_pid_visible_after"] = det.locator(
            "code").first.is_visible()
        checks["proc_pid_text"] = det.locator(
            "code").first.inner_text() == "ingestion.live"
        # карта зависимостей: раскрытие → слои и ребро.
        page.locator("[data-viz-deps] button").first.click()
        page.wait_for_timeout(300)
        checks["deps_layers"] = page.locator(".viz-deps__col").count() == 4
        checks["deps_edge_text"] = page.locator(
            "[data-viz-deps]").inner_text().find("smart_messages") >= 0
        shot(page, "w3a_processes_desktop_1440.png")

        # ═══ Запуски: маршрут обработки + human-метка прогона ═══
        page.evaluate("location.hash = '#/oversight?view=runs'")
        page.wait_for_timeout(1500)
        route_text = page.locator("[data-viz-route]").inner_text()
        checks["route_root_100"] = route_text.find(
            "Вход: принятые сообщения") >= 0 \
            and route_text.find("100") >= 0
        checks["route_branches"] = page.locator(
            ".viz-route__branch").count() == 6
        checks["route_zero_honest"] = route_text.find("инициатива") >= 0
        checks["runs_human_label"] = page.locator(
            '[data-mca17c="runs-list"]').inner_text().find("Сводка") >= 0
        shot(page, "w3a_runs_desktop_1440.png")

        # ═══ Память и интеллект: цикл памяти + timeline дат фактчека ═══
        page.evaluate("location.hash = '#/oversight?tab=memory'")
        page.wait_for_timeout(1800)
        flow_text = page.locator("[data-viz-flow]").inner_text()
        checks["flow_rendered"] = flow_text.find("Приём сообщений") >= 0 \
            and flow_text.find("100") >= 0
        checks["flow_nodes_9"] = page.locator(
            ".viz-flow__node").count() == 9
        checks["flow_caption_stats"] = flow_text.find(
            "в графе: 1200 фактов") >= 0
        fd = page.locator("[data-viz-factdates]")
        checks["factdates_block"] = fd.count() == 1
        fd.locator("summary").click()
        page.wait_for_timeout(300)
        fd_text = fd.inner_text()
        checks["factdates_source_label"] = fd_text.find(
            "дата из источника (пересылка): 1") >= 0
        checks["factdates_unknown_honest"] = fd_text.find(
            "неизвестна (честно): 1") >= 0
        checks["factdates_rows"] = page.locator(
            ".viz-factdates__row").count() == 2
        shot(page, "w3a_memory_desktop_1440.png")

        # ═══ Модели и расходы: waterfall ═══
        page.evaluate("location.hash = '#/oversight?tab=models'")
        page.wait_for_timeout(1800)
        wf_text = page.locator("[data-viz-waterfall]").inner_text()
        checks["wf_total"] = wf_text.find("9 с") >= 0
        checks["wf_labels"] = wf_text.find("L1 · Карта") >= 0 \
            and wf_text.find("L2 · Писатель") >= 0
        checks["wf_bars_3"] = page.locator(".viz-wf__bar").count() == 3
        checks["wf_err_bar"] = page.locator(
            ".viz-wf__bar--err").count() == 1
        checks["wf_capacity"] = wf_text.find("вход") >= 0
        shot(page, "w3a_models_desktop_1440.png")

        # ═══ B08: карточки историй (ready + insufficient) ═══
        page.evaluate("location.hash = '#/memory/rag'")
        page.wait_for_timeout(1800)
        table = page.locator("[data-stories-table]")
        checks["stories_table_rows"] = page.locator(
            "[data-stories-table] tbody tr").count() == 2
        checks["stories_insuf_badge"] = table.inner_text().find(
            "нет источников") >= 0
        # ready-карточка
        page.locator("[data-stories-table] tbody tr").first.click()
        page.wait_for_timeout(800)
        card = page.locator("[data-story-card]")
        checks["card_ready_open"] = card.count() == 1
        card_text = card.inner_text()
        checks["card_ready_title"] = card_text.find(
            "Спор о сроках ремонта") >= 0
        checks["card_synopsis"] = card_text.find(
            "Участники обсуждали сроки") >= 0
        checks["card_dates_three"] = card_text.find("События:") >= 0 \
            and card_text.find("Обнаружена:") >= 0 \
            and card_text.find("Пересобрана:") >= 0
        checks["card_questions"] = card_text.find(
            "Кто в итоге отвечал за сроки?") >= 0
        checks["card_participants_5"] = card_text.find("Олег") >= 0
        more_btn = page.locator("[data-story-participants] button")
        checks["card_more_btn"] = more_btn.count() == 1 \
            and more_btn.inner_text().find("ещё 2") >= 0
        more_btn.click()
        page.wait_for_timeout(600)
        parts_text = page.locator(
            "[data-story-participants]").inner_text()
        checks["card_more_expand"] = bool(parts_text)
        checks["card_more_names"] = parts_text.find("Аня") >= 0 \
            and parts_text.find("Борис") >= 0
        # раскрываемая хронология + refs по правам
        page.locator("[data-story-timeline-toggle]").click()
        page.wait_for_timeout(300)
        checks["card_timeline_items"] = page.locator(
            ".story-card__tl-item").count() == 2
        href = page.locator(".story-card__tl-refs a").first
        checks["card_ref_tme"] = (href.get_attribute("href")
                                  == "https://t.me/c/1234567890/10")
        checks["card_ref_archive"] = page.locator(
            ".story-card__tl-refs").nth(1).inner_text().find(
            "в архиве") >= 0
        shot(page, "w3a_story_ready_desktop_1440.png")
        shot_el(page, page.locator("[data-story-card]"),
                "w3a_story_ready_card_closeup.png")
        # insufficient-карточка: честно, без success-раскраски
        page.locator("[data-stories-table] tbody tr").nth(1).click()
        page.wait_for_timeout(800)
        card2 = page.locator("[data-story-card]")
        cls = (card2.get_attribute("class") or "")
        checks["card_insuf_class"] = "story-card--insufficient" in cls
        c2 = card2.inner_text()
        checks["card_insuf_title"] = c2.find(
            "Не удалось восстановить сюжет") >= 0
        checks["card_insuf_msg"] = c2.find("нет источников") >= 0
        checks["card_insuf_dates"] = c2.count("нет данных") >= 2 \
            and c2.find("1970") < 0
        shot(page, "w3a_story_insufficient_desktop_1440.png")
        shot_el(page, card2, "w3a_story_insufficient_card_closeup.png")

        checks["desktop_1440_no_overflow"] = no_h_overflow(page)

        # ═══ Мобильные/landscape (V05) ═══
        for label, w, h in (("mobile_320", 320, 700),
                            ("mobile_390", 390, 844),
                            ("landscape_667x375", 667, 375)):
            mctx = browser.new_context(
                viewport={"width": w, "height": h}, reduced_motion="reduce")
            mctx.add_init_script(M.TMA_STUB)
            mctx.route("**/api/**", _api_handler)
            mp = mctx.new_page()
            mp.on("pageerror", lambda e: result["console_errors"].append(
                "pageerror:" + str(e)[:200]))
            mp.goto(base, wait_until="load")
            mp.wait_for_timeout(1800)
            for tab in ("#/oversight", "#/oversight?view=processes",
                        "#/memory/rag"):
                mp.evaluate("location.hash = '%s'" % tab)
                mp.wait_for_timeout(1200)
                checks["no_overflow_%s_%s" % (
                    label, tab.replace('#/', '').replace('?', '_')
                    or "root")] = no_h_overflow(mp)
            mp.evaluate("location.hash = '#/oversight?tab=overview'")
            mp.wait_for_timeout(1200)
            shot(mp, "w3a_overview_%s.png" % label)
            mp.evaluate("location.hash = '#/oversight?view=processes'")
            mp.wait_for_timeout(1200)
            shot(mp, "w3a_processes_%s.png" % label)
            mp.evaluate("location.hash = '#/memory/rag'")
            mp.wait_for_timeout(1400)
            mp.locator("[data-stories-table] tbody tr").first.click()
            mp.wait_for_timeout(800)
            mp.locator("[data-story-timeline-toggle]").click()
            mp.wait_for_timeout(300)
            checks["story_card_mobile_visible_%s" % label] = \
                mp.locator("[data-story-card]").is_visible()
            checks["story_card_width_%s" % label] = mp.evaluate(
                "document.querySelector('[data-story-card]')"
                ".getBoundingClientRect().width <= window.innerWidth + 2")
            shot(mp, "w3a_story_card_%s.png" % label)
            shot_el(mp, mp.locator("[data-story-card]"),
                    "w3a_story_card_closeup_%s.png" % label)
            mctx.close()

        # ═══ Честное пустое состояние heatmap (телеметрия OFF) ═══
        state["activity_off"] = True
        octx = browser.new_context(viewport={"width": 1440, "height": 900},
                                   reduced_motion="reduce")
        octx.add_init_script(M.TMA_STUB)
        octx.route("**/api/**", _api_handler)
        op = octx.new_page()
        op.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror:" + str(e)[:200]))
        op.goto(base, wait_until="load")
        op.wait_for_timeout(1500)
        op.evaluate("location.hash = '#/oversight'")
        op.wait_for_timeout(1500)
        hm = op.locator("[data-viz-heatmap]").inner_text()
        checks["heatmap_off_honest"] = hm.find("telemetry_off") >= 0
        checks["heatmap_off_no_cells"] = op.locator(
            "[data-viz-heatmap] .viz-heat__cell").count() == 0
        octx.close()

        browser.close()

    result["console_errors"] = [e for e in result["console_errors"]
                                if "favicon" not in e]
    ok_checks = [k for k, v in checks.items() if v]
    fail_checks = {k: v for k, v in checks.items() if not v}
    out = {"ok": not fail_checks and not result["console_errors"],
           "passed": len(ok_checks), "failed": fail_checks,
           "console_errors": result["console_errors"][:10],
           "screenshots": result["screenshots"]}
    out_path = os.path.join(
        os.environ.get("OPENCODE_WORKFLOW_SCRATCH",
                       os.path.join(REPO, "tools")),
        "_ui_w3_analytics_e2e.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    print(json.dumps(out, ensure_ascii=False)[:2400])
    httpd.shutdown()
    if out["ok"]:
        print("W3-ANALYTICS-E2E-OK: %d checks, %d screenshots"
              % (len(ok_checks), len(result["screenshots"])))
        return 0
    print("W3-ANALYTICS-E2E-FAIL: %s" % fail_checks)
    return 1


if __name__ == "__main__":
    sys.exit(main())
