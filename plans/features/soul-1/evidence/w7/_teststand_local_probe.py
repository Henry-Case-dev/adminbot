"""W7: положительная проверка разрешённой test-среды (SOUL-13.2).

Стенд `tests/glass-teststand/glass-teststand.html` должен быть работоспособен
именно как фикстура тестовой среды (относительные ссылки на боевые ассеты
`../../web/static/...`), при этом анонимно в проде недостижим (7 путей
401/403/404 — tests/test_webapp_teststand_guard.py). Здесь — рендер и
скриншот локально.

Запуск: .venv/Scripts/python.exe tools/... ; артефакт — в evidence/w7.
"""
import json
import os
import sys

REPO = r"C:\Code\Python\adminbot"
HTML = os.path.join(REPO, "tests", "glass-teststand", "glass-teststand.html")
OUT = os.path.join(REPO, "plans", "features", "soul-1", "evidence", "w7")

PROBE = r"""(() => {
  const q = (s) => document.querySelector(s);
  return {
    title: document.title,
    textLen: (document.body.innerText || '').length,
    sheetCount: document.styleSheets.length,
    links: Array.from(document.querySelectorAll('link[rel=stylesheet]'))
      .map((l) => l.getAttribute('href')),
    scripts: Array.from(document.querySelectorAll('script[src]'))
      .map((s) => s.getAttribute('src')),
    glassNodes: document.querySelectorAll('[data-glass]').length,
    probeMeta: (q('[data-stand-probe]') ? q('[data-stand-probe]').textContent.trim().slice(0, 160) : null),
    bodyBg: getComputedStyle(document.body).backgroundColor,
  };
})()"""


def main():
    from playwright.sync_api import sync_playwright
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1100, "height": 900})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)[:200]))
        page.goto("file:///" + HTML.replace("\\", "/"), wait_until="load")
        page.wait_for_timeout(900)
        rec = page.evaluate(PROBE)
        rec["pageErrors"] = errs
        page.screenshot(path=os.path.join(OUT, "teststand-test-env-local-render.png"),
                        full_page=True)
        b.close()
    with open(os.path.join(OUT, "teststand-test-env-local.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
    print(json.dumps(rec, ensure_ascii=False)[:700])
    return 0


if __name__ == "__main__":
    sys.exit(main())
