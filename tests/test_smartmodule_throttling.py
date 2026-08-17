"""Tests for services/smartmodule_throttling.py (T-257-B, Section 42.4/42.10).

CooldownTracker: dict-TTL per (chat, user), истечение, НЕЗАВИСИМОСТЬ двух
инстансов (search vs factcheck, D107). format_remaining_time: ТЗ-формат
«X мин Y сек» / «Z сек» (ceil-guard).
"""
import pytest

from services.smartmodule_throttling import CooldownTracker, format_remaining_time


@pytest.fixture
def fake_time(monkeypatch):
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.smartmodule_throttling.time", FakeTime)
    return state


class TestFormatRemainingTime:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0.0, "1 сек"),        # guard max(1, ceil)
            (0.4, "1 сек"),        # ceil вверх (T-257-B)
            (45.0, "45 сек"),
            (59.0, "59 сек"),
            (59.5, "1 мин"),       # ceil(59.5) = 60 → divmod(60, 60) = (1, 0)
            (60.0, "1 мин"),
            (90.0, "1 мин 30 сек"),
            (119.5, "2 мин"),      # ceil(119.5) = 120
            (125.0, "2 мин 5 сек"),
            (300.0, "5 мин"),
            (301.0, "5 мин 1 сек"),
        ],
    )
    def test_format_remaining_time(self, seconds, expected):
        assert format_remaining_time(seconds) == expected


class TestCooldownTracker:
    def test_remaining_zero_before_touch(self):
        tracker = CooldownTracker(300.0)
        assert tracker.remaining(1, 2) == 0.0

    def test_remaining_positive_after_touch(self, fake_time):
        tracker = CooldownTracker(300.0)
        tracker.touch(1, 2)
        fake_time["now"] += 30
        assert tracker.remaining(1, 2) == pytest.approx(270.0)

    def test_expires_after_ttl(self, fake_time):
        tracker = CooldownTracker(300.0)
        tracker.touch(1, 2)
        fake_time["now"] += 301
        assert tracker.remaining(1, 2) == 0.0

    def test_remaining_never_negative(self, fake_time):
        tracker = CooldownTracker(300.0)
        tracker.touch(1, 2)
        fake_time["now"] += 99999
        assert tracker.remaining(1, 2) == 0.0

    def test_key_is_chat_and_user(self, fake_time):
        tracker = CooldownTracker(300.0)
        tracker.touch(chat_id=1, user_id=10)
        assert tracker.remaining(1, 10) > 0
        assert tracker.remaining(2, 10) == 0.0
        assert tracker.remaining(1, 11) == 0.0

    def test_touch_updates_slot(self, fake_time):
        tracker = CooldownTracker(300.0)
        tracker.touch(1, 2)
        fake_time["now"] += 200
        tracker.touch(1, 2)   # повторный валидный триггер продлевает окно
        fake_time["now"] += 200
        assert tracker.remaining(1, 2) > 0

    def test_independence_of_two_instances(self, fake_time):
        """D107/T-257-B: touch search-трекера не влияет на factcheck-трекер и наоборот."""
        search_tracker = CooldownTracker(300.0)
        factcheck_tracker = CooldownTracker(300.0)
        search_tracker.touch(1, 2)
        assert search_tracker.remaining(1, 2) > 0
        assert factcheck_tracker.remaining(1, 2) == 0.0
        fake_time["now"] += 100
        factcheck_tracker.touch(1, 2)
        fake_time["now"] += 250   # итого +350 от слота search, +250 от слота factcheck
        # search истёк, factcheck — ещё жив (слоты в разных словарях)
        assert search_tracker.remaining(1, 2) == 0.0
        assert factcheck_tracker.remaining(1, 2) > 0

    def test_instances_have_separate_dicts(self):
        search_tracker = CooldownTracker(300.0)
        factcheck_tracker = CooldownTracker(300.0)
        search_tracker.touch(1, 2)
        assert search_tracker._last is not factcheck_tracker._last
        assert factcheck_tracker._last == {}
