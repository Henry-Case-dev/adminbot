# -*- coding: utf-8 -*-
"""ACCEPTANCE-95 — live rendered view of the prod MiniApp (real admin UI).

Local Playwright (no SSH): loads the DEPLOYED page from the prod URL and
renders as the admin, using a TMA initData built at runtime from the local
.env bot token (never written to disk or evidence).

Checks:
  * CFG-03.6 live (a): the 5 honest «Не влияет…» descriptions rendered in the
    real admin UI (Память tab + «Ответы в чате» + «Выжимка видео» modals) +
    `limits.memory_backup_keep` («НЕ действует»);
  * CFG-02B.2/.2.3/.8 UI part: with a temporary chat-scoped premise (budgets
    ON + freq ON) the compact freq settings are shown (burst/cooldown/mode),
    the mode select has exactly 2 mutually exclusive options, the «Лимиты
    генерации» facts block shows activity/scope/source/remaining/next; then
    the premise is restored exactly and the honest OFF state is re-verified;
  * mobile 390px: same facts visible, no horizontal overflow;
  * console errors collected.

Evidence: OPENCODE_WORKFLOW_SCRATCH/acceptance-95/evidence/ui/** +
ui-live-check95.json (+ API request/response log).

Run: .venv\\Scripts\\python.exe ui_live_check95.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(r"C:\Code\Python\adminbot")
OUT = REPO / "OPENCODE_WORKFLOW_SCRATCH" / "acceptance-95" / "evidence"
BASE = "https://admin-bot.duckdns.org"
ADMIN_ID = 5885953495
WORK_CHAT = -1002661910336
HONEST = "Не влияет"
NOT_ACTING = "НЕ действует"

TOUCHED = ["flags.budgets_enabled", "limits.image_daily_limit",
           "limits.image_freq_limit_enabled",
           "limits.image_freq_limit_burst",
           "limits.image_freq_limit_cooldown_seconds",
           "limits.image_freq_limit_mode"]

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
  const vm = window.__adminbotVm;
  if (!vm) return 'no-vm';
  const m = (vm.modules || []).find(x => x && x.id === id);
  if (!m) return 'no-module';
  try {
    if (typeof vm.closeModule === 'function' && vm.openModuleId) {
      vm.closeModule();
    }
    vm.openModuleWindow(m);
  } catch (e) { return 'error:' + (e && e.message ? e.message : 'x'); }
  return (vm.openModuleId === id) ? 'opened' : ('not-opened:' + vm.openModuleId);
}
"""

EXPAND_MODAL_JS = """
() => {
  const root = document.querySelector('.modal-body');
  if (!root) return 0;
  let n = 0;
  root.querySelectorAll('summary').forEach(s => {
    if ((s.textContent || '').indexOf('Расширенные') >= 0) {
      const d = s.closest('details'); if (d) { d.open = true; n += 1; }
    }
  });
  return n;
}
"""

LOAD_QUOTA_JS = """
async () => {
  const vm = window.__adminbotVm;
  if (!vm) return 'no-vm';
  try {
    if (typeof vm.maybeLoadImageQuota === 'function') {
      await vm.maybeLoadImageQuota();
    }
    if (!vm.budgetInfo && typeof vm.loadBudgetInfo === 'function') {
      await vm.loadBudgetInfo();
    }
  } catch (e) { return 'error:' + (e && e.message ? e.message : 'x'); }
  const bi = vm.budgetInfo || null;
  const entry = bi ? (bi.chats || []).find(c => c.scope === 'chat:%d') : null;
  return {
    budget_present: !!bi,
    chats_len: bi ? (bi.chats || []).length : 0,
    entry_has_image_usage: entry ? !!entry.image_usage : false,
    entry_has_freq: (entry && entry.image_usage)
      ? ('freq' in entry.image_usage) : false,
  };
}
""" % WORK_CHAT

FREQ_UI_JS = """
() => {
  const res = {};
  const q = (sel) => document.querySelector(sel);
  const txt = (sel) => { const e = q(sel);
    return e ? (e.innerText || e.textContent || '')
      .replace(/\\s+/g, ' ').trim() : null; };
  res.facts_present = !!q('[data-image-freq-facts]');
  res.active_label = txt('[data-image-freq-active]');
  res.mode_label = txt('[data-image-freq-mode]');
  res.source_label = txt('[data-image-freq-source]');
  res.remaining = txt('[data-image-freq-remaining]');
  res.next = txt('[data-image-freq-next]');
  res.burst_input = !!q('[data-image-freq-burst-input]');
  res.cooldown_input = !!q('[data-image-freq-cooldown-input]');
  res.burst_value = q('[data-image-freq-burst-input]')
    ? q('[data-image-freq-burst-input]').value : null;
  res.cooldown_value = q('[data-image-freq-cooldown-input]')
    ? q('[data-image-freq-cooldown-input]').value : null;
  res.quota_facts_present = !!q('[data-image-quota-facts]');
  res.quota_scope_label = txt('[data-image-quota-scope-label]');
  res.quota_used = txt('[data-image-quota-used]');
  res.quota_remaining = txt('[data-image-quota-remaining]');
  res.quota_mode_notice = txt('[data-image-quota-mode]');
  // enabled toggle state (bool item card for limits.image_freq_limit_enabled)
  const leaves = Array.from(document.querySelectorAll('div'))
    .filter(d => d.children.length === 0);
  const keyEl = leaves.find(d => (d.textContent || '').trim()
    === 'limits.image_freq_limit_enabled');
  if (keyEl) {
    let card = keyEl;
    while (card.parentElement && card.parentElement.className.indexOf('grid') < 0) {
      card = card.parentElement;
    }
    const cb = card.querySelector('input[type=checkbox]');
    res.freq_toggle_present = !!cb;
    res.freq_toggle_checked = cb ? !!cb.checked : null;
  } else { res.freq_toggle_present = false; }
  // mode select options (card for limits.image_freq_limit_mode)
  const modeEl = leaves.find(d => (d.textContent || '').trim()
    === 'limits.image_freq_limit_mode');
  if (modeEl) {
    let card = modeEl;
    while (card.parentElement && card.parentElement.className.indexOf('grid') < 0) {
      card = card.parentElement;
    }
    const sel = card.querySelector('select');
    res.mode_select_present = !!sel;
    res.mode_options = sel ? Array.from(sel.options).map(o => o.value) : null;
    res.mode_options_labels = sel
      ? Array.from(sel.options).map(o => (o.textContent || '').trim()) : null;
    res.mode_checked_count = card.querySelectorAll('input[type=checkbox]').length;
  } else { res.mode_select_present = false; }
  return res;
}
"""


def _token() -> str:
    txt = (REPO / ".env").read_text(encoding="utf-8", errors="replace")
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("API_TOKEN not found in .env")


def make_init_data(tok: str, user_id: int = ADMIN_ID) -> str:
    fields = {"auth_date": str(int(time.time())),
              "query_id": "AAHaccept95ui",
              "user": json.dumps({"id": user_id, "first_name": "Accept95",
                                  "username": "accept95"},
                                 separators=(",", ":"))}
    dc = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, dc.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


class ApiLog:
    def __init__(self, init_data: str):
        self.init = init_data
        self.log: list[dict] = []

    def req(self, method: str, path: str, body=None, chat_id=WORK_CHAT):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={
                                         "X-Telegram-Init-Data": self.init,
                                         "X-Chat-Id": str(chat_id),
                                         "Content-Type": "application/json",
                                         "User-Agent": "accept95-ui"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", "replace")
                status = r.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            status = exc.code
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw_head": raw[:200]}
        rec = {"method": method, "path": path, "chat_id": chat_id,
               "status": status,
               "body_head": json.dumps(parsed, ensure_ascii=False)[:400]}
        self.log.append(rec)
        return status, parsed

    def cfg(self):
        st, body = self.req("GET", "/api/config")
        items = body.get("items") if isinstance(body, dict) else []
        return {str(it.get("key")): it for it in (items or [])}


def _expand_advanced(page) -> None:
    page.evaluate(
        "(() => { document.querySelectorAll('summary').forEach(s => {"
        "  if ((s.textContent || '').indexOf('Расширенные') >= 0) {"
        "    const d = s.closest('details'); if (d) d.open = true; } }); })()")
    page.wait_for_timeout(400)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ui_dir = OUT / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    tok = _token()
    init = make_init_data(tok)
    api = ApiLog(init)
    result: dict = {"console_errors": [], "checks": {}, "screenshots": [],
                    "now_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                             time.gmtime())}

    # snapshot the touched chat values BEFORE any premise
    before = api.cfg()
    snapshot = {k: (before.get(k) or {}).get("value") for k in TOUCHED}
    snapshot_source = {k: (before.get(k) or {}).get("chat_source")
                       for k in TOUCHED}
    result["premise_snapshot"] = {"values": snapshot,
                                  "chat_source": snapshot_source}

    from playwright.sync_api import sync_playwright
    checks = result["checks"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000},
                                  reduced_motion="reduce")
        ctx.add_init_script(
            "try { sessionStorage.setItem('adminbot.initData', %s); } "
            "catch (e) {}" % json.dumps(init))
        page = ctx.new_page()
        page.on("console", lambda m: result["console_errors"].append(
            m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(
            "pageerror: " + str(e)[:200]))
        page.on("dialog", lambda d: d.accept())
        page.goto(BASE + "/web/", wait_until="load", timeout=60000)
        try:
            page.wait_for_function(
                "typeof window.__adminbotVm !== 'undefined'", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        checks["vm_present"] = page.evaluate(
            "typeof window.__adminbotVm !== 'undefined'")
        checks["served_version_in_html"] = page.evaluate(
            "document.documentElement.outerHTML.includes('2.58.95')")
        if checks["vm_present"]:
            page.evaluate("window.__adminbotVm.setActiveChat(%d)" % WORK_CHAT)
            page.wait_for_timeout(1200)

        # ── 1. Память (#/memory/rag): честные описания ─────────────────────
        page.evaluate("window.location.hash = '#/memory/rag'")
        page.wait_for_timeout(1400)
        try:
            page.wait_for_selector('[data-config-group]', timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(700)
        _expand_advanced(page)
        for gid, key in (("search", "limits.dig_year_back_window_days"),
                         ("storage", "limits.memory_backup_keep")):
            checks["memory_%s" % key] = page.evaluate(
                CARD_BY_KEY_JS, {"gid": gid, "key": key})
        shot = ui_dir / "01-memory-honest-desc-live.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshots"].append(shot.name)

        # ── 2. Модалка «Ответы в чате» ─────────────────────────────────────
        page.evaluate("window.location.hash = '#/modules'")
        page.wait_for_timeout(1400)
        checks["open_direct"] = page.evaluate(OPEN_MODULE_JS, "mod_direct")
        page.wait_for_timeout(1400)
        page.evaluate(EXPAND_MODAL_JS)
        page.wait_for_timeout(500)
        for key in ("limits.chat_lock_max_entries",
                    "limits.chat_budget_response_ratio"):
            checks["direct_%s" % key] = page.evaluate(
                CARD_BY_TITLE_JS, {"limits.chat_lock_max_entries":
                                   "Потолок словаря замков",
                                   "limits.chat_budget_response_ratio":
                                   "Доля бюджета: Response"}[key])
        shot = ui_dir / "02-module-direct-honest-desc-live.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshots"].append(shot.name)

        # ── 3. Модалка «Выжимка видео» ─────────────────────────────────────
        checks["open_video"] = page.evaluate(OPEN_MODULE_JS,
                                             "mod_video_summary")
        page.wait_for_timeout(1400)
        page.evaluate(EXPAND_MODAL_JS)
        page.wait_for_timeout(500)
        for key, title in (
                ("limits.youtube_transcript_proxy_locations",
                 "CSV-коды стран Webshare"),
                ("limits.youtube_transcript_proxy_retries",
                 "Повторы при блокировке (Webshare)")):
            checks["video_%s" % key] = page.evaluate(CARD_BY_TITLE_JS, title)
        checks["video_content_media"] = page.evaluate(
            """() => {
              const root = document.querySelector('.modal-body');
              if (!root) return { modal: false };
              const txt = (root.innerText || '');
              return { modal: true,
                groups: Array.from(root.querySelectorAll('[data-config-group]'))
                  .map(e => e.getAttribute('data-config-group')),
                share: txt.indexOf('Каталог временной публикации видео') >= 0,
                public: txt.indexOf('Внешний базовый адрес /media') >= 0 };
            }""")
        shot = ui_dir / "03-module-video-honest-desc-live.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshots"].append(shot.name)

        # ── 4. CFG-02B premise: freq ON (chat) → UI checks ────────────────
        # `image_daily_limit` temporarily raised (used+50) so that enabling
        # the budgets master does NOT deny the owner's real generations in
        # this short window; it is restored (override removed) afterwards.
        st, budget_now = api.req("GET", "/api/workers/budget")
        entry = None
        for e in (budget_now.get("chats") or []):
            if str(e.get("scope")) == "chat:%d" % WORK_CHAT:
                entry = e
                break
        used_now = int(((entry or {}).get("image_calls") or {}).get(
            "used") or 0)
        result["premise_used_now"] = used_now
        st, body = api.req("POST", "/api/config", body={"items": [
            {"key": "flags.budgets_enabled", "value": True},
            {"key": "limits.image_daily_limit", "value": used_now + 50},
            {"key": "limits.image_freq_limit_enabled", "value": True},
            {"key": "limits.image_freq_limit_burst", "value": 2},
            {"key": "limits.image_freq_limit_cooldown_seconds", "value": 120},
            {"key": "limits.image_freq_limit_mode", "value": "per_user"},
        ], "updated_at": None})
        result["premise_write"] = {"status": st,
                                   "body": json.dumps(body,
                                                      ensure_ascii=False)[:300]}
        page.reload(wait_until="load", timeout=60000)
        try:
            page.wait_for_function(
                "typeof window.__adminbotVm !== 'undefined'", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        if checks.get("vm_present"):
            page.evaluate("window.__adminbotVm.setActiveChat(%d)" % WORK_CHAT)
            page.wait_for_timeout(900)
        page.evaluate("window.location.hash = '#/modules/images/settings'")
        try:
            page.wait_for_selector('[data-config-group="limits_images"]',
                                   timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        _expand_advanced(page)
        checks["quota_load"] = page.evaluate(LOAD_QUOTA_JS)
        try:
            page.wait_for_selector('[data-image-freq-facts]', timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        checks["freq_ui_on"] = page.evaluate(FREQ_UI_JS)
        shot = ui_dir / "04-images-freq-on-facts-live.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshots"].append(shot.name)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(1000)
        checks["freq_ui_on_mobile"] = page.evaluate(FREQ_UI_JS)
        checks["mobile_no_overflow"] = page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 2")
        shot = ui_dir / "05-images-freq-on-mobile-live.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshots"].append(shot.name)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.wait_for_timeout(600)

        # ── 5. restore the premise EXACTLY (snapshot values/override state) ─
        restore_items = []
        restore_deletes = []
        for k in TOUCHED:
            if snapshot_source.get(k) == "chat":
                restore_items.append({"key": k, "value": snapshot[k]})
            else:
                restore_deletes.append(k)
        st2, body2 = api.req("POST", "/api/config",
                             body={"items": restore_items,
                                   "updated_at": None})
        result["restore_write"] = {
            "status": st2, "body": json.dumps(body2,
                                              ensure_ascii=False)[:300]}
        result["restore_deletes"] = {}
        for k in restore_deletes:
            st3, body3 = api.req(
                "DELETE", "/api/config/chat/" + urllib.parse.quote(k))
            result["restore_deletes"][k] = {
                "status": st3,
                "body": json.dumps(body3, ensure_ascii=False)[:200]}
        time.sleep(2)
        after = api.cfg()
        result["config_after_restore"] = {
            k: {"value": (after.get(k) or {}).get("value"),
                "chat_source": (after.get(k) or {}).get("chat_source")}
            for k in TOUCHED}
        result["restore_matches"] = all(
            (after.get(k) or {}).get("value") == snapshot[k]
            and (after.get(k) or {}).get("chat_source", "")
            == (snapshot_source.get(k) or "")
            for k in TOUCHED)
        page.reload(wait_until="load", timeout=60000)
        try:
            page.wait_for_function(
                "typeof window.__adminbotVm !== 'undefined'", timeout=45000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        if checks.get("vm_present"):
            page.evaluate("window.__adminbotVm.setActiveChat(%d)" % WORK_CHAT)
            page.wait_for_timeout(900)
        page.evaluate("window.location.hash = '#/modules/images/settings'")
        try:
            page.wait_for_selector('[data-config-group="limits_images"]',
                                   timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        checks["quota_load_after_restore"] = page.evaluate(LOAD_QUOTA_JS)
        page.wait_for_timeout(800)
        checks["freq_ui_after_restore"] = page.evaluate(FREQ_UI_JS)
        shot = ui_dir / "06-images-freq-off-restored-live.png"
        page.screenshot(path=str(shot), full_page=True)
        result["screenshots"].append(shot.name)

        browser.close()

    result["api_log"] = api.log
    (OUT / "ui-live-check95.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── verdict ───────────────────────────────────────────────────────────
    def honest(name):
        card = checks.get(name) or {}
        return bool(card.get("card")) and HONEST in str(card.get("text"))

    fu = checks.get("freq_ui_on") or {}
    fum = checks.get("freq_ui_on_mobile") or {}
    off = checks.get("freq_ui_after_restore") or {}
    ok = (
        not result["console_errors"]
        and honest("memory_limits.dig_year_back_window_days")
        and NOT_ACTING in str((checks.get("memory_limits.memory_backup_keep")
                               or {}).get("text"))
        and honest("direct_limits.chat_lock_max_entries")
        and honest("direct_limits.chat_budget_response_ratio")
        and honest("video_limits.youtube_transcript_proxy_locations")
        and honest("video_limits.youtube_transcript_proxy_retries")
        # video_content_media: информационно (bonus для CFG-03.1); основное
        # требование 03.6 — 5 честных описаний выше.
        # CFG-02B.2: settings shown when ON
        and fu.get("burst_input") and fu.get("cooldown_input")
        and fu.get("freq_toggle_checked") is True
        and str(fu.get("burst_value")) == "2"
        and str(fu.get("cooldown_value")) == "120"
        # CFG-02B.2.3: exactly two mutually exclusive options
        and fu.get("mode_select_present")
        and sorted(fu.get("mode_options") or []) == ["per_chat", "per_user"]
        and fu.get("mode_checked_count") == 0
        # CFG-02B.8: facts block with activity/scope/source/remaining/next
        and fu.get("facts_present")
        and "Включено" in str(fu.get("active_label"))
        and "действует" in str(fu.get("active_label")).lower()
        and fu.get("mode_label") and fu.get("source_label")
        and fu.get("remaining") and fu.get("next")
        and fu.get("quota_facts_present")
        # mobile: same facts, no overflow
        and fum.get("facts_present")
        and checks.get("mobile_no_overflow") is True
        # honest OFF state restored
        and result.get("restore_matches") is True
        and "Выключено" in str(off.get("active_label"))
        and off.get("burst_input") is False
    )
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("api_log",)}, ensure_ascii=False,
                     indent=1)[:6000])
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
