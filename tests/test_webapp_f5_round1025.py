"""F5 round 10.25 — рабочее пространство модуля (ADR-1025-15).

Проверяет:
  * D1/D6: витринные метаданные workspace (`routeSlug`, `tabs`) в JS `MODULES`;
    динамический резолвер `#/modules/<slug>[/<wt>[/<stage>/<key>]]`;
  * D2: шов `openModuleWorkspace` — навигация, `openModuleWindow` сохранён;
  * §9.3: инвариант покрытия групп (все группы старой вкладки достижимы);
  * D3/§48: «один промпт — один источник», редактор не в аккордеоне;
  * D4/§49: 6 групп моделей, reuse эндпоинтов, «не менять сохранённую модель»;
  * D5/§84/§85: только UI (карточки L1/L2 + табы Саммари), backend не тронут;
  * инварианты: Δ каталога = 0, CSP/zero-build, без WebGL/новых библиотек.
"""
import dataclasses
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")


def _block(start_marker: str, end_marker: str) -> str:
    start = APP_JS.index(start_marker)
    end = APP_JS.index(end_marker, start)
    return APP_JS[start:end]


# ── D1/D6: витрина workspace ────────────────────────────────────────────────
def test_workspace_metadata_present():
    assert "var WORKSPACE_TABS = {" in APP_JS
    assert "routeSlug" in APP_JS
    assert "m.routeSlug = String(m.id).replace(/^mod_/, '')" in APP_JS
    assert "m.tabs = WORKSPACE_TABS[m.id]" in APP_JS
    # Карта вкладок §4.2 spec.md (выборочно, ключевые модули).
    for entry in (
        "mod_summary: ['overview', 'settings', 'prep', 'clusterizer', 'writer',",
        "mod_factcheck: ['overview', 'settings', 'synthesizer', 'verbalizer',",
        "mod_images: ['overview', 'settings', 'models', 'testing']",
        "mod_media_download: ['overview', 'settings', 'limits']",
    ):
        assert entry in APP_JS, entry


def test_workspace_tab_labels():
    for label in ("overview: 'Обзор'", "settings: 'Основные настройки'",
                  "synthesizer: 'Синтезатор'", "verbalizer: 'Вербализатор'",
                  "prep: 'Подготовка сообщений'", "clusterizer: 'Кластеризатор'",
                  "writer: 'Писатель'", "testing: 'Тестирование'"):
        assert label in APP_JS, label


# ── D1: динамический резолвер (без 13 статических записей) ─────────────────
def test_dynamic_workspace_resolver():
    for fn in ("function parseWorkspaceRoute(route)",
               "function isWorkspaceRoute(route)",
               "function parsePromptLibraryRoute(route)",
               "function _wsModuleById(slug)"):
        assert fn in APP_JS, fn
    # normalizeRoute распознаёт workspace-маршруты динамически.
    norm = _block("function normalizeRoute(hash)", "function routeToTab(route)")
    assert "isWorkspaceRoute(r)" in norm
    assert "parsePromptLibraryRoute(r)" in norm
    # routeToTab отдаёт m.tab (RBAC/kill-switch без правок).
    rtt = _block("function routeToTab(route)", "function tabToRoute(tabId)")
    assert "return m.tab;" in rtt, "routeToTab workspace → m.tab"
    # D3/§48: вторая дверь `#/ai/prompts/<slug>[/<stage>]` → tab prompts.
    assert "parsePromptLibraryRoute(r)" in rtt, \
        "routeToTab обрабатывает библиотеку промптов (#/ai/prompts/<slug>)"
    assert "return 'prompts';" in rtt, "библиотека промптов → activeTab prompts"
    # НЕ перечисляем 13 модулей статически.
    assert APP_JS.count("'#/modules/factcheck'") == 0, \
        "workspace-маршруты не должны быть в статической карте"


def test_router_parent_and_depth():
    rp = _block("function routeParent(route)", "function routeDepth(route)")
    assert "parseWorkspaceRoute(r)" in rp
    assert "'#/modules/' + ws.slug" in rp
    # routeDepth 0/1/2; маркер базовой глубины сохранён (back-button).
    assert "routeParent(route) ? 1 : 0" in APP_JS
    assert "return base + 1;" in APP_JS


def test_applyroute_handles_unknown_slug():
    block = _block("applyRoute: function (rawHash)", "this.route = route;")
    assert "Модуль не найден" in block
    assert "route = '#/modules';" in block
    # неприменимая вкладка → дефолт «Обзор».
    assert "'#/modules/' + wsParsed.slug" in block
    # D3/§48: библиотека промптов — неизвестный slug → чистая библиотека.
    assert "parsePromptLibraryRoute(route)" in block, \
        "applyRoute обрабатывает вторую дверь"
    assert "route = '#/ai/prompts';" in block, \
        "неизвестный slug библиотеки → #/ai/prompts (без белого экрана)"
    # T-2700: пустая вкладка «Тестирование» не рендерится (стат. применимость).
    assert "_workspaceTabApplicable(wsm, wsParsed.tab)" in block


def test_prompt_library_second_door_and_testing_tab():
    """D3/§48 вторая дверь + T-2700 «только применимые вкладки»."""
    # UI-точки входа в библиотеку промптов (раздел ИИ и модуль).
    assert 'data-prompt-library-modules' in INDEX
    assert 'data-prompt-doors' in INDEX
    assert "promptLibraryEntries: function" in APP_JS
    # openPromptLibrary реально вызывается из шаблона (не мёртвый код).
    assert "openPromptLibrary(e.module" in INDEX
    assert "openPromptLibrary(workspaceModule, workspace.stage)" in INDEX
    # §48: обе двери → один объект; library-дверь даёт tab prompts.
    ws = _block("workspace: function ()", "workspaceModule: function ()")
    assert "parsePromptLibraryRoute(route)" in ws, \
        "workspace вычисляется и для двери библиотеки"
    assert "door: door" in ws, "дверь фиксируется производной"
    # T-2700: вкладка «Тестирование» — по фактическому содержимому.
    assert "if (tabId === 'testing') return true;" not in APP_JS
    assert "workspaceTestingBlocks: function" in APP_JS
    assert 'data-workspace-testing' in INDEX
    # Инвариант покрытия §9.3 — доказательный: учитывает m.tabs и статические
    # источники TABS[m.tab].sources (не выводит old из groupedForTab).
    cov = _block("workspaceCoverage: function", "providerGrouped: function")
    assert "_workspaceTabApplicable(m, wt)" in cov, \
        "coverage учитывает объявленные вкладки модуля (m.tabs)"
    assert "t.sources" in cov, "coverage сравнивает со статическими источниками"
    assert "this.groupedForTab(t).forEach(function (g) { old[g.id] = true; });" \
        not in cov, "тавтологичное построение old устранено"


# ── M-F5S-1/L-F5S-1..3: доработка библиотечной двери ───────────────────────
def test_prompt_library_focus_empty_door_and_touch_aria():
    """M-F5S-1: промпт из библиотеки открывает редактор (не «Обзор»).

    L-F5S-1: тач-цель табов workspace ≥44px на mobile.
    L-F5S-2: без `role=listitem` на кнопках дерева промптов.
    L-F5S-3: «пустая» дверь библиотеки → чистая `#/ai/prompts`.
    """
    pl = _block("function parsePromptLibraryRoute(route)",
                "function _wsModuleById(slug)")
    assert "promptKey" in pl, "библиотечная дверь поддерживает фокус промпта"
    assert "if (stage && stage.indexOf('prompts.') === 0)" in pl, \
        "ключ промпта в слоте stage распознаётся по префиксу prompts."
    # openWorkspacePrompt учитывает дверь (из библиотеки — библиотека).
    owp = _block("openWorkspacePrompt: function (item, stage)",
                 "openPromptLibrary: function")
    assert "ws.door === 'library'" in owp, "M-F5S-1: дверь учтена"
    assert "'#/ai/prompts/' + ws.slug" in owp, \
        "M-F5S-1: библиотечный маршрут сохраняется"
    # L-F5S-3: модуль без промптов → #/ai/prompts.
    apply_blk = _block("applyRoute: function (rawHash)", "this.route = route;")
    assert "MODULE_PROMPT_GROUPS[plm.id]" in apply_blk, \
        "L-F5S-3: пустая библиотечная дверь → #/ai/prompts"
    # L-F5S-2: дерево промптов — без невалидной пары list/listitem.
    tree_start = INDEX.index("prompt-tree card")
    tree_end = INDEX.index("data-prompt-editor", tree_start)
    tree = INDEX[tree_start:tree_end]
    assert 'role="list"' not in tree, "L-F5S-2: без role=list на aside"
    assert 'role="listitem"' not in tree, "L-F5S-2: без role=listitem на button"
    assert 'role="group"' in tree and 'aria-label="Промпты"' in tree, \
        "L-F5S-2: контейнер — role=group + aria-label"
    # L-F5S-1: тач-цель табов workspace ≥44px на mobile.
    assert "[data-workspace-tabs] button { min-height: 44px; }" in CSS, \
        "L-F5S-1: тач-цель табов ≥44px"


# ── D2: шов/регресс-путь ────────────────────────────────────────────────────
def test_shim_navigates_and_preserves_regression_path():
    block = _block("openModuleWorkspace: function (m)",
                   "_workspaceNavAvailable: function")
    assert "this.navigateTo('#/modules/' + slug)" in block
    assert "return this.openModuleWindow(m);" in block, \
        "fallback на регресс-путь сохранён"
    assert "openModuleWindow: function (m)" in APP_JS, \
        "регресс-путь openModuleWindow не удалён"
    # Точка входа не меняется.
    assert "openModuleWorkspace(m)" in INDEX
    assert "openModuleWindow(m)" not in INDEX


# ── §9.3: инвариант покрытия ────────────────────────────────────────────────
def test_coverage_invariant_present():
    assert "workspaceCoverage: function" in APP_JS
    assert "workspaceGroupTab: function" in APP_JS
    assert "_workspaceGroupsFor: function" in APP_JS
    block = _block("workspaceCoverage: function", "providerGrouped: function")
    assert "missing" in block, "инвариант покрытия вычисляет missing"


# ── D3/§48: один промпт — один источник ────────────────────────────────────
def test_single_prompt_source():
    assert "var MODULE_PROMPT_GROUPS = {" in APP_JS
    assert "_workspacePromptGroup: function" in APP_JS
    # Оба маршрута — один config-item prompts.* (без второго хранилища).
    assert "adminbot.prompt" not in APP_JS
    assert "workspacePromptList: function" in APP_JS
    assert "openPromptLibrary: function" in APP_JS
    # Редактор виден сразу (data-prompt-textarea вне <details>).
    assert 'data-prompt-textarea' in INDEX
    assert 'data-workspace-prompts' in INDEX
    # Аккордеон — не основная навигация новых раскладок.
    assert "promptsShowAccordion: function" in APP_JS


# ── D4/§49: 6 групп ────────────────────────────────────────────────────────
def test_provider_six_groups():
    assert "var PROVIDER_GROUPS = [" in APP_JS
    for gid in ("id: 'prov_text'", "id: 'prov_stt'", "id: 'prov_video'",
                "id: 'prov_embeddings'", "id: 'prov_background'",
                "id: 'prov_images'"):
        assert gid in APP_JS, gid
    assert "providerGrouped: function" in APP_JS
    assert "workspaceModelGroups: function" in APP_JS
    assert 'data-provider-group' in INDEX
    # «Проверить» на существующих эндпоинтах.
    assert "'/api/llm/test'" in APP_JS
    assert "'/api/images/test'" in APP_JS
    # §49: форма только читает (blockFieldValue), 0 POST при открытии.
    body = _block("blockFieldValue: function", "blockFieldBool: function")
    assert "this.configItems.find" in body


def test_connection_card_fields_and_disclosure():
    """§49/T-2714: карточка подключения — все поля + «Проверить»/«Настроить».

    Значения — из существующей структуры (`PROVIDER_BLOCKS`/`models_*`);
    ключи как значения не выводятся (F9/§46); «Настроить» раскрывает
    существующую форму без записи (§49 «не менять модель»).
    """
    # JS-производная карточки + действия.
    assert "function buildConnectionCard(ctx, b)" in APP_JS
    assert "connectionCard: function" in APP_JS
    assert "workspaceModelCards: function" in APP_JS
    assert "toggleConnectionSettings: function" in APP_JS
    assert "testConnection: async function" in APP_JS
    assert "connectionSettingsOpen: {}" in APP_JS
    card = _block("function buildConnectionCard(ctx, b)",
                  "// Маршрут валиден")
    assert card, "блок карточки найден"
    # Секреты не читаются карточкой (читается только role === 'model').
    assert "role === 'api_key'" not in card, "карточка не читает секреты (F9/§46)"
    assert "fields[i].role === 'model'" in card

    # Шаблон: все поля карточки + действия + раскрытие формы.
    for marker in ('data-connection-card', 'data-conn-field="title"',
                   'data-conn-field="purpose"',
                   'data-conn-field="primary-model"',
                   'data-conn-field="fallback-model"',
                   'data-conn-field="status"', 'data-conn-test',
                   'data-conn-configure', 'data-connection-settings'):
        assert marker in INDEX, marker
    assert "workspaceModelCards" in INDEX
    assert "toggleConnectionSettings(c.block)" in INDEX
    assert "testConnection(c.block)" in INDEX
    # Тач-цели карточки ≥44px на сенсорных ширинах.
    assert "[data-conn-test]" in CSS
    assert "[data-conn-configure]" in CSS
    assert "min-height: 44px" in CSS


def test_no_new_endpoints_reused_only():
    """F5 не добавляет НОВЫХ эндпоинтов (R16)."""
    assert "'/api/llm/test'" in APP_JS
    assert "'/api/images/test'" in APP_JS
    # Новых серверных маршрутов нет.
    for forbidden in ("/api/module", "/api/workspace", "/api/prompts/"):
        assert forbidden not in APP_JS, forbidden


def test_api_keys_not_copied_into_module():
    """§46/§117(2): API-ключи НЕ копируются в конфигурацию модуля.

    Секреты остаются единственным источником в категории `keys.*` (раздел
    секретов, F9); витрина workspace/карты §49 не заводит модульных копий.
    """
    ws = _block("var WORKSPACE_TABS = {", "var MODULE_PROMPT_GROUPS")
    model_blocks = _block("var MODULE_MODEL_BLOCKS = {", "// A4/T-1207")
    for seg in ("api_key", "secret", "keys."):
        assert seg not in ws, f"workspace-карта не хранит секреты ({seg})"
        assert seg not in model_blocks, f"карта моделей не хранит секреты ({seg})"
    # Секреты читаются/пишутся только по каноническим `keys.*` (F9).
    assert "keys.llm_api_key" in APP_JS
    assert re.search(r"mod_\w+\.\w*api_key", APP_JS) is None, \
        "нет модульных копий API-ключей"


# ── D5/§84/§85: только UI ──────────────────────────────────────────────────
def test_summary_and_direct_ui_only():
    # §85: табы Саммари — честный placeholder.
    assert 'data-workspace-stage' in INDEX
    assert "Раздел появится после обновления пайплайна" in INDEX
    # §84: L1/L2 карточки.
    assert "directStageCards: function" in APP_JS
    assert 'data-direct-stages' in INDEX
    assert "'L1 · Синтезатор'" in APP_JS
    assert "'L2 · Вербализатор'" in APP_JS
    # Мобильная раскладка L1/L2 вертикально + 44px тач-цели.
    assert ".workspace-prompt-lib" in CSS
    assert "min-height: 44px" in CSS


# ── §47: ИИ — ровно 5 страниц, порядок ТЗ ──────────────────────────────────
def test_ai_hub_five_pages_order():
    block = _block("var HUBS_V2 = {", "'#/memory': {")
    titles = re.findall(r"\btitle: '([^']+)'", block)
    assert titles[1:] == ["Библиотека промптов", "Модели и подключения",
                          "Личность и стиль", "Имена и алиасы",
                          "Умный кэш"], titles
    routes = re.findall(r"route: '([^']+)'", block)
    assert routes == ["#/ai/prompts", "#/ai/llm", "#/ai/persona",
                      "#/ai/names", "#/ai/smart-cache"], routes


# ── Инварианты окружения ────────────────────────────────────────────────────
def test_catalog_delta_zero():
    import services.param_catalog as pc
    from config.settings import Settings
    assert len(pc.REGISTRY) == 459
    assert len(pc.GROUPS) == 98
    assert len(pc._TAB_BY_GROUP) == 96
    assert len(pc.TAB_RULES) == 21
    assert len({f.name for f in dataclasses.fields(Settings)}) == 418


def test_no_webgl_and_no_new_libraries():
    lowered = APP_JS.lower()
    for lib in ("pinia", "zustand", "redux", "mobx"):
        assert lib not in lowered, lib
    # WebGL запрещён: нет создания WebGL-контекста (комментарии не считаем).
    assert "getcontext('webgl" not in lowered, "WebGL запрещён"
    assert 'getcontext("webgl' not in lowered, "WebGL запрещён"
    assert "require(" not in APP_JS
    assert re.search(r"^\s*import\s", APP_JS, flags=re.M) is None
    assert re.search(r'<script[^>]+src="https?://', INDEX) is None


def test_no_backend_files_in_scope():
    """F5 меняет только web/** (дифф-гард §84/§85)."""
    # Маркеры UI присутствуют; backend-модули не упоминаются как изменённые.
    assert "services/param_catalog.py" not in INDEX
    # Реэмплой эндпоинтов (без создания новых) — уже проверено выше.
    assert "direct_chat_service" not in APP_JS
