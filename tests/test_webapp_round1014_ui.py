"""F3 `persona-ui-tab-round1014` — UI подраздела «Личность» (#/ai/persona).

Покрытие (spec §2/§6/§7):
  * карточка «Личность» в Hub «ИИ» и special-маршрут #/ai/persona;
  * форма ТОЛЬКО статических параметров (3 поля + чекбокс), без визуализаций;
  * scope-индикатор + «унаследовано/переопределено» + сброс override;
  * scope-реактивность (setActiveChat/setTab/scopeEpoch);
  * инвариант special-tab: каталог-Δ = 0, «persona» НЕ config-вкладка TABS.
"""
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
# F4 10.16: CSS-канон вынесен в app.css — static-маркеры читают разметку+стили.
HTML = ((ROOT / "web" / "index.html").read_text(encoding="utf-8")
        + (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8"))


def _block(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


class TestCatalogInvariant:
    def test_counts_unchanged(self):
        import dataclasses

        from config.settings import Settings
        from services import param_catalog as pc
        # F3 НЕ вводит новых ключей (персона — PG-API): Δ каталога F3 = 0.
        # 10.14 (F8 self-reflection-llm-provider): +4/+4/+4 → 434/406/410;
        # 10.14 (F6 help-guide-integration): +1 PG-only → 435/406/411.
        # 10.18 (F1): +1 env-only BETTERSTACK_HOST (ADR-1018-1 D3)
        # → 436/406/411.
        # 10.19 (F3/ADR-1019-3 D3, UPD3 п.5): → 437/92/90/20/407/412.
        # 10.23 (F5/ADR-1023-5 D5): +5/+3/+3 → 446/95/93/20/416/421.
        # 10.24 (F21/ADR-1024-22 D8): +1/+1/+1 → 459/98/96/20/418/434.
        assert len(pc.REGISTRY) == 529
        assert len(pc.GROUPS) == 113
        assert len(pc._TAB_BY_GROUP) == 111
        assert len(pc.TAB_RULES) == 22
        assert len({f.name for f in dataclasses.fields(Settings)}) == 454
        categorized = [s for s in pc.REGISTRY.values()
                       if s.category is not None]
        assert len(categorized) == 504

    def test_persona_not_config_tab(self):
        # «Личность» — special-screen, НЕ запись TABS (иначе ломается
        # зеркало «TABS — TAB_RULES»). В TAB_SECTION_ORDER persona нет.
        assert "id: 'persona'" not in JS
        assert "'persona'," not in _block(JS, "var TAB_SECTION_ORDER = [",
                                          "];")
        assert "var TABS = [" in JS


class TestRoutes:
    def test_route_map(self):
        assert "'#/ai/persona': 'persona'," in JS
        assert "persona: '#/ai/persona'," in JS
        assert "'#/ai/persona': '#/ai'," in JS

    def test_hub_card(self):
        hub = _block(JS, "var HUBS = {", "#/access': {")
        assert "title: 'Личность'" in hub
        assert "route: '#/ai/persona', tab: 'persona'" in hub
        assert "icon: 'psychology'" in hub


class TestPersonaForm:
    def test_methods_present(self):
        for marker in ("loadPersona: async function",
                       "savePersona: async function",
                       "resetPersona: async function",
                       "personaSetField: function",
                       "personaDisabled: function"):
            assert marker in JS, marker

    def test_template_controls_only_static(self):
        block = _block(HTML, "activeTab === 'persona'",
                       "activeTab === 'info'")
        # ровно 2 textarea (Биография/Характер) + 1 input (Имя) + чекбокс.
        assert block.count("<textarea") == 2
        assert block.count("<input") == 2      # Имя (text) + checkbox
        assert 'type="text"' in block
        assert 'type="checkbox"' in block
        assert "Осознаёт себя ИИ" in block
        assert "personaDraft.name" in block
        assert "personaDraft.biography" in block
        assert "personaDraft.system_prompt_overrides" in block
        assert "personaDraft.is_aware_ai" in block
        assert "personaSetField('name'" in block
        assert "personaSetField('biography'" in block
        assert "personaSetField('system_prompt_overrides'" in block
        assert "personaSetField('is_aware_ai'" in block
        # кнопки сохранения/сброса
        assert "savePersona()" in block
        assert "resetPersona()" in block
        assert "Сбросить к глобальному" in block
        # scope-индикатор + наследование/переопределение
        assert "personaScopeBadge" in block
        assert "унаследовано от глобального" in block
        assert "переопределено для чата" in block
        # бейдж выключенного флага + disabled-контролы
        assert "Фича выключена" in block
        assert "personaDisabled" in block

    def test_no_visualization(self):
        block = _block(HTML, "activeTab === 'persona'",
                       "activeTab === 'info'")
        for forbidden in ("dynamic_traits", "traits", "ribbon", "canvas",
                          "chart", "v-html"):
            assert forbidden not in block, forbidden

    def test_fail_closed_no_html(self):
        # R17-дух: форма — только value-биндинги, без сырого HTML.
        assert "v-html" not in _block(
            HTML, "activeTab === 'persona'", "activeTab === 'info'")


class TestScopeReactivity:
    def test_load_persona_uses_scope_guard(self):
        block = _block(JS, "loadPersona: async function",
                       "savePersona: async function")
        assert "this._scopeGuard(epoch)" in block
        assert "this.api('/api/persona')" in block

    def test_save_and_reset_use_dedicated_api(self):
        save = _block(JS, "savePersona: async function",
                      "resetPersona: async function")
        assert "this.api('/api/persona'" in save
        assert "method: 'PUT'" in save
        reset = _block(JS, "resetPersona: async function",
                       "// ═══ Лор чатов")
        assert "this.api('/api/persona'" in reset
        assert "method: 'DELETE'" in reset

    def test_set_active_chat_resets_draft(self):
        block = _block(JS, "setActiveChat: function",
                       "isChatContext: function")
        assert "this.personaDraft = null" in block
        assert "this.personaMeta = null" in block
        assert "this.loadPersona()" in block
        assert "this.scopeEpoch++" in block

    def test_set_tab_loads_persona(self):
        block = _block(JS, "setTab: function", "toggleFullscreen: function")
        assert "id === 'persona'" in block
        assert "this.loadPersona()" in block

    def test_empty_value_not_default(self):
        # Пустое значение → '' и плейсхолдер, не захардкоженный дефолт.
        block = _block(JS, "loadPersona: async function",
                       "savePersona: async function")
        assert "v.name || ''" in block
        assert "v.biography || ''" in block
        assert "v.system_prompt_overrides || ''" in block
        assert "!!v.is_aware_ai" in block


class TestJsUnit:
    def test_routing_test_covers_persona(self):
        test = (ROOT / "tests" / "js" / "routing_test.js").read_text(
            encoding="utf-8")
        assert "persona-ui-tab-round1014" in test
        assert "routeToTab(#/ai/persona) == persona" in test
        assert "loadPersona" in test


# ═══ F4 `persona-traits-ribbon-round1014` (ТЗ §3.1 + UPD п.4) ═════════════
# Третья лента «Эволюция характера» + панель метрик Личности в «Сводке».

class TestTraitsRibbon:
    def test_third_ribbon_markup(self):
        block = _block(HTML, 'class="cognition-ribbons"', "Граф связей")
        assert block.count('class="ribbon"') == 3, "F4: ровно 3 ленты"
        assert "Убеждения" in block
        assert "Парадигмы" in block
        assert "Эволюция характера" in block
        assert "v-for=\"it in cognitionTraitsLoop\"" in block
        assert "fmtDayMonth(it.created_at)" in block
        assert "Пул черт пуст." in block
        # ленты beliefs/paradigms не сломаны
        assert "cognitionBeliefsLoop" in block
        assert "cognitionParadigmsLoop" in block

    def test_grid_three_columns_responsive(self):
        assert (".cognition-ribbons { display: grid; "
                "grid-template-columns: 1fr 1fr 1fr; gap: 12px; }") in HTML
        assert ("@media (max-width: 640px) { .cognition-ribbons "
                "{ grid-template-columns: 1fr; } }") in HTML

    def test_prefers_reduced_motion_preserved(self):
        assert ".ribbon-track { animation: none !important; }" in HTML

    def test_computed_reuses_ribbon_loop(self):
        assert "cognitionTraitsLoop: function" in JS
        block = _block(JS, "cognitionTraitsLoop: function",
                       "personaExtractorBadge: function")
        assert "this._ribbonLoop(this.cognitionTraits)" in block, \
            "F4: переиспользован _ribbonLoop (без дубля)"

    def test_data_fields(self):
        assert "cognitionTraits: []" in JS
        assert "personaHealth: null" in JS

    def test_adapter_shape(self):
        block = _block(JS, "_traitsAdapter: function", "_ribbonLoop: function")
        assert "it.text || ''" in block
        assert "created_at: it.ts || 0" in block
        assert "it.id != null" in block

    def test_fmt_day_month_helper(self):
        assert "fmtDayMonth: function" in JS

    def test_load_cognition_fail_open(self):
        block = _block(JS, "loadCognition: async function",
                       "loadMemoryWidget: async function")
        assert "this.api('/api/persona' + q)" in block
        assert "this._traitsAdapter(" in block
        assert "persona.dynamic_traits" in block
        assert "this.cognitionTraits = []" in block, "F4: fail-open пусто"
        assert "this.loadPersonaHealth()" in block


class TestPersonaHealthPanel:
    def test_panel_markup(self):
        block = _block(HTML, "activeTab === 'oversight'",
                       "activeTab === 'access'")
        assert "Личность" in block
        assert "personaHealth.traits_count" in block
        assert "personaHealth.last_trait_at" in block
        assert "personaHealth.extractor_status" in block
        assert "personaExtractorBadge" in block
        assert "loadPersonaHealth()" in block

    def test_loader_fail_open(self):
        block = _block(JS, "loadPersonaHealth: async function",
                       "oversightRows: function")
        assert "this.api('/api/persona/health')" in block
        assert "this.personaHealth = null" in block

    def test_health_loaded_on_oversight_entry_and_summary(self):
        set_tab = _block(JS, "if (id === 'oversight')",
                         "if (id === 'info')")
        assert "this.loadPersonaHealth()" in set_tab
        summary = _block(JS, "loadOversight: async function",
                         "loadPersonaHealth: async function")
        assert "this.loadPersonaHealth()" in summary

    def test_extractor_badge_mapping(self):
        block = _block(JS, "personaExtractorBadge: function",
                       "canEditInfo: function")
        for status in ("ok", "empty", "error", "never"):
            assert status + ":" in block, status
        assert "'badge-ok'" in block
        assert "'badge-err'" in block


# ═══ F7 `status-layout-reorder-round1014` (ТЗ §7) ════════════════════════
# Порядок блоков страницы «Статус»: Сводка → Сердцебиение → Бот → Сервер →
# Мониторинг Интеллекта → Доступность ключей. Чистая перестановка
# разметки (каталог-Δ = 0), без правок web/app.js.
# NOTE (ASAP 6 Wave 2, санкция visual-preservation-map): хвост «История»
# переехал в «Аналитику» (см. TestStatusLayoutOrderF7.ORDER).

def _status_block() -> str:
    """Срез разметки активной вкладки «Статус» (T-1535: границы v-else-if)."""
    return _block(HTML, "activeTab === 'status'", "activeTab === 'persona'")


class TestStatusLayoutOrderF7:
    # Заголовки-маркеры блоков (по видимому тексту, не по комментариям).
    # NOTE (санкция владельца: ASAP 6 Wave 2 — current_task.md §13.1:30978-30988
    # + visual-preservation-map «STATUS»): «История доступности ключей» и
    # «Логи» — REDESIGN и ПЕРЕНОС в «Аналитику» (вкладки «Модели и расходы»
    # и «Логи»); на «Статусе» остались компактный strip «Доступность ключей»,
    # случайность с техно-деталями в <details> и карточка-переход логов.
    # Порядок обновлён под санкционированный layout; перенесённые блоки
    # ассертятся в новом доме (test_moved_blocks_live_in_analytics ниже) —
    # защита от потери блока сохранена, не снята.
    ORDER = (
        # F1 (10.25, Human Gate §8.1): «Сводка» → «Аналитика» (route цел).
        ("Аналитика", "hub-card-title block\">Аналитика</span>"),
        ("Сердцебиение", "monitoring') }}</span> Сердцебиение</div>"),
        ("Бот", "smart_toy') }}</span> Бот</div>"),
        ("Сервер", "dns') }}</span> Сервер</div>"),
        ("Мониторинг Интеллекта",
         "psychology') }}</span> Мониторинг Интеллекта</div>"),
        ("Доступность ключей", "key') }}</span> Доступность ключей</div>"),
        ("Источник случайности",
         "bolt') }}</span> Источник случайности</div>"),
        ("Логи (переход)", "receipt_long') }}</span> Логи</div>"),
    )

    def test_order_confirmed(self):
        block = _status_block()
        idx = []
        for name, marker in self.ORDER:
            assert marker in block, "F7: пропал блок " + name
            idx.append(block.index(marker))
        assert idx == sorted(idx), \
            "F7: порядок блоков нарушен (Сводка→Сердцебиение→Бот→Сервер→" \
            "Мониторинг→Доступность→Случайность→Логи-переход)"

    def test_no_block_lost_or_duplicated(self):
        block = _status_block()
        for name, marker in self.ORDER:
            # «Доступность ключей» — подстрока «История доступности ключей»
            # не совпадает: регистр первой буквы и иконка разные.
            assert block.count(marker) == 1, (name, block.count(marker))

    def test_moved_blocks_live_in_analytics(self):
        """Перенесённые блоки не потеряны: полный дом — в «Аналитике».

        NOTE (FIX-logs-anchor, поправка владельца): блок «Логи» — НЕ вкладка,
        а ФИЗИЧЕСКИЙ дом внизу «Аналитики» (вне таб-гвардов, всегда в DOM,
        последний блок oversight); вкладка «Логи» — якорь/шорткат (скролл к
        #status-logs), отдельный режим не создаётся. «История доступности
        ключей» остаётся на вкладке «Модели и расходы». Рендер-внутренности
        реестра ключей гейтятся test_webapp_key_availability_ui (компактный
        список/график/no-hardcode), поведение логов — test_webapp_f11
        (log counts) + js-тесты; здесь — инвариант ПЕРЕНОСА (дом + отсутствие
        дублей + якорная ссылка на Статусе)."""
        # «История доступности ключей» → «Модели и расходы» (единый дом).
        i = HTML.index("data-key-history")
        seg_keys = HTML[HTML.rfind("<div", 0, i):HTML.index('id="status-logs"', i)]
        assert "История доступности ключей" in seg_keys
        assert "oversightTab === 'models'" in seg_keys
        assert "isGlobalAdmin" in seg_keys
        # «Логи» — физический дом в #/oversight ВНЕ таб-гвардов (последним):
        # НЕ внутри v-if вкладки «Логи»; viewer/level-select/чип «Саммари».
        j = HTML.index('id="status-logs"')
        seg_logs = HTML[j:HTML.index("</template>", j)]
        assert "oversightTab === 'logs'" not in seg_logs, \
            "логи не должны жить под v-if вкладки «Логи» (якорь-контракт)"
        assert 'v-model="logLevel"' in seg_logs
        assert "toggleLogSummary()" in seg_logs
        # Полный дом: trace-фильтры и копирование на месте.
        assert 'id="mca-log-filters"' in seg_logs
        assert "copyAllLogs()" in seg_logs
        # На «Статусе» остались strip ключей и карточка-переход логов.
        block = _status_block()
        assert "data-key-strip" in block
        assert 'id="status-logs-link"' in block
        assert "scrollToLogs()" in block
        # Прежний статусный дом истории ключей не дублируется: блок ровно один.
        assert HTML.count("data-key-history") == 1
        assert HTML.count('id="status-logs"') == 1

    def test_heartbeat_between_summary_and_bot(self):
        block = _status_block()
        summary = block.index(self.ORDER[0][1])
        heartbeat = block.index(self.ORDER[1][1])
        bot = block.index(self.ORDER[2][1])
        assert summary < heartbeat < bot

    def test_cognition_between_server_and_keys(self):
        block = _status_block()
        server = block.index(self.ORDER[3][1])
        cognition = block.index(self.ORDER[4][1])
        keys = block.index(self.ORDER[5][1])
        assert server < cognition < keys

    def test_f4_third_ribbon_kept_inside_cognition(self):
        block = _status_block()
        cognition = block.index(self.ORDER[4][1])
        keys = block.index(self.ORDER[5][1])
        segment = block[cognition:keys]
        assert "Эволюция характера" in segment
        assert segment.count('class="ribbon"') == 3
        assert "cognitionBeliefsLoop" in segment
        assert "cognitionParadigmsLoop" in segment
        assert "cognitionTraitsLoop" in segment
        # F11 (10.25, ADR-1025-23 D1/D4, §12): граф связей ВЫНЕСЕН в отдельную
        # карточку строки 2 (`.sg-8`, перед «Мониторингом Интеллекта») — это
        # AMEND целевой композиции «Статуса». Виджет не потерян: контейнер
        # `ref="cognitionGraph"` сохранён и присутствует в ветке «Статуса».
        assert "cognitionGraph" in block, "F11: граф не потерян"
        assert block.index("cognitionGraph") < cognition, \
            "F11 §12: граф — строка 2 (перед «Мониторингом Интеллекта»)"

    def test_heartbeat_block_intact(self):
        block = _status_block()
        heartbeat = block[block.index(self.ORDER[1][1]):
                          block.index(self.ORDER[2][1])]
        # hotfix6/C2 (ADR-1025-12 D4): SVG-EKG заменён на Canvas 2D + rAF;
        # legacy-SVG сохранён под v-if/v-else (откат UI_HEARTBEAT_CANVAS_ENABLED).
        for marker in ("hb-wrap", "hb-canvas", "ekg-base", "ekg-trace",
                       "heartbeatCanvasEnabled", "heartbeat.badge",
                       "heartbeat.period"):
            assert marker in heartbeat, marker

    def test_app_js_untouched(self):
        # F7 — только разметка: computed/ref/загрузчики порядко-независимы,
        # правок web/app.js нет (T-1535).
        assert "heartbeat: function" in JS
        assert "loadCognition: async function" in JS
        assert "loadKeyHistory: async function" in JS

