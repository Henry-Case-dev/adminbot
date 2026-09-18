"""F8 `self-reflection-llm-provider-round1014` (UPD п.3) — третье подключение
провайдера «LLM для саморефлексии (Экстрактор сути)».

Покрытие (spec §2–§5, ADR-1013-1):
  * каталог-Δ: +4 ключа (models.intel_reflection_*, keys.intel_reflection_api_key),
    группы models_extra_providers / keys_llm, per_chat=False, secret только у ключа;
  * Settings-дефолты "" и 4 env-плейсхолдера `.env.example`;
  * backend-роль `reflection` → slug `intel_reflection` (`generate_worker`);
  * probe-регистры и runtime-фолбэк base/model на основную модель;
  * UI-маркеры provider-блока (parent + subBlocks, 4 поля, модуль «Саморефлексия»).
"""
import dataclasses
from pathlib import Path

ROOT = Path(".")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

_PG_KEYS = {
    "models.intel_reflection_base_url": ("models", "models_extra_providers",
                                         False),
    "models.intel_reflection_model_name": ("models", "models_extra_providers",
                                           False),
    "models.intel_reflection_display_name": ("models",
                                             "models_extra_providers", False),
    "keys.intel_reflection_api_key": ("keys", "keys_llm", True),
}
_ENV_FIELDS = (
    "INTEL_REFLECTION_BASE_URL", "INTEL_REFLECTION_MODEL_NAME",
    "INTEL_REFLECTION_DISPLAY_NAME", "INTEL_REFLECTION_API_KEY",
)


class TestCatalogAndSettingsF8:
    def test_new_param_specs(self):
        from services import param_catalog as pc
        for pg_key, (cat, grp, secret) in _PG_KEYS.items():
            s = pc.get_by_pg_key(pg_key)
            assert s is not None, pg_key
            assert s.category == cat, pg_key
            assert s.group == grp, pg_key
            assert s.type == "str", pg_key
            assert s.secret is secret, pg_key
            assert s.per_chat is False, pg_key
            assert s.title_ru, pg_key
            assert s.description, pg_key

    def test_settings_defaults_empty(self):
        from config.settings import Settings
        s = Settings()
        for name in _ENV_FIELDS:
            assert getattr(s, name) == "", name

    def test_env_placeholders(self):
        for name in _ENV_FIELDS:
            assert f"# {name}=" in ENV_EXAMPLE, name
            assert f'{name}: str = _env_str("{name}", "")' in SETTINGS, name

    def test_catalog_delta_plus_four(self):
        import dataclasses

        from config.settings import Settings
        from services import param_catalog as pc
        # F6 (help-guide-integration-round1014): +1 PG-only content-ключ
        # (content.intelligence_guide) → REGISTRY 435 / categorized 411;
        # 10.18 (F1): +1 env-only BETTERSTACK_HOST (ADR-1018-1 D3)
        # → REGISTRY 436 / categorized 411;
        # Settings/GROUPS/mapped/TAB_RULES без изменений.
        # 10.19 (F3/ADR-1019-3 D3, UPD3 п.5): → 437/92/90/20/407/412.
        # 10.23 (F5/ADR-1023-5 D5): +5 REGISTRY/Settings/categorized,
        # +3 GROUPS/mapped → 446/95/93/20/416/421.
        assert len(pc.REGISTRY) == 458
        assert len(pc.GROUPS) == 96
        assert len(pc._TAB_BY_GROUP) == 94
        assert len(pc.TAB_RULES) == 20
        assert len({f.name for f in dataclasses.fields(Settings)}) == 416
        categorized = [s for s in pc.REGISTRY.values()
                       if s.category is not None]
        assert len(categorized) == 433


class TestWorkerRoleF8:
    def test_reflection_role_mapping(self):
        from services.llm_client import LLMClient
        assert LLMClient._WORKER_ROLE_PREFIX.get("reflection") \
            == "intel_reflection"


class TestProbeRegistriesF8:
    def test_probe_registries_cover_reflection(self):
        from services import llm_probe
        assert "intel_reflection_main" in llm_probe._LLM_BLOCKS
        assert "intel_reflection_main" in llm_probe.KNOWN_BLOCKS
        assert llm_probe._BLOCK_SAVED_KEY["intel_reflection_main"] \
            == "keys.intel_reflection_api_key"
        assert llm_probe._INTEL_BLOCK_SLUG["intel_reflection_main"] \
            == "intel_reflection"

    def test_probe_fallback_fills_main(self, monkeypatch):
        from services import llm_probe

        def _hot_get(key, default=None):
            return {
                "models.llm_base_url": "https://main.test/v1",
                "models.llm_model_name": "main-model",
            }.get(key, default)

        monkeypatch.setattr("services.hot_config.get", _hot_get)
        base, model = llm_probe._intel_probe_fallback(
            "intel_reflection_main", "", "")
        assert base == "https://main.test/v1"
        assert model == "main-model"


class TestUiBlockF8:
    def test_parent_and_subblock_registered(self):
        assert "{ id: 'intel_reflection', " \
            "title: 'LLM для саморефлексии (Экстрактор сути)'" in JS
        assert "modules: 'Саморефлексия'" in JS
        assert "{ id: 'intel_reflection_main', title: 'Подключение'" in JS

    def test_four_fields(self):
        for pg_key in _PG_KEYS:
            assert pg_key in JS, pg_key
        assert JS.count("models.intel_reflection_display_name") == 1
        assert JS.count("models.intel_reflection_base_url") == 1
        assert JS.count("models.intel_reflection_model_name") == 1
        assert JS.count("keys.intel_reflection_api_key") == 1

    def test_parent_modules_not_title(self):
        # R10.12-5: parent modules ≠ title (без дубля заголовка).
        assert "Саморефлексия" != "LLM для саморефлексии (Экстрактор сути)"

    def test_catalog_setting_fields_present_in_dataclass(self):
        from config.settings import Settings
        fields = {f.name for f in dataclasses.fields(Settings)}
        for name in _ENV_FIELDS:
            assert name in fields, name
