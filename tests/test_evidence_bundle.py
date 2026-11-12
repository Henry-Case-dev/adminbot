"""SELF-DIAG-01 D3 — контракт DiagnosticEvidenceBundle (ТЗ §10).

Проверяется логический контракт, а не внутренняя реализация: закрытые
наборы статусов/утверждений, раздельные declared/configured/probe_succeeded/
healthy, observed_at как время измерения, coverage/continuation, редакция по
классам, совместимость с существующими mca_events/provenance и отсутствие
второй БД.
"""
import json
import time
from pathlib import Path

import pytest

from services import evidence_bundle as eb
from services import mca_events
from services import provenance


def _source(**over):
    data = {
        "kind": "logs",
        "status": eb.STATUS_OK,
        "observed_at": "2026-11-13T00:00:00+00:00",
        "source_id": "logs:local",
        "owner": "journal",
        "scope": "instance",
        "latency_ms": 12,
        "coverage": eb.coverage(("local_logs",), complete=True),
        "reason_code": None,
        "declared": True,
        "configured": True,
        "probe_succeeded": True,
        "healthy": None,
        "facts": {"window_lines": 3},
        "not_checked": ("journal_contents",),
        "redaction": eb.redaction(0, ()),
    }
    data.update(over)
    return eb.SourceEvidence(**data)


def _bundle(sources=None, claims=None, **over):
    data = {
        "request_id": "req-1",
        "chat_scope": "current_chat",
        "scope": "current_chat",
        "sources": sources or [_source()],
        "claims": claims or [],
        "access": {"resource_scope": "current_chat"},
        "observed_at": "2026-11-13T00:00:00+00:00",
        "latency_ms": 7,
        "runtime": {"service_identity": "unknown"},
    }
    data.update(over)
    return eb.build_bundle(**data)


class TestStatusVocabulary:
    def test_closed_set_of_nine(self):
        assert eb.STATUSES == (
            "ok", "degraded", "unavailable", "permission_denied",
            "not_configured", "stale", "unsupported", "unknown",
            "not_checked")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError):
            _source(status="healthy")

    def test_aggregation_deterministic(self):
        assert eb.aggregate_status(["ok", "ok"]) == eb.STATUS_OK
        assert eb.aggregate_status(["ok", "unavailable"]) == \
            eb.STATUS_DEGRADED
        assert eb.aggregate_status(["unavailable", "degraded"]) == \
            eb.STATUS_DEGRADED
        assert eb.aggregate_status([]) == eb.STATUS_NOT_CHECKED
        assert eb.aggregate_status(["not_checked"]) == eb.STATUS_NOT_CHECKED
        assert eb.aggregate_status(["weird"]) == eb.STATUS_UNKNOWN

    def test_permission_denied_wins(self):
        assert eb.aggregate_status(
            ["permission_denied", "unavailable", "ok"]) == \
            eb.STATUS_PERMISSION_DENIED


class TestBundleContract:
    def test_all_contract_fields_present(self):
        payload = _bundle().to_dict()
        for field in eb.BUNDLE_FIELDS:
            assert field in payload, field
        source = payload["sources"][0]
        for field in ("observed_at", "source_id", "owner", "scope", "status",
                      "coverage", "latency_ms", "reason_code", "declared",
                      "configured", "probe_succeeded", "healthy",
                      "not_checked"):
            assert field in source, field
        assert payload["status"] == eb.STATUS_OK
        json.dumps(payload)     # сериализуемость

    def test_four_availability_states_are_distinct(self):
        source = _source(declared=True, configured=True,
                         probe_succeeded=False, healthy=None)
        payload = source.to_dict()
        assert payload["declared"] is True
        assert payload["configured"] is True
        assert payload["probe_succeeded"] is False
        assert payload["healthy"] is None
        # Ни одно состояние не выводится из другого автоматически.
        assert not (payload["declared"] and payload["probe_succeeded"])
        unhealthy = _source(healthy=False).to_dict()
        assert unhealthy["healthy"] is False
        assert unhealthy["probe_succeeded"] is True

    def test_observed_at_is_measurement_time_not_render_time(self):
        moment = eb.utc_now_iso(1_700_000_000)
        bundle = _bundle(observed_at=moment)
        assert bundle.to_dict()["observed_at"] == moment
        rendered = bundle.to_dict()["observed_at"]
        assert rendered == moment
        assert "latency_ms" in bundle.to_dict()

    def test_claims_are_deduplicated_and_closed(self):
        observed = eb.claim(eb.CLAIM_OBSERVED, "fact", ["logs:local"])
        bundle = _bundle(claims=[observed, dict(observed)])
        assert len(bundle.claims) == 1
        with pytest.raises(ValueError):
            eb.claim("guess", "x")
        payload = bundle.to_dict()
        assert payload["claims"][0]["kind"] == "observed"
        assert "confidence" not in payload["claims"][0]
        assert "confidence" not in json.dumps(payload["claims"])

    def test_hypothesis_requires_no_percentages(self):
        item = eb.claim(eb.CLAIM_HYPOTHESIS, "possible cause",
                        ["logs:local"], ["late_commit_not_blamed"])
        assert item["kind"] == "hypothesis"
        assert item["limitations"] == ["late_commit_not_blamed"]
        assert "%" not in item["statement"]

    def test_redaction_count_by_class(self):
        report = eb.redaction(3, ("secret_value", "bearer"))
        assert report["performed"] is True
        assert report["redacted_fields"] == 3
        assert report["classes"] == ["bearer", "secret_value"]
        assert "value" not in report

    def test_source_ref_uses_existing_provenance_contract(self):
        ref = eb.source_ref(store="sqlite", entity_type="message",
                            entity_id="42", chat_id=-100,
                            tg_message_id=42)
        expected_keys = set(provenance.SourceRef(
            store="sqlite", entity_type="message", entity_id="42",
            chat_id=-100, tg_message_id=42).as_dict())
        assert set(ref) == expected_keys
        assert ref["store"] in provenance.STORES
        assert ref["entity_type"] in provenance.ENTITY_TYPES
        with pytest.raises(ValueError):
            eb.source_ref(store="runtime", entity_type="probe",
                          entity_id="x")

    def test_mca_event_projection_uses_only_existing_fields(self):
        fields = _bundle().mca_event_fields()
        event = mca_events.build_event(
            "inspect_runtime_called", outcome="success", **fields)
        assert event is not None
        assert event["event_name"] == "inspect_runtime_called"
        for key in event:
            assert key in mca_events.ALLOWED_FIELDS
        # Неизвестное поле не создаёт «теневое» расширение контракта.
        event2 = mca_events.build_event(
            "inspect_runtime_called", outcome="success",
            unknown_field="x", **fields)
        assert event2 is not None and "unknown_field" not in event2

    def test_coverage_marks_partial_and_truncation(self):
        cov = eb.coverage(("logs",), complete=False, truncated=True,
                          why="fallback_source")
        assert cov["state"] == "partial"
        assert cov["truncated"] is True
        assert cov["why"] == "fallback_source"


class TestStackSummary:
    def _traceback(self, frames=12):
        lines = ["Traceback (most recent call last):"]
        for index in range(frames):
            lines.append(
                f'  File "/app/services/stage_{index}.py", line {index + 10}, '
                f'in handler_{index}')
            lines.append("    return process(item)")
        lines.append("RuntimeError: provider timeout at stage 11")
        return "\n".join(lines)

    def test_frames_and_continuation_not_dumb_truncation(self):
        text = self._traceback()
        first = eb.stack_summary(text, budget_chars=700)
        assert first["frame_count"] == 12
        assert 0 < first["shown_frames"] < 12
        assert first["next_cursor"].startswith("frame:")
        shown_indexes = {f["index"] for f in first["frames"]}
        assert 11 not in shown_indexes       # хвост не влез в первую страницу
        page = first
        seen = set(shown_indexes)
        while page["next_cursor"]:
            page = eb.stack_summary(text, budget_chars=700,
                                    cursor=page["next_cursor"])
            seen |= {f["index"] for f in page["frames"]}
        assert 11 in seen
        assert first["exception"]["type"] == "RuntimeError"
        assert first["raw_chars"] == len(text)
        assert first["coverage"]["truncated"] is True

    def test_budget_shrinks_page_but_keeps_structure(self):
        text = self._traceback(frames=4)
        page = eb.stack_summary(text, budget_chars=260)
        assert page["status"] == "ok"
        assert len(page["frames"]) >= 1
        assert all("file" in f and "line" in f and "function" in f
                   for f in page["frames"])

    def test_unknown_or_bad_cursor_fails_closed(self):
        page = eb.stack_summary(self._traceback(2), cursor="nope")
        assert page["status"] == eb.STATUS_UNKNOWN
        assert page["reason_code"] == "unknown_cursor"
        assert page["frames"] == []

    def test_no_traceback_is_honest(self):
        page = eb.stack_summary("plain line without frames")
        assert page["status"] == eb.STATUS_NOT_CHECKED
        assert page["frame_count"] == 0
        assert page["reason_code"] == "no_traceback_frames"

    def test_bearer_value_is_sanitized(self):
        text = (
            "Traceback (most recent call last):\n"
            '  File "/app/x.py", line 1, in call\n'
            "Authorization: Bearer sk-live-abcdef1234567890\n"
            "RuntimeError: auth failed")
        page = eb.stack_summary(text)
        blob = json.dumps(page)
        assert "abcdef1234567890" not in blob
        assert "Buckets" not in blob


class TestPageRendering:
    def _many_sources(self, count=20):
        return [
            _source(source_id=f"probe:{index}",
                    facts={"payload": "x" * 300, "index": index})
            for index in range(count)
        ]

    def test_pagination_keeps_every_source_retrievable(self):
        bundle = _bundle(sources=self._many_sources(20))
        page, next_offset = eb.render_page(bundle, max_chars=2500)
        assert next_offset < 20
        assert page["truncated"] is True
        shown = [s["source_id"] for s in page["sources"]]
        assert shown
        page2, next2 = eb.render_page(bundle, max_chars=2500, offset=next_offset)
        union = shown + [s["source_id"] for s in page2["sources"]]
        assert len(set(union)) == len(union)
        assert len(union) >= len(shown)
        assert page["coverage"]["output"]["state"] == "partial"

    def test_complete_page_has_no_cursor(self):
        page, next_offset = eb.render_page(_bundle(), max_chars=6000)
        assert next_offset == 1
        assert "next_cursor" not in page
        assert page["coverage"]["output"]["state"] == "complete"

    def test_facts_text_built_from_same_bundle(self):
        bundle = _bundle(sources=[
            _source(source_id="deploy:identity",
                    facts={"deployed_sha": "abc", "dirty": False})])
        text = eb.render_facts_text(bundle)
        assert text.startswith("DIAGNOSTIC_EVIDENCE status=ok")
        assert "deploy:identity" in text
        assert "deployed_sha=abc" in text


class TestNoSecondStore:
    def test_module_has_no_ddl_or_writes(self):
        source = Path("services/evidence_bundle.py").read_text(
            encoding="utf-8")
        for marker in ("CREATE TABLE", "INSERT INTO", "UPDATE ", "DELETE FROM",
                       "import sqlite3"):
            assert marker not in source, marker
