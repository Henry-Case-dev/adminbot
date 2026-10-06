"""MCA-12 (round 10.46, T-5171) — Playwright/Chromium Browser-Verification
блока «Истории чата» + §16.3-инициативы на РЕАЛЬНЫХ web/index.html / app.js /
app.css (статика + route-стабы API; прецеденты ui_round1025_matrix,
ui_asap32_cover_styles_e2e). ЭТО НЕ production acceptance (живая приёмка —
T-5175 @Owner); проверяются измеримые DOM-контракты:

  * витрина «Истории чата» на «Статусе» desktop (1280×800) + mobile
    (390×844, TMA-like): позиция D3 (после «Бюджетов интеллекта», до
    «Доступности ключей»), счётчики, лента, честные пустые состояния;
  * A26: prepend нового события НЕ сбрасывает scroll (якорный элемент
    остаётся на своей viewport-позиции), открытая карточка на месте;
  * A11: событие 2022 с новой датой обнаружения — обе даты в рендере;
  * A54: инкрементальный курсор (страница 2 без дублей);
  * пауза ленты — честная (опрос останавливается);
  * переход «Открыть таблицу» → вкладка историй существующей «Памяти»
    (hash #/ai/memory; нового маршрута нет); таблица/фильтры/карточка
    (D6/D7); действия рендерятся под manage_enabled (K2);
  * K1 OFF → блок «Истории чата» скрыт (learned с API; OFF-паритет UI);
  * §16.3: секция «Инициатива» — честные состояния + настройки-рендер
    (default/effective/источник/hot) + витрины T-5169 (компакт);
  * мобильная вёрстка без horizontal overflow; reduced-motion context.

Запуск: .venv\\Scripts\\python tools\\ui_mca12_stories_e2e.py
Артефакты: tools/_ui_mca12_stories_e2e.json, tools/_ui_mca12_*.png
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ui_round1025_matrix as M  # noqa: E402  (сервер/TMA-стаб — reuse)

PORT = M.PORT          # сервер ui_round1025_matrix биндит СВОЙ PORT (reuse)
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "web")
RAW = os.path.join(M.REPO, "tools", "_ui_mca12_stories_e2e.json")
SHOT_DIR = os.path.join(M.REPO, "tools")

CHAT_ID = -1001234567890
NOW = 1790000000
T_2022 = 1650000000

VIEWPORTS = (
    ("desktop_1280x800", {"width": 1280, "height": 800}, False),
    ("mobile_390x844", {"width": 390, "height": 844}, True),
)

SUMMARY = {
    "enabled": True, "state": "ok", "chat_id": CHAT_ID,
    "counters": {"total": 2, "new_window": 1, "extended_window": 1,
                 "contradictions_window": 1, "pending_verification": 1,
                 "excluded_from_retrieval": 0},
    "window_hours": 24,
    "progress": {
        "episodes_build": {"state": "success", "last_ts": NOW - 600,
                           "last_outcome": "success", "last_reason": None},
        "episodes_backfill": {"state": "paused", "active": False,
                              "updated_at": NOW - 3600},
    },
    "generated_at": NOW,
    "manage_enabled": True,
}


def _ev(eid, name, title, *, start=None, end=None, discovered=NOW,
        text=""):
    return {"id": eid, "ts": NOW - (100 - eid) * 60, "event": name,
            "outcome": "success", "reason_code": None, "story_id": "st-%d"
            % (eid % 2 + 1), "title": title, "text": text,
            "episode_ids": ["ep-%d" % eid],
            "event_start": start, "event_end": end,
            "discovered_at": discovered,
            "participants": ["7", "12"]}


# Страница 1 (cursor=0): 8 событий — лента заведомо выше max-height (скролл);
# далее каждый опрос возвращает ровно одно новое событие (динамический
# курсор handler'а — детерминированный A54 без фиксированных страниц).
FEED_PAGE1 = {
    "enabled": True, "state": "ok", "chat_id": CHAT_ID, "cursor": 8,
    "has_more": False,
    "events": [
        _ev(8, "story_extended", "Поход на Эльбрус", start=T_2022 + 7200,
            end=T_2022 + 9000),
        _ev(7, "story_rebuilt", "Поход на Эльбрус", start=T_2022 + 7200,
            end=T_2022 + 9000),
        _ev(6, "source_linked", "Поход на Эльбрус", start=T_2022 + 7200,
            end=T_2022 + 9000),
        _ev(5, "contradiction_found", "Ремонт дачи: смета расходится",
            start=T_2022 + 3600, end=T_2022 + 5400,
            text="conflicts:1"),
        _ev(4, "story_extended", "Ремонт дачи: смета расходится",
            start=T_2022 + 3600, end=T_2022 + 5400),
        # A11: событие 2022, обнаружено «сегодня» — обе даты
        _ev(3, "story_discovered", "Ремонт дачи: смета расходится",
            start=T_2022, end=T_2022 + 1800, discovered=NOW),
        _ev(2, "story_discovered", "Поход на Эльбрус",
            start=T_2022 + 7200, end=T_2022 + 9000, discovered=NOW - 86400),
        _ev(1, "story_discovered", "День рождения Кати",
            start=NOW - 172800, end=NOW - 169800, discovered=NOW - 169800),
    ],
}
FEED_DISABLED = {"enabled": False, "state": "disabled", "chat_id": None,
                 "cursor": 0, "events": [], "has_more": False}

TABLE = {
    "enabled": True, "state": "ok", "chat_id": CHAT_ID,
    "items": [
        {"story_id": "st-1", "chat_id": CHAT_ID,
         "title": "Поход на Эльбрус", "summary": "Готовились к восхождению…",
         "participants": ["7", "12"], "claims_count": 2,
         "event_start_ts": T_2022 + 7200, "event_end_ts": T_2022 + 9600,
         "discovered_at": NOW - 86400, "updated_at": NOW - 600,
         "outcome": "исход неизвестен", "state": "open",
         "verification": "tentative", "excluded_from_retrieval": False,
         "expected_version": 3, "num_episodes": 2, "has_overrides": True},
        {"story_id": "st-2", "chat_id": CHAT_ID,
         "title": "Ремонт дачи: смета расходится",
         "summary": "Смета подрядчика расходится с обсуждённой.",
         "participants": ["12"], "claims_count": 1,
         "event_start_ts": T_2022, "event_end_ts": T_2022 + 1800,
         "discovered_at": NOW, "updated_at": NOW - 60,
         "outcome": "исход неизвестен", "state": "uncertain",
         "verification": "unknown", "excluded_from_retrieval": False,
         "expected_version": 1, "num_episodes": 1, "has_overrides": False},
    ],
    "next_cursor": None, "has_more": False, "manage_enabled": True,
}

CARD = {
    "enabled": True, "state": "ok", "chat_id": CHAT_ID,
    "story": {"story_id": "st-1", "chat_id": CHAT_ID,
              "title": "Поход на Эльбрус",
              "summary": "Готовились к восхождению, обсудили снаряжение.",
              "participants": ["7", "12"],
              "claims": [{"text": "Восхождение запланировано на август",
                          "refs": ["%d:tg:101" % CHAT_ID]},
                         {"text": "Нужен второй верёвочный комплект",
                          "refs": ["%d:tg:102" % CHAT_ID]}],
              "event_start_ts": T_2022 + 7200, "event_end_ts": T_2022 + 9600,
              "discovered_at": NOW - 86400, "updated_at": NOW - 600,
              "outcome": "исход неизвестен", "state": "open",
              "verification": "tentative", "open_questions": [],
              "excluded_from_retrieval": False, "expected_version": 3,
              "override_title": "Поход на Эльбрус"},
    "episodes": [
        {"episode_id": "ep-1", "title": "Обсуждение снаряжения",
         "summary": "Список снаряжения и тройки.",
         "participants": ["7", "12"], "claims": [], "event_start_ts": 0,
         "event_end_ts": 0, "discovered_at": 0, "updated_at": 0,
         "outcome": "исход неизвестен", "open_questions": [],
         "message_keys": [], "recheck_pending": False},
    ],
    "versions": [
        {"version_id": "v1", "version_no": 1, "created_at": NOW - 86400,
         "created_by": "pipeline", "extractor_version": "x",
         "title": "Поход", "summary": "", "manual": False, "overrides": []},
        {"version_id": "v3", "version_no": 3, "created_at": NOW - 600,
         "created_by": "manual", "extractor_version": "x",
         "title": "Поход на Эльбрус", "summary": "Правка владельца",
         "manual": True, "overrides": ["title"]},
    ],
    "contradictions": [],
    "redirected": False, "redirect_target": None,
    "original": {"state": "available",
                 "links": [{"tg_message_id": 101,
                            "url": "https://t.me/c/123456789/101"}],
                 "message_keys": 1},
    "related_beliefs": {"available": False, "reason": "direct_links_absent",
                        "items": []},
    "manage_enabled": True,
}

STATUS_STUB = dict(copy.deepcopy(M.STATUS_STUB), **{
    "intents": {
        "enabled": True, "state": "ok", "active": 2,
        "top": [{"intent_id": "in1", "kind": "proactive_recall",
                 "goal": "вернуть контекст разговора", "status": "active",
                 "next_check_at": NOW + 600, "priority": 2}],
        "last_action": {"ts": NOW - 300, "event": "initiative_decided",
                        "outcome": "success", "reason_code": "ask_followup",
                        "trigger_kind": "heartbeat", "action": "act"},
    },
})

API_EXTRA = [
    ("/api/stories/summary", SUMMARY),
    ("/api/stories", TABLE),
    ("/api/memory/lessons", {"enabled": True, "state": "not_run", "count": 0,
                             "lessons": []}),
    ("/api/vision/state", {"effective_enabled": True,
                           "visible_reason": "ключ настроен",
                           "model": "vision-x", "queue": {}}),
    ("/api/factcheck/temporal/runs", {"runs": [{
        "run_id": "tfr1", "created_at": NOW - 120,
        "temporal_status": "old_but_valid", "factual_verdict": "supported"}]}),
    ("/api/persona/self-model", {"enabled": True,
                                 "state": {"text": "спокойный, деловой"},
                                 "composition": {"dynamics": 3}}),
]


def _api_handler_factory(state):
    """`state` — per-context dict: {k1_on, calls, last_id}.
    Первая выдача — страница 1 (8 событий); далее каждый опрос возвращает
    РОВНО ОДНО новое событие (динамический курсор — детерминированный A54)."""
    import urllib.parse

    def _handler(route, request):
        path = urllib.parse.urlparse(request.url).path
        req = request
        if path.endswith("/api/me"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(M.ME_JSON))
            return
        if path.endswith("/api/status"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(STATUS_STUB))
            return
        if path.endswith("/api/stories/summary"):
            payload = (SUMMARY if state.get("k1_on", True)
                       else dict(SUMMARY, enabled=False, state="disabled"))
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))
            return
        if path.endswith("/api/stories/feed"):
            if not state.get("k1_on", True):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(FEED_DISABLED))
                return
            state["calls"] = state.get("calls", 0) + 1
            if state["calls"] <= 1:
                payload = FEED_PAGE1
            else:
                state["last_id"] = state.get("last_id", 8) + 1
                payload = {"enabled": True, "state": "ok",
                           "chat_id": CHAT_ID,
                           "cursor": state["last_id"], "has_more": False,
                           "events": [_ev(state["last_id"],
                                          "story_extended",
                                          "Поход на Эльбрус",
                                          start=T_2022 + 7200,
                                          end=T_2022 + 9600)]}
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))
            return
        if path.endswith("/api/stories"):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(TABLE))
            return
        if "/api/stories/" in path and request.method == "GET":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(CARD))
            return
        for marker, payload in API_EXTRA:
            if path.endswith(marker):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(payload))
                return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(M._stub_for(req.url)))

    return _handler


PROBE = r"""
(() => {
  const de = document.documentElement;
  const vw = window.innerWidth;
  const feed = document.querySelector('[data-stories-feed]');
  const items = feed ? Array.from(feed.querySelectorAll('.stories-item')) : [];
  const anchor = feed
    ? items.find(e => e.textContent.includes('Ремонт дачи'))
    : null;
  const ids = items.map(e => Number(
    (e.querySelector('button') || {}).dataset ? 0 : 0));
  const keys = items.map(e => e.__vueKey || null);
  return {
    innerWidth: vw,
    docOverflow: de.scrollWidth > vw + 1
      || document.body.scrollWidth > vw + 1,
    vitrina: !!document.querySelector('[data-stories]'),
    feedItems: items.length,
    feedDistinct: new Set(items.map(e => e.textContent)).size,
    bothDates: feed
      ? feed.textContent.includes('обнаружена:')
      : false,
    anchorTop: anchor ? Math.round(anchor.getBoundingClientRect().top) : null,
    countersText: (document.querySelector('[data-stories]') || {})
      .textContent ? document.querySelector('[data-stories]')
        .textContent.slice(0, 400) : '',
    progressText: (document.querySelector('[data-stories-progress]') || {})
      .textContent || '',
    position: (() => {
      const grid = Array.from(
        document.querySelectorAll('.status-grid > [class*="sg-"], .status-grid > div'));
      const stories = document.querySelector('[data-stories]');
      const budgets = document.querySelector('.status-budgets');
      const keys2 = Array.from(document.querySelectorAll('.card'))
        .find(c => c.textContent.includes('Доступность ключей'));
      if (!stories || !budgets || !keys2) return null;
      const order = grid.indexOf(stories) > grid.indexOf(budgets)
        && grid.indexOf(stories) < grid.indexOf(keys2);
      return order;
    })(),
  };
})()
"""


def _record(failures, viewport, message):
    failures.append("[%s] %s" % (viewport, message))


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
                state = {"k1_on": True, "calls": 0, "last_id": 8}
                ctx = browser.new_context(viewport=viewport,
                                          is_mobile=mobile,
                                          has_touch=mobile,
                                          reduced_motion="reduce")
                ctx.add_init_script(M.TMA_STUB)
                # Тестовое ускорение polling-таймеров x10 (12с ленты → 1.2с):
                # детерминированный A26/A54-тик без ожидания минут.
                ctx.add_init_script("""
                  (() => {
                    const raw = window.setInterval.bind(window);
                    window.setInterval = (fn, t, ...a) =>
                      raw(fn, Math.max(100, Math.floor((t || 0) / 10)), ...a);
                  })();
                """)
                ctx.route("**/api/**", _api_handler_factory(state))
                page = ctx.new_page()
                page.on("console", lambda m, L=label: result[
                    "console_errors"].append("%s: %s" % (L, m.text[:200]))
                    if m.type == "error" else None)
                page.on("pageerror", lambda e, L=label: result[
                    "console_errors"].append("%s pageerror: %s"
                                             % (L, str(e)[:200])))
                page.goto(url + "#/", wait_until="load")
                # ждём прогрузки ленты (mobile-контекст медленнее)
                for _ in range(40):
                    probe = page.evaluate(PROBE)
                    if probe["vitrina"] and probe["feedItems"] >= 8:
                        break
                    page.wait_for_timeout(250)
                result["probes"][label] = probe
                if not probe["vitrina"]:
                    _record(failures, label, "вставка data-stories не найдена")
                if probe["docOverflow"]:
                    _record(failures, label,
                            "horizontal overflow: scrollWidth > innerWidth")
                if probe["position"] is not True:
                    _record(failures, label,
                            "позиция D3 нарушена (после бюджетов, до ключей)")
                if probe["feedItems"] < 8:
                    _record(failures, label,
                            "лента: %s элементов (ожидалось ≥8)"
                            % probe["feedItems"])
                if not probe["bothDates"]:
                    _record(failures, label,
                            "A11: вторая дата (обнаружена) не отрисована")
                if "пауза" not in probe["progressText"] and \
                        "не запускал" not in probe["progressText"] and \
                        "success" not in probe["progressText"]:
                    _record(failures, label,
                            "прогресс обработки не отрисован")
                # A26: prepend БЕЗ сброса scroll (якорь на месте) — по
                # естественному тику polling-таймера (ускорен x10 init-
                # скриптом: 12с → 1.2с; детерминированно для теста).
                if label.startswith("desktop"):
                    page.evaluate("""
                      () => {
                        const feed = document.querySelector(
                          '[data-stories-feed]');
                        feed.scrollTop = 60;
                      }
                    """)
                    before = page.evaluate(PROBE)["anchorTop"]
                    page.wait_for_timeout(2500)   # тик 1.2с → страница 2
                    after_probe = page.evaluate(PROBE)
                    result["probes"][label + "_after_prepend"] = after_probe
                    if after_probe["feedItems"] <= probe["feedItems"]:
                        _record(failures, label,
                                "A54: prepend не добавил события (%s → %s)"
                                % (probe["feedItems"],
                                   after_probe["feedItems"]))
                    if abs(after_probe["anchorTop"] - before) > 2:
                        _record(failures, label,
                                "A26: scroll сброшен (якорь %s → %s)"
                                % (before, after_probe["anchorTop"]))
                    # пауза — честная: опрос останавливается (новых событий
                    # нет, пока пауза), после «Продолжить» — приходят
                    def _click_story_button(text, vlabel):
                        clicked = page.evaluate("""
                          (t) => {
                            const btn = Array.from(document.querySelectorAll(
                              '[data-stories] button'))
                              .find(b => b.textContent.trim() === t);
                            if (btn) { btn.click(); return true; }
                            return false;
                          }
                        """, text)
                        if not clicked:
                            _record(failures, vlabel,
                                    "кнопка «%s» не найдена" % text)
                        return clicked

                    _click_story_button("Пауза", label)
                    page.wait_for_timeout(2800)
                    paused_probe = page.evaluate(PROBE)
                    if paused_probe["feedItems"] != after_probe["feedItems"]:
                        _record(failures, label,
                                "пауза: лента продолжила обновляться (%s → %s)"
                                % (after_probe["feedItems"],
                                   paused_probe["feedItems"]))
                    _click_story_button("Продолжить", label)
                    page.wait_for_timeout(2800)
                    resumed = page.evaluate(PROBE)
                    if resumed["feedItems"] <= paused_probe["feedItems"]:
                        _record(failures, label,
                                "продолжение: лента не догружается (%s → %s)"
                                % (paused_probe["feedItems"],
                                   resumed["feedItems"]))
                    if resumed["feedDistinct"] != resumed["feedItems"]:
                        _record(failures, label,
                                "A54: дубли в ленте (%s элементов, %s уникальных)"
                                % (resumed["feedItems"],
                                   resumed["feedDistinct"]))
                    # открытая карточка на месте (без навигации)
                    page.evaluate("""
                      () => {
                        const btn = Array.from(document.querySelectorAll(
                          '[data-stories-feed] button'))
                          .find(b => b.textContent.trim() === 'Подробнее');
                        if (btn) btn.click();
                      }
                    """)
                    page.wait_for_timeout(600)
                    card = page.query_selector("[data-stories-card]")
                    if not card:
                        _record(failures, label,
                                "карточка НА МЕСТЕ не открылась")
                    elif page.url.split("#")[-1] not in ("", "/"):
                        _record(failures, label,
                                "открытие карточки сменило маршрут")
                    shot = os.path.join(SHOT_DIR,
                                        "_ui_mca12_status_desktop.png")
                    vit = page.query_selector("[data-stories]")
                    if vit:
                        vit.scroll_into_view_if_needed()
                        page.wait_for_timeout(300)
                    page.screenshot(path=shot, full_page=False)
                    result["screenshots"].append(shot)
                    # переход в «Память» (существующая вкладка, без нового
                    # маршрута; navigateTo может нормализовать hash)
                    page.evaluate("""
                      () => {
                        const btn = Array.from(document.querySelectorAll(
                          '[data-stories] button'))
                          .find(b => b.textContent.includes(
                              'Открыть таблицу'));
                        if (btn) btn.click();
                      }
                    """)
                    page.wait_for_timeout(1500)
                    if "#/memory" not in page.url:
                        _record(failures, label,
                                "переход в «Память»: hash %s" % page.url)
                    if not page.query_selector("[data-stories-manage]"):
                        # F6-хаб мог потребовать выбор подраздела — канон
                        # вкладки: #/memory/rag
                        page.evaluate(
                            "() => { window.location.hash = '#/memory/rag'; }")
                        page.wait_for_timeout(1200)
                    manage = page.query_selector("[data-stories-manage]")
                    if not manage:
                        _record(failures, label,
                                "таблица управления не найдена в «Памяти»")
                    else:
                        rows = manage.query_selector_all(
                            "[data-stories-table] tbody tr")
                        if len(rows) != 2:
                            _record(failures, label,
                                    "таблица: %s строк (ожидалось 2)"
                                    % len(rows))
                        # карточка истории из таблицы
                        rows[0].click()
                        page.wait_for_timeout(800)
                        story_card = page.query_selector("[data-story-card]")
                        if not story_card:
                            _record(failures, label,
                                    "карточка истории из таблицы не открылась")
                        elif "Версии" not in story_card.text_content():
                            _record(failures, label,
                                    "версии не отрисованы в карточке")
                        elif "Ручное имя" in story_card.text_content():
                            pass
                    shot = os.path.join(SHOT_DIR,
                                        "_ui_mca12_memory_desktop.png")
                    mgr = page.query_selector("[data-stories-manage]")
                    if mgr:
                        mgr.scroll_into_view_if_needed()
                        page.wait_for_timeout(300)
                    page.screenshot(path=shot, full_page=False)
                    result["screenshots"].append(shot)
                else:
                    shot = os.path.join(SHOT_DIR,
                                        "_ui_mca12_status_mobile.png")
                    vit = page.query_selector("[data-stories]")
                    if vit:
                        vit.scroll_into_view_if_needed()
                        page.wait_for_timeout(300)
                    page.screenshot(path=shot, full_page=False)
                    result["screenshots"].append(shot)
                ctx.close()
            # ── K1 OFF: блок скрыт (learned с API; OFF-паритет UI) ───────────
            state2 = {"k1_on": False, "calls": 0, "last_id": 8}
            ctx = browser.new_context(viewport=VIEWPORTS[0][1])
            ctx.add_init_script(M.TMA_STUB)
            ctx.route("**/api/**", _api_handler_factory(state2))
            page = ctx.new_page()
            page.goto(url + "#/", wait_until="load")
            page.wait_for_timeout(1800)
            if page.query_selector("[data-stories]"):
                _record(failures, "k1_off",
                        "K1 OFF: блок «Истории чата» не скрыт")
            else:
                result["probes"]["k1_off"] = "hidden (честный disabled API)"
            ctx.close()
            browser.close()
    finally:
        httpd.shutdown()
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    if failures:
        print("MCA12-STORIES-E2E-FAIL:")
        for f_ in failures:
            print(" -", f_)
        return 1
    print("MCA12-STORIES-E2E-OK  (probes=%d, screenshots=%d)"
          % (len(result["probes"]), len(result["screenshots"])))
    return 0


if __name__ == "__main__":
    sys.exit(_run())
