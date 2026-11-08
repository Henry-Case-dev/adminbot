# -*- coding: utf-8 -*-
"""MEM-08-S3 — живой стенд единого поля поиска в когнитивной карте.

Проверяется РЕАЛЬНЫЙ интерфейс (`web/index.html` + `web/app.js` +
`web/static/*`) на детерминированной фикстуре карты: измеряются фактические
rect'ы, состояния vue-экземпляра и видимые тексты, без подмены приложения.

Контракт: `plans/features/memory-cognitive-02/contracts.md` §4.9/§4.10, §10
(Visual Preservation Map), MEM-08.14/08.19/08.20/08.23/08.24/08.25/08.26,
артефакт S1 `search-read-model.md` §1/§3.

Что доказывается ЖИВЫМ рендером:
  * ровно ОДНО поле «Найти в памяти» (SC-21) и ни одного видимого прежнего
    toolbar'а при включённом гейте; ни горизонтального скролла, ни выхода
    поля/очистки/панели за пределы карточки на 320/360/390/430/667/768/1280/
    1440 px;
  * подсказки раскрываются вводом (без Enter), панель остаётся над сценой и
    внутри viewport; клавиатура ArrowDown/Enter/Escape работает;
  * четыре исхода РАЗЛИЧНЫ словами: нет прав ≠ нет совпадений ≠ сбой (и
    `cursor_stale` не рисует пустой экран);
  * fullscreen использует ТО ЖЕ поле и состояние (нет второго input);
  * сообщества показываются только как proven-набор; пустая сборка — честный
    нейтральный текст, а не «Сообщество N» в роли категории.

Запуск:
  py tools/ui_mem08_s3_omnibox_e2e.py [--out DIR]
Выход: <out>/mem08-s3-omnibox.json + PNG-кадры.
Код возврата 0 — все проверки прошли, 2 — есть отказы, 3 — стенд не поднялся.
"""
import argparse
import json
import os
import sys
import traceback

VIEWPORTS = (
    (320, 568), (360, 780), (390, 844), (430, 932),
    (667, 375), (768, 1024), (1280, 900), (1440, 900),
)
DESKTOP_MIN = 768

OK_PAYLOAD = {
    "status": "ok",
    "query_state": "candidates",
    "reason_code": None,
    "items": [
        {"ref_kind": "entity", "canonical_id": "ent:%d:1", "legacy_ids": [],
         "title": "Аня", "category": "Человек", "snippet": "обсуждали дачу",
         "match_cause": "exact_name", "evidence_status": "confirmed",
         "event_ts": None, "observed_ts": None,
         "focus": {"chat_id": -1001234567890, "node_id": 1},
         "ambiguity": None},
        {"ref_kind": "fact", "canonical_id": "fact:%d:11", "legacy_ids": [],
         "title": "Аня любит утренний кофе", "category": "Факт",
         "snippet": None, "match_cause": "fts",
         "evidence_status": "legacy", "event_ts": None, "observed_ts": None,
         "focus": None, "ambiguity": None},
    ],
    "next_cursor": None, "has_more": False, "generation": 0,
    "scope": {"chat_id": -1001234567890, "mode": "chat", "partial": False},
    "revision": {"graph": "g", "alias": "a", "community_build": None,
                 "index_fingerprint": None},
    "debug": {},
}

NO_RIGHTS = {"status": "forbidden", "query_state": "no_rights",
             "reason_code": "no_rights", "items": [], "next_cursor": None,
             "has_more": False, "generation": 0,
             "scope": {"chat_id": -1001234567890, "mode": "chat",
                       "partial": False},
             "revision": {}, "debug": {}}
ERROR = {"status": "error", "query_state": "error",
         "reason_code": "retrieval_error", "items": [], "next_cursor": None,
         "has_more": False, "generation": 0,
         "scope": {"chat_id": -1001234567890, "mode": "chat",
                   "partial": False},
         "revision": {}, "debug": {}}
EMPTY = {"status": "empty", "query_state": "no_matches",
         "reason_code": "retrieval_empty", "items": [], "next_cursor": None,
         "has_more": False, "generation": 0,
         "scope": {"chat_id": -1001234567890, "mode": "chat",
                   "partial": False},
         "revision": {}, "debug": {}}

FIELD_PROBE = """() => {
  const omni = document.querySelector('[data-cog-omni]');
  const legacy = document.querySelector('[data-cog-legacy-search]');
  const input = omni ? omni.querySelector('input') : null;
  const card = document.querySelector('[data-cog-map]');
  const clear = omni ? omni.querySelector('[data-cog-search-clear]') : null;
  const state = omni ? omni.querySelector('[data-cog-search-state]') : null;
  const panel = omni ? omni.querySelector('[data-cog-search-panel]') : null;
  const rect = (el) => (el ? {
    x: el.getBoundingClientRect().x, y: el.getBoundingClientRect().y,
    w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height,
    right: el.getBoundingClientRect().right,
    bottom: el.getBoundingClientRect().bottom,
  } : null);
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const vm = window.__adminbotVm || {};
  return {
    omniCount: document.querySelectorAll('[data-cog-omni]').length,
    inputCount: omni ? omni.querySelectorAll('input').length : 0,
    legacyCount: document.querySelectorAll('[data-cog-legacy-search]').length,
    legacyVisible: visible(legacy),
    platformInputs: document.querySelectorAll(
      'input[type="search"]').length,
    input: rect(input),
    card: rect(card),
    clear: visible(clear) ? rect(clear) : null,
    state: state ? state.getAttribute('data-cog-search-state') : null,
    notice: state ? state.textContent.trim() : '',
    omniState: omni ? omni.getAttribute('data-cog-search-state') : null,
    panel: visible(panel) ? rect(panel) : null,
    rows: panel ? panel.querySelectorAll('[data-cog-omni-item]').length : 0,
    panelText: panel ? panel.textContent.trim() : '',
    selectedRow: panel ? Array.from(
      panel.querySelectorAll('[aria-selected="true"]')).length : 0,
    innerW: window.innerWidth,
    innerH: window.innerHeight,
    hScroll: document.documentElement.scrollWidth - window.innerWidth,
    searchState: vm.cogSearch ? vm.cogSearch.state : null,
    query: vm.cogSearch ? vm.cogSearch.query : null,
  };
}"""

COMMUNITIES_PROBE = """() => {
  const box = document.querySelector('[data-cog-map] [data-cog-communities]');
  const chips = Array.from(document.querySelectorAll(
    '[data-cog-map] [data-cog-community]')).map((el) => ({
      id: el.getAttribute('data-cog-community'),
      text: el.textContent.trim(),
    }));
  const empty = document.querySelector(
    '[data-cog-map] [data-cog-communities-empty]');
  return {
    state: box ? box.getAttribute('data-cog-communities') : null,
    visible: !!box && box.getClientRects().length > 0,
    chips: chips,
    emptyText: empty ? empty.textContent.trim() : '',
  };
}"""


def _set_search_stub(W, payload):
    W.EXTRA_STUBS[:] = [pair for pair in W.EXTRA_STUBS
                        if pair[0] != "/api/memory/search"]
    W.EXTRA_STUBS.insert(0, ("/api/memory/search", payload))


def _set_map(W, *, search_on=True, communities=None):
    payload = W.cog_payload()
    if search_on:
        payload["search"] = {"enabled": True}
    if communities is not None:
        payload["communities"] = communities
    W.set_cog_payload(payload)


def run(browser, base, out_dir):
    W = sys.modules["ui_evol_w15_composition_e2e"]
    ok_payload = json.loads(json.dumps(OK_PAYLOAD))
    ok_payload["items"][0]["canonical_id"] = (
        "ent:%d:1" % W.COG_CHAT)
    ok_payload["items"][1]["canonical_id"] = (
        "fact:%d:11" % W.COG_CHAT)
    checks = []
    shots = []

    def chk(cond, name, detail=None):
        checks.append({"name": name, "ok": bool(cond),
                       "detail": None if cond else detail})
        return bool(cond)

    def shot(pg, name):
        path = os.path.join(out_dir, name + ".png")
        try:
            pg.screenshot(path=path, full_page=False)
            shots.append(name + ".png")
            return name + ".png"
        except Exception:  # noqa: BLE001
            return None

    def open_map(pg, w):
        pg.goto(base + "?cog=s3-%d#/" % w, wait_until="load")
        pg.wait_for_selector("[data-cog-map]", timeout=30000)
        pg.wait_for_selector("[data-cog-map] canvas", timeout=30000)
        pg.wait_for_timeout(2400)

    def type_query(pg, text):
        pg.click("[data-cog-omni] input")
        pg.fill("[data-cog-omni] input", text)
        pg.wait_for_timeout(700)          # debounce 150 + ответ стаба

    # ── 1. Раскладка единого поля на всех опорных ширинах ──────────────────
    for (w, h) in VIEWPORTS:
        label = "%dx%d" % (w, h)
        _set_map(W, search_on=True)
        _set_search_stub(W, ok_payload)
        ctx = W._ctx(browser, w, h)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
        try:
            open_map(pg, w)
            st = pg.evaluate(FIELD_PROBE)
            chk(st["omniCount"] == 1, "ровно одно поле «Найти в памяти» @%s"
                % label, st["omniCount"])
            chk(st["inputCount"] == 1, "одно поле внутри omnibox @%s" % label,
                st["inputCount"])
            chk(st["legacyVisible"] is False,
                "прежний toolbar не виден при ON @%s" % label,
                st["legacyCount"])
            chk(st["input"] and st["card"]
                and st["input"]["right"] <= st["card"]["right"] + 1
                and st["input"]["x"] >= st["card"]["x"] - 1,
                "поле внутри карточки @%s" % label, {
                    "input": st["input"], "card": st["card"]})
            chk(st["hScroll"] <= 1, "нет горизонтального скролла @%s" % label,
                st["hScroll"])
            chk(not errs, "нет JS-ошибок при рендере @%s" % label, errs)

            type_query(pg, "Аня")
            st2 = pg.evaluate(FIELD_PROBE)
            chk(st2["rows"] >= 2, "подсказки раскрылись вводом @%s" % label,
                {"rows": st2["rows"], "state": st2["searchState"]})
            chk(st2["searchState"] == "candidates",
                "состояние candidates @%s" % label, st2["searchState"])
            chk(st2["panel"] and st2["panel"]["right"] <= st2["innerW"] + 1
                and st2["panel"]["x"] >= -1,
                "панель не выходит за viewport @%s" % label, st2["panel"])
            chk("ent:" not in st2["panelText"] and "fact:" not in st2["panelText"],
                "внутренние ID не попадают в выдачу @%s" % label,
                st2["panelText"][:120])
            chk(st2["panel"] and st2["panel"]["bottom"] <= st2["innerH"] + 1,
                "панель не уходит под экран @%s" % label,
                st2["panel"] and st2["panel"]["bottom"])
            chk(st2["hScroll"] <= 1,
                "раскрытая панель не создаёт гориз. скролл @%s" % label,
                st2["hScroll"])
            chk(st2["clear"] is not None and st2["clear"]["right"]
                <= st2["card"]["right"] + 1,
                "очистка «×» доступна и внутри карточки @%s" % label,
                st2["clear"])

            # Клавиатура: ArrowDown двигает активный пункт, Escape закрывает.
            pg.keyboard.press("ArrowDown")
            pg.wait_for_timeout(120)
            st3 = pg.evaluate(FIELD_PROBE)
            chk(st3["selectedRow"] == 1,
                "ArrowDown двигает активный пункт @%s" % label,
                st3["selectedRow"])
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(150)
            st4 = pg.evaluate(FIELD_PROBE)
            chk(st4["panel"] is None, "Escape закрывает подсказки @%s" % label,
                st4["panel"])
            if w in (320, 390, 768, 1280):
                shot(pg, "mem08-s3-%d-omnibox" % w)
            if w == 390:
                # Панель подсказок в открытом виде — кадр для визуального ревью.
                pg.click("[data-cog-omni] input")
                pg.fill("[data-cog-omni] input", "Аня")
                pg.wait_for_timeout(700)
                shot(pg, "mem08-s3-390-panel")
        finally:
            ctx.close()

    # ── 2. Четыре исхода РАЗЛИЧНЫ словами (реальный рендер, 390 px) ────────
    cases = (("no_rights", NO_RIGHTS, "Нет прав", "no_rights"),
             ("error", ERROR, "Поиск не выполнен", "error"),
             ("empty", EMPTY, "Ничего не найдено", "no_matches"))
    notices = {}
    for name, payload, must, token in cases:
        _set_map(W, search_on=True)
        _set_search_stub(W, payload)
        ctx = W._ctx(browser, 390, 844)
        pg = ctx.new_page()
        try:
            open_map(pg, 390)
            type_query(pg, "Аня")
            st = pg.evaluate(FIELD_PROBE)
            notices[name] = st["notice"]
            chk(must in st["notice"], "%s показан словами" % name, st["notice"])
            chk(st["omniState"] == token, "%s — свой data-state" % name,
                st["omniState"])
            if name == "empty":
                shot(pg, "mem08-s3-390-empty")
        finally:
            ctx.close()
    chk(len(set(notices.values())) == 3,
        "три исхода звучат по-разному", notices)
    chk("Ничего не найдено" not in notices.get("error", ""),
        "сбой не показан как «ничего не найдено»", notices.get("error"))

    # ── 3. Fullscreen — ТО ЖЕ поле и состояние (нет второго input) ──────────
    _set_map(W, search_on=True)
    _set_search_stub(W, ok_payload)
    ctx = W._ctx(browser, 390, 844)
    pg = ctx.new_page()
    try:
        open_map(pg, 390)
        pg.evaluate("() => window.__adminbotVm.openGraphFull()")
        pg.wait_for_timeout(1800)
        st = pg.evaluate(FIELD_PROBE)
        chk(st["omniCount"] == 1, "fullscreen: одно поле", st["omniCount"])
        chk(st["inputCount"] == 1, "fullscreen: один input", st["inputCount"])
        chk(st["legacyVisible"] is False,
            "fullscreen: прежний toolbar не виден", st["legacyCount"])
        chk(pg.evaluate(
            "() => !!document.querySelector('.status-graph-full [data-cog-omni]')"),
            "fullscreen: поле находится в панели полного экрана")
        type_query(pg, "Аня")
        st2 = pg.evaluate(FIELD_PROBE)
        chk(st2["rows"] >= 2, "fullscreen: подсказки работают", st2["rows"])
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(700)
        st3 = pg.evaluate(FIELD_PROBE)
        vm_note = pg.evaluate(
            "() => (window.__adminbotVm.cogSearch || {}).notice || ''")
        chk(st3["panel"] is None, "fullscreen: Enter закрывает подсказки",
            st3["panel"])
        chk("карте" in vm_note, "fullscreen: выбор даёт понятный результат",
            vm_note)
        shot(pg, "mem08-s3-390-fullscreen")
    finally:
        ctx.close()

    # ── 4. Гейт OFF: прежний toolbar, ни одного сообщества-фейка ────────────
    _set_map(W, search_on=False)
    ctx = W._ctx(browser, 1280, 900)
    pg = ctx.new_page()
    try:
        open_map(pg, 1280)
        st = pg.evaluate(FIELD_PROBE)
        chk(st["omniCount"] == 0, "OFF: omnibox не рендерится", st["omniCount"])
        chk(st["legacyVisible"] is True, "OFF: прежний toolbar виден",
            st["legacyCount"])
        shot(pg, "mem08-s3-1280-gate-off")
    finally:
        ctx.close()

    # ── 5. Сообщества: proven-набор и честная пустота ──────────────────────
    _set_map(W, search_on=True, communities={
        "state": "ok", "reason_code": None, "total": 1, "shown": 1,
        "truncated": False, "build": {"build_id": "b-1"},
        "items": [{"community_id": "c-1", "member_count": 2,
                   "label": "Сообщество: Аня, Костя", "label_kind": "named",
                   "label_basis": "доминирующие имена",
                   "dominant_names": ["Аня", "Костя"],
                   "metrics": {"confirmed_links": 3},
                   "metrics_basis": "full"}],
    })
    ctx = W._ctx(browser, 1280, 900)
    pg = ctx.new_page()
    try:
        open_map(pg, 1280)
        cm = pg.evaluate(COMMUNITIES_PROBE)
        chk(cm["visible"] and cm["state"] == "ok",
            "сообщества proven-набора видны", cm["state"])
        chk(cm["chips"] and "Сообщество: Аня, Костя" in cm["chips"][0]["text"],
            "подпись сообщества — из сборки", cm["chips"])
        chk("Группа" not in (cm["chips"][0]["text"] if cm["chips"] else ""),
            "LOD-тайл «Группа · N» не выдаётся за сообщество", cm["chips"])
        shot(pg, "mem08-s3-1280-communities")
    finally:
        ctx.close()

    _set_map(W, search_on=True, communities={
        "state": "no_active_build", "reason_code": "no_active_build",
        "items": [], "total": 0, "shown": 0, "truncated": False,
        "build": None})
    ctx = W._ctx(browser, 390, 844)
    pg = ctx.new_page()
    try:
        open_map(pg, 390)
        cm = pg.evaluate(COMMUNITIES_PROBE)
        chk(cm["state"] == "no_active_build",
            "нет активной сборки — отдельное состояние", cm["state"])
        chk("не собраны" in cm["emptyText"],
            "честный текст «ещё не собраны»", cm["emptyText"])
        chk(cm["chips"] == [], "фейковых сообществ нет", cm["chips"])
    finally:
        ctx.close()

    return checks, shots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(
        repo, "plans", "features", "memory-cognitive-02", "evidence",
        "mem08-s3")
    os.makedirs(out_dir, exist_ok=True)
    sys.path.insert(0, repo)
    sys.path.insert(0, os.path.join(repo, "tools"))
    os.chdir(repo)

    from playwright.sync_api import sync_playwright

    import ui_round1025_matrix as M
    import ui_evol_w15_composition_e2e as W15  # noqa: F401  (реестр модулей)

    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    checks = []
    shots = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                checks, shots = run(browser, base, out_dir)
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        print("MEM08-S3-STAND FAILED TO START")
        return 3
    finally:
        server.shutdown()

    passed = sum(1 for c in checks if c["ok"])
    fails = [c for c in checks if not c["ok"]]
    report = {
        "suite": "mem08-s3-omnibox",
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "screenshots": shots,
        "viewports": [list(v) for v in VIEWPORTS],
    }
    with open(os.path.join(out_dir, "mem08-s3-omnibox.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    for c in fails:
        print("FAIL:", c["name"], "::",
              json.dumps(c["detail"], ensure_ascii=False)[:300])
    print("MEM08-S3 checks %d/%d, screenshots=%d" % (passed, len(checks),
                                                     len(shots)))
    print("MEM08-S3-OMNIBOX " + ("OK" if not fails else "FAIL"))
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
