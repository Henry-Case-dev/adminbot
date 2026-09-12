"""Раунд 10.12 (`providers-kostik-round1012`) — UI/каталог/read-path маркеры.

Покрывается (spec §1.7/§2.6/§3.8):
  * item 1 — развязка embed base_url/ключа (OD-1), фикс 422 (global-save);
  * item 2 — merged parent-блоки + подпись «Название модели»;
  * item 3 — блок Костика, виджет list, под-флаг flags.kostik_enabled;
  * sanctioned Δ каталога: REGISTRY 405 / Settings 377 / categorized 381.
"""
import dataclasses
from pathlib import Path

ROOT = Path(".")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
LLM_CLIENT = (ROOT / "services" / "llm_client.py").read_text(encoding="utf-8")
STATUS = (ROOT / "services" / "status_service.py").read_text(encoding="utf-8")
KOSTIK = (ROOT / "handlers" / "kostik.py").read_text(encoding="utf-8")
PERMSOC = (ROOT / "services" / "permsoc.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


class TestItem1EmbedDecoupling:
    def test_new_settings_defaults(self):
        from config.settings import Settings
        s = Settings()
        assert s.LLM_BASE_URL == "https://nano-gpt.com/api/v1"
        assert s.EMBEDDING_BASE_URL == "https://apinet.cloud/v1"
        assert s.EMBEDDING_API_KEY == ""
        assert s.OPENROUTER_TRANSCRIBE_DISPLAY_NAME == ""

    def test_env_example_updated(self):
        assert "LLM_BASE_URL=https://nano-gpt.com/api/v1" in ENV_EXAMPLE
        assert "EMBEDDING_BASE_URL=https://apinet.cloud/v1" in ENV_EXAMPLE
        assert "EMBEDDING_API_KEY" in ENV_EXAMPLE
        assert "KOSTIK_ENABLED=True" in ENV_EXAMPLE

    def test_save_key_item_global_path(self):
        """Scanner LOW follow-up: keys.* (per_chat=false) в saveKeyItem —
        глобальный путь без X-Chat-Id (не 422)."""
        i = JS.index("saveKeyItem: async function")
        chunk = JS[i:i + 900]
        assert "var isGlobal = item.per_chat === false" in chunk
        assert "global: isGlobal" in chunk

    def test_llm_client_embed_base_and_key(self):
        assert "embed_base_url: str | None = None" in LLM_CLIENT
        assert "embed_api_key: str | None = None" in LLM_CLIENT
        assert "models.embedding_base_url" in LLM_CLIENT
        assert "keys.embedding_api_key" in LLM_CLIENT
        assert "_embed_base_url" in LLM_CLIENT
        assert "def _current_embed_api_key" in LLM_CLIENT
        assert "base_url=self._embed_base_url" in LLM_CLIENT

    def test_status_service_emb_main_uses_embed_base(self):
        assert "models.embedding_base_url" in STATUS
        assert "emb_base" in STATUS
        # STT-фолбэк — отдельный display-name (не общий с видео).
        assert "models.openrouter_transcribe_display_name" in STATUS

    def test_ui_embeddings_main_own_fields(self):
        i = JS.index("id: 'embeddings_main'")
        chunk = JS[i:i + 900]
        assert "models.embedding_base_url" in chunk
        assert "keys.embedding_api_key" in chunk
        assert "{ key: 'models.llm_base_url'" not in chunk

    def test_global_save_option(self):
        # api() поддерживает global и не утекает флагом в fetch.
        assert "options.global !== true" in JS
        assert "delete init.global" in JS
        assert "global: true" in JS
        # saveBlock/saveConfigItem различают per_chat=false.
        assert "isGlobalKey" in JS
        assert "global: allGlobal" in JS
        assert "var isGlobal = item.per_chat === false" in JS

    def test_bot_di_all_four_call_sites(self):
        """Ревью-дефект 1: DI embed-base/ключа во ВСЕХ 4 точках LLMClient."""
        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        assert bot.count(
            'embed_base_url=hot.get("models.embedding_base_url"') == 4
        assert bot.count(
            'embed_api_key=hot.get("keys.embedding_api_key"') == 4


class TestItem2MergedBlocks:
    def test_parent_titles(self):
        assert "id: 'direct', title: 'Прямые ответы'" in JS
        assert "id: 'transcription', title: 'Транскрибация'" in JS
        assert "id: 'video_summary', title: 'Саммаризация видео'" in JS

    def test_merged_subblock_titles(self):
        assert "title: 'Запасная модель'," in JS
        assert "title: 'Модель транскрибации'" in JS
        assert "title: 'Запасная модель транскрибации'" in JS
        assert "title: 'Саммаризация видео'," in JS
        assert "title: 'Запасная модель саммаризации видео'" in JS

    def test_display_name_label(self):
        assert "blockDisplayName: function" in JS
        assert "{{ blockDisplayName(b) }}" in HTML
        assert "{{ blockDisplayName(sb) }}" in HTML
        # Резервный текст — modules (не пусто/не хардкод); дубль заголовка
        # подавляется (modules == title).
        assert "x.modules || ''" in JS
        assert "value === x.title) return ''" in JS

    def test_stt_display_name_split(self):
        assert "models.openrouter_transcribe_display_name" in JS
        # видео-блок остаётся на общем models.openrouter_display_name.
        assert "models.openrouter_display_name" in JS

    def test_all_ids_preserved_and_probe_router(self):
        for bid in ("direct_main", "direct_fallback", "transcribe_groq",
                    "transcribe_openrouter", "video_summary_openrouter",
                    "video_fallback"):
            assert f"id: '{bid}'" in JS, bid

    def test_stt_and_summary_wiring_no_swap(self):
        """§2.1: транскрибация → groq/openrouter_transcribe_model,
        саммаризация → video_primary/fallback_model (свопа в коде нет)."""
        from SmartModule.transcriber.groq_transcriber import (
            GROQ_TRANSCRIBE_MODEL)
        from SmartModule.transcriber.openrouter_transcriber import (
            OPENROUTER_TRANSCRIBE_MODEL)
        import SmartModule.service as svc
        import inspect
        src = inspect.getsource(svc)
        assert "GroqTranscriber" in src and "OpenRouterTranscriber" in src
        # Видео-каскад читает video_* через youtube_summarizer_service.
        yt = (ROOT / "services" / "youtube_summarizer_service.py").read_text(
            encoding="utf-8")
        assert "models.video_primary_model" in yt
        assert "models.video_fallback_model" in yt
        # Транскрибация использует STT-модели.
        assert GROQ_TRANSCRIBE_MODEL
        assert OPENROUTER_TRANSCRIBE_MODEL


class TestItem3Kostik:
    def test_settings_default_pool(self):
        from config.settings import DEFAULT_KOSTIK_REPLIES
        assert len(DEFAULT_KOSTIK_REPLIES) == 14
        assert "Папочка, только не в попочку" in DEFAULT_KOSTIK_REPLIES
        assert "Daddy, i'm scared, убери это пожалуйста" \
            in DEFAULT_KOSTIK_REPLIES

    def test_handler_reads_hot_no_literal(self):
        assert "hot.get(\"reactions.kostik_replies\"" in KOSTIK
        assert "кринжатура" not in KOSTIK
        assert "def _resolve_replies" in KOSTIK

    def test_permsoc_sub_flag(self):
        assert '"flags.kostik_enabled"' in PERMSOC
        assert 'DEFAULT_SUB_FLAGS' in PERMSOC

    def test_owner_block_in_ui(self):
        assert "id: 'kostik', title: 'Костик'" in JS
        assert "'flags.kostik_enabled': true" in JS
        assert "'reactions.kostik_replies'" in JS
        assert "'limits.kostik_reply_probability'" in JS

    def test_list_widget_both_templates(self):
        # desktop + mobile/compact ветки.
        assert HTML.count("item.widget === 'list'") == 2
        assert 'id="list-editor-tpl"' in HTML
        assert "+ Добавить фразу" in HTML
        assert "list-editor :item=\"item\"" in HTML
        assert "app.component('list-editor'" in JS

    def test_list_editor_component(self):
        i = JS.index("app.component('list-editor'")
        chunk = JS[i:i + 2200]
        for marker in ("sync: function", "addRow: function",
                       "removeRow: function", "save: async function"):
            assert marker in chunk, marker
        # Stable :key (не index): параллельный rowIds-массив.
        assert "rowIds" in chunk
        assert ':key="rowIds[i]"' in HTML
        assert ":key=\"'le' + i\"" not in HTML


class TestCatalogDelta1012:
    def test_counts(self):
        from config.settings import Settings
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 405
        assert len(pc.GROUPS) == 90
        assert len(pc._TAB_BY_GROUP) == 88
        assert len(pc.TAB_RULES) == 19
        assert len({f.name for f in dataclasses.fields(Settings)}) == 377
        categorized = [s for s in pc.REGISTRY.values()
                       if s.category is not None]
        assert len(categorized) == 381

    def test_new_param_specs(self):
        from services import param_catalog as pc
        cases = {
            "models.embedding_base_url":
                ("models", "models_embeddings", "str", False, ""),
            "models.openrouter_transcribe_display_name":
                ("models", "models_extra_providers", "str", False, ""),
            "keys.embedding_api_key":
                ("keys", "keys_llm", "str", True, ""),
            "flags.kostik_enabled":
                ("flags", "flags_permsoc", "bool", False, ""),
            "reactions.kostik_replies":
                ("reactions", "reactions_kostik", "json", False, "list"),
        }
        for pg_key, (cat, grp, typ, secret, widget) in cases.items():
            spec = pc.get_by_pg_key(pg_key)
            assert spec is not None, pg_key
            assert spec.category == cat, pg_key
            assert spec.group == grp, pg_key
            assert spec.type == typ, pg_key
            assert spec.secret is secret, pg_key
            assert spec.widget == widget, pg_key
            if cat == "models":
                assert spec.per_chat is False
            if cat == "reactions":
                assert spec.per_chat is True

    def test_kostik_replies_per_chat(self):
        from services import param_catalog as pc
        spec = pc.get_by_pg_key("reactions.kostik_replies")
        assert spec.per_chat is True
        assert spec.widget == "list"

    def test_provider_covered_keys(self):
        # Новые ключи — first-class каталог; UI покрывает их в блоках.
        assert "models.embedding_base_url" in JS
        assert "keys.embedding_api_key" in JS
        assert "models.openrouter_transcribe_display_name" in JS
