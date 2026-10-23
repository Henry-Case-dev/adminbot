"""ASAP-speech-arch / INSPECTOR — UI-e2e точного промпта и причин пропуска.

TEST-LIFECYCLE: CONTRACT owner=ASAP-SPEECH/INSPECTOR (source-2026-10-22 §6,
INS-EXACT / INS-TRACE / INS-SKIPREASON / INS-HIERARCHY / INS-CONFLICT, U-04).

Гоняет РЕАЛЬНЫЕ `web/index.html` + `web/app.js` + `web/static/app.css` на
Playwright. `/api/speech/inspector` отдаёт payload, построенный НАСТОЯЩИМ
`web/api/speech.py::_inspector_payload` (temp-SQLite, без сети): сид манифеста
реального хода + запись реального provider-вызова композера. Ничего не
выдумывается руками — фикстура воспроизводима флагом `--dump`.

Проверяется:
  * «Полный итоговый промпт» подписан «фактический запрос провайдера» и
    показывает checksum = sha256 фактически отправленного payload;
  * причины пропуска слоёв — по-русски, машинный код только в `title`;
  * клик по блоку иерархии раскрывает его текст, источник и редакцию;
  * длинные русские фразы/URL/код не обрезаются и не дают горизонтальной
    прокрутки страницы (320/360/390/430/1280/1440/landscape).

Запуск:
  .venv/Scripts/python.exe tests/ui_inspector_exact_e2e.py
  .venv/Scripts/python.exe tests/ui_inspector_exact_e2e.py --dump   # JSON
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(TOOLS))
os.chdir(REPO)

import sqlite3  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

import ui_soul1_w6_speech_e2e as W6  # noqa: E402
from test_p0_persistfix_speech_chat_scope import (  # noqa: E402
    SqlitePg,
    create_schema,
    seed_profile,
)

import web.api.speech as S  # noqa: E402
from services import chat_params  # noqa: E402
from services import llm_client  # noqa: E402
from services import prompt_factory as pf  # noqa: E402
from services import prompt_composer as composer  # noqa: E402

SHOTS = REPO / "plans" / "features" / "asap-speech-arch" / "evidence" / "inspector"
CHAT_ID = 0
VIEWPORTS = ((320, 720), (360, 780), (390, 844), (430, 932),
             (1280, 900), (1440, 900), (667, 375))
LONG_WORD = "сверхдлинноесловобезпробеловкотороенедолжнообрезатьсянаузкомэкране"
URL = "https://example.test/very/long/path?query=1&token_hint=not-a-secret"
#: INS-PRIVACY (review F2): секрет и длинный Telegram-ID не должны попасть в DOM.
SECRET = "sk-live-e2e0123456789abcdef"
LONG_ID = "987654321012"


def build_payload() -> dict:
    """Payload Inspector из РЕАЛЬНОГО кода (temp-SQLite, без сети)."""
    db = sqlite3.connect(":memory:", isolation_level=None,
                         check_same_thread=False)
    create_schema(db)
    seed_profile(db, -100500)
    chat_params.set_chat_params_cache(chat_params.ChatParamsCache(SqlitePg(db)))

    from test_soul1_w6_speech_ui import _Cache

    cache = _Cache(pg=SqlitePg(db))
    ctx = SimpleNamespace(is_global_admin=True, effective_permissions=None)
    user = SimpleNamespace(id=4242)

    async def access(request, _user, x_chat_id):
        return cache, (int(x_chat_id) if x_chat_id else None), ctx

    original_access = S._access
    original_default_cache = getattr(pf, "_default_cache", None)
    S._access = access
    pf._default_cache = lambda: cache
    composer.reset_state()
    try:
        # Реальный ход: манифест writer'а Direct L2 + фактический provider-вызов.
        run_id = "e2e-inspector-correlation"
        manifest = composer.compose_prompt(composer.PromptPlan(
            profile=composer.PROFILE_SPEECH_PLAIN, writer="l2_writer",
            chat_id=CHAT_ID, run_id=run_id,
            base_prompt="СИСТЕМНАЯ РОЛЬ: контракт канала Direct.",
            identity=composer.IdentityRef(
                text=("Ты участник чата. Правило: %s\napi_key=%s; участник %s"
                      % (LONG_WORD, SECRET, LONG_ID)),
                source="global"),
            user_parts=("Пользователь: %s" % URL,),
            gates=composer.gates_from_config()))
        system = manifest.system + "\n\nДлинная проверка: %s\n%s" % (LONG_WORD,
                                                                     URL)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": "Пользователь: %s" % URL}]
        payload = {"model": "e2e-trace-model", "messages": messages,
                   "temperature": 0.4}
        # Как в проде: журнал получает уже санитизированные тексты (R17).
        masked = [{"role": m["role"],
                   "content": llm_client._mask_secrets(m["content"])}
                  for m in messages]
        composer.record_provider_call(
            payload=payload, messages=masked, model="e2e-trace-model",
            provider="provider.example", module="direct_chat", step="single",
            correlation_id=run_id, chat_id=CHAT_ID, status="ok")
        insp = asyncio.run(S._inspector_payload(cache, user, ctx, CHAT_ID))
        insp["_e2e"] = {
            "checksum": composer.payload_checksum(payload),
            "system": system,
            "skip_codes": [r.get("code") for r in insp.get("skip_reasons", [])],
        }
        return insp
    finally:
        S._access = original_access
        if original_default_cache is not None:
            pf._default_cache = original_default_cache
        composer.reset_state()
        chat_params.set_chat_params_cache(None)
        db.close()


def make_routes(payload):
    """Статический стенд + подмена ТОЛЬКО `/api/speech/inspector`."""
    base = W6.make_api_handler()

    def _route(route):
        url = route.request.url.split("?")[0]
        if url.endswith("/api/speech/inspector"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(payload, ensure_ascii=False))
        return base(route)
    return _route


def serve(port):
    httpd = ThreadingHTTPServer(("127.0.0.1", port),
                                W6.make_handler(str(REPO / "web")))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--no-shots", action="store_true")
    args = ap.parse_args()
    payload = build_payload()
    if args.dump:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    checks = 0

    def ok(cond, label):
        nonlocal checks
        checks += 1
        if not cond:
            failures.append(label)
            print("  FAIL %s" % label)

    exact = payload["exact"]
    ok(exact.get("label") == "last actual request", "exact label is actual")
    ok(exact.get("checksum") == payload["_e2e"]["checksum"],
       "checksum == sha256 of the sent payload")

    httpd = serve(0)
    port = httpd.server_address[1]
    base = "http://127.0.0.1:%d" % port
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width, height in VIEWPORTS:
                    label = "%sx%s" % (width, height)
                    ctx = browser.new_context(
                        viewport={"width": width, "height": height},
                        device_scale_factor=1)
                    ctx.add_init_script(W6.SDK_STUB)
                    page = ctx.new_page()
                    page.route("**/api/**", make_routes(payload))
                    page.goto(base + "/web/index.html?bgseed=1337#/ai/speech",
                              wait_until="load")
                    page.wait_for_timeout(950)
                    page.click("[data-speech-card='inspector']")
                    page.wait_for_selector("[data-speech-exact]", timeout=15000)
                    page.wait_for_timeout(350)

                    # INS-EXACT: подпись + checksum + точный system.
                    ok(page.inner_text("[data-speech-exact-label]").strip()
                       .startswith("фактический запрос"),
                       label + ": exact подписан как фактический запрос")
                    ok(payload["_e2e"]["checksum"] in
                       page.inner_text("[data-speech-exact-checksum]"),
                       label + ": checksum виден")
                    hash_box = page.evaluate("""() => {
                      const el = document.querySelector('[data-speech-exact-checksum]');
                      const card = el.closest('.card');
                      return {right: el.getBoundingClientRect().right,
                              cardRight: card.getBoundingClientRect().right,
                              sw: el.scrollWidth, cw: el.clientWidth};
                    }""")
                    ok(hash_box["right"] <= hash_box["cardRight"] + 1
                       and hash_box["sw"] <= hash_box["cw"] + 1,
                       label + ": checksum не выходит за карточку")
                    system_text = page.inner_text("[data-speech-exact-system]")
                    ok(payload["_e2e"]["system"].splitlines()[0]
                       in system_text, label + ": system совпадает")
                    # Длинные строки: внутри карточки, без обрезки/overflow.
                    box = page.evaluate("""() => {
                      const el = document.querySelector('[data-speech-exact-system]');
                      const card = el.closest('.card');
                      const cs = getComputedStyle(el);
                      return {sw: el.scrollWidth, cw: el.clientWidth,
                              ws: cs.whiteSpace, ow: cs.overflowWrap,
                              cardRight: card.getBoundingClientRect().right,
                              elRight: el.getBoundingClientRect().right,
                              doc: document.documentElement.scrollWidth,
                              win: window.innerWidth};
                    }""")
                    ok(box["sw"] <= box["cw"] + 1,
                       label + ": нет горизонтального обрезания текста")
                    ok(box["ws"].startswith("pre-wrap")
                       and box["ow"] == "anywhere",
                       label + ": pre-wrap/anywhere сохранены")
                    ok(box["elRight"] <= box["cardRight"] + 1,
                       label + ": текст не выходит за карточку")
                    ok(box["doc"] <= box["win"] + 1,
                       label + ": нет второй горизонтальной прокрутки")

                    # INS-PRIVACY (review F2): в DOM нет секрета/полного ID.
                    html = page.content()
                    ok(SECRET not in html, label + ": секрет не в DOM")
                    ok(LONG_ID not in html, label + ": полный ID не в DOM")
                    # INS-TRACE: покрытие каналов видно владельцу.
                    ok(page.query_selector("[data-speech-trace-coverage]")
                       is not None, label + ": покрытие журнала показано")

                    # INS-SKIPREASON: русский текст + машинный код в title.
                    if not args.no_shots and width in (390, 1280):
                        page.evaluate("window.scrollTo(0, 0)")
                        page.wait_for_timeout(200)
                        page.screenshot(path=str(
                            SHOTS / ("inspector_exact_top_%s.png"
                                     % label.replace("x", "_"))))
                    rows = page.query_selector_all("[data-speech-skip-layer]")
                    ok(len(rows) > 0, label + ": есть пропущенные слои")
                    if rows:
                        text = rows[0].inner_text()
                        code = rows[0].query_selector(".text-xs[title]")
                        title = code.get_attribute("title") if code else ""
                        ok("." in text and "samples_absent" not in text,
                           label + ": причина по-русски, не машинный код")
                        ok(bool(title), label + ": код причины в диагностике")

                    # INS-HIERARCHY: клик раскрывает текст/источник/редакцию.
                    hier = page.query_selector_all(
                        "[data-speech-hierarchy-row]")
                    ok(len(hier) >= 3, label + ": иерархия слоёв видна")
                    target = None
                    for row in hier:
                        if row.query_selector(".badge-info"):
                            target = row
                            break
                    ok(target is not None, label + ": есть включённый блок")
                    if target is not None:
                        layer = target.get_attribute(
                            "data-speech-hierarchy-row")
                        target.click()
                        page.wait_for_timeout(200)
                        detail = page.query_selector(
                            "[data-speech-hierarchy-detail='%s']" % layer)
                        ok(detail is not None and detail.is_visible(),
                           label + ": блок раскрылся")
                        if detail is not None:
                            body = detail.inner_text()
                            ok("редакция:" in body and "источник:" in body,
                               label + ": видны источник и редакция")
                            pre = detail.query_selector(".speech-pre")
                            ok(pre is not None and len(pre.inner_text()) > 0,
                               label + ": виден точный текст блока")

                    # INS-CONFLICT: классы перечислены по реальным данным.
                    ok(page.query_selector("[data-speech-conflicts]")
                       is not None, label + ": карточка конфликтов есть")

                    if not args.no_shots:
                        page.screenshot(path=str(
                            SHOTS / ("inspector_exact_%s.png"
                                     % label.replace("x", "_"))))
                    ctx.close()
            finally:
                browser.close()
    finally:
        httpd.shutdown()

    print("[inspector-exact-e2e] checks=%d failures=%d" % (checks,
                                                           len(failures)))
    for f in failures:
        print("  -", f)
    if not args.no_shots:
        print("[inspector-exact-e2e] shots →", SHOTS)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
