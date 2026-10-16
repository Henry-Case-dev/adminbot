"""SOUL-1 / W1 — полнота реестра речевых инструкций (SOUL-AMD.3.1–3.4).

Доказывается:
  * у каждого каталог-ключa ``prompts.*`` есть стабильный Registry ID и
    человеческие метаданные (назначение, потребители, точка композиции);
  * ни один ``prompts.*``-литерал рантайма не остался вне каталога (аудит
    §1: ``prompts.direct_l1_planner_system_prompt`` был «читается, но
    невидим» — этот класс дефектов закрыт тестом);
  * фабричные ревизии версионированы, отпечаток набора совпадает с
    объявленным (правка любого канона без осознанного бампа ломает тест —
    guard «нет неучтённой речевой инструкции»);
  * управляемые пользовательские шаблоны (включая жёсткую фразу отказа
    image-generation) зарегистрированы как Factory Default-сообщения;
  * effective-значение показывает источник/ревизию/отличие от заводского.

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.3.1/3.2/3.4 (soul-1, слайс W1)
"""
from __future__ import annotations

import pathlib
import re

import pytest

from services import param_catalog as pc
from services import prompt_registry as pr
from services import hot_config as hot

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Ключи с легально пустым заводским текстом (пусто = «не выбрано»).
EMPTY_FACTORY_OK = frozenset({"summary.cover.style_id"})

_PG_LITERAL_RE = re.compile(r"[\"'](prompts\.[a-z0-9_]+)[\"']")


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


def test_registry_ids_unique_and_fields_filled():
    ids = [b.block_id for b in pr.all_blocks()]
    assert len(ids) == len(set(ids)), "дубли Registry ID"
    assert all(not i.startswith("unregistered:") for i in ids), (
        "есть PG-ключи каталога без метаданных реестра")
    for spec in pr.all_blocks():
        assert spec.purpose.strip(), spec.block_id
        assert spec.family.strip(), spec.block_id
        assert spec.consumers, spec.block_id
        assert spec.composition_point.strip(), spec.block_id
        assert spec.scope in ("global", "global_chat", "code"), spec.block_id
        assert spec.owner_lane.startswith("W"), spec.block_id
        assert spec.migration.split(":")[0] in (
            "factory", "managed_message", "registered_pending"), spec.block_id


def test_every_catalog_prompt_key_has_registry_block():
    keys = [s.pg_key for s in pc.REGISTRY.values()
            if s.category == pc.CATEGORY_PROMPTS]
    assert keys, "каталог промптов пуст — тест бессмыслен"
    missing = [key for key in keys
               if pr.by_pg_key(key) is None
               or pr.by_pg_key(key).block_id.startswith("unregistered:")]
    assert missing == [], f"PG-ключи без Registry ID: {missing}"
    assert pr.unregistered_catalog_keys() == ()


def test_every_runtime_prompt_literal_is_a_catalog_key():
    """Ни один читаемый ``prompts.*``-ключ не остаётся «невидимым»."""
    seen: dict[str, set[str]] = {}
    for path in sorted((ROOT / "services").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _PG_LITERAL_RE.finditer(text):
            seen.setdefault(match.group(1), set()).add(path.name)
    assert seen, "литералы prompts.* не найдены — сломан сканер"
    invisible = {key: files for key, files in seen.items()
                 if pc.get_by_pg_key(key) is None}
    assert invisible == {}, (
        f"читаемые, но нередактируемые (вне каталога) ключи: {invisible}")


def test_factory_fingerprint_matches_declared_constant():
    """Guard: любая правка канона без бампа реестра ломает этот тест.

    Если тест упал — вы правили речевую инструкцию: обновите фабричную метку
    в ``FACTORY_REVISION_LABELS`` и ``FACTORY_SET_SHA256_12`` осознанно
    (SOUL-AMD.3.2: «никаких речевых инструкций, видимых лишь в Python»).
    """
    assert pr.FACTORY_SET_SHA256_12 != "REPLACE_ME", "отпечаток не объявлен"
    assert pr.factory_set_fingerprint() == pr.FACTORY_SET_SHA256_12, (
        "набор фабричных текстов изменился без бампа FACTORY_SET_SHA256_12")


def test_all_blocks_have_factory_text_or_explicit_empty():
    empty = {b.block_id for b in pr.all_blocks()
             if not pr.factory_text(b.block_id)}
    assert empty <= EMPTY_FACTORY_OK, (
        f"блоки без резолвящегося фабричного текста: {sorted(empty)}")


def test_legacy_persona_canons_are_registered_with_revision_labels():
    legacy = {b.block_id: b for b in pr.legacy_persona_blocks()}
    for block_id in (
            "direct.base.tool_phase", "direct.base.l2_writer",
            "factcheck.base.single", "factcheck.base.verbalizer",
            "summary.base.single", "summary.base.narrator",
            "search.base.system", "checkup.base.system",
            "youtube.base.system", "youtube.base.video", "web.base.system",
            "verbilizer.mode.deep_research", "message.smartmodule.chat_persona"):
        assert block_id in legacy, f"{block_id} не помечен legacy_persona"
        assert pr.legacy_persona_present(pr.factory_text(block_id)), block_id
    for block_id in legacy:
        assert block_id in pr.FACTORY_REVISION_LABELS, (
            f"{block_id}: фабричная редакция без версии-метки")
        assert pr.factory_revision(block_id).startswith(pr.FACTORY_PREFIX)


def test_managed_user_facing_templates_registered():
    fallback = pr.block("message.image_generation_fallback")
    assert fallback is not None
    assert fallback.speech is True
    assert fallback.migration == "managed_message"
    assert fallback.ui == "catalog_pending"      # ключ каталога добавит W10
    assert "IMAGE_GENERATION_FALLBACK_PHRASE" in (fallback.code_source or "")
    assert pr.factory_text(fallback.block_id).strip(), "фабричный текст пуст"
    # Семейство шаблонных фраз smartmodule — тоже управляемые сообщения.
    phrases = pr.block("message.smartmodule.phrases")
    assert phrases is not None and phrases.code_members == "*"
    module = __import__("services.smartmodule_phrases", fromlist=["*"])
    assert "CHAT_STYLE_UNKNOWN_PHRASE=" in pr.factory_text(phrases.block_id)
    del module


def test_checkup_fallback_notice_is_registered_as_managed_message():
    """fix-pass review-w1 SMALL-4a: user-audible фраза без регистрации видна.

    `CHECKUP_FALLBACK_NOTICE` (с «поиздевайся …») добавляется в system-сообщение
    чек-апа — это шаблонное сообщение пользователю, значит оно обязано быть в
    реестре как управляемый Factory Default (§3.4), а не жить только в Python.
    """
    from services.checkup_prompts import CHECKUP_FALLBACK_NOTICE

    spec = pr.block("message.checkup_fallback_notice")
    assert spec is not None
    assert spec.code_source == \
        "services.checkup_prompts.CHECKUP_FALLBACK_NOTICE"
    assert spec.speech is True
    assert spec.migration == "managed_message"
    assert spec.ui == "catalog_pending"          # ключ каталога добавит W3
    assert spec.owner_lane == "W3"
    assert pr.factory_text(spec.block_id) == CHECKUP_FALLBACK_NOTICE
    # Виден в витрине «блоки без ключа каталога» (никто не спрятан).
    rows = {row["block_id"] for row in pc.unmanaged_speech_blocks()}
    assert spec.block_id in rows


def test_registry_consumer_pointers_point_at_real_lines():
    """Трассируемость SOUL-AMD.3.1: указатель потребителя — реальная строка."""
    from services import prompt_registry as _pr

    pointers = {
        "internal.lore.init": ("lore_worker.py", "LORE_INIT_SYSTEM_PROMPT"),
        "internal.lore.merge": ("lore_worker.py", "LORE_MERGE_SYSTEM_PROMPT"),
        "internal.lore.story": ("lore_compiler_service.py",
                                "LORE_STORY_SYSTEM_PROMPT"),
        "message.checkup_fallback_notice": ("checkup_service.py",
                                            "CHECKUP_FALLBACK_NOTICE"),
    }
    for block_id, (filename, needle) in pointers.items():
        spec = _pr.block(block_id)
        assert spec is not None, block_id
        hits = [c for c in spec.consumers if c.startswith(filename + ":")]
        assert hits, (block_id, spec.consumers)
        lines = (ROOT / "services" / filename).read_text(
            encoding="utf-8").splitlines()
        for pointer in hits:
            number = int(pointer.split(":")[1].split()[0])
            assert needle in lines[number - 1], (
                f"{block_id}: {pointer} не содержит {needle} "
                f"(фактически: {lines[number - 1]!r})")


def test_registry_view_joins_catalog_and_shows_unmanaged_blocks():
    view = {row["block_id"]: row for row in pc.speech_registry_view()}
    assert view, "speech_registry_view пуст"
    ok = view["direct.base.l2_writer"]
    assert ok["catalog_key"] is True and ok["pg_key"]
    assert ok["title_ru"] and ok["group"]
    assert ok["factory_revision"].startswith(pr.FACTORY_PREFIX)
    unmanaged = pc.unmanaged_speech_blocks()
    assert unmanaged, "нет блоков без ключа каталога — проверка обесценена"
    for row in unmanaged:
        assert row["owner_lane"].startswith("W")
        assert row["speech"] is True


def test_effective_prompt_reports_source_and_factory_delta():
    block_id = "direct.base.l2_writer"
    factory = pr.factory_text(block_id)
    custom = factory + "\n\nПравка владельца."
    default = pr.effective_prompt(block_id)
    assert default.source == "default"
    assert default.text == factory
    assert default.differs_from_factory is False
    assert default.factory_revision == pr.factory_revision(block_id)
    # fix-pass review-w1 BLOCKER-1: незаписанное через API реестра значение
    # канона старой личности НЕ является активным слоем — действует заводская
    # редакция, а сохранённая ревизия видна отдельно (провенанс, §1.2/4.6).
    custom_row = pr.effective_prompt(block_id, pg_value=custom)
    assert custom_row.source == "default"
    assert custom_row.withheld is True
    assert custom_row.withheld_sha256_12 == pr.sha12(custom)
    assert custom_row.provenance_reason == "provenance_unavailable"
    assert custom_row.stored_source == "global"
    assert custom_row.stored_differs_from_factory is True
    assert custom_row.text == pr.suppress_legacy_speech(factory,
                                                        source="global")[0]
    assert "persisted_value_withheld" in custom_row.diagnostics
    chat_row = pr.effective_prompt(block_id, pg_value=custom,
                                   chat_value=factory)
    assert chat_row.withheld is True          # чат-слой тоже без провенанса
    assert chat_row.stored_source == "chat"
    unknown = pr.effective_prompt("no.such.block")
    assert unknown.source == "missing"
    assert unknown.diagnostics == ("block_unknown",)


def test_effective_prompt_shows_attested_registry_value():
    """Значение, записанное через API реестра, снова действующий слой."""
    block_id = "direct.base.l2_writer"
    key = pr.block(block_id).pg_key
    factory = pr.factory_text(block_id)
    custom = factory + "\n\nПравка владельца через реестр."
    ledger = {pr.PROVENANCE_DOC_KEY: {
        "v": 1, "items": {},
        pr.PROVENANCE_MAP_FIELD: {block_id: {
            "revision": pr.ACTIVE_PREFIX + pr.sha12(custom),
            "sha256_12": pr.sha12(custom), "kind": "owner_edit",
            "scope": "global", "at": "2026-10-16T00:00:00+00:00"}}}}

    class _Cache:
        def get(self, key_, default=None):
            return ledger.get(key_, default)

    prev_present = pr.by_pg_key(key) is not None
    assert prev_present
    row = pr.effective_prompt(block_id, pg_value=custom)
    assert row.source == "default"          # без кэша провенанс недоступен
    hot.set_config_cache(_Cache())
    try:
        row = pr.effective_prompt(block_id, pg_value=custom)
    finally:
        hot.set_config_cache(None)
    assert row.withheld is False
    assert row.source == "global"
    assert row.text == custom
    assert row.differs_from_factory is True
    assert row.factory_source == "Global Custom"
    assert row.provenance_reason == "attested"
