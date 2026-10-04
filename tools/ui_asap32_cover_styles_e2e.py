"""ASAP 4.3 (T-4858, §10/§10.1–§10.4) — Playwright/Chromium геометрия
«Стили обложки» на трёх вьюпортах: 390×844 (portrait), 844×390 (landscape),
1280×800 (desktop) + Telegram-like safe-area эмуляция (mobile-контексты).

СТАТИЧЕСКАЯ страница (реальные web/index.html / app.js / app.css) + route-стабы
API (прецеденты ui_round1025_matrix.py, ui_asap42_mobile_layout_e2e.py).
ЭТО НЕ production acceptance; проверяются измеримые DOM-rect контракты:

  * `documentElement.scrollWidth <= innerWidth + 1` (нет horizontal overflow);
  * editor: header/body/footer; footer и Save-кнопка ЦЕЛИКОМ во вьюпорте;
    body — единственный скроллер (scrollHeight > clientHeight, scrollTop > 0);
  * fullscreen editor на mobile: shell bottom-nav закрыта overlay'ем
    (hit-test внизу возвращает элемент внутри `[data-cover-style-overlay]`);
  * closed more-sheet ОТСУТСТВУЕТ в DOM (регресс 4.2);
  * compact preview `[До] msr-chevron [После]` — одна горизонтальная группа,
    после-shrink помещается по ширине; стрелка — `.msr`, не текст;
  * Test Style: клик по кнопке НЕ открывает file picker; двойной тап не
    создаёт второй paid job (`test_starts == 1`); stage-текст виден; после
    completed — before/after из valid-пары без перезагрузки;
  * без valid-пары (custom-стиль) — Ч/Б placeholder из `extra_images`
    (запрос к `/api/cover/placeholders/*`), не «ваза».

Запуск: .venv\\Scripts\\python tools\\ui_asap32_cover_styles_e2e.py
Артефакт: tools/_ui_asap43_cover_styles_geometry.json
"""
import copy
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA-стаб — reuse)

PORT = M.PORT + 5
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "web")
RAW = os.path.join(M.REPO, "tools", "_ui_asap43_cover_styles_geometry.json")

VIEWPORTS = (
    ("portrait_390x844", {"width": 390, "height": 844}, True, 56),
    ("landscape_844x390", {"width": 844, "height": 390}, True, 24),
    ("desktop_1280x800", {"width": 1280, "height": 800}, False, 0),
)

SEED_STYLE = {
    "profile_id": "medved_press",
    "name": "Графический роман Медведь Press",
    "origin": "seeded_example",
    "is_example": True,
    "pipeline_mode": "generate_then_edit",
    "instruction": "Редактируй готовую обложку как выпуск «Медведь Press».",
    "counter_enabled": True,
    "counter_value": 0,
    "counter_format": "ВЫПУСК {counter}",
    "model_mode": "default",
    "connection_id": None,
    "model_id": None,
    "revision": 3,
    "enabled": True,
    "preview_before_asset_id": "cas_before",
    "preview_after_asset_id": "cas_after",
    "preview_revision": 3,
    # ASAP 4.3 (§4): контракт пары — валидна только от одного успешного job.
    "preview_pair_valid": True,
    "preview_status": "success",
    "preview_job_id": "cov_prev1",
    "preview_stale": False,
    "reference_count": 1,
    "preview_issue": "ВЫПУСК 00",
    "can_edit": True,
    "references": [{"ref_id": "csr_ref", "asset_id": "cas_ref",
                    "label": "Медведь Press",
                    "description": "Логотип издательства",
                    "ordering": 0,
                    "url": "/api/cover/assets/cas_ref"}],
}

DETAIL_META = {
    "capabilities": {"edit_supported": True, "image_edit": "true"},
    "connection": {"configured": True, "connected": True, "api_key_set": True,
                   "connection_id": "default", "custom_unresolved": False,
                   "message": "Подключено"},
    "budget": {"known": False, "limit_known": False, "limit": None,
               "components": {"style": 61, "context": 0, "refs": 34,
                              "system": 52, "total": 147}},
    "prompt_limit": {"operation": "image_edit", "mode": "auto",
                     "value": None, "unit": "chars", "limit_known": False,
                     "source": "unknown", "provider": "nanogpt",
                     "base_url": "https://nano-gpt.com/v1",
                     "model": "qwen-image-edit"},
}

CONNECTION = {"connection_id": "csc_1", "label": "NanoGPT Images",
              "provider": "nanogpt", "base_url": "https://nano-gpt.com/v1",
              "api_key_set": True, "api_key_masked": "sk-…xy"}

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201cfa02d0d0000000049454e44ae"
    "426082")

PLACEHOLDER_BEFORE = "style_example_01.png"
PLACEHOLDER_AFTER = "style_example_02.jpg"


def _png_response(route, content_type="image/png"):
    route.fulfill(status=200, content_type=content_type, body=PNG_BYTES)


PROBE_CLOSED = r"""
(() => {
  const de = document.documentElement;
  const vw = window.innerWidth, vh = window.innerHeight;
  const rect = (sel) => {
    const e = document.querySelector(sel);
    if (!e) return null;
    const r = e.getBoundingClientRect();
    const st = getComputedStyle(e);
    const vis = r.width > 0 && r.height > 0 && st.display !== 'none'
      && st.visibility !== 'hidden';
    return { x: Math.round(r.x), y: Math.round(r.y),
             w: Math.round(r.width), h: Math.round(r.height),
             right: Math.round(r.right), bottom: Math.round(r.bottom),
             position: st.position, zIndex: st.zIndex, visible: vis,
             inViewport: r.bottom <= vh + 1 && r.top >= -1
               && r.right <= vw + 1 && r.left >= -1 };
  };
  const overlap = (a, b) => !!a && !!b && a.visible && b.visible
    && !(a.right <= b.x || b.right <= a.x
         || a.bottom <= b.y || b.bottom <= a.y);
  return {
    innerWidth: vw, innerHeight: vh,
    docScrollWidth: de.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    docOverflow: de.scrollWidth > vw + 1
      || document.body.scrollWidth > vw + 1,
    management: !!document.querySelector('[data-cover-styles]'),
    bottomNav: rect('.bottom-nav'),
    stickySave: rect('.sticky-save'),
    saveBtn: rect('.sticky-save .btn-accent'),
    saveNavOverlap: (() => {
      const nav = document.querySelector('.bottom-nav');
      const bar = document.querySelector('.sticky-save');
      if (!nav || !bar) return false;
      const nr = nav.getBoundingClientRect(), br = bar.getBoundingClientRect();
      return !(br.right <= nr.left || nr.right <= br.left
               || br.bottom <= nr.top || nr.bottom <= br.top);
    })(),
    moreSheetPresent: !!document.querySelector('.more-sheet'),
    moreBackdropPresent: !!document.querySelector('.more-backdrop'),
  };
})()
"""

PROBE_EDITOR = r"""
(() => {
  const de = document.documentElement;
  const vw = window.innerWidth, vh = window.innerHeight;
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y),
             w: Math.round(r.width), h: Math.round(r.height),
             right: Math.round(r.right), bottom: Math.round(r.bottom),
             top: Math.round(r.top), left: Math.round(r.left) };
  };
  const q = (sel) => rect(document.querySelector(sel));
  const body = document.querySelector(
    '[data-cover-style-editor] .cover-editor-body');
  let scroller = null;
  if (body) {
    const before = body.scrollTop;
    body.scrollTop = body.scrollHeight;
    scroller = {
      scrollHeight: body.scrollHeight, clientHeight: body.clientHeight,
      scrollTop: body.scrollTop, before: before,
      overflowY: getComputedStyle(body).overflowY,
      scrollable: body.scrollHeight > body.clientHeight
        && body.scrollTop > 0,
    };
  }
  const nav = document.querySelector('.bottom-nav');
  const overlay = document.querySelector('[data-cover-style-overlay]');
  let navUsable = null;
  if (nav) {
    const nr = nav.getBoundingClientRect();
    const el = document.elementFromPoint(
      Math.round(Math.min(Math.max(nr.width / 2, 2), vw - 2)),
      Math.round(Math.min(Math.max((nr.top + nr.bottom) / 2, 2), vh - 2)));
    navUsable = !(el && overlay && overlay.contains(el));
  }
  const save = document.querySelector('[data-cover-style-save]');
  let saveHit = null;
  if (save) {
    const sr = save.getBoundingClientRect();
    const el = document.elementFromPoint(
      Math.round(Math.min(Math.max((sr.left + sr.right) / 2, 2), vw - 2)),
      Math.round(Math.min(Math.max((sr.top + sr.bottom) / 2, 2), vh - 2)));
    saveHit = !!(el && save.contains(el));
  }
  const arrowEl = document.querySelector('[data-cover-preview-arrow]');
  const arrow = rect(arrowEl);
  const before = q('[data-cover-before-img]');
  const after = q('[data-cover-after-img]');
  const previewFits = (() => {
    if (!before || !after || !arrow) return null;
    return {
      horizontalOrder: before.right <= arrow.x + 1
        && arrow.right <= after.x + 1,
      bottomAligned: Math.abs(before.bottom - after.bottom) <= 6,
      fitsWidth: before.left >= -1 && after.right <= vw + 1,
      arrowIsMsr: !!(arrowEl && arrowEl.classList.contains('msr')),
    };
  })();
  return {
    innerWidth: vw, innerHeight: vh,
    docScrollWidth: de.scrollWidth,
    docOverflow: de.scrollWidth > vw + 1
      || document.body.scrollWidth > vw + 1,
    editor: q('[data-cover-style-editor]'),
    head: q('.cover-editor-head'),
    foot: q('.cover-editor-foot'),
    save: q('[data-cover-style-save]'),
    saveHit,
    scroller: scroller,
    bottomNav: rect(nav),
    navUsableUnderOverlay: navUsable,
    moreSheetPresent: !!document.querySelector('.more-sheet'),
    previewArrow: q('[data-cover-preview-arrow]'),
    previewBefore: before,
    previewAfter: after,
    previewFits,
  };
})()
"""


def _record_failure(failures, viewport, message):
    failures.append("[%s] %s" % (viewport, message))


def _check_editor_probe(probe, viewport, failures, *, mobile_nav):
    editor = probe.get("editor")
    if not editor:
        _record_failure(failures, viewport, "editor не найден")
        return
    vw, vh = probe["innerWidth"], probe["innerHeight"]
    if probe.get("docOverflow"):
        _record_failure(failures, viewport,
                        "horizontal overflow: doc=%s body=%s vw=%s"
                        % (probe.get("docScrollWidth"),
                           probe.get("docScrollWidth"), vw))
    if editor["x"] < -1 or editor["right"] > vw + 1 \
            or editor["top"] < -1 or editor["bottom"] > vh + 1:
        _record_failure(failures, viewport,
                        "editor вне вьюпорта: %s" % editor)
    foot = probe.get("foot")
    if not foot or foot["bottom"] > vh + 1 or foot["top"] < -1:
        _record_failure(failures, viewport, "footer не виден: %s" % foot)
    save = probe.get("save")
    if not save or save["bottom"] > vh + 1 or save["left"] < -1 \
            or save["right"] > vw + 1:
        _record_failure(failures, viewport,
                        "Save button обрезан/вне вьюпорта: %s" % save)
    if save and probe.get("saveHit") is False:
        _record_failure(failures, viewport,
                        "Save перекрыт другим элементом (hit-test)")
    scroller = probe.get("scroller")
    if not scroller or not scroller.get("scrollable"):
        _record_failure(failures, viewport,
                        "body не единственный скроллер: %s" % scroller)
    else:
        oy = scroller.get("overflowY")
        if oy not in ("auto", "scroll"):
            _record_failure(failures, viewport,
                            "body overflow-y=%s (ожидается auto/scroll)" % oy)
    if mobile_nav:
        nav = probe.get("bottomNav")
        if nav and nav.get("w", 0) > 0 \
                and probe.get("navUsableUnderOverlay") is not False:
            _record_failure(
                failures, viewport,
                "shell bottom-nav доступна под editor overlay — контракт "
                "«nav скрыта/вне usable viewport» нарушен")
    fits = probe.get("previewFits")
    if not fits:
        _record_failure(failures, viewport,
                        "compact preview не найден (before/arrow/after)")
    else:
        for key, human in (("horizontalOrder",
                            "preview не в одну горизонтальную группу"),
                           ("bottomAligned", "preview не выровнен по низу"),
                           ("fitsWidth", "preview выходит по ширине"),
                           ("arrowIsMsr", "стрелка не .msr")):
            if not fits.get(key):
                _record_failure(failures, viewport, human)
    if probe.get("moreSheetPresent"):
        _record_failure(failures, viewport, "ghost more-sheet в DOM")


def _run():
    from playwright.sync_api import sync_playwright

    os.chdir(M.REPO)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    styles_payload = {
        "enabled": True,
        "no_style_label": "Без дополнительного стиля",
        "selected_style_id": "",
        "pipeline_modes": ["generate_only", "generate_then_edit", "edit_only"],
        "placeholders": {
            "before_url": "/api/cover/placeholders/" + PLACEHOLDER_BEFORE,
            "after_url": "/api/cover/placeholders/" + PLACEHOLDER_AFTER,
        },
        "styles": [copy.deepcopy(SEED_STYLE)],
    }
    state = {"styles": styles_payload, "created": [], "saves": [],
             "uploads": [], "test_starts": 0, "test_status": 0,
             "placeholder_hits": 0, "file_choosers": 0, "new_seq": 0}
    result = {"failures": [], "console_errors": [], "probes": {},
              "test_starts": 0, "placeholder_hits": 0}
    failures = result["failures"]

    def _api_handler(route):
        req = route.request
        url = req.url
        path = url.split("?")[0]
        query = url.split("?", 1)[1] if "?" in url else ""
        # placeholders (§5) — фактические файлы extra_images (read-only)
        if "/api/cover/placeholders/" in path:
            state["placeholder_hits"] += 1
            ctype = "image/jpeg" if path.endswith((".jpg", ".jpeg")) \
                else "image/png"
            return _png_response(route, ctype)
        if path.endswith("/api/cover/assets/cas_ref") \
                or path.endswith("/api/cover/assets/cas_before") \
                or path.endswith("/api/cover/assets/cas_after"):
            return _png_response(route)
        # Test Style durable job (§2.2/§11)
        if path.endswith("/api/cover/test-style") and req.method == "POST":
            state["test_starts"] += 1
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"job_id": "cov_test1", "status": "queued",
                                 "stage": "queued", "reused": False,
                                 "preview_issue": "ВЫПУСК 00"}))
            return
        if path.endswith("/api/cover/test-style/cov_test1") \
                and req.method == "GET":
            state["test_status"] += 1
            if state["test_status"] <= 1:
                payload = {"job_id": "cov_test1", "status": "running",
                           "stage": "base_generating",
                           "started_at": 1, "last_progress_at": 2,
                           "provider": "", "model": "",
                           "human_message": "", "machine_reason": "",
                           "preview_before_url": None,
                           "preview_after_url": None,
                           "prompt": {"total_chars": None, "limit": None}}
            else:
                payload = {"job_id": "cov_test1", "status": "completed",
                           "stage": "completed", "started_at": 1,
                           "last_progress_at": 3, "provider": "nanogpt",
                           "model": "qwen-image-edit",
                           "human_message": "Стиль применён",
                           "machine_reason": "",
                           "preview_before_url": "/api/cover/assets/cas_before",
                           "preview_after_url": "/api/cover/assets/cas_after",
                           "preview_revision": 3,
                           "preview_job_id": "cov_test1",
                           "preview_status": "success",
                           "prompt": {"style_chars": 61, "context_chars": 0,
                                      "refs_chars": 34, "system_chars": 52,
                                      "total_chars": 147, "limit": None,
                                      "unit": None, "exceeded": False}}
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))
            return
        if path.endswith("/api/cover/prompt-limit") \
                and req.method in ("GET", "POST"):
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"operation": "image_edit", "mode": "auto",
                                 "value": None, "unit": "chars",
                                 "limit_known": False, "source": "unknown",
                                 "provider": "nanogpt",
                                 "base_url": "https://nano-gpt.com/v1",
                                 "model": "qwen-image-edit"}))
            return
        if path.endswith("/api/cover/styles") and req.method == "POST":
            body = json.loads(req.post_data or "{}")
            if "style_id=" in query:
                state["saves"].append(body)
                sid = query.split("style_id=")[1].split("&")[0]
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(dict(
                                  next(s for s in state["styles"]["styles"]
                                       if s["profile_id"] == sid), **body)))
                return
            state["created"].append(body)
            state["new_seq"] += 1
            new_id = "csp_new%d" % state["new_seq"]
            profile = dict(SEED_STYLE)
            profile.update({"profile_id": new_id, "name": body["name"],
                            "origin": "custom", "is_example": False,
                            "revision": 1, "counter_enabled": False,
                            "counter_value": 0,
                            "preview_before_asset_id": None,
                            "preview_after_asset_id": None,
                            "preview_revision": None,
                            "preview_pair_valid": False,
                            "preview_status": None,
                            "preview_job_id": None,
                            "reference_count": 0, "references": [],
                            "preview_issue": "ВЫПУСК 00"})
            state["styles"]["styles"].append(profile)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(profile))
            return
        if path.endswith("/api/cover/styles") and req.method == "GET":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(state["styles"]))
            return
        if "/api/cover/styles/csp_new" in path and req.method == "GET":
            pid = path.rsplit("/", 1)[-1]
            profile = next(s for s in state["styles"]["styles"]
                           if s["profile_id"] == pid)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(dict(profile, **DETAIL_META)))
            return
        if "/api/cover/styles/medved_press" in path and req.method == "GET":
            route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(dict(copy.deepcopy(SEED_STYLE),
                                     **DETAIL_META)))
            return
        if "/api/cover/styles/medved_press" in path and req.method == "POST":
            body = json.loads(req.post_data or "{}")
            state["saves"].append(body)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(dict(SEED_STYLE, **body)))
            return
        if path.endswith("/api/cover/connections"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"connections": [CONNECTION]}))
            return
        if path.endswith("/api/cover/select"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True}))
            return
        if path.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps([
                              {"chat_id": 100, "title": "Chat A",
                               "is_dm": False, "photo_file_id": None,
                               "access": "admin"}]))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url)))

    def _open_styles(page, url):
        page.goto(url + "#/modules", wait_until="load")
        page.wait_for_timeout(1500)
        page.evaluate(
            "() => { window.location.hash = '#/modules/summary/styles'; }")
        page.wait_for_timeout(1200)
        if not page.query_selector("[data-cover-styles]"):
            for t in page.query_selector_all("[data-workspace-tab]"):
                if t.get_attribute("data-workspace-tab") == "styles":
                    t.click()
                    break
            page.wait_for_timeout(900)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            url = "http://127.0.0.1:%d/web/index.html" % PORT
            for label, viewport, mobile, safe_bottom in VIEWPORTS:
                state["test_status"] = 0    # stage-снимок на каждый viewport
                ctx = browser.new_context(viewport=viewport,
                                          is_mobile=mobile, has_touch=mobile)
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", _api_handler)
                page = ctx.new_page()
                page.on("console", lambda m, L=label: result[
                    "console_errors"].append("%s: %s" % (L, m.text[:200]))
                    if m.type == "error" else None)
                page.on("pageerror", lambda e, L=label: result[
                    "console_errors"].append("%s pageerror: %s"
                                             % (L, str(e)[:200])))
                page.on("dialog", lambda d: d.accept())
                page.on("filechooser", lambda f: state.__setitem__(
                    "file_choosers", state["file_choosers"] + 1))

                if safe_bottom:
                    page.evaluate(
                        "() => { document.documentElement.style.setProperty("
                        "'--tg-content-safe-area-inset-bottom', '%dpx');"
                        " }" % safe_bottom)

                _open_styles(page, url)
                closed = page.evaluate(PROBE_CLOSED)
                result["probes"][label + "_closed"] = closed
                if not closed["management"]:
                    _record_failure(failures, label,
                                    "management screen не найден")
                if closed["docOverflow"]:
                    _record_failure(failures, label,
                                    "horizontal overflow: %s > %s"
                                    % (closed["docScrollWidth"],
                                       closed["innerWidth"]))
                if closed["moreSheetPresent"] \
                        or closed["moreBackdropPresent"]:
                    _record_failure(failures, label,
                                    "closed more-sheet в DOM")
                if closed["saveNavOverlap"]:
                    _record_failure(failures, label,
                                    "sticky-save пересекает bottom-nav")
                bar = closed.get("stickySave")
                btn = closed.get("saveBtn")
                if bar and bar.get("visible") and not bar.get("inViewport"):
                    _record_failure(failures, label,
                                    "sticky-save не в viewport: %s" % bar)
                if btn and btn.get("visible") and not btn.get("inViewport"):
                    _record_failure(failures, label,
                                    "sticky-save кнопка обрезана: %s" % btn)

                # ── seeded editor: geometry + Test Style flow ────────────────
                open_btn = page.query_selector(
                    '[data-cover-style="medved_press"] '
                    '[data-cover-style-open]')
                if not open_btn:
                    _record_failure(failures, label,
                                    "кнопка «Открыть» seeded не найдена")
                    ctx.close()
                    continue
                open_btn.click()
                page.wait_for_timeout(900)
                if not page.query_selector("[data-cover-style-editor]"):
                    _record_failure(failures, label,
                                    "редактор не открылся")
                    ctx.close()
                    continue

                test_btn = page.query_selector("[data-cover-test-button]")
                if not test_btn:
                    _record_failure(failures, label,
                                    "кнопка «Проверить стиль» не найдена")
                else:
                    # двойной тап: второй клик при активном job не создаёт
                    # второй paid job (серверный dedup + UI-guard).
                    starts_before = state["test_starts"]
                    test_btn.click()
                    page.wait_for_timeout(200)
                    # Второй тап — синхронный DOM-click (не блокирует
                    # actionability): disabled-кнопка/guard не создают job.
                    page.evaluate(
                        "() => { const b = document.querySelector("
                        "'[data-cover-test-button]'); if (b) b.click(); }")
                    page.wait_for_timeout(400)
                    if state["test_starts"] - starts_before != 1:
                        _record_failure(
                            failures, label,
                            "double-tap создал %d job'ов (ожидается 1)"
                            % (state["test_starts"] - starts_before))
                    # stage-прогресс виден до завершения
                    try:
                        page.wait_for_selector("[data-cover-test-progress]",
                                               timeout=4000)
                    except Exception:
                        _record_failure(
                            failures, label,
                            "progress не появился (starts=%d status=%d "
                            "last_err=%s)" % (
                                state["test_starts"], state["test_status"],
                                (result["console_errors"] or ["-"])[-1]))
                        ctx.close()
                        continue
                    stage = page.query_selector("[data-cover-test-stage]")
                    stage_text = stage.inner_text() if stage else ""
                    if "Генерируем базовую обложку" not in stage_text \
                            and "Применяем стиль" not in stage_text \
                            and "Сохраняем результат" not in stage_text:
                        _record_failure(
                            failures, label,
                            "stage-текст не человеческий: %r" % stage_text)
                    # completed → обе картинки и «Стиль применён»
                    page.wait_for_selector("[data-cover-test-human]",
                                           timeout=10000)
                    human = page.query_selector(
                        "[data-cover-test-human]").inner_text()
                    if "Стиль применён" not in human:
                        _record_failure(failures, label,
                                        "success-текст не показан: %r" % human)
                    if not page.query_selector("[data-cover-before-img]") \
                            or not page.query_selector(
                                "[data-cover-after-img]"):
                        _record_failure(
                            failures, label,
                            "после success нет before/after пары")
                    if state["file_choosers"]:
                        _record_failure(
                            failures, label,
                            "Test Style открыл file picker (%d)"
                            % state["file_choosers"])

                budget = page.query_selector("[data-cover-budget-breakdown]")
                if not budget or "Последняя сборка" not in budget.inner_text():
                    _record_failure(failures, label,
                                    "breakdown Style/Context/Refs/System "
                                    "не показан")
                limit_label = page.query_selector("[data-cover-limit-resolved]")
                if not limit_label \
                        or "Лимит текущей модели" not in limit_label.inner_text():
                    _record_failure(failures, label,
                                    "строка «Лимит текущей модели» не найдена")

                probe = page.evaluate(PROBE_EDITOR)
                result["probes"][label + "_editor"] = probe
                _check_editor_probe(probe, label, failures,
                                    mobile_nav=mobile)
                page.screenshot(path=os.path.join(
                    M.REPO, "tools",
                    "_ui_asap43_%s_editor.png" % label), full_page=False)

                # ── store at close after test: NO publish / NO file picker ───
                page.click("[data-cover-editor-close]")
                page.wait_for_timeout(600)

                page.click("[data-cover-style-new]")
                page.wait_for_timeout(400)
                page.fill("[data-cover-style-name]", "Мой стиль")
                page.click("[data-cover-style-create]")
                page.wait_for_timeout(1000)
                page.wait_for_selector("[data-cover-before-img]", timeout=5000)
                fallback = page.evaluate(
                    "() => {"
                    " const el = (s) => document.querySelector(s);"
                    " const ok = (e) => !!e && e.src.indexOf('blob:') === 0"
                    "   && e.complete && e.naturalWidth > 0;"
                    " const src = el('[data-cover-editor-preview-source]');"
                    " return { before: ok(el('[data-cover-before-img]')),"
                    "          after: ok(el('[data-cover-after-img]')),"
                    "          label: src ? src.textContent.trim() : '' };"
                    " }")
                if not (fallback["before"] and fallback["after"]):
                    _record_failure(failures, label,
                                    "Ч/Б placeholder не отрисован: %s"
                                    % fallback)
                if "Пример" not in fallback["label"]:
                    _record_failure(failures, label,
                                    "источник preview не «Пример»: %r"
                                    % fallback["label"])
                if state["placeholder_hits"] <= 0:
                    _record_failure(
                        failures, label,
                        "placeholders не запрошены из "
                        "/api/cover/placeholders/*")
                page.click("[data-cover-editor-close]")
                page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(
                    M.REPO, "tools",
                    "_ui_asap43_%s_management.png" % label), full_page=False)
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    uniq = [e for e in result["console_errors"] if "favicon" not in e]
    if uniq:
        failures.append("console/pageerror: %s" % uniq[:3])
    result["test_starts"] = state["test_starts"]
    result["placeholder_hits"] = state["placeholder_hits"]
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if failures:
        print("FAILURES: %d" % len(failures))
        for f in failures:
            print(" -", f)
        return 1
    print("ASAP43 COVER STYLES GEOMETRY E2E: OK (3 viewports)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
