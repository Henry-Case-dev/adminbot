# -*- coding: utf-8 -*-
"""CFG-04 — Playwright e2e мобильных форм MiniApp (D.2/D.3, before/after).

Матрица (source L174): 320×640, 360×740, 390×844, 430×932 (портрет) и
667×375, 844×390, 915×412 (ландшафт); DPR 2/3; Telegram safe-area снизу —
56 px (`--tg-content-safe-area-inset-bottom`), как сообщил бы клиент.

Проверяет на РЕАЛЬНЫХ `web/index.html` + `web/app.js` (стабы `/api/*` из
`tools/ui_round1025_matrix.py`, `/api/config` — из живого каталога):

  * B.1 — сколько видимых интерактивных save-CTA: dirty → ровно один
    (панель), индикатор шапки не кликабельный;
  * B.2 — safe-area: `padding-bottom` панели = base + max(env, --tg-safe,
    --tg-content-safe) ровно один раз; клавиатура (`--kb-offset`) двигает
    геометрию панели, «Сохранить»/«Отмена» видны;
  * B.3 — высота панели измерена (не фикс. 4.5rem), последнее поле/каретка
    не перекрыты панелью (проверка `scrollIntoView block:end`);
  * C.1 — на ширине <768 одна колонка, горизонтального overflow нет;
  * C.2 — touch-зона переключателя ≥44×44, кнопки панели ≥44 высотой;
  * C.3 — полный технический ключ: раскрытие + копирование в clipboard;
  * A.1 — поворот 390×844 → 844×390 сохраняет значение, dirty, маршрут,
    прокрутку и активное поле;
  * C.5 — glass-токены/фон не меняются (вычисленные значения + скриншоты).

Два режима:
  * `--baseline` — BEFORE: `baseline.json` + `ui/before/*.png`;
  * (по умолчанию) — AFTER: `after.json` + `ui/after/*.png`.

Запуск: .venv\\Scripts\\python.exe tools\\ui_cfg04_forms_e2e.py [--baseline]
"""
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("CFG04_REPO") or os.path.dirname(HERE)
CODE = os.environ.get("CFG04_CODE") or REPO
sys.path.insert(0, os.path.join(CODE, "tools"))
sys.path.insert(0, CODE)
os.chdir(CODE)
LIVE_URL = os.environ.get("CFG04_LIVE_URL", "").strip()

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8847
EVID = os.environ.get("CFG04_EVID") or os.path.join(
    REPO, "plans", "features", "cfg", "evidence", "cfg-04")
MODE = "live" if LIVE_URL else ("before" if "--baseline" in sys.argv
                                else "after")
SHOTS = os.path.join(EVID, "shots")
RAW = os.path.join(EVID, "live-after.json" if LIVE_URL else
                   ("baseline.json" if MODE == "before" else "after.json"))

VIEWPORTS = [
    ("320x640", 320, 640, 2, 56),
    ("360x740", 360, 740, 3, 56),
    ("390x844", 390, 844, 3, 56),
    ("430x932", 430, 932, 3, 56),
    ("667x375", 667, 375, 2, 24),
    ("844x390", 844, 390, 3, 24),
    ("915x412", 915, 412, 3, 24),
]
# Модель Telegram chrome (синтетическая; реальные величины сообщает клиент):
# портрет — нижняя навигационная зона 56 px, ландшафт — жестовая полоса 24 px.
KB_OFFSET = 280
BASE_PANEL_PAD = 0.45 * 16  # .45rem — базовая часть padding-bottom панели
PARAM_KEY = "limits.dig_year_back_window_days"


def _api_handler(route):
    req = route.request
    if req.method != "GET":
        keys = []
        try:
            payload = json.loads(req.post_data or "{}")
            keys = [it.get("key") for it in payload.get("items", [])]
        except Exception:  # noqa: BLE001
            pass
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"updated_at": 1,
                                       "updated": keys}, ensure_ascii=False))
        return
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(M._stub_for(req.url), ensure_ascii=False))


# ── JS-зонды (возвращают только факты; решение — в Python) ──────────────────
SET_SAFE_AREA_JS = """
(bottom) => {
  const de = document.documentElement;
  const h = window.innerHeight || 0;
  de.style.setProperty('--tg-content-safe-area-inset-bottom', bottom + 'px');
  de.style.setProperty('--tg-safe-area-inset-bottom', bottom + 'px');
  de.style.setProperty('--tg-viewport-stable-height', Math.max(0, h - bottom) + 'px');
  de.style.setProperty('--app-usable-height', Math.max(0, h - bottom) + 'px');
  return { safe: bottom, h: h };
}
"""

SET_KB_JS = """
(px) => {
  document.documentElement.style.setProperty('--kb-offset', px + 'px');
  return px;
}
"""

DIRTY_MAIN_JS = """
(arg) => {
  const key = (arg && arg.key) || null;
  const newValue = (arg && arg.value) || '2';
  const main = document.querySelector('main.scroll-area')
    || document.querySelector('.scroll-area');
  if (!main) return { ok: false, reason: 'no-main' };
  let el = key ? main.querySelector('[data-cfg-key="' + key + '"]') : null;
  if (!el && key) {
    const leaf = Array.from(main.querySelectorAll('div'))
      .filter(d => d.children.length === 0
        && (d.textContent || '').trim() === key)[0];
    const card = leaf ? leaf.closest('.card') : null;
    el = card ? card.querySelector('input.field, textarea.field, select.field') : null;
  }
  if (!el) {
    const fields = Array.from(main.querySelectorAll(
      'input.field, textarea.field, select.field'))
      .filter(x => !x.disabled && x.offsetParent !== null
        && x.closest('.card'));
    el = fields[0] || null;
  }
  if (!el) return { ok: false, reason: 'no-fields' };
  const before = el.value;
  el.focus();
  el.value = newValue;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true, key: el.getAttribute('data-cfg-key') || null,
           tag: el.tagName, type: el.type || '', before: before,
           after: el.value };
}
"""

CLEAN_MAIN_JS = """
() => {
  const main = document.querySelector('main.scroll-area')
    || document.querySelector('.scroll-area');
  if (!main) return false;
  const fields = Array.from(main.querySelectorAll(
    'input.field, textarea.field, select.field'))
    .filter(el => !el.disabled && el.offsetParent !== null);
  if (!fields.length) return false;
  fields.forEach(el => {
    if (el.tagName === 'SELECT') return;
    if (el.type === 'checkbox') return;
    el.value = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  return true;
}
"""

MAIN_PROBE_JS = """
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const main = document.querySelector('main.scroll-area')
    || document.querySelector('.scroll-area');
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && cs.visibility !== 'hidden'
      && cs.display !== 'none';
  };
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: +r.x.toFixed(1), y: +r.y.toFixed(1),
             w: +r.width.toFixed(1), h: +r.height.toFixed(1),
             right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1) };
  };
  const cta = Array.from(new Set(Array.from(document.querySelectorAll('button'))
    .filter(vis)
    .filter(b => /Сохранить/.test(b.innerText || ''))));
  const chip = document.querySelector('[data-save-indicator]')
    || document.querySelector('.header-save-chip');
  const chipIsButton = !!(chip && chip.tagName === 'BUTTON'
    && vis(chip) && !cta.includes(chip));
  const panel = document.querySelector('.sticky-save');
  const pcs = panel ? getComputedStyle(panel) : null;
  const padBottom = pcs ? parseFloat(pcs.paddingBottom) : 0;
  const btnSave = panel ? panel.querySelector('.btn-accent') : null;
  const btnCancel = panel ? panel.querySelector('.btn-ghost') : null;
  const fields = main ? Array.from(main.querySelectorAll(
    'input.field, textarea.field, select.field'))
    .filter(el => !el.disabled && el.offsetParent !== null) : [];
  const first = fields.length ? fields[0] : null;
  const last = fields.length ? fields[fields.length - 1] : null;
  const cards = main ? Array.from(main.querySelectorAll('.card')) : [];
  const cardWidths = cards.map(c => +c.getBoundingClientRect().width.toFixed(1))
    .filter(w => w > 0);
  return {
    vw, vh,
    overflowDoc: document.documentElement.scrollWidth
      - document.documentElement.clientWidth,
    overflowMain: main ? (main.scrollWidth - main.clientWidth) : null,
    gridColumns: main ? getComputedStyle(main).gridTemplateColumns
      .split(' ').filter(Boolean).length : null,
    cardWidths: cardWidths.slice(0, 6),
    panel: box(panel), panelVisible: vis(panel),
    panelPadBottom: padBottom,
    panelBottomCss: pcs ? pcs.bottom : null,
    btnSave: box(btnSave), btnCancel: box(btnCancel),
    cta: cta.map(b => ({ text: (b.innerText || '').trim().slice(0, 40),
                         rect: box(b), inPanel: !!b.closest('.sticky-save'),
                         title: b.getAttribute('title') || '' })),
    ctaCount: cta.length + (chipIsButton ? 1 : 0),
    chip: chip ? { tag: chip.tagName, text: (chip.innerText || '').trim().slice(0, 40),
                   role: chip.getAttribute('role') || '',
                   rect: box(chip) } : null,
    firstField: box(first), lastField: box(last),
    fieldCount: fields.length,
    scrollTop: main ? Math.round(main.scrollTop) : null,
    activeKey: (document.activeElement
      && document.activeElement.getAttribute
      && document.activeElement.getAttribute('data-cfg-key')) || null,
    hash: window.location.hash,
    dirtyCount: (function () {
      try {
        const el = document.querySelector('#app');
        const app = el && el.__vue_app__;
        const inst = (app && app._instance) || (el && el._vnode && el._vnode.component);
        const proxy = inst && (inst.proxy || inst.ctx);
        return proxy ? proxy.stickyDirtyCount : null;
      } catch (e) { return null; }
    })(),
    glass: {
      bgStrong: getComputedStyle(document.documentElement)
        .getPropertyValue('--glass-bg-strong').trim(),
      blur: getComputedStyle(document.documentElement)
        .getPropertyValue('--glass-blur').trim(),
      aurora: !!document.querySelector('.aurora-bg'),
      panelBg: pcs ? pcs.backgroundColor : '',
      panelBackdrop: pcs ? (pcs.backdropFilter || pcs.webkitBackdropFilter || '') : ''
    }
  };
}
"""

LAST_FIELD_JS = """
() => {
  const main = document.querySelector('main.scroll-area')
    || document.querySelector('.scroll-area');
  const panel = document.querySelector('.sticky-save');
  if (!main) return { ok: false, reason: 'no-main' };
  const fields = Array.from(main.querySelectorAll(
    'input.field, textarea.field, select.field'))
    .filter(el => !el.disabled && el.offsetParent !== null);
  if (!fields.length) return { ok: false, reason: 'no-fields' };
  const el = fields[fields.length - 1];
  el.focus();
  el.scrollIntoView({ block: 'end' });
  const fr = el.getBoundingClientRect();
  const pr = panel ? panel.getBoundingClientRect() : null;
  return {
    ok: true,
    key: el.getAttribute('data-cfg-key') || null,
    field: { top: +fr.top.toFixed(1), bottom: +fr.bottom.toFixed(1),
             h: +fr.height.toFixed(1) },
    panelTop: pr ? +pr.top.toFixed(1) : null,
    overlap: pr ? +(fr.bottom - pr.top).toFixed(1) : null,
    caretVisible: fr.bottom <= (pr ? pr.top : window.innerHeight) + 0.5
      && fr.top >= 0,
    activeKey: el.getAttribute('data-cfg-key') || null
  };
}
"""

OPEN_MODULE_JS = """
(id) => {
  const el = document.querySelector('#app');
  const app = el && el.__vue_app__;
  const inst = (app && app._instance) || (el && el._vnode && el._vnode.component);
  const proxy = inst && (inst.proxy || inst.ctx);
  if (!proxy) return { opened: false, reason: 'no-vue-instance' };
  const m = (proxy.modules || []).find(x => x && x.id === id);
  if (!m) return { opened: false, reason: 'no-module' };
  if (typeof proxy.closeModule === 'function' && proxy.openModuleId) {
    proxy.closeModule();
  }
  proxy.openModuleWindow(m);
  return { opened: proxy.openModuleId === id };
}
"""

DIRTY_MODAL_JS = """
(key, newValue) => {
  const root = document.querySelector('.modal-body');
  if (!root) return { ok: false, reason: 'no-modal' };
  let el = key ? root.querySelector('[data-cfg-key="' + key + '"]') : null;
  if (!el) {
    const inputs = Array.from(root.querySelectorAll(
      'input.field, textarea.field, select.field'))
      .filter(x => !x.disabled && x.offsetParent !== null);
    el = inputs[0] || null;
  }
  if (!el) return { ok: false, reason: 'no-field' };
  const before = el.value;
  el.focus();
  el.value = newValue;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true, key: el.getAttribute('data-cfg-key') || null,
           tag: el.tagName, before: before, after: el.value };
}
"""

MODAL_PROBE_JS = """
() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: +r.x.toFixed(1), y: +r.y.toFixed(1),
             w: +r.width.toFixed(1), h: +r.height.toFixed(1),
             right: +r.right.toFixed(1), bottom: +r.bottom.toFixed(1) };
  };
  const body = document.querySelector('.modal-body');
  const panel = document.querySelector('.modal-actions .sticky-save')
    || document.querySelector('.modal-actions');
  const footer = document.querySelector('.modal-actions');
  const cta = Array.from(new Set(Array.from(document.querySelectorAll('button'))
    .filter(vis).filter(b => /Сохранить/.test(b.innerText || ''))));
  const chip = document.querySelector('[data-save-indicator]')
    || document.querySelector('.header-save-chip');
  const chipIsButton = !!(chip && chip.tagName === 'BUTTON' && vis(chip)
    && !cta.includes(chip));
  const toggles = Array.from(document.querySelectorAll(
    '.modal-body label.param-toggle, .param-toggle')).filter(vis);
  const fields = body ? Array.from(body.querySelectorAll(
    'input.field, textarea.field, select.field'))
    .filter(x => !x.disabled && x.offsetParent !== null) : [];
  if (body) body.scrollTop = body.scrollHeight;
  const last = fields.length ? fields[fields.length - 1] : null;
  const lr = last ? last.getBoundingClientRect() : null;
  const fr = footer ? footer.getBoundingClientRect() : null;
  return {
    vw, vh,
    modalOpen: !!document.querySelector('.modal-card'),
    overflowDoc: document.documentElement.scrollWidth
      - document.documentElement.clientWidth,
    panel: box(panel), footer: box(footer),
    panelVisible: vis(panel),
    saveBtn: box(document.querySelector('.sticky-save .btn-accent')),
    cancelBtn: box(document.querySelector('.sticky-save .btn-ghost')),
    cta: cta.map(b => ({ text: (b.innerText || '').trim().slice(0, 40),
                         rect: box(b), inPanel: !!b.closest('.sticky-save') })),
    ctaCount: cta.length + (chipIsButton ? 1 : 0),
    chip: chip ? { tag: chip.tagName,
                   text: (chip.innerText || '').trim().slice(0, 40) } : null,
    toggle: toggles.length ? box(toggles[0]) : null,
    lastField: lr ? { top: +lr.top.toFixed(1), bottom: +lr.bottom.toFixed(1) } : null,
    lastAboveFooter: (lr && fr) ? +(lr.bottom - fr.top).toFixed(1) : null,
    bodyScrollTop: body ? Math.round(body.scrollTop) : null,
    bodyScrollHeight: body ? body.scrollHeight : null,
    hash: window.location.hash
  };
}
"""

KEY_PROBE_JS = """
(key) => {
  const el = document.querySelector('[data-tech-key="' + key + '"]');
  if (!el) return { found: false };
  const value = el.querySelector('.tech-key__value');
  const copy = el.querySelector('.tech-key__copy');
  const vr = value ? value.getBoundingClientRect() : null;
  return {
    found: true,
    tag: value ? value.tagName : '',
    title: value ? (value.getAttribute('title') || '') : '',
    text: value ? (value.textContent || '').trim() : '',
    truncated: value ? (value.scrollWidth > value.clientWidth + 1) : null,
    ariaExpanded: value ? value.getAttribute('aria-expanded') : null,
    rect: vr ? { w: +vr.width.toFixed(1), h: +vr.height.toFixed(1) } : null,
    copy: !!copy
  };
}
"""

KEY_OPEN_JS = """
(key) => {
  const el = document.querySelector('[data-tech-key="' + key + '"]');
  if (!el) return { found: false };
  const value = el.querySelector('.tech-key__value');
  if (value) value.click();
  return { found: true, clicked: !!value };
}
"""

KEY_OPEN_MEASURE_JS = """
(key) => {
  const el = document.querySelector('[data-tech-key="' + key + '"]');
  if (!el) return { found: false };
  const value = el.querySelector('.tech-key__value');
  const r = value ? value.getBoundingClientRect() : null;
  return {
    found: true,
    ariaExpanded: value ? value.getAttribute('aria-expanded') : null,
    truncated: value ? (value.scrollWidth > value.clientWidth + 1) : null,
    fullText: value ? (value.textContent || '').trim() : '',
    rect: r ? { w: +r.width.toFixed(1), h: +r.height.toFixed(1) } : null
  };
}
"""

KEY_COPY_JS = """
async (key) => {
  const el = document.querySelector('[data-tech-key="' + key + '"]');
  if (!el) return { found: false };
  const copy = el.querySelector('.tech-key__copy');
  if (!copy) return { found: true, copy: false };
  copy.click();
  let text = null;
  try { text = await navigator.clipboard.readText(); } catch (e) { text = null; }
  return { found: true, copy: true, clipboard: text,
           copied: copy.getAttribute('data-copied') === '1' };
}
"""

TOGGLE_PROBE_JS = """
() => {
  let labels = Array.from(document.querySelectorAll('.param-toggle'))
    .filter(el => el.offsetParent !== null);
  if (!labels.length) {
    labels = Array.from(document.querySelectorAll(
      '.modal-body label')).filter(el => el.offsetParent !== null)
      .filter(el => el.querySelector('input[type=checkbox]'));
  }
  if (!labels.length) return { found: false };
  const r = labels[0].getBoundingClientRect();
  return { found: true, w: +r.width.toFixed(1), h: +r.height.toFixed(1),
           marked: labels[0].classList.contains('param-toggle') };
}
"""


def _open_config_tab(page, hash_route="#/memory/rag"):
    page.evaluate("(r) => { window.location.hash = r; }", hash_route)
    page.wait_for_timeout(900)
    try:
        page.wait_for_selector('[data-config-group]', timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    page.evaluate(
        "(() => { document.querySelectorAll('summary').forEach(s => {"
        "  if ((s.textContent || '').indexOf('Расширенные') >= 0) {"
        "    const d = s.closest('details'); if (d) d.open = true; } }); })()")
    page.wait_for_timeout(300)


def _modal_blockers(probe, label):
    out = []
    if not probe.get("modalOpen"):
        out.append("%s: модалка модуля не открылась" % label)
        return out
    if probe.get("ctaCount") != 1:
        out.append("%s: save-CTA в модалке = %s (ожидался 1)"
                   % (label, probe.get("ctaCount")))
    if not probe.get("panelVisible"):
        out.append("%s: панель сохранения не видна в модалке" % label)
    for name in ("saveBtn", "cancelBtn"):
        r = probe.get(name)
        if not r:
            out.append("%s: нет %s" % (label, name))
            continue
        if r["bottom"] > probe["vh"] + 1 or r["right"] > probe["vw"] + 1 \
                or r["x"] < -1 or r["y"] < -1:
            out.append("%s: %s за пределами экрана %s" % (label, name, r))
    if probe.get("overflowDoc", 0) > 2:
        out.append("%s: горизонтальный overflow %s" % (label, probe["overflowDoc"]))
    if probe.get("lastAboveFooter") is not None and probe["lastAboveFooter"] > 1:
        out.append("%s: последнее поле под футером на %s px"
                   % (label, probe["lastAboveFooter"]))
    return out


def _main_blockers(probe, label, kb_px=None, safe_px=None):
    out = []
    if probe.get("overflowDoc", 0) > 2:
        out.append("%s: горизонтальный overflow %s" % (label, probe["overflowDoc"]))
    if probe.get("overflowMain") is not None and probe["overflowMain"] > 2:
        out.append("%s: overflow контента %s" % (label, probe["overflowMain"]))
    if probe["vw"] < 768 and probe.get("gridColumns") not in (1, None):
        out.append("%s: на смартфоне %s колонок (ожидалась 1)"
                   % (label, probe["gridColumns"]))
    for w in probe.get("cardWidths") or []:
        limit = min(280, probe["vw"] - 64)
        if w < limit:
            out.append("%s: карточка сжата до %s px (< %s)" % (label, w, limit))
            break
    if not probe.get("panelVisible"):
        out.append("%s: панель dirty не появилась" % label)
    if probe.get("ctaCount") != 1:
        out.append("%s: видимых save-CTA = %s (ожидался ровно 1: панель)"
                   % (label, probe["ctaCount"]))
    expected_pad = BASE_PANEL_PAD + (safe_px if safe_px is not None else 56)
    pad = probe.get("panelPadBottom") or 0
    if abs(pad - expected_pad) > 2:
        out.append("%s: safe-area панели %.1f px (ожидалось ~%.1f = base+56)"
                   % (label, pad, expected_pad))
    ret = probe.get("btnSave")
    cancel = probe.get("btnCancel")
    for name, r in (("Сохранить", ret), ("Отмена", cancel)):
        if not r:
            out.append("%s: нет кнопки %s" % (label, name))
            continue
        if r["h"] < 43.5:
            out.append("%s: touch-зона «%s» %.1f px < 44" % (label, name, r["h"]))
        if r["bottom"] > probe["vh"] + 1 or r["right"] > probe["vw"] + 1 \
                or r["x"] < -1 or r["y"] < -1:
            out.append("%s: «%s» за пределами экрана %s" % (label, name, r))
    if kb_px:
        panel = probe.get("panel")
        if not panel:
            out.append("%s: нет панели для проверки клавиатуры" % label)
        else:
            if panel["bottom"] > probe["vh"] - kb_px + 2:
                out.append("%s: клавиатура %s px — панель не поднялась "
                           "(bottom %.1f > %.1f)"
                           % (label, kb_px, panel["bottom"], probe["vh"] - kb_px))
            if panel["y"] < -1:
                out.append("%s: клавиатура %s px — панель обрезана сверху "
                           "(top %.1f)" % (label, kb_px, panel["y"]))
    return out


def _orientation_blockers(before, after, label):
    out = []
    for name in ("dirty", "value", "hash", "scroll", "active"):
        if not after.get(name + "_ok"):
            out.append("%s: поворот потерял %s (%s → %s)"
                       % (label, name, before.get(name), after.get(name)))
    return out


def _serve_only() -> int:
    """Режим визуальной проверки (Browser Use): статика + серверные стабы.

    ТОЛЬКО для локального осмотра: в отдаваемый `index.html` добавляется
    тестовый TMA-стаб (`M.TMA_STUB` — тот же, что в Playwright), иначе миниапп
    без Telegram-контекста показывает блокирующую заглушку. Файл в репозитории
    НЕ меняется; прод/деплой этим режимом не затрагивается.
    """
    stub_js = M.TMA_STUB.encode("utf-8")
    M.REPO = REPO          # статика/индекс берутся из зеркала прод-байтов

    class _ServeHandler(M._Handler):
        def log_message(self, *args):      # тишина
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):                  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            keys = []
            try:
                keys = [it.get("key") for it in
                        json.loads(raw.decode("utf-8")).get("items", [])]
            except Exception:  # noqa: BLE001
                pass
            self._json({"updated_at": 1, "updated": keys})

        def do_GET(self):                   # noqa: N802
            path = self.path.split("?")[0]
            if path == "/__cfg04_tma_stub.js":
                return self._bytes(stub_js, "application/javascript; charset=utf-8")
            if path in ("/web/index.html", "/web/", "/web"):
                full = os.path.join(REPO, "web", "index.html")
                with open(full, "rb") as fh:
                    html = fh.read()
                marker = b'<script src="/web/app.js'
                inject = (b'<script src="/__cfg04_tma_stub.js"></script>\n  ')
                if marker in html:
                    html = html.replace(marker, inject + marker, 1)
                return self._bytes(html, "text/html; charset=utf-8")
            if path.startswith("/api/"):
                return self._json(M._stub_for(self.path))
            return super().do_GET()

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _ServeHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    print("SERVE %s#/memory/rag" % base, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:      # pragma: no cover
        return 0


def main() -> int:
    if "--serve" in sys.argv:
        return _serve_only()
    if LIVE_URL:
        base = LIVE_URL
        origin = "https://admin-bot.duckdns.org"
        try:
            parts = urllib.parse.urlsplit(LIVE_URL)
            origin = "%s://%s" % (parts.scheme, parts.netloc)
        except Exception:
            pass
        print("LIVE base=%s origin=%s" % (base, origin))
    else:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d/web/index.html" % PORT
        origin = "http://127.0.0.1:%d" % PORT
    os.makedirs(SHOTS, exist_ok=True)

    from playwright.sync_api import sync_playwright
    result = {"mode": MODE, "port": PORT, "live_url": LIVE_URL,
              "viewports": {},
              "console_errors": [], "screenshots": [], "failures": []}
    failures = result["failures"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, w, h, dpr, safe in VIEWPORTS:
            ctx = browser.new_context(
                viewport={"width": w, "height": h},
                device_scale_factor=dpr, is_mobile=True, has_touch=True,
                reduced_motion="reduce")
            ctx.add_init_script(M.TMA_STUB)
            ctx.grant_permissions(["clipboard-read", "clipboard-write"],
                                  origin=origin)
            ctx.route("**/api/**", _api_handler)
            page = ctx.new_page()
            page.on("console", lambda m, n=name: result["console_errors"].append(
                "%s: %s" % (n, m.text[:160])) if m.type == "error" else None)
            page.on("pageerror", lambda e, n=name: result["console_errors"].append(
                "%s: pageerror %s" % (n, str(e)[:160])))
            page.on("dialog", lambda d: d.accept())
            page.goto(base, wait_until="load")
            page.wait_for_timeout(1500)
            page.evaluate(SET_SAFE_AREA_JS, safe)
            page.wait_for_timeout(150)
            vp = {"size": [w, h], "dpr": dpr, "safe_bottom": safe,
                  "keyboard_model": "visualViewport emulation (--kb-offset)"}
            result["viewports"][name] = vp

            # ── A. config-вкладка: clean → dirty → геометрия ──────────────
            _open_config_tab(page)
            clean = page.evaluate(MAIN_PROBE_JS)
            vp["config_clean"] = {
                "ctaCount": clean["ctaCount"],
                "panelVisible": clean["panelVisible"],
                "chip": clean["chip"], "gridColumns": clean["gridColumns"],
                "overflowDoc": clean["overflowDoc"],
            }
            if clean["ctaCount"] != 0 or clean["panelVisible"]:
                failures.append("%s clean: панель/CTA видны без изменений (%s/%s)"
                                % (name, clean["ctaCount"], clean["panelVisible"]))

            dirty = page.evaluate(DIRTY_MAIN_JS,
                                  {"key": PARAM_KEY, "value": "2"})
            page.wait_for_timeout(400)
            probe = page.evaluate(MAIN_PROBE_JS)
            probe["dirtyAction"] = dirty
            vp["config_dirty"] = probe
            failures.extend(_main_blockers(probe, "%s config" % name,
                                           safe_px=safe))
            if not probe.get("dirtyCount"):
                failures.append("%s config: dirty-счётчик пуст после правки" % name)
            shot = os.path.join(SHOTS, "%s-config-dirty.png" % name)
            page.screenshot(path=shot)
            result["screenshots"].append(shot)

            # последнее поле/каретка не под панелью
            last = page.evaluate(LAST_FIELD_JS)
            page.wait_for_timeout(250)
            last = page.evaluate(LAST_FIELD_JS)
            vp["last_field"] = last
            if last.get("ok"):
                if last.get("overlap") is not None and last["overlap"] > 0.5:
                    failures.append(
                        "%s: последнее поле под панелью на %.1f px"
                        "(field.bottom=%.1f panel.top=%.1f)"
                        % (name, last["overlap"], last["field"]["bottom"],
                           last["panelTop"]))
                if not last.get("caretVisible"):
                    failures.append("%s: последнее поле/каретка не видны" % name)
            else:
                failures.append("%s: last-field probe: %s"
                                % (name, last.get("reason")))

            # ── B. клавиатура: --kb-offset двигает панель ────────────────
            # Реалистичная высота клавиатуры: ~половина экрана в ландшафте,
            # до 280 px в портрете (эмуляция visualViewport, не реальный клиент).
            kb_px = min(KB_OFFSET, int(round(h * 0.5)))
            page.evaluate(SET_KB_JS, kb_px)
            page.wait_for_timeout(250)
            kb_probe = page.evaluate(MAIN_PROBE_JS)
            vp["config_keyboard"] = {
                "kb": kb_px, "panel": kb_probe.get("panel"),
                "saveBtn": kb_probe.get("saveBtn"),
                "cancelBtn": kb_probe.get("cancelBtn"),
                "vh": kb_probe.get("vh"),
            }
            failures.extend(_main_blockers(kb_probe, "%s kb" % name,
                                           kb_px=kb_px, safe_px=safe))
            page.evaluate(SET_KB_JS, 0)
            page.wait_for_timeout(250)
            kb_closed = page.evaluate(MAIN_PROBE_JS)
            vp["config_kb_closed"] = {
                "panel": kb_closed.get("panel"),
                "expected_bottom": kb_closed.get("vh", 0) - safe,
            }
            pnl = kb_closed.get("panel") or {}
            if pnl:
                if pnl.get("bottom", 0) > kb_closed["vh"] + 1:
                    failures.append(
                        "%s: при закрытой клавиатуре панель вышла за экран "
                        "(bottom %.1f > vh %.1f)"
                        % (name, pnl["bottom"], kb_closed["vh"]))
                # стейл offset сдвинул бы панель на всю высоту клавиатуры
                # (>=180 px); честная граница — полоса у нижнего края.
                if pnl.get("bottom", 0) < kb_closed["vh"] - 120:
                    failures.append(
                        "%s: стейл --kb-offset после закрытия клавиатуры "
                        "(panel bottom %.1f, vh %.1f, панель %.1f)"
                        % (name, pnl["bottom"], kb_closed["vh"],
                           pnl.get("h", 0)))

            # ── C. полный технический ключ ───────────────────────────────
            key = "limits.dig_year_back_window_days"
            key_info = page.evaluate(KEY_PROBE_JS, key)
            vp["tech_key"] = key_info
            vp["tech_key_count"] = page.evaluate(
                "() => document.querySelectorAll('.tech-key').length")
            if not vp["tech_key_count"]:
                failures.append("%s: на странице нет tech-key карточек" % name)
            if not key_info.get("found"):
                failures.append("%s: технический ключ %s без раскрытия (C.3)"
                                % (name, key))
            else:
                if key_info.get("title") != key:
                    failures.append("%s: title ключа не содержит полное значение"
                                    % name)
                opened = page.evaluate(KEY_OPEN_JS, key)
                page.wait_for_timeout(250)
                opened = page.evaluate(KEY_OPEN_MEASURE_JS, key)
                vp["tech_key_open"] = opened
                if opened.get("truncated"):
                    failures.append("%s: раскрытый ключ всё ещё обрезан" % name)
                if opened.get("fullText") != key:
                    failures.append("%s: раскрытие показало не полный ключ (%r)"
                                    % (name, opened.get("fullText")))
                copied = page.evaluate(KEY_COPY_JS, key)
                vp["tech_key_copy"] = copied
                if not copied.get("clipboard") or copied["clipboard"] != key:
                    failures.append("%s: копирование ключа не сработало (%r)"
                                    % (name, copied.get("clipboard")))

            # ── D. поворот: значение/dirty/скролл/маршрут/поле ──────────
            if (w, h) == (390, 844):
                before = page.evaluate("""(key) => {
                  const main = document.querySelector('main.scroll-area');
                  const fields = Array.from(main.querySelectorAll(
                    'input.field, textarea.field, select.field'))
                    .filter(el => !el.disabled && el.offsetParent !== null);
                  let el = main.querySelector('[data-cfg-key="' + key + '"]');
                  if (!el) {
                    const leaf = Array.from(main.querySelectorAll('div'))
                      .filter(d => d.children.length === 0
                        && (d.textContent || '').trim() === key)[0];
                    const card = leaf ? leaf.closest('.card') : null;
                    el = card ? card.querySelector(
                      'input.field, textarea.field, select.field') : null;
                  }
                  if (!el) return { error: 'no-field' };
                  el.focus();
                  el.value = '7';
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                  main.scrollTop = 220;
                  const doc = document.scrollingElement || document.documentElement;
                  const mainScrollable = main.scrollHeight > main.clientHeight + 1;
                  return { value: el.value, dirty: true,
                           scroll: Math.round(mainScrollable
                             ? main.scrollTop : doc.scrollTop),
                           mainScrollable: mainScrollable,
                           hash: window.location.hash,
                           key: el.getAttribute('data-cfg-key') || key,
                           index: fields.indexOf(el) };
                }""", PARAM_KEY)
                page.wait_for_timeout(250)
                page.set_viewport_size({"width": 844, "height": 390})
                page.wait_for_timeout(700)
                after = page.evaluate("""(a) => {
                  const main = document.querySelector('main.scroll-area');
                  if (!main) return { value: null, scroll: null, hash: window.location.hash,
                                     active: null, dirty: null, dirty_ok: false,
                                     value_ok: false, hash_ok: false,
                                     scroll_ok: false, active_ok: false };
                  const fields = Array.from(main.querySelectorAll(
                    'input.field, textarea.field, select.field'))
                    .filter(el => !el.disabled && el.offsetParent !== null);
                  let el = a.key ? main.querySelector(
                    '[data-cfg-key="' + a.key + '"]') : null;
                  if (!el) el = fields[a.index] || null;
                  const active = document.activeElement;
                  const activeKey = (active && active.getAttribute
                    && active.getAttribute('data-cfg-key')) || null;
                  const same = el && activeKey && a.key
                    ? activeKey === a.key : !!(el && active === el);
                  let dirty = null;
                  try {
                    const root = document.querySelector('#app');
                    const app = root && root.__vue_app__;
                    const inst = (app && app._instance)
                      || (root && root._vnode && root._vnode.component);
                    const proxy = inst && (inst.proxy || inst.ctx);
                    dirty = proxy ? proxy.stickyDirtyCount : null;
                  } catch (e) { dirty = null; }
                  const doc = document.scrollingElement
                    || document.documentElement;
                  const mainScrollable = main.scrollHeight > main.clientHeight + 1;
                  const eff = mainScrollable ? main.scrollTop : doc.scrollTop;
                  return {
                    value: el ? el.value : null,
                    scroll: Math.round(eff),
                    mainScrollable: mainScrollable,
                    docScrollTop: Math.round(doc.scrollTop || 0),
                    hash: window.location.hash,
                    active: activeKey || (active ? active.tagName : null),
                    dirty: dirty,
                    value_ok: !!(el && el.value === '7'),
                    hash_ok: window.location.hash === a.hash,
                    dirty_ok: dirty === 1,
                    scroll_ok: Math.abs(Math.round(eff) - a.scroll) <= 6,
                    active_ok: same
                  };
                }""", before)
                vp["orientation"] = {"before": before, "after": after}
                failures.extend(_orientation_blockers(before, after, name))
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(500)

            # ── E. модалка модуля «Ответы в чате» ───────────────────────
            page.evaluate("window.location.hash = '#/modules'")
            page.wait_for_timeout(900)
            opened = page.evaluate(OPEN_MODULE_JS, "mod_direct")
            page.wait_for_timeout(900)
            vp["module_open"] = opened
            if opened.get("opened"):
                mdirty = page.evaluate(DIRTY_MODAL_JS,
                                       ["limits.chat_burst_limit", "3"])
                page.wait_for_timeout(350)
                mprobe = page.evaluate(MODAL_PROBE_JS)
                mprobe["dirtyAction"] = mdirty
                vp["module_dirty"] = mprobe
                failures.extend(_modal_blockers(mprobe, "%s module" % name))
                toggle = page.evaluate(TOGGLE_PROBE_JS)
                vp["toggle"] = toggle
                if toggle.get("found"):
                    if toggle["w"] < 43.5 or toggle["h"] < 43.5:
                        failures.append(
                            "%s: touch-зона переключателя %.1f×%.1f < 44×44"
                            % (name, toggle["w"], toggle["h"]))
                else:
                    failures.append("%s: переключатель не найден в модалке" % name)
                vp["module_after_scroll"] = page.evaluate(MODAL_PROBE_JS)
            else:
                failures.append("%s: модуль mod_direct не открылся (%s)"
                                % (name, opened.get("reason")))

            # ── F. скриншоты (before/after) ─────────────────────────────
            shot = os.path.join(SHOTS, "%s-module-dirty.png" % name)
            page.screenshot(path=shot)
            result["screenshots"].append(shot)

            # glass/фон: инварианта измеряется на чистых токенах
            vp["glass"] = page.evaluate(
                "() => { const de = document.documentElement;"
                " const cs = getComputedStyle(de);"
                " return { bgStrong: cs.getPropertyValue('--glass-bg-strong').trim(),"
                "  blur: cs.getPropertyValue('--glass-blur').trim(),"
                "  aurora: !!document.querySelector('.aurora-bg'),"
                "  bodyBefore: getComputedStyle(document.body, '::before').content"
                " }; }")
            ctx.close()

        browser.close()

    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print("[cfg04] mode=%s viewports=%d failures=%d shots=%d console_errors=%d"
          % (MODE, len(result["viewports"]), len(failures),
             len(result["screenshots"]), len(result["console_errors"])))
    for f in failures:
        print("  FAIL:", f)
    if result["console_errors"]:
        for e in result["console_errors"][:10]:
            print("  CONSOLE:", e)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
