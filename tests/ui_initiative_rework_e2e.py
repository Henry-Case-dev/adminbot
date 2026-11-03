# -*- coding: utf-8 -*-
"""P1 «Инициатива» — рекомпоновка страницы (реальный UI, не макеты).

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(прецедент `tests/ui_meme_ui_fields_e2e.py`: статический сервер + route-стабы
`/api/**`, Telegram SDK — route-mock). Ничего не пишется на сервер: POST
перехватывается стабом и возвращает управляемый ответ.

Контракт (ТЗ владельца §2.2–§2.4, 2026-11-03):

  1. ОДНА шапка страницы: «Инициатива» + область + итоговое состояние +
     ссылка в каталог; ниже ровно ПЯТЬ вкладок (Обзор, Текстовая инициатива,
     Мемы, Публикации, Диагностика).
  2. «Обзор»: две равнозначные карточки механизмов со своим effective ON/OFF,
     правом управления, последней/следующей проверкой, последней реальной
     публикацией, кулдауном, квотой, причиной ожидания и входом в настройки;
     компактная полоса «Координация отправки»; 3–5 значимых событий; тяжёлый
     журнал при первом открытии НЕ запрашивается.
  3. «Текстовая инициатива»: «Включение и условия», «Частота и лимиты»,
     «Последнее решение» (вероятность + реальный источник случайности); ни
     одной настройки мемов.
  4. «Мемы»: ON/OFF + эффективный источник, статус, квота дня, последний
     готовый/опубликованный результат, причина пропуска; две смысловые
     колонки (триггер/расписание и создание мема с pipeline из 4 шагов); ДВА
     промпта рядом с ОДНОЙ кнопкой сохранения и реальным результатом;
     «Отменить изменения» и «Вернуть наследование»; бюджет итогового
     image prompt (потолок/шаблон/доступно приколу/фактическая длина);
     компактная «Последняя попытка» без повторов «фактов этапа нет»;
     ручной `/meme` обозначен админской командой.
  5. «Публикации»: фильтры (период/тип/режим/исход/причина), одна строка на
     логическую попытку, деталь по клику с цепочкой событий (включая
     «генерация успешна, отправка отменена»), пагинация; пустая деталь не
     становится строкой.
  6. «Диагностика»: инспектор ОДНОЙ попытки, группы (условия, случайное
     решение, контекст/снапшот, этапы генерации, речевые слои, send/recheck,
     события), сжато по умолчанию, ревизии/manifest при раскрытии.
  7. Адаптив: 1536×960 / 390×844 / 360×740 — без горизонтальной прокрутки
     страницы; на мобильном прокручивается ТОЛЬКО лента вкладок.

Запуск:
  py -3 tests/ui_initiative_rework_e2e.py
  ... --shots <dir> --json <path>

TEST-LIFECYCLE: CONTRACT owner=HOTFIX-MEME-PUBLICATION-AND-INITIATIVE-UI §2
(P1: перекомпоновка страницы «Модули → Инициатива»).
"""
import argparse
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import ui_round1025_matrix as M  # noqa: E402  (базовые /api-стабы)

PORT = 8873
BASE = "http://127.0.0.1:%d" % PORT
CHAT_A = -100500
CHAT_B = -100501
NOW = 1800000300

SDK_STUB = """
try { sessionStorage.setItem('adminbot.initData',
  'user=%7B%22id%22%3A5885953495%7D&hash=audit'); } catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  platform: 'android', version: '9.0', colorScheme: 'dark', themeParams: {},
  get viewportStableHeight() { return Math.max(0, (window.innerHeight || 800) - 56); },
  isExpanded: true, isFullscreen: false,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, close() {},
  setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
  requestFullscreen() {}, exitFullscreen() {},
  disableVerticalSwipes() {}, enableClosingConfirmation() {},
  onEvent() {}, offEvent() {},
  openLink() {}, openTelegramLink() {}, showAlert() {}, showConfirm() {},
  BackButton: { isVisible: false, show() {}, hide() {}, onClick() {}, offClick() {} },
  MainButton: { show() {}, hide() {}, showProgress() {}, hideProgress() {},
                setText() {}, onClick() {}, offClick() {} },
  HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
} };
"""

STATE = {
    "post_body": None,
    "post_count": 0,
    "prompts_by_chat": {},
    "images_by_chat": {},
    "joke_source_by_chat": {},
    "image_source_by_chat": {},
    "requests": [],
    "axes_on": False,
    "post_chat": None,
}

DEFAULT_JOKE = "Придумай короткий абсурдный прикол."
DEFAULT_IMAGE = "Мем: {joke}"
#: Два разных чата — доказательство, что данные перечитываются, а не липнут.
CHAT_PROMPTS = {str(CHAT_A): "JOKE-A: прикол для чата A",
                str(CHAT_B): "JOKE-B: прикол для чата B"}


# ── стабы payload'ов ─────────────────────────────────────────────────────
def _speech():
    return {
        "composer": "on", "system_sha12": "f0c2695c31ca",
        "manifest": "62aaae1adf259de9",
        "core": "r21.848ba4c426b8", "core_detail": "compact:document_default",
        "identity": "a227bfbefc8732fb", "expression": "386f4ac001c1",
        "style_policy": "g5.6aff783e44a7", "humor": "402b6636e025",
        "technique": "literalism", "humor_status": "rendered",
        "off_axes": ["humor_library_enabled"],
        "layers": [
            {"layer": "core", "block": "core.personality.compact",
             "revision": "r21.848ba4c426b8", "chars": 900, "rendered": True,
             "skip": ""},
            {"layer": "humor", "block": "humor.craft",
             "revision": "402b6636e025", "chars": 210, "rendered": True,
             "skip": ""},
            {"layer": "few_shot", "block": "examples", "revision": "",
             "chars": 0, "rendered": False, "skip": "expression_examples_absent"},
        ],
        "skipped": {"few_shot": "expression_examples_absent"},
    }


def _attempt_rows():
    def facts(obj):
        return json.dumps(obj, ensure_ascii=False)
    base = {"job_id": "job-77", "limit_value": 400,
            "limit_source": "model_capability", "window_messages": 300}
    return [
        dict(base, attempt_id="a4", ts=NOW, stage="publish",
             outcome="published", reason_code="sent",
             detail=facts({"publish": {"manual": False, "gate": "open",
                                       "claim": {"state": "released"},
                                       "output": {"tg_message_id": 4321},
                                       "watermark": {"at_generation": 10,
                                                     "at_publish": 10}}})),
        dict(base, attempt_id="a3", ts=NOW - 5, stage="image_generation",
             outcome="passed", reason_code="",
             detail=facts({"chars": 23, "template_chars": 5,
                           "joke_chars": 6})),
        dict(base, attempt_id="a2", ts=NOW - 9, stage="joke",
             outcome="passed", reason_code="",
             detail=facts({"limit": 395, "template_chars": 5, "ceiling": 400,
                           "chars": 6, "trimmed": False, "source": "chat",
                           "placeholder": "slot", "speech": _speech()})),
        dict(base, attempt_id="a1", ts=NOW - 12, stage="summary",
             outcome="passed", reason_code="",
             detail=facts({"chars": 41, "source": "factory"})),
    ]


def _meme_settings(chat_id=None):
    chat = CHAT_A if chat_id is None else int(chat_id)
    spent = 1 if chat == CHAT_A else 0
    joke = STATE["prompts_by_chat"].get(str(chat), CHAT_PROMPTS.get(str(chat), DEFAULT_JOKE))
    image = STATE["images_by_chat"].get(str(chat), DEFAULT_IMAGE)
    joke_source = ("chat" if STATE["joke_source_by_chat"].get(str(chat), True)
                   else "factory")
    image_source = STATE["image_source_by_chat"].get(str(chat), "factory")
    return {
        "chat_id": chat, "generated_at": NOW,
        "settings": {"enabled": True, "window_messages": 300, "daily_limit": 3,
                     "cooldown_seconds": 21600, "min_messages": 8,
                     "summarizer_model": "", "quiet_hours": "",
                     "length_admin": None},
        "availability": {"available": True, "reason": "ok",
                         "initiative_enabled": True,
                         "image": {"available": True},
                         "blocks_text_initiative": False},
        "quota": {"available": True, "reason": "ok", "limit": 3, "spent": spent,
                  "remaining": 3 - spent, "timezone_name": "Europe/Moscow",
                  "next_reset": "2026-11-01T00:00:00+03:00"},
        "day": {"bucket": "2026-10-31", "timezone_name": "Europe/Moscow",
                "timezone_source": "chat",
                "next_reset": "2026-11-01T00:00:00+03:00"},
        "length_limit": {"ceiling": 400, "source": "model_capability",
                         "template_chars": 5, "joke_budget": 395,
                         "known": True, "placeholder": "slot", "candidates": []},
        "template": {"text": image,
                     "source": image_source, "placeholders": 1,
                     "valid": True, "error": ""},
        "prompts": {
            "image": {"block_id": "initiative.meme.image",
                      "text": image,
                      "source": image_source,
                      "differs_from_factory": image_source == "chat",
                      "factory_revision": "fac-img", "revision": 4,
                      "setting_key": "prompts.meme_image"},
            "joke": {"block_id": "initiative.meme.joke",
                     "text": joke,
                     "source": joke_source,
                     "differs_from_factory": joke_source == "chat",
                     "factory_revision": "fac-joke",
                     "revision": 2 if joke_source == "chat" else 1,
                     "setting_key": "prompts.meme_joke"},
            "summary": {"block_id": "initiative.meme.summary", "text": "s",
                        "differs_from_factory": False},
        },
        "analytics": {
            "output_kind": "meme_initiative", "separate_from_initiative": True,
            "coverage": "durable",
            "counters": {"considered": 4, "eligible": 2, "summary": 2,
                         "joke": 2, "image_generation": 1, "publish": 1,
                         "failed": 0, "skipped": 1},
            "skip_reasons": {"no_random_hit": 1},
            "last_joke": {"limit": 395, "template_chars": 5, "ceiling": 400,
                          "chars": 6, "trimmed": False, "source": "chat",
                          "placeholder": "slot", "speech": _speech()},
            "attempts": _attempt_rows(),
        },
        "delivery": {"output_kind": "meme_initiative",
                     "blocks_text_initiative": False,
                     "publish_blocked_count": 1,
                     "skip_reasons": {"no_random_hit": 1},
                     "stages": ["considered", "eligible", "summary", "joke",
                                "image_generation", "publish", "failed",
                                "skipped"]},
        "schema_present": True,
        "defaults": {"enabled": False, "window_messages": 300, "daily_limit": 3,
                     "cooldown_seconds": 21600, "min_messages": 8,
                     "trigger_probability": 0.05},
        "master_key": "flags.initiative_enabled",
        "own_key": "flags.meme_initiative_enabled",
    }


def _block(mechanism, **over):
    base = {
        "mechanism": mechanism,
        "output_kind": ("initiative_reply" if mechanism == "text_initiative"
                        else "meme_initiative"),
        "source": "stub", "available": True, "data_state": "ok",
        "no_data_reasons": [], "ready": True, "ready_reason": "",
        "last_check_ts": None, "next_check_ts": None,
        "next_check_basis": "eval_interval", "random": None,
        "conditions": None, "stages": None, "skip": None, "skip_recorded": None,
        "cooldown": {"own_seconds": 21600, "remaining_seconds": 0,
                     "basis": "last_initiative_publication",
                     "basis_ts": NOW - 4000, "scope": "mechanism_own"},
        "quota": {"available": True, "limit": 3, "used": 1, "remaining": 2,
                  "limit_reached": False, "unlimited": False, "next_reset": ""},
        "publication": {"available": True, "coordination": "ok", "degraded": False,
                        "conflict": False, "conflict_state": "none",
                        "ok": True, "reason": "", "reason_label": "",
                        "detail": "", "state": "released",
                        "holder_kind": mechanism, "claimed_by": "",
                        "other_kind": "", "other_age_seconds": None,
                        "interval_seconds": 900,
                        "manual_priority_until": None, "checked_at": NOW},
        "blocking": {"blocked": [], "warned": []},
    }
    base.update(over)
    return base


def _diag():
    axes = bool(STATE.get("axes_on"))
    text_over = {}
    meme_over = {"last_check_ts": NOW - 60, "next_check_ts": NOW + 300,
                 "stages": {"considered": 1, "joke": 1},
                 "conditions": {"messages": 42, "quota_left": 2},
                 "random": {"performed": True, "outcome": "hit", "value": 0.02,
                            "hit": True, "probability": 0.05,
                            "purpose": "trigger", "source": "quantum",
                            "selected_source": "quantum",
                            "fallback": False, "reason": ""}}
    if not axes:
        # Честный стейт выключенного механизма: готовность false и ТОЧНАЯ
        # причина — так же, как это отдаёт боевой сборщик диагностики.
        text_over = {"ready": False, "ready_reason": "initiative_disabled",
                     "skip": {"code": "initiative_disabled",
                              "label": "инициатива выключена",
                              "origin": "gate"}}
        meme_over.update({"ready": False,
                          "ready_reason": "initiative_disabled",
                          "skip": {"code": "initiative_disabled",
                                   "label": "инициатива выключена",
                                   "origin": "gate"}})
    return {
        "schema_version": 1, "generated_at": NOW, "chat_id": CHAT_A,
        "text_initiative": _block(
            "text_initiative",
            random={"performed": True, "outcome": "hit", "value": 0.08,
                    "hit": True, "probability": 0.125, "purpose": "trigger",
                    "source": "quantum", "selected_source": "quantum",
                    "fallback": False, "reason": ""},
            conditions={"messages": 42, "quiet": False},
            **text_over),
        "meme": _block("meme", **meme_over),
        "degraded": [],
    }


def _vitality():
    return {
        "available": True, "now_ts": NOW, "hours": 24, "chat_id": CHAT_A,
        "scope": {"master": True, "chat_enabled": True},
        "window": {"delivered": 1},
        "activity": {}, "gates": {},
        "decisions": [
            {"ts": NOW - 120, "action": "reply.text", "outcome": "say",
             "reason_code": "", "reason_label": "без причины",
             "correlation_id": "corr-1", "intent_id": "i-1", "stage": "decision"},
            {"ts": NOW - 900, "action": "silent", "outcome": "silent",
             "reason_code": "no_random_hit", "reason_label": "порог не пройден",
             "correlation_id": "corr-2", "intent_id": "i-2", "stage": "decision"},
        ],
        "refusals": [],
        "sends": [{"ts": NOW - 4000, "message_id": 777,
                   "correlation_id": "corr-0", "chars": 88,
                   "output_kind": "initiative_reply",
                   "delivery_status": "delivered", "core_revision": "r21",
                   "style_policy_revision": "g5", "identity_revision": "a2",
                   "manifest_id": "m1", "composer": "on", "delivery": "text",
                   "delivery_form": "text", "reply_to": "", "delivery_mismatch": "",
                   "ledger_output_id": 1}],
    }


def _status():
    return {
        "intents": {"module": {
            "requested": True, "effective": True, "source": "registry",
            "master_param": "flags.initiative_enabled",
            "env_param": "MCA_INTENTS_ENABLED", "pending": 2,
            "last_decision": {"ts": NOW - 120, "outcome": "say",
                              "reason_code": "", "action": "reply.text"},
            "last_skip": {"ts": NOW - 900, "event": "recheck_deferred",
                          "reason_code": "no_random_hit"},
            "next_due": NOW + 600,
            "heartbeat": {"enabled": True, "registered": True,
                          "next_tick": NOW + 120, "job": "intent_hb",
                          "tick_seconds": 300,
                          "last_tick": {"ts": NOW - 180, "enabled": True}},
            "state_label": "Инициатива работает: решения принимаются",
            "top_block_reason": "",
            "funnel": {"producers_24h": {"chat": 3}, "intents_created_24h": 5,
                       "due": 2, "decisions_24h": 2, "writer_generated_24h": 1,
                       "recheck_passed_24h": 1, "sent_24h": 1},
        }},
    }


def _pub_rows():
    return [
        {"attempt_id": "meme:job-77", "kind": "meme", "job_id": "job-77",
         "mode": "auto", "ts": NOW, "stage": "publish", "outcome": "published",
         "reason_code": "sent", "reason_label": "отправлено",
         "delivered": True, "message_id": 4321, "chain_len": 4,
         "reason_codes": ["sent"],
         "window_messages": 300, "limit_source": "model_capability",
         "limit_value": 400, "events_len": 5},
        # P0-семантика: отправку отложил реальный конфликт координации.
        {"attempt_id": "meme:job-78", "kind": "meme", "job_id": "job-78",
         "mode": "auto", "ts": NOW - 300, "stage": "publish",
         "outcome": "deferred", "reason_code": "publication_conflict",
         "reason_label": "публикацию отложил конфликт с другим механизмом",
         "delivered": None, "message_id": None, "chain_len": 4,
         "reason_codes": ["publication_conflict",
                          "publication_deferred_conflict"],
         "window_messages": 300, "limit_source": "model_capability",
         "limit_value": 400, "events_len": 6},
        {"attempt_id": "meme:job-76", "kind": "meme", "job_id": "job-76",
         "mode": "auto", "ts": NOW - 600, "stage": "publish",
         "outcome": "skipped", "reason_code": "publication_stale",
         "reason_label": "устаревшая бронь публикации", "delivered": False,
         "message_id": None, "chain_len": 4, "reason_codes":
             ["publication_stale"],
         "window_messages": 300,
         "limit_source": "model_capability", "limit_value": 400},
        {"attempt_id": "meme:job-75", "kind": "meme", "job_id": "job-75",
         "mode": "manual", "ts": NOW - 1200, "stage": "publish",
         "outcome": "published", "reason_code": "sent",
         "reason_label": "отправлено", "delivered": True, "message_id": 4300,
         "chain_len": 4, "reason_codes": ["sent"], "window_messages": 300,
         "limit_source": "manual",
         "limit_value": None},
        {"attempt_id": "text:corr-1", "kind": "text_initiative", "job_id": "corr-1",
         "mode": "auto", "ts": NOW - 1800, "stage": "decision",
         "outcome": "say", "reason_code": "", "reason_label": "",
         "delivered": True, "message_id": 4200, "chain_len": 1,
         "window_messages": None, "limit_source": "", "limit_value": None},
    ]


def _meme_chain_skipped():
    """Генерация прошла полностью, отправка ОТМЕНЕНА — точная цепочка."""
    def facts(obj):
        return json.dumps(obj, ensure_ascii=False)
    base = {"limit_source": "model_capability", "limit_value": 400,
            "window_messages": 300}
    return [
        {"stage": "summary", "ts": NOW - 700, "outcome": "passed",
         "reason_code": "", "reason_label": "",
         "facts": {"chars": 41, "source": "factory"},
         "limit_source": "model_capability", "limit_value": 400,
         "window_messages": 300},
        {"stage": "joke", "ts": NOW - 690, "outcome": "passed",
         "reason_code": "", "reason_label": "",
         "facts": {"limit": 395, "template_chars": 5, "ceiling": 400,
                   "chars": 6, "trimmed": False, "source": "chat",
                   "placeholder": "slot", "speech": _speech()},
         "limit_source": "model_capability", "limit_value": 400,
         "window_messages": 300},
        {"stage": "image_generation", "ts": NOW - 680, "outcome": "passed",
         "reason_code": "", "reason_label": "",
         "facts": {"chars": 23, "template_chars": 5, "joke_chars": 6},
         "limit_source": "model_capability", "limit_value": 400,
         "window_messages": 300},
        {"stage": "publish", "ts": NOW - 600, "outcome": "skipped",
         "reason_code": "publication_stale",
         "reason_label": "устаревшая бронь публикации",
         "facts": {"publish": {"manual": False, "gate": "open",
                               "claim": {"state": "released"},
                               "watermark": {"at_generation": 10,
                                             "at_publish": 12}}},
         "limit_source": "model_capability", "limit_value": 400,
         "window_messages": 300},
    ]


def _detail(attempt_id):
    if attempt_id.startswith("meme:job-77"):
        rows = list(reversed(_attempt_rows()))
        # attempt_rows идут «сверху вниз», в трассе нужен хронологический порядок
        chain = [
            {"stage": "summary", "ts": NOW - 12, "outcome": "passed",
             "reason_code": "", "reason_label": "",
             "facts": {"chars": 41, "source": "factory"},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "joke", "ts": NOW - 9, "outcome": "passed",
             "reason_code": "", "reason_label": "",
             "facts": {"limit": 395, "template_chars": 5, "ceiling": 400,
                       "chars": 6, "trimmed": False, "source": "chat",
                       "placeholder": "slot", "speech": _speech()},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "image_generation", "ts": NOW - 5, "outcome": "passed",
             "reason_code": "", "reason_label": "",
             "facts": {"chars": 23, "template_chars": 5, "joke_chars": 6},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "publish", "ts": NOW, "outcome": "published",
             "reason_code": "sent", "reason_label": "отправлено",
             "facts": {"publish": {"manual": False, "gate": "open",
                                   "claim": {"state": "released"},
                                   "output": {"tg_message_id": 4321},
                                   "watermark": {"at_generation": 10,
                                                 "at_publish": 10}}},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
        ]
        _ = rows
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-77", "kind": "meme",
                            "job_id": "job-77", "mode": "auto", "ts": NOW,
                            "stage": "publish", "outcome": "published",
                            "reason_code": "sent", "delivered": True,
                            "message_id": 4321},
                "chain": chain, "events": [],
                "delivery": {"delivered": True, "message_id": 4321}}
    if attempt_id.startswith("meme:job-78"):
        # Отложено конфликтом: генерация прошла, отправка ждёт слота.
        chain = _meme_chain_skipped()
        chain[-1] = {"stage": "publish", "ts": NOW - 300, "outcome": "deferred",
                     "reason_code": "publication_conflict",
                     "reason_label": "публикацию отложил конфликт с другим "
                                     "механизмом",
                     "facts": {"publish": {"manual": False,
                                           "claim": {"state": "released"},
                                           "event_chain": True}},
                     "limit_source": "model_capability", "limit_value": 400,
                     "window_messages": 300}
        events = [
            {"id": None, "ts": NOW - 400, "event_name": "image_ready",
             "stage": "attempt", "outcome": "image_ready", "reason_code": "",
             "reason_label": "", "detail": "", "delivered": None,
             "level": "", "error_type": ""},
            {"id": None, "ts": NOW - 350, "event_name": "publication_requested",
             "stage": "attempt", "outcome": "publication_requested",
             "reason_code": "", "reason_label": "",
             "detail": "claim_requested", "delivered": None, "level": "",
             "error_type": ""},
            {"id": None, "ts": NOW - 300,
             "event_name": "publication_deferred_conflict", "stage": "deferred",
             "outcome": "publication_deferred_conflict",
             "reason_code": "publication_conflict",
             "reason_label": "конфликт публикаций",
             "detail": "deferred|slot_busy", "delivered": None, "level": "",
             "error_type": ""},
        ]
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-78", "kind": "meme",
                            "job_id": "job-78", "mode": "auto",
                            "ts": NOW - 300, "stage": "publish",
                            "outcome": "deferred",
                            "reason_code": "publication_conflict",
                            "delivered": None, "message_id": None},
                "chain": chain, "events": events,
                "delivery": {"delivered": None, "message_id": None}}
    if attempt_id.startswith("meme:job-76"):
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-76", "kind": "meme",
                            "job_id": "job-76", "mode": "auto",
                            "ts": NOW - 600, "stage": "publish",
                            "outcome": "skipped",
                            "reason_code": "publication_stale",
                            "delivered": False, "message_id": None},
                "chain": _meme_chain_skipped(), "events": [],
                "delivery": {"delivered": False, "message_id": None}}
    if attempt_id.startswith("meme:job-75"):
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-75", "kind": "meme",
                            "job_id": "job-75", "mode": "manual",
                            "ts": NOW - 1200, "stage": "publish",
                            "outcome": "published", "reason_code": "sent",
                            "delivered": True, "message_id": 4300},
                "chain": _meme_chain_skipped(), "events": [],
                "delivery": {"delivered": True, "message_id": 4300}}
    if attempt_id.startswith("text:corr-1"):
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "text:corr-1",
                            "kind": "text_initiative", "job_id": "corr-1",
                            "mode": "auto", "ts": NOW - 1800,
                            "stage": "decision", "outcome": "say",
                            "delivered": True, "message_id": 4200},
                "chain": [], "events": [
                    {"id": 1, "ts": NOW - 1800, "event_name": "initiative_decided",
                     "stage": "decision", "outcome": "say", "reason_code": "",
                     "reason_label": "", "level": "INFO",
                     "duration_ms": 12, "error_type": ""},
                    {"id": 2, "ts": NOW - 1790,
                     "event_name": "initiative_recheck_passed",
                     "stage": "recheck", "outcome": "passed", "reason_code": "",
                     "reason_label": "", "level": "INFO",
                     "duration_ms": 5, "error_type": ""},
                ],
                "delivery": {"delivered": True, "message_id": 4200,
                             "sent_at": NOW - 1780,
                             "delivery_status": "delivered",
                             "output_kind": "initiative_reply"}}
    return {"schema_version": 1, "available": True, "notes": ["trace_empty"],
            "attempt": None, "chain": [], "events": [], "delivery": None}


def make_api_handler():
    def _handler(route):
        req = route.request
        url = req.url
        path = url.split("?")[0]
        qs = url.split("?")[1] if "?" in url else ""
        STATE["requests"].append(path + ("?" + qs if qs else ""))
        headers = {k.lower(): v for k, v in (req.headers or {}).items()}
        try:
            chat_hdr = int(headers.get("x-chat-id") or CHAT_A)
        except (TypeError, ValueError):
            chat_hdr = CHAT_A

        def send(payload, status=200):
            route.fulfill(status=status, content_type="application/json",
                          body=json.dumps(payload, ensure_ascii=False))

        if path.endswith("/api/initiative/meme-settings"):
            if req.method == "POST":
                try:
                    body = json.loads(req.post_data or "{}")
                except Exception:  # noqa: BLE001
                    body = {}
                STATE["post_body"] = body
                STATE["post_chat"] = chat_hdr
                STATE["post_count"] += 1
                chat_key = str(chat_hdr)
                if "prompt_joke" in body:
                    value = str(body["prompt_joke"])
                    if value:
                        STATE["prompts_by_chat"][chat_key] = value
                        STATE["joke_source_by_chat"][chat_key] = True
                    else:
                        STATE["prompts_by_chat"].pop(chat_key, None)
                        STATE["joke_source_by_chat"][chat_key] = False
                if "prompt_image" in body:
                    value = str(body["prompt_image"])
                    if value:
                        STATE["images_by_chat"][chat_key] = value
                        STATE["image_source_by_chat"][chat_key] = "chat"
                    else:
                        STATE["images_by_chat"].pop(chat_key, None)
                        STATE["image_source_by_chat"][chat_key] = "factory"
            return send(_meme_settings(chat_hdr))
        if path.endswith("/api/initiative/mechanism-diagnostics"):
            return send(_diag())
        if path.endswith("/api/initiative/publications/detail"):
            attempt = ""
            for part in qs.split("&"):
                if part.startswith("attempt_id="):
                    attempt = part.split("=", 1)[1]
            from urllib.parse import unquote
            return send(_detail(unquote(attempt)))
        if path.endswith("/api/initiative/publications"):
            rows = _pub_rows()
            offset = 0
            for part in qs.split("&"):
                if part.startswith("offset="):
                    try:
                        offset = int(part.split("=", 1)[1])
                    except ValueError:
                        offset = 0
                if part.startswith("kind=") and part.split("=", 1)[1] not in (
                        "", "all"):
                    kind = part.split("=", 1)[1]
                    rows = [r for r in rows if r["kind"] == kind]
                if part.startswith("mode=") and part.split("=", 1)[1] not in (
                        "", "all"):
                    mode = part.split("=", 1)[1]
                    rows = [r for r in rows if r["mode"] == mode]
                if part.startswith("outcome=") and part.split("=", 1)[1] not in (
                        "", "all"):
                    outcome = part.split("=", 1)[1]
                    rows = [r for r in rows if r["outcome"] == outcome]
                if part.startswith("reason=") and part.split("=", 1)[1]:
                    reason = part.split("=", 1)[1].lower()
                    rows = [r for r in rows
                            if reason in str(r.get("reason_code") or "").lower()
                            or any(reason in str(c).lower()
                                   for c in (r.get("reason_codes") or []))]
            page = rows[offset:offset + 2]
            return send({
                "schema_version": 1, "generated_at": NOW, "chat_id": CHAT_A,
                "available": True, "notes": [],
                "filters": {}, "rows": page,
                "counts": {"total": len(rows),
                           "text": sum(1 for r in rows
                                       if r["kind"] == "text_initiative"),
                           "meme": sum(1 for r in rows if r["kind"] == "meme"),
                           "published": sum(1 for r in rows
                                            if r["outcome"] == "published"),
                           "not_delivered": sum(1 for r in rows
                                                if r["delivered"] is False)},
                "next_offset": (offset + len(page)) if offset + len(page) < len(rows)
                else None,
            })
        if path.endswith("/api/memory/initiative-vitality"):
            return send(_vitality())
        if path.endswith("/api/config"):
            payload = M._stub_for(url)
            if STATE.get("axes_on"):
                # Доказательство композиции: включаем ТРИ реальные оси и
                # проверяем, что карточка обзора меняет состояние (а не
                # повторяет мастер-флаг).
                for item in payload.get("items") or []:
                    if item.get("key") in ("flags.initiative_enabled",
                                           "flags.initiative_observer_enabled",
                                           "initiative.enabled"):
                        item["value"] = True
                        item["global_value"] = True
            return send(payload)
        if path.endswith("/api/status"):
            return send(_status())
        if path.endswith("/api/access/me"):
            return send({"is_global_admin": True, "is_local_admin": True,
                         "effective_permissions": None})
        if path.endswith("/api/access/chats"):
            return send([
                {"chat_id": CHAT_A, "title": "Чат A", "is_dm": False,
                 "photo_file_id": None, "access": "admin", "is_active": True},
                {"chat_id": CHAT_B, "title": "Чат B", "is_dm": False,
                 "photo_file_id": None, "access": "admin", "is_active": True},
            ])
        return send(M._stub_for(url))
    return _handler


def serve_static(port, webroot):
    class _Handler(SimpleHTTPRequestHandler):
        def translate_path(self, path):  # noqa: N802
            p = path.split("?")[0]
            if p.startswith("/static/"):
                rel = "static/" + p[len("/static/"):]
            elif p.startswith("/web/"):
                rel = p[len("/web/"):]
            elif p in ("/", "", "/index.html"):
                rel = "index.html"
            else:
                rel = p.lstrip("/")
            return os.path.join(webroot, rel.replace("/", os.sep))

        def log_message(self, *args):  # тихо
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


failures = []
notes = []


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


def check(cond, label, msg):
    if not cond:
        fail(label, msg)
    return bool(cond)


def new_page(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430, has_touch=width <= 430)
    ctx.route("**/api/**", make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(
                  status=200, content_type="application/javascript",
                  body=SDK_STUB))
    ctx.add_init_script(
        "try { localStorage.setItem('adminbot.active_chat_id', '%d'); }"
        " catch (e) {}" % CHAT_A)
    page = ctx.new_page()
    page.set_default_timeout(20000)
    return ctx, page


def shot(page, shots, name):
    if not shots:
        return
    os.makedirs(shots, exist_ok=True)
    try:
        page.screenshot(path=os.path.join(shots, name + ".png"),
                        full_page=True)
    except Exception:  # noqa: BLE001
        pass


def open_page(page, tab=None):
    url = BASE + "/#/modules/initiative" + ("/" + tab if tab else "")
    page.goto(url, wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_timeout(700)


def open_tab(page, tab):
    page.click('[data-workspace-tab="%s"]' % tab)
    page.wait_for_timeout(600)


# ── Сценарий 1: шапка и вкладки ───────────────────────────────────────────
HEAD_PROBE = r"""
() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const tabs = Array.from(document.querySelectorAll('[data-workspace-tab]'))
    .map((el) => strip(el.textContent));
  const strip = null;
  return {
    title: strip((document.querySelector('.workspace-head .text-base') || {})
      .textContent),
    scope: strip((document.querySelector('[data-workspace-scope]') || {})
      .textContent),
    state: strip((document.querySelector('.workspace-head .badge:last-child')
      || {}).textContent),
    catalog: !!document.querySelector('[data-module-managed-link]'),
    tabs: tabs,
    activeTab: (document.querySelector('[data-workspace-tab][aria-selected="true"]')
      || {}).textContent,
  };
}
"""


def run_head(browser, width, height, label, shots):
    STATE["requests"] = []
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page)
        data = page.evaluate(
            "() => { const strip = (s) => String(s || '').replace(/\\s+/g, ' ').trim();"
            " const tabs = Array.from(document.querySelectorAll('[data-workspace-tab]'))"
            "   .map((el) => strip(el.textContent));"
            " return { title: strip((document.querySelector('.workspace-head .text-base')"
            "   || {}).textContent),"
            "  scope: strip((document.querySelector('[data-workspace-scope]') || {})"
            "    .textContent),"
            "  catalog: !!document.querySelector('[data-module-managed-link]'),"
            "  tabs: tabs,"
            "  active: strip((document.querySelector("
            "    '[data-workspace-tab][aria-selected=\"true\"]') || {}).textContent) }; }")
        notes.append({label + "-head": data})
        check(data["title"] == "Инициатива", label,
              "шапка страницы не «Инициатива»: %r" % data["title"])
        check(bool(data["scope"]), label, "в шапке нет области действия")
        check(data["catalog"], label, "нет ссылки в каталог модулей")
        want = ["Обзор", "Текстовая инициатива", "Мемы", "Публикации",
                "Диагностика"]
        check(data["tabs"] == want, label, "вкладки: %r" % (data["tabs"],))
        check(data["active"] == "Обзор", label,
              "первая вкладка не «Обзор»: %r" % data["active"])
        check(not any("/api/initiative/publications" in r
                      for r in STATE["requests"]), label,
              "«Обзор» запрашивает тяжёлый журнал при первом открытии")
        shot(page, shots, "overview_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 2: «Обзор» ───────────────────────────────────────────────────
OVERVIEW_PROBE = r"""
() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top),
             w: Math.round(r.width), h: Math.round(r.height) };
  };
  const card = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    return { text: strip(el.textContent),
             facts: Array.from(el.querySelectorAll('.ini-fact')).map((f) => ({
               k: strip((f.querySelector('.ini-fact__k') || {}).textContent),
               v: strip((f.querySelector('.ini-fact__v') || {}).textContent) })) };
  };
  const events = Array.from(document.querySelectorAll('[data-ini-event]'));
  return {
    textCard: card('[data-ini-card="text"]'),
    memeCard: card('[data-ini-card="meme"]'),
    textRect: rect('[data-ini-card="text"]'),
    memeRect: rect('[data-ini-card="meme"]'),
    textEffect: strip((document.querySelector('[data-ini-effect="text"]') || {})
      .textContent),
    memeEffect: strip((document.querySelector('[data-ini-effect="meme"]') || {})
      .textContent),
    coord: {
      state: (document.querySelector('[data-ini-coordination]') || {}).getAttribute
        ? document.querySelector('[data-ini-coordination]')
          .getAttribute('data-ini-coord-state') : null,
      label: strip((document.querySelector('[data-ini-coord-label]') || {})
        .textContent),
      event: strip((document.querySelector('[data-ini-coord-event]') || {})
        .textContent),
      text: strip((document.querySelector('[data-ini-coordination]') || {})
        .textContent),
    },
    events: events.map((el) => strip(el.textContent)),
    eventCount: events.length,
    hasWorkspaceOverview: !!document.querySelector('[data-workspace-overview]'),
    hasPrimary: !!document.querySelector('[data-module-primary-action]'),
    overviewH: (rect('[data-initiative-overview]') || {}).h,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}
"""


def run_overview(browser, width, height, label, shots):
    STATE["requests"] = []
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page)
        data = page.evaluate(OVERVIEW_PROBE)
        notes.append({label + "-overview": {
            "coord": data["coord"], "eventCount": data["eventCount"],
            "textRect": data["textRect"], "memeRect": data["memeRect"]}})
        check(data["textCard"] and data["memeCard"], label,
              "нет двух карточек механизмов")
        if data["textCard"] and data["memeCard"]:
            tk = {f["k"] for f in data["textCard"]["facts"]}
            mk = {f["k"] for f in data["memeCard"]["facts"]}
            for want in ("Кто может изменить", "Последняя проверка",
                         "Следующая проверка", "Последняя реальная публикация",
                         "Свой кулдаун", "Дневная квота", "Ждёт сейчас"):
                check(want in tk, label, "в карточке текста нет поля %r" % want)
                check(want in mk, label, "в карточке мемов нет поля %r" % want)
            # Композиция РЕАЛЬНЫХ осей: выключенный механизм (мастер ON, но
            # оси/гейт OFF) обязан читаться как «выключена», включённый — как
            # «включена». Это не повтор мастер-флага.
            want_text = "включена" if STATE.get("axes_on") else "выключена"
            check(data["textEffect"] == want_text, label,
                  "состояние текста не собрано из осей: ожидалось %r, показано %r"
                  % (want_text, data["textEffect"]))
            want_meme = "включены" if STATE.get("axes_on") else "выключены"
            check(data["memeEffect"] == want_meme, label,
                  "состояние мемов не собрано из осей: ожидалось %r, показано %r"
                  % (want_meme, data["memeEffect"]))
            check("Генерации сегодня: 1 / 3" in data["memeCard"]["text"], label,
                  "квота дня мемов не из настроек: %r"
                  % data["memeCard"]["text"][:200])
        check(data["coord"]["state"] == "free", label,
              "координация не «свободно»: %r" % data["coord"])
        check(bool(data["coord"]["event"]), label,
              "в координации нет реального события/паузы из API")
        check(3 <= data["eventCount"] <= 5, label,
              "значимых событий %d (нужно 3–5)" % data["eventCount"])
        check(data["hasWorkspaceOverview"] and data["hasPrimary"], label,
              "у обзора нет основного действия")
        check((data["overviewH"] or 0) > 240, label,
              "обзор выглядит одной строкой на всю ширину: %r"
              % data["overviewH"])
        if width >= 1200 and data["textRect"] and data["memeRect"]:
            check(abs(data["textRect"]["w"] - data["memeRect"]["w"]) <= 2, label,
                  "карточки разной ширины: %s vs %s"
                  % (data["textRect"]["w"], data["memeRect"]["w"]))
            check(data["textRect"]["y"] == data["memeRect"]["y"], label,
                  "карточки не в два столбца на десктопе")
        if width < 1200:
            check(data["textRect"] and data["memeRect"]
                  and data["textRect"]["y"] < data["memeRect"]["y"], label,
                  "на узком экране карточки не перешли в одну колонку")
        check(data["overflow"] <= 1, label,
              "горизонтальная прокрутка страницы: %d px" % data["overflow"])
        shot(page, shots, "overview_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 3: «Текстовая инициатива» ───────────────────────────────────
def run_text(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page, "text")
        data = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const sec = (id) => !!document.querySelector(
            '[data-initiative-section="' + id + '"]');
          const decision = strip((document.querySelector(
            '[data-initiative-last-decision]') || {}).textContent);
          return {
            enable: sec('enable'), limits: sec('limits'), decision: sec('decision'),
            status: !!document.querySelector('[data-initiative-status]'),
            perChat: !!document.querySelector('[data-initiative-per-chat]'),
            advanced: !!document.querySelector('[data-initiative-advanced]'),
            groups: Array.from(document.querySelectorAll(
              '[data-initiative-group]')).map((g) =>
                g.getAttribute('data-initiative-group')),
            decision: decision,
            memeToggle: !!document.querySelector('[data-meme-toggle]'),
            memePrompt: !!document.querySelector('[data-meme-prompt-joke]'),
            memeWindow: !!document.querySelector('[data-meme-window]'),
            limitsHeader: Array.from(document.querySelectorAll('div'))
              .some((el) => strip(el.textContent) === 'Частота и лимиты'),
            overflow: document.documentElement.scrollWidth - window.innerWidth,
          };
        }
        """)
        notes.append({label + "-text": {k: data[k] for k in
                                        ("enable", "limits", "decision",
                                         "groups", "limitsHeader")}})
        for key in ("enable", "limits", "decision"):
            check(data[key], label, "нет секции %r" % key)
        check(data["status"] and data["perChat"] and data["advanced"], label,
              "старые параметры инициативы не нашли нового дома")
        check("auto" in data["groups"] and "schedule" in data["groups"], label,
              "семантические группы осей не отрисованы: %r" % data["groups"])
        check(not data["memeToggle"] and not data["memePrompt"]
              and not data["memeWindow"], label,
              "на вкладке текста остались настройки мемов")
        check("12.5 %" in data["decision"], label,
              "вероятность последнего решения не показана: %r"
              % data["decision"][:220])
        check("quantum" in data["decision"], label,
              "реальный источник случайности не показан: %r"
              % data["decision"][:220])
        check(data["limitsHeader"], label,
              "нет секции «Частота и лимиты» с параметрами")
        check(data["overflow"] <= 1, label,
              "горизонтальная прокрутка: %d px" % data["overflow"])
        shot(page, shots, "text_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 4: «Мемы» ────────────────────────────────────────────────────
MEMES_PROBE = r"""
() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top),
             w: Math.round(r.width), h: Math.round(r.height) };
  };
  const txt = (sel) => strip((document.querySelector(sel) || {}).textContent);
  const card = document.querySelector('[data-meme-settings]');
  return {
    hasCard: !!card,
    topline: txt('[data-ini-meme-topline]'),
    today: txt('[data-ini-meme-today]'),
    colTrigger: rect('[data-ini-meme-col="trigger"]'),
    colCreate: rect('[data-ini-meme-col="create"]'),
    pipeline: Array.from(document.querySelectorAll('[data-ini-pipeline-step]'))
      .map((el) => el.getAttribute('data-ini-pipeline-step')),
    promptJoke: rect('[data-ini-prompt="joke"]'),
    promptImage: rect('[data-ini-prompt="image"]'),
    saveButtons: document.querySelectorAll('[data-meme-save]').length,
    saveState: txt('[data-meme-save-state]'),
    ceiling: txt('[data-meme-limit-ceiling]'),
    template: txt('[data-meme-limit-template]'),
    jokeBudget: txt('[data-meme-limit-joke]'),
    actual: txt('[data-meme-limit-actual]'),
    lengthField: !!document.querySelector('[data-meme-length-limit]'),
    attemptStages: Array.from(document.querySelectorAll(
      '[data-meme-attempt-stage]')).map((el) =>
        el.getAttribute('data-meme-attempt-stage')),
    attemptResult: txt('[data-ini-attempt-result]'),
    attemptTs: txt('[data-ini-attempt-ts]'),
    manual: txt('[data-ini-meme-manual]'),
    noFacts: (card ? card.textContent : '').indexOf('фактов этапа нет') >= 0,
    speechShown: !!document.querySelector('[data-meme-speech]'),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}
"""


def run_memes(browser, width, height, label, shots):
    STATE["post_body"] = None
    STATE["post_count"] = 0
    STATE["post_chat"] = None
    # Сброс значений стаба: иначе второй прогон (другой вьюпорт) видит уже
    # сохранённый текст и честно не отправляет его повторно.
    STATE["prompts_by_chat"] = {}
    STATE["images_by_chat"] = {}
    STATE["joke_source_by_chat"] = {}
    STATE["image_source_by_chat"] = {}
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page, "memes")
        data = page.evaluate(MEMES_PROBE)
        notes.append({label + "-memes": {
            k: data[k] for k in ("topline", "today", "pipeline", "attemptStages",
                                 "attemptResult", "ceiling", "actual")}})
        check(data["hasCard"], label, "карточка мемов не отрисована")
        check("включены" in data["topline"], label,
              "нет своего ON/OFF мемов: %r" % data["topline"])
        check("Квота сегодня" in data["today"], label,
              "нет квоты дня в верхней строке: %r" % data["today"])
        check("Последняя публикация" in data["today"], label,
              "нет последней публикации в верхней строке")
        check(data["pipeline"] == ["summary", "joke", "image_generation",
                                   "publish"], label,
              "pipeline не из 4 шагов: %r" % (data["pipeline"],))
        if width >= 1200:
            check(data["colTrigger"]["y"] == data["colCreate"]["y"], label,
                  "«Триггер» и «Создание мема» не в два столбца")
            check(data["promptJoke"]["y"] == data["promptImage"]["y"], label,
                  "два промпта не рядом на десктопе")
        else:
            check(data["colTrigger"]["y"] < data["colCreate"]["y"], label,
                  "на узком экране колонки не сложились вертикально")
            check(data["promptJoke"]["y"] < data["promptImage"]["y"], label,
                  "на узком экране промпты не сложились вертикально")
        check(data["saveButtons"] == 1, label,
              "кнопок сохранения не одна: %d" % data["saveButtons"])
        check(data["lengthField"], label,
              "нет поля «потолок длины промпта (пусто — авто)")
        for key, want in (("ceiling", "400"), ("template", "5"),
                          ("jokeBudget", "395")):
            check(data[key] == want, label,
                  "бюджет %s = %r (ожидалось %r)" % (key, data[key], want))
        check("23" in data["actual"] and "6" in data["actual"], label,
              "фактическая длина последней сборки не показана: %r"
              % data["actual"])
        check(data["attemptStages"] == ["summary", "joke", "image_generation",
                                        "publish"], label,
              "«Последняя попытка» без четырёх этапов: %r"
              % (data["attemptStages"],))
        check("реально опубликовано" in data["attemptResult"], label,
              "компактная попытка не сообщает факт публикации: %r"
              % data["attemptResult"])
        check(bool(data["attemptTs"]), label, "нет timestamp последней попытки")
        check(not data["noFacts"], label,
              "в карточке остались повторы «фактов этапа нет»")
        check("админская команда" in data["manual"] and "/meme" in data["manual"],
              label, "ручной /meme не обозначен админской командой: %r"
              % data["manual"][:160])
        check(data["speechShown"], label, "нет блока речевой сборки")
        check(data["overflow"] <= 1, label,
              "горизонтальная прокрутка: %d px" % data["overflow"])
        shot(page, shots, "memes_%s" % label)

        # Один POST на оба промпта + реальный результат сохранения.
        page.fill("textarea[data-meme-prompt-joke]", "Свой прикол: коротко.")
        page.fill("textarea[data-meme-prompt-image]", "Кадр мема: {joke}")
        page.wait_for_timeout(250)
        check(page.evaluate(
            "() => !!document.querySelector('[data-meme-dirty]')"), label,
            "после правки промптов нет индикатора несохранённых изменений")
        shot(page, shots, "memes_dirty_%s" % label)
        page.click("[data-meme-save]")
        page.wait_for_timeout(800)
        body = STATE["post_body"] or {}
        check(body.get("prompt_joke") == "Свой прикол: коротко.", label,
              "промпт прикола не ушёл в общий save: %r" % (body,))
        check(body.get("prompt_image") == "Кадр мема: {joke}", label,
              "шаблон изображения не ушёл в общий save: %r" % (body,))
        check(STATE["post_count"] == 1, label,
              "сохранение ушло %d раз(а) вместо одного" % STATE["post_count"])
        state_text = page.evaluate(
            "() => ((document.querySelector('[data-meme-save-state]') || {})"
            ".textContent || '').trim()")
        check("Сохранено для этого чата" in state_text, label,
              "результат сохранения не показан: %r" % state_text)

        # «Отменить изменения» возвращает серверное значение (без POST).
        before = STATE["post_count"]
        page.fill("textarea[data-meme-prompt-joke]", "черновик-мусор")
        page.click("[data-meme-draft-reset]")
        page.wait_for_timeout(300)
        value = page.evaluate(
            "() => document.querySelector('textarea[data-meme-prompt-joke]').value")
        check(value == "Свой прикол: коротко.", label,
              "«Отменить изменения» не вернуло значение: %r" % value)
        check(STATE["post_count"] == before, label,
              "«Отменить изменения» отправило запрос на сервер")

        # «Вернуть наследование» → пустое поле → сервер снимает override.
        page.click("[data-meme-prompt-reset-image]")
        page.wait_for_timeout(200)
        value = page.evaluate(
            "() => document.querySelector('textarea[data-meme-prompt-image]').value")
        check(value == "", label,
              "«Вернуть наследование» не очистило поле: %r" % value)
        page.click("[data-meme-save]")
        page.wait_for_timeout(800)
        body = STATE["post_body"] or {}
        check(body.get("prompt_image") == "", label,
              "снятие override не отправлено пустой строкой: %r" % (body,))
        src = page.evaluate(
            "() => ((document.querySelector('[data-meme-prompt-image-source]')"
            " || {}).textContent || '').trim()")
        check("заводской" in src, label,
              "после снятия override источник не «заводской»: %r" % src)
        shot(page, shots, "memes_saved_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 5: «Публикации» ─────────────────────────────────────────────
def run_publications(browser, width, height, label, shots):
    STATE["requests"] = []
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page, "publications")
        page.wait_for_selector("[data-ini-pub-row]", state="attached")
        page.wait_for_timeout(400)
        data = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const rows = Array.from(document.querySelectorAll('[data-ini-pub-row]'))
            .map((el) => ({ id: el.getAttribute('data-ini-pub-row'),
                            text: strip(el.textContent),
                            outcome: (el.querySelector('[data-ini-pub-outcome]') || {})
                              .getAttribute ? el.querySelector(
                                '[data-ini-pub-outcome]').getAttribute(
                                  'data-ini-pub-outcome') : null,
                            delivery: (el.querySelector('[data-ini-pub-delivery]')
                              || {}).getAttribute ? el.querySelector(
                                '[data-ini-pub-delivery]').getAttribute(
                                  'data-ini-pub-delivery') : null }));
          return {
            filters: document.querySelectorAll('[data-ini-filter]').length,
            rows: rows,
            counts: strip((document.querySelector('[data-ini-pub-counts]') || {})
              .textContent),
            more: !!document.querySelector('[data-ini-pub-more]'),
            details: document.querySelectorAll('[data-ini-pub-detail]').length,
            overflow: document.documentElement.scrollWidth - window.innerWidth,
          };
        }
        """)
        notes.append({label + "-pub": {"filters": data["filters"],
                                       "rows": len(data["rows"]),
                                       "counts": data["counts"]}})
        check(data["filters"] == 6, label,
              "фильтров %d (чат + период/тип/режим/исход/причина = 6)"
              % data["filters"])
        check(2 <= len(data["rows"]) <= 2, label,
              "первая страница должна содержать 2 строки: %d"
              % len(data["rows"]))
        check(data["details"] == 0, label,
              "детали раскрыты по умолчанию (должны быть по клику)")
        check(data["more"], label, "нет пагинации при next_offset")
        first = data["rows"][0]
        for want in ("Мемы", "Публикация", "доставлено"):
            check(want in first["text"], label,
                  "строка журнала без %r: %r" % (want, first["text"]))
        # Пагинация: вторая страница дописывается, а не заменяет первую.
        page.click("[data-ini-pub-more]")
        page.wait_for_timeout(700)
        total = page.evaluate(
            "() => document.querySelectorAll('[data-ini-pub-row]').length")
        check(total > len(data["rows"]), label,
              "«Показать ещё» не дописало строки: %d" % total)
        # Деталь отменённой отправки: генерация прошла, отправки не было.
        page.click('[data-ini-pub-row="meme:job-76"]')
        page.wait_for_timeout(700)
        detail = page.evaluate(
            "() => { const el = document.querySelector('[data-ini-pub-detail]');"
            " return el ? String(el.textContent).replace(/\\s+/g, ' ').trim() : ''; }")
        check("публикация" in detail.lower(), label,
              "деталь не показывает этап публикации: %r" % detail[:200])
        check("устаревшая бронь публикации" in detail, label,
              "деталь не объясняет отмену отправки: %r" % detail[:300])
        summary = page.evaluate(
            "() => ((document.querySelector('[data-ini-pub-summary]') || {})"
            ".textContent || '').replace(/\\s+/g, ' ').trim()")
        check("генерация успешна, отправка отменена" in summary, label,
              "итог детали не различает генерацию и отправку: %r" % summary)
        check("Выжимка" in detail and "Генерация картинки" in detail, label,
              "деталь не показывает, что генерация прошла: %r" % detail[:300])
        check("нет данных для этой стадии" not in detail, label,
              "пустая строка детали попала в цепочку")
        # Фильтр типа: уходит серверный параметр, строки перечитываются.
        STATE["requests"] = []
        page.select_option('[data-ini-filter="kind"]', "text_initiative")
        page.wait_for_timeout(700)
        check(any("kind=text_initiative" in r for r in STATE["requests"]), label,
              "фильтр типа не ушёл на сервер: %r" % STATE["requests"][:4])
        rows_after = page.evaluate(
            "() => Array.from(document.querySelectorAll('[data-ini-pub-row]'))"
            ".map((el) => el.getAttribute('data-ini-pub-row'))")
        check(all(r.startswith("text:") for r in rows_after), label,
              "фильтр «текст» вернул мемы: %r" % rows_after)
        page.select_option('[data-ini-filter="kind"]', "all")
        page.wait_for_timeout(700)
        # F2: отложенный конфликтом мем читается как «отложено», а не ошибка,
        # и причина цепочки видна в строке.
        page.click('[data-ini-pub-row="meme:job-78"]')
        page.wait_for_timeout(700)
        deferred = page.evaluate(r"""
        () => {
          const row = document.querySelector('[data-ini-pub-row="meme:job-78"]');
          const detail = document.querySelector('[data-ini-pub-detail]');
          return {
            text: row ? String(row.textContent).replace(/\s+/g, ' ').trim() : '',
            outcome: row ? (row.querySelector('[data-ini-pub-outcome]') || {})
              .getAttribute('data-ini-pub-outcome') : null,
            detail: detail ? String(detail.textContent).replace(/\s+/g, ' ')
              .trim() : '',
            events: Array.from(document.querySelectorAll(
              '[data-ini-pub-event]')).map((el) =>
                el.getAttribute('data-ini-pub-event')),
          };
        }
        """)
        notes.append({label + "-deferred-row": deferred})
        check(deferred["outcome"] == "deferred", label,
              "отложенный конфликт не помечен `deferred`: %r" % deferred)
        check("отложено" in deferred["text"], label,
              "строка не подписана «отложено»: %r" % deferred["text"][:160])
        check("не доставлено" not in deferred["text"], label,
              "отложенный конфликт подан как недоставка: %r"
              % deferred["text"][:160])
        check("в цепочке" in deferred["text"], label,
              "в строке нет причин цепочки (конфликт) : %r"
              % deferred["text"][:160])
        check("publication_deferred_conflict" in deferred["events"], label,
              "в деталях нет события отложенного конфликта: %r"
              % deferred["events"])
        check("slot_busy" in deferred["detail"], label,
              "деталь не показывает, на чём именно отложено: %r"
              % deferred["detail"][:200])
        check("отложена координацией" in (
            page.evaluate("() => ((document.querySelector('[data-ini-pub-summary]')"
                          " || {}).textContent || '')")), label,
              "итог детали не называет отложение")
        # Фильтр по причине конфликта находит отложенную попытку.
        STATE["requests"] = []
        page.select_option('[data-ini-filter="outcome"]', "deferred")
        page.wait_for_timeout(700)
        only_deferred = page.evaluate(
            "() => Array.from(document.querySelectorAll('[data-ini-pub-row]'))"
            ".map((el) => el.getAttribute('data-ini-pub-row'))")
        check(only_deferred == ["meme:job-78"], label,
              "фильтр исхода «отложено» вернул %r" % only_deferred)
        page.select_option('[data-ini-filter="outcome"]', "all")
        page.wait_for_timeout(600)
        check(data["overflow"] <= 1, label,
              "горизонтальная прокрутка: %d px" % data["overflow"])
        shot(page, shots, "publications_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 6: «Диагностика» ────────────────────────────────────────────
def run_diagnostics(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    try:
        # Попытка выбирается из журнала: «Подробная трасса» с «Публикаций».
        open_page(page, "publications")
        page.wait_for_selector("[data-ini-pub-row]", state="attached")
        page.click('[data-ini-pub-row="meme:job-77"]')
        page.wait_for_timeout(600)
        page.click("[data-ini-pub-trace]")
        page.wait_for_selector("[data-ini-trace-group]", state="attached")
        page.wait_for_timeout(700)
        data = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const groups = Array.from(document.querySelectorAll(
            '[data-ini-trace-group]'));
          return {
            keys: groups.map((el) => el.getAttribute('data-ini-trace-group')),
            collapsed: groups.every((el) => {
              const btn = el.querySelector('.ini-trace__head');
              return btn && btn.getAttribute('aria-expanded') === 'false';
            }),
            bodyVisible: groups.some((el) => !!el.querySelector('.ini-trace__body')),
            hashes: (document.querySelector('[data-ini-trace-manifest]') || {})
              .textContent ? strip(document.querySelector(
                '[data-ini-trace-manifest]').textContent) : '',
            diagBlocks: document.querySelectorAll('[data-meme-diag]').length,
            diagSection: !!document.querySelector('[data-meme-diag-section]'),
            overflow: document.documentElement.scrollWidth - window.innerWidth,
          };
        }
        """)
        want = ["conditions", "random", "context", "stages", "speech", "send",
                "events"]
        for key in want:
            check(key in data["keys"], label,
                  "нет группы трассы %r (есть %r)" % (key, data["keys"]))
        check(len(data["keys"]) == len(set(data["keys"])), label,
              "группы трассы дублируются: %r" % (data["keys"],))
        check(data["collapsed"], label,
              "группы трассы раскрыты по умолчанию (нужен сжатый view)")
        check(not data["bodyVisible"], label,
              "тело группы отрисовано без раскрытия (тяжёлые данные зря)")
        check(data["diagSection"] and data["diagBlocks"] == 2, label,
              "полные блоки двух механизмов не на вкладке «Диагностика»")
        # Раскрытие «Речевые слои» показывает ревизии и манифест.
        page.click('[data-ini-trace-group="speech"] .ini-trace__head')
        page.wait_for_timeout(400)
        speech = page.evaluate(
            "() => { const el = document.querySelector("
            "'[data-ini-trace-group=\"speech\"]');"
            " return el ? String(el.textContent).replace(/\\s+/g, ' ').trim() : ''; }")
        for want in ("Core", "Expression", "Humor", "манифест сборки",
                     "62aaae1adf259de9"):
            check(want in speech, label,
                  "в раскрытой речевой сборке нет %r: %r" % (want, speech[:220]))
        check("вошёл" in speech or "пропущен" in speech, label,
              "нет индикатора вошёл/пропущен по слоям")
        # Безопасный срез манифеста: содержимое слоёв, а не id под видом текста.
        page.evaluate(
            "() => { const d = Array.from(document.querySelectorAll("
            "'[data-ini-trace-group=\"speech\"] details'))[0]; if (d) d.open = true; }")
        page.wait_for_timeout(300)
        manifest_text = page.evaluate(
            "() => ((document.querySelector('[data-ini-trace-manifest-text]') || {})"
            ".textContent || '').trim()")
        for want in ("core ←", "манифест", "R17"):
            check(want in manifest_text, label,
                  "безопасный срез манифеста без %r: %r"
                  % (want, manifest_text[:200]))
        # Раскрытие «Этапы генерации» показывает факты этапов.
        page.click('[data-ini-trace-group="stages"] .ini-trace__head')
        page.wait_for_timeout(300)
        stages = page.evaluate(
            "() => { const el = document.querySelector("
            "'[data-ini-trace-group=\"stages\"]');"
            " return el ? String(el.textContent).replace(/\\s+/g, ' ').trim() : ''; }")
        for want in ("шаблон 5", "бюджет прикола 395", "итоговый промпт 23"):
            check(want in stages, label,
                  "в этапах нет факта %r: %r" % (want, stages[:260]))
        check(data["overflow"] <= 1, label,
              "горизонтальная прокрутка: %d px" % data["overflow"])
        shot(page, shots, "diagnostics_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 7: мобильная навигация вкладками ────────────────────────────
def run_mobile_nav(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page)
        data = page.evaluate(r"""
        () => {
          const strip = document.querySelector('[data-workspace-tabs]');
          const r = strip ? strip.getBoundingClientRect() : null;
          return {
            scrollable: strip ? strip.scrollWidth > strip.clientWidth + 2 : false,
            tabH: Array.from(document.querySelectorAll('[data-workspace-tab]'))
              .map((el) => Math.round(el.getBoundingClientRect().height)),
            stripW: r ? Math.round(r.width) : 0,
            pageOverflow: document.documentElement.scrollWidth
              - window.innerWidth,
          };
        }
        """)
        check(data["scrollable"], label,
              "лента вкладок не прокручивается внутри полосы: %r" % data)
        check(data["pageOverflow"] <= 1, label,
              "прокручивается ВСЯ страница по горизонтали: %d px"
              % data["pageOverflow"])
        check(min(data["tabH"]) >= 40, label,
              "тач-цель вкладки меньше 40px: %r" % data["tabH"])
        # Все пять вкладок достижимы и каждая отрисовывает свой блок.
        markers = {"overview": "[data-initiative-overview]",
                   "text": "[data-initiative-text]",
                   "memes": "[data-meme-settings]",
                   "publications": "[data-initiative-publications]",
                   "diagnostics": "[data-initiative-diagnostics]"}
        for tab, sel in markers.items():
            open_tab(page, tab)
            ok = page.evaluate(
                "(sel) => !!document.querySelector(sel)", sel)
            check(ok, label, "вкладка %r не отрисовала свой блок" % tab)
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - window.innerWidth")
            check(overflow <= 1, label,
                  "вкладка %r даёт горизонтальную прокрутку: %d px"
                  % (tab, overflow))
            shot(page, shots, "nav_%s_%s" % (tab, label))
    finally:
        ctx.close()


# ── Сценарий 8: смена чата настоящим селектором (ревью F4) ────────────────
def run_chat_switch(browser, width, height, label, shots):
    """Смена чата через РЕАЛЬНЫЙ селектор области.

    Ревью показало, что прежний вариант искал несуществующие атрибуты
    (`data-scope-toggle`/`data-scope-chat`) и потому ничего не проверял.
    Теперь используется настоящий `.scope-trigger` → `.scope-option`, и
    утверждается именно ПЕРЕЧИТЫВАНИЕ данных: промпт и квота другого чата,
    отсутствие прежних значений на экране, предупреждение о несохранённом
    черновике (dirty-guard) и отсутствие ошибок консоли.
    """
    STATE["prompts_by_chat"] = {}
    STATE["images_by_chat"] = {}
    STATE["joke_source_by_chat"] = {}
    STATE["image_source_by_chat"] = {}
    STATE["post_body"] = None
    STATE["post_count"] = 0
    STATE["axes_on"] = False
    ctx, page = new_page(browser, width, height)
    errs = []
    dialogs = []
    page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    try:
        open_page(page, "memes")
        page.wait_for_selector("textarea[data-meme-prompt-joke]", state="visible")
        page.wait_for_timeout(600)
        before = page.evaluate(r"""
        () => ({
          joke: document.querySelector('textarea[data-meme-prompt-joke]').value,
          quota: ((document.querySelector('[data-meme-quota-text]') || {})
            .textContent || '').trim(),
          card: ((document.querySelector('[data-meme-settings]') || {})
            .textContent || ''),
          scope: ((document.querySelector('.scope-trigger .scope-name') || {})
            .textContent || '').trim(),
        })
        """)
        notes.append({label + "-chat-switch-before": before})
        check(before["joke"] == CHAT_PROMPTS[str(CHAT_A)], label,
              "исходный промпт чата A не показан: %r" % before["joke"])
        check("1 / 3" in before["quota"], label,
              "квота чата A не показана: %r" % before["quota"])

        # F3: несохранённая правка + уход на другую вкладку — не теряется.
        page.fill("textarea[data-meme-prompt-joke]", "ЧЕРНОВИК 123")
        page.wait_for_timeout(250)
        dirty = page.evaluate(
            "() => !!document.querySelector('[data-meme-dirty]')")
        check(dirty, label, "индикатор несохранённых изменений не появился")
        check(page.evaluate(
            "() => !!document.querySelector('[data-meme-dirty-hint]')"), label,
            "нет подсказки о судьбе несохранённых правок")
        open_tab(page, "overview")
        open_tab(page, "memes")
        page.wait_for_selector("textarea[data-meme-prompt-joke]", state="visible")
        page.wait_for_timeout(500)
        kept = page.evaluate(
            "() => document.querySelector('textarea[data-meme-prompt-joke]').value")
        check(kept == "ЧЕРНОВИК 123", label,
              "правка промпта потерялась при переключении вкладок: %r" % kept)
        check(STATE["post_count"] == 0, label,
              "переключение вкладок отправило POST (несохранённое сохранили молча)")

        # Настоящий селектор области: .scope-trigger → .scope-option «Чат B».
        page.click(".scope-trigger")
        page.wait_for_selector(".scope-panel .scope-option", state="visible")
        options = page.evaluate(r"""
        () => Array.from(document.querySelectorAll('.scope-panel .scope-option'))
          .map((el) => (el.textContent || '').replace(/\s+/g, ' ').trim())
        """)
        notes.append({label + "-scope-options": options})
        check(any("Чат B" in o for o in options), label,
              "в селекторе области нет чата B: %r" % options)
        STATE["requests"] = []
        page.click(".scope-panel .scope-option:has-text('Чат B')")
        page.wait_for_timeout(1200)

        # Dirty-guard обязан предупредить, а не стереть черновик молча.
        check(bool(dialogs), label,
              "при смене чата с несохранённым черновиком нет предупреждения")

        after = page.evaluate(r"""
        () => ({
          joke: document.querySelector('textarea[data-meme-prompt-joke]').value,
          quota: ((document.querySelector('[data-meme-quota-text]') || {})
            .textContent || '').trim(),
          card: ((document.querySelector('[data-meme-settings]') || {})
            .textContent || ''),
          scope: ((document.querySelector('.scope-trigger .scope-name') || {})
            .textContent || '').trim(),
          dirty: !!document.querySelector('[data-meme-dirty]'),
        })
        """)
        notes.append({label + "-chat-switch-after": {
            "joke": after["joke"], "quota": after["quota"],
            "scope": after["scope"]}})
        check("Чат B" in after["scope"], label,
              "область не переключилась на чат B: %r" % after["scope"])
        check(any("/api/initiative/meme-settings" in r
                  for r in STATE["requests"]), label,
              "карточка мемов не перечиталась после смены чата: %r"
              % STATE["requests"][-5:])
        check(after["joke"] == CHAT_PROMPTS[str(CHAT_B)], label,
              "после смены чата промпт не перечитан: %r" % after["joke"])
        check("0 / 3" in after["quota"], label,
              "после смены чата квота не перечитана: %r" % after["quota"])
        check(CHAT_PROMPTS[str(CHAT_A)] not in after["card"], label,
              "на экране остались данные прежнего чата (промпт A)")
        check("ЧЕРНОВИК 123" not in after["card"], label,
              "черновик чата A утёк в контекст чата B")
        check(not after["dirty"], label,
              "после смены чата остался dirty-индикатор прежнего чата")
        check(STATE["post_count"] == 0, label,
              "смена чата что-то сохранила без явной команды")
        check(not errs, label, "ошибки консоли при смене чата: %r" % errs[:2])
        shot(page, shots, "chatswitch_%s" % label)
    finally:
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    webroot = os.path.join(REPO, "web")
    httpd = serve_static(PORT, webroot)
    print("[initiative-rework-e2e] webroot =", webroot)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                run_head(browser, 1536, 960, "1536", args.shots)
                run_overview(browser, 1536, 960, "1536", args.shots)
                run_overview(browser, 1024, 900, "1024", args.shots)
                # Вторая ось композиции: все три реальные оси включены.
                STATE["axes_on"] = True
                run_overview(browser, 1536, 960, "1536-axeson", args.shots)
                STATE["axes_on"] = False
                run_text(browser, 1536, 960, "1536", args.shots)
                run_memes(browser, 1536, 960, "1536", args.shots)
                run_memes(browser, 390, 844, "390", args.shots)
                run_publications(browser, 1536, 960, "1536", args.shots)
                run_diagnostics(browser, 1536, 960, "1536", args.shots)
                run_mobile_nav(browser, 390, 844, "390", args.shots)
                run_mobile_nav(browser, 360, 740, "360", args.shots)
                run_overview(browser, 390, 844, "390", args.shots)
                run_chat_switch(browser, 1280, 900, "1280", args.shots)
            finally:
                browser.close()
    finally:
        httpd.shutdown()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"failures": failures, "notes": notes,
                       "post_body": STATE["post_body"]}, fh, ensure_ascii=False,
                      indent=1)
    print("")
    print("== Итог: failures=%d" % len(failures))
    for f in failures:
        print("  - " + f)
    if failures:
        return 1
    print("INITIATIVE-REWORK-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
