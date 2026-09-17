"""F2 (T-1954/T-1957, ADR-1021-2) — детерминированный grounding-валидатор.

Проверяем: сбор допустимых якорей; сохранение реальных тегов; жёсткое
вырезание фантомных (чужой id / чужой месяц / «голый» fact:ID); отсутствие
поломок на пустом/None-входе; R17 (логи без содержимого).
"""
import logging

from services.grounding_validator import (
    GroundingAnchors,
    StripStats,
    collect_allowed_anchors,
    strip_phantom_tags,
)

_EMPTY = GroundingAnchors(frozenset(), frozenset(), frozenset())


class TestCollectAllowedAnchors:
    def test_collects_ids_months_and_dates(self):
        anchors = collect_allowed_anchors(
            "факт fact:2574 в [04.2023 | Автор: Ваня], дата 2024-05-01")
        assert anchors.ids == frozenset({"2574"})
        assert anchors.months == frozenset({"04.2023"})
        assert anchors.dates == frozenset({"2024-05-01"})

    def test_multiple_and_dedup(self):
        anchors = collect_allowed_anchors("fact:1 fact:2 fact:1 [01.2020] [01.2020]")
        assert anchors.ids == frozenset({"1", "2"})
        assert anchors.months == frozenset({"01.2020"})

    def test_month_ignores_long_digit_runs(self):
        anchors = collect_allowed_anchors("число 104.20233 и 12.34567")
        assert anchors.months == frozenset()

    def test_empty_and_none_are_safe(self):
        assert collect_allowed_anchors("").ids == frozenset()
        assert collect_allowed_anchors(None).months == frozenset()


class TestStripPhantomTags:
    def test_phantom_tag_with_unknown_id_removed(self):
        out, stats = strip_phantom_tags(
            "бред [04.2023 | fact:2574] конец",
            collect_allowed_anchors("в контексте ничего нет"))
        assert "fact:2574" not in out
        assert "[04.2023" not in out
        assert "бред" in out and "конец" in out
        assert stats.stripped_phantom == 1
        assert stats.kept == 0

    def test_real_tag_kept(self):
        anchors = collect_allowed_anchors(
            "[04.2023 | Автор | fact:2574]: событие")
        out, stats = strip_phantom_tags(
            "см. [04.2023 | fact:2574] и всё", anchors)
        assert "[04.2023 | fact:2574]" in out
        assert stats.kept == 1
        assert stats.stripped_phantom == 0

    def test_known_id_but_unknown_month_removed(self):
        anchors = collect_allowed_anchors("fact:2574 [04.2023 | Автор]")
        out, stats = strip_phantom_tags("см. [11.2099 | fact:2574]", anchors)
        assert "fact:2574" not in out
        assert stats.stripped_phantom == 1

    def test_known_month_but_unknown_id_removed(self):
        anchors = collect_allowed_anchors("[04.2023 | Автор]")
        out, stats = strip_phantom_tags("[04.2023 | fact:9999]", anchors)
        assert "fact:9999" not in out
        assert stats.stripped_phantom == 1

    def test_multi_id_tag_removed_if_any_missing(self):
        anchors = collect_allowed_anchors("fact:1 [01.2020]")
        out, _ = strip_phantom_tags("[01.2020 | fact:1 | fact:2]", anchors)
        assert "fact:1" not in out and "fact:2" not in out

    def test_date_only_tag_without_fact_checked(self):
        # S10.21-4: метка с датой без `fact:ID` проверяется по контексту.
        out, stats = strip_phantom_tags(
            "верно [04.2024 | Автор: X] ок", _EMPTY)
        assert "[04.2024" not in out and "Автор" not in out
        assert stats == StripStats(0, 1, 0)
        kept, kept_stats = strip_phantom_tags(
            "верно [04.2024 | Автор: X] ок",
            collect_allowed_anchors("контекст 04.2024"))
        assert kept == "верно [04.2024 | Автор: X] ок"
        assert kept_stats.kept == 1

    def test_date_only_iso_tag_checked(self):
        out, stats = strip_phantom_tags(
            "факт [2024-05-01 | Иван]", _EMPTY)
        assert "2024-05-01" not in out
        assert stats.stripped_phantom == 1
        kept, _ = strip_phantom_tags(
            "факт [2024-05-01 | Иван]",
            collect_allowed_anchors("в контексте 2024-05-01"))
        assert "[2024-05-01 | Иван]" in kept

    def test_bracket_without_date_or_fact_untouched(self):
        out, stats = strip_phantom_tags("верно [Автор: X]", _EMPTY)
        assert out == "верно [Автор: X]"

    def test_plain_dates_untouched(self):
        out, stats = strip_phantom_tags("в 04.2024 было 12.2099", _EMPTY)
        assert out == "в 04.2024 было 12.2099"
        assert stats == StripStats(0, 0, 0)

    def test_bare_fact_id_outside_anchors_removed(self):
        anchors = collect_allowed_anchors("только fact:1")
        out, stats = strip_phantom_tags("foo fact:2 bar", anchors)
        assert out == "foo  bar"
        assert stats.stripped_bare == 1

    def test_bare_fact_id_inside_anchors_kept(self):
        anchors = collect_allowed_anchors("fact:7")
        out, stats = strip_phantom_tags("см. fact:7", anchors)
        assert out == "см. fact:7"
        assert stats.stripped_bare == 0

    def test_iso_date_tag(self):
        anchors = collect_allowed_anchors("fact:5 2024-05-01")
        out, stats = strip_phantom_tags("[2024-05-01 | fact:5]", anchors)
        assert "[2024-05-01 | fact:5]" in out and stats.kept == 1
        out2, stats2 = strip_phantom_tags("[2020-01-01 | fact:5]", anchors)
        assert "fact:5" not in out2 and stats2.stripped_phantom == 1

    def test_month_tag_matches_iso_month_in_context(self):
        # F2 fix-round 2: [01.2024 | fact:N] при наличии только ISO
        # 2024-01-01 в контексте — не фантом.
        anchors = collect_allowed_anchors("факт fact:7, дата 2024-01-01")
        out, stats = strip_phantom_tags("[01.2024 | fact:7]", anchors)
        assert "[01.2024 | fact:7]" in out and stats.kept == 1

    def test_month_tag_other_month_still_phantom(self):
        anchors = collect_allowed_anchors("факт fact:7, дата 2024-01-01")
        out, stats = strip_phantom_tags("[02.2024 | fact:7]", anchors)
        assert "fact:7" not in out and stats.stripped_phantom == 1

    def test_iso_date_tag_matches_month_in_context(self):
        anchors = collect_allowed_anchors("fact:7 [01.2024]")
        out, stats = strip_phantom_tags("[2024-01-15 | fact:7]", anchors)
        assert "[2024-01-15 | fact:7]" in out and stats.kept == 1

    def test_no_tags_is_noop(self):
        text = "чистый вердикт без тегов, но с датой 04.2024"
        out, stats = strip_phantom_tags(text, _EMPTY)
        assert out == text
        assert stats == StripStats(0, 0, 0)

    def test_empty_and_none_safe(self):
        assert strip_phantom_tags("", _EMPTY) == ("", StripStats(0, 0, 0))
        out, stats = strip_phantom_tags(None, _EMPTY)
        assert out == "" and stats == StripStats(0, 0, 0)

    def test_mixed_real_and_phantom(self):
        anchors = collect_allowed_anchors(
            "[04.2023 | Автор | fact:2574] fact:2574")
        text = ("реальный [04.2023 | fact:2574] и фантом "
                "[09.2099 | fact:8888]")
        out, stats = strip_phantom_tags(text, anchors)
        assert "[04.2023 | fact:2574]" in out
        assert "fact:8888" not in out
        assert stats.kept == 1 and stats.stripped_phantom == 1


class TestValidatorContract:
    def test_never_raises_on_weird_input(self):
        for bad in (None, "", "   ", "[]", "[fact:1", "fact:abc",
                    "[01.2020 | fact:]"):
            out, stats = strip_phantom_tags(bad, _EMPTY)
            assert isinstance(out, str)
            assert isinstance(stats, StripStats)

    def test_does_not_leak_content_to_logs(self, caplog):
        """R17: валидатор сам не логирует содержимое (только внешний counts-лог)."""
        with caplog.at_level(logging.DEBUG, logger="services.grounding_validator"):
            strip_phantom_tags(
                "секрет [04.2023 | fact:2574]", _EMPTY)
        assert caplog.records == []
