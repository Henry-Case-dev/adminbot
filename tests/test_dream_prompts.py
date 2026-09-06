"""Раунд 9 (AGI Memory, T-825/D4, spec §3.4.5/Q10) — промпт-канон
дистилляции «сна» и парсинг ответа (tests по конвенции канон-тестов,
прецедент test_lore_prompts.py).
"""
import re

import pytest

from services.dream_prompts import (
    DREAM_DISTILL_PROMPT,
    build_dream_user,
    parse_distill_answer,
)


class TestCanon:
    def test_prompt_canon_rules(self):
        text = DREAM_DISTILL_PROMPT
        assert "синтезатор" in text
        assert "кластер" in text
        assert "1-2" in text
        assert "120 символов" in text
        assert "beliefs" in text
        assert "evidence" in text
        assert "JSON" in text
        assert "UNCHANGED" in text
        assert "кавычек-ёлочек и длинных тире" in text

    def test_no_quotes_and_dashes_in_canon(self):
        """Канон-дисциплина (NFR-6): без «», —, – в тексте промпта."""
        for bad in ("«", "»", "—", "–"):
            assert bad not in DREAM_DISTILL_PROMPT, f"{bad!r} в каноне"

    def test_prompt_is_russian_text(self):
        assert len(DREAM_DISTILL_PROMPT) > 400

    def test_json_contract_strict(self):
        """Правило 1: СТРОГО один JSON-объект; каждое убеждение опирается
        минимум на 2 факта (правило 2); пусто — {"beliefs":[]} или UNCHANGED."""
        assert '{"beliefs":[{"text":"...","evidence":[<номера фактов>]}]}' \
            in DREAM_DISTILL_PROMPT
        assert "минимум на 2 факта" in DREAM_DISTILL_PROMPT
        assert '{"beliefs":[]}' in DREAM_DISTILL_PROMPT


class TestBuildDreamUser:
    def test_numbered_rows_with_dates(self):
        rows = [
            {"id": 10, "fact": "вася не заплатил за пиво",
             "message_timestamp": 1_700_000_000, "importance": 4},
            {"id": 11, "fact": "вася снова не заплатил за пиво",
             "message_timestamp": None, "created_at": 1_700_000_000,
             "importance": 5},
        ]
        text = build_dream_user(rows)
        lines = text.splitlines()
        assert lines[0] == "Кластер фактов чата:"
        # сортировка по importance DESC (11 важнее 10)
        assert "1. [" in lines[1] and "вася снова" in lines[1]
        assert "2. [" in lines[2] and "вася не заплатил" in lines[2]
        assert re.search(r"\d{4}-\d{2}-\d{2}", lines[1]) is not None
        # дата берётся из message_timestamp (11) или created_at (10)
        assert "2023-11-14" in text or "2023-11-15" in text

    def test_bad_timestamp_fallback(self):
        text = build_dream_user([{"id": 1, "fact": "без даты",
                                  "message_timestamp": None,
                                  "created_at": None, "importance": 1}])
        assert "????-??-??" in text

    def test_max_facts_cap(self):
        rows = [{"id": i, "fact": f"факт номер {i}",
                 "message_timestamp": 1_700_000_000, "importance": 1}
                for i in range(10, 50)]
        text = build_dream_user(rows, max_facts=25)
        lines = text.splitlines()
        assert len(lines) == 26            # заголовок + 25 фактов
        # топ-25 по (importance, id) DESC → id 49..25
        assert lines[-1].endswith("факт номер 25")
        assert "факт номер 24" not in text

    def test_empty_rows(self):
        assert build_dream_user([]) == "Кластер фактов чата:"


class TestParseDistillAnswer:
    def test_valid_beliefs(self):
        out = parse_distill_answer(
            '{"beliefs":[{"text":"вася всегда платит за всех",'
            '"evidence":[1,2]}]}', [10, 11, 12])
        assert out == [{"text": "вася всегда платит за всех",
                        "evidence": [10, 11]}]

    def test_fenced_json_and_markdown_text(self):
        raw = '```json\n{"beliefs":[{"text":"петя не любит кошек",' \
              '"evidence":[3,1]}]}\n```'
        out = parse_distill_answer(raw, [10, 11, 12])
        assert out[0]["evidence"] == [10, 12]    # порядок по фактам

    def test_unchanged_and_empty_beliefs(self):
        for raw in ("UNCHANGED", " unchanged ", "Unchanged",
                    '{"beliefs":[]}', '{"beliefs": []}'):
            assert parse_distill_answer(raw, [10, 11]) == []

    def test_bad_json_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_distill_answer("это не json", [10, 11])
        with pytest.raises(ValueError):
            parse_distill_answer("", [10, 11])
        with pytest.raises(ValueError):
            parse_distill_answer('{"no_beliefs":1}', [10, 11])
        with pytest.raises(ValueError):
            parse_distill_answer('[1,2,3]', [10, 11])

    def test_evidence_out_of_range_dropped(self):
        """evidence-номера вне списка отбрасываются (spec §3.4.5); belief с
        < 2 реальными фактами НЕ пишется (анти-галлюцинации)."""
        out = parse_distill_answer(
            '{"beliefs":[{"text":"убеждение","evidence":[1,7,99]}]}',
            [10, 11])
        assert out == []

    def test_belief_with_less_than_two_sources_not_written(self):
        """belief с < 2 реальными фактами НЕ пишется (анти-галлюцинации)."""
        out = parse_distill_answer(
            '{"beliefs":[{"text":"без доказательств","evidence":[2]},'
            '{"text":"ок","evidence":[1,3]}]}', [10, 11, 12])
        assert out == [{"text": "ок", "evidence": [10, 12]}]

    def test_invalid_items_skipped(self):
        out = parse_distill_answer(
            '{"beliefs":[null,"x",{"text":"","evidence":[1,2]},'
            '{"text":"хорошее","evidence":[1,2],"extra":1}]}', [10, 11])
        assert out == [{"text": "хорошее", "evidence": [10, 11]}]
