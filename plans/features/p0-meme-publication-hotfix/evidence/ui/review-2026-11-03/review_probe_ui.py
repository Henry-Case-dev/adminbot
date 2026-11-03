# -*- coding: utf-8 -*-
"""Reviewer adversarial UI probe for the initiative page recomposition."""
import importlib.util, json, os, sys
REPO = r"C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\evol-71536a366a11-a15826a0"
OUT = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("rw", os.path.join(REPO, "tests", "ui_initiative_rework_e2e.py"))
RW = importlib.util.module_from_spec(spec)
sys.modules["rw"] = RW
spec.loader.exec_module(RW)
PORT = 8874
RW.PORT = PORT
RW.BASE = "http://127.0.0.1:%d" % PORT
CHAT_A = RW.CHAT_A
CHAT_B = RW.CHAT_B
NOW = RW.NOW
RESULT = {"fails": [], "notes": {}}

def rec(key, value):
    RESULT["notes"][key] = value

def fail(msg):
    RESULT["fails"].append(msg)
    print("  FAIL " + msg)

def ok(msg):
    print("  ok   " + msg)

MODE = {"pubs": "rows"}
_inner = RW.make_api_handler()

def handler(route):
    req = route.request
    url = req.url
    path = url.split("?")[0]
    chat_hdr = req.headers.get("x-chat-id") or ""
    RW.STATE["requests"].append(path + ("?" + url.split("?")[1] if "?" in url else ""))
    if MODE.get("detail") and path.endswith("/api/initiative/publications/detail"):
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(MODE["detail"], ensure_ascii=False))
    if path.endswith("/api/initiative/meme-settings") and req.method != "POST":
        payload = RW._meme_settings()
        payload["chat_id"] = int(chat_hdr) if chat_hdr.lstrip("-").isdigit() else CHAT_A
        payload["prompts"]["joke"]["text"] = "JOKE-FOR-" + str(payload["chat_id"])
        payload["prompts"]["image"]["text"] = "IMG-FOR-" + str(payload["chat_id"]) + " {joke}"
        if chat_hdr.strip() == str(CHAT_B):
            payload["quota"]["spent"] = 0
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(payload, ensure_ascii=False))
    if path.endswith("/api/initiative/publications") and req.method == "GET":
        if MODE["pubs"] == "empty":
            body = {"schema_version": 1, "generated_at": NOW,
                    "chat_id": CHAT_A, "available": True, "notes": [],
                    "filters": {}, "rows": [],
                    "counts": {"total": 0, "text": 0, "meme": 0,
                               "published": 0, "not_delivered": 0},
                    "next_offset": None}
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(body, ensure_ascii=False))
        if MODE["pubs"] == "long":
            long_label = ("устаревшая бронь публикации, потому что другой механизм "
                          "уже занял слот отправки в этом чате и удерживает бронь "
                          "дольше разрешённого интервала координации отправки")
            rows = [{"attempt_id": "meme:long-1", "kind": "meme", "job_id": "long-1",
                     "mode": "auto", "ts": NOW, "stage": "publish",
                     "outcome": "skipped", "reason_code": "publication_stale",
                     "reason_label": long_label, "delivered": False,
                     "message_id": None, "chain_len": 4,
                     "window_messages": 300, "limit_source": "model_capability",
                     "limit_value": 400}]
            body = {"schema_version": 1, "generated_at": NOW, "chat_id": CHAT_A,
                    "available": True, "notes": [], "filters": {}, "rows": rows,
                    "counts": {"total": 1, "text": 0, "meme": 1,
                               "published": 0, "not_delivered": 1},
                    "next_offset": None}
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(body, ensure_ascii=False))
    return _inner(route)

SDK_STUB = RW.SDK_STUB

def new_page(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width <= 430, has_touch=width <= 430)
    ctx.route("**/api/**", handler)
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda route: route.fulfill(status=200,
                                          content_type="application/javascript",
                                          body=SDK_STUB))
    ctx.add_init_script(
        "try { localStorage.setItem('adminbot.active_chat_id', '%d'); } catch (e) {}"
        % CHAT_A)
    page = ctx.new_page()
    page.set_default_timeout(20000)
    return ctx, page

def open_page(page, tab=None):
    url = RW.BASE + "/#/modules/initiative" + ("/" + tab if tab else "")
    page.goto(url, wait_until="load")
    page.wait_for_selector("header.header-sticky", state="visible")
    page.wait_for_timeout(800)

def open_tab(page, tab):
    page.click('[data-workspace-tab="%s"]' % tab)
    page.wait_for_timeout(700)

def shot(page, name):
    try:
        page.screenshot(path=os.path.join(OUT, name + ".png"), full_page=True)
    except Exception as e:
        print("  shot failed " + str(e))

STRUCT_PROBE = r"""
() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {x: Math.round(r.left), y: Math.round(r.top),
            w: Math.round(r.width), h: Math.round(r.height)};
  };
  const tabsEl = document.querySelector('[data-workspace-tabs]');
  return {
    title: strip((document.querySelector('.workspace-head .text-base') || {}).textContent),
    scope: strip((document.querySelector('[data-workspace-scope]') || {}).textContent),
    state: strip((document.querySelector('.workspace-head .badge:last-child') || {}).textContent),
    badges: Array.from(document.querySelectorAll('.workspace-head .badge'))
      .map((el) => strip(el.textContent)),
    scopeTrigger: strip((document.querySelector('.scope-trigger .scope-name') || {}).textContent),
    catalog: !!document.querySelector('[data-module-managed-link]'),
    tabs: Array.from(document.querySelectorAll('[data-workspace-tab]'))
      .map((el) => strip(el.textContent)),
    tabHeights: Array.from(document.querySelectorAll('[data-workspace-tab]'))
      .map((el) => Math.round(el.getBoundingClientRect().height)),
    stripScroll: tabsEl ? {sw: tabsEl.scrollWidth, cw: tabsEl.clientWidth,
                           overflowX: getComputedStyle(tabsEl).overflowX} : null,
    pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
    bodyOverflow: document.body.scrollWidth - window.innerWidth,
    textRect: rect('[data-ini-card="text"]'),
    memeRect: rect('[data-ini-card="meme"]'),
    coord: strip((document.querySelector('[data-ini-coordination]') || {}).textContent),
    coordState: (document.querySelector('[data-ini-coordination]') || {}).getAttribute
      ? document.querySelector('[data-ini-coordination]').getAttribute('data-ini-coord-state') : null,
    events: Array.from(document.querySelectorAll('[data-ini-event]'))
      .map((el) => strip(el.textContent)),
    overviewH: (rect('[data-initiative-overview]') || {}).h,
    glassOneLine: Array.from(document.querySelectorAll('.glass'))
      .filter((el) => el.getBoundingClientRect().height < 70
              && el.getBoundingClientRect().width > window.innerWidth * 0.7).length,
  };
}
"""

TABS = ["overview", "text", "memes", "publications", "diagnostics"]
MARK = {"overview": "[data-initiative-overview]", "text": "[data-initiative-text]",
        "memes": "[data-meme-settings]",
        "publications": "[data-initiative-publications]",
        "diagnostics": "[data-initiative-diagnostics]"}


def scenario_layout(browser, width, height, label):
    print("== LAYOUT %s (%sx%s) ==" % (label, width, height))
    ctx, page = new_page(browser, width, height)
    try:
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        open_page(page, "overview")
        d = page.evaluate(STRUCT_PROBE)
        rec("layout-" + label, {k: d[k] for k in
                                ("title", "scope", "state", "scopeTrigger", "catalog", "tabs",
                                 "tabHeights", "stripScroll", "pageOverflow",
                                 "textRect", "memeRect", "events", "overviewH",
                                 "glassOneLine")})
        print("  title=%r scope=%r state=%r scopeTrigger=%r catalog=%s" %
              (d["title"], d["scope"], d["state"], d["scopeTrigger"], d["catalog"]))
        print("  tabs=%r heights=%r strip=%r" % (d["tabs"], d["tabHeights"], d["stripScroll"]))
        print("  badges=%r" % (d["badges"],))
        print("  cards text=%r meme=%r" % (d["textRect"], d["memeRect"]))
        print("  pageOverflow=%s coord=%r" % (d["pageOverflow"], d["coord"][:90]))
        if d["tabs"] != ["Обзор", "Текстовая инициатива", "Мемы", "Публикации", "Диагностика"]:
            fail("вкладки не те: %r" % (d["tabs"],))
        else:
            ok("пять вкладок в правильном порядке")
        if not (d["title"] == "Инициатива" and d["scope"] and d["state"] and d["catalog"] and d["scopeTrigger"]):
            fail("шапка неполная: %r" % ({k: d[k] for k in ("title", "scope", "state", "catalog")},))
        else:
            ok("шапка: название, область, состояние, ссылка в каталог")
        if d["pageOverflow"] > 1:
            fail("%s: горизонтальная прокрутка страницы %d px" % (label, d["pageOverflow"]))
        else:
            ok("%s: страница без горизонтальной прокрутки" % label)
        if min(d["tabHeights"]) < 32:
            fail("%s: тач-цель вкладки %r" % (label, d["tabHeights"]))
        if width >= 1200:
            if not d["textRect"] or not d["memeRect"] or d["textRect"]["y"] != d["memeRect"]["y"]:
                fail("%s: карточки не в один ряд на десктопе" % label)
            elif abs(d["textRect"]["w"] - d["memeRect"]["w"]) > 2:
                fail("%s: карточки разной ширины %r/%r" % (label, d["textRect"]["w"], d["memeRect"]["w"]))
            else:
                ok("%s: две равные карточки в один ряд (%d px)" % (label, d["textRect"]["w"]))
        elif width >= 768:
            if not (d["textRect"] and d["memeRect"] and d["textRect"]["y"] < d["memeRect"]["y"]):
                fail("%s: на 768-1199 карточки не в одну колонку" % label)
            else:
                ok("%s: одна колонка на 768-1199" % label)
        if not (3 <= len(d["events"]) <= 5):
            fail("%s: значимых событий %d" % (label, len(d["events"])))
        else:
            ok("%s: событий %d (3-5)" % (label, len(d["events"])))
        if d["glassOneLine"]:
            fail("%s: %d однострочных блока на всю ширину" % (label, d["glassOneLine"]))
        for tab in TABS:
            open_tab(page, tab)
            present = page.evaluate("(s) => !!document.querySelector(s)", MARK[tab])
            ov = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
            if not present:
                fail("%s: вкладка %s не отрисовала блок" % (label, tab))
            if ov > 1:
                fail("%s: вкладка %s даёт прокрутку страницы %d px" % (label, tab, ov))
        ok("%s: все пять вкладок отрисованы, прокрутки страницы нет" % label)
        if errors:
            fail("%s: ошибки консоли %r" % (label, errors[:2]))
        shot(page, "layout_%s" % label)
    finally:
        ctx.close()


def scenario_coordination(browser):
    print("== COORDINATION: не симуляция отсчёта ==")
    ctx, page = new_page(browser, 1536, 960)
    try:
        open_page(page, "overview")
        a = page.evaluate("() => (document.querySelector('[data-ini-coordination]') || {}).textContent || ''")
        page.wait_for_timeout(4500)
        b = page.evaluate("() => (document.querySelector('[data-ini-coordination]') || {}).textContent || ''")
        rec("coordination", {"t0": a.strip(), "t45": b.strip()})
        print("  t0 =%r" % a.strip()[:160])
        print("  t45=%r" % b.strip()[:160])
        if a.strip() != b.strip():
            fail("полоса координации меняется сама во времени (клиентский отсчёт)")
        else:
            ok("полоса координации статична между запросами (факт из API)")
        if "ожида" in a.lower() or "свободно" in a.lower() or "занят" in a.lower():
            ok("состояние координации выражено словами из API")
    finally:
        ctx.close()


def scenario_budget_auto(browser):
    print("== BUDGET: пустой потолок = auto ==")
    ctx, page = new_page(browser, 1536, 960)
    try:
        base = RW._meme_settings()
        AUTO = dict(base)
        AUTO["length_limit"] = {"ceiling": None, "source": "auto",
                                "template_chars": 5, "joke_budget": None,
                                "known": False, "placeholder": None,
                                "candidates": []}
        AUTO["settings"] = dict(base["settings"])
        AUTO["settings"]["length_admin"] = None
        RW._meme_settings = lambda: AUTO
        open_page(page, "memes")
        page.wait_for_timeout(700)
        d = page.evaluate(r"""
        () => {
          const t = (s) => ((document.querySelector(s) || {}).textContent || '').replace(/\s+/g, ' ').trim();
          const all = ((document.querySelector('[data-meme-settings]') || {}).textContent || '')
            .replace(/\s+/g, ' ');
          return {ceiling: t('[data-meme-limit-ceiling]'),
                  template: t('[data-meme-limit-template]'),
                  joke: t('[data-meme-limit-joke]'),
                  actual: t('[data-meme-limit-actual]'),
                  unknown: !!document.querySelector('[data-meme-budget-unknown]'),
                  field: !!document.querySelector('[data-meme-length-limit]'),
                  bad: ['NaN', 'undefined', '0/800', '771'].filter((x) => all.indexOf(x) >= 0)};
        }
        """)
        rec("budget-auto", d)
        print("  %r" % d)
        if "Автоматически" not in (d["ceiling"] + d["joke"]):
            fail("пустой потолок не показан как «Автоматически»: %r" % d)
        else:
            ok("пустой потолок = «Автоматически»")
        if d["bad"]:
            fail("в бюджете фиктивные значения %r" % d["bad"])
        else:
            ok("нет 0/800/NaN/undefined в бюджете")
    finally:
        RW._meme_settings = lambda: base
        ctx.close()


def scenario_publications(browser, mode, label):
    print("== PUBLICATIONS: %s ==" % label)
    MODE["pubs"] = mode
    ctx, page = new_page(browser, 1536, 960)
    try:
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        open_page(page, "publications")
        page.wait_for_timeout(900)
        d = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const box = document.querySelector('[data-initiative-publications]');
          const rows = Array.from(document.querySelectorAll('[data-ini-pub-row]'));
          return {rows: rows.length,
                  text: strip((box || {}).textContent).slice(0, 400),
                  rowTexts: rows.map((r) => strip(r.textContent).slice(0, 200)),
                  empty: !!document.querySelector('[data-ini-pub-empty]'),
                  emptyDetails: Array.from(document.querySelectorAll('[data-ini-pub-detail]')).length,
                  overflow: document.documentElement.scrollWidth - window.innerWidth,
                  tableHeaders: document.querySelectorAll('[data-ini-pub-row] th').length};
        }
        """)
        rec("publications-" + mode, d)
        print("  rows=%d empty=%s overflow=%d" % (d["rows"], d["empty"], d["overflow"]))
        print("  text=%r" % d["text"][:240])
        if d["overflow"] > 1:
            fail("%s: горизонтальная прокрутка %d px" % (label, d["overflow"]))
        if mode == "empty":
            if d["rows"] != 0:
                fail("пустой журнал нарисовал %d строк" % d["rows"])
            if not d["empty"]:
                fail("пустой журнал без честного пустого состояния")
            else:
                ok("пустой журнал: пустое состояние, строк нет")
        if mode == "long":
            if d["rows"] != 1:
                fail("длинная причина: строк %d" % d["rows"])
            if any("неизвест" in x.lower() for x in d["rowTexts"]):
                pass
        if errors:
            fail("%s: ошибки консоли %r" % (label, errors[:2]))
        shot(page, "pubs_%s" % mode)
    finally:
        ctx.close()


def scenario_unsaved(browser):
    print("== UNSAVED EDIT + TAB SWITCH ==")
    RW.STATE["post_count"] = 0
    RW.STATE["prompt_joke"] = "Серверный прикол."
    RW.STATE["joke_source"] = "chat"
    ctx, page = new_page(browser, 1536, 960)
    try:
        open_page(page, "memes")
        page.wait_for_selector("textarea[data-meme-prompt-joke]", state="visible")
        page.fill("textarea[data-meme-prompt-joke]", "ЧЕРНОВИК 123")
        dirty = page.evaluate(r"""
        () => {
          const t = (s) => ((document.querySelector(s) || {}).textContent || '').trim();
          return {hint: t('[data-meme-dirty]'),
                  saveDisabled: ((document.querySelector('[data-meme-save]') || {}).disabled !== false),
                  value: document.querySelector('textarea[data-meme-prompt-joke]').value};
        }
        """)
        open_tab(page, "overview")
        open_tab(page, "memes")
        page.wait_for_timeout(700)
        after = page.evaluate(r"""
        () => {
          const el = document.querySelector('textarea[data-meme-prompt-joke]');
          const t = (s) => ((document.querySelector(s) || {}).textContent || '').trim();
          return {value: el ? el.value : null, hint: t('[data-meme-dirty]')};
        }
        """)
        rec("unsaved", {"before": dirty, "after": after,
                        "post_count": RW.STATE["post_count"]})
        print("  до переключения: %r" % dirty)
        print("  после возврата:  %r (POST=%d)" % (after, RW.STATE["post_count"]))
        if RW.STATE["post_count"] != 0:
            fail("переключение вкладок отправило %d POST" % RW.STATE["post_count"])
        if after["value"] == "ЧЕРНОВИК 123":
            ok("черновик пережил переключение вкладок")
        elif after["value"] == "Серверный прикол.":
            fail("черновик потерян молча: поле вернулось к серверному значению без предупреждения")
    finally:
        ctx.close()


def scenario_chat_switch(browser):
    print("== CHAT SWITCH: нет данных прошлого чата ==")
    ctx, page = new_page(browser, 1536, 960)
    try:
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        open_page(page, "memes")
        page.wait_for_timeout(700)
        before = page.evaluate(
            "() => (document.querySelector('textarea[data-meme-prompt-joke]') || {}).value")
        opened = page.evaluate(r"""
        () => {
          const btn = document.querySelector('.scope-trigger');
          if (btn) { btn.click(); return true; }
          return false;
        }
        """)
        if not opened:
            fail("не нашёл переключатель области действия (.scope-trigger)")
            return
        page.wait_for_timeout(500)
        picked = page.evaluate(r"""
        () => {
          const items = Array.from(document.querySelectorAll('.scope-option'));
          const target = items.find((el) => el.textContent.indexOf('B') >= 0
            && el.textContent.indexOf('Чат') >= 0);
          if (target) { target.click(); return true; }
          return false;
        }
        """)
        if not picked:
            fail("не нашёл чат B в списке области")
            return
        page.wait_for_timeout(1400)
        after = page.evaluate(r"""
        () => {
          const t = (s) => ((document.querySelector(s) || {}).textContent || '').trim();
          const el = document.querySelector('textarea[data-meme-prompt-joke]');
          return {value: el ? el.value : null,
                  topline: t('[data-ini-meme-topline]'),
                  today: t('[data-ini-meme-today]'),
                  scope: t('[data-workspace-scope]')};
        }
        """)
        rec("chat-switch", {"before": before, "after": after})
        print("  чат A промпт=%r" % before)
        print("  после переключения: value=%r scope=%r today=%r" %
              (after["value"], after["scope"], after["today"][:80]))
        if after["value"] and "FOR-" + str(CHAT_A) in after["value"]:
            fail("на экране остались данные прошлого чата: %r" % after["value"])
        elif after["value"] and "FOR-" + str(CHAT_B) in after["value"]:
            ok("после смены чата промпт перечитан из нового чата")
        else:
            fail("после смены чата промпт не относится ни к одному чату: %r" % after["value"])
        if errors:
            fail("ошибки консоли при смене чата %r" % errors[:2])
    finally:
        ctx.close()

def _detail_payload():
    speech = {
        "composer": "on", "system_sha12": "f0c2695c31ca",
        "manifest": "62aaae1adf259de9",
        "core": "r21.848ba4c426b8", "expression": "386f4ac001c1",
        "humor": "402b6636e025", "humor_status": "rendered",
        "layers": [
            {"layer": "core", "revision": "r21.848ba4c426b8", "chars": 900,
             "rendered": True, "skip": ""},
            {"layer": "humor", "revision": "402b6636e025", "chars": 210,
             "rendered": True, "skip": ""},
            {"layer": "expression", "revision": "386f4ac001c1", "chars": 0,
             "rendered": False, "skip": "expression_layer_disabled"},
            {"layer": "style_policy", "revision": "g5.6aff783e44a7", "chars": 0},
        ],
    }
    chain = [
        {"stage": "summary", "ts": NOW - 50, "outcome": "passed",
         "reason_code": "", "reason_label": "",
         "facts": {"chars": 41}, "limit_source": "model_capability",
         "limit_value": 400, "window_messages": 300},
        {"stage": "joke", "ts": NOW - 40, "outcome": "passed",
         "reason_code": "", "reason_label": "",
         "facts": {"limit": 395, "template_chars": 5, "ceiling": 400,
                   "chars": 6, "speech": speech},
         "limit_source": "model_capability", "limit_value": 400,
         "window_messages": 300},
        {"stage": "image_generation", "ts": NOW - 30, "outcome": "passed",
         "reason_code": "", "reason_label": "", "facts": {"chars": 23},
         "limit_source": "model_capability", "limit_value": 400,
         "window_messages": 300},
        {"stage": "publish", "ts": NOW - 20, "outcome": "skipped",
         "reason_code": "publication_stale",
         "reason_label": "результат признан потерявшим актуальность",
         "facts": {"publish": {"manual": False, "gate": "open",
                               "claim": {"state": "released"}}},
         "limit_source": "model_capability", "limit_value": 400,
         "window_messages": 300},
    ]
    return {"schema_version": 1, "available": True, "notes": [],
            "attempt": {"attempt_id": "meme:probe-1", "kind": "meme",
                        "job_id": "probe-1", "mode": "auto", "ts": NOW - 20,
                        "stage": "publish", "outcome": "skipped",
                        "reason_code": "publication_stale",
                        "delivered": False, "message_id": None},
            "chain": chain, "events": [],
            "delivery": {"delivered": False, "message_id": None}}


def scenario_diagnostics(browser):
    print("== DIAGNOSTICS: вошёл/пропущен и сжатость ==")
    MODE["detail"] = _detail_payload()
    ctx, page = new_page(browser, 1536, 960)
    try:
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        open_page(page, "publications")
        page.wait_for_timeout(900)
        clicked = page.evaluate(r"""
        () => {
          const rows = Array.from(document.querySelectorAll('[data-ini-pub-row]'));
          const target = rows.find((el) => (el.getAttribute('data-ini-pub-row') || '')
            .indexOf('job-76') >= 0);
          if (target) { target.click(); return target.getAttribute('data-ini-pub-row'); }
          return rows.length ? rows[1].getAttribute('data-ini-pub-row') : null;
        }
        """)
        page.wait_for_timeout(900)
        print("  открыл попытку: %r" % clicked)
        trace_clicked = page.evaluate(r"""
        () => {
          const b = document.querySelector('[data-ini-pub-trace]');
          if (b) { b.click(); return true; }
          return false;
        }
        """)
        page.wait_for_timeout(900)
        if not trace_clicked:
            open_tab(page, "diagnostics")
            page.wait_for_timeout(700)
        in_diag = page.evaluate(
            "() => !!document.querySelector('[data-ini-trace-group]')")
        print("  трасса открыта на вкладке «Диагностика»: %s" % in_diag)
        groups = page.evaluate(r"""
        () => {
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          const box = document.querySelector('[data-initiative-diagnostics]');
          const titles = Array.from(box ? box.querySelectorAll('button, summary') : [])
            .map((el) => strip(el.textContent)).filter((t) => t.length > 2 && t.length < 80);
          return {titles: titles.slice(0, 20),
                  text: box ? strip(box.textContent).slice(0, 600) : ''};
        }
        """)
        rec("diag-groups", groups["titles"])
        print("  groups=%r" % groups["titles"])
        print("  text=%r" % groups["text"][:300])
        compact = page.evaluate(r"""
        () => {
          const box = document.querySelector('[data-initiative-diagnostics]');
          const t = box ? box.textContent : '';
          return {hash: t.indexOf('f0c2695c31ca') >= 0,
                  manifest: t.indexOf('62aaae1adf259de9') >= 0,
                  textLen: t.length};
        }
        """)
        rec("diag-compact", compact)
        print("  compact: %r" % compact)
        if compact["manifest"]:
            fail("манифест/хеши показаны сразу, без раскрытия")
        else:
            ok("тяжёлые данные (хеши, манифест) скрыты по умолчанию")
        # раскрыть группы речевых слоёв и этапов
        for key in ("speech", "stages", "send", "events", "conditions", "random", "context"):
            page.evaluate(r"""
            (k) => {
              const g = document.querySelector('[data-ini-trace-group="' + k + '"]');
              if (!g) return;
              const head = g.querySelector('.ini-trace__head') || g.querySelector('[aria-expanded]');
              if (head) head.click();
            }
            """, key)
            page.wait_for_timeout(120)
        page.evaluate(r"""
        () => {
          Array.from(document.querySelectorAll('[data-ini-trace-group] details'))
            .forEach((d) => { d.open = true; });
        }
        """)
        page.wait_for_timeout(500)
        opened = page.evaluate(r"""
        () => {
          const box = document.querySelector('[data-initiative-diagnostics]');
          const t = box ? box.textContent : '';
          const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
          return {hash: t.indexOf('f0c2695c31ca') >= 0,
                  manifest: t.indexOf('62aaae1adf259de9') >= 0,
                  entered: (t.match(/вошёл/g) || []).length,
                  skipped: (t.match(/пропущен/g) || []).length,
                  speechGroup: strip((document.querySelector('[data-ini-trace-group="speech"]') || {}).textContent).slice(0, 700),
                  manifestCopy: strip((document.querySelector('[data-ini-trace-manifest-text]') || {}).textContent),
                  crowd: (t.match(/фактов этапа нет/g) || []).length,
                  text: strip(t).slice(0, 1200)};
        }
        """)
        rec("diag-opened", {k: opened[k] for k in
                            ("hash", "manifest", "entered", "skipped", "crowd")})
        print("  opened: %r" % {k: opened[k] for k in
                                ("hash", "manifest", "entered", "skipped", "crowd")})
        print("  text=%r" % opened["text"][:700])
        print("  speechGroup=%r" % opened.get("speechGroup", "")[:400])
        print("  manifestCopy=%r" % opened.get("manifestCopy", "")[:260])
        if not opened["manifest"]:
            fail("после раскрытия манифест/хеши так и не показаны")
        else:
            ok("после раскрытия видны id/хеши сборки")
        if opened["entered"] not in (2, 4):
            fail("«вошёл» показан %d раз при двух слоях rendered=true" % opened["entered"])
        else:
            ok("«вошёл» ровно у двух слоёв с rendered=true, слой без rendered не выдан за вошедший")
        if opened["crowd"] > 0:
            fail("в диагностике снова стена «фактов этапа нет»: %d" % opened["crowd"])
        if errors:
            fail("ошибки консоли в диагностике %r" % errors[:2])
        shot(page, "diag_open")
    finally:
        MODE["detail"] = None
        ctx.close()


def scenario_extras(browser):
    print("== EXTRAS: разделение настроек, события, запросы, фокус ==")
    ctx, page = new_page(browser, 1536, 960)
    try:
        RW.STATE["requests"] = []
        open_page(page, "text")
        page.wait_for_timeout(600)
        text_tab = page.evaluate(r"""
        () => {
          const q = (s) => document.querySelectorAll(s).length;
          const limits = document.querySelector('[data-config-group="limits_intent"]');
          return {memeToggle: q('[data-meme-toggle]'),
                  memeWindow: q('[data-meme-window]'),
                  memePrompt: q('[data-meme-prompt-joke]'),
                  memeLength: q('[data-meme-length-limit]'),
                  iniStatus: q('[data-initiative-status]'),
                  perChat: q('[data-initiative-per-chat]'),
                  limitsItems: limits ? limits.querySelectorAll('input, select, textarea')
                    .length : -1,
                  limitsText: limits ? String(limits.textContent).replace(/\s+/g, ' ').trim()
                    .slice(0, 260) : ''};
        }
        """)
        rec("text-tab", text_tab)
        print("  текстовая: %r" % text_tab)
        if text_tab["memeToggle"] or text_tab["memeWindow"] or text_tab["memePrompt"] or text_tab["memeLength"]:
            fail("на вкладке текста остались мем-настройки")
        else:
            ok("на вкладке «Текстовая инициатива» нет мем-настроек")
        if not (text_tab["iniStatus"] and text_tab["perChat"]):
            fail("на вкладке текста нет старых полей инициативы")
        if text_tab["limitsItems"] < 5:
            fail("в «Частота и лимиты» меньше 5 полей: %d" % text_tab["limitsItems"])
        else:
            ok("«Частота и лимиты»: %d полей" % text_tab["limitsItems"])

        RW.STATE["requests"] = []
        open_tab(page, "memes")
        page.wait_for_timeout(700)
        memes = page.evaluate(r"""
        () => {
          const q = (s) => document.querySelectorAll(s).length;
          const t = (s) => ((document.querySelector(s) || {}).textContent || '').trim();
          return {textStatus: q('[data-initiative-status]'),
                  textLimits: q('[data-config-group="limits_intent"]'),
                  toggle: q('[data-meme-toggle]'), window: q('[data-meme-window]'),
                  minMsg: q('[data-meme-min-messages]'), cooldown: q('[data-meme-cooldown]'),
                  daily: q('[data-meme-daily-limit]'), quiet: q('[data-meme-quiet-hours]'),
                  summarizer: q('[data-meme-summarizer]'), length: q('[data-meme-length-limit]'),
                  speech: q('[data-meme-speech]'), delivery: q('[data-meme-delivery]'),
                  analytics: q('[data-meme-analytics]'),
                  quietLabel: t('[data-meme-quiet-hours]'),
                  summarizerLabel: t('[data-meme-summarizer]')};
        }
        """)
        rec("memes-tab", memes)
        print("  мемы: %r" % memes)
        for key in ("toggle", "window", "minMsg", "cooldown", "daily", "quiet",
                    "summarizer", "length", "speech", "delivery", "analytics"):
            if not memes[key]:
                fail("на вкладке «Мемы» нет поля/блока %r" % key)
        if memes["textStatus"] or memes["textLimits"]:
            fail("на вкладке «Мемы» остались настройки текстовой инициативы")
        else:
            ok("на вкладке «Мемы» нет настроек текста")
        reqs = [r for r in RW.STATE["requests"] if "meme-settings" in r]
        print("  запросов meme-settings при входе на вкладку: %d" % len(reqs))
        if len(reqs) > 1:
            fail("вход на вкладку «Мемы» дал %d запросов meme-settings" % len(reqs))
        else:
            ok("один запрос настроек мемов на вход")

        # повторный вход на вкладку не должен дублировать запросы
        RW.STATE["requests"] = []
        open_tab(page, "overview")
        open_tab(page, "memes")
        page.wait_for_timeout(600)
        page.wait_for_timeout(1500)
        RW.STATE["requests"] = []
        open_tab(page, "overview")
        page.wait_for_timeout(1500)
        print("  ОДИН клик -> обзор: %r" % (RW.STATE["requests"],))
        RW.STATE["requests"] = []
        open_tab(page, "memes")
        page.wait_for_timeout(1500)
        print("  ОДИН клик -> мемы: %r" % (RW.STATE["requests"],))
        again = [r for r in RW.STATE["requests"] if "meme-settings" in r]
        print("  запросы после перехода overview->memes: %r" % (RW.STATE["requests"],))
        print("  повторный вход: запросов meme-settings=%d" % len(again))
        if len(again) > 1:
            fail("повторный вход на вкладку «Мемы» дублирует запросы (%d)" % len(again))

        # события «Обзора» ведут в «Публикации»
        open_tab(page, "overview")
        page.wait_for_timeout(500)
        went = page.evaluate(r"""
        () => {
          const ev = document.querySelector('[data-ini-event]');
          if (!ev) return 'нет событий';
          ev.click();
          return 'clicked';
        }
        """)
        page.wait_for_timeout(900)
        on_pubs = page.evaluate(
            "() => !!document.querySelector('[data-initiative-publications]')")
        print("  клик по событию: %s -> вкладка «Публикации»: %s" % (went, on_pubs))
        if not on_pubs:
            fail("клик по значимому событию не ведёт в «Публикации»")
        else:
            ok("событие «Обзора» открывает «Публикации»")

        # фокус с клавиатуры на вкладках
        page.evaluate("() => { const t = document.querySelector('[data-workspace-tab=\"overview\"]'); if (t) t.blur(); }")
        focus = None
        for _ in range(90):
            page.keyboard.press("Tab")
            focus = page.evaluate(r"""
            () => {
              const el = document.activeElement;
              if (!el || !el.getAttribute) return null;
              const isTab = el.getAttribute('data-workspace-tab');
              if (!isTab) return {isTab: null, tag: el.tagName,
                                  label: (el.textContent || '').trim().slice(0, 20)};
              const cs = getComputedStyle(el);
              return {isTab: isTab, tag: el.tagName,
                      focusVisible: el.matches(':focus-visible'),
                      outlineWidth: cs.outlineWidth, outlineStyle: cs.outlineStyle,
                      outlineColor: cs.outlineColor, boxShadow: cs.boxShadow,
                      label: (el.textContent || '').trim()};
            }
            """)
            if focus and focus.get("isTab"):
                break
        rec("focus", focus)
        print("  фокус вкладки: %r" % focus)
        if not focus or not focus.get("isTab"):
            fail("вкладка не получает фокус с клавиатуры")
        elif (focus["outlineStyle"] in ("none", "") and focus["boxShadow"] in ("none", "")):
            fail("у вкладки нет видимой рамки фокуса при keyboard-focus")
        else:
            ok("у вкладки видимая рамка фокуса при keyboard-focus (%s %s)" % (focus["outlineStyle"], focus["outlineWidth"]))
        shot(page, "extras")
    finally:
        ctx.close()




def scenario_shots(browser, width, height, label):
    print("== SHOTS %s ==" % label)
    ctx, page = new_page(browser, width, height)
    try:
        open_page(page, "overview")
        for tab in TABS:
            open_tab(page, tab)
            page.wait_for_timeout(500)
            shot(page, "my_%s_%s" % (tab, label))
    finally:
        ctx.close()

def main():
    httpd = RW.serve_static(PORT, os.path.join(REPO, "web"))
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                ONLY = sys.argv[1] if len(sys.argv) > 1 else ""
                if not ONLY or ONLY == "layout":
                    scenario_layout(browser, 1536, 960, "1536")
                if not ONLY or ONLY == "layout": scenario_layout(browser, 1366, 768, "1366")
                scenario_layout(browser, 768, 1024, "768")
                scenario_layout(browser, 390, 844, "390")
                scenario_layout(browser, 360, 740, "360")
                if not ONLY or ONLY == "coord": scenario_coordination(browser)
                if not ONLY or ONLY == "budget": scenario_budget_auto(browser)
                scenario_publications(browser, "empty", "пустой журнал")
                scenario_publications(browser, "long", "длинная причина")
                MODE["pubs"] = "rows"
                if not ONLY or ONLY == "unsaved": scenario_unsaved(browser)
                if not ONLY or ONLY == "chat": scenario_chat_switch(browser)
                if not ONLY or ONLY == "diag": scenario_diagnostics(browser)
                if not ONLY or ONLY == "extras": scenario_extras(browser)
                if not ONLY or ONLY == "shots":
                    scenario_shots(browser, 1536, 960, "1536")
                    scenario_shots(browser, 390, 844, "390")
            finally:
                browser.close()
    finally:
        httpd.shutdown()
    with open(os.path.join(OUT, "ui_probe_result.json"), "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, ensure_ascii=False, indent=1)
    print("")
    print("RESULT: " + ("PASS" if not RESULT["fails"] else "FAIL (%d)" % len(RESULT["fails"])))
    for item in RESULT["fails"]:
        print("  - " + item)
    return 0 if not RESULT["fails"] else 1


if __name__ == "__main__":
    sys.exit(main())
