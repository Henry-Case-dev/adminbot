"""S16-FC-FINALIZE — финализация фактчека: ответ по предмету, честный
частичный результат, чистая речь, пропорциональность.

Контракт owner §9.1-9.4 + §10.6 (`plans/owner_inputs/
2026-11-14-factcheck-request-integrity-v2-full.md`), карта
`requirements-map-fc-amendment.json` (SFC-9-01..9-04, SFC-10-06).

Проверяется НАБЛЮДАЕМОЕ поведение существующих стадий L1 Analyst →
L2 Verbalizer → Renderer, а не наличие констант:

* предмет проверки доходит до аналитика и вербализатора: проверка всего
  сообщения и вопрос о связанной части материала (owner §9.2);
* при техническом прерывании уже собранный evidence сохраняется и честно
  разделяется на подтверждённое/опровергнутое/недостаточно
  подтверждённое/технически непроверенное; стандартная заглушка не
  подменяет содержательный частичный ответ, а техническое прерывание не
  выдаётся за истинность/ложность (owner §9.3);
* служебные enum, технические идентификаторы и сырые контейнеры (OCR-контекст)
  не появляются в пользовательской речи вместо нормального ответа (§10.6);
* длина ответа остаётся пропорциональной задаче: короткий факт — короткая
  проверка, сложная публикация не обрезается (§9.4);
* третья обязательная LLM-стадия/отдельный редактор не появились, канон
  голоса и версионирование промптов не менялись (§9.1).

TEST-LIFECYCLE: CONTRACT owner=S16-FC-FINALIZE (SFC-9-01..9-04, SFC-10-06).
"""
from __future__ import annotations

import hashlib
import json

import pytest

import services.temporal_factcheck as tf
from services import factcheck_orchestrator as orch
from services import factcheck_planner as fsp
from services import factcheck_prompts as fp
from services import prompt_registry as pr
from services.factcheck_renderer import render_factcheck
from services.factcheck_service import FactCheckService

ANALYST_INSUFFICIENT = json.dumps({
    "factual_verdict": "insufficient_evidence",
    "temporal_status": "unknown",
    "evaluated_period": {"from": None, "to": None},
    "reason": None,
    "parts": [],
}, ensure_ascii=False)
VALIDATOR = json.dumps(
    {"agree": True, "corrected_factual_verdict": None,
     "corrected_temporal_status": None, "note": "ok"},
    ensure_ascii=False)

#: Байты канона голоса/аналитика/одиночного пути на базе 9a89e3da — S16 не
#: меняет речевой контракт и не переоткрывает версионирование промптов.
PROMPT_SEALS = {
    "FACTCHECK_VERBALIZER_SYSTEM_PROMPT": "45361c23221c",
    "FACTCHECK_ANALYST_SYSTEM_PROMPT": "ed4c7a642804",
    "FACTCHECK_SYSTEM_PROMPT": "dcbd765fb860",
    "FACTCHECK_CRITIQUE_DIRECTIVE": "cfcd9009df17",
}


class RecordingLLM:
    """LLM-двойник стадий фактчека; пишет payload каждого шага."""

    def __init__(self, *, analyst=None, verbalizer="Ответ (test).",
                 fail_verbalize=False):
        self.analyst = analyst or ANALYST_INSUFFICIENT
        self.verbalizer = verbalizer
        self.fail_verbalize = fail_verbalize
        self.calls: list[tuple[str, list]] = []

    async def generate(self, messages, *, step="", **_kw):
        self.calls.append((step, list(messages)))
        if step in ("temporal_verdict", "temporal_fallback"):
            return self.analyst
        if step == "temporal_validator":
            return VALIDATOR
        if self.fail_verbalize:
            raise RuntimeError("verbalizer down")
        return self.verbalizer

    def payload(self, step: str) -> str:
        for name, messages in self.calls:
            if name == step:
                return str(messages[-1]["content"])
        raise AssertionError(f"step {step} not called: "
                             f"{[c[0] for c in self.calls]}")

    def steps(self) -> list[str]:
        return [name for name, _messages in self.calls]


def _env(claim_text: str, *, material: str | None = None,
         request_text: str | None = None, form_request: str = ""):
    return tf.TemporalClaimEnvelope(
        claim_id="tcl-s16", chat_id=1, target_tg_message_id=10,
        target_revision=1, target_content_hash="h1",
        trigger_tg_message_id=11, claim_text=claim_text,
        claim_span=None, source_type="text", attribution={"author": "A"},
        origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="A",
        repost_received_at=1760000000, original_published_at=1665277000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000,
        material_claim_text=(claim_text if material is None else material),
        request_text=request_text, form_request=form_request)


def _ref(i: int, *, support: str | None = None):
    return orch.EvidenceRef(
        evidence_id=f"ev-{i}", url=f"https://source{i}.example/page",
        support=(support if support is not None
                 else f"Выдержка {i}: событие задокументировано."),
        source_kind="secondary", published_at=1665277000, claims=("c1",))


def _outcome(refs, *, budget_exhausted: bool = False):
    return fsp.RetrievalOutcome(
        evidence_map=orch.EvidenceMap(
            refs=tuple(refs), allowlist=tuple(r.evidence_id for r in refs)),
        search_text="фрагмент выдачи " * 20, queries_attempted=2,
        queries_used=2, refs_collected=len(refs), fetch_errors=0,
        budget_exhausted=budget_exhausted,
        stop_reason="budget" if budget_exhausted else "complete")


async def _run(env, llm, *, refs=(), budget=False):
    service = FactCheckService(aggregator=None, llm=llm)
    retrieval = _outcome(refs, budget_exhausted=budget) if refs else None
    return await service.check_claim_envelope(env, retrieval=retrieval)


def _presentation(run) -> orch.FactcheckPresentation:
    refs = tuple(
        orch.EvidenceRef(
            evidence_id=str(r.get("evidence_id") or ""),
            url=r.get("url"),
            support=str(r.get("support") or ""),
            source_kind=str(r.get("source_kind") or "secondary"),
            published_at=r.get("published_at"),
            claims=((str(r.get("claim_part")),)
                    if r.get("claim_part") else ()))
        for r in (run.evidence_rows or ()))
    verdict = orch.CheckedVerdict(
        verdict_text=run.verdict_text, route="envelope_temporal",
        factual_verdict=run.verdict.factual_verdict,
        temporal_status=run.verdict.temporal_status,
        evaluated_period=run.verdict.evaluated_period,
        uncertainty=run.verdict.uncertainty,
        evidence=orch.EvidenceMap(
            refs=refs, allowlist=tuple(r.evidence_id for r in refs)),
        reason_code=run.verdict.reason, as_of=run.verdict.as_of,
        fallback_used=run.fallback_used,
        evidence_refs=tuple(run.verdict.evidence_refs or ()),
        parts=tuple(run.verdict.parts or ()))
    return orch.build_presentation(verdict)


# ── SFC-9-02: ответ соответствует фактическому предмету проверки ─────────────

@pytest.mark.asyncio
async def test_whole_message_is_the_subject_without_duplication():
    """Проверка всего сообщения: предмет — материал целиком, без второго
    блока и без отдельного «уточнённого фокуса»."""
    material = "Первое утверждение. Второе утверждение. Третье утверждение."
    llm = RecordingLLM(verbalizer="Разобрал сообщение целиком: факты не сходятся.")
    run = await _run(_env(material), llm, refs=[_ref(1)])

    analyst = llm.payload("temporal_verdict")
    assert f"<claim>{material}</claim>" in analyst
    assert "<original_material>" not in analyst
    verbl = llm.payload("temporal_verbalize")
    payload = json.loads(verbl.split("ВЕРДИКТ (JSON):\n", 1)[1])
    assert payload["claim"] == material
    assert "original_material" not in payload
    # живой ответ не подменён формализованным отчётом/карточками
    assert run.verdict_text == "Разобрал сообщение целиком: факты не сходятся."


@pytest.mark.asyncio
async def test_related_part_question_sees_material_and_request():
    """Вопрос о связанной части: часть получает приоритет, но материал и
    собственный вопрос пользователя видны проверке и вербализатору; вывод
    остаётся ответом на вопрос."""
    material = ("Курс вырос вдвое. Инфляция осталась низкой. "
                "Безработица не изменилась.")
    subject = "Инфляция осталась низкой."
    request = "проверь второе предложение"
    llm = RecordingLLM(verbalizer="По второму предложению: инфляция осталась низкой.")
    run = await _run(_env(subject, material=material, request_text=request,
                          form_request="коротко"), llm, refs=[_ref(1)])

    analyst = llm.payload("temporal_verdict")
    assert f"<claim>{subject}</claim>" in analyst
    assert f"<original_material>{material}</original_material>" in analyst
    assert f"<user_request>{request}</user_request>" in analyst
    verbl = llm.payload("temporal_verbalize")
    payload = json.loads(verbl.split("ВЕРДИКТ (JSON):\n", 1)[1])
    assert payload["claim"] == subject
    assert payload["original_material"] == material
    assert payload["user_request"] == request
    assert payload["requested_form"] == "коротко"
    # ответ — ровно живой текст вербализатора: ни обязательного объявления
    # предмета, ни обязательного раздела «уточнённый фокус» не добавляется
    assert run.verdict_text == "По второму предложению: инфляция осталась низкой."
    assert "уточнённый фокус" not in run.verdict_text.casefold()


# ── SFC-9-03: честный частичный результат вместо заглушки ───────────────────

@pytest.mark.asyncio
async def test_budget_interruption_keeps_evidence_and_splits_honestly():
    """Техническое прерывание: собранный evidence не выбрасывается, результат
    честно разделён, а не заменён стандартной заглушкой."""
    llm = RecordingLLM(fail_verbalize=True)
    refs = [_ref(1, support="Выдержка A: курс вырос вдвое."),
            _ref(2, support="Выдержка B: инфляция осталась низкой."),
            _ref(3, support="Выдержка C: безработица не изменилась.")]
    run = await _run(_env("Курс вырос вдвое."), llm, refs=refs, budget=True)

    text = run.verdict_text
    # 1) собранный evidence сохранён (durable строки прогона не потеряны)
    assert len(run.evidence_rows) == 3
    # 2) техническая граница названа, а не замаскирована под «нет данных»
    assert "бюджета/времени" in text
    assert "истёк лимит времени" in text or "ограничением бюджета" in text
    # 3) уже полученные материалы присутствуют, а не заменены заглушкой
    assert "Уже собрано" in text
    assert "Выдержка A: курс вырос вдвое." in text
    # 4) техническое прерывание не объявлено истинностью/ложностью
    assert "не доказательство истинности или ложности" in text
    # 5) оговорка о границе поиска видна и в структуре вердикта
    assert "budget" in (run.verdict.uncertainty or {}).get(
        "search_boundary", "") or "бюджет" in (run.verdict.uncertainty or {}).get(
            "search_boundary", "")


@pytest.mark.asyncio
async def test_verbalizer_receives_partial_inventory_not_limit_stub():
    """Нормальный вербализатор при неполном разборе получает честный инвентарь
    (что подтверждено/не проверено + собранное), а не «назови ограничение»."""
    analyst = json.dumps({
        "factual_verdict": "insufficient_evidence",
        "temporal_status": "unknown",
        "evaluated_period": {"from": None, "to": None},
        "reason": None,
        "parts": [],
    }, ensure_ascii=False)
    llm = RecordingLLM(analyst=analyst,
                       verbalizer="Что уже видно: курс вырос вдвое; остальное не проверено.")
    run = await _run(_env("Курс вырос вдвое."), llm,
                     refs=[_ref(1), _ref(2)], budget=True)
    verbl = llm.payload("temporal_verbalize")
    assert "ВЕРДИКТ (JSON):\n" in verbl
    payload = json.loads(verbl.split("ВЕРДИКТ (JSON):\n", 1)[1])
    partial = payload.get("partial") or {}
    assert partial.get("collected"), partial
    assert any("бюджет" in str(row) for row in partial.get("technical", []))
    assert "partial_note" in payload
    assert "limit_note" not in payload
    assert "не заменяй общей оговоркой" in payload["partial_note"]
    assert run.verdict_text == (
        "Что уже видно: курс вырос вдвое; остальное не проверено.")


@pytest.mark.asyncio
async def test_technical_part_is_not_reported_as_no_data():
    """Часть, упавшая технически, называется технически непроверенной и не
    превращается в «данных недостаточно»/«опровергнуто»."""
    analyst = json.dumps({
        "factual_verdict": "insufficient_evidence",
        "temporal_status": "unknown",
        "evaluated_period": {"from": None, "to": None},
        "reason": None,
        "parts": [
            {"part_id": "p1", "factual_verdict": "insufficient_evidence",
             "status_detail": "source_extract_failed",
             "text": "Источник не открылся.", "evidence_refs": []},
            {"part_id": "p2", "factual_verdict": "supported",
             "text": "Курс вырос вдвое.", "evidence_refs": ["ev-1"]},
        ],
    }, ensure_ascii=False)
    llm = RecordingLLM(analyst=analyst, fail_verbalize=True)
    run = await _run(_env("Курс вырос вдвое, источник не открылся."), llm,
                     refs=[_ref(1)], budget=True)
    text = run.verdict_text
    assert "Технически не проверено: Источник не открылся." in text
    assert "Подтверждено: Курс вырос вдвое." in text
    # техническая часть не превращается в опровержение тезиса
    assert "опровергнуто" not in text.casefold()


@pytest.mark.asyncio
async def test_empty_research_still_reports_the_technical_cause():
    """Результата нет вовсе → прежняя честная техническая фраза (без выдумки)."""
    llm = RecordingLLM(fail_verbalize=True)
    run = await _run(_env("Утверждение без материалов."), llm)
    assert "Это технический сбой, а не отсутствие фактов." in run.verdict_text


# ── SFC-10-06: чистая пользовательская речь ─────────────────────────────────

@pytest.mark.asyncio
async def test_service_enums_ids_and_ocr_context_never_reach_the_user():
    """Служебные метки/ID/OCR-контейнер вычищаются; нормальный ответ остаётся."""
    leak = ("Курс вырос вдвое — это подтверждается. "
            "factual_verdict=insufficient_evidence; ev-1; claim c1; "
            "<chat_context note=\"OCR dump\">сырой OCR-текст с картинки"
            "</chat_context> reason_code=source_missing")
    llm = RecordingLLM(verbalizer=leak)
    run = await _run(_env("Курс вырос вдвое."), llm, refs=[_ref(1)])
    text = run.verdict_text
    assert "Курс вырос вдвое" in text
    for forbidden in ("insufficient_evidence", "reason_code", "source_missing",
                      "ev-1", "claim c1", "chat_context", "OCR"):
        assert forbidden not in text
    # и на границе renderer'а те же метки не публикуются
    rendered = render_factcheck(_presentation(run)).text
    for forbidden in ("insufficient_evidence", "reason_code", "chat_context"):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_service_only_answer_is_not_published_as_the_answer():
    """Ответ, состоящий из служебного дампа, не публикуется вместо ответа:
    берётся честный частичный результат по собранным материалам."""
    llm = RecordingLLM(
        verbalizer="factual_verdict=insufficient_evidence; ev-1; p1; c1; "
                   "reason_code=source_missing")
    run = await _run(_env("Курс вырос вдвое."), llm, refs=[_ref(1)])
    text = run.verdict_text
    assert "insufficient_evidence" not in text
    assert "ev-1" not in text
    assert "частично" in text.casefold()
    assert "Выдержка 1" in text


def test_renderer_strips_service_tokens_from_verdict_text():
    """Renderer — последняя граница: служебные поля не попадают в публикацию."""
    verdict = orch.CheckedVerdict(
        verdict_text="Нормальный ответ. reason_code=source_missing; ev-7.",
        route="legacy_single", factual_verdict=None)
    rendered = render_factcheck(orch.FactcheckPresentation(
        text=verdict.verdict_text), verdict)
    assert "Нормальный ответ." in rendered.text
    assert "reason_code" not in rendered.text
    assert "ev-7" not in rendered.text


@pytest.mark.asyncio
async def test_legacy_single_path_also_keeps_service_tokens_out(monkeypatch):
    """Одиночный legacy-путь (kill-switch/rollback) публикует тот же чистый
    пользовательский текст, а не служебные метки."""
    from unittest.mock import AsyncMock, MagicMock
    from services.factcheck_service import FactCheckService

    aggregator = MagicMock()
    aggregator.search = AsyncMock(return_value="хиты поиска")
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value="Курс вырос вдвое. factual_verdict=insufficient_evidence; "
                     "ev-3; reason_code=source_missing")
    service = FactCheckService(aggregator, llm)
    result = await service.check_claim("Курс вырос вдвое.")
    assert "Курс вырос вдвое." in result
    for forbidden in ("insufficient_evidence", "reason_code", "source_missing",
                      "ev-3"):
        assert forbidden not in result


# ── SFC-9-04: объём пропорционален задаче ───────────────────────────────────

@pytest.mark.asyncio
async def test_short_fact_gets_short_answer_and_long_publication_is_not_capped():
    short_answer = "Нет, не подтверждается."
    llm = RecordingLLM(verbalizer=short_answer)
    short_run = await _run(_env("2+2=5"), llm, refs=[_ref(1)])
    assert short_run.verdict_text == short_answer
    assert len(short_run.verdict_text) < 200

    long_answer = "Развёрнутый разбор публикации. " * 60
    llm = RecordingLLM(verbalizer=long_answer)
    long_run = await _run(_env("Сложная публикация. " * 150), llm,
                          refs=[_ref(1), _ref(2)])
    # тот же вербализатор, без нового жёсткого потолка на финализации
    assert long_run.verdict_text == long_answer.strip()
    assert len(long_run.verdict_text) > 1000


# ── SFC-9-01: контракт стадий и канон сохранены ─────────────────────────────

@pytest.mark.asyncio
async def test_no_third_llm_stage_or_editor_and_voice_canon_bytes_kept():
    """L1 Analyst → L2 Verbalizer → Renderer без новой обязательной стадии;
    промпты характера/выражения/стиля/мата — прежние байты."""
    llm = RecordingLLM(verbalizer="Живой связный ответ без нового шаблона.")
    run = await _run(_env("Утверждение."), llm, refs=[_ref(1)])

    assert llm.steps() == ["temporal_verdict", "temporal_validator",
                           "temporal_verbalize"]
    assert not [step for step in llm.steps()
                if any(marker in step for marker in
                       ("finalize", "editor", "refine", "rewrite"))]
    # ответ вербализатора публикуется как есть — пост-редактора нет
    assert run.verdict_text == "Живой связный ответ без нового шаблона."

    for name, seal in PROMPT_SEALS.items():
        digest = hashlib.sha256(getattr(fp, name).encode()).hexdigest()[:12]
        assert digest == seal, f"{name} bytes changed"
    assert pr.seal_integrity() == {}
    # обязательного раздела/шаблона в каноне нет
    canon = fp.FACTCHECK_VERBALIZER_SYSTEM_PROMPT.casefold()
    assert "обязательный раздел" not in canon
    assert "уточнённый фокус" not in canon
