"""SOUL-1 / CORE-DOC — первоисточник Personality Core и компактная редакция.

Доказывается (SOUL-AMD.1.1 «Factory Default = полный авторский текст»,
SOUL-02.1–02.6 «Речь, юмор и мышление»):

  * заводская ПОЛНАЯ редакция блока ``core.personality`` — байт-в-байт
    под-блок «### Речь, юмор и мышление» файла-первоисточника: сравнение идёт
    с САМИМ файлом и со строчными хешами SOUL-1 карты требований, а не с
    копией текста внутри теста (копия ничего бы не доказывала);
  * компактная редакция ``core.personality.compact`` — ручное сжатие тех же
    предложений: каждый задокументированный маркер смысла есть и в источнике,
    и в сжатии (таблица ``PERSONALITY_CORE_COMPACT_DERIVATION``), запреты и
    характер сохранены, «ассистентского» голоса нет;
  * обе редакции зарегистрированы как отдельные блоки реестра с фабричными
    ревизиями и версиями-метками владельца.

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.1.1 / SOUL-02.1–02.6 (soul-1, CORE-DOC)
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib

import pytest

from services import prompt_registry as pr
from services.chat_prompts import (PERSONALITY_CORE_COMPACT_DERIVATION,
                                   PERSONALITY_CORE_COMPACT_TEXT,
                                   PERSONALITY_CORE_FULL_TEXT)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "plans/features/soul-1/source-current-task.md"
MAP_PATH = ROOT / "plans/features/soul-1/requirements-map.json"

#: Запреты/смысловые якоря полной редакции, обязанные остаться в сжатии
#: (каждый из них — подстрока соответствующего абзаца-источника, см. таблицу
#: деривации; произвольные «ключевые слова» здесь не проверяются).
KEPT_PROHIBITIONS = (
    "Не подменяй шутку оскорблением",
    "Не обрывай удачную мысль",
    "бессмысленную ссору",
    "приправа к каждому предложению",
    "статистику чата",
)

#: «Стерильный ассистент» — прямой анти-цель владельца (SOUL-AMD.1.3:
#: «Не превращать персонажа в стерильного „дружелюбного помощника“»).
ASSISTANT_SLOP = ("ассистент", "помощник", "я не могу")


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


def _source_lines() -> list[str]:
    return SOURCE_PATH.read_text(encoding="utf-8").split("\n")


def _map_rows() -> dict[str, dict]:
    doc = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    rows: dict[str, dict] = {}
    for group in ("items", "additional_requirements"):
        for row in doc.get(group) or ():
            if isinstance(row, dict) and row.get("req_id"):
                rows[str(row["req_id"])] = row
    return rows


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_full_factory_text_is_byte_exact_source_subbock():
    """Factory Default = первоисточник: байт-в-байт, без «улучшений»."""
    lines = _source_lines()
    start, end = pr.CORE_SOURCE["line_start"], pr.CORE_SOURCE["line_end"]
    assert lines[start - 3].strip() == pr.CORE_SOURCE["heading"], \
        "граница диапазона не там, где объявлена (заголовок под-блока)"
    assert lines[end + 1].startswith("**Runtime:**"), \
        "диапазон не заканчивается перед абзацем «Runtime»"
    from_source = "\n".join(lines[start - 1:end])
    factory = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    assert factory == from_source, (
        "заводской Core разошёлся с первоисточником: "
        f"chars {len(factory)} != {len(from_source)}")
    assert factory == PERSONALITY_CORE_FULL_TEXT
    assert "### Речь, юмор и мышление" not in factory, \
        "заголовок документа не является частью характера"
    # Никакой нормализации «на лету»: байты, а не смысл.
    assert factory == from_source.encode("utf-8").decode("utf-8")
    assert _sha256(factory) == _sha256(from_source)


def test_core_constants_are_defined_exactly_once_in_module_source():
    """Единственный источник: Core-константы определены в модуле ровно по разу.

    Регресс FIX-CORE-DUP (review-core R1): блок CORE-DOC лежал в файле тремя
    копиями — Python исполняет последнюю, поэтому «активное значение» и тесты
    на него не видят теневые варианты текста характера. Считаем определения по
    AST самого файла-канона (любая вложенная копия тоже ловится).

    TEST-LIFECYCLE: REGRESSION owner=SOUL-1/FIX-CORE-DUP
    """
    module_path = ROOT / "services/chat_prompts.py"
    tree = ast.parse(module_path.read_bytes())
    names = {"PERSONALITY_CORE_FULL_TEXT", "PERSONALITY_CORE_COMPACT_TEXT",
             "PERSONALITY_CORE_COMPACT_DERIVATION"}
    body_ids = {id(node) for node in tree.body}
    defs: dict[str, list[int]] = {name: [] for name in names}
    top_level: set[str] = set()
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        for target in targets:
            if target in names:
                defs[target].append(node.lineno)
                if id(node) in body_ids:
                    top_level.add(target)
    for name, lines in defs.items():
        assert len(lines) == 1, (
            f"{name} определён {len(lines)} раз(а) (строки {lines}): теневая "
            "копия текста характера недопустима (No Hidden Behavioral Prompts)")
        assert name in top_level, f"{name} определён не на верхнем уровне модуля"


def test_source_snapshot_and_map_hashes_match_source_file():
    """Провенанс: файл-источник и строки SOUL-1 карты — те самые байты."""
    doc = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    raw = SOURCE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == doc["source_sha256"], \
        "source snapshot изменился — карта требований построена по другим байтам"
    assert str(doc["source_path"]).endswith("source-current-task.md")
    rows = _map_rows()
    lines = _source_lines()
    checked = 0
    for req_id in pr.CORE_SOURCE["req_ids"]:
        row = rows.get(req_id)
        assert row is not None, f"{req_id} отсутствует в карте SOUL-1"
        line_no = int(row["source_line"])
        assert pr.CORE_SOURCE["line_start"] <= line_no <= pr.CORE_SOURCE["line_end"]
        assert _sha256(lines[line_no - 1]) == row["source_text_sha256"], (
            f"{req_id}: строка {line_no} не совпала с source_text_sha256 карты")
        assert lines[line_no - 1] in pr.factory_text(pr.CORE_FULL_BLOCK_ID)
        checked += 1
    assert checked == 6, "ожидались все шесть строк характера SOUL-02.1–02.6"


def test_compact_revision_keeps_documented_meaning_markers():
    """Компактная редакция — сжатие тех же предложений, а не новый характер."""
    assert PERSONALITY_CORE_COMPACT_DERIVATION, "деривация не задокументирована"
    lines = _source_lines()
    full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert compact == PERSONALITY_CORE_COMPACT_TEXT
    source_paragraphs = set()
    for line_no, markers in PERSONALITY_CORE_COMPACT_DERIVATION:
        source_paragraphs.add(line_no)
        source_line = lines[line_no - 1]
        assert source_line in full, f"строка {line_no} не входит в полный текст"
        for marker in markers:
            assert marker in source_line, (line_no, marker)
            assert marker in compact, ("маркер потерян при сжатии", marker)
    assert source_paragraphs == {43, 45, 47, 49, 51}, (
        "деривация обязана покрывать все абзацы характера; закрывающий абзац "
        "53 описывает сам ДОКУМЕНТ (форматный слой — Speech Style Policy)")


def test_compact_keeps_character_and_prohibitions_without_assistant_slop():
    full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    words = len(compact.split())
    assert 150 <= words <= 250, f"компактная редакция вне диапазона: {words} слов"
    assert len(compact) < len(full), "компактная редакция не короче полной"
    assert compact != full
    for anchor in KEPT_PROHIBITIONS:
        assert anchor in compact, f"запрет потерян: {anchor}"
        assert anchor in full, f"якорь отсутствует в первоисточнике: {anchor}"
    for bad in ASSISTANT_SLOP:
        assert bad not in compact and bad not in full, bad
    # Характер, а не формат: правила оформления живут в Speech Style Policy.
    assert "кавычк" not in compact.lower()
    assert "эмодзи" not in compact.lower()


def test_both_core_blocks_are_registered_with_factory_revisions():
    full_spec = pr.block(pr.CORE_FULL_BLOCK_ID)
    compact_spec = pr.block(pr.CORE_COMPACT_BLOCK_ID)
    assert full_spec is not None and compact_spec is not None
    assert full_spec.pg_key == pr.CORE_DOC_KEY
    assert compact_spec.pg_key == pr.CORE_DOC_KEY
    assert full_spec.pg_doc_field == "full_text"
    assert compact_spec.pg_doc_field == "compact_text"
    for spec in (full_spec, compact_spec):
        assert spec.speech is True
        assert spec.migration == "factory"
        assert spec.owner_lane.startswith("W")
        assert spec.code_source.startswith("services.chat_prompts.")
        assert pr.production_kind(spec.block_id) == "factory_document"
        revision = pr.factory_revision(spec.block_id)
        assert revision.startswith(pr.FACTORY_PREFIX), revision
        assert "(" in revision, "фабричная ревизия без версии-метки владельца"
    assert pr.FACTORY_REVISION_LABELS[pr.CORE_FULL_BLOCK_ID] in \
        pr.factory_revision(pr.CORE_FULL_BLOCK_ID)
    assert pr.CORE_SOURCE["amendment"] == "SOUL-AMD.1.1"
    assert pr.CORE_SOURCE["factory_rev_label"] == \
        pr.FACTORY_REVISION_LABELS[pr.CORE_FULL_BLOCK_ID]
