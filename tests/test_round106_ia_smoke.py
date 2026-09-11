"""Раунд 10.6 (T-1211) — smoke/маркеры новой IA TMA (A1–A9).

Покрытие: каталог-инвариант 392/91/364/mapped 89; 5 master-флагов default ON;
реальные гейты; 11 модулей/7 AI; нет sidebar; scroll-модель; emoji→icon;
эксклюзивный аккордеон; per-block test-endpoint.
"""
import dataclasses

import pytest

from config.settings import Settings
from services import param_catalog as pc

JS = open("web/app.js", encoding="utf-8").read()
HTML = open("web/index.html", encoding="utf-8").read()


class TestCatalogInvariant106:
    def test_counts(self):
        assert len(pc.REGISTRY) == 392
        assert len(pc.GROUPS) == 91
        assert len(pc._TAB_BY_GROUP) == 89
        assert len(pc.TAB_RULES) == 19
        assert len({f.name for f in dataclasses.fields(Settings)}) == 364

    def test_five_master_flags_default_true(self):
        s = Settings()
        for field in ("FACTCHECK_ENABLED", "SEARCH_ENABLED",
                      "VIDEO_SUMMARY_ENABLED", "WEBPAGE_ENABLED",
                      "CHECKUP_ENABLED"):
            assert getattr(s, field) is True, field
            spec = pc.get(field)
            assert spec is not None and spec.category == "flags"

    def test_master_flag_groups(self):
        by_key = {s.pg_key: s for s in pc.REGISTRY.values()}
        assert by_key["flags.factcheck_enabled"].group == "flags_module_factcheck"
        assert by_key["flags.search_enabled"].group == "flags_module_search"
        assert by_key["flags.video_summary_enabled"].group == "flags_module_video_summary"
        assert by_key["flags.webpage_enabled"].group == "flags_module_web"
        assert by_key["flags.checkup_enabled"].group == "flags_service"

    def test_limits_rag_has_two_keys(self):
        keys = [s.pg_key for s in pc.REGISTRY.values()
                if s.group == "limits_rag"]
        assert sorted(keys) == [
            "limits.chat_budget_rag_ratio",
            "limits.chat_rag_dedup_overlap_ratio"]
        assert pc.group_tab("limits_rag") == pc.TAB_MEMORY_RAG


class TestRuntimeGates:
    def test_handlers_gate_on_hot_flags(self):
        checks = {
            "handlers/factcheck.py": "flags.factcheck_enabled",
            "handlers/search.py": "flags.search_enabled",
            "handlers/web.py": "flags.webpage_enabled",
            "handlers/checkup.py": "flags.checkup_enabled",
            "handlers/youtube.py": "flags.video_summary_enabled",
        }
        for path, marker in checks.items():
            src = open(path, encoding="utf-8").read()
            assert marker in src, path

    def test_youtube_gate_only_summary(self):
        src = open("handlers/youtube.py", encoding="utf-8").read()
        assert 'request.mode == "summary"' in src


class TestNavShell:
    def test_no_sidebar(self):
        assert "sidebar" not in JS
        assert "sidebar" not in HTML
        assert "MENU_ORDER" not in JS
        assert "MENU_LABELS" not in JS
        assert "☰" not in HTML

    def test_navbar_labels_visible(self):
        assert 'class="nav-label"' in HTML
        assert ".nav-link > span:not(.msr) { display: none; }" not in HTML
        assert 'aria-current' in HTML

    def test_scroll_model(self):
        assert ".app-shell" in HTML
        assert ".scroll-area" in HTML
        assert ".fullscreen-mode .scroll-area" in HTML
        assert "overflow-y: auto" in HTML


class TestModulesAndAi:
    def test_modules_exactly_11(self):
        assert JS.count("toggleKey:") == 11
        for title in ("Саммаризация", "Прямые ответы", "Фактчек", "Поиск",
                      "Транскрипт голосовых и видео", "Выжимка видео",
                      "Скачивание медиа", "Веб-страницы", "Диагностика",
                      "Сон", "Ностальгия"):
            assert title in JS, title

    def test_no_custom_modules(self):
        assert "Кастомные модули" not in JS
        assert "Кастомные модули" not in HTML

    def test_ai_hub_seven_cards(self):
        assert "id: 'smart_cache'" in JS
        assert "'#/ai/smart-cache'" in JS
        # «Лимиты»/«Сон»/«Ностальгия» — не в AI
        assert "route: '#/ai/limits'" not in JS
        assert "route: '#/ai/sleep'" not in JS
        assert "route: '#/ai/nostalgia'" not in JS

    def test_provider_blocks_nine(self):
        assert JS.count("role: 'base_url'") >= 4
        assert "direct_main" in JS and "direct_fallback" in JS
        assert "transcribe_groq" in JS and "transcribe_openrouter" in JS
        assert "video_summary_openrouter" in JS
        assert "search_keys" in JS and "media_share" in JS
        assert "embeddings" in JS and "llm_guard" in JS
        assert "Проверить" in HTML


class TestA6A7A9:
    def test_emoji_to_icon(self):
        assert "ℹ️ Как это работает" not in HTML
        assert "🔐 Матрица ролей" not in HTML
        assert "iconGlyph('help')" in HTML
        assert "iconGlyph('admin_panel_settings')" in HTML
        assert "iconGlyph('manage_accounts')" in HTML
        assert "iconGlyph('restart_alt')" in HTML

    def test_access_windows(self):
        # 10.8 (§4, ADR-001): route-driven модалки вместо аккордеона.
        assert "accessOpen" in JS
        assert "openAccessWindow: function (id)" in JS
        assert "closeAccessWindow: function ()" in JS
        assert "setAccess" not in JS
        assert 'class="modal-backdrop"' in HTML
        assert 'class="acc-head"' not in HTML
        assert 'role="tabpanel"' not in HTML
        assert "isAccessOpen('roles')" in HTML
        assert "isAccessOpen('local')" in HTML
        assert "isAccessOpen('admins')" in HTML

    def test_removed_routes_aliased(self):
        for old in ("#/ai/limits", "#/ai/sleep", "#/ai/nostalgia",
                    "#/modules/features", "#/modules/switches",
                    "#/modules/reactions", "#/modules/custom"):
            assert old in JS, old


class TestLlmProbeService:
    def test_sanitize_error_removes_key(self):
        from services.llm_probe import sanitize_error, KNOWN_BLOCKS
        assert "sk-secret" not in sanitize_error("bad sk-secret", "sk-secret")
        assert "***" in sanitize_error("bad sk-secret", "sk-secret")
        for block in ("direct_main", "direct_fallback", "transcribe_groq",
                      "transcribe_openrouter", "video_summary_openrouter",
                      "embeddings", "search_keys", "checkup_betterstack"):
            assert block in KNOWN_BLOCKS, block
        # MAJOR-1: llm_guard — не сетевой провайдер, тест не поддерживается.
        assert "llm_guard" not in KNOWN_BLOCKS

    def test_search_keys_no_base_url_needed(self, monkeypatch):
        """MAJOR-1: ветка search обрабатывается ДО проверки base_url."""
        import asyncio
        from services import llm_probe

        class _Resp:
            status_code = 200
            text = ""

        async def fake_search(client, base, api_key, provider=None):
            return _Resp()

        monkeypatch.setattr(llm_probe, "_probe_search", fake_search)
        res = asyncio.run(llm_probe.probe_block("search_keys", "", "", "tvly-x"))
        assert res["ok"] is True, res
        assert res["http_status"] == 200

    @pytest.mark.parametrize("block,expected", [
        ("search_keys:tavily", "tavily"),
        ("search_keys:exa", "exa"),
    ])
    def test_search_keys_per_provider(self, monkeypatch, block, expected):
        """MINOR-2: search_keys:tavily/exa → _probe_search(provider=...)."""
        import asyncio
        from services import llm_probe

        seen = {}

        class _Resp:
            status_code = 200
            text = ""

        async def fake_search(client, base, api_key, provider=None):
            seen["provider"] = provider
            return _Resp()

        monkeypatch.setattr(llm_probe, "_probe_search", fake_search)
        res = asyncio.run(llm_probe.probe_block(block, "", "", "key-x"))
        assert res["ok"] is True
        assert seen["provider"] == expected

    def test_search_keys_bad_provider_rejected(self):
        import asyncio
        from services.llm_probe import probe_block
        res = asyncio.run(probe_block("search_keys:bogus", "", "", "k"))
        assert res["ok"] is False
        assert res["error"] == "неизвестный блок"

    def test_embeddings_requires_base_url(self):
        import asyncio
        from services.llm_probe import probe_block
        res = asyncio.run(probe_block("embeddings", "", "m", "k"))
        assert res["ok"] is False
        assert "base_url" in res["error"]

    def test_llm_guard_is_not_testable(self):
        import asyncio
        from services.llm_probe import probe_block
        res = asyncio.run(probe_block("llm_guard", "https://x/v1", "30", "k"))
        assert res["ok"] is False
        assert res["error"] == "неизвестный блок"

    def test_ssrf_http_external_rejected(self):
        import asyncio
        from services.llm_probe import probe_block
        res = asyncio.run(probe_block("direct_main", "http://evil.example/v1",
                                      "m", "k"))
        assert res["ok"] is False
        assert "https" in res["error"]

    @pytest.mark.parametrize("host", [
        "http://localhost.evil.com/v1",
        "http://127.0.0.1.evil.com/v1",
        "http://localhost:8080@evil.com/v1",
    ])
    def test_ssrf_prefix_bypass_rejected(self, host):
        """MINOR-1: префиксная проверка обходилась localhost.evil.com."""
        import asyncio
        from services.llm_probe import probe_block
        res = asyncio.run(probe_block("direct_main", host, "m", "k"))
        assert res["ok"] is False, res
        assert "https" in res["error"]

    def test_ssrf_exact_localhost_allowed(self, monkeypatch):
        """MINOR-1: ровно loopback-host по-прежнему разрешён (dev)."""
        import asyncio
        from services import llm_probe

        class _Resp:
            status_code = 200
            text = ""

        async def fake_post(client, url, headers, body):
            return _Resp()

        monkeypatch.setattr(llm_probe, "_post_json", fake_post)
        res = asyncio.run(llm_probe.probe_block(
            "direct_main", "http://localhost:8000/v1", "m", "k"))
        assert res["ok"] is True, res

    def test_media_share_validation_no_network(self):
        import asyncio
        from services.llm_probe import probe_block
        res = asyncio.run(probe_block("media_share", "", "", ""))
        assert res["ok"] is False
        res_ok = asyncio.run(probe_block("media_share", "", "", "secret"))
        assert res_ok["ok"] is True


class TestProviderBlockTestability:
    """MAJOR-1: кнопка «Проверить» рендерится только для testable-блоков."""

    def test_embeddings_and_llm_guard_not_testable(self):
        assert "testable: false" in JS
        # embeddings + llm_guard помечены testable:false (2 блока)
        assert JS.count("testable: false") == 2
        assert "b.testable !== false" in HTML

    def test_llm_guard_fields_no_model_role(self):
        # Значения llm_guard не отправляются как `model`.
        i = JS.index("id: 'llm_guard'")
        chunk = JS[i:i + 500]
        assert "role: ''" in chunk
        assert "role: 'model'" not in chunk

    def test_search_keys_no_base_url_field(self):
        i = JS.index("id: 'search_keys'")
        chunk = JS[i:i + 700]
        assert "role: 'base_url'" not in chunk
        # MINOR-2: раздельные пробы каждого ключа.
        assert "perFieldTest: true" in chunk
        assert "probeTarget: 'search_keys:tavily'" in chunk
        assert "probeTarget: 'search_keys:exa'" in chunk
        assert "testField(b, f)" in HTML


class TestModalReachability:
    """MAJOR-2 / MODERATE-2: панели Сон/Ностальгия — в модалке; Esc/бэк."""

    def test_sleep_panels_inside_modal(self):
        assert "activeModule && activeModule.id === 'mod_sleep' && isGlobalAdmin" in HTML
        assert "activeModule && activeModule.id === 'mod_nostalgia' && isGlobalAdmin" in HTML
        assert "activeTab === 'mod_sleep'" not in HTML
        assert "activeTab === 'mod_nostalgia'" not in HTML

    def test_ensure_module_data_present(self):
        assert "_ensureModuleData" in JS
        assert "loadDreamBeliefs()" in JS
        assert "loadNostalgiaLog()" in JS

    def test_global_esc_listener(self):
        assert "_onKeydown" in JS
        assert "window.addEventListener('keydown', _onKeydown)" in JS
        assert "e.key === 'Escape'" in JS


class TestAliasNormalization:
    def test_route_alias_map(self):
        i = JS.index("var ROUTE_ALIAS")
        chunk = JS[i:i + 500]
        for old in (
            "'#/ai/limits': '#/ai'",
            "'#/ai/sleep': '#/modules'",
            "'#/ai/nostalgia': '#/modules'",
        ):
            assert old in chunk, old
        assert "history.replaceState(null, '', aliasTarget)" in JS


class TestScannerR106Fixes:
    """R10.6-1 (один дом редакторов) + R10.6-3 (422 без эха секрета)."""

    def test_provider_blocks_single_home(self):
        import re
        assert "providerCoveredKeys" in JS
        assert "covered && covered[it.key]" in JS
        i = JS.index("var PROVIDER_BLOCKS")
        chunk = JS[i:JS.index("];", i)]
        keys = re.findall(r"key: '([^']+)'", chunk)
        assert len(keys) == 23          # полей в блоках
        assert len(set(keys)) == 21     # уникальных ключей (2 общих OpenRouter)
        # generic-фильтр только для llm_providers
        assert "(tab.id === 'llm_providers')" in JS

    def test_422_sanitized_in_source(self):
        app = open("web/app.py", encoding="utf-8").read()
        assert "@app.exception_handler(RequestValidationError)" in app
        assert '"loc": list(err.get("loc", []))' in app
        assert "input" not in app.split("_safe_validation_handler")[1][:600]
        assert "ctx" not in app.split("_safe_validation_handler")[1][:600]
        assert "JSONResponse(status_code=422" in app
