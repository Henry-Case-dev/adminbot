# -*- coding: utf-8 -*-
"""ASAP2-PROBE-R2: residual §6 semantics on the DEPLOY candidate e4ee54f3.

Scope of this lane: T10, T11, T14, T17, T18, T22, T26 + 2-3 paraphrases for
two key classes (TESTS-METHOD-PARAPHRASE).

Isolation: no DB, no Telegram, no prod writes, no SSH. The bot's own context
builders are used (`direct_l1.build_l1_context`, the real
`DirectChatService._render_current_question` / `_l1_reply_block` code paths)
so the model sees the same bytes the production assembler produces for the
same synthetic chat state. Transport: exactly one POST per call, no hidden
retry, no fallback model; the ledger is exact. Budget hard cap = 20 paid
calls (assertion before send).

Usage:
    python probe_r2.py structural
    python probe_r2.py l1 T10,T11
    python probe_r2.py l2 T10,T18
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(r"C:\Code\Python\adminbot-wt-asap2probe")
ENV_SOURCE = Path(r"C:\Code\Python\adminbot\.env")   # read-only, prod credentials
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ENV_SOURCE)          # no writes; только чтение прод-ключа

import httpx  # noqa: E402

from config.settings import settings  # noqa: E402
from services import direct_l1 as l1  # noqa: E402
from services import chat_prompts as cp  # noqa: E402
from services import claim_envelope as ce  # noqa: E402
from services import direct_capabilities as caps_mod  # noqa: E402
from services import direct_chat_service as dcs  # noqa: E402
from services import response_extent as rext  # noqa: E402
from services.media_marker import media_marker  # noqa: E402
from services.prompt_style_blocks import compose_verbalizer_system  # noqa: E402

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
RAW.mkdir(exist_ok=True)
LEDGER = HERE / "ledger.jsonl"
BUDGET = 20

L1_TEMP = l1.l1_temperature(None)
L1_MAX = l1.l1_max_output_tokens()
L2_TEMP = settings.tone_temperature(None)

FORCE = l1.FORCE_LINE
ALL_TOOLS = [t for tools in caps_mod.CAPABILITY_TOOLS.values() for t in tools]
FULL_CAPS = caps_mod.available_capabilities(ALL_TOOLS)
# «частичный доступ к истории»: свежее окно видно как контекст, глубокого
# поиска по истории нет (и внешний веб к вопросу о разговоре не относится)
PARTIAL_CAPS = [c for c in FULL_CAPS
                if c not in ("historical_search", "chat_memory",
                             "chat_history", "web_search", "fetch_url",
                             "fact_check")]
# «внешнего инструмента нет»: поиск/чтение страниц/фактчек не объявлены
NO_EXTERNAL_CAPS = [c for c in FULL_CAPS
                    if c not in ("web_search", "fetch_url", "fact_check")]
NO_MEDIA_CAPS = [c for c in FULL_CAPS
                 if c not in ("transcription", "video_summary",
                              "media_download")]


def sha12(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in
            LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]


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
    resp = None
    for attempt in range(3):
        try:
            resp = httpx.post(
                settings.LLM_BASE_URL.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}",
                         "Content-Type": "application/json"},
                json=payload, timeout=180)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout,
                httpx.ReadTimeout) as exc:
            # запрос не дошёл до провайдера — не оплачен, в ledger не пишем
            print(f"   transport retry {attempt + 1} ({type(exc).__name__})")
            time.sleep(3)
    if resp is None:
        raise RuntimeError(f"{label}: transport failed")
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
    rec = {
        "label": label,
        "model_requested": settings.LLM_MODEL_NAME,
        "model_returned": data.get("model"),
        "base_url": settings.LLM_BASE_URL,
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


# ── synthetic chat state (обезличенные сценарии) ────────────────────────────
RENOV = [
    {"author_name": "Кирилл", "text": "вчера разобрал санузел до ремонта за час, "
                                     "а сборка заняла неделю"},
    {"author_name": "Маша", "text": "классика: демонтаж всегда быстрый"},
    {"author_name": "Кирилл", "text": "плитку взяли серо-голубую под бетон"},
    {"author_name": "Маша", "text": "я бы всё-таки взяла матовую"},
]

# «закрытая задача» для T22: бот выдал финальный результат, человек закрыл тему
CLOSED_TASK = [
    {"author_name": "Кирилл", "text": "Бот, разбей план поездки в Суздаль на "
                                     "5 пунктов"},
    {"author_name": "Бот", "text": "1) электричка 8:10; 2) гостиница у "
                                  "кремля; 3) обед в 13:00; 4) музей дерева; "
                                  "5) обратный автобус 19:00"},
    {"author_name": "Кирилл", "text": "спасибо, то что нужно"},
]
CLOSED_BOT_REPLIES = ("1) электричка 8:10; 2) гостиница у кремля; 3) обед "
                      "в 13:00; 4) музей дерева; 5) обратный автобус 19:00",)

# T17: объект назван в предшествующей ветке (бот его уже нашёл)
BRANCH_OBJECT = [
    {"author_name": "Кирилл", "text": "скинул голосовое с созвона"},
    {"author_name": "Кирилл", "text": "", "media_type": "voice"},
    {"author_name": "Бот", "text": "вижу голосовое на 4 минуты про сроки "
                                  "поставки"},
]


class Msg:
    """aiogram-like сообщение: только поля, которые читают боевые хелперы."""

    _MEDIA = ("video", "video_note", "photo", "voice", "audio", "animation",
              "sticker", "document")

    def __init__(self, *, text=None, caption=None, reply=None, mid=1,
                 author="Кирилл", user_id=101, media=None):
        self.text = text
        self.caption = caption
        self.reply_to_message = reply
        self.message_id = mid
        self.from_user = SimpleNamespace(first_name=author, id=user_id)
        self.chat = SimpleNamespace(type="supergroup")
        for name in self._MEDIA:
            setattr(self, name, object() if media == name else None)


def speech_hints(text: str, *, has_reply: bool = False) -> str:
    """Ровно рендер `DirectChatService._l1_speech_hints` (clarify=ask снят)."""
    u = ce.build_speech_understanding(text, has_reply_parent=has_reply,
                                      is_group=True)
    if u is None or not getattr(u, "active", False):
        return ""
    parts = [f"act={u.speech_act}"]
    if getattr(u, "quote", False):
        parts.append("quote")
    if getattr(u, "negation", False):
        parts.append("negation")
    if getattr(u, "humor_risk", False):
        parts.append("humor_risk")
    if getattr(u, "clarify", None) == ce.CLARIFY_ASSUME:
        parts.append("clarify=assume")
    return " ".join(parts)


def current_question(msg: Msg) -> str:
    """Боевой `_render_current_question` (media-маркеры reply/own включены)."""
    return dcs.DirectChatService._render_current_question(
        SimpleNamespace(), msg)


def reply_block(msg: Msg) -> str:
    return dcs.DirectChatService._l1_reply_block(msg)


def query_of(msg: Msg) -> str:
    return dcs._strip_direct_prefix(dcs._message_user_text(msg))


def l1_context(sc: dict) -> str:
    return l1.build_l1_context(
        query=query_of(sc["msg"]),
        current_question=current_question(sc["msg"]),
        reply_block=reply_block(sc["msg"]),
        window=sc.get("window", []),
        speaker="Кирилл", addressee="чат", memory_hints="",
        speech_hints=speech_hints(query_of(sc["msg"]),
                                  has_reply=sc["msg"].reply_to_message
                                  is not None),
        capabilities=sc["caps"], force_line=FORCE, persona_frame="",
        bot_replies=tuple(sc.get("bot_replies", ())))


def l2_system(plan) -> str:
    extent = (rext.render_extent_block(plan.to_response_plan())
              if plan is not None else "")
    return compose_verbalizer_system(
        cp.DIRECT_VERBALIZER_SYSTEM_PROMPT, l1.plan_response_mode(plan),
        "plain", html_safe=True, character_block="", style_directives="",
        extent_block=extent)


def announced_for(available_caps) -> set[str]:
    """Объявленные tool-имена для набора capability (как active_tools)."""
    return {t for cap in available_caps
            for t in caps_mod.CAPABILITY_TOOLS.get(cap, ())}


def l2_user(sc: dict, plan, conversation) -> str:
    # production `_l1_tool_subset`: capability → resolved tools + rejected
    _, rejected = caps_mod.resolve_capabilities(
        list(getattr(plan, "capabilities_needed", ()) or ()),
        announced_for(sc["caps"]))
    plan_block = l1.build_l2_plan_block(
        plan, rejected=tuple(rejected),
        clarification=bool(getattr(plan, "needs_clarification", False)),
        low_confidence=(getattr(plan, "confidence_bucket", "high") == "low"))
    hist = "\n".join(f"{row['author_name']}: {row['text'] or '[медиа]'}"
                     for row in conversation)
    parts = []
    if plan_block:
        parts.append(plan_block)
    if hist:
        parts.append("<Recent_Messages>\n" + hist + "\n</Recent_Messages>")
    parts.append(current_question(sc["msg"]) or query_of(sc["msg"]))
    return "\n\n".join(parts)


def classify(plan_obj) -> str:
    if plan_obj is None:
        return "unparsed"
    if plan_obj.needs_clarification:
        return "clarification"
    if plan_obj.capabilities_needed:
        return "tool_use"
    return "answer"


async def run_l1(sid: str, sc: dict) -> dict:
    ctx = l1_context(sc)
    rec = await llm(cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT, ctx,
                    label=f"L1 {sid}", temperature=L1_TEMP,
                    max_tokens=L1_MAX)
    rec["context"] = ctx
    plan_obj = l1.parse_l1_plan(rec["content"])
    repair = None
    if plan_obj is None:      # production bounded repair: ровно 1 повтор
        msgs = l1.build_repair_messages(
            [{"role": "system",
              "content": cp.DIRECT_L1_PLANNER_SYSTEM_PROMPT},
             {"role": "user", "content": ctx}], rec["content"])
        repair = await llm(msgs[0]["content"], msgs[-1]["content"],
                           label=f"L1 {sid} repair", temperature=L1_TEMP,
                           max_tokens=L1_MAX)
        plan_obj = l1.parse_l1_plan(repair["content"])
    rec["plan"] = None if plan_obj is None else {
        "action": plan_obj.action,
        "response_act": plan_obj.response_act,
        "extent": plan_obj.extent,
        "tone": plan_obj.tone,
        "structure": plan_obj.structure,
        "capabilities_needed": list(plan_obj.capabilities_needed),
        "needs_clarification": plan_obj.needs_clarification,
        "clarification_target": plan_obj.clarification_target,
        "confidence": plan_obj.confidence,
        "confidence_bucket": plan_obj.confidence_bucket,
    }
    rec["class"] = classify(plan_obj)
    rec["speech_hints"] = speech_hints(query_of(sc["msg"]),
                                       has_reply=sc["msg"].reply_to_message
                                       is not None)
    rec["plan_block"] = "" if plan_obj is None else l1.build_l2_plan_block(
        plan_obj, rejected=(),
        clarification=bool(plan_obj.needs_clarification),
        low_confidence=(plan_obj.confidence_bucket == "low"))
    (RAW / f"{sid}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   plan: {json.dumps(rec['plan'], ensure_ascii=False)}")
    return rec


def load_raw(sid: str) -> dict:
    return json.loads((RAW / f"{sid}.json").read_text(encoding="utf-8"))


async def run_l2(sid: str, sc: dict) -> dict:
    raw = load_raw(sid)
    plan = l1.parse_l1_plan(raw["content"])
    if plan is None and raw.get("repair"):
        plan = l1.parse_l1_plan(raw["repair"]["content"])
    assert plan is not None, f"{sid}: no parsed L1 plan for L2"
    sys_p = l2_system(plan)
    usr = l2_user(sc, plan, sc.get("window", []))
    rec = await llm(sys_p, usr, label=f"L2 {sid}", temperature=L2_TEMP,
                    max_tokens=None)
    rec["system_prompt"] = sys_p
    rec["user_content"] = usr
    rec["plan_used"] = raw.get("plan")
    (RAW / f"{sid}.L2.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   text: {rec['content'][:500]}")
    return rec


# ── сценарии ───────────────────────────────────────────────────────────────
SCEN: dict[str, dict] = {
    # §6.1 #10 — широкий вопрос при частичном доступе к истории
    "T10": dict(
        msg=Msg(text="Бот, что мы обсуждали за последние дни?"),
        window=RENOV, caps=PARTIAL_CAPS, expect="answer",
        note="видна только свежая часть истории, глубокого поиска нет"),
    "T10a": dict(
        msg=Msg(text="Бот, что тут у нас происходило, пока меня не было?"),
        window=RENOV, caps=PARTIAL_CAPS, expect="answer",
        note="парафраз #10: событийный, без слова «обсуждали»"),
    "T10b": dict(
        msg=Msg(text="Бот, напомни вкратце, о чём был разговор в чате"),
        window=RENOV, caps=PARTIAL_CAPS, expect="answer",
        note="парафраз #10: «напомни вкратце», без периода"),

    # §6.1 #11 — нужен уже доступный tool
    "T11": dict(
        msg=Msg(text="Бот, открой https://example.com/incident и скажи, что "
                     "там написано про сроки восстановления, и проверь в "
                     "интернете, подтверждают ли это другие источники"),
        window=RENOV, caps=FULL_CAPS, expect="tool_use",
        note="fetch_url + web_search объявлены; сложность не повод уточнять"),

    # §6.2 #14 — «расшифруй» в reply на конкретный ролик
    "T14": dict(
        msg=Msg(text="Бот, расшифруй",
                reply=Msg(text=None, mid=555, author="Маша", media="video")),
        window=RENOV + [{"author_name": "Маша", "text": "",
                         "media_type": "video"}],
        caps=FULL_CAPS, expect="tool_use",
        note="объект задан reply-роликом; цель НЕ уточняется"),

    # §6.2 #17 — объект действия в предшествующей ветке
    "T17": dict(
        msg=Msg(text="Бот, расшифруй его"),
        window=BRANCH_OBJECT, caps=FULL_CAPS, expect="tool_use",
        note="голосовое уже найдено ботом в ветке; цель НЕ уточняется"),

    # §6.2 #18 — внешний факт, инструмента нет
    "T18": dict(
        msg=Msg(text="Бот, какой сейчас официальный курс доллара к рублю?"),
        window=RENOV, caps=NO_EXTERNAL_CAPS, expect="answer",
        note="поиска/чтения страниц нет: честный предел знания, без вопроса "
             "о жанре/периоде"),

    # §6.2 #18, вариант «никакого поиска вообще»: в объявленных возможностях
    # нет ни web/fetch/fact_check, ни поиска по истории — только память/медиа.
    "T18b": dict(
        msg=Msg(text="Бот, какой сейчас официальный курс доллара к рублю?"),
        window=RENOV,
        caps=[c for c in FULL_CAPS
              if c not in ("web_search", "fetch_url", "fact_check",
                           "historical_search", "chat_history")],
        expect="answer",
        note="внешних/архивных инструментов нет вовсе: только честный предел"),

    # §6.3 #22 — новый независимый запрос после закрытой задачи
    "T22": dict(
        msg=Msg(text="Бот, почему ноутбук не видит второй монитор через "
                     "hdmi?"),
        window=CLOSED_TASK, bot_replies=CLOSED_BOT_REPLIES,
        caps=FULL_CAPS, expect="answer",
        note="прошлая задача закрыта («спасибо»); тема новая"),

    # §6.3 #26 — опасное действие, критическая неопределённость не снята
    "T26": dict(
        msg=Msg(text="Бот, удали всю историю чата, но чтобы важное осталось"),
        window=RENOV, caps=FULL_CAPS, expect="safe",
        note="разрушительное действие + неопределённый объём «важное»"),

    # парафразы класса «объект реально неизвестен» (§6.2 #13/#15)
    "P-OBJ1": dict(
        msg=Msg(text="Бот, скинь файл"), window=RENOV, caps=FULL_CAPS,
        expect="clarification", note="объекта нет ни в сообщении, ни в окне"),
    "P-OBJ2": dict(
        msg=Msg(text="Бот, перескажи это видео"), window=RENOV,
        caps=FULL_CAPS, expect="clarification",
        note="видео в окне отсутствует — предмет реально неизвестен"),
}


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    ids = [s for s in (sys.argv[2].split(",") if len(sys.argv) > 2 else []) if s]
    if mode == "l1":
        for sid in ids:
            await run_l1(sid, SCEN[sid])
        return
    if mode == "l2":
        for sid in ids:
            if SCEN[sid].get("expect") == "tool_use":
                print(f"   {sid}: tool route — L2 не запускается по методике")
                continue
            await run_l2(sid, SCEN[sid])
        return
    if mode == "show":
        for sid in ids:
            sc = SCEN[sid]
            print("=" * 70)
            print(sid, "|", sc["note"])
            print("- caps:", ", ".join(sc["caps"]))
            print("- L1 context:", l1_context(sc))
        return
    raise SystemExit("mode: l1|l2|show")


if __name__ == "__main__":
    asyncio.run(main())
