# -*- coding: utf-8 -*-
"""ASAP2 LANE BOUNDARY: T20 continuation + T10 marker (3 paid calls max).

Изоляция: без БД/Telegram/прода/SSH. Сборка контекста — прод-функции
(`direct_l1.build_l1_context`, `build_l2_plan_block`, канон
`chat_prompts.DIRECT_VERBALIZER_SYSTEM_PROMPT`). Один POST на вызов,
без ретраев по HTTP-статусу, без fallback-модели; ledger дописывается
строкой на вызов.

Usage: py -3 probe_t20_boundary.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Code\Python\adminbot")
ENV_SOURCE = ROOT / ".env"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ENV_SOURCE)

import httpx  # noqa: E402

from config.settings import settings  # noqa: E402
from services import chat_prompts as cp  # noqa: E402
from services import direct_chat_service as dcs  # noqa: E402
from services import direct_l1 as l1  # noqa: E402
from services import response_extent as rext  # noqa: E402
from services.prompt_style_blocks import compose_verbalizer_system  # noqa: E402
from types import SimpleNamespace  # noqa: E402

HERE = ROOT / "plans/features/asap2-direct-chat/evidence/probe-r2"
RAW = HERE / "raw"
OUT = RAW / "t20_boundary"
OUT.mkdir(exist_ok=True)
LEDGER = OUT / "ledger.jsonl"
BUDGET = 5

L1_TEMP = l1.l1_temperature(None)
L1_MAX = l1.l1_max_output_tokens()
L2_TEMP = settings.tone_temperature(None)
FORCE = l1.FORCE_LINE


def sha12(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(x) for x in
            LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]


async def llm(system: str, user: str, *, label: str, temperature, max_tokens):
    n = len(ledger_rows())
    assert n < BUDGET, f"CAP: budget {BUDGET} exhausted (n={n})"
    payload: dict = {"model": settings.LLM_MODEL_NAME,
                     "messages": [{"role": "system", "content": system},
                                  {"role": "user", "content": user}]}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens:
        payload["max_tokens"] = max_tokens
    t0 = time.time()
    resp = httpx.post(
        settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {settings.LLM_API_KEY}",
                 "Content-Type": "application/json"},
        json=payload, timeout=180)
    dt = round(time.time() - t0, 2)
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"n": n + 1, "label": label,
                             "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "status": resp.status_code},
                            ensure_ascii=False) + "\n")
    if resp.status_code != 200:
        raise RuntimeError(f"{label}: HTTP {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    msg = data["choices"][0]["message"]
    content = str(msg.get("content") or "")
    rec = {"label": label, "model_requested": settings.LLM_MODEL_NAME,
           "model_returned": data.get("model"), "base_url": settings.LLM_BASE_URL,
           "temperature": temperature if temperature is not None else "omitted",
           "max_tokens": max_tokens or "omitted",
           "system_sha12": sha12(system), "system_chars": len(system),
           "user_sha12": sha12(user), "messages_sha12": sha12(system + "\x00" + user),
           "finish_reason": data["choices"][0].get("finish_reason"),
           "usage": data.get("usage", {}), "latency_s": dt,
           "system_prompt": system, "user_content": user, "content": content,
           "reasoning_head": str(msg.get("reasoning_content") or "")[:400]}
    print(f"[call {n + 1}/{BUDGET}] {label} | finish={rec['finish_reason']} "
          f"| chars={len(content)} | {dt}s")
    return rec


# ── прод-сборка L1 (те же хелперы, что у сервиса) ──────────────────────────
def query_of(text: str) -> str:
    return dcs._strip_direct_prefix(text)


def l1_context(text: str, window, caps) -> str:
    msg = SimpleNamespace(text=text, caption=None, reply_to_message=None,
                          message_id=1, from_user=SimpleNamespace(
                              first_name="Кирилл", id=101),
                          chat=SimpleNamespace(type="supergroup"))
    return l1.build_l1_context(
        query=query_of(text),
        current_question=dcs.DirectChatService._render_current_question(
            SimpleNamespace(), msg),
        reply_block=dcs.DirectChatService._l1_reply_block(msg),
        window=window, speaker="Кирилл", addressee="чат", memory_hints="",
        speech_hints="", capabilities=caps, force_line=FORCE,
        persona_frame="", bot_replies=())


def plan_of(rec):
    plan = l1.parse_l1_plan(rec["content"])
    if plan is None and rec.get("repair"):
        plan = l1.parse_l1_plan(rec["repair"])
    return plan


async def run_l1(label: str, text: str, window, caps) -> dict:
    ctx = l1_context(text, window, caps)
    rec = await llm(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT, ctx, label=label,
                    temperature=L1_TEMP, max_tokens=L1_MAX)
    rec["context"] = ctx
    plan = l1.parse_l1_plan(rec["content"])
    rec["class"] = ("unparsed" if plan is None
                    else "clarification" if plan.needs_clarification
                    else "tool_use" if plan.capabilities_needed else "answer")
    rec["plan"] = None if plan is None else {
        "action": plan.action, "response_act": plan.response_act,
        "capabilities_needed": list(plan.capabilities_needed),
        "needs_clarification": plan.needs_clarification,
        "clarification_target": plan.clarification_target,
        "confidence": plan.confidence}
    (OUT / f"{label}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("   plan:", json.dumps(rec["plan"], ensure_ascii=False))
    return rec


# ── прод-сборка L2 (канон + блок плана + окно + inline-пометка) ────────────
def l2_run(label: str, plan, window, question: str, note: bool,
           clarification: bool = False) -> dict:
    extent = rext.render_extent_block(plan.to_response_plan())
    sys_p = compose_verbalizer_system(
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, l1.plan_response_mode(plan),
        "plain", html_safe=True, character_block="", style_directives="",
        extent_block=extent)
    plan_block = l1.build_l2_plan_block(
        plan, rejected=(), clarification=clarification,
        low_confidence=(plan.confidence_bucket == "low"))
    hist = "\n".join(f"{r['author_name']}: {r['text'] or '[медиа]'}"
                     for r in window)
    parts = [plan_block]
    head = f"фон: дословно последние {len(window)} сообщений"
    if note:                      # как в проде `_build_global_context_parts`
        head += f" ({l1.HISTORY_PARTIAL_INLINE})"
    parts.insert(0, head)
    if hist:
        parts.append("<Recent_Messages>\n" + hist + "\n</Recent_Messages>")
    parts.append(question)
    usr = "\n\n".join(p for p in parts if p)
    return sys_p, usr


async def main() -> None:
    user = dcs.DirectChatService._render_current_question(
        SimpleNamespace(), SimpleNamespace(
            text="", caption=None, reply_to_message=None, message_id=1,
            from_user=SimpleNamespace(first_name="Кирилл", id=101),
            chat=SimpleNamespace(type="supergroup")))
    caps = ["summarization"]
    # ── T20, ход 1: объект не назван → легальное уточнение ────────────────
    step1 = await run_l1("T20s1", "Бот, скинь отчёт", [], caps)
    plan1 = plan_of(step1)
    target = (getattr(plan1, "clarification_target", "") or "").strip()
    # Реальный вопрос бота: прод-путь Writer'а с clarification-блоком плана
    # (это и есть текст, который человек увидит в чате).
    question = ""
    if plan1 is not None and plan1.needs_clarification:
        sys_p, usr = l2_run("T20s1", plan1, [], "Бот, скинь отчёт", note=False,
                            clarification=True)
        rec_q = await llm(sys_p, usr, label="T20s1 L2 clarify",
                          temperature=L2_TEMP, max_tokens=None)
        (OUT / "T20s1.L2.json").write_text(
            json.dumps(rec_q, ensure_ascii=False, indent=1), encoding="utf-8")
        question = str(rec_q["content"]).strip()
        print("   bot question:", question[:300])
    # ── T20, ход 2: исходная просьба + реальный вопрос бота + «сегодняшний»
    window2 = [
        {"author_name": "Кирилл", "text": "Бот, скинь отчёт", "user_id": 101,
         "timestamp": 1_700_000_000, "media_type": None},
        {"author_name": "Бот", "text": question or "за какой период нужен отчёт?",
         "user_id": 0, "timestamp": 1_700_000_010, "media_type": None},
    ]
    step2 = await run_l1("T20s2", "сегодняшний", window2, caps)
    # ── T10: маркер в L2-пакете (прод-пометка), 1 вызов ───────────────────
    t10 = json.loads((RAW / "T10.json").read_text(encoding="utf-8"))
    plan10 = l1.parse_l1_plan(t10["content"])
    window10 = [
        {"author_name": "Кирилл", "text": "вчера разобрал санузел до ремонта за "
                                          "час, а сборка заняла неделю"},
        {"author_name": "Маша", "text": "классика: демонтаж всегда быстрый"},
        {"author_name": "Кирилл", "text": "плитку взяли серо-голубую под бетон"},
        {"author_name": "Маша", "text": "я бы всё-таки взяла матовую"},
    ]
    sys_p, usr = l2_run("T10", plan10, window10,
                        "Бот, что мы обсуждали за последние дни?", note=True)
    rec = await llm(sys_p, usr, label="T10 L2+marker",
                    temperature=L2_TEMP, max_tokens=None)
    (OUT / "T10.L2.marker.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print("   T10 L2:", rec["content"][:600])
    (OUT / "summary.json").write_text(json.dumps({
        "t20_step1_class": step1["class"],
        "t20_step1_target": target,
        "t20_step1_question": question,
        "t20_step2_class": step2["class"],
        "t20_step2_plan": step2["plan"],
        "t10_l2_text": rec["content"],
        "calls": len(ledger_rows()),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
