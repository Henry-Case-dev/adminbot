# -*- coding: utf-8 -*-
"""ASAP2-PROBE: semantic probe of Direct Chat §6 matrix (real L1 + L2 calls).

Isolation: no DB, no Telegram, no prod config writes. Prompts are the code
canons from services/chat_prompts.py (the same bytes the Postgres migration
installs). Transport: one explicit POST per call (no hidden retry cascade), so
the paid-call ledger is exact.

Usage:
    python probe.py structural            # 0 calls (T27-T31)
    python probe.py l1 <ids>               # L1 only for scenario ids
    python probe.py l2 <ids>               # L2 for ids that have L1 raw
    python probe.py chain <id>             # turn2 of a multihop chain
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Code\Python\adminbot")
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from config.settings import settings  # noqa: E402
from services import direct_l1 as l1  # noqa: E402
from services import chat_prompts as cp  # noqa: E402
from services import claim_envelope as ce  # noqa: E402
from services import response_extent as rext  # noqa: E402
from services.prompt_style_blocks import compose_verbalizer_system  # noqa: E402
from services.summary_xml import escape_xml_text  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
RAW = OUT / "raw"
RAW.mkdir(exist_ok=True)
LEDGER = OUT / "ledger.jsonl"
BUDGET = 45

L1_TEMP = l1.l1_temperature(None)          # production: None -> key omitted
L1_MAX = l1.l1_max_output_tokens()         # 512
L2_TEMP = settings.tone_temperature(None)  # production Direct L2 temperature

# Все сценарии — прямое обращение к боту (production FORCE_LINE), чтобы проба
# измеряла семантику уточнения, а не выбор silent/react.
FORCE = l1.FORCE_LINE
CAPS = ("web_search", "fetch_url", "chat_history", "chat_memory",
        "user_memory", "historical_search", "fact_check",
        "image_understanding", "media_download", "transcription",
        "video_summary", "image_generation", "health", "statistics")


def sha12(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def ledger_count() -> int:
    if not LEDGER.exists():
        return 0
    return sum(1 for line in LEDGER.read_text(encoding="utf-8").splitlines()
               if line.strip())


def ledger_append(row: dict) -> None:
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


async def llm(system: str, user: str, *, label: str, temperature, max_tokens):
    n = ledger_count()
    assert n < BUDGET, f"CAP: budget {BUDGET} exhausted (n={n})"
    payload: dict = {"model": settings.LLM_MODEL_NAME,
                     "messages": [{"role": "system", "content": system},
                                  {"role": "user", "content": user}]}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens:
        payload["max_tokens"] = max_tokens
    t0 = time.time()
    resp = None
    for attempt in range(4):
        try:
            resp = httpx.post(
                settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}",
                         "Content-Type": "application/json"},
                json=payload, timeout=180)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout,
                httpx.ReadTimeout) as exc:
            # transport failure: запрос не дошёл до провайдера — не платный
            print(f"   transport retry {attempt + 1} ({type(exc).__name__})")
            time.sleep(3)
    if resp is None:
        raise RuntimeError(f"{label}: transport failed 4x")
    dt = round(time.time() - t0, 2)
    ledger_append({"label": label, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "status": resp.status_code})
    if resp.status_code != 200:
        raise RuntimeError(f"{label}: HTTP {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    msg = data["choices"][0]["message"]
    content = str(msg.get("content") or "")
    rec = {
        "label": label,
        "model_requested": settings.LLM_MODEL_NAME,
        "model_returned": data.get("model"),
        "temperature": temperature if temperature is not None else "omitted",
        "max_tokens": max_tokens or "omitted",
        "system_sha12": sha12(system),
        "system_chars": len(system),
        "user_sha12": sha12(user),
        "messages_sha12": sha12(system + "\x00" + user),
        "finish_reason": data["choices"][0].get("finish_reason"),
        "usage": data.get("usage", {}),
        "latency_s": dt,
        "content": content,
        "reasoning_head": str(msg.get("reasoning_content") or "")[:400],
    }
    print(f"[call {n + 1}/{BUDGET}] {label} | finish="
          f"{rec['finish_reason']} | chars={len(content)} | {dt}s")
    return rec


# ── сценарии ────────────────────────────────────────────────────────────────
def w(*pairs):
    out = []
    for item in pairs:
        if isinstance(item, dict):
            out.append(item)
        else:
            a, t = item
            out.append({"author_name": a, "text": t})
    return out


RENOV = w(("Кирилл", "вчера разобрал санузел до ремонта за час, а сборка заняла "
                     "неделю"),
          ("Маша", "классика: демонтаж всегда быстрый"),
          ("Кирилл", "плитку взяли серо-голубую под бетон"),
          ("Маша", "я бы всё-таки взяла матовую, глянец в санузле выглядит "
                   "дёшево"),
          ("Кирилл", "матовая в санузле плохая идея: на ней разводы видно"),
          ("Маша", "зато не бликует и мыть проще"))

TRIP = w(("Пётр", "на выходных думаем в Суздаль, но не решили, как ехать"),
         ("Маша", "смотря во сколько вставать"),
         ("Пётр", "если рано, то электричка удобнее"))

BOT_TWO = ("по поездке два варианта: 1) электричка в 8:10, идёт два часа "
           "и приходит прямо в город; 2) автобус в 9:00, идёт три часа, но "
           "останавливается у гостиницы")

BOT_PLAN = "я считаю, что планирование важнее импровизации в ремонте"

SCEN = {
 "T01": dict(cls="answered", query="Бот, что происходит?", window=RENOV),
 "T02": dict(cls="answered", query="Что за движ здесь?", window=RENOV),
 "T03": dict(cls="answered", query="О чём спорили сегодня?",
             window=RENOV + TRIP),
 "T04": dict(cls="answered",
             query="Расскажи обо всём важном за последнее время",
             window=RENOV + TRIP),
 "T05": dict(cls="answered", window=TRIP, query=(
     "Бот, у меня сервак на Ubuntu, nginx держит три сайта, хочу добавить "
     "четвёртый с websocket-приложением на FastAPI. Как лучше организовать "
     "конфиг: отдельный server-блок или location внутри существующего, и "
     "надо ли выносить websocket-проксирование в отдельный upstream? Ещё "
     "важно, чтобы сертификаты letsencrypt не слетели при этом, и чтобы "
     "старые три сайта не отвалились.")),
 "T06": dict(cls="answered",
             query="Бот, почему у меня вечером лагает интернет в квартире?",
             window=w(("Маша", "у меня тоже вечером всё тупит"),
                      ("Пётр", "провайдеры в час пик проседают"))),
 "T07": dict(cls="answered", query="Почему?", window=RENOV + [
             {"author_name": "Бот", "text": BOT_PLAN}],
             bot_replies=(BOT_PLAN,)),
 "T08": dict(cls="answered", query="А он правда это говорил?", window=w(
     ("Кирилл", "я плитку сам кладу, мастеров не беру"),
     ("Маша", "ну да, конечно"),
     ("Маша", "Кирилл сказал, что плитку клали мастера"))),
 "T09": dict(cls="answered", query="А что насчёт второго?",
             window=TRIP + [{"author_name": "Бот", "text": BOT_TWO}],
             bot_replies=(BOT_TWO,)),
 "T13": dict(cls="one_reasonable_clarification", query="Бот, скачай это",
             window=RENOV),
 "T15": dict(cls="one_reasonable_clarification", query="Бот, расшифруй",
             window=RENOV),
 "T25": dict(cls="answered", query="а как?", window=[
             {"author_name": "Бот",
              "text": "я перешёл на новый планировщик задач: apscheduler "
                      "вместо cron"}],
             bot_replies=("я перешёл на новый планировщик задач: apscheduler "
                          "вместо cron",)),
 "T20-IN": dict(cls="chain-turn1", query="Бот, что мы обсуждали?",
                window=w(("Маша", "вчера до ночи выбирали плитку"),
                         ("Кирилл", "а в среду спорили про отпуск"),
                         ("Пётр", "сегодня утром я принёс стремянку"),
                         ("Маша", "и договорились, что затирка в субботу"))),
 "T20-STAT": dict(cls="chain-turn1", query="Бот, собери статистику по чату",
                  window=RENOV + TRIP),
 "T20-STAT2": dict(cls="chain-turn1", query="Бот, сколько сообщений в чате?",
                   window=RENOV + TRIP),
 "T20-STAT3": dict(cls="chain-turn1", query="Бот, сколько я тут пишу?",
                   window=RENOV + TRIP),
 "T12": dict(cls="answered", window=TRIP, query=(
     "Бот, разбей план поездки в Суздаль на 5 пунктов, каждый не длиннее "
     "двух строк, без воды и без вступлений.")),
 "T16": dict(cls="one_reasonable_clarification",
             query="Бот, удали это сообщение", window=RENOV),
 "T23-IN": dict(cls="chain-turn1", query="Бот, расшифруй",
                window=w(("Кирилл", "смотрите что записал на прогулке"),
                         {"author_name": "Кирилл", "text": "",
                          "media_type": "voice"})),
}

# Многоходовые цепочки: базовый ход (реальное уточнение бота) + ответ человека.
CHAINS = {
 "T21": dict(base="T13",
             answer="вот ссылка: https://example.com/report.zip", after=[]),
 "T19": dict(base="T13", answer="тот pdf, который Маша скинула",
             after=[{"author_name": "Маша", "text": "",
                     "media_type": "document"}]),
 "T23": dict(base="T15", answer="вот это",
             after=[{"author_name": "Кирилл", "text": "",
                     "media_type": "voice"}]),
 "T20": dict(base="T20-STAT", answer="сегодня", after=[]),
}


def speech_hints(text: str) -> str:
    """Ровно то, что рендерит DirectChatService._l1_speech_hints (без reply)."""
    u = ce.build_speech_understanding(text, has_reply_parent=False,
                                      is_group=True)
    if u is None or not u.active:
        return ""
    parts = [f"act={u.speech_act}"]
    if u.quote:
        parts.append("quote")
    if u.negation:
        parts.append("negation")
    if u.humor_risk:
        parts.append("humor_risk")
    if u.clarify == ce.CLARIFY_ASSUME:
        parts.append("clarify=assume")
    return " ".join(parts)


def current_question(query: str) -> str:
    body = re.sub(r"^(?:бот|@[\w_]+)[,:]?\s*", "", str(query).strip(),
                  flags=re.IGNORECASE)
    if not body:
        return ""
    return f"<Current_Question>\n{escape_xml_text(body)}\n</Current_Question>"


def l1_context(sc: dict) -> str:
    return l1.build_l1_context(
        query=sc["query"], current_question=current_question(sc["query"]),
        reply_block=sc.get("reply_block", ""), window=sc.get("window", []),
        speaker="Кирилл", addressee="чат", memory_hints="",
        speech_hints=speech_hints(sc["query"]), capabilities=CAPS,
        force_line=FORCE, persona_frame="",
        bot_replies=tuple(sc.get("bot_replies", ())))


def l2_system(plan) -> str:
    extent = (rext.render_extent_block(plan.to_response_plan())
              if plan is not None else "")
    return compose_verbalizer_system(
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, l1.plan_response_mode(plan),
        "plain", html_safe=True, character_block="", style_directives="",
        extent_block=extent)


def l2_user(sc: dict, plan, conversation: list[dict]) -> str:
    plan_block = l1.build_l2_plan_block(
        plan, rejected=(),
        clarification=bool(getattr(plan, "needs_clarification", False)),
        low_confidence=(getattr(plan, "confidence_bucket", "high") == "low"))
    hist = "\n".join(f"{row['author_name']}: {row['text']}"
                     for row in conversation if row.get("text"))
    parts = []
    if plan_block:
        parts.append(plan_block)
    if hist:
        parts.append("<Recent_Messages>\n" + hist + "\n</Recent_Messages>")
    parts.append(current_question(sc["query"]) or sc["query"])
    return "\n\n".join(parts)


async def run_l1(sid: str, sc: dict, *, suffix: str = "") -> dict:
    ctx = l1_context(sc)
    rec = await llm(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT, ctx,
                    label=f"L1 {sid}{suffix}", temperature=L1_TEMP,
                    max_tokens=L1_MAX)
    rec["context"] = ctx
    plan_obj = l1.parse_l1_plan(rec["content"])
    repair = None
    if plan_obj is None:      # production bounded repair: ровно 1 повтор
        msgs = l1.build_repair_messages(
            [{"role": "system", "content": cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT},
             {"role": "user", "content": ctx}], rec["content"])
        repair = await llm(msgs[0]["content"], msgs[-1]["content"],
                           label=f"L1 {sid}{suffix} repair",
                           temperature=L1_TEMP, max_tokens=L1_MAX)
        plan_obj = l1.parse_l1_plan(repair["content"])
    rec["plan"] = None if plan_obj is None else {
        "action": plan_obj.action,
        "response_act": plan_obj.response_act,
        "extent": plan_obj.extent,
        "tone": plan_obj.tone,
        "structure": plan_obj.structure,
        "tool_policy": plan_obj.tool_policy,
        "capabilities_needed": list(plan_obj.capabilities_needed),
        "needs_clarification": plan_obj.needs_clarification,
        "clarification_target": plan_obj.clarification_target,
        "confidence": plan_obj.confidence,
        "confidence_bucket": plan_obj.confidence_bucket,
    }
    rec["repair"] = repair
    rec["speech_hints"] = speech_hints(sc["query"])
    path = RAW / f"{sid}{suffix}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"   plan: {json.dumps(rec['plan'], ensure_ascii=False)}")
    return rec


def load_raw(sid: str, suffix: str = "") -> dict | None:
    path = RAW / f"{sid}{suffix}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


async def run_l2(sid: str, sc: dict, plan_raw: dict, *,
                 conversation=None, suffix: str = "") -> dict:
    plan = l1.parse_l1_plan(plan_raw["content"])
    if plan is None and plan_raw.get("repair"):
        plan = l1.parse_l1_plan(plan_raw["repair"]["content"])
    if plan is None:
        raise RuntimeError(f"{sid}: no parsed L1 plan for L2")
    conv = conversation if conversation is not None else sc.get("window", [])
    sys_p = l2_system(plan)
    usr = l2_user(sc, plan, conv)
    rec = await llm(sys_p, usr, label=f"L2 {sid}{suffix}",
                    temperature=L2_TEMP, max_tokens=None)
    rec["system_prompt"] = sys_p
    rec["user_content"] = usr
    rec["plan_used"] = plan_raw.get("plan")
    path = RAW / f"{sid}{suffix}.L2.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"   text: {rec['content'][:400]}")
    return rec


def structural() -> dict:
    """T27-T31: 0 платных вызовов."""
    cases = {
        "T27 false": {"action": "reply", "needs_clarification": False},
        "T28 'false'": {"action": "reply", "needs_clarification": "false"},
        "T28b 'true'": {"action": "reply", "needs_clarification": "true"},
        "T28c 1": {"action": "reply", "needs_clarification": 1},
        "T28d []": {"action": "reply", "needs_clarification": []},
        "T28e {}": {"action": "reply", "needs_clarification": {}},
        "T29 null": {"action": "reply", "needs_clarification": None},
        "T30 true+empty": {"action": "reply", "needs_clarification": True,
                           "clarification_target": ""},
        "T31 clarification-act+false": {
            "action": "reply", "response_act": "clarification",
            "needs_clarification": False},
        "T31b clarification-act+true": {
            "action": "reply", "response_act": "clarification",
            "needs_clarification": True, "clarification_target": ""},
    }
    out = {}
    for name, data in cases.items():
        plan = l1.normalize_l1_plan(dict(data))
        block = l1.build_l2_plan_block(
            plan, clarification=bool(getattr(plan, "needs_clarification",
                                             False)))
        out[name] = {
            "needs_clarification": plan.needs_clarification,
            "clarification_target": plan.clarification_target,
            "response_act": plan.response_act,
            "plan_block": block,
            "generic_directive": ("недостающий обязательный предмет" in block),
            "fixed_question_branch": rext.clarification_question(
                plan.to_response_plan(), has_target=False),
        }
    out["speech_T25"] = {
        "short_dependency": ce.build_speech_understanding(
            "а как?", has_reply_parent=False,
            is_group=True).short_dependency,
        "clarify": ce.build_speech_understanding(
            "а как?", has_reply_parent=False, is_group=True).clarify,
        "hints_rendered": speech_hints("а как?"),
        "ask_branch_exists": any(
            "задай" in s and "вопрос" in s for s in
            [ce.render_speech_block(ce.build_speech_understanding(
                "а как?", has_reply_parent=False,
                is_group=True))]),
    }
    (OUT / "structural.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    ids = [s for s in (sys.argv[2].split(",") if len(sys.argv) > 2 else []) if s]
    if mode == "structural":
        structural()
        return
    if mode == "l1":
        for sid in ids:
            await run_l1(sid, SCEN[sid])
        return
    if mode == "l2":
        for sid in ids:
            raw = load_raw(sid)
            assert raw is not None, f"{sid}: run l1 first"
            await run_l2(sid, SCEN[sid], raw)
        return
    if mode == "chain":
        sid = ids[0]
        spec = CHAINS[sid]
        base, answer = spec["base"], spec["answer"]
        sc = SCEN[base]
        prev = load_raw(base)
        prev_l2 = load_raw(base, ".L2")
        assert prev, "base turn must be complete"
        bot_q = (prev_l2 or {}).get("content", "").strip()
        chain_sc = {
            "query": answer,
            "window": list(sc.get("window", [])) + list(spec.get("after", []))
            + [{"author_name": "Кирилл", "text": sc["query"]},
               {"author_name": "Бот", "text": bot_q or "(бот не ответил)"},
               {"author_name": "Кирилл", "text": answer}],
            "bot_replies": ((bot_q,) if bot_q else ()),
        }
        rec = await run_l1(sid, chain_sc, suffix=".turn2")
        plan = rec.get("plan") or {}
        if not plan.get("capabilities_needed") and \
                not plan.get("needs_clarification"):
            await run_l2(sid, chain_sc, rec, suffix=".turn2",
                         conversation=chain_sc["window"])
        else:
            print("   (L2 skipped: tool route / clarification plan)")
        return
    raise SystemExit("mode: structural|l1|l2|chain")


if __name__ == "__main__":
    asyncio.run(main())
