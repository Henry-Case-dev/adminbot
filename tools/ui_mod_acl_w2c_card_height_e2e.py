"""W2c card-height regression — targeted long-content acceptance.

Reproduces the postdeploy failure: production chat-scope labels + realistic
long titles at 4-column catalog width make `.module-title` wrap to a second
line (14px * 1.25 = 17.5px), pushing cards to 179.56 instead of 132–164.
The harness uses the same `ui_mod_acl_m4a_w2c_e2e` server/routes and the real
W2c config; only titles/descriptions are made realistic-long for the four
cards named in deploy-2.58.221.

Run: py tools/ui_mod_acl_w2c_card_height_e2e.py
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

import ui_mod_acl_m4a_w2c_e2e as w2c  # noqa: E402

PORT = int(os.environ.get("MOD_ACL_W2C_CARD_HEIGHT_PORT", "8822"))
SHOTS = os.environ.get(
    "MOD_ACL_W2C_CARD_HEIGHT_SHOTS",
    os.path.join(REPO, "plans", "features", "mod-acl-ux-01", "evidence",
                 "m4a", "w2c", "fix-card-height", "shots"))
VIEWPORTS = (1680, 1440, 320)
CARDS = ("mod_transcribe", "mod_video_summary", "mod_media_download",
         "mod_images")

LONG = {
    "transcribe": (
        "Транскрипт голосовых и видеосообщений",
        "Превращает голосовые сообщения, видео и видеосообщения в текст, "
        "чтобы их можно было прочитать и использовать в ответе."),
    "video_summary": (
        "Выжимка видео по ссылкам и файлам",
        "Пересказывает видео по ссылке или файлу и выделяет главное, "
        "сохраняя ключевые фрагменты для ответа."),
    "media_download": (
        "Скачивание медиа и видео по ссылке",
        "Скачивает видео и медиа по ссылке в чат, сохраняя исходный файл "
        "и показывая фактический результат загрузки."),
    "images": (
        "Генерация изображений по описанию",
        "Рисует изображения по просьбе в чате, используя выбранную модель "
        "и фактические лимиты генерации."),
}

# Apply long but realistic titles/descriptions to both global and chat DTOs;
# the catalog probe switches to chat scope below, matching production.
for cfg in (w2c.CFG, w2c.CFG_CHAT):
    for card in cfg.get("modules", []):
        short = str(card.get("id") or "")
        if short in LONG:
            card["title"], card["description"] = LONG[short]


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    w2c.e2e.PORT = PORT
    httpd = w2c.e2e._start_server()
    base = "http://127.0.0.1:%d/web/index.html" % PORT
    failures = []
    report = {"viewports": {}, "failures": failures, "shots": SHOTS}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for width in VIEWPORTS:
                ctx = browser.new_context(viewport={"width": width,
                                                    "height": 1000})
                ctx.add_init_script(w2c.e2e.TMA_STUB)
                ctx.route("**/api/**", w2c._route)
                page = ctx.new_page()
                page.goto(base + "#/modules", wait_until="domcontentloaded")
                page.wait_for_selector(".module-catalog [data-mod]",
                                       timeout=9000)
                page.click(".scope-trigger")
                page.click(".scope-option:has-text('%s')" % w2c.e2e.CHAT_TITLE)
                page.wait_for_timeout(650)
                data = page.evaluate("""(ids) => {
                  const out = {};
                  ids.forEach((id) => {
                    const card = document.querySelector(
                      '.module-catalog [data-mod="' + id + '"]');
                    if (!card) { out[id] = null; return; }
                    const r = card.getBoundingClientRect();
                    const t = card.querySelector('.module-title');
                    const d = card.querySelector('.module-card-phrase');
                    const l = card.querySelector('.module-control-row__label');
                    out[id] = {
                      h: Math.round(r.height * 100) / 100,
                      titleH: t ? Math.round(t.getBoundingClientRect().height) : null,
                      descH: d ? Math.round(d.getBoundingClientRect().height) : null,
                      labelH: l ? Math.round(l.getBoundingClientRect().height) : null,
                      title: t ? t.textContent.trim() : null,
                    };
                  });
                  return out;
                }""", list(CARDS))
                page.screenshot(path=os.path.join(
                    SHOTS, "card-height-%d.png" % width))
                report["viewports"][str(width)] = data
                for cid, row in data.items():
                    if not row:
                        failures.append("%d: %s missing" % (width, cid))
                        continue
                    if not (132 <= row["h"] <= 164):
                        failures.append(
                            "%d: %s height %.2f outside 132–164"
                            % (width, cid, row["h"]))
                    # Title must be one visual line (<= 18px); the full text
                    # remains in DOM/title, so ellipsis is a presentation cap.
                    if (row["titleH"] or 0) > 18:
                        failures.append(
                            "%d: %s title wraps (titleH=%s)"
                            % (width, cid, row["titleH"]))
                ctx.close()
            browser.close()
    finally:
        httpd.shutdown()

    out = os.environ.get("MOD_ACL_W2C_CARD_HEIGHT_REPORT")
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("->", out)
    print("card-height viewports=%d failures=%d"
          % (len(VIEWPORTS), len(failures)))
    for f in failures:
        print("FAIL:", f)
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
