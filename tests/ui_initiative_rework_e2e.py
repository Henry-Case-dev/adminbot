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
    #: Режим осей: off | on | cooldown | delivery_unknown | foreign_chat.
    "diag_mode": "off",
    # Правки ревью на 430703be: устаревшее окно и чужой чат в ответе.
    "stale_window": False,
    "pub_foreign": False,
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


def _length_limit():
    """Потолок в шейпе выпущенной 2.58.152 (P0.5): режим приходит с сервера.

    `auto` — пусто/не задано: числа НЕТ («не задан» / «определяет провайдер»).
    `fixed` — явно заданный потолок: 400 / шаблон 5 / доступно приколу 395.
    """
    if STATE.get("length_fixed"):
        return {"ceiling": 400, "source": "model_capability", "mode": "fixed",
                "template_chars": 5, "joke_budget": 395, "known": True,
                "placeholder": "slot", "candidates": []}
    return {"ceiling": None, "source": "auto", "mode": "auto",
            "template_chars": 5, "joke_budget": None, "known": False,
            "placeholder": "slot", "candidates": []}


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
        "length_limit": _length_limit(),
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
        # P0 (§1): пять осей — та же форма, что отдаёт сборщик диагностики.
        "configuration": {"enabled": True, "source": "chat", "scope": "chat",
                          "reason": ""},
        "health": {"state": "ok", "dependencies": [
            {"name": "event_log", "state": "ok",
             "source": "initiative_observer.chat_block_state"},
            {"name": "publication_precheck", "state": "ok",
             "source": "PublicationCoordinator.precheck"}]},
        "readiness": {"state": "ready", "reason": "", "reason_class": "",
                      "next_eligible_at": None, "next_basis": "none"},
        "last_attempt": {"at": NOW - 120, "mode": "auto", "run_id": "job-77",
                         "outcome": "published", "stop_stage": "publish",
                         "incomplete_historical": False},
        "last_delivery": {"status": "confirmed", "at": NOW - 120,
                          "destination": CHAT_A, "message_id": 4321,
                          "run_id": "job-77"},
    }
    base.update(over)
    return base


def _diag(chat_id=None):
    """Диагностика двух механизмов с ПЯТЬЮ осями (как боевой сборщик).

    Ответ привязан к ЗАПРОШЕННОМУ чату (`X-Chat-Id`): у чатов разные
    идентификаторы доставки и разные попытки, поэтому переключение чата видно
    на экране. `STATE["diag_mode"]` переключает реальные состояния, на которых
    прежняя витрина лгала.
    """
    base = CHAT_A if chat_id is None else int(chat_id)
    other = CHAT_B if base == CHAT_A else CHAT_A
    is_a = base == CHAT_A
    mode = STATE.get("diag_mode") or "off"
    msg_id = 4321 if is_a else 987654
    run_id = "job-77" if is_a else "job-88"
    sent_at = NOW - 120 if is_a else NOW - 3600
    meme_over = {"last_check_ts": NOW - 60, "next_check_ts": NOW + 300,
                 # P0IM-BAN-NOETA: доказанная нижняя граница (провайдер +
                 # кулдаун), а не расписание.
                 "next_check_basis": "cooldown",
                 "cooldown": {"own_seconds": 21600,
                              "remaining_seconds": 300,
                              "basis": "last_provider_call",
                              "basis_ts": NOW - 21300,
                              "scope": "mechanism_own"},
                 "stages": {"considered": 1, "joke": 1},
                 "conditions": {"messages": 42 if is_a else 7, "quota_left": 2},
                 "last_attempt": {"at": sent_at, "mode": "auto",
                                  "run_id": run_id, "outcome": "published",
                                  "stop_stage": "publish",
                                  "incomplete_historical": False},
                 "last_delivery": {"status": "confirmed", "at": sent_at,
                                   "destination": base, "message_id": msg_id,
                                   "run_id": run_id},
                 "random": {"performed": True, "outcome": "hit", "value": 0.02,
                            "hit": True, "probability": 0.05,
                            "purpose": "trigger", "source": "quantum",
                            "selected_source": "quantum",
                            "fallback": False, "reason": ""}}
    text_over = {
        # P0IM-BAN-NOETA: проверок не было — времени не существует.
        "last_check_ts": None, "next_check_ts": None,
        "next_check_basis": "never_checked",
        "last_attempt": {"at": NOW - 120, "mode": "auto",
                         "run_id": ("corr-a" if is_a else "corr-b"),
                         "outcome": "say", "stop_stage": "initiative_sent",
                         "incomplete_historical": False},
        "last_delivery": {"status": "confirmed", "at": sent_at,
                          "destination": base,
                          "message_id": (777 if is_a else 888999),
                          "run_id": ("corr-a" if is_a else "corr-b")},
    }
    if mode == "off":
        # Явный OFF настройкой: ready=false И configuration.enabled=false.
        # Попытка и доставка остаются фактами чата (их не прячем).
        text_over.update({
            "ready": False, "ready_reason": "initiative_disabled",
            "skip": {"code": "initiative_disabled",
                     "label": "инициатива выключена", "origin": "gate"},
            "configuration": {"enabled": False, "source": "product",
                              "scope": "global", "reason": "master_off"},
            "readiness": {"state": "blocked", "reason": "initiative_disabled",
                          "reason_class": "disabled", "next_eligible_at": None,
                          "next_basis": "unknown"}})
        meme_over.update({
            "ready": False, "ready_reason": "initiative_disabled",
            "skip": {"code": "initiative_disabled",
                     "label": "инициатива выключена", "origin": "gate"},
            "configuration": {"enabled": False, "source": "product",
                              "scope": "global", "reason": "master_off"},
            "readiness": {"state": "blocked", "reason": "initiative_disabled",
                          "reason_class": "disabled", "next_eligible_at": None,
                          "next_basis": "unknown"},
            "last_attempt": {"at": NOW - 900, "mode": "auto", "run_id": "job-76",
                             "outcome": "skipped", "stop_stage": "publish",
                             "incomplete_historical": False},
            "last_delivery": {"status": "never", "at": None, "destination": None,
                              "message_id": None, "run_id": ""}})
    elif mode == "on":
        # Второй чат намеренно в другом состоянии: сравнение должно показывать
        # РАЗНИЦУ по осям, а не две одинаковые колонки.
        if not is_a:
            meme_over.update({
                "ready": False, "ready_reason": "cooldown_active",
                "skip": {"code": "cooldown_active", "label": "кулдаун",
                         "origin": "cooldown"},
                "cooldown": {"own_seconds": 21600, "remaining_seconds": 5400,
                             "basis": "last_provider_call",
                             "basis_ts": NOW - 16200, "scope": "mechanism_own"},
                "readiness": {"state": "waiting", "reason": "cooldown_active",
                              "reason_class": "cooldown",
                              "next_eligible_at": NOW + 5400,
                              "next_basis": "cooldown"}})
    elif mode == "cooldown":
        # ГЛАВНЫЙ кейс дефекта: механизм РАЗРЕШЁН, но ждёт кулдаун.
        meme_over.update({
            "ready": False, "ready_reason": "cooldown_active",
            "skip": {"code": "cooldown_active", "label": "кулдаун",
                     "origin": "cooldown"},
            "cooldown": {"own_seconds": 21600, "remaining_seconds": 3600,
                         "basis": "last_provider_call",
                         "basis_ts": NOW - 18000, "scope": "mechanism_own"},
            "configuration": {"enabled": True, "source": "chat",
                              "scope": "chat", "reason": ""},
            "readiness": {"state": "waiting", "reason": "cooldown_active",
                          "reason_class": "cooldown",
                          "next_eligible_at": NOW + 3600,
                          "next_basis": "cooldown"},
            "last_attempt": {"at": NOW - 18000, "mode": "manual",
                             "run_id": "job-80", "outcome": "published",
                             "stop_stage": "publish",
                             "incomplete_historical": False},
            "last_delivery": {"status": "confirmed", "at": NOW - 18000,
                              "destination": CHAT_A, "message_id": 555444,
                              "run_id": "job-80"}})
    elif mode == "delivery_unknown":
        meme_over.update({
            "last_attempt": {"at": NOW - 300, "mode": "auto",
                             "run_id": "job-81", "outcome": "skipped",
                             "stop_stage": "publication_stale",
                             "incomplete_historical": False},
            "last_delivery": {"status": "unknown", "at": NOW - 300,
                              "destination": base, "message_id": None,
                              "run_id": "job-81"}})
        text_over.update({
            "last_attempt": {"at": NOW - 240, "mode": "auto",
                             "run_id": "corr-9", "outcome": "silent",
                             "stop_stage": "initiative_decided",
                             "incomplete_historical": False},
            "last_delivery": {"status": "never", "at": None,
                              "destination": None, "message_id": None,
                              "run_id": ""}})
    elif mode == "expired_priority":
        # Истёкший приоритет ручного /meme — НЕ живой блок.
        meme_over.update({
            "publication": {"available": True, "coordination": "ok",
                            "degraded": False, "conflict": False,
                            "conflict_state": "none", "ok": True,
                            "reason": "", "reason_label": "", "detail": "",
                            "state": "released", "holder_kind": "meme",
                            "claimed_by": "", "other_kind": "",
                            "other_age_seconds": None, "interval_seconds": 900,
                            "manual_priority_until": NOW - 600,
                            "manual_priority_active": False,
                            "manual_priority_expired": True,
                            "claim_expires_at": NOW - 900, "checked_at": NOW},
            "readiness": {"state": "ready", "reason": "", "reason_class": "",
                          "next_eligible_at": None, "next_basis": "none"}})
    elif mode == "live_priority":
        meme_over.update({
            "publication": {"available": True, "coordination": "ok",
                            "degraded": False, "conflict": False,
                            "conflict_state": "none", "ok": True,
                            "reason": "", "reason_label": "", "detail": "",
                            "state": "claimed", "holder_kind": "meme",
                            "claimed_by": "meme", "other_kind": "",
                            "other_age_seconds": None, "interval_seconds": 900,
                            "manual_priority_until": NOW + 600,
                            "manual_priority_active": True,
                            "manual_priority_expired": False,
                            "claim_expires_at": NOW + 600, "checked_at": NOW},
            "readiness": {"state": "waiting", "reason": "publication_conflict",
                          "reason_class": "manual_priority",
                          "next_eligible_at": NOW + 600,
                          "next_basis": "manual_priority_until"}})
    elif mode == "never_called":
        # Провайдера ещё не вызывали: времени не существует (раньше тут был `now`).
        meme_over.update({
            "next_check_ts": None, "next_check_basis": "unknown",
            "cooldown": {"own_seconds": 21600, "remaining_seconds": 0,
                         "basis": "no_prior_provider_call", "basis_ts": None,
                         "scope": "mechanism_own"}})
    elif mode == "no_basis":
        # Штамп есть, основания нет: «не раньше» печатать нечем.
        meme_over.update({
            "readiness": {"state": "waiting", "reason": "cooldown_active",
                          "reason_class": "cooldown",
                          "next_eligible_at": NOW + 3600, "next_basis": ""}})
    return {
        "schema_version": 1, "generated_at": NOW,
        "chat_id": (other if mode == "foreign_chat" else base),
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
         "limit_value": 400, "events_len": 5,
         "stages": [{"stage": "summary", "outcome": "passed", "reason_code": "", "at": NOW - 12},
                    {"stage": "joke", "outcome": "passed", "reason_code": "", "at": NOW - 9},
                    {"stage": "image_generation", "outcome": "passed", "reason_code": "", "at": NOW - 5},
                    {"stage": "publish", "outcome": "published", "reason_code": "sent", "at": NOW}]},
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
        # P1/FIX 1: незнакомое событие P0 — строка ЖИВА, имя показано сырым.
        {"attempt_id": "text:U3", "kind": "text_initiative", "job_id": "U3",
         "mode": "auto", "ts": NOW - 900, "stage": "claim",
         "outcome": "other", "reason_code": "", "reason_label": "",
         "delivered": None, "message_id": None, "chain_len": 2,
         "reason_codes": ["publication_pending"],
         "other_events": [{"name": "publication_pending",
                           "outcome": "pending", "reason": ""}],
         "window_messages": None, "limit_source": "", "limit_value": None},
        # P1/FIX 1: «доставка неизвестна» — отдельный честный исход.
        {"attempt_id": "text:U4", "kind": "text_initiative", "job_id": "U4",
         "mode": "auto", "ts": NOW - 1000, "stage": "send",
         "outcome": "delivery_unknown", "reason_code": "delivery_unknown",
         "reason_label": "", "delivered": None, "message_id": None,
         "chain_len": 1, "reason_codes": ["delivery_unknown"],
         "window_messages": None, "limit_source": "", "limit_value": None},
        # P0: терминальная отмена отправки (событие `publication_cancelled`).
        {"attempt_id": "meme:job-74", "kind": "meme", "job_id": "job-74",
         "mode": "auto", "ts": NOW - 1100, "stage": "publish",
         "outcome": "cancelled", "reason_code": "publication_cancelled",
         "reason_label": "отправка отменена", "delivered": False,
         "message_id": None, "chain_len": 4,
         "reason_codes": ["publication_cancelled"],
         "window_messages": 300, "limit_source": "model_capability",
         "limit_value": 400},
        {"attempt_id": "meme:job-75", "kind": "meme", "job_id": "job-75",
         "mode": "manual", "ts": NOW - 1200, "stage": "publish",
         "outcome": "published", "reason_code": "sent",
         "reason_label": "отправлено", "delivered": True, "message_id": 4300,
         "chain_len": 4, "reason_codes": ["sent"], "window_messages": 300,
         "limit_source": "manual",
         "limit_value": None,
         "stages": [{"stage": "summary", "outcome": "passed",
                     "reason_code": "", "at": NOW - 1260},
                    {"stage": "joke", "outcome": "passed",
                     "reason_code": "", "at": NOW - 1250},
                    {"stage": "image_generation", "outcome": "passed",
                     "reason_code": "", "at": NOW - 1240},
                    {"stage": "publish", "outcome": "published",
                     "reason_code": "sent", "at": NOW - 1200}]},
        # S4-TRACE: ранний стоп ручного /meme — ошибка в конкретном шаге.
        {"attempt_id": "meme:job-72", "kind": "meme", "job_id": "job-72",
         "mode": "manual", "ts": NOW - 780, "stage": "failed",
         "outcome": "failed", "reason_code": "joke_generation_failed",
         "reason_label": "генерация прикола не удалась", "delivered": False,
         "message_id": None, "chain_len": 2,
         "reason_codes": ["joke_generation_failed"], "window_messages": 300,
         "limit_source": "model_capability", "limit_value": 400,
         "stages": [{"stage": "summary", "outcome": "passed",
                     "reason_code": "", "at": NOW - 800},
                    {"stage": "failed", "outcome": "failed",
                     "reason_code": "joke_generation_failed", "at": NOW - 780}]},
        # S4-TRACE: незнакомый код причины — читаемый фолбэк «код: …».
        {"attempt_id": "meme:job-71", "kind": "meme", "job_id": "job-71",
         "mode": "auto", "ts": NOW - 700, "stage": "failed",
         "outcome": "failed", "reason_code": "brand_new_gate",
         "reason_label": "", "delivered": False, "message_id": None,
         "chain_len": 1, "reason_codes": ["brand_new_gate"],
         "window_messages": 300, "limit_source": "model_capability",
         "limit_value": 400,
         "stages": [{"stage": "failed", "outcome": "failed",
                     "reason_code": "brand_new_gate", "at": NOW - 700}]},
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
    if attempt_id.startswith("meme:job-79"):
        # Строки прикола нет, но картинка собрана ИЗ него и отправка прошла.
        chain = [
            {"stage": "summary", "ts": NOW - 500, "outcome": "passed",
             "reason_code": "", "reason_label": "",
             "facts": {"chars": 33, "source": "chat"},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "image_generation", "ts": NOW - 480,
             "outcome": "passed", "reason_code": "", "reason_label": "",
             "facts": {"chars": 20, "template_source": "chat",
                       "template_revision": "t1", "joke_chars": 7},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "publish", "ts": NOW - 460, "outcome": "published",
             "reason_code": "sent", "reason_label": "отправлено",
             "facts": {"manual": False, "gate": "open",
                       "output": {"tg_message_id": 4400, "ledger_id": 8}},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
        ]
        events = [
            {"id": None, "ts": NOW - 500, "event_name": "digest_ready",
             "stage": "attempt", "outcome": "digest_ready", "reason_code": "",
             "reason_label": "", "detail": "chars:33", "delivered": None,
             "level": "", "error_type": ""},
            {"id": None, "ts": NOW - 480, "event_name": "image_ready",
             "stage": "attempt", "outcome": "image_ready", "reason_code": "",
             "reason_label": "", "detail": "prompt:20|bytes:900",
             "delivered": None, "level": "", "error_type": ""},
            {"id": None, "ts": NOW - 460, "event_name": "publication_sent",
             "stage": "attempt", "outcome": "publication_sent",
             "reason_code": "sent", "reason_label": "отправлено",
             "detail": "tg:4400", "delivered": True, "level": "",
             "error_type": ""},
        ]
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-79", "kind": "meme",
                            "job_id": "job-79", "mode": "auto",
                            "ts": NOW - 460, "stage": "publish",
                            "outcome": "published", "reason_code": "sent",
                            "delivered": True, "message_id": 4400},
                "chain": chain, "events": events,
                "delivery": {"delivered": True, "message_id": 4400}}
    if attempt_id.startswith("meme:job-70"):
        # R0-случай: ручной /meme убит на стадии картинки, строк журнала нет.
        return {"schema_version": 1, "available": True,
                "notes": ["no_attempt_rows"], "attempt": None,
                "chain": [], "events": [], "delivery": None}
    if attempt_id.startswith("meme:job-71"):
        # Неизвестный код причины: подпись «код: …», без выдуманного шага.
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-71", "kind": "meme",
                            "job_id": "job-71", "mode": "auto",
                            "ts": NOW - 700, "stage": "failed",
                            "outcome": "failed",
                            "reason_code": "brand_new_gate",
                            "delivered": False, "message_id": None},
                "chain": [{"stage": "failed", "ts": NOW - 700,
                           "outcome": "failed",
                           "reason_code": "brand_new_gate",
                           "reason_label": "", "facts": {},
                           "limit_source": "", "limit_value": None,
                           "window_messages": 300}],
                "events": [],
                "delivery": {"delivered": False, "message_id": None}}
    if attempt_id.startswith("meme:job-72"):
        # Ручной /meme, остановленный на приколе: ранние шаги и место стопа.
        chain = [
            {"stage": "summary", "ts": NOW - 800, "outcome": "passed",
             "reason_code": "", "reason_label": "",
             "facts": {"chars": 37, "source": "chat"},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "failed", "ts": NOW - 780, "outcome": "failed",
             "reason_code": "joke_generation_failed",
             "reason_label": "генерация прикола не удалась",
             "facts": {}, "limit_source": "model_capability",
             "limit_value": 400, "window_messages": 300},
        ]
        events = [
            {"id": None, "ts": NOW - 810, "event_name": "source_snapshot",
             "stage": "attempt", "outcome": "source_snapshot",
             "reason_code": "", "reason_label": "",
             "detail": "messages:42", "delivered": None, "level": "",
             "error_type": ""},
            {"id": None, "ts": NOW - 800, "event_name": "digest_ready",
             "stage": "attempt", "outcome": "digest_ready",
             "reason_code": "", "reason_label": "",
             "detail": "chars:37", "delivered": None, "level": "",
             "error_type": ""},
        ]
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-72", "kind": "meme",
                            "job_id": "job-72", "mode": "manual",
                            "ts": NOW - 780, "stage": "failed",
                            "outcome": "failed",
                            "reason_code": "joke_generation_failed",
                            "delivered": False, "message_id": None},
                "chain": chain, "events": events,
                "delivery": {"delivered": False, "message_id": None}}
    if attempt_id.startswith("meme:job-75"):
        # Ручной опубликованный мем: полная трасса от команды до сообщения.
        chain = [
            {"stage": "summary", "ts": NOW - 1260, "outcome": "passed",
             "reason_code": "", "reason_label": "",
             "facts": {"chars": 41, "source": "chat"},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "joke", "ts": NOW - 1250, "outcome": "passed",
             "reason_code": "", "reason_label": "",
             "facts": {"limit": 395, "template_chars": 5,
                       "ceiling": 400, "chars": 6, "trimmed": False,
                       "source": "chat", "placeholder": "slot",
                       "speech": _speech()},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "image_generation", "ts": NOW - 1240,
             "outcome": "passed", "reason_code": "", "reason_label": "",
             "facts": {"chars": 23, "template_chars": 5,
                       "joke_chars": 6, "template_source": "chat",
                       "template_revision": "t1"},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
            {"stage": "publish", "ts": NOW - 1200, "outcome": "published",
             "reason_code": "sent", "reason_label": "отправлено",
             "facts": {"manual": True, "gate": "open",
                       "claim": {"granted": True, "state": "claimed"},
                       "output": {"tg_message_id": 4300, "ledger_id": 5},
                       "source": {"chat_id": CHAT_A, "run_id": "job-75",
                                  "mode": "manual",
                                  "request_ref": "1209864",
                                  "message_count": 42,
                                  "first_id": 10, "last_id": 51,
                                  "captured_at": NOW - 1300},
                       "rights": {"mode": "permission_hook",
                                  "ok": True, "detail": ""}},
             "limit_source": "model_capability", "limit_value": 400,
             "window_messages": 300},
        ]
        events = [
            {"id": None, "ts": NOW - 1300, "event_name": "source_snapshot",
             "stage": "attempt", "outcome": "source_snapshot",
             "reason_code": "", "reason_label": "", "detail": "messages:42",
             "delivered": None, "level": "", "error_type": ""},
            {"id": None, "ts": NOW - 1260, "event_name": "digest_ready",
             "stage": "attempt", "outcome": "digest_ready",
             "reason_code": "", "reason_label": "", "detail": "chars:41",
             "delivered": None, "level": "", "error_type": ""},
            {"id": None, "ts": NOW - 1250, "event_name": "joke_ready",
             "stage": "attempt", "outcome": "joke_ready",
             "reason_code": "", "reason_label": "", "detail": "chars:6",
             "delivered": None, "level": "", "error_type": ""},
            {"id": None, "ts": NOW - 1240, "event_name": "image_ready",
             "stage": "attempt", "outcome": "image_ready",
             "reason_code": "", "reason_label": "",
             "detail": "prompt:23|bytes:1234", "delivered": None,
             "level": "", "error_type": ""},
            {"id": None, "ts": NOW - 1230, "event_name": "publication_requested",
             "stage": "attempt", "outcome": "publication_requested",
             "reason_code": "", "reason_label": "",
             "detail": "claim_requested", "delivered": None, "level": "",
             "error_type": ""},
            {"id": None, "ts": NOW - 1200, "event_name": "publication_sent",
             "stage": "attempt", "outcome": "publication_sent",
             "reason_code": "sent", "reason_label": "отправлено",
             "detail": "tg:4300", "delivered": True, "level": "",
             "error_type": ""},
        ]
        return {"schema_version": 1, "available": True, "notes": [],
                "attempt": {"attempt_id": "meme:job-75", "kind": "meme",
                            "job_id": "job-75", "mode": "manual",
                            "ts": NOW - 1200, "stage": "publish",
                            "outcome": "published", "reason_code": "sent",
                            "delivered": True, "message_id": 4300},
                "chain": chain, "events": events,
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
            # Ответ привязан к чату запроса: подмена чата видна на экране.
            return send(_diag(chat_hdr))
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
            asked_days = 7
            for part in qs.split("&"):
                if part.startswith("days="):
                    try:
                        asked_days = int(part.split("=", 1)[1])
                    except ValueError:
                        asked_days = 7
            window_days = 7 if STATE.get("stale_window") else asked_days
            return send({
                "schema_version": 1, "generated_at": NOW,
                "chat_id": (CHAT_B if STATE.get("pub_foreign") else CHAT_A),
                "available": True, "notes": [],
                "window": {"days": window_days,
                           "since": NOW - window_days * 86400, "until": NOW},
                "filters": {}, "rows": page,
                "counts": {"total": len(rows),
                           "checked": len(rows),
                           "decided": sum(1 for r in rows if r["outcome"]),
                           "text": sum(1 for r in rows
                                       if r["kind"] == "text_initiative"),
                           "meme": sum(1 for r in rows if r["kind"] == "meme"),
                           "published": sum(1 for r in rows
                                            if r["outcome"] == "published"),
                           "delivered": sum(1 for r in rows
                                            if r["delivered"] is True),
                           "pending": sum(1 for r in rows
                                          if r["outcome"] == "deferred"),
                           "delivery_unknown": sum(
                               1 for r in rows
                               if r["delivered"] is None
                               and r["outcome"] != "deferred"),
                           "not_delivered": sum(1 for r in rows
                                                if r["delivered"] is False)},
                "next_offset": (offset + len(page)) if offset + len(page) < len(rows)
                else None,
            })
        if path.endswith("/api/memory/initiative-vitality"):
            return send(_vitality())
        if path.endswith("/api/config"):
            payload = M._stub_for(url)
            if STATE.get("diag_mode") != "off":
                # Настройки ЧАТА разрешают механизм (как в жизни при кулдауне),
                # поэтому «Разрешено: ВКЛ» приходит из осей, а не из флага
                # витрины: при cooldown `ready=False`, а карточка обязана
                # остаться ВКЛ.
                for item in payload.get("items") or []:
                    if item.get("key") in ("flags.initiative_enabled",
                                           "flags.initiative_observer_enabled",
                                           "initiative.enabled"):
                        item["value"] = True
                        item["global_value"] = True
            return send(payload)
        if path.endswith("/api/status"):
            return send(_status())
        # PVR-S4: единый компонент версий запрашивает историю каждого промпта.
        # Заглушка отдаёт «действует заводская ревизия» — состояние карточки
        # (человеческая фраза) проверяется как реальный контракт.
        if "/api/prompts/" in path and path.endswith("/versions"):
            key = path.split("/api/prompts/", 1)[1][: -len("/versions")]
            return send({
                "known": True, "block_id": key, "pg_key": key,
                "scope": "global", "chat_id": None, "hidden": False,
                "manageable": True, "journal_available": True,
                "can_activate": True, "factory_revision": "fac-test",
                "sealed_revision": "fac-test", "factory_matches_active": True,
                "active": {"revision_id": "rev-fac", "origin": "factory",
                           "sha256_12": "aaaaaaaaaaaa", "chars": 10,
                           "created_at": "2026-11-03T20:42:00+00:00",
                           "source": "from_release"},
                "baseline": {"source": "factory", "baseline": None,
                             "cleared_at": None, "cleared_by": ""},
                "capabilities": {"can_assign_baseline": True,
                                 "can_clear_baseline": False,
                                 "can_restore_baseline": False,
                                 "can_copy_to_global": False},
                "entries": [], "revisions": [], "activations": [],
                "page": {"next_cursor": "", "has_more": False, "returned": 0},
                "supported_schema_compat": [],
            })
        if path.endswith("/api/access/me"):
            return send({"is_global_admin": True, "is_local_admin": True,
                         "effective_permissions": None})
        if path.endswith("/api/access/chats"):
            if STATE.get("single_chat"):
                # Честная деградация: в доступе только один чат.
                return send([
                    {"chat_id": CHAT_A, "title": "Чат A", "is_dm": False,
                     "photo_file_id": None, "access": "admin",
                     "is_active": True},
                ])
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
  // Пять осей читаются по СВОИМ узлам: одно значение не может приехать из
  // чужого механизма или из чужой оси.
  const axis = (card, name) => {
    const el = document.querySelector(
      '[data-ini-card="' + card + '"] [data-ini-axis="' + card + ':' + name + '"]');
    if (!el) return null;
    const v = el.querySelector('.ini-fact__v');
    const valueEl = v || el;
    return {
      k: strip((el.querySelector('.ini-fact__k') || {}).textContent),
      v: strip(el.textContent),
      value: strip(valueEl.textContent),
      // Обрезка: текст оси обязан помещаться в свой узел целиком.
      truncated: valueEl.scrollWidth > valueEl.clientWidth + 1,
      right: Math.round(valueEl.getBoundingClientRect().right),
      visible: valueEl.getBoundingClientRect().height > 0,
      state: el.getAttribute('data-ini-readiness')
        || el.getAttribute('data-ini-delivery') || '',
    };
  };
  const card = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const badge = el.querySelector('[data-ini-effect]');
    return {
      text: strip(el.textContent),
      badge: badge ? strip(badge.textContent) : '',
      config: badge ? badge.getAttribute('data-ini-config') : null,
      health: !!el.querySelector('[data-ini-health]'),
      axes: ['config', 'now', 'next', 'check', 'attempt', 'delivery', 'quota',
             'who'].map((name) => ({ name: name, row: axis(
               el.getAttribute('data-ini-card'), name) })),
    };
  };
  const scopeLine = document.querySelector('[data-ini-overview-scope]');
  const events = Array.from(document.querySelectorAll('[data-ini-event]'));
  const coord = document.querySelector('[data-ini-coordination]');
  const truncatedFacts = Array.from(
    document.querySelectorAll('[data-ini-card] .ini-fact__v'))
    .filter((el) => el.scrollWidth > el.clientWidth + 1).length;
  return {
    textCard: card('[data-ini-card="text"]'),
    memeCard: card('[data-ini-card="meme"]'),
    textRect: rect('[data-ini-card="text"]'),
    memeRect: rect('[data-ini-card="meme"]'),
    textEffect: strip((document.querySelector('[data-ini-effect="text"]') || {})
      .textContent),
    memeEffect: strip((document.querySelector('[data-ini-effect="meme"]') || {})
      .textContent),
    scope: {
      text: strip((scopeLine || {}).textContent),
      chat: strip((document.querySelector('[data-ini-overview-chat]') || {})
        .textContent),
      tz: strip((document.querySelector('[data-ini-overview-tz]') || {})
        .textContent),
      snapshot: strip((document.querySelector('[data-ini-overview-snapshot]') || {})
        .textContent),
      hasRefresh: !!document.querySelector('[data-ini-refresh]'),
      truncated: !!scopeLine
        && scopeLine.scrollWidth > scopeLine.clientWidth + 1,
    },
    diagError: strip((document.querySelector('[data-ini-overview-diag-error]')
      || {}).textContent),
    coord: {
      present: !!coord,
      state: coord ? coord.getAttribute('data-ini-coord-state') : null,
      label: strip((document.querySelector('[data-ini-coord-label]') || {})
        .textContent),
      event: strip((document.querySelector('[data-ini-coord-event]') || {})
        .textContent),
      text: strip((coord || {}).textContent),
    },
    events: events.map((el) => strip(el.textContent)),
    eventCount: events.length,
    attemptRefs: {
      text: ((document.querySelector('[data-ini-open-attempt="text"]') || {})
        .getAttribute ? document.querySelector('[data-ini-open-attempt="text"]')
        .getAttribute('data-ini-attempt-ref') : ''),
      meme: ((document.querySelector('[data-ini-open-attempt="meme"]') || {})
        .getAttribute ? document.querySelector('[data-ini-open-attempt="meme"]')
        .getAttribute('data-ini-attempt-ref') : ''),
    },
    hasWorkspaceOverview: !!document.querySelector('[data-workspace-overview]'),
    hasPrimary: !!document.querySelector('[data-module-primary-action]'),
    overviewH: (rect('[data-initiative-overview]') || {}).h,
    truncatedFacts: truncatedFacts,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    vw: window.innerWidth,
  };
}
"""

#: Ожидаемые формулировки пяти осей по режиму диагностики. Одна таблица —
#: одно место правды для сценариев (текст проверяется дословно по смыслу).
#: `cards` — общие фразы обеих карточек, `meme`/`text` — фразы своей карточки.
#: `coord` — показывается ли полоса координации; `forbid` — чего на экране
#: быть не должно вовсе.
AXIS_EXPECT = {
    "off": {
        "badge": "ВЫКЛ",
        "config": ["выключено", "глобальный выключатель"],
        "attempt_ref": {"text": "text:corr-a", "meme": "meme:job-76"},
        "text": {"now": ["заблокировано", "выключено настройкой"],
                 "readiness": "blocked",
                 "delivery": ["подтверждено", "сообщение 777"],
                 "delivery_state": "confirmed"},
        "meme": {"now": ["заблокировано", "выключено настройкой"],
                 "readiness": "blocked",
                 "delivery": ["ещё не доставлял"],
                 "delivery_state": "never",
                 "attempt": ["остановилось", "публикация"]},
    },
    "on": {
        "badge": "ВКЛ",
        "config": ["включено", "настройка этого чата"],
        "attempt_ref": {"text": "text:corr-a", "meme": "meme:job-77"},
        "text": {"now": ["может сработать сейчас"],
                 "next": ["точное время не назначено"],
                 "readiness": "ready",
                 "delivery": ["подтверждено", "сообщение 777"],
                 "delivery_state": "confirmed"},
        "meme": {"now": ["может сработать сейчас"],
                 "next": ["точное время не назначено"],
                 "readiness": "ready",
                 "delivery": ["подтверждено", "сообщение 4321"],
                 "delivery_state": "confirmed"},
    },
    "cooldown": {
        "badge": "ВКЛ",
        "config": ["включено", "настройка этого чата"],
        "attempt_ref": {"meme": "meme:job-80"},
        "text": {"now": ["может сработать сейчас"], "readiness": "ready"},
        "meme": {"now": ["ждёт", "кулдаун", "осталось 1 ч"],
                 "next": ["не раньше", "по собственному кулдауну"],
                 "readiness": "waiting",
                 "delivery": ["подтверждено", "сообщение 555444"],
                 "delivery_state": "confirmed",
                 "attempt": ["вручную (/meme)", "опубликовано"]},
        "forbid": ["выключено"],
    },
    "delivery_unknown": {
        "badge": "ВКЛ",
        "attempt_ref": {"text": "text:corr-9", "meme": "meme:job-81"},
        "text": {"delivery": ["ещё не доставлял"],
                 "delivery_state": "never",
                 # Блокер 5: молчание — решение бота, а не «остановка».
                 "attempt": ["бот решил промолчать"]},
        "meme": {"delivery": ["доставка неизвестна", "id сообщения нет"],
                 "delivery_state": "unknown",
                 "attempt": ["остановилось", "устаревшая бронь"]},
        "forbid": ["остановилось: решение"],
    },
    "expired_priority": {
        "badge": "ВКЛ",
        "attempt_ref": {"meme": "meme:job-77"},
        "meme": {"now": ["может сработать сейчас"], "readiness": "ready"},
        "coord": False,
        # Блокер 2: истёкший дедлайн не рисуется ни полосой, ни словом.
        "forbid": ["приоритет ручного", "отложено"],
    },
    "live_priority": {
        "badge": "ВКЛ",
        "attempt_ref": {"meme": "meme:job-77"},
        "meme": {"now": ["ждёт"], "readiness": "waiting"},
        "coord": True,
        "coord_state": "deferred",
    },
    "no_basis": {
        "badge": "ВКЛ",
        "attempt_ref": {"meme": "meme:job-77"},
        "meme": {"now": ["ждёт", "кулдаун"],
                 "next": ["основание срока не записано"],
                 "readiness": "waiting"},
        # Блокер 3: без названного основания «не раньше» не печатается.
        "forbid": ["не раньше"],
    },
}

def _axis_rows(card):
    return {row["name"]: row["row"] for row in (card or {}).get("axes") or []}


def _frags(value):
    """Ожидание — строка или список подстрок (одна ось, несколько фактов)."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def run_overview(browser, width, height, label, shots):
    STATE["requests"] = []
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page)
        data = page.evaluate(OVERVIEW_PROBE)
        notes.append({label + "-overview": {
            "scope": data["scope"], "coord": data["coord"],
            "eventCount": data["eventCount"],
            "textRect": data["textRect"], "memeRect": data["memeRect"],
            "badges": (data["textEffect"], data["memeEffect"]),
            "truncatedFacts": data["truncatedFacts"],
            "axes": {c: {r["name"]: r["row"]["value"]
                         for r in (data[c] or {}).get("axes") or []}
                     for c in ("textCard", "memeCard")}}})
        check(data["textCard"] and data["memeCard"], label,
              "нет двух карточек механизмов")
        if data["textCard"] and data["memeCard"]:
            text_rows = _axis_rows(data["textCard"])
            meme_rows = _axis_rows(data["memeCard"])
            # Обе карточки дают ВСЕ пять осей + квоту, каждая в своём узле.
            for name in ("config", "now", "next", "attempt", "delivery",
                         "quota"):
                check(text_rows.get(name), label,
                      "в карточке текста нет оси %r" % name)
                check(meme_rows.get(name), label,
                      "в карточке мемов нет оси %r" % name)
            for name in ("config", "now", "next", "attempt", "delivery"):
                row = text_rows.get(name) or {}
                check(row.get("visible"), label,
                      "ось %r текста не видна без перехода на другую вкладку"
                      % name)
                check(not row.get("truncated"), label,
                      "значение оси %r текста обрезано" % name)
                row_m = meme_rows.get(name) or {}
                check(row_m.get("visible"), label,
                      "ось %r мемов не видна" % name)
                check(not row_m.get("truncated"), label,
                      "значение оси %r мемов обрезано" % name)
            for row in list(text_rows.values()) + list(meme_rows.values()):
                check(row and row["right"] <= data["vw"] + 1, label,
                      "значение оси вышло за экран: %r" % (row,))
            check("Генерации сегодня: 1 / 3" in data["memeCard"]["text"], label,
                  "квота дня мемов не из настроек: %r"
                  % data["memeCard"]["text"][:200])

        mode = STATE.get("diag_mode") or "off"
        expect = AXIS_EXPECT.get(mode)
        notes.append({label + "-mode": mode})
        if mode == "foreign_chat":
            # Ответ чужого чата ОТБРОШЕН: карточки не показывают его данные,
            # шапка не подписана его снимком, причина названа.
            check(data["diagError"], label,
                  "ответ чужого чата не объяснён на экране")
            joined = ((data["textCard"] or {}).get("text") or "") + \
                     ((data["memeCard"] or {}).get("text") or "")
            check("555444" not in joined and "4321" not in joined, label,
                  "данные чужого чата попали в карточки: %r" % joined[:200])
            check("снимок ещё не прочитан" in data["scope"]["text"], label,
                  "снимок чужого чата подписал шапку: %r" % data["scope"])
            # Ссылка на попытку тоже не может прийти из чужого снимка.
            check(not data["attemptRefs"]["meme"]
                  and not data["attemptRefs"]["text"], label,
                  "ссылка на попытку выведена из чужого снимка: %r"
                  % data["attemptRefs"])
        elif expect:
            # Обе карточки: одно и то же «Разрешено» (одна ось конфигурации).
            for card_key, card_name in (("textCard", "текст"),
                                        ("memeCard", "мемы")):
                card = data[card_key] or {}
                rows = _axis_rows(card)
                check(card.get("badge") == expect["badge"], label,
                      "%s: «Разрешено» не %r (%r)"
                      % (card_name, expect["badge"], card.get("badge")))
                for frag in _frags(expect.get("config")):
                    check(frag in (rows.get("config") or {}).get("value", ""),
                          label, "%s: в «Разрешено» нет %r: %r"
                          % (card_name, frag,
                             (rows.get("config") or {}).get("value")))
            # Фразы своей карточки: ожидание — по механизму, а не «где-нибудь».
            for card_key, card_name, expect_key in (
                    ("textCard", "текст", "text"),
                    ("memeCard", "мемы", "meme")):
                own = expect.get(expect_key) or {}
                rows = _axis_rows(data[card_key])
                for name in ("now", "next", "attempt", "delivery"):
                    for frag in _frags(own.get(name)):
                        check(frag in (rows.get(name) or {}).get("value", ""),
                              label, "%s: в оси %r нет %r: %r"
                              % (card_name, name, frag,
                                 (rows.get(name) or {}).get("value")))
                if own.get("readiness"):
                    check((rows.get("now") or {}).get("state")
                          == own["readiness"], label,
                          "%s: готовность %r, ожидалось %r"
                          % (card_name, (rows.get("now") or {}).get("state"),
                             own["readiness"]))
                if own.get("delivery_state"):
                    check((rows.get("delivery") or {}).get("state")
                          == own["delivery_state"], label,
                          "%s: состояние доставки %r, ожидалось %r"
                          % (card_name,
                             (rows.get("delivery") or {}).get("state"),
                             own["delivery_state"]))
            if mode == "delivery_unknown":
                # Три состояния доставки не схлопываются: у текста «ещё не
                # доставлял», у мемов «доставка неизвестна» — разные строки.
                text_val = (_axis_rows(data["textCard"]).get("delivery")
                            or {}).get("value", "")
                meme_val = (_axis_rows(data["memeCard"]).get("delivery")
                            or {}).get("value", "")
                check(text_val != meme_val, label,
                      "«неизвестно» и «никогда» показаны одинаково: %r"
                      % text_val)
            # Блокер 5: в списке значимых событий нет голых машинных слов.
            joined_events = " | ".join(data.get("events") or [])
            for token in (" silent", " sent", " reply.text", " delivery_unknown"):
                check(token + " " not in joined_events + " "
                      and not joined_events.endswith(token), label,
                      "в списке событий голый токен %r: %r"
                      % (token.strip(), joined_events))
        if expect:
            # «Чего на экране быть не должно» — по всему обзору, а не по строке.
            page_text = " ".join([
                (data["textCard"] or {}).get("text", ""),
                (data["memeCard"] or {}).get("text", ""),
                data["scope"]["text"],
                (data["coord"] or {}).get("text", ""),
                " ".join(data.get("events") or []),
            ])
            for bad in expect.get("forbid") or []:
                check(bad not in page_text, label,
                      "на обзоре всё ещё есть %r: %r" % (bad, page_text[:300]))
            # Блокер 2: полоса координации — только по живому событию.
            want_coord = expect.get("coord")
            if want_coord is None:
                check(not data["coord"]["present"], label,
                      "полоса координации висит без события: %r" % data["coord"])
            elif want_coord is False:
                check(not data["coord"]["present"], label,
                      "истёкший приоритет нарисован полосой: %r" % data["coord"])
            else:
                check(data["coord"]["present"], label,
                      "живой конфликт/приоритет не показан полосой: %r"
                      % data["coord"])
                if expect.get("coord_state"):
                    check(data["coord"]["state"] == expect["coord_state"], label,
                          "состояние координации %r, ожидалось %r"
                          % (data["coord"]["state"], expect["coord_state"]))
        if expect and mode in ("off", "cooldown"):
            # ready=false НИКОГДА не рисуется как «выключено», кроме явного OFF.
            cards = (data["textCard"] or {}).get("text", "") + \
                    (data["memeCard"] or {}).get("text", "")
            if mode == "cooldown":
                check("выключено" not in cards, label,
                      "кулдаун отрисован как «выключено»")
        check(bool(data["scope"]["chat"]), label, "в шапке не назван чат")
        check(bool(data["scope"]["tz"]), label, "в шапке не назван пояс")
        check(data["scope"]["hasRefresh"], label, "нет кнопки «Обновить»")
        check(not data["scope"]["truncated"], label,
              "строка чата/пояса обрезана")
        check(data["truncatedFacts"] == 0, label,
              "обрезанных значений в карточках: %d" % data["truncatedFacts"])
        # Блокер 4: у попытки есть действие, ведущее в её трассу.
        refs = expect.get("attempt_ref") if expect else None
        if refs:
            for face in ("text", "meme"):
                if face not in refs:
                    continue
                check(data["attemptRefs"].get(face) == refs[face], label,
                      "%s: ссылка на попытку %r, ожидалась %r"
                      % (face, data["attemptRefs"].get(face), refs[face]))
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
        shot(page, shots, "overview_%s_%s" % (mode, label))
    finally:
        ctx.close()


# ── Сценарий 2b: «Показать попытку» ведёт в ЕЁ трассу (блокер 4) ──────────
def run_attempt_focus(browser, width, height, label, shots):
    STATE["diag_mode"] = "on"
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page)
        page.wait_for_selector('[data-ini-open-attempt="meme"]', timeout=15000)
        ref = page.get_attribute('[data-ini-open-attempt="meme"]',
                                 'data-ini-attempt-ref')
        check(bool(ref), label, "кнопка попытки не несёт ссылку")
        page.click('[data-ini-open-attempt="meme"]')
        page.wait_for_selector("[data-ini-trace-head]", timeout=15000)
        page.wait_for_timeout(400)
        data = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const facts = {};
          Array.from(document.querySelectorAll('[data-ini-trace-head] .ini-fact'))
            .forEach((el) => {
              facts[strip((el.querySelector('.ini-fact__k') || {}).textContent)] =
                strip((el.querySelector('.ini-fact__v') || {}).textContent);
            });
          return { href: location.hash, facts: facts,
                   outcome: strip((document.querySelector('[data-ini-trace-outcome]')
                     || {}).textContent),
                   noChat: !!document.querySelector('[data-ini-trace-nochat]') };
        }
        """)
        notes.append({label + "-attempt-focus": data})
        check("/diagnostics" in data["href"], label,
              "действие карточки не открыло «Диагностику»: %r" % data["href"])
        check(data["facts"].get("Попытка") == ref, label,
              "открыта не та попытка: %r (ждали %r)"
              % (data["facts"].get("Попытка"), ref))
        check(data["facts"].get("Механизм") == "Мемы", label,
              "вид механизма не передан: %r" % data["facts"].get("Механизм"))
        check(not data["noChat"], label, "трасса открылась без чата")
        # Блокер 5: исход в трассе — по-русски, без голого `published`.
        check(data["outcome"] == "опубликовано", label,
              "исход в трассе не переведён: %r" % data["outcome"])
        check("meme:job-77" in ref, label,
              "в ссылку попал не родитель попытки: %r" % ref)
        shot(page, shots, "attempt_focus_%s" % label)
    finally:
        ctx.close()
    STATE["diag_mode"] = "off"


# ── Сценарий 2c: смена чата очищает карточки (блокер 1) ───────────────────
def run_chat_switch_cards(browser, width, height, label, shots):
    """Заполненный обзор чата A → переключение на B → карточки не показывают A.

    Проверяется именно дефект: под шапкой «Чат B» не может висеть снимок A
    (и его message_id). После ответа B на экране появляются ЕГО идентификаторы.
    """
    STATE["diag_mode"] = "on"
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page)
        page.wait_for_selector('[data-ini-card="meme"] [data-ini-axis="meme:delivery"]',
                               timeout=15000)
        page.wait_for_timeout(500)
        before = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const val = (sel) => strip((document.querySelector(sel) || {})
            .textContent);
          return {
            scopeText: val('[data-ini-overview-scope]'),
            textDelivery: val('[data-ini-axis="text:delivery"] .ini-fact__v'),
            memeDelivery: val('[data-ini-axis="meme:delivery"] .ini-fact__v'),
            hScroll: document.documentElement.scrollWidth - window.innerWidth,
            truncated: Array.from(document.querySelectorAll(
              '[data-ini-card] .ini-fact__v'))
              .filter((el) => el.scrollWidth > el.clientWidth + 1).length,
          };
        }
        """)
        notes.append({label + "-switch-before": before})
        check("Чат A" in before["scopeText"], label,
              "в шапке не чат A: %r" % before["scopeText"])
        check("4321" in before["memeDelivery"], label,
              "обзор A пуст до переключения: %r" % before["memeDelivery"])
        check("777" in before["textDelivery"], label,
              "обзор A без доставки текста: %r" % before["textDelivery"])
        check(before["hScroll"] <= 1, label,
              "заполненный обзор A прокручивается по горизонтали: %d"
              % before["hScroll"])
        check(before["truncated"] == 0, label,
              "в заполненном обзоре A обрезаны значения: %d" % before["truncated"])
        shot(page, shots, "overview_filled_a_%s" % label)

        page.click(".scope-trigger")
        page.wait_for_selector(".scope-panel .scope-option", state="visible")
        try:
            page.click(".scope-panel .scope-option:has-text('Чат B')",
                       timeout=5000)
        except Exception:  # noqa: BLE001
            # Стеклянный слой иногда перехватывает hit-test в момент отрисовки:
            # кликаем ТОТ ЖЕ элемент его собственным DOM-кликом.
            page.eval_on_selector(
                ".scope-panel .scope-option:has-text('Чат B')",
                "el => el.click()")
        # Ни в один момент под шапкой B не должно быть данных A.
        page.wait_for_function(
            "() => { const el = document.querySelector("
            "'[data-ini-overview-scope]');"
            " return !!el && el.textContent.indexOf('Чат B') >= 0; }",
            timeout=10000)
        leaked = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const val = (sel) => strip((document.querySelector(sel) || {})
            .textContent);
          return { text: val('[data-ini-card="text"]'),
                   meme: val('[data-ini-card="meme"]'),
                   scope: val('[data-ini-overview-scope]') };
        }
        """)
        notes.append({label + "-switch-immediate": {
            "scope": leaked["scope"],
            "meme": leaked["meme"][:160]}})
        check("4321" not in leaked["meme"] and "777" not in leaked["text"],
              label,
              "под шапкой B остался снимок чата A: %r"
              % leaked["meme"][:200])

        page.wait_for_function(
            "() => { const el = document.querySelector("
            "'[data-ini-axis=\"meme:delivery\"] .ini-fact__v');"
            " return !!el && el.textContent.indexOf('987654') >= 0; }",
            timeout=15000)
        page.wait_for_timeout(400)
        after = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const val = (sel) => strip((document.querySelector(sel) || {})
            .textContent);
          return {
            scopeText: val('[data-ini-overview-scope]'),
            textDelivery: val('[data-ini-axis="text:delivery"] .ini-fact__v'),
            memeDelivery: val('[data-ini-axis="meme:delivery"] .ini-fact__v'),
            textCard: val('[data-ini-card="text"]'),
            memeCard: val('[data-ini-card="meme"]'),
            hScroll: document.documentElement.scrollWidth - window.innerWidth,
            truncated: Array.from(document.querySelectorAll(
              '[data-ini-card] .ini-fact__v'))
              .filter((el) => el.scrollWidth > el.clientWidth + 1).length,
          };
        }
        """)
        notes.append({label + "-switch-after": {
            "scope": after["scopeText"],
            "textDelivery": after["textDelivery"],
            "memeDelivery": after["memeDelivery"],
            "hScroll": after["hScroll"],
            "truncated": after["truncated"]}})
        check("Чат B" in after["scopeText"], label,
              "шапка не переключилась на B: %r" % after["scopeText"])
        check("987654" in after["memeDelivery"], label,
              "карточка мемов не показала доставку чата B: %r"
              % after["memeDelivery"])
        check("888999" in after["textDelivery"], label,
              "карточка текста не показала доставку чата B: %r"
              % after["textDelivery"])
        check("4321" not in after["memeCard"], label,
              "в карточке B остался message_id чата A")
        check("Чат A" not in after["scopeText"], label,
              "шапка одновременно называет оба чата: %r" % after["scopeText"])
        check(after["hScroll"] <= 1, label,
              "заполненный обзор B прокручивается по горизонтали: %d"
              % after["hScroll"])
        check(after["truncated"] == 0, label,
              "в заполненном обзоре B обрезаны значения: %d" % after["truncated"])
        shot(page, shots, "overview_filled_b_%s" % label)
    finally:
        ctx.close()
    STATE["diag_mode"] = "off"


# ── Сценарий 2d: P0IM-OV-HEADER — «этот / другой / сравнить» ─────────────
PEEK_PROBE = r"""
() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const val = (sel) => strip((document.querySelector(sel) || {}).textContent);
  const clipped = (root) => Array.from(
    document.querySelectorAll((root || '') + ' .ini-fact__v, ' +
                              (root || '') + ' .ini-compare__val'))
    .filter((el) => el.scrollWidth > el.clientWidth + 1).length;
  const offscreen = (root) => Array.from(
    document.querySelectorAll((root || '') + ' .ini-fact__v, ' +
                              (root || '') + ' .ini-compare__val'))
    .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
    .length;
  const groups = Array.from(
    document.querySelectorAll('[data-ini-compare-mech]')).map((g) => ({
      mech: g.getAttribute('data-ini-compare-mech'),
      title: strip((g.querySelector('.ini-compare__title') || {}).textContent),
      left: strip((g.querySelector('[data-ini-compare-chat="left"]') || {})
        .textContent),
      right: strip((g.querySelector('[data-ini-compare-chat="right"]') || {})
        .textContent),
      rows: Array.from(g.querySelectorAll('[data-ini-compare-axis]')).map((r) => ({
        axis: r.getAttribute('data-ini-compare-axis'),
        label: strip((r.querySelector('.ini-compare__label') || {}).textContent),
        left: strip((r.querySelector('[data-ini-compare-side="left"]') || {})
          .textContent),
        right: strip((r.querySelector('[data-ini-compare-side="right"]') || {})
          .textContent),
        differs: r.classList.contains('ini-compare__row--diff'),
      })),
    }));
  const cards = {};
  ['text', 'meme'].forEach((c) => {
    const root = '[data-ini-card="' + c + '"]';
    cards[c] = {
      present: !!document.querySelector(root),
      delivery: val(root + ' [data-ini-axis="' + c + ':delivery"] .ini-fact__v'),
      config: val(root + ' [data-ini-axis="' + c + ':config"] .ini-fact__v'),
      attemptBtn: !!document.querySelector(root + ' [data-ini-open-attempt]'),
    };
  });
  return {
    switchVisible: !!document.querySelector('[data-ini-switch]'),
    switchMode: (document.querySelector('[data-ini-switch]') || {}).getAttribute
      ? document.querySelector('[data-ini-switch]')
        .getAttribute('data-ini-switch-mode') : null,
    buttons: Array.from(document.querySelectorAll('[data-ini-switch-mode-btn]'))
      .map((b) => b.getAttribute('data-ini-switch-mode-btn')),
    compareBtn: !!document.querySelector('[data-ini-switch-mode-btn="compare"]'),
    comparePresent: !!document.querySelector('[data-ini-compare]'),
    compareReady: (document.querySelector('[data-ini-compare]') || {})
      .getAttribute ? document.querySelector('[data-ini-compare]')
      .getAttribute('data-ini-compare-ready') : null,
    compareWaiting: val('[data-ini-compare-waiting]'),
    peekLabel: val('[data-ini-peek-label]'),
    peekError: val('[data-ini-peek-error]'),
    scopeChat: val('[data-ini-overview-chat]'),
    cards: cards,
    groups: groups,
    clipCards: clipped('[data-ini-card]'),
    clipCompare: clipped('[data-ini-compare]'),
    offCards: offscreen('[data-ini-card]'),
    offCompare: offscreen('[data-ini-compare]'),
    hScroll: document.documentElement.scrollWidth - window.innerWidth,
    vw: window.innerWidth,
  };
}
"""


def run_peek_modes(browser, width, height, label, shots):
    """Три состояния обзора + честная деградация одним прогоном."""
    STATE["diag_mode"] = "on"
    STATE["single_chat"] = False
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page)
        page.wait_for_selector('[data-ini-switch]', timeout=15000)
        page.wait_for_timeout(500)
        base = page.evaluate(PEEK_PROBE)
        notes.append({label + "-peek-self": {
            "buttons": base["buttons"], "mode": base["switchMode"],
            "delivery": base["cards"]["meme"]["delivery"]}})
        check(base["switchVisible"], label, "нет переключателя чатов")
        check(base["buttons"] == ["self", "other", "compare"], label,
              "переключатель не из трёх состояний: %r" % (base["buttons"],))
        check(base["switchMode"] == "self", label,
              "исходное состояние не «этот чат»: %r" % base["switchMode"])
        check(not base["comparePresent"], label,
              "сравнение показано в состоянии «этот чат»")
        check("4321" in base["cards"]["meme"]["delivery"], label,
              "свой чат не показан: %r" % base["cards"]["meme"]["delivery"])

        # «Другой чат»: свои пять осей второго чата, без чисел своего.
        page.click('[data-ini-switch-mode-btn="other"]')
        page.wait_for_function(
            "() => { const el = document.querySelector("
            "'[data-ini-card=\"meme\"] [data-ini-axis=\"meme:delivery\"] .ini-fact__v');"
            " return !!el && el.textContent.indexOf('987654') >= 0; }",
            timeout=15000)
        page.wait_for_timeout(300)
        other = page.evaluate(PEEK_PROBE)
        notes.append({label + "-peek-other": {
            "mode": other["switchMode"], "label": other["peekLabel"],
            "delivery": other["cards"]["meme"]["delivery"]}})
        check(other["switchMode"] == "other", label,
              "режим не переключился: %r" % other["switchMode"])
        check("987654" in other["cards"]["meme"]["delivery"], label,
              "другой чат не показал свою доставку: %r"
              % other["cards"]["meme"]["delivery"])
        check("4321" not in other["cards"]["meme"]["delivery"], label,
              "в «другом чате» осталось число своего чата")
        check("Чат B" in other["peekLabel"], label,
              "режим не назвал, чей чат показан: %r" % other["peekLabel"])
        check(not other["cards"]["meme"]["attemptBtn"], label,
              "в чужом чате предложена ссылка на попытку своего журнала")
        check(other["hScroll"] <= 1, label,
              "«другой чат» прокручивается по горизонтали: %d" % other["hScroll"])
        check(other["clipCards"] == 0, label,
              "в «другом чате» обрезаны значения: %d" % other["clipCards"])
        shot(page, shots, "peek_other_%s" % label)

        # «Сравнить чаты»: две подписанные колонки, без третьего набора чисел.
        page.click('[data-ini-switch-mode-btn="compare"]')
        page.wait_for_selector('[data-ini-compare][data-ini-compare-ready="true"]',
                               timeout=15000)
        page.wait_for_timeout(400)
        cmp = page.evaluate(PEEK_PROBE)
        notes.append({label + "-peek-compare": {
            "mode": cmp["switchMode"], "groups": [
                {"mech": g["mech"], "left": g["left"], "right": g["right"],
                 "rows": len(g["rows"])} for g in cmp["groups"]],
            "hScroll": cmp["hScroll"], "clip": cmp["clipCompare"],
            "off": cmp["offCompare"]}})
        check(cmp["comparePresent"], label, "нет блока сравнения")
        check(len(cmp["groups"]) == 2, label,
              "сравнение не по двум механизмам: %r"
              % [g["mech"] for g in cmp["groups"]])
        check(not cmp["cards"]["text"]["present"], label,
              "в сравнении остались карточки одного чата")
        for g in cmp["groups"]:
            check(g["left"] == "Чат A" and g["right"] == "Чат B", label,
                  "колонки не подписаны чатами: %r / %r"
                  % (g["left"], g["right"]))
            check(len(g["rows"]) == 5, label,
                  "сравнение не по пяти осям (%s): %r"
                  % (g["mech"], [r["axis"] for r in g["rows"]]))
            for row in g["rows"]:
                check(bool(row["left"]) and bool(row["right"]), label,
                      "пустая ячейка сравнения: %r" % row)
        meme_rows = {r["axis"]: r for r in
                     [x for g in cmp["groups"] if g["mech"] == "meme"
                      for x in g["rows"]]}
        delivery = meme_rows.get("meme:delivery") or {}
        check("4321" in (delivery.get("left") or ""), label,
              "левая колонка не из своего payload: %r" % delivery)
        check("987654" in (delivery.get("right") or ""), label,
              "правая колонка не из payload другого чата: %r" % delivery)
        check(delivery.get("differs") is True, label,
              "расхождение значений не отмечено")
        # Разница видна и по СОСТОЯНИЮ: у мемов второй чат ждёт кулдаун.
        now_row = meme_rows.get("meme:now") or {}
        check("может сработать сейчас" in (now_row.get("left") or ""), label,
              "левая колонка «Сейчас» не своя: %r" % now_row)
        check("кулдаун" in (now_row.get("right") or ""), label,
              "правая колонка «Сейчас» не показала ожидание второго чата: %r"
              % now_row)
        check(now_row.get("differs") is True, label,
              "разные состояния чатов не отмечены как расхождение")
        # Время в обеих колонках — UTC (иначе сравнивать пришлось бы с пересчётом).
        check("UTC" in (delivery.get("left") or ""), label,
              "время левой колонки без явного пояса: %r" % delivery)
        check("UTC" in (delivery.get("right") or ""), label,
              "время правой колонки без явного пояса: %r" % delivery)
        check(cmp["hScroll"] <= 1, label,
              "сравнение прокручивается по горизонтали: %d px" % cmp["hScroll"])
        check(cmp["clipCompare"] == 0, label,
              "в сравнении обрезаны значения: %d" % cmp["clipCompare"])
        check(cmp["offCompare"] == 0, label,
              "значения сравнения вышли за экран: %d" % cmp["offCompare"])
        shot(page, shots, "peek_compare_%s" % label)

        # Возврат к своему чату: чужие числа исчезают.
        page.click('[data-ini-switch-mode-btn="self"]')
        page.wait_for_function(
            "() => { const el = document.querySelector("
            "'[data-ini-card=\"meme\"] [data-ini-axis=\"meme:delivery\"] .ini-fact__v');"
            " return !!el && el.textContent.indexOf('4321') >= 0; }",
            timeout=15000)
        back = page.evaluate(PEEK_PROBE)
        check("987654" not in back["cards"]["meme"]["delivery"], label,
              "после возврата осталось число другого чата: %r"
              % back["cards"]["meme"]["delivery"])
        check(not back["comparePresent"], label,
              "сравнение осталось на экране после возврата к своему чату")

        # Деградация: один чат в доступе — переключателя нет, ошибок нет.
        STATE["single_chat"] = True
        page.reload(wait_until="load")
        page.wait_for_selector('[data-workspace-overview]', timeout=15000)
        page.wait_for_timeout(1200)
        single = page.evaluate(PEEK_PROBE)
        notes.append({label + "-peek-single": {
            "switch": single["switchVisible"], "compare": single["compareBtn"],
            "delivery": single["cards"]["meme"]["delivery"]}})
        check(not single["switchVisible"], label,
              "при одном чате показан пустой переключатель")
        check(not single["compareBtn"], label,
              "при одном чате предложено сравнение")
        check(not single["comparePresent"], label,
              "при одном чате показан пустой блок сравнения")
        check("4321" in single["cards"]["meme"]["delivery"], label,
              "при одном чате пропали его собственные данные: %r"
              % single["cards"]["meme"]["delivery"])
        check(single["hScroll"] <= 1, label,
              "при одном чате появилась горизонтальная прокрутка")
        shot(page, shots, "peek_single_%s" % label)
    finally:
        STATE["single_chat"] = False
        STATE["diag_mode"] = "off"
        ctx.close()


# ── Сценарий 2e: S4-TRACE — строка попытки и её связная трасса ───────────
TRACE_PROBE = r"""
() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const val = (sel) => strip((document.querySelector(sel) || {}).textContent);
  const traceHost = document.querySelector('[data-ini-trace-steps]')
    || document.querySelector('[data-ini-pub-steps]');
  const steps = traceHost ? Array.from(
    traceHost.querySelectorAll('[data-ini-trace-step]')).map((el) => ({
      key: el.getAttribute('data-ini-trace-step'),
      state: el.getAttribute('data-ini-step-state'),
      text: strip(el.textContent),
    })) : [];
  const row = document.querySelector('[data-ini-pub-row]');
  return {
    hasRows: !!document.querySelector('[data-ini-pub-rows]'),
    countsText: val('[data-ini-pub-counts]'),
    windowAttr: (document.querySelector('[data-ini-pub-counts]') || {})
      .getAttribute ? document.querySelector('[data-ini-pub-counts]')
      .getAttribute('data-ini-pub-window') : null,
    chatFilter: document.querySelectorAll('[data-ini-pub-chat]').length,
    firstRun: val('[data-ini-pub-run]'),
    firstDeliverySign: ((document.querySelector('[data-ini-pub-delivery-sign]')
      || {}).getAttribute ? document.querySelector('[data-ini-pub-delivery-sign]')
      .getAttribute('data-ini-pub-delivery-sign') : ''),
    firstStages: val('[data-ini-pub-stages-row]'),
    failedStage: val('[data-ini-pub-failed-stage]'),
    trace: traceHost ? {
      kind: traceHost.getAttribute('data-ini-trace-kind'),
      norows: traceHost.getAttribute('data-ini-trace-norows'),
      status: val('[data-ini-trace-status]') || val('[data-ini-trace-status-line]'),
      stop: val('[data-ini-trace-stop]') || val('[data-ini-trace-stop-line]')
        || val('[data-ini-trace-status-line]'),
      attempt: val('[data-ini-trace-attempt]'),
      steps: steps,
    } : null,
    hScroll: document.documentElement.scrollWidth - window.innerWidth,
    overflowValues: Array.from(document.querySelectorAll(
      '.ini-trace-step__text, .ini-trace-step__code, .ini-trace-step__note, ' +
      '.ini-row__id, .ini-row__stage'))
      .filter((el) => el.scrollWidth > el.clientWidth + 1).length,
    offscreen: Array.from(document.querySelectorAll(
      '.ini-trace-step__name, .ini-trace-step__time'))
      .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
      .length,
  };
}
"""


def _step_of(trace, key):
    return next((s for s in (trace or {}).get("steps") or []
                 if s["key"] == key), None)


def run_trace(browser, width, height, label, shots):
    """Одна строка = одна попытка; клик раскрывает трассу из реальных записей."""
    STATE["diag_mode"] = "on"
    ctx, page = new_page(browser, width, height)
    try:
        # 1) «Публикации»: строка называет run id, чат, стадии и доставку.
        open_page(page, "publications")
        page.wait_for_selector("[data-ini-pub-row]", timeout=15000)
        # Сужаем журнал фильтрами ЭТОЙ поверхности (тип + исход), чтобы нужная
        # попытка была на первой странице — серверные фильтры, не клиентские.
        page.select_option('[data-ini-filter="kind"]', "meme")
        page.wait_for_timeout(500)
        page.select_option('[data-ini-filter="outcome"]', "published")
        page.wait_for_selector('[data-ini-pub-row="meme:job-75"]',
                               state="visible", timeout=20000)
        rows = page.evaluate(TRACE_PROBE)
        notes.append({label + "-trace-rows": {
            "counts": rows["countsText"], "run": rows["firstRun"],
            "delivery": rows["firstDeliverySign"],
            "stages": rows["firstStages"]}})
        check(rows["hasRows"], label, "журнал публикаций не отрисован")
        check(bool(rows["firstRun"]), label, "строка не называет идентификатор попытки")
        check(rows["windowAttr"] == "за 7 дн.", label,
              "окно счётчиков не названо: %r" % rows["windowAttr"])
        for word in ("проверено", "решено", "опубликовано", "доставлено",
                     "ожидает"):
            check(word in rows["countsText"], label,
                  "в счётчиках нет «%s»: %r" % (word, rows["countsText"]))
        check(rows["chatFilter"] >= 1, label,
              "в «Публикациях» нет фильтра по чату")
        check(rows["firstDeliverySign"] in (
            "доставлено", "не подтверждено", "не доставлялось"), label,
            "непонятный признак доставки: %r" % rows["firstDeliverySign"])
        check("→" in rows["firstStages"], label,
              "в строке нет последовательности стадий: %r" % rows["firstStages"])
        check(rows["hScroll"] <= 1, label,
              "журнал прокручивается по горизонтали: %d" % rows["hScroll"])

        # 2) Трасса опубликованного ручного /meme (job-75).
        page.click('[data-ini-pub-row="meme:job-75"]')
        page.wait_for_selector('[data-ini-pub-detail] [data-ini-trace-steps]',
                               state="attached", timeout=25000)
        page.wait_for_timeout(400)
        manual = page.evaluate(TRACE_PROBE)
        notes.append({label + "-trace-manual": {
            "status": manual["trace"]["status"], "stop": manual["trace"]["stop"],
            "steps": [(s["key"], s["state"]) for s in manual["trace"]["steps"]]}})
        check(manual["trace"] is not None, label, "трасса не раскрылась")
        check(manual["trace"]["kind"] == "meme", label,
              "вид механизма не определён: %r" % manual["trace"]["kind"])
        check(manual["trace"]["norows"] == "false", label,
              "есть записи, а трасса помечена «нет записей»")
        keys = [s["key"] for s in manual["trace"]["steps"]]
        check(keys == ["update", "permission", "command", "priority", "gates",
                       "messages", "summary", "joke", "image", "claim", "send",
                       "result"], label,
              "словарь шагов ручного мема иной: %r" % (keys,))
        upd = _step_of(manual["trace"], "update")
        check(upd and upd["state"] == "done"
              and "1209864" in upd["text"], label,
              "шаг «Получение команды» без реального id: %r" % (upd,))
        for key in ("command", "priority"):
            step = _step_of(manual["trace"], key)
            check(step and step["state"] == "unknown", label,
                  "шаг %r выдуман: %r" % (key, step))
        send = _step_of(manual["trace"], "send")
        check(send and send["state"] == "done" and "4300" in send["text"], label,
              "шаг отправки без message_id: %r" % (send,))
        check("опубликовано" in manual["trace"]["status"], label,
              "итог трассы не назван: %r" % manual["trace"]["status"])
        shot(page, shots, "trace_manual_%s" % label)

        # 3) «Диагностика»: ранний стоп, неизвестный код, отсутствие записей.
        open_tab(page, "diagnostics")
        def load(attempt, expect=None):
            page.fill("[data-ini-trace-input]", attempt)
            page.press("[data-ini-trace-input]", "Enter")
            if expect:
                page.wait_for_function(
                    "(want) => { const head = document.querySelector("
                    "'[data-ini-trace-head]');"
                    " return !!head && head.textContent.indexOf(want) >= 0; }",
                    arg=expect, timeout=15000)
            else:
                page.wait_for_function(
                    "() => { const el = document.querySelector("
                    "'[data-ini-trace-steps]');"
                    " return !!el && el.getAttribute('data-ini-trace-norows')"
                    " === 'true'; }", timeout=15000)
            page.wait_for_timeout(350)
            return page.evaluate(TRACE_PROBE)

        early = load("meme:job-72", "meme:job-72")
        notes.append({label + "-trace-early": {
            "status": early["trace"]["status"], "stop": early["trace"]["stop"],
            "steps": [(s["key"], s["state"]) for s in early["trace"]["steps"]]}})
        check(early["trace"]["norows"] == "false", label,
              "ранний стоп прочитан как «нет записей»")
        check("Прикол" in early["trace"]["stop"], label,
              "место остановки не названо: %r" % early["trace"]["stop"])
        joke = _step_of(early["trace"], "joke")
        check(joke and joke["state"] == "failed", label,
              "шаг «Прикол» не помечен ошибкой: %r" % (joke,))
        for key in ("image", "claim", "send"):
            step = _step_of(early["trace"], key)
            check(step and step["state"] == "not_run", label,
                  "шаг %r выдуман после остановки: %r" % (key, step))
        check("не выполнялось" in " ".join(
            s["text"] for s in early["trace"]["steps"]), label,
            "нет ни одного честного «не выполнялось»")
        shot(page, shots, "trace_early_%s" % label)

        odd = load("meme:job-71", "meme:job-71")
        notes.append({label + "-trace-odd": {
            "status": odd["trace"]["status"], "stop": odd["trace"]["stop"]}})
        check("код: brand_new_gate" in odd["trace"]["status"], label,
              "незнакомый код не подписан: %r" % odd["trace"]["status"])
        check("brand_new_gate " not in " ".join(
            s["text"] for s in odd["trace"]["steps"]), label,
            "голый код попал в текст шага")

        empty = load("meme:job-70")
        notes.append({label + "-trace-empty": {
            "status": empty["trace"]["status"],
            "states": sorted({s["state"] for s in empty["trace"]["steps"]})}})
        check(empty["trace"]["norows"] == "true", label,
              "попытка без записей не помечена")
        check("не запускалась" in empty["trace"]["status"], label,
              "нет честной формулировки «не запускалась»: %r"
              % empty["trace"]["status"])
        check({s["state"] for s in empty["trace"]["steps"]} == {"not_run"},
              label, "у попытки без записей выдуманы шаги: %r"
              % sorted({s["state"] for s in empty["trace"]["steps"]}))
        shot(page, shots, "trace_empty_%s" % label)

        # 4) Замеры: прокрутка и обрезка на этом же экране.
        final = page.evaluate(TRACE_PROBE)
        notes.append({label + "-trace-metrics": {
            "hScroll": final["hScroll"], "truncated": final["overflowValues"],
            "offscreen": final["offscreen"]}})
        check(final["hScroll"] <= 1, label,
              "трасса прокручивается по горизонтали: %d" % final["hScroll"])
        check(final["overflowValues"] == 0, label,
              "в трассе обрезаны значения: %d" % final["overflowValues"])
        check(final["offscreen"] == 0, label,
              "элементы трассы вышли за экран: %d" % final["offscreen"])
    finally:
        STATE["diag_mode"] = "off"
        ctx.close()


# ── Сценарий 2f: P0IM-BAN-NOETA — «Не раньше (расчёт)», а не расписание ──
def run_next_bound(browser, width, height, label, shots):
    """Строка границы: названное основание; без базиса — «нет данных»."""
    STATE["diag_mode"] = "on"
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page, "diagnostics")
        page.wait_for_timeout(600)
        # Технический блок механизмов свёрнут по умолчанию — раскрываем его.
        page.evaluate(
            "() => { const d = document.querySelector('[data-meme-diag-section]');"
            " if (d) d.open = true; }")
        page.wait_for_selector('[data-meme-diag-next="meme"]', timeout=15000)
        page.wait_for_timeout(300)
        data = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const txt = (sel) => strip((document.querySelector(sel) || {})
            .textContent);
          return {
            meme: txt('[data-meme-diag-next="meme"]'),
            memeBasis: ((document.querySelector(
              '[data-meme-diag-next="meme"]') || {}).getAttribute
              ? document.querySelector('[data-meme-diag-next="meme"]')
                .getAttribute('data-meme-diag-next-basis') : null),
            text: txt('[data-meme-diag-next="text_initiative"]'),
            pageText: strip(document.body.innerText),
            hScroll: document.documentElement.scrollWidth - window.innerWidth,
            truncated: Array.from(document.querySelectorAll(
              '[data-meme-diag-next]')).filter(
                (el) => el.scrollWidth > el.clientWidth + 1).length,
          };
        }
        """)
        notes.append({label + "-next-bound": {
            "meme": data["meme"], "basis": data["memeBasis"],
            "text": data["text"], "hScroll": data["hScroll"],
            "truncated": data["truncated"]}})
        check("не раньше" in data["meme"], label,
              "граница не названа «не раньше»: %r" % data["meme"])
        check("кулдаун" in data["meme"] and "провайдер" in data["meme"], label,
              "основание расчёта не названо: %r" % data["meme"])
        check(data["memeBasis"] == "cooldown", label,
              "основание не передано: %r" % data["memeBasis"])
        check("нет данных" in data["text"], label,
              "без базиса нет честного «нет данных»: %r" % data["text"])
        check("проверок ещё не было" in data["text"], label,
              "причина «нет данных» не названа: %r" % data["text"])
        check("Следующая проверка" not in data["pageText"], label,
              "на странице осталась строка «Следующая проверка»")
        check(data["hScroll"] <= 1, label,
              "диагностика прокручивается по горизонтали: %d" % data["hScroll"])
        check(data["truncated"] == 0, label,
              "значение границы обрезано: %d" % data["truncated"])
        shot(page, shots, "next_bound_%s" % label)

        # Провайдера ещё не вызывали: «нет данных» + причина, без времени.
        # Отдельный контекст — состояние прошлой страницы не участвует.
        STATE["diag_mode"] = "never_called"
        ctx2, page2 = new_page(browser, width, height)
        try:
            open_page(page2, "diagnostics")
            page2.wait_for_timeout(600)
            page2.evaluate(
                "() => { const d = document.querySelector("
                "'[data-meme-diag-section]'); if (d) d.open = true; }")
            page2.wait_for_selector('[data-meme-diag-next="meme"]', timeout=15000)
            page2.wait_for_timeout(300)
            never = page2.evaluate(
                "() => String((document.querySelector("
                "'[data-meme-diag-next=\"meme\"]') || {}).textContent || '')"
                ".replace(/\\s+/g, ' ').trim()")
            notes.append({label + "-next-bound-never": never})
            check("нет данных" in never, label,
                  "без вызова провайдера нет «нет данных»: %r" % never)
            check("провайдер" in never, label,
                  "причина не названа: %r" % never)
            check("не раньше" not in never, label,
                  "подставлено время без вызова провайдера: %r" % never)
            shot(page2, shots, "next_bound_never_%s" % label)
        finally:
            ctx2.close()
    finally:
        STATE["diag_mode"] = "off"
        ctx.close()


# ── Сценарий 2g: правки ревью на 430703be ────────────────────────────────
def run_review4(browser, width, height, label, shots):
    """Прикол без записи, неизвестный код, окно счётчиков, чужой чат, строка."""
    STATE["diag_mode"] = "on"
    STATE["stale_window"] = False
    STATE["pub_foreign"] = False
    ctx, page = new_page(browser, width, height)
    try:
        # (а) Строка списка: только читаемый текст, без сырых кодов.
        open_page(page, "publications")
        page.wait_for_selector("[data-ini-pub-row]", timeout=15000)
        page.wait_for_timeout(500)
        rows = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const rows = Array.from(document.querySelectorAll('[data-ini-pub-row]'))
            .map((el) => strip(el.textContent));
          return {rows: rows,
                  counts: strip((document.querySelector('[data-ini-pub-counts]')
                    || {}).textContent),
                  codes: document.querySelectorAll('.ini-row__code').length,
                  hScroll: document.documentElement.scrollWidth - window.innerWidth};
        }
        """)
        notes.append({label + "-review4-rows": {
            "rows": rows["rows"][:3], "counts": rows["counts"],
            "codes": rows["codes"]}})
        joined = " | ".join(rows["rows"])
        for raw in ("joke_generation_failed", "publication_stale",
                    " publication_conflict", " brand_new_gate"):
            check(raw.strip() + " " not in joined + " ", label,
                  "в свёрнутой строке сырой код %r: %r" % (raw, joined[:220]))
            check(" " + raw.strip() not in joined, label,
                  "в свёрнутой строке сырой код %r: %r" % (raw, joined[:220]))
        check(rows["codes"] == 0, label,
              "в строке списка остался элемент кода: %d" % rows["codes"])
        check("за 7 дн." in rows["counts"], label,
              "счётчики не назвали окно: %r" % rows["counts"])
        check("нет данных" not in rows["counts"], label,
              "счётчики пришли, а показано «нет данных»: %r" % rows["counts"])
        check(rows["hScroll"] <= 1, label,
              "журнал прокручивается по горизонтали: %d" % rows["hScroll"])

        # (б) Подпись окна — из серверного `window`, даже если фильтр другой.
        STATE["stale_window"] = True
        page.select_option('[data-ini-filter="days"]', "30")
        page.wait_for_timeout(800)
        late = page.evaluate(
            "() => String((document.querySelector('[data-ini-pub-counts]') || {})"
            ".textContent || '').replace(/\\s+/g, ' ').trim()")
        notes.append({label + "-review4-window": late[:160]})
        check("за 7 дн." in late, label,
              "окно подписано не по серверу: %r" % late[:160])
        check("за 30 дн." not in late, label,
              "поздний ответ подписан текущим фильтром: %r" % late[:160])
        STATE["stale_window"] = False
        page.select_option('[data-ini-filter="days"]', "7")
        page.wait_for_timeout(600)
        shot(page, shots, "review4_rows_%s" % label)

        # (в) Чужой чат в ответе журнала: строки не подменяются.
        STATE["pub_foreign"] = True
        page.click("[data-ini-pub-refresh]")
        page.wait_for_timeout(800)
        foreign = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          return {rows: document.querySelectorAll('[data-ini-pub-row]').length,
                  error: strip((document.querySelector('[data-ini-pub-error]')
                    || {}).textContent),
                  counts: strip((document.querySelector('[data-ini-pub-counts]')
                    || {}).textContent)};
        }
        """)
        notes.append({label + "-review4-foreign": {
            "rows": foreign["rows"], "error": foreign["error"],
            "counts": foreign["counts"][:100]}})
        # Ответ чужого чата не наполняет журнал: строки не появляются, причина
        # названа, а счётчики не подменяются числами другого чата.
        check(foreign["rows"] == 0, label,
              "строки чужого чата попали в журнал: %d" % foreign["rows"])
        check("другого чата" in foreign["error"], label,
              "отброс чужого ответа не объяснён: %r" % foreign["error"])
        check("нет данных" in foreign["counts"], label,
              "счётчики подменены ответом чужого чата: %r"
              % foreign["counts"][:120])
        STATE["pub_foreign"] = False

        # (г) Трасса: прикол без записи, но с фактом более позднего шага.
        open_tab(page, "diagnostics")
        def load(attempt, expect=None):
            page.fill("[data-ini-trace-input]", attempt)
            page.press("[data-ini-trace-input]", "Enter")
            if expect:
                page.wait_for_function(
                    "(want) => { const head = document.querySelector("
                    "'[data-ini-trace-head]');"
                    " return !!head && head.textContent.indexOf(want) >= 0; }",
                    arg=expect, timeout=15000)
            page.wait_for_timeout(350)
            return page.evaluate(TRACE_PROBE)

        nojoke = load("meme:job-79", "meme:job-79")
        joke = _step_of(nojoke["trace"], "joke")
        image = _step_of(nojoke["trace"], "image")
        notes.append({label + "-review4-nojoke": {
            "joke": (joke or {}).get("state"),
            "image": (image or {}).get("state")}})
        check(image and image["state"] == "done", label,
              "картинка не показана как выполненная: %r" % (image,))
        check(joke and joke["state"] != "not_run", label,
              "прикол назван «не выполнялось», хотя картинка собрана из него: %r"
              % (joke,))
        check("не выполнялось" not in (joke or {}).get("text", ""), label,
              "в тексте шага прикола «не выполнялось»: %r" % (joke,))

        # (д) Неизвестный код не выбирает шаг остановки.
        odd = load("meme:job-71", "meme:job-71")
        status = odd["trace"]["status"]
        notes.append({label + "-review4-unknown": status[:200]})
        check("этап остановки не определён" in status, label,
              "неизвестный код назвал этап: %r" % status[:200])
        check("Прикол" not in status, label,
              "неизвестный код угадал шаг «Прикол»: %r" % status[:200])
        check("код: brand_new_gate" in status, label,
              "читаемая подпись кода потерялась: %r" % status[:200])
        shot(page, shots, "review4_unknown_%s" % label)
    finally:
        STATE["stale_window"] = False
        STATE["pub_foreign"] = False
        STATE["diag_mode"] = "off"
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
    autoHint: !!document.querySelector('[data-meme-budget-auto]'),
    unknownHint: !!document.querySelector('[data-meme-budget-unknown]'),
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
        # P0.5 (2.58.152): пустой потолок = АВТО. Никаких 0/800/NaN, режим
        # назван прямо; подпись источника — выпущенная формулировка.
        check(data["ceiling"] == "не задан", label,
              "потолок в авто-режиме не «не задан»: %r" % data["ceiling"])
        check(data["jokeBudget"] == "определяет провайдер", label,
              "бюджет прикола в авто-режиме: %r" % data["jokeBudget"])
        check(data["template"] == "5", label,
              "длина шаблона не показана: %r" % data["template"])
        check(data["autoHint"], label,
              "нет честной подписи авто-режима (потолок не задан)")
        for bad in ("NaN", "undefined", "неизвестен"):
            check(bad not in (data["actual"] or ""), label,
                  "в блоке бюджета остался %r: %r"
                  % (bad, (data["actual"] or "")[:160]))
        check(data["unknownHint"] is False, label,
              "вернулся снятый «unknown»-режим потолка (P0.5: fixed|auto)")
        # Фиксированный потолок: те же три числа, что и раньше.
        STATE["length_fixed"] = True
        page.reload(wait_until="load")
        page.wait_for_selector("textarea[data-meme-prompt-joke]", state="visible")
        page.wait_for_timeout(700)
        fixed = page.evaluate(MEMES_PROBE)
        notes.append({label + "-memes-fixed": {
            k: fixed[k] for k in ("ceiling", "template", "jokeBudget")}})
        for key, want in (("ceiling", "400"), ("template", "5"),
                          ("jokeBudget", "395")):
            check(fixed[key] == want, label,
                  "фиксированный потолок %s = %r (ожидалось %r)"
                  % (key, fixed[key], want))
        check(not fixed["autoHint"], label,
              "подпись авто-режима осталась при фиксированном потолке")
        STATE["length_fixed"] = False
        page.reload(wait_until="load")
        page.wait_for_selector("textarea[data-meme-prompt-joke]", state="visible")
        page.wait_for_timeout(700)
        data = page.evaluate(MEMES_PROBE)
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
        # PVR-S4: источник показывается человеческой фразой в единой карточке
        # версий (сырой бейдж источника и `{joke}: N` убраны из мета-строки).
        src = page.evaluate(
            "() => { const c = document.querySelector("
            "'[data-pv-key=\"prompts.meme_image\"]');"
            " return c ? ((c.querySelector('[data-pv-state]') || {})"
            ".textContent || '').trim() : ''; }")
        check("Исходный из кода" in src, label,
              "после снятия override источник не «Исходный из кода»: %r" % src)
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
        # Ревью 430703be: в СВЁРНУТОЙ строке — только читаемый текст;
        # сырой код причины живёт только в раскрытой трассе.
        check("конфликт" in deferred["text"], label,
              "в строке нет читаемой причины конфликта: %r"
              % deferred["text"][:160])
        check("publication_deferred_conflict" not in deferred["text"], label,
              "в свёрнутой строке напечатан сырой код причины: %r"
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

        # FIX 1 (ревью 2): незнакомое событие НЕ удаляет строку и показывается
        # сырым именем; «доставка неизвестна» — отдельный исход и фильтруема.
        page.select_option('[data-ini-filter="days"]', "0")
        page.wait_for_timeout(800)
        # Догружаем страницы штатной кнопкой, пока нужные строки не появились.
        for _ in range(8):
            present = page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-ini-pub-row]'))"
                ".map((el) => el.getAttribute('data-ini-pub-row'))")
            if "text:U3" in present and "text:U4" in present:
                break
            more = page.query_selector("[data-ini-pub-more]")
            if not more:
                break
            more.click()
            page.wait_for_timeout(600)
        rows_all = page.evaluate(r"""
        () => {
          const out = {};
          Array.from(document.querySelectorAll('[data-ini-pub-row]')).forEach((el) => {
            const id = el.getAttribute('data-ini-pub-row');
            out[id] = {
              text: String(el.textContent || '').replace(/\s+/g, ' ').trim(),
              outcome: (el.querySelector('[data-ini-pub-outcome]') || {})
                .getAttribute ? el.querySelector('[data-ini-pub-outcome]')
                  .getAttribute('data-ini-pub-outcome') : null,
              badge: (el.querySelector('[data-ini-pub-outcome]') || {})
                .className || '',
              other: (el.querySelector('[data-ini-pub-other]') || {})
                .textContent ? String(el.querySelector('[data-ini-pub-other]')
                  .textContent).replace(/\s+/g, ' ').trim() : '',
            };
          });
          return out;
        }
        """)
        notes.append({label + "-other-row": rows_all.get("text:U3"),
                      label + "-unknown-row": rows_all.get("text:U4")})
        check("text:U3" in rows_all, label,
              "незнакомое событие: строки попытки нет в журнале (%r)"
              % list(rows_all)[:8])
        if "text:U3" in rows_all:
            u3 = rows_all["text:U3"]
            check(u3["outcome"] == "other", label,
                  "незнакомое событие не помечено как «other»: %r" % u3)
            check("неклассифицированное событие" in u3["text"], label,
                  "строка не названа честно: %r" % u3["text"][:140])
            check("publication_pending" in u3["other"], label,
                  "сырое имя события не показано: %r" % u3["other"])
            check("pending" in u3["other"], label,
                  "сырой outcome события не показан: %r" % u3["other"])
            check("badge-warn" not in u3["badge"], label,
                  "незнакомое событие подано как ошибка: %r" % u3["badge"])
        check("text:U4" in rows_all, label,
              "«доставка неизвестна» не появилась строкой")
        if "text:U4" in rows_all:
            check(rows_all["text:U4"]["outcome"] == "delivery_unknown", label,
                  "исход delivery_unknown не передан: %r"
                  % rows_all["text:U4"]["outcome"])
            check("доставка неизвестна" in rows_all["text:U4"]["text"], label,
                  "строка не подписана «доставка неизвестна»: %r"
                  % rows_all["text:U4"]["text"][:140])
        STATE["requests"] = []
        page.select_option('[data-ini-filter="outcome"]', "delivery_unknown")
        page.wait_for_timeout(700)
        unknown_rows = page.evaluate(
            "() => Array.from(document.querySelectorAll('[data-ini-pub-row]'))"
            ".map((el) => el.getAttribute('data-ini-pub-row'))")
        check(unknown_rows == ["text:U4"], label,
              "фильтр исхода «доставка неизвестна» вернул %r" % unknown_rows)
        page.select_option('[data-ini-filter="outcome"]', "all")
        page.wait_for_timeout(500)
        # Сырое имя события находится фильтром причины (код не потерян).
        STATE["requests"] = []
        page.fill('[data-ini-filter="reason"]', "publication_pending")
        page.press('[data-ini-filter="reason"]', "Enter")
        page.wait_for_timeout(800)
        pending_rows = page.evaluate(
            "() => Array.from(document.querySelectorAll('[data-ini-pub-row]'))"
            ".map((el) => el.getAttribute('data-ini-pub-row'))")
        check(pending_rows == ["text:U3"], label,
              "фильтр причины по сырому имени вернул %r" % pending_rows)
        page.fill('[data-ini-filter="reason"]', "")
        page.press('[data-ini-filter="reason"]', "Enter")
        page.wait_for_timeout(600)

        # P0: терминальная отмена отправки (`publication_cancelled`) — строка
        # и фильтр по причине.
        STATE["requests"] = []
        page.fill('[data-ini-filter="reason"]', "publication_cancelled")
        page.press('[data-ini-filter="reason"]', "Enter")
        page.wait_for_timeout(800)
        cancelled_rows = page.evaluate(r"""
        () => Array.from(document.querySelectorAll('[data-ini-pub-row]'))
          .map((el) => ({
            id: el.getAttribute('data-ini-pub-row'),
            outcome: (el.querySelector('[data-ini-pub-outcome]') || {})
              .getAttribute ? el.querySelector('[data-ini-pub-outcome]')
                .getAttribute('data-ini-pub-outcome') : null,
            text: String(el.textContent || '').replace(/\s+/g, ' ').trim(),
          }))
        """)
        notes.append({label + "-cancelled-row": cancelled_rows})
        check([r["id"] for r in cancelled_rows] == ["meme:job-74"], label,
              "фильтр `publication_cancelled` вернул %r" % cancelled_rows)
        if cancelled_rows:
            check(cancelled_rows[0]["outcome"] == "cancelled", label,
                  "отмена отправки не помечена cancelled: %r" % cancelled_rows[0])
            check("отменено" in cancelled_rows[0]["text"]
                  and "не доставлено" in cancelled_rows[0]["text"], label,
                  "строка отмены не читается честно: %r"
                  % cancelled_rows[0]["text"][:160])
        page.fill('[data-ini-filter="reason"]', "")
        page.press('[data-ini-filter="reason"]', "Enter")
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
    STATE["diag_mode"] = "off"
    ctx, page = new_page(browser, width, height)
    errs = []
    dialogs = []
    STATE["dialog_accept"] = True
    page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:200]))

    def _on_dialog(d):
        dialogs.append(d.message)
        if STATE.get("dialog_accept"):
            d.accept()
        else:
            d.dismiss()
    page.on("dialog", _on_dialog)
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
        # FIX 2 (ревью 2): переключение вкладки НЕ спрашивает подтверждение —
        # правки сохраняются, значит модалка «потерять их?» была бы ложью.
        open_tab(page, "overview")
        open_tab(page, "memes")
        page.wait_for_selector("textarea[data-meme-prompt-joke]", state="visible")
        page.wait_for_timeout(500)
        kept = page.evaluate(
            "() => document.querySelector('textarea[data-meme-prompt-joke]').value")
        check(kept == "ЧЕРНОВИК 123", label,
              "правка промпта потерялась при переключении вкладок: %r" % kept)
        check(not dialogs, label,
              "переключение вкладок спрашивает подтверждение (%r) — правки при "
              "этом НЕ теряются, модалка лжёт" % dialogs[:2])
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
        dialogs.clear()
        page.click(".scope-panel .scope-option:has-text('Чат B')")
        page.wait_for_timeout(1200)

        # Ровно ОДНО подтверждение — и оно правдивое.
        check(len(dialogs) == 1, label,
              "при смене чата ожидалось ровно одно подтверждение, получено %r"
              % dialogs[:3])
        if dialogs:
            msg = dialogs[0]
            check("(1)" in msg, label,
                  "в подтверждении нет числа изменённых полей: %r" % msg)
            check("(0)" not in msg, label,
                  "подтверждение показывает ложный «(0)»: %r" % msg)
            check("Сохранить настройки мемов" in msg, label,
                  "подтверждение не называет реальную кнопку сохранения: %r"
                  % msg)
            check("Чат A" in msg, label,
                  "подтверждение не называет область правки: %r" % msg)
            check("потерять" in msg.lower() or "заменит" in msg.lower(), label,
                  "подтверждение не объясняет последствие: %r" % msg)
        notes.append({label + "-chat-switch-dialog": dialogs[:1]})

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

        # Отказ в подтверждении НИЧЕГО не теряет: область остаётся чатом B,
        # набранный в чате B текст — на месте, POST нет.
        page.fill("textarea[data-meme-prompt-joke]", "ЧЕРНОВИК ЧАТА B")
        page.wait_for_timeout(300)
        dialogs.clear()
        STATE["dialog_accept"] = False
        page.click(".scope-trigger")
        page.wait_for_selector(".scope-panel .scope-option", state="visible")
        page.click(".scope-panel .scope-option:has-text('Чат A')")
        page.wait_for_timeout(1200)
        cancelled = page.evaluate(r"""
        () => ({
          value: document.querySelector('textarea[data-meme-prompt-joke]').value,
          scope: ((document.querySelector('.scope-trigger .scope-name') || {})
            .textContent || '').trim(),
          dirty: !!document.querySelector('[data-meme-dirty]'),
        })
        """)
        notes.append({label + "-chat-switch-cancel": {
            "dialogs": dialogs[:1], "after": cancelled}})
        check(len(dialogs) == 1, label,
              "отказ от смены чата: ожидалось одно подтверждение, получено %r"
              % dialogs[:2])
        check("Чат B" in cancelled["scope"], label,
              "после отказа область всё равно сменилась: %r" % cancelled["scope"])
        check(cancelled["value"] == "ЧЕРНОВИК ЧАТА B", label,
              "после отказа черновик потерян: %r" % cancelled["value"])
        check(cancelled["dirty"], label,
              "после отказа пропал индикатор несохранённых изменений")
        check(STATE["post_count"] == 0, label,
              "отказ от смены чата всё равно отправил POST")
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
                # P0 (§1/§6): состояния пяти осей на РЕАЛЬНОМ UI.
                # 1) разрешено и готово; 2) разрешено + кулдаун (главный
                # дефект: ready=false не смеет давать «выключено»);
                # 3) доставка неизвестна ≠ «ещё не доставлял»;
                # 4) истёкший приоритет /meme не блок; живой — блок;
                # 5) штамп без основания не «не раньше»;
                # 6) ответ чужого чата отброшен.
                for mode in ("on", "cooldown", "delivery_unknown",
                             "expired_priority", "live_priority", "no_basis",
                             "foreign_chat"):
                    STATE["diag_mode"] = mode
                    run_overview(browser, 1536, 960, "1536-" + mode, args.shots)
                    run_overview(browser, 390, 844, "390-" + mode, args.shots)
                STATE["diag_mode"] = "off"
                # Блокер 4: действие карточки ведёт в трассу ТОЙ ЖЕ попытки.
                run_attempt_focus(browser, 1536, 960, "1536", args.shots)
                # P0IM-OV-HEADER: три состояния обзора + честная деградация.
                run_peek_modes(browser, 1536, 960, "1536", args.shots)
                run_peek_modes(browser, 390, 844, "390", args.shots)
                # S4-TRACE: строка попытки и связная трасса (десктоп + телефон).
                run_trace(browser, 1536, 960, "1536", args.shots)
                run_trace(browser, 390, 844, "390", args.shots)
                # P0IM-BAN-NOETA: граница «не раньше», а не расписание.
                run_next_bound(browser, 1536, 960, "1536", args.shots)
                run_next_bound(browser, 390, 844, "390", args.shots)
                # Правки ревью на 430703be (трасса, журнал, строка).
                run_review4(browser, 1536, 960, "1536", args.shots)
                run_review4(browser, 390, 844, "390", args.shots)
                # Блокер 1: смена чата очищает карточки, затем показывает свои.
                run_chat_switch_cards(browser, 1536, 960, "1536", args.shots)
                run_chat_switch_cards(browser, 390, 844, "390", args.shots)
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
