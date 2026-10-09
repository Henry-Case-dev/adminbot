# -*- coding: utf-8 -*-
"""ASAP 7 (F4, §3.2) — Playwright/Chromium Browser-Verification подмодулей
реестра (stories/character/experience/random) на РЕАЛЬНЫХ web/index.html /
app.js / app.css (статика + route-стабы API; прецедент ui_asap7_f3_e2e).
ЭТО НЕ production acceptance (живая приёмка — @Owner в Telegram WebView);
проверяются измеримые DOM-контракты:

  * хаб «Модули»: 4 подкарточки из реестра (desktop + mobile), без overflow;
  * #/modules/stories: data-f4-module-gate (Работает/requested/source,
    env-ось, restart-пометка), табы overview+settings;
  * settings: ТОЛЬКО своя группа (flags_stories ×6 / flags_character ×7 /
    memory_experience / memory_random) — чужие группы отсутствуют
    («no orphan controls», паттерн Initiative);
  * random: переключателя в голове НЕТ («no master»), мастер — env-ось,
    ссылки-переходы Сон/Инициатива;
  * env-emergency OFF (stories): честный «Не работает» + restart-пометка;
  * отсутствие horizontal overflow на проверенных маршрутах.

Запуск: .venv\\Scripts\\python tools\\ui_asap7_f4_e2e.py
Артефакты: OPENCODE_WORKFLOW_SCRATCH (ui_asap7_f4_e2e.json, *.png).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA-стаб — reuse)

PORT = M.PORT
SCRATCH = os.environ.get("OPENCODE_WORKFLOW_SCRATCH") or os.path.join(
    M.REPO, "tools")
RAW = os.path.join(SCRATCH, "ui_asap7_f4_e2e.json")
SHOT_DIR = SCRATCH

VIEWPORTS = (
    ("desktop_1280x800", {"width": 1280, "height": 800}, False),
    ("mobile_390x844", {"width": 390, "height": 844}, True),
)

OWN_BOOL_KEYS = (
    "flags.stories_vitrina_enabled", "flags.stories_manage_enabled",
    "flags.episodes_enabled", "flags.episodes_compiler_facade_enabled",
    "flags.episodes_continuation_enabled", "flags.episodes_backfill_enabled",
    "flags.self_model_enabled", "flags.trait_rules_enabled",
    "flags.legacy_traits_migration_enabled",
    "flags.character_layers_enabled", "flags.character_speech_enabled",
    "flags.style_scope_enabled", "flags.postprocess_form_guard_enabled",
    "memory.experience_learning_enabled", "memory.random_fallback_to_pseudorandom",
)


def _config_stub_with_modules(gate_override=None) -> dict:
    data = M._config_stub()
    # Когерентность витрины: product-оси ON (иначе тумблер «выкл» при
    # статусе «Работает» — как в F3-прецеденте).
    for it in data.get("items", []):
        if it.get("key") in OWN_BOOL_KEYS:
            it["value"] = True
    try:
        from services.module_registry import registry_for_frontend
        modules = registry_for_frontend()
    except Exception as exc:  # noqa: BLE001
        print("[f4-e2e] registry недоступен:", exc)
        modules = []
    for spec in modules:
        if gate_override and spec.get("id") in gate_override:
            spec["gate"] = dict(spec.get("gate") or {}, **gate_override[spec["id"]])
    data["modules"] = modules
    return data


CONFIG_STUB = _config_stub_with_modules()
STORIES_EMERGENCY = _config_stub_with_modules(gate_override={
    "stories": {"requested": True, "effective": False,
                "source": "emergency_env", "env_enabled": False,
                "env_param": "MCA_STORIES_VITRINA_ENABLED",
                "master_param": "flags.stories_vitrina_enabled"}})

API_EXTRA = [
    ("/api/workers/budget", {}),
    ("/api/analytics/usage/latest", {}),
    ("/api/analytics/budget", {}),
    ("/api/vision/state", {}),
    ("/api/factcheck/temporal/runs", {"runs": []}),
    ("/api/persona/self-model", {}),
    ("/api/status/media-health", {}),
]


def _api_handler_factory(config_payload):
    import urllib.parse

    def _handler(route, request):
        path = urllib.parse.urlparse(request.url).path
        if path.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(M.ME_JSON))
            return
        if path.endswith("/api/status"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(M.STATUS_STUB))
            return
        if path.endswith("/api/config"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(config_payload))
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
  const q = (id) => document.querySelector('[data-mod="' + id + '"]');
  const byId = {};
  ['mod_stories', 'mod_character', 'mod_experience', 'mod_random']
    .forEach((id) => { byId[id] = !!q(id); });
  return {
    innerWidth: vw,
    docOverflow: de.scrollWidth > vw + 1
      || document.body.scrollWidth > vw + 1,
    cards: byId,
    storiesTitle: (q('mod_stories') || {}).textContent ?
      q('mod_stories').textContent.includes('Истории и эпизоды') : false,
  };
})()
"""

PROBE_WORKSPACE = r"""
((slug) => {
  const de = document.documentElement;
  const vw = window.innerWidth;
  const head = document.querySelector('[data-workspace-head]');
  const gate = document.querySelector('[data-f4-module-gate]');
  const tabs = Array.from(
    document.querySelectorAll('[data-workspace-tab]')).map(e => e.dataset
    .workspaceTab);
  const st = gate ? gate.textContent : '';
  const headToggle = head ? !!head.querySelector('input[type="checkbox"]')
    : null;
  return {
    innerWidth: vw,
    docOverflow: de.scrollWidth > vw + 1
      || document.body.scrollWidth > vw + 1,
    headModule: head ? head.dataset.module : null,
    headToggle: headToggle,
    tabs: tabs,
    hasGate: !!gate,
    gateText: st.slice(0, 400),
    effectiveOn: st.includes('Работает'),
    effectiveOff: st.includes('Не работает'),
    requestedLine: st.includes('requested:'),
    sourceLine: st.includes('source:'),
    envLine: st.includes('Аварийная env-ось'),
    restartNote: st.includes('требует рестарта'),
    noMasterNote: st.includes('мастер — env-ось'),
    links: Array.from(gate ? gate.querySelectorAll('a') : [])
      .map(a => a.getAttribute('href')),
  };
})
"""

PROBE_SETTINGS = r"""
(() => {
  const text = document.body.textContent;
  return {
    // stories (flags_stories)
    storiesGroup: text.includes('Модуль: Истории и эпизоды'),
    vitrinaToggle: text.includes('Витрина историй (мастер read-контура)'),
    manageToggle: text.includes('Действия с историями (мутации)'),
    episodesMaster: text.includes('Эпизоды: мастер'),
    backfillToggle: text.includes('Эпизоды: backfill'),
    // character (flags_character)
    characterGroup: text.includes('Модуль: Характер (SelfModel)'),
    selfModelToggle: text.includes('Модель себя (мастер)'),
    formGuardToggle: text.includes('Форм-гард постобработки'),
    // experience / random (существующие группы)
    experienceGroup: text.includes('Опыт и уроки'),
    learningToggle: text.includes('Опыт и уроки: обучение'),
    randomGroup: text.includes('Случайность'),
    sourceSelect: text.includes('Случайность: источник'),
    // ЧУЖИЕ группы (orphan controls — их быть НЕ должно)
    foreignMemory: text.includes('Память и граф знаний'),
    foreignRagLimits: text.includes('Память: лимиты RAG'),
    foreignLore: text.includes('Лор чатов'),
    foreignPermsoc: text.includes('Функции PERMsoc: рубильники'),
    foreignRelations: text.includes('Отношения'),
    foreignDream: text.includes('Сон: рубильник'),
  };
})()
"""


def _record(failures, viewport, message):
    failures.append("[%s] %s" % (viewport, message))


def _wait_probe(page, probe_js, key, tries=40, arg=None):
    probe = {}
    js = probe_js.replace("((slug)", "((slug)") if arg is None else \
        "(%s)(%s)" % (probe_js, json.dumps(arg))
    for _ in range(tries):
        probe = page.evaluate(js)
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
                          _api_handler_factory(CONFIG_STUB))
                page = ctx.new_page()
                page.on("console", lambda m, L=label: result[
                    "console_errors"].append("%s: %s" % (L, m.text[:200]))
                    if m.type == "error" else None)
                page.on("pageerror", lambda e, L=label: result[
                    "console_errors"].append("%s pageerror: %s"
                                             % (L, str(e)[:200])))
                # ── 1) Хаб «Модули»: 4 подкарточки из реестра ──────────────
                page.goto(url + "#/modules", wait_until="load")
                hub = _wait_probe(page, PROBE_HUB, "storiesTitle")
                result["probes"]["%s_hub" % label] = hub
                for card_id, present in (hub.get("cards") or {}).items():
                    if not present:
                        _record(failures, label,
                                "подкарточка %s не отрисована из реестра"
                                % card_id)
                if not hub.get("storiesTitle"):
                    _record(failures, label,
                            "подкарточка stories без заголовка")
                if hub.get("docOverflow"):
                    _record(failures, label, "hub: horizontal overflow")
                page.screenshot(path=os.path.join(
                    SHOT_DIR, "ui_asap7_f4_%s_hub.png" % label),
                    full_page=True)
                result["screenshots"].append(
                    "ui_asap7_f4_%s_hub.png" % label)

                # ── 2) Страницы подмодулей: гейт + свои группы ─────────────
                cases = (
                    ("stories", {
                        "group": "storiesGroup",
                        "toggles": ("vitrinaToggle", "manageToggle",
                                    "episodesMaster", "backfillToggle"),
                        "has_toggle": True,
                        "links": ["#/status"],
                    }),
                    ("character", {
                        "group": "characterGroup",
                        "toggles": ("selfModelToggle", "formGuardToggle"),
                        "has_toggle": True,
                        "links": [],
                    }),
                    ("experience", {
                        "group": "experienceGroup",
                        "toggles": ("learningToggle",),
                        "has_toggle": True,
                        "links": [],
                    }),
                    ("random", {
                        "group": "randomGroup",
                        "toggles": ("sourceSelect",),
                        "has_toggle": False,
                        "links": ["#/modules/sleep", "#/modules/initiative"],
                    }),
                )
                for slug, case in cases:
                    page.goto(url + "#/modules/" + slug, wait_until="load")
                    ws = _wait_probe(page, PROBE_WORKSPACE, "hasGate",
                                     arg=slug)
                    result["probes"]["%s_%s" % (label, slug)] = ws
                    if ws.get("headModule") != "mod_" + slug:
                        _record(failures, label,
                                "%s: workspace-голова не mod_%s"
                                % (slug, slug))
                    if not ws.get("hasGate"):
                        _record(failures, label,
                                "%s: data-f4-module-gate не отрисован" % slug)
                    else:
                        if not ws.get("effectiveOn"):
                            _record(failures, label,
                                    "%s: effective ON не показан" % slug)
                        if not ws.get("requestedLine"):
                            _record(failures, label,
                                    "%s: requested не показан" % slug)
                        if not ws.get("sourceLine"):
                            _record(failures, label,
                                    "%s: source не показан" % slug)
                        if not ws.get("envLine"):
                            _record(failures, label,
                                    "%s: env-ось не показана" % slug)
                        if not ws.get("restartNote"):
                            _record(failures, label,
                                    "%s: restart-пометка env нет" % slug)
                    if slug == "random":
                        if not ws.get("noMasterNote"):
                            _record(failures, label,
                                    "random: «мастер — env-ось» не показан")
                        if ws.get("headToggle"):
                            _record(failures, label,
                                    "random: мёртвый переключатель в голове")
                    elif ws.get("headToggle") is False:
                        _record(failures, label,
                                "%s: переключатель мастера отсутствует"
                                % slug)
                    for want in case["links"]:
                        if want not in (ws.get("links") or []):
                            _record(failures, label,
                                    "%s: нет ссылки-перехода %s" % (slug,
                                                                   want))
                    if ws.get("docOverflow"):
                        _record(failures, label,
                                "%s: horizontal overflow" % slug)
                    # settings-вкладка — только свои группы (desktop)
                    if label.startswith("desktop"):
                        page.click('[data-workspace-tab="settings"]')
                        page.wait_for_timeout(400)
                        sp = page.evaluate(PROBE_SETTINGS)
                        result["probes"]["%s_%s_settings"
                                         % (label, slug)] = sp
                        if not sp.get(case["group"]):
                            _record(failures, label,
                                    "%s: своя группа не отрисована" % slug)
                        for t in case["toggles"]:
                            if not sp.get(t):
                                _record(failures, label,
                                        "%s: свой контрол %s не отрисован"
                                        % (slug, t))
                        for foreign in ("foreignMemory", "foreignRagLimits",
                                        "foreignLore", "foreignPermsoc",
                                        "foreignRelations", "foreignDream"):
                            if sp.get(foreign):
                                _record(failures, label,
                                        "%s: ЧУЖАЯ группа %s на settings"
                                        % (slug, foreign))
                        page.screenshot(path=os.path.join(
                            SHOT_DIR, "ui_asap7_f4_%s_%s_settings.png"
                            % (label, slug)), full_page=True)
                        result["screenshots"].append(
                            "ui_asap7_f4_%s_%s_settings.png" % (label, slug))
                ctx.close()
            # ── 3) env-emergency OFF (stories, desktop) — честный blocked ──
            # In-flow навигация (boot '#/modules' → карточка → страница):
            # холодный deep-link '#/modules/stories' перезаписывается
            # boot-роутером ДО loadConfig (общая семантика аддитивного
            # реестра §3.1, не регрессия — задокументировано в f4-report).
            ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                      reduced_motion="reduce")
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**",
                      _api_handler_factory(STORIES_EMERGENCY))
            page = ctx.new_page()
            page.goto(url + "#/modules", wait_until="load")
            _wait_probe(page, PROBE_HUB, "storiesTitle")
            page.goto(url + "#/modules/stories", wait_until="load")
            emg = _wait_probe(page, PROBE_WORKSPACE, "hasGate",
                              arg="stories")
            result["probes"]["emergency_off_stories"] = emg
            if not emg.get("effectiveOff"):
                _record(failures, "emergency",
                        "stories: env-emergency OFF не показан («Не работает»)")
            if emg.get("effectiveOn"):
                _record(failures, "emergency",
                        "stories: env-emergency OFF показан как «Работает»")
            if not emg.get("restartNote"):
                _record(failures, "emergency",
                        "stories: restart-пометка env-оси не показана")
            page.screenshot(path=os.path.join(
                SHOT_DIR, "ui_asap7_f4_emergency_stories.png"),
                full_page=True)
            result["screenshots"].append("ui_asap7_f4_emergency_stories.png")
            ctx.close()
            browser.close()
    finally:
        try:
            httpd.shutdown()
        except Exception:
            pass
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("failures:", len(failures))
    for f in failures:
        print(" -", f)
    print("raw:", RAW)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())
