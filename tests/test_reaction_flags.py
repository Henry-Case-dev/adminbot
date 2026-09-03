"""Эпик 04.09.2026 (Часть 3, T-24) — реакции-тумблеры: дефолты false,
наличие в REGISTRY+Settings, поведение гейтов (vasya/kucha/mimic/alan-mimic
детально в test_vasya/test_slavik_handlers/test_common), славячий mimic
НЕ зависит от flags.mimic_enabled (3.4.3, FR-20).
"""
import dataclasses

import pytest
from unittest.mock import MagicMock

from config.settings import Settings, settings
from services import hot_config as hot
from services.param_catalog import REGISTRY, get as catalog_get

TOGGLES = {
    "VASYA_ENABLED": "reactions.vasya_enabled",
    "KUCHA_ENABLED": "reactions.kucha_enabled",
    "MIMIC_ENABLED": "flags.mimic_enabled",
    "ALAN_MIMIC_ENABLED": "reactions.alan_mimic_enabled",
}


class TestToggleDefaults:
    """FR-18/NFR-3: все 4 тумблера default false (Settings + REGISTRY)."""

    def test_settings_defaults_false(self):
        st = Settings()
        for field, _pg_key in TOGGLES.items():
            assert getattr(st, field) is False, field

    def test_registry_records_bool_not_secret(self):
        for field, pg_key in TOGGLES.items():
            spec = catalog_get(field)
            assert spec is not None, field
            assert spec.type == "bool"
            assert spec.secret is False
            assert spec.pg_key == pg_key
            assert spec.title_ru.strip()
            assert spec.description.strip()
            assert spec.group.strip()

    def test_hot_get_fallback_default_false(self):
        # без кэша hot.get отдаёт settings-дефолт (False для всех тумблеров)
        for field, pg_key in TOGGLES.items():
            assert hot.get(pg_key, getattr(settings, field)) is False, pg_key

    def test_settings_fields_covered_by_registry(self):
        fields = {f.name for f in dataclasses.fields(Settings)}
        assert TOGGLES.keys() <= fields


class TestSlavikMimicIndependent:
    """FR-20/AC-3.4: славячий mimic в handlers/slavik.py НЕ читает
    flags.mimic_enabled — управляется limits.slavik_mimic_min_words/cooldown."""

    def test_slavik_mimic_trigger_with_global_flag_off(self, monkeypatch):
        import handlers.slavik as slavik_module

        st = MagicMock()
        st.SLAVIK_USER_ID = 479167456
        st.SLAVIK_MIMIC_MIN_WORDS = 5
        st.SLAVIK_MIMIC_COOLDOWN = 0.0
        st.MIMIC_FORWARDS_ENABLED = False
        st.KUCHA_ENABLED = False
        monkeypatch.setattr(slavik_module, "settings", st)
        slavik_module._slavik_mimic_last_sent.clear()
        try:
            # флаг мимикрии common выключен (дефолт) — славячий mimic жив
            assert hot.get("flags.mimic_enabled", settings.MIMIC_ENABLED) is False
            result = slavik_module._slavik_mimic_should_trigger(
                -100123, "один два три четыре пять шесть", is_forwarded=False)
            assert result is True
        finally:
            slavik_module._slavik_mimic_last_sent.clear()


class TestCatalogRenameLeha:
    """AC-3.6: отображаемые тексты «Леха», код-идентификаторы сохранены."""

    def test_alan_display_titles_renamed(self):
        assert catalog_get("ALAN_USER_ID").title_ru == "Telegram ID Лехи"
        assert catalog_get("ALAN_USERNAME").title_ru == "Юзернейм Лехи"
        assert catalog_get("ALAN_GREETING_DIR").title_ru == "Папка приветствий Лехи"
        assert "Алан" not in catalog_get("ALAN_USER_ID").description

    def test_pg_keys_and_env_names_untouched(self):
        assert catalog_get("ALAN_USER_ID").pg_key == "reactions.alan_user_id"
        assert catalog_get("ALAN_USER_ID").env_name == "ALAN_USER_ID"
        assert catalog_get("ALAN_MIMIC_ENABLED").pg_key == "reactions.alan_mimic_enabled"
        assert catalog_get("ALAN_MIMIC_ENABLED").env_name == "ALAN_MIMIC_ENABLED"

    def test_group_titles_renamed(self):
        from services.param_catalog import GROUPS
        groups = {g.id: g for g in GROUPS}
        assert groups["limits_persons"].title_ru == "Персонажи: Леха и Костик"
        assert groups["reactions_alan"].title_ru == "Леха"

    def test_no_alan_in_display_texts(self):
        from services.param_catalog import GROUPS
        for spec in REGISTRY.values():
            if spec.category is None:
                continue
            assert "Алан" not in spec.title_ru, spec.pg_key
            assert "Алан" not in spec.description, spec.pg_key
        for g in GROUPS:
            assert "Алан" not in g.title_ru
            assert "Алан" not in g.description
