"""S15-FC-EVIDENCE — сквозной аудит восьми звеньев + производственный случай.

Прогон НЕ использует сеть и БД: LLM/агрегатор — детерминированные двойники.
Один и тот же файл запускается на базе (80c83d24), кандидате (HEAD) и
deployed-коммите (d20a7f73), поэтому все различия в выводе — различия
поведения кода, а не окружения.

    python plans/features/smart-execution-reliability-01/evidence/\
fc-evidence/raw/s15_audit_probe.py > raw/audit-<ref>.json

Секции:

* ``caps``       — какие лимиты объявлены/применяются в этом дереве;
* ``subject``    — сохраняется ли пользовательский запрос в предмете проверки
                   (производственный случай: материал + вопрос пользователя);
* ``delivery``   — сколько evidence реально доходит до analyst/validator,
                   что происходит с остатком при превышении ёмкости;
* ``provenance`` — видит ли аналитик opened/source_kind и запрет вывода
                   «доказательств нет» после бюджетной остановки;
* ``db``         — совпадают ли durable-строки с доставленными в payload.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import os
import re
import sys

sys.path.insert(0, os.getcwd())

import services.temporal_factcheck as tf                       # noqa: E402
from services import factcheck_orchestrator as orch            # noqa: E402
from services import factcheck_planner as fsp                  # noqa: E402
from services.factcheck_service import FactCheckService        # noqa: E402

# Производственный случай 14.11.2026 (release/2.58.199, tfr-d4f381867a884cbd).
MATERIAL = (
    "Не вышла бы она блять из обихода. Еще раз повторю, обрезание женщин "
    "настолько древняя традиция, что сша и в помине не было, когда она "
    "появилась \nИ распространена в современном мире в странах, на которые "
    "не имело влияние сша")
REQUEST = (
    "Фактчек, бот, реально есть страны с этой традицией на которые не влияли "
    "такие гегемоны как Франция/Великобритания/Германия/США?")
FB_URL = ("https://www.facebook.com/tvrain/videos/%D0%B6%D0%B5%D0%BD%D1%81"
          "%D0%BA%D0%BE%D0%B5-%D0%BE%D0%B1%D1%80%D0%B5%D0%B7%D0%B0%D0%BD"
          "%D0%B8%D0%B5/412129140568974")
FB_SNIPPET = ("Женское обрезание: что это и зачем его делают? .... ДАННОЕ "
              "СООБЩЕНИЕ (МАТЕРИАЛ) СОЗДАНО И (ИЛИ) РАСПРОСТРАНЕНО "
              "ИНОСТРАННЫМ СРЕДСТВОМ МАССОВОЙ ИНФОРМАЦИИ, ВЫПОЛНЯЮЩИМ "
              "ФУНКЦИИ ИНОСТРАННОГО АГЕНТА, И ...Read more")

ANALYST = json.dumps({
    "factual_verdict": "insufficient_evidence", "temporal_status": "unknown",
    "evaluated_period": {"from": None, "to": None}, "reason": "probe",
    "parts": []}, ensure_ascii=False)
VALIDATOR = json.dumps({
    "agree": True, "corrected_factual_verdict": None,
    "corrected_temporal_status": None, "note": "ok"}, ensure_ascii=False)


class RouteLLM:
    """LLM-двойник: маршрут (модель+endpoint), fallback-адаптер, все стадии."""

    def __init__(self, *, model="route-model",
                 base_url="https://primary.example/api/v1",
                 fallback_model="fallback-model",
                 fallback_base_url="https://fallback.example/api/v1",
                 fallback_on=()):
        self._chat_model = model
        self._base_url = base_url
        self._fallback_model = fallback_model
        self._fallback_base_url = fallback_base_url
        self.fallback_on = set(fallback_on)
        self.calls: list[tuple[str, str, bool]] = []

    async def generate(self, messages, *, step="", fallback_payload_adapter=None,
                       **kw):
        user = messages[-1]["content"]
        adapted = False
        if step in self.fallback_on and fallback_payload_adapter:
            out = fallback_payload_adapter(
                {"model": self._chat_model, "messages": list(messages)})
            if isinstance(out, dict) and out.get("messages"):
                user = out["messages"][-1]["content"]
                adapted = True
        self.calls.append((step, user, adapted))
        if step in ("temporal_verdict", "temporal_fallback"):
            return ANALYST
        if step == "temporal_validator":
            return VALIDATOR
        return "Проверка: данных недостаточно (probe)."

    def user_for(self, step):
        for name, user, _a in self.calls:
            if name == step:
                return user
        return ""


class SubjectLLM(RouteLLM):
    """Отвечает на стадию subject_resolve структурным решением."""

    def __init__(self, subject: str, **kw):
        super().__init__(**kw)
        self._subject = subject

    async def generate(self, messages, *, step="", **kw):
        if step == "subject_resolve":
            return json.dumps({
                "subject": self._subject,
                "material_part": "",
                "request_part": REQUEST,
                "form_request": ""}, ensure_ascii=False)
        return await super().generate(messages, step=step, **kw)


def _env():
    return tf.TemporalClaimEnvelope(
        claim_id="tcl-s15", chat_id=1, target_tg_message_id=10,
        target_revision=1, target_content_hash="h1",
        trigger_tg_message_id=11, claim_text=MATERIAL, claim_span=None,
        source_type="text", attribution={"author": "A"},
        origin_type="channel", origin_sender_user_id=None,
        origin_chat_id=-777, origin_display_name="A",
        repost_received_at=1760000000, original_published_at=1665277000,
        original_published_precision="day", claim_period_from=None,
        claim_period_to=None, claim_period_precision=None,
        date_source="telegram_origin", date_precision="day",
        date_timezone=None, date_uncertainty={}, requested_mode="contextual",
        analysis_as_of=1760000000)


def _kw(cls, **values):
    """Оставить только поля dataclass'а (проба живёт на разных коммитах)."""
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in values.items() if k in names}


def _ref(i, support, url=None):
    return orch.EvidenceRef(**_kw(
        orch.EvidenceRef,
        evidence_id=f"ev-{i}", url=url or f"https://source{i}.example/page",
        support=support, source_kind="secondary", published_at=1665277000,
        claims=("c1",)))


def _coverage(refs, opened=None):
    opened = opened or {}
    unit = fsp.ClaimUnit(claim_id="c1", text="часть тезиса",
                         claim_type=fsp.CLAIM_TYPE_FACT)
    return (fsp.ClaimCoverage(**_kw(
        fsp.ClaimCoverage,
        claim=unit, search_status=fsp.CLAIM_SEARCH_SEARCHED,
        status_detail=fsp.CLAIM_STATUS_PARTIAL,
        outcome=fsp.CLAIM_OUTCOME_PARTIAL,
        evidence=tuple(fsp.ClaimEvidence(**_kw(
            fsp.ClaimEvidence,
            claim_id="c1", evidence_id=r.evidence_id, url=r.url,
            role=fsp.EVIDENCE_ROLE_SUPPORTS, note="probe", strength="direct",
            opened=bool(opened.get(r.evidence_id, False)))) for r in refs),
        citation_ids=tuple(r.evidence_id for r in refs),
        queries_count=1, candidates=len(refs), opened=len(refs))),)


def _outcome(refs, *, budget_exhausted=False, skipped=0, coverage=()):
    text = "фрагмент выдачи " * 200
    return fsp.RetrievalOutcome(**_kw(
        fsp.RetrievalOutcome,
        evidence_map=orch.EvidenceMap(
            refs=tuple(refs), allowlist=tuple(r.evidence_id for r in refs)),
        search_text=text, queries_attempted=4, queries_used=4,
        refs_collected=len(refs), fetch_errors=0,
        budget_exhausted=budget_exhausted, provider_failures=0,
        empty_results=0, irrelevant_results=0, claims=tuple(coverage),
        stop_reason="budget_exhausted" if budget_exhausted
        else "sufficient_evidence",
        fetch_skipped_budget=skipped, fetch_skipped_deadline=skipped,
        search_text_portions=(text,), search_text_total_chars=len(text)))


class CaptureDB:
    def __init__(self):
        self.run = None
        self.evidence = None

    async def record_factcheck_run(self, payload):
        self.run = payload

    async def record_factcheck_evidence(self, run_id, rows, *, max_rows=20):
        self.evidence = {"rows": len(rows), "max_rows": max_rows,
                         "supports": [len(str(r.get("support") or ""))
                                      for r in rows]}
        return len(rows[:max(0, int(max_rows))])


def _ids(payload):
    return re.findall(r"\[(ev-\d+)\]", payload)


def _section(payload, tag):
    start = payload.find(f"<{tag}>")
    end = payload.find(f"</{tag}>")
    return "" if start < 0 or end < 0 else payload[start:end + len(tag) + 3]


def _caps():
    """Какие лимиты объявлены в ЭТОМ дереве (факт из кода, не догадка)."""
    import services.factcheck_planner as p
    out = {}
    for name in ("_EXCERPT_MAX_CHARS", "_MAX_EVIDENCE_REFS",
                 "_SEARCH_TEXT_BUDGET_CHARS", "_BUDGET_SECONDS_DEFAULT",
                 "_BUDGET_SECONDS_MAX", "_REFINE_CALLS_DEFAULT",
                 "_MAX_QUERIES_TOTAL_DEFAULT", "_CLAIM_UNITS_HARD_CAP",
                 "FACTCHECK_EXCERPT_CHARS", "FACTCHECK_PAGE_SIZE",
                 "FACTCHECK_QUERIES_TOTAL", "FACTCHECK_SEARCH_TEXT_CHARS",
                 "FACTCHECK_BUDGET_SECONDS", "FACTCHECK_CLAIM_PORTION",
                 "FACTCHECK_PRIMARY_FETCHES"):
        if hasattr(p, name):
            out[name] = getattr(p, name)
    try:
        from services import mca_gates
        out["temporal_max_evidence_per_run()"] = \
            mca_gates.temporal_max_evidence_per_run()
    except Exception as exc:                       # pragma: no cover
        out["temporal_max_evidence_per_run()"] = f"error:{exc}"
    src = (inspect.getsource(p) + inspect.getsource(tf)
           + inspect.getsource(sys.modules[FactCheckService.__module__]))
    out["support_cut_1200_in_rows"] = "[:1200]" in src
    out["assignments_16384"] = len(re.findall(r"=\s*16384\b", src))
    out["has_capacity_resolver"] = hasattr(
        sys.modules[FactCheckService.__module__], "_route_capacity")
    out["has_subject_resolver"] = hasattr(orch, "resolve_check_subject")
    try:
        import services.model_capacity as mc
        window, source = mc.resolve_evidence_window_tokens(
            "unknown-model-xyz", "https://unknown.example/api/v1")
        out["unknown_model_window"] = [window, source]
        out["evidence_budget_for_unknown"] = mc.evidence_window_for_tokens(
            window) if hasattr(mc, "evidence_window_for_tokens") else None
        out["output_reserve_for_unknown"] = (
            mc.output_reserve_tokens(window)
            if hasattr(mc, "output_reserve_tokens") else None)
        out["default_route_window"] = [
            *mc.resolve_evidence_window_tokens()]
    except Exception as exc:
        out["capacity_error"] = f"{type(exc).__name__}: {exc}"
    return out


async def _subject():
    """Сохраняется ли пользовательский вопрос в предмете проверки."""
    from services.factcheck_planner import _claim_units
    units = _claim_units([{"text": REQUEST},
                          {"text": MATERIAL}], MATERIAL, cap=32)
    units_subject = _claim_units([{"text": REQUEST}], REQUEST, cap=32)
    out = {
        "material_chars": len(MATERIAL),
        "request_chars": len(REQUEST),
        "units_from_material_claim": [u[:90] for u in units],
        "units_request_only": [u[:90] for u in units_subject],
        "request_survives_in_material_claim": bool(
            any("страны" in u for u in units)),
        "subject_resolver": hasattr(orch, "resolve_check_subject"),
    }
    llm = SubjectLLM(REQUEST)
    try:
        subj = await orch.resolve_check_subject(
            type("S", (), {"llm": llm})(), material_text=MATERIAL,
            request_text=REQUEST, material_author="Цибуля",
            request_author="A", material_tg_message_id=10,
            request_tg_message_id=11, chat_id=1)
        out["subject_text"] = subj.text[:300]
        out["subject_origin"] = getattr(subj, "origin", "")
        out["subject_resolved_by"] = getattr(subj, "resolved_by", "")
        out["subject_keeps_request"] = bool(
            REQUEST[:40] in (subj.text or "")
            or "страны" in (subj.text or "")
            or (getattr(subj, "request_text", "") or "") == REQUEST)
    except Exception as exc:
        out["subject_error"] = f"{type(exc).__name__}: {exc}"
    return out


async def _delivery_case(name, refs, *, window=None, windows=None,
                         coverage, llm=None, budget_exhausted=False,
                         skipped=0, fallback_on=()):
    import services.factcheck_service as fcs
    import services.model_capacity as mc
    patched = False
    original = getattr(mc, "resolve_evidence_window_tokens", None)
    calls = []
    windows = windows or {}

    if original is not None:
        def _resolve(model=None, base_url=None):
            calls.append((model, base_url))
            if (model, base_url) in windows:
                return windows[(model, base_url)], "probe"
            return (window if window is not None else 1_000_000), "probe"
        mc.resolve_evidence_window_tokens = _resolve
        patched = True
    llm = llm or RouteLLM(fallback_on=fallback_on)
    service = FactCheckService(aggregator=None, llm=llm)
    outcome = _outcome(refs, coverage=coverage,
                       budget_exhausted=budget_exhausted, skipped=skipped)
    run = await service.check_claim_envelope(_env(), retrieval=outcome)
    if patched:
        mc.resolve_evidence_window_tokens = original
    analyst = llm.user_for("temporal_verdict")
    validator = llm.user_for("temporal_validator")
    used = llm.user_for("temporal_fallback") or analyst
    meta = {}
    block = _section(analyst, "evidence_delivery")
    if block:
        try:
            meta = json.loads(block[len("<evidence_delivery>"):-
                                  len("</evidence_delivery>")]
                              .replace("&quot;", '"').replace("&amp;", "&")
                              .replace("&lt;", "<").replace("&gt;", ">"))
        except Exception as exc:                   # pragma: no cover
            meta = {"parse_error": str(exc)}
    db = CaptureDB()
    try:
        await tf.record_temporal_run(
            db, run, scope="probe",
            max_evidence=max(len(run.evidence_rows or ()), 1))
    except Exception as exc:                       # pragma: no cover
        db.evidence = {"error": str(exc)}
    return {
        "case": name,
        "input": {"refs": len(refs),
                  "support_chars": [len(r.support) for r in refs],
                  "total_chars": sum(len(r.support) for r in refs),
                  "window_tokens": window},
        "analyst": {
            "payload_chars": len(analyst),
            "evidence_rows": len(_ids(analyst)),
            "evidence_ids": _ids(analyst)[:40],
            "evidence_chars": len(_section(analyst, "evidence")),
            "delivery_meta": meta,
            "budget_note": ("Поиск остановлен ограничением бюджета"
                            in analyst),
            "provenance_opened_yes": "opened=yes" in analyst,
            "provenance_opened_no": "opened=no" in analyst,
            "search_text_leaked": bool(outcome.search_text
                                       and outcome.search_text[:120]
                                       in analyst),
        },
        "validator": {"payload_chars": len(validator),
                      "evidence_rows": len(_ids(validator))},
        "fallback": {"adapted_delivery_meta": (
            json.loads(_section(used, "evidence_delivery")[
                len("<evidence_delivery>"):-len("</evidence_delivery>")]
                .replace("&quot;", '"').replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">"))
            if _section(used, "evidence_delivery") else {})},
        "capacity_calls": calls[:4],
        "durable": {"evidence_rows": (db.evidence or {}).get("rows"),
                    "max_rows": (db.evidence or {}).get("max_rows"),
                    "supports": (db.evidence or {}).get("supports")},
        "run_evidence_rows": len(run.evidence_rows),
    }


async def _main():
    result = {"caps": _caps(), "subject": await _subject(), "cwd": os.getcwd()}
    fb = _ref(1, FB_SNIPPET, url=FB_URL)
    wide = [_ref(i, ("источник %d: " % i) + "практика задокументирована "
                    + "данные " * 300) for i in range(1, 13)]
    many = [_ref(i, "выдержка " * 130) for i in range(1, 61)]
    result["delivery"] = [
        await _delivery_case(
            "fb-production-single-snippet", [fb], window=1_000_000,
            coverage=_coverage([fb], opened={"ev-1": True}),
            budget_exhausted=True, skipped=7),
        await _delivery_case(
            "wide-12x2000", wide, window=1_000_000,
            coverage=_coverage(wide)),
        await _delivery_case(
            "overflow-60x900-window-3000", many, window=3000,
            coverage=_coverage(many)),
        await _delivery_case(
            "fallback-8x400", [_ref(i, "выдержка " * 70) for i in range(1, 9)],
            window=1_000_000,
            windows={("fallback-model", "https://fallback.example/api/v1"):
                     1000},
            coverage=_coverage([_ref(i, "x") for i in range(1, 9)]),
            fallback_on={"temporal_verdict"}),
    ]
    text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        print("WROTE", sys.argv[1])
    else:
        print(text)


def main():
    asyncio.run(_main())


if __name__ == "__main__":
    main()
