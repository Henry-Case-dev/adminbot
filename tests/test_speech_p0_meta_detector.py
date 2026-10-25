# -*- coding: utf-8 -*-
"""P0-CORRECTIVE §3: детектор мета-вступлений L2 не слепнет снова.

TEST-LIFECYCLE: CONTRACT
owner=P0-SPEECH/hotfix
why=замечание F2 ревью: прежний анализатор искал только с начала строки и
    давал `meta=[]` для «Ох бля… Ладно, глянул твои сообщения…». Здесь
    фиксируется контракт закоммиченного детектора на УЖЕ снятых raw:
    негативный контроль (5 из 8 ответов прогона 0428c271) и положительный
    (чистые ответы того же прогона и эталонные строки).
replace_when=если сменится набор evidence-raw или формат категорий.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "probes_full"))

import analyze_l2_meta as meta  # noqa: E402


def test_detector_self_check_controls_pass():
    """Негативный контроль 5/8 + положительный контроль + раздельные типы."""
    assert meta.self_check() == 0


def test_detector_catches_preamble_in_second_sentence():
    """Тип A1: эмоциональная первая фраза, анонс во второй — не слепое пятно."""
    rep = meta.analyze_text(
        "Ох бля, Макс, ну ты даёшь запрос. Ладно, глянул твои сообщения.\n\n"
        "Ты вступился за Костю.")
    assert rep["flagged"] is True
    assert rep["announce"] and rep["leadin"]
    assert rep["label"] == []


def test_detector_flags_report_label_as_separate_category():
    rep = meta.analyze_text("**Вердикт:** он не злобный, просто устал.")
    assert rep["label"] and rep["flagged"] is True
    assert rep["announce"] == []


def test_detector_ignores_user_quote_prefix():
    """Цитата пользователя в начале — не речь бота."""
    rep = meta.analyze_text(
        "«Давай разберём» — так ты сказал вчера. Теперь по делу: он не злой.")
    assert rep["flagged"] is False


def test_detector_clean_answer_stays_clean():
    rep = meta.analyze_text("Он не злобный, он просто устал от споров.")
    assert rep["flagged"] is False
    assert rep["meta"] == []
