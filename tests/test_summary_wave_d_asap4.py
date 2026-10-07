"""ASAP-4 волна D (epic `asap-4-embedding-graphrag-cover-runtime`, spec §4
D.1–D.10, ADR-1028-7 D3/D4/D5; T-4428…T-4437) — Hybrid L2 Writer/Reviewer
bounded revision loop.

Покрытие:
  * T-4428 (§50.3–§50.6, ADR D4): prompt migration prose-first — запрет
    цитат SUPERSEDED, канон/эталон байт-в-байт, ступень миграции R1028_ASAP4
    → R1029 + ROLLBACK (пин-тесты в test_summary_l2_writer; здесь —
    reviewer/reviser промпты и их эталон).
  * T-4429 (§50.7–§50.9): evidence_message_ids (refs из пакета; invented →
    validation error; shared evidence; ≥1 ref — мягкий сигнал Reviewer'у);
    participant roster (§50.8: дубли display-name по ID, aliases);
    relations kind msg|reply|forward|quote (§50.9, Q35).
  * T-4430 (§50.18/§50.19): deterministic validator ДО Reviewer — порядок,
    quote lookup, mechanical repair без LLM.
  * T-4431 (§50.10–§50.17, §50.26–§50.29): Semantic Reviewer — structured
    verdict, 15 codes §50.12, invalid findings отбрасываются, unknown >
    hallucinated, reviewer outage → review_degraded (fail-soft, ADR D3.5).
  * T-4432 (§50.22–§50.25, ADR D5): bounded revision ×2, patch-контракт
    replace_paragraphs (primary), full-doc escape-hatch, preserve,
    progress criterion, call budget ≤6 (golden M/J; ADR D3.3).
  * T-4433 (§50.30–§50.32): FactPackage grade + coverage map (topics/events).
  * T-4436 (§50.53/§50.54): publication_status ≠ pipeline_health;
    append-only stage events; успешный Legacy не стирает «L2 rejected →
    Legacy used» (Q36).
  * T-4437 (§50.58/§50.63): review metrics §50.58; golden A/D/E/F/G/H/L/M;
    kill-switch OFF-паритеты (SUMMARY_L2_REVIEW_ENABLED — single-call,
    SUMMARY_REVISION_PATCH_ENABLED — full-doc ветка bounded).

R17: в логах/метриках только числа/коды/id; тексты цитат/сообщений не
логируются.
"""
import json
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from services import mca_events as me
from services.summary_l2_review import (
    CALL_BUDGET_L2_STAGE,
    FINDING_CODES,
    METRIC_REVIEW_DEGRADED,
    REASON_L2_REVIEW_REJECTED,
    REASON_L2_REVIEW_UNUSABLE,
    apply_full_revision,
    apply_revision_patch,
    build_participant_roster,
    build_review_content,
    build_revision_content,
    l2_review_enabled,
    parse_review_verdict,
    resolve_l2_reviewer_slot,
    revision_patch_enabled,
    run_l2_with_review,
)
from services.summary_l2_writer import (
    REASON_INVALID_EVIDENCE,
    build_l2_input,
    package_message_id_space,
    run_l2,
    validate_l2_document,
)
from services.summary_legacy_fullwindow import compute_package_coverage
from services.summary_prompts import (
    SUMMARY_L2_REVIEWER_SYSTEM_PROMPT,
    SUMMARY_L2_REVISER_SYSTEM_PROMPT,
    SUMMARY_L2_WRITER_SYSTEM_PROMPT,
)

pytestmark = pytest.mark.asap4

RID = "asap4d-run-0001"
CHAT = -100266


@pytest.fixture(autouse=True)
def _wd_env(monkeypatch):
    """Волна D ON (прод-дефолты); conftest-изоляция держит флаги OFF для
    остальных тестов — сценарии зоны D доопределяют явно (паттерн C)."""
    _flag(monkeypatch, "SUMMARY_L2_REVIEW_ENABLED", True)
    _flag(monkeypatch, "SUMMARY_REVISION_PATCH_ENABLED", True)
    yield


def _flag(monkeypatch, name, value):
    """Патч флага на всех вариантах класса Settings (S10.18-10 reload)."""
    import config.settings as _cs
    import services.summary_l2_review as _rev
    import services.summary_l2_writer as _wr
    import services.summary_generator as _gen
    classes = {Settings, type(_cs.settings), type(_rev.settings),
               type(_wr.settings), type(_gen.settings)}
    for _cls in classes:
        monkeypatch.setattr(_cls, name, value, raising=False)


# ── Фикстуры пакета/документа/каналов ──────────────────────────────────────

def _frag(mid, author_id, name, text, *, reply_to=None, kind="msg",
          forward_source=None):
    entry = {"message_id": mid, "author_id": author_id, "display_name": name,
             "timestamp": 1000 + mid, "reply_to_id": reply_to, "kind": kind,
             "text": text}
    if forward_source:
        entry["forward_source"] = forward_source
    return entry


_DEF_FRAG_1 = _frag(101, 7001, "Тагир",
                    "клиентка перепутала толщину стенки с длиной")
_DEF_FRAG_2 = _frag(102, 7002, "Макс", "ну классика жанра", reply_to=101,
                    kind="reply")


def _package(*, fragments=None, facts=None, topic="тема дня"):
    return {
        "schema_version": 2, "status": "ok",
        "threads": [{
            "thread_id": "thread_001", "name": topic, "description": "",
            "chronology": [
                {"message_id": f["message_id"], "timestamp": f["timestamp"],
                 "topic_ids": ["thread_001"]}
                for f in (fragments if fragments is not None else
                          [_DEF_FRAG_1, _DEF_FRAG_2])
            ],
            "facts": facts or [
                {"text": "клиентка перепутала толщину стенки с длиной",
                 "evidence_message_ids": [101]},
                {"text": "обсудили классику жанра", "evidence_message_ids":
                 [102]},
            ],
            "evidence_ids": [101, 102],
            "fragments": fragments if fragments is not None else
            [_DEF_FRAG_1, _DEF_FRAG_2],
        }],
        "unassigned_message_ids": [],
        "service": {"response_mode": "serious", "cover_prompt": "",
                    "package_grade": "semantic"},
        "budget": {"kind": "tokens", "limit": 30000, "estimated": 42,
                   "fits": True},
    }


def _doc(*paragraphs, title="Спор о трубах", finale=None):
    doc = {"schema_version": 1, "title": title,
           "paragraphs": [{"text": t, "emphasis": None,
                           "emphasis_spans": [],
                           "evidence_message_ids": []} for t in paragraphs]}
    if finale:
        doc["finale"] = finale
    return doc


class WriterStub:
    """Канал Writer: возвращает готовый JSON-документ (ровно 1 вызов)."""

    def __init__(self, document: dict):
        self.document = document
        self.calls = 0

    async def __call__(self, messages):
        self.calls += 1
        return json.dumps(self.document, ensure_ascii=False)


class StageStub:
    """Скриптованный канал Reviewer/Revision: ответы по очереди."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.messages = []

    async def __call__(self, messages):
        self.calls += 1
        self.messages.append(messages)
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)


def _verdict(status, findings=None):
    return json.dumps({"status": status, "findings": findings or []},
                      ensure_ascii=False)


def _finding(code, index=0, refs=(101,), severity="blocking",
             instruction="исправь"):
    return {"code": code, "severity": severity, "paragraph_index": index,
            "evidence_refs": list(refs), "instruction": instruction}


def _patch(index_text_map, refs=None):
    return json.dumps({"replace_paragraphs": [
        {"index": i, "text": t,
         "evidence_message_ids": list((refs or {}).get(i, [101]))}
        for i, t in index_text_map.items()]}, ensure_ascii=False)


def _full_doc(document):
    return json.dumps(document, ensure_ascii=False)


# ══ T-4428: prompt migration prose-first (канон/эталон) ════════════════════

class TestPromptMigrationProseFirst:
    def test_reviewer_prompt_canon_discipline(self):
        """Reviewer/Reviser промпты — code-canonical, эталон содержит их
        байт-в-байт (правило project.md: эталоны только в canon/)."""
        from pathlib import Path
        canon = Path("plans/docs/canon/architecture.md").read_text(
            encoding="utf-8")
        assert SUMMARY_L2_REVIEWER_SYSTEM_PROMPT in canon
        assert SUMMARY_L2_REVISER_SYSTEM_PROMPT in canon

    def test_reviewer_prompt_semantics(self):
        """§50.10–§50.17/§50.26: reviewer не пишет статью; refs ⊆ package;
        unknown > hallucinated; style ≠ fact; числа high-risk; timeline;
        major topics; заголовок — factual surface."""
        p = SUMMARY_L2_REVIEWER_SYSTEM_PROMPT
        assert "НЕ пишешь новую статью" in p
        assert "нет доказательства - нет находки" in p
        assert "Unknown лучше выдуманной правки" in p
        assert "Ближайшее к цитате имя НЕ является доказательством" in p
        assert "high-risk" in p and "unsupported_number" in p
        assert "factual_overstatement" in p and "timeline_inconsistency" in p
        assert "major_topic_omitted" in p
        assert "заголовок проверяй как факт" in p
        # §50.26: стиль не бракуется.
        assert "мат, сарказм, иронию" in p
        # Пин (Rework-1 T-4438, L-ASAP4-D2): minor-находки сами по себе —
        # не основание для needs_fixes/Legacy; нет blocking → approved.
        assert "сами по себе - не основание для needs_fixes" in p
        assert "не переводят статью в Legacy" in p
        # Полный набор кодов §50.12 в промпте:
        for code in FINDING_CODES:
            assert code in p

    def test_reviser_prompt_preserve_contract(self):
        """§50.22: preserve-инструкция — исправить только необходимое,
        корректные абзацы сохранить, без новых фактов/имён/чисел/цитат."""
        p = SUMMARY_L2_REVISER_SYSTEM_PROMPT
        assert "только необходимые места" in p
        assert "Сохрани все корректные абзацы" in p
        assert "Не добавляй новых фактов, имён, чисел или цитат" in p
        assert "Не переписывай статью целиком" in p

    def test_supersede_no_contradicting_canons(self):
        """ADR-1028-7 Supersede register: двух противоречащих канонов нет —
        активный канон один, старый живёт только как PREV-слепок."""
        from services.summary_prompts import (
            PREV_SUMMARY_L2_WRITER_R1028_ASAP4,
        )
        assert "Прямые цитаты не приводи" not in SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "Прямые цитаты не приводи" in PREV_SUMMARY_L2_WRITER_R1028_ASAP4
        # PREV не входит в PROMPT_MIGRATIONS как new-канон нигде.
        from services.prompt_migrations import PROMPT_MIGRATIONS
        for _key, steps in PROMPT_MIGRATIONS.items():
            for _prev, new in steps:
                assert new != PREV_SUMMARY_L2_WRITER_R1028_ASAP4


# ══ T-4429: evidence-трассировка + roster + relations ══════════════════════

class TestEvidenceTracing:
    def test_id_space_covers_package_sources(self):
        ids = package_message_id_space(_package())
        assert ids == {101, 102}

    def test_valid_evidence_refs_kept(self):
        doc = _doc("Тагир рассказывал про клиентку.")
        doc["paragraphs"][0]["evidence_message_ids"] = [101]
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert document["paragraphs"][0]["evidence_message_ids"] == [101]
        assert metrics["evidence_refs_total"] == 1
        assert metrics["evidence_paragraphs"] == 1
        assert metrics["paragraphs_without_evidence"] == 0

    def test_invented_evidence_ref_is_validation_error(self):
        """§50.7: invented refs → validation error (fail-closed)."""
        doc = _doc("Текст.")
        doc["paragraphs"][0]["evidence_message_ids"] = [999]
        document, metrics = validate_l2_document(doc, _package())
        assert document is None
        assert metrics["reason"] == REASON_INVALID_EVIDENCE

    def test_bad_evidence_type_is_validation_error(self):
        doc = _doc("Текст.")
        doc["paragraphs"][0]["evidence_message_ids"] = "101"
        document, metrics = validate_l2_document(doc, _package())
        assert document is None
        assert metrics["reason"] == REASON_INVALID_EVIDENCE
        doc2 = _doc("Текст.")
        doc2["paragraphs"][0]["evidence_message_ids"] = [True]
        document2, metrics2 = validate_l2_document(doc2, _package())
        assert document2 is None
        assert metrics2["reason"] == REASON_INVALID_EVIDENCE

    def test_shared_evidence_and_multiple_refs_allowed(self):
        """§50.7: несколько refs на абзац + shared evidence между абзацами."""
        doc = _doc("Первый абзац.", "Второй абзац.")
        doc["paragraphs"][0]["evidence_message_ids"] = [101, 102]
        doc["paragraphs"][1]["evidence_message_ids"] = [101]
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert metrics["evidence_refs_total"] == 3
        assert document["paragraphs"][0]["evidence_message_ids"] == [101, 102]
        assert document["paragraphs"][1]["evidence_message_ids"] == [101]

    def test_paragraph_without_evidence_is_soft(self):
        """Абзацы без refs валидны (поле аддитивно); отсутствие — мягкий
        сигнал Reviewer (unsupported_claim по месту), не reject."""
        doc = _doc("Абзац без ссылок.")
        document, metrics = validate_l2_document(doc, _package())
        assert document is not None
        assert metrics["paragraphs_without_evidence"] == 1

    def test_evidence_refs_not_published(self):
        """§50.7: internal metadata — форматтер публикации поле игнорирует."""
        from services.summary_article_formatter import format_rich_html
        doc = _doc("Тагир рассказывал про клиентку.")
        doc["paragraphs"][0]["evidence_message_ids"] = [101]
        document, _ = validate_l2_document(doc, _package())
        html = format_rich_html(document)
        assert "101" not in html
        assert "Тагир рассказывал" in html

    def test_l2_input_carries_roster_and_relations(self):
        """§50.8/§50.9: Writer получает roster + kind/forward_source."""
        pkg = _package(fragments=[
            _frag(101, 7001, "Славик", "новость про биржу",
                  kind="forward", forward_source="РБК"),
            _frag(102, 7002, "Макс", "ну наконец-то", reply_to=101,
                  kind="reply"),
        ])
        content = build_l2_input(pkg)
        assert '"participants"' in content
        assert '"kind":"forward"' in content and '"forward_source"' in content
        assert '"kind":"reply"' in content
        # Ростер из фрагментов: author_id + display_name.
        assert '"author_id":7001' in content
        assert '"display_name":"Славик"' in content


class TestParticipantRoster:
    def test_roster_dedup_by_author_with_aliases(self):
        """§50.8/§50.43: смена display_name в окне — один человек с
        aliases; каноническое имя — первое в пакете."""
        pkg = _package(fragments=[
            _frag(101, 7001, "Лёха", "раз"),
            _frag(102, 7001, "Aleksey", "два"),
            _frag(103, 7001, "Лёха", "три"),
        ])
        roster = build_participant_roster(pkg)
        assert len(roster) == 1
        assert roster[0]["author_id"] == 7001
        assert roster[0]["display_name"] == "Лёха"
        assert roster[0]["aliases"] == ["Aleksey"]

    def test_same_display_names_not_merged(self):
        """§50.44: два разных author_id с одинаковым именем НЕ склеиваются
        (reviewer проверяет по ID; user-facing без тех-ID)."""
        pkg = _package(fragments=[
            _frag(101, 7001, "Лёха", "раз"),
            _frag(102, 7002, "Лёха", "два"),
        ])
        roster = build_participant_roster(pkg)
        assert len(roster) == 2
        assert {r["author_id"] for r in roster} == {7001, 7002}
        assert all(r["display_name"] == "Лёха" for r in roster)
        assert all(r["aliases"] == [] for r in roster)

    def test_roster_skips_fragments_without_author(self):
        pkg = _package(fragments=[
            _frag(101, 7001, "Вася", "текст"),
            {"message_id": 102, "author_id": None, "display_name": "?",
             "timestamp": 1, "reply_to_id": None, "kind": "msg",
             "text": "без автора"},
        ])
        roster = build_participant_roster(pkg)
        assert [r["author_id"] for r in roster] == [7001]


# ══ T-4431: Semantic Reviewer — вердикты и валидация findings ══════════════

class TestReviewVerdictParsing:
    def test_valid_verdict(self):
        verdict = parse_review_verdict(
            _verdict("needs_fixes", [_finding("wrong_person_attribution",
                                              index=1, refs=(101, 102))]),
            package=_package(), document=_doc("а", "б"))
        assert verdict.status == "needs_fixes"
        assert verdict.raw_status == "ok"
        assert len(verdict.findings) == 1
        f = verdict.findings[0]
        assert f.code == "wrong_person_attribution"
        assert f.severity == "blocking"
        assert f.paragraph_index == 1
        assert f.evidence_refs == (101, 102)
        assert verdict.blocking_count == 1

    def test_unknown_code_dropped(self):
        """§50.11: invalid findings отбрасываются (не валидируются)."""
        verdict = parse_review_verdict(
            _verdict("needs_fixes", [_finding("made_up_code"),
                                     _finding("unsupported_number")]),
            package=_package())
        assert len(verdict.findings) == 1
        assert verdict.findings[0].code == "unsupported_number"
        assert verdict.dropped_findings == 1

    def test_finding_with_invented_ref_dropped(self):
        """§50.11: finding валиден только с refs ⊆ package; invented ref →
        finding отброшен; needs_fixes без валидных findings → approved
        (основания нет; unknown > hallucinated)."""
        verdict = parse_review_verdict(
            _verdict("needs_fixes", [_finding("unsupported_number",
                                              refs=(999,))]),
            package=_package())
        assert verdict.status == "approved"
        assert verdict.findings == ()
        assert verdict.dropped_findings == 1

    def test_finding_without_refs_dropped(self):
        """§50.11 (M-ASAP4-D1 fix): находка с ПУСТЫМ или ОТСУТСТВУЮЩИМ
        evidence_refs недействительна так же, как с выдуманным ID —
        отбрасывается (лог L2_REVIEW_FINDING_DROPPED cause=missing_refs).
        Единственная находка без refs → needs_fixes без валидных → approved;
        валидная находка рядом сохраняется."""
        no_field = {"code": "unsupported_number", "severity": "blocking",
                    "paragraph_index": 0, "instruction": "исправь"}
        verdict = parse_review_verdict(
            _verdict("needs_fixes", [
                _finding("unsupported_number", index=0, refs=()),
                no_field,
                _finding("unsupported_number", index=1),
            ]),
            package=_package(), document=_doc("а", "б"))
        # Две бездоказательные отброшены, валидная (refs ⊆ package) жива.
        assert verdict.status == "needs_fixes"
        assert len(verdict.findings) == 1
        assert verdict.findings[0].evidence_refs == (101,)
        assert verdict.dropped_findings == 2
        # Единственная находка без refs → основания нет → approved.
        only_empty = parse_review_verdict(
            _verdict("needs_fixes",
                     [_finding("unsupported_number", refs=())]),
            package=_package())
        assert only_empty.status == "approved"
        assert only_empty.findings == ()
        assert only_empty.dropped_findings == 1

    def test_paragraph_index_out_of_range_dropped(self):
        verdict = parse_review_verdict(
            _verdict("needs_fixes", [_finding("unsupported_number", index=7)]),
            package=_package(), document=_doc("а"))
        assert verdict.status == "approved"

    def test_unknown_severity_defaults_blocking(self):
        verdict = parse_review_verdict(
            _verdict("needs_fixes", [_finding("unsupported_number",
                                              severity="критично")]),
            package=_package())
        assert verdict.findings[0].blocking is True

    def test_invalid_status_is_outage(self):
        verdict = parse_review_verdict(
            _verdict("почти ок"), package=_package())
        assert verdict.outage and verdict.raw_status == "invalid"

    def test_non_json_is_outage(self):
        verdict = parse_review_verdict("упс", package=_package())
        assert verdict.outage and verdict.reason == "review_invalid_json"

    def test_unusable_status_passes_through(self):
        verdict = parse_review_verdict(_verdict("unusable"),
                                       package=_package())
        assert verdict.status == "unusable" and not verdict.outage

    def test_fifteen_codes_minimal_set(self):
        """§50.12: полный минимальный набор кодов."""
        assert len(FINDING_CODES) == 15


# ══ T-4432: bounded revision loop + call budget ════════════════════════════

class TestBoundedRevisionLoop:
    @pytest.mark.asyncio
    async def test_golden_m_first_pass_approved_two_calls_no_rewrite(self):
        """Golden M: Writer good on first pass → Reviewer APPROVED →
        ровно 2 логических вызова (writer+reviewer), БЕЗ лишнего rewrite
        (документ байт-в-байт черновик; §50.x owner)."""
        document = _doc("Тагир рассказывал, что клиентка перепутала трубы.",
                        "Макс пошутил про классику жанра.")
        for p, refs in zip(document["paragraphs"], ([101], [102])):
            p["evidence_message_ids"] = list(refs)
        writer = WriterStub(document)
        reviewer = StageStub([_verdict("approved")])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=writer, reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "ok" and result.usable
        assert result.document["title"] == document["title"]
        assert writer.calls == 1 and reviewer.calls == 1
        m = result.metrics
        assert m["l2_first_pass_approved"] == 1
        assert m["l2_final_approved"] == 1
        assert m["l2_revision_count"] == 0
        assert m["l2_review_calls"] == 1 and m["l2_revision_calls"] == 0
        assert m["l2_review_findings_total"] == 0

    @pytest.mark.asyncio
    async def test_finding_without_refs_no_revision_first_pass_published(self):
        """M-ASAP4-D1 fix (§50.11, репро Reviewer): галлюцинированная
        blocking-находка БЕЗ evidence_refs отбрасывается как недоказуемая →
        needs_fixes без валидных находок = approved → споровая ревизия НЕ
        запускается, хорошая first-pass статья публикуется (не уходит в
        Legacy через «нет прогресса»)."""
        document = _doc("Тагир рассказывал, что клиентка перепутала трубы.",
                        "Макс пошутил про классику жанра.")
        for p, refs in zip(document["paragraphs"], ([101], [102])):
            p["evidence_message_ids"] = list(refs)
        writer = WriterStub(document)
        # Единственная находка ревьюера — без refs (пустой список).
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("unsupported_number", index=0,
                                              refs=())]),
        ])
        revision = StageStub([])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=writer, reviewer_call=reviewer, revision_call=revision)
        assert result.status == "ok" and result.usable
        # Статья опубликована байт-в-байт черновиком (никто её не трогал).
        assert result.document == document
        assert writer.calls == 1 and reviewer.calls == 1
        # Споровой ревизии НЕ было (находка отброшена — основания нет).
        assert revision.calls == 0
        m = result.metrics
        assert m["l2_first_pass_approved"] == 1
        assert m["l2_final_approved"] == 1
        assert m["l2_revision_count"] == 0
        assert m["l2_review_findings_total"] == 0
        assert m["l2_review_dropped_findings"] == 1
        assert m["l2_legacy_after_review"] == 0

    @pytest.mark.asyncio
    async def test_golden_a_reply_conflict_revision_fixes(self):
        """Golden A: reply conflict — неверная атрибуция (реплика ответа
        приписана не тому) → Reviewer needs_fixes (wrong_person_attribution,
        refs из пакета) → Revision #1 (patch) → Review approved. Ровно 4
        логических вызова."""
        document = _doc("Макс рассказал, что клиентка перепутала трубы.",
                        "Обсудили классику жанра.")
        document["paragraphs"][0]["evidence_message_ids"] = [101, 102]
        document["paragraphs"][1]["evidence_message_ids"] = [102]
        writer = WriterStub(document)
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("wrong_person_attribution",
                                              index=0, refs=(101,))]),
            _verdict("approved"),
        ])
        revised = _doc("Тагир рассказал, что клиентка перепутала трубы.",
                       "Обсудили классику жанра.")
        revised["paragraphs"][0]["evidence_message_ids"] = [101]
        revised["paragraphs"][1]["evidence_message_ids"] = [102]
        revision = StageStub([_patch({0: revised["paragraphs"][0]["text"]},
                                     refs={0: [101]})])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=writer, reviewer_call=reviewer, revision_call=revision)
        assert result.status == "ok"
        assert result.document["paragraphs"][0]["text"].startswith("Тагир")
        # Нетронутый абзац сохранён байт-в-байт (принцип §50.2).
        assert result.document["paragraphs"][1] == document["paragraphs"][1]
        assert writer.calls == 1 and reviewer.calls == 2
        assert revision.calls == 1
        m = result.metrics
        assert m["l2_first_pass_approved"] == 0
        assert m["l2_review_findings_total"] == 1
        assert m["l2_revision_count"] == 1
        assert m["l2_revision_fixed_count"] == 1
        assert m["l2_revision_new_findings"] == 0
        assert m["l2_final_approved"] == 1
        assert m["l2_legacy_after_review"] == 0
        # Бюджет ADR D3.3: happy/rev1 = 4 логических вызова.
        assert (m["l2_review_calls"] + m["l2_revision_calls"]) == 3

    @pytest.mark.asyncio
    async def test_golden_e_unsupported_number_revision(self):
        """Golden E: неподтверждённое число → Reviewer → Revision (patch;
        черновик из двух абзацев — находка на одном не majority)."""
        document = _doc("Тагир сказал, что возврат стоил 5000 рублей.",
                        "Тема закрылась сама собой.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        document["paragraphs"][1]["evidence_message_ids"] = [102]
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("unsupported_number", index=0,
                                              refs=(101,))]),
            _verdict("approved"),
        ])
        revision = StageStub([_patch(
            {0: "Тагир рассказал про возврат после путаницы с трубами."},
            refs={0: [101]})])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision)
        assert result.status == "ok"
        assert "5000" not in result.document["paragraphs"][0]["text"]
        assert result.metrics["l2_revision_count"] == 1
        assert result.metrics["l2_final_approved"] == 1

    @pytest.mark.asyncio
    async def test_golden_l_major_topic_omitted_goes_to_revision(self):
        """Golden L: Writer потерял крупную тему → Reviewer возвращает на
        Revision (major_topic_omitted); patch дописывает абзац (index ==
        len — append-расширение контракта ADR D5), не трогая первый."""
        document = _doc("Тагир рассказывал про клиентку.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("major_topic_omitted",
                                              index=None, refs=(102,))]),
            _verdict("approved"),
        ])
        revision = StageStub([_patch(
            {1: "Макс отреагировал классикой жанра."}, refs={1: [102]})])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision)
        assert result.status == "ok"
        assert len(result.document["paragraphs"]) == 2
        assert result.document["paragraphs"][0] == document["paragraphs"][0]
        assert result.metrics["l2_revision_count"] == 1
        assert result.metrics["l2_final_approved"] == 1

    @pytest.mark.asyncio
    async def test_golden_d_wrong_speaker_quote_repaired_not_legacy(self):
        """Golden D: цитата с неверным спикером → Revision, а не сразу
        Legacy (§50.20/§75; deterministic repair Wave C + review loop)."""
        # Deterministic слой: quote found + speaker mismatch → repair
        # (de-quote), документ остаётся usable.
        from services.summary_quote_repair import (
            REASON_QUOTE_SPEAKER_MISMATCH,
            process_paragraph_quotes,
        )
        pkg = _package(fragments=[
            _frag(101, 7001, "Тагир", "толщину стенку с длиной перепутала"),
        ])
        text, stats = process_paragraph_quotes(
            'Макс сказал: "толщину стенку с длиной перепутала"', pkg)
        assert REASON_QUOTE_SPEAKER_MISMATCH in stats.reason_codes
        assert '"' not in text and stats.repaired == 1
        # Review-слой: такие находки идут в needs_fixes → revision.
        document = _doc('Макс сказал: "толщину стенку с длиной перепутала".',
                        "Тема закрылась.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        document["paragraphs"][1]["evidence_message_ids"] = [102]
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("quote_speaker_mismatch",
                                              index=0, refs=(101,))]),
            _verdict("approved"),
        ])
        revision = StageStub([_patch(
            {0: "Тагир рассказывал, как клиентка перепутала трубы."},
            refs={0: [101]})])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision)
        assert result.status == "ok"
        assert result.invalid_reason is None
        assert "Макс сказал" not in result.document["paragraphs"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_budget_ceiling_six_calls(self):
        """ADR D3.3: потолок ≤6 логических вызовов L2-стадии. Reviewer
        всегда needs_fixes с УМЕНЬШАЮЩИМСЯ числом blocking (progress ок) →
        w1+r1+rev1+r2+rev2+r3 = ровно 6; после — автономных циклов нет
        (needs_fixes финального ревизии → Legacy)."""
        document = _doc("Абзац один.", "Абзац два.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        document["paragraphs"][1]["evidence_message_ids"] = [102]
        reviewer = StageStub([
            _verdict("needs_fixes", [
                _finding("unsupported_number", index=0),
                _finding("invented_name", index=1)]),
            _verdict("needs_fixes", [
                _finding("unsupported_number", index=0)]),
            _verdict("needs_fixes", [
                _finding("unsupported_number", index=0)]),
        ])
        # Патч-ответы со «сломанным» текстом длиной >900 — детерминированная
        # валидация их отвергнет, но вызовы засчитываются.
        revision = StageStub([_patch({0: "x" * 950}),
                              _patch({0: "x" * 950})])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision)
        assert result.status == "invalid"
        assert result.invalid_reason == REASON_L2_REVIEW_REJECTED
        assert reviewer.calls == 3 and revision.calls == 2
        m = result.metrics
        assert m["l2_review_calls"] == 3 and m["l2_revision_calls"] == 2
        assert m["l2_legacy_after_review"] == 1
        assert m["l2_final_approved"] == 0
        # Итоговая арифметика бюджета: 1 writer + 3 + 2 = 6 ≤ 6.
        assert 1 + m["l2_review_calls"] + m["l2_revision_calls"] \
            <= CALL_BUDGET_L2_STAGE

    @pytest.mark.asyncio
    async def test_progress_criterion_no_improvement_legacy_without_rev2(self):
        """§50.25: blocking findings не уменьшились после Revision #1 →
        БЕЗ Revision #2 — сразу safe fallback (4 вызова, не 6)."""
        document = _doc("Абзац один.", "Абзац два.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        document["paragraphs"][1]["evidence_message_ids"] = [102]
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
            # После ревизии: то же число blocking (0 уменьшений) + новая.
            _verdict("needs_fixes", [
                _finding("unsupported_number", index=0),
                _finding("contradiction_with_package", index=1)]),
        ])
        revision = StageStub([_patch({0: "Исправленный абзац один."})])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision)
        assert result.status == "invalid"
        assert result.invalid_reason == REASON_L2_REVIEW_REJECTED
        assert reviewer.calls == 2 and revision.calls == 1
        m = result.metrics
        assert m["l2_revision_count"] == 1
        assert m["l2_revision_new_findings"] == 1
        assert m["l2_legacy_after_review"] == 1

    @pytest.mark.asyncio
    async def test_unusable_without_evidence_downgraded_not_legacy(self):
        """ASAP 5 D3/§16#5 (SUPERSEDE «unusable → Legacy немедленно»):
        raw unusable БЕЗ evidence-квоты (0 findings, без deterministic
        proof) НЕ terminal — даунгрейд до needs_fixes (l2_unusable_gate),
        ремонта нет (0 findings) → deterministic-валидный черновик
        публикуется degraded, а не выбрасывается в Legacy."""
        reviewer = StageStub([_verdict("unusable")])
        document = _doc("Что-то.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.usable is True
        assert result.invalid_reason is None
        assert result.metrics["l2_review_degraded"] == 1
        assert result.metrics["l2_unusable_gate_downgrades"] == 1
        assert result.metrics.get("l2_legacy_after_review", 0) == 0
        assert reviewer.calls == 1

    @pytest.mark.asyncio
    async def test_unusable_with_two_independent_hard_legacy_immediately(
            self):
        """ASAP 5 D3/§16#6: server-подтверждённая HARD corruption
        (≥2 независимых hard findings: разные коды И разные paragraph
        targets) проходит gate → Legacy немедленно, без ревизий."""
        document = _doc("Абзац один.", "Абзац два.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        document["paragraphs"][1]["evidence_message_ids"] = [102]
        reviewer = StageStub([_verdict("unusable", [
            _finding("unsupported_number", index=0),
            _finding("invented_name", index=1, refs=(102,))])])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "invalid"
        assert result.invalid_reason == REASON_L2_REVIEW_UNUSABLE
        assert result.metrics["l2_legacy_after_review"] == 1
        assert result.metrics["l2_unusable_gate"] == 1
        assert reviewer.calls == 1

    @pytest.mark.asyncio
    async def test_reviewer_outage_publish_degraded_not_lost(self):
        """§50.29/ADR D3.5: reviewer timeout/error НЕ теряет хороший
        документ — deterministic checks прошли → publish degraded
        (l2_review_degraded=1), не success."""
        class Boom:
            calls = 0

            async def __call__(self, messages):
                self.calls += 1
                raise TimeoutError("reviewer timeout")

        document = _doc("Нормальный абзац.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        boom = Boom()
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=boom,
            revision_call=StageStub([]))
        assert result.status == "ok" and result.usable
        assert result.document["title"] == document["title"]
        assert result.metrics[METRIC_REVIEW_DEGRADED] == 1

    @pytest.mark.asyncio
    async def test_reviewer_invalid_verdict_degraded(self):
        """Невалидный вердикт (мусор вместо JSON) — тот же fail-soft путь."""
        reviewer = StageStub(["не вердикт вовсе"])
        document = _doc("Абзац.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "ok"
        assert result.metrics[METRIC_REVIEW_DEGRADED] == 1

    @pytest.mark.asyncio
    async def test_writer_failure_returned_untouched(self):
        """Writer не дал документа → прежняя семантика (негативный L2Result
        возвращается как есть; генератор идёт в Legacy — §50.2)."""
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=AsyncMock(return_value="мусор"),
            reviewer_call=StageStub([]), revision_call=StageStub([]))
        assert result.status == "invalid"
        assert result.invalid_reason == "invalid_json"


class TestPatchContract:
    def test_patch_applied_untouched_bytes_preserved(self):
        """ADR D5: патч гарантирует байт-в-байт сохранность нетронутых
        абзацев («починил одну цитату → не сломал три других»)."""
        document = _doc("Первый абзац.", "Второй абзац.", "Третий абзац.")
        for i, ref in enumerate((101, 102, 101)):
            document["paragraphs"][i]["evidence_message_ids"] = [ref]
        patch = json.dumps({"replace_paragraphs": [
            {"index": 1, "text": "Второй абзац исправлен.",
             "evidence_message_ids": [102]}]}, ensure_ascii=False)
        revised, reason = apply_revision_patch(document, patch,
                                               package=_package())
        assert revised is not None, reason
        assert revised["paragraphs"][0] == document["paragraphs"][0]
        assert revised["paragraphs"][2] == document["paragraphs"][2]
        assert revised["paragraphs"][1]["text"] == "Второй абзац исправлен."

    def test_patch_bad_index_invalid(self):
        document = _doc("Абзац.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        patch = json.dumps({"replace_paragraphs": [
            {"index": 5, "text": "х", "evidence_message_ids": []}]})
        revised, reason = apply_revision_patch(document, patch,
                                               package=_package())
        assert revised is None and reason == "revision_invalid_patch"

    def test_patch_with_invented_ref_fails_deterministic_validation(self):
        """Патч с выдуманным evidence-ref проваливает детерминированную
        валидацию (дважды → full-doc escape-hatch)."""
        document = _doc("Абзац.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        patch = json.dumps({"replace_paragraphs": [
            {"index": 0, "text": "новый текст",
             "evidence_message_ids": [424242]}]}, ensure_ascii=False)
        revised, reason = apply_revision_patch(document, patch,
                                               package=_package())
        assert revised is None
        assert reason == "revision_invalid_patch"

    def test_full_doc_revision_validated(self):
        document = _doc("Абзац.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        revised, reason = apply_full_revision(
            _full_doc(document), package=_package())
        assert revised is not None, reason
        bad = _doc("Абзац.")
        bad["paragraphs"][0]["evidence_message_ids"] = [777]
        revised2, reason2 = apply_full_revision(_full_doc(bad),
                                                package=_package())
        assert revised2 is None

    @pytest.mark.asyncio
    async def test_full_doc_escape_hatch_after_double_invalid_patch(self):
        """ADR D5 (б): патч невалиден → full-doc ветка на следующей ревизии
        (интерпретация «дважды» при бюджете ×2 — см. докстринг модуля)."""
        document = _doc("Абзац один.", "Абзац два.")
        for p, r in zip(document["paragraphs"], ([101], [102])):
            p["evidence_message_ids"] = list(r)
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
            _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
            _verdict("approved"),
        ])
        # Оба ответа ревизии: patch с выдуманным ref → невалиден; затем
        # фолбэк-модель отвечает полным документом.
        bad_patch = json.dumps({"replace_paragraphs": [
            {"index": 0, "text": "чинишь",
             "evidence_message_ids": [31337]}]}, ensure_ascii=False)
        full = json.dumps({
            "schema_version": 1, "title": "Спор о трубах",
            "paragraphs": [
                {"text": "Абзац один исправлен.", "emphasis_spans": [],
                 "evidence_message_ids": [101]},
                {"text": "Абзац два.", "emphasis_spans": [],
                 "evidence_message_ids": [102]},
            ]}, ensure_ascii=False)
        # Ревизия №1 получает patch-режим (bad_patch), ревизия №2 —
        # full-doc (потому что patch_failures>=1 → use_full_doc).
        revision = StageStub([bad_patch, full])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision)
        assert result.status == "ok"
        assert result.document["paragraphs"][0]["text"] == \
            "Абзац один исправлен."
        assert result.metrics["l2_revision_count"] == 2

    @pytest.mark.asyncio
    async def test_findings_over_half_paragraphs_force_full_doc(self):
        """ADR D5 (а): findings > 50% абзацев → full-document revision."""
        document = _doc("Абзац один.", "Абзац два.")
        for p, r in zip(document["paragraphs"], ([101], [102])):
            p["evidence_message_ids"] = list(r)
        reviewer = StageStub([
            _verdict("needs_fixes", [
                _finding("unsupported_number", index=0),
                _finding("invented_name", index=1)]),
            _verdict("approved"),
        ])
        full = json.dumps({
            "schema_version": 1, "title": "Спор о трубах",
            "paragraphs": [
                {"text": "Абзац один.", "emphasis_spans": [],
                 "evidence_message_ids": [101]},
                {"text": "Абзац два.", "emphasis_spans": [],
                 "evidence_message_ids": [102]},
            ]}, ensure_ascii=False)
        seen_modes = []

        async def revision_channel(messages):
            seen_modes.append(messages[1]["content"])
            return full

        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision_channel)
        assert result.status == "ok"
        assert any("replace_paragraphs" not in m for m in seen_modes)

    def test_revision_content_carries_package_findings_preserve(self):
        """§50.22: revision input = draft + пакет + findings + preserve."""
        content = build_revision_content(
            _package(), _doc("Абзац."), (), full_doc=False)
        assert '"package_json"' in content and '"draft"' in content
        assert '"findings"' in content and '"preserve"' in content
        assert "replace_paragraphs" in content
        full = build_revision_content(_package(), _doc("Абзац."), (),
                                      full_doc=True)
        assert "schema_version" in full and "replace_paragraphs" not in full


# ══ Kill-switches (spec §8.2) ══════════════════════════════════════════════

class TestKillSwitches:
    @pytest.mark.asyncio
    async def test_review_off_single_call_bit_identical(self, monkeypatch):
        """SUMMARY_L2_REVIEW_ENABLED=false → прежний single-call L2:
        Reviewer/Revision не вызываются, документ возвращается как draft."""
        _flag(monkeypatch, "SUMMARY_L2_REVIEW_ENABLED", False)
        document = _doc("Абзац.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        reviewer = StageStub([_verdict("needs_fixes", [
            _finding("unsupported_number")])])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "ok" and result.usable
        assert reviewer.calls == 0
        assert l2_review_enabled() is False

    @pytest.mark.asyncio
    async def test_patch_off_full_doc_revision_bounded(self, monkeypatch):
        """SUMMARY_REVISION_PATCH_ENABLED=false (master ON) → revision
        ПОЛНЫМ документом (деградация не до Legacy), ветка bounded."""
        _flag(monkeypatch, "SUMMARY_REVISION_PATCH_ENABLED", False)
        document = _doc("Абзац один.", "Абзац два.")
        for p, r in zip(document["paragraphs"], ([101], [102])):
            p["evidence_message_ids"] = list(r)
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
            _verdict("approved"),
        ])
        full = json.dumps({
            "schema_version": 1, "title": "Спор о трубах",
            "paragraphs": [
                {"text": "Абзац один.", "emphasis_spans": [],
                 "evidence_message_ids": [101]},
                {"text": "Абзац два.", "emphasis_spans": [],
                 "evidence_message_ids": [102]},
            ]}, ensure_ascii=False)
        seen = []

        async def revision_channel(messages):
            seen.append(messages[1]["content"])
            return full

        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision_channel)
        assert result.status == "ok"
        assert result.metrics["l2_final_approved"] == 1
        assert seen and "replace_paragraphs" not in seen[0]
        assert revision_patch_enabled() is False

    @pytest.mark.asyncio
    async def test_generator_review_flag_helper(self, monkeypatch):
        """Генератор: OFF → helper False → run_l2-ветка (бит-в-бит)."""
        from services.summary_generator import _l2_review_enabled_safe
        assert _l2_review_enabled_safe() is True
        _flag(monkeypatch, "SUMMARY_L2_REVIEW_ENABLED", False)
        assert _l2_review_enabled_safe() is False


# ══ T-4433: FactPackage grade + coverage map ═══════════════════════════════

class TestFactPackageCoverage:
    def test_coverage_map_topics_and_events(self):
        """§50.32: coverage map — topics/events total/represented (internal,
        в Analytics); reduction-слитые восстанавливают total."""
        pkg = _package()
        pkg["service"]["reduction_topics_merged"] = 1
        pkg["service"]["reduction_facts_merged"] = 3
        cov = compute_package_coverage(pkg, 688)
        assert cov["source_messages_total"] == 688
        assert cov["major_topics_represented"] == 1
        assert cov["major_topics_total"] == 2
        assert cov["unique_events_represented"] == 2
        assert cov["unique_events_total"] == 5
        assert cov["coverage_percent"] < 100.0

    def test_degraded_package_grade_visible(self):
        """§50.30: L1_FALLBACK_PACKAGE ≠ semantic package — grade виден."""
        from services.summary_fact_package import (
            build_fallback_package,
        )
        items = [
            {"message_id": 5001, "chat_id": CHAT, "timestamp": 1000,
             "author_id": 7, "display_name": "Вася", "text": "текст",
             "reply_to_id": None, "message_type": "text"},
        ]
        result = build_fallback_package(items, correlation_id=RID,
                                        chat_id=CHAT)
        assert result is not None
        assert result.package["service"]["package_grade"] == "degraded"

    def test_semantic_package_grade(self):
        pkg = _package()
        assert pkg["service"]["package_grade"] == "semantic"


# ══ T-4436: publication_status / pipeline_health / stage events ════════════

class TestRunState:
    def test_ctx_publication_and_health_separate(self):
        """§50.53: publication_status (publish_status) и pipeline_health —
        разные оси; успешный Legacy НЕ стирает degraded-историю (Q36)."""
        from services.summary_run_log import RunContext, log_summary_complete
        ctx = RunContext(run_id=RID, chat_id=CHAT)
        ctx.publish_status = "ok"
        ctx.pipeline_health = "degraded"
        ctx.fallback = "legacy"
        assert ctx.publish_status == "ok"
        assert ctx.pipeline_health == "degraded"
        # Событие собирается без ошибок (additive поля health/package_grade).
        log_summary_complete(ctx)

    def test_stage_events_append_only(self):
        """§50.54: stage events append-only; run record не переписывает."""
        import time as _time
        from services.summary_l2_review import _record, _stage_event
        ctx = RunContextStub()
        started = _time.time()
        _record(ctx, _stage_event("l2_reviewer", attempt=1, status="ok",
                                  started=started))
        _record(ctx, _stage_event("revision", attempt=1, status="ok",
                                  started=started))
        assert [e["stage"] for e in ctx.stage_events] == \
            ["l2_reviewer", "revision"]
        assert ctx.stage_events[0]["finished_at"] >= started

    @pytest.mark.asyncio
    async def test_review_loop_records_stage_events(self):
        document = _doc("Абзац один.", "Абзац два.")
        for p, r in zip(document["paragraphs"], ([101], [102])):
            p["evidence_message_ids"] = list(r)
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("unsupported_number", index=0)]),
            _verdict("approved"),
        ])
        revision = StageStub([_patch({0: "Абзац один с числом из пакета."})])
        ctx = RunContextStub()
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision, ctx=ctx)
        assert result.status == "ok"
        stages = [e["stage"] for e in ctx.stage_events]
        assert stages == ["l2_reviewer", "revision", "l2_reviewer"]
        assert ctx.stage_events[1]["repair_target"] == "patch"

    def test_health_set_on_legacy_path(self):
        """Q36: генератор выставляет health=degraded ДО Legacy и не стирает
        при успехе (пин исходника)."""
        import inspect
        from services import summary_generator as sg
        source = inspect.getsource(sg.SummaryGenerator._run_hybrid_l2)
        # Волна D: L2-fail ветка фиксирует health до _legacy_fallback.
        assert 'ctx.pipeline_health = "degraded"' in source
        # "ok" для health выставляется РОВНО ОДИН раз — и только под guard
        # (нет деградации → healthy); сброс при Legacy-успехе отсутствует.
        assert source.count('ctx.pipeline_health = "ok"') == 1
        ok_pos = source.index('ctx.pipeline_health = "ok"')
        assert 'if not getattr' in source[max(0, ok_pos - 200):ok_pos]


class RunContextStub:
    """Минимальный ctx-контракт review loop (stage_events append-only)."""

    def __init__(self):
        self.stage_events = []


# ══ T-4437: слоты, события, golden smoke ═══════════════════════════════════

class TestReviewerSlotAndEvents:
    def test_reviewer_slot_inherits_l2_by_default(self):
        """§50.28: без override Reviewer наследует слот L2 (безопасный
        default; админ не выбирает ещё десять моделей)."""
        slot = resolve_l2_reviewer_slot(hot_get=lambda k, d: d,
                                        settings_obj=type("S", (), {
                                            "SUMMARY_L2_REVIEWER_BASE_URL": "",
                                            "SUMMARY_L2_REVIEWER_MODEL_NAME":
                                                "",
                                            "SUMMARY_L2_REVIEWER_API_KEY":
                                                "",
                                        })())
        assert slot is not None
        assert slot.dedicated in (True, False)

    def test_reviewer_slot_partial_override_stays_dedicated(self):
        """Явный override модели → dedicated-слот (частичное поле добирается
        из L2-слота, не из глобальной модели)."""

        class Hot:
            def __init__(self, values):
                self.values = values

            def get(self, key, default=None):
                return self.values.get(key, default)

        from services.summary_l2_writer import resolve_l2_slot
        l2 = resolve_l2_slot(hot_get=Hot({}).get,
                             settings_obj=type("S", (), {})())
        slot = resolve_l2_reviewer_slot(
            hot_get=Hot({"models.summary_l2_reviewer_model_name":
                         "reviewer-x"}).get,
            settings_obj=type("S", (), {
                "SUMMARY_L2_REVIEWER_BASE_URL": "",
                "SUMMARY_L2_REVIEWER_MODEL_NAME": "",
                "SUMMARY_L2_REVIEWER_API_KEY": "",
                "SUMMARY_L2_BASE_URL": "",
                "SUMMARY_L2_MODEL_NAME": "",
                "SUMMARY_L2_API_KEY": "",
            })())
        assert slot.model == "reviewer-x"
        assert slot.base_url == l2.base_url or slot.base_url

    def test_new_reason_codes_in_shared_dict(self):
        """Волна D: новые reason codes — в ЕДИНОМ словаре REASON_CODES
        (spec §5 E.1; не новый словарь)."""
        for code in ("l2_review_rejected", "l2_review_unusable",
                     "review_degraded"):
            assert code in me.REASON_CODES

    def test_no_raw_content_in_review_logs(self, caplog):
        """R17: L2_REVIEW/L2_REVIEW_DEGRADED — только числа/коды/id."""
        import logging
        from services.summary_l2_review import _log_review
        metrics = _review_metrics_snapshot()
        with caplog.at_level(logging.INFO, logger="services.summary_l2_review"):
            _log_review(run_id=RID, chat_id=CHAT, metrics=metrics,
                        status="approved")
            _log_review(run_id=RID, chat_id=CHAT, metrics=metrics,
                        status="rejected", reason="l2_review_rejected")
        text = caplog.text
        assert "L2_REVIEW" in text
        # Никаких текстов статей/цитат в логе (фикстурные строки отсутствуют).
        assert "Тагир" not in text and "клиентка" not in text


def _review_metrics_snapshot() -> dict:
    from services.summary_l2_review import _review_metrics
    return _review_metrics()


# ══ T-4434: chunk boundary + L1 merge (§50.33–§50.35) ══════════════════════

class TestChunkBoundaryMerge:
    @pytest.mark.asyncio
    async def test_reply_chain_survives_chunk_boundary(self):
        """§50.33: вопрос в chunk A, ответ в chunk B — reply-chain не
        теряется (overlap-нарезка + merge-union); в пакете оба сообщения
        одной темы, relation kind=reply сохранён (§50.9)."""
        rows = [
            {"id": 1, "tg_message_id": 5001, "timestamp": 1_759_400_001,
             "user_id": 10, "author_name": "Аня", "text": "он правда "
             "уволился?", "reply_to_id": None, "media_type": "text"},
            {"id": 2, "tg_message_id": 5002, "timestamp": 1_759_400_002,
             "user_id": 11, "author_name": "Боря",
             "text": "да, с понедельника", "reply_to_id": 5001,
             "media_type": "text"},
        ]
        # Planning обязан видеть reply-density; merge собирает payload.
        from services.summary_l1_clusterizer import merge_l1_payloads
        chunk_a = {"schema_version": 2,
                   "threads": [{"thread_id": "t1", "topic": "увольнение",
                                "message_ids": [5001, 5002],
                                "facts": [{"text": "Аня спросила про "
                                           "увольнение",
                                           "evidence_message_ids": [5001]}]}],
                   "unassigned_message_ids": []}
        chunk_b = {"schema_version": 2,
                   "threads": [{"thread_id": "t1", "topic": "увольнение",
                                "message_ids": [5002],
                                "facts": [{"text": "Боря подтвердил: с "
                                           "понедельника",
                                           "evidence_message_ids": [5002]}]}],
                   "unassigned_message_ids": []}
        merged = merge_l1_payloads([chunk_a, chunk_b])
        assert len(merged["threads"]) == 1
        assert merged["threads"][0]["message_ids"] == [5001, 5002]
        texts = {f["text"] for f in merged["threads"][0]["facts"]}
        assert len(texts) == 2        # уникальные факты не уничтожены
        # Пакетный уровень: reply-связь и kind доходят до Writer/Reviewer.
        from services.summary_fact_package import build_fact_package
        items = [
            {"message_id": 5001, "chat_id": CHAT, "timestamp": 1_759_400_001,
             "author_id": 10, "display_name": "Аня",
             "text": "он правда уволился?", "reply_to_id": None,
             "message_type": "text"},
            {"message_id": 5002, "chat_id": CHAT, "timestamp": 1_759_400_002,
             "author_id": 11, "display_name": "Боря",
             "text": "да, с понедельника", "reply_to_id": 5001,
             "message_type": "text"},
        ]
        payload = {"schema_version": 2, "response_mode": "serious",
                   "threads": merged["threads"],
                   "unassigned_message_ids": []}
        result = build_fact_package(_raw_l1(payload), items,
                                    budget=("tokens", 100000))
        frags = result.package["threads"][0]["fragments"]
        by_id = {f["message_id"]: f for f in frags}
        assert by_id[5002]["kind"] == "reply"
        assert by_id[5002]["reply_to_id"] == 5001

    def test_failsoft_unknown_id_contract_untouched(self):
        """§50.35 (R4-D-035): unknown/malformed L1 ID — прежний fail-soft
        контракт (упаковщик: MISSING_SOURCE → invalid → fallback-пакет),
        capacity guard волны C не маскирует (регресс ASAP-2)."""
        from services.summary_fact_package import build_fact_package
        items = [{"message_id": 5001, "chat_id": CHAT, "timestamp": 1,
                  "author_id": 10, "display_name": "Вася", "text": "т",
                  "reply_to_id": None, "message_type": "text"}]
        payload = {"schema_version": 2,
                   "threads": [{"thread_id": "t1", "topic": "т",
                                "message_ids": [999999], "facts": []}],
                   "unassigned_message_ids": []}
        result = build_fact_package(_raw_l1(payload), items,
                                    budget=("tokens", 100000))
        # unknown ID в теме → invalid (fail-closed структуры) — контракт
        # §50.35 не смягчён волной D.
        assert result.status == "invalid"


def _raw_l1(payload):
    """Минимальный L1-result-стуб для build_fact_package (паттерн Wave C)."""
    class _R:
        pass
    r = _R()
    r.payload = payload
    r.status = "ok"
    r.invalid_reason = None
    r.response_mode = payload.get("response_mode", "")
    r.cover_prompt = ""
    r.truncated = False
    r.skipped_ids = ()
    r.chunk_count = 1
    return r


# ══ T-4435: факто-сохраняющий набор (§50.39–§50.47 — пины правил) ══════════

class TestFactPreservingSet:
    def test_long_message_lossless_segmentation_exists(self):
        """§50.39: длинное сообщение — lossless-сегментация (ASAP-3.2 §42)
        не тронута: part/part_total, конкатенация == исходный текст."""
        from services.summary_fact_package import _segment_text
        text = "слово " * 200
        parts = _segment_text(text)
        assert len(parts) > 1
        assert "".join(parts) == text
        for i, p in enumerate(parts, start=1):
            assert len(p) <= 1000

    def test_forward_not_author_rule_in_prompt_and_reviewer(self):
        """§50.40: forward ≠ авторство — правило в каноне Writer И в
        промпте Reviewer (forward_attribution_error)."""
        assert "содержание принадлежит источнику пересылки" in \
            SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "forward_attribution_error" in SUMMARY_L2_REVIEWER_SYSTEM_PROMPT

    def test_external_reality_not_verified_rule(self):
        """§50.45: внешняя реальность не «допроверяется»."""
        assert "допроверяй" in SUMMARY_L2_WRITER_SYSTEM_PROMPT
        assert "в чате обсуждали новость" in SUMMARY_L2_WRITER_SYSTEM_PROMPT

    def test_title_is_factual_surface_rule(self):
        """§50.46: заголовок — factual surface (проверяется Reviewer'ом)."""
        assert "заголовок проверяй как факт" in \
            SUMMARY_L2_REVIEWER_SYSTEM_PROMPT
        assert "заголовок обязан соответствовать фактам" in \
            SUMMARY_L2_WRITER_SYSTEM_PROMPT

    def test_finale_candidate_from_roster_rule(self):
        """§50.47: «главный шиз» — участник пакета, не выдуманное имя."""
        assert "Кандидат обязан быть участником пакета" in \
            SUMMARY_L2_WRITER_SYSTEM_PROMPT


# ══ Golden F/G/H: modality/стиль/имена (review-правила) ════════════════════

class TestGoldenModalityStyleNames:
    @pytest.mark.asyncio
    async def test_golden_f_question_not_assertion_blocked(self):
        """Golden F: вопрос, превращённый в утверждение → factual_
        overstatement → Revision (modality сохраняется, §50.41)."""
        document = _doc("Он уволился.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        reviewer = StageStub([
            _verdict("needs_fixes", [_finding("factual_overstatement",
                                              index=0, refs=(101,))]),
            _verdict("approved"),
        ])
        revision = StageStub([_patch(
            {0: "В чате обсудили, не уволился ли он."}, refs={0: [101]})])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=revision)
        assert result.status == "ok"
        assert result.metrics["l2_revision_count"] == 1

    @pytest.mark.asyncio
    async def test_golden_g_sarcasm_not_blocked(self):
        """Golden G: сарказм/гипербола НЕ бракуются (style ≠ fact, §50.26):
        approved без findings; стилистический оборот остаётся в статье."""
        document = _doc("Спор окончательно поехал по рельсам конфы.")
        document["paragraphs"][0]["evidence_message_ids"] = [101]
        reviewer = StageStub([_verdict("approved")])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "ok"
        assert "рельсам конфы" in result.document["paragraphs"][0]["text"]
        assert result.metrics["l2_first_pass_approved"] == 1

    def test_golden_h_same_names_distinct_in_roster(self):
        """Golden H: два разных author_id с одинаковыми именами не сливаются
        (проверка по ID); reviewer-верdict с refs на конкретного автора
        проходит валидацию против общего id-space пакета."""
        pkg = _package(fragments=[
            _frag(101, 7001, "Лёха", "первый Лёха"),
            _frag(102, 7002, "Лёха", "второй Лёха"),
        ])
        roster = build_participant_roster(pkg)
        assert len(roster) == 2
        verdict = parse_review_verdict(
            _verdict("needs_fixes", [_finding("wrong_person_attribution",
                                              index=0, refs=(102,))]),
            package=pkg, document=_doc("Абзац."))
        assert len(verdict.findings) == 1

    @pytest.mark.asyncio
    async def test_golden_j_smoke_review_loop_on_wide_package(self):
        """Golden J (smoke; полный golden J — Wave C, T-4422): review loop
        работает на пакете с 31+ фактами — budget/валидация не ломаются."""
        facts = [{"text": f"полезный факт номер {n}",
                  "evidence_message_ids": [101 + (n % 40)]}
                 for n in range(35)]
        fragments = [_frag(101 + i, 7001, "Вася", f"сообщение {i}")
                     for i in range(40)]
        pkg = _package(fragments=fragments, facts=facts)
        document = _doc("Сорок сообщений одной темы.")
        document["paragraphs"][0]["evidence_message_ids"] = \
            [101 + i for i in range(40)]
        reviewer = StageStub([_verdict("approved")])
        result = await run_l2_with_review(
            None, pkg, correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "ok"
        assert result.metrics["l2_first_pass_approved"] == 1

    @pytest.mark.asyncio
    async def test_deterministic_validator_before_reviewer_order(self):
        """§50.18: deterministic validator идёт ДО Reviewer — структурно
        битый документ НЕ доходит до semantic reviewer (writer invalid)."""
        reviewer = StageStub([_verdict("approved")])
        bad_doc = {"schema_version": 1, "title": "х",
                   "paragraphs": [{"text": "текст", "bogus_field": 1}]}
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(bad_doc), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "invalid"
        assert result.invalid_reason == "unknown_field"
        assert reviewer.calls == 0

    @pytest.mark.asyncio
    async def test_formatting_repair_is_code_not_llm(self):
        """§50.19: механические вещи чинит детерминированный слой — ревизия
        НЕ тратится на типографику (спан невалиден → дроп, документ ok)."""
        document = _doc("Текст с жирностью.")
        p = document["paragraphs"][0]
        p["evidence_message_ids"] = [101]
        p["emphasis_spans"] = [{"text": "нет такого фрагмента",
                                "kind": "event"}]
        reviewer = StageStub([_verdict("approved")])
        result = await run_l2_with_review(
            None, _package(), correlation_id=RID, chat_id=CHAT,
            llm_call=WriterStub(document), reviewer_call=reviewer,
            revision_call=StageStub([]))
        assert result.status == "ok"
        assert result.document["paragraphs"][0]["emphasis_spans"] == []
        assert result.metrics["l2_revision_count"] == 0
        assert reviewer.calls == 1
