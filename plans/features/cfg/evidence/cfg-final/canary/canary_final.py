# -*- coding: utf-8 -*-
"""CFG-FINAL F1 delta-canary: v2-пайплайн на тестовом контуре @ deployed 8ea6ed4e (2.58.104).

Адаптация cfg06-canary/canary_v2.py (канарейка 20.10 @ 7142ffcf/2.58.99).
Runtime-дерево байт-равно проде 8ea6ed4e (probe-delta.json), дельта фактчек-семьи
с базы канарейки: factcheck_orchestrator (+153/-12, CFG-07C-G egress-guard швы),
factcheck_service (+23/-2, 07D.5 metatext retry). Дельта-проверки: guard-наблюдения
новых швов в логах прогонов.

Ноль сообщений в реальные Telegram-чаты: FakeBot только ЗАПИСЫВАЕТ отправки.
Поиск (Tavily/Exa/DDG) и LLM — РЕАЛЬНЫЕ. db=None → ветка legacy_single.

Режимы: preflight (бесплатно) | g1 | g4 (платные, бюджет 2) | e4 (бесплатно).
"""
import os
import io
import re
import sys
import json
import time
import asyncio
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))    # корень проекта

os.environ["FACTCHECK_PIPELINE_V2_ENABLED"] = "true"   # ДО импорта settings

from config.settings import settings                    # noqa: E402
from services.search_aggregator import SearchAggregator  # noqa: E402
from services.llm_client import LLMClient               # noqa: E402
from services.factcheck_service import FactCheckService  # noqa: E402
from services import factcheck_orchestrator as orch      # noqa: E402
from services import factcheck_planner as fsp            # noqa: E402
from services import factcheck_suitability as fsg        # noqa: E402
from services import factcheck_renderer as fr            # noqa: E402
from services import mca_gates                           # noqa: E402
from services.factcheck_orchestrator import (            # noqa: E402
    FactcheckRequest, run_factcheck)
from aiogram.exceptions import TelegramBadRequest        # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
CHAT_ID = -100999000701          # синтетический chat_id (никто реальный)
TARGET_TG = 7000
TRIGGER_TG = 7001


def guard_observations(log_lines):
    """Дельта-проверка CFG-07C-G: предупреждения новых guard-швов в прогонах.

    Чистые тексты/honesty-классы проходят байт-в-байт (07C-контракт) — для
    честных прогонов ожидаем 0 событий; любое событие фиксируется честно
    (fail-soft repair), не рвёт доставку."""
    ev = [ln for ln in log_lines
          if "speech guard" in ln or "speech guard failed" in ln
          or "egress_guard" in ln or "delivery unguardable" in ln]
    return {"count": len(ev), "lines": ev}

CLAIM_G1 = ("дрожжи — это грибы, а не бактерии, поэтому пробиотики с "
            "Saccharomyces boulardii восстанавливают микрофлору после "
            "антибиотиков")
CLAIM_G4 = ("Население Земли превысило 8 миллиардов человек "
            "15 ноября 2022 года")

EGRESS_FORBIDDEN_RE = orch._EGRESS_FORBIDDEN_RE
ADMIN_TOKENS_RE = re.compile(
    r"(reason_code|gate_version|temporal_status|factual_verdict|"
    r"evaluated_period|evidence_refs|plan_version|factcheck_run|"
    r"factcheck_temporal|queries_attempted|queries_used|budget_exhausted|"
    r"fetch_errors|planner_version|ev-\d+|intent=|mca_event)", re.IGNORECASE)


# ── Контур: моки ─────────────────────────────────────────────────────────────

class FakeBot:
    """Мок Telegram: только запись. Ни одного реального вызова."""
    id = 862000000

    def __init__(self, fail_html_marker=None):
        self.sent = []
        self.actions = []
        self.fail_html_marker = fail_html_marker

    async def send_message(self, chat_id, text, **kw):
        if self.fail_html_marker and kw.get("parse_mode") \
                and self.fail_html_marker in text:
            raise TelegramBadRequest(method="sendMessage",
                                     message="Bad Request: can't parse "
                                             "entities")
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return type("M", (), {"message_id": 555})()

    async def send_chat_action(self, chat_id, action, **kw):
        self.actions.append((chat_id, action))
        return True

    async def set_message_reaction(self, chat_id, message_id, **kw):
        self.actions.append((chat_id, "reaction:%s" % message_id))
        return True


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def get_update_marker(self, key, *, ttl_seconds):
        return None

    async def set_update_marker(self, key, payload, *, ttl_seconds):
        self.store["marker:" + key] = payload

    def build_key(self, slug, raw):
        from services.smart_cache import build_key, normalize_text
        return build_key(slug, normalize_text(str(raw)))


# ── Записывающие прокси (поведение не меняют) ────────────────────────────────

class RecordingAggregator:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    async def search(self, query, max_symbols):
        t0 = time.monotonic()
        try:
            text = await self.inner.search(query, max_symbols)
            self.calls.append({
                "query": query, "max_symbols": max_symbols, "ok": True,
                "latency_s": round(time.monotonic() - t0, 2),
                "result_chars": len(str(text or "")),
                "urls": re.findall(r"https?://\S+", str(text or ""))[:8],
            })
            return text
        except Exception as exc:
            self.calls.append({
                "query": query, "max_symbols": max_symbols, "ok": False,
                "error": type(exc).__name__,
                "latency_s": round(time.monotonic() - t0, 2)})
            raise


class RecordingLLM:
    def __init__(self, inner):
        self.inner = inner
        self.calls = []

    async def generate(self, messages, **kw):
        t0 = time.monotonic()
        in_chars = sum(len(str(m.get("content") or "")) for m in messages)
        rec = {"module": kw.get("module"), "step": kw.get("step"),
               "model": getattr(self.inner, "_model_name", None)
               or getattr(self.inner, "model_name", None)
               or settings.LLM_MODEL_NAME,
               "in_chars": in_chars, "in_messages": len(messages)}
        try:
            raw = await self.inner.generate(messages, **kw)
            rec.update({"ok": True,
                        "latency_s": round(time.monotonic() - t0, 2),
                        "out_chars": len(str(raw or ""))})
            self.calls.append(rec)
            return raw
        except Exception as exc:
            rec.update({"ok": False, "error": type(exc).__name__,
                        "latency_s": round(time.monotonic() - t0, 2)})
            self.calls.append(rec)
            raise

    def __getattr__(self, name):
        return getattr(self.inner, name)


class Run:
    """Ёмкость одного прогона: прокси + патч первоисточников."""

    def __init__(self):
        self.agg = RecordingAggregator(SearchAggregator())
        self.llm = RecordingLLM(LLMClient(
            settings.LLM_BASE_URL, settings.LLM_API_KEY,
            settings.LLM_MODEL_NAME, settings.EMBEDDING_MODEL_NAME,
            embed_base_url=settings.EMBEDDING_BASE_URL,
            embed_api_key=settings.EMBEDDING_API_KEY))
        self.svc = FactCheckService(self.agg, self.llm)
        self.retrieval_outcomes = []
        self.primary = []
        self._orig_run_retrieval = fsp.run_retrieval
        self._orig_fetch_primary = fsp.fetch_primary_evidence

    def install(self):
        run = self

        async def rec_run_retrieval(plan, **kw):
            outcome = await run._orig_run_retrieval(plan, **kw)
            run.retrieval_outcomes.append({
                "queries_attempted": outcome.queries_attempted,
                "queries_used": outcome.queries_used,
                "refs_collected": outcome.refs_collected,
                "fetch_errors": outcome.fetch_errors,
                "budget_exhausted": outcome.budget_exhausted,
                "planner_version": outcome.planner_version,
                "search_text_chars": len(outcome.search_text or ""),
                "evidence_map": _evmap_json(outcome.evidence_map),
            })
            return outcome

        async def rec_fetch_primary(url, **kw):
            ref = await run._orig_fetch_primary(url, **kw)
            run.primary.append({
                "url": url,
                "ok": ref is not None,
                "source_kind": getattr(ref, "source_kind", None),
                "published_at": getattr(ref, "published_at", None),
                "excerpt_chars": len(getattr(ref, "support", "") or "")
                if ref else 0})
            return ref

        fsp.run_retrieval = rec_run_retrieval
        fsp.fetch_primary_evidence = rec_fetch_primary

    def uninstall(self):
        fsp.run_retrieval = self._orig_run_retrieval
        fsp.fetch_primary_evidence = self._orig_fetch_primary


def _evmap_json(evmap):
    if evmap is None:
        return None
    return {"allowlist": list(evmap.allowlist), "refs": [
        {"evidence_id": r.evidence_id, "url": r.url, "support": r.support,
         "source_kind": r.source_kind, "published_at": r.published_at}
        for r in evmap.refs]}


class CapHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append("%s %s: %s" % (record.levelname, record.name,
                                             record.getMessage()))
        except Exception:
            pass


def relevant_logs(lines):
    keep = ("factcheck", "SearchAggregator", "mca_event", "llm_client",
            "llm", "temporal", "safe_fetch")
    return [ln for ln in lines
            if any(k.lower() in ln.lower() for k in keep)]


# ── Детерминированный офлайн-снимок (гейт + план; без оплаты) ────────────────

def offline_snapshot(claim):
    decision, ctx = asyncio.get_event_loop().run_until_complete(
        fsg.evaluate_with_expansion(None, CHAT_ID, claim_text=claim,
                                    user_hint=None,
                                    target_tg_message_id=TARGET_TG,
                                    trigger_tg_message_id=TRIGGER_TG))
    plan = fsp.build_retrieval_plan(decision, ctx=ctx, claim_text=claim)
    snap = {
        "decision": None if decision is None else {
            "decision": decision.decision,
            "claim_type": decision.claim_type,
            "claim_items": [{"text": i.text, "verifiable": i.verifiable,
                             "source": i.source}
                            for i in (decision.claim_items or ())],
            "scope": decision.scope,
            "reason_code": decision.reason_code,
            "confidence": decision.confidence,
            "temporal_hint": decision.temporal_hint},
        "plan": None if plan is None else {
            "queries": [{"text": q.text, "intent": q.intent,
                         "max_symbols": q.max_symbols}
                        for q in plan.queries],
            "needs_web": plan.needs_web,
            "needs_primary_fetch": plan.needs_primary_fetch,
            "dropped_privacy": list(plan.dropped_privacy)},
    }
    return decision, plan, snap


# ── Платный прогон v2 ────────────────────────────────────────────────────────

async def run_v2(claim, *, user_hint=None):
    run = Run()
    bot = FakeBot()
    cache = FakeCache()
    req = FactcheckRequest(chat_id=CHAT_ID,
                           trigger_tg_message_id=TRIGGER_TG,
                           target_tg_message_id=TARGET_TG,
                           target_text=claim, user_hint=user_hint,
                           kind="reply")
    run.install()
    t0 = time.monotonic()
    error = None
    try:
        await run_factcheck(req, service=run.svc, db=None, bot=bot,
                            cache=cache)
    except Exception as exc:                      # не ожидается; фиксируем
        error = "%s: %s" % (type(exc).__name__, exc)
    dur = round(time.monotonic() - t0, 2)
    run.uninstall()
    return {
        "claim": claim, "wall_seconds": dur, "orchestrator_error": error,
        "sent": bot.sent, "chunk_lens": [len(s["text"]) for s in bot.sent],
        "aggregator_calls": run.agg.calls, "llm_calls": run.llm.calls,
        "primary_fetches": run.primary,
        "retrieval_outcomes": run.retrieval_outcomes,
    }


# ── Проверки строк леджера ───────────────────────────────────────────────────

def check_payload(payload_sent, evmap, claim):
    """Общие проверки user-payload против EvidenceMap."""
    checks = {}
    texts = [s["text"] for s in payload_sent]
    joined = "\n".join(texts)
    checks["payload_nonempty"] = bool(joined.strip())
    checks["chunks_le_4096"] = all(len(t) <= fr._CHUNK_LIMIT for t in texts)
    checks["parse_mode_html"] = all(s.get("parse_mode") == "HTML"
                                    for s in payload_sent)
    checks["reply_first_only"] = (
        "reply_to_message_id" in (payload_sent[0] if payload_sent else {})
        and all("reply_to_message_id" not in s for s in payload_sent[1:]))
    hrefs = re.findall(r'href="([^"]+)"', joined)
    ev_urls = [r["url"] for r in (evmap or {}).get("refs", [])
               if r.get("url")]
    checks["payload_has_links"] = bool(hrefs)
    checks["hrefs_from_evidencemap_only"] = all(h in ev_urls for h in hrefs)
    checks["no_service_markers"] = not EGRESS_FORBIDDEN_RE.search(joined)
    checks["no_admin_tokens"] = not ADMIN_TOKENS_RE.search(joined)
    checks["not_literal_claim_echo"] = claim.strip().lower() \
        not in joined.lower()
    return checks, hrefs


# ── E4: renderer + delivery на моке (бесплатно) ──────────────────────────────

def _make_presentation(text, links, *, refs=True):
    ev = orch.EvidenceMap(refs=tuple(
        orch.EvidenceRef(evidence_id="ev-%d" % (i + 1), url=u,
                         support="поддержка %d" % (i + 1))
        for i, u in enumerate(links)) if refs else ())
    verdict = orch.CheckedVerdict(verdict_text=text, route="legacy_single",
                                  evidence=ev)
    pres = orch.build_presentation(verdict, reply_to_message_id=TARGET_TG)
    return verdict, pres


def html_tag_balance(chunk):
    """Открыто=закрыто для b/i/a/u/s/code/pre/blockquote; нет рваных тегов."""
    ok = True
    for tag in ("b", "i", "a", "u", "s", "code", "pre", "blockquote"):
        opens = len(re.findall(r"<%s(?:\s[^>]*)?>" % tag, chunk))
        closes = len(re.findall(r"</%s>" % tag, chunk))
        if opens != closes:
            ok = False
    # незакрытая скобка без пары в тексте → признак рваного тега
    if re.search(r"<[a-zA-Z/][^>]*$", chunk, re.M):
        ok = False
    return ok


async def e4_suite(results):
    e4 = {"variants": []}

    # Вариант 1: длинный (> 4096) с URL + Unicode (тире, кавычки, emoji, CJK,
    # combining), несколько предложений → чанки.
    long_body = (
        "Дрожжи относятся к царству грибов — это confirm-факт микробиологии, "
        "подтверждается культуральными и молекулярными признаками. "
        "Saccharomyces boulardii — пробиотический штамм, «грибной», не "
        "бактериальный 🧬✔; применяются после антибиотиков — данные "
        "когортных исследований cochrane-обзоров неоднозначны, но частичный "
        "эффект при диарее путешественников описан.联合国 текст CJK и "
        "combining: áéй — сохранность юникода обязательна. ")
    long_body += "Дополнительное предложение %d с деталями и числами 42%%. " \
                 % 0
    for i in range(1, 40):
        long_body += ("Пункт %d: аргументированная часть вердикта — "
                      "корректное уточнение отделяется от ошибочного тезиса, "
                      "ссылки только из EvidenceMap текущего прогона. " % i)
    links = ["https://ru.wikipedia.org/wiki/Saccharomyces_boulardii",
             "https://example.org/path?q=saccharomyces&lang=ru#frag"]
    verdict, pres = _make_presentation(long_body, links)
    rendered = fr.render_factcheck(pres, verdict)
    bot = FakeBot()
    await fr.deliver_factcheck(bot, CHAT_ID, rendered,
                               reply_to_message_id=TARGET_TG)
    texts = [s["text"] for s in bot.sent]
    joined = "\n".join(texts)
    v1 = {
        "name": "long_unicode_links",
        "render_len": len(rendered.text),
        "chunks": len(texts),
        "chunk_lens": [len(t) for t in texts],
        "chunks_le_4096": all(len(t) <= fr._CHUNK_LIMIT for t in texts),
        "tag_balance_all_chunks": all(html_tag_balance(t) for t in texts),
        "reply_first_only": "reply_to_message_id" in bot.sent[0]
        and all("reply_to_message_id" not in s for s in bot.sent[1:]),
        "parse_mode_html_all": all(s.get("parse_mode") == "HTML"
                                   for s in bot.sent),
        "links_each_exactly_once": {
            u: joined.count('href="%s"' % u.replace("&", "&amp;"))
            for u in links},
        "bibliography_not_duplicated": joined.count("Источники:") == 1,
        "unicode_sentinels_kept": all(
            m in joined for m in ("—", "🧬", "联合", "«грибной»")),
        "combining_kept": ("и" + "̆") in joined
        and ("a" + "́") in joined,
        "chunk_texts": texts,
        "no_service_markers": not EGRESS_FORBIDDEN_RE.search(joined),
        "no_admin_tokens": not ADMIN_TOKENS_RE.search(joined),
    }
    e4["variants"].append(v1)

    # Вариант 2: пустой evidence → честное ограничение, без фальшивых ссылок.
    body2 = ("Утверждение о рекорде осадков не подтверждается доступными "
             "данными. Погодная станция не публикует архив за указанную "
             "дату.")
    verdict2 = orch.CheckedVerdict(verdict_text=body2, route="legacy_single",
                                   evidence=orch.EvidenceMap(
                                       refs=(orch.EvidenceRef(
                                           evidence_id="ev-1", url=None,
                                           support="только текст, без URL"),)))
    pres2 = orch.build_presentation(verdict2, reply_to_message_id=TARGET_TG)
    rendered2 = fr.render_factcheck(pres2, verdict2)
    bot2 = FakeBot()
    await fr.deliver_factcheck(bot2, CHAT_ID, rendered2,
                               reply_to_message_id=TARGET_TG)
    j2 = "\n".join(s["text"] for s in bot2.sent)
    v2 = {
        "name": "empty_evidence",
        "honest_notice_present": "Первоисточники в этот раз открыть не "
                                 "удалось" in j2,
        "no_links_claimed": "href=" not in j2,
        "no_verified_in_internet_claim": not re.search(
            r"проверено в интернете", j2, re.I),
        "parse_mode_html": bot2.sent[0].get("parse_mode") == "HTML"
        if bot2.sent else False,
        "no_service_markers": not EGRESS_FORBIDDEN_RE.search(j2),
    }
    e4["variants"].append(v2)

    # Вариант 3a: перегруженный HTML (инъекции) → экранирование в HTML-режиме.
    evil = ("<script>alert(1)</script> Утверждение <b>ломает</b> разметку & "
            "вставляет <a href=\"javascript:alert(1)\">злу</a> и незакрытый "
            "тег <i тут. <<>> Но факты: дрожжи — грибы.")
    verdict3 = orch.CheckedVerdict(verdict_text=evil, route="legacy_single")
    pres3 = orch.build_presentation(verdict3, reply_to_message_id=TARGET_TG)
    rendered3 = fr.render_factcheck(pres3, verdict3)
    bot3 = FakeBot()
    await fr.deliver_factcheck(bot3, CHAT_ID, rendered3,
                               reply_to_message_id=TARGET_TG)
    j3 = "\n".join(s["text"] for s in bot3.sent)
    real_hrefs = re.findall(r'<a href="([^"]*)"', j3)
    v3a = {
        "name": "html_overload_escaping",
        "parse_mode_html": bool(bot3.sent
                                and bot3.sent[0].get("parse_mode") == "HTML"),
        "raw_script_tag_absent": "<script>" not in j3,
        "escaped_text_present": "&lt;script&gt;" in j3,
        "unmatched_tag_escaped": "&lt;i тут" in j3,
        "real_href_attrs_whitelist_only": all(
            h.startswith(("https://", "http://")) for h in real_hrefs),
        "javascript_not_live_href": not re.search(
            r'<a\s+href="javascript', j3),
        "b_tag_injected_by_verdict_not_live": "&lt;b&gt;ломает&lt;/b&gt;" in j3,
        "sent_len": len(j3),
    }
    e4["variants"].append(v3a)

    # Вариант 3b: Unexpected-ввод — бот отвергает HTML (TelegramBadRequest)
    # → РОВНО сломанный чанк деградирует в plain (literal-текст), остальное
    # не затронуто; содержимое сохраняется.
    long_ok = "\n\n".join(
        "• Пункт %d: корректная часть вердикта сохраняется в HTML-чанке с "
        "целыми тегами и ссылками https://example.org/src%d." % (i, i)
        for i in range(90))
    pres4 = orch.FactcheckPresentation(text=long_ok + "\n\nломает-маркер",
                                       links=(), parse_mode="HTML")
    bot4 = FakeBot(fail_html_marker="ломает-маркер")
    await fr.deliver_factcheck(bot4, CHAT_ID, pres4,
                               reply_to_message_id=TARGET_TG)
    html_sends = [s for s in bot4.sent if s.get("parse_mode")]
    plain_sends = [s for s in bot4.sent if not s.get("parse_mode")]
    v3b = {
        "name": "badrequest_plain_degradation",
        "sends": [{"parse_mode": s.get("parse_mode"),
                   "len": len(s["text"])} for s in bot4.sent],
        "html_chunks_kept": bool(html_sends),
        "exactly_one_plain_degraded": len(plain_sends) == 1,
        "plain_is_visible_text": (
            "<b>" not in plain_sends[0]["text"]
            and "ломает-маркер" in plain_sends[0]["text"])
            if plain_sends else False,
        "plain_reply_absent": all("reply_to_message_id" not in s
                                  for s in plain_sends),
    }
    e4["variants"].append(v3b)
    results["e4"] = e4


import html as _html_mod  # noqa: E402  (stdlib; экранирование/unescape-проверки)


# ── Главная ──────────────────────────────────────────────────────────────────

def dump(name, obj):
    path = os.path.join(OUT_DIR, name)
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    print("WROTE %s" % path)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    cap = CapHandler()
    logging.getLogger().addHandler(cap)
    logging.getLogger().setLevel(logging.INFO)

    boot = {
        "pipeline_v2_enabled": orch.pipeline_v2_enabled(),
        "planner_enabled": fsp.planner_enabled(),
        "flag_hot": None,
        "env_flag": os.environ.get("FACTCHECK_PIPELINE_V2_ENABLED"),
        "event_contract_enabled": mca_gates.event_contract_enabled(),
        "temporal_gate": mca_gates.temporal_factcheck_enabled(),
        "llm_model": settings.LLM_MODEL_NAME,
        "llm_base_url_set": bool(settings.LLM_BASE_URL),
        "tavily_set": bool(settings.TAVILY_API_KEY),
        "exa_set": bool(settings.EXA_API_KEY),
        "prod_binding": {
            "deployed": "8ea6ed4e016cf8fbb23e1447cb02503c54131650",
            "version": "2.58.104",
            "hot_flag_note": "prod flags.factcheck_pipeline_v2=true (bot_settings, deploy-104 v2_flag.touched=false); локально effective=env true",
            "runtime_byte_equal": "probe-delta.json: runtime_delta non-plans = []",
        },
    }
    print("BOOT %s" % json.dumps(boot, ensure_ascii=False))

    if mode == "preflight":
        out = {"boot": boot}
        for key, claim in (("g1", CLAIM_G1), ("g4", CLAIM_G4)):
            decision, plan, snap = asyncio.new_event_loop().run_until_complete(
                _preflight_async(claim))
            out[key] = snap
        dump("preflight.json", out)
        return

    if mode in ("g1", "g4"):
        claim = CLAIM_G1 if mode == "g1" else CLAIM_G4
        decision, plan, snap = asyncio.new_event_loop().run_until_complete(
            _preflight_async(claim))
        record = asyncio.new_event_loop().run_until_complete(run_v2(claim))
        record["boot"] = boot
        record["offline_snapshot"] = snap
        record["logs"] = relevant_logs(cap.lines)
        record["guard_observations"] = guard_observations(record["logs"])
        if mode == "g1":
            evmap = (record["retrieval_outcomes"][0]["evidence_map"]
                     if record["retrieval_outcomes"] else None)
            checks, hrefs = check_payload(record["sent"], evmap, claim)
            joined_q = " ".join(
                q["text"].lower()
                for q in snap["plan"]["queries"]) if snap["plan"] else ""
            checks["queries_not_literal_slice"] = all(
                q["text"].lower() != claim.lower()[:200]
                for q in (snap["plan"]["queries"] if snap["plan"] else []))
            checks["binomen_in_queries"] = (
                "saccharomyces" in joined_q and "boulardii" in joined_q)
            checks["real_search_calls"] = sum(
                1 for c in record["aggregator_calls"] if c["ok"])
            ev_urls = [r["url"] for r in (evmap or {}).get("refs", [])
                       if r.get("url")]
            checks["evidencemap_has_real_url"] = bool(ev_urls)
            checks["atomic_theses_extracted"] = bool(
                snap["decision"]["claim_items"])
            record["checks"] = checks
            record["payload_hrefs"] = hrefs
        else:
            evmap = (record["retrieval_outcomes"][0]["evidence_map"]
                     if record["retrieval_outcomes"] else None)
            checks, hrefs = check_payload(record["sent"], evmap, claim)
            checks["queries_not_literal_slice"] = all(
                q["text"].lower() != claim.lower()[:200]
                for q in (snap["plan"]["queries"] if snap["plan"] else []))
            intents = sorted({q["intent"]
                              for q in (snap["plan"]["queries"]
                                        if snap["plan"] else [])})
            checks["distinct_intents"] = len(intents) >= 2
            checks["temporal_intent_present"] = "temporal_context" in intents
            checks["real_search_calls"] = sum(
                1 for c in record["aggregator_calls"] if c["ok"])
            prim = record["primary_fetches"]
            checks["publication_check_attempted"] = bool(prim)
            published = [p for p in prim if p.get("published_at")]
            checks["publication_date_extracted"] = bool(published)
            record["checks"] = checks
            record["payload_hrefs"] = hrefs
        dump("run-%s.json" % mode, record)
        return

    if mode == "e4":
        results = {"boot": boot}
        asyncio.new_event_loop().run_until_complete(e4_suite(results))
        dump("run-e4.json", results)
        return

    print("UNKNOWN MODE %s" % mode)
    sys.exit(2)


async def _preflight_async(claim):
    decision, ctx = await fsg.evaluate_with_expansion(
        None, CHAT_ID, claim_text=claim, user_hint=None,
        target_tg_message_id=TARGET_TG, trigger_tg_message_id=TRIGGER_TG)
    plan = fsp.build_retrieval_plan(decision, ctx=ctx, claim_text=claim)
    snap = {
        "decision": None if decision is None else {
            "decision": decision.decision,
            "claim_type": decision.claim_type,
            "claim_items": [{"text": i.text, "verifiable": i.verifiable,
                             "source": i.source}
                            for i in (decision.claim_items or ())],
            "scope": decision.scope,
            "reason_code": decision.reason_code,
            "confidence": decision.confidence,
            "temporal_hint": decision.temporal_hint},
        "plan": None if plan is None else {
            "queries": [{"text": q.text, "intent": q.intent,
                         "max_symbols": q.max_symbols} for q in plan.queries],
            "needs_web": plan.needs_web,
            "needs_primary_fetch": plan.needs_primary_fetch,
            "dropped_privacy": list(plan.dropped_privacy)},
    }
    return decision, plan, snap


if __name__ == "__main__":
    main()
