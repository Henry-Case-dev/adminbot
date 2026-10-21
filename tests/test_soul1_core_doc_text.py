# -*- coding: utf-8 -*-
"""SOUL-1 / CORE-DOC — первоисточник Personality Core и компактная редакция.

Доказывается (SOUL-AMD.1.1 «Factory Default = полный авторский текст»,
SOUL-02.1–02.6 «Речь, юмор и мышление» + CORRECTIVE-FOLLOWUP 21.10.2026 §1):

  * заводская ПОЛНАЯ редакция блока ``core.personality`` — под-блок
    «### Речь, юмор и мышление» файла-первоисточника ЗА ИСКЛЮЧЕНИЕМ
    ДОКУМЕНТИРОВАННОЙ правки владельца (21.10.2026): тема мата удалена из
    Core полностью — регулирование нецензурной лексики принадлежит только
    слою Expression. Файл-первоисточник НЕ правится (провенанс цел):
    сравнение идёт с САМИМ файлом — каждая нетронутая строка байт-в-байт,
    удалены ровно задокументированные мат-фрагменты, прежние байты живут в
    PREV_PERSONALITY_CORE_*;
  * компактная редакция ``core.personality.compact`` — ручное сжатие тех же
    предложений (таблица ``PERSONALITY_CORE_COMPACT_DERIVATION``): маркеры
    смысла есть и в источнике, и в сжатии (мат-маркер «приправа» удалён по
    той же правке), «ассистентского» голоса нет;
  * обе редакции зарегистрированы как отдельные блоки реестра с фабричными
    ревизиями и версиями-метками владельца (v2);
  * гвард superseded-core: сохранённое в PG значение, байт-в-байт равное
    прежней заводской редакции, не действует — действует новая заводская
    (данные не трогаются; прецедент withheld_factory_governs).

TEST-LIFECYCLE: CONTRACT owner=SOUL-AMD.1.1 / SOUL-02.1–02.6 (soul-1,
CORE-DOC) + FIX-CORRECTIVE-FOLLOWUP 21.10.2026 §1
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
                                   PERSONALITY_CORE_FULL_TEXT,
                                   PREV_PERSONALITY_CORE_COMPACT_TEXT,
                                   PREV_PERSONALITY_CORE_FULL_TEXT)

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "plans/features/soul-1/source-current-task.md"
MAP_PATH = ROOT / "plans/features/soul-1/requirements-map.json"

#: Запреты/смысловые якоря полной редакции, обязанные остаться в сжатии
#: (каждый из них — подстрока соответствующего абзаца-источника, см. таблицу
#: деривации). Мат-якорь «приправа к каждому предложению» УДАЛЁН правкой
#: 21.10.2026 (тема мата больше не часть Core).
KEPT_PROHIBITIONS = (
    "Не подменяй шутку оскорблением",
    "Не обрывай удачную мысль",
    "бессмысленную ссору",
    "статистику чата",
)

#: «Стерильный ассистент» — прямой анти-цель владельца (SOUL-AMD.1.3:
#: «Не превращать персонажа в стерильного „дружелюбного помощника“»).
ASSISTANT_SLOP = ("ассистент", "помощник", "я не могу")

#: ДОКУМЕНТИРОВАННАЯ правка CORRECTIVE-FOLLOWUP 21.10.2026 §1: единственные
#: фрагменты, которыми заводской Core отличается от первоисточника.
AMENDED_MAT_SENTENCES = (
    "Мат - естественная часть речи, а не обязательная приправа к каждому "
    "предложению. Используй его свободно, если он делает фразу "
    "выразительнее, смешнее или эмоционально точнее. ",
)
#: Компактная редакция удаляет СВОЁ сжатое мат-предложение (зеркалит правку).
AMENDED_COMPACT_MAT_SENTENCE = (
    "Мат - естественная часть речи, а не приправа к каждому предложению: "
    "используй его, когда он делает фразу выразительнее, смешнее или "
    "эмоционально точнее. "
)
AMENDED_HEADING_OLD = "**Мат и грубость.**"
AMENDED_HEADING_NEW = "**Грубость.**"


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


import re

_MAT_WORD_RE = re.compile(r"\bмат(а|у|е|ом|ов|ами|ах)?\b", re.IGNORECASE)


def _has_mat_word(text: str) -> bool:
    """Словесные формы «мат» (не «форматный»/«материал»/«матч»)."""
    return bool(_MAT_WORD_RE.search(str(text or "")))


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


def _amend_source_paragraph(line: str) -> str:
    """Применить документированную правку к абзацу-источнику (строка 47)."""
    amended = line
    for sentence in AMENDED_MAT_SENTENCES:
        assert sentence in amended, \
            "документированный мат-фрагмент не найден в источнике"
        amended = amended.replace(sentence, "")
    assert AMENDED_HEADING_OLD in amended
    amended = amended.replace(AMENDED_HEADING_OLD, AMENDED_HEADING_NEW)
    return amended


def _expected_factory_from_source() -> str:
    """Заводской текст = первоисточник + документированная правка."""
    lines = _source_lines()
    start, end = pr.CORE_SOURCE["line_start"], pr.CORE_SOURCE["line_end"]
    out = []
    for no in range(start, end + 1):
        line = lines[no - 1]
        out.append(_amend_source_paragraph(line)
                   if AMENDED_HEADING_OLD in line else line)
    return "\n".join(out)


def test_full_factory_text_is_source_subblock_with_documented_amendment():
    """Factory = первоисточник минус РОВНО документированные мат-фрагменты."""
    factory = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    assert factory == PERSONALITY_CORE_FULL_TEXT
    assert factory == _expected_factory_from_source(), (
        "заводской Core разошёлся с «первоисточник + документированная "
        "правка 21.10.2026»")
    # тема мата в действующей редакции отсутствует полностью (словесные
    # формы; «форматный»/«материал» словами мата не считаются)
    assert not _has_mat_word(factory), factory
    assert "приправа" not in factory
    # остальные авторские данные абзаца сохранены
    for anchor in ("Не подменяй шутку оскорблением",
                   "сам дурак", "Грубость",
                   "резким, злым, циничным и неприличным",
                   "бессмысленную ссору"):
        assert anchor in factory, anchor
    assert "### Речь, юмор и мышление" not in factory, \
        "заголовок документа не является частью характера"
    # прежние байты (с мат-темой) заморожены как PREV-снапшот
    assert PREV_PERSONALITY_CORE_FULL_TEXT == "\n".join(
        _source_lines()[pr.CORE_SOURCE["line_start"] - 1:
                        pr.CORE_SOURCE["line_end"]]), (
        "PREV-снапшот обязан быть байт-в-байт копией первоисточника")
    assert AMENDED_MAT_SENTENCES[0] in PREV_PERSONALITY_CORE_FULL_TEXT
    assert AMENDED_HEADING_OLD in PREV_PERSONALITY_CORE_FULL_TEXT


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
             "PERSONALITY_CORE_COMPACT_DERIVATION",
             "PREV_PERSONALITY_CORE_FULL_TEXT",
             "PREV_PERSONALITY_CORE_COMPACT_TEXT"}
    body_ids = {id(node) for node in tree.body}
    defs: dict[str, list[int]] = {name: [] for name in names}
    top_level: set[str] = set()
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and node.target is not None \
                and isinstance(node.target, ast.Name):
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
    """Провенанс: файл-источник и строки SOUL-1 карты — те самые байты
    (первоисточник правкой 21.10.2026 НЕ затронут)."""
    doc = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    raw = SOURCE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == doc["source_sha256"], \
        "source snapshot изменился — карта требований построена по другим байтам"
    assert str(doc["source_path"]).endswith("source-current-task.md")
    rows = _map_rows()
    lines = _source_lines()
    factory = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    prev = PREV_PERSONALITY_CORE_FULL_TEXT
    checked = 0
    for req_id in pr.CORE_SOURCE["req_ids"]:
        row = rows.get(req_id)
        assert row is not None, f"{req_id} отсутствует в карте SOUL-1"
        line_no = int(row["source_line"])
        assert pr.CORE_SOURCE["line_start"] <= line_no <= pr.CORE_SOURCE["line_end"]
        assert _sha256(lines[line_no - 1]) == row["source_text_sha256"], (
            f"{req_id}: строка {line_no} не совпала с source_text_sha256 карты")
        source_line = lines[line_no - 1]
        if AMENDED_HEADING_OLD in source_line:
            # строка абзаца «Мат и грубость» действует в заводском тексте
            # только в amended-виде; исходные байты — в PREV-снапшоте
            assert source_line in prev
            assert _amend_source_paragraph(source_line) in factory
        else:
            assert source_line in factory
            assert source_line in prev
        checked += 1
    assert checked == 6, "ожидались все шесть строк характера SOUL-02.1–02.6"


def test_compact_revision_keeps_documented_meaning_markers():
    """Компактная редакция — сжатие тех же предложений, а не новый характер."""
    assert PERSONALITY_CORE_COMPACT_DERIVATION, "деривация не задокументирована"
    lines = _source_lines()
    full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    prev_full = PREV_PERSONALITY_CORE_FULL_TEXT
    compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert compact == PERSONALITY_CORE_COMPACT_TEXT
    assert compact == PREV_PERSONALITY_CORE_COMPACT_TEXT.replace(
        AMENDED_COMPACT_MAT_SENTENCE, "").replace(AMENDED_HEADING_OLD,
                                                  AMENDED_HEADING_NEW), (
        "компактная правка обязана зеркалить документированную правку полной")
    source_paragraphs = set()
    for line_no, markers in PERSONALITY_CORE_COMPACT_DERIVATION:
        source_paragraphs.add(line_no)
        source_line = lines[line_no - 1]
        assert source_line in prev_full, \
            f"строка {line_no} не входит в прежний (PREV) текст"
        for marker in markers:
            assert marker in source_line, (line_no, marker)
            assert marker in compact, ("маркер потерян при сжатии", marker)
    assert source_paragraphs == {43, 45, 47, 49, 51}, (
        "деривация обязана покрывать все абзацы характера; закрывающий абзац "
        "53 описывает сам ДОКУМЕНТ (форматный слой — Speech Style Policy)")
    # зеркальные якоря amended-полного текста есть в компактном
    for anchor in ("Не подменяй шутку оскорблением", "сам дурак",
                   "Грубость", "бессмысленную ссору"):
        assert anchor in full and anchor in compact, anchor


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
    # CORRECTIVE-FOLLOWUP 21.10.2026: тема мата отсутствует в обеих редакциях
    for text, name in ((full, "full"), (compact, "compact")):
        assert not _has_mat_word(text), name
        assert "приправа" not in text, name
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
    assert pr.FACTORY_REVISION_LABELS[pr.CORE_FULL_BLOCK_ID] == \
        "soul02-author-full-v2"
    assert pr.FACTORY_REVISION_LABELS[pr.CORE_COMPACT_BLOCK_ID] == \
        "soul02-compact-v2"
    assert pr.CORE_SOURCE["amendment"] == \
        "SOUL-AMD.1.1 + FIX-CORRECTIVE-FOLLOWUP 21.10.2026 §1"
    assert pr.CORE_SOURCE["factory_rev_label"] == \
        pr.FACTORY_REVISION_LABELS[pr.CORE_FULL_BLOCK_ID]


# ═══ superseded-core: прежние заводские байты не действуют из PG ════════════

def test_superseded_core_doc_bytes_do_not_reach_effective():
    """Follow-up §1 (анти-воскрешение): сохранённое значение, байт-в-байт
    равное ПРЕЖНЕЙ заводской редакции, заменяется новой заводской на
    разрешении; кастом владельца не подменяется; данные не пишутся."""
    old_doc = {"full_text": PREV_PERSONALITY_CORE_FULL_TEXT,
               "compact_text": PREV_PERSONALITY_CORE_COMPACT_TEXT,
               "detail_level": "full", "revision": "5"}
    sel = pr.core_selection(old_doc, source="global")
    assert sel["superseded_fields"] == ("full_text", "compact_text")
    assert sel["full_text"] == pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    assert sel["compact_text"] == pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert sel["text"] == sel["full_text"]
    assert sel["active_from_owner"] is False
    assert not _has_mat_word(sel["text"])
    # Inspektor-вид честно показывает подмену (R17-safe: имена полей)
    view = pr.core_selection_view(old_doc, source="global")
    assert view["superseded_fields"] == ["full_text", "compact_text"]
    # кастом владельца (даже на один символ) НЕ подменяется
    custom = {"full_text": PREV_PERSONALITY_CORE_FULL_TEXT + " ",
              "detail_level": "full"}
    sel_custom = pr.core_selection(custom, source="global")
    assert sel_custom["superseded_fields"] == ()
    assert "мат" in sel_custom["text"]      # кастом остаётся данными владельца
    # документ без документа → заводская (чистая) редакция
    sel_default = pr.core_selection(None)
    assert sel_default["superseded_fields"] == ()
    assert not _has_mat_word(sel_default["text"])
