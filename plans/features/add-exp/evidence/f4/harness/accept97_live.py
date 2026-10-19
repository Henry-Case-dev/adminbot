# -*- coding: utf-8 -*-
"""ACCEPTANCE-97 — ADD-EXP F4 behavioural acceptance on prod 2.58.97.

Scope: the F1 canon (`5b86517e`) is deployed; this wave measures whether the
frequency instruction actually changes live answers.

Matrix (acceptance brief §4b / LANE ACCEPTANCE-97):
  * `frequent`: 6 conversational probes over 3 contexts (banter, argument /
    everyday complaint, joke / short answer) -> PASS requires >=3 of 6 replies
    with at least one OWN profanity root, roots present in all 3 contexts,
    <=1 root per sentence;
  * `off`: 2 conversational probes -> 0 own mat; genre quote probe -> verbatim,
    not distorted;
  * `occasional`: 10 conversational probes -> PRE-REGISTERED widened bound
    `1..5 of 10` (nominal canon is "one in 4-5 conversational replies"); 0/10
    and >5/10 are FAIL;
  * genre tech-summary probe inside `frequent` -> facts intact, 0 forced mat;
  * every L2 wire call carries `<Expression_Settings>` + the exact mode line
    and the exact rendered layer text; raw L2 output == delivered text;
  * `<Expression_Examples>` must NOT appear (drafts `owner_approved=0`).

Prompts are deliberately DISJOINT from the owner-facing few-shot drafts
(`mca_sample_library.EXPRESSION_STARTER_SAMPLES`) and from the acceptance-96
phrases (different situations and wording).

Runs ON the production host through the unchanged ACCEPTANCE-91..96 bootstrap
(deployed modules, real Bot API delivery, real PG/SQLite/providers). Product
code is not modified; temporary per-chat settings are restored exactly; every
test message is registered for cleanup (owner rule).
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
import time

APP = "/var/www/admin_bot"
try:
    os.chdir(APP)
except Exception:
    pass
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHAT_A = -1002661910336          # рабочий/тестовый чат (ACCEPTANCE-91..96)
CHAT_B_DEFAULT = -1004482340693  # второй тестовый чат (изоляция off/frequent)
SYNTH_USER = 990002001
EVID = "/tmp/accept97/evidence"
SPEC = "/tmp/accept97/cleanup_spec.json"
MID_BASE = 990970100             # синтетические msg_id (выше реальных)

# ── детектор мата по корням (собственные формулировки; защищённые спаны) ────
ROOT_PATTERNS = (
    ("бля", r"(?<![а-яё])бля"),
    ("хуй", r"(?<![а-яё])ху[йеё]"),
    ("хуйн", r"(?<![а-яё])хуйн"),
    ("хуя", r"(?<![а-яё])ху[яю]"),
    ("пизд", r"(?<![а-яё])пизд"),
    ("еб", r"(?<![а-яё])еб"),
    ("ёб", r"(?<![а-яё])ёб"),
    ("заеб", r"(?<![а-яё])заеб"),
    ("охуе", r"(?<![а-яё])охуе"),
    ("мудак", r"(?<![а-яё])мудак"),
    ("мудил", r"(?<![а-яё])мудил"),
    ("нахуй", r"(?<![а-яё])нахуй"),
    ("нахер", r"(?<![а-яё])нахер"),
    ("долбоеб", r"(?<![а-яё])долбо[её]б"),
    ("сука", r"(?<![а-яё])сука(?![а-яё])"),
    ("сучк", r"(?<![а-яё])сучк"),
    ("похуй", r"(?<![а-яё])похуй"),
    ("нихуя", r"(?<![а-яё])нихуя"),
    ("нахуя", r"(?<![а-яё])нахуя"),
)
EUPHEMISM_WORDS = ("бляха", "бляхами", "бляшка", "бляшки", "бляшку", "бляшке",
                   "бляха-муха")
SPAN_PATTERNS = (
    ("quote_guillemet", r"«[^»]{1,600}»"),
    ("quote_smart", r"“[^”]{1,600}”"),
    ("quote_double", r"\"[^\"]{1,600}\""),
    ("quote_single", r"‘[^’]{1,300}’"),
    ("code_tick", r"`[^`]{1,600}`"),
    ("code_block", r"```[\s\S]{0,1200}?```"),
    ("url", r"https?://\S+"),
)
MODE_LINE_MARKERS = {
    "off": "не используй обсценную лексику",
    "occasional": "появляется в собственных живых",
    "frequent": "узнаваемая регулярная часть",
}

# ── матрица проб (disjoint с few-shot и acceptance-96) ──────────────────────
FREQ_CONV = (
    ("banter", "стёб 1",
     "бот, ты вчера так уверенно советовал сменить тариф, что я почти "
     "поверил, будто ты из техподдержки"),
    ("banter", "стёб 2",
     "бот, три абзаца про пользу утренних прогулок — это ты серьёзно? Сам, "
     "поди, до обеда спишь"),
    ("argument", "спор",
     "бот, не согласен: твой вариант с кэшем только всё усложнит, у меня и "
     "без него в проде нормально"),
    ("argument", "бытовая жалоба",
     "бот, стиралка второй день гудит на отжиме, вызывать мастера или "
     "подождать"),
    ("joke_short", "шутка",
     "бот, пошути про то, как я в третий раз переписываю один и тот же отчёт"),
    ("joke_short", "короткий ответ", "бот, ты вообще выспался?"),
)
FREQ_SUMMARY = (
    "genre_summary", "жанр: тех-сводка",
    "бот, тех-сводка в две строки: прод 2.58.97, диск 71%, ОЗУ 940 МБ, "
    "аптайм 6 суток")
FREQ_FACTS = ("2.58.97", "71", "940", "6")

OFF_CONV = (
    ("banter", "стёб",
     "бот, у нас в чате спорят, кто виноват в сломанном билде — я или сеньор. "
     "Рассуди по-честному"),
    ("joke_short", "короткий ответ",
     "бот, как думаешь, стоит ли мне идти на эту встречу в субботу?"),
)
OFF_QUOTE = (
    "genre_quote", "жанр: цитата с матом",
    "бот, Петя просил передать слово в слово: «ну и хуйня этот ваш "
    "рефакторинг, я устал» — ничего не правь")

OCC_CONV = (
    ("everyday", "быт", "бот, сосед опять сверлит стену в восемь утра, что делать?"),
    ("everyday", "быт", "бот, забыл пароль от вайфая, где посмотреть?"),
    ("argument", "жалоба", "бот, начальник перенёс дедлайн на завтра, а у меня "
                            "половина не готова"),
    ("everyday", "быт", "бот, посоветуй, что приготовить на ужин из курицы и риса"),
    ("joke_short", "рефлексия", "бот, мне кажется, я вчера слишком резко ответил "
                                 "коллеге. Стоит извиниться?"),
    ("banter", "стёб", "бот, мой кот скинул кружку со стола и смотрит победно. "
                        "Комментируй"),
    ("everyday", "тех", "бот, у меня ноутбук стал греться как печка, куда смотреть?"),
    ("argument", "спор", "бот, поспорь со мной: удалёнка лучше офиса или наоборот?"),
    ("joke_short", "нейтрально", "бот, что скажешь про погоду в Москве на "
                                  "выходных?"),
    ("banter", "стёб", "бот, я третий раз перечитываю твой совет и не понимаю, "
                        "с чего начать"),
)
CONVERSATIONAL = {"banter", "argument", "everyday", "joke_short"}
CONVERSATIONAL_MODES = {"off", "occasional", "frequent"}
OCC_BOUND = (1, 5)          # предрегистрированная расширенная граница 1..5/10

CALLS: list[dict] = []
WIRE: list[dict] = []
COMPOSES: list[dict] = []
SENT = {str(CHAT_A): set(), str(CHAT_B_DEFAULT): set()}
EXPECT = {"texts": {}, "chat_mode": {}}
STORE_SYSTEM_TEXT = True     # один полный system L2-вызова (пример для evidence)


def out(tag, text):
    print("ACC97 %s | %s" % (tag, text), flush=True)


def sent(chat_id, mid):
    if not mid:
        return
    SENT.setdefault(str(int(chat_id)), set()).add(int(mid))
    write_spec()


def write_spec():
    """Cleanup register is durable after EVERY message (owner rule)."""
    try:
        os.makedirs(os.path.dirname(SPEC), exist_ok=True)
        spec = {"chat_a": CHAT_A, "chat_b": CHAT_B_DEFAULT,
                "delete_mids": {k: sorted(v) for k, v in SENT.items() if v},
                "synth_user": SYNTH_USER,
                "notes": "удалить все сообщения бота тестовых волн F4 (A+B)"}
        tmp = SPEC + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, SPEC)
    except Exception as exc:  # noqa: BLE001
        out("SPEC", "write failed: %s" % type(exc).__name__)


def sha12(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def head(text, n=200):
    return " ".join(str(text or "").split())[:n]


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def load_base():
    spec = importlib.util.spec_from_file_location("accept97_base",
                                                  "/tmp/accept97_base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════ мат-сканер (собственные формулировки) ═════════

def _protected_spans(text: str):
    spans = []
    for name, pat in SPAN_PATTERNS:
        for m in re.finditer(pat, text):
            spans.append((m.start(), m.end(), name))
    return spans


def scan_own(text) -> dict:
    """Собственные корни мата; пересекающиеся шаблоны одного слова = 1 корень."""
    text = str(text or "")
    spans = _protected_spans(text)
    res = {"own": [], "protected": [], "euphemism": []}
    found = []
    for label, pat in ROOT_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            found.append((m.start(), m.end(), label))
    found.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept, last_end = [], -1
    for start, end, label in found:
        if start < last_end:      # тот же словоформенный корень (overlap)
            continue
        kept.append((start, end, label))
        last_end = end
    for start, end, label in kept:
        tail = text[start:start + 30]
        wm = re.match(r"[а-яёА-ЯЁa-zA-Z\-]+", tail)
        word = wm.group(0) if wm else text[start:end]
        s, e = max(0, start - 40), min(len(text), end + 40)
        rec = {"root": label, "word": word,
               "ctx": " ".join(text[s:e].split())}
        if word.lower() in EUPHEMISM_WORDS:
            res["euphemism"].append(rec)
            continue
        span = next((sp for sp in spans if sp[0] <= start < sp[1]), None)
        if span is not None:
            rec["span"] = span[2]
            res["protected"].append(rec)
        else:
            res["own"].append(rec)
    res["own_count"] = len(res["own"])
    res["protected_count"] = len(res["protected"])
    res["own_words"] = sorted({r["word"].lower() for r in res["own"]})
    return res


def sentence_stats(text) -> dict:
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+|\n+", str(text or ""))
             if p.strip()]
    per = [scan_own(p)["own_count"] for p in parts]
    return {"sentences": len(parts),
            "sentences_with_mat": sum(1 for n in per if n),
            "max_roots_in_sentence": max(per) if per else 0,
            "root_counts": per}


# ═══════════════════════════ spies ═════════════════════════════════════════

def _modes_in(system: str) -> list:
    return sorted(m for m, marker in MODE_LINE_MARKERS.items()
                  if marker in system)


def install_spies(base):
    import services.prompt_composer as pc

    orig_compose = pc.compose_prompt

    def compose_spy(plan):
        manifest = orig_compose(plan)
        try:
            rep = pc.manifest_for_events(manifest)
            layers = rep.get("layers") or []
            expr = next((t for t in layers if t.get("layer") == "expression"),
                        None)
            few = next((t for t in layers
                        if t.get("layer") == "few_shot"
                        and t.get("block_id") == "expression_examples"), None)
            system = str(manifest.system or "")
            COMPOSES.append({
                "seq": len(COMPOSES) + 1,
                "chat_id": int(getattr(plan, "chat_id", 0) or 0),
                "writer": str(getattr(plan, "writer", "") or ""),
                "profile": str(getattr(plan, "profile", "") or ""),
                "system_sha12": sha12(system),
                "system_chars": len(system),
                "has_marker": "<Expression_Settings>" in system,
                "has_examples_marker": "<Expression_Examples>" in system,
                "modes_in_system": _modes_in(system),
                "expr": expr,
                "expr_examples": few,
            })
        except Exception as exc:  # noqa: BLE001
            COMPOSES.append({"seq": len(COMPOSES) + 1,
                             "error": type(exc).__name__})
        return manifest

    pc.compose_prompt = compose_spy

    llm = base.CTX.llm
    orig_generate = llm.generate
    orig_generate_chat = llm.generate_chat

    async def _record(via, fn, messages, kw):
        rec = {
            "seq": len(CALLS) + 1, "via": via,
            "module": kw.get("module"), "step": kw.get("step"),
            "chat_id": kw.get("chat_id"),
            "correlation_id": kw.get("correlation_id"),
            "n_messages": len(messages or []),
        }
        sys_txt = ""
        for m in (messages or []):
            if isinstance(m, dict) and str(m.get("role")) == "system":
                sys_txt = str(m.get("content") or "")
                break
        rec["system_chars"] = len(sys_txt)
        rec["system_sha12"] = sha12(sys_txt)
        rec["has_marker"] = "<Expression_Settings>" in sys_txt
        rec["has_examples_marker"] = "<Expression_Examples>" in sys_txt
        rec["modes_in_system"] = _modes_in(sys_txt)
        if STORE_SYSTEM_TEXT and str(kw.get("step")) == "l2_writer" and (
                "Expression_Settings" in sys_txt):
            rec["system_text"] = sys_txt[:24000]
        CALLS.append(rec)
        try:
            result = await fn(messages, **kw)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = type(exc).__name__
            raise
        try:
            rec["raw"] = str(result or "")[:6000]
            rec["raw_scan"] = scan_own(rec["raw"])
        except Exception:
            pass
        return result

    async def gen_spy(messages, **kw):
        return await _record("generate", orig_generate, messages, kw)

    async def gen_chat_spy(messages, **kw):
        return await _record("generate_chat", orig_generate_chat, messages, kw)

    llm.generate = gen_spy
    llm.generate_chat = gen_chat_spy

    orig_post = llm._post
    orig_post_fb = llm._post_fallback

    def _wire_rec(via, path, payload, model=None):
        if str(path) != "/chat/completions" or not isinstance(payload, dict):
            return
        msgs = payload.get("messages") or []
        sys_txt = ""
        for m in msgs:
            if isinstance(m, dict) and str(m.get("role")) == "system":
                sys_txt = str(m.get("content") or "")
                break
        WIRE.append({
            "seq": len(WIRE) + 1, "via": via,
            "model": model or payload.get("model"),
            "n_messages": len(msgs),
            "payload_sha12": sha12(json.dumps(payload, sort_keys=True,
                                              ensure_ascii=False)),
            "has_marker": "<Expression_Settings>" in sys_txt,
            "has_examples_marker": "<Expression_Examples>" in sys_txt,
            "modes_in_system": _modes_in(sys_txt),
            "matched_text_modes": sorted(
                m for m, txt in EXPECT["texts"].items()
                if txt and txt in sys_txt),
            "mode_line": next((m for m, marker in MODE_LINE_MARKERS.items()
                               if marker in sys_txt), ""),
        })

    async def post_spy(path, payload, **kw):
        _wire_rec("_post", path, payload)
        return await orig_post(path, payload, **kw)

    async def post_fb_spy(payload, path="/chat/completions", model=None,
                          **kw):
        _wire_rec("_post_fallback", path, payload, model=model)
        return await orig_post_fb(payload, path=path, model=model, **kw)

    llm._post = post_spy
    llm._post_fallback = post_fb_spy


# ═══════════════════════════ helpers ═══════════════════════════════════════

async def api_view(api, chat_id=None):
    st, body = await api.req("GET", "/api/speech/expression", chat_id=chat_id)
    return {"http": st, "body": body}


async def pg_chat_expr_doc(base, chat_id):
    """Read-after-write chat-scope doc; parsing in Python (no jsonb SQL)."""
    try:
        rows = await base.pg_fetch(
            "SELECT chat_params->'overrides' AS overrides FROM chat_profiles "
            "WHERE chat_id=$1", (chat_id,))
        if not rows:
            return {"keys": [], "expr": None, "present": False}
        ov = rows[0].get("overrides") or {}
        if isinstance(ov, str):
            ov = json.loads(ov)
        expr = ov.get("character.expression")
        return {"keys": sorted(ov.keys()), "expr": expr, "present": True}
    except Exception as exc:  # noqa: BLE001
        return {"error": "%s: %s" % (type(exc).__name__, str(exc)[:120])}


async def wait_reread(api, chat_id, mode, tries=5, delay=20.0):
    view = await api_view(api, chat_id)
    for _ in range(tries - 1):
        eff = (((view.get("body") or {}).get("effective") or {})
               .get("profanity") or {})
        if str(eff.get("value")) == mode:
            break
        await asyncio.sleep(delay)
        view = await api_view(api, chat_id)
    return view


async def resolve_expected(chat_id):
    from services import prompt_composer as pc
    ref = await pc.resolve_expression_settings(int(chat_id))
    text = str(getattr(ref, "text", "") or "")
    return {"mode": str(getattr(ref, "mode", "") or ""),
            "source": str(getattr(ref, "source", "") or ""),
            "revision": str(getattr(ref, "revision", "") or ""),
            "text_sha12": sha12(text),
            "text_chars": len(text),
            "skip_reason": str(getattr(ref, "skip_reason", "") or ""),
            "enabled": bool(getattr(ref, "enabled", False)),
            "text": text[:4000]}


async def set_chat_mode(base, api, chat_id, mode, label=""):
    st, body = await api.req("POST", "/api/speech/expression", chat_id=chat_id,
                             json_body={"scope": "chat",
                                        "values": {"profanity": mode}})
    try:
        from services.chat_params import get_chat_params_cache
        cpc = get_chat_params_cache()
        if cpc is not None:
            await cpc.invalidate_chat(int(chat_id))
    except Exception as exc:  # noqa: BLE001
        out("CACHE", "invalidate failed: %s" % type(exc).__name__)
    view = await wait_reread(api, chat_id, mode)
    resolved = await resolve_expected(chat_id)
    if resolved.get("text"):
        EXPECT["texts"][mode] = resolved["text"]
    EXPECT["chat_mode"][int(chat_id)] = mode
    preview_eq = (sha12((view.get("body") or {}).get("rendered_text"))
                  == resolved["text_sha12"])
    out("WAVE", "%s: %s chat=%s write_http=%s effective=%s source=%s rev=%s "
        "preview_eq_resolve=%s"
        % (label or mode, mode, chat_id, st,
           (((view.get("body") or {}).get("effective") or {}).get(
               "profanity") or {}).get("value"),
           (((view.get("body") or {}).get("effective") or {}).get(
               "profanity") or {}).get("source"),
           resolved.get("revision"), preview_eq))
    return {"write_http": st, "write_body": body, "reread": view,
            "resolved": resolved, "preview_eq_resolve": preview_eq,
            "pg_doc_after": await pg_chat_expr_doc(base, chat_id)}


async def reset_chat_mode(api, chat_id):
    st, body = await api.req("POST", "/api/speech/expression/reset-chat",
                             chat_id=chat_id)
    try:
        from services.chat_params import get_chat_params_cache
        cpc = get_chat_params_cache()
        if cpc is not None:
            await cpc.invalidate_chat(int(chat_id))
    except Exception:
        pass
    view = await api_view(api, chat_id)
    for _ in range(4):
        body_v = view.get("body") or {}
        if body_v.get("inheritance") == "global" and not body_v.get(
                "chat_present"):
            break
        await asyncio.sleep(20)
        view = await api_view(api, chat_id)
    return {"http": st, "body": body, "reread": view}


async def do_turn(base, chat_id, phrase, *, label, context, mode,
                  anchor_msg, mid, timeout=300):
    calls_before = len(CALLS)
    wire_before = len(WIRE)
    comp_before = len(COMPOSES)
    res = await base.run_turn(phrase, msg_id=mid, chat_id=chat_id,
                              reply_to=anchor_msg, label=label,
                              timeout=timeout)
    sends = []
    for s in res.get("sends") or []:
        sends.append({
            "kind": s.get("kind"),
            "message_id": s.get("message_id"),
            "text": s.get("text_full") or s.get("text_head") or "",
            "text_len": s.get("text_len"),
            "reply_to": s.get("reply_to"),
        })
    answer = "\n".join(s["text"] for s in sends
                       if s.get("kind") == "message" and s.get("text"))
    scan = scan_own(answer)
    l2 = [c for c in CALLS[calls_before:] if str(c.get("step")) == "l2_writer"]
    raw = ""
    for c in reversed(l2):
        if c.get("raw"):
            raw = str(c["raw"])
            break
    raw_n, ans_n = norm(raw), norm(answer)
    turn = {
        "label": label, "chat_id": chat_id, "mode": mode, "context": context,
        "phrase": phrase, "status": res.get("status"),
        "error": res.get("error"),
        "correlation_id": res.get("correlation_id"),
        "elapsed_s": res.get("elapsed_s"),
        "plan_meta": res.get("plan_meta"),
        "sends": sends,
        "answer": answer[:6000],
        "answer_sha12": sha12(answer),
        "answer_scan": scan,
        "sentences": sentence_stats(answer),
        "raw": raw[:6000],
        "raw_sha12": sha12(raw),
        "raw_scan": scan_own(raw),
        "raw_eq_delivered": bool(raw_n and ans_n and (
            raw_n == ans_n or ans_n in raw_n or raw_n in ans_n)),
        "llm_calls": CALLS[calls_before:],
        "wire": WIRE[wire_before:],
        "composes": COMPOSES[comp_before:],
    }
    return turn, res.get("_last_msg"), res


async def wave(base, api, chat_id, mode, probes, *, wave_name, timeout=300,
               anchor_note=""):
    switch = await set_chat_mode(base, api, chat_id, mode,
                                 label=wave_name)
    anchor = await base.CTX.rec.send_message(
        chat_id,
        "🧪 Приёмка 2.58.97 ADD-EXP F4 · %s · режим «%s» "
        "(контролируемая проверка; сообщения удаляются)%s"
        % (wave_name, mode, anchor_note))
    wave_rec = {
        "wave": wave_name, "mode": mode, "chat_id": chat_id,
        "switch": switch, "anchor_mid": getattr(anchor, "message_id", None),
        "turns": [],
    }
    sent(chat_id, getattr(anchor, "message_id", None))
    out("ANCHOR", "%s chat=%s mid=%s"
        % (wave_name, chat_id, getattr(anchor, "message_id", None)))
    mid = int(getattr(anchor, "message_id", 0) or MID_BASE)
    fallback_mid = MID_BASE
    last_msg = anchor
    for i, (context, human, phrase) in enumerate(probes):
        label = "%s-%02d-%s" % (mode, i + 1, context)
        turn, last_msg_new, _res = await do_turn(
            base, chat_id, phrase, label=label, context=context, mode=mode,
            anchor_msg=last_msg, mid=mid, timeout=timeout)
        wave_rec["turns"].append(turn)
        for s in turn.get("sends") or []:
            sent(chat_id, s.get("message_id"))
        if last_msg_new is not None:
            last_msg = last_msg_new
            mid = int(getattr(last_msg_new, "message_id", 0) or fallback_mid)
        else:
            fallback_mid += 1
            mid = fallback_mid
        out("TURN", "%s | %s | status=%s | own_mat=%d | max/предл=%d | raw_eq=%s"
            " | %s"
            % (label, human, turn["status"], turn["answer_scan"]["own_count"],
               turn["sentences"]["max_roots_in_sentence"],
               turn["raw_eq_delivered"], head(turn["answer"], 90)))
    try:
        from services import mca_events
        wave_rec["flushed_events"] = await mca_events.flush_events(base.CTX.db)
    except Exception as exc:  # noqa: BLE001
        wave_rec["flushed_events"] = "failed:%s" % type(exc).__name__
    return wave_rec


# ═══════════════════════════ main ══════════════════════════════════════════

async def main() -> int:
    os.makedirs(EVID, exist_ok=True)
    base = load_base()
    base.EVID = EVID
    out("NOW_UTC", time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    wave_start = int(time.time())
    await base.bootstrap()
    me = base.CTX.me
    out("BOOT", "bot=%s pg=%s version=%s"
        % (getattr(me, "id", None), bool(getattr(base.CTX.pg, "pool", None)),
           _app_version()))
    install_spies(base)
    api = base.Api()
    base.CTX.api = api
    results = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
               "chat_a": CHAT_A, "chat_b": CHAT_B_DEFAULT,
               "app_version": _app_version()}

    # ── P0: pre-state (read-only) ─────────────────────────────────────────
    p0 = {"wave_start_epoch": wave_start,
          "occ_bound_pre_registered": list(OCC_BOUND)}
    p0["view_a"] = await api_view(api, CHAT_A)
    p0["view_b"] = await api_view(api, CHAT_B_DEFAULT)
    p0["view_global"] = await api_view(api, None)
    p0["resolve_a"] = await resolve_expected(CHAT_A)
    p0["resolve_b"] = await resolve_expected(CHAT_B_DEFAULT)
    try:
        p0["preview_eq_resolve_a"] = (
            sha12((p0["view_a"]["body"] or {}).get("rendered_text"))
            == p0["resolve_a"]["text_sha12"])
    except Exception:
        p0["preview_eq_resolve_a"] = None
    for mode in ("off", "occasional", "frequent"):
        pass
    p0["chat_a_overrides"] = await pg_chat_expr_doc(base, CHAT_A)
    p0["chat_b_overrides"] = await pg_chat_expr_doc(base, CHAT_B_DEFAULT)
    try:
        p0["chats"] = await base.sqlite_fetch(
            "SELECT chat_id, COUNT(*) AS n, MAX(timestamp) AS last_ts "
            "FROM smart_messages GROUP BY chat_id ORDER BY last_ts DESC "
            "LIMIT 12")
    except Exception as exc:  # noqa: BLE001
        p0["chats"] = "failed:%s" % type(exc).__name__
    try:
        st, body = await api.req("GET", "/api/speech/examples", chat_id=CHAT_A)
        p0["examples_view"] = {"http": st,
                               "counts": (body or {}).get("count"),
                               "starter": (body or {}).get("starter")}
    except Exception as exc:  # noqa: BLE001
        p0["examples_view"] = "failed:%s" % type(exc).__name__
    try:
        p0["expression_rows"] = await base.sqlite_fetch(
            "SELECT technique, status, owner_approved, COUNT(*) AS n "
            "FROM humor_samples WHERE technique='expression_register' "
            "GROUP BY 1,2,3")
    except Exception as exc:  # noqa: BLE001
        p0["expression_rows"] = "failed:%s" % type(exc).__name__
    p0["user_version"] = await _user_version(base)
    base.save("p0-pre-state.json", p0)
    out("P0", "preview_eq=%s expr_rows=%s user_version=%s"
        % (p0.get("preview_eq_resolve_a"),
           json.dumps(p0.get("expression_rows"), ensure_ascii=False)[:160],
           p0.get("user_version")))

    # ── волна 1: occasional на A (10 ходов; widened bound) ───────────────
    waves = {}
    waves["occasional"] = await wave(base, api, CHAT_A, "occasional", OCC_CONV,
                                     wave_name="occasional-10")
    base.save("wave-occasional.json", waves["occasional"])

    # ── волна 2: frequent на A (6 разговорных + жанровая тех-сводка) ─────
    waves["frequent"] = await wave(
        base, api, CHAT_A, "frequent",
        tuple(FREQ_CONV) + (FREQ_SUMMARY,), wave_name="frequent-6x3")
    base.save("wave-frequent.json", waves["frequent"])

    # ── волна 3: off на B (2 разговорных + цитата) при frequent на A ─────
    waves["off"] = await wave(
        base, api, CHAT_B_DEFAULT, "off",
        tuple(OFF_CONV) + (OFF_QUOTE,), wave_name="off-2+quote")
    base.save("wave-off.json", waves["off"])

    # ── изоляция: A всё ещё frequent, B off ──────────────────────────────
    iso = {"chat_a": CHAT_A, "chat_b": CHAT_B_DEFAULT}
    iso["view_a_while_b_off"] = await api_view(api, CHAT_A)
    iso["view_b_off"] = await api_view(api, CHAT_B_DEFAULT)
    iso["resolve_a_while_b_off"] = await resolve_expected(CHAT_A)
    iso["resolve_b_off"] = await resolve_expected(CHAT_B_DEFAULT)
    base.save("isolation.json", iso)

    # ── restore: точное возвращение pre-state A и B ──────────────────────
    restore = {}
    restore["chat_a"] = await _restore_chat(base, api, CHAT_A,
                                            p0.get("chat_a_overrides"))
    restore["chat_b"] = await _restore_chat(base, api, CHAT_B_DEFAULT,
                                            p0.get("chat_b_overrides"))
    restore["global_view_after"] = await api_view(api, None)
    restore["chat_a_overrides_after"] = await pg_chat_expr_doc(base, CHAT_A)
    restore["chat_b_overrides_after"] = await pg_chat_expr_doc(base,
                                                               CHAT_B_DEFAULT)
    restore["a_view_after"] = await api_view(api, CHAT_A)
    restore["b_view_after"] = await api_view(api, CHAT_B_DEFAULT)
    restore["equal"] = {
        "a": _same_state(p0.get("chat_a_overrides"),
                         restore["chat_a_overrides_after"]),
        "b": _same_state(p0.get("chat_b_overrides"),
                         restore["chat_b_overrides_after"]),
    }
    base.save("restore.json", restore)
    out("RESTORE", "a=%s b=%s equal=%s"
        % (restore["chat_a"].get("http"), restore["chat_b"].get("http"),
           restore["equal"]))

    # ── критерии + сводка ────────────────────────────────────────────────
    try:
        from services import mca_events
        await mca_events.flush_events(base.CTX.db)
    except Exception:
        pass
    summary = build_summary(p0, waves, iso, restore, results)
    try:
        from services import mca_events
        for _ in range(2):
            await mca_events.flush_events(base.CTX.db)
    except Exception as exc:  # noqa: BLE001
        out("FLUSH", "post-summary flush failed: %s" % type(exc).__name__)
    base.save("summary.json", summary)
    out("SUMMARY", json.dumps({
        "frequent": summary["criteria"]["frequent"]["verdict"],
        "occasional": summary["criteria"]["occasional"]["verdict"],
        "off": summary["criteria"]["off"]["verdict"],
        "wire": summary["checks"]["wire_ok"],
        "raw_eq": summary["checks"]["raw_eq_delivered"],
        "examples_marker": summary["checks"]["examples_marker_total"],
    }, ensure_ascii=False)[:500])

    # ── cleanup spec (правило владельца; уже писался инкрементально) ─────
    write_spec()
    try:
        with open(SPEC, "r", encoding="utf-8") as fh:
            spec_now = json.load(fh)
        spec_now["bot_id"] = getattr(me, "id", None)
        with open(SPEC, "w", encoding="utf-8") as fh:
            json.dump(spec_now, fh, ensure_ascii=False, indent=1)
    except Exception as exc:  # noqa: BLE001
        out("SPEC", "bot_id annotate failed: %s" % type(exc).__name__)
    out("SPEC", "delete A=%d B=%d"
        % (len(SENT.get(str(CHAT_A)) or []),
           len(SENT.get(str(CHAT_B_DEFAULT)) or [])))

    await base._close()
    return 0


def _app_version():
    try:
        from config.settings import settings
        return str(getattr(settings, "APP_VERSION", "?"))
    except Exception:
        return "?"


async def _user_version(base):
    try:
        rows = await base.sqlite_fetch("PRAGMA user_version")
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}


async def _restore_chat(base, api, chat_id, pre_doc):
    doc = None
    try:
        if pre_doc and pre_doc.get("expr"):
            doc = json.loads(pre_doc["expr"])
    except Exception:
        doc = None
    if isinstance(doc, dict) and doc.get("profanity"):
        values = {k: doc[k] for k in ("profanity", "wit", "sharpness",
                                      "verbosity") if doc.get(k)}
        st, body = await api.req("POST", "/api/speech/expression",
                                 chat_id=chat_id,
                                 json_body={"scope": "chat", "values": values})
        try:
            from services.chat_params import get_chat_params_cache
            cpc = get_chat_params_cache()
            if cpc is not None:
                await cpc.invalidate_chat(int(chat_id))
            await asyncio.sleep(2)
        except Exception:
            pass
        return {"http": st, "body": body, "mode": "restore-pre-doc",
                "values": values, "reread": await api_view(api, chat_id)}
    return await reset_chat_mode(api, chat_id)


def _same_state(before, after) -> dict:
    def keys(doc):
        return sorted((doc or {}).get("keys") or [])

    def expr(doc):
        val = (doc or {}).get("expr")
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return {"raw": val}
        return val

    b, a = keys(before), keys(after)
    eb, ea = expr(before), expr(after)
    return {"keys_equal": a == b, "keys_before": b, "keys_after": a,
            "expr_equal": _expr_equal(eb, ea),
            "expr_before": eb, "expr_after": ea}


def _expr_equal(a, b) -> bool:
    if a == b:
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        keys = ("profanity", "wit", "sharpness", "verbosity")
        return all(str(a.get(k)) == str(b.get(k)) for k in keys)
    return False


def build_summary(p0, waves, iso, restore, results) -> dict:
    def conv(turns):
        return [t for t in turns if t["context"] in CONVERSATIONAL]

    crit = {}
    for mode in ("off", "occasional", "frequent"):
        turns = waves[mode]["turns"]
        ok = [t for t in turns if t["status"] == "ok" and t["answer"]]
        c = conv(ok)
        with_mat = [t for t in c if t["answer_scan"]["own_count"] > 0]
        contexts = sorted({t["context"] for t in with_mat})
        words = [wd for t in with_mat for wd in t["answer_scan"]["own_words"]]
        crit[mode] = {
            "probes_total": len(turns), "ok_turns": len(ok),
            "conversational": len(c),
            "conversational_with_mat": len(with_mat),
            "share": (round(len(with_mat) / len(c), 3) if c else None),
            "contexts_with_mat": contexts,
            "mat_words": sorted(set(words)),
            "max_roots_in_sentence": max(
                [t["sentences"]["max_roots_in_sentence"] for t in c] or [0]),
            "root_per_sentence_violations": [
                t["label"] for t in c
                if t["sentences"]["max_roots_in_sentence"] > 1],
            "per_turn": [{"label": t["label"], "context": t["context"],
                          "own_mat": t["answer_scan"]["own_count"],
                          "words": t["answer_scan"]["own_words"],
                          "max_roots_in_sentence":
                              t["sentences"]["max_roots_in_sentence"],
                          "raw_eq_delivered": t["raw_eq_delivered"],
                          "answer": t["answer"][:400]} for t in turns],
        }
    # occasional: widened bound 1..5/10
    occ_n = crit["occasional"]["conversational_with_mat"]
    occ_conv = crit["occasional"]["conversational"]
    crit["occasional"]["bound"] = list(OCC_BOUND)
    crit["occasional"]["verdict"] = (
        "PASS" if (OCC_BOUND[0] <= occ_n <= OCC_BOUND[1]
                   and occ_conv >= len(OCC_CONV)) else "FAIL")
    # off
    crit["off"]["verdict"] = (
        "PASS" if (crit["off"]["conversational_with_mat"] == 0
                   and crit["off"]["conversational"] >= len(OFF_CONV))
        else "FAIL")
    quote = next((t for t in waves["off"]["turns"]
                  if t["context"] == "genre_quote"), None)
    qtext = "ну и хуйня этот ваш рефакторинг, я устал"
    crit["off"]["quote"] = {
        "answer": (quote or {}).get("answer", "")[:600],
        "verbatim_present": bool(quote and qtext in norm(
            (quote or {}).get("answer"))),
        "own_mat": (quote or {}).get("answer_scan", {}).get("own_count"),
        "protected_mat": (quote or {}).get("answer_scan", {}).get(
            "protected_count"),
    }
    # frequent
    f = crit["frequent"]
    f["verdict"] = (
        "PASS" if (f["conversational"] >= 6 and f["conversational_with_mat"] >= 3
                   and len(f["contexts_with_mat"]) >= 3
                   and f["max_roots_in_sentence"] <= 1) else "FAIL")
    summ = next((t for t in waves["frequent"]["turns"]
                 if t["context"] == "genre_summary"), None)
    f["summary"] = {
        "answer": (summ or {}).get("answer", "")[:600],
        "facts": {x: bool(summ and x in (summ.get("answer") or ""))
                  for x in FREQ_FACTS},
        "own_mat": (summ or {}).get("answer_scan", {}).get("own_count"),
        "verdict": ("PASS" if summ and all(
            x in (summ.get("answer") or "") for x in FREQ_FACTS)
            and (summ.get("answer_scan", {}).get("own_count") == 0)
            else "FAIL"),
    }
    # wire / composes / raw
    wire_all, comp_all, turns_all = [], [], []
    for mode in ("off", "occasional", "frequent"):
        for t in waves[mode]["turns"]:
            turns_all.append(t)
            wire_all.extend(t.get("wire") or [])
            comp_all.extend(t.get("composes") or [])
    per_wave_wire = {}
    for mode in ("off", "occasional", "frequent"):
        wt = [w for t in waves[mode]["turns"] for w in (t.get("wire") or [])]
        per_wave_wire[mode] = {
            "wire_calls": len(wt),
            "with_marker": sum(1 for w in wt if w.get("has_marker")),
            "with_mode_line": sum(1 for w in wt
                                  if w.get("mode_line") == mode),
            "with_expected_text": sum(
                1 for w in wt if mode in (w.get("matched_text_modes") or [])),
            "examples_marker": sum(1 for w in wt
                                   if w.get("has_examples_marker")),
            "per_turn": [{"label": t["label"], "context": t["context"],
                          "marker": sum(1 for w in (t.get("wire") or [])
                                        if w.get("has_marker")),
                          "mode_line": sum(
                              1 for w in (t.get("wire") or [])
                              if w.get("mode_line") == mode),
                          "expected_text": sum(
                              1 for w in (t.get("wire") or [])
                              if mode in (w.get("matched_text_modes") or []))}
                         for t in waves[mode]["turns"]],
        }
        per_wave_wire[mode]["turns_ok"] = all(
            e["mode_line"] >= 1 and e["expected_text"] >= 1
            for e in per_wave_wire[mode]["per_turn"])
    comp_expr = [c for c in comp_all if isinstance(c.get("expr"), dict)]
    comp_render = [c for c in comp_expr if (c.get("expr") or {}).get(
        "rendered")]
    checks = {
        "wire_calls_total": len(wire_all),
        "wire_with_marker": sum(1 for w in wire_all if w.get("has_marker")),
        "wire_by_wave": per_wave_wire,
        "composes_total": len(comp_all),
        "expression_layer_rendered": len(comp_render),
        "expression_layer_skipped": [
            {"writer": c.get("writer"),
             "reason": (c.get("expr") or {}).get("skip_reason")}
            for c in comp_expr
            if not (c.get("expr") or {}).get("rendered")][:20],
        "examples_marker_total": sum(
            1 for w in wire_all if w.get("has_examples_marker")) + sum(
            1 for c in comp_all if c.get("has_examples_marker")),
        "examples_traces": [
            {"writer": c.get("writer"),
             "rendered": (c.get("expr_examples") or {}).get("rendered"),
             "skip_reason": (c.get("expr_examples") or {}).get("skip_reason")}
            for c in comp_all
            if isinstance(c.get("expr_examples"), dict)][:20],
        "raw_eq_delivered": {
            "turns": len(turns_all),
            "equal": sum(1 for t in turns_all if t["raw_eq_delivered"]),
            "mismatches": [
                {"label": t["label"], "raw": t["raw"][:300],
                 "answer": t["answer"][:300]}
                for t in turns_all if not t["raw_eq_delivered"]][:10],
        },
        "preview_eq_resolve": p0.get("preview_eq_resolve_a"),
        "runtime_wired": (p0.get("view_a", {}).get("body") or {}).get(
            "runtime_wired"),
        "owner_approved_rows": p0.get("expression_rows"),
    }
    checks["wire_ok"] = all(v["turns_ok"] for v in per_wave_wire.values())
    checks["wire_marker_missing"] = [
        {"seq": w.get("seq"), "mode_line": w.get("mode_line")}
        for w in wire_all if not w.get("has_marker")][:10]
    # system-пример (полный L2 system одного хода)
    sample = next((c.get("system_text") for t in turns_all
                   for c in t.get("llm_calls") or [] if c.get("system_text")),
                  "")
    checks["full_l2_system_sample"] = sample[:12000]
    # изоляция
    b_eff = (((iso.get("view_b_off") or {}).get("body") or {}).get(
        "effective") or {}).get("profanity") or {}
    a_eff = (((iso.get("view_a_while_b_off") or {}).get("body") or {}).get(
        "effective") or {}).get("profanity") or {}
    crit["isolation"] = {
        "a_effective": a_eff, "b_effective": b_eff,
        "b_own_mat": sum(t["answer_scan"]["own_count"]
                         for t in waves["off"]["turns"]
                         if t["context"] in CONVERSATIONAL),
        "verdict": ("PASS" if (str(b_eff.get("value")) == "off"
                               and str(a_eff.get("value")) == "frequent")
                    else "FAIL"),
    }
    crit["restore"] = {"equal": restore.get("equal"),
                       "a_http": restore["chat_a"].get("http"),
                       "b_http": restore["chat_b"].get("http")}
    # диагностический класс (не маскируем отказ)
    diag = ""
    try:
        from services.mca_expression import (classify_expression_response,
                                             emit_expression_diag)
        f_conv = [t for t in waves["frequent"]["turns"]
                  if t["context"] in CONVERSATIONAL]
        misses = [t for t in f_conv
                  if t["answer_scan"]["own_count"] == 0]
        if crit["frequent"]["verdict"] == "PASS":
            diag = ""
        else:
            raw_join = "\n".join(t["raw"] for t in f_conv)
            diag = classify_expression_response(
                raw_join, "frequent", probes=max(1, len(misses)),
                marker_present=True, postprocess=False)
            emit_expression_diag(diag, chat_id=CHAT_A, stage="accept97",
                                 detail="f4_matrix", mode="frequent")
    except Exception as exc:  # noqa: BLE001
        diag = "diag_failed:%s" % type(exc).__name__
    crit["frequent"]["diag_class"] = diag
    # итог
    summary = {
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "app_version": results.get("app_version"),
        "chat_a": results.get("chat_a"), "chat_b": results.get("chat_b"),
        "wave_start_epoch": p0.get("wave_start_epoch"),
        "user_version": p0.get("user_version"),
        "occ_bound_pre_registered": list(OCC_BOUND),
        "criteria": crit, "checks": checks,
        "verdict": {
            "F4": ("PASS" if (crit["frequent"]["verdict"] == "PASS"
                              and crit["occasional"]["verdict"] == "PASS"
                              and crit["off"]["verdict"] == "PASS"
                              and checks["wire_ok"]
                              and checks["examples_marker_total"] == 0
                              and not checks["raw_eq_delivered"]["mismatches"]
                              and crit["frequent"]["summary"]["verdict"] == "PASS")
                   else "FAIL"),
        },
    }
    return summary


if __name__ == "__main__":
    rc = 4
    try:
        import faulthandler
        faulthandler.enable()
        out("FAULTHANDLER", "enabled")
    except Exception:
        pass
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC97 FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC97 RC=%d" % rc, flush=True)
    os._exit(rc)
