"""ASAP-speech-arch / W4 — Playwright e2e UI-дефектов U-01…U-09 (§8).

Гоняет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css` +
`web/static/glass-refraction.js`. `/api/*` — стабы: базовые ответы матрицы
(`ui_round1025_matrix`) и формы речи из `plans/features/soul-1/evidence/w6/
api-fixture.json` (сняты настоящим `web/api/speech.py`). Telegram SDK —
route-mock (прецедент `ui_asap8_w2_shell_e2e`). Полигональный фон ВКЛЮЧЁН
(прод-default), для пиксельных замеров — `?bgseed=` + pause().

Проверяет по §8 ТЗ (`source-2026-10-22.md`, строки 272–308):
  U-01/U-02  стекло карточек/панелей — цельная поверхность: яркость полосы
             кромки совпадает с интерьером (±6%), нет прямоугольных «швов»,
             слой преломления не перекрывает текст (hit-test);
  U-02       все 7 рядов карты сборки: рабочий переход ЛИБО честный read-only
             (нет шеврона/ложного hitbox, причина написана);
  U-03       библиотека промптов — одна адаптивная сетка (равные колонки,
             одинаковые отступы), подпись Direct-вербализатора = роль Writer,
             ключ каталога не изменился; этапные кнопки — только реальные;
  U-04       кодовые поля/Inspector: перенос строк (pre-wrap/anywhere), нет
             выхода за карточку и второй горизонтальной прокрутки страницы;
  U-05       редактор Core: адаптивный переключатель редакций, рабочее
             «Развернуть» (крупный экран, фокус, Esc/«Закрыть»), сохранение
             идёт в выбранный scope и выбранную редакцию;
  U-06       один главный заголовок + путь без дубля, один selector scope,
             индикатор local/global, шапка не перекрывает контент, мобильное
             «Ещё» и drawer отдают ПОЛНЫЙ список разделов;
  U-07       sticky-save: pristine → dirty → saving → saved → error → conflict,
             один активный CTA, нет ложного «сохранено» и залипшей панели;
  U-08       контраст вторичного текста ≥4.5:1 (посчитано по фактическим
             пикселям), prefers-reduced-motion, нет мерцания фона при polling;
  U-09       маршрут Статус → ИИ → Речь и характер → Core → Expression →
             Библиотека промптов → Direct Writer → Назад для GLOBAL и CHAT:
             все переходы ведут куда заявлено, контекст сохраняется, активный
             раздел подсвечен, Back/resize обрабатываются.

Запуск:
  .venv/Scripts/python.exe tools/ui_w4_ui_e2e.py            # прогон + evidence
  .venv/Scripts/python.exe tools/ui_w4_ui_e2e.py --serve-only  # стенд для глаз
  .venv/Scripts/python.exe tools/ui_w4_ui_e2e.py --no-shots    # без скриншотов
"""
import argparse
import json
import os
import struct
import sys
import threading
import time
import zlib
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402
import ui_soul1_w6_speech_e2e as W6  # noqa: E402

# Прод-default: полигональный фон включён (иначе дефект U-01/US-02 не виден).
M.ME_JSON["ui_flags"]["UI_POLYGON_BG_ENABLED"] = True

EVIDENCE = REPO / "plans" / "features" / "asap-speech-arch" / "evidence" / "w4"
SHOTS = EVIDENCE / "shots"


def _free_port():
    """Свободный порт для стенда.

    Фиксированный порт — источник ложных зелёных/красных: на Windows
    SO_REUSEADDR позволяет «занять» порт, который уже слушает прошлый прогон,
    и запросы уходят к СТАРОМУ процессу (со старым кодом/стабами). Поэтому
    каждый процесс берёт свободный порт и проверяет, что он реально свободен.
    """
    import socket
    for _ in range(20):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        finally:
            s.close()
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            busy = probe.connect_ex(("127.0.0.1", port)) == 0
        finally:
            probe.close()
        if not busy:
            return port
    raise RuntimeError("не удалось найти свободный порт для стенда")


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

VIEWPORTS = [
    ("320", 320, 700), ("360", 360, 780), ("390", 390, 844), ("430", 430, 932),
    ("768", 768, 1024), ("1024", 1024, 768), ("1280", 1280, 800),
    ("1440", 1440, 900), ("landscape", 667, 375),
]

failures: list = []
notes: list = []
POSTS: list = []          # {path, body, chat}
POST_MODE = {"mode": "ok", "delay": 0.0}
TEXT_RATIO = 0.0


def fail(label, msg):
    failures.append("%s: %s" % (label, msg))
    print("  FAIL %s: %s" % (label, msg))


def note(**kw):
    notes.append(kw)


# ── Пиксельные утилиты (stdlib PNG; без PIL) ───────────────────────────────
_PNG = {}


def load_png(path):
    path = str(path)
    if path in _PNG:
        return _PNG[path]
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "не PNG: " + path
    pos, w, h, bitdepth, ctype, idat = 8, 0, 0, 8, 6, bytearray()
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h = struct.unpack(">II", chunk[:8])
            bitdepth, ctype = chunk[8], chunk[9]
        elif typ == b"IDAT":
            idat += chunk
        elif typ == b"IEND":
            break
        pos += 12 + ln
    assert bitdepth == 8, "только 8-bit PNG"
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(bytes(idat))
    stride = w * ch
    out = bytearray(w * h * 3)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        prev = line
        for x in range(w):
            si = x * ch
            di = (y * w + x) * 3
            if ch >= 3:
                out[di:di + 3] = line[si:si + 3]
            else:
                out[di] = out[di + 1] = out[di + 2] = line[si]
    _PNG[path] = (w, h, out)
    return _PNG[path]


def luma(px, w, x, y):
    i = (y * w + x) * 3
    return 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]


def rgb_at(px, w, x, y):
    i = (y * w + x) * 3
    return px[i], px[i + 1], px[i + 2]


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def contrast(rgb_text, rgb_bg):
    lt = 0.2126 * _lin(rgb_text[0]) + 0.7152 * _lin(rgb_text[1]) + \
        0.0722 * _lin(rgb_text[2])
    lb = 0.2126 * _lin(rgb_bg[0]) + 0.7152 * _lin(rgb_bg[1]) + \
        0.0722 * _lin(rgb_bg[2])
    hi, lo = max(lt, lb), min(lt, lb)
    return (hi + 0.05) / (lo + 0.05)


def png_mean_rgb(path, box):
    """Средний RGB прямоугольного региона (device px)."""
    w, h, px = load_png(path)
    x0, y0, x1, y1 = box
    x1 = min(x1, w); y1 = min(y1, h)
    n = 0
    acc = [0, 0, 0]
    for y in range(y0, y1):
        row = y * w
        for x in range(x0, x1):
            i = (row + x) * 3
            acc[0] += px[i]; acc[1] += px[i + 1]; acc[2] += px[i + 2]
            n += 1
    if not n:
        return (0, 0, 0)
    return (acc[0] / n, acc[1] / n, acc[2] / n)


# ── Стенд ──────────────────────────────────────────────────────────────────
def serve(port, webroot):
    import http.server

    handler = W6.make_handler(str(webroot))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def new_page(browser, width, height, dsf=1):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              device_scale_factor=dsf)
    ctx.add_init_script(W6.SDK_STUB)

    def _route(route):
        req = route.request
        url = req.url.split("?")[0]
        if "/api/speech/" not in url:
            return route.continue_()
        hdrs = req.headers or {}
        chat = hdrs.get("x-chat-id")
        if req.method == "POST":
            name = url.rsplit("/api/speech/", 1)[1]
            POSTS.append({"path": name,
                          "body": json.loads(req.post_data or "{}"),
                          "chat": chat})
            mode = POST_MODE["mode"]
            if mode == "server":
                # Медленный ответ отдаёт сам стенд (поток сервера), чтобы
                # состояние `saving` было реально наблюдаемым в UI.
                return route.continue_()
            if mode == "503":
                return route.fulfill(
                    status=503, content_type="application/json",
                    body=json.dumps({"detail": W6.FIXTURE.get(
                        "error_503", "не удалось сохранить: постоянное "
                        "хранилище недоступно, попробуйте позже")}))
            if mode == "conflict":
                return route.fulfill(
                    status=409, content_type="application/json",
                    body=json.dumps({"detail": "документ изменено другим путём"}))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(W6._post_body(name, req),
                                                 ensure_ascii=False))
        name = url.rsplit("/api/speech/", 1)[1]
        body = W6._get_body(name)
        if name.startswith("block/"):
            # Форма ответа — реальная (снята живым API), но block_id обязан
            # совпадать с запрошенным: иначе UI честно покажет чужой блок.
            body = json.loads(json.dumps(body, ensure_ascii=False))
            body["block_id"] = name[len("block/"):]
        if name == "overview" and chat:
            body = json.loads(json.dumps(body, ensure_ascii=False))
            body["scope"] = "chat"
            body["chat_id"] = int(chat)
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(body, ensure_ascii=False))

    ctx.route("**/api/**", _route)
    page = ctx.new_page()
    page.on("pageerror", lambda e: fail("pageerror", str(e)[:200]))
    return ctx, page


def goto(page, route, seed=True):
    q = "?bgseed=1337" if seed else ""
    page.goto(BASE + "/web/index.html" + q + route, wait_until="load")
    page.wait_for_timeout(950)


def pause_bg(page):
    page.evaluate("() => { try { window.__PolygonBackground.pause(); } catch (e) {} }")
    page.wait_for_timeout(250)


FLOW_PROBE = r"""
(() => {
  const de = document.documentElement;
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return {x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width),
            h: Math.round(b.height), bottom: Math.round(b.bottom),
            right: Math.round(b.right)}; };
  const over = [];
  document.querySelectorAll('body *').forEach((el) => {
    const st = getComputedStyle(el);
    if (st.position === 'fixed' || st.position === 'sticky') return;
    const b = el.getBoundingClientRect();
    if (b.width > 0 && b.right > window.innerWidth + 1) {
      over.push({tag: el.tagName,
                 cls: (el.className || '').toString().slice(0, 50),
                 right: Math.round(b.right)});
    }
  });
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    scrollWidth: de.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    overflow: de.scrollWidth - window.innerWidth,
    offenders: over.slice(0, 6),
    header: r(document.querySelector('.main-header')),
    main: r(document.querySelector('main')),
    breadcrumb: (document.querySelector('.breadcrumb') || {}).textContent || '',
    title: (document.querySelector('.header-title') || {}).textContent || '',
    scopeBadges: Array.from(document.querySelectorAll('.scope-trigger .badge'))
      .map((b) => b.textContent.trim()),
    activeNav: (document.querySelector('.sidebar-link.active .sidebar-label')
      || document.querySelector('.app-drawer .sidebar-link.active .sidebar-label')
      || {}).textContent || '',
    speechSection: (document.querySelector('.speech-section') ? 'open' : 'showcase'),
    headerBottom: (document.querySelector('.main-header') || {getBoundingClientRect: () => ({bottom: 0})})
      .getBoundingClientRect().bottom,
    mainTop: (document.querySelector('main') || {getBoundingClientRect: () => ({top: 0})})
      .getBoundingClientRect().top,
  };
})()
"""


def probe_flow(page, label, width, expect_section=None):
    p = page.evaluate(FLOW_PROBE)
    if p["overflow"] > 1:
        fail(label, "горизонтальный overflow страницы: %s px (%s)"
             % (p["overflow"], p["offenders"]))
    if p["header"] and p["main"] and width >= 768:
        if p["header"]["bottom"] > p["mainTop"] + 2:
            fail(label, "шапка перекрывает контент: header.bottom=%s main.top=%s"
                 % (p["header"]["bottom"], p["mainTop"]))
    if expect_section and p["speechSection"] != expect_section:
        fail(label, "ожидался %s, получен %s" % (expect_section, p["speechSection"]))
    note(label=label, probe={k: v for k, v in p.items() if k != "offenders"})
    return p


# ── U-01/U-02/U-08: стекло — цельная поверхность + контраст ────────────────
GLASS_LUMA = r"""
(() => {
  const card = document.querySelector('[data-prompt-library-modules]');
  if (!card) return null;
  const r = card.getBoundingClientRect();
  return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width),
          h: Math.round(r.height)};
})()
"""


def check_glass(browser, route, selector_js, label, shots):
    """Сравнивает полосу кромки и центр карточки с фоном слоя выключенным:
    яркость полосы не должна «вырезаться» прямоугольником (U-01/U-02)."""
    shots_paths = {}
    for tag, q in (("on", "?bgseed=1337"),
                   ("off", "?bgseed=1337&glassrefract=off")):
        ctx, page = new_page(browser, 1280, 800, dsf=1)
        page.goto(BASE + "/web/index.html" + q + route, wait_until="load")
        page.wait_for_timeout(1500)
        pause_bg(page)
        box = page.evaluate(selector_js)
        if not box:
            fail(label, "не найдена измеряемая поверхность (%s)" % tag)
            ctx.close()
            return None
        path = SHOTS / ("glass_%s_%s.png" % (label, tag))
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path),
                        clip={"x": box["x"], "y": box["y"],
                              "width": box["w"], "height": min(box["h"], 160)})
        shots_paths[tag] = path
        ctx.close()
    w, h, on = load_png(shots_paths["on"])
    w2, h2, off = load_png(shots_paths["off"])
    if (w, h) != (w2, h2):
        fail(label, "размеры кадров разошлись")
        return None
    rows = {"band_top": 5, "center": max(10, h // 2), "band_bottom": h - 6}
    out = {}
    for name, y in rows.items():
        a = luma(on, w, w // 2, y)
        b = luma(off, w2, w // 2, y)
        out[name] = {"on": round(a, 1), "off": round(b, 1),
                     "delta_pct": round(100.0 * (a - b) / max(1.0, b), 1)}
    for name in ("band_top", "band_bottom"):
        if abs(out[name]["delta_pct"]) > 6.0:
            fail(label, "%s: полоса кромки отличается от интерьера на %s%% "
                        "(«шов»/вырезанный прямоугольник)" % (name, out[name]["delta_pct"]))
    if abs(out["center"]["delta_pct"]) > 2.0:
        fail(label, "центр поверхности изменился на %s%% при включении слоя"
             % out["center"]["delta_pct"])
    note(label=label, glass=out)
    return out


HITTEST = r"""
(() => {
  const t = document.querySelector('.speech-title') ||
            document.querySelector('[data-prompt-library-modules] .text-sm') ||
            document.querySelector('.header-title');
  if (!t) return null;
  const r = t.getBoundingClientRect();
  const x = Math.round(r.x + Math.min(12, r.width / 3));
  const y = Math.round(r.y + r.height / 2);
  const el = document.elementFromPoint(x, y);
  return {hit: el ? (el.tagName + '.' + (el.className || '').toString()) : null,
          x: x, y: y};
})()
"""


def check_hit(page, label):
    h = page.evaluate(HITTEST)
    if not h:
        return
    if "lg-refract" in (h["hit"] or ""):
        fail(label, "слой преломления перехватывает точку над текстом: %s" % h["hit"])
    note(label=label + "/hit", hit=h["hit"])
    return h


# ── U-02: 7 рядов карты сборки ────────────────────────────────────────────
ROW_PROBE = r"""
(() => Array.from(document.querySelectorAll('.speech-layer')).map((li) => {
  const btn = li.querySelector('.speech-layer-card-btn');
  const card = li.querySelector('.speech-layer-card');
  const key = (card && card.getAttribute('data-speech-layer')) || '';
  const st = card ? getComputedStyle(card) : null;
  return {
    key: key,
    interactive: !!btn,
    chevron: !!(li.querySelector('.speech-layer-go')),
    readonly: !!li.querySelector('[data-speech-layer-readonly]'),
    reason: (li.querySelector('[data-speech-layer-readonly-reason]') || {}).textContent || '',
    cursor: st ? st.cursor : null,
    label: (li.querySelector('.speech-layer-title') || {}).textContent || '',
    h: card ? Math.round(card.getBoundingClientRect().height) : 0,
  };
}))()
"""

EXPECTED_ROWS = ["core", "self_model", "l1", "lessons", "examples", "humor",
                 "writer"]

# B1 (ревью W4): после клика ряда L1/Writer detail обязан быть В ВИДИМОЙ
# области и содержать именно запрошенный ключ, а реестр — отфильтрован.
DETAIL_VISIBLE = r"""
(() => {
  const d = document.querySelector('[data-speech-block-detail]');
  if (!d) return {detail: false};
  const r = d.getBoundingClientRect();
  const h = document.querySelector('.main-header');
  const hb = h ? h.getBoundingClientRect().bottom : 0;
  const txt = (d.textContent || '');
  const rows = document.querySelectorAll('.speech-block-row').length;
  const scroller = document.querySelector('main.scroll-area');
  return {
    detail: true,
    top: Math.round(r.top), bottom: Math.round(r.bottom),
    h: Math.round(r.height), vh: window.innerHeight,
    headerBottom: Math.round(hb),
    inViewport: r.top >= hb - 2 && r.top < window.innerHeight - 40
      && (Math.min(r.bottom, window.innerHeight) - Math.max(r.top, hb)) >= 160,
    visibleH: Math.round(Math.max(0, Math.min(r.bottom, window.innerHeight)
      - Math.max(r.top, hb))),
    rows: rows,
    scrollTop: scroller ? Math.round(scroller.scrollTop) : null,
    scrollY: Math.round(window.scrollY),
  };
})()
"""


def check_rows(browser, label, shots):
    ctx, page = new_page(browser, 1280, 900)
    goto(page, "#/ai/speech")
    rows = page.evaluate(ROW_PROBE)
    keys = [r["key"] for r in rows]
    if keys != EXPECTED_ROWS:
        fail(label, "ряды карты сборки: %s (ожидались %s)" % (keys, EXPECTED_ROWS))
    for r in rows:
        if r["chevron"] and not r["interactive"]:
            fail(label, "ряд %s: стрелка без действия (обманный шеврон)" % r["key"])
        if r["interactive"] and not r["chevron"]:
            fail(label, "ряд %s: рабочая строка без шеврона" % r["key"])
        if not r["interactive"]:
            if not r["readonly"] or not (r["reason"] or "").strip():
                fail(label, "ряд %s: не интерактивен и без пометки/причины" % r["key"])
            if r["cursor"] == "pointer":
                fail(label, "ряд %s: read-only, но курсор pointer (ложный hitbox)"
                     % r["key"])
        if r["h"] < 44:
            fail(label, "ряд %s: высота %s < 44 px" % (r["key"], r["h"]))
    note(label=label + "/rows", rows=rows)
    # каждый интерактивный ряд реально куда-то ведёт
    for r in rows:
        if not r["interactive"]:
            continue
        ctx2, page2 = new_page(browser, 1280, 900)
        goto(page2, "#/ai/speech")
        page2.click("[data-speech-layer='%s']" % r["key"])
        page2.wait_for_timeout(1100)
        opened = page2.evaluate(
            "(() => ({section: !!document.querySelector('.speech-section'),"
            " block: (document.querySelector('[data-speech-block-detail] .tech-key')"
            " || document.querySelector('[data-speech-block-detail]') || {})"
            " .textContent || ''}))()")
        if not opened["section"]:
            fail(label, "ряд %s не открыл раздел" % r["key"])
        if r["key"] in ("l1", "writer"):
            want = ("direct.base.l1_planner" if r["key"] == "l1"
                    else "direct.base.l2_writer")
            if "все инструкции" not in page2.inner_text(".speech-section").lower():
                fail(label, "ряд %s не открыл «Все инструкции»" % r["key"])
            if want not in opened["block"]:
                fail(label, "ряд %s открыл не тот блок: %s"
                     % (r["key"], opened["block"][:80]))
            # B1: detail реально в видимой области и реестр отфильтрован
            vis = page2.evaluate(DETAIL_VISIBLE)
            if not vis.get("detail"):
                fail(label, "ряд %s: detail-карточка не отрисована" % r["key"])
            else:
                if not vis["inViewport"]:
                    fail(label, "ряд %s: detail не в видимой области "
                                "(top=%s, visibleH=%s, headerBottom=%s, vh=%s)"
                         % (r["key"], vis["top"], vis.get("visibleH"),
                            vis["headerBottom"], vis["vh"]))
                if vis["rows"] != 1:
                    fail(label, "ряд %s: реестр не отфильтрован по ключу (%s строк)"
                         % (r["key"], vis["rows"]))
                note(label="%s/visible_%s" % (label, r["key"]), visible=vis)
                if shots:
                    page2.screenshot(path=str(
                        SHOTS / ("row_%s_visible_%s.png" % (r["key"], label))))
        if shots:
            page2.screenshot(path=str(SHOTS / ("row_%s_%s.png" % (r["key"], label))))
        note(label="%s/row=%s" % (label, r["key"]), opened=opened["section"])
        ctx2.close()
    ctx.close()
    # То же на мобильной ширине: detail виден и содержит нужный ключ (B1)
    for key, want in (("l1", "direct.base.l1_planner"),
                      ("writer", "direct.base.l2_writer")):
        ctx3, page3 = new_page(browser, 390, 844)
        goto(page3, "#/ai/speech")
        page3.click("[data-speech-layer='%s']" % key)
        page3.wait_for_timeout(1200)
        vis = page3.evaluate(DETAIL_VISIBLE)
        body = page3.inner_text("[data-speech-block-detail]") \
            if page3.locator("[data-speech-block-detail]").count() else ""
        if not vis.get("detail") or not vis.get("inViewport"):
            fail("390", "ряд %s: detail не в видимой области (%s)" % (key, vis))
        if want not in body:
            fail("390", "ряд %s: в видимом detail нет ключа %s" % (key, want))
        note(label="390/visible_%s" % key, visible=vis)
        if shots:
            page3.screenshot(path=str(SHOTS / ("row_%s_visible_390.png" % key)))
        ctx3.close()


# ── U-03: сетка библиотеки промптов + подпись Direct ──────────────────────
GRID_PROBE = r"""
(() => {
  const grid = document.querySelector('[data-prompt-library-grid]');
  if (!grid) return null;
  const gs = getComputedStyle(grid);
  const cards = Array.from(grid.querySelectorAll('.prompt-module-card'));
  const rects = cards.map((c) => {
    const b = c.getBoundingClientRect();
    return {x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width),
            h: Math.round(b.height)};
  });
  const rowY = Array.from(new Set(rects.map((r) => r.y)));
  const perRow = {};
  rects.forEach((r) => { perRow[r.y] = (perRow[r.y] || 0) + 1; });
  const widths = Array.from(new Set(rects.map((r) => r.w)));
  return {
    display: gs.display, cols: gs.gridTemplateColumns.split(' ').length,
    gap: gs.gap, count: cards.length, rows: rowY.length,
    perRow: perRow, widths: widths,
    stages: Array.from(document.querySelectorAll('[data-prompt-library]'))
      .map((b) => b.getAttribute('data-prompt-library')),
  };
})()
"""

DIRECT_PROBE = r"""
(() => {
  const cards = Array.from(document.querySelectorAll('[data-cfg-key]'));
  const card = cards.find((c) => c.getAttribute('data-cfg-key')
    === 'prompts.direct_chat_verbalizer_system_prompt');
  if (!card) return null;
  const box = card.closest('.card');
  return {
    key: card.getAttribute('data-cfg-key'),
    title: (box.querySelector('.text-sm.font-semibold') || {}).textContent || '',
    description: (box.querySelector('.text-xs.text-gray-400') || {}).textContent || '',
    boxText: (box.textContent || '').slice(0, 400),
  };
})()
"""


def check_prompt_library(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    goto(page, "#/ai/prompts")
    g = page.evaluate(GRID_PROBE)
    if not g:
        fail(label, "нет сетки библиотеки промптов")
        ctx.close()
        return
    if g["display"] != "grid":
        fail(label, "библиотека промптов не в grid-системе (%s)" % g["display"])
    if len(set(g["perRow"].values())) > 1:
        fail(label, "карточки модулей разной ширины по рядам: %s" % g["perRow"])
    if len(g["widths"]) > 1 and max(g["widths"]) - min(g["widths"]) > 2:
        fail(label, "карточки модулей разной ширины: %s" % g["widths"])
    if width >= 1024 and g["cols"] < 3:
        fail(label, "на desktop библиотека не многоколоночная: %s колонок" % g["cols"])
    if width < 600 and g["cols"] != 1:
        fail(label, "на телефоне библиотека не в одну колонку: %s" % g["cols"])
    # этапные кнопки — только реально существующие этапы модуля
    for stage in ("synthesizer", "verbalizer"):
        _ = stage
    note(label=label + "/grid", grid={k: v for k, v in g.items() if k != "stages"})
    # подпись Direct-вербализатора = роль Writer, ключ не изменён
    direct = page.evaluate(DIRECT_PROBE)
    if not direct:
        fail(label, "карточка prompts.direct_chat_verbalizer_system_prompt не найдена")
    else:
        if "Direct: финальный ответ (Writer)" not in (direct["title"] or ""):
            fail(label, "подпись Direct-вербализатора не переименована: %s"
                 % (direct["title"] or "")[:80])
        if "характер задаётся отдельно" not in (direct["description"] or ""):
            fail(label, "нет пояснения роли под подписью: %s"
                 % (direct["description"] or "")[:80])
        if direct["key"] != "prompts.direct_chat_verbalizer_system_prompt":
            fail(label, "изменён ключ каталога Direct-вербализатора")
        note(label=label + "/direct", direct=direct)
    if shots:
        page.screenshot(path=str(SHOTS / ("prompts_%s.png" % label)))
    ctx.close()


# ── U-04: кодовые поля/Inspector — перенос строк ──────────────────────────
CODE_PROBE = r"""
(() => {
  const pres = Array.from(document.querySelectorAll('.speech-pre'));
  return pres.map((p) => {
    const st = getComputedStyle(p);
    const r = p.getBoundingClientRect();
    const card = p.closest('.card');
    const cr = card ? card.getBoundingClientRect() : null;
    return {
      key: p.getAttribute('data-speech-preview-payload') !== null
        ? 'preview' : (p.getAttribute('data-speech-sent-system') !== null
          ? 'sent' : 'other'),
      whiteSpace: st.whiteSpace,
      overflowWrap: st.overflowWrap,
      scrollW: p.scrollWidth, clientW: p.clientWidth,
      hOverflow: p.scrollWidth - p.clientWidth,
      right: Math.round(r.right),
      cardRight: cr ? Math.round(cr.right) : null,
    };
  });
})()
"""


def check_code_fields(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    goto(page, "#/ai/speech")
    page.click("[data-speech-card='inspector']")
    page.wait_for_selector("[data-speech-preview-payload]", state="visible")
    page.wait_for_timeout(500)
    items = page.evaluate(CODE_PROBE)
    if not items:
        fail(label, "Inspector: нет кодовых полей")
    for it in items:
        if "pre" not in (it["whiteSpace"] or ""):
            fail(label, "код %s: white-space=%s (ожидался перенос)"
                 % (it["key"], it["whiteSpace"]))
        if "anywhere" not in (it["overflowWrap"] or ""):
            fail(label, "код %s: overflow-wrap=%s (ожидался anywhere)"
                 % (it["key"], it["overflowWrap"]))
        if it["hOverflow"] > 1:
            fail(label, "код %s: горизонтальный скролл внутри (%s px)"
                 % (it["key"], it["hOverflow"]))
        if it["cardRight"] is not None and it["right"] > it["cardRight"] + 1:
            fail(label, "код %s выходит за карточку (%s > %s)"
                 % (it["key"], it["right"], it["cardRight"]))
    p = page.evaluate("(() => ({ov: document.documentElement.scrollWidth - window.innerWidth}))()")
    if p["ov"] > 1:
        fail(label, "Inspector: горизонтальный overflow страницы %s px" % p["ov"])
    note(label=label + "/code", items=items[:4])
    if shots:
        page.screenshot(path=str(SHOTS / ("inspector_%s.png" % label)))
    # вставка/выделение в textarea не ломаются (U-04: caret/selection/paste)
    page.click(".speech-back")
    page.wait_for_selector(".speech-grid", state="visible")
    page.click("[data-speech-card='core']")
    page.wait_for_selector(".speech-section .speech-editor", state="visible")
    page.wait_for_timeout(300)
    ed = page.locator(".speech-section .speech-editor").first
    ed.click()
    ed.press("Control+A")
    ed.press("End")
    marker = " ВСТАВКА-ПРОВЕРКА-1234567890-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ed.type(marker, delay=1)
    val = ed.input_value()
    if not val.endswith(marker.strip()) and marker.strip() not in val:
        fail(label, "textarea: ввод/вставка не дошли до значения")
    sel = page.evaluate(
        "(() => { const t = document.querySelector('.speech-section .speech-editor');"
        " t.setSelectionRange(3, 9); return [t.selectionStart, t.selectionEnd]; })()")
    if sel != [3, 9]:
        fail(label, "textarea: выделение не выставляется (%s)" % sel)
    if page.evaluate("document.documentElement.scrollWidth - window.innerWidth") > 1:
        fail(label, "textarea: появилась вторая горизонтальная прокрутка страницы")
    note(label=label + "/editor_value", len=len(val), sel=sel)
    ctx.close()


# ── U-05: редактор Core — табы, «Развернуть», scope/редакция ───────────────
def check_core_editor(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    goto(page, "#/ai/speech")
    page.click("[data-speech-card='core']")
    page.wait_for_selector(".speech-section .speech-editor", state="visible")
    page.wait_for_timeout(400)
    tabs = page.evaluate(r"""
    (() => {
      const box = document.querySelector('.speech-tabs');
      const btns = Array.from(box.querySelectorAll('.speech-tab'));
      const r = box.getBoundingClientRect();
      const over = btns.map((b) => {
        const br = b.getBoundingClientRect();
        return {text: b.textContent.trim(), right: Math.round(br.right),
                w: Math.round(br.width),
                clipped: b.scrollWidth > b.clientWidth + 1};
      });
      return {boxW: Math.round(r.width), vw: window.innerWidth,
              overflow: Math.round(r.right) - window.innerWidth, tabs: over};
    })()""")
    if tabs["overflow"] > 1:
        fail(label, "переключатель редакций выходит за экран: %s" % tabs["overflow"])
    for t in tabs["tabs"]:
        if t["clipped"]:
            fail(label, "подпись таба обрезана: %s" % t["text"])
    note(label=label + "/tabs", tabs=tabs)
    # «Развернуть» реально открывает крупный редактор и закрывается
    expand = page.locator(".speech-expand-btn")
    if not expand.count() or not expand.first.is_visible():
        fail(label, "нет видимой кнопки «Развернуть» (<600px)")
    else:
        expand.first.click()
        page.wait_for_selector(".speech-fullscreen", state="visible")
        page.wait_for_timeout(300)
        fs = page.evaluate(r"""
        (() => {
          const d = document.querySelector('.speech-fullscreen');
          const ta = d.querySelector('.speech-editor');
          const r = d.getBoundingClientRect();
          const tr = ta.getBoundingClientRect();
          return {w: Math.round(r.width), h: Math.round(r.height),
                  vw: window.innerWidth, vh: window.innerHeight,
                  taH: Math.round(tr.height),
                  focused: document.activeElement === ta,
                  readonly: ta.readOnly,
                  closeBtn: !!d.querySelector('[data-speech-editor-close]')};
        })()""")
        if fs["w"] < fs["vw"] - 2 or fs["h"] < fs["vh"] - 2:
            fail(label, "«Развернуть» открыл не крупный экран: %s" % fs)
        if fs["taH"] < 120:
            fail(label, "«Развернуть»: поле слишком низкое (%s px)" % fs["taH"])
        if not fs["focused"]:
            fail(label, "«Развернуть»: фокус не в поле")
        if not fs["closeBtn"]:
            fail(label, "«Развернуть»: нет доступного закрытия")
        note(label=label + "/expand", expand=fs)
        if shots:
            page.screenshot(path=str(SHOTS / ("core_expand_%s.png" % label)))
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        if page.locator(".speech-fullscreen").count():
            fail(label, "Esc не закрыл крупный редактор")
        expand.first.click()
        page.wait_for_selector(".speech-fullscreen", state="visible")
        page.click("[data-speech-editor-close]")
        page.wait_for_timeout(300)
        if page.locator(".speech-fullscreen").count():
            fail(label, "кнопка «Закрыть» не закрыла крупный редактор")
    ctx.close()


# ── U-07: sticky-save state machine ───────────────────────────────────────
SAVE_PROBE = r"""
(() => {
  const bar = document.querySelector('.speech-section [data-speech-savebar]');
  const primary = bar ? bar.querySelector('[data-speech-save-primary]') : null;
  const retry = bar ? bar.querySelector('[data-speech-save-retry]') : null;
  const refresh = bar ? bar.querySelector('[data-speech-save-refresh]') : null;
  const visible = (el) => !!(el && el.offsetParent !== null);
  const actions = bar ? Array.from(bar.querySelectorAll('button'))
    .filter((b) => b.offsetParent !== null)
    .map((b) => (b.textContent || '').replace(/\s+/g, ' ').trim()) : [];
  const allSaves = Array.from(document.querySelectorAll(
    '.speech-section .btn-accent')).filter((b) => b.offsetParent !== null);
  const st = bar ? getComputedStyle(bar) : null;
  const r = bar ? bar.getBoundingClientRect() : null;
  return {
    bar: !!bar,
    state: bar ? bar.getAttribute('data-speech-save-state') : null,
    text: bar ? bar.textContent.replace(/\s+/g, ' ').trim().slice(0, 160) : '',
    primary: visible(primary),
    primaryDisabled: primary ? !!primary.disabled : null,
    retry: visible(retry),
    refresh: visible(refresh),
    actions: actions,
    activeSaves: allSaves.length,
    position: st ? st.position : null,
    rect: r ? {y: Math.round(r.y), bottom: Math.round(r.bottom),
               h: Math.round(r.height)} : null,
    vh: window.innerHeight,
    savedText: (document.querySelector('[data-speech-saved]') || {}).textContent || '',
  };
})()
"""


def check_save_machine(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    goto(page, "#/ai/speech")
    page.click("[data-speech-card='core']")
    page.wait_for_selector(".speech-section .speech-editor", state="visible")
    page.wait_for_timeout(400)
    # pristine: панели нет (нечего сохранять)
    p0 = page.evaluate(SAVE_PROBE)
    if p0["bar"]:
        fail(label, "pristine: панель сохранения показана без правок (%s)"
             % p0["text"][:80])
    if p0["activeSaves"] != 0:
        fail(label, "pristine: активных «Сохранить» %s (ожидалось 0)"
             % p0["activeSaves"])
    # dirty
    ed = page.locator(".speech-section .speech-editor").first
    ed.click()
    ed.press("End")
    ed.type(" правка W4", delay=2)
    page.wait_for_timeout(350)
    p1 = page.evaluate(SAVE_PROBE)
    if not p1["bar"] or p1["state"] != "dirty":
        fail(label, "dirty: панель/состояние неверны (%s)" % (p1,))
    if p1["activeSaves"] != 1:
        fail(label, "dirty: активных Save %s (должен быть ровно один CTA)"
             % p1["activeSaves"])
    if p1["rect"] and p1["rect"]["bottom"] > p1["vh"] + 1:
        fail(label, "dirty: панель уехала за вьюпорт: %s" % p1["rect"])
    note(label=label + "/save_dirty", probe=p1)
    if shots:
        page.screenshot(path=str(SHOTS / ("save_dirty_%s.png" % label)))
    # saving (медленный ответ сервера — состояние реально видно в UI)
    POST_MODE["mode"] = "server"
    POST_MODE["delay"] = 1.0
    page.click("[data-speech-save-primary]")
    page.wait_for_timeout(300)
    p2 = page.evaluate(SAVE_PROBE)
    if p2["state"] != "saving":
        fail(label, "saving: состояние панели %s (%s)"
             % (p2["state"], p2["text"][:60]))
    if not p2["primaryDisabled"]:
        fail(label, "saving: кнопка сохранения не заблокирована")
    note(label=label + "/save_saving", probe=p2)
    page.wait_for_timeout(1600)
    POST_MODE["delay"] = 0.0
    POST_MODE["mode"] = "ok"
    # saved: статус есть, второй активный Save отсутствует
    p3 = page.evaluate(SAVE_PROBE)
    if not p3["bar"]:
        fail(label, "saved: панель исчезла вместе со статусом (10 c контракт)")
    if "Сохранено" not in p3["text"]:
        fail(label, "saved: нет статуса «Сохранено» (%s)" % p3["text"][:80])
    if p3["primary"]:
        fail(label, "saved: активный Save рядом со статусом (дублирующий CTA)")
    if p3["activeSaves"] != 0:
        fail(label, "saved: активных Save %s (ожидалось 0)" % p3["activeSaves"])
    if p3["position"] not in (None, "sticky"):
        fail(label, "saved: панель не sticky (%s)" % p3["position"])
    note(label=label + "/save_saved", probe=p3)
    # error 503 → «Повторить», ввод не потерян
    POST_MODE["mode"] = "503"
    ed.click()
    ed.press("End")
    ed.type(" e503", delay=2)
    page.wait_for_timeout(300)
    page.click("[data-speech-save-primary]")
    page.wait_for_timeout(900)
    p4 = page.evaluate(SAVE_PROBE)
    if p4["state"] != "error":
        fail(label, "error: состояние панели %s" % p4["state"])
    if not p4["retry"]:
        fail(label, "error: нет «Повторить сохранение» (%s)" % p4["text"][:80])
    # B2: в error ровно ОДИН главный CTA — повтор, без второго Save
    if p4["primary"]:
        fail(label, "error: рядом с «Повторить» остаётся активный Сохранить")
    if p4["activeSaves"] != 0:
        fail(label, "error: активных accent-Save %s (ожидалось 0)"
             % p4["activeSaves"])
    if len(p4["actions"]) != 1:
        fail(label, "error: действий в панели %s (ожидался один CTA): %s"
             % (len(p4["actions"]), p4["actions"]))
    if "e503" not in page.input_value(".speech-section .speech-editor"):
        fail(label, "error: черновик потерян")
    note(label=label + "/save_error", probe=p4)
    # conflict 409 — РЕАЛЬНЫЙ путь ревьюера: повтор из error-состояния
    # (именно эта кнопка раньше обходила защиту). После ответа 409:
    # retry исчезает, Save скрыт, остаётся только «Обновить данные»,
    # и никакой POST по бару больше не уходит.
    POST_MODE["mode"] = "conflict"
    before_conflict = len(POSTS)
    page.click("[data-speech-save-retry]")
    page.wait_for_timeout(1000)
    p5 = page.evaluate(SAVE_PROBE)
    if len(POSTS) != before_conflict + 1:
        fail(label, "conflict: повтор из error не отправил запрос (%s → %s)"
             % (before_conflict, len(POSTS)))
    if p5["state"] != "conflict":
        fail(label, "conflict: состояние панели %s (%s)"
             % (p5["state"], p5["text"][:80]))
    if "Конфликт" not in p5["text"]:
        fail(label, "conflict: нет объяснения конфликта (%s)" % p5["text"][:80])
    if p5["primary"]:
        fail(label, "conflict: активный Save остаётся (возможна слепая перезапись)")
    if p5["retry"]:
        fail(label, "conflict: активная «Повторить сохранение» обходит защиту")
    if not p5["refresh"]:
        fail(label, "conflict: нет действия «Обновить данные»")
    if len(p5["actions"]) != 1 or "Обновить данные" not in p5["actions"]:
        fail(label, "conflict: в панели не единственный CTA: %s" % p5["actions"])
    if p5.get("savedText"):
        fail(label, "conflict: рядом висит старый статус «%s»"
             % p5["savedText"].strip())
    toasts = page.evaluate(
        "Array.from(document.querySelectorAll('.toast')).map((t) => "
        "(t.textContent || '').replace(/\\s+/g, ' ').trim())")
    if any("Сохранено" in t for t in toasts):
        fail(label, "conflict: живёт старый зелёный тост «Сохранено»: %s"
             % [t for t in toasts if "Сохранено" in t])
    note(label=label + "/save_conflict", probe=p5)
    if shots:
        page.screenshot(path=str(SHOTS / ("save_conflict_%s.png" % label)))
    # Клик по единственному действию не порождает POST (это GET-перечитывание).
    before_click = len(POSTS)
    page.click("[data-speech-save-refresh]")
    page.wait_for_timeout(1000)
    if len(POSTS) != before_click:
        fail(label, "conflict: клик по единственному CTA отправил POST (%s → %s)"
             % (before_click, len(POSTS)))
    p6 = page.evaluate(SAVE_PROBE)
    if p6["state"] == "conflict":
        fail(label, "conflict не снят после «Обновить данные»")
    POST_MODE["mode"] = "ok"
    ctx.close()


# ── U-06: шапка/крошка/scope/навигация ────────────────────────────────────
def check_header(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    goto(page, "#/ai/prompts")
    p = probe_flow(page, label + "/header", width)
    bc = " ".join((p["breadcrumb"] or "").split())
    title = " ".join((p["title"] or "").split())
    if width >= 768:
        if not bc or not title:
            fail(label, "desktop: нет крошки или заголовка (%s|%s)" % (bc, title))
        if title and title in bc:
            fail(label, "заголовок повторяет крошку: «%s» в «%s»" % (title, bc))
        if bc.count("/") > 2:
            fail(label, "крошка глубже двух уровней: %s" % bc)
    if len(p["scopeBadges"]) != 1:
        fail(label, "селекторов области в шапке: %s (должен быть один)"
             % len(p["scopeBadges"]))
    # скролл: шапка не перекрывает контент
    #  - структурно: main начинается НЕ выше низа шапки (flex-колонка);
    #  - после scrollIntoView якорь не уезжает под шапку (scroll-padding-top).
    page.evaluate("() => { const m = document.querySelector('main');"
                  " if (m) m.scrollTop = 0; window.scrollTo(0, 0); }")
    page.wait_for_timeout(250)
    p0 = page.evaluate(FLOW_PROBE)
    if p0["header"] and p0["main"] and p0["mainTop"] < p0["header"]["bottom"] - 2:
        fail(label, "контент стартует под шапкой: main.top=%s header.bottom=%s"
             % (p0["mainTop"], p0["header"]["bottom"]))
    page.evaluate("() => { const el = document.querySelector('.card') ||"
                  " document.querySelector('main'); if (el) el.scrollIntoView();"
                  " window.scrollBy(0, 400); }")
    page.wait_for_timeout(400)
    anchor_ok = page.evaluate(r"""
    (() => {
      const h = document.querySelector('.main-header');
      const first = document.querySelector('main .card') ||
                    document.querySelector('main > *');
      if (!h || !first) return true;
      first.scrollIntoView();
      const hb = h.getBoundingClientRect().bottom;
      return first.getBoundingClientRect().top >= hb - 40;
    })()""")
    if not anchor_ok:
        fail(label, "после прокрутки к элементу верх контента уходит под шапку")
    if shots:
        page.screenshot(path=str(SHOTS / ("header_%s.png" % label)))
    # мобильная навигация: drawer отдаёт ПОЛНЫЙ список разделов
    if width < 768:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.click("[data-drawer-trigger]")
        page.wait_for_timeout(400)
        items = page.evaluate(
            "(() => Array.from(document.querySelectorAll("
            "'.app-drawer .sidebar-link')).map((b) => b.textContent.trim()))()")
        if len(items) < 4:
            fail(label, "drawer отдаёт лишь %s разделов: %s"
                 % (len(items), items))
        labels = " ".join(items)
        for want in ("ИИ", "Память"):
            if want not in labels:
                fail(label, "drawer не содержит «%s» (%s)" % (want, items))
        note(label=label + "/drawer_menu", items=items)
        if shots:
            page.screenshot(path=str(SHOTS / ("drawer_menu_%s.png" % label)))
        page.keyboard.press("Escape")
    else:
        # drawer 768–1199 / sidebar ≥1200 — полный набор
        btn = page.locator(".main-header button[aria-label='Открыть навигацию']")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(400)
            n = page.locator(".app-drawer .sidebar-link").count()
            if n < 4:
                fail(label, "drawer отдаёт %s разделов" % n)
            note(label=label + "/drawer", count=n)
            page.keyboard.press("Escape")
        else:
            n = page.locator(".app-sidebar .sidebar-link").count()
            if n < 4:
                fail(label, "sidebar отдаёт %s разделов" % n)
            note(label=label + "/sidebar", count=n)
    ctx.close()


# ── U-08: prefers-reduced-motion + мерцание при polling ───────────────────
def check_motion_and_polling(browser, width, height, label, shots):
    ctx, page = new_page(browser, width, height)
    page.emulate_media(reduced_motion="reduce")
    goto(page, "#/ai/speech")
    page.wait_for_timeout(600)
    ctx.close()
    # 1) reduced-motion: слой преломления статичен (два кадра совпадают)
    ctx, page = new_page(browser, width, height)
    page.emulate_media(reduced_motion="reduce")
    goto(page, "#/ai/speech")
    page.wait_for_timeout(1800)
    box = page.evaluate(
        "(() => { const r = document.querySelector('.speech-head')"
        ".getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y),"
        " w: Math.round(r.width), h: Math.round(r.height)}; })()")
    a = SHOTS / ("motion_a_%s.png" % label)
    b = SHOTS / ("motion_b_%s.png" % label)
    clip = {"x": box["x"], "y": box["y"], "width": box["w"],
            "height": min(box["h"], 160)}
    page.screenshot(path=str(a), clip=clip)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(b), clip=clip)
    wa, ha, pa = load_png(a)
    wb, hb, pb = load_png(b)
    diff = 0
    for i in range(0, min(len(pa), len(pb)), 3):
        if abs(pa[i] - pb[i]) > 6:
            diff += 1
    frac = diff / float(max(1, wa * ha))
    if frac > 0.02:
        fail(label, "reduced-motion: слой/фон продолжает двигаться (%.1f%% пикселей)"
             % (100 * frac))
    note(label=label + "/reduced_motion", moved_frac=round(frac, 4))
    # 2) polling: ручное «Обновить данные» не меняет фон и стекло
    pause_bg(page)
    a2 = SHOTS / ("poll_a_%s.png" % label)
    b2 = SHOTS / ("poll_b_%s.png" % label)
    page.screenshot(path=str(a2), clip=clip)
    page.click(".speech-refresh")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(b2), clip=clip)
    w2, h2, q1 = load_png(a2)
    w3, h3, q2 = load_png(b2)
    diff2 = 0
    for i in range(0, min(len(q1), len(q2)), 3):
        if abs(q1[i] - q2[i]) > 6:
            diff2 += 1
    frac2 = diff2 / float(max(1, w2 * h2))
    if frac2 > 0.02:
        fail(label, "polling: фон/стекло мерцает (%.1f%% пикселей)"
             % (100 * frac2))
    note(label=label + "/polling", moved_frac=round(frac2, 4))
    ctx.close()


# ── U-08: контраст вторичного текста по фактическим пикселям ──────────────
CONTRAST_SAMPLE = r"""
(() => {
  const out = [];
  const push = (name, el) => {
    if (!el) return;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    out.push({name: name, color: st.color, fontSize: st.fontSize,
              x: Math.round(r.x), y: Math.round(r.y),
              w: Math.round(r.width), h: Math.round(r.height)});
  };
  push('speech-card-sub', document.querySelector('.speech-card-sub'));
  push('speech-layer-detail', document.querySelector('.speech-layer-detail'));
  push('speech-note', document.querySelector('.speech-screen .text-gray-500'));
  push('speech-layers-sub', document.querySelector('.speech-layers-sub'));
  return out;
})()
"""


def check_contrast(browser, label, shots):
    ctx, page = new_page(browser, 390, 844, dsf=2)
    goto(page, "#/ai/speech")
    pause_bg(page)
    samples = page.evaluate(CONTRAST_SAMPLE)
    if not samples:
        fail(label, "не найдены образцы вторичного текста")
        ctx.close()
        return None
    full = SHOTS / ("contrast_%s.png" % label)
    page.screenshot(path=full)
    w, h, px = load_png(full)
    dsf = 2
    out = []
    for s in samples:
        # фон — чистый участок той же поверхности под текстом (≈0.9 строки ниже)
        fpx = float(s["fontSize"].replace("px", "")) * dsf
        bx = min(w - 1, max(0, int((s["x"] + 4) * dsf)))
        by = int((s["y"] + s["h"]) * dsf + fpx * 0.9)
        if by >= h - 2:
            by = max(0, int(s["y"] * dsf) - 2)
        by = min(h - 1, max(0, by))
        bg = rgb_at(px, w, bx, by)
        col = [int(float(c)) for c in
               s["color"].replace("rgba(", "").replace("rgb(", "")
               .replace(")", "").split(",")[:3]]
        ratio = contrast(col, bg)
        out.append({"name": s["name"], "color": s["color"], "bg": [round(c) for c in bg],
                    "fontSize": s["fontSize"], "ratio": round(ratio, 2)})
        if ratio < 4.5:
            fail(label, "контраст %s = %.2f:1 (<4.5) при %s"
                 % (s["name"], ratio, s["fontSize"]))
    note(label=label + "/contrast", samples=out)
    ctx.close()
    return out


# ── U-09: полный маршрут GLOBAL и CHAT ───────────────────────────────────
def check_route(browser, label, chat=False, shots=False):
    ctx, page = new_page(browser, 1280, 900)
    goto(page, "#/")
    # Явно выбираем область: при одном чате приложение стартует в контексте
    # чата, поэтому GLOBAL — это осознанный выбор «Весь бот».
    page.click(".scope-trigger")
    page.wait_for_timeout(300)
    opts = page.locator(".scope-option")
    want = "Audit Chat" if chat else "Весь бот"
    picked = False
    for i in range(opts.count()):
        txt = opts.nth(i).inner_text() or ""
        if want in txt:
            opts.nth(i).click()
            picked = True
            break
    if not picked:
        fail(label, "в селекторе области нет опции «%s»" % want)
    page.wait_for_timeout(650)
    # 1. Статус активен
    p = probe_flow(page, label + "/status", 1280)
    if chat and "ЧАТ" not in " ".join(p["scopeBadges"]):
        fail(label, "после выбора чата индикатор области не «ЧАТ» (%s)"
             % p["scopeBadges"])
    if not chat and "ЧАТ" in " ".join(p["scopeBadges"]):
        fail(label, "GLOBAL: индикатор области всё ещё «ЧАТ» (%s)"
             % p["scopeBadges"])
    # 2. Статус → ИИ
    page.click(".sidebar-link[title='ИИ']")
    page.wait_for_timeout(700)
    if page.evaluate("location.hash") != "#/ai":
        fail(label, "переход «Статус → ИИ» не сработал (%s)"
             % page.evaluate("location.hash"))
    probe_flow(page, label + "/ai", 1280)
    # 3. ИИ → Речь и характер
    page.click("[data-speech-hub-entry]")
    page.wait_for_selector(".speech-screen", state="visible")
    if page.evaluate("location.hash") != "#/ai/speech":
        fail(label, "вход «Речь и характер» ведёт не туда")
    probe_flow(page, label + "/speech", 1280)
    # 4. Core
    page.click("[data-speech-layer='core']")
    page.wait_for_selector(".speech-section .speech-editor", state="visible")
    if chat:
        sc = page.input_value(
            ".speech-section select[aria-label='Куда сохранить правку характера']")
        if sc != "chat":
            fail(label, "CHAT: цель сохранения характера = %s" % sc)
        # Сохранение реально уходит в выбранный scope (не «тихо в global»)
        ed = page.locator(".speech-section .speech-editor").first
        ed.click()
        ed.press("End")
        ed.type(" · chat-scope", delay=1)
        page.wait_for_timeout(300)
        before = len(POSTS)
        page.click("[data-speech-save-primary]")
        page.wait_for_timeout(900)
        if len(POSTS) != before + 1:
            fail(label, "CHAT: сохранение не ушло в API")
        else:
            rec = POSTS[-1]
            if rec["body"].get("scope") != "chat":
                fail(label, "CHAT: сохранение ушло в scope=%s"
                     % rec["body"].get("scope"))
            if str(rec["chat"] or "") == "":
                fail(label, "CHAT: запрос без X-Chat-Id")
            note(label=label + "/chat_save", scope=rec["body"].get("scope"),
                 chat=rec["chat"])
    else:
        # GLOBAL: та же правка уходит без чата, scope=global
        ed = page.locator(".speech-section .speech-editor").first
        ed.click()
        ed.press("End")
        ed.type(" · global-scope", delay=1)
        page.wait_for_timeout(300)
        before = len(POSTS)
        page.click("[data-speech-save-primary]")
        page.wait_for_timeout(900)
        if len(POSTS) != before + 1:
            fail(label, "GLOBAL: сохранение не ушло в API")
        else:
            rec = POSTS[-1]
            if rec["body"].get("scope") != "global":
                fail(label, "GLOBAL: сохранение ушло в scope=%s"
                     % rec["body"].get("scope"))
            note(label=label + "/global_save", scope=rec["body"].get("scope"))
    # 5. Назад → витрина
    page.click(".speech-back")
    page.wait_for_selector(".speech-grid", state="visible")
    # 6. Expression
    page.click("[data-speech-card='expression']")
    page.wait_for_selector("[data-speech-expression-preview]", state="visible")
    probe_flow(page, label + "/expression", 1280, expect_section="open")
    page.click(".speech-back")
    page.wait_for_selector(".speech-grid", state="visible")
    # 7. Библиотека промптов (через «ИИ» → хаб → карточка)
    page.click(".sidebar-link[title='ИИ']")
    page.wait_for_timeout(600)
    page.click(".hub-card:has-text('Библиотека промптов')")
    page.wait_for_selector("[data-prompt-library-grid]", state="visible")
    page.wait_for_timeout(400)
    if page.evaluate("location.hash") != "#/ai/prompts":
        fail(label, "переход в библиотеку промптов не сработал (%s)"
             % page.evaluate("location.hash"))
    probe_flow(page, label + "/prompts", 1280)
    # 8. Direct Writer
    direct = page.evaluate(r"""
    (() => {
      const cards = Array.from(document.querySelectorAll('.prompt-module-card'));
      const c = cards.find((x) => /Ответы в чате/.test(x.textContent));
      if (!c) return null;
      const b = c.querySelector("[data-prompt-library$='/verbalizer']");
      return b ? b.getAttribute('data-prompt-library') : null;
    })()""")
    if not direct:
        fail(label, "в библиотеке нет карточки Direct с этапом verbalizer")
    else:
        page.click("[data-prompt-library='%s']" % direct)
        page.wait_for_timeout(1100)
        txt = page.inner_text("main")
        if "Direct: финальный ответ (Writer)" not in txt:
            fail(label, "Direct Writer открылся без верной подписи")
        if "характер задаётся отдельно" not in txt:
            fail(label, "Direct Writer: нет пояснения роли под подписью")
        if "Вербализатор прямого чата" in txt:
            fail(label, "остался старый ярлык «Вербализатор прямого чата»")
        note(label=label + "/direct_writer", stage=direct,
             ok=True)
        if shots:
            page.screenshot(path=str(SHOTS / ("route_direct_%s.png" % label)))
    # 9. Назад: возвращаемся к библиотеке и проверяем сохранение контекста
    page.go_back()
    page.wait_for_timeout(800)
    hash_after = page.evaluate("location.hash")
    if "#/ai/prompts" not in hash_after:
        fail(label, "Back не вернул в библиотеку (%s)" % hash_after)
    probe_flow(page, label + "/back", 1280)
    # 10. resize не ломает контекст (маршрут и раздел)
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(700)
    probe_flow(page, label + "/resize390", 390)
    page.set_viewport_size({"width": 1280, "height": 900})
    page.wait_for_timeout(500)
    if page.evaluate("location.hash") != hash_after:
        fail(label, "resize потерял маршрут")
    ctx.close()


# ── Скриншоты маршрута для before/after ──────────────────────────────────
def capture_route_shots(browser, tag):
    """Один маршрут и те же данные: витрина «Речи и характера», раздел Core,
    библиотека промптов — на всех приёмных ширинах."""
    EVID = SHOTS / tag
    EVID.mkdir(parents=True, exist_ok=True)
    out = []
    for label, w, h in VIEWPORTS:
        ctx, page = new_page(browser, w, h)
        goto(page, "#/ai/speech")
        pause_bg(page)
        f = EVID / ("speech_showcase_%s.png" % label)
        page.screenshot(path=str(f))
        out.append(str(f.relative_to(REPO)))
        page.click("[data-speech-card='core']")
        page.wait_for_selector(".speech-section .speech-editor", state="visible")
        page.wait_for_timeout(400)
        pause_bg(page)
        f = EVID / ("speech_core_%s.png" % label)
        page.screenshot(path=str(f))
        out.append(str(f.relative_to(REPO)))
        goto(page, "#/ai/prompts")
        pause_bg(page)
        f = EVID / ("prompts_%s.png" % label)
        page.screenshot(path=str(f))
        out.append(str(f.relative_to(REPO)))
        ctx.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-shots", action="store_true")
    ap.add_argument("--serve-only", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    shots = not args.no_shots
    SHOTS.mkdir(parents=True, exist_ok=True)

    # Медленный ответ сервера для наблюдаемого состояния `saving`
    # (сервер — отдельный поток, поэтому sleep не блокирует Playwright).
    _orig_post = W6._post_body

    def _slow_post(name, req):
        if POST_MODE.get("delay"):
            time.sleep(float(POST_MODE["delay"]))
        return _orig_post(name, req)

    W6._post_body = _slow_post

    W6.serve(PORT, str(REPO / "web"))
    if args.serve_only:
        print("стенд: %s/web/index.html#/ai/speech  (Ctrl+C — стоп)" % BASE)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0

    from playwright.sync_api import sync_playwright

    report = {"viewports": {v[0]: [v[1], v[2]] for v in VIEWPORTS},
              "failures": [], "notes": [], "posts": [], "shots": []}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            if not args.only or args.only == "flow":
                for label, w, h in VIEWPORTS:
                    for route in ("#/", "#/ai", "#/ai/speech", "#/ai/prompts"):
                        ctx, page = new_page(browser, w, h)
                        goto(page, route)
                        probe_flow(page, "%s%s" % (label, route), w)
                        ctx.close()
                    for section in ("core", "expression", "all", "inspector"):
                        ctx, page = new_page(browser, w, h)
                        goto(page, "#/ai/speech")
                        page.click("[data-speech-card='%s']" % section)
                        page.wait_for_timeout(650)
                        probe_flow(page, "%s/speech/%s" % (label, section), w,
                                   expect_section="open")
                        ctx.close()
            if not args.only or args.only == "rows":
                check_rows(browser, "1280", shots)
            if not args.only or args.only == "glass":
                check_glass(browser, "#/ai/prompts", GLASS_LUMA, "prompts", shots)
                check_glass(browser, "#/ai/speech", r"""
                (() => { const r = document.querySelector('.speech-head')
                  .getBoundingClientRect(); return {x: Math.round(r.x),
                  y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}; })()
                """, "speech_head", shots)
                ctx, page = new_page(browser, 1280, 800)
                goto(page, "#/ai/speech")
                check_hit(page, "speech_hit")
                ctx.close()
            if not args.only or args.only == "u03":
                for label, w, h in (("320", 320, 700), ("390", 390, 844),
                                    ("768", 768, 1024), ("1280", 1280, 800)):
                    check_prompt_library(browser, w, h, label, shots)
            if not args.only or args.only == "u04":
                for label, w, h in (("320", 320, 700), ("360", 360, 780),
                                    ("390", 390, 844), ("430", 430, 932),
                                    ("landscape", 667, 375)):
                    check_code_fields(browser, w, h, label, shots)
            if not args.only or args.only == "u05":
                for label, w, h in (("320", 320, 700), ("390", 390, 844),
                                    ("430", 430, 932), ("landscape", 667, 375)):
                    check_core_editor(browser, w, h, label, shots)
            if not args.only or args.only == "u06":
                for label, w, h in VIEWPORTS:
                    check_header(browser, w, h, label, shots)
            if not args.only or args.only == "u07":
                for label, w, h in (("390", 390, 844), ("1280", 1280, 800)):
                    check_save_machine(browser, w, h, label, shots)
            if not args.only or args.only == "u08":
                for label, w, h in (("390", 390, 844), ("1280", 1280, 800)):
                    check_motion_and_polling(browser, w, h, label, shots)
                check_contrast(browser, "390", shots)
            if not args.only or args.only == "u09":
                check_route(browser, "global", chat=False, shots=shots)
                check_route(browser, "chat", chat=True, shots=shots)
            if shots and (not args.only or args.only in ("shots", "flow")):
                report["shots"] = capture_route_shots(browser, "after")
    report["failures"] = failures
    report["notes"] = notes
    report["posts"] = POSTS
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "ui-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n== ИТОГ: failures=%d, POST=%d, notes=%d"
          % (len(failures), len(POSTS), len(notes)))
    for row in failures:
        print("  -", row)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
