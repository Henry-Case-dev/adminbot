import importlib.util
import json
import os

spec = importlib.util.spec_from_file_location(
    "g2", r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\rebind45\glass_rebind_check2.py")
g2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g2)

from playwright.sync_api import sync_playwright  # noqa: E402

g2.serve(g2.PORT, os.path.join(g2.WORKTREE, "web"))
rec = {}
with sync_playwright() as p:
    browser = g2.launch(p)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                              device_scale_factor=3)
    page = ctx.new_page()
    page.goto(g2.STAND + "?bg=wave", wait_until="load")
    page.wait_for_selector("#stand-probe[data-tiera]", timeout=6000)
    page.wait_for_timeout(400)
    probe_el = page.query_selector("#stand-probe")
    rec["probe"] = {"tierA": probe_el.get_attribute("data-tiera"),
                    "reason": probe_el.get_attribute("data-reason")}
    box = page.evaluate(g2.SURFACE_JS, "#panel-hero")
    rec["panel"] = box
    clip = {"x": box["x"] - 24, "y": box["y"] - 24, "width": box["w"] + 48, "height": box["h"] + 48}
    page.screenshot(path=g2.ev_path("stand_wave_3x_on.png"), clip=clip)
    page.screenshot(path=g2.ev_path("stand_wave_full_3x.png"))
    page.evaluate("() => { const el = document.querySelector('#panel-hero');"
                  " el.style.visibility = 'hidden'; }")
    page.wait_for_timeout(250)
    page.screenshot(path=g2.ev_path("stand_wave_3x_hidden.png"), clip=clip)
    ctx.close()
    browser.close()

a3 = g2.decode_png(open(g2.ev_path("stand_wave_3x_on.png"), "rb").read())
d3 = 3
x0, y0 = int(24 * d3 + 9), int(24 * d3 + 9)
x1, y1 = int(24 * d3 + box["w"] * d3 - 9), int(24 * d3 + box["h"] * d3 - 9)
lums = [g2.lum_at(a3, x, y) for y in range(y0, y1, 2) for x in range(x0, x1, 2)]
p5, p995 = g2.percentile(lums, 0.05), g2.percentile(lums, 0.995)
rec["contrast_wave"] = {"p5": round(p5, 4), "p99_5": round(p995, 4),
                        "wcag": round((p995 + 0.05) / (p5 + 0.05), 2)}
with open(g2.ev_path("stand_wave_extra.json"), "w", encoding="utf-8") as fh:
    json.dump(rec, fh, ensure_ascii=False, indent=1)
print(json.dumps(rec, ensure_ascii=False)[:400])
