# -*- coding: utf-8 -*-
"""ASAP-SUMMARY-COVER-INTEGRITY-01 v2.1 — UI-контракт P1/P2 (desktop+mobile).

Проверяются наблюдаемые контракты, а не «внутренности»:

* §5  — РОВНО ОДИН переключатель на карточке модуля, его область = верхний
        селектор (GLOBAL/A/B), наследование, «Наследовать глобальное» как
        действие, pending по scope-ключу;
* §4.2 — пять независимых рабочих вкладок «Речи и характера», «Мат» на той же
        серверной сущности, защита несохранённых черновиков;
* §6.1/6.2 — нет app-level «…», нет dev-диагностики в prod-UI, одна кнопка ⛶,
        drawer ниже системной области (без «магических» пикселей);
* §6.3/6.4 — один блок здоровья с тремя сегментами и локальной тонировкой;
* §7  — «Избранное» отсутствует как концепция;
* §2/§3.4 — дата активации версии и серверный таймер Test Style.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")


def _block(src: str, start: str, end: str) -> str:
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


def _catalog() -> str:
    return _block(INDEX, "activeTab === 'modules'", "activeTab === 'oversight'")


def _speech_screen() -> str:
    return _block(INDEX, "activeTab === 'speech'", "activeTab === 'status'")


# ═══ §5. Один переключатель, scope = верхний селектор ═══════════════════════

class TestModulesOneScopedToggle:
    def test_exactly_one_toggle_per_card(self):
        cat = _catalog()
        assert cat.count("data-module-scope-toggle") == 1
        # Второго (global + chat) переключателя на карточке нет ни в каком виде.
        assert "data-module-global-toggle" not in cat
        assert "data-module-chat-toggle" not in cat
        # И карточка не содержит двух независимых чекбоксов вообще.
        card = _block(cat, '<article class="module-card', "</article>")
        assert card.count('type="checkbox"') == 1

    def test_scope_comes_from_top_selector(self):
        block = _block(APP_JS, "moduleScopeToggleAvailable: function",
                       "moduleScopeState: function")
        assert "this.moduleScopeIsGlobal()" in block
        assert "this.moduleHasChatScope(m)" in block
        # chat-scope возможен только у per_chat-модулей; gate='global' —
        # read-only «Управляется глобально» (без ложного ON).
        assert "(m.runtimeGate || 'global') !== 'global'" in APP_JS
        cat = _catalog()
        assert "data-module-scope-readonly" in cat
        assert "управляется глобально" in cat

    def test_single_write_path_per_scope(self):
        block = _block(APP_JS, "setModuleScopeState: async function",
                       "moduleOverrideResetAvailable: function")
        assert "this.setModuleGlobalState(m, enabled)" in block
        assert "this.setModuleState(this.storeScope(), m.id, enabled)" in block
        # global-scope по-прежнему пишет только глобальный ключ (per_chat:false).
        gblock = _block(APP_JS, "setModuleGlobalState: async function",
                        "moduleHealthView: function")
        assert "per_chat: false" in gblock
        # chat-scope использует канонический per_chat элемента конфигурации.
        cblock = _block(APP_JS, "setModuleState: async function",
                        "refreshModuleState: async function")
        assert "per_chat: item.per_chat" in cblock

    def test_inheritance_and_reset_action(self):
        block = _block(APP_JS, "moduleScopeSourceHint: function",
                       "moduleScopeToggleAria: function")
        assert "наследуется от глобального" in block
        assert "переопределено для этого чата" in block
        rb = _block(APP_JS, "resetModuleChatOverride: async function",
                    "moduleHealthView: function")
        assert "'/api/config/chat/' + encodeURIComponent(m.toggleKey)" in rb
        assert "method: 'DELETE'" in rb
        # Снимок scope/epoch берётся ДО await: поздний ответ чужой области
        # не применяется.
        assert "var epoch = this.scopeEpoch;" in rb
        assert "scope.type === 'global'" in rb
        cat = _catalog()
        assert "moduleOverrideResetAvailable(m)" in cat
        assert "Наследовать глобальное" in cat

    def test_pending_is_scoped_by_snapshot(self):
        block = _block(APP_JS, "storeKey: function", "_moduleById: function")
        assert "type + '/' + idPart + '/' + moduleId" in block
        gblock = _block(APP_JS, "moduleGlobalOpKey: function",
                        "moduleGlobalErrorFor: function")
        assert "'global/null/'" in gblock
        # Ошибка/откат показываются ТОЛЬКО для текущей области карточки.
        cat = _catalog()
        assert "moduleScopeErrorFor(m)" in cat
        assert "moduleSaveErrorFor(m)" not in cat

    def test_no_second_toggle_in_module_details(self):
        modal = _block(INDEX, "Окно параметров модуля", "activeModuleGroups")
        assert "data-module-readonly-status" in modal
        assert "data-module-managed-hint" in modal
        assert "data-module-scope-toggle" not in modal
        assert "data-module-global-toggle" not in modal


# ═══ §4.2. Пять независимых вкладок «Речи и характера» ═════════════════════

class TestSpeechFiveTabs:
    def test_area_registry_has_five_working_sections(self):
        areas = _block(APP_JS, "var SPEECH_AREAS = [", "  ];")
        ids = re.findall(r"id: '([a-z]+)'", areas)
        assert ids == ["persona", "style", "profanity", "examples", "rules"], ids
        titles = re.findall(r"title: '([^']+)'", areas)
        for expected in ("Личность", "Речь и стиль", "Мат", "Примеры",
                         "Правила и источники"):
            assert expected in titles, expected
        assert "data-speech-area-nav" in INDEX

    def test_each_tab_renders_its_own_editor(self):
        screen = _speech_screen()
        for section in ("persona", "profanity", "rules"):
            assert "speechSection === '%s'" % section in screen, section
        # Persona больше не висит под витриной: она — вкладка.
        assert '<section v-if="speechSection === \'persona\'" id="speech-persona"' in screen
        # «Личность» не содержит многокилометрового effective-списка:
        # карточка SelfModel переехала в «Правила и источники».
        persona = _block(screen, "speechSection === 'persona'",
                         "speechSection === 'rules'")
        assert "Что сейчас формирует характер" not in persona
        rules = _block(screen, "speechSection === 'rules'", "data-speech-groups")
        assert "Что сейчас формирует характер" in rules
        assert "data-speech-rules-link=\"inspector\"" in rules

    def test_profanity_shares_expression_write_path(self):
        # «Мат» — тот же серверный документ и тот же save-путь.
        assert "return id === 'profanity' ? 'expression' : id;" in APP_JS
        assert "_speechSectionLoadKey" in APP_JS
        screen = _speech_screen()
        prof = _block(screen, "speechSection === 'profanity'", "speechSection === 'humor'")
        assert "speechExpressionControls('profanity')" in prof
        assert "saveSpeechExpression()" in prof
        # Контролы выражения не дублируются: в «Речи и стиле» — все, кроме мата.
        style = _block(screen, "speechSection === 'expression'",
                       "speechSection === 'profanity'")
        assert "speechExpressionControls('style')" in style

    def test_unsaved_draft_is_protected_and_visible(self):
        assert "speechSectionTouched" in APP_JS
        block = _block(APP_JS, "speechAreaDirty: function",
                       "// P0A-UX §5.5")
        for area in ("persona", "style", "profanity", "examples"):
            assert area in block, area
        assert "data-speech-area-dirty" in INDEX
        assert ".speech-area-nav__dot" in CSS
        # Личность не теряет черновик при переключении вкладки.
        assert "this.personaDirty = true;" in APP_JS

    def test_hub_deep_links_open_specific_tab(self):
        hub = _block(INDEX, "data-ai-hub", "data-ai-prompts")
        for area in ("style", "profanity", "examples", "rules"):
            assert 'data-ai-speech-tab="%s"' % area in hub, area
        assert "openSpeechAreaFromHub" in APP_JS
        # Компактный хаб: карточки не растягиваются по самой длинной соседке.
        assert "align-items: start;" in _block(CSS, ".w10-panel__sections {", "}")
        assert "grid-auto-rows: min-content;" in _block(
            CSS, ".w10-panel__sections {", "}")


# ═══ §6.1/§6.2. Мобильная шапка, fullscreen, drawer ════════════════════════

class TestMobileShell:
    def test_no_app_level_overflow_menu(self):
        for marker in ("data-more-trigger", 'class="more-menu-root"',
                       "more-menu-profile", "data-fs-geom-diag-entry"):
            assert marker not in INDEX, marker
        assert "moreMenuOpen" not in APP_JS
        # Панель dev-диагностики существует, но только под внутренним флагом.
        assert "fsGeomDevEnabled && fsGeomDiagOpen" in INDEX

    def test_single_fullscreen_button(self):
        assert INDEX.count("header-fs-btn") == 1
        assert "data-fs-toggle" in INDEX
        assert "toggleFullscreen()" in INDEX
        # Реальное состояние: иконка/aria по isFullscreen и подтверждённому
        # fsAriaPressed, а не по «ожидаемому» API-результату.
        assert ":aria-pressed=\"fsAriaPressed\"" in INDEX

    def test_dev_geometry_is_flag_gated(self):
        assert "fsGeomDevEnabled" in APP_JS
        assert "fsGeomDevEnabled && fsGeomDiagOpen" in INDEX
        assert "if (!this.fsGeomDevEnabled) return;" in APP_JS
        assert "fs_geom_dev=1" in APP_JS

    def test_drawer_starts_below_system_ui(self):
        i = CSS.index(".app-drawer {",
                      CSS.index("Drawer (768–1199)"))
        rule = CSS[i:CSS.index("}", i)]
        assert "safe-area-inset-top" in rule
        assert "var(--tg-safe-area-inset-top" in rule
        assert "var(--tg-content-safe-area-inset-top" in rule
        assert "position: fixed; left: 0; bottom: 0;" in rule
        assert "top: 0;" not in rule
        assert "overflow-y: auto" in rule
        assert "--vv-h" in rule
        # Закрытый drawer не оставляет маску и не перехватывает клики.
        assert ".app-shell:not(.drawer-open) .app-drawer { visibility: hidden; }" in CSS

    def test_mobile_bot_actions_are_compact_with_touch_target(self):
        block = _block(CSS, ".status-health__bot-actions", ".status-health__bot-btn {")
        assert "gap: 6px" in block
        btn = _block(CSS, ".status-health__bot-btn {", "}")
        assert "min-height: var(--control-h-touch, 44px)" in btn
        assert "font-size: var(--tx-small, 12px)" in btn


# ═══ §6.4. Один блок оперативного здоровья ════════════════════════════════

class TestUnifiedHealthBlock:
    def _block_html(self) -> str:
        return _block(INDEX, 'class="card p-4 status-block status-health sg-12"',
                      "Граф связей")

    def test_single_surface_with_three_segments(self):
        block = self._block_html()
        assert block.count('class="card p-4') == 1
        for seg in ('data-status-seg="bot"', 'data-status-seg="heartbeat"',
                    'data-status-seg="server"'):
            assert seg in block, seg
        # Порядок по ТЗ: Бот | Сердцебиение | Сервер.
        assert block.index("status-block__bot") < \
            block.index("status-block__pulse") < \
            block.index("status-block__server")

    def test_compact_problem_line_with_addressed_link(self):
        block = self._block_html()
        assert "data-status-counts" in block
        assert "data-status-health-analytics" in block
        assert 'href="#/oversight?tab=overview"' in block
        assert "logErrorCount" in block and "logWarnCount" in block
        # Строка ошибок стоит ВЫШЕ сегментов и в той же поверхности.
        assert block.index("data-status-counts") < block.index("status-health__segs")

    def test_tint_only_on_faulty_segment(self):
        # Тонировка — на сегменте (health-glass-surface), а не на всём блоке.
        block = self._block_html()
        assert 'subsystem="bot"' in block
        assert 'subsystem="heartbeat"' in block
        assert "data-health-material" not in block.split(
            'class="card p-4 status-block status-health sg-12"', 1)[1][:200]
        # Между сегментами — тонкие разделители из токенов, без вторых рамок.
        seg = _block(CSS, ".status-health__seg {", "}")
        assert "padding: var(--space-3)" in seg
        assert "border-left: var(--border-hairline) solid var(--surface-border)" in CSS

    def test_health_block_css_uses_tokens(self):
        block = _block(CSS, ".status-health {", ".status-health__bot-btn {")
        assert not re.search(r"border-radius:\s*[0-9.]+\s*(?:px|rem)", block)
        assert not re.search(r"font-size:\s*[0-9.]+\s*(?:px|rem)", block)


# ═══ §7. «Избранное» отсутствует ═══════════════════════════════════════════

class TestFavoritesRemoved:
    def test_no_favorites_concept_anywhere(self):
        for src, name in ((INDEX, "index.html"), (APP_JS, "app.js"), (CSS, "app.css")):
            for marker in ("В избранном", "В избранное", "Избранные",
                           "modules_quickpicks", "toggleQuickpick",
                           "isQuickpick", "module-pin-btn"):
                assert marker not in src, "%s: %s" % (name, marker)
        # Замена другим именем запрещена.
        assert "Закреплено" not in INDEX
        assert "Быстрый доступ" not in INDEX

    def test_categories_search_filters_kept(self):
        assert "moduleSearch" in APP_JS
        for f in ("'Все'", "'Включённые'", "'Выключенные'", "'Есть проблемы'"):
            assert f in APP_JS, f
        assert "id: 'picks'" not in APP_JS


# ═══ §2/§3.4. История версий и таймер Test Style ═══════════════════════════

class TestHistoryAndCoverTimer:
    def test_history_shows_activation_date(self):
        block = _block(APP_JS, "phActivationNote: function",
                       "workspaceCoverage: function")
        assert "this.phWhen(hit.created_at)" in block
        # Устаревшая сноска «таймер активации не отдаётся» удалена.
        assert "таймер\n" not in INDEX
        assert "Отдельный таймер" not in INDEX
        assert "data-prompt-history-time-note" not in INDEX

    def test_history_active_line_uses_tokens_and_does_not_collapse(self):
        rule = _block(CSS, ".prompt-history-active {", "}")
        assert "display: flex;" in rule
        assert "flex-wrap: wrap;" in rule
        assert "gap: var(--space-1) var(--space-3);" in rule
        assert ".prompt-history-active > * + *::before" in CSS

    def test_cover_timer_uses_server_time_only(self):
        block = _block(APP_JS, "coverTestElapsedText: function",
                       "coverPreviewStageText: function")
        assert "server_elapsed_ms" in block
        assert "performance.now" in APP_JS
        # Внутри Test Style нет арифметики Date.now() − started_at.
        cover = _block(APP_JS, "coverStylePreview: function",
                       "openCoverConnections: function")
        assert "Date.now()" not in cover
        assert "Date.now() / 1000" not in cover
        # «В очереди» без started_at, честное «—» вместо миллионов секунд.
        assert "queued: 'В очереди'" in APP_JS
        assert "return '—';" in block

    def test_cover_state_machine_and_terminal_handling(self):
        block = _block(APP_JS, "coverTestState: function",
                       "coverPreviewStageText: function")
        for state in ("'queued'", "'running_base'", "'running_edit'",
                      "'succeeded'", "'failed'", "'cancelled'", "'expired'"):
            assert state in block, state
        fin = _block(APP_JS, "coverStyleFinishJob: function",
                     "coverStyleRetryStart: function")
        assert "st.previewBusy = false;" in fin
        assert "_coverTestTickStop()" in fin
        poll = _block(APP_JS, "coverStylePollJob: function",
                      "openCoverConnections: function")
        # 404 — честный финал, а не вечное «Обработка…».
        assert "e.status === 404" in poll
        assert "job_not_found" in poll
        # Поздний ответ не «оживляет» завершённую задачу.
        assert "if (jj.finished) return;" in poll
        # Кнопка/спиннер больше не показывают бесконечное «Обработка…».
        assert "Обработка…" not in INDEX
        assert "coverTestActive() ? coverTestStateLabel() + '…' : 'Проверить стиль'" in INDEX

    def test_cover_result_distinguishes_styled_vs_base_and_stale(self):
        block = _block(INDEX, "data-cover-sec-result", "data-cover-manifest")
        assert "data-cover-test-styled" in block
        assert "data-cover-test-base-note" in block
        assert "Стиль не применён (styled нет)" in block
        stale = _block(INDEX, "data-cover-preview-stale", "data-cover-sec-result")
        assert "data-cover-preview-stale-rev" in stale
        assert "Это не успешная проверка текущей версии" in stale
