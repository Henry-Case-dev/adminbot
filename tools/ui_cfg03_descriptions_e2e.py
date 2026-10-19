# -*- coding: utf-8 -*-
"""CFG-03 — Playwright e2e честной витрины и UI-покрытия (Ф4).

Проверяет на реальных `web/index.html` + `web/app.js` (стабы `/api/*` из
`tools/ui_round1025_matrix.py`; `/api/config` собирается из РЕАЛЬНОГО
`services/param_catalog.py` — описания живые):

  * CFG-03.6 — «мёртвые ручки» показываются честно: описания
    `limits.chat_budget_response_ratio` / `limits.chat_lock_max_entries` /
    `limits.dig_year_back_window_days` /
    `limits.youtube_transcript_proxy_locations` / `..._retries` содержат
    «Не влияет» (вкладка «Память» и модалки модулей «Ответы в чате» /
    «Выжимка видео»); `limits.memory_backup_keep` — «НЕ действует»;
  * CFG-03.1 — `content_media` (tab=None) реально рендерится
    synthetic-группой в окне Модуля 6 («Выжимка видео»): карточки
    «Медиа-шара» с `MEDIA_SHARE_DIR`/`MEDIA_PUBLIC_BASE_URL` — UI_missing=0;
  * мобильный 390px: те же факты видны, горизонтального оверфлоу нет;
  * консоль без ошибок.

Запуск: .venv\\Scripts\\python.exe tools\\ui_cfg03_descriptions_e2e.py
Артефакты: plans/features/cfg/evidence/cfg-03/ui/ + e2e-log.json
"""
import json
import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/стабы/TMA — reuse)

PORT = 8845
EVID = os.path.join(REPO, "plans", "features", "cfg", "evidence", "cfg-03")
SHOTS = os.path.join(EVID, "ui")
RAW = os.path.join(EVID, "e2e-log.json")

HONEST_MARK = "Не влияет"
DEAD_KEYS = [
    "limits.chat_budget_response_ratio",
    "limits.chat_lock_max_entries",
    "limits.dig_year_back_window_days",
    "limits.youtube_transcript_proxy_locations",
    "limits.youtube_transcript_proxy_retries",
]
DEAD_TITLES = {
    "limits.chat_budget_response_ratio": "Доля бюджета: Response",
    "limits.chat_lock_max_entries": "Потолок словаря замков",
    "limits.youtube_transcript_proxy_locations": "CSV-коды стран Webshare",
    "limits.youtube_transcript_proxy_retries": "Повторы при блокировке (Webshare)",
    "limits.dig_year_back_window_days": "dig_into_lore: окно «N лет назад», дней",
}

# JS: карточка по точному тексту ключа (generic config-вкладка).
CARD_BY_KEY_JS = """
(a) => {
  const gid = a.gid, key = a.key;
  const g = document.querySelector('[data-config-group="' + gid + '"]');
  if (!g) return { group: false, gid: gid };
  const leaves = Array.from(g.querySelectorAll('div'))
    .filter(d => d.children.length === 0);
  const keyEl = leaves.find(d => (d.textContent || '').trim() === key);
  if (!keyEl) return { group: true, card: false };
  let card = keyEl;
  while (card.parentElement && card.parentElement !== g
         && card.parentElement.className.indexOf('grid') < 0) {
    card = card.parentElement;
  }
  return { group: true, card: true,
           text: (card.innerText || '').replace(/\\s+/g, ' ').trim() };
}
"""

# JS: карточка в модалке модуля по точному тексту заголовка.
CARD_BY_TITLE_JS = """
(title) => {
  const root = document.querySelector('.modal-body');
  if (!root) return { modal: false };
  const leaves = Array.from(root.querySelectorAll('div'))
    .filter(d => d.children.length === 0);
  const t = leaves.find(d => (d.textContent || '').trim() === title);
  if (!t) return { modal: true, card: false };
  let card = t;
  while (card.parentElement && card.parentElement !== root
         && card.parentElement.className.indexOf('grid') < 0) {
    card = card.parentElement;
  }
  return { modal: true, card: true,
           text: (card.innerText || '').replace(/\\s+/g, ' ').trim() };
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


def _api_handler(route):
    """/api/* — стабы матрицы (config собирается из реального каталога)."""
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(M._stub_for(route.request.url),
                                  ensure_ascii=False))


def _expand_advanced(page) -> None:
    page.evaluate(
        "(() => { document.querySelectorAll('summary').forEach(s => {"
        "  if ((s.textContent || '').indexOf('Расширенные') >= 0) {"
        "    const d = s.closest('details'); if (d) d.open = true; } }); })()")
    page.wait_for_timeout(400)


def _serve_only() -> int:
    """Режим визуальной проверки (Browser Use): статика + серверные стабы."""
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

        def do_POST(self):                  # noqa: N802
            self._json({"updated": []})

        def do_GET(self):                   # noqa: N802
            if self.path.split("?")[0].startswith("/api/"):
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
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    os.makedirs(SHOTS, exist_ok=True)

    from playwright.sync_api import sync_playwright
    result = {"console_errors": [], "checks": {}, "screenshots": []}
    checks = result["checks"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000},
                                  reduced_motion="reduce")
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        page.goto(base, wait_until="load")
        page.wait_for_timeout(1600)

        # ── 1. Вкладка «Память» (#/memory/rag): честные описания ──────────
        # Презентационные подгруппы памяти (app.js::_memorySubgroupOf):
        # DIG_* → 'search', MEMORY_BACKUP → 'storage'.
        page.evaluate("window.location.hash = '#/memory/rag'")
        page.wait_for_timeout(1200)
        try:
            page.wait_for_selector('[data-config-group]', timeout=10000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(800)
        _expand_advanced(page)
        for gid, key in (("search", "limits.dig_year_back_window_days"),
                         ("storage", "limits.memory_backup_keep")):
            card = page.evaluate(CARD_BY_KEY_JS, {"gid": gid, "key": key})
            checks["memory_%s" % key] = card
        shot = os.path.join(SHOTS, "01-memory-honest-desc.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # ── 2. Модалка «Ответы в чате»: честные описания ──────────────────
        # Модалка модуля рендерится на вкладке «Модули» (activeTab=modules).
        page.evaluate("window.location.hash = '#/modules'")
        page.wait_for_timeout(1200)
        page.evaluate(OPEN_MODULE_JS, "mod_direct")
        page.wait_for_timeout(1200)
        for key in ("limits.chat_lock_max_entries",
                    "limits.chat_budget_response_ratio"):
            checks["direct_%s" % key] = page.evaluate(
                CARD_BY_TITLE_JS, DEAD_TITLES[key])
        shot = os.path.join(SHOTS, "02-module-direct-honest-desc.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # ── 3. Модалка «Выжимка видео»: youtube-proxy + content_media ─────
        page.evaluate(OPEN_MODULE_JS, "mod_video_summary")
        page.wait_for_timeout(1200)
        for key in ("limits.youtube_transcript_proxy_locations",
                    "limits.youtube_transcript_proxy_retries"):
            checks["video_%s" % key] = page.evaluate(
                CARD_BY_TITLE_JS, DEAD_TITLES[key])
        checks["video_content_media_group"] = page.evaluate(
            "(() => { const root = document.querySelector('.modal-body');"
            " if (!root) return { modal: false };"
            " const t = Array.from(root.querySelectorAll('div'))"
            "   .filter(d => d.children.length === 0)"
            "   .find(d => (d.textContent || '').trim() === 'Медиа-шара');"
            " if (!t) return { modal: true, group: false };"
            " const txt = (root.innerText || '');"
            " return { modal: true, group: true,"
            "   share: txt.indexOf('Каталог временной публикации видео') >= 0,"
            "   public: txt.indexOf('Внешний базовый адрес /media') >= 0 };"
            "})()")
        shot = os.path.join(SHOTS, "03-module-video-content-media.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        # ── 4. Мобильный 390px: тот же факт виден, оверфлоу нет ───────────
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(900)
        checks["mobile_content_media_visible"] = page.evaluate(
            "(() => { const root = document.querySelector('.modal-body');"
            " if (!root) return false;"
            " const t = Array.from(root.querySelectorAll('div'))"
            "   .filter(d => d.children.length === 0)"
            "   .find(d => (d.textContent || '').trim() === 'Медиа-шара');"
            " if (!t) return false; const r = t.getBoundingClientRect();"
            " return r.width > 0 && r.height > 0; })()")
        checks["mobile_no_overflow"] = page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 2")
        shot = os.path.join(SHOTS, "04-mobile-content-media.png")
        page.screenshot(path=shot, full_page=True)
        result["screenshots"].append(shot)

        browser.close()

    os.makedirs(EVID, exist_ok=True)
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k != "screenshots"}, ensure_ascii=False, indent=2))

    def honest(name, key):
        card = checks.get(name) or {}
        return bool(card.get("card")) and HONEST_MARK in str(card.get("text"))

    ok = (
        not result["console_errors"]
        and honest("memory_limits.dig_year_back_window_days",
                   "limits.dig_year_back_window_days")
        and "НЕ действует" in str(
            (checks.get("memory_limits.memory_backup_keep") or {}).get("text"))
        and honest("direct_limits.chat_lock_max_entries",
                   "limits.chat_lock_max_entries")
        and honest("direct_limits.chat_budget_response_ratio",
                   "limits.chat_budget_response_ratio")
        and honest("video_limits.youtube_transcript_proxy_locations",
                   "limits.youtube_transcript_proxy_locations")
        and honest("video_limits.youtube_transcript_proxy_retries",
                   "limits.youtube_transcript_proxy_retries")
        and bool((checks.get("video_content_media_group") or {}).get("group"))
        and bool((checks.get("video_content_media_group") or {}).get("share"))
        and bool((checks.get("video_content_media_group") or {}).get("public"))
        and checks.get("mobile_content_media_visible") is True
        and checks.get("mobile_no_overflow") is True
    )
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--serve" in sys.argv:
        raise SystemExit(_serve_only())
    raise SystemExit(main())
