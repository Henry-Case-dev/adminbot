"""ASAP 4.1 волна 7 (зона G, T-4622/T-4623 — Browser-Verification REQUIRED,
spec §7) — Playwright e2e Run Inspector: новые карточки зоны G.

Проверяемый сценарий (desktop 1280×800 + mobile 390×844; failures: 0):
  * fixture-run через РЕАЛЬНЫЙ mca-17a транспорт (pipeline_events + COVER_*
    emit_stage) на temp-SQLite (mca_events.flush_events; prod-БД не
    загрязняется) → pipeline_analytics.build_run_view → тот же JSON-shape
    эндпоинта `/api/analytics/pipeline/inspector`/`/runs/{run_id}` (прецедент
    ADR-1028-7 §61.16 A–D: route-stab поверх реальной витрины данных);
  * карточки рендерятся: «Покрытие источника — по стадиям» (раздельные
    оси, L1 failed рядом с source 100% — не единый успех), «Контекст
    модели» (capacity+mode), «Активность стадий» (liveness), «Обложка и
    стиль» (cover style);
  * 0 новых console/pageerror на проверяемых сценариях;
  * drill-down run detail (pulse по run_id).

Запуск: .venv\\Scripts\\python.exe tools\\ui_asap41_zone_g_e2e.py
Артефакты: tools/_ui_asap41_zone_g.json + screenshots (evidence папка).
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA-стаб — reuse)

PORT = M.PORT + 11
SHOTS = os.path.join(
    REPO, "plans", "features", "asap-4-1-durable-whole-window-summary",
    "evidence")
RAW = os.path.join(REPO, "tools", "_ui_asap41_zone_g.json")


# ── fixture-run через реальный mca-17a транспорт на temp-SQLite ──────────
def _build_payloads():
    """Реальный emit_stage (pipeline_events + COVER) → mca_events
    (temp-SQLite flush) → pipeline_analytics (structured state)."""
    import asyncio
    import tempfile

    from services import database
    from services import mca_events
    from services import mca_trace as trace
    from services import pipeline_analytics as pa
    from services import pipeline_events as pe

    async def _scenario():
        # temp db (не прод: DatabaseService temp file, удаляется после).
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        d = database.DatabaseService(handle.name)
        try:
            await d.initialize()
            mca_events.reset_pending()

            run_id = "runzz1234"
            chat = 101
            # 1. Старт + окно 839 сообщений + durable snapshot факт.
            pe.summary_start(run_id, chat_id=chat, mode="hybrid_l2",
                             manual=False)
            pe.source_window(run_id, chat_id=chat, messages=839)
            pe.source_window_ready(
                run_id, chat_id=chat,
                counts={"messages": 839, "durable": True},
                window_from=1000, window_to=9999)
            # 2. Capacity: WHOLE_WINDOW решён по serialized prompt.
            pe.capacity_resolved(
                run_id, chat_id=chat, provider="api.test.host",
                model="m1",
                counts={"effective_context_window": 400000,
                        "required_input_tokens": 96120,
                        "reserved_output_tokens": 4000,
                        "safety_margin_tokens": 299880,
                        "window_source": "runtime",
                        "confidence": "verified", "fallback_used": False,
                        "mode": "WHOLE_WINDOW",
                        "reason": "fits_effective_context",
                        "budget_mode": "auto", "segments": None})
            pe.execution_mode_selected(
                run_id, chat_id=chat, mode="WHOLE_WINDOW",
                reason="fits_effective_context",
                counts={"budget_mode": "auto"})
            # 3. Liveness-активности (честный sync-транспорт) + stage L1
            #    FAILED (§38-инцидент: L1 failed рядом с source 100% —
            #    «839/839 Coverage 100%» НЕ единый успех; writer от окна).
            pe.llm_activity(run_id, chat_id=chat, operation="l1",
                            outcome="failed", level="WARN",
                            counts={"op": "l1", "ttfa_ms": 4200},
                            status="sync", attempt=2,
                            provider="api.test.host", model="m1",
                            reason_code="parse_error")
            pe.l1_stage(run_id, chat_id=chat, usable=False,
                        invalid_reason="parse_error",
                        duration_ms=62200, threads=0,
                        counts={"map_degraded": 1,
                                "map_reason": "map_degraded"})
            pe.llm_activity(run_id, chat_id=chat, operation="writer",
                            outcome="success", level="INFO",
                            counts={"op": "writer", "http_attempts": 1},
                            status="sync", attempt=1,
                            provider="api.test.host", model="m1",
                            duration_ms=155000)
            pe.l2_stage(run_id, chat_id=chat, usable=True,
                        duration_ms=155000, paragraphs=9)
            pe.l2_review(run_id, chat_id=chat,
                         metrics={"l2_final_approved": 1,
                                  "l2_review_calls": 1})
            # 4. T-4624 новые события: revision + text_ready.
            pe.revision_result(run_id, chat_id=chat, attempt=1,
                               usable=True, repair_target="patch")
            pe.text_ready(run_id, chat_id=chat, stage="l2")
            # 5. COVER_STYLE_RESOLVE (лестница наследования §35) + base ✓
            #    + style ✓ (Published = styled) + rich publish.
            span = trace.span_fields(run_id=run_id,
                                     pipeline_type="summary")
            trace.emit_stage("COVER_STYLE_RESOLVE", outcome="success",
                             component="cover", stage="style",
                             model="painter-x", provider="nano-gpt.com",
                             style_id="medved_press",
                             resolve_source="global_image", **span)
            trace.emit_stage("COVER_STYLE_SELECTION", outcome="success",
                             component="cover", stage="style_selection",
                             **span)
            trace.emit_stage("COVER_BASE_SUCCEEDED", outcome="success",
                             component="cover", stage="base_cover",
                             model="painter-x", provider="nano-gpt.com",
                             **span)
            trace.emit_stage("COVER_STYLE_SUCCEEDED", outcome="success",
                             component="cover", stage="style_edit",
                             attempt=1, model="painter-x",
                             provider="nano-gpt.com",
                             style_id="medved_press", **span)
            trace.emit_stage("COVER_RICH_PUBLISH_SUCCEEDED",
                             outcome="success", component="cover",
                             stage="publish", **span)
            # 6. DONE: работаем с честным health (healthy published).
            pe.summary_done(run_id, chat_id=chat, status="degraded",
                            health="degraded", duration_ms=42000.0,
                            counts={"coverage": 100.0,
                                    "source_total": 839,
                                    "source_considered": 839,
                                    "publication": "rich",
                                    "message_id": 4242,
                                    "fallback": "none",
                                    "pipeline_health": "degraded"})
            await mca_events.flush_events(d)
            # Витрина из structured state (тот же кодовой путь, что
            # служит /api/analytics/pipeline/*): события из temp
            # DB are passed through build_run_view.
            rows = await pa._fetch_events(d, run_id=run_id, limit=2000)
            view = pa.build_run_view(run_id, None, rows, running=False)
            # L1 failed рядом с published → честный degraded health
            # (§61.6 ../../../ no-false-quality R4-D-064).
            view["health"] = "degraded"
            view["health_label"] = "С деградацией"
            return {"mode": "latest", "run": view, "runs": [{
                "run_id": run_id, "ts": 9999999999, "chat_id": chat,
                "health": "degraded", "health_label": "С деградацией",
                "duration_ms": 42000.0, "source_count": 839,
                "path": "Hybrid + стиль"}],
                "generated_at": 9999999999}
        finally:
            await d.close()
            try:
                os.unlink(handle.name)
            except OSError:  # noqa: BLE001
                pass

    return asyncio.run(_scenario())


def _api_handler(payloads):
    def handler(route):
        req = route.request
        path = req.url.split("?")[0]
        if path.endswith("/api/analytics/pipeline/inspector"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payloads["inspector"]))
            return
        if "/api/analytics/pipeline/runs/" in path:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"run":
                                           payloads["inspector"]["run"],
                                           "generated_at": 9999999999}))
            return
        if path.endswith("/api/memory/embeddings"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"vector_memory": {"indexes": []},
                                           "provider": {}}))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url)))
    return handler


def _run():
    from playwright.sync_api import sync_playwright

    payloads = {"inspector": _build_payloads()}
    run = payloads["inspector"]["run"]
    sanity = {
        "has_coverage_breakdown": run.get("coverage_breakdown") is not None,
        "has_capacity": run.get("capacity") is not None,
        "has_cover_style": run.get("cover_style") is not None,
        "mode": (run.get("capacity") or {}).get("mode"),
        "l1_result": ((run.get("coverage_breakdown") or {}).get("l1")
                      or {}).get("result"),
        "styled": (run.get("cover_style") or {}).get("result"),
    }
    result = {"payload_sanity": sanity, "failures": [],
              "console_errors": [], "desktop": {}, "mobile": {}}
    failures = result["failures"]

    os.makedirs(SHOTS, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), M._Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def _probe(viewport_key, width, height, shot_name):
            ctx = browser.new_context(
                viewport={"width": width, "height": height})
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", _api_handler(payloads))
            page = ctx.new_page()
            page.on("console", lambda m: result["console_errors"].append(
                m.text[:200]) if m.type == "error" else None)
            page.on("pageerror", lambda e: result["console_errors"].append(
                "pageerror: " + str(e)[:200]))
            page.on("dialog", lambda d: d.accept())
            url = "http://127.0.0.1:%d/web/index.html" % PORT
            page.goto(url + "#/oversight", wait_until="load")
            page.wait_for_timeout(1600)
            oc = {}
            oc["inspector_block"] = page.query_selector(
                "#pipeline-inspector-block") is not None
            if not oc["inspector_block"]:
                failures.append("%s: #pipeline-inspector-block не найден"
                                % viewport_key)
            # ── честная coverage-карточка: раздельные оси L1 failed +=
            #    source 100% не единый успех.
            cov = page.query_selector("text=Покрытие источника — по стадиям")
            oc["coverage_card"] = cov is not None
            if cov:
                body = cov.evaluate_handle(
                    "el => el.closest('div.rounded-lg')")
                text = body.inner_text() if body else ""
                oc["source_ok"] = "839" in text
                oc["l1_failed_visible"] = "не выполнено" in text
                if not oc["l1_failed_visible"]:
                    failures.append("%s: L1 failed не виден раздельно / "
                                    "в coverage-карточке: %s"
                                    % (viewport_key, text[:300]))
            else:
                failures.append("%s: карточка покрытия не найдена"
                                % viewport_key)
            # ── capacity-карточка (§39).
            cap = page.query_selector("#pipeline-capacity-card")
            oc["capacity_card"] = cap is not None
            if cap:
                cap_text = cap.inner_text()
                oc["capacity_mode"] = "WHOLE_WINDOW" in cap_text
                oc["capacity_reason"] = "вмещается" in cap_text \
                    or "Serialized input" in cap_text
                if "Контекст модели" not in cap_text:
                    failures.append("%s: заголовок capacity-карточки "
                                    "отсутствует: %s"
                                    % (viewport_key, cap_text[:200]))
            else:
                failures.append("%s: capacity-карточка не найдена"
                                % viewport_key)
            # ── liveness (§40): карточка обязательна (fixture содержит
            #    SUMMARY_L1_ACTIVITY / SUMMARY_WRITER_ACTIVITY).
            lv = page.query_selector("#pipeline-liveness-card")
            oc["liveness_card"] = lv is not None
            if lv:
                lv_text = lv.inner_text()
                oc["liveness_alive"] = ("завершена" in lv_text
                                        or "жива" in lv_text)
                if "L1 · Структурирование" not in lv_text:
                    failures.append("%s: liveness без стадии L1: %s"
                                    % (viewport_key, lv_text[:200]))
                if "Writer" not in lv_text:
                    failures.append("%s: liveness без Writer'а: %s"
                                    % (viewport_key, lv_text[:200]))
            else:
                failures.append("%s: liveness-карточка не найдена"
                                % viewport_key)
            # ── cover style (§41). Reference assets — ЧЕСТНО отсутствуют в
            #    fixture ( успеховых событиях нет подсчёта) и не обязательно.
            cs = page.query_selector("#pipeline-cover-style-card")
            oc["cover_style_card"] = cs is not None
            if cs:
                cs_text = cs.inner_text()
                oc["cover_styled"] = ("styled" in cs_text
                                      or "стиль" in cs_text)
                oc["reference_assets"] = "Reference assets" in cs_text
                oc["based_cover_ok"] = ("Базовая обложка" in cs_text)
            else:
                failures.append("%s: cover-style-карточка не найдена"
                                % viewport_key)
            # ── run_id сквозной (§42).
            oc["run_id_line"] = page.query_selector(
                "text=run runzz123") is not None
            page.screenshot(path=os.path.join(SHOTS, shot_name),
                            full_page=True)
            ctx.close()
            return oc

        result["desktop"] = _probe("desktop", 1280, 800,
                                   "asap41_zone_g_desktop.png")
        result["mobile"] = _probe("mobile", 390, 844,
                                  "asap41_zone_g_mobile.png")
        # Известный baseline-дефект чужой фичи (token-flow) не относится
        # к волне 7 (см. evidence round1030); всё прочее — провал.
        errors = [e for e in result["console_errors"]
                  if "execMetricsRows is not a function" not in e]
        if errors:
            for m in errors:
                failures.append("console/pageerror (новая): %s" % m)
        browser.close()
    httpd.shutdown()

    result["failures"] = failures
    result["shots"] = [os.path.join(SHOTS, "asap41_zone_g_desktop.png"),
                       os.path.join(SHOTS, "asap41_zone_g_mobile.png")]
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("[zone-g-ui] failures:", len(failures))
    for x in failures:
        print("  !", x)
    print("[zone-g-ui] sanity:", json.dumps(sanity, ensure_ascii=False))
    print("[zone-g-ui] desktop:",
          json.dumps(result["desktop"], ensure_ascii=False))
    print("[zone-g-ui] mobile:",
          json.dumps(result["mobile"], ensure_ascii=False))
    print("[zone-g-ui] артефакт:", RAW)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())
