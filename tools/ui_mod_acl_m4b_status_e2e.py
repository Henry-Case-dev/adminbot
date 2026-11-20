"""M4B B1 — «пять лент» на «Статусе»: Playwright e2e (детерминированный).

Проверяет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css`
(`/api/*` — синтетические стабы; R17: только идентификаторы/числа/тексты
фикстуры, секретов нет):

  * ровно 5 лент в одной карточке, «Досье» — пятая (person-проекция того же
    dossier_feed, без 1:1 дубля и без нижней карточки);
  * сетка 3+2 при ≥1280, 2+2+1 при 768–1279, 1 колонка + вкладки ≤767;
  * 1440/1920/1280/768/390/320: нет горизонтального overflow, 5 живых окон,
    в каждом есть реальные строки; досье группирует Аню (2 записи) в одну;
  * pause/resume после ручного wheel, detail (окно записи) и вторичное
    действие «Досье субъекта», provenance/даты реальные;
  * mobile: активная вкладка/aria-current, 5 переключателей, touch ≥44 px;
  * scope: «Тихий чат» не показывает данные другого чата (S15-03);
  * reduced-motion: ленты не двигаются, контент остаётся;
  * 503 dossier_feed: причина показана, а не «0 записей».

Запуск: .venv\\Scripts\\python.exe tools\\ui_mod_acl_m4b_status_e2e.py
Артефакты: plans/features/mod-acl-ux-01/evidence/m4b/b1/shots/ + e2e-report.json
"""
import copy
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA/стабы — reuse)

PORT = int(os.environ.get("MOD_ACL_M4B_STATUS_PORT", "8856"))
SHOTS = os.environ.get(
    "MOD_ACL_M4B_STATUS_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4b", "b1", "shots"))
REPORT = os.environ.get(
    "MOD_ACL_M4B_STATUS_REPORT",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4b", "b1", "e2e-report.json"))

NOW = 1791900000
CHAT = -1001234567890
CHAT_TITLE = "Audit Chat"
EMPTY_CHAT = -1009876543210
EMPTY_TITLE = "Тихий чат"

DOSSIER_ITEMS = [
    {"id": 11, "chat_id": CHAT, "name": "Аня", "user_name": "Аня",
     "user_id": 501, "excerpt": "любит кофе без сахара",
     "text": "Аня любит кофе без сахара", "created_at": NOW - 120,
     "message_timestamp": NOW - 5000, "last_confirmed_at": NOW - 110,
     "origin": "chat_history", "tg_message_id": 9001, "kind": "preference"},
    {"id": 12, "chat_id": CHAT, "name": "Аня", "user_name": "Аня",
     "user_id": 501, "excerpt": "переехала в другой район",
     "text": "Аня переехала в другой район", "created_at": NOW - 60,
     "message_timestamp": NOW - 3000, "last_confirmed_at": NOW - 50,
     "origin": "summary", "tg_message_id": 9002, "kind": "event"},
    {"id": 13, "chat_id": CHAT, "name": "Борис", "user_name": "Борис",
     "user_id": 502, "excerpt": "работает над проектом",
     "text": "Борис работает над проектом", "created_at": NOW - 200,
     "message_timestamp": NOW - 6000, "last_confirmed_at": NOW - 190,
     "origin": "chat_history", "tg_message_id": 9003, "kind": "fact"},
    {"id": 14, "chat_id": CHAT, "name": "Гость", "user_name": "Гость",
     "user_id": None, "excerpt": "запись без user_id",
     "text": "Гость: запись без user_id", "created_at": NOW - 240,
     "message_timestamp": None, "last_confirmed_at": None,
     "origin": "voice_transcript", "tg_message_id": None, "kind": "fact"},
    {"id": 15, "chat_id": CHAT, "name": None, "user_name": None,
     "user_id": None, "excerpt": "безымянная запись",
     "text": "Безымянная запись", "created_at": NOW - 300,
     "message_timestamp": None, "last_confirmed_at": None,
     "origin": None, "tg_message_id": None, "kind": "fact"},
]

BELIEFS = [
    {"id": 1, "fact": "Люди ценят честность", "created_at": NOW - 100},
    {"id": 2, "fact": "Кофе помогает разговору", "created_at": NOW - 90},
    {"id": 3, "fact": "Юмор сближает", "created_at": NOW - 80},
]
PARADIGMS = [
    {"id": 4, "fact": "Раньше было тише, теперь живее",
     "created_at": NOW - 400},
    {"id": 5, "fact": "Доверие росло постепенно", "created_at": NOW - 300},
    {"id": 6, "fact": "Темп общения ускорился", "created_at": NOW - 200},
]
TRAITS = [
    {"id": 7, "ts": NOW - 100, "text": "Стал более спокойным",
     "source": "self_fact"},
    {"id": 8, "ts": NOW - 90, "text": "Чаще шутит", "source": "self_fact"},
    {"id": 9, "ts": NOW - 80, "text": "Реже перебивает", "source": "self_fact"},
]

COGNITION = {
    "dream": {"running": False, "enabled": True, "effective": True,
              "active": False, "active_until": None, "manual": False,
              "last_run_at": NOW - 7200, "next_wake_at": NOW + 3600,
              "state": "sleep",
              "budget": {"distilled_today": 1, "distilled_limit": 5,
                         "tokens_today": 100, "tokens_limit": 2000}},
    "deep_sleep": {"running": False, "enabled": True, "active": False,
                   "active_until": None, "manual": False,
                   "last_run_at": NOW - 3600, "next_run_at": NOW + 7200,
                   "paradigms_status": "ok"},
    "generated_at": NOW,
}
DEEP_SLEEP = {"paradigms_status": "ok", "gate": True, "effective": True}
HEALTH = {
    "beliefs_active": 3, "beliefs_archived": 0, "resurrections_total": 0,
    "decay_runs_total": 1, "last_decay_at": NOW - 4000,
    "facts_overdue": 0, "facts_unconfirmed": 0,
    "smart_messages_total": 42,
    "storage": {"db_size_bytes": 1048576, "db_size_mb": 1.0,
                "disk_free_bytes": 1073741824},
}
EXPIRED = {
    "available": True, "now_ts": NOW, "expired_total": 0,
    "expired_searchable": 0, "needs_recheck": 0,
    "superseded_total": 0, "infinite_retention": True,
}
INTEL_FUNNELS = {
    "available": True, "now_ts": NOW, "chat_scoped_events": False,
    "initiative": {"available": True, "job": {"status": "completed"},
                   "events": {"24h": {}, "7d": {}}},
    "experience": {"available": True, "job": {"status": "completed"},
                   "semantic_lag": {"pending": 0, "lag_rows": 0},
                   "events": {"24h": {}, "7d": {}}},
}
STATUS = copy.deepcopy(M.STATUS_STUB)
STATUS["intents"] = {"enabled": True, "state": "not_run", "active": 0,
                     "top": [], "last_action": None}
STATUS["experience"] = {"enabled": True, "state": "not_run", "items": [],
                        "counters": {"lessons": 0, "active": 0,
                                     "suspended": 0, "applications": 0}}
STATUS["random"] = {"ready": True, "enabled": False}
LOGS = {"logs": [], "levels": [], "count": 0, "counts": {}}


def _chat_id_of(request_url):
    q = parse_qs(urlparse(request_url).query)
    vals = q.get("chat_id") or []
    return vals[0] if vals else None


def _api_handler(route, dossier_fail=False):
    req = route.request
    parsed = urlparse(req.url)
    path = parsed.path
    if path.endswith("/api/access/chats"):
        body = [
            {"chat_id": CHAT, "title": CHAT_TITLE, "is_dm": False,
             "photo_file_id": None, "access": "admin"},
            {"chat_id": EMPTY_CHAT, "title": EMPTY_TITLE, "is_dm": False,
             "photo_file_id": None, "access": "admin"},
        ]
    elif path.endswith("/api/oversight/summary"):
        body = {"chats": [
            {"chat_id": CHAT, "title": CHAT_TITLE},
            {"chat_id": EMPTY_CHAT, "title": EMPTY_TITLE},
        ], "totals": {}}
    elif path.endswith("/api/oversight/dossier_feed"):
        if dossier_fail:
            route.fulfill(status=503, content_type="application/json",
                          body=json.dumps({"detail": "temporarily unavailable"}))
            return
        cid = _chat_id_of(req.url)
        if cid is not None and str(cid) != str(CHAT):
            body = {"items": []}
        else:
            body = {"items": copy.deepcopy(DOSSIER_ITEMS)}
    elif path.endswith("/api/memory/cognition/status"):
        body = COGNITION
    elif path.endswith("/api/memory/deep-sleep"):
        body = DEEP_SLEEP
    elif path.endswith("/api/memory/dream/beliefs"):
        kind = (parse_qs(parsed.query).get("kind") or [""])[0]
        body = copy.deepcopy(PARADIGMS if kind == "paradigm" else BELIEFS)
    elif path.endswith("/api/persona"):
        body = {"dynamic_traits": copy.deepcopy(TRAITS),
                "traits_status": "ok", "self_facts_count": 3}
    elif path.endswith("/api/memory/health"):
        body = HEALTH
    elif path.endswith("/api/memory/expired-overview"):
        body = EXPIRED
    elif path.endswith("/api/memory/intel-funnels"):
        body = INTEL_FUNNELS
    elif path.endswith("/api/status/logs"):
        body = LOGS
    elif path.endswith("/api/status"):
        body = STATUS
    elif path.endswith("/api/config"):
        hdrs = {str(k).lower(): v for k, v in req.headers.items()}
        body = (M.CONFIG_STUB_CHAT if hdrs.get("x-chat-id") in
                (str(CHAT), str(EMPTY_CHAT)) else M.CONFIG_STUB)
    elif "/dossier/" in path and path.endswith("/rebuild/latest"):
        body = {}
    elif "/dossier/" in path:
        body = {"extracted": "Авто-досье: любит кофе, ценит прямоту",
                "manual_traits": "", "links": [], "patterns": [], "themes": []}
    else:
        body = M._stub_for(req.url)
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body, ensure_ascii=False))


def _start_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _geometry(page):
    return page.evaluate(
        """() => {
          const grid = document.querySelector('.cognition-ribbons');
          const cards = Array.from(grid.querySelectorAll(':scope > .ribbon'));
          const visible = cards.filter((c) => {
            const cs = getComputedStyle(c);
            return cs.display !== 'none' && c.getBoundingClientRect().height > 0;
          });
          const tops = visible.map((c) => Math.round(c.getBoundingClientRect().top));
          const rows = [];
          tops.forEach((t) => { if (!rows.length || rows[rows.length - 1] !== t) rows.push(t); });
          const rowCounts = rows.map((t) => tops.filter((x) => x === t).length);
          const cols = getComputedStyle(grid).gridTemplateColumns
            .split(' ').filter(Boolean).length;
          return {cols: cols, rows: rowCounts, count: cards.length,
                  visible: visible.length, tops: tops,
                  sections: cards.map((c) => c.getAttribute('data-intel-section'))};
        }""")


def _overflow(page):
    return page.evaluate(
        """() => {
          const de = document.documentElement;
          const cards = Array.from(
            document.querySelectorAll('.cognition-ribbons > .ribbon'));
          return {
            page: de.scrollWidth <= window.innerWidth + 1,
            cards: cards.every((c) => c.scrollWidth <= c.clientWidth + 1),
            widths: cards.map((c) => [c.scrollWidth, c.clientWidth]),
          };
        }""")


def _ribbon_rows(page):
    return page.evaluate(
        """() => {
          const out = {};
          document.querySelectorAll('.cognition-ribbons > .ribbon').forEach((r) => {
            out[r.getAttribute('data-intel-section')] =
              r.querySelectorAll('[data-sfeed-row]').length;
          });
          return out;
        }""")


def _dossier_probe(page):
    return page.evaluate(
        """() => {
          const card = document.querySelector(
            '[data-intel-section="dossier"]');
          const rows = Array.from(card.querySelectorAll('[data-sfeed-row]'));
          return {
            rows: rows.length,
            names: rows.map((r) => {
              const n = r.querySelector('.sfeed-item__subject');
              return n ? n.textContent.trim() : '';
            }),
            badges: rows.map((r) => {
              const b = r.querySelector('.sfeed-item__badge');
              return b ? b.textContent.trim() : '';
            }),
            arias: rows.map((r) => r.getAttribute('aria-label') || ''),
            texts: rows.map((r) => {
              const t = r.querySelector('.sfeed-item__text');
              return t ? t.textContent.trim() : '';
            }),
            dates: rows.map((r) => {
              const d = r.querySelector('.sfeed-item__date');
              return d ? d.textContent.trim() : '';
            }),
            heading: card.querySelector('.ribbon-title')
              ? card.querySelector('.ribbon-title').textContent.trim() : '',
            empty: !!card.querySelector('[data-sfeed-empty]'),
            error: !!card.querySelector('[data-sfeed-error]'),
          };
        }""")


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    result = {"checks": {}, "viewports": {}, "console": [], "screenshots": []}
    failures = []

    def check(name, value):
        result["checks"][name] = bool(value)
        if not value:
            failures.append(name)

    httpd = _start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def new_page(width, height, reduced=False, dossier_fail=False):
                ctx = browser.new_context(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce" if reduced else "no-preference")
                ctx.add_init_script(M.TMA_STUB)
                ctx.route(
                    "**/api/**",
                    lambda route: _api_handler(route, dossier_fail=dossier_fail))
                page = ctx.new_page()
                errors = []

                def on_console(m):
                    if m.type != "error":
                        return
                    text = m.text[:200]
                    # 503 — ожидаемое сетевое состояние в сценарии отказа;
                    # проверяется отдельным data-sfeed-error, не console.
                    if dossier_fail and ("Failed to load resource" in text
                                         or "503" in text):
                        return
                    errors.append(text)

                page.on("console", on_console)
                page.on("pageerror", lambda e: errors.append(
                    "pageerror: " + str(e)[:200]))
                page.goto(base + "#/", wait_until="load")
                page.wait_for_selector('[data-intel-widget]', timeout=12000)
                page.wait_for_selector(
                    '[data-intel-section="dossier"]', state="attached",
                    timeout=12000)
                page.wait_for_timeout(900)
                return ctx, page, errors

            # ── 1. Все viewport: 5 лент, 3+2 / 2+2+1 / 1, overflow, строки ──
            PLAN = [
                (1920, 1080, 3, [3, 2], "desktop_1920"),
                (1440, 900, 3, [3, 2], "desktop_1440"),
                (1280, 800, 3, [3, 2], "desktop_1280"),
                (768, 1024, 2, [2, 2, 1], "tablet_768"),
                (390, 844, 1, [1], "mobile_390"),
                (320, 700, 1, [1], "mobile_320"),
            ]
            for width, height, cols, rows, name in PLAN:
                ctx, page, errors = new_page(width, height)
                geo = _geometry(page)
                over = _overflow(page)
                live = _ribbon_rows(page)
                dossier = _dossier_probe(page)
                result["viewports"][name] = {
                    "geometry": geo, "overflow": over, "rows": live,
                    "dossier": dossier,
                }
                check(name + "_five_sections", geo["count"] == 5)
                check(name + "_visible_cards",
                      geo["visible"] == (1 if width <= 767 else 5))
                check(name + "_section_order",
                      geo["sections"] == ["facts", "beliefs", "paradigms",
                                          "traits", "dossier"])
                check(name + "_grid_cols", geo["cols"] == cols)
                check(name + "_grid_rows", geo["rows"] == rows)
                check(name + "_no_h_overflow", over["page"] and over["cards"])
                check(name + "_five_live_ribbons",
                      all(live.get(k, 0) >= 1 for k in
                          ("facts", "beliefs", "paradigms", "traits", "dossier")))
                check(name + "_dossier_not_1to1",
                      dossier["rows"] == 4 and
                      dossier["names"].count("Аня") == 1)
                check(name + "_dossier_count_badge",
                      any("досье · 2" in b for b in dossier["badges"]))
                check(name + "_dossier_unknown_honest",
                      "Участники не определены" in dossier["names"])
                check(name + "_dossier_provenance",
                      any("записей: 2" in a and "источник:" in a
                          for a in dossier["arias"]))
                check(name + "_dossier_date_not_event",
                      bool(dossier["dates"][0]))
                shot = os.path.join(SHOTS, "status-five-ribbons-%s.png" % name)
                page.screenshot(path=shot, full_page=True)
                result["screenshots"].append(shot)

                if width <= 767:
                    # 1a. Mobile: одна лента + 5 вкладок; «Досье» открывается.
                    facts = page.query_selector(
                        '[data-intel-section="facts"]')
                    dossier_card = page.query_selector(
                        '[data-intel-section="dossier"]')
                    check(name + "_mobile_tabs_visible",
                          page.is_visible('[data-intel-switcher]'))
                    check(name + "_mobile_one_visible",
                          page.is_visible('[data-intel-section="facts"]')
                          and not page.is_visible(
                              '[data-intel-section="dossier"]'))
                    check(name + "_mobile_five_tabs",
                          page.evaluate(
                              "document.querySelectorAll("
                              "'[data-intel-tab-btn]').length") == 5)
                    tab = page.query_selector(
                        '[data-intel-tab-btn="dossier"]')
                    box = tab.bounding_box()
                    check(name + "_mobile_touch_44",
                          bool(box) and box["height"] >= 43.5
                          and box["width"] >= 43.5)
                    page.click('[data-intel-tab-btn="dossier"]')
                    page.wait_for_timeout(250)
                    check(name + "_mobile_dossier_visible",
                          page.is_visible('[data-intel-section="dossier"]')
                          and not page.is_visible(
                              '[data-intel-section="facts"]'))
                    check(name + "_mobile_aria_current",
                          page.evaluate(
                              "(() => { const b = document.querySelector("
                              "'[data-intel-tab-btn=\"dossier\"]');"
                              " return b.getAttribute('aria-current') === 'page'"
                              " && b.getAttribute('aria-selected') === 'true'"
                              " && b.getAttribute('tabindex') === '0'; })()"))
                    # Клавиатура: с «Досье» ArrowLeft → «Эволюция».
                    page.focus('[data-intel-tab-btn="dossier"]')
                    page.keyboard.press("ArrowLeft")
                    page.wait_for_timeout(250)
                    check(name + "_mobile_keyboard",
                          page.evaluate(
                              "document.activeElement.getAttribute("
                              "'data-intel-tab-btn')") == "traits"
                          and page.is_visible(
                              '[data-intel-section="traits"]'))
                    # Оставляем «Досье» видимым для проверок detail ниже.
                    page.click('[data-intel-tab-btn="dossier"]')
                    page.wait_for_timeout(150)

                # 1b. Detail: клик по человеку → существующее окно записи.
                page.click('[data-intel-section="dossier"] '
                           '[data-sfeed-row]')
                page.wait_for_selector('[data-sfeed-modal]', timeout=4000)
                modal_text = page.inner_text('[data-sfeed-modal]')
                check(name + "_detail_full_text",
                      "Аня переехала в другой район" in modal_text)
                check(name + "_detail_provenance",
                      "Первоисточники" in modal_text and
                      "Дата события" in modal_text)
                check(name + "_detail_dossier_action",
                      page.is_visible('[data-rec-dossier]'))
                page.click('[data-rec-dossier]')
                page.wait_for_selector('#dossier-edit', timeout=4000)
                check(name + "_dossier_modal_open",
                      page.is_visible('#dossier-edit'))
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)
                check(name + "_dossier_modal_closed",
                      not page.is_visible('#dossier-edit'))

                if errors:
                    result["console"].append({"viewport": name,
                                              "errors": errors[:8]})
                    failures.append(name + "_console_clean")
                ctx.close()

            # ── 2. Pause/resume: авто-движение, wheel-пауза, возврат ──────
            ctx, page, errors = new_page(1440, 900)
            sel = '[data-intel-section="dossier"] .sfeed-viewport'
            page.wait_for_function(
                "() => { const v = document.querySelector("
                "'[data-intel-section=\"dossier\"] .sfeed-viewport');"
                " return v && v.scrollHeight > v.clientHeight + 20; }",
                timeout=6000)
            start = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            page.wait_for_timeout(1400)
            moved = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            check("pause_autoplay_runs", moved > start + 2)
            page.evaluate(
                "(() => { const v = document.querySelector('%s');"
                " v.dispatchEvent(new WheelEvent('wheel',"
                " {deltaY: 40, bubbles: true})); })()" % sel)
            page.wait_for_timeout(250)
            paused = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            page.wait_for_timeout(1000)
            still = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            check("pause_holds_after_wheel", abs(still - paused) <= 1)
            page.wait_for_timeout(3400)
            resumed = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            check("pause_resumes_autoplay", resumed > still + 2)
            page.screenshot(path=os.path.join(
                SHOTS, "status-dossier-paused-resumed.png"))
            check("pause_console_clean", not errors)
            ctx.close()

            # ── 3. Scope: «Тихий чат» не показывает данные Audit Chat ─────
            ctx, page, errors = new_page(1440, 900)
            page.click(".scope-trigger")
            page.click(".scope-option:has-text('%s')" % EMPTY_TITLE)
            page.wait_for_timeout(1400)
            scoped = page.evaluate(
                """() => {
                  const card = document.querySelector(
                    '[data-intel-section="dossier"]');
                  return {text: card.innerText, rows:
                    card.querySelectorAll('[data-sfeed-row]').length,
                    empty: !!card.querySelector('[data-sfeed-empty]')};
                }""")
            result["scope_empty"] = scoped
            check("scope_empty_no_foreign_rows", scoped["rows"] == 0)
            check("scope_empty_honest_text",
                  scoped["empty"] and "выбранном чате" in scoped["text"])
            check("scope_empty_no_foreign_name", "Аня" not in scoped["text"])
            page.screenshot(path=os.path.join(
                SHOTS, "status-dossier-empty-chat.png"), full_page=True)
            page.click(".scope-trigger")
            page.click(".scope-option:has-text('%s')" % CHAT_TITLE)
            page.wait_for_timeout(1400)
            back = page.evaluate(
                "document.querySelectorAll("
                "'[data-intel-section=\"dossier\"] [data-sfeed-row]').length")
            check("scope_back_returns_rows", back >= 3)
            check("scope_console_clean", not errors)
            ctx.close()

            # ── 4. Reduced motion: лента не двигается, контент на месте ───
            ctx, page, errors = new_page(1440, 900, reduced=True)
            page.wait_for_selector(
                '[data-intel-section="dossier"] [data-sfeed-row]')
            before = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            page.wait_for_timeout(1600)
            after = page.evaluate(
                "document.querySelector('%s').scrollTop" % sel)
            check("reduced_motion_no_scroll", abs(after - before) <= 0)
            check("reduced_motion_content_present",
                  page.inner_text('[data-intel-section="dossier"]')
                  .find("Аня") >= 0)
            check("reduced_motion_console_clean", not errors)
            ctx.close()

            # ── 5. 503 dossier_feed: причина, не «0 записей» ──────────────
            ctx, page, errors = new_page(1440, 900, dossier_fail=True)
            fail_state = _dossier_probe(page)
            result["dossier_503"] = fail_state
            check("dossier_503_error_visible", fail_state["error"] is True)
            check("dossier_503_not_zero",
                  fail_state["error"] and not fail_state["empty"])
            check("dossier_503_console_clean", not errors)
            page.screenshot(path=os.path.join(
                SHOTS, "status-dossier-503.png"))
            ctx.close()

            browser.close()
    finally:
        httpd.shutdown()

    result["failures"] = failures
    result["ok"] = not failures
    result["limitations"] = [
        "Synthetic Playwright API stub; production bytes of the release "
        "candidate are served locally, not a live TMA session.",
        "No backend/DDL/flags/prompts changed; the same dossier_feed "
        "endpoint is reused.",
    ]
    with open(REPORT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": result["ok"], "checks": len(result["checks"]),
                      "failures": failures}, ensure_ascii=False))
    print("report:", REPORT)
    print("M4B-STATUS-E2E-OK" if result["ok"] else "M4B-STATUS-E2E-FAIL")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
