# -*- coding: utf-8 -*-
"""Стенд P0 SPEECH: guard от `UnboundLocalError` и честный `rag_source`.

TEST-LIFECYCLE: REGRESSION
owner=P0-SPEECH/hotfix
why=живой прогон e0a46414 упал на `llm` (чтение на стр. 1030, присваивание на
    1072): RAG собрался дампом, L2 не вызвался, а `--self-check` этого не
    видел, потому что не вызывает `_run`. Здесь закреплён детерминированный
    AST-guard и требование к `rag_source` в сводке.
replace_when=если стенд переедет на другой способ проверки потока `_run`.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "probes_full"))

import harness_probe_full as H  # noqa: E402

BAD_SAMPLE = (
    "def run(args, result):\n"
    "    block, meta = make(result, llm=llm)\n"
    "    llm = build(args)\n"
    "    return block\n"
)
GOOD_SAMPLE = (
    "def run(args, result):\n"
    "    llm = build(args)\n"
    "    block, meta = make(result, llm=llm)\n"
    "    return block\n"
)


def test_harness_has_no_use_before_assignment():
    """Реальный файл стенда чист: имя не читается раньше присваивания."""
    with open(H.HARNESS_PATH, encoding="utf-8") as fh:
        assert H.unbound_local_findings(fh.read()) == []


def test_guard_catches_the_shipped_defect_shape():
    found = H.unbound_local_findings(BAD_SAMPLE)
    assert [f["name"] for f in found] == ["llm"]
    assert found[0]["line"] < found[0]["first_assign"]


def test_guard_does_not_flag_correct_order_or_scopes():
    assert H.unbound_local_findings(GOOD_SAMPLE) == []
    scoped = (
        "def f(rows, param):\n"
        "    total = [x for x in rows]\n"          # включение: своя область
        "    def inner():\n"
        "        return late\n"                    # тело вызовется позже
        "    late = sum(total) + param\n"
        "    return inner, late\n"
    )
    assert H.unbound_local_findings(scoped) == []


def test_summary_reports_real_rag_source():
    for source in (H.RAG_SERVICE, H.RAG_DUMP):
        assert H.run_summary({"rag": {"rag_source": source}})[
            "rag_source"] == source
    # Отсутствие данных — явное «unreported», а не null в отчёте.
    assert H.run_summary({})["rag_source"] == "unreported"
