"""MOD-ACL-UX-01 M4A W2c (2.58.221) — Playwright-приёмка NAV-01/LAY-01/WF-01.

Реальный `web/index.html` + `web/static/*` на локальном http-сервере;
`/api/*` — стабы из существующего M4A e2e (реальный DTO реестра и каталога).
Проверяются 5 нормативных viewport (1440/1280/768/390/320) + 1680 для
фактического потолка рабочей области:
  * NAV-01: каталог → модуль → подраздел прямым `<a href>`; parent-чип
    подмодуля ведёт на `#/memory/rag` / `#/permsoc`;
  * на родительской поверхности — строки «Настраивается в …» и НЕТ полей
    групп подмодулей (design §6.3);
  * LAY-01: sidebar 190–220; рабочая область сложных ≤1440; малые ≤1000;
    opt-in 8/12+4/12 только на двух sibling-блоках; touch ≥44; без
    горизонтального overflow;
  * WF-01: одна шапка, 3–5 событий «Обзора», классы модулей, единая
    подпись «Расширенные системные».

Запуск: py tools/ui_mod_acl_m4a_w2c_e2e.py
Артефакты: %MOD_ACL_W2C_SHOTS% (по умолчанию evidence/m4a/w2c/shots).
"""
import copy
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import ui_mod_acl_m4_catalog_e2e as e2e  # noqa: E402

PORT = int(os.environ.get("MOD_ACL_W2C_PORT", "8799"))
SHOTS = os.environ.get(
    "MOD_ACL_W2C_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4a", "w2c", "shots"))
VIEWPORTS = [(1680, 1000), (1440, 900), (1280, 800), (768, 1024),
             (390, 844), (320, 568)]
EXPECT_COLUMNS = {1680: 4, 1440: 4, 1280: 3, 768: 2, 390: 1, 320: 1}

# ── config: реальный каталог + явные advanced-параметры для зоны WF-01 ─────
CFG = copy.deepcopy(e2e.CONFIG_GLOBAL)
for _item in CFG.get("items", []):
    if _item.get("group") in ("flags_summary", "limits_summary"):
        _item["progressive_level"] = "advanced"
CFG_CHAT = copy.deepcopy(e2e.CONFIG_CHAT)
for _item in CFG_CHAT.get("items", []):
    if _item.get("group") in ("flags_summary", "limits_summary"):
        _item["progressive_level"] = "advanced"


def _route(route):
    req = route.request
    url = req.url.split("?")[0]
    if url.endswith("/api/config"):
        payload = CFG_CHAT if (req.headers or {}).get("x-chat-id") else CFG
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload))
        return
    if url.endswith("/api/oversight/runs"):
        if "run_id=" in req.url:
            run_id = req.url.split("run_id=")[1].split("&")[0]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "available": True, "enabled": True,
                "run": {"pipeline_run_id": run_id, "pipeline_type": "summary",
                        "status": "succeeded", "started_ts": 1794909500,
                        "updated_ts": 1794909510, "duration_ms": 10000,
                        "stages_total": 2, "stages_failed": 0, "stages_ok": 2,
                        "chat_id": e2e.CHAT_ID, "stages": []}}))
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "available": True, "enabled": True, "runs": e2e.SUMMARY_RUNS,
            "counts": {}, "next_cursor": None}))
        return
    if url.endswith("/api/memory/nostalgia/log"):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(e2e.NOSTALGIA_ROWS))
        return
    if url.endswith("/api/memory/dream/log"):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(e2e.DREAM_ROWS))
        return
    if url.endswith("/api/factcheck/temporal/runs"):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "available": True, "enabled": True, "runs": e2e.TEMPORAL_ROWS}))
        return
    if url.endswith("/api/memory/lessons"):
        # W2c не проверяет уроки; пустой конверт не ломает «Память» и не
        # подменяет W2b-сценарии (они живут в ui_mod_acl_m4_catalog_e2e.py).
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "enabled": False, "state": "disabled", "count": 0, "lessons": []}))
        return
    if url.endswith("/api/memory/embeddings"):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "vector_memory": {"available": True, "state": "ready"},
            "provider": {"name": "openai", "ready": True},
            "rebuild": {"running": False}, "backlog": {"pending": 0},
            "generation": 3, "compat": {"ok": True}}))
        return
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(e2e._stub_for(url)))


PROBE = r"""
() => {
  const r = (el) => { const b = el.getBoundingClientRect();
    return {x: b.x, y: b.y, w: b.width, h: b.height, top: b.top}; };
  const cards = Array.from(document.querySelectorAll(
    '.module-catalog [data-mod]'));
  const byTop = {};
  cards.forEach((c) => { const t = Math.round(r(c).top);
    byTop[t] = (byTop[t] || 0) + 1; });
  const parents = Array.from(document.querySelectorAll(
    '.module-catalog [data-mod]')).map((card) => {
      const a = card.querySelector('[data-module-parent]');
      if (!a) return null;
      return {
        id: card.getAttribute('data-mod'),
        route: a.getAttribute('data-module-parent-route'),
        href: a.getAttribute('href'),
        text: (a.textContent || '').trim()
      };
    }).filter(Boolean);
  const surf = document.querySelector('main[data-workspace-surface]');
  const sidebar = document.querySelector('.app-sidebar');
  const split = document.querySelector('[data-workspace-split]');
  const splitMain = document.querySelector('[data-workspace-split-main]');
  const splitSide = document.querySelector('[data-workspace-split-side]');
  const heads = document.querySelectorAll('[data-workspace-head]');
  const titles = document.querySelectorAll('main h1');
  const head = document.querySelector('[data-workspace-head]');
  const rowsOverview = document.querySelectorAll(
    '[data-overview-history-row]');
  const ownerLinks = Array.from(document.querySelectorAll(
    '[data-owner-link]')).map((a) => ({
      id: a.getAttribute('data-owner-link'),
      route: a.getAttribute('href'),
      text: (a.textContent || '').trim()
    }));
  const tabs = Array.from(document.querySelectorAll(
    '[data-workspace-tabs] [data-workspace-tab]')).map((b) => ({
      id: b.getAttribute('data-workspace-tab'),
      current: b.getAttribute('aria-current'),
      h: r(b).h
    }));
  const cfgKeys = Array.from(document.querySelectorAll('[data-cfg-key]'))
    .map((el) => el.getAttribute('data-cfg-key'));
  const adv = Array.from(document.querySelectorAll(
    'main details.advanced summary, main details summary'))
    .map((el) => (el.textContent || '').trim())
    .filter((t) => t.indexOf('Расширенные') === 0);
  const targets = Array.from(document.querySelectorAll(
    'main.workspace-surface button, main.workspace-surface [role="tab"], '
    + 'main.workspace-surface .btn-ghost, main.workspace-surface .btn-accent, '
    + 'main.workspace-surface .module-tristate-btn, main.workspace-surface select, '
    + 'main.workspace-surface summary, main.workspace-surface .module-toggle, '
    + 'main.workspace-surface .ctl-toggle, main.workspace-surface '
    + 'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'))
    .filter((el) => { const b = el.getBoundingClientRect();
      return b.width > 0 && b.height > 0; })
    .map((el) => ({tag: el.tagName.toLowerCase(),
                   text: (el.textContent || '').trim().slice(0, 24),
                   w: r(el).w, h: r(el).h}));
  const smallTargets = targets.filter((x) => x.h < 43.5);
  return {
    vw: innerWidth,
    hash: location.hash,
    scrollWidth: document.documentElement.scrollWidth,
    cards: cards.length,
    firstRowColumns: cards.length
      ? byTop[Math.round(r(cards[0]).top)] : 0,
    cardHeights: cards.map((c) => Math.round(r(c).h)),
    parents: parents,
    surfaceClass: surf ? surf.getAttribute('data-workspace-surface') : null,
    surfaceW: surf ? Math.round(r(surf).w) : null,
    headW: head ? Math.round(r(head).w) : null,
    sidebarW: sidebar ? Math.round(r(sidebar).w) : null,
    split: split ? {children: split.children.length,
                    mainW: splitMain ? Math.round(r(splitMain).w) : null,
                    sideW: splitSide ? Math.round(r(splitSide).w) : null,
                    mainTop: splitMain ? Math.round(r(splitMain).top) : null,
                    sideTop: splitSide ? Math.round(r(splitSide).top) : null,
                    w: Math.round(r(split).w)} : null,
    heads: heads.length,
    titles: titles.length,
    overviewRows: rowsOverview.length,
    ownerLinks: ownerLinks,
    tabs: tabs,
    cfgKeys: cfgKeys,
    advanced: adv,
    touch: {count: targets.length,
            small: smallTargets.slice(0, 12), smallCount: smallTargets.length},
    mainScrollWidth: (() => { const m = document.querySelector('main');
      return m ? m.scrollWidth : null; })(),
    mainClientWidth: (() => { const m = document.querySelector('main');
      return m ? m.clientWidth : null; })()
  };
}
"""

failures = []
report = {"viewports": {}, "flows": {}, "shots": SHOTS}


def check(cond, msg, bucket):
    if not cond:
        failures.append(msg)
        bucket.append(msg)
    return cond


def _goto(page, base, hash_route):
    page.goto(base + hash_route, wait_until="domcontentloaded")
    page.wait_for_timeout(650)


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    e2e.PORT = PORT
    httpd = e2e._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for (w, h) in VIEWPORTS:
                vp_fail = []
                ctx = browser.new_context(viewport={"width": w, "height": h})
                ctx.add_init_script(e2e.TMA_STUB)
                ctx.route("**/api/**", _route)
                page = ctx.new_page()
                errs = []
                page.on("pageerror", lambda e, b=errs: b.append(str(e)[:300]))
                vp = {}
                report["viewports"]["%dx%d" % (w, h)] = vp

                # ── каталог ─────────────────────────────────────────────
                _goto(page, base, "#/modules")
                page.wait_for_selector(".module-catalog [data-mod]",
                                       timeout=9000)
                cat = page.evaluate(PROBE)
                vp["catalog"] = cat
                check(cat["cards"] == 21,
                      "%d: каталог 21 карточка (%s)" % (w, cat["cards"]),
                      vp_fail)
                check(cat["firstRowColumns"] == EXPECT_COLUMNS[w],
                      "%d: колонки %d (%s)" % (w, EXPECT_COLUMNS[w],
                                               cat["firstRowColumns"]),
                      vp_fail)
                check(all(132 <= x <= 164 for x in cat["cardHeights"]),
                      "%d: высота карточек 132–164 (%s)"
                      % (w, sorted(set(cat["cardHeights"]))[:8]), vp_fail)
                ids = sorted([x["id"] for x in cat["parents"]])
                check(ids == ["mod_character", "mod_experience", "mod_random",
                              "mod_stories"],
                      "%d: parent-чипы только у 4 подмодулей (%s)"
                      % (w, ids), vp_fail)
                for pchip in cat["parents"]:
                    exp = "#/memory/rag" if pchip["id"] != "mod_character" \
                        else "#/permsoc"
                    check(pchip["route"] == exp and pchip["href"] == exp,
                          "%d: %s chip → %s" % (w, pchip["id"], exp), vp_fail)
                check(cat["scrollWidth"] <= w + 1,
                      "%d: нет горизонтального overflow каталога"
                      % w, vp_fail)
                if w >= 1200:
                    check(cat["sidebarW"] is not None
                          and 190 <= cat["sidebarW"] <= 220,
                          "%d: sidebar 190–220 (%s)" % (w, cat["sidebarW"]),
                          vp_fail)
                page.screenshot(path=os.path.join(SHOTS, "catalog-%d.png" % w))
                # Чип карточки — ссылка владельца, а НЕ открытие модуля.
                page.click('[data-mod="mod_experience"] [data-module-parent]')
                page.wait_for_timeout(450)
                check(page.evaluate("location.hash") == "#/memory/rag",
                      "%d: чип карточки открывает родительскую «Память»" % w,
                      vp_fail)

                # ── NAV-01: child chip → parent surface ────────────────
                _goto(page, base, "#/modules/experience")
                page.wait_for_selector("[data-workspace-parent]", timeout=9000)
                child = page.evaluate(PROBE)
                vp["experience"] = child
                href = page.get_attribute("[data-workspace-parent]", "href")
                check(href == "#/memory/rag",
                      "%d: чип «Опыта» ведёт на #/memory/rag (%s)"
                      % (w, href), vp_fail)
                page.screenshot(path=os.path.join(
                    SHOTS, "experience-parent-%d.png" % w))
                page.click("[data-workspace-parent]")
                page.wait_for_timeout(450)
                check(page.evaluate("location.hash") == "#/memory/rag",
                      "%d: клик по чипу открывает «Память»" % w, vp_fail)
                page.wait_for_selector("[data-owner-links]", timeout=9000)
                mem = page.evaluate(PROBE)
                vp["memory_parent"] = mem
                owner_ids = [x["id"] for x in mem["ownerLinks"]]
                check(owner_ids == ["mod_stories", "mod_experience",
                                    "mod_random"],
                      "%d: «Память» ← ссылки трёх частей (%s)"
                      % (w, owner_ids), vp_fail)
                for link in mem["ownerLinks"]:
                    check(link["route"].startswith("#/modules/"),
                          "%d: deep link %s" % (w, link["route"]), vp_fail)
                check(not any(k.startswith("flags.stories")
                              or k.startswith("memory.experience")
                              for k in mem["cfgKeys"]),
                      "%d: поля подмодулей не дублируются на «Памяти»"
                      % w, vp_fail)
                page.screenshot(path=os.path.join(
                    SHOTS, "memory-parent-%d.png" % w))

                _goto(page, base, "#/permsoc")
                page.wait_for_selector("[data-owner-links]", timeout=9000)
                per = page.evaluate(PROBE)
                vp["permsoc_parent"] = per
                check(("mod_character" in [x["id"] for x in per["ownerLinks"]]),
                      "%d: PERMsoc ссылается на «Характер»" % w, vp_fail)
                check(not any("character" in (k or "")
                              or k.startswith("flags.self_model")
                              for k in per["cfgKeys"]),
                      "%d: поля «Характера» не дублируются на PERMsoc"
                      % w, vp_fail)
                page.screenshot(path=os.path.join(
                    SHOTS, "permsoc-parent-%d.png" % w))

                # ── LAY-01: сложный / малый / инфраструктура ───────────
                _goto(page, base, "#/modules/summary/overview")
                page.wait_for_selector("[data-workspace-head]", timeout=9000)
                page.wait_for_timeout(500)
                comp = page.evaluate(PROBE)
                vp["summary"] = comp
                check(comp["surfaceClass"] == "complex",
                      "%d: «Сводки» — complex" % w, vp_fail)
                check(comp["heads"] == 1 and comp["titles"] == 1,
                      "%d: одна шапка/один H1 (%s/%s)"
                      % (w, comp["heads"], comp["titles"]), vp_fail)
                check(3 <= comp["overviewRows"] <= 5,
                      "%d: «Обзор» 3–5 событий (%s)"
                      % (w, comp["overviewRows"]), vp_fail)
                check("overview" in [x["id"] for x in comp["tabs"]],
                      "%d: табы по классам на месте" % w, vp_fail)
                page.screenshot(path=os.path.join(SHOTS, "summary-%d.png" % w))

                _goto(page, base, "#/modules/nostalgia/settings")
                page.wait_for_selector("[data-workspace-head]", timeout=9000)
                small = page.evaluate(PROBE)
                vp["nostalgia"] = small
                check(small["surfaceClass"] == "small",
                      "%d: «Ностальгия» — small" % w, vp_fail)
                if w >= 1200:
                    check(900 <= (small["headW"] or 0) <= 1000,
                          "%d: простая вкладка 900–1000 (%s)"
                          % (w, small["headW"]), vp_fail)
                if w >= 1600:
                    check((small["headW"] or 0) <= 1000,
                          "%d: малая колонка ≤1000 (%s)"
                          % (w, small["headW"]), vp_fail)
                check(small["split"] is None,
                      "%d: один блок не растягивается в 8/4" % w, vp_fail)
                page.screenshot(path=os.path.join(
                    SHOTS, "nostalgia-%d.png" % w))

                _goto(page, base, "#/modules/direct/models")
                page.wait_for_selector("[data-workspace-split]", timeout=9000)
                split = page.evaluate(PROBE)
                vp["direct_models"] = split
                check(split["split"] and split["split"]["children"] == 2,
                      "%d: 8/12+4/12 только два sibling-блока (%s)"
                      % (w, split["split"]), vp_fail)
                if split["split"]:
                    mw = split["split"]["mainW"] or 0
                    sw = split["split"]["sideW"] or 0
                    if w >= 1024:
                        check(sw > 0 and mw / sw >= 1.7 and mw / sw <= 2.3,
                              "%d: реальные пропорции 8/4 (%.0f/%.0f)"
                              % (w, mw, sw), vp_fail)
                    else:
                        check(mw == sw or abs(mw - sw) <= 2,
                              "%d: 8/4 схлопнут в одну колонку (%.0f/%.0f)"
                              % (w, mw, sw), vp_fail)
                        check(split["split"]["sideTop"]
                              > split["split"]["mainTop"],
                              "%d: блоки стоят друг под другом" % w,
                              vp_fail)
                if w >= 1200:
                    check((split["headW"] or 0) <= 1440,
                          "%d: рабочая область ≤1440 (%s)"
                          % (w, split["headW"]), vp_fail)
                if w >= 1600:
                    check(1360 <= (split["headW"] or 0) <= 1440,
                          "%d: рабочая область 1360–1440 (%s)"
                          % (w, split["headW"]), vp_fail)
                page.screenshot(path=os.path.join(
                    SHOTS, "direct-models-%d.png" % w))

                _goto(page, base, "#/modules/embeddings/overview")
                page.wait_for_selector("[data-workspace-head]", timeout=9000)
                infra = page.evaluate(PROBE)
                vp["embeddings"] = infra
                check(infra["surfaceClass"] == "infrastructure",
                      "%d: «Векторная память» — infrastructure" % w, vp_fail)
                page.screenshot(path=os.path.join(
                    SHOTS, "embeddings-%d.png" % w))

                # ── WF-01: advanced-подпись и deep link на подраздел ───
                _goto(page, base, "#/modules/summary/settings")
                page.wait_for_selector("[data-workspace-head]", timeout=9000)
                page.wait_for_timeout(500)
                adv = page.evaluate(PROBE)
                vp["summary_settings"] = adv
                check(any(t.startswith("Расширенные системные")
                          for t in adv["advanced"]),
                      "%d: единая подпись advanced (%s)"
                      % (w, adv["advanced"][:3]), vp_fail)
                if w >= 1200:
                    check((adv["headW"] or 0) <= 1440,
                          "%d: complex ≤1440 (%s)"
                          % (w, adv["headW"]), vp_fail)
                if w >= 1600:
                    check(1360 <= (adv["headW"] or 0) <= 1440,
                          "%d: complex 1360–1440 (%s)"
                          % (w, adv["headW"]), vp_fail)

                # ── touch targets на tablet/mobile ─────────────────────
                if w <= 1199:
                    check(small["touch"]["smallCount"] == 0,
                          "%d: touch-цели workspace ≥44 (%s)"
                          % (w, small["touch"]["small"]), vp_fail)
                    check(comp["touch"]["smallCount"] == 0,
                          "%d: touch-цели summary ≥44 (%s)"
                          % (w, comp["touch"]["small"]), vp_fail)

                # ── overflow на всех поверхностях ──────────────────────
                for name in ("summary", "nostalgia", "direct_models",
                             "embeddings", "memory_parent", "permsoc_parent"):
                    block = vp.get(name) or {}
                    check((block.get("scrollWidth") or 0) <= w + 1,
                          "%d: overflow на %s (%s)"
                          % (w, name, block.get("scrollWidth")), vp_fail)
                    check((block.get("mainScrollWidth") or 0)
                          <= (block.get("mainClientWidth") or 0) + 1,
                          "%d: внутренний overflow на %s" % (w, name),
                          vp_fail)

                check(not errs,
                      "%d: JS-ошибки страницы (%s)" % (w, errs[:2]), vp_fail)
                report["flows"]["%dx%d" % (w, h)] = vp_fail
                ctx.close()

            # ── deep link summary/overview → history + reload ──────────
            dctx = browser.new_context(viewport={"width": 1440, "height": 900})
            dctx.add_init_script(e2e.TMA_STUB)
            dctx.route("**/api/**", _route)
            dp = dctx.new_page()
            _goto(dp, base, "#/modules/summary/overview")
            dp.wait_for_selector("[data-overview-link]", timeout=9000)
            hrefs = dp.eval_on_selector_all(
                "[data-overview-link]",
                "els => els.map(e => ({id: e.getAttribute('data-overview-link'),"
                " href: e.getAttribute('href')}))")
            hist = [x for x in hrefs if x["id"] == "history"]
            report["flows"]["deep_link"] = {"links": hrefs, "history": hist}
            check(bool(hist) and hist[0]["href"] == "#/modules/summary/history",
                  "deep link: «История» — прямой href", failures)
            if hist:
                dp.click("[data-overview-link=history]")
                dp.wait_for_timeout(400)
                check(dp.evaluate("location.hash") == "#/modules/summary/history",
                      "deep link: клик открывает /summary/history", failures)
                dp.reload(wait_until="domcontentloaded")
                dp.wait_for_selector("[data-workspace-head]", timeout=9000)
                dp.wait_for_timeout(600)
                cur = dp.evaluate(
                    "() => { const el = document.querySelector("
                    "'[data-workspace-tabs] [aria-current=page]');"
                    "return el ? el.getAttribute('data-workspace-tab') : null; }")
                check(cur == "history",
                      "deep link: reload сохраняет «Историю» (%s)" % cur,
                      failures)
            dp.screenshot(path=os.path.join(SHOTS, "deep-link-1440.png"))
            dctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    report["failures"] = failures
    out = os.environ.get("MOD_ACL_W2C_REPORT")
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("->", out)
    print(json.dumps(report, ensure_ascii=False)[:2000])
    print("viewports=%d failures=%d" % (len(VIEWPORTS), len(failures)))
    for f in failures:
        print("FAIL:", f)
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
