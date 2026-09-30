"""ASAP-3.2 (ADR-1028-5 D14, ТЗ §106–§118/§131) — UI E2E редизайна
«Стили обложки» (Builder implementation loop, §115).

СТАТИЧЕСКАЯ страница + route-стабы API (прецедент ui_round1025_e2e.py).
ЭТО НЕ production acceptance (§96/§133: закрытие — только authenticated
real backend у Reviewer/DevOps); цель — геометрия/поведение редизайна:
management screen (§107), full-screen editor (§108), progressive
disclosure (§109), крупный Before→After (§110), reference card (§111),
New Style flow (§112), ОДИН Save (§113), мобильная геометрия (§114).

Запуск: .venv\\Scripts\\python tools\\ui_asap32_cover_styles_e2e.py
"""
import copy
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA-стаб — reuse)

PORT = M.PORT + 5
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "web")

SEED_STYLE = {
    "profile_id": "medved_press",
    "name": "Графический роман Медведь Press",
    "origin": "seeded_example",
    "is_example": True,
    "pipeline_mode": "generate_then_edit",
    "instruction": "Приведи обложку к правилам серии.",
    "counter_enabled": True,
    "counter_value": 0,
    "counter_format": "ВЫПУСК {counter}",
    "model_mode": "default",
    "connection_id": None,
    "model_id": None,
    "revision": 3,
    "enabled": True,
    "preview_before_asset_id": "cas_before",
    "preview_after_asset_id": "cas_after",
    "preview_revision": 3,
    "preview_stale": False,
    "reference_count": 1,
    "preview_issue": "ВЫПУСК 00",
    "references": [{"ref_id": "csr_ref", "asset_id": "cas_ref",
                    "label": "Медведь Press",
                    "description": "Логотип издательства",
                    "ordering": 0,
                    "url": "/api/cover/assets/cas_ref"}],
}

CONNECTION = {"connection_id": "csc_1", "label": "NanoGPT Images",
              "provider": "nanogpt", "base_url": "https://nano-gpt.com/v1",
              "api_key_set": True, "api_key_masked": "sk-…xy"}

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201cfa02d0d0000000049454e44ae"
    "426082")


def _png_response(route):
    route.fulfill(status=200, content_type="image/png",
                  body=PNG_BYTES)


def _run():
    from playwright.sync_api import sync_playwright

    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    styles_payload = {"enabled": True,
                      "no_style_label": "Без дополнительного стиля",
                      "selected_style_id": "",
                      "pipeline_modes": ["generate_only",
                                         "generate_then_edit",
                                         "edit_only"],
                      "styles": [copy.deepcopy(SEED_STYLE)]}
    state = {"styles": styles_payload, "created": [], "saves": [],
             "uploads": []}
    result = {"failures": [], "console_errors": []}
    failures = result["failures"]

    def _api_handler(route):
        req = route.request
        url = req.url
        path = url.split("?")[0]
        query = url.split("?", 1)[1] if "?" in url else ""
        if path.endswith("/api/cover/assets/cas_ref"):
            return _png_response(route)
        if path.endswith("/api/cover/assets/cas_before"):
            return _png_response(route)
        if path.endswith("/api/cover/assets/cas_after"):
            return _png_response(route)
        if path.endswith("/api/cover/styles") and req.method == "POST":
            body = json.loads(req.post_data or "{}")
            if "style_id=" in query:
                # §113: Save существующего (update через query style_id)
                state["saves"].append(body)
                sid = query.split("style_id=")[1].split("&")[0]
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(dict(
                                  next(s for s in state["styles"]["styles"]
                                       if s["profile_id"] == sid), **body)))
                return
            state["created"].append(body)
            profile = dict(SEED_STYLE)
            profile.update({"profile_id": "csp_new1", "name": body["name"],
                            "origin": "custom", "is_example": False,
                            "revision": 1, "counter_enabled": False,
                            "counter_value": 0,
                            "preview_before_asset_id": None,
                            "preview_after_asset_id": None,
                            "preview_revision": None,
                            "reference_count": 0, "references": [],
                            "preview_issue": "ВЫПУСК 00"})
            state["styles"]["styles"].append(profile)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(profile))
            return
        if path.endswith("/api/cover/styles") and req.method == "GET":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(state["styles"]))
            return
        if "/api/cover/styles/csp_new1" in path and req.method == "GET":
            profile = next(s for s in state["styles"]["styles"]
                           if s["profile_id"] == "csp_new1")
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(dict(
                              profile,
                              capabilities={"edit_supported": True},
                              connection={"configured": True,
                                          "connected": True,
                                          "api_key_set": True,
                                          "connection_id": "default",
                                          "custom_unresolved": False,
                                          "message": "Подключено"},
                              budget={"known": False})))
            return
        if "/api/cover/styles/medved_press" in path and req.method == "GET":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(dict(
                              copy.deepcopy(SEED_STYLE),
                              capabilities={"edit_supported": True},
                              connection={"configured": True,
                                          "connected": True,
                                          "api_key_set": True,
                                          "connection_id": "default",
                                          "custom_unresolved": False,
                                          "message": "Подключено"},
                              budget={"known": False})))
            return
        if "/api/cover/styles/medved_press" in path and req.method == "POST":
            body = json.loads(req.post_data or "{}")
            state["saves"].append(body)
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(dict(SEED_STYLE, **body)))
            return
        if path.endswith("/api/cover/connections"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"connections": [CONNECTION]}))
            return
        if path.endswith("/api/cover/select"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True}))
            return
        if path.endswith("/api/access/chats"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps([
                              {"chat_id": 100, "title": "Chat A",
                               "is_dm": False, "photo_file_id": None,
                               "access": "admin"}]))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url)))

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(M.TMA_STUB)
        ctx.route("**/api/**", _api_handler)
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        shots = os.path.join(
            "plans", "features",
            "asap-32-runtime-reliability-graphrag-provider-discovery")
        os.makedirs(shots, exist_ok=True)
        url = "http://127.0.0.1:%d/web/index.html" % PORT

        # ── management screen (§107) ─────────────────────────────────────
        page.goto(url + "#/modules", wait_until="load")
        page.wait_for_timeout(1500)
        page.evaluate(
            "() => { window.location.hash = '#/modules/summary/styles'; }")
        page.wait_for_timeout(1200)
        if not page.query_selector("[data-cover-styles]"):
            # навигация по табам может отличаться — пробуем клик по табу
            tabs = page.query_selector_all("[data-workspace-tab]")
            for t in tabs:
                if t.get_attribute("data-workspace-tab") == "styles":
                    t.click()
                    break
            page.wait_for_timeout(900)
        management = page.query_selector("[data-cover-styles]")
        if not management:
            failures.append("management screen не найден")
        else:
            card = page.query_selector(
                '[data-cover-style="medved_press"]')
            if not card:
                failures.append("§107: карточка seeded не найдена")
            badge = page.query_selector(
                '[data-cover-style="medved_press"] .badge-info')
            if not badge:
                failures.append("§107: бейдж «Пример» не найден")
            # селектор «Стиль этого чата» + Применить
            if not page.query_selector("[data-cover-style-select]"):
                failures.append("§107: селектор стиля чата не найден")
            if not page.query_selector("[data-cover-style-apply]"):
                failures.append("§107: кнопка «Применить» не найдена")

        # ── открыть seeded → full-screen editor (§108/§110/§111) ─────────
        page.click('[data-cover-style="medved_press"] '
                   '[data-cover-style-open]')
        page.wait_for_timeout(900)
        editor = page.query_selector("[data-cover-style-editor]")
        if not editor:
            failures.append("§108: редактор не открылся")
        else:
            # overlay = fixed, поверх (dedicated surface, не inline)
            overlay = page.query_selector("[data-cover-style-overlay]")
            pos = overlay.evaluate("e => getComputedStyle(e).position")
            if pos != "fixed":
                failures.append("§108: редактор не fixed-overlay: %s" % pos)
            # §110: крупные Before/After (не 32px-иконки)
            before = page.query_selector("[data-cover-before-img]")
            after = page.query_selector("[data-cover-after-img]")
            if not before or not after:
                failures.append("§110: Before/After не найдены")
            else:
                box = after.bounding_box()
                if not box or box["width"] < 200:
                    failures.append(
                        "§110: After слишком мал: %s" % (box and box["width"]))
            # §111: reference card с thumbnail
            ref = page.query_selector("[data-cover-ref-thumb]")
            if not ref:
                failures.append("§111: reference thumbnail не найден")
            # §109: техника — collapsed
            details = page.query_selector("[data-cover-model-section]")
            if not details:
                failures.append("§109: секция «Модель и подключение» не найдена")
            # §113: один Save
            saves = page.query_selector_all("[data-cover-style-save]")
            if len(saves) != 1:
                failures.append("§113: кнопок Save %d (ожидается 1)"
                                % len(saves))
            # dirty-индикатор
            page.fill("[data-cover-style-name]", "Медведь Press v2")
            page.wait_for_timeout(200)
            if not page.query_selector("[data-cover-unsaved-dot]"):
                failures.append("§108: несохранённые изменения не показаны")
            # Save → persists (стаб считает мутации)
            page.click("[data-cover-style-save]")
            page.wait_for_timeout(600)
            if not state["saves"]:
                failures.append("§113: Save не отправил мутацию")
            if page.query_selector("[data-cover-unsaved-dot]"):
                failures.append("§113: после Save dirty-флаг не снят")
            page.screenshot(path=os.path.join(
                shots, "ui_editor_desktop.png"), full_page=False)
            # §112: создать стиль → шаг 1 → «Создать и продолжить» →
            # референсы сразу активны
            page.click("[data-cover-editor-close]")
            page.wait_for_timeout(600)
            page.click("[data-cover-style-new]")
            page.wait_for_timeout(400)
            if not page.query_selector("[data-cover-style-create]"):
                failures.append("§112: шаг 1 New Style не открыт")
            else:
                page.fill("[data-cover-style-name]", "Мой стиль")
                page.click("[data-cover-style-create]")
                page.wait_for_timeout(900)
                if not state["created"]:
                    failures.append("§112: «Создать и продолжить» не создал")
                if not page.query_selector("[data-cover-style-refs]"):
                    failures.append(
                        "§112: референсы неактивны после создания")
            page.click("[data-cover-editor-close]")
            page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(
                shots, "ui_management_desktop.png"), full_page=False)
        mctx = browser.new_context(viewport={"width": 360, "height": 740},
                                   is_mobile=True, has_touch=True)
        mctx.add_init_script(M.TMA_STUB)
        mctx.route("**/api/**", _api_handler)
        mpage = mctx.new_page()
        mpage.on("pageerror", lambda e: result["console_errors"].append(
            "mobile pageerror: " + str(e)[:200]))
        mpage.goto(url + "#/modules", wait_until="load")
        mpage.wait_for_timeout(1500)
        mpage.evaluate(
            "() => { window.location.hash = '#/modules/summary/styles'; }")
        mpage.wait_for_timeout(1200)
        mpage.click('[data-cover-style="medved_press"] '
                    '[data-cover-style-open]')
        mpage.wait_for_timeout(900)
        med = mpage.query_selector("[data-cover-style-editor]")
        if not med:
            failures.append("§114: мобильный редактор не открылся")
        else:
            box = med.bounding_box()
            vw = 360
            if box["x"] < -1 or box["x"] + box["width"] > vw + 1:
                failures.append("§114: горизонтальный overflow редактора")
            save = mpage.query_selector("[data-cover-style-save]")
            sbox = save.bounding_box() if save else None
            if not sbox or sbox["y"] + sbox["height"] > 740 + 1:
                failures.append("§114: Save вне вьюпорта: %s" % sbox)
            # контент скроллится до последнего поля (нет content-trap)
            scroll = mpage.query_selector(
                "[data-cover-style-editor] .overflow-y-auto")
            if scroll:
                info = scroll.evaluate(
                    "e => { e.scrollTop = e.scrollHeight;"
                    " return { top: e.scrollTop, sh: e.scrollHeight,"
                    " ch: e.clientHeight }; }")
                if info["sh"] > info["ch"] and info["top"] <= 0:
                    failures.append("§114: контент редактора не скроллится")
        mpage.screenshot(path=os.path.join(
            shots, "ui_editor_mobile.png"), full_page=False)
        mctx.close()
        browser.close()

    httpd.shutdown()
    uniq_errors = [e for e in result["console_errors"]
                   if "favicon" not in e]
    if uniq_errors:
        failures.append("console/pageerror: %s" % uniq_errors[:3])
    result["created"] = len(state["created"])
    result["saves"] = len(state["saves"])

    print(json.dumps(result, ensure_ascii=False, indent=1))
    if failures:
        print("FAILURES: %d" % len(failures))
        for f in failures:
            print(" -", f)
        return 1
    print("COVER STYLES UI E2E: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
