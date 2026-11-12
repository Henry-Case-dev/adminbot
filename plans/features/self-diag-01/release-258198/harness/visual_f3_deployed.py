# -*- coding: utf-8 -*-
"""F3/hard_rules visual gate on the DEPLOYED 2.58.198 (real Mini App, read-only).

Playwright, real prod URL + real API, TMA initData injected from the local .env
(never printed). No messages, no saves: the matrix toggle only changes local
component state before "Сохранить".

Checks (390x844 and 1536x960, checked/unchecked/disabled):
  * every matrix control is the design-system checkbox (ctl-check__box), no native;
  * control size/accent from the design system;
  * no horizontal scroll, no clipped text, no console/pageerror;
  * "Жёсткие правила" rendered as human text (no [object Object], no internal code);
  * one unchecked control toggles to checked locally (if such a control exists).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(r"C:\Code\Python\adminbot\plans\features\self-diag-01\release-258198\harness")))
import live_258198 as H  # noqa: E402  (auth helpers, .env, BASE)

OUT = Path(sys.argv[1]).resolve()
CHAT = H.CHAT_A
URL = H.BASE + "/web/#/access"
EXPECTED_SIZE = "18x18"
EXPECTED_ACCENT = "rgb(139, 111, 232)"

INIT_SCRIPT = """
window.Telegram = window.Telegram || {};
window.Telegram.WebApp = {
  initData: %s,
  initDataUnsafe: { user: { id: %d, first_name: 'owner' } },
  ready: function(){}, expand: function(){}, close: function(){},
  onEvent: function(){}, offEvent: function(){},
  colorScheme: 'dark', themeParams: {}, isExpanded: true,
  viewportStableHeight: Math.max(0, (window.innerHeight || 800) - 56),
  viewportHeight: window.innerHeight || 800
};
try { sessionStorage.setItem('adminbot.initData', %s); } catch (e) {}
try { localStorage.setItem('adminbot.active_chat_id', '%s'); } catch (e) {}
"""

PROBE = r"""
(() => {
  const card = document.querySelector('[data-self-diag-access]');
  const caps = Array.from(document.querySelectorAll('[data-self-diag-cap]'));
  const boxes = Array.from(card ? card.querySelectorAll('input[type="checkbox"]') : []);
  const state = (b) => ({
    cap: b.closest('[data-self-diag-cap]') ? b.closest('[data-self-diag-cap]').dataset.selfDiagCap : null,
    action: b.closest('[data-self-diag-action]') ? b.closest('[data-self-diag-action]').dataset.selfDiagAction : null,
    role: b.closest('label') ? b.closest('label').textContent.trim().split('\n')[0].slice(0, 24) : null,
    checked: b.checked,
    disabled: b.disabled,
    width: Math.round(b.getBoundingClientRect().width * 100) / 100,
    height: Math.round(b.getBoundingClientRect().height * 100) / 100,
    accent: getComputedStyle(b).accentColor,
    cursor: getComputedStyle(b).cursor,
    labelMinHeight: getComputedStyle(b.closest('label')).minHeight,
    native: !b.classList.contains('ctl-check__box'),
  });
  const sample = { unchecked: null, checked: null, disabled: null };
  for (const b of boxes) {
    const s = state(b);
    if (s.disabled && !sample.disabled) sample.disabled = s;
    if (!s.disabled && s.checked && !sample.checked) sample.checked = s;
    if (!s.disabled && !s.checked && !sample.unchecked) sample.unchecked = s;
  }
  let clipped = 0;
  if (card) {
    for (const el of card.querySelectorAll('span, b, div, label')) {
      if (!el.textContent || !el.textContent.trim()) continue;
      if (el.children.length) continue;
      const cs = getComputedStyle(el);
      if (cs.overflow === 'hidden' && el.scrollWidth > el.clientWidth + 1) clipped++;
    }
  }
  const de = document.documentElement;
  const rulesRows = card ? Array.from(card.querySelectorAll('[data-self-diag-cap]')).map((capEl) => {
    const row = Array.from(capEl.querySelectorAll('div')).find(
      (d) => d.textContent.trim().startsWith('Жёсткие правила:'));
    return { cap: capEl.dataset.selfDiagCap, text: row ? row.textContent.trim() : null };
  }) : [];
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    card_present: !!card,
    caps: caps.length,
    checkboxes: boxes.length,
    nativeCheckboxes: boxes.filter((b) => !b.classList.contains('ctl-check__box')).length,
    sample,
    hardRulesRows: rulesRows,
    hardRulesObjectLeak: /\[object Object\]/.test(card ? card.innerText : ''),
    accentUnique: Array.from(new Set(boxes.map((b) => getComputedStyle(b).accentColor))),
    sizeUnique: Array.from(new Set(boxes.map((b) => {
      const r = b.getBoundingClientRect();
      return Math.round(r.width) + 'x' + Math.round(r.height);
    }))),
    labelMinHeightUnique: Array.from(new Set(boxes.map(
      (b) => getComputedStyle(b.closest('label')).minHeight))),
    hScroll: Math.max(0, de.scrollWidth - de.clientWidth),
    bodyHScroll: Math.max(0, document.body.scrollWidth - document.body.clientWidth),
    clippedText: clipped,
    card_text_head: card ? card.innerText.replace(/\s+/g, ' ').trim().slice(0, 800) : null,
  };
})()
"""

FIND_UNCHECKED = r"""
(() => {
  const card = document.querySelector('[data-self-diag-access]');
  if (!card) return null;
  const all = Array.from(card.querySelectorAll('input[type="checkbox"]'));
  const target = all.find((b) => !b.disabled && !b.checked);
  if (!target) return null;
  const capEl = target.closest('[data-self-diag-cap]');
  const actionEl = target.closest('[data-self-diag-action]');
  const group = Array.from((actionEl || card).querySelectorAll('input[type="checkbox"]'));
  return {
    cap: capEl ? capEl.dataset.selfDiagCap : null,
    action: actionEl ? actionEl.dataset.selfDiagAction : null,
    index_in_action: group.indexOf(target),
    checked_before: target.checked,
    role: target.closest('label').textContent.trim().split('\n')[0].slice(0, 24),
  };
})()
"""


def served_sha(path: str) -> dict:
    from live_258198 import BASE
    with urllib.request.urlopen(BASE + path, timeout=40) as resp:
        raw = resp.read()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "release": "2.58.198",
        "candidate": "dae6ffeae07cbf2b8d533bb99eaeaf267de335a2",
        "release_sha": "234776589c934024ed0e8dceba189fb9d70d3215",
        "mode": "DEPLOYED prod, read-only (no saves, no messages)",
        "url": URL,
        "chat_id": CHAT,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "served_assets": {},
        "screens": {},
        "images": [],
        "console_errors": [],
        "failures": [],
        "skips": [],
    }
    failures, skips = result["failures"], result["skips"]
    try:
        for path in ("/web/app.js", "/web/", "/web/static/app.css"):
            try:
                result["served_assets"][path] = served_sha(path)
            except Exception as exc:
                result["served_assets"][path] = {"error": type(exc).__name__}
    except Exception:
        pass

    init = json.dumps(H.INIT)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for label, vp, mobile in (("390x844", {"width": 390, "height": 844}, True),
                                      ("1536x960", {"width": 1536, "height": 960}, False)):
                ctx = browser.new_context(viewport=vp, is_mobile=mobile, has_touch=mobile,
                                          device_scale_factor=2, locale="ru-RU")
                ctx.add_init_script(INIT_SCRIPT % (init, H.OWNER, init, CHAT))
                page = ctx.new_page()
                page.on("console", lambda m, L=label: result["console_errors"].append(
                    "%s: %s" % (L, m.text[:200])) if m.type == "error" else None)
                page.on("pageerror", lambda e, L=label: result["console_errors"].append(
                    "%s pageerror: %s" % (L, str(e)[:200])))
                page.on("dialog", lambda d: d.accept())
                page.goto(URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3500)
                if page.query_selector("[data-self-diag-access-toggle]"):
                    page.click("[data-self-diag-access-toggle]", timeout=10000)
                try:
                    page.wait_for_selector("[data-self-diag-cap]", timeout=25000)
                except Exception:
                    failures.append("%s: матрица не появилась" % label)
                    result["screens"][label] = {"card_present": False,
                                                "body_head": page.inner_text("body")[:400]}
                    page.screenshot(path=str(OUT / ("live-f3-matrix-%s-missing-2.58.198.png" % label)))
                    ctx.close()
                    continue
                page.wait_for_timeout(700)
                card = page.query_selector("[data-self-diag-access]")
                if card:
                    card.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                probe = page.evaluate(PROBE)
                result["screens"][label + "_default"] = probe
                p1 = OUT / ("live-f3-matrix-%s-default-2.58.198.png" % label)
                page.screenshot(path=str(p1))
                result["images"].append(p1.name)
                if card:
                    p2 = OUT / ("live-f3-matrix-%s-default-block-2.58.198.png" % label)
                    card.screenshot(path=str(p2))
                    result["images"].append(p2.name)

                target = page.evaluate(FIND_UNCHECKED)
                if not target:
                    skips.append("%s: нет enabled+unchecked контрола — toggle не выполнялся "
                                 "(сохранённые overrides чата)" % label)
                else:
                    cap_el = page.query_selector('[data-self-diag-cap="%s"]' % target["cap"])
                    sel = ('[data-self-diag-cap="%s"] [data-self-diag-action="%s"] '
                           'input.ctl-check__box'
                           % (target["cap"], target["action"]))
                    box = page.locator(sel).nth(target["index_in_action"])
                    if cap_el:
                        cap_el.scroll_into_view_if_needed()
                        page.wait_for_timeout(200)
                        p3 = OUT / ("live-f3-matrix-%s-toggle-before-2.58.198.png" % label)
                        cap_el.screenshot(path=str(p3))
                        result["images"].append(p3.name)
                    box.click(timeout=10000)
                    page.wait_for_timeout(400)
                    after = page.evaluate(PROBE)
                    after["clicked"] = target
                    after["clicked_state"] = page.evaluate(
                        """([sel, idx]) => { const b = document.querySelectorAll(sel)[idx];
                            return b ? {checked: b.checked, disabled: b.disabled} : null; }""",
                        [sel, target["index_in_action"]])
                    result["screens"][label + "_after_toggle"] = after
                    if cap_el:
                        p4 = OUT / ("live-f3-matrix-%s-toggle-after-2.58.198.png" % label)
                        cap_el.screenshot(path=str(p4))
                        result["images"].append(p4.name)
                    if card:
                        p5 = OUT / ("live-f3-matrix-%s-checked-block-2.58.198.png" % label)
                        card.screenshot(path=str(p5))
                        result["images"].append(p5.name)
                    if not after["clicked_state"] or not after["clicked_state"]["checked"]:
                        failures.append("%s: клик не включил контрол (%s)" % (label, after["clicked_state"]))
                    if after["clicked_state"] and after["clicked_state"]["disabled"]:
                        failures.append("%s: после клика контрол disabled" % label)

                for key, pr in result["screens"].items():
                    if not key.startswith(label):
                        continue
                    if not pr.get("card_present", True):
                        continue
                    tag = "%s/%s" % (label, key.split("_", 1)[-1])
                    if pr["nativeCheckboxes"]:
                        failures.append("%s: нативных чекбоксов %d" % (tag, pr["nativeCheckboxes"]))
                    if pr["hScroll"] or pr["bodyHScroll"]:
                        failures.append("%s: hScroll=%s body=%s" % (tag, pr["hScroll"], pr["bodyHScroll"]))
                    if pr["clippedText"]:
                        failures.append("%s: обрезанный текст %d" % (tag, pr["clippedText"]))
                    if pr["sizeUnique"] != [EXPECTED_SIZE]:
                        failures.append("%s: размеры контролов %s" % (tag, pr["sizeUnique"]))
                    if pr["accentUnique"] != [EXPECTED_ACCENT]:
                        failures.append("%s: accent %s" % (tag, pr["accentUnique"]))
                    if pr.get("hardRulesObjectLeak"):
                        failures.append("%s: '[object Object]' в карточке" % tag)
                    rows = [r for r in (pr.get("hardRulesRows") or []) if r.get("text")]
                    if not rows:
                        failures.append("%s: ни одной строки «Жёсткие правила»" % tag)
                    for r in rows:
                        leak = re.search(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", r["text"])
                        if leak:
                            failures.append("%s: внутренний код правила в UI (%s: %s)"
                                            % (tag, r["cap"], leak.group(0)))
                            break
                    for st in ("unchecked", "checked", "disabled"):
                        if not (pr.get("sample") or {}).get(st):
                            skips.append("%s: состояние %s отсутствует в живых данных чата" % (tag, st))
                ctx.close()
        finally:
            browser.close()

    errs = [e for e in result["console_errors"] if "favicon" not in e]
    result["console_errors"] = errs
    if errs:
        failures.append("console/pageerror: %s" % errs[:3])
    (OUT / "live-f3-matrix-2.58.198.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("served_assets", "failures", "skips", "images")},
                     ensure_ascii=False, indent=1)[:3000])
    for key, pr in result["screens"].items():
        if isinstance(pr, dict) and pr.get("card_present", True):
            print("%-26s caps=%s boxes=%s native=%s sizes=%s accent=%s hScroll=%s clipped=%s rules=%s" % (
                key, pr.get("caps"), pr.get("checkboxes"), pr.get("nativeCheckboxes"),
                pr.get("sizeUnique"), pr.get("accentUnique"), pr.get("hScroll"),
                pr.get("clippedText"), [r["text"][:60] for r in (pr.get("hardRulesRows") or []) if r.get("text")][:2]))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
