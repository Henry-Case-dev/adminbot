"""EVOL-018 — контракты реестра: печати заводских ревизий + grep-аудит.

Постоянные проверки проекта (контракт ``plans/features/evol/arch/contracts.md``
§1.7, ``plans/current_task.md`` EVOL-018):

  1. печать каждого блока равна ``(метка, sha12(текст))`` — смена текста без
     бампа метки (или бамп без печати) роняет этот тест (fail-closed CI);
  2. набор фабричных текстов совпадает с ``FACTORY_SET_SHA256_12``;
  3. grep-аудит ``services/`` + ``handlers/``: prompt-константа вне реестра
     (``code_source``) или allowlist с непустой причиной — падение теста;
  4. фиктивная необъявленная константа ловится аудитом, объявленная через
     ``declare_prompt`` — нет.

Запуск в CI: ``pytest tests/test_evol018_prompt_audit.py``.

TEST-LIFECYCLE: CONTRACT owner=EVOL-018 (посев; полный аудит сборочных точек
LLM-вызовов — отдельная волна EVOL-018)
"""
from __future__ import annotations

import pathlib

import pytest

from services import prompt_registry as pr

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


def test_factory_seals_match_labels_and_text():
    """Печать = (метка, sha12(текст)) для каждого блока с текстом."""
    problems = pr.seal_integrity()
    assert problems == {}, (
        "нарушены печати заводских ревизий (текст правили без бампа метки "
        "или метку без печати): " + repr(problems))


def test_every_text_block_is_sealed():
    for spec in pr.all_blocks():
        text = pr.factory_text(spec.block_id)
        if not text:
            continue
        seal = pr.FACTORY_REVISION_SEALS.get(spec.block_id)
        assert seal is not None, f"{spec.block_id}: нет печати"
        assert seal[0] == pr.FACTORY_REVISION_LABELS.get(spec.block_id, ""), (
            f"{spec.block_id}: метка печати ≠ метке реестра")
        assert seal[1] == pr.sha12(text), f"{spec.block_id}: печать устарела"


def test_sealed_revision_identity_is_label_hash():
    """Идентичность заводской ревизии — ``fac:sha12(метки)`` (контракт §1.3)."""
    for block_id, (label, _sha) in pr.FACTORY_REVISION_SEALS.items():
        if not label:
            continue
        assert pr.sealed_factory_revision(block_id) == \
            pr.FACTORY_PREFIX + pr.sha12(label)
    assert pr.sealed_factory_revision("no.such.block") == ""


def test_factory_fingerprint_matches_declared_constant():
    assert pr.FACTORY_SET_SHA256_12 != "REPLACE_ME"
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12, (
        "набор фабричных текстов изменился без бампа FACTORY_SET_SHA256_12")


def test_grep_audit_finds_no_unregistered_prompt_constants():
    """Аудит сборки: prompt-константы services/+handlers/ вне реестра."""
    problems = pr.audit_unregistered_prompt_constants(ROOT)
    assert problems == [], (
        "обнаружены prompt-константы вне реестра (зарегистрируйте через "
        "declare_prompt или обоснуйте в PROMPT_AUDIT_ALLOWLIST): "
        + repr(problems))


def test_allowlist_entries_have_reasons():
    for name, reason in pr.PROMPT_AUDIT_ALLOWLIST.items():
        assert name.replace("_PROMPT", "").replace("_SYSTEM", "").isupper() \
            or name.isupper(), name
        assert isinstance(reason, str) and reason.strip(), (
            f"allowlist[{name!r}]: пустая причина недопустима (контракт §1.7)")


def test_audit_catches_fresh_unregistered_constant(tmp_path):
    """Фиктивная необъявленная константа роняет аудит (регрессия детектора)."""
    services = tmp_path / "services"
    services.mkdir()
    (services / "fresh_module.py").write_text(
        'SOMETHING_FRESH_PROMPT = """Новая постоянная инструкция,\n'
        "которую кто-то добавил мимо реестра.\n"
        '"""\n',
        encoding="utf-8")
    problems = pr.audit_unregistered_prompt_constants(tmp_path)
    assert any(p["attr"] == "SOMETHING_FRESH_PROMPT"
               and p["kind"] == "unregistered_prompt_constant"
               for p in problems), problems


def test_audit_passes_declared_constant(tmp_path):
    """Константа, объявленная через declare_prompt, аудиту не мешает."""
    services = tmp_path / "services"
    services.mkdir()
    (services / "declared_module.py").write_text(
        'DECLARED_PROMPT = """Зарегистрированная инструкция.\n"""\n',
        encoding="utf-8")
    spec = pr.declare_prompt(
        block_id="audit.declared",
        purpose="Тестовая декларация для проверки аудита.",
        family="internal", scope="code",
        code_source="services.declared_module.DECLARED_PROMPT",
        consumers=("tests/test_evol018_prompt_audit.py",),
        composition_point="internal/test", owner_lane="W2A-EVOL016",
        speech=False)
    try:
        problems = pr.audit_unregistered_prompt_constants(tmp_path,
                                                          blocks=[spec])
        assert problems == [], problems
    finally:
        pr._DECLARED.pop("audit.declared", None)


def test_audit_scans_only_services_and_handlers():
    """Границы аудита: tests/, web/, корень не сканируются (контракт §1.7)."""
    assert pr._AUDIT_SCAN_MODULES == ("services", "handlers")
    assert "prompt_migrations.py" in pr._AUDIT_SKIP_FILES


def test_declare_prompt_redeclaration_conflict():
    """Та же метка с другими данными → PromptDeclarationError (EVOL-018)."""
    spec = pr.block("summary.base.narrator")
    assert spec is not None
    with pytest.raises(pr.PromptDeclarationError):
        pr.declare_prompt(
            block_id=spec.block_id,
            purpose="ДРУГОЕ назначение — конфликт декларации.",
            family=spec.family, scope=spec.scope, pg_key=spec.pg_key,
            code_source=spec.code_source, consumers=spec.consumers,
            composition_point=spec.composition_point)
