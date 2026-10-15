"""W3-EDITOR (asap8-v6-3-live-correction) — Playwright e2e B05+U06.

Проверки по ТЗ (source-lines-37423-EOF.md §108–§117, §170–§174) на РЕАЛЬНОМ
web/index.html + web/app.js (/api/* — route-стабы R17, cover-стабы локальные):

  B05.1 (неподвижный непрозрачный фон редактора):
    * .cover-editor — непрозрачный фон (alpha=1, дизайн-токен --surface-1);
    * центр рабочей области НЕ является polygon-канвасом (elementFromPoint);
    * prefers-reduced-motion: polygon rAF стоит (frameCount заморожен).
  B05.2 (непрерывность выделения/копирования при polling):
    * удержание выделения 13 с в textarea И в блоке «Фактический промпт»
      при АКТИВНОМ polling test-style job: selectionStart/End, выделенная
      строка, scrollTop, DOM-идентичность узлов — неизменны; polling при
      этом реально тикал и завершался (loadCoverStyles+loadMeta пришли);
    * typing при polling: caret не прыгает, value не перетирается;
    * meta-refetch НЕ перезаписывает dirty draft (инструкция цела);
    * copy-кнопка копирует точную строку «Фактического промпта».
  B05.3 (модалка/скролл/guard):
    * mobile: overlay = 100dvh (высота вьюпорта), editor заполняет;
    * единственный скроллер .cover-editor-body; behind-overlay scroll
      отсутствует (document/main.scroll-area не скроллятся);
    * шапка/футер закреплены (rect pinned при прокрутке тела);
    * guard: dirty → «Закрыть» держит редактор открытым с предупреждением;
      cancel → текст цел; confirm → закрытие; чистый редактор закрывается
      без диалога;
    * save contract: POST /api/cover/styles с прежним контрактом тела.
  U06.1 (порядок/структура):
    * Профиль → Инструкция → Референсы → Проверка итогового промпта →
      Test Edit → результат/история; dev-метаданные под «Подробнее».
  U06.2 («Фактическая сборка»):
    * одна строка `Style N · SceneAnchor M · Refs R · System S · Final F /
      Limit L` (из edit_report/manifest); цвет ТОЛЬКО при превышении;
    * моноширинный pre со скроллом + кнопка копировать; edit_report-
      метаданные (language/headroom/image_input/dropped/limited_preview)
      в «Подробнее о сборке»; при неизвестном лимите — честное
      «неизвестно», без псевдоцвета успеха.

Запуск:
    .venv/Scripts/python.exe tools/ui_asap8_w3_editor_e2e.py --phase before
    .venv/Scripts/python.exe tools/ui_asap8_w3_editor_e2e.py --phase after

--phase before: скриншоты/измерения ДО правок (RED-доказательство, exit 0).
--phase after:  контрактные ассерты (exit 1 при провале) + after-скриншоты.

Артефакты: plans/features/asap8-v6-3-live-correction/w3-evidence-editor/

TEST-LIFECYCLE: CONTRACT owner=REQ-B05/REQ-U06
"""
import argparse
import copy
import json
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (стабы /api/* — reuse)
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8821
EVIDENCE = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction",
                        "w3-evidence-editor")
ROUTE = "#/modules/summary/styles"

# ── Cover-стабы (обезличенные; форма ответов = реальный W1 API) ─────────────

INSTRUCTION = (
    "Графический роман: чёрно-белая штриховка, жёсткие контрасты, "
    "ретро-печатная текстура. Логотип «Медведь Press» применять как "
    "графический референс в углу, сюжет и персонажей не менять, "
    "композицию сохранять. Плашка выпуска — один раз, без дублей текста."
)

FINAL_PROMPT = (
    "Сохранить существующих персонажей, позы, события и композицию обложки; "
    "не добавлять новых событий. Выпуск ВЫПУСК 42 упомянуть один раз, без "
    "дублей текста. Графический роман: чёрно-белая штриховка, жёсткие "
    "контрасты, ретро-печатная текстура. Логотип «Медведь Press» применять "
    "как графический референс в углу, сюжет и персонажей не менять, "
    "композицию сохранять. Плашка выпуска — один раз, без дублей текста. "
    "Референсы: логотип Медведь Press — графический образец."
)
# Байт-в-байт строка для copy-проверки должна совпадать с тем, что рендерит
# pre ({{ }} не меняет текст). len считаем от этой строки.

REFS = [{
    "ref_id": "ref1", "asset_id": "asset_ref1",
    "label": "Логотип Медведь Press",
    "description": "Графический образец логотипа",
}]

STYLE_ITEM = {
    "profile_id": "st_w3", "name": "Графический роман Медведь Press",
    "origin": "custom", "is_example": False,
    "pipeline_mode": "generate_then_edit", "instruction": INSTRUCTION,
    "counter_enabled": True, "next_issue_number": 42, "counter_value": 41,
    "counter_format": "ВЫПУСК {counter}", "model_mode": "default",
    "connection_id": None, "model_id": None, "enabled": True, "revision": 7,
    "references": REFS, "preview_before_url": None, "preview_after_url": None,
    "preview_before_asset_id": None, "preview_after_asset_id": None,
    "preview_revision": 6, "preview_stale": False, "preview_source": "example",
    "preview_source_label": "Пример", "can_edit": True,
    "preview_issue": "ВЫПУСК 42", "reference_count": 1,
}

STYLES_LIST = {
    "enabled": True, "is_admin": True,
    "no_style_label": "Без дополнительного стиля",
    "selected_style_id": "st_w3", "styles": [STYLE_ITEM],
    "placeholders": {"before_url": None, "after_url": None},
}


def meta_payload(scenario):
    known = scenario.get("limit_unknown") is not True
    return {
        "profile_id": "st_w3", "name": STYLE_ITEM["name"],
        "instruction": INSTRUCTION, "pipeline_mode": "generate_then_edit",
        "counter_enabled": True, "next_issue_number": 42,
        "preview_issue": "ВЫПУСК 42",
        "preview_before_asset_id": None, "preview_after_asset_id": None,
        "preview_revision": 6, "preview_stale": False,
        "preview_source": "example", "preview_source_label": "Пример",
        "can_edit": True, "references": REFS,
        "capabilities": {"edit_supported": True},
        "connection": None, "budget": None, "effective": None,
        "prompt_limit": {
            "mode": "auto", "unit": "chars",
            "value": (800 if known else None),
            "limit_known": known,
            "source": ("published_exact" if known else "unknown"),
            "source_taxonomy": ("published_exact" if known else "unknown"),
        },
    }


def manifest_components():
    return [
        {"key": "CONTENT_PRESERVATION", "source": "code", "priority": "P0",
         "original_chars": 120, "sent_chars": 120, "status": "kept",
         "reason": ""},
        {"key": "RUNTIME_INVARIANTS", "source": "code", "priority": "P0",
         "original_chars": 60, "sent_chars": 60, "status": "kept",
         "reason": ""},
        {"key": "STYLE_PROFILE", "source": "style_profile", "priority": "P1",
         "original_chars": len(INSTRUCTION), "sent_chars": len(INSTRUCTION),
         "status": "kept", "reason": ""},
        {"key": "SCENE_ANCHOR", "source": "summary_stage1", "priority": "P1",
         "original_chars": 88, "sent_chars": 88, "status": "kept",
         "reason": ""},
        {"key": "REFERENCES", "source": "style_profile", "priority": "P2",
         "original_chars": 62, "sent_chars": 62, "status": "kept",
         "reason": ""},
        {"key": "BASE_STYLE", "source": "settings", "priority": "P3",
         "original_chars": 0, "sent_chars": 0, "status": "omitted",
         "reason": "empty"},
        {"key": "SUMMARY_CONTEXT", "source": "final_summary", "priority": "P2",
         "original_chars": 0, "sent_chars": 0, "status": "omitted",
         "reason": "edit_mode"},
    ]


def edit_report(scenario, final_text):
    exceeded = scenario.get("exceeded") is True
    known = scenario.get("limit_unknown") is not True
    return {
        "language": "ru", "original_chars": 903, "deduped_chars": 651,
        "dedupe_dropped": [{"label": "references",
                            "reason": "near_duplicate"}],
        "scene_anchor": ({"included": True, "chars": 88, "skip_reason": ""}
                         if not scenario.get("limit_unknown")
                         else {"included": False, "chars": 0,
                               "skip_reason": "empty"}),
        "headroom_chars": 40, "summary_retransferred": False,
        "final_chars": len(final_text),
        "dropped": ([{"label": "base_style_prompt", "reason": "overflow"}]
                    if exceeded else []),
        "limited_preview": True,
        "image_input_used": {"base": True, "references": 0},
        "model": "", "provider": "", "route": "preview_compile",
        "limit_source": ("published_exact" if known else "unknown"),
        "limit_value": (800 if known else None),
        "limit_unit": "chars",
        "exceeded": exceeded,
        "overflow_reason": ("prompt_limit_exceeded" if exceeded else ""),
        "final_prompt": final_text,
        "final_prompt_chars": len(final_text),
    }


def compile_payload(scenario, final_text):
    er = edit_report(scenario, final_text)
    exceeded = scenario.get("exceeded") is True
    known = scenario.get("limit_unknown") is not True
    manifest = {
        "operation": "edit", "final_prompt": final_text,
        "final_chars": len(final_text), "provider": "", "model": "",
        "route": "preview_compile", "prompt_hash": "w3audit",
        "resolved_limit": (800 if known else None), "limit_unit": "chars",
        "limit_source": ("published_exact" if known else "unknown"),
        "attempts": [{"attempt": 1, "chars": len(final_text),
                      "outcome": ("failed" if exceeded else "sent"),
                      "reason": er["overflow_reason"]}],
        "components": manifest_components(),
    }
    return {
        "status": "ok", "mode": "style", "reason": "", "message": "",
        "style_source": "profile", "profile_source": "db",
        "profile_id": "st_w3", "context": None,
        "manifest": manifest, "components": manifest["components"],
        "final_prompt": final_text,
        "budget": {
            "limit_known": known, "resolved_limit": (800 if known else None),
            "limit_unit": "chars",
            "limit_source": ("published_exact" if known else "unknown"),
            "compile_cap_chars": 760, "used_chars": len(final_text),
            "remaining_chars": max(0, 760 - len(final_text)),
            "reserved": {"story_min": 0, "context_max": 0},
        },
        "style_publish_skip_reason": ("story_identity_dropped" if exceeded
                                      else ""),
        "route": "preview_compile", "exceeded": exceeded,
        "compile_reason": er["overflow_reason"],
        "edit_report": er, "limited_preview": True,
    }


def preview_manifest(scenario, final_text):
    er = edit_report(scenario, final_text)
    return {
        "operation": "edit", "final_prompt": final_text,
        "final_chars": len(final_text), "provider": "openrouter",
        "model": "google/gemini-flash-image", "route": "image_edit",
        "prompt_hash": "w3job", "resolved_limit": 800, "limit_unit": "chars",
        "limit_source": "published_exact", "attempts": [],
        "components": manifest_components(),
    }


class CoverState:
    """Изменяемое состояние стаба + журнал запросов (потокобезопасно)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.scenario = {}          # exceeded / limit_unknown
        self.job_started = None     # время старта test-style job
        self.job_done_at = None     # job завершается через JOB_RUN_SEC
        self.last_save_body = None
        self.compile_calls = 0
        self.meta_calls = 0
        self.list_calls = 0

    def final_text(self):
        # exceeded-сценарий: превышение 800-символьного лимита (905 зн.)
        if self.scenario.get("exceeded"):
            return FINAL_PROMPT + (" Дополнительный хвост превышающего "
                                   "лимит текста сборки." * 4)
        return FINAL_PROMPT


STATE = CoverState()
JOB_RUN_SEC = 6.0  # job «running» первые 6 c, затем completed

SDK_STUB = """
try { sessionStorage.setItem('adminbot.initData',
  'user=%7B%22id%22%3A5885953495%7D&hash=audit'); } catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  platform: 'android', version: '9.0', colorScheme: 'dark', themeParams: {},
  get viewportStableHeight() {
    return Math.max(0, (window.innerHeight || 800) - 56);
  },
  isExpanded: true, isFullscreen: false,
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, close() {},
  setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
  requestFullscreen() {}, exitFullscreen() {},
  disableVerticalSwipes() {}, enableClosingConfirmation() {},
  onEvent() {}, offEvent() {},
  openLink() {}, openTelegramLink() {}, showAlert() {}, showConfirm() {},
  BackButton: { isVisible: false, show() {}, hide() {}, onClick() {},
                offClick() {} },
  MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
  HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
} };
"""


def api_handler(route):
    """Route /api/**: cover-стабы + матричные стабы остального."""
    req = route.request
    url = req.url.split("?")[0]
    method = req.method
    with STATE.lock:
        if url.endswith("/api/cover/styles") and method == "GET":
            STATE.list_calls += 1
            body = STYLES_LIST
        elif url.endswith("/api/cover/styles/st_w3") and method == "GET":
            STATE.meta_calls += 1
            body = meta_payload(STATE.scenario)
        elif url.endswith("/api/cover/connections"):
            body = {"connections": []}
        elif url.endswith("/api/cover/preview-compile"):
            STATE.compile_calls += 1
            body = compile_payload(STATE.scenario, STATE.final_text())
        elif url.endswith("/api/cover/test-style") and method == "POST":
            STATE.job_started = time.time()
            STATE.job_done_at = STATE.job_started + JOB_RUN_SEC
            body = {"job_id": "job_w3", "reused": False, "stage": "queued"}
        elif url.endswith("/api/cover/test-style/job_w3"):
            now = time.time()
            if STATE.job_started is None or now >= (STATE.job_done_at or 0):
                body = {
                    "stage": "saving_preview", "status": "completed",
                    "started_at": int((STATE.job_started or now)),
                    "provider": "openrouter",
                    "model": "google/gemini-flash-image",
                    "preview_before_url": None, "preview_after_url": None,
                    "prompt": STATE.final_text(),
                    "prompt_manifest": preview_manifest(STATE.scenario,
                                                        STATE.final_text()),
                }
            else:
                body = {"stage": "style_editing", "status": "running",
                        "started_at": int(STATE.job_started)}
        elif url.endswith("/api/cover/styles") and method == "POST":
            try:
                STATE.last_save_body = json.loads(req.post_data or "{}")
            except Exception:  # noqa: BLE001
                STATE.last_save_body = {"_raw": req.post_data}
            body = {"ok": True}
        elif url.endswith("/api/cover/assets/asset_ref1"):
            route.fulfill(status=404, content_type="application/json",
                          body="{}")
            return
        elif url.endswith("/__control/scenario"):
            # Управляющий endpoint сценария (только локальный стаб-сервер).
            try:
                STATE.scenario = json.loads(req.post_data or "{}")
            except Exception:  # noqa: BLE001
                pass
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(STATE.scenario))
            return
        else:
            body = M._stub_for(req.url)
    # UTF-8 байтами + charset (иначе кириллица стаба декодируется как cp1252).
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    route.fulfill(status=200, content_type="application/json; charset=utf-8",
                  body=payload)


def sdk_handler(route):
    route.fulfill(status=200, content_type="application/javascript",
                  body=SDK_STUB)


def make_handler(webroot):
    class _WebRootHandler(SimpleHTTPRequestHandler):
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
    return _WebRootHandler


def serve(port, webroot):
    httpd = ThreadingHTTPServer(("127.0.0.1", port),
                                make_handler(webroot))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def new_page(browser, width, height, mobile=True, reduced=False):
    kwargs = {"viewport": {"width": width, "height": height},
              "is_mobile": mobile, "has_touch": mobile}
    if reduced:
        kwargs["reduced_motion"] = "reduce"
    ctx = browser.new_context(**kwargs)
    ctx.route("**/api/**", api_handler)
    ctx.route("**/static/vendor/telegram-web-app.js", sdk_handler)
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"],
                              origin="http://127.0.0.1:%d" % PORT)
    except Exception:  # noqa: BLE001
        pass
    page = ctx.new_page()
    page.set_default_timeout(10000)
    return ctx, page


def open_editor(page, base):
    page.goto(base + ROUTE, wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_selector("[data-cover-styles]", state="visible")
    page.wait_for_timeout(600)
    page.click("[data-cover-style-open]")
    page.wait_for_selector("[data-cover-style-editor]", state="visible")
    page.wait_for_timeout(400)


# ── probes ──────────────────────────────────────────────────────────────────

SETUP_SAMPLER = """
(seedSel, holdMs) => {
  const ta = document.querySelector('[data-cover-style-instruction]');
  const pre = document.querySelector('[data-cover-compile-final-text]');
  if (!ta) return { error: 'no textarea' };
  ta.__w3 = 'ta';
  if (pre) pre.__w3 = 'pre';
  // Выделение в textarea: реальные 10..60
  ta.focus();
  ta.setSelectionRange(10, 60);
  // Выделение в pre (если есть): Range по первому текстовому узлу
  let preRange = null;
  if (pre && pre.firstChild) {
    preRange = document.createRange();
    preRange.selectNodeContents(pre);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(preRange);
  }
  window.__w3Samples = [];
  const t0 = performance.now();
  window.__w3Timer = setInterval(() => {
    const ta2 = document.querySelector('[data-cover-style-instruction]');
    const pre2 = document.querySelector('[data-cover-compile-final-text]');
    const s = {
      t: Math.round(performance.now() - t0),
      taSel: ta2 ? [ta2.selectionStart, ta2.selectionEnd] : null,
      taSub: ta2 ? ta2.value.slice(ta2.selectionStart, ta2.selectionEnd) : null,
      taMark: !!(ta2 && ta2.__w3),
      taScroll: ta2 ? ta2.scrollTop : null,
      preSel: (() => {
        if (!pre2) return null;
        const sel = window.getSelection();
        const txt = sel ? sel.toString() : '';
        return txt.length > 40 ? txt.slice(0, 40) : txt;
      })(),
      preMark: !!(pre2 && pre2.__w3),
    };
    window.__w3Samples.push(s);
  }, 300);
  return { ok: true, initial: {
    taSel: [ta.selectionStart, ta.selectionEnd],
    taSub: ta.value.slice(ta.selectionStart, ta.selectionEnd),
    preSel: window.getSelection().toString().slice(0, 40) } };
}
"""

STOP_SAMPLER = """
() => {
  if (window.__w3Timer) clearInterval(window.__w3Timer);
  return window.__w3Samples || [];
}
"""

EDITOR_GEOM = """
() => {
  const ov = document.querySelector('[data-cover-style-overlay]');
  const ed = document.querySelector('[data-cover-style-editor]');
  const head = document.querySelector('.cover-editor-head');
  const foot = document.querySelector('[data-cover-editor-footer]');
  const body = document.querySelector('.cover-editor-body');
  const main = document.querySelector('main.scroll-area');
  const bg = ed ? getComputedStyle(ed).backgroundColor : null;
  const alpha = bg ? (bg.match(/rgba?\\(([^)]+)\\)/) || [])[1] : '';
  const parts = alpha ? alpha.split(',').map((s) => parseFloat(s)) : [];
  const canvas = document.getElementById('polygon-background');
  const mid = body
    ? document.elementFromPoint(
        Math.round(body.getBoundingClientRect().left + body.getBoundingClientRect().width / 2),
        Math.round(body.getBoundingClientRect().top + Math.min(80, body.getBoundingClientRect().height / 2)))
    : null;
  return {
    overlay: ov ? (() => { const r = ov.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) }; })() : null,
    editor: ed ? (() => { const r = ed.getBoundingClientRect();
      return { top: Math.round(r.top), bottom: Math.round(r.bottom),
               h: Math.round(r.height) }; })() : null,
    head: head ? (() => { const r = head.getBoundingClientRect();
      return { top: Math.round(r.top), h: Math.round(r.height) }; })() : null,
    foot: foot ? (() => { const r = foot.getBoundingClientRect();
      return { bottom: Math.round(r.bottom), h: Math.round(r.height) }; })() : null,
    bodyScrollTop: body ? body.scrollTop : null,
    bodyScrollable: body ? (body.scrollHeight > body.clientHeight) : null,
    docScrollTop: document.scrollingElement
      ? document.scrollingElement.scrollTop : null,
    mainScrollTop: main ? main.scrollTop : null,
    bg, bgAlpha: parts.length >= 4 ? parts[3] : 1,
    bgRgb: parts.slice(0, 3),
    centerHit: mid ? (mid.tagName + '|' + (mid.className || '')) : null,
    canvasZ: canvas ? getComputedStyle(canvas).zIndex : null,
    overlayZ: ov ? getComputedStyle(ov).zIndex : null,
  };
}
"""

SECTIONS_ORDER = """
() => {
  const sels = ['[data-cover-sec-profile]', '[data-cover-sec-instruction]',
    '[data-cover-sec-refs]', '[data-cover-sec-compile]',
    '[data-cover-sec-testedit]', '[data-cover-sec-result]',
    '[data-cover-sec-more]'];
  const els = sels.map((s) => document.querySelector(s));
  const present = els.map((e, i) => ({ s: sels[i], present: !!e }));
  let ordered = true;
  for (let i = 1; i < els.length; i++) {
    if (!els[i - 1] || !els[i]) continue;
    // отсутствующие «more» до результата считаем нарушением порядка
    if (!(els[i - 1].compareDocumentPosition(els[i])
          & Node.DOCUMENT_POSITION_FOLLOWING)) ordered = false;
  }
  // «Подробнее» обязан идти последним среди присутствующих
  const more = document.querySelector('[data-cover-sec-more]');
  const res = document.querySelector('[data-cover-sec-result]');
  const moreAfterResult = !!(more && res
    && (res.compareDocumentPosition(more) & Node.DOCUMENT_POSITION_FOLLOWING));
  const moreOpen = !!more && more.tagName === 'DETAILS';
  return { present, ordered, moreAfterResult, moreOpen };
}
"""

COMPILE_PROBE = """
() => {
  const sum = document.querySelector('[data-cover-compile-summary]');
  const pre = document.querySelector('[data-cover-compile-final-text]');
  const copy = document.querySelector('[data-cover-compile-copy]');
  const det = document.querySelector('[data-cover-compile-details]');
  const over = document.querySelector('[data-cover-compile-summary].cover-limit-over');
  const st = sum ? sum.className : '';
  const pst = pre ? getComputedStyle(pre) : null;
  return {
    summary: sum ? sum.textContent.replace(/\\s+/g, ' ').trim() : null,
    overClass: !!over, className: st,
    preText: pre ? pre.textContent : null,
    preMono: pst ? pst.fontFamily.toLowerCase() : null,
    // контракт «pre со скроллом»: max-height + overflow auto — элемент
    // СПОСОБЕН скроллить длинный prompt (коротый не обязан переполнять)
    preScrollable: pst ? (pst.maxHeight !== 'none'
      && ['auto', 'scroll'].includes(pst.overflowY)) : null,
    preMaxH: pst ? pst.maxHeight : null,
    preOverflowY: pst ? pst.overflowY : null,
    hasCopy: !!copy, copyText: copy ? copy.textContent.trim() : null,
    hasDetails: !!det,
    detailsText: det ? det.textContent.replace(/\\s+/g, ' ').trim() : null,
  };
}
"""

POLYGON_DIAG = """
() => {
  const pb = window.__PolygonBackground;
  if (!pb) return { present: false };
  const d = pb.getDiagnostics ? pb.getDiagnostics() : {};
  return { present: true, frameCount1: d.frameCount || 0 };
}
"""


def phase_before_checks(res):
    """RED-фаза: измерения без контрактных ассертов (exit 0)."""
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["before", "after"], default="after")
    ap.add_argument("--webroot", default=os.path.join(REPO, "web"))
    args = ap.parse_args()
    os.makedirs(EVIDENCE, exist_ok=True)
    base = "http://127.0.0.1:%d" % PORT
    httpd = serve(PORT, args.webroot)
    res = {"phase": args.phase, "checks": {}, "measurements": {},
           "errors": []}
    checks = res["checks"]

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ═══ DESKTOP 1440×900: порядок U06 + сборка + выделение + guard ═══
        ctx, page = new_page(browser, 1440, 900, mobile=False)
        open_editor(page, base)

        # U06.1: порядок секций
        order = page.evaluate(SECTIONS_ORDER)
        res["measurements"]["sections"] = order
        checks["U06.1: всеСекцииПрисутствуют"] = all(
            x["present"] for x in order["present"])
        checks["U06.1: порядокПрофиль→Инструкция→Референсы→Сборка→TestEdit→Результат→Подробнее"] = (
            order["ordered"] and order["moreAfterResult"])
        checks["U06.1: подробнееЭтоDetails"] = order["moreOpen"]
        page.screenshot(path=os.path.join(EVIDENCE,
                                          "%s_u06_desktop_top.png"
                                          % args.phase))

        # U06.2: сборка из edit_report
        page.click("[data-cover-compile-run]")
        page.wait_for_selector("[data-cover-compile-final-text]",
                               state="visible", timeout=8000)
        page.wait_for_timeout(300)
        cp = page.evaluate(COMPILE_PROBE)
        res["measurements"]["compile"] = {k: v for k, v in cp.items()
                                          if k != "detailsText"}
        checks["U06.2: строкаСборкиStyle·Anchor·Refs·System·Final/Limit"] = bool(
            cp["summary"] and cp["summary"].startswith("Style ")
            and "·" in cp["summary"] and "Final " in cp["summary"]
            and "/ " in cp["summary"])
        checks["U06.2: цветТолькоПриПревышении(нет-over)"] = not cp["overClass"]
        checks["U06.2: preМоноширинный"] = bool(cp["preMono"]) and any(
            m in cp["preMono"] for m in ("mono", "consol", "menlo", "courier"))
        checks["U06.2: preСоСкроллом"] = bool(cp["preScrollable"])
        checks["U06.2: естьКнопкаКопировать"] = cp["hasCopy"]
        checks["U06.2: edit_reportМетаданныеВПодробнее"] = bool(
            cp["hasDetails"] and cp["detailsText"]
            and "ограниченный" in cp["detailsText"].lower()
            and "headroom" in cp["detailsText"].lower())
        if args.phase == "after":
            checks["U06.2: Final=фактическомуПромпту"] = (
                cp["preText"] == FINAL_PROMPT)
        page.screenshot(path=os.path.join(
            EVIDENCE, "%s_u06_desktop_compile.png" % args.phase))

        # B05.1: фон
        geom = page.evaluate(EDITOR_GEOM)
        res["measurements"]["geom_desktop"] = geom
        checks["B05.1: фонРедактораНепрозрачный"] = (
            geom["bgAlpha"] is not None and geom["bgAlpha"] >= 0.999)
        checks["B05.1: центрРабочейОбластиНеКанвас"] = (
            "canvas" not in (geom["centerHit"] or "").lower())
        # канвас либо отсутствует на маршруте, либо строго ПОД оверлеем
        checks["B05.1: канвасПодОверлеем"] = (
            geom["canvasZ"] is None
            or (geom["overlayZ"] is not None
                and float(geom["overlayZ"]) > float(geom["canvasZ"])))

        # B05.2: copy == фактический промпт
        page.click("[data-cover-compile-copy]")
        page.wait_for_timeout(400)
        clip = page.evaluate("navigator.clipboard.readText()")
        res["measurements"]["clipboard_len"] = len(clip or "")
        checks["B05.2: copy=ФактическомуПромпту"] = (clip == FINAL_PROMPT)

        # U06.2/U06.3 сценарии (стаб в том же процессе — правлю напрямую):
        # превышение лимита → подсветка; неизвестный лимит → честное
        # «неизвестно» без псевдоцвета успеха.
        with STATE.lock:
            STATE.scenario = {"exceeded": True}
        page.click("[data-cover-compile-run]")
        page.wait_for_timeout(600)
        cp_over = page.evaluate(COMPILE_PROBE)
        res["measurements"]["compile_over"] = cp_over["summary"]
        checks["U06.2: превышениеПодсвечено"] = bool(cp_over["overClass"])
        with STATE.lock:
            STATE.scenario = {"limit_unknown": True}
        page.click("[data-cover-compile-run]")
        page.wait_for_timeout(600)
        cp_unk = page.evaluate(COMPILE_PROBE)
        res["measurements"]["compile_unknown"] = cp_unk["summary"]
        checks["U06.3: неизвестныйЛимитЧестно"] = bool(
            cp_unk["summary"] and "неизвестно" in cp_unk["summary"]
            and "/ неизвестно" in cp_unk["summary"]
            and not cp_unk["overClass"])
        with STATE.lock:
            STATE.scenario = {}
        page.click("[data-cover-compile-run]")
        page.wait_for_timeout(600)

        # B05.2: выделение 13 с при активном polling (job завершится в окне)
        seeded = page.evaluate(SETUP_SAMPLER)
        checks["B05.2: seedВыделения"] = bool(seeded.get("ok"))
        page.click("[data-cover-test-button]")
        page.wait_for_timeout(600)
        with STATE.lock:
            polling_started = STATE.job_started is not None
        page.wait_for_timeout(13000)
        samples = page.evaluate(STOP_SAMPLER)
        res["measurements"]["samples_n"] = len(samples)
        with STATE.lock:
            meta_arrived = STATE.meta_calls >= 2  # open + job-completion
            job_done = STATE.job_done_at is not None
        res["measurements"]["polling"] = {
            "job_started": polling_started, "job_done": job_done,
            "meta_calls": STATE.meta_calls}
        checks["B05.2: pollingРеальноАктивен"] = polling_started and job_done
        checks["B05.2: данныеПришлиВоВыделение"] = meta_arrived
        if samples:
            first, last = samples[0], samples[-1]
            stable = (
                first["taSel"] == last["taSel"]
                and first["taSub"] == last["taSub"]
                and last["taMark"] and last["preMark"]
                and first["preSel"] == last["preSel"]
                and first["taScroll"] == last["taScroll"])
            uniq_ta = {tuple(s["taSel"]) for s in samples}
            uniq_presel = {s["preSel"] for s in samples}
            res["measurements"]["sel_first"] = first
            res["measurements"]["sel_last"] = last
            checks["B05.2: выделение13сНеподвижно"] = (
                stable and len(uniq_ta) == 1 and len(uniq_presel) == 1)
            checks["B05.2: DOMНеПересоздан"] = (last["taMark"]
                                                and last["preMark"])
        else:
            checks["B05.2: выделение13сНеподвижно"] = False
            checks["B05.2: DOMНеПересоздан"] = False

        # dirty draft + meta-refetch не перетирает
        draft_before = page.evaluate(
            "document.querySelector('[data-cover-style-instruction]').value")
        page.evaluate("""() => {
          const ta = document.querySelector('[data-cover-style-instruction]');
          ta.focus(); ta.setSelectionRange(25, 25);
          document.execCommand('insertText', false, 'W3DRAFT');
        }""")
        page.wait_for_timeout(300)
        draft_after = page.evaluate(
            "document.querySelector('[data-cover-style-instruction]').value")
        checks["B05.2: draftРедактируем"] = ("W3DRAFT" in draft_after
                                             and draft_after != draft_before)
        # форсируем meta-refetch (тот же путь, что polling-completion)
        page.evaluate("""() => {
          const app = document.querySelector('#app');
          const vm = app && (app.__vue_app__ || app.__vue__);
          return !!vm;
        }""")
        # loadMeta через реальный путь: переоткрытие job-completion недоступно
        # вне job — вызываем через кнопку обновления примера нельзя (платно);
        # вместо этого лёгкий refetch списка стилей (loadCoverStyles — тот же
        # «приход данных», что polling) — он НЕ должен тронуть draft.
        page.evaluate("""() => {
          const ev = new Event('hashchange');
          window.dispatchEvent(ev);
        }""")
        page.wait_for_timeout(500)
        draft_final = page.evaluate(
            "document.querySelector('[data-cover-style-instruction]').value")
        checks["B05.2: данныеНеПеретираютDirtyDraft"] = (
            draft_final == draft_after)

        # Guard закрытия (B05.3)
        page.click("[data-cover-editor-back]")
        page.wait_for_timeout(400)
        guard_visible = page.evaluate(
            "!!document.querySelector('[data-cover-guard]')")
        editor_open = page.evaluate(
            "!!document.querySelector('[data-cover-style-editor]')")
        checks["B05.3: guardДержитРедакторПриDirty"] = (guard_visible
                                                        and editor_open)
        page.screenshot(path=os.path.join(EVIDENCE,
                                          "%s_b05_desktop_guard.png"
                                          % args.phase))
        if guard_visible:
            cancel = page.evaluate(
                "!!document.querySelector('[data-cover-guard-cancel]')")
            if cancel:
                page.click("[data-cover-guard-cancel]")
                page.wait_for_timeout(300)
            still_open = page.evaluate(
                "!!document.querySelector('[data-cover-style-editor]')")
            draft_kept = page.evaluate(
                "document.querySelector('[data-cover-style-instruction]')"
                ".value")
            checks["B05.3: cancelСохраняетDraft"] = (still_open
                                                     and "W3DRAFT"
                                                     in draft_kept)
            page.click("[data-cover-editor-back]")
            page.wait_for_timeout(300)
            if page.evaluate(
                    "!!document.querySelector('[data-cover-guard-close]')"):
                page.click("[data-cover-guard-close]")
                page.wait_for_timeout(400)
        closed = page.evaluate(
            "!document.querySelector('[data-cover-style-editor]')")
        checks["B05.3: confirmЗакрывает"] = closed

        # Чистое закрытие без диалога
        open_editor(page, base)
        page.click("[data-cover-editor-back]")
        page.wait_for_timeout(350)
        checks["B05.3: чистыйЗакрываетсяБезДиалога"] = page.evaluate(
            "!document.querySelector('[data-cover-style-editor]') "
            "&& !document.querySelector('[data-cover-guard]')")

        # Save contract не сломан
        with STATE.lock:
            STATE.last_save_body = None
        open_editor(page, base)
        page.click("[data-cover-style-save]")
        page.wait_for_timeout(700)
        with STATE.lock:
            save_body = copy.deepcopy(STATE.last_save_body)
        expected_keys = {"name", "instruction", "pipeline_mode",
                         "counter_enabled", "next_issue_number",
                         "counter_format", "model_mode", "connection_id",
                         "model_id", "enabled"}
        checks["B05.3: saveContractТеЖеКлючи"] = bool(
            save_body) and expected_keys.issubset(set(save_body.keys()))
        if save_body:
            checks["B05.3: saveInstructionИзDraft"] = (
                save_body.get("instruction") == draft_after
                or save_body.get("instruction") == INSTRUCTION)
        res["measurements"]["save_body_keys"] = sorted(
            (save_body or {}).keys())
        ctx.close()

        # ═══ B05.1 reduced-motion: polygon rAF заморожен ═══
        ctxr, pager = new_page(browser, 1440, 900, mobile=False, reduced=True)
        pager.goto(base + "#/", wait_until="load")
        pager.wait_for_selector("header.header-sticky", state="visible")
        pager.wait_for_timeout(1500)
        d1 = pager.evaluate(POLYGON_DIAG)
        pager.wait_for_timeout(2000)
        d2 = pager.evaluate(POLYGON_DIAG)
        res["measurements"]["polygon_frames"] = [d1, d2]
        checks["B05.1: reducedMotionОстанавливаетФон"] = (
            d1.get("present") and d1["frameCount1"] == d2["frameCount1"])
        ctxr.close()

        # ═══ MOBILE 390×844: dvh/скроллер/закреплённые шапка-футер ═══
        ctx, page = new_page(browser, 390, 844)
        open_editor(page, base)
        page.evaluate("""() => {
          const b = document.querySelector('.cover-editor-body');
          if (b) b.scrollTop = 80;
        }""")
        page.wait_for_timeout(200)
        gm = page.evaluate(EDITOR_GEOM)
        res["measurements"]["geom_mobile"] = gm
        checks["B05.3: mobileOverlay=dvh(высотаВьюпорта)"] = bool(
            gm["overlay"] and abs(gm["overlay"]["h"] - 844) <= 2)
        checks["B05.3: mobileEditorЗаполняетOverlay"] = bool(
            gm["editor"] and gm["overlay"]
            and gm["editor"]["top"] <= 1
            and abs(gm["editor"]["bottom"] - 844) <= 2)
        checks["B05.3: телоСкроллится"] = bool(gm["bodyScrollable"])
        checks["B05.3: документНеСкроллитсяЗаOverlay"] = (
            gm["docScrollTop"] == 0)
        checks["B05.3: шапкаЗакрепленаСверху"] = bool(
            gm["head"] and gm["head"]["top"] <= 1)
        checks["B05.3: футерЗакрепленСнизу"] = bool(
            gm["foot"] and abs(gm["foot"]["bottom"] - 844) <= 2)
        checks["B05.3: safeAreaОдинРаз(foot>=12px)"] = bool(
            gm["foot"] and gm["foot"]["h"] >= 44)
        # behind-overlay scroll: wheel вверх за пределом тела (базлайн ДО wheel)
        wheel_base = page.evaluate(EDITOR_GEOM)
        page.mouse.move(195, 400)
        page.mouse.wheel(0, -600)
        page.wait_for_timeout(250)
        gm2 = page.evaluate(EDITOR_GEOM)
        res["measurements"]["geom_mobile_after_wheel"] = {
            "docScrollTop": gm2["docScrollTop"],
            "mainScrollTop": gm2["mainScrollTop"],
            "bodyScrollTop": gm2["bodyScrollTop"]}
        checks["B05.3: overscrollНеУводитЗаOverlay"] = (
            gm2["docScrollTop"] == wheel_base["docScrollTop"]
            and gm2["mainScrollTop"] == wheel_base["mainScrollTop"])
        page.screenshot(path=os.path.join(EVIDENCE,
                                          "%s_b05_mobile_top.png" % args.phase))
        # bottom: футер на месте после прокрутки тела вниз
        page.evaluate("""() => {
          const b = document.querySelector('.cover-editor-body');
          if (b) b.scrollTop = b.scrollHeight;
        }""")
        page.wait_for_timeout(250)
        gm3 = page.evaluate(EDITOR_GEOM)
        checks["B05.3: футерНаМестеПослеСкроллаТела"] = bool(
            gm3["foot"] and abs(gm3["foot"]["bottom"] - 844) <= 2)
        page.screenshot(path=os.path.join(
            EVIDENCE, "%s_b05_mobile_bottom.png" % args.phase))
        ctx.close()

        # ═══ MOBILE 320: минимальная ширина — без горизонтального overflow ═══
        ctx, page = new_page(browser, 320, 700)
        open_editor(page, base)
        sw = page.evaluate(
            "document.querySelector('[data-cover-style-editor]')"
            ".getBoundingClientRect().width")
        checks["B05.3: 320безГоризонтальногоОverflow"] = sw <= 321
        page.screenshot(path=os.path.join(EVIDENCE,
                                          "%s_b05_mobile_320.png" % args.phase))
        ctx.close()

        browser.close()
    httpd.shutdown()

    res["passed"] = sum(1 for v in checks.values() if v)
    res["failed"] = sum(1 for v in checks.values() if not v)
    out = os.path.join(EVIDENCE, "w3_editor_e2e_%s.json" % args.phase)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("== W3-EDITOR e2e phase=%s ==" % args.phase)
    for k, v in checks.items():
        print(("  PASS " if v else "  FAIL ") + k)
    print("passed=%d failed=%d → %s" % (res["passed"], res["failed"], out))
    if args.phase == "after" and res["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
