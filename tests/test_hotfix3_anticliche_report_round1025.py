"""Хотфикс-3 (round10.25, T-2488…T-2493, ADR-1025-7 D2) — анти-клише:
честный отчёт о сохранении, ручные фразы не теряются, канон длины 2…120.

Падают на старом коде: `build_patterns_report`/`dropped` не существовали,
`build_patterns` тихо дропал ручную фразу «подводя итог», а API принимал
фразы длиной до 500 символов.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from services import anticliche_cache as ac
from services import anticliche_worker as aw
from services.negative_constraints import DYNAMIC_PHRASE_MAX
from web.api.anticliche import PatternIn


# ── build_patterns_report: честная разбивка (T-2489) ─────────────────────────

class TestBuildPatternsReport:
    def test_breakdown_by_reason(self):
        report = aw.build_patterns_report([
            {"phrase": "подводя итог"},        # хардкод-клише
            {"phrase": "свежая фраза"},        # ok
            {"phrase": "Свежая   фраза"},      # дубль (нормализация)
            {"phrase": "a"},                   # invalid (короткая)
            {"phrase": "я" * 200},             # invalid (> канон 120)
        ], max_patterns=50)

        assert report["count"] == 1
        assert [p["phrase"] for p in report["saved"]] == ["свежая фраза"]
        assert report["dropped"]["hardcoded"] == ["подводя итог"]
        assert report["dropped"]["duplicate"] == ["свежая фраза"]
        assert len(report["dropped"]["invalid"]) == 2
        assert report["dropped"]["over_limit"] == []
        assert report["total"] == 5

    def test_over_limit_reported(self):
        entries = [{"phrase": f"фраза номер {i}"} for i in range(5)]
        report = aw.build_patterns_report(entries, max_patterns=2)
        assert report["count"] == 2
        assert len(report["dropped"]["over_limit"]) == 3

    def test_build_patterns_wrapper_is_saved_only(self):
        out = aw.build_patterns([{"phrase": "живая фраза"}])
        assert [p["phrase"] for p in out] == ["живая фраза"]


# ── ручные фразы НЕ фильтруются хардкод-правилами (T-2490) ───────────────────

class TestManualSemantics:
    def test_manual_keeps_hardcoded_and_flags(self):
        report = aw.build_patterns_report(
            [{"phrase": "подводя итог"}], manual=True)
        assert report["count"] == 1
        assert report["saved"][0]["phrase"] == "подводя итог"
        assert report["dropped"]["hardcoded"] == []      # НЕ отброшено
        assert report["hardcoded_flagged"] == ["подводя итог"]

    def test_manual_still_limits_length_and_dupes(self):
        report = aw.build_patterns_report([
            {"phrase": "a"},
            {"phrase": "повтор"},
            {"phrase": "Повтор"},
        ], manual=True, max_patterns=10)
        assert [p["phrase"] for p in report["saved"]] == ["повтор"]
        assert len(report["dropped"]["invalid"]) == 1
        assert report["dropped"]["duplicate"] == ["повтор"]

    @pytest.mark.asyncio
    async def test_apply_manual_returns_honest_contract(self, monkeypatch):
        monkeypatch.setattr(aw.anticliche_cache, "write_patterns",
                            AsyncMock(return_value=7))
        result = await aw.apply_manual(
            object(), [{"phrase": "подводя итог"}, {"phrase": "a"}])

        assert result["status"] == "ok"
        assert result["source"] == "manual"
        assert result["count"] == 1
        assert result["saved"][0]["phrase"] == "подводя итог"
        assert result["dropped"]["invalid"]          # отчёт честный
        assert result["hardcoded_flagged"] == ["подводя итог"]


# ── канон длины 2…120 на входе API (T-2488) ──────────────────────────────────

class TestPhraseLengthCanon:
    def test_max_length_is_canon(self):
        assert PatternIn.model_fields["phrase"].metadata  # field ограничен
        # ровно канон — ок, на символ больше — понятная ошибка валидации
        assert PatternIn(phrase="я" * DYNAMIC_PHRASE_MAX).phrase
        with pytest.raises(ValidationError):
            PatternIn(phrase="я" * (DYNAMIC_PHRASE_MAX + 1))

    def test_canon_value_is_120(self):
        assert DYNAMIC_PHRASE_MAX == 120
