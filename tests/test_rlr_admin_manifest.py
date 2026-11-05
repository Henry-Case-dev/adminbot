"""RLR-05-ADMIN — migration manifest снятого rephrasing-пути.

REMOVE-LEGACY-REPHRASING v2.0 §4/§5 (BGS-05/BGS-06)/§6.1–§6.4.

Проверяем наблюдаемый контракт, а не текст исходников:
* manifest покрывает все ключи/поведения снятого пути и классы закрыты;
* deprecated-ключ `SYSTEM2_DIRECT_ENABLED` при любом сыром значении
  (`false`/`0`/`null`/`true`) даёт эффективный флаг `False` — двойной Writer
  не активируется;
* ключи `removed`/`deprecated_compat` не имеют редактируемого контрола в
  каталоге, но остаются читаемыми (значения/ревизии не удаляются);
* технические guard'ы остаются рабочими (их не удаляют по слову `guard`).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from config import settings as settings_module
from config.settings import Settings, settings
from services import evidence_policy, mca_gates, outgoing_guard
from services import param_catalog as pc


REQUIRED_KEYS = {
    "SYSTEM2_DIRECT_ENABLED",
    "prompts.direct_chat_synthesizer_system_prompt",
    "SYSTEM2_VALIDATOR_LOOP_ENABLED",
    "MCA_POSTPROCESS_FORM_GUARD_ENABLED",
    "MCA_NUMERIC_CLAIM_GUARD_ENABLED",
    "MCA_RESPONSE_FRESHNESS_GUARD_ENABLED",
    "EVIDENCE_EGRESS_GUARD_ENABLED",
    "EVIDENCE_ROUTING_POLICY_ENABLED",
}

REQUIRED_BEHAVIOURS = {
    "system2_direct_two_call",
    "duplicate_text_regeneration",
    "form_freeform_retry",
    "numeric_freeform_postedit",
    "evidence_egress_rewrite_drop",
    "public_speech_cut",
    "format_retry",
    "cliche_metatext_retry",
}

#: env-only ключи, которые читаются не через Settings-атрибут.
_ENV_MODULE_CONSTANTS = {
    "EVIDENCE_EGRESS_GUARD_ENABLED": (evidence_policy, "EGRESS_GATE_ENV"),
    "EVIDENCE_ROUTING_POLICY_ENABLED": (evidence_policy, "POLICY_GATE_ENV"),
}

_MANIFEST_PATH = (Path(__file__).resolve().parents[1] / "plans" / "features"
                  / "remove-legacy-rephrasing" / "migration-manifest.json")


def _manifest() -> dict:
    return pc.legacy_migration_manifest()


def _editable_pg_keys() -> set[str]:
    """Ключи, которые админка реально показывает как редактируемые."""
    return {spec.pg_key for spec in pc.REGISTRY.values()
            if spec.category is not None and not spec.hidden}


def test_manifest_covers_all_removed_path_keys_and_behaviours():
    manifest = _manifest()
    keys = {row["name"] for row in manifest["keys"]}
    behaviours = {row["name"] for row in manifest["behaviours"]}
    assert REQUIRED_KEYS <= keys
    assert REQUIRED_BEHAVIOURS <= behaviours
    assert not (keys & behaviours)


def test_manifest_rows_are_classified_and_explained():
    manifest = _manifest()
    assert tuple(manifest["classes"]) == pc.MIGRATION_CLASSES
    for row in manifest["keys"] + manifest["behaviours"]:
        assert row["migration_class"] in pc.MIGRATION_CLASSES
        assert row["kind"] in {"catalog", "env", "behaviour"}
        # Каждая запись имеет реального потребителя либо явное «нет» +
        # человеческую подпись, что покажет админка.
        assert row["consumer"].strip()
        assert row["ui"].strip()


def test_catalog_rows_exist_readable_and_carry_classification():
    for row in _manifest()["keys"]:
        if row["kind"] != "catalog":
            continue
        spec = pc.REGISTRY[row["name"]]
        assert spec.category is not None
        assert spec.migration_class == row["migration_class"]
        assert spec.migration_consumer == row["consumer"]
        assert spec.migration_ui == row["ui"]
        # Значение читаемо по PG-ключу даже у скрытой записи.
        assert pc.get_by_pg_key(spec.pg_key) is not None


def test_no_catalog_entry_has_unexplained_migration_class():
    manifest_names = {row["name"] for row in _manifest()["keys"]
                      if row["kind"] == "catalog"}
    for name, spec in pc.REGISTRY.items():
        if not spec.migration_class:
            continue
        assert name in manifest_names, name
        assert spec.migration_class in pc.MIGRATION_CLASSES
        assert spec.migration_consumer.strip()
        assert spec.migration_ui.strip()


def test_env_rows_are_readable_without_error():
    for row in _manifest()["keys"]:
        if row["kind"] != "env":
            continue
        name = row["name"]
        if name in _ENV_MODULE_CONSTANTS:
            module, const = _ENV_MODULE_CONSTANTS[name]
            assert getattr(module, const) == name
            continue
        assert hasattr(Settings, name), name
        # getattr не бросает и не требует БД/env-значения.
        assert getattr(settings, name) is not None


@pytest.mark.parametrize(
    "raw",
    [False, 0, None, "", "0", "false", "off", "no", True, 1, "true", "on"],
)
def test_deprecated_key_resolves_off_for_every_raw_value(raw):
    """`false`/`0`/`null` НЕ включают legacy; `true` тоже (ключ deprecated)."""
    assert settings_module.resolve_legacy_rephrasing_env_flag(
        "SYSTEM2_DIRECT_ENABLED", raw) is False


def test_legacy_gate_expression_resolves_off():
    """Ровно выражение гейта legacy-ветки direct_chat_service.py."""
    gate = bool(getattr(settings, "SYSTEM2_DIRECT_ENABLED", True))
    assert gate is False


def _load_settings_module(monkeypatch, raw_env: str):
    """Изолированная загрузка config.settings под заданным env.

    Не трогает глобальный модуль/класс, который autouse-фикстура conftest
    принудительно патчит в False: проверяем именно резолв env → флаг.
    """
    monkeypatch.setenv("SYSTEM2_DIRECT_ENABLED", raw_env)
    name = f"_rlr_settings_probe_{raw_env}"
    spec = importlib.util.spec_from_file_location(
        name, Path(settings_module.__file__))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module       # dataclass ищет модуль в sys.modules
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(name, None)


@pytest.mark.parametrize("raw_env", ["true", "1"])
def test_env_cannot_enable_legacy_gate_even_without_autouse_patch(
        monkeypatch, raw_env):
    """Без autouse-патча: env=true/1 всё равно даёт реальный гейт False."""
    module = _load_settings_module(monkeypatch, raw_env)
    assert module.Settings.SYSTEM2_DIRECT_ENABLED is False
    assert bool(getattr(module.settings, "SYSTEM2_DIRECT_ENABLED", True)) \
        is False


def test_synthesizer_prompt_is_hidden_but_readable_and_untouched():
    name = "prompts.direct_chat_synthesizer_system_prompt"
    spec = pc.REGISTRY[name]
    # Висячая карточка убрана из редактируемого Prompt Library.
    assert spec.hidden is True
    assert spec.migration_class == pc.MIGRATION_DEPRECATED_COMPAT
    assert name not in _editable_pg_keys()
    # Значение/история читаемы: запись осталась в реестре и в PG-сид-списке
    # (prompts — PG-only, ConfigCache сидит их код-каноном).
    assert pc.get_by_pg_key(name) is spec
    assert name in {s.pg_key for s in pc.iter_pg_only()}
    # Текст промпта и его источник не переписаны этим срезом.
    assert spec.code_source == (
        "services.chat_prompts.DIRECT_SYNTHESIZER_SYSTEM_PROMPT")
    module_name, attr = spec.code_source.rsplit(".", 1)
    prompt_text = getattr(importlib.import_module(module_name), attr)
    assert isinstance(prompt_text, str) and prompt_text.strip()
    assert spec.title_ru == "Синтезатор прямого чата (Логика)"
    # Вербализатор читает живой L2 — его не скрываем и не классифицируем.
    verbalizer = pc.REGISTRY["prompts.direct_chat_verbalizer_system_prompt"]
    assert verbalizer.hidden is False
    assert verbalizer.migration_class == ""


def test_reroll_behaviours_are_reported_as_removed():
    """RLR-04 снял оба reroll'а: манифест говорит «нет», а не «ещё активен»."""
    rows = {row["name"]: row for row in _manifest()["behaviours"]}
    for name in ("duplicate_text_regeneration", "numeric_freeform_postedit"):
        row = rows[name]
        # Класс — целевое состояние (§4/R-04/R-05) и оно ДОСТИГНУТО.
        assert row["migration_class"] == pc.MIGRATION_REMOVED
        assert "RLR-04" in (row["consumer"] + row["note"]
                            + row["current_state"])
        assert "active" not in row["current_state"].lower()
        assert "нет" in row["consumer"].lower()
        assert "нет переключателя" == row["ui"]
    # Свободная речь больше не правится; гард остался только у lore-сборки.
    assert "lore" in rows["numeric_freeform_postedit"]["consumer"].lower()


def test_removed_and_deprecated_keys_have_no_editable_control():
    editable = _editable_pg_keys()
    hidden_classes = {pc.MIGRATION_REMOVED, pc.MIGRATION_DEPRECATED_COMPAT}
    for row in _manifest()["keys"]:
        if row["migration_class"] not in hidden_classes:
            continue
        spec = pc.REGISTRY.get(row["name"])
        # Либо записи нет в каталоге вовсе (env-only), либо она hidden и её
        # значение не редактируется через UI/API.
        assert spec is None or spec.hidden, row["name"]
        if spec is not None:
            assert spec.pg_key not in editable
            assert pc.get_by_pg_key(spec.pg_key) is spec
    assert "flags.system2_direct_enabled" not in editable


def test_retained_catalog_guard_is_editable_with_honest_label():
    spec = pc.REGISTRY["MCA_POSTPROCESS_FORM_GUARD_ENABLED"]
    assert spec.hidden is False
    assert spec.migration_class == pc.MIGRATION_RETAINED_EXPLICIT
    assert "явном редактировании" in spec.description.lower()
    assert "не переписывается" in spec.description.lower()


def test_technical_guards_remain_present_and_functional(monkeypatch):
    # Техническая очистка машинных маркеров (не речевая цензура).
    cleaned = outgoing_guard.sanitize_outgoing(
        "<thought>внутреннее</thought> привет fact:12 msg:7")
    assert "<thought>" not in cleaned and "fact:12" not in cleaned
    assert "msg:7" not in cleaned
    assert "привет" in cleaned

    # Egress/SSRF guard.
    monkeypatch.setattr(Settings, "MCA_EGRESS_GUARD_ENABLED", False)
    assert mca_gates.egress_guard_enabled() is False
    monkeypatch.setattr(Settings, "MCA_EGRESS_GUARD_ENABLED", True)
    assert mca_gates.egress_guard_enabled() is True

    # Идемпотентность доставки инструмента.
    monkeypatch.setattr(Settings, "MCA_TOOL_DELIVERY_GUARD_ENABLED", False)
    assert mca_gates.tool_delivery_guard_enabled() is False
    monkeypatch.setattr(Settings, "MCA_TOOL_DELIVERY_GUARD_ENABLED", True)
    assert mca_gates.tool_delivery_guard_enabled() is True

    # Защита от повторной отправки одного события.
    monkeypatch.setattr(Settings, "MCA_SEND_RECHECK_ENABLED", False)
    assert mca_gates.send_recheck_enabled() is False

    # Форм-гард жив и управляем, но относится только к явной трансформации.
    monkeypatch.setattr(
        Settings, "MCA_POSTPROCESS_FORM_GUARD_ENABLED", False)
    assert mca_gates.postprocess_form_guard_enabled() is False
    monkeypatch.setattr(
        Settings, "MCA_POSTPROCESS_FORM_GUARD_ENABLED", True)
    assert mca_gates.postprocess_form_guard_enabled() is True

    # Лимит детектора клише реально читается (не мёртвая ручка).
    from services import anticliche_cache
    assert 1 <= anticliche_cache.max_patterns() <= 1000

    # Egress-наблюдение включается/выключается без изменения текста.
    monkeypatch.setattr(evidence_policy, "EGRESS_ENABLED_OVERRIDE", False)
    assert evidence_policy.egress_guard_enabled() is False
    monkeypatch.setattr(evidence_policy, "EGRESS_ENABLED_OVERRIDE", True)
    assert evidence_policy.egress_guard_enabled() is True


def test_json_manifest_matches_code_source():
    assert _MANIFEST_PATH.is_file(), _MANIFEST_PATH
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    code = _manifest()
    assert data["schema"] == code["schema"]
    assert data["keys"] == code["keys"]
    assert data["behaviours"] == code["behaviours"]
    assert data["classes"] == code["classes"]
    assert data["source"] == (
        "plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md")
