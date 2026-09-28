"""ASAP-2.1 — T-3989: тесты emphasis (§29), style/typography (§30),
finale (§31) — §99 v1.1 (ADR-1028-1 D3/D5/D6).

§29:3592 — абзац «Никита предложил новую схему, после чего Лёха её разъебал.»:
все три span'а bold в Rich, invalid span не ломает публикацию.
§30:3594–3608 — канон/типографика L2 (проверка контракта, не LLM).
§31:3612–3624 — fixture A=30/B=5, абсурд у B: code НЕ выбирает A, winner из
LLM output (code не имеет fallback на счётчик сообщений).
"""
import json

import pytest

from services.summary_article_formatter import (
    format_plain_html,
    format_plain_text,
    format_rich_html,
)
from services.summary_l2_writer import validate_l2_document


def _package(texts):
    """Минимальный deliverable-пакет §96: fragments ВНУТРИ thread (пул цитат
    собирается из threads[].facts/fragments — см. _package_text_pool)."""
    return {"threads": [{
        "thread_id": "thread_001", "name": "Тема",
        "description": " ".join(texts)[:100],
        "chronology": [], "facts": [],
        "fragments": [{"message_id": 100 + i, "timestamp": 1000 + i,
                       "text": t} for i, t in enumerate(texts)],
        "evidence_ids": [],
    }], "unassigned_message_ids": [], "service": {}, "budget": {}}


def _doc(paragraphs, finale=None):
    return {
        "schema_version": 1,
        "title": "Заголовок",
        "paragraphs": paragraphs,
        **({"finale": finale} if finale else {}),
    }


# ── §29: emphasis_spans ────────────────────────────────────────────────────

def test_three_spans_accepted_and_rendered_bold():
    text = "Никита предложил новую схему, после чего Лёха её разъебал."
    raw = _doc([{"text": text, "emphasis_spans": [
        {"text": "Никита", "kind": "person"},
        {"text": "новую схему", "kind": "event"},
        {"text": "Лёха", "kind": "person"},
    ]}])
    canonical, metrics = validate_l2_document(raw, _package([text]))
    assert canonical is not None, metrics
    spans = canonical["paragraphs"][0]["emphasis_spans"]
    assert spans == ["Никита", "новую схему", "Лёха"]
    assert canonical["paragraphs"][0]["emphasis"] == "Никита"  # derived
    assert metrics["emphasis_spans_count"] == 3

    html = format_rich_html(canonical, cover_id=None)
    assert "<b>Никита</b>" in html
    assert "<b>новую схему</b>" in html
    assert "<b>Лёха</b>" in html
    # plain fallback сохраняет bold.
    plain = format_plain_html(canonical)
    assert "<b>Никита</b>" in plain and "<b>Лёха</b>" in plain
    # raw fallback — полный текст без markup.
    raw_text = format_plain_text(canonical)
    assert text in raw_text
    assert "<b>" not in raw_text


def test_invalid_span_ignored_publication_not_broken():
    text = "Никита предложил новую схему."
    raw = _doc([{"text": text, "emphasis_spans": [
        {"text": "Никита", "kind": "person"},
        {"text": "нет такого фрагмента", "kind": "person"},   # не подстрока
        {"text": "<b>тег</b>", "kind": "event"},               # тегоподобный
    ]}])
    canonical, metrics = validate_l2_document(raw, _package([text]))
    assert canonical is not None, metrics
    spans = canonical["paragraphs"][0]["emphasis_spans"]
    assert spans == ["Никита"]
    assert metrics["emphasis_dropped_count"] == 2
    html = format_rich_html(canonical, cover_id=None)
    assert "<b>Никита</b>" in html
    assert "тег" not in html              # забракованный спан не доходит до рендера


def test_formatter_escapes_taglike_span_defense_in_depth():
    """Raw HTML от L2 не проходит как разметка СТРУКТУРНО: если тегоподобный
    спан каким-то образом дошёл до форматтера (в обход валидатора) — он
    экранируется, а не рендерится."""
    doc = {"schema_version": 1, "title": "Т", "paragraphs": [{
        "text": "Текст с попыткой инъекции <b>жирным</b>.",
        "emphasis": None,
        "emphasis_spans": ["<b>жирным</b>"],   # bypass валидатора (defense)
    }]}
    html = format_rich_html(doc, cover_id=None)
    # Инъекция НЕ рендерится как разметка — только экранируется внутри
    # bold-обёртки валидного спана.
    assert "&lt;b&gt;жирным&lt;/b&gt;" in html
    assert "<b>жирным</b>" not in html


def test_unknown_kind_counted_not_fatal():
    text = "Кот спит."
    raw = _doc([{"text": text, "emphasis_spans": [
        {"text": "Кот", "kind": "mascot"},        # не person/event
    ]}])
    canonical, metrics = validate_l2_document(raw, _package([text]))
    assert canonical is not None
    assert canonical["paragraphs"][0]["emphasis_spans"] == ["Кот"]
    assert metrics["emphasis_spans_count"] == 1


def test_overlap_deterministic_and_cap_four():
    text = "abcdef"
    raw = _doc([{"text": text, "emphasis_spans": [
        {"text": "abc", "kind": "event"},
        {"text": "cde", "kind": "event"},   # пересекается с abc → мимо
        {"text": "f", "kind": "person"},
        {"text": "bcd", "kind": "event"},   # пересекается с abc → мимо
    ]}])
    canonical, metrics = validate_l2_document(raw, _package([text]))
    assert canonical is not None
    assert canonical["paragraphs"][0]["emphasis_spans"] == ["abc", "f"]
    assert metrics["emphasis_dropped_count"] == 2


def test_cap_four_fifth_dropped():
    text = "a b c d e"
    raw = _doc([{"text": text, "emphasis_spans": [
        {"text": "a", "kind": "person"},
        {"text": "b", "kind": "person"},
        {"text": "c", "kind": "person"},
        {"text": "d", "kind": "person"},
        {"text": "e", "kind": "person"},    # 5-й — за капом
    ]}])
    canonical, metrics = validate_l2_document(raw, _package([text]))
    assert canonical is not None
    assert canonical["paragraphs"][0]["emphasis_spans"] == ["a", "b", "c", "d"]
    assert metrics["emphasis_dropped_count"] == 1


def test_legacy_emphasis_first_in_queue_backward_compatible():
    text = "Старый документ с акцентом."
    raw = _doc([{"text": text, "emphasis": "акцентом"}])
    canonical, metrics = validate_l2_document(raw, _package([text]))
    assert canonical is not None
    para = canonical["paragraphs"][0]
    assert para["emphasis"] == "акцентом"
    assert para["emphasis_spans"] == ["акцентом"]


def test_documents_without_new_fields_valid():
    raw = {"schema_version": 1, "title": "Т",
           "paragraphs": [{"text": "Текст старого канона.", "emphasis": None}]}
    canonical, metrics = validate_l2_document(raw, _package(["Текст старого канона."]))
    assert canonical is not None
    assert canonical["paragraphs"][0]["emphasis_spans"] == []
    assert metrics["finale_present"] == 0
    assert "finale" not in canonical


# ── §30: typography (deterministic normalizer, T-3978) ─────────────────────

def test_typography_cleanup_on_canonicalization():
    text = "Он сказал «привет» — и ушёл."
    raw = _doc([{"text": text, "emphasis_spans": [
        {"text": "«привет»", "kind": "event"},   # спан ДО cleanup
    ]}])
    canonical, metrics = validate_l2_document(raw, _package(["Он сказал \"привет\" - и ушёл."]))
    assert canonical is not None, metrics
    para = canonical["paragraphs"][0]
    # Текст нормализован теми же 6 заменами (содержание не изменено).
    assert para["text"] == "Он сказал \"привет\" - и ушёл."
    # Спан, очищенный той же картой, остался подстрокой финального текста.
    assert para["emphasis_spans"] == ["\"привет\""]


def test_typography_idempotent_and_content_preserved():
    from services.summary_cleanup import cleanup_llm_text
    once = cleanup_llm_text("Текст «в кавычках» — с тире „и“ “ёлочками» – норм.")
    twice = cleanup_llm_text(once)
    assert once == twice
    # Разрешённые замены не меняют длину содержательных символов 1:1.
    assert cleanup_llm_text("абзац без типографики") == "абзац без типографики"


# ── §31: finale — code НЕ выбирает winner ─────────────────────────────────

def test_finale_taken_from_llm_only(monkeypatch):
    """Fixture A=30/B=5, абсурд у B: canonical finale == то, что дала LLM
    (про B); code не подставляет самого активного (A) ни при каком раскладе."""
    text_a = "сообщение" 
    rows = ([{"id": i, "tg_message_id": i, "timestamp": 1000 + i,
              "text": text_a, "user_id": 1, "author_name": "UserA",
              "reply_to_id": None, "media_type": "text"}
             for i in range(1, 31)]
            + [{"id": 100 + i, "tg_message_id": 100 + i, "timestamp": 2000 + i,
                "text": "абсурдный эпизод", "user_id": 2,
                "author_name": "UserB", "reply_to_id": None,
                "media_type": "text"} for i in range(1, 6)])
    package = _package([r["text"] for r in rows])
    raw = _doc(
        [{"text": "UserB устроил самый абсурдный эпизод вечера.",
          "emphasis_spans": [{"text": "UserB", "kind": "person"}]}],
        finale="Главным шизом объявляется UserB.")
    canonical, metrics = validate_l2_document(raw, package)
    assert canonical is not None
    assert canonical["finale"] == "Главным шизом объявляется UserB."
    assert metrics["finale_present"] == 1
    # Code не имеет статистического fallback: символ удалён из генератора.
    import inspect

    import services.summary_generator as sg
    source = inspect.getsource(sg)
    assert "most_active_author" not in source
    assert source.count("UserA") == 0


def test_finale_invalid_dropped_no_string():
    raw = _doc([{"text": "Текст."}], finale="   ")
    canonical, metrics = validate_l2_document(raw, _package(["Текст."]))
    assert canonical is not None
    assert "finale" not in canonical
    assert metrics["finale_present"] == 0

    raw2 = _doc([{"text": "Текст."}], finale="многострока\nвторая")
    canonical2, _m = validate_l2_document(raw2, _package(["Текст."]))
    assert canonical2 is not None
    assert "finale" not in canonical2       # одна строка required

    raw3 = _doc([{"text": "Текст."}], finale="x" * 201)
    canonical3, _m = validate_l2_document(raw3, _package(["Текст."]))
    assert canonical3 is not None
    assert "finale" not in canonical3       # 1..200


def test_finale_rendered_last_block_in_all_channels():
    doc = {
        "schema_version": 1, "title": "Т",
        "paragraphs": [{"text": "Абзац один.", "emphasis": None,
                        "emphasis_spans": []}],
        "finale": "Главным шизом объявляется Кот.",
    }
    rich = format_rich_html(doc, cover_id=None)   # 1 абзац → без ката
    assert rich.rstrip().endswith("<p>Главным шизом объявляется Кот.</p>")
    plain = format_plain_html(doc)
    assert plain.rstrip().endswith("Главным шизом объявляется Кот.")
    raw = format_plain_text(doc)
    assert raw.rstrip().endswith("Главным шизом объявляется Кот.")
