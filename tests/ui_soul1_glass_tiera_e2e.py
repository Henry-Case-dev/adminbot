"""HOTFIX-TIERA (SOUL-1): реальная рефракция Tier A на РЕАЛЬНЫХ страницах MiniApp.

Задача (владелец): Tier A — основной материал ВСЕХ стеклянных поверхностей
(карточки/панели/навигация/модули/Статус/Аналитика/настройки/модалки);
Tier B — только честный fallback, Tier C — редакторы/таблицы/плотный текст.
`tierA=true` НЕ является доказательством: нужен ИЗМЕРИМЫЙ сдвиг подложки.

Метод (детерминированный, прод не меняется):
  * прод-страница отдаётся статикой из `web/` (как ui_asap8_w2_shell_e2e.py),
    `/api/*` — стабы матрицы round1025 (`UI_POLYGON_BG_ENABLED=True`);
  * `?bgseed=<N>` → детерминированная сцена полигонального фона, затем
    `window.__PolygonBackground.pause()` — фон ЗАМОРОЖЕН (только в харнессе);
  * в body добавляется ТЕСТ-слой измерения (fixed, z-index 0 ПОД #app и НАД
    canvas фона): вертикальные полосы периода 24px — высококонтрастная мишень
    ЗА поверхностью;
  * ON = `UI_GLASS_TIER_OVERRIDE=a` (Tier A), OFF = `b` (Tier B frost) на одной
    и той же замороженной позиции фона;
  * замер: контент самой поверхности (дети) на время пиксельного замера скрыт
    (visibility:hidden, одинаково в ON и OFF) — иначе кросс-корреляция ловит
    собственный текст/иконки вместо смещённой мишени ЗА стеклом;
  * метрика: локальный сдвиг мишени (окно 32px, ±12px) внутри поверхности.
    Линза (выпуклая, выборка К ЦЕНТРУ) даёт сдвиг у кромок и ≈0 в центре;
    frost-blur сдвига НЕ даёт (симметричное размытие) — метрика разделяет
    «рефракцию» и «blur». Дополнительно считается видимость мишени за
    поверхностью (pattern_energy): плотная подложка → замер неприменим
    (сообщаем честно, а не «0 = нет рефракции»).

Запуск:
  .venv/Scripts/python.exe tests/ui_soul1_glass_tiera_e2e.py inventory
  .venv/Scripts/python.exe tests/ui_soul1_glass_tiera_e2e.py verify [--dpr 1]
  .venv/Scripts/python.exe tests/ui_soul1_glass_tiera_e2e.py perf

TEST-LIFECYCLE: CONTRACT owner=SOUL-1/HOTFIX-TIERA (Tier A = реальная рефракция
на реальных страницах); REGRESSION owner=HOTFIX-TIERA (карточки админки
показывали Tier B frost вместо рефракции до фикса 2026-10-16).
"""
import argparse
import json
import math
import os
import sys
import threading
import zlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (стабы /api/* — reuse)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

PORT = 8907
BASE = "http://127.0.0.1:%d/web/index.html" % PORT
# Mutable-состояние для инспекции в обычном браузере (cmd_serve): tier-оверрайд
# через `GET /__tier?a|b|c|auto` (аналог env UI_GLASS_TIER_OVERRIDE).
_STATE = {"tier": None}
EVIDENCE = os.path.join(REPO, "plans", "features", "soul-1", "evidence",
                        "glass-tiera")
# Префикс имён артефактов (--prefix): позволяет снять evidence ПОСЛЕ правки
# (`_strong_*`), не перезаписывая замеры предыдущего кандидата, которые
# параллельно читает ревью. По умолчанию пустой (поведение прежнее).
EVID_PREFIX = ""
BG_SEED = 424242

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
  MainButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
  HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
} };
"""

# Тест-мишень ПОД стеклянными поверхностями (харнесс-слой, не прод).
# TIERA-STRONG: период 48px (полосы 24px) вместо 24px — при периодической
# мишени 24px сдвиг >=12px алиасится (кросс-корреляция имеет боковые пики на
# +-период), а усиленная линза даёт 14-16px у кромок. Период 48px + поиск
# +-24px делают замер однозначным до 24px.
TARGET_JS = """
(() => {
  const id = 'gl-measure-target';
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('div');
    el.id = id;
    document.body.appendChild(el);
  }
  el.setAttribute('aria-hidden', 'true');
  el.style.cssText = 'position:fixed;inset:0;z-index:0;pointer-events:none;' +
    'background:repeating-linear-gradient(90deg,' +
    'rgba(4,6,12,0) 0 24px, rgba(236,246,255,0.95) 24px 48px), #05070d';
  return true;
})()
"""

# Усиленная мишень для поверхностей ЗА скримом (модалки: дим .5 + стекло .5 →
# мишень видна ~25%): белые полосы 255 на чёрном, период 48px.
TARGET_JS_BRIGHT = """
(() => {
  const id = 'gl-measure-target';
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('div');
    el.id = id;
    document.body.appendChild(el);
  }
  el.setAttribute('aria-hidden', 'true');
  el.style.cssText = 'position:fixed;inset:0;z-index:0;pointer-events:none;' +
    'background:repeating-linear-gradient(90deg,' +
    'rgba(0,0,0,1) 0 24px, rgba(255,255,255,1) 24px 48px), #000';
  return true;
})()
"""

FREEZE_JS = """
(() => {
  const out = { paused: false, mode: null, seed: null };
  try {
    const pb = window.__PolygonBackground;
    if (pb && typeof pb.pause === 'function') {
      pb.pause();
      out.paused = true;
      if (typeof pb.mode === 'function') out.mode = pb.mode();
      const d = typeof pb.getDiagnostics === 'function' ? pb.getDiagnostics() : null;
      if (d) out.seed = d.sceneSeed != null ? d.sceneSeed : null;
    }
  } catch (e) { out.error = String(e); }
  return out;
})()
"""

SURFACE_PROBE_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  return {
    x: Math.round(r.x * 10) / 10, y: Math.round(r.y * 10) / 10,
    w: Math.round(r.width * 10) / 10, h: Math.round(r.height * 10) / 10,
    tier: el.getAttribute('data-glass-tier'),
    declared: el.getAttribute('data-glass'),
    reason: el.getAttribute('data-glass-reason'),
    downgraded: el.getAttribute('data-glass-downgraded'),
    nested: el.getAttribute('data-glass-nested'),
    bf: (cs.backdropFilter || cs.webkitBackdropFilter || 'none').slice(0, 130),
    inlineBf: (el.style.backdropFilter || '').slice(0, 130),
    bg: cs.backgroundColor,
  };
}
"""

ISOLATE_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  // Поверхность целиком в экране (мишень fixed — позиция фона не зависит от
  // скролла; ON и OFF скроллятся одинаково).
  try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) {}
  // Изоляция оптики: контент поверхности (дети) скрыт на время пиксельного
  // замера — состояние ОДИНАКОВО в ON и OFF прогонах.
  for (const ch of Array.from(el.children)) {
    ch.style.setProperty('visibility', 'hidden', 'important');
  }
  let r = el.getBoundingClientRect();
  if (r.height < 48) {
    el.style.setProperty('min-height', '48px', 'important');
    r = el.getBoundingClientRect();
  }
  const cs = getComputedStyle(el);
  return {
    x: r.x, y: r.y, w: r.width, h: r.height,
    tier: el.getAttribute('data-glass-tier'),
    declared: el.getAttribute('data-glass'),
    reason: el.getAttribute('data-glass-reason'),
    bg: cs.backgroundColor,
    bf: (cs.backdropFilter || cs.webkitBackdropFilter || 'none').slice(0, 130),
    inlineBf: (el.style.backdropFilter || '').slice(0, 130),
  };
}
"""

LENS_ATTRS_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const bf = el.style.backdropFilter || getComputedStyle(el).backdropFilter || '';
  const m = /url\\("#?([\\w-]+)"?\\)/.exec(bf);
  const out = { filter: m ? m[1] : null, bf: bf.slice(0, 110),
                map: null, scale: null,
                pool: document.querySelectorAll('.lg-filter-defs filter').length };
  if (m) {
    const f = document.getElementById(m[1]);
    if (f) {
      const fe = f.querySelector('feImage');
      const dm = f.querySelector('feDisplacementMap');
      out.map = fe ? { w: fe.getAttribute('width'), h: fe.getAttribute('height') } : null;
      out.scale = dm ? dm.getAttribute('scale') : null;
    }
  }
  return out;
}
"""

PICK_JS = """
(sel) => {
  // Детерминированный выбор ИЗМЕРЯЕМОЙ поверхности: первый видимый узел
  // селектора с достаточным размером (мелкие/скрытые табы не подходят).
  const cands = Array.from(document.querySelectorAll(sel));
  let pick = null, info = [];
  for (const el of cands) {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const vis = cs.display !== 'none' && cs.visibility !== 'hidden'
      && r.width > 0 && r.height > 0;
    info.push({ w: Math.round(r.width), h: Math.round(r.height), vis });
    if (!pick && vis && r.width >= 200 && r.height >= 80) pick = el;
  }
  if (!pick) return { picked: false, cands: cands.length, info: info.slice(0, 6) };
  document.querySelectorAll('[data-gl-measure]').forEach((n) =>
    n.removeAttribute('data-gl-measure'));
  pick.setAttribute('data-gl-measure', '1');
  const r = pick.getBoundingClientRect();
  return { picked: true, cands: cands.length, w: Math.round(r.width),
           h: Math.round(r.height), cls: (pick.className || '').toString().slice(0, 60) };
}
"""

MEASURE_SEL = '[data-gl-measure="1"]'

DELENS_JS = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  // Контроль изоляции линзы: та ЖЕ поверхность/материал/alpha, у которой из
  // inline backdrop-filter убран только url(#…) — разница картинок даёт
  // чистый вклад displacement (без разницы blur/alpha между tier A и B).
  const targets = [el];
  const child = el.querySelector('.lg-panel__backdrop');
  if (child) targets.push(child);
  for (const t of targets) {
    const bf = t.style.backdropFilter || t.style.webkitBackdropFilter || '';
    if (!bf) continue;
    const bare = bf.replace(/\\s*url\\([^)]*\\)/g, '').trim();
    t.style.setProperty('-webkit-backdrop-filter', bare);
    t.style.setProperty('backdrop-filter', bare);
  }
  const cs = getComputedStyle(el);
  return { bf: (cs.backdropFilter || cs.webkitBackdropFilter || 'none').slice(0, 130),
           inlineBf: (el.style.backdropFilter || '').slice(0, 130) };
}
"""


INVENTORY_JS = """
() => {
  const sel = '[data-glass], .card, .module-card, .glass-panel, .hub-card,' +
    ' .prov-block, .modal-card, .scope-panel, .sticky-save, .lg-mini-lens';
  const nodes = Array.from(document.querySelectorAll(sel));
  const byTier = {}, byClass = {}, rows = [];
  let lens = 0, blurOnly = 0, none = 0;
  for (const el of nodes) {
    const cs = getComputedStyle(el);
    const bf = (el.style.backdropFilter || cs.backdropFilter ||
      cs.webkitBackdropFilter || 'none');
    const t = el.getAttribute('data-glass-tier') || 'none';
    byTier[t] = (byTier[t] || 0) + 1;
    const cls = (el.className || '').toString().split(/\\s+/)
      .filter(c => /card|panel|block|modal|shell|hub|prov|sticky|lens/.test(c))
      .join('.');
    byClass[cls || '(none)'] = (byClass[cls || '(none)'] || 0) + 1;
    if (/url\\(/.test(bf)) lens++;
    else if (bf !== 'none' && bf !== '') blurOnly++;
    else none++;
    let anc = el.parentElement, ancCls = null, depth = 0;
    while (anc && depth < 40) {
      const acs = getComputedStyle(anc);
      if ((acs.backdropFilter || acs.webkitBackdropFilter || 'none') !== 'none') {
        ancCls = (anc.className || '').toString().slice(0, 34);
        break;
      }
      anc = anc.parentElement; depth++;
    }
    const r = el.getBoundingClientRect();
    rows.push({ cls: cls || '(none)', declared: el.getAttribute('data-glass'),
                tier: t, reason: el.getAttribute('data-glass-reason'),
                bf: bf.slice(0, 54), bg: cs.backgroundColor,
                w: Math.round(r.width), h: Math.round(r.height),
                nestedInGlass: ancCls });
  }
  return { count: nodes.length, byTier, lens, blurOnly, none,
           byClass: Object.entries(byClass).sort((a, b) => b[1] - a[1])
             .slice(0, 14), rows: rows.slice(0, 70) };
}
"""


# ═══════════════════════════ PNG (чистый stdlib) ═══════════════════════════


def decode_png(buf):
    if buf[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not png")
    pos, idat = 8, []
    w = h = bd = ct = il = 0
    while pos < len(buf):
        ln = int.from_bytes(buf[pos:pos + 4], "big")
        typ = buf[pos + 4:pos + 8]
        data = buf[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w = int.from_bytes(data[0:4], "big")
            h = int.from_bytes(data[4:8], "big")
            bd = data[8]
            ct = data[9]
            il = data[12]
        elif typ == b"IDAT":
            idat.append(data)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if bd != 8 or il != 0 or ct not in (2, 6):
        raise ValueError("unsupported png ct=%s bd=%s il=%s" % (ct, bd, il))
    bpp = 4 if ct == 6 else 3
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        p += 1
        row = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for x in range(bpp, stride):
                row[x] = (row[x] + row[x - bpp]) & 0xFF
        elif ft == 2:
            for x in range(stride):
                row[x] = (row[x] + prev[x]) & 0xFF
        elif ft == 3:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ft == 4:
            for x in range(stride):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                row[x] = (row[x] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = row
        prev = row
    return {"w": w, "h": h, "bpp": bpp, "data": bytes(out)}


def lum_at(img, x, y):
    i = (y * img["w"] + x) * img["bpp"]
    d = img["data"]
    return 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]


def column_profile(img, x0, x1, y0, y1):
    prof = []
    for x in range(x0, x1):
        s = 0.0
        for y in range(y0, y1):
            s += lum_at(img, x, y)
        prof.append(s / (y1 - y0))
    return prof


def local_shift(img_a, img_b, x0, y0, win, max_shift):
    """Сдвиг мишени в A относительно B (A(x) ≈ B(x - shift))."""
    prof_a = column_profile(img_a, x0, x0 + win, y0, y0 + win)
    bc = column_profile(img_b, x0 - max_shift, x0 + win + max_shift, y0,
                        y0 + win)
    mean_a = sum(prof_a) / win
    mean_b = sum(bc) / len(bc)
    best = (0, -2.0)
    for s in range(-max_shift, max_shift + 1):
        num = den_a = den_b = 0.0
        for k in range(win):
            a = prof_a[k] - mean_a
            b = bc[k + max_shift - s] - mean_b
            num += a * b
            den_a += a * a
            den_b += b * b
        sc = num / ((den_a * den_b) ** 0.5 + 1e-6)
        if sc > best[1]:
            best = (s, sc)
    return best


def shift_profile(img_on, img_off, box, dpr, win=48, max_shift=24, step=8,
                  y_css=None):
    """Профиль сдвига мишени по X внутри поверхности (CSS px).

    TIERA-STRONG: окно 48px и поиск +-24px (было 32/+-12) — при усиленной
    линзе (14-16px у кромки) прежний диапазон насыщался и замер переставал
    что-либо показывать.
    """
    xs, shifts, scores = [], [], []
    x_from = int((box["x"] + 2) * dpr)
    x_to = int((box["x"] + box["w"] - 2) * dpr)
    win_px = int(win * dpr)
    max_px = int(max_shift * dpr)
    step_px = max(1, int(step * dpr))
    if y_css is None:
        y_css = box["y"] + box["h"] * 0.5
    y0 = int((y_css - win / 2) * dpr)
    for x0 in range(x_from, max(x_from + 1, x_to - win_px), step_px):
        s, sc = local_shift(img_on, img_off, x0, y0, win_px, max_px)
        xs.append(round((x0 + win_px / 2.0) / dpr - box["x"], 1))
        shifts.append(round(s / dpr, 2))
        scores.append(round(sc, 3))
    return {"xs": xs, "shifts": shifts, "scores": scores,
            "y_css": round(y_css, 1)}


def _median(vals):
    if not vals:
        return 0.0
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def summarize(profile, box, min_corr=0.6, edge_band=40.0):
    """edge/center-сдвиги мишени внутри поверхности (CSS px).

    edge — окна в пределах `edge_band` от левой/правой кромки (зона линзы;
    окно 48px → первый центр в 26px от кромки, поэтому 40, а не 24);
    center — центральные 40% (по карте линзы неподвижны);
    max — максимум |сдвига|, med — медиана (устойчива к одиночным выбросам).
    """
    edge, center = [], []
    for x, s, sc in zip(profile["xs"], profile["shifts"], profile["scores"]):
        if sc < min_corr:
            continue
        if min(x, box["w"] - x) <= edge_band:
            edge.append(abs(s))
        if box["w"] * 0.3 <= x <= box["w"] * 0.7:
            center.append(abs(s))
    return {"edge_max": round(max(edge, default=0.0), 2),
            "edge_med": round(_median(edge), 2), "edge_n": len(edge),
            "center_max": round(max(center, default=0.0), 2),
            "center_med": round(_median(center), 2), "center_n": len(center)}


def pattern_energy(img, box, dpr, x_css=None, period=48.0, win=64, y_css=None):
    """Амплитуда мишени (период 48px) внутри поверхности / вне её.

    ratio < 0.15 → мишень за поверхностью почти не видна (плотная подложка),
    численный замер неприменим (сообщаем честно).
    """
    if y_css is None:
        y_css = box["y"] + box["h"] * 0.5

    def amp(x_c):
        w = int(win * dpr)
        x0 = max(0, min(img["w"] - w, int(x_c * dpr)))
        y0 = max(0, min(img["h"] - w, int((y_css - win / 2) * dpr)))
        if w < 8 or x0 < 0 or y0 < 0:
            return 0.0
        prof = column_profile(img, x0, x0 + w, y0, y0 + w)
        n = max(1, len(prof))
        mean = sum(prof) / n
        per = max(2.0, period * dpr)
        re = im = 0.0
        for k, v in enumerate(prof):
            ph = 2 * math.pi * k / per
            re += (v - mean) * math.cos(ph)
            im += (v - mean) * math.sin(ph)
        return 2.0 * math.hypot(re, im) / n

    inside_css = box["x"] + box["w"] * 0.5
    outside_css = box["x"] + box["w"] + max(30.0, period * 1.5)
    inside = amp(inside_css)
    outside = amp(outside_css)
    return {"inside": round(inside, 2), "outside": round(outside, 2),
            "ratio": round(inside / outside, 3) if outside > 1e-6 else None}


# ═══════════════════════════ сервер / страница ════════════════════════════


def make_handler(webroot):
    class _H(SimpleHTTPRequestHandler):
        def _api(self):
            """Стабы /api/* для инспекции в ОБЫЧНОМ браузере (см. cmd_serve)."""
            p = self.path.split("?")[0]
            if p.startswith("/__tier"):
                val = (self.path.split("?")[1].split("=")[-1]
                       if "?" in self.path else "auto")
                _STATE["tier"] = None if val in ("", "auto") else val[:1]
                body = json.dumps({"tier": _STATE["tier"]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            payload = (me_payload(_STATE["tier"]) if p.endswith("/api/me")
                       else M._stub_for(p))
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            p = self.path.split("?")[0]
            # REVIEW-TIERA (неблок. находка 1): `/__tier` обещан docstring'ом
            # cmd_serve, но роутился в статику → переключатель tier не работал.
            if p == "/__tier":
                self._api()
                return
            if p.startswith("/api/"):
                self._api()
                return
            if p == "/static/vendor/telegram-web-app.js":
                # В обычном браузере нет Playwright route-mock'а: отдаём тот же
                # TMA-стаб, что и харнесс (иначе app.js уходит в authLocked).
                body = SDK_STUB.encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return SimpleHTTPRequestHandler.do_GET(self)

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

        def log_message(self, *a):
            pass
    return _H


def serve(port, webroot):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(webroot))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def me_payload(override):
    me = json.loads(json.dumps(M.ME_JSON))
    flags = dict(me["ui_flags"])
    flags["UI_POLYGON_BG_ENABLED"] = True
    if override:
        flags["UI_GLASS_TIER_OVERRIDE"] = override
    me["ui_flags"] = flags
    return me


def make_api_route(me):
    """Playwright route-handler для /api/** (одно-аргументная форма)."""
    def _handler(route):
        p = route.request.url.split("?")[0]
        payload = me if p.endswith("/api/me") else M._stub_for(
            route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload, ensure_ascii=False))
    return _handler


def launch(p, channel="chrome", headless=True, args=None):
    """Реальный Chromium-клиент (channel=chrome) — как Telegram WebView/TMA.

    probe `glass-probe.js` определяет engine по capability-сигналу
    `window.chrome`; у Playwright-сборки chromium его нет → честный
    `engine-unproven-backdrop-url` (Tier B). Замер ведём в реальном Chrome
    (window.chrome есть, как в Blink WebView/Android TMA).
    """
    kw = {"headless": headless}
    if channel:
        kw["channel"] = channel
    if args:
        kw["args"] = args
    return p.chromium.launch(**kw)


def open_page(browser, width, height, override, dpr=1, route="#/", tma=True,
              pre_js=None, bright_target=False, settle_ms=700):
    ctx = browser.new_context(viewport={"width": width, "height": height},
                              is_mobile=width < 768, has_touch=width < 768,
                              device_scale_factor=dpr)
    me = me_payload(override)
    ctx.route("**/api/**", make_api_route(me))
    ctx.route("**/static/vendor/telegram-web-app.js",
              lambda r: r.fulfill(status=200,
                                  content_type="application/javascript",
                                  body=SDK_STUB))
    if tma:
        ctx.add_init_script("window.__TMA_MOCK__ = 1;")
    page = ctx.new_page()
    page.set_default_timeout(9000)
    errors = []
    page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)[:200]))
    page.on("console", lambda m: errors.append("console: " + m.text[:200])
            if m.type == "error" else None)
    page.goto("%s?bgseed=%d%s" % (BASE, BG_SEED, route), wait_until="load")
    page.wait_for_selector(".app-shell", state="visible")
    page.wait_for_timeout(1300)
    if pre_js:
        try:
            pre = page.evaluate(pre_js)
        except Exception as exc:  # noqa: BLE001
            errors.append("pre: " + str(exc)[:160])
            pre = {"error": str(exc)[:120]}
        page.wait_for_timeout(settle_ms)
    else:
        pre = None
    freeze = page.evaluate(FREEZE_JS)
    page.evaluate(TARGET_JS_BRIGHT if bright_target else TARGET_JS)
    page.wait_for_timeout(250)
    return ctx, page, freeze, errors, pre


def capture_state(page, sel, dpr, width, height, label, tag, save, pick=False):
    """Один снимок состояния поверхности: видимый PNG + изолированный кроп."""
    rec = {}
    if pick:
        rec["pick"] = page.evaluate(PICK_JS, sel)
        if not rec["pick"].get("picked"):
            rec["not_found"] = True
            return rec, None
        sel = MEASURE_SEL
    vis = page.evaluate(SURFACE_PROBE_JS, sel)
    rec["box"] = vis
    rec["lens"] = page.evaluate(LENS_ATTRS_JS, sel)
    if save:
        os.makedirs(EVIDENCE, exist_ok=True)
        pad = 24
        x0 = max(0, vis["x"] - pad)
        y0 = max(0, vis["y"] - pad)
        clip = {"x": x0, "y": y0,
                "width": min(vis["w"] + 2 * pad, width - x0),
                "height": min(vis["h"] + 2 * pad, height - y0)}
        if clip["width"] > 8 and clip["height"] > 8:
            path = os.path.join(EVIDENCE, "%s%s-%s-%d.png"
                                % (EVID_PREFIX, label, tag, width))
            with open(path, "wb") as fh:
                fh.write(page.screenshot(clip=clip))
            rec["vis_png"] = os.path.relpath(path, REPO).replace("\\", "/")
    box = page.evaluate(ISOLATE_JS, sel)
    if not box or box["w"] < 60 or box["h"] < 30:
        rec["isolated_missing"] = box
        return rec, None
    y_lo = box["y"] + 20
    y_hi = min(box["y"] + box["h"] - 20, height - 20)
    if y_hi - y_lo < 16:
        rec["not_in_viewport"] = {"y": box["y"], "h": box["h"], "vh": height}
        return rec, None
    y_css = 0.5 * (y_lo + y_hi)
    rec["iso_box"] = box
    rec["y_css"] = round(y_css, 1)
    cy = int(y_css * dpr)
    pad = 36
    x0 = max(0, box["x"] - pad)
    clip = {"x": x0, "y": max(0, cy - pad),
            "width": min(box["w"] + 2 * pad, width - x0),
            "height": 2 * pad}
    clip["height"] = min(clip["height"], height - clip["y"])
    if clip["width"] < 24 or clip["height"] < 24:
        rec["clip_invalid"] = clip
        return rec, None
    raw = page.screenshot(clip=clip)
    if save:
        path = os.path.join(EVIDENCE, "%s%s-%s-%d-iso.png"
                            % (EVID_PREFIX, label, tag, width))
        with open(path, "wb") as fh:
            fh.write(raw)
        rec["iso_png"] = os.path.relpath(path, REPO).replace("\\", "/")
    return rec, {"raw": raw, "clip": clip, "box": box, "y_css": y_css}


def on_off_pair(browser, width, height, route, sel, dpr=1, label=None,
                save=False, pre_js=None):
    """Три состояния на ОДНОЙ замороженной позиции фона (seed фиксирован):

      A       — tier A (линза url(#lg-lens) + blur);
      B       — честный Tier B фолбэк (override=b);
      A-nolens— тот же tier A материал БЕЗ url() (контроль изоляции линзы).

    metric_lens = A vs A-nolens — численное доказательство, что сдвиг даёт
    именно линза (у blur/alpha разницы нет);
    metric_ab   = A vs B — что видит пользователь с фолбэком.
    """
    rec = {"label": label or sel, "route": route, "sel": sel, "width": width}
    got = {}
    # A + A-nolens (один контекст/страница).
    bright = bool(pre_js)
    ctx, page, freeze, errors, pre = open_page(browser, width, height, "a",
                                               dpr=dpr, route=route,
                                               pre_js=pre_js,
                                               bright_target=bright)
    rec["a"] = {"freeze": freeze, "errors": errors[:3], "pre": pre}
    rec_a, shot_a = capture_state(page, sel, dpr, width, height,
                                  label or "surface", "on", save, pick=True)
    rec["a"].update(rec_a)
    if shot_a:
        # Контроль изоляции линзы: снимаем только url(#…) (материал/alpha те же).
        # Покадрово проверяем, что линза действительно снята: app.js может
        # переприменить inline-фильтр на DOM-мутациях (модалка догружает данные),
        # поэтому делаем до 3 попыток «сняли → сразу снимок → проверили».
        for attempt in range(3):
            rec["a"]["delens"] = page.evaluate(DELENS_JS, MEASURE_SEL)
            raw_nl = page.screenshot(clip=shot_a["clip"])
            back = page.evaluate(LENS_ATTRS_JS, MEASURE_SEL) or {}
            if "url(" not in (back.get("bf") or ""):
                got["nolens"] = {"raw": raw_nl, "clip": shot_a["clip"],
                                 "box": shot_a["box"],
                                 "y_css": shot_a["y_css"]}
                rec["a"]["nolens_attempts"] = attempt + 1
                break
            page.wait_for_timeout(120)
        if save and "nolens" in got:
            path = os.path.join(EVIDENCE, "%s%s-%s-%d-iso.png"
                                % (EVID_PREFIX, label or "surface",
                                   "on-nolens", width))
            with open(path, "wb") as fh:
                fh.write(got["nolens"]["raw"])
            rec["a"]["nolens_png"] = os.path.relpath(path, REPO).replace(
                "\\", "/")
    ctx.close()
    # B (фолбэк).
    ctx, page, freeze, errors, pre_b = open_page(browser, width, height, "b",
                                                 dpr=dpr, route=route,
                                                 pre_js=pre_js,
                                                 bright_target=bright)
    rec["b"] = {"freeze": freeze, "errors": errors[:3], "pre": pre_b}
    rec_b, shot_b = capture_state(page, sel, dpr, width, height,
                                  label or "surface", "off", save, pick=True)
    rec["b"].update(rec_b)
    ctx.close()
    if shot_b:
        got["b"] = shot_b
    if shot_a:
        got["a"] = shot_a
    rec["pre"] = (rec.get("a", {}).get("pre") or rec.get("b", {}).get("pre"))
    if "a" not in got or ("b" not in got and "nolens" not in got):
        rec["metric"] = {"error": "surface-missing"}
        rec["ok"] = False
        return rec

    def pair(base_key, cmp_key):
        a = decode_png(got["a"]["raw"])
        c = decode_png(got[cmp_key]["raw"])
        clip = got["a"]["clip"]
        box = dict(got["a"]["box"])
        box["x"] -= clip["x"]
        box["y"] -= clip["y"]
        y_css = got["a"]["y_css"] - clip["y"]
        prof = shift_profile(a, c, box, dpr, y_css=y_css)
        # За скримом (модалки) мишень ослаблена димом ~4×: допускаем окна с
        # меньшей корреляцией (0.45 против 0.6), иначе замер «слепой».
        mc = 0.45 if bright else 0.6
        return {"profile": prof, "metric": summarize(prof, box, min_corr=mc),
                "pattern_base": pattern_energy(a, box, dpr, y_css=y_css),
                "pattern_cmp": pattern_energy(c, box, dpr, y_css=y_css)}

    if "nolens" in got:
        m = pair("a", "nolens")
        rec["profile"] = m["profile"]
        rec["metric_lens"] = m["metric"]
        rec["pattern_on"] = m["pattern_base"]
        rec["pattern_nolens"] = m["pattern_cmp"]
    if "b" in got:
        m2 = pair("a", "b")
        rec["profile_ab"] = m2["profile"]
        rec["metric_ab"] = m2["metric"]
        rec["pattern_off"] = m2["pattern_cmp"]
    key = "metric_lens" if "metric_lens" in rec else "metric_ab"
    mm = rec.get(key, {})
    pat = max(((rec.get("pattern_on") or {}).get("ratio") or 0),
              ((rec.get("pattern_nolens") or {}).get("ratio") or 0),
              ((rec.get("pattern_off") or {}).get("ratio") or 0))
    rec["metric"] = mm
    rec["ok"] = (mm.get("edge_max", 0) >= 3.0 and mm.get("edge_med", 0) >= 1.0
                 and mm.get("center_max", 9) <= 1.5 and pat >= 0.15)
    return rec


# ═══════════════════════════ сценарии ════════════════════════════════════

# Поверхности реальных страниц (владелец: Status/Modules/Analytics/Settings/
# модалка/навигация). skip_mobile=True — поверхность существует только на
# desktop (sidebar по §4 — строго ≥1200px).
SURFACES = [
    ("status-hero", "#/", '.status-hero', False, None),
    ("status-card", "#/", 'main .card', False, None),
    ("status-bigcard", "#/", '.card.intel-card', False, None),
    ("modules-card", "#/modules", '.module-card', False, None),
    ("analytics-card", "#/oversight", 'main .card', False, None),
    ("settings-card", "#/ai/llm", '.prov-block.card', False, None),
    ("sidebar", "#/", '.app-sidebar', True, None),
    ("header", "#/", 'header.header-sticky', False, None),
    # Модалка реального UI: «Редактировать» в списке ролей (#/access/roles) →
    # `.modal-backdrop > .modal-card` (скрим только затемняет; рефракцию несёт
    # карточка модалки, скрим больше не блюрит — см. HOTFIX-TIERA в app.css).
    ("modal-card", "#/access/roles", '.modal-card', False, None),
]

# Пред-шаг открытия модалки: сначала БОЕВОЙ путь (клик по «Стоп» на Status →
# подтверждение), фолбэк — состояние приложения (confirmAction='stop', тот же
# v-if и та же разметка). Возвращаем, каким путём модалка открылась.
OPEN_PRE_JS = {
    "modal-card": """() => {
      const btn = Array.from(document.querySelectorAll('button'))
        .find((b) => b.textContent.indexOf('Редактировать') >= 0);
      if (btn) btn.click();
      return { how: btn ? 'click-edit-role' : 'none',
               modal: !!document.querySelector('.modal-card') };
    }""",
}


def cmd_inventory(args):
    from playwright.sync_api import sync_playwright
    serve(PORT, os.path.join(REPO, "web"))
    out = {}
    with sync_playwright() as p:
        browser = launch(p, args.channel)
        for width, height in ((1440, 900), (390, 844)):
            for route in ("#/", "#/oversight", "#/modules", "#/ai/llm"):
                ctx, page, freeze, errors, _pre = open_page(browser, width,
                                                            height, None,
                                                            route=route)
                key = "%dx%d %s" % (width, height, route)
                out[key] = {"tiers": page.evaluate(INVENTORY_JS),
                            "lens": page.evaluate(LENS_ATTRS_JS, 'main .card'),
                            "freeze": freeze, "errors": errors[:2],
                            "diag": page.evaluate(
                                "() => { const a = document.querySelector('#app');"
                                " return a && a.__vue_app__ ? null : null; }")}
                ctx.close()
                t = out[key]["tiers"]
                print("[inventory]", key, "count=%d" % t["count"],
                      t["byTier"], "lens=%d" % t["lens"],
                      "blur-only=%d" % t["blurOnly"], "none=%d" % t["none"],
                      "errors=%s" % errors[:1])
            browser.close()
            browser = launch(p, args.channel)
        browser.close()
    os.makedirs(EVIDENCE, exist_ok=True)
    path = args.out or os.path.join(EVIDENCE, "inventory.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("[inventory] ->", path)
    return out


def cmd_verify(args):
    from playwright.sync_api import sync_playwright
    serve(PORT, os.path.join(REPO, "web"))
    results, checks = [], {}
    with sync_playwright() as p:
        browser = launch(p, args.channel)
        for name, route, sel, skip_mobile, _pre in SURFACES:
            for width, height in ((1440, 900), (390, 844)):
                if width < 768 and skip_mobile:
                    continue
                rec = on_off_pair(browser, width, height, route, sel,
                                  dpr=args.dpr, label=name, save=True,
                                  pre_js=OPEN_PRE_JS.get(name))
                results.append(rec)
                key = "%s@%d" % (name, width)
                ml = rec.get("metric_lens", {}) or {}
                ma = rec.get("metric_ab", {}) or {}
                po = rec.get("pattern_off") or {}
                pat = max(((rec.get("pattern_on") or {}).get("ratio") or 0),
                          ((rec.get("pattern_nolens") or {}).get("ratio") or 0))
                # Мишень «видна» только если её амплитуда выше шума: под
                # скримом модалок/плотной подложкой shell сигнал падает до ~0.
                amp = max(((rec.get("pattern_on") or {}).get("inside") or 0),
                          ((rec.get("pattern_nolens") or {}).get("inside") or 0))
                scrim = bool(OPEN_PRE_JS.get(name))
                checks[key + ":lens_edge_refraction"] = ml.get("edge_max", 0) >= 3.0
                checks[key + ":lens_edge_consistent"] = ml.get("edge_med", 0) >= 1.0
                checks[key + ":lens_center_static"] = ml.get("center_max", 9) <= 1.5
                if scrim:
                    # За скримом мишень ослаблена ~4× димом: критерий «видимости
                    # мишени» здесь не информативен (7-8 px сдвиг при этом
                    # измеряется кросс-корреляцией) — фиксируем значение, не гейт.
                    rec["pattern_note"] = (
                        "модалка за скримом: ratio=%.3f amp=%.2f (информационно)"
                        % (pat, amp))
                else:
                    checks[key + ":pattern_visible"] = (pat >= 0.15 and amp >= 1.0)
                if ma:
                    # A↔B сравнение осмысленно только когда мишень видна и в
                    # фолбэке (плотная подложка B скрывает фон → n/a, не fail).
                    if (po.get("ratio") or 0) >= 0.30 and (po.get("inside") or 0) >= 3.0:
                        checks[key + ":ab_edge_refraction"] = ma.get("edge_max", 0) >= 3.0
                    else:
                        rec["ab_check"] = ("n/a: фон за фолбэком B практически не "
                                           "виден (ratio=%.3f, amp=%.2f)"
                                           % (po.get("ratio") or 0,
                                              po.get("inside") or 0))
                print("[verify]", key,
                      "a=%s b=%s" % (
                          (rec.get("a", {}).get("iso_box") or {}).get("tier"),
                          (rec.get("b", {}).get("iso_box") or {}).get("tier")),
                      "lens=%s" % json.dumps(ml, ensure_ascii=False),
                      "ab=%s" % json.dumps(ma, ensure_ascii=False),
                      "pat=%s" % pat)
        browser.close()
    summary = {"pass": sum(1 for v in checks.values() if v),
               "fail": sum(1 for v in checks.values() if not v)}
    os.makedirs(EVIDENCE, exist_ok=True)
    path = args.out or os.path.join(EVIDENCE, "verify.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"checks": checks, "summary": summary, "results": results},
                  fh, ensure_ascii=False, indent=1)
    print("[verify] %d pass / %d fail -> %s"
          % (summary["pass"], summary["fail"], path))
    for k, v in checks.items():
        if not v:
            print("   FAIL:", k)
    return summary


PERF_JS_INIT = """
() => {
  window.__FT = { frames: [], longtasks: [] };
  let last = performance.now();
  const tick = () => {
    const now = performance.now();
    window.__FT.frames.push(now - last); last = now;
    window.__FT.raf = requestAnimationFrame(tick);
  };
  window.__FT.raf = requestAnimationFrame(tick);
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries())
        window.__FT.longtasks.push(Math.round(e.duration));
    }).observe({ entryTypes: ['longtask'] });
  } catch (e) {}
  return true;
}
"""

PERF_JS_READ = """
() => {
  const f = window.__FT.frames.slice(3).sort((a, b) => a - b);
  const lt = window.__FT.longtasks;
  const pct = (q) => f.length ? f[Math.min(f.length - 1,
    Math.floor(q * f.length))] : null;
  const r = (v) => (v == null ? null : Math.round(v * 100) / 100);
  return { frames: f.length, p50: r(pct(0.5)), p95: r(pct(0.95)),
           worst: r(f.length ? f[f.length - 1] : null),
           longtasks: lt.length, longtaskMax: lt.length ? Math.max(...lt) : 0,
           longtaskSum: lt.reduce((a, b) => a + b, 0),
           lensNodes: document.querySelectorAll('[data-glass-tier="a"]').length,
           glassNodes: document.querySelectorAll('[data-glass-tier]').length,
           filters: document.querySelectorAll('.lg-filter-defs filter').length };
}
"""


def _cdp_metrics(session):
    raw = session.send("Performance.getMetrics")
    out = {}
    for m in raw.get("metrics", []):
        out[m["name"]] = m["value"]
    return out


def cmd_perf(args):
    from playwright.sync_api import sync_playwright
    serve(PORT, os.path.join(REPO, "web"))
    out = {"headed": bool(args.headed)}
    with sync_playwright() as p:
        browser = launch(p, args.channel, headless=not args.headed,
                         args=["--enable-gpu-rasterization"])
        for route in ("#/", "#/modules", "#/ai/llm"):
            for tag, override in (("tierA", "a"), ("tierB", "b")):
                ctx, page, freeze, errors, _pre = open_page(browser, args.width,
                                                            args.height,
                                                            override,
                                                            route=route)
                session = ctx.new_cdp_session(page)
                session.send("Performance.enable")
                page.evaluate(PERF_JS_INIT)
                page.wait_for_timeout(600)
                main_h = page.evaluate(
                    "() => { const m = document.querySelector('main');"
                    " return m ? m.scrollHeight : 0; }")
                m0 = _cdp_metrics(session)
                t0 = page.evaluate("() => performance.now()")
                for i in range(10):
                    page.evaluate(
                        "(y) => { const m = document.querySelector('main');"
                        " if (m) m.scrollTop = y; }",
                        int(main_h * (i + 1) / 12))
                    page.wait_for_timeout(220)
                    page.mouse.wheel(0, 340)
                    page.wait_for_timeout(220)
                t1 = page.evaluate("() => performance.now()")
                m1 = _cdp_metrics(session)
                data = page.evaluate(PERF_JS_READ)
                wall = (t1 - t0) / 1000.0
                data["wall_s"] = round(wall, 2)
                for k in ("TaskDuration", "LayoutDuration",
                          "RecalcStyleDuration", "ScriptDuration",
                          "LayoutCount", "RecalcStyleCount"):
                    if k in m0 and k in m1:
                        dv = m1[k] - m0[k]
                        data[k] = round(dv, 3)
                        if k.endswith("Duration") and wall > 0:
                            data[k + "Pct"] = round(100.0 * dv / wall, 1)
                data["errors"] = errors[:2]
                data["freeze"] = freeze
                out["%s %s" % (route, tag)] = data
                print("[perf]", route, tag, json.dumps(data, ensure_ascii=False))
                ctx.close()
        browser.close()
    os.makedirs(EVIDENCE, exist_ok=True)
    path = args.out or os.path.join(EVIDENCE, "perf.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("[perf] ->", path)
    return out


DELENS_ALL_JS = """
() => {
  const nodes = Array.from(document.querySelectorAll('[data-glass-tier="a"]'));
  const targets = [];
  for (const el of nodes) {
    targets.push(el);
    const child = el.querySelector('.lg-panel__backdrop');
    if (child) targets.push(child);
  }
  let n = 0;
  for (const t of targets) {
    const bf = t.style.backdropFilter || t.style.webkitBackdropFilter || '';
    if (!bf) continue;
    const bare = bf.replace(/\\s*url\\([^)]*\\)/g, '').trim();
    t.style.setProperty('-webkit-backdrop-filter', bare);
    t.style.setProperty('backdrop-filter', bare);
    n++;
  }
  return n;
}
"""

BOXES_JS = """
() => Array.from(document.querySelectorAll('[data-glass-tier]')).map((el) => {
  const r = el.getBoundingClientRect();
  return { tier: el.getAttribute('data-glass-tier'),
           x: Math.round(r.x), y: Math.round(r.y),
           w: Math.round(r.width), h: Math.round(r.height),
           cls: (el.className || '').toString().split(' ')[0] };
}).filter((b) => b.w > 40 && b.h > 30 && b.y < innerHeight && b.y + b.h > 0)
"""


def cmd_shots(args):
    """Чистые визуальные скриншоты РЕАЛЬНОЙ страницы (без тест-мишени):
    Tier A vs Tier B на одной замороженной позиции полигонального фона.

    Это evidence «как видит владелец»: мишень-слой не добавляется, фон
    детерминирован (?bgseed) и заморожен (pause) — сравнимы 1:1.
    """
    from playwright.sync_api import sync_playwright
    serve(PORT, os.path.join(REPO, "web"))
    os.makedirs(EVIDENCE, exist_ok=True)
    out = {}
    routes = [("#/", "status"), ("#/oversight", "analytics"),
              ("#/modules", "modules"), ("#/ai/llm", "settings")]
    with sync_playwright() as p:
        browser = launch(p, args.channel)
        for route, name in routes:
            for width, height in ((1440, 900), (390, 844)):
                for tier in ("a", "b"):
                    ctx = browser.new_context(viewport={"width": width,
                                                        "height": height},
                                              is_mobile=width < 768,
                                              has_touch=width < 768)
                    ctx.route("**/api/**", make_api_route(me_payload(tier)))
                    ctx.route("**/static/vendor/telegram-web-app.js",
                              lambda r: r.fulfill(
                                  status=200,
                                  content_type="application/javascript",
                                  body=SDK_STUB))
                    page = ctx.new_page()
                    page.goto("%s?bgseed=%d%s" % (BASE, BG_SEED, route),
                              wait_until="load")
                    page.wait_for_selector(".app-shell", state="visible")
                    page.wait_for_timeout(1300)
                    page.evaluate(FREEZE_JS)
                    page.wait_for_timeout(250)
                    diag = page.evaluate("""
                    () => {
                      const nodes = Array.from(
                        document.querySelectorAll('[data-glass-tier]'));
                      const t = {};
                      for (const el of nodes) {
                        const k = el.getAttribute('data-glass-tier') || 'none';
                        t[k] = (t[k] || 0) + 1;
                      }
                      return { tiers: t, nodes: nodes.length,
                               lens: nodes.filter((el) =>
                                 /url\\(/.test(el.style.backdropFilter || ''))
                                 .length,
                               probe: window.__GlassProbe.cached() };
                    }
                    """)
                    boxes = page.evaluate(BOXES_JS)
                    path = os.path.join(EVIDENCE, "%sreal-%s-%s-%d.png"
                                        % (EVID_PREFIX, name, tier, width))
                    page.screenshot(path=path)
                    if tier == "a":
                        # Контроль видимости: тот же материал БЕЗ линзы
                        # (разница = чистый вклад displacement на РЕАЛЬНОМ фоне).
                        n = page.evaluate(DELENS_ALL_JS)
                        page.wait_for_timeout(200)
                        nl = os.path.join(EVIDENCE,
                                          "%sreal-%s-a-nolens-%d.png"
                                          % (EVID_PREFIX, name, width))
                        page.screenshot(path=nl)
                        out["%s@%d visual_nolens" % (name, width)] = {
                            "nodes_delensed": n}
                    out["%s@%d tier%s" % (name, width, tier)] = diag
                    out["%s@%d boxes tier%s" % (name, width, tier)] = boxes
                    print("[shots]", name, width, tier,
                          json.dumps(diag, ensure_ascii=False)[:220])
                    ctx.close()
        browser.close()
    path = args.out or os.path.join(EVIDENCE, "shots.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("[shots] ->", path)
    return out


def cmd_probe(args):
    from playwright.sync_api import sync_playwright
    serve(PORT, os.path.join(REPO, "web"))
    with sync_playwright() as p:
        browser = launch(p, args.channel)
        rec = on_off_pair(browser, args.width, args.height, args.route, args.sel,
                          dpr=args.dpr, label="probe", save=True)
        prof = rec.get("profile", {})
        states = {}
        for k in ("on", "off"):
            b = rec.get(k, {}).get("iso_box") or rec.get(k, {}).get("box")
            states[k] = ({kk: b.get(kk) for kk in
                          ("tier", "reason", "bf", "bg", "w", "h")}
                         if b else None)
        print(json.dumps({"sel": args.sel, "route": args.route,
                          "lens_on": rec.get("on", {}).get("lens"),
                          "states": states, "metric": rec.get("metric"),
                          "pattern_on": rec.get("pattern_on"),
                          "pattern_off": rec.get("pattern_off"),
                          "shifts": prof.get("shifts"), "xs": prof.get("xs"),
                          "ok": rec.get("ok")}, ensure_ascii=False))
        browser.close()


# Telegram WebView (Android TMA): реальный клиент = Blink WebView с window.chrome;
# iOS Telegram = WebKit (url() в backdrop-filter не рендерится, bug 245510).
UA_ANDROID_TMA = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36")
DPR_TMA = 2.625  # типичный DPR телефона в Telegram WebView (390 CSS px)


def _tma_context(browser, dsf):
    """Контекст Telegram-WebView (Android TMA): UA, mobile, touch, TMA SDK мок."""
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True,
                              device_scale_factor=dsf,
                              user_agent=UA_ANDROID_TMA)
    me = me_payload(None)
    ctx.route("**/api/**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(me if r.request.url.split("?")[0].endswith("/api/me")
                        else M._stub_for(r.request.url), ensure_ascii=False)))
    ctx.route("**/static/vendor/telegram-web-app.js", lambda r: r.fulfill(
        status=200, content_type="application/javascript", body=SDK_STUB))
    return ctx


def cmd_webview(args):
    """Контекст Telegram WebView (TMA-мок): Android TMA + честный фолбэк.

    Сценарии на РЕАЛЬНОЙ странице в WebView-подобном контексте:
      * chromium-TMA (window.chrome есть, как в Blink WebView) → Tier A и
        численно доказанная рефракция на Status-hero (dsf=1 для чистого
        пиксельного замера; dsf=2.625 — визуальный скриншот того же клиента);
      * WebKit-подобный клиент (window.chrome отсутствует → probe честно
        отказывает) → Tier B, НИ ОДНОЙ поверхности с url() в backdrop-filter
        (никакой имитации рефракции) + diagnostic reason на каждом узле.
    """
    from playwright.sync_api import sync_playwright
    serve(PORT, os.path.join(REPO, "web"))
    out = {}
    with sync_playwright() as p:
        browser = launch(p, args.channel)
        # 1) Android TMA, DPR телефона — визуальный артефакт + диагностика.
        ctx = _tma_context(browser, DPR_TMA)
        page = ctx.new_page()
        page.goto("%s?bgseed=%d#/" % (BASE, BG_SEED), wait_until="load")
        page.wait_for_selector(".app-shell", state="visible")
        page.wait_for_timeout(1500)
        page.evaluate("() => { const pb = window.__PolygonBackground;"
                      " if (pb && pb.pause) pb.pause(); }")
        page.wait_for_timeout(250)
        os.makedirs(EVIDENCE, exist_ok=True)
        with open(os.path.join(EVIDENCE, "%stma-android-390.png" % EVID_PREFIX),
                  "wb") as fh:
            fh.write(page.screenshot(full_page=False))
        out["android_tma_visual"] = {
            "probe": page.evaluate("() => window.__GlassProbe.cached()"),
            "tierA_nodes": page.evaluate(
                "() => document.querySelectorAll('[data-glass-tier=\"a\"]').length"),
            "lens_nodes": page.evaluate(
                "() => Array.from(document.querySelectorAll('[data-glass-tier]'))"
                ".filter((el) => /url\\(/.test(el.style.backdropFilter || '')).length"),
            "diag": page.evaluate("() => { const a = document.querySelector('#app');"
                                  " return a && a.__vue_app__ ? null : null; }"),
        }
        print("[webview] android_tma_visual",
              json.dumps(out["android_tma_visual"], ensure_ascii=False)[:400])
        ctx.close()

        # 2) Android TMA, dsf=1 — численный замер рефракции (Status-hero).
        ctx = _tma_context(browser, 1)
        page = ctx.new_page()
        page.goto("%s?bgseed=%d#/" % (BASE, BG_SEED), wait_until="load")
        page.wait_for_selector(".app-shell", state="visible")
        page.wait_for_timeout(1300)
        page.evaluate(FREEZE_JS)
        page.evaluate(TARGET_JS)
        page.evaluate(PICK_JS, '.status-hero')
        page.wait_for_timeout(250)
        rec_a, shot_a = capture_state(page, MEASURE_SEL, 1, 390, 844,
                                      "tma-android", "on", True)
        delens = page.evaluate(DELENS_JS, MEASURE_SEL) if shot_a else None
        page.wait_for_timeout(200)
        rec_nl, shot_nl = capture_state(page, MEASURE_SEL, 1, 390, 844,
                                        "tma-android", "on-nolens", True)
        m1 = {"probe": page.evaluate("() => window.__GlassProbe.cached()"),
              "surface": rec_a.get("box"), "lens": rec_a.get("lens"),
              "delens": delens}
        if shot_a and shot_nl:
            a = decode_png(shot_a["raw"])
            c = decode_png(shot_nl["raw"])
            clip = shot_a["clip"]
            box = dict(shot_a["box"])
            box["x"] -= clip["x"]
            box["y"] -= clip["y"]
            y_css = shot_a["y_css"] - clip["y"]
            prof = shift_profile(a, c, box, 1, y_css=y_css)
            m1["metric_lens"] = summarize(prof, box)
            m1["pattern"] = pattern_energy(a, box, 1, y_css=y_css)
            m1["shifts"] = prof["shifts"]
        out["android_tma"] = m1
        print("[webview] android_tma", json.dumps(m1, ensure_ascii=False)[:600])
        ctx.close()

        # 3) WebKit-подобный клиент (probe обязан честно отказать).
        ctx = _tma_context(browser, 1)
        ctx.add_init_script("try { delete window.chrome; } catch (e) {}"
                            " window.chrome = undefined;")
        page = ctx.new_page()
        page.goto("%s?bgseed=%d#/" % (BASE, BG_SEED), wait_until="load")
        page.wait_for_selector(".app-shell", state="visible")
        page.wait_for_timeout(1500)
        fallback = page.evaluate("""
        () => {
          const nodes = Array.from(document.querySelectorAll('[data-glass-tier]'));
          const lenses = nodes.filter((el) => {
            const bf = el.style.backdropFilter ||
              getComputedStyle(el).backdropFilter || '';
            return /url\\(/.test(bf);
          });
          const reasons = {}, tiers = {};
          for (const el of nodes) {
            const r = el.getAttribute('data-glass-reason') || 'none';
            reasons[r] = (reasons[r] || 0) + 1;
            const t = el.getAttribute('data-glass-tier') || 'none';
            tiers[t] = (tiers[t] || 0) + 1;
          }
          return { probe: window.__GlassProbe.cached(), nodes: nodes.length,
                   lensNodes: lenses.length, tiers, reasons,
                   nested: document.querySelectorAll('[data-glass-nested]').length,
                   downgraded: document.querySelectorAll(
                     '[data-glass-downgraded]').length };
        }
        """)
        out["webkit_like_fallback"] = fallback
        print("[webview] webkit_like", json.dumps(fallback, ensure_ascii=False)[:600])
        ctx.close()
        browser.close()
    os.makedirs(EVIDENCE, exist_ok=True)
    path = args.out or os.path.join(EVIDENCE, "webview.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("[webview] ->", path)
    return out


MEASURE_SEL_OR_SURFACE = '[data-gl-measure="1"], .status-hero'


def cmd_serve(args):
    """Локальный стенд для инспекции РЕАЛЬНОГО рендера (Browser Use / Chrome).

    Отдаёт web/ + стабы /api/* (как harness). Переключение tier — по URL:
    `GET /__tier?a|b|c|auto` (аналог env UI_GLASS_TIER_OVERRIDE), затем
    перезагрузка страницы. Работает до Ctrl+C."""
    if args.tier:
        _STATE["tier"] = args.tier
    port = args.port or PORT
    serve(port, os.path.join(REPO, "web"))
    print("[serve] http://127.0.0.1:%d/web/index.html?bgseed=%d#/  (tier=%s)"
          % (port, BG_SEED, _STATE["tier"]))
    print("[serve] tier: http://127.0.0.1:%d/__tier?a  (или ?b / ?auto)" % port)
    print("[serve] Ctrl+C для остановки")
    import time
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["inventory", "verify", "perf", "probe",
                                     "webview", "serve", "shots"])
    ap.add_argument("--dpr", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--sel", default="main .card")
    ap.add_argument("--route", default="#/")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--channel", default="chrome")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--webview", action="store_true")
    ap.add_argument("--tier", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--prefix", default="",
                    help="префикс имён артефактов evidence (напр. _strong_)")
    args = ap.parse_args()
    global EVID_PREFIX
    EVID_PREFIX = args.prefix or ""
    if args.mode == "inventory":
        cmd_inventory(args)
    elif args.mode == "verify":
        cmd_verify(args)
    elif args.mode == "perf":
        cmd_perf(args)
    elif args.mode == "webview":
        cmd_webview(args)
    elif args.mode == "serve":
        cmd_serve(args)
    elif args.mode == "shots":
        cmd_shots(args)
    else:
        cmd_probe(args)


if __name__ == "__main__":
    main()
