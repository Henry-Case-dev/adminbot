"""EXTRA (extra-cover-style-pipeline, round1028, ADR-1028-4 D3/D4;
spec §3.2/§3.3/§3.9, tasks T-4116…T-4123) — Cover Style pipeline helpers.

Проверяем:
  * раздельные model slots (base vs style) — §32;
  * per-style override (§34); kill-switch (§55/OFF);
  * gate §38 (модель без edit → API не вызывается);
  * normalizer semantics (§23): инструкция профиля как есть, без special-case;
  * pipeline modes (§54); per-chat выбор (DC-5); connection validation (§73).
"""
import types

import pytest

from services import cover_style_pipeline as csp


def patch_slot(monkeypatch, *, base_url="", model="", api_key="",
               enabled=True, hot_values=None):
    """Подменить `settings`/`hot` в модуле (Settings — frozen dataclass)."""
    fake = types.SimpleNamespace(
        IMAGE_STYLE_BASE_URL=base_url,
        IMAGE_STYLE_MODEL=model,
        IMAGE_STYLE_API_KEY=api_key,
        IMAGE_BASE_URL="https://base/v1",
        IMAGE_MODEL="flux",
        COVER_STYLES_ENABLED=enabled)
    monkeypatch.setattr(csp, "settings", fake)
    values = hot_values or {}

    def _hot_get(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr(csp.hot, "get", _hot_get)


class TestSlots:
    def test_style_slot_separate_from_base(self, monkeypatch):
        patch_slot(monkeypatch, base_url="https://nano.example/v1",
                   model="qwen-image")
        slot = csp.resolve_style_slot()
        assert slot["base_url"] == "https://nano.example/v1"
        assert slot["model"] == "qwen-image"
        assert slot["configured"] is True
        assert slot["provider"] == "nano.example"
        # базовый слот не затронут (отдельные ключи)
        assert csp.KEY_BASE_URL != csp.KEY_STYLE_BASE_URL
        assert csp.KEY_MODEL != csp.KEY_STYLE_MODEL

    def test_per_style_override(self, monkeypatch):
        """ASAP-3.2 (§103–§105, D14): connection_id — настоящий FK к Image
        Connection; base_url берётся из ЗАПИСИ подключения (не raw URL из
        профиля). Без записи — честный fallback на default (custom_unresolved)."""
        patch_slot(monkeypatch, base_url="https://default/v1",
                   model="default-model")
        profile = {"model_mode": csp.MODEL_MODE_CUSTOM,
                   "connection_id": "csc_custom",
                   "model_id": "custom-model"}
        connection = {"connection_id": "csc_custom",
                      "base_url": "https://custom/v1", "api_key": "k"}
        slot = csp.resolve_style_slot(profile=profile, connection=connection)
        assert slot["base_url"] == "https://custom/v1"
        assert slot["model"] == "custom-model"
        assert slot["connection_id"] == "csc_custom"
        assert slot["custom_unresolved"] is False
        # FK без записи → fallback default, raw URL НЕ подставляется
        slot2 = csp.resolve_style_slot(profile=profile)
        assert slot2["base_url"] == "https://default/v1"
        assert slot2["connection_id"] == "default"
        assert slot2["custom_unresolved"] is True

    def test_default_mode_ignores_override(self, monkeypatch):
        patch_slot(monkeypatch, base_url="https://default/v1",
                   model="default-model")
        profile = {"model_mode": csp.MODEL_MODE_DEFAULT,
                   "connection_id": "https://X", "model_id": "Y"}
        slot = csp.resolve_style_slot(profile=profile)
        assert slot["base_url"] == "https://default/v1"


class TestKillSwitch:
    def test_enabled_default(self, monkeypatch):
        patch_slot(monkeypatch, enabled=True)
        assert csp.cover_styles_enabled() is True

    def test_off_disables_style_stage(self, monkeypatch):
        patch_slot(monkeypatch, enabled=False)
        assert csp.cover_styles_enabled() is False
        assert csp.uses_style_stage({"pipeline_mode": "generate_then_edit"}) \
            is False


class TestEditGate:
    def test_no_edit_blocks(self, monkeypatch):
        from services import image_capabilities as cap
        caps = cap.conservative_unknown()
        caps.image_edit = cap.FALSE
        allowed, msg = csp.check_edit_allowed(capabilities=caps)
        assert allowed is False
        assert msg == csp.NO_EDIT_MESSAGE
        assert "не умеет редактировать" in msg

    def test_edit_yes_allows(self):
        from services import image_capabilities as cap
        caps = cap.conservative_unknown()
        caps.image_edit = cap.TRUE
        allowed, msg = csp.check_edit_allowed(capabilities=caps)
        assert allowed is True
        assert msg == ""

    def test_unknown_does_not_block(self):
        # §58: unknown не запрещает (профиль сохраняется), блок только FALSE.
        from services import image_capabilities as cap
        caps = cap.conservative_unknown()   # image_edit=unknown
        allowed, _ = csp.check_edit_allowed(capabilities=caps)
        assert allowed is True


class TestNormalizer:
    def test_instruction_as_is(self):
        # §23: инструкция профиля используется как есть; runtime не добавляет
        # special-case.
        profile = {"instruction": "приведи к правилам серии"}
        assert csp.normalizer_instruction(profile) == \
            "приведи к правилам серии"

    def test_no_hardcoded_brand(self):
        import inspect
        src = inspect.getsource(csp)
        assert "medved_press" not in src.lower()


class TestModes:
    def test_pipeline_modes(self):
        assert csp.pipeline_mode(None) == "none"
        assert csp.pipeline_mode({"pipeline_mode": "edit_only"}) == "edit_only"
        assert csp.uses_base_generation(None) is True
        assert csp.uses_base_generation({"pipeline_mode": "generate_only"}) \
            is True
        assert csp.uses_base_generation({"pipeline_mode": "edit_only"}) is False
        assert csp.uses_style_stage({"pipeline_mode": "edit_only"}) is True
        assert csp.uses_style_stage({"pipeline_mode": "generate_only"}) is False

    def test_no_style_profile_skips(self):
        # §55: `Без дополнительного стиля` — не профиль.
        assert csp.uses_style_stage(None) is False


class TestConnectionValidation:
    def test_unconfigured(self, monkeypatch):
        patch_slot(monkeypatch, base_url="", model="")
        status = csp.connection_status()
        assert status["configured"] is False
        assert status["connected"] is False
        assert "не настроены" in status["message"]

    def test_configured_no_key(self, monkeypatch):
        patch_slot(monkeypatch, base_url="https://x/v1", model="m")
        status = csp.connection_status()
        assert status["configured"] is True
        assert status["connected"] is False
        assert status["message"] == "API ключ не настроен"

    def test_key_not_leaked(self, monkeypatch):
        patch_slot(monkeypatch, base_url="https://x/v1", model="m",
                   api_key="sk-secret-123")
        status = csp.connection_status()
        assert "sk-secret-123" not in str(status)
        assert status["api_key_set"] is True
