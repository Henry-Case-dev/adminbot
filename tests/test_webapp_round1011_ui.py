"""Раунд 10.11 (llm-providers-refactor-round1011) — UI-маркеры + инварианты.

Покрывается (spec §6.3):
  * п.1 (ADR-1011-1) — R17-индикатор сохранённого ключа + hint «без ввода»;
  * п.2.1 — nav/профиль/hub-сетка (CSS-маркеры);
  * п.2.2 — зоны «Подключения» / «Расширенные настройки»;
  * п.2.3 (ADR-1011-2) — embeddings: 3 подблока + Δ каталога без роста счётчиков;
  * п.2.4 — запасная видео-модель под основной (video_fallback), code-default;
  * п.2.5 — media_share в advanced + human-subtext;
  * п.3 (ADR-1011-3) — linear-time ось, spanGaps:true, parsing:false, без adapter.

Все проверки — статические grep-маркеры (как test_webapp_round1010_ui).
"""
import dataclasses
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
PROBE = (ROOT / "services" / "llm_probe.py").read_text(encoding="utf-8")
LLM_CLIENT = (ROOT / "services" / "llm_client.py").read_text(encoding="utf-8")
STATUS = (ROOT / "services" / "status_service.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")


class TestProviderKeyHint:
    """п.1 (ADR-1011-1): маска + hint, сырой секрет не в DOM/сети."""

    def test_hint_marker(self):
        assert "blockFieldConfigured: function" in JS
        assert "last4ByKey: function" in JS
        assert "Ключ сохранён (••••" in HTML
        assert "можно проверить без ввода" in HTML
        # Сырой ключ по-прежнему не идёт в value (маска/placeholder).
        assert ':value="blockFieldValue(f)"' in HTML
        assert 'v-model="blockDrafts[f.key]"' not in HTML

    def test_backend_resolves_saved_key(self):
        assert "_BLOCK_SAVED_KEY" in PROBE
        assert "_saved_api_key" in PROBE
        assert "if not (api_key or \"\").strip():" in PROBE
        assert '"keys.media_share_secret"' in PROBE
        assert '"keys.embedding_fallback_api_key"' in PROBE
        assert '"keys.embedding_fallback_api_key_2"' in PROBE

    def test_feeds_for_media_share_and_video(self):
        assert '"video_fallback"' in PROBE
        assert '"embeddings_fallback1"' in PROBE
        assert '"embeddings_fallback2"' in PROBE


class TestZonesAndLayout:
    """пп.2.1–2.2: зоны, nav/профиль/сетка."""

    def test_zones(self):
        assert "v-for=\"b in providerConnectionBlocks\"" in HTML
        assert "v-for=\"b in providerAdvancedBlocks\"" in HTML
        assert "Расширенные настройки" in HTML
        assert ":is=\"activeTab === 'llm_providers' ? 'details' : 'div'\"" in HTML

    def test_zone_helpers_are_computed_not_methods(self):
        """Reviewer CRITICAL: bare-ref в шаблоне (`v-for ... in X`,
        `X.length`) требует computed; метод-функция рендерилась бы как `[]`
        и все блоки 2.2–2.5 исчезали. Жёсткий гейт против регресса."""
        for name in ("providerConnectionBlocks", "providerAdvancedBlocks"):
            assert JS.count(f"{name}: function") == 1, name
            assert f"{name}: function" in JS
        computed_at = JS.index("computed:")
        methods_at = JS.index("methods:")
        assert computed_at < methods_at
        for name in ("providerConnectionBlocks", "providerAdvancedBlocks"):
            at = JS.index(f"{name}: function")
            assert computed_at < at < methods_at, (
                f"{name} должен быть в computed: (не methods:)")
        # computed вызывать как функцию в шаблоне нельзя.
        assert "providerConnectionBlocks()" not in HTML
        assert "providerAdvancedBlocks()" not in HTML
        # метод-двойник отсутствует (иначе снова bare-ref → []).
        assert "providerConnectionBlocks: function" not in JS.split("methods:")[1]
        assert "providerAdvancedBlocks: function" not in JS.split("methods:")[1]

    def test_provider_blocks_zones(self):
        i = JS.index("var PROVIDER_BLOCKS")
        chunk = JS[i:JS.index("];", i)]
        assert "zone: 'advanced'" in chunk
        assert "subBlocks:" in chunk
        # llm_guard/search_keys/media_share — advanced.
        assert chunk.count("zone: 'advanced'") == 3

    def test_nav_and_profile(self):
        assert ".nav-link .nav-icon { font-size: 22px" in HTML
        assert "gap: .15rem" in HTML
        assert "min-width: 60px" in HTML
        assert "items-center gap-1.5 text-xs shrink-0" in HTML
        assert "whitespace-nowrap max-w-[7rem]" in HTML
        assert "max-width: 64rem" in HTML


class TestEmbeddingsAndVideo:
    """пп.2.3–2.5: 3 подблока, video_fallback, media_share внизу."""

    def test_embeddings_three_subblocks(self):
        assert "id: 'embeddings_main'" in JS
        assert "id: 'embeddings_fallback1'" in JS
        assert "id: 'embeddings_fallback2'" in JS
        assert "Адрес и модель общие с «Фоллбэк 1»" in JS
        assert "b.subBlocks" in HTML
        # generic-фильтр рекурсивно покрывает подблоки.
        assert "b.subBlocks || []" in JS

    def test_video_fallback_after_primary(self):
        i = JS.index("id: 'video_summary_openrouter'")
        j = JS.index("id: 'video_fallback'")
        assert i < j, "видео-фоллбэк идёт после основной видео-модели"
        assert "models.video_fallback_model" in JS

    def test_media_share_advanced_with_note(self):
        assert "Секретный токен для авторизации бота" in JS
        m = JS.index("id: 'media_share'")
        chunk = JS[m:m + 400]
        assert "zone: 'advanced'" in chunk

    def test_embeddings_read_path_hot(self):
        for key in ("models.embedding_fallback_base_url",
                    "models.embedding_fallback_model",
                    "keys.embedding_fallback_api_key",
                    "keys.embedding_fallback_api_key_2"):
            assert key in LLM_CLIENT, key
            assert key in STATUS, key


class TestCatalogDelta1011:
    """ADR-1011-2: sanctioned Δ без роста счётчиков; 4 ключа — first-class."""

    def test_counts_unchanged(self):
        from config.settings import Settings
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 400
        assert len(pc.GROUPS) == 90
        assert len(pc._TAB_BY_GROUP) == 88
        assert len(pc.TAB_RULES) == 19
        assert len({f.name for f in dataclasses.fields(Settings)}) == 372

    def test_moved_entries_are_catalog(self):
        from services import param_catalog as pc
        cases = {
            "models.embedding_fallback_base_url": ("models", "models_embeddings", False),
            "models.embedding_fallback_model": ("models", "models_embeddings", False),
            "keys.embedding_fallback_api_key": ("keys", "keys_llm", True),
            "keys.embedding_fallback_api_key_2": ("keys", "keys_llm", True),
        }
        for pg_key, (cat, grp, secret) in cases.items():
            spec = pc.get_by_pg_key(pg_key)
            assert spec is not None, pg_key
            assert spec.category == cat, pg_key
            assert spec.group == grp, pg_key
            assert spec.secret is secret, pg_key

    def test_removed_from_infra(self):
        from services import param_catalog as pc
        infra_fields = {row[0] for row in pc._INFRA}
        for field in ("EMBEDDING_FALLBACK_BASE_URL",
                      "EMBEDDING_FALLBACK_MODEL",
                      "EMBEDDING_FALLBACK_API_KEY",
                      "EMBEDDING_FALLBACK_API_KEY_2"):
            assert field not in infra_fields, field
        # тайминги остаются infra.
        assert "EMBEDDING_FALLBACK_TIMEOUT_SECONDS" in infra_fields
        assert "EMBEDDING_FALLBACK_MAX_RETRIES" in infra_fields


class TestKeyHistoryAxis:
    """п.3 (ADR-1011-3): linear-time, spanGaps:true, без date-adapter."""

    def test_model_points_and_xmin(self):
        assert "xMin: grid[0] * 1000" in JS
        assert "xMax: grid[grid.length - 1] * 1000" in JS
        assert "x: ts * 1000" in JS

    def test_render_config(self):
        assert "spanGaps: true" in JS
        assert "stepped: true" in JS
        assert "parsing: false" in JS
        assert "type: 'linear'" in JS
        assert "type: 'time'" not in JS
        assert "return pad(d.getHours()) + ':' + pad(d.getMinutes());" in JS

    def test_adr1010_contract_preserved(self):
        assert "maintainAspectRatio: false" in JS
        assert "keyHistoryChartHeight + 'px'" in HTML
        assert 'ref="keyHistoryCanvas"' in HTML


class TestScannerLows1011:
    """Scanner lows: раздельные localStorage-ключи аккордеонов и актуальные
    подсказки (каталог/мини-апп вместо .env)."""

    def test_advanced_zone_distinct_localstorage_key(self):
        # Внешняя зона advanced — отдельный стабильный ключ.
        assert "expandOpen(activeTab, 'prov-advanced')" in HTML
        assert "toggleExpand(activeTab, 'prov-advanced')" in HTML
        # Хелперы принимают scope; есть общий построитель ключа.
        assert "expandOpen: function (tabId, scope)" in JS
        assert "toggleExpand: function (tabId, scope)" in JS
        assert "function _expandKey(tabId, scope)" in JS
        # Внутренние group-аккордеоны остаются на историческом ключе.
        assert ':open="expandOpen(activeTab)"' in HTML

    def test_embed_hints_point_to_miniapp_not_env(self):
        # Устаревших .env-подсказок по embed-ключам больше нет.
        assert ".env EMBEDDING_*" not in LLM_CLIENT
        assert "EMBEDDING_FALLBACK_API_KEY(_2)) в .env" not in LLM_CLIENT
        assert "проверьте их в .env" not in LLM_CLIENT
        # Подсказки указывают на каталог в мини-аппе.
        assert "«LLM Провайдеры»" in LLM_CLIENT
        assert "«Эмбеддинги»" in LLM_CLIENT
        # settings: комментарий про редактирование в мини-аппе (embed-блок).
        assert "«LLM Провайдеры» → «Эмбеддинги»" in SETTINGS
        assert "BASE_URL/MODEL/API_KEY/API_KEY_2 — редактируются в мини-аппе" \
            in SETTINGS
