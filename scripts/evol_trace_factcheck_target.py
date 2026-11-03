"""§5.2/§13.26: РЕАЛЬНАЯ трасса пути trigger → target → context → claim →
search → verdict → delivery для пакета EVOL-REPLY-CONTEXT-INTEGRITY-01.

Зачем: прежний `plans/features/evol-reply-context-integrity-01/evidence/
trace-factcheck-target.txt` был собран разовым скриптом вне репозитория и
содержал невозможную пару (`provider_attempts=0` при `provider_failures=2`):
счётчики не выводились из фактических объектов прогона. Здесь трасса
ГЕНЕРИРУЕТСЯ исполнением производственного кода на детерминированной
фикстуре — ни одно значение не пишется руками.

Что реально исполняется (production-функции, не переписанные копии):

* ``services.factcheck_suitability.resolve_context_claim`` — сборка
  окружения, выбор антецедента, ``ContextProbe.feed``;
* ``services.temporal_factcheck.build_envelope`` — резолвер тезиса/цели;
* ``services.factcheck_planner.run_retrieval`` — поиск, извлечение,
  фактические счётчики стадии (``provider_status``/``fetch_errors``/…);
* ``services.factcheck_service.classify_retrieval`` и
  ``services.factcheck_service.evidence_diagnostics`` — класс исхода §11.2 и
  диагностика §11.3 из этих же объектов;
* ``services.temporal_factcheck.verdict_from_payload`` +
  ``services.factcheck_renderer.headline_code`` — вердикт и код заголовка.

Что НЕ исполняется (и почему это честно помечено в трассе):

* LLM-вызовы (аналитик/вербализатор) — детерминированный прогон без сети;
  вердикт берётся из существующего degraded-пути
  ``verdict_from_payload({}, …)`` — это ровно то, что прод делает, когда обе
  попытки аналитика мимо (``factcheck_service.check_claim_envelope``);
* фактическая отправка в Telegram — трасса фиксирует РЕШЕНИЕ доставки
  (``delivery_reply_to``), а не сетевой вызов;
* сеть поисковика: отказ провайдера подаётся на существующем шве
  ``aggregator.search_relevant`` реальным исключением с ``reason``, как это
  делает поисковый слой (``factcheck_planner._attempt``).

Запуск (из корня репозитория):

    python scripts/evol_trace_factcheck_target.py            # печать в stdout
    python scripts/evol_trace_factcheck_target.py --write    # записать артефакт

TEST-LIFECYCLE: CONTRACT (owner=EVOL-REPLY-CONTEXT-INTEGRITY-01 §5.2/§13.26).
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import factcheck_context as fcx          # noqa: E402
from services import factcheck_planner as fcp         # noqa: E402
from services import factcheck_service as fcs         # noqa: E402
from services import factcheck_suitability as fsg     # noqa: E402
from services import temporal_factcheck as tf         # noqa: E402
from services.canonical_context import SpeechProjection  # noqa: E402
from services.factcheck_orchestrator import CheckedVerdict  # noqa: E402
from services.factcheck_renderer import headline_code  # noqa: E402

CHAT_ID = -1007710001
#: Фикстура: цель — пустая реакция (текста нет), триггер — команда «фактчек».
TARGET_TG = 771001          # реакция «ну такое» (пустой текст, без Reply)
TRIGGER_TG = 771002         # команда «фактчек»
TOPIC_TG = 771003           # тематически связанная реплика с проверяемым тезисом
NOISE_TG = 771004           # соседняя ветка (гибриды) — целью стать не должна
TS0 = 1_760_000_000

CLAIM_TEXT = "мышечные волокна бывают двух типов: на силу и на выносливость"
HINT = "волокна мышцы сила выносливость"


def _row(tg_id, *, uid, name, text, ts, reply_to_db=None):
    """Строка ``smart_messages`` в той форме, в которой её видит рендер."""
    return {
        "id": tg_id + 100,
        "tg_message_id": tg_id,
        "chat_id": CHAT_ID,
        "user_id": uid,
        "author_name": name,
        "text": text,
        "caption": None,
        "timestamp": ts,
        "reply_to_id": reply_to_db,
        "is_forward": 0,
        "forward_source": None,
        "media_type": "text",
    }


ROWS = [
    _row(NOISE_TG, uid=99004, name="Гений", ts=TS0,
         text="двойные и тройные гибриды дают перекрестное опыление"),
    _row(TOPIC_TG, uid=99003, name="Васек", ts=TS0 + 60,
         text="мышечные волокна бывают двух типов: на силу и на выносливость,"
              " их прокачивать можно по разному"),
    _row(TARGET_TG, uid=99002, name="Хан", text="", ts=TS0 + 120),
    _row(TRIGGER_TG, uid=99001, name="Пётр", text="фактчек", ts=TS0 + 180,
         reply_to_db=TARGET_TG + 100),
]


class _Db:
    """Только те чтения, которые реально делает pipeline (без сети)."""

    async def get_messages_around(self, chat_id, target, before, after):
        return [dict(r) for r in ROWS]

    async def get_recent_messages(self, chat_id, limit, **kw):
        return [dict(r) for r in ROWS[-limit:]] if limit else []

    async def get_smart_message_by_tg_id(self, chat_id, tg):
        for row in ROWS:
            if row["tg_message_id"] == tg:
                return dict(row)
        return None

    async def get_smart_message_origin_block(self, chat_id, tg):
        row = await self.get_smart_message_by_tg_id(chat_id, tg)
        if row is None:
            return None
        return {"text": row["text"], "caption": row["caption"],
                "sent_at": row["timestamp"], "origin_type": None,
                "origin_sent_at": None, "current_revision": 1,
                "content_hash": None}


class _NullCache:
    """Без кеша: трасса снимает фактический прогон, а не прошлый результат."""

    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        return None


class _ProviderError(RuntimeError):
    """Отказ провайдера на шве агрегатора (``reason`` читает planner)."""

    def __init__(self, reason: str = "provider_error"):
        super().__init__(reason)
        self.reason = reason


class _Aggregator:
    """Детерминированный агрегатор: сеть не нужна, исход задаётся сценарием."""

    def __init__(self, *, mode: str, chunk: str = ""):
        self.mode = mode
        self.chunk = chunk

    async def search_relevant(self, query, max_symbols, *, relevance_terms=(),
                              timeout_budget=None, trace=None):
        if trace is not None:
            trace["provider"] = "fixture_provider"
        if self.mode == "ok":
            return self.chunk
        raise _ProviderError(self.mode)


async def _fetch_text_never(url, **_kw):
    """Извлечение первоисточника, которое реально не удалось."""
    return None


def _claim_plan():
    """План retrieval из фактической claim-декомпозиции (без LLM)."""
    claims = fcp.build_claim_units([], CLAIM_TEXT)
    queries = tuple(
        fcp.SearchQuery(text=CLAIM_TEXT, intent="base",
                        claim_id=claims[0].claim_id if claims else "")
        for _ in range(1))
    return fcp.RetrievalPlan(
        queries=queries, needs_web=True,
        needs_primary_fetch=False, claim_text=CLAIM_TEXT, claims=claims)


async def _run_search(*, mode: str, chunk: str = "",
                      budget_seconds: float | None = 5.0,
                      needs_primary_fetch: bool = False):
    plan = dataclasses.replace(_claim_plan(),
                               needs_primary_fetch=needs_primary_fetch)
    return await fcp.run_retrieval(
        plan, aggregator=_Aggregator(mode=mode, chunk=chunk),
        fetch_text=_fetch_text_never if needs_primary_fetch else None,
        budget_seconds=budget_seconds)


def _verdict(retrieval, retrieval_state: str):
    """Вердикт degraded-пути прод (`check_claim_envelope`) + код заголовка."""
    reason = fcs._RETRIEVAL_REASON.get(retrieval_state)
    return tf.verdict_from_payload({}, ENVELOPE, fallback_reason=reason,
                                   allowed_refs=set())


def _checked(verdict) -> CheckedVerdict:
    """Маппинг temporal → CheckedVerdict (паритет
    ``factcheck_orchestrator._run_envelope_branch``)."""
    return CheckedVerdict(
        verdict_text=verdict.verdict_text, route="envelope_temporal",
        factual_verdict=verdict.factual_verdict,
        temporal_status=verdict.temporal_status,
        evaluated_period=verdict.evaluated_period,
        uncertainty=verdict.uncertainty, reason_code=verdict.reason,
        fallback_used=True)


async def _diagnostics_row(label: str, retrieval, verdict) -> list[str]:
    state = fcs.classify_retrieval(retrieval)
    diag = fcs.evidence_diagnostics(
        retrieval=retrieval, retrieval_state=state, evidence=(), verdict=verdict)
    checked = _checked(verdict)
    order = ("source_query_count", "provider_attempts", "provider_failures",
             "documents_retrieved", "queries_with_results", "extract_attempts",
             "extract_failures", "extract_successes", "fetch_skipped_deadline",
             "irrelevant_results", "off_topic_sources_dropped",
             "relevant_evidence_count", "citable_evidence_count",
             "budget_exhausted", "empty_results", "retrieval_class",
             "technical_reason")
    head = (f"  {label}: class={state} reason={_reason_text(state)} "
            f"headline={headline_code(checked)}")
    counters = "    " + " ".join(
        f"{key}={diag.get(key)}" for key in order if key in diag)
    return [head, counters]


def _reason_text(state: str) -> str:
    return fcs._RETRIEVAL_REASON.get(state, "")


ENVELOPE = None      # заполняется в main() настоящим build_envelope


async def _collect() -> str:
    global ENVELOPE
    db = _Db()
    lines: list[str] = []
    lines.append(
        "EVOL-REPLY-CONTEXT-INTEGRITY-01 §5.2/§13.26 — trace-factcheck-target")
    lines.append(
        "source: scripts/evol_trace_factcheck_target.py — реальный прогон "
        "production-кода на детерминированной фикстуре")
    lines.append(
        "fixture: chat=-1007710001 target=771001 (пустая реакция) "
        "trigger=771002 («фактчек») topic=771003 noise=771004")
    lines.append(
        "не исполнялось: LLM-аналитик/вербализатор (вердикт — degraded-путь "
        "verdict_from_payload({}); текст ответа формирует модель), "
        "фактическая отправка в Telegram (зафиксировано РЕШЕНИЕ доставки), "
        "сеть поисковика (отказ провайдера подан на шве агрегатора)")
    lines.append("")

    # ── 1/7 trigger ────────────────────────────────────────────────────────
    lines.append("[1/7 trigger]")
    trigger_row = next(r for r in ROWS if r["tg_message_id"] == TRIGGER_TG)
    lines.append(f"  trigger_tg_message_id={TRIGGER_TG} "
                 f"author={trigger_row['author_name']} "
                 f"text_len={len(trigger_row['text'])} "
                 f"reply_to_db_id={trigger_row['reply_to_id']}")

    # ── 2/7 target (резолвер тезиса/цели) ──────────────────────────────────
    claims = fcp.build_claim_units([], CLAIM_TEXT)
    lines.append("[2/7 target]")
    lines.append(f"  declared_target_tg_message_id={TARGET_TG} "
                 f"(текста нет → контекстный поиск тезиса)")
    probe = await fsg.resolve_context_claim(
        db, CHAT_ID, target_tg_message_id=TARGET_TG,
        trigger_tg_message_id=TRIGGER_TG,
        reply_to_tg_id=trigger_row["reply_to_id"] and TARGET_TG,
        hint=HINT, cache=_NullCache())
    claim = probe.claim if probe is not None else None
    lines.append(f"  contextual_claim_found={claim is not None} "
                 f"basis={probe.claim_basis if probe else 'none'} "
                 f"source={getattr(claim, 'source', '')} "
                 f"anchor_tg={getattr(claim, 'tg_message_id', None)} "
                 f"author={getattr(claim, 'author', None)}")
    lines.append(f"  window_messages={probe.window_messages if probe else 0} "
                 f"chain_len={probe.chain_len if probe else 0} "
                 f"ambiguous={probe.ambiguous if probe else None}")

    # ── 3/7 context ────────────────────────────────────────────────────────
    lines.append("[3/7 context]")
    feed = probe.feed if probe is not None else ""
    lines.append(f"  feed_chars={len(feed)} "
                 f"raw_ref_leak={'yes' if 'tg:' in feed else 'no'} "
                 f"semantic_relation={'yes' if '↳ по теме' in feed else 'no'} "
                 f"reply_relation={'yes' if '↳ Reply' in feed else 'no'}")
    for feed_line in feed.split("\n"):
        lines.append(f"  | {feed_line}")

    # ── 4/7 claim (envelope) ───────────────────────────────────────────────
    lines.append("[4/7 claim]")
    ref = tf.InputRef(kind="command", chat_id=CHAT_ID,
                      target_tg_message_id=getattr(claim, "tg_message_id",
                                                   None),
                      trigger_tg_message_id=TRIGGER_TG, hint=HINT,
                      claim_text=(claim.text if claim is not None else None),
                      claim_anchor_tg_message_id=getattr(
                          claim, "tg_message_id", None))
    envelope, reject_reason = await tf.build_envelope(db, ref,
                                                      default_mode="contextual")
    ENVELOPE = envelope
    claims_total = len(claims)
    lines.append(f"  envelope_reject_reason={reject_reason} "
                 f"envelope_built={envelope is not None} "
                 f"claim_units={claims_total}")
    if envelope is not None:
        lines.append(f"  claim_text_matches_claim_object="
                     f"{envelope.claim_text == getattr(claim, 'text', '')} "
                     f"anchor_tg={envelope.claim_anchor_tg_message_id} "
                     f"target_tg={envelope.target_tg_message_id} "
                     f"date_source={envelope.date_source} "
                     f"mode={envelope.requested_mode}")

    # ── 5/7 search (реальные счётчики стадии) ──────────────────────────────
    retrieval = await _run_search(mode="provider_error", budget_seconds=5.0)
    lines.append("[5/7 search]")
    lines.append(f"  provider_refusal: queries_attempted="
                 f"{retrieval.queries_attempted} queries_used="
                 f"{retrieval.queries_used} provider_failures="
                 f"{retrieval.provider_failures} fetch_errors="
                 f"{retrieval.fetch_errors} "
                 f"claims={len(tuple(retrieval.claims))}")

    # ── 6/7 verdict ────────────────────────────────────────────────────────
    state = fcs.classify_retrieval(retrieval)
    verdict = _verdict(retrieval, state)
    lines.append("[6/7 verdict]")
    lines.append(f"  retrieval_class={state} reason={_reason_text(state)} "
                 f"factual_verdict={verdict.factual_verdict} "
                 f"temporal_status={verdict.temporal_status} "
                 f"headline={headline_code(_checked(verdict))} "
                 f"fallback_used=True (degraded-путь: пустой payload "
                 f"аналитика)")

    # ── 7/7 delivery ───────────────────────────────────────────────────────
    # Правило прод-хендлера (handlers/factcheck.py:1105-1107): контекстная
    # подмена цели → ответ на ТРИГГЕР, а не на пустое сообщение-цель.
    contextual = bool(claim is not None)
    delivery_reply_to = TRIGGER_TG if contextual else TARGET_TG
    lines.append("[7/7 delivery]")
    lines.append(f"  contextual_target={contextual} "
                 f"delivery_reply_to={delivery_reply_to} "
                 f"правило=handlers/factcheck.py:1105-1107 (сетевой вызов "
                 f"Telegram в детерминированном прогоне не исполняется)")

    # ── §11.3: матрица технических статусов из фактических счётчиков ──────
    lines.append("")
    lines.append("[evidence_status_matrix] (каждая строка — отдельный "
                 "реальный прогон run_retrieval)")
    variants = [
        ("provider_down", dict(mode="provider_error", budget_seconds=5.0)),
        ("deadline", dict(mode="ok", chunk="", budget_seconds=0.0)),
        ("extract_failed", dict(
            mode="ok",
            # Формат выдачи провайдера: URL отдельной строкой, затем сниппет
            # (``evidence_refs_from_search``). Извлечение этого URL реально
            # падает (``_fetch_text_never``) → processing_failed.
            chunk=("https://example.org/fibers\n"
                   "Мышeчные волокна делятся на два типа: на силу и на "
                   "выносливость"),
            budget_seconds=5.0, needs_primary_fetch=True)),
        ("empty_results", dict(mode="empty_results", budget_seconds=5.0)),
        ("no_relevant", dict(mode="irrelevant_results", budget_seconds=5.0)),
        ("no_citable", dict(
            mode="ok",
            chunk=("Мышeчные волокна делятся на два типа: на силу и на "
                   "выносливость"),
            budget_seconds=5.0)),
    ]
    for label, kwargs in variants:
        run = await _run_search(**kwargs)
        run_state = fcs.classify_retrieval(run)
        run_verdict = _verdict(run, run_state)
        lines.extend(await _diagnostics_row(label, run, run_verdict))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="записать артефакт в дерево проекта")
    parser.add_argument("--out", default=None,
                        help="путь артефакта (по умолчанию — evidence пакета)")
    args = parser.parse_args(argv)
    text = asyncio.run(_collect())
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "plans" / "features" / "evol-reply-context-integrity-01"
        / "evidence" / "trace-factcheck-target.txt")
    if args.write:
        out.write_text(text, encoding="utf-8")
        print(f"written: {out} ({len(text)} chars)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
