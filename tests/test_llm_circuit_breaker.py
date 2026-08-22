"""Epic 53 (Section 62.3, тест-план 62.5 #10): конечный автомат LLMCircuitBreaker.

CLOSED → (threshold транзиентных фейлов подряд) → OPEN (кулдаун) → HALF_OPEN
(ровно одна пробная генерация) → CLOSED/OPEN. Время — мок time.monotonic
(прецедент fake_time из test_direct_chat.py).
"""
import logging

import pytest

from services.llm_circuit_breaker import (
    LLMCircuitBreaker,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
)


@pytest.fixture
def fake_time(monkeypatch):
    """Заменяем time.monotonic() в llm_circuit_breaker на управляемый счётчик."""
    state = {"now": 1000.0}

    class FakeTime:
        @staticmethod
        def monotonic():
            return state["now"]

    monkeypatch.setattr("services.llm_circuit_breaker.time", FakeTime)
    return state


class TestStateMachine:
    def test_closed_allows_requests(self):
        cb = LLMCircuitBreaker()
        assert cb.state == STATE_CLOSED
        assert cb.allow_request() is True

    def test_failures_below_threshold_stay_closed(self):
        cb = LLMCircuitBreaker(failure_threshold=3)
        cb.on_failure()
        cb.on_failure()
        assert cb.state == STATE_CLOSED
        assert cb._failures == 2
        assert cb.allow_request() is True

    def test_three_failures_open(self, fake_time):
        cb = LLMCircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
        cb.on_failure()
        cb.on_failure()
        cb.on_failure()
        assert cb.state == STATE_OPEN
        assert cb.allow_request() is False

    def test_open_blocks_until_cooldown_expiry(self, fake_time):
        cb = LLMCircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
        for _ in range(3):
            cb.on_failure()
        fake_time["now"] += 299.0
        assert cb.allow_request() is False          # кулдаун ещё идёт
        fake_time["now"] += 1.0
        assert cb.allow_request() is True           # истёк → half-open проба

    def test_half_open_allows_exactly_one_probe(self, fake_time):
        cb = LLMCircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
        for _ in range(3):
            cb.on_failure()
        fake_time["now"] += 300.0
        assert cb.allow_request() is True           # пробная генерация
        assert cb.state == STATE_HALF_OPEN
        assert cb.allow_request() is False          # вторая — отказ до результата

    def test_probe_success_closes_and_resets(self, fake_time):
        cb = LLMCircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
        for _ in range(3):
            cb.on_failure()
        fake_time["now"] += 300.0
        assert cb.allow_request() is True
        cb.on_success()
        assert cb.state == STATE_CLOSED
        assert cb._failures == 0
        assert cb.allow_request() is True

    def test_probe_failure_reopens_with_new_cooldown(self, fake_time):
        cb = LLMCircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)
        for _ in range(3):
            cb.on_failure()
        fake_time["now"] += 300.0
        assert cb.allow_request() is True           # проба
        cb.on_failure()                             # проба упала
        assert cb.state == STATE_OPEN               # снова OPEN
        fake_time["now"] += 299.0
        assert cb.allow_request() is False          # НОВЫЙ кулдаун (не старый)
        fake_time["now"] += 1.0
        assert cb.allow_request() is True

    def test_success_resets_counter_below_threshold(self):
        cb = LLMCircuitBreaker(failure_threshold=3)
        cb.on_failure()
        cb.on_failure()
        cb.on_success()
        assert cb.state == STATE_CLOSED
        assert cb._failures == 0

    def test_failures_capped_at_threshold(self, fake_time):
        """L3: счётчик нормализуется порогом и не растёт бесконечно."""
        cb = LLMCircuitBreaker(failure_threshold=3)
        for _ in range(10):
            cb.on_failure()
        assert cb._failures == 3
        assert cb.state == STATE_OPEN

    def test_custom_threshold_and_zero_cooldown(self, fake_time):
        cb = LLMCircuitBreaker(failure_threshold=2, cooldown_seconds=0.0)
        cb.on_failure()
        assert cb.state == STATE_CLOSED
        cb.on_failure()
        assert cb.state == STATE_OPEN
        assert cb.allow_request() is True           # кулдаун 0 → сразу half-open

    def test_open_logs_warning(self, fake_time, caplog):
        cb = LLMCircuitBreaker(failure_threshold=2)
        with caplog.at_level(logging.WARNING):
            cb.on_failure()
            cb.on_failure()
        assert any("LLM CB opened | failures=2/2" in r.message for r in caplog.records)

    def test_half_open_transition_logs_info(self, fake_time, caplog):
        cb = LLMCircuitBreaker(failure_threshold=1, cooldown_seconds=10.0)
        cb.on_failure()
        fake_time["now"] += 10.0
        with caplog.at_level(logging.INFO):
            assert cb.allow_request() is True
        assert any("LLM CB half-open" in r.message for r in caplog.records)
