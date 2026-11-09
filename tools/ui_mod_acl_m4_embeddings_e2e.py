"""MOD-ACL-UX-01 M4 — страница «Векторная память»: реальные параметры и честная пустота.

Детерминированный Playwright-прогон НАСТОЯЩИХ `web/index.html` + `web/app.js`
на локальном http-сервере (Telegram не задействован: синтетическая
TMA-идентичность из `tools/ui_round1025_matrix.py`, `/api/*` перехватываются).
Один прогон показывает ОБА состояния на одном и том же маршруте
`#/modules/embeddings` в 1280x900:

  * **база** (`--base`, по умолчанию `dd52cbf9`) — дерево `web/` достаётся из
    git через `git archive` во временный каталог; ожидаем дефект владельца:
    одна вкладка «Обзор» + блок «нет доступных параметров / сервер
    отфильтровал их по правам» при глобальном админе;
  * **кандидат** (рабочее дерево) — вкладки «Обзор» + «Основные настройки»,
    две РЕАЛЬНЫЕ группы каталога (models_embeddings 16 + keys_llm 9 = 25),
    без ложного упоминания прав; поиск сужает до одного параметра.

`/api/config` собирается из `services/param_catalog.py` (все непустые
категории; секреты — `{configured,last4}`, как маскирует продукт) и содержит
`modules = registry_for_frontend()`, иначе карточки инфраструктурного модуля
на витрине нет. Идентичность — синтетический ГЛОБАЛЬНЫЙ админ (`/api/me`
`is_global_admin: true` + `/api/access/me`), поэтому область — GLOBAL, как на
снимке владельца.

Проверяемые DOM-контракты (кандидат):
  1. список вкладок: `['overview', 'settings']` (пустых вкладок нет);
  2. две группы «Основные настройки» с каталоговыми заголовками и количеством
     параметров 16 + 9 = 25;
  3. в тексте страницы НЕТ формулировки про фильтр прав;
  4. поиск «embedding_dim» сужает до одного параметра (внутри набора групп);
  5. четыре честные причины пустого блока выбираются по фактическому
     состоянию: `no-data` / `scope` / `filtered` / `none` — и слова про права
     появляются ТОЛЬКО в `filtered` (проверяется на реальном DOM).

Запуск (одна команда, ничего доустанавливать не нужно):

    py -3 tools\\ui_mod_acl_m4_embeddings_e2e.py

  --out DIR    куда писать артефакты (по умолчанию docs/evidence/mod-acl-ux-01-m4)
  --base SHA   коммит-база для сравнения «до» (по умолчанию dd52cbf9)
  --keep       не удалять временное дерево базы (для ручного разбора)
  --serve-only поднять стенд и ждать: для ручного осмотра в своём браузере
               (в консоли нужен TMA-стаб — команда печатается; без него
               страница честно скажет «Миниапп открыт без Telegram-контекста»)

Артефакты: m4-embeddings-e2e.json + PNG-снимки обоих состояний.
Маркер успеха: `MOD-ACL-M4-EMBEDDINGS OK` (код возврата 0).

Примечание: Browser Use для этого доказательства НЕ требуется. Если в
окружении ревьюера он падает на постороннем модуле (`oci` — Oracle SDK, к
проекту отношения не имеет), доказательством служат снимки и DOM-набор этого
скрипта: он запускает тот же Chromium локально.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (TMA_STUB/ME_JSON/стабы)

DEFAULT_BASE = "dd52cbf9"
DEFAULT_OUT = os.path.join(REPO, "docs", "evidence", "mod-acl-ux-01-m4")
ROUTE = "#/modules/embeddings"
ROUTE_SETTINGS = "#/modules/embeddings/settings"
EMB_GROUP = "models_embeddings"
KEYS_GROUP = "keys_llm"
EXPECT_EMB = 16
EXPECT_KEYS = 9
GLOBAL_ME_ACCESS = {"is_local_admin": False, "is_global_admin": True,
                    "permissions": {"wildcard": True}}
# Роль без глобального админа, но с доступом к разделу «Модули»
# (`canViewTab('modules')` = section.reactions) — на ней проверяется честная
# причина `filtered`: страница открыта, сервер не отдал секретные параметры.
MODULES_USER_ME = {"telegram_id": 7711771, "username": "u", "first_name": "U",
                   "role_name": "участник", "permissions": {
                       "sections": ["reactions"]},
                   "is_custom": False, "is_global_admin": False,
                   "ui_flags": dict(M.ME_JSON["ui_flags"])}


# ── сервер ────────────────────────────────────────────────────────────────
class _Handler(SimpleHTTPRequestHandler):
    root = REPO

    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0].split("#")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p.startswith("/web/"):
            rel = p[1:]
        elif p in ("/", "", "/index.html"):
            rel = "web/index.html"
        else:
            rel = p.lstrip("/")
        return os.path.join(self.root, rel.replace("/", os.sep))

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def _serve(root, port):
    cls = type("H", (_Handler,), {"root": root})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), cls)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ── полезная нагрузка /api/config ─────────────────────────────────────────
def _config_payload():
    """`/api/config` из реального каталога + реестр модулей."""
    from services.module_registry import registry_for_frontend
    payload = {"items": M.CONFIG_STUB["items"],
               "groups": M.CONFIG_STUB["groups"],
               "modules": registry_for_frontend()}
    emb = [i for i in payload["items"] if i["group"] == EMB_GROUP]
    keys = [i for i in payload["items"] if i["group"] == KEYS_GROUP]
    assert len(emb) == EXPECT_EMB, (
        "каталог изменился: models_embeddings=%d (ожидалось %d)"
        % (len(emb), EXPECT_EMB))
    assert len(keys) == EXPECT_KEYS, (
        "каталог изменился: keys_llm=%d (ожидалось %d)"
        % (len(keys), EXPECT_KEYS))
    assert all(isinstance(i["value"], dict) for i in keys if i["secret"]), (
        "секреты обязаны быть маскированы ({configured,last4})")
    return payload


def _routes_factory(payload):
    def routes(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/config"):
            body = payload
        elif url.endswith("/api/me"):
            body = M.ME_JSON
        elif url.endswith("/api/access/me"):
            body = GLOBAL_ME_ACCESS
        else:
            body = M._stub_for(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body))
    return routes


# ── DOM-пробы ─────────────────────────────────────────────────────────────
PROBE = r"""
() => {
  const txt = (el) => ((el && el.textContent) || '').trim();
  const tabs = Array.from(document.querySelectorAll('[data-workspace-tab]'))
    .map((b) => ({id: b.getAttribute('data-workspace-tab'),
                  label: txt(b)}));
  const groups = Array.from(document.querySelectorAll('[data-config-group]'))
    .map((g) => ({id: g.getAttribute('data-config-group'),
                  title: txt(g.querySelector(
                    'summary, .font-semibold, .text-sm')).slice(0, 60),
                  items: g.querySelectorAll('[data-cfg-key]').length}));
  const empty = document.querySelector('[data-empty-tab]');
  return {
    hash: window.location.hash,
    scope: txt(document.querySelector('[data-workspace-scope]')),
    tabs: tabs,
    groups: groups,
    items: groups.reduce((n, g) => n + g.items, 0),
    empty: empty ? {
      title: txt(empty.querySelector('.font-semibold')),
      reason: txt(empty.querySelector('.text-xs')),
      cause: empty.getAttribute('data-empty-cause'),
    } : null,
    text: document.body.innerText.replace(/\s+/g, ' '),
    searchVisible: !!document.querySelector('[data-config-search] input'),
  };
}
"""

PROXY_JS = ("document.querySelector('#app').__vue_app__._container"
            "._vnode.component.proxy")

# Сценарии четырёх честных причин: каждое состояние создаётся изменением
# РЕАЛЬНОГО состояния компонента (как если бы сервер/роль/область отличались),
# затем читается отрендеренный блок пустой вкладки.
CAUSE_SCENARIOS = {
    "none": r"""
      (p) => { window.__m4reg = window.__m4reg || p._f4Registry;
                p._f4Registry = {};
                p.configItems = p.configItems.slice(); }
    """,
    "no-data": "(p) => { p.configItems = []; }",
    "scope": r"""
      (p) => { p._f4Registry = {};
                p.configItems = p.configItems.slice();
                p.activeChatId = -1001234567890; }
    """,
    "filtered": r"""
      (p) => { p._f4Registry = window.__m4reg || p._f4Registry;
                p.me = %s;
                p.activeChatId = null;
                p.configItems = p.configItems
                  .filter((i) => i.group !== '%s' && i.group !== '%s')
                  .slice(); }
    """ % (json.dumps(MODULES_USER_ME), EMB_GROUP, KEYS_GROUP),
}


def _uuid_ok(conds, fails, label):
    for cond, msg in conds:
        if not cond:
            fails.append("%s: %s" % (label, msg))
        yield cond


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--serve-only", action="store_true",
                    help="поднять стенд кандидата и ждать (для ручного/иного "
                         "браузерного осмотра; Ctrl+C — остановить)")
    args = ap.parse_args()
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    if args.serve_only:
        payload = _config_payload()
        httpd = _serve(REPO, 8871)
        print("стенд: http://127.0.0.1:8871/web/index.html%s" % ROUTE)
        print("без TMA-стаба страница покажет «Миниапп открыт без "
              "Telegram-контекста» — в консоли браузера выполните:\n%s"
              % M.TMA_STUB)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.shutdown()
        return 0

    from playwright.sync_api import sync_playwright

    fails = []
    report = {"base": args.base, "route": ROUTE, "viewports": {},
              "payload": {}, "checks": {}, "builds": {}}

    payload = _config_payload()
    report["payload"] = {
        "items_total": len(payload["items"]),
        "models_embeddings": len([i for i in payload["items"]
                                  if i["group"] == EMB_GROUP]),
        "keys_llm": len([i for i in payload["items"]
                         if i["group"] == KEYS_GROUP]),
        "modules": len(payload["modules"]),
    }

    # ── дерево `web/` базового коммита (без правки рабочего дерева) ───────
    tmp = tempfile.mkdtemp(prefix="m4_base_")
    base_tree = os.path.join(tmp, "base")
    zip_path = os.path.join(tmp, "base.zip")
    res = subprocess.run(["git", "archive", "--format=zip",
                          "--output=" + zip_path, args.base, "web"],
                         cwd=REPO, capture_output=True)
    if res.returncode != 0:
        print("git archive упал: " + res.stderr.decode("utf-8", "replace"))
        return 2
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(base_tree)

    srv_head = _serve(REPO, 8871)
    srv_base = _serve(base_tree, 8872)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--disable-lcd-text"])

            def open_page(port):
                ctx = browser.new_context(viewport={"width": 1280,
                                                    "height": 900})
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**", _routes_factory(payload))
                page = ctx.new_page()
                page.errors = []
                page.on("pageerror",
                        lambda e: page.errors.append(str(e)[:300]))
                page.goto("http://127.0.0.1:%d/web/index.html%s"
                          % (port, ROUTE), wait_until="load")
                page.wait_for_selector(".app-shell", timeout=20000)
                page.wait_for_function(
                    "() => { const el = document.querySelector('#app');"
                    " const app = el && el.__vue_app__;"
                    " const c = app && app._container;"
                    " return !!(c && c._vnode && c._vnode.component"
                    " && c._vnode.component.proxy); }", timeout=15000)
                page.wait_for_timeout(800)
                return ctx, page

            # ═══ БАЗА: дефект владельца на том же маршруте ═══════════════
            ctx, page = open_page(8872)
            base = page.evaluate(PROBE)
            report["builds"]["base"] = base
            page.screenshot(path=os.path.join(
                out_dir, "m4-embeddings-1280x900-base.png"))
            _uuid_ok([
                ([t["id"] for t in base["tabs"]] == ["overview"],
                 "ожидалась одна вкладка «Обзор»"),
                (base["items"] == 0, "ожидалось 0 параметров"),
                (bool(base["empty"]), "ожидался блок пустой вкладки"),
                (bool(base["empty"]) and "по правам" in base["empty"]["reason"],
                 "ожидалась ложная причина «по правам» (дефект владельца)"),
            ], fails, "base")
            ctx.close()

            # ═══ КАНДИДАТ: обзор + настройки ═════════════════════════════
            ctx, page = open_page(8871)
            head = page.evaluate(PROBE)
            report["builds"]["head_overview"] = head
            page.screenshot(path=os.path.join(
                out_dir, "m4-embeddings-1280x900-head-overview.png"))
            _uuid_ok([
                (head["scope"] == "GLOBAL", "область — GLOBAL (как у владельца)"),
                ([t["id"] for t in head["tabs"]] == ["overview", "settings"],
                 "вкладки: Обзор + Основные настройки, без пустых"),
                (head["empty"] is None,
                 "на «Обзоре» нет ложного пустого блока"),
                ("по правам" not in head["text"],
                 "на странице нет формулировки про фильтр прав"),
            ], fails, "head/overview")

            page.evaluate(
                "() => document.querySelector("
                "'[data-workspace-tab=\"settings\"]').click()")
            page.wait_for_timeout(700)
            settings = page.evaluate(PROBE)
            report["builds"]["head_settings"] = settings
            page.screenshot(path=os.path.join(
                out_dir, "m4-embeddings-1280x900-head-settings.png"))
            got = {g["id"]: g for g in settings["groups"]}
            _uuid_ok([
                (list(got) == [KEYS_GROUP, EMB_GROUP],
                 "группы в порядке каталога: keys_llm, models_embeddings"),
                (got.get(EMB_GROUP, {}).get("title")
                 == "Отпечатки текста и длина", "каталоговый заголовок emb"),
                (got.get(KEYS_GROUP, {}).get("title") == "Основная нейросеть",
                 "каталоговый заголовок ключей"),
                (got.get(EMB_GROUP, {}).get("items") == EXPECT_EMB,
                 "models_embeddings: %d параметров" % EXPECT_EMB),
                (got.get(KEYS_GROUP, {}).get("items") == EXPECT_KEYS,
                 "keys_llm: %d ключей" % EXPECT_KEYS),
                (settings["items"] == EXPECT_EMB + EXPECT_KEYS,
                 "всего на вкладке 25 параметров"),
                (settings["searchVisible"], "поиск по параметрам доступен"),
                ("по правам" not in settings["text"],
                 "нет ложного упоминания прав"),
                (not page.errors, "без JS-ошибок: %s" % page.errors),
            ], fails, "head/settings")

            # ═══ поиск внутри набора групп ═══════════════════════════════
            page.fill("[data-config-search] input", "embedding_dim")
            page.wait_for_timeout(600)
            search = page.evaluate(PROBE)
            report["checks"]["search"] = search
            page.screenshot(path=os.path.join(
                out_dir, "m4-embeddings-1280x900-head-search.png"))
            _uuid_ok([
                (len(search["groups"]) == 1
                 and search["groups"][0]["id"] == EMB_GROUP,
                 "поиск «embedding_dim» оставляет одну группу"),
                (search["items"] == 1, "поиск сужает до одного параметра"),
                (search["empty"] is None, "поиск не подменяется пустым блоком"),
            ], fails, "head/search")
            ctx.close()

            # ═══ четыре честные причины пустого блока ════════════════════
            causes = {}
            for name, js in CAUSE_SCENARIOS.items():
                ctx, page = open_page(8871)
                page.evaluate("(js) => { const p = %s;"
                              " p.configItems = p.configItems.slice();"
                              " (new Function('p', 'return (' + js + ')(p)'))(p); }"
                              % PROXY_JS, js)
                page.wait_for_timeout(700)
                probe = page.evaluate(PROBE)
                causes[name] = probe["empty"]
                if name == "filtered":
                    page.screenshot(path=os.path.join(
                        out_dir, "m4-embeddings-1280x900-head-empty-filtered.png"))
                ctx.close()
            report["checks"]["empty_causes"] = causes
            for name, want_cause in (("none", "none"), ("no-data", "no-data"),
                                     ("scope", "scope"),
                                     ("filtered", "filtered")):
                blink = causes.get(name)
                _uuid_ok([
                    (bool(blink), "сценарий %s: блок пустой вкладки отрисован"
                     % name),
                    (bool(blink) and blink["cause"] == want_cause,
                     "сценарий %s: причина в DOM = %s" % (name, want_cause)),
                ], fails, "cause/" + name)
            # «по правам» — ТОЛЬКО когда фильтр прав реально сработал.
            for name, blink in causes.items():
                text = ((blink or {}).get("reason") or "")
                rights = "по правам" in text or "отфильтровал" in text
                if name == "filtered":
                    if not rights:
                        fails.append("cause/filtered: нет честного упоминания "
                                     "фильтра прав")
                elif rights:
                    fails.append("cause/%s: ложное упоминание прав: %s"
                                 % (name, text[:120]))

            browser.close()
    finally:
        srv_head.shutdown()
        srv_base.shutdown()
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)

    report["ok"] = not fails
    report["fails"] = fails
    with open(os.path.join(out_dir, "m4-embeddings-e2e.json"), "w",
              encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(json.dumps({"ok": report["ok"], "base": args.base,
                      "payload": report["payload"],
                      "base_tabs": report["builds"]["base"]["tabs"],
                      "head_tabs": report["builds"]["head_overview"]["tabs"],
                      "head_groups": report["builds"]["head_settings"]["groups"],
                      "search_items": report["checks"]["search"]["items"],
                      "empty_causes": {k: (v or {}).get("cause")
                                       for k, v in
                                       report["checks"]["empty_causes"].items()},
                      "fails": fails}, ensure_ascii=False, indent=2))
    print("MOD-ACL-M4-EMBEDDINGS OK" if report["ok"]
          else "MOD-ACL-M4-EMBEDDINGS FAIL")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
