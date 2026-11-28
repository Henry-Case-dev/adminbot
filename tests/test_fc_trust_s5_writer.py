"""FCT-S5 U1 — даты в Writer payload (FCT-801), 28.11.2026.

Источник: `plans/features/fc-trust-01/evidence/fct-s5-s6-scoping-2026-11-28/
scoping.md` sha `e49fbf01…` §S5 + D-S5-1 (можно `factcheck_service.py`;
`factcheck_prompts.py` не трогать).

Проверяется наблюдаемый Writer payload `_temporal_verbalize`:

* дата публикации оригинала и фактические даты доказательств берутся ТОЛЬКО
  из уже собранных полей evidence U1 (`published_at_source`,
  `claim_valid_from/to`, `retrieved_at`, `original_posted_at`, `timezone`,
  `timestamp_source/confidence`);
* неизвестная дата не подменяется `now()`/текущим годом — поля просто нет;
* канон промптов не изменён (пин байтов `factcheck_prompts.py`).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from services import factcheck_service as fs
from services import temporal_factcheck as tf

CHAT_ID = -100777
PROMPT_CANON_SHA256 = (
    "4cd1e893d8c5fed8566ed242af1b1c54d90da91d71bd6dd7b782f1415dde1bb4")


def _env(**kwargs):
    base = dict(
        claim_id="c-1", chat_id=CHAT_ID, target_tg_message_id=900,
        target_revision=None, target_content_hash=None,
        trigger_tg_message_id=901,
        claim_text="в Килякете выпало 120 мм осадков за сутки",
        claim_span=None, source_type="text", attribution={},
        origin_type=None, origin_sender_user_id=None, origin_chat_id=None,
        origin_display_name=None, repost_received_at=None,
        original_published_at=None, original_published_precision=None,
        claim_period_from=None, claim_period_to=None,
        claim_period_precision=None, date_source="unknown",
        date_precision="unknown", date_timezone=None, date_uncertainty={},
        requested_mode="contextual", analysis_as_of=1760900000)
    base.update(kwargs)
    return tf.TemporalClaimEnvelope(**base)


def _verdict(**kwargs):
    base = dict(
        factual_verdict="refuted", temporal_status="unknown",
        evaluated_period={"from": None, "to": None, "precision": "unknown"},
        assessment_mode="contextual", as_of=1760900000,
        evidence_refs=("ev-1",), uncertainty={}, parts=(), reason=None)
    base.update(kwargs)
    return tf.TemporalVerdict(**base)


class _Capture:
    def __init__(self):
        self.messages = None

    async def __call__(self, _generate, messages, **kwargs):
        self.messages = messages
        return "готовый ответ", {"attempts": 1, "retries": 0, "hits": [],
                                 "fallback": False}


async def _writer_payload(monkeypatch, evidence=(), env=None):
    cap = _Capture()
    monkeypatch.setattr(fs, "verbalize_validated", cap)

    async def _compose(chat_id, *, writer, base_prompt):
        return base_prompt

    async def _no_critique(chat_id, policy):
        return ""

    monkeypatch.setattr(fs, "_compose_genre_speech", _compose)
    monkeypatch.setattr(fs, "_critique_section_block", _no_critique)
    service = fs.FactCheckService(None, None, None)
    await service._temporal_verbalize(
        env or _env(), _verdict(), False, None, evidence=evidence)
    system, user = (m["content"] for m in cap.messages)
    assert user.startswith("ВЕРДИКТ (JSON):\n")
    return json.loads(user[len("ВЕРДИКТ (JSON):\n"):])


# ── FCT-801: известная дата доходит до Writer ──────────────────────────────

class TestKnownDates:
    @pytest.mark.asyncio
    async def test_known_dates_reach_writer_payload(self, monkeypatch):
        evidence = ({
            "evidence_id": "ev-1",
            "url": "https://example.org/a",
            "published_at": 1767225600,          # 01.01.2026 UTC
            "published_at_source": "page",
            "original_posted_at": 1735689600,    # 01.01.2025 UTC
            "claim_valid_from": 1767225600,
            "claim_valid_to": 1767312000,        # 02.01.2026 UTC
            "retrieved_at": 1767398400,          # 03.01.2026 UTC
            "timezone": "Europe/Moscow",
            "timestamp_source": "page",
            "timestamp_confidence": "high",
        },)
        payload = await _writer_payload(monkeypatch, evidence)
        assert payload["dates"]["original_publication"] == "01.01.2025"
        assert payload["dates"]["evidence"] == [{
            "evidence_id": "ev-1",
            "published_at": "01.01.2026",
            "original_posted_at": "01.01.2025",
            "claim_period": "с 01.01.2026 по 02.01.2026",
            "retrieved_at": "03.01.2026",
            "timezone": "Europe/Moscow",
            "date_source": "со страницы",
            "date_confidence": "высокая",
        }]
        # технические коды оси дат не публикуются Writer'у
        encoded = json.dumps(payload, ensure_ascii=False)
        for code in ("json_ld", "html_meta", "date_parse_failed", "unknown",
                     "planner_fetch", "timestamp_confidence"):
            assert code not in encoded

    @pytest.mark.asyncio
    async def test_envelope_original_date_used_when_evidence_silent(
            self, monkeypatch):
        env = _env(original_published_at=1735689600)
        payload = await _writer_payload(monkeypatch, evidence=(), env=env)
        assert payload["dates"] == {"original_publication": "01.01.2025"}

    @pytest.mark.asyncio
    async def test_medium_confidence_is_humanized(self, monkeypatch):
        evidence = ({
            "evidence_id": "ev-1",
            "url": "https://example.org/a",
            "published_at": 1767225600,
            "published_at_source": "provider",
            "timestamp_confidence": "medium",
        },)
        payload = await _writer_payload(monkeypatch, evidence)
        item = payload["dates"]["evidence"][0]
        assert item["date_source"] == "из поисковой выдачи"
        assert item["date_confidence"] == "средняя"
        assert "provider" not in json.dumps(payload, ensure_ascii=False)


# ── FCT-801: неизвестная дата остаётся неизвестной ─────────────────────────

class TestUnknownDates:
    @pytest.mark.asyncio
    async def test_unknown_dates_add_no_field_and_no_now(self, monkeypatch):
        evidence = ({
            "evidence_id": "ev-1",
            "url": "https://example.org/a",
            "published_at": None,
            "published_at_source": None,
            "original_posted_at": None,
            "claim_valid_from": None,
            "claim_valid_to": None,
            "retrieved_at": None,
            "timezone": "",
            "timestamp_source": "",
            "timestamp_confidence": "unknown",
        },)
        payload = await _writer_payload(monkeypatch, evidence)
        assert "dates" not in payload
        assert "01.01.2026" not in json.dumps(payload, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_retrieval_date_never_replaces_publication_date(
            self, monkeypatch):
        """Фактический момент получения не выдаётся за дату публикации."""
        evidence = ({
            "evidence_id": "ev-1",
            "url": "https://example.org/a",
            "published_at": None,
            "original_posted_at": None,
            "retrieved_at": 1767225600,          # 01.01.2026 UTC
            "timestamp_source": "",
            "timestamp_confidence": "unknown",
        },)
        payload = await _writer_payload(monkeypatch, evidence)
        assert "original_publication" not in payload["dates"]
        item = payload["dates"]["evidence"][0]
        assert "published_at" not in item
        assert "original_posted_at" not in item
        assert item["retrieved_at"] == "01.01.2026"

    @pytest.mark.asyncio
    async def test_rows_without_url_do_not_become_publication_dates(
            self, monkeypatch):
        evidence = ({
            "evidence_id": "ev-1",
            "url": None,
            "published_at": 1735689600,
            "original_posted_at": 1735689600,
        },)
        payload = await _writer_payload(monkeypatch, evidence)
        assert "dates" not in payload


# ── D-S5-1: канон промптов не изменён ─────────────────────────────────────

class TestPromptCanonUntouched:
    def test_factcheck_prompts_bytes_unchanged(self):
        data = open("services/factcheck_prompts.py", "rb").read()
        assert hashlib.sha256(data).hexdigest() == PROMPT_CANON_SHA256

    @pytest.mark.asyncio
    async def test_writer_payload_introduces_no_new_instruction_text(
            self, monkeypatch):
        """Даты — данные payload, а не новая инструкция модели."""
        cap = _Capture()
        monkeypatch.setattr(fs, "verbalize_validated", cap)

        async def _compose(chat_id, *, writer, base_prompt):
            return base_prompt

        async def _no_critique(chat_id, policy):
            return ""

        monkeypatch.setattr(fs, "_compose_genre_speech", _compose)
        monkeypatch.setattr(fs, "_critique_section_block", _no_critique)
        service = fs.FactCheckService(None, None, None)
        await service._temporal_verbalize(
            _env(), _verdict(), False, None,
            evidence=({"evidence_id": "ev-1", "url": "https://e.org/a",
                       "published_at": 1767225600},))
        system = cap.messages[0]["content"]
        assert "FCT-801" not in system
        assert "дата публикации оригинала" not in system
        assert "server_time" not in system
