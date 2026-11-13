"""S13 FACTCHECK-REQUEST-INTEGRITY: единый предмет проверки.

TEST-LIFECYCLE: CONTRACT owner=FACTCHECK-REQUEST-INTEGRITY-v2 §3.3/§4.1-4.5
(план SMART-EXECUTION-RELIABILITY-01 §11, срез S13-FC-REQUEST).

Проверяются пользовательские инварианты, а не устройство helper'ов:

* A — обычный «фактчек» без текста: материал проверяется байт-в-байт,
  дополнительного LLM-вызова нет, дата/автор/связи сохраняются;
* B — разговорное уточнение не меняет предмет;
* C — уточнение сужает проверку до части материала;
* D — уточнение добавляет условие (период) к исходному тезису;
* E — самостоятельный вопрос пользователя становится предметом, дата
  материала на него не переносится, автор вопроса не подменяется автором
  публикации;
* F — расширение: проверяются и исходный тезис, и дополнительный факт;
* G — просьба о форме не меняет предмет и не добавляет исследований;
* `_claim_units` не отбрасывает корректный предмет и не теряет остаток
  предмета (условие/вопрос пользователя);
* cache identity различает предметы и переиспользует подходящий срез;
* полный текст уточнения не обрезается на durable media-пути.

Смысл уточнения определяет LLM (в тестах — детерминированный двойник,
возвращающий структурированное решение). Код в этих тестах ничего не
классифицирует по словам: одинаковое решение при разных формулировках даёт
одинаковый предмет, а слова-«маркеры» без решения предмет не меняют.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

from config.settings import settings
from handlers import factcheck as fh
from services import factcheck_context as fcx
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_suitability as fsg
from services import media_readiness as mrd
from services import temporal_factcheck as tf

CHAT_ID = -100991
TARGET_TG = 5010
TRIGGER_TG = 5011
SENT_AT = 1792200000

MATERIAL = ("Древняя традиция женского обрезания существует тысячи лет. "
            "На её распространение влияли Франция, Великобритания, Германия "
            "и США. По отчёту 2016 года, 87% случаев приходились на три "
            "региона.")

MIXED_SUBJECT = ("Древняя традиция женского обрезания существует тысячи лет. "
                 "Проверить, влияла ли Турция.")
REQUEST_ONLY = ("Есть ли страны, где традиция сохраняется без влияния "
                "Франции, Великобритании, Германии и США?")
CONDITION = "Проверить только период 1990–2000 годов"


# ── Двойники: LLM/DB/сервис (без сети, без прод-чатов) ───────────────────────

class FakeLLM:
    """Детерминированная семантическая стадия: возвращает заданное решение."""

    def __init__(self, replies=()):
        self.replies = list(replies)
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if not self.replies:
            raise AssertionError("неожиданный LLM-вызов")
        reply = self.replies.pop(0)
        if isinstance(reply, dict):
            return json.dumps(reply, ensure_ascii=False)
        return str(reply)


class FakeService:
    def __init__(self, replies=()):
        self.llm = FakeLLM(replies) if replies else None
        self.check_claim_calls = []

    async def check_claim(self, target_text, user_hint, forward_source, *,
                          chat_id=None, chat_context=None,
                          search_results=None):
        self.check_claim_calls.append(
            {"target_text": target_text, "user_hint": user_hint})
        return "Проверено."


class FakeDB:
    def __init__(self, row):
        self.row = row

    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(self.row)


def _row(text=MATERIAL, *, sent_at=SENT_AT, origin_sent_at=None,
         origin_type=None, author_name="Автор поста"):
    return {"text": text, "caption": None, "origin_type": origin_type,
            "origin_sent_at": origin_sent_at, "sent_at": sent_at,
            "current_revision": 3, "content_hash": "hash-1",
            "origin_sender_user_id": None, "origin_chat_id": None,
            "origin_display_name": None, "author_name": author_name,
            "forward_source": None}


def _resolve(material=MATERIAL, hint=None, replies=(), *,
             material_author="Автор поста", request_author="Аня"):
    service = FakeService(replies)
    subject = asyncio.run(orch.resolve_check_subject(
        service, material_text=material, request_text=hint,
        material_author=material_author, request_author=request_author,
        material_tg_message_id=TARGET_TG,
        request_tg_message_id=TRIGGER_TG, chat_id=CHAT_ID))
    return subject, service


def _envelope(subject, *, mode="contextual", row=None, attribution=None):
    ref = tf.InputRef(
        kind="reply", chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG,
        claim_text=(subject.text if subject is not None else MATERIAL),
        explicit_mode=mode, attribution=attribution or {},
        subject=subject)
    env, reason = asyncio.run(tf.build_envelope(FakeDB(row or _row()), ref))
    assert reason is None
    return env


def _decision(items, scope="web"):
    claim_items = tuple(
        fsg.ClaimItem(text=text, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
                      verifiable=True, source=source)
        for text, source in items)
    return fsg.SuitabilityDecision(
        decision=fsg.DECISION_CHECKABLE,
        claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
        claim_items=claim_items, scope=scope, reason_code="test",
        confidence=0.9, target_ref={})


@pytest.fixture
def planner_on():
    old = getattr(settings, "FACTCHECK_PIPELINE_V2_ENABLED", False)
    object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", True)
    try:
        yield
    finally:
        object.__setattr__(settings, "FACTCHECK_PIPELINE_V2_ENABLED", old)


# ── A. Обычный фактчек без уточнения ────────────────────────────────────────

class TestScenarioAOrdinary:
    def test_material_is_byte_identical_without_llm_call(self):
        subject, service = _resolve(hint=None, replies=[{"subject": "unused"}])
        assert subject.text == MATERIAL
        assert subject.material_text == MATERIAL
        assert subject.material_part == MATERIAL
        assert subject.request_text is None
        assert subject.request_part == ""
        assert subject.origin == orch.SUBJECT_ORIGIN_MATERIAL
        assert subject.resolved_by == "material"
        assert service.llm is not None and service.llm.calls == []

    def test_envelope_keeps_ordinary_claim_date_and_anchor(self):
        subject, _ = _resolve(hint=None)
        env = _envelope(subject)
        assert env.claim_text == MATERIAL
        assert env.material_claim_text == MATERIAL
        assert env.request_text is None
        assert env.original_published_at == SENT_AT
        assert env.material_published_at == SENT_AT
        assert env.date_source == "telegram_message"
        assert env.claim_anchor_tg_message_id == TARGET_TG

    def test_handler_wrapper_does_not_call_llm_without_hint(self):
        service = FakeService([{"subject": MATERIAL}])
        old = fh._service
        fh._service = service
        try:
            message = SimpleNamespace(
                message_id=TRIGGER_TG, chat=SimpleNamespace(id=CHAT_ID),
                from_user=SimpleNamespace(first_name="Аня"))
            target = SimpleNamespace(
                message_id=TARGET_TG, from_user=None, sender_chat=None,
                author_signature=None)
            publication = SimpleNamespace(
                claim_anchor_author="Автор поста", forward_source=None,
                target_tg_message_id=TARGET_TG)
            subject = asyncio.run(fh._resolve_subject(
                message, target, publication, MATERIAL, None))
        finally:
            fh._service = old
        assert subject.text == MATERIAL
        assert subject.resolved_by == "material"
        assert service.llm.calls == []


# ── B. Уточнение не изменяет предмет ────────────────────────────────────────

class TestScenarioBNoChange:
    def test_doubt_keeps_material_and_preserves_request(self):
        hint = "серьёзно, это правда?"
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": MATERIAL, "material_part": MATERIAL,
            "request_part": "", "form_request": ""}])
        assert subject.text == MATERIAL
        assert subject.origin == orch.SUBJECT_ORIGIN_MATERIAL
        assert subject.request_text == hint
        assert subject.request_part == ""
        env = _envelope(subject)
        assert env.claim_text == MATERIAL
        assert env.request_text == hint

    def test_conversational_hint_does_not_create_new_claim(self):
        hint = "ну и что, это же очевидно"
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": MATERIAL, "material_part": MATERIAL,
            "request_part": "", "form_request": ""}])
        assert subject.text == MATERIAL
        plan = fsp._build_plan_inner(
            _decision([(MATERIAL, "literal")]), claim_text=subject.text,
            max_queries=None, subject_origin=subject.origin)
        assert plan is not None
        assert all("ну и что" not in q.text.lower() for q in plan.queries)


# ── C. Уточнение сужает проверку ────────────────────────────────────────────

class TestScenarioCNarrowing:
    def test_selected_part_is_the_subject_not_full_material(self):
        part = "87% случаев приходились на три региона"
        subject, _ = _resolve(hint="а эти 87% точно?", replies=[{
            "subject": "Утверждение о 87% случаев", "material_part": part,
            "request_part": "", "form_request": ""}])
        assert subject.origin == orch.SUBJECT_ORIGIN_MATERIAL
        assert part in subject.text
        assert "тысячи лет" not in subject.text
        env = _envelope(subject)
        assert env.claim_text == subject.text
        assert "87%" in env.claim_text
        assert "тысячи лет" not in env.claim_text
        # дата исходной публикации не теряется при сужении
        assert env.original_published_at == SENT_AT
        assert env.material_claim_text == MATERIAL


# ── D. Уточнение добавляет условие ──────────────────────────────────────────

class TestScenarioDCondition:
    def test_condition_is_part_of_subject_and_period(self):
        material_part = ("Древняя традиция женского обрезания существует "
                         "тысячи лет.")
        hint = "но интересует только период 1990–2000 годов"
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": material_part + " " + CONDITION,
            "material_part": material_part,
            "request_part": CONDITION, "form_request": ""}])
        assert subject.origin == orch.SUBJECT_ORIGIN_MIXED
        assert material_part in subject.text
        assert "1990" in subject.text
        env = _envelope(subject)
        assert env.claim_text == subject.text
        assert env.claim_period_from == 631152000
        # дата материала сохранена отдельно; условие не выдаётся за дату
        assert env.material_published_at == SENT_AT
        assert env.original_published_at == SENT_AT
        assert env.request_text == hint

    def test_condition_reaches_retrieval_plan(self, planner_on):
        material_part = ("Древняя традиция женского обрезания существует "
                         "тысячи лет.")
        subject, _ = _resolve(hint=CONDITION, replies=[{
            "subject": material_part + " " + CONDITION,
            "material_part": material_part,
            "request_part": CONDITION, "form_request": ""}])
        plan = fsp.build_retrieval_plan(
            _decision([(material_part, "literal")], scope="web"),
            claim_text=subject.text, subject_origin=subject.origin,
            subject_anchor_tg_message_id=TRIGGER_TG,
            subject_author="Аня", subject_request_text=subject.request_part)
        assert plan is not None
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "традиция" in joined
        assert "1990" in joined or "турция" in joined
        assert len(plan.claims) >= 2


    def test_condition_reaches_plan_without_subject_kwargs(self, planner_on):
        """RED на базе: план строится только из принятого item и теряет
        добавленное условие, даже когда условие — часть проверяемого текста."""
        material_part = ("Древняя традиция женского обрезания существует "
                         "тысячи лет.")
        subject_text = material_part + " " + CONDITION
        plan = fsp.build_retrieval_plan(
            _decision([(material_part, "literal")]), claim_text=subject_text)
        assert plan is not None
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "1990" in joined


# ── E. Уточнение задаёт самостоятельный вопрос ──────────────────────────────

class TestScenarioEStandaloneQuestion:
    def test_request_is_subject_and_material_date_not_transferred(self):
        hint = REQUEST_ONLY
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": REQUEST_ONLY, "material_part": "",
            "request_part": REQUEST_ONLY, "form_request": ""}])
        assert subject.origin == orch.SUBJECT_ORIGIN_REQUEST
        assert subject.text == REQUEST_ONLY
        env = _envelope(
            subject, attribution={"author": "Автор поста"})
        assert env.claim_text == REQUEST_ONLY
        assert env.request_text == REQUEST_ONLY
        assert env.material_claim_text == MATERIAL
        # дата материала не переносится на вопрос пользователя
        assert env.original_published_at is None
        assert env.material_published_at == SENT_AT
        assert env.date_source == "unknown"
        # авторство: вопрос принадлежит пользователю, не автору публикации
        assert env.attribution.get("author") == "Аня"
        assert env.material_author == "Автор поста"
        # структурные связи: цель остаётся целью, анкор — сообщение запроса
        assert env.target_tg_message_id == TARGET_TG
        assert env.claim_anchor_tg_message_id == TRIGGER_TG

    def test_question_is_not_proven_as_original_quote(self, planner_on):
        subject, _ = _resolve(hint=REQUEST_ONLY, replies=[{
            "subject": REQUEST_ONLY, "material_part": "",
            "request_part": REQUEST_ONLY, "form_request": ""}])
        plan = fsp.build_retrieval_plan(
            _decision([(MATERIAL, "literal")], scope="web"),
            claim_text=subject.text, subject_origin=subject.origin,
            subject_anchor_tg_message_id=TRIGGER_TG,
            subject_author="Аня", subject_request_text=subject.request_part)
        assert plan is not None
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "страны" in joined
        assert "87%" not in joined


# ── F. Уточнение расширяет проверку ─────────────────────────────────────────

class TestScenarioFExpansion:
    def test_material_and_added_fact_both_in_subject(self, planner_on):
        material_part = ("Древняя традиция женского обрезания существует "
                         "тысячи лет.")
        hint = "и проверь, влияла ли Турция"
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": material_part + " Влияла ли Турция.",
            "material_part": material_part,
            "request_part": "Влияла ли Турция.", "form_request": ""}])
        assert subject.origin == orch.SUBJECT_ORIGIN_MIXED
        assert "тысячи лет" in subject.text
        assert "Турция" in subject.text
        plan = fsp.build_retrieval_plan(
            _decision([(material_part, "literal")], scope="web"),
            claim_text=subject.text, subject_origin=subject.origin,
            subject_fingerprint=subject.fingerprint,
            subject_anchor_tg_message_id=TRIGGER_TG,
            subject_author="Аня", subject_request_text=subject.request_part)
        assert plan is not None
        joined = " ".join(q.text.lower() for q in plan.queries)
        assert "турция" in joined
        assert "традиция" in joined
        origins = {row.get("origin") for row in plan.claim_anchors}
        assert "user_request" in origins
        request_rows = [row for row in plan.claim_anchors
                        if row.get("origin") == "user_request"]
        assert request_rows and all(
            row.get("anchor_tg_message_id") == TRIGGER_TG
            for row in request_rows)


# ── G. Уточнение относится к форме ответа ───────────────────────────────────

class TestScenarioGForm:
    def test_form_request_does_not_change_subject_or_queries(self, planner_on):
        subject, _ = _resolve(hint="объясни короче", replies=[{
            "subject": MATERIAL, "material_part": MATERIAL,
            "request_part": "", "form_request": "объясни короче"}])
        assert subject.origin == orch.SUBJECT_ORIGIN_MATERIAL
        assert subject.text == MATERIAL
        assert subject.form_request == "объясни короче"
        baseline = fsp.build_retrieval_plan(
            _decision([(MATERIAL, "literal")]), claim_text=MATERIAL,
            subject_origin="material")
        with_form = fsp.build_retrieval_plan(
            _decision([(MATERIAL, "literal")]), claim_text=subject.text,
            subject_origin=subject.origin)
        assert baseline is not None and with_form is not None
        assert [q.text for q in with_form.queries] == [
            q.text for q in baseline.queries]
        env = _envelope(subject)
        assert env.form_request == "объясни короче"
        assert env.claim_text == MATERIAL


# ── Смысл определяет решение, а не слова ────────────────────────────────────

class TestNoLexicalRouting:
    def test_same_decision_for_different_wordings_gives_same_subject(self):
        decision = {"subject": MATERIAL, "material_part": MATERIAL,
                    "request_part": "", "form_request": ""}
        first, _ = _resolve(hint="серьёзно?", replies=[dict(decision)])
        second, _ = _resolve(hint="ну и что, это правда?", replies=[
            dict(decision)])
        assert first.text == second.text == MATERIAL
        assert first.origin == second.origin == orch.SUBJECT_ORIGIN_MATERIAL

    def test_keyword_like_words_do_not_change_subject_without_decision(self):
        decision = {"subject": MATERIAL, "material_part": MATERIAL,
                    "request_part": "", "form_request": ""}
        for hint in ("короче", "подробнее", "покажи основания",
                     "проверь только дату"):
            subject, _ = _resolve(hint=hint, replies=[dict(decision)])
            assert subject.text == MATERIAL

    def test_subject_resolution_has_no_lexical_classifier(self):
        source = (inspect.getsource(orch.resolve_check_subject)
                  + inspect.getsource(orch._subject_from_decision))
        for forbidden in ("re.search(", "re.match(", "re.findall(",
                          "startswith(", "endswith("):
            assert forbidden not in source


# ── `_claim_units`: предмет не отбрасывается, provenance не теряется ────────

class TestClaimUnits:
    def test_condition_not_dropped_when_material_item_matches(self):
        material_part = ("Древняя традиция женского обрезания существует "
                         "тысячи лет.")
        subject = material_part + " " + CONDITION
        item = fsg.ClaimItem(
            text=material_part, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
            verifiable=True, source="literal")
        units = fsp._claim_units([item], subject)
        assert any("тысячи лет" in unit for unit in units)
        assert any("1990" in unit for unit in units)

    def test_request_subject_is_not_replaced_by_material(self):
        item = fsg.ClaimItem(
            text=MATERIAL, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
            verifiable=True, source="literal")
        units = fsp._claim_units([item], REQUEST_ONLY)
        assert len(units) == 1
        assert "страны" in units[0]
        assert "87%" not in units[0]

    def test_semantically_correct_subject_not_verbatim_in_material(self):
        paraphrase = ("Традиция практикуется давно, и нужно установить "
                      "страны без западного влияния.")
        item = fsg.ClaimItem(
            text=MATERIAL, claim_type=fsg.CHECKABLE_FACTUAL_CLAIM,
            verifiable=True, source="literal")
        units = fsp._claim_units([item], paraphrase)
        assert units
        assert "страны без западного влияния" in " ".join(units)


# ── Cache identity: разные предметы не делят готовый результат ──────────────

class TestCacheIdentity:
    def _ctx(self, *, newest=900, window=(10, 10)):
        return fcx.ConversationContext(
            chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, messages=(),
            window={"before": window[0], "after": window[1]},
            newest_message_id=newest)

    def test_different_subjects_get_different_slice_keys(self):
        ctx = self._ctx()
        first = fcx.slice_cache_key(ctx, before=10, after=10,
                                    claim_text=REQUEST_ONLY)
        second = fcx.slice_cache_key(ctx, before=10, after=10,
                                     claim_text=MATERIAL)
        assert first and second and first != second

    def test_same_subject_reuses_slice_and_different_request_does_not_split_it(
            self):
        ctx = self._ctx()
        first = fcx.slice_cache_key(ctx, before=10, after=10,
                                    claim_text=REQUEST_ONLY)
        again = fcx.slice_cache_key(ctx, before=10, after=10,
                                    claim_text="  " + REQUEST_ONLY + "  ")
        assert first == again
        components = fcx.slice_cache_components(
            ctx, before=10, after=10, claim_text=REQUEST_ONLY)
        assert components["subject"]

    def test_envelope_fingerprint_distinguishes_subject_and_mode(self):
        subject, _ = _resolve(hint=REQUEST_ONLY, replies=[{
            "subject": REQUEST_ONLY, "material_part": "",
            "request_part": REQUEST_ONLY, "form_request": ""}])
        other, _ = _resolve(hint=CONDITION, replies=[{
            "subject": CONDITION, "material_part": "",
            "request_part": CONDITION, "form_request": ""}])
        contextual = _envelope(subject, mode="contextual")
        same = _envelope(subject, mode="contextual")
        historical = _envelope(subject, mode="historical_truth")
        different = _envelope(other, mode="contextual")
        assert contextual.subject_fingerprint
        assert contextual.subject_fingerprint == same.subject_fingerprint
        assert contextual.subject_fingerprint != historical.subject_fingerprint
        assert contextual.subject_fingerprint != different.subject_fingerprint


# ── Provenance: запрос без обрезки, авторы и связи раздельно ────────────────

class TestProvenance:
    def test_full_request_is_preserved_without_truncation(self):
        hint = "Проверь конкретно: " + ("очень длинное уточнение " * 40).strip()
        assert len(hint) > 400
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": REQUEST_ONLY, "material_part": "",
            "request_part": REQUEST_ONLY, "form_request": ""}])
        assert subject.request_text == hint
        env = _envelope(subject)
        assert env.request_text == hint
        assert env.material_claim_text == MATERIAL

    def test_material_origin_keeps_material_author(self):
        subject, _ = _resolve(hint="это правда?", replies=[{
            "subject": MATERIAL, "material_part": MATERIAL,
            "request_part": "", "form_request": ""}])
        env = _envelope(subject, attribution={"author": "Автор поста"})
        assert env.attribution.get("author") == "Автор поста"
        assert env.request_author == "Аня"
        assert env.material_author == "Автор поста"
        assert env.claim_anchor_tg_message_id == TARGET_TG
        assert env.target_tg_message_id == TARGET_TG

    def test_forwarded_origin_date_not_mixed_with_message_date(self):
        subject, _ = _resolve(hint=REQUEST_ONLY, replies=[{
            "subject": REQUEST_ONLY, "material_part": "",
            "request_part": REQUEST_ONLY, "form_request": ""}])
        env = _envelope(
            subject,
            row=_row(origin_type="channel", origin_sent_at=1700000000,
                     sent_at=SENT_AT),
            attribution={"author": "Автор поста"})
        assert env.original_published_at is None
        assert env.material_published_at == 1700000000
        assert env.repost_received_at == SENT_AT

    def test_handler_wrapper_passes_full_hint_to_semantic_stage(self):
        hint = "  Полный текст уточнения: " + ("деталь " * 90).strip()
        service = FakeService([{
            "subject": REQUEST_ONLY, "material_part": "",
            "request_part": REQUEST_ONLY, "form_request": ""}])
        old = fh._service
        fh._service = service
        try:
            message = SimpleNamespace(
                message_id=TRIGGER_TG, chat=SimpleNamespace(id=CHAT_ID),
                from_user=SimpleNamespace(first_name="Аня"))
            target = SimpleNamespace(
                message_id=TARGET_TG, from_user=None, sender_chat=None,
                author_signature=None)
            publication = SimpleNamespace(
                claim_anchor_author="Автор поста", forward_source=None,
                target_tg_message_id=TARGET_TG)
            subject = asyncio.run(fh._resolve_subject(
                message, target, publication, MATERIAL, hint))
        finally:
            fh._service = old
        assert subject.request_text == hint.strip()
        prompt = service.llm.calls[0]["messages"][1]["content"]
        assert hint.strip() in prompt


# ── Durable media-путь: полное уточнение не обрезается ──────────────────────

class TestDeferredMediaRequest:
    def _defer(self, monkeypatch, request_text):
        captured = {}

        class _Store:
            def __init__(self, db):
                pass

            async def enqueue(self, **kwargs):
                captured.update(kwargs)
                return "job-1"

        import services.task_supervisor as task_supervisor
        monkeypatch.setattr(task_supervisor, "TaskJobStore", _Store)
        monkeypatch.setattr(mrd, "_emit_defer_event", lambda *a, **k: None)
        readiness = SimpleNamespace(
            chat_id=CHAT_ID, target_message_id=TARGET_TG, ready=False,
            analysis_status="pending", assets=(), media_group_id="",
            association_kind="", asset_id="", consumer="factcheck",
            as_dict=lambda: {})
        result = asyncio.run(mrd.defer_until_ready(
            object(), readiness, consumer="factcheck",
            message_id=TRIGGER_TG, query=request_text, user_id=7,
            notify=False, context={"request_text": request_text}))
        assert result.get("job_id") == "job-1"
        return json.loads(captured["payload"])

    def test_full_request_survives_durable_roundtrip(self, monkeypatch):
        request_text = "Проверить только " + ("этот фрагмент " * 40).strip()
        assert len(request_text) > 400
        payload = self._defer(monkeypatch, request_text)
        assert payload["question"] == request_text[:400]
        assert payload["context"]["request_text"] == request_text

        captured = {}

        async def fake_run(req, **kwargs):
            captured["req"] = req
            return "ok"

        monkeypatch.setattr(orch, "run_factcheck", fake_run)
        monkeypatch.setitem(orch._RUNTIME, "db", object())
        monkeypatch.setitem(orch._RUNTIME, "service", object())
        monkeypatch.setitem(orch._RUNTIME, "cache", None)
        intent = {"chat_id": CHAT_ID, "trigger_message_id": TARGET_TG,
                  "user_id": 7, "consumer": "factcheck",
                  "question": payload["question"],
                  "context": payload["context"], "reason_code": None}
        assert asyncio.run(orch.deliver_deferred_factcheck(
            intent, [], bot=object())) is True
        assert captured["req"].user_hint == request_text


class _RoundTripCache:
    """SmartCache-двойник с маркерами TTL (get/set_update_marker)."""

    def __init__(self):
        self.markers = {}

    async def get_update_marker(self, key, *, ttl_seconds):
        return self.markers.get(key)

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.markers[key] = payload


class TestCacheRoundTrip:
    """§4.5/§12.4: готовый срез другого предмета не выдаётся как наш."""

    def _ctx(self):
        message = fcx.ContextMessage(
            message_id=1, tg_message_id=TARGET_TG, chat_id=CHAT_ID,
            author="Автор поста", timestamp=SENT_AT, reply_to_tg_id=None,
            is_forward=False, forward_source=None, text=MATERIAL,
            verbatim=True)
        return fcx.ConversationContext(
            chat_id=CHAT_ID, target_tg_message_id=TARGET_TG,
            trigger_tg_message_id=TRIGGER_TG, messages=(message,),
            window={"before": 10, "after": 0}, newest_message_id=900)

    def test_slice_written_for_subject_a_is_not_read_for_subject_b(self):
        cache = _RoundTripCache()
        ctx = self._ctx()
        assert asyncio.run(fcx.write_slice_cache(
            cache, ctx, before=10, after=0, claim_text=MATERIAL))
        hit = asyncio.run(fcx.read_slice_cache(
            cache, ctx, before=10, after=0, claim_text=MATERIAL))
        assert hit is not None and hit.messages
        miss = asyncio.run(fcx.read_slice_cache(
            cache, ctx, before=10, after=0, claim_text=REQUEST_ONLY))
        assert miss is None

    def test_same_subject_with_other_clarification_reuses_slice(self):
        cache = _RoundTripCache()
        ctx = self._ctx()
        asyncio.run(fcx.write_slice_cache(
            cache, ctx, before=10, after=0, claim_text=REQUEST_ONLY))
        hit = asyncio.run(fcx.read_slice_cache(
            cache, ctx, before=10, after=0,
            claim_text="  " + REQUEST_ONLY + "  "))
        assert hit is not None and hit.messages


class TestStructuralRejection:
    """§4.4/§4.2: чужие слова не подписываются автору, новый тезис без
    происхождения не принимается, fallback сохраняет запрос."""

    def test_ungrounded_material_part_is_dropped_not_signed_to_author(self):
        subject, _ = _resolve(hint="проверь", replies=[{
            "subject": MATERIAL,
            "material_part": "традиция исчезла", "request_part": "",
            "form_request": ""}])
        assert "традиция исчезла" not in subject.material_part
        assert subject.material_part == MATERIAL   # принято только дословное
        assert subject.note == "ungrounded_material_part"
        assert subject.text == MATERIAL
        assert subject.resolved_by == "llm"

    def test_subject_without_provenance_rejected_to_fallback(self):
        hint = "докажи вот это"
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": "совершенно новый тезис без основания",
            "material_part": "", "request_part": "", "form_request": ""}])
        assert subject.resolved_by == "fallback"
        assert subject.note == "unusable_decision"
        assert subject.text == MATERIAL
        assert subject.request_text == hint

    def test_invalid_json_fallback_keeps_request(self):
        subject, _ = _resolve(hint=REQUEST_ONLY, replies=["не json"])
        assert subject.resolved_by == "fallback"
        assert subject.note == "invalid_json"
        assert subject.text == MATERIAL
        assert subject.request_text == REQUEST_ONLY

    def test_llm_error_fallback_keeps_request(self):
        class BrokenLLM:
            async def generate(self, messages, **kwargs):
                raise RuntimeError("provider down")

        service = FakeService()
        service.llm = BrokenLLM()
        subject = asyncio.run(orch.resolve_check_subject(
            service, material_text=MATERIAL, request_text=REQUEST_ONLY,
            material_author="Автор поста", request_author="Аня",
            material_tg_message_id=TARGET_TG,
            request_tg_message_id=TRIGGER_TG, chat_id=CHAT_ID))
        assert subject.resolved_by == "fallback"
        assert subject.text == MATERIAL
        assert subject.request_text == REQUEST_ONLY


class _FakeBot:
    id = 862000001

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return SimpleNamespace(message_id=888)

    async def send_chat_action(self, chat_id, action, **kw):
        return True


class _StageService(FakeService):
    """Сервис обеих веток: envelope-ветка возвращает TemporalRunResult."""

    def __init__(self, replies=()):
        super().__init__(replies)
        self.envelope_calls = []

    async def check_claim_envelope(self, envelope, *, chat_context=None):
        self.envelope_calls.append({"envelope": envelope})
        from services.temporal_factcheck import (
            TemporalRunResult, TemporalVerdict)
        verdict = TemporalVerdict(
            factual_verdict="refuted", temporal_status="current",
            evaluated_period={"from": 100, "to": 200, "precision": "day"},
            assessment_mode="contextual", as_of=1792200100,
            evidence_refs=("ev-1",), reason=None)
        return TemporalRunResult(
            envelope=envelope, verdict=verdict, verdict_text="Проверено.",
            evidence_rows=({"evidence_id": "ev-1",
                            "url": "https://example.org/src",
                            "support": "подтверждение",
                            "source_kind": "secondary",
                            "published_at": None},),
            fallback_used=False)


class _StageDB:
    def __init__(self, row):
        self.row = row

    async def get_messages_around(self, chat_id, tg, before, after):
        return []

    async def get_recent_messages(self, chat_id, limit):
        return []

    async def get_smart_message_origin_block(self, chat_id, tg):
        return dict(self.row)


class TestStageConsistency:
    """§4.1/§12.3: предмет, установленный на входе, доходит до РЕАЛЬНЫХ
    стадий оркестратора (envelope-ветка и legacy-ветка), а не только до
    helper'ов."""

    def _req(self, hint):
        return orch.FactcheckRequest(
            chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
            target_tg_message_id=TARGET_TG, target_text=MATERIAL,
            user_hint=hint, kind="reply", requester_name="Аня")

    def _subject(self, hint=REQUEST_ONLY):
        subject, _ = _resolve(hint=hint, replies=[{
            "subject": REQUEST_ONLY, "material_part": "",
            "request_part": REQUEST_ONLY, "form_request": ""}])
        return subject

    def test_envelope_branch_checks_the_established_subject(
            self, monkeypatch):
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: True)
        monkeypatch.setattr(
            "services.factcheck_orchestrator.pipeline_v2_enabled",
            lambda: True)
        service = _StageService()
        subject = self._subject()
        asyncio.run(orch.run_factcheck(
            self._req(REQUEST_ONLY), service=service,
            db=_StageDB(_row()), bot=_FakeBot(), cache=None,
            subject=subject))
        assert service.envelope_calls, "envelope-ветка должна выполниться"
        envelope = service.envelope_calls[0]["envelope"]
        assert envelope.claim_text == REQUEST_ONLY
        assert envelope.request_text == REQUEST_ONLY
        assert envelope.material_claim_text == MATERIAL
        assert envelope.subject_origin == orch.SUBJECT_ORIGIN_REQUEST

    def test_legacy_branch_checks_the_established_subject(self, monkeypatch):
        monkeypatch.setattr(
            "services.factcheck_orchestrator.pipeline_v2_enabled",
            lambda: True)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: False)
        service = _StageService()
        subject = self._subject()
        asyncio.run(orch.run_factcheck(
            self._req(REQUEST_ONLY), service=service,
            db=_StageDB(_row()), bot=_FakeBot(), cache=None,
            subject=subject))
        assert service.check_claim_calls
        assert service.check_claim_calls[0]["target_text"] == REQUEST_ONLY

    def test_no_clarification_makes_no_semantic_subject_call(
            self, monkeypatch):
        """A: обычный путь не получает новых LLM-вызовов вообще."""
        monkeypatch.setattr(
            "services.factcheck_orchestrator.pipeline_v2_enabled",
            lambda: True)
        monkeypatch.setattr(
            "services.mca_gates.temporal_factcheck_enabled", lambda: False)
        service = _StageService()
        asyncio.run(orch.run_factcheck(
            orch.FactcheckRequest(
                chat_id=CHAT_ID, trigger_tg_message_id=TRIGGER_TG,
                target_tg_message_id=TARGET_TG, target_text=MATERIAL,
                kind="reply"),
            service=service, db=_StageDB(_row()), bot=_FakeBot(),
            cache=None))
        assert service.llm is None            # llm не запрашивался вообще
        assert service.check_claim_calls[0]["target_text"] == MATERIAL


class TestGateAdmissionSeparation:
    """§4.1: гейт допуска оценивает МАТЕРИАЛ, а нерез контекста строится под
    ПРЕДМЕТ — разделение сохраняется и на handler-стадии."""

    def test_gate_gets_admission_text_and_context_gets_subject(
            self, monkeypatch):
        captured = {}

        class _Ctx:
            def render_feed(self):
                return "feed"

        def fake_evaluate(db, chat_id, **kwargs):
            captured.update(kwargs)

            async def _run():
                return (_decision([(MATERIAL, "literal")], scope="web"), _Ctx())
            return _run()

        monkeypatch.setattr(fcx, "wide_context_enabled", lambda: True)
        monkeypatch.setattr(fsg, "suitability_gate_enabled", lambda: True)
        monkeypatch.setattr(fsg, "evaluate_with_expansion", fake_evaluate)
        monkeypatch.setattr(fh, "get_smart_cache", lambda: None)
        feed, decision = asyncio.run(fh._fetch_context_with_gate(
            CHAT_ID, 40, 10, target_tg_message_id=TARGET_TG,
            trigger_message_id=TRIGGER_TG, claim_text=REQUEST_ONLY,
            admission_text=MATERIAL, user_hint=REQUEST_ONLY,
            explicit_request=True))
        assert feed == "feed"
        assert captured["claim_text"] == MATERIAL   # решение — по материалу
        assert captured["subject_text"] == REQUEST_ONLY  # срез — под предмет
        assert captured["explicit_request"] is True
