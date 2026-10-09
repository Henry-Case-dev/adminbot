"""ASAP 7 (F3, §3.1–§3.3) — Playwright/Chromium Browser-Verification модуля
«Инициатива» + registry-merge на РЕАЛЬНЫХ web/index.html / app.js / app.css
(статика + route-стабы API; прецеденты ui_round1025_matrix,
ui_mca12_stories_e2e). ЭТО НЕ production acceptance (живая приёмка —
@Owner в Telegram WebView); проверяются измеримые DOM-контракты:

  * «Модули»: карточка mod_initiative присутствует (desktop + mobile),
    registry-injected карточка (F4-путь, без правки JS-каркаса) появляется;
  * #/modules/initiative: workspace-голова, табы overview/settings/limits,
    живой блок data-initiative-status (requested/effective/source, heartbeat,
    pending, последнее решение/пропуск, next due);
  * settings-вкладка рендерит СОБСТВЕННУЮ группу flags_intent (4 тумблера),
    limits-вкладка — limits_intent (5 лимитов) через generic-рендер;
  * env-emergency OFF (intents.module.source=emergency_env): честный
    «Не работает» + restart-пометка env-оси;
  * «Настройки блока» Статуса: СОБСТВЕННЫЕ Intent-ключи + ссылки-переходы,
    ЧУЖИЕ random/budget ключи отсутствуют (фикс P7-C-3);
  * отсутствие horizontal overflow на проверенных маршрутах.

Запуск: .venv\\Scripts\\python tools\\ui_asap7_f3_e2e.py
Артефакты: tools/_ui_asap7_f3_e2e.json, tools/_ui_asap7_f3_*.png
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA-стаб — reuse)

PORT = M.PORT
RAW = os.path.join(M.REPO, "tools", "_ui_asap7_f3_e2e.json")
SHOT_DIR = os.path.join(M.REPO, "tools")

CHAT_ID = -1001234567890
NOW = 1790000000

VIEWPORTS = (
    ("desktop_1280x800", {"width": 1280, "height": 800}, False),
    ("mobile_390x844", {"width": 390, "height": 844}, True),
)

# F4-путь: модуль из реестра, которого НЕТ в JS-витрине (каркас не правится).
EXTRA_REGISTRY_MODULE = {
    "id": "randomness_probe", "title": "Случайность (probe)",
    "parent_id": None,
    "description": "F4-проба: карточка приходит из реестра.",
    "master_param": "memory.random_source", "runtime_gate": "global",
    "settings_groups": ["memory_random"], "model_slots": [],
    "status_source": "status.random", "analytics_anchor": "random.uses",
    "help_anchor": "Источник случайности", "visibility": "visible",
    "classification": "submodule", "rationale": "e2e probe (F4-путь)",
    "tab": "mod_randomness_probe", "route": "#/modules/randomness_probe",
}


def _config_stub_with_modules() -> dict:
    data = M._config_stub()
    # Когерентность витрины: product-оси Initiative ON (как в проде —
    # 0 env-оверрайдов), иначе тумблер «Выключен» при статусе «Работает».
    for it in data.get("items", []):
        if it.get("key") in ("flags.initiative_enabled",
                             "flags.intent_heartbeat_enabled",
                             "flags.intent_decision_enabled",
                             "flags.send_recheck_enabled"):
            it["value"] = True
    try:
        from services.module_registry import registry_for_frontend
        modules = registry_for_frontend()
    except Exception as exc:  # noqa: BLE001
        print("[f3-e2e] registry недоступен:", exc)
        modules = []
    data["modules"] = modules + [dict(EXTRA_REGISTRY_MODULE)]
    return data


CONFIG_STUB = _config_stub_with_modules()

INTENTS_MODULE_ON = {
    "module_id": "initiative",
    "master_param": "flags.initiative_enabled",
    "env_param": "MCA_INTENTS_ENABLED",
    "requested": True, "effective": True, "source": "both",
    "env_enabled": True,
    "pending": 2,
    "last_decision": {"ts": NOW - 600, "outcome": "reply",
                      "reason_code": "default", "action": "sent"},
    "last_skip": {"ts": NOW - 1200, "event": "recheck_deferred",
                  "reason_code": "already_answered"},
    "next_due": NOW + 900,
    "heartbeat": {"job": "intent_heartbeat_tick", "tick_seconds": 300,
                  "enabled": True, "restart_required_env": True},
}

INTENTS_MODULE_EMERGENCY_OFF = dict(INTENTS_MODULE_ON)
INTENTS_MODULE_EMERGENCY_OFF.update({
    "requested": True, "effective": False, "source": "emergency_env",
    "env_enabled": False,
    # K1 OFF → K2-тик инертен (bit-parity mca-09)
    "heartbeat": dict(INTENTS_MODULE_ON["heartbeat"], enabled=False),
})

INTENTS_ON = {
    "enabled": True, "state": "ok", "active": 2,
    "top": [{"intent_id": "in-1", "kind": "follow_up",
             "goal": "Спросить про смету", "status": "pending",
             "next_check_at": NOW + 900, "priority": 2}],
    "last_action": {"ts": NOW - 600, "event": "initiative_decided",
                    "outcome": "reply", "reason_code": "default",
                    "trigger_kind": "intent_due", "action": "sent"},
    "module": INTENTS_MODULE_ON,
}

STATUS_STUB = dict(M.STATUS_STUB)
STATUS_STUB.update({
    "permsoc": {"master": True, "enabled": 5, "total": 5, "modules": {}},
    "random": {"enabled": True, "state": "ok"},
    "experience": {"enabled": True, "state": "implemented",
                   "items": [], "counters": {}, "improvement": []},
    "llm_stats": {"requests": 1, "timeouts": 0, "fallbacks": 0,
                  "timeout_share": 0.0},
    "intents": INTENTS_ON,
})

STATUS_STUB_EMERGENCY = dict(STATUS_STUB)
STATUS_STUB_EMERGENCY["intents"] = dict(INTENTS_ON, module=INTENTS_MODULE_EMERGENCY_OFF)

API_EXTRA = [
    ("/api/workers/budget", {}),
    ("/api/analytics/usage/latest", {}),
    ("/api/analytics/budget", {}),
    ("/api/vision/state", {}),
    ("/api/factcheck/temporal/runs", {"runs": []}),
    ("/api/persona/self-model", {}),
    ("/api/status/media-health", {}),
]


def _api_handler_factory(status_payload):
    import urllib.parse

    def _handler(route, request):
        path = urllib.parse.urlparse(request.url).path
        if path.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(M.ME_JSON))
            return
        if path.endswith("/api/status"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(status_payload))
            return
        if path.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(CONFIG_STUB))
            return
        for marker, payload in API_EXTRA:
            if path.endswith(marker):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))
                return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(request.url)))

    return _handler


PROBE_HUB = r"""
(() => {
  const de = document.documentElement;
  const vw = window.innerWidth;
  const card = document.querySelector('[data-mod="mod_initiative"]');
  const probeCard = document.querySelector(
    '[data-mod="mod_randomness_probe"]');
  return {
    innerWidth: vw,
    docOverflow: de.scrollWidth > vw + 1
      || document.body.scrollWidth > vw + 1,
    initiativeCard: !!card,
    initiativeTitle: card ? (card.textContent.includes('Инициатива'))
      : false,
    registryProbeCard: !!probeCard,
  };
})()
"""

PROBE_WORKSPACE = r"""
(() => {
  const de = document.documentElement;
  const vw = window.innerWidth;
  const head = document.querySelector('[data-workspace-head]');
  const status = document.querySelector('[data-initiative-status]');
  const tabs = Array.from(
    document.querySelectorAll('[data-workspace-tab]')).map(e => e.dataset
    .workspaceTab);
  const st = status ? status.textContent : '';
  return {
    innerWidth: vw,
    docOverflow: de.scrollWidth > vw + 1
      || document.body.scrollWidth > vw + 1,
    headModule: head ? head.dataset.module : null,
    tabs: tabs,
    hasStatus: !!status,
    statusText: st.slice(0, 500),
    effectiveOn: st.includes('Работает'),
    requestedLine: st.includes('requested:')
      && st.includes('flags.initiative_enabled'),
    sourceLine: st.includes('source:'),
    heartbeatLine: st.includes('intent_heartbeat_tick'),
    pendingLine: st.includes('Ожидают решения: 2'),
    decisionLine: st.includes('initiative_decided') ||
      st.includes('Последнее решение'),
    skipLine: st.includes('recheck_deferred') ||
      st.includes('Последний пропуск'),
    nextDueLine: st.includes('ближайшая проверка'),
  };
})()
"""

PROBE_TAB_GROUPS = r"""
((tab) => {
  const text = document.body.textContent;
  return {
    groupTitleIntent: text.includes('Модуль: Инициатива'),
    groupTitleLimits: text.includes('Инициатива: лимиты'),
    masterToggle: text.includes('включён (мастер)'),
    recheckToggle: text.includes('Проверка перед отправкой (recheck)'),
    batchLimit: text.includes('Heartbeat: батч due-скана'),
    backoffLimit: text.includes('Пауза после «не тот момент»'),
  };
})
"""

PROBE_STATUS_SETTINGS = r"""
(() => {
  const block = document.querySelector('[data-stories-settings]');
  if (!block) return { present: false };
  const text = block.textContent;
  const links = Array.from(block.querySelectorAll('a'))
    .map(a => a.getAttribute('href'));
  return {
    present: true,
    ownMaster: text.includes('Инициатива включена (мастер)'),
    ownHeartbeat: text.includes('Heartbeat: due-скан'),
    ownBackoff: text.includes('Пауза после «не тот момент»'),
    foreignRandom: text.includes('Спонтанность: вероятность исследования'),
    foreignBudget: text.includes('Фон: вызовов LLM в сутки на чат'),
    foreignContext: text.includes('Бюджет контекста, токенов'),
    // ASAP 7 F4: у «Случайности» появилась owner-подкарточка — ссылка
    // Initiative ведёт к владельцу (#/modules/random), а не к Сну.
    linkRandom: links.includes('#/modules/random'),
    linkBudgets: links.includes('#/modules/budgets'),
  };
})()
"""


def _record(failures, viewport, message):
    failures.append("[%s] %s" % (viewport, message))


def _wait_probe(page, probe_js, key, tries=40):
    probe = {}
    for _ in range(tries):
        probe = page.evaluate(probe_js)
        if probe.get(key):
            break
        page.wait_for_timeout(250)
    return probe


def _run():
    from playwright.sync_api import sync_playwright
    httpd = M._start_server()
    result = {"probes": {}, "screenshots": [], "console_errors": [],
              "failures": []}
    failures = result["failures"]
    url = "http://127.0.0.1:%d/web/index.html" % PORT
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for label, viewport, mobile in VIEWPORTS:
                ctx = browser.new_context(viewport=viewport,
                                          is_mobile=mobile,
                                          has_touch=mobile,
                                          reduced_motion="reduce")
                ctx.add_init_script(M.TMA_STUB)
                ctx.route("**/api/**",
                          _api_handler_factory(STATUS_STUB))
                page = ctx.new_page()
                page.on("console", lambda m, L=label: result[
                    "console_errors"].append("%s: %s" % (L, m.text[:200]))
                    if m.type == "error" else None)
                page.on("pageerror", lambda e, L=label: result[
                    "console_errors"].append("%s pageerror: %s"
                                             % (L, str(e)[:200])))
                # ── 1) Хаб «Модули»: карточка Initiative + registry-probe ──
                page.goto(url + "#/modules", wait_until="load")
                # ждём именно merge реестра (аддитивный путь после /api/config)
                hub = _wait_probe(page, PROBE_HUB, "registryProbeCard")
                result["probes"]["%s_hub" % label] = hub
                if not hub.get("initiativeCard"):
                    _record(failures, label,
                            "карточка mod_initiative не найдена в «Модулях»")
                if not hub.get("initiativeTitle"):
                    _record(failures, label,
                            "карточка без заголовка «Инициатива»")
                if not hub.get("registryProbeCard"):
                    _record(failures, label,
                            "F4-путь: карточка из registry не добавлена")
                if hub.get("docOverflow"):
                    _record(failures, label,
                            "hub: horizontal overflow")
                page.screenshot(path=os.path.join(
                    SHOT_DIR, "_ui_asap7_f3_%s_hub.png" % label),
                    full_page=True)
                result["screenshots"].append(
                    "_ui_asap7_f3_%s_hub.png" % label)
                # ── 2) Страница модуля: обзор с живым гейтом ────────────────
                page.goto(url + "#/modules/initiative", wait_until="load")
                ws = _wait_probe(page, PROBE_WORKSPACE, "hasStatus")
                result["probes"]["%s_workspace" % label] = ws
                if ws.get("headModule") != "mod_initiative":
                    _record(failures, label,
                            "workspace-голова не mod_initiative")
                for tab in ("overview", "settings", "limits"):
                    if tab not in (ws.get("tabs") or []):
                        _record(failures, label,
                                "вкладка %s не отрисована" % tab)
                if not ws.get("effectiveOn"):
                    _record(failures, label,
                            "обзор: effective ON не показан («Работает»)")
                if not ws.get("requestedLine"):
                    _record(failures, label,
                            "обзор: requested/мастер-ключ не показан")
                if not ws.get("sourceLine"):
                    _record(failures, label, "обзор: source не показан")
                if not ws.get("heartbeatLine"):
                    _record(failures, label,
                            "обзор: heartbeat-джоба не показана")
                if not ws.get("pendingLine"):
                    _record(failures, label,
                            "обзор: pending intents не показан")
                if not ws.get("decisionLine"):
                    _record(failures, label,
                            "обзор: последнее решение не показано")
                if not ws.get("skipLine"):
                    _record(failures, label,
                            "обзор: последний пропуск не показан")
                if not ws.get("nextDueLine"):
                    _record(failures, label, "обзор: next due не показан")
                if ws.get("docOverflow"):
                    _record(failures, label,
                            "workspace: horizontal overflow")
                page.screenshot(path=os.path.join(
                    SHOT_DIR, "_ui_asap7_f3_%s_overview.png" % label),
                    full_page=True)
                result["screenshots"].append(
                    "_ui_asap7_f3_%s_overview.png" % label)
                # ── 3) Вкладки settings/limits — собственные группы ────────
                if label.startswith("desktop"):
                    page.click('[data-workspace-tab="settings"]')
                    page.wait_for_timeout(400)
                    settings_probe = page.evaluate(
                        "(() => (%s))('settings')" % PROBE_TAB_GROUPS)
                    result["probes"]["%s_settings" % label] = settings_probe
                    if not settings_probe.get("groupTitleIntent"):
                        _record(failures, label,
                                "settings: группа flags_intent не отрисована")
                    if not settings_probe.get("masterToggle"):
                        _record(failures, label,
                                "settings: мастер-тумблер не отрисован")
                    page.click('[data-workspace-tab="limits"]')
                    page.wait_for_timeout(400)
                    limits_probe = page.evaluate(
                        "(() => (%s))('limits')" % PROBE_TAB_GROUPS)
                    result["probes"]["%s_limits" % label] = limits_probe
                    if not limits_probe.get("groupTitleLimits"):
                        _record(failures, label,
                                "limits: группа limits_intent не отрисована")
                    if not limits_probe.get("batchLimit"):
                        _record(failures, label,
                                "limits: лимит батча не отрисован")
                    page.screenshot(path=os.path.join(
                        SHOT_DIR, "_ui_asap7_f3_%s_settings.png" % label),
                        full_page=True)
                    result["screenshots"].append(
                        "_ui_asap7_f3_%s_settings.png" % label)
                    # ── 4) Статус: «Настройки блока» — свои ключи + ссылки ──
                    page.goto(url + "#/", wait_until="load")
                    page.wait_for_timeout(600)
                    # data-stories-settings рендерится после раскрытия
                    opened = False
                    for _ in range(20):
                        btn = page.query_selector(
                            'button[data-stories-settings], '
                            '[data-stories-settings]')
                        block = page.query_selector(
                            '[data-stories-settings]')
                        if block:
                            opened = True
                            break
                        toggle = None
                        for b in page.query_selector_all("button"):
                            if "Настройки блока" in (b.text_content() or ""):
                                toggle = b
                                break
                        if toggle:
                            toggle.click()
                        page.wait_for_timeout(250)
                    st_probe = page.evaluate(PROBE_STATUS_SETTINGS) \
                        if opened else {"present": False}
                    result["probes"]["%s_status_settings" % label] = st_probe
                    if not st_probe.get("present"):
                        _record(failures, label,
                                "«Настройки блока» не раскрылись на Статусе")
                    else:
                        if not st_probe.get("ownMaster"):
                            _record(failures, label,
                                    "настройки блока: свой мастер-ключ "
                                    "отсутствует")
                        if st_probe.get("foreignRandom"):
                            _record(failures, label,
                                    "настройки блока: ЧУЖИЙ ключ "
                                    "random_exploration_probability")
                        if st_probe.get("foreignBudget"):
                            _record(failures, label,
                                    "настройки блока: ЧУЖИЙ ключ "
                                    "worker_daily_llm_calls_per_chat")
                        if st_probe.get("foreignContext"):
                            _record(failures, label,
                                    "настройки блока: ЧУЖИЙ ключ "
                                    "chat_context_budget_tokens")
                        if not (st_probe.get("linkRandom")
                                and st_probe.get("linkBudgets")):
                            _record(failures, label,
                                    "настройки блока: ссылки-переходы "
                                    "не отрисованы")
                ctx.close()
            # ── 5) env-emergency OFF (desktop) — честный blocked ────────────
            ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                      reduced_motion="reduce")
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**",
                      _api_handler_factory(STATUS_STUB_EMERGENCY))
            page = ctx.new_page()
            page.goto(url + "#/modules/initiative", wait_until="load")
            emg = _wait_probe(page, PROBE_WORKSPACE, "hasStatus")
            result["probes"]["emergency_off_workspace"] = emg
            if emg.get("effectiveOn"):
                _record(failures, "emergency",
                        "env-emergency OFF показан как «Работает»")
            if "env-emergency" not in emg.get("statusText", ""):
                _record(failures, "emergency",
                        "source=emergency_env не подписан")
            if "рестарта" not in emg.get("statusText", ""):
                _record(failures, "emergency",
                        "restart-семантика env-оси не подписана")
            page.screenshot(path=os.path.join(
                SHOT_DIR, "_ui_asap7_f3_emergency_off.png"), full_page=True)
            result["screenshots"].append("_ui_asap7_f3_emergency_off.png")
            ctx.close()
            browser.close()
    finally:
        httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print("failures: %d" % len(failures))
    for f in failures:
        print("FAIL:", f)
    print("artifacts:", RAW)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
