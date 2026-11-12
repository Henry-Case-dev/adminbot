"""SELF-DIAG-01 D2-24 (`SD1-D2-23`) — обязательная sensitivity при регистрации.

ТЗ §9.1: «Источник истины о секретных полях — конфигурационный каталог/secret
store с типами и флагом sensitivity: SECRET_VALUE, PROMPT_CONTENT,
NON_SECRET_CONFIG, PUBLIC_DIAGNOSTIC. Для нового провайдера метаданные
sensitivity обязательны при регистрации».

Проверяется наблюдаемый контракт:
  * новый параметр/провайдер без sensitivity не регистрируется (ошибка, а не
    тихий `secret=False`);
  * объявленный тип не может противоречить классу записи (ключ провайдера
    нельзя объявить несекретным);
  * каталог хранит тип для КАЖДОЙ записи, проекция читает его из каталога, а
    не выводит своё правило заново;
  * метки существующих записей и их per-chat/секретная семантика не меняются.
"""
import pytest

from services import output_projection as projection
from services import param_catalog as pc


def _provider_spec(**overrides) -> pc.ParamSpec:
    """Запись «нового провайдера» с типичной формой ключа."""
    fields = {
        "settings_field": "NEW_PROVIDER_API_KEY",
        "env_name": "NEW_PROVIDER_API_KEY",
        "category": pc.CATEGORY_KEYS,
        "title_ru": "Ключ нового провайдера",
        "type": "str",
    }
    fields.update(overrides)
    return pc.ParamSpec(**fields)


# ── Новый провайдер без sensitivity ───────────────────────────────────────

def test_new_provider_without_sensitivity_is_rejected():
    registry: dict[str, pc.ParamSpec] = {}
    with pytest.raises(pc.ParamSensitivityRequired) as excinfo:
        pc.register_param(_provider_spec(), registry=registry)
    assert "sensitivity is required at registration" in str(excinfo.value)
    assert registry == {}


def test_new_provider_unknown_sensitivity_is_rejected():
    registry: dict[str, pc.ParamSpec] = {}
    with pytest.raises(pc.ParamSensitivityError):
        pc.register_param(_provider_spec(sensitivity="TOP_SECRET"),
                          registry=registry)
    assert registry == {}


def test_new_provider_with_sensitivity_registers():
    registry: dict[str, pc.ParamSpec] = {}
    spec = _provider_spec(sensitivity=pc.SENSITIVITY_SECRET, secret=True)
    registered = pc.register_param(spec, registry=registry)
    stored = registry["NEW_PROVIDER_API_KEY"]
    assert registered is not None
    assert stored.sensitivity == pc.SENSITIVITY_SECRET
    assert stored.sensitivity_source == pc.SENSITIVITY_SOURCE_DECLARED
    assert stored.resolved_sensitivity == pc.SENSITIVITY_SECRET
    assert stored.is_protected is True
    assert stored.per_chat is False          # существующая семантика ключей


def test_provider_credential_cannot_be_declared_non_secret():
    """`keys.*` не может объявить себя NON_SECRET_CONFIG даже «явно»."""
    registry: dict[str, pc.ParamSpec] = {}
    with pytest.raises(pc.ParamSensitivityError):
        pc.register_param(
            _provider_spec(sensitivity=pc.SENSITIVITY_CONFIG, secret=False),
            registry=registry)
    # secret=True и «несекретный» тип — тем более противоречие.
    with pytest.raises(pc.ParamSensitivityError):
        pc.register_param(
            _provider_spec(sensitivity=pc.SENSITIVITY_CONFIG, secret=True),
            registry=registry)
    assert registry == {}


def test_new_non_secret_config_requires_explicit_class():
    """Несекретный параметр тоже регистрируется только с явным типом."""
    registry: dict[str, pc.ParamSpec] = {}
    spec = _provider_spec(
        settings_field="NEW_PROVIDER_MODEL",
        env_name="NEW_PROVIDER_MODEL",
        category=pc.CATEGORY_MODELS,
        sensitivity=pc.SENSITIVITY_CONFIG, secret=False)
    pc.register_param(spec, registry=registry)
    assert registry["NEW_PROVIDER_MODEL"].resolved_sensitivity \
        == pc.SENSITIVITY_CONFIG
    with pytest.raises(pc.ParamSensitivityRequired):
        pc.register_param(
            _provider_spec(settings_field="NEW_PROVIDER_REGION",
                           env_name="NEW_PROVIDER_REGION",
                           category=pc.CATEGORY_MODELS),
            registry=registry)


def test_duplicate_registration_is_still_rejected():
    registry: dict[str, pc.ParamSpec] = {}
    spec = _provider_spec(sensitivity=pc.SENSITIVITY_SECRET, secret=True)
    pc.register_param(spec, registry=registry)
    with pytest.raises(ValueError):
        pc.register_param(spec, registry=registry)
    pc.register_param(spec, registry=registry, replace=True)
    assert len(registry) == 1


# ── Каталог как источник истины ───────────────────────────────────────────

def test_every_catalog_entry_records_a_sensitivity_type():
    problems = pc.audit_sensitivity()
    assert problems == []
    assert pc.REGISTRY, "каталог пуст — проверка бессмысленна"
    for name, spec in pc.REGISTRY.items():
        assert spec.sensitivity in pc.SENSITIVITY_VALUES, name
        assert spec.sensitivity_source in (
            pc.SENSITIVITY_SOURCE_DECLARED, pc.SENSITIVITY_SOURCE_DERIVED), name
        assert spec.resolved_sensitivity == spec.sensitivity, name


def test_audit_detects_contradictory_metadata():
    """Аудит ловит запись, вернувшуюся к «тихому» несекретному состоянию."""
    good = _provider_spec(sensitivity=pc.SENSITIVITY_SECRET, secret=True)
    problems = pc.audit_sensitivity({"NEW_PROVIDER_API_KEY": good})
    assert problems == []
    silent = pc.ParamSpec("NEW_PROVIDER_API_KEY", "NEW_PROVIDER_API_KEY",
                          pc.CATEGORY_KEYS, "Ключ", "str", secret=False)
    problems = pc.audit_sensitivity({"NEW_PROVIDER_API_KEY": silent})
    assert any("sensitivity not recorded" in item for item in problems)


def test_projection_reads_catalog_instead_of_duplicating_the_rule():
    for spec in pc.REGISTRY.values():
        assert projection.sensitivity_of_pg_key(spec.pg_key) \
            == spec.resolved_sensitivity, spec.pg_key
    assert projection.SENSITIVITY_SECRET == pc.SENSITIVITY_SECRET
    assert projection.SENSITIVITY_PROMPT_CONTENT == pc.SENSITIVITY_PROMPT_CONTENT
    assert projection.SENSITIVITY_CONFIG == pc.SENSITIVITY_CONFIG
    assert projection.SENSITIVITY_PUBLIC == pc.SENSITIVITY_PUBLIC
    assert set(projection.SENSITIVITY_VALUES) == set(pc.SENSITIVITY_VALUES)


def test_existing_secret_and_prompt_classes_are_unchanged():
    """Поведение проекции на реальных ключах не изменилось."""
    assert projection.is_secret_pg_key("keys.llm_api_key") is True
    assert projection.is_secret_pg_key("postgres_password") is True
    assert projection.is_secret_pg_key("prompts.checkup_system_prompt") is False
    assert projection.sensitivity_of_pg_key(
        "prompts.checkup_system_prompt") == pc.SENSITIVITY_PROMPT_CONTENT
    assert projection.sensitivity_of_pg_key(
        "flags.checkup_enabled") == pc.SENSITIVITY_CONFIG
    assert projection.sensitivity_of_pg_key("unknown.key") \
        == pc.SENSITIVITY_PUBLIC
    # Секретные метки каталога и per-chat семантика не переписаны.
    assert pc.get_by_pg_key("keys.llm_api_key").secret is True
    assert pc.REGISTRY["CHECKUP_ENABLED"].per_chat is True
    assert pc.get_by_pg_key("keys.llm_api_key").per_chat is False
