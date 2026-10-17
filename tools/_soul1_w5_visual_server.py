# -*- coding: utf-8 -*-
"""W5 visual server: РЕАЛЬНЫЙ web/index.html + стабы данных Статуса.

Отдаёт настоящий `web/**` (index.html/app.js/static) и подставляет
JSON-стабы `/api/*`, чтобы панель «Воронка наблюдателя» отрендерилась с
ПОЛНЫМ набором W5-полей (предупреждение health≠outcome, причины, ворота,
решения/отказы, доставки с message_id и ревизиями, мягкие цели, кнопка
проверки). Ничего в репозитории не меняется: сервер только читает файлы.

Запуск:  py -3 tools/_soul1_w5_visual_server.py [port]
Стоп:    Ctrl+C.
"""
import importlib.util
import json
import os
import sys
from http.server import ThreadingHTTPServer

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

_spec = importlib.util.spec_from_file_location(
    "ui_round1025_matrix", os.path.join(REPO, "tools",
                                       "ui_round1025_matrix.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else (M.PORT + 101)
CHAT_ID = -1001234567890

STATUS_STUB = dict(M.STATUS_STUB)
STATUS_STUB["intents"] = {
    "enabled": True,
    "state": "ok",
    "active": 2,
    "top": [],
    "last_action": None,
    "module": {"state_label": "Heartbeat работает", "top_block_reason": "",
               "last_decision": None, "last_skip": None, "next_due": None},
}

FUNNELS_STUB = {
    "available": True,
    "now_ts": 1792230000,
    "chat_scoped_events": True,
    "initiative": {
        "available": True,
        "job": {"status": "completed", "reason_code": None,
                "created_at": 1792220000, "updated_at": 1792229400,
                "finished_at": 1792229400,
                "counters": {"passes": 288, "observed": 2140, "eligible": 940,
                             "evals": 96, "opportunities": 7,
                             "silent_decisions": 5, "react_decisions": 1,
                             "intents_created": 2, "sent": 1,
                             "writer_unavailable": 0, "eval_unavailable": 3,
                             "errors": 0,
                             "eval_skips": {"min_gap": 12,
                                            "not_enough_messages": 40,
                                            "context_duplicate": 9}}},
        "liveness": {"ts": 1792229700, "status": "completed",
                     "observed": 2140, "opportunities": 7},
        "events": {"24h": {"initiative_observer_scan": 288,
                           "initiative_opportunity": 7,
                           "initiative_sent": 1},
                   "7d": {"initiative_observer_scan": 2010,
                          "initiative_opportunity": 41,
                          "initiative_writer_generated": 12,
                          "initiative_recheck_passed": 8,
                          "initiative_sent": 6}},
    },
    "experience": {"available": False},
}

VITALITY_STUB = {
    "available": True, "now_ts": 1792230000, "hours": 24,
    "chat_id": CHAT_ID, "chat_scoped": True,
    "scope": {"master": True, "chat_enabled": True},
    "funnel": FUNNELS_STUB["initiative"],
    "windows": {"24h": {}},
    "window": {"hours": 24, "coverage": "full",
               "coverage_note": "история прогонов наблюдателя дотягивается до "
                                "начала окна",
               "scans": 288, "observed": 2140, "eligible": 940, "evals": 96,
               "opportunities": 7,
               "opportunities_by_kind": {"humor": 3, "dispute": 2},
               "decisions": {"say": 2, "react": 1, "silent": 4,
                             "cancelled": 1, "other": 0},
               "silence_by_reason": [
                   {"reason_code": "min_gap",
                    "label": "пауза после последней реплики бота",
                    "count": 12},
                   {"reason_code": "recent_reply",
                    "label": "бот недавно уже отвечал", "count": 4}],
               "intents_created": 2, "writer_generated": 3,
               "writer_unavailable": 0, "send_attempts": 2, "delivered": 1,
               "delivered_ledger": 1, "delivered_events": 1,
               "delivered_counters": 1, "refusals": 1, "duplicates": 0,
               "eval_skips": {"min_gap": 12, "not_enough_messages": 40},
               "errors": 0, "diagnostics": 0,
               "latency_seconds": {"p50": 41, "max": 88, "samples": 1},
               "last": {"scan_ts": 1792229700, "opportunity_ts": 1792228800,
                        "decision_ts": 1792228100, "delivered_ts": 1792227000,
                        "send_attempt_ts": 0}},
    "activity": {
        "state": "opportunities_no_messages", "level": "warn",
        "title": "Возможности есть, сообщений нет",
        "warning": "За окно найдено возможностей: 7, решений молчанием: 4, "
                   "доставлено: 0. Воронка жива, но инициативных сообщений не "
                   "было.",
        "recommendation": "Главная причина: пауза после последней реплики "
                          "бота (12). Проверить плечи writer/recheck и причины "
                          "решений ниже.",
        "reasons": [{"reason_code": "min_gap",
                     "label": "пауза после последней реплики бота", "count": 12},
                    {"reason_code": "not_enough_messages",
                     "label": "в чате пока мало новых сообщений", "count": 40}],
        "live_messages": 2450,
        "thresholds": {"live_messages_busy": 2000, "silent_streak": 3},
        "health": {"heartbeat_ok": True, "last_tick_ts": 1792229700,
                   "last_tick_status": "completed", "jobs_processed": 288,
                   "note": "heartbeat≠outcome: тики и прогоны не являются "
                           "отправкой"},
        "counters": {"scans": 288, "observed": 2140, "opportunities": 7,
                     "delivered": 0, "silent": 4},
        "silent_streak": 4},
    "gates": {
        "blocked_now": True, "blocked_count": 2, "warn_count": 1,
        "items": [
            {"gate": "master", "status": "pass", "reason_code": "",
             "label": "Наблюдатель инициативы включён", "value": None,
             "limit": None, "unit": "none"},
            {"gate": "chat_kind", "status": "pass", "reason_code": "",
             "label": "Групповой чат", "value": None, "limit": None,
             "unit": "none"},
            {"gate": "chat_scope", "status": "pass", "reason_code": "",
             "label": "Инициатива разрешена в этом чате", "value": None,
             "limit": None, "unit": "none"},
            {"gate": "live_context", "status": "pass", "reason_code": "",
             "label": "Живых сообщений за 24ч: 2450", "value": 2450,
             "limit": 1, "unit": "count"},
            {"gate": "pending", "status": "pass", "reason_code": "",
             "label": "Накоплено сообщений: 14 из 8", "value": 14, "limit": 8,
             "unit": "count"},
            {"gate": "min_gap", "status": "block", "reason_code": "min_gap",
             "label": "С последней реплики бота: 420 с (пауза 7200 с)",
             "value": 420, "limit": 7200, "unit": "s"},
            {"gate": "eval_budget", "status": "block",
             "reason_code": "eval_budget",
             "label": "Оценок израсходовано сегодня: 12 из 12", "value": 12,
             "limit": 12, "unit": "count"},
            {"gate": "subscription", "status": "n/a", "reason_code": "",
             "label": "Права бота на отправку проверяются при отправке",
             "value": None, "limit": None, "unit": "none"}],
        "effective": {"profile": "normal", "min_gap_seconds": 7200,
                      "max_replies_per_day": 6,
                      "eval_min_interval_seconds": 1800,
                      "eval_min_messages": 8,
                      "eval_llm_budget_per_day": 12,
                      "max_replies_per_topic": 1, "day_window_seconds": 86400},
        "soft_targets": {"replies_per_day": 6,
                         "observation_interval_seconds": 1800,
                         "active": True,
                         "bounds": "мягкая цель влияет только на паузу между "
                                   "инициативами и на частоту проверок окна; "
                                   "дневной лимит, дедуп контекста и тем, "
                                   "бюджет оценок, recheck и право промолчать "
                                   "не отключаются",
                         "floors": {"observation_interval_seconds": 600,
                                    "eval_min_messages": 4,
                                    "min_gap_seconds": 1800}},
        "easing": {"observation": True, "min_gap": True},
        "day_goal": {"target": 6, "sent_in_window": 1, "behind": True},
        "state": {"pending": 14, "last_eval_age_seconds": 1900,
                  "sent_in_window": 1, "eval_used_today": 12,
                  "last_bot_output_age_seconds": 420,
                  "cursor_lag_messages": 2, "live_messages_24h": 2450}},
    "decisions": [
        {"ts": 1792228100, "action": "silent", "outcome": "silent",
         "reason_code": "recent_reply",
         "reason_label": "бот недавно уже отвечал", "intent_id": "",
         "stage": "new_message"},
        {"ts": 1792227900, "action": "react", "outcome": "success",
         "reason_code": "initiative_sent",
         "reason_label": "инициативное сообщение доставлено", "intent_id": "i1",
         "stage": "new_message"}],
    "refusals": [
        {"ts": 1792227800, "action": "say", "outcome": "cancelled",
         "reason_code": "intent_closed",
         "reason_label": "намерение закрылось до отправки", "intent_id": "i2",
         "stage": "new_message"}],
    "sends": [
        {"ts": 1792227000, "message_id": 987654, "correlation_id": "corr-1",
         "chars": 42, "output_kind": "initiative_reply",
         "delivery_status": "delivered", "core_revision": "8f3ac1b2e4d5",
         "style_policy_revision": "77ab90cd12ef",
         "identity_revision": "1c2d3e4f5a6b", "manifest_id": "mf-9f8e7d",
         "composer": "on", "ledger_output_id": 501}],
}

CHECK_STUB = {
    "available": True, "chat_id": CHAT_ID, "hours": 24, "published": False,
    "publish_mode": "mock", "publish_disabled_reason": "publish_axis_off",
    "trace": [
        {"stage": "gates", "status": "blocked", "reason_code": "eval_budget",
         "label": "Сейчас мешает: Оценок израсходовано сегодня: 12 из 12",
         "value": 14, "limit": None},
        {"stage": "window", "status": "ok", "reason_code": "",
         "label": "Свежих реплик в окне: 14", "value": 14, "limit": 14},
        {"stage": "evaluate", "status": "ok", "reason_code": "",
         "label": "Вердикт: humor / say", "value": None, "limit": None},
        {"stage": "decision", "status": "skipped", "reason_code": "default",
         "label": "Решение: silent (silent)", "value": None, "limit": None},
        {"stage": "writer", "status": "skipped", "reason_code": "writer_failed",
         "label": "Текст не сгенерирован", "value": None, "limit": None},
        {"stage": "mock_send", "status": "skipped", "reason_code": "default",
         "label": "Отправка не состоялась бы", "value": None, "limit": None}],
    "verdict": {"opportunity": True, "kind": "humor", "action": "say",
                "horizon": "now", "rationale": "участники шутят про поездку"},
    "decision": {"action": "silent", "reason_code": "default",
                 "reason_label": "решение молчать по умолчанию (уместность не "
                                 "подтверждена)", "status": "silent",
                 "delivery_kind": "silent"},
    "writer": {"available": True, "generated": False, "style": {}},
    "mock_send": {"attempted": False, "would_send_chars": 0, "preview": "",
                  "preview_truncated": False, "chunks": 0, "published": False},
    "llm_calls": 1, "duration_ms": 830,
}

MEMORY_STUBS = {
    "/api/memory/expired-overview": {
        "available": True, "now_ts": 1792230000, "expired_total": 0,
        "expired_searchable": 0, "needs_recheck": 0, "superseded_total": 0,
        "infinite_retention": False},
    "/api/memory/intel-funnels": FUNNELS_STUB,
    "/api/memory/initiative-vitality": VITALITY_STUB,
    "/api/memory/cognition/status": {},
    "/api/memory/health": {},
    "/api/memory/lessons": {"items": []},
    "/api/oversight/experience/funnel": {"available": False},
}


class _Handler(M._Handler):
    def _json(self, payload, code=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api_payload(self, url: str):
        """Стабы API (матрица отдаёт их через Playwright route — здесь HTTP)."""
        table = dict(M.API_STUBS)
        table.update(MEMORY_STUBS)
        for marker, payload in table.items():
            if url.endswith(marker):
                return payload
        return None

    def do_GET(self):  # noqa: N802
        url = self.path.split("?")[0]
        if url.endswith("/api/status"):
            self._json(STATUS_STUB)
            return
        payload = self._api_payload(url)
        if payload is not None:
            self._json(payload)
            return
        M._Handler.do_GET(self)

    def do_POST(self):  # noqa: N802
        url = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if url.endswith("/api/memory/initiative-check"):
            self._json(CHECK_STUB)
            return
        if url.endswith("/api/config"):
            self._json({"ok": True, "saved": 0})
            return
        self._json({"ok": True})


if __name__ == "__main__":
    print("[w5-visual] http://127.0.0.1:%d/web/index.html#/status" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), _Handler).serve_forever()
