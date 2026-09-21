"""F1 round 10.25 — Playwright/Chromium матрица shell'ов (§71, T-2407).

Реальный `web/index.html` + `web/static/*` на локальном http-сервере; `/api/*`
перехватываются Playwright'ом и отдаются фейковыми ответами (R17: без
секретов, без реального бэкенда/БД). Telegram.WebApp стубируется init-script'ом.

Проверяет для каждого вьюпорта §71:
  * `document.documentElement.scrollWidth <= window.innerWidth + 1`
    (нет горизонтального скролла страницы);
  * реальные `getBoundingClientRect()` ключевых shell-элементов
    (sidebar ≥1200 / drawer 768–1199 / bottom-nav <768 — взаимоисключающе);
  * нижняя навигация = N пунктов (админ hotfix4: Статус/Справка/Модули/Ещё = 4);
  * hotfix4 (T-2517): вертикальная граница — `.bottom-nav`/`.more-sheet`
    целиком в экране: `rect.bottom <= innerHeight + 1` И (при наличии
    системного бара) `rect.bottom <= stableHeight + 1` → FAIL при выходе;
  * touch-таргеты ≥44×44;
  * скриншоты desktop/mobile.

Матрица: 320×700, 360×780, 390×844, 430×932, 768×1024, 1024×768,
1280×800, 1440×900, 1920×1080, 2560×1440.

Запуск: .venv/Scripts/python.exe tools/ui_round1025_matrix.py
Артефакты: tools/_ui_round1025_raw.json + tools/_ui_round1025_shots/*.png

ВАЖНО: это инструмент @Builder/@Reviewer/@DevOps. Успешный прогон локально НЕ
заменяет живую приёмку в Telegram WebView (10.20-UPD3/10.21 урок).
"""
import json
import os
import re
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PORT = 8791
SHOTS = os.path.join(REPO, "tools", "_ui_round1025_shots")
RAW = os.path.join(REPO, "tools", "_ui_round1025_raw.json")

VIEWPORTS = [
    (320, 700), (360, 780), (390, 844), (430, 932), (768, 1024),
    (1024, 768), (1280, 800), (1440, 900), (1920, 1080), (2560, 1440),
]
ROUTES = ["#/", "#/oversight", "#/how", "#/modules", "#/ai",
          "#/ai/llm", "#/ai/prompts", "#/ai/smart-cache", "#/ai/names",
          "#/memory", "#/memory/rag", "#/memory/lore", "#/access"]


class _Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p.startswith("/web/"):
            rel = p[1:]
        elif p in ("/", "", "/index.html"):
            rel = "web/index.html"
        else:
            rel = p.lstrip("/")
        return os.path.join(REPO, rel.replace("/", os.sep))

    def log_message(self, *args):  # тишина
        pass


def _start_server() -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


ME_JSON = {
    "telegram_id": 5885953495,
    "username": "audit",
    "first_name": "Audit",
    "last_name": None,
    "photo_url": None,
    "role_name": "global_admin",
    "permissions": {"wildcard": True},
    "is_custom": False,
    "is_global_admin": True,
    "ui_flags": {
        "TOKEN_FLOW_NODEFLOW_ENABLED": True,
        "IMAGE_MODULE_CARD_ENABLED": True,
        "PROMPTS_UI_V2_ENABLED": True,
        "BYOK_IMAGE_KEY_ENABLED": True,
        "DOSSIER_LIVE_FEED_ENABLED": True,
        "ALIASES_KEYSVALUE_RENDER_ENABLED": True,
        "IA_V2_ENABLED": True,
    },
}

# F3 (reviewer 2): локальный админ — UI должен совпадать с правами сервера
# (DELETE-override разрешён is_local_admin, routes.py). Роль без wildcard;
# секция «memory» открывает config-вкладку #/memory/rag для проверки кнопки.
LOCAL_ADMIN_ME = dict(ME_JSON)
LOCAL_ADMIN_ME.update({
    "username": "localadmin",
    "first_name": "Local",
    "role_name": "local_admin",
    "permissions": {"sections": ["memory"], "params": [], "keys": []},
    "is_global_admin": False,
})


# Минимально достаточные ответы API, чтобы шаблоны монтировались без падений
# (реальный бэкенд/БД не поднимаем; секретов нет — R17).
STATUS_STUB = {
    "bot": {"uptime_seconds": 3600, "state": "running", "errors_total": 0},
    "server": {
        "cpu_percent": 3.0,
        "memory": {"used": 536870912, "total": 2147483648, "percent": 25},
        "disk": {"used": 10737418240, "total": 107374182400, "percent": 10},
        "loadavg": [0.1, 0.2, 0.3],
        "process": {"pid": 1234, "rss_mb": 120, "threads": 8},
    },
    "llm": [],
    "context": {},
}

def _config_stub() -> dict:
    """Непустой `/api/config` из `services/param_catalog.py` (P0-инцидент F1).

    Даёт реальный рендер generic config-разделов (`#/ai/llm`, `#/ai/names`,
    `#/ai/smart-cache`, `#/ai/prompts`, `#/memory/rag`) — чтобы render-ошибки
    класса `stickyFieldFailed is not a function` ловились автоматически.
    Секретов нет (R17): секретные значения — `{configured,last4}`."""
    try:
        from services import param_catalog as pc
    except Exception as exc:  # noqa: BLE001
        print("[matrix] config stub: param_catalog недоступен:", exc)
        return {"items": [], "groups": []}
    items = []
    for key, spec in sorted(pc.REGISTRY.items()):
        if getattr(spec, "hidden", False):
            continue
        secret = bool(getattr(spec, "secret", False))
        widget = getattr(spec, "widget", "") or ""
        stype = getattr(spec, "type", "str") or "str"
        if secret:
            value = {"configured": True, "last4": "0000"}
        elif widget == "keyvalue":
            value = {}
        elif stype == "bool":
            value = False
        elif stype in ("int", "float"):
            value = 1
        elif widget == "select" and getattr(spec, "select_options", None):
            value = list(spec.select_options)[0]
        else:
            value = ""
        items.append({
            "key": key, "value": value, "category": spec.category,
            "secret": secret, "chat_source": "", "global_value": None,
            "title": getattr(spec, "title_ru", key) or key, "type": stype,
            "updated_at": None, "group": getattr(spec, "group", "") or "",
            "description": getattr(spec, "description", "") or "",
            "widget": widget,
            "select_options": list(spec.select_options)
            if widget == "select" and getattr(spec, "select_options", None)
            else None,
            "select_labels": list(spec.select_labels)
            if widget == "select" and getattr(spec, "select_labels", None)
            else None,
            "per_chat": bool(getattr(spec, "per_chat", False)),
            "progressive_level": "basic",
            "stage": getattr(spec, "stage", None),
            "view_roles": [], "edit_roles": [], "chat_updated_at": None,
        })
    present = {it["category"] for it in items}
    groups = [{"id": g.id, "category": g.category, "title": g.title_ru,
               "description": g.description, "order": g.order}
              for g in pc.GROUPS if g.category in present]
    groups.sort(key=lambda g: g["order"])
    print("[matrix] config stub: items=%d groups=%d" % (len(items), len(groups)))
    return {"items": items, "groups": groups}


def _chat_variant(base: dict) -> dict:
    """F3 (reviewer High): chat-ответ `/api/config` с РЕАЛЬНЫМ override.

    Без этого матрица ложно-зелёная: все items с `chat_source:""` →
    кнопка «Вернуть глобальное» и §43-пометка не рендерятся. Помечаем
    per_chat-bool как локально включённые при глобально выключенных
    (per_chat override wins по серверной логике `routes.py::get_config`)."""
    import copy
    data = copy.deepcopy(base)
    n = 0
    for it in data.get("items", []):
        if it.get("per_chat") and it.get("type") == "bool":
            it["chat_source"] = "chat"
            it["global_value"] = False
            it["value"] = True
            n += 1
    print("[matrix] chat-вариант config: override items=%d" % n)
    return data


CONFIG_STUB = _config_stub()
CONFIG_STUB_CHAT = _chat_variant(CONFIG_STUB)

API_STUBS = [
    ("/api/me", ME_JSON),
    ("/api/status/key-history", {"providers": []}),
    ("/api/status/logs", {"logs": [], "levels": [], "counts": {}}),
    ("/api/status", STATUS_STUB),
    ("/api/access/me", {"is_local_admin": False, "permissions": {}}),
    ("/api/access/param_permissions", {"items": {}, "roles": []}),
    # F3 (§5): ≥1 чат → селектор области постоянно доступен (проверяем
    # позицию desktop/mobile). Без photo_file_id — без сетевых avatar-запросов.
    ("/api/access/chats", [
        {"chat_id": -1001234567890, "title": "Audit Chat", "is_dm": False,
         "photo_file_id": None, "access": "admin"},
    ]),
    ("/api/admins", {"admins": []}),
    ("/api/roles", {"roles": [{"role_name": "user", "permissions": {}}]}),
    ("/api/oversight/summary", {"chats": [], "totals": {}}),
    ("/api/oversight/dossier_feed", {"items": []}),
    ("/api/workers/budget", {}),
    ("/api/config", CONFIG_STUB),
    ("/api/info/guide", {"markdown": "", "updated_at": None}),
    ("/api/info", {"html": "", "updated_at": None, "canon_drift": False}),
]


def _stub_for(url: str):
    for marker, payload in API_STUBS:
        if url.split("?")[0].endswith(marker):
            return payload
    return {}


TMA_STUB = """
try {
  // Реальный telegram-web-app.js перетирает window.Telegram своим WebApp с
  // пустым initData (нет настоящего TG). app.js::getInitData кэширует/читает
  // sessionStorage — засеваем его, чтобы hasInitData() был истинным.
  sessionStorage.setItem('adminbot.initData', 'user=%7B%22id%22%3A5885953495%7D&hash=audit');
} catch (e) {}
window.Telegram = { WebApp: {
  initData: 'user=%7B%22id%22%3A5885953495%7D&hash=audit',
  initDataUnsafe: { user: { id: 5885953495, first_name: 'Audit' } },
  themeParams: {}, colorScheme: 'dark',
  // hotfix4 (T-2517): имитируем системный нижний бар Telegram — visible
  // (stable) высота меньше layout (innerHeight) на 56px. Тогда панель с
  // bottom:0 выходит за видимую область, а с offset-компенсацией — нет.
  get viewportStableHeight() {
    return Math.max(0, (window.innerHeight || 800) - 56);
  },
  safeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  contentSafeAreaInset: { top: 0, bottom: 0, left: 0, right: 0 },
  ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {},
  setBottomBarColor() {}, onEvent() {}, offEvent() {}, isExpanded: true,
  BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
} };
"""

PROBE_JS = """
(() => {
  const de = document.documentElement;
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return { x: Math.round(r.x), y: Math.round(r.y),
             w: Math.round(r.width), h: Math.round(r.height),
             bottom: Math.round(r.bottom),
             display: st.display, visible: r.width > 0 && r.height > 0 };
  };
  const links = Array.from(document.querySelectorAll('.bottom-nav-link'));
  const minTouch = links.reduce((m, el) => {
    const r = el.getBoundingClientRect();
    return Math.min(m, Math.min(r.width || 999, r.height || 999));
  }, 999);
  const stableRaw = getComputedStyle(de)
    .getPropertyValue('--tg-viewport-stable-height').trim();
  return {
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    stableHeight: parseFloat(stableRaw) || window.innerHeight,
    scrollWidth: de.scrollWidth,
    overflow: de.scrollWidth > window.innerWidth + 1,
    sidebar: rect('.app-sidebar'),
    drawer: rect('.app-drawer'),
    bottomNav: rect('.bottom-nav'),
    moreSheet: rect('.more-sheet'),
    moreOpen: !!document.querySelector('.more-sheet.open'),
    navbarBand: rect('.navbar-band'),
    bottomNavCount: links.length,
    minTouch: links.length ? Math.round(minTouch) : null,
    hasAsideEl: !!document.querySelector('.app-sidebar'),
    // F3 (§5/§70): селектор области — постоянно доступный; на mobile
    // отдельной строкой ПОД заголовком, тач-цель ≥44px.
    scopeWrap: rect('.scope-wrap'),
    scopeTrigger: rect('.scope-trigger'),
    headerTitle: rect('.header-title-wrap'),
    // hotfix6/C1 (T-2598): сердебиение §15 в границах контейнера.
    hbBlock: rect('.status-block'),
    hbWrap: rect('.hb-wrap'),
    hbCanvas: rect('.hb-canvas'),
    hbOverflow: (() => {
      const w = document.querySelector('.hb-wrap');
      return w ? (w.scrollWidth - w.clientWidth) : 0;
    })(),
    // hotfix6/D (T-2611): компактная шапка, резерв высоты, ⛶ в вьюпорте.
    headerCompact: !!document.querySelector(
      'header.header-sticky.header-compact-v2'),
    headerH: getComputedStyle(de).getPropertyValue('--header-h').trim(),
    fsBtnInViewport: (() => {
      const b = document.querySelector('.header-fs-btn');
      if (!b) return null;
      const r = b.getBoundingClientRect();
      return r.right <= window.innerWidth + 1 && r.left >= -1;
    })(),
    mediaMin1200: window.matchMedia('(min-width: 1200px)').matches,
    mediaMax767: window.matchMedia('(max-width: 767px)').matches,
  };
})()
"""


# F2 (T-2554, §8/§9/§10): F2-пробы — реальные computed-стили, диапазоны
# длительностей, glass allow/deny, пауза при document.hidden.
F2_PROBE_JS = """
(() => {
  const de = document.documentElement;
  const tok = (n) => getComputedStyle(de).getPropertyValue(n).trim();
  const bf = (el) => {
    if (!el) return null;
    const st = getComputedStyle(el);
    return (st.backdropFilter || st.webkitBackdropFilter || '');
  };
  const before = getComputedStyle(document.body, '::before');
  const c = document.querySelector('[data-glass="c"]');
  // D-1/@Reviewer: фактический цвет Tailwind-утилиты внутри стекла (12px).
  const utilEl = document.querySelector('[data-glass] .text-gray-500') ||
                 document.querySelector('.text-gray-500');
  const utility = utilEl ? getComputedStyle(utilEl).color : null;
  // hotfix6/T-2591 (HIGH): реальные computed-цвета текста новых стеклянных
  // панелей (`.sidebar-link`/`.bottom-nav-label` 10px/`.more-item`/`header`).
  // Композит --glass-bg(.5)/--glass-bg-strong(.85) над худшей фазой фона
  // считается в `_panel_contrast_failures` (Python) → FAIL при <4.5:1.
  const panelTextColor = (sel) => {
    const el = document.querySelector(sel);
    return el ? getComputedStyle(el).color : null;
  };
  const panelText = {
    sidebarLink: panelTextColor('.sidebar-link'),
    bottomNavLabel: panelTextColor('.bottom-nav-label'),
    bottomNavActive: panelTextColor('.bottom-nav-link.active'),
    moreItem: panelTextColor('.more-sheet .more-item'),
    headerTitle: panelTextColor('.header-title-wrap .text-sm'),
    headerUser: panelTextColor('.header-scope-row .text-gray-300'),
  };
  // T-2585 (AMEND ADR-1025-12 D1): по каждому opt-in узлу A — выбранный tier
  // (`data-glass-tier`), причина и признак понижения. Микроуровень — feature-
  // detect в app.js, здесь фиксируем ФАКТ применения.
  const allow = Array.from(document.querySelectorAll('[data-glass="a"]'))
    .map((el) => {
      const r = el.getBoundingClientRect();
      return {
        minSide: Math.round(Math.min(r.width, r.height)),
        tier: el.getAttribute('data-glass-tier') || '',
        reason: el.getAttribute('data-glass-reason') || '',
        downgraded: el.hasAttribute('data-glass-downgraded'),
      };
    });
  // A2/T-2588…T-2590: стеклянные панели текущего выюпорта — blur-подложка.
  const panel = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return null;
    const st = getComputedStyle(el);
    return { bf: (st.backdropFilter || st.webkitBackdropFilter || '') };
  };
  return {
    tokens: {
      s0: tok('--surface-0'), s1: tok('--surface-1'), teal: tok('--teal-500'),
      warn: tok('--warn'), err: tok('--err'),
      gs: tok('--grad-speed'), gss: tok('--grad-speed-slow'),
      glassBg: tok('--glass-bg'), glassBgStrong: tok('--glass-bg-strong'),
      displace: tok('--glass-displace'),
      errText: tok('--err-text'),
    },
    beforeAnim: before.animationName,
    beforeDur: before.animationDuration,
    allow: allow,
    utility: utility,
    panelText: panelText,
    denyBf: bf(c),
    denyCount: document.querySelectorAll('[data-glass="c"]').length,
    panels: {
      sidebar: panel('.app-sidebar'), drawer: panel('.app-drawer'),
      header: panel('header.header-sticky'),
      bottomNav: panel('.bottom-nav'), moreSheet: panel('.more-sheet'),
    },
    hasLensFilter: !!document.getElementById('lg-lens'),
    headerH: tok('--header-h'),
    overflow: de.scrollWidth > window.innerWidth + 1,
  };
})()
"""

# §10/T-2547: пауза дорогих эффектов при document.hidden (через
# Object.defineProperty + dispatch — единственный обработчик в app.js).
HIDDEN_PROBE_JS = """
(() => {
  let cls = false, ap = '';
  try {
    Object.defineProperty(document, 'hidden',
      { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  } catch (e) {}
  cls = document.documentElement.classList.contains('lg-bg-paused');
  ap = getComputedStyle(document.body, '::before').animationPlayState;
  try {
    Object.defineProperty(document, 'hidden',
      { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
  } catch (e) {}
  return { cls: cls, ap: ap };
})()
"""

F2_RM_PROBE_JS = """
(() => {
  const before = getComputedStyle(document.body, '::before');
  return { beforeAnim: before.animationName, beforeDur: before.animationDuration };
})()
"""

# hotfix6/T-2591 (HIGH): `.more-item` существует только при ОТКРЫТОЙ шторке
# «Ещё» — отдельная проба рядом с открытием (тот же AA-композит).
MORE_ITEM_PROBE_JS = """
(() => {
  const de = document.documentElement;
  const tok = (n) => getComputedStyle(de).getPropertyValue(n).trim();
  const el = document.querySelector('.more-sheet .more-item');
  return {
    panelText: { moreItem: el ? getComputedStyle(el).color : null },
    tokens: { glassBg: tok('--glass-bg'), s0: tok('--surface-0'),
              teal: tok('--teal-500') },
  };
})()
"""


def _secs(raw: str):
    try:
        return float(str(raw).strip().rstrip("s"))
    except Exception:  # noqa: BLE001
        return None


# D-1/@Reviewer: худший (самый светлый) эффективный фон стекла-B —
# --glass-bg alpha .5 поверх wash §10 alpha .42 (teal-фаза) → rgb(27,62,69).
GLASS_EFF_WORST = (27, 62, 69)


def _lum_rgb(rgb) -> float:
    def f(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_rgb(a, b) -> float:
    l1, l2 = _lum_rgb(a), _lum_rgb(b)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _parse_rgb(s):
    m = re.match(r"rgba?\(([^)]+)\)", s or "")
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",")]
    try:
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:  # noqa: BLE001
        return None


def _parse_rgba(s):
    """rgba(...) → ([r,g,b], alpha); alpha по умолчанию 1."""
    m = re.match(r"rgba?\(([^)]+)\)", str(s or ""))
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",")]
    try:
        rgb = [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:  # noqa: BLE001
        return None
    try:
        a = float(parts[3]) if len(parts) > 3 else 1.0
    except Exception:  # noqa: BLE001
        a = 1.0
    return rgb, a


def _parse_color(s):
    """Поддержка `#RRGGBB` и `rgb()/rgba()`."""
    if not s:
        return None
    m = re.match(r"#([0-9a-fA-F]{6})$", str(s).strip())
    if m:
        h = m.group(1)
        return [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return _parse_rgb(s)


# hotfix6/T-2591 (HIGH): какие классы текста на какой подложке меряем AA.
_PANEL_TEXT_TARGETS = (
    ("sidebarLink", "glass"), ("bottomNavLabel", "glass"),
    ("bottomNavActive", "glass"), ("moreItem", "glass"),
    ("headerTitle", "strong"), ("headerUser", "strong"),
)


def _panel_contrast_failures(panel_text, tokens, label: str) -> list:
    """AA ≥4.5:1 для текста стеклянных панелей на КОМПОЗИТЕ подложки.

    Эффективный фон = `--glass-bg(.5)`/`--glass-bg-strong(.85)` поверх худшей
    (самой светлой) фазы анимированного фона §10 — teal `--grad-a` при opacity
    .42 над `--surface-0`. Это продолжение D-1 (та же worst-фаза, что у
    GLASS_EFF_WORST), но по реальным computed-цветам классов панелей."""
    out = []
    if not panel_text:
        return out
    s0 = _parse_color(tokens.get("s0"))
    phase = _parse_color(tokens.get("teal"))
    if s0 is None or phase is None:
        return out
    wash = [0.42 * p + 0.58 * b for p, b in zip(phase, s0)]
    bgs = {}
    for kind, key in (("glass", "glassBg"), ("strong", "glassBgStrong")):
        rgba = _parse_rgba(tokens.get(key))
        if rgba:
            base, a = rgba
            bgs[kind] = [a * c + (1 - a) * w for c, w in zip(base, wash)]
    for key, kind in _PANEL_TEXT_TARGETS:
        rgb = _parse_color(panel_text.get(key))
        bg = bgs.get(kind)
        if rgb is None or bg is None:
            continue
        ratio = _contrast_rgb(rgb, bg)
        if ratio < 4.5:
            out.append("%s AA: %s %r на %s-подложке = %.2f:1 (<4.5)"
                       % (label, key, panel_text.get(key), kind, ratio))
    return out


def _f2_failures(probe: dict, label: str) -> list:
    """F2 (T-2554): палитра §8 / длительности §10 / glass allow-deny."""
    out = []
    t = probe.get("tokens", {})
    expect = {"s0": "#090D17", "s1": "#151B2A", "teal": "#42D6C4",
              "warn": "#F6C56F", "err": "#F07178"}
    for k, v in expect.items():
        if (t.get(k) or "").upper() != v:
            out.append("%s палитра §8: --%s=%r (ожидалось %s)"
                       % (label, k, t.get(k), v))
    gs, gss = _secs(t.get("gs")), _secs(t.get("gss"))
    if gs is None or not (60.0 <= gs <= 90.0):
        out.append("%s фон §10: --grad-speed=%r вне [60,90]s" % (label, t.get("gs")))
    if gss is None or not (90.0 <= gss <= 120.0):
        out.append("%s фон §10: --grad-speed-slow=%r вне [90,120]s"
                   % (label, t.get("gss")))
    if "grad-spin" not in (probe.get("beforeAnim") or ""):
        out.append("%s фон: body::before без grad-spin (%r)"
                   % (label, probe.get("beforeAnim")))
    # T-2544/итерация @Reviewer: диапазоны из computed animationDuration
    # (без хардкода 75s/105s): основной 60–90 c, вторичный 90–120 c.
    durs = [float(s) for s in re.findall(r"([\d.]+)s", probe.get("beforeDur") or "")]
    if not any(60.0 <= s <= 90.0 for s in durs):
        out.append("%s фон §10: основной цикл не в [60,90]s (%r)"
                   % (label, probe.get("beforeDur")))
    if not any(90.0 <= s <= 120.0 for s in durs):
        out.append("%s фон §10: вторичный цикл не в [90,120]s (%r)"
                   % (label, probe.get("beforeDur")))
    if not probe.get("hasLensFilter"):
        out.append("%s glass: SVG-фильтр #lg-lens отсутствует" % label)
    displace = (t.get("displace") or "").replace(" ", "")
    if displace != "url(#lg-lens)":
        out.append("%s glass: --glass-displace=%r" % (label, displace))
    # T-2585 (AMEND ADR-1025-12 D1): tier выбирается feature-detect + перф-кап.
    # Фиксируем факт A и согласованность маркеров (нет tier=a с downgraded).
    allow = probe.get("allow") or []
    if not any(x.get("tier") for x in allow):
        out.append("%s glass allow: маркер data-glass-tier отсутствует "
                   "(reconcile не отработал)" % label)
    if not any(x.get("tier") == "a" for x in allow):
        out.append("%s glass allow: ни один [data-glass=\"a\"] не получил "
                   "tier A" % label)
    for x in allow:
        if x.get("tier") == "a" and x.get("downgraded"):
            out.append("%s glass allow: tier=a с data-glass-downgraded "
                       "(несогласованность)" % label)
    # A2 (T-2588…T-2591): стеклянные панели текущего вьюпорта несут blur
    # (непрозрачный fallback допустим только на движке без backdrop-filter).
    for name, box in (probe.get("panels") or {}).items():
        if box is None:
            continue
        if (box.get("bf") or "none").replace(" ", "") in ("none", ""):
            out.append("%s glass panel %s: нет backdrop-filter (ожидался blur)"
                       % (label, name))
    # D-1/@Reviewer: 12px-утилита Tailwind внутри стекла — контраст ≥4.5:1
    # на худшем эффективном фоне стекла.
    util_rgb = _parse_rgb(probe.get("utility"))
    if util_rgb is not None:
        ratio = _contrast_rgb(util_rgb, list(GLASS_EFF_WORST))
        if ratio < 4.5:
            out.append("%s D-1: .text-gray-500 в стекле %.2f:1 (<4.5) %r"
                       % (label, ratio, probe.get("utility")))
    # hotfix6/T-2591 (HIGH): AA-контраст текста стеклянных панелей.
    out.extend(_panel_contrast_failures(probe.get("panelText"), t, label))
    if probe.get("denyCount", 0) < 1:
        out.append("%s glass deny: нет [data-glass=\"c\"] на экране" % label)
    elif (probe.get("denyBf") or "none").replace(" ", "") not in ("none", ""):
        out.append("%s glass deny: backdrop-filter=%r (ожидалось none)"
                   % (label, probe.get("denyBf")))
    if probe.get("overflow"):
        out.append("%s F2: horizontal overflow" % label)
    return out


def _vertical_failures(probe: dict, label: str) -> list:
    """hotfix4 (T-2517): нижняя панель/шторка целиком в видимой области.

    Два инварианта: `rect.bottom <= innerHeight + 1` (layout-вьюпорт) и, при
    смоделированном системном баре Telegram, `rect.bottom <= stableHeight + 1`
    (именно этот инвариант ловил прод-дефект «панель под нижним баром»)."""
    out = []
    for name, box in (("bottom-nav", probe.get("bottomNav")),
                      ("more-sheet", probe.get("moreSheet"))):
        if not box or not box.get("visible"):
            continue
        if name == "more-sheet" and not probe.get("moreOpen"):
            continue                      # закрытая шторка уехала трансформом
        if box["bottom"] > probe["innerHeight"] + 1:
            out.append("%s: %s выходит за экран (bottom=%d > innerHeight=%d)"
                       % (label, name, box["bottom"], probe["innerHeight"]))
        if box["bottom"] > probe["stableHeight"] + 1:
            out.append("%s: %s ниже видимой области (bottom=%d > stable=%d)"
                       % (label, name, box["bottom"], probe["stableHeight"]))
    return out


def _scope_failures(probe: dict, label: str, width: int) -> list:
    """F3 (§5/§70): селектор области — постоянно доступный элемент.

    Проверяем, что при наличии ≥1 чата он реально виден; на mobile (<768)
    расположен ОТДЕЛЬНОЙ строкой под заголовком страницы и его тач-цель ≥44px."""
    out = []
    wrap = probe.get("scopeWrap")
    if not (wrap and wrap.get("visible")):
        out.append("%s: селектор области не виден (постоянная доступность §5)"
                   % label)
        return out
    if width < 768:
        title = probe.get("headerTitle")
        if title and title.get("visible") and wrap["y"] < title["bottom"] - 1:
            out.append("%s: mobile-селектор не под заголовком "
                       "(y=%d < title.bottom=%d)"
                       % (label, wrap["y"], title["bottom"]))
        trig = probe.get("scopeTrigger")
        if trig and trig.get("visible") and trig["h"] < 44:
            out.append("%s: тач-цель селектора %dpx < 44" % (label, trig["h"]))
    return out


def _hotfix6_failures(probe: dict, label: str) -> list:
    """hotfix6 (T-2598/T-2611): C1 — сердебиение в границах контейнера;
    D — кнопка ⛶ и селектор не выходят за вьюпорт."""
    out = []
    if probe.get("hbOverflow", 0) and probe["hbOverflow"] > 1:
        out.append("%s C1: overflow сердебиения %d px > 1"
                   % (label, probe["hbOverflow"]))
    wrap = probe.get("hbWrap")
    if wrap and wrap.get("visible"):
        if wrap["x"] < -1:
            out.append("%s C1: hb-wrap выходит влево (x=%d)" % (label, wrap["x"]))
        if wrap["x"] + wrap["w"] > probe["innerWidth"] + 1:
            out.append("%s C1: hb-wrap шире вьюпорта (%d > %d)"
                       % (label, wrap["x"] + wrap["w"], probe["innerWidth"]))
    if probe.get("fsBtnInViewport") is False:
        out.append("%s D: кнопка ⛶ выходит за вьюпорт" % label)
    return out


def _snap(page, name):
    try:
        page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=False)
    except Exception as e:  # noqa: BLE001
        print("[matrix] screenshot fail", name, e)


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    httpd = _start_server()
    out = {"viewports": {}, "console": [],
           "url": "http://127.0.0.1:%d/web/index.html" % PORT}
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for (w, h) in VIEWPORTS:
            ctx = browser.new_context(viewport={"width": w, "height": h})
            ctx.add_init_script(TMA_STUB)

            def _route(route):
                url = route.request.url
                if url.split("?")[0].endswith("/api/config"):
                    # F3: chat-scope (X-Chat-Id) получает конфиг с override,
                    # global — чистый (не путать источник значения).
                    hdrs = route.request.headers or {}
                    payload = (CONFIG_STUB_CHAT if hdrs.get("x-chat-id")
                               else CONFIG_STUB)
                else:
                    payload = _stub_for(url)
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))

            def _route_local(route):
                # F3: стенд локального админа (тот же конфиг с override).
                p = route.request.url.split("?")[0]
                if p.endswith("/api/me"):
                    payload = LOCAL_ADMIN_ME
                elif p.endswith("/api/access/me"):
                    payload = {"is_local_admin": True,
                               "permissions": {"sections": ["memory"]}}
                elif p.endswith("/api/config"):
                    hdrs = route.request.headers or {}
                    payload = (CONFIG_STUB_CHAT if hdrs.get("x-chat-id")
                               else CONFIG_STUB)
                else:
                    payload = _stub_for(route.request.url)
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))

            ctx.route("**/api/**", _route)
            page = ctx.new_page()
            vp_errors = []
            page.on("console", lambda m, b=vp_errors: (
                b.append("%s: %s" % (m.type, m.text[:200]))
                if m.type == "error" else None))
            page.on("pageerror", lambda e, b=vp_errors: b.append(
                "pageerror: " + str(e)[:300]))
            url = "http://127.0.0.1:%d/web/index.html" % PORT + "#/"
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector(".app-shell", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(700)
            # IA v2: shell-режим мог не пересчитаться после stub-me → ресайз.
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(300)
            # hotfix4 (T-2517): имитируем системный нижний бар Telegram —
            # visible (stable) высота = innerHeight − 56. Реальный
            # `telegram-web-app.js` определяет viewportStableHeight как
            # non-configurable getter (патч SDK невозможен), поэтому выставляем
            # ровно те CSS-переменные, которые клиент бы сообщил: так проверяем
            # РАСКЛАДКУ панели/шторки относительно видимой области (вычисление
            # переменных в telegram-init.js покрыто unit/JS-тестами).
            # hotfix4+hotfix6 (T-2517/T-2595, ADR-1025-8 D2 / ADR-1025-12 D3):
            # имитируем нижнюю «занятую» зону Telegram. Восстанавливаем
            # системный бар как РАЗНИЦУ видимой высоты (`stable = innerHeight−56`
            # → A=56), плюс contentSafeAreaInset.bottom=56 (B=56) — как клиент
            # сообщил бы эти переменные. Инвариант `rect.bottom <= stableHeight`
            # остаётся ЗНАЧАЩИМ: без offset-компенсации панель уходит за бар.
            # Логика max(A,B,C) отдельно покрыта JS-юнитом
            # (round1025_hotfix4_shell_test.js: A/B/C/max).
            if w < 768:
                page.evaluate(
                    "() => {"
                    "  var h = window.innerHeight || 0;"
                    "  var de = document.documentElement;"
                    "  de.style.setProperty('--tg-viewport-stable-height',"
                    "    Math.max(0, h - 56) + 'px');"
                    "  de.style.setProperty('--tg-content-safe-area-inset-bottom',"
                    "    '56px');"
                    "  de.style.setProperty('--tg-viewport-bottom-offset',"
                    "    '56px');"
                    "}")
                page.wait_for_timeout(150)

            vp_key = "%dx%d" % (w, h)
            out["viewports"][vp_key] = {"routes": {}}
            for route in ROUTES:
                page.evaluate("(r) => { window.location.hash = r; }", route)
                page.wait_for_timeout(350)
                probe = page.evaluate(PROBE_JS)
                out["viewports"][vp_key]["routes"][route] = probe
                if probe["overflow"]:
                    failures.append("%s %s: horizontal overflow %d > %d"
                                    % (vp_key, route, probe["scrollWidth"],
                                       probe["innerWidth"]))
                if w >= 1200:
                    if not (probe["sidebar"] and probe["sidebar"]["visible"]):
                        failures.append("%s %s: sidebar не виден (≥1200)"
                                        % (vp_key, route))
                    if probe["bottomNav"]:
                        failures.append("%s %s: bottom-nav не должен быть ≥1200"
                                        % (vp_key, route))
                elif w >= 768:
                    if probe["sidebar"] and probe["sidebar"]["visible"]:
                        failures.append("%s %s: sidebar не должен быть 768–1199"
                                        % (vp_key, route))
                    if probe["bottomNav"]:
                        failures.append("%s %s: bottom-nav не должен быть 768–1199"
                                        % (vp_key, route))
                else:
                    if not (probe["bottomNav"] and probe["bottomNav"]["visible"]):
                        failures.append("%s %s: нет bottom-nav (<768)"
                                        % (vp_key, route))
                    # hotfix4 (T-2522): админ hotfix4 = 4
                    # (Статус/Справка/Модули/Ещё); чистый user = 2;
                    # раздел-онли = 3 (Статус/Справка/Ещё).
                    if probe["bottomNavCount"] not in (0, 2, 3, 4):
                        failures.append("%s %s: bottom-nav=%d (ожидалось 2/3/4)"
                                        % (vp_key, route, probe["bottomNavCount"]))
                    if probe["sidebar"] and probe["sidebar"]["visible"]:
                        failures.append("%s %s: sidebar не должен быть <768"
                                        % (vp_key, route))
                    # hotfix4 (T-2517): вертикальные границы панели.
                    failures.extend(_vertical_failures(
                        probe, "%s %s" % (vp_key, route)))
                # F3 (§5/§70): позиция/размер селектора области.
                failures.extend(_scope_failures(
                    probe, "%s %s" % (vp_key, route), w))
                # hotfix6 (T-2598/T-2611): C1-overflow / ⛶ в вьюпорте.
                failures.extend(_hotfix6_failures(
                    probe, "%s %s" % (vp_key, route)))
                if route == "#/":
                    _snap(page, "%s_root" % vp_key)
                if route == "#/memory":
                    _snap(page, "%s_memory" % vp_key)
            # F2 (T-2554): F2-пробы на корневой Статус-вкладке (палитра/фон/
            # glass allow-deny), затем пауза при document.hidden (§10/T-2547).
            page.evaluate("() => { window.location.hash = '#/'; }")
            page.wait_for_timeout(350)
            f2 = page.evaluate(F2_PROBE_JS)
            out["viewports"][vp_key]["f2"] = f2
            failures.extend(_f2_failures(f2, vp_key))
            hid = page.evaluate(HIDDEN_PROBE_JS)
            out["viewports"][vp_key]["hidden"] = hid
            if not hid.get("cls") or hid.get("ap") != "paused":
                failures.append("%s hidden: фон не на паузе (cls=%s, play=%s)"
                                % (vp_key, hid.get("cls"), hid.get("ap")))
            # F3 (§5/§43, reviewer Critical+High): область ЧАТА с РЕАЛЬНЫМ
            # override — источник значения, §43-пометка и кнопка возврата к
            # глобальному рендерятся; нет горизонтального overflow на узких
            # ширинах (320/360/390) и на desktop (1280).
            if (w, h) in ((320, 700), (360, 780), (390, 844), (1280, 800)):
                page.evaluate(
                    "() => localStorage.setItem('adminbot.active_chat_id',"
                    "  '-1001234567890')")
                page.reload(wait_until="load")
                try:
                    page.wait_for_selector(".app-shell", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(400)
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(200)
                page.evaluate("() => { window.location.hash = '#/memory/rag'; }")
                page.wait_for_timeout(900)
                chat_probe = page.evaluate(PROBE_JS)
                out["viewports"][vp_key]["chat_scope"] = chat_probe
                if chat_probe["overflow"]:
                    failures.append(
                        "%s chat-scope: horizontal overflow %d > %d"
                        % (vp_key, chat_probe["scrollWidth"],
                           chat_probe["innerWidth"]))
                failures.extend(_scope_failures(
                    chat_probe, "%s chat-scope" % vp_key, w))
                chat_txt = page.evaluate("() => document.body.innerText")
                btn = page.evaluate(
                    "() => !!document.querySelector("
                    "'button[aria-label=\"Вернуть глобальное значение\"]')")
                seen = {
                    "src": "Источник:" in chat_txt,
                    "notice": ("Локально включено, хотя глобально выключено"
                               in chat_txt),
                    "button": bool(btn),
                }
                out["viewports"][vp_key]["chat_scope_ui"] = seen
                if not seen["src"]:
                    failures.append(
                        "%s chat-scope: нет подписи «Источник:» (§5)" % vp_key)
                if not seen["notice"]:
                    failures.append(
                        "%s chat-scope: нет §43-пометки о расхождении" % vp_key)
                if not seen["button"]:
                    failures.append(
                        "%s chat-scope: нет кнопки «Вернуть глобальное»" % vp_key)
            # F3 (reviewer 2): local_admin — кнопка возврата к глобальному
            # видна (паритет UI↔сервер) и не даёт overflow на 320/360/390.
            if w in (320, 360, 390):
                la_ctx = browser.new_context(
                    viewport={"width": w, "height": h})
                la_ctx.add_init_script(TMA_STUB)
                la_ctx.add_init_script(
                    "() => localStorage.setItem('adminbot.active_chat_id',"
                    " '-1001234567890')")
                la_ctx.route("**/api/**", _route_local)
                la_page = la_ctx.new_page()
                la_errors = []
                la_page.on("console", lambda m, b=la_errors: (
                    b.append("%s: %s" % (m.type, m.text[:200]))
                    if m.type == "error" else None))
                la_page.on("pageerror", lambda e, b=la_errors: b.append(
                    "pageerror: " + str(e)[:300]))
                la_page.goto(url, wait_until="load")
                try:
                    la_page.wait_for_selector(".app-shell", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                la_page.wait_for_timeout(500)
                la_page.evaluate(
                    "() => { window.location.hash = '#/memory/rag'; }")
                la_page.wait_for_timeout(900)
                la_probe = la_page.evaluate(PROBE_JS)
                out["viewports"][vp_key]["local_admin"] = la_probe
                if la_probe["overflow"]:
                    failures.append(
                        "%s local_admin: horizontal overflow %d > %d"
                        % (vp_key, la_probe["scrollWidth"],
                           la_probe["innerWidth"]))
                la_btn = bool(la_page.evaluate(
                    "() => !!document.querySelector("
                    "'button[aria-label=\"Вернуть глобальное значение\"]')"))
                out["viewports"][vp_key]["local_admin_button"] = la_btn
                if not la_btn:
                    failures.append(
                        "%s local_admin: нет кнопки «Вернуть глобальное»"
                        % vp_key)
                for msg in la_errors:
                    failures.append("%s local_admin console/pageerror: %s"
                                    % (vp_key, msg))
                la_ctx.close()
            # F2 (T-2548): prefers-reduced-motion → animation-name: none.
            if (w, h) == VIEWPORTS[0]:
                rm_ctx = browser.new_context(
                    viewport={"width": w, "height": h}, reduced_motion="reduce")
                rm_ctx.add_init_script(TMA_STUB)
                rm_ctx.route("**/api/**", _route)
                rm_page = rm_ctx.new_page()
                rm_page.goto(url, wait_until="load")
                try:
                    rm_page.wait_for_selector(".app-shell", timeout=8000)
                except Exception:  # noqa: BLE001
                    pass
                rm_page.wait_for_timeout(500)
                rm_page.evaluate("() => { window.location.hash = '#/'; }")
                rm_page.wait_for_timeout(350)
                rm_probe = rm_page.evaluate(F2_RM_PROBE_JS)
                out["viewports"][vp_key]["reduced_motion"] = rm_probe
                if rm_probe.get("beforeAnim") not in ("none", ""):
                    failures.append("%s reduced-motion: animationName=%r"
                                    % (vp_key, rm_probe.get("beforeAnim")))
                rm_ctx.close()
            # hotfix4 (T-2517): шторка «Ещё» — вертикаль ПРИ ОТКРЫТИИ.
            if w < 768:
                try:
                    btn = page.query_selector('.bottom-nav-link[title="Ещё"]')
                    if btn:
                        btn.click()
                        page.wait_for_timeout(300)
                        probe_more = page.evaluate(PROBE_JS)
                        failures.extend(_vertical_failures(
                            probe_more, "%s more-sheet(open)" % vp_key))
                        # T-2591: AA-контраст текста шторки (`.more-item`).
                        more_txt = page.evaluate(MORE_ITEM_PROBE_JS)
                        failures.extend(_panel_contrast_failures(
                            more_txt.get("panelText"), more_txt.get("tokens"),
                            "%s more-sheet(open)" % vp_key))
                except Exception as exc:  # noqa: BLE001
                    failures.append("%s more-sheet probe: %s"
                                    % (vp_key, str(exc)[:200]))
            # P0-инцидент F1: render-ошибки (console.error/pageerror) — FAIL,
            # иначе класс «раздел пуст, но метрики чистые» не ловится.
            for msg in vp_errors:
                failures.append("%s console/pageerror: %s" % (vp_key, msg))
            out["console"].extend("%s %s" % (vp_key, m) for m in vp_errors)
            print("[matrix] %-9s root: scrollW=%d innerW=%d sidebar=%s "
                  "bottomNav=%s(%d)" % (
                      vp_key, out["viewports"][vp_key]["routes"]["#/"]["scrollWidth"],
                      w,
                      bool(out["viewports"][vp_key]["routes"]["#/"]["sidebar"]),
                      bool(out["viewports"][vp_key]["routes"]["#/"]["bottomNav"]),
                      out["viewports"][vp_key]["routes"]["#/"]["bottomNavCount"]))
            ctx.close()
        browser.close()

    httpd.shutdown()
    out["failures"] = failures
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("[matrix] failures:", len(failures))
    for f_ in failures:
        print("  !", f_)
    print("[matrix] артефакты:", RAW, "+", SHOTS)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
