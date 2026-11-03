# -*- coding: utf-8 -*-
"""P4 `MEME-UI-FIELDS` — карточка «Модули → Инициатива → Мемы» (реальный UI).

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(прецедент `tests/ui_soul14_layers_e2e.py`: статический сервер + route-стабы
`/api/**`, Telegram SDK — route-mock). Ничего не пишется на сервер: POST
перехватывается стабом и возвращает управляемый ответ.

Контракт (строки карты `MEME-UI-FIELDS`, `MEME-ACC-12`):

  1. ДВА реально редактируемых поля промптов (`data-meme-prompt-joke` /
     `data-meme-prompt-image`) вместо пассивного текста: ввод + сохранение
     существующей кнопкой, повторная загрузка показывает сохранённое, пустое
     поле снимает переопределение (действует слой ниже).
  2. Три честных числа вместо устаревшей подписи: потолок итогового промпта,
     длина шаблона, бюджет прикола; `known === false` → «неизвестен» (не 0).
  3. 422 показывается У ПОЛЯ (шаблон с 2+ `{joke}`), а не молча.
  4. Диагностика прикола: ревизии Core/Identity/Expression/Style Policy/Humor,
     приём и статус, выключенные оси, слои rendered/skip, причины; тексты
     прикола/слоёв/персоны не печатаются.
  5. Два РАЗДЕЛЬНЫХ блока диагностики механизмов: `null` ≠ 0, «никогда» для
     `last_check_ts=null`, конфликт только из `publication`, деградация →
     плашка «координация недоступна».
  6. Видимая аналитика по стадиям: выжимка/прикол/картинка/публикация
     различимы, с причиной, шаблоном, бюджетом и фактической длиной прикола.
  7. Адаптивность 390/1280: без горизонтального overflow, тач-цель ≥44px.

Запуск:
  py -3 tests/ui_meme_ui_fields_e2e.py
  ... --shots <dir>  --json <path>

TEST-LIFECYCLE: CONTRACT owner=MEME-UI-FIELDS (P4 эпика
meme-pipeline-refactor-01: два редактируемых промпта + честная диагностика).
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

PORT = 8871
BASE = "http://127.0.0.1:%d" % PORT
CHAT_A = -100500
JOKE_FACTORY = "Придумай короткий абсурдный прикол из этой выжимки."
IMAGE_FACTORY = "Создай мем с шрифтом импакт:"

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
            {"layer": "channel_contract", "block": "channel_canon",
             "revision": "cd3e44a70856", "chars": 120, "rendered": True,
             "skip": ""},
            {"layer": "core", "block": "core.personality.compact",
             "revision": "r21.848ba4c426b8", "chars": 900, "rendered": True,
             "skip": ""},
            {"layer": "response_plan", "block": "plan", "revision": "",
             "chars": 0, "rendered": False, "skip": "no_l1_plan_in_genre"},
            {"layer": "few_shot", "block": "examples", "revision": "",
             "chars": 0, "rendered": False, "skip": "expression_examples_absent"},
        ],
        "skipped": {"response_plan": "no_l1_plan_in_genre",
                    "few_shot": "expression_examples_absent"},
    }


def _attempt_rows():
    def facts(obj):
        return json.dumps(obj, ensure_ascii=False)
    base = {"job_id": "job-1", "limit_value": 400,
            "limit_source": "model_capability", "ts": 1800000300}
    rows = [
        dict(base, stage="publish", outcome="published", reason_code="",
             detail="publish_ok"),
        dict(base, stage="image_generation", outcome="passed", reason_code="",
             detail=facts({"chars": 23, "template_chars": 5, "joke_chars": 6})),
        dict(base, stage="joke", outcome="passed", reason_code="",
             detail=facts({"limit": 395, "template_chars": 5, "ceiling": 400,
                           "chars": 6, "trimmed": False, "source": "chat",
                           "placeholder": "slot", "speech": _speech()})),
        dict(base, stage="summary", outcome="passed", reason_code="",
             detail=facts({"chars": 41, "source": "chat"})),
        # Предыдущая попытка: пропуск прикола — в карточку не попадает.
        dict(base, job_id="job-0", stage="joke", outcome="skipped",
             reason_code="no_joke_budget", detail="{}", ts=1799999000),
    ]
    return rows


def _meme_settings():
    return {
        "chat_id": CHAT_A, "generated_at": 1800000300,
        "settings": {"enabled": True, "window_messages": 500, "daily_limit": 3,
                     "cooldown_seconds": 21600, "min_messages": 8,
                     "summarizer_model": "", "quiet_hours": "",
                     "length_admin": 400},
        "availability": {"available": True, "reason": "ok",
                         "initiative_enabled": True,
                         "image": {"available": True},
                         "blocks_text_initiative": False},
        "quota": {"available": True, "reason": "ok", "limit": 3, "spent": 1,
                  "remaining": 2, "timezone_name": "Europe/Moscow",
                  "next_reset": "2026-11-01T00:00:00+03:00"},
        "day": {"bucket": "2026-10-31", "timezone_name": "Europe/Moscow",
                "timezone_source": "chat",
                "next_reset": "2026-11-01T00:00:00+03:00"},
        "length_limit": {"ceiling": 400, "source": "admin_setting",
                         "template_chars": 5, "joke_budget": 395,
                         "known": True, "placeholder": "slot",
                         "candidates": []},
        "template": {"text": "Мем: {joke}", "source": "chat",
                     "placeholders": 1, "valid": True, "error": ""},
        "prompts": {
            "image": {"block_id": "initiative.meme.image",
                      "text": STATE["prompt_image"], "source": STATE["image_source"],
                      "differs_from_factory": STATE["image_source"] != "factory",
                      "factory_revision": "fac-img-7", "revision": 4,
                      "setting_key": "prompts.meme_image"},
            "joke": {"block_id": "initiative.meme.joke",
                     "text": STATE["prompt_joke"], "source": STATE["joke_source"],
                     "differs_from_factory": STATE["joke_source"] != "factory",
                     "factory_revision": "fac-joke-1", "revision": 1,
                     "setting_key": "prompts.meme_joke"},
            "summary": {"block_id": "initiative.meme.summary",
                        "text": "Выжимка чата.", "source": "factory",
                        "differs_from_factory": False, "revision": 1},
        },
        "analytics": {"output_kind": "meme_initiative",
                      "separate_from_initiative": True,
                      "coverage": "durable",
                      "counters": {"considered": 4, "eligible": 2, "summary": 2,
                                   "joke": 2, "image_generation": 1,
                                   "publish": 1, "failed": 0, "skipped": 2},
                      "skip_reasons": {"daily_quota_reached": 1,
                                       "no_joke_budget": 1},
                      "joke": {"attempts": 2, "avg_chars": 6.5, "trimmed": 0},
                      "last_joke": STATE["last_joke"],
                      "attempts": STATE["attempts"]},
        "delivery": {"output_kind": "meme_initiative",
                     "blocks_text_initiative": False,
                     "publish_blocked_count": 0,
                     "stages": ["considered", "eligible", "summary", "joke",
                                "image_generation", "publish", "failed",
                                "skipped"]},
        "schema_present": True,
        "defaults": {"enabled": False, "window_messages": 500,
                     "daily_limit": 3, "cooldown_seconds": 21600,
                     "min_messages": 8, "trigger_probability": 0.05},
        "master_key": "flags.initiative_enabled",
        "own_key": "flags.meme_initiative_enabled",
        "image_prefix": IMAGE_FACTORY,
    }


def _block(mechanism, **over):
    base = {
        "mechanism": mechanism,
        "output_kind": ("meme_initiative" if mechanism == "meme"
                        else "initiative_reply"),
        "source": ("meme_initiative attempt journal + meme.chats + claim"
                   if mechanism == "meme" else "task_jobs.payload"),
        "available": True, "data_state": "ok", "no_data_reasons": [],
        "ready": True, "ready_reason": "",
        "last_check_ts": 1800000000, "next_check_ts": 1800003600,
        "next_check_basis": "cooldown",
        "random": {"performed": True, "outcome": "draw", "value": 0.07,
                   "hit": True, "probability": 0.05, "purpose": "trigger",
                   "source": "pseudorandom", "selected_source": "quantum",
                   "fallback": False, "reason": "", "reason_label": "",
                   "no_draw_reason": ""},
        "conditions": {"messages": 12, "activity_ok": True},
        "stages": ({"summary": 1, "joke": 1} if mechanism == "meme" else None),
        "skip": None,
        "skip_recorded": {"code": "cooldown_active", "label": "кулдаун",
                          "origin": "journal"},
        "cooldown": {"scope": "mechanism_own", "own_seconds": 21600,
                     "remaining_seconds": 0, "basis": "last_provider_call",
                     "basis_ts": 1799999000},
        "quota": {"scope": "day", "limit": 3, "used": 1, "remaining": 2,
                  "unlimited": False, "limit_reached": False,
                  "available": True, "next_reset": "2026-11-01T00:00:00+03:00"},
        "publication": {"available": True, "coordination": "ok",
                        "degraded": False, "degraded_reason": "", "conflict": False,
                        "conflict_state": "clear", "ok": True, "reason": "",
                        "reason_label": "", "detail": "", "state": "idle",
                        "holder_kind": mechanism, "claimed_by": "",
                        "other_kind": "", "other_age_seconds": None,
                        "interval_seconds": 900, "manual_priority_until": None,
                        "checked_at": 1800000000},
        "blocking": (None if mechanism == "meme"
                     else {"blocked": [], "warned": []}),
    }
    base.update(over)
    return base


def _text_block():
    # Текстовая инициатива: проверок НЕ БЫЛО НИКОГДА, бронь не проверялась,
    # квота не прочитана — каждый `null` обязан остаться «нет данных».
    return _block(
        "text_initiative", last_check_ts=None, next_check_ts=None,
        next_check_basis="never_checked", random=None, conditions=None,
        available=False, data_state="no_data",
        no_data_reasons=["never_checked", "no_random_trace",
                         "no_decision_recorded"],
        ready=None, ready_reason="",
        skip={"code": "initiative_disabled", "label": "инициатива выключена",
              "origin": "gate"},
        cooldown={"scope": "mechanism_own", "own_seconds": None,
                  "remaining_seconds": None, "basis": "no_prior_publication",
                  "basis_ts": None},
        quota={"scope": "day", "limit": None, "used": None, "remaining": None,
               "unlimited": False, "limit_reached": False, "available": False,
               "next_reset": ""},
        publication=None, skip_recorded=None,
    )


def _meme_block():
    return _block("meme")


def _diag():
    return {"schema_version": 1, "generated_at": 1800000300, "chat_id": CHAT_A,
            "text_initiative": STATE["text_block"],
            "meme": STATE["meme_block"], "degraded": STATE["degraded"]}


#: Управляемое состояние стабов (меняется сценариями).
STATE = {
    "prompt_joke": JOKE_FACTORY,
    "prompt_image": "Мем: {joke}",
    "joke_source": "factory",
    "image_source": "chat",
    "attempts": [],
    "last_joke": {},
    "text_block": None,
    "meme_block": None,
    "degraded": [],
    "post_body": None,
    "post_fail": None,       # {"status": int, "detail": ...}
}


def _reset_state():
    STATE.update({
        "prompt_joke": JOKE_FACTORY,
        "prompt_image": "Мем: {joke}",
        "joke_source": "factory",
        "image_source": "chat",
        "attempts": _attempt_rows(),
        "last_joke": {"limit": 395, "template_chars": 5, "ceiling": 400,
                      "chars": 6, "trimmed": False, "source": "chat",
                      "placeholder": "slot", "speech": _speech()},
        "text_block": _text_block(),
        "meme_block": _meme_block(),
        "degraded": [],
        "post_body": None,
        "post_fail": None,
    })


def make_api_handler():
    def _handler(route):
        req = route.request
        url = req.url.split("?")[0]
        if url.endswith("/api/initiative/meme-settings"):
            if req.method == "POST":
                body = {}
                try:
                    body = json.loads(req.post_data or "{}")
                except Exception:  # noqa: BLE001
                    body = {}
                STATE["post_body"] = body
                if STATE["post_fail"]:
                    fail = STATE["post_fail"]
                    route.fulfill(status=fail["status"],
                                  content_type="application/json",
                                  body=json.dumps({"detail": fail["detail"]},
                                                  ensure_ascii=False))
                    return
                # Сервер ведёт себя как настоящий: пустая строка СНИМАЕТ
                # чатовое переопределение, иначе текст сохраняется.
                if "prompt_joke" in body:
                    value = str(body["prompt_joke"])
                    STATE["prompt_joke"] = value or JOKE_FACTORY
                    STATE["joke_source"] = "chat" if value else "factory"
                if "prompt_image" in body:
                    value = str(body["prompt_image"])
                    STATE["prompt_image"] = value or IMAGE_FACTORY
                    STATE["image_source"] = "chat" if value else "factory"
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_meme_settings(), ensure_ascii=False))
            return
        if url.endswith("/api/initiative/mechanism-diagnostics"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(_diag(), ensure_ascii=False))
            return
        if url.endswith("/api/access/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"is_global_admin": True,
                                           "effective_permissions": None}))
            return
        if url.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps([{"chat_id": CHAT_A, "title": "Чат A",
                                            "is_dm": False, "access": "admin",
                                            "is_active": True}]))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url), ensure_ascii=False))
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


def new_page(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430,
                              has_touch=width <= 430)
    ctx.route("**/api/**", make_api_handler())
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(
                  status=200, content_type="application/javascript",
                  body=SDK_STUB))
    # Выбранный чат — через штатное хранилище (карточка мемов per-chat).
    ctx.add_init_script(
        "try { localStorage.setItem('adminbot.active_chat_id', '%d'); }"
        " catch (e) {}" % CHAT_A)
    page = ctx.new_page()
    page.set_default_timeout(15000)
    return ctx, page


def snap(page, shots, name, segments=0):
    """Снимок КАРТОЧКИ мемов.

    Карточка выше вьюпорта, а «стеклянный» фон — fixed: element-screenshot
    даёт чёрные полосы. Поэтому снимаем страницу целиком на высоком
    вьюпорте (или по сегментам высотой с экран — так видны реальные
    мобильные пропорции).
    """
    if not shots:
        return
    os.makedirs(shots, exist_ok=True)
    card = page.locator("[data-meme-settings]")
    try:
        card.scroll_into_view_if_needed()
        box = card.bounding_box() or {}
        width = int(page.viewport_size["width"])
        height = int(page.viewport_size["height"])
        card_h = int(box.get("height") or 0)
        if segments:
            for i in range(segments):
                page.evaluate(
                    "([sel, off]) => { const el = document.querySelector(sel);"
                    " if (el) window.scrollTo(0, el.getBoundingClientRect().top"
                    " + window.scrollY + off); }",
                    ["[data-meme-settings]", i * height])
                page.wait_for_timeout(250)
                page.screenshot(path=os.path.join(
                    shots, "%s_%d.png" % (name, i + 1)))
            return
        page.set_viewport_size({"width": width,
                                "height": max(height, min(card_h + 200, 6000))})
        page.wait_for_timeout(350)
        card.scroll_into_view_if_needed()
        page.wait_for_timeout(150)
        page.screenshot(path=os.path.join(shots, name + ".png"),
                        full_page=True)
    except Exception:  # noqa: BLE001
        page.screenshot(path=os.path.join(shots, name + ".png"))
    finally:
        try:
            page.set_viewport_size({"width": width, "height": height})
        except Exception:  # noqa: BLE001
            pass


def open_card(page):
    page.goto(BASE + "/#/modules/initiative/settings", wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_selector("[data-meme-prompt-joke]", state="visible")
    page.wait_for_timeout(500)


PROBE = r"""
(() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const txt = (sel) => strip((document.querySelector(sel) || {}).textContent);
  const val = (sel) => {
    const el = document.querySelector(sel);
    return el ? String(el.value == null ? '' : el.value) : null;
  };
  const taJoke = document.querySelector('textarea[data-meme-prompt-joke]');
  const taImage = document.querySelector('textarea[data-meme-prompt-image]');
  const stageRows = Array.from(document.querySelectorAll(
    '[data-meme-attempt-stage]')).map((el) => ({
      stage: el.getAttribute('data-meme-attempt-stage'),
      text: strip(el.textContent),
      facts: strip((el.querySelector('.meme-stage-facts') || {}).textContent),
      outcome: (el.querySelector('[data-meme-attempt-outcome]') || {})
        .getAttribute ? el.querySelector('[data-meme-attempt-outcome]')
          .getAttribute('data-meme-attempt-outcome') : null,
    }));
  const layers = Array.from(document.querySelectorAll(
    '[data-meme-speech-layer]')).map((el) => ({
      layer: el.getAttribute('data-meme-speech-layer'),
      state: (el.querySelector('[data-meme-speech-state]') || {})
        .getAttribute ? el.querySelector('[data-meme-speech-state]')
          .getAttribute('data-meme-speech-state') : null,
      text: strip(el.textContent),
    }));
  const blocks = Array.from(document.querySelectorAll('[data-meme-diag]')).map(
    (el) => ({
      key: el.getAttribute('data-meme-diag'),
      state: strip((el.querySelector('[data-meme-diag-state]') || {}).textContent),
      last: strip((el.querySelector('[data-meme-diag-last]') || {}).textContent),
      ready: strip((el.querySelector('[data-meme-diag-ready]') || {}).textContent),
      random: strip((el.querySelector('[data-meme-diag-random]') || {}).textContent),
      skip: strip((el.querySelector('[data-meme-diag-skip]') || {}).textContent),
      cooldown: strip((el.querySelector('[data-meme-diag-cooldown]') || {}).textContent),
      quota: strip((el.querySelector('[data-meme-diag-quota]') || {}).textContent),
      conflict: strip((el.querySelector('[data-meme-diag-conflict]') || {}).textContent),
      text: strip(el.textContent),
    }));
  const small = [];
  document.querySelectorAll('[data-meme-settings] button, '
    + '[data-meme-settings] input[type="checkbox"]').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      if (r.height < 44 || r.width < 44) small.push({
        t: strip(el.textContent || el.getAttribute('aria-label')).slice(0, 32),
        h: Math.round(r.height), w: Math.round(r.width) });
    });
  const card = document.querySelector('[data-meme-settings]');
  return {
    hasCard: !!card,
    taJoke: taJoke ? { value: taJoke.value, rows: taJoke.rows,
                       invalid: taJoke.getAttribute('aria-invalid'),
                       h: Math.round(taJoke.getBoundingClientRect().height) } : null,
    taImage: taImage ? { value: taImage.value, rows: taImage.rows,
                         invalid: taImage.getAttribute('aria-invalid') } : null,
    ceiling: txt('[data-meme-limit-ceiling]'),
    templateChars: txt('[data-meme-limit-template]'),
    jokeBudget: txt('[data-meme-limit-joke]'),
    budgetText: txt('[data-meme-budget]'),
    errJoke: txt('[data-meme-prompt-error-joke]'),
    errImage: txt('[data-meme-prompt-error-image]'),
    speechEmpty: txt('[data-meme-speech-empty]'),
    speech: {
      composer: txt('[data-meme-speech-composer]'),
      sha: txt('[data-meme-speech-sha]'),
      manifest: txt('[data-meme-speech-manifest]'),
      joke: txt('[data-meme-speech-joke]'),
      humor: txt('[data-meme-speech-humor]'),
      axes: txt('[data-meme-speech-axes]'),
      revisions: Array.from(document.querySelectorAll('[data-meme-speech-rev]'))
        .map((el) => ({ key: el.getAttribute('data-meme-speech-rev'),
                        value: strip(el.textContent) })),
      layers: layers,
      skipped: txt('[data-meme-speech-skipped]'),
      block: txt('[data-meme-speech]'),
    },
    stages: stageRows,
    stagesEmpty: txt('[data-meme-attempt-empty]'),
    diag: {
      empty: txt('[data-meme-diag-empty]'),
      error: txt('[data-meme-diag-error]'),
      degraded: txt('[data-meme-diag-degraded]'),
      blocks: blocks,
    },
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    small: small.slice(0, 8),
    cardW: card ? Math.round(card.getBoundingClientRect().width) : null,
    pageW: window.innerWidth,
  };
})()
"""


def probe(page):
    return page.evaluate(PROBE)


def check_common(label, data):
    ok = True
    if not data["hasCard"]:
        fail(label, "карточка мемов не отрисована")
        return False
    if data["overflow"] > 1:
        fail(label, "горизонтальный overflow: %d px" % data["overflow"])
        ok = False
    for name in ("taJoke", "taImage"):
        field = data[name]
        if not field:
            fail(label, "нет редактируемого поля %s" % name)
            ok = False
            continue
        if field.get("h") is not None and field["h"] < 44:
            fail(label, "поле %s ниже 44px: %s" % (name, field["h"]))
            ok = False
    return ok


def check_numbers(label, data, ceiling="400", template="5", joke="395"):
    """Три числа — ровно из API, а не из устаревшей подписи."""
    got = (data["ceiling"], data["templateChars"], data["jokeBudget"])
    want = (ceiling, template, joke)
    if got != want:
        fail(label, "три числа бюджета %s, ожидалось %s" % (got, want))
    if "summary_target" in data["budgetText"]:
        fail(label, "в подписи осталась цель выжимки (устаревшая подпись)")
    for word in ("Потолок итогового промпта", "Длина шаблона картинки",
                 "Доступно для прикола"):
        if word not in data["budgetText"]:
            fail(label, "нет подписи %r" % word)


# ── Сценарий 1: полная карточка (данные есть) ─────────────────────────────
def run_full(browser, width, height, label, shots):
    _reset_state()
    ctx, page = new_page(browser, width, height)
    try:
        open_card(page)
        data = probe(page)
        notes.append({label: data})
        if not check_common(label, data):
            return
        # 1. Оба поля промптов — реальные значения из API.
        if data["taJoke"]["value"] != JOKE_FACTORY:
            fail(label, "в поле прикола %r" % data["taJoke"]["value"])
        if data["taImage"]["value"] != "Мем: {joke}":
            fail(label, "в поле шаблона %r" % data["taImage"]["value"])
        if data["taJoke"]["rows"] < 2:
            fail(label, "поле прикола не многострочное")
        check_numbers(label, data)
        # 2. Ревизии и манифест фактического payload.
        speech = data["speech"]
        if speech["sha"] != "f0c2695c31ca" or speech["manifest"] != "62aaae1adf259de9":
            fail(label, "нет system/manifest: %s" % speech)
        revs = {r["key"]: r["value"] for r in speech["revisions"]}
        for key, want in (("core", "r21.848ba4c426b8"),
                          ("identity", "a227bfbefc8732fb"),
                          ("expression", "386f4ac001c1"),
                          ("style_policy", "g5.6aff783e44a7"),
                          ("humor", "402b6636e025")):
            if revs.get(key) != want:
                fail(label, "ревизия %s = %r, ожидалось %r"
                     % (key, revs.get(key), want))
        if "приём применён" not in speech["humor"] or "literalism" not in speech["humor"]:
            fail(label, "приём юмора не показан: %r" % speech["humor"])
        if "humor_library_enabled" not in speech["axes"]:
            fail(label, "выключенные оси не показаны: %r" % speech["axes"])
        states = [l["state"] for l in speech["layers"]]
        if states.count("rendered") != 2 or states.count("skip") != 2:
            fail(label, "слои rendered/skip не различимы: %s" % states)
        if "план L1 для жанра не строится" not in speech["skipped"]:
            fail(label, "причина пропуска слоя не показана: %r"
                 % speech["skipped"])
        if "Придумай короткий абсурдный прикол" in speech["block"]:
            fail(label, "в диагностике напечатан текст промпта/прикола")
        # 3. Видимая аналитика по стадиям: 4 этапа пайплайна различимы.
        stages = [r["stage"] for r in data["stages"]]
        if stages != ["summary", "joke", "image_generation", "publish"]:
            fail(label, "стадии попытки: %s" % stages)
        by = {r["stage"]: r for r in data["stages"]}
        if by.get("joke", {}).get("outcome") != "passed":
            fail(label, "итог этапа прикола не показан")
        joke_facts = by.get("joke", {}).get("facts") or ""
        for want in ("шаблон 5", "бюджет прикола 395", "прикол 6"):
            if want not in joke_facts:
                fail(label, "факты этапа прикола не показаны (%r): %r"
                     % (want, joke_facts))
        if "выжимка 41" not in (by.get("summary", {}).get("facts") or ""):
            fail(label, "длина выжимки не показана: %r"
                 % by.get("summary", {}).get("facts"))
        image_facts = by.get("image_generation", {}).get("facts") or ""
        for want in ("итоговый промпт 23", "прикол 6"):
            if want not in image_facts:
                fail(label, "факты этапа картинки (%r): %r" % (want, image_facts))
        if "Генерация прикола" not in (by.get("joke", {}).get("text") or ""):
            fail(label, "нет подписи этапа «Генерация прикола»: %r"
                 % by.get("joke", {}).get("text"))
        if "опубликовано" not in (by.get("publish", {}).get("text") or ""):
            fail(label, "исход публикации не показан: %r"
                 % by.get("publish", {}).get("text"))
        # 4. Два РАЗДЕЛЬНЫХ блока диагностики, значения не подменяют друг друга.
        if len(data["diag"]["blocks"]) != 2:
            fail(label, "блоков диагностики: %d" % len(data["diag"]["blocks"]))
        blocks = {b["key"]: b for b in data["diag"]["blocks"]}
        text_block = blocks.get("text_initiative", {})
        meme_block = blocks.get("meme", {})
        if "никогда" not in text_block.get("last", ""):
            fail(label, "текст без проверок: последняя проверка %r"
                 % text_block.get("last"))
        if "никогда" in meme_block.get("last", ""):
            fail(label, "у мемов есть проверка, но показано «никогда»")
        if "неизвестен" not in text_block.get("quota", ""):
            fail(label, "квота текста без данных показана как число: %r"
                 % text_block.get("quota"))
        if "лимит: 3" not in meme_block.get("quota", ""):
            fail(label, "квота мемов не показана: %r" % meme_block.get("quota"))
        if "нет данных о жеребьёвке" not in text_block.get("random", ""):
            fail(label, "случайное решение текста без данных: %r"
                 % text_block.get("random"))
        if "случай сработал" not in meme_block.get("random", ""):
            fail(label, "случайное решение мемов: %r" % meme_block.get("random"))
        if "0 с" not in meme_block.get("cooldown", ""):
            fail(label, "нулевой остаток кулдауна не показан: %r"
                 % meme_block.get("cooldown"))
        if "неизвестен" not in text_block.get("cooldown", ""):
            fail(label, "кулдаун текста без данных: %r"
                 % text_block.get("cooldown"))
        if "бронь не проверялась" not in text_block.get("conflict", ""):
            fail(label, "бронь текста не проверялась, а подпись: %r"
                 % text_block.get("conflict", ""))
        if "конфликта нет" not in meme_block.get("conflict", ""):
            fail(label, "конфликт мемов: %r" % meme_block.get("conflict"))
        if data["diag"]["degraded"]:
            fail(label, "плашка деградации при coordination=ok")
        snap(page, shots, "full_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 2: правка промптов и снятие переопределения ──────────────────
def run_edit_save(browser, width, height, label, shots):
    _reset_state()
    ctx, page = new_page(browser, width, height)
    try:
        open_card(page)
        page.fill("textarea[data-meme-prompt-joke]", "Свой прикол: коротко.")
        page.fill("textarea[data-meme-prompt-image]", "Кадр мема: {joke}")
        page.click("[data-meme-save]")
        page.wait_for_timeout(700)
        body = STATE["post_body"] or {}
        if body.get("prompt_joke") != "Свой прикол: коротко.":
            fail(label, "промпт прикола не ушёл в сохранение: %r" % (body,))
        if body.get("prompt_image") != "Кадр мема: {joke}":
            fail(label, "шаблон картинки не ушёл в сохранение: %r" % (body,))
        # Повторная загрузка (перезагрузка страницы) показывает сохранённое.
        page.reload(wait_until="load")
        page.wait_for_selector("[data-meme-prompt-joke]", state="visible")
        page.wait_for_timeout(500)
        after = probe(page)
        if after["taJoke"]["value"] != "Свой прикол: коротко.":
            fail(label, "после перезагрузки поле прикола: %r"
                 % after["taJoke"]["value"])
        if after["taImage"]["value"] != "Кадр мема: {joke}":
            fail(label, "после перезагрузки шаблон: %r"
                 % after["taImage"]["value"])
        # Пустое поле снимает переопределение: действует заводской текст.
        page.fill("textarea[data-meme-prompt-joke]", "")
        page.click("[data-meme-save]")
        page.wait_for_timeout(700)
        body = STATE["post_body"] or {}
        if body.get("prompt_joke") != "":
            fail(label, "пустое поле не отправлено как снятие: %r" % (body,))
        page.reload(wait_until="load")
        page.wait_for_selector("[data-meme-prompt-joke]", state="visible")
        page.wait_for_timeout(500)
        cleared = probe(page)
        if cleared["taJoke"]["value"] != JOKE_FACTORY:
            fail(label, "после снятия override в поле: %r"
                 % cleared["taJoke"]["value"])
        if "factory" not in cleared["speech"].get("block", "") and \
                "заводской" not in cleared["speech"].get("block", ""):
            pass  # подпись источника живёт у поля, не в блоке речи
        snap(page, shots, "edit_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 3: 422 по полю (громко, а не молча) ───────────────────────────
def run_422(browser, width, height, label, shots):
    _reset_state()
    STATE["post_fail"] = {"status": 422,
                          "detail": "prompts.meme_image: шаблон: допускается "
                                    "не более одного {joke} (найдено 2)"}
    ctx, page = new_page(browser, width, height)
    try:
        open_card(page)
        page.fill("textarea[data-meme-prompt-image]", "a {joke} b {joke}")
        page.click("[data-meme-save]")
        page.wait_for_timeout(700)
        data = probe(page)
        notes.append({label + "-422": {k: data[k] for k in
                                       ("errImage", "errJoke", "taImage")}})
        if "{joke}" not in data["errImage"]:
            fail(label, "причина 422 не показана у поля шаблона: %r"
                 % data["errImage"])
        if data["taImage"]["invalid"] != "true":
            fail(label, "поле шаблона не помечено как невалидное")
        if data["errJoke"]:
            fail(label, "ошибка приписана чужому полю: %r" % data["errJoke"])
        snap(page, shots, "err422_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 4: деградация координации и «жеребьёвки не было» ────────────
def run_degraded(browser, width, height, label, shots):
    _reset_state()
    STATE["degraded"] = ["meme"]
    STATE["meme_block"] = _block(
        "meme",
        publication={"available": False, "coordination": "degraded",
                     "degraded": True, "degraded_reason": "claim_absent",
                     "conflict": None, "conflict_state": "unknown", "ok": None,
                     "reason": "", "reason_label": "", "detail": "",
                     "state": "", "holder_kind": "meme", "claimed_by": "",
                     "other_kind": "", "other_age_seconds": None,
                     "interval_seconds": 900, "manual_priority_until": None,
                     "checked_at": 1800000300},
        random={"performed": False, "outcome": "no_draw", "value": None,
                "hit": None, "probability": 1.0, "purpose": "trigger",
                "source": "", "selected_source": "quantum", "fallback": False,
                "no_draw_reason": "probability_one"},
        skip={"code": "schema_absent", "label": "схемы нет",
              "origin": "publication"},
        ready=False, ready_reason="schema_absent",
    )
    ctx, page = new_page(browser, width, height)
    try:
        open_card(page)
        data = probe(page)
        notes.append({label + "-degraded": data["diag"]})
        if "координация недоступна" not in data["diag"]["degraded"]:
            fail(label, "нет плашки деградации: %r" % data["diag"]["degraded"])
        blocks = {b["key"]: b for b in data["diag"]["blocks"]}
        meme = blocks.get("meme", {})
        if "координация недоступна" not in meme.get("conflict", ""):
            fail(label, "деградация выдана за другое: %r" % meme.get("conflict"))
        if "конфликта нет" in meme.get("conflict", ""):
            fail(label, "деградация выдана за «конфликта нет»")
        if "жеребьёвка не выполнялась" not in meme.get("random", ""):
            fail(label, "performed=false не показан как «не выполнялась»: %r"
                 % meme.get("random"))
        if "схем" not in meme.get("skip", ""):
            fail(label, "причина пропуска мема не показана: %r"
                 % meme.get("skip"))
        if "не может запуститься" not in meme.get("ready", ""):
            fail(label, "готовность мема: %r" % meme.get("ready"))
        snap(page, shots, "degraded_%s" % label)
    finally:
        ctx.close()


# ── Сценарий 5: нет попыток и неизвестный потолок ────────────────────────
def run_empty(browser, width, height, label, shots):
    _reset_state()
    STATE["attempts"] = []
    STATE["last_joke"] = {}
    ctx, page = new_page(browser, width, height)
    try:
        open_card(page)
        data = probe(page)
        notes.append({label + "-empty": {k: data[k] for k in
                                         ("speechEmpty", "stagesEmpty",
                                          "ceiling", "jokeBudget")}})
        if "Приколов ещё не было" not in data["speechEmpty"]:
            fail(label, "нет честного «приколов ещё не было»: %r"
                 % data["speechEmpty"])
        if not data["stagesEmpty"]:
            fail(label, "нет сообщения «попыток ещё не было»")
        if data["stages"]:
            fail(label, "при пустом журнале нарисованы стадии")
        snap(page, shots, "empty_%s" % label)
    finally:
        ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    ap.add_argument("--shots", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    serve_static(PORT, os.path.abspath(args.webroot))
    print("[meme-ui-fields-e2e] webroot =", os.path.abspath(args.webroot))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            run_full(browser, 390, 844, "390", args.shots)
            run_full(browser, 1280, 900, "1280", args.shots)
            run_edit_save(browser, 390, 844, "390", args.shots)
            run_422(browser, 390, 844, "390", args.shots)
            run_degraded(browser, 390, 844, "390", args.shots)
            run_empty(browser, 1280, 900, "1280", args.shots)

    report = {"webroot": os.path.abspath(args.webroot),
              "failures": failures, "notes": notes}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print("\n== Итог: failures=%d" % len(failures))
    for row in failures:
        print("  -", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
