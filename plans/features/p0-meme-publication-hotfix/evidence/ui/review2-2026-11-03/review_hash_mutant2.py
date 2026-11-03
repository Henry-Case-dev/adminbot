# -*- coding: utf-8 -*-
"""Reviewer mutation 2: only the JOURNAL system hash is falsified.

Real payload keeps its true hash; the journal claims a different one.
The parity assertion (`system_sha12` == sha256(sent system)) must fail.
"""
import pytest


@pytest.fixture(autouse=True)
def _break_journal_hash(monkeypatch):
    from services import meme_initiative as meme
    original = meme._speech_facts

    def fake(system, manifest, technique):
        facts = original(system, manifest, technique)
        facts = dict(facts or {})
        facts["system_sha12"] = "deadbeefcafe"
        return facts

    monkeypatch.setattr(meme, "_speech_facts", fake)
