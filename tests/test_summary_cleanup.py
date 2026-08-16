"""Tests for services/summary_cleanup.py (T-218, R28-3)."""
import pytest

from services.summary_cleanup import REPLACEMENTS, cleanup_llm_text


class TestCleanup:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("«привет»", '"привет"'),
            ("открыли « а закрыли »", 'открыли " а закрыли "'),
            ("„цитата“", '"цитата"'),
            ("тире — длинное", "тире - длинное"),
            ("короткое – тире", "короткое - тире"),
        ],
    )
    def test_each_replacement_pair(self, raw, expected):
        assert cleanup_llm_text(raw) == expected

    def test_mixed_text_all_pairs(self):
        raw = "«ёлочки» и „лапки“ с тире — и ещё – одно"
        assert cleanup_llm_text(raw) == '"ёлочки" и "лапки" с тире - и ещё - одно'

    def test_clean_text_unchanged(self):
        text = 'уже чисто: "кавычки" и дефис - ок'
        assert cleanup_llm_text(text) == text

    def test_idempotent(self):
        raw = "«а» — «б»"
        once = cleanup_llm_text(raw)
        assert cleanup_llm_text(once) == once

    def test_empty_text(self):
        assert cleanup_llm_text("") == ""

    def test_replacements_structure(self):
        assert len(REPLACEMENTS) == 6
        for pair in REPLACEMENTS:
            assert isinstance(pair, tuple) and len(pair) == 2
            assert isinstance(pair[0], str) and isinstance(pair[1], str)
            assert pair[0] != pair[1]
