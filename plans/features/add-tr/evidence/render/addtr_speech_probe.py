# -*- coding: utf-8 -*-
"""TR-RECON: DOMRect-замеры витрины «Речь и характер» на ПРОД-байтах 3b02366e.

Read-only относительно репозитория: web-дерево уже экспортировано в scratch,
шаги/шоты/JSON пишутся в scratch. Сервер + /api-стабы переиспользуют
tests/ui_p0a_ux_speech_compact_e2e.py (тот же harness, что у P0A-UX e2e).
"""
import json
import os
import sys

REPO = r"C:\Code\Python\adminbot"
SCRATCH = os.path.join(os.environ["OPENCODE_WORKFLOW_SCRATCH"], "addtr_recon")
WEBROOT = os.path.join(SCRATCH, "prod_web")
OUT = os.path.join(SCRATCH, "out")
SHOTS = os.path.join(OUT, "shots")
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))
os.chdir(REPO)

import tests.ui_p0a_ux_speech_compact_e2e as E  # noqa: E402

PORT = 8877
BASE = "http://127.0.0.1:%d" % PORT

PROBE = r"""
(() => {
  const strip = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const round = (r) => ({x: Math.round(r.x), y: Math.round(r.y),
                         w: Math.round(r.width), h: Math.round(r.height)});
  const grid = document.querySelector('.speech-grid');
  const cols = grid ? getComputedStyle(grid).gridTemplateColumns : '';
  const inter = (a, b) => {
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return (w > 0 && h > 0) ? {w: Math.round(w), h: Math.round(h)} : null;
  };
  const cards = [];
  document.querySelectorAll('[data-speech-card]').forEach((el) => {
    const r = el.getBoundingClientRect();
    const title = el.querySelector('.speech-card-title');
    const sub = el.querySelector('.speech-card-sub');
    const detail = el.querySelector('.speech-card-detail');
    const body = el.querySelector('.speech-card-body');
    const badge = el.querySelector('span.badge');
    const tr = title ? title.getBoundingClientRect() : null;
    const br = badge ? badge.getBoundingClientRect() : null;
    const bd = body ? body.getBoundingClientRect() : null;
    cards.push({
      id: el.getAttribute('data-speech-card'),
      card: round(r),
      body: bd ? round(bd) : null,
      title: tr ? round(tr) : null,
      sub: sub ? round(sub.getBoundingClientRect()) : null,
      detail: detail ? round(detail.getBoundingClientRect()) : null,
      badge: br ? round(br) : null,
      badgeText: badge ? strip(badge.textContent) : '',
      titleBadgeOverlap: (tr && br) ? inter(tr, br) : null,
      bodyBadgeOverlap: (bd && br) ? inter(bd, br) : null,
      titleOverflowPx: title ? (title.scrollWidth - title.clientWidth) : null,
      badgeOverflowPx: badge ? (badge.scrollWidth - badge.clientWidth) : null,
      titleWhiteSpace: title ? getComputedStyle(title).whiteSpace : '',
      titleOverflowWrap: title ? getComputedStyle(title).overflowWrap : '',
    });
  });
  const root = document.querySelector('.speech-screen');
  return {
    vw: window.innerWidth, vh: window.innerHeight,
    hash: location.hash,
    colsRaw: cols,
    cols: cols ? cols.split(' ').length : 0,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    screenVisible: !!root && root.offsetParent !== null,
    cards,
  };
})()
"""

WIDTHS = [
    ("320", 320, 640),
    ("360", 360, 740),
    ("390", 390, 844),
    ("430", 430, 932),
    ("landscape", 844, 390),
    ("768", 768, 1024),
]


def main():
    os.makedirs(SHOTS, exist_ok=True)
    E.serve_static(PORT, os.path.abspath(WEBROOT))
    from playwright.sync_api import sync_playwright

    report = {"webroot": WEBROOT, "viewports": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        with browser:
            for label, w, h in WIDTHS:
                ctx, page = E.new_page(browser, w, h)
                page.goto(BASE + "/#/ai/speech", wait_until="load")
                page.wait_for_selector("[data-speech-groups]", timeout=15000)
                page.wait_for_timeout(350)
                data = page.evaluate(PROBE)
                page.screenshot(path=os.path.join(SHOTS, "speech_%s.png" % label),
                                full_page=True)
                report["viewports"][label] = data
                ctx.close()
    with open(os.path.join(OUT, "measure.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # компактная сводка
    for label, data in report["viewports"].items():
        bad = [c for c in data["cards"]
               if c["titleBadgeOverlap"] or (c["titleOverflowPx"] or 0) > 0]
        print("%-9s cols=%s viewport=%d overflow=%d cards=%d problems=%d"
              % (label, data["cols"], data["vw"], data["overflow"],
                 len(data["cards"]), len(bad)))
        for c in bad[:6]:
            print("   - %-18s card_w=%s body_w=%s badge_w=%s title_ovf=%s "
                  "overlap=%s badge=%s body=%s"
                  % (c["id"], c["card"]["w"],
                     c["body"]["w"] if c["body"] else None,
                     c["badge"]["w"] if c["badge"] else None,
                     c["titleOverflowPx"], c["titleBadgeOverlap"],
                     c["badge"]["x"] if c["badge"] else None,
                     c["body"]["x"] if c["body"] else None))


if __name__ == "__main__":
    main()
