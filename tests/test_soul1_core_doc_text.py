# -*- coding: utf-8 -*-
"""SOUL-1/CORE-DOC + ASAP W1 — Personality Core: заводская редакция v3.

Доказывается (SOUL-AMD.1.1 «Factory Default = полный авторский текст» →
ASAP W1 §3.2/§3.3 source-2026-10-22.md «готовые тексты владельца»):

  * заводская ПОЛНАЯ редакция ``core.personality`` (v3) = §3.2 снапшота
    asap-speech-arch БАЙТ-В-БАЙТ (владелец специально подготовил тексты,
    ДОП-2 п.3; примитивизация запрещена). Свойства v3: нет регулирования
    мата (только Expression), нет служебной SOUL-16-ремарки, токсичность/
    цинизм/язвительность/абсурдный юмор сохранены как личность;
  * цепочка ревизий: v1 = авторский SOUL-02 (PREV_PERSONALITY_CORE_*,
    байт-в-байт строки 43–53 файла-первоисточника SOUL-1) → v2 =
    FIX-CORRECTIVE-FOLLOWUP (мат-тема снята; PREV_PERSONALITY_CORE_*_V2_TEXT,
    прод-байты 2.58.110 d98e72ec7926/e0529832ba7c) → v3 = §3.2/§3.3;
  * компактная редакция (v3) = §3.3 байт-в-байт — сжатие §3.2 без иных
    дозволений/запретов (таблица PERSONALITY_CORE_COMPACT_DERIVATION:
    абзац §3.2 → смысловые маркеры в обеих редакциях);
  * обе редакции зарегистрированы в реестре (v3-метки владельца);
  * гвард superseded-core: сохранённые в PG байты v1 И v2 не действуют —
    действует v3; кастом владельца не подменяется.

TEST-LIFECYCLE: CONTRACT owner=ASAP-W1 P0-B/P0-C (asap-speech-arch §3.2/3.3)
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest

from services import prompt_registry as pr
from services.chat_prompts import (CORE_REAL_EVENTS_PARAGRAPH,
                                   PERSONALITY_CORE_COMPACT_DERIVATION,
                                   PERSONALITY_CORE_COMPACT_TEXT,
                                   PERSONALITY_CORE_FULL_TEXT,
                                   PREV_PERSONALITY_CORE_COMPACT_TEXT,
                                   PREV_PERSONALITY_CORE_COMPACT_V2_TEXT,
                                   PREV_PERSONALITY_CORE_FULL_TEXT,
                                   PREV_PERSONALITY_CORE_FULL_V2_TEXT)

#: P0-CHECKUP/CORE (24.10.2026, addendum §3): минимальное дополнение Compact.
CORE_REAL_EVENTS_COMPACT = ("Когда есть фактура, рассказывай через характерные "
                            "детали и цепочку последствий: развивай точное "
                            "язвительное сравнение вместо набора общих оценок, "
                            "не подменяя им факты.")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_PATH = ROOT / "plans/features/asap-speech-arch/source-2026-10-22.md"
MAP_PATH = ROOT / "plans/features/asap-speech-arch/requirements-map.json"
SOURCE_V1_PATH = ROOT / "plans/features/soul-1/source-current-task.md"

#: SHA256[:12] прод-байтов v2 (W0-инвентаризация 22.10.2026:
#: plans/features/asap-speech-arch/evidence/w0-inventory.md §1).
V2_FULL_SHA12 = "d98e72ec7926"
V2_COMPACT_SHA12 = "e0529832ba7c"

#: Запреты/смысловые якоря v3 (сохранность характера по ДОП-1/ДОП-2);
#: формулировки изданий различаются — якоря покрывают обе редакции.
KEPT_FULL_ANCHORS = (
    "Не подменяй шутку",
    "Не обрывай удачную мысль",
    "бессмысленную ссору",
    "статистику чата",
)
KEPT_COMPACT_ANCHORS = (
    "не заменяй шутку банальным оскорблением",
    "Чередуй короткие и длинные реплики",
    "в ссору",
    "статистику чата",
)
KEPT_PERSONALITY = (
    "остроумие", "язвительн", "непристойн", "абсурд",
    "резким, злым, циничным и неприличным",
    "сам дурак",
)

#: «Стерильный ассистент» — прямой анти-цель владельца (ДОП-1).
ASSISTANT_SLOP = ("ассистент", "помощник", "я не могу")


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    pr.reset_cache()
    yield
    pr.reset_cache()


_mat_word_re = re.compile(r"\bмат(а|у|е|ом|ов|ами|ах)?\b", re.IGNORECASE)


def _has_mat_word(text: str) -> bool:
    """Словесные формы «мат» (не «форматный»/«материал»/«матч»)."""
    return bool(_mat_word_re.search(str(text or "")))


def _source_text() -> str:
    return SOURCE_PATH.read_text(encoding="utf-8")


def _fence(heading: str) -> str:
    """Байты первого ```text-блока после заголовка §N (первоисточник)."""
    src = _source_text()
    idx = src.index(heading)
    found = re.compile(r"```text\n(.*?)\n```", re.DOTALL).search(src, idx)
    assert found, heading
    return found.group(1)


def test_full_factory_text_is_owner_text_32_byte_exact():
    """v3 = §3.2 байт-в-байт; P0-CHECKUP/CORE (24.10.2026) добавляет РОВНО
    один недостающий абзац владельца §3 аддендума после «Как рождается юмор»
    и перед «Грубость и конфликт»; остальные байты не меняются. Регуляций
    мата и служебных меток нет; личность сохранена."""
    factory = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    assert factory == PERSONALITY_CORE_FULL_TEXT
    base = _fence("### 3.2. P0-B")
    anchor = "Грубость и конфликт."
    pos = base.index(anchor)
    expected = (base[:pos] + CORE_REAL_EVENTS_PARAGRAPH + "\n\n" + base[pos:])
    assert factory == expected, (
        "заводской Core разошёлся с §3.2 + owner-абзацем §3 аддендума (байты)")
    assert factory.count(CORE_REAL_EVENTS_PARAGRAPH) == 1
    assert not _has_mat_word(factory)
    assert "SOUL-" not in factory and "**Важно:**" not in factory
    for anchor in KEPT_PERSONALITY:
        assert anchor in factory, anchor
    for anchor in KEPT_FULL_ANCHORS:
        assert anchor in factory, anchor
    assert "### Речь, юмор и мышление" not in factory


def test_compact_factory_text_is_owner_text_33_byte_exact():
    """v3-компакт = §3.3 байт-в-байт; P0-CHECKUP/CORE дописывает ОДНО
    предложение того же смысла в существующий абзац, не меняя остального."""
    compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert compact == PERSONALITY_CORE_COMPACT_TEXT
    base = _fence("### 3.3. P0-C")
    marker = " Не выдумывай реальные события"
    assert marker in base
    expected = base.replace(marker,
                            " " + CORE_REAL_EVENTS_COMPACT + marker, 1)
    assert compact == expected
    assert compact.count(CORE_REAL_EVENTS_COMPACT) == 1
    assert "\n" not in compact          # остаётся одним связным абзацем
    assert not _has_mat_word(compact)
    assert "SOUL-" not in compact
    for anchor in ("язвительный", "непристойному юмору",
                   "резким и циничным", "не объясняй шутки",
                   "статистику чата"):
        assert anchor in compact, anchor


def test_prev_chain_v1_v2_is_frozen_byte_exact():
    """Цепочка PREV: v1 = строки 43–53 первоисточника SOUL-1 (с мат-темой);
    v2 = прод-байты 2.58.110 (sha12 по W0-инвентаризации)."""
    v1_lines = SOURCE_V1_PATH.read_text(encoding="utf-8").split("\n")
    expected_v1 = "\n".join(v1_lines[pr.CORE_SOURCE_V1["line_start"] - 1:
                                     pr.CORE_SOURCE_V1["line_end"]])
    assert PREV_PERSONALITY_CORE_FULL_TEXT == expected_v1
    assert "**Мат и грубость.**" in PREV_PERSONALITY_CORE_FULL_TEXT
    assert PREV_PERSONALITY_CORE_FULL_V2_TEXT != PREV_PERSONALITY_CORE_FULL_TEXT
    assert hashlib.sha256(
        PREV_PERSONALITY_CORE_FULL_V2_TEXT.encode("utf-8")).hexdigest()[:12] \
        == V2_FULL_SHA12
    assert hashlib.sha256(
        PREV_PERSONALITY_CORE_COMPACT_V2_TEXT.encode("utf-8")).hexdigest()[:12] \
        == V2_COMPACT_SHA12
    # v2: мат-тема уже снята, SOUL-16-ремарка ещё присутствовала
    assert "**Грубость.**" in PREV_PERSONALITY_CORE_FULL_V2_TEXT
    assert "SOUL-16" in PREV_PERSONALITY_CORE_FULL_V2_TEXT
    assert not _has_mat_word(PREV_PERSONALITY_CORE_FULL_V2_TEXT)
    # компактная v2 зеркалит правку (без SOUL-16-ремарки)
    assert "SOUL-16" not in PREV_PERSONALITY_CORE_COMPACT_V2_TEXT
    assert not _has_mat_word(PREV_PERSONALITY_CORE_COMPACT_V2_TEXT)


def test_compact_revision_keeps_documented_meaning_markers():
    """Компактная v3 — сжатие §3.2 тех же смысловых блоков (деривация:
    абзац §3.2 → маркеры, обязанные быть в Full и Compact)."""
    full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert PERSONALITY_CORE_COMPACT_DERIVATION, "деривация не задокументирована"
    paragraphs = full.split("\n\n")
    covered = set()
    for para_no, markers in PERSONALITY_CORE_COMPACT_DERIVATION:
        covered.add(para_no)
        source_para = paragraphs[para_no - 1]
        for marker in markers:
            assert marker in source_para, (para_no, marker)
            assert marker in compact, ("маркер потерян при сжатии", marker)
    # деривация покрывает все содержательные абзацы §3.2 + добавленный
    # owner-абзац P0-CHECKUP/CORE (1-6)
    assert covered == {1, 2, 3, 4, 5, 6}
    # зеркальные якоря есть в обеих редакциях (формулировки изданий разные)
    for anchor in KEPT_FULL_ANCHORS:
        assert anchor in full, anchor
    for anchor in KEPT_COMPACT_ANCHORS:
        assert anchor in compact, anchor


def test_compact_keeps_character_and_prohibitions_without_assistant_slop():
    full = pr.factory_text(pr.CORE_FULL_BLOCK_ID)
    compact = pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
    assert len(compact) < len(full), "компактная редакция не короче полной"
    assert compact != full
    for anchor in KEPT_COMPACT_ANCHORS:
        assert anchor in compact, f"запрет потерян: {anchor}"
    for bad in ASSISTANT_SLOP:
        assert bad not in compact and bad not in full, bad
    # CORRECTIVE-FOLLOWUP: тема мата отсутствует в обеих редакциях v3
    for text, name in ((full, "full"), (compact, "compact")):
        assert not _has_mat_word(text), name
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
    # v3-метки владельца (ASAP W1, §3.2/§3.3)
    assert pr.FACTORY_REVISION_LABELS[pr.CORE_FULL_BLOCK_ID] == \
        "asap-core-full-v3"
    assert pr.FACTORY_REVISION_LABELS[pr.CORE_COMPACT_BLOCK_ID] == \
        "asap-core-compact-v3"
    # провенанс источника v3 + сохранённая история v1
    assert str(pr.CORE_SOURCE["path"]).endswith(
        "asap-speech-arch/source-2026-10-22.md")
    assert "### 3.2" in pr.CORE_SOURCE["heading"]
    assert pr.CORE_SOURCE_V1["line_start"] == 43
    assert pr.CORE_SOURCE_V1["line_end"] == 53


# ═══ superseded-core: прежние заводские байты (v1 И v2) не действуют ════════

def test_superseded_core_doc_bytes_do_not_reach_effective():
    """Follow-up §1 + ASAP W1 (анти-воскрешение): сохранённое значение,
    байт-в-байт равное ЛЮБОЙ прежней заводской редакции (v1 с мат-темой /
    v2 прод 2.58.110), заменяется заводской v3 на разрешении; кастом
    владельца не подменяется; данные не пишутся."""
    for prev_full, prev_compact in (
            (PREV_PERSONALITY_CORE_FULL_TEXT,
             PREV_PERSONALITY_CORE_COMPACT_TEXT),
            (PREV_PERSONALITY_CORE_FULL_V2_TEXT,
             PREV_PERSONALITY_CORE_COMPACT_V2_TEXT)):
        old_doc = {"full_text": prev_full, "compact_text": prev_compact,
                   "detail_level": "full", "revision": "6"}
        sel = pr.core_selection(old_doc, source="global")
        assert sel["superseded_fields"] == ("full_text", "compact_text")
        assert sel["full_text"] == pr.factory_text(pr.CORE_FULL_BLOCK_ID)
        assert sel["compact_text"] == pr.factory_text(pr.CORE_COMPACT_BLOCK_ID)
        assert sel["text"] == sel["full_text"]
        assert sel["active_from_owner"] is False
        assert not _has_mat_word(sel["text"])
        # Inspector-вид честно показывает подмену (R17-safe: имена полей)
        view = pr.core_selection_view(old_doc, source="global")
        assert view["superseded_fields"] == ["full_text", "compact_text"]
    # кастом владельца (даже на один символ) НЕ подменяется никогда
    custom = {"full_text": PREV_PERSONALITY_CORE_FULL_V2_TEXT + " ",
              "detail_level": "full"}
    sel_custom = pr.core_selection(custom, source="global")
    assert sel_custom["superseded_fields"] == ()
    # документ без документа → заводская (чистая) редакция
    sel_default = pr.core_selection(None)
    assert sel_default["superseded_fields"] == ()
    assert not _has_mat_word(sel_default["text"])


def test_source_snapshot_hash_matches_map():
    """Провенанс: снапшот asap-speech-arch — те самые байты, что в карте."""
    doc = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    raw = SOURCE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == doc["source_sha256"]
