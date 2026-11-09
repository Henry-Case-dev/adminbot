"""Управляемый источник случайности для тестов QND-NONDET (не тест-модуль).

Контракт §7: «controlled RandomSource, no wall-clock races». Повторяет
интерфейс `RandomSourceService` (`draw_probability`/`draw_index`) и возвращает
ЗАДАННУЮ последовательность значений: тест проверяет поведение механизма под
конкретными квантовыми значениями, а не «повезло/не повезло».
"""
from __future__ import annotations

import itertools
from types import SimpleNamespace


class FakeQuantumSource:
    """Последовательность значений `[0,1)` на каждый draw.

    * ``values`` — очередь значений; пусто → ``default``;
    * ``deferred_reason`` — источник не выдал значение (провайдер недоступен);
    * ``error`` — исключение из draw;
    * ``source`` — фактический источник в результате (quantum / pseudorandom).
    """

    def __init__(self, values=(), *, default=0.0, deferred_reason=None,
                 fallback_reason=None, source="quantum",
                 provider="ANU Quantum Numbers", error=None,
                 indices=()):
        self.values = list(values)
        self.default = default
        self.deferred_reason = deferred_reason
        self.fallback_reason = fallback_reason
        self.source = source
        self.provider = provider
        self.error = error
        self.indices = list(indices)
        self.calls: list[dict] = []
        self._counter = itertools.count(1)

    # ── интерфейс RandomSourceService ────────────────────────────────────
    def _result(self, *, value=None, index=None, deferred=False,
                reason=None) -> SimpleNamespace:
        number = next(self._counter)
        return SimpleNamespace(
            index=index,
            value=value,
            source=(self.source if not deferred else "pseudorandom"),
            selected_source=self.source,
            provider=(self.provider if not deferred else None),
            batch_id=None,
            draw_id=(None if deferred else f"fake-draw-{number}"),
            fallback_reason=(self.fallback_reason if not deferred
                             else reason),
            reason=reason,
            deferred=deferred,
            source_impl=("anu-quantum" if self.source == "quantum" else None),
            policy_version="qnd-test",
            attempts=1,
        )

    async def draw_probability(self, *, chat_id=None, purpose="",
                               policy_version=None, probability=None):
        self.calls.append({"kind": "probability", "chat_id": chat_id,
                           "purpose": str(purpose or ""),
                           "probability": probability})
        if self.error is not None:
            raise self.error
        if self.deferred_reason is not None:
            return self._result(deferred=True, reason=self.deferred_reason)
        value = self.values.pop(0) if self.values else self.default
        return self._result(value=float(value))

    async def draw_index(self, n, *, chat_id=None, purpose="",
                         policy_version=None, candidates=None,
                         probability=None):
        self.calls.append({"kind": "index", "n": n, "chat_id": chat_id,
                           "purpose": str(purpose or ""),
                           "candidates": list(candidates or [])})
        if self.error is not None:
            raise self.error
        if self.deferred_reason is not None:
            return self._result(deferred=True, reason=self.deferred_reason)
        index = self.indices.pop(0) if self.indices else 0
        return self._result(index=int(index), value=int(index))

    # ── удобства для проверок ────────────────────────────────────────────
    def purposes(self, kind: str = "probability") -> list[str]:
        return [c["purpose"] for c in self.calls if c["kind"] == kind]

    def count(self, purpose: str | None = None) -> int:
        if purpose is None:
            return len(self.calls)
        return len([c for c in self.calls if c["purpose"] == purpose])


class RaisingModules:
    """Патч «псевдослучайность запрещена» (§7: no PRNG in semantic paths)."""

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch

    def __enter__(self):
        import random
        import secrets

        def _boom(*args, **kwargs):
            raise AssertionError("pseudorandom запрещён в семантическом пути")

        self._monkeypatch.setattr(random, "random", _boom)
        self._monkeypatch.setattr(random, "randint", _boom)
        self._monkeypatch.setattr(random, "choice", _boom)
        self._monkeypatch.setattr(random, "randrange", _boom)
        self._monkeypatch.setattr(secrets, "randbelow", _boom)
        return self

    def __exit__(self, *exc):
        return False
