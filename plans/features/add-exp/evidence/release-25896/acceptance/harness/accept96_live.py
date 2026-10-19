# -*- coding: utf-8 -*-
"""ACCEPTANCE-96 — ADD-EXP Ф6: живая приёмка режимов «Выражение» на проде 2.58.96.

Матрица design-add-exp.md §7.2 + release-25896-report.md §4:
  * 7 контекстов × 3 режима (дружеский стёб / спор / короткий ответ / быт /
    шутка-ирония / нейтральная техзадача / фактчек) + 3 повторяемости
    (стёб/короткий/шутка) + 2 жанровые пробы (цитата с матом; тех-сводка);
  * переключение режима через POST /api/speech/expression (chat-scope тестового
    чата A; global остаётся заводским/из документа); reread после сохранения;
  * изоляция: второй чат B с chat-scope off при frequent на A;
  * wire-payload: <Expression_Settings> + строка режима (preview vs production);
  * диагностические классы §6 по промахам; «Проверить вживую» — 1 проба;
  * маршруты: Direct (полные ходы), Initiative (writer-вызов), авторский
    жанровый (authorial_system compose);
  * harness сам сохраняет тексты ответов (прод их не хранит; Ф0 §3);
  * уборка: все тестовые сообщения удаляются (правило владельца), включая
    остаток-долг «1 фото 95a» — только при надёжной идентификации.

Runs ON prod через bootstrap ACCEPTANCE-91..95 (/tmp/accept96_base.py):
развёрнутые модули, реальная Telegram-доставка (локальная Bot API-сессия),
реальные PG/SQLite/провайдеры. Прод-код не меняется; временные настройки —
только chat-scope тестовых чатов (точное восстановление reset-chat).

Выход: /tmp/accept96/evidence/*.json + /tmp/accept96/cleanup_spec.json.
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

CHAT_A = -1002661910336          # рабочий/тестовый чат (как ACCEPTANCE-91..95)
SYNTH_USER = 990002001
BOT_ID = 8802473181
EVID = "/tmp/accept96/evidence"
SPEC = "/tmp/accept96/cleanup_spec.json"
MID_BASE = 990960100             # синтетические msg_id (далеко выше реальных)

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

# ── матрица проб: (context, human, phrase) ─────────────────────────────────
CONVERSATIONAL = {"banter", "argument", "short", "everyday", "joke"}

WAVE_OFF = (
    ("banter", "дружеский стёб",
     "бот, ну ты и выдал вчера с этим докладом, весь чат ржал"),
    ("argument", "спор",
     "бот, твой вариант вообще не работает, я вчера проверял на сервере"),
    ("short", "короткий ответ", "бот, пойдёшь завтра с нами?"),
    ("everyday", "бытовая реплика",
     "бот, интернет опять отвалился, роутер перезагрузил - не помогло"),
    ("joke", "шутка/ирония", "бот, расскажи короткую шутку про понедельник"),
    ("tech", "нейтральная техзадача",
     "бот, напомни, какой командой посмотреть занятое место на диске"),
    ("factcheck", "фактчек/цитата", "бот, проверь факт: у осьминога три сердца"),
    ("genre_quote", "жанр: цитата с матом",
     "бот, передай дословно, что написал Вася: «да пошёл он нахуй со своими "
     "правками, я устал»"),
)
WAVE_OCC = (
    ("banter", "дружеский стёб",
     "бот, ну ты и выдал вчера с докладом, до сих пор вспоминаю"),
    ("argument", "спор",
     "бот, твой вариант не работает, я его на стенде гонял полдня"),
    ("short", "короткий ответ", "бот, ты завтра с нами?"),
    ("everyday", "бытовая реплика",
     "бот, интернет снова отвалился, куда смотреть в первую очередь?"),
    ("joke", "шутка/ирония", "бот, расскажи короткую шутку про дедлайны"),
    ("tech", "нейтральная техзадача",
     "бот, какой командой посмотреть размер папки на сервере?"),
    ("factcheck", "фактчек/цитата",
     "бот, это правда, что у осьминога три сердца?"),
    ("short_repeat", "короткий ответ (повтор)", "бот, ты завтра с нами?"),
)
WAVE_FREQ = (
    ("banter", "дружеский стёб",
     "бот, ну ты и выдал вчера с докладом, это было эпично"),
    ("argument", "спор",
     "бот, твой вариант вообще не работает, я на него полдня убил"),
    ("short", "короткий ответ", "бот, ты в деле завтра?"),
    ("everyday", "бытовая реплика",
     "бот, интернет опять сдох, уже третий раз за вечер"),
    ("joke", "шутка/ирония",
     "бот, расскажи короткую шутку про понедельник и дедлайны"),
    ("tech", "нейтральная техзадача",
     "бот, чем посмотреть топ процессов по памяти? коротко"),
    ("factcheck", "фактчек/цитата",
     "бот, проверь: у осьминога три сердца или одно?"),
    ("banter_repeat", "дружеский стёб (повтор)",
     "бот, ну ты и выдал вчера с докладом, это было эпично"),
    ("joke_repeat", "шутка/ирония (повтор)",
     "бот, расскажи короткую шутку про понедельник и дедлайны"),
    ("genre_summary", "жанр: тех-сводка",
     "бот, сделай короткую тех-сводку: сервер admin-bot, версия 2.58.96, "
     "диск занят на 68%, память 961 МБ, аптайм 5 дней"),
)
HEDGE_OCC = ("everyday", "бытовая реплика (добор)",
             "бот, интернет лагает второй день, что проверить в первую очередь?")
HEDGE_FREQ = ("argument", "спор (добор)",
              "бот, твой вариант не работает, я его вдоль и поперёк проверил")

TURNS_BUDGET = 30

CALLS: list[dict] = []
WIRE: list[dict] = []
COMPOSES: list[dict] = []
EXPECT = {"mode": "", "text": "", "revision": ""}
CURRENT = {"step": "", "module": "", "via": ""}
STORE_SYSTEM_TEXT = False      # follow-up: полный system одного L2-вызова


def out(tag, text):
    print("ACC96 %s | %s" % (tag, text), flush=True)


def sha12(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def head(text, n=200):
    return " ".join(str(text or "").split())[:n]


def load_base():
    spec = importlib.util.spec_from_file_location("accept96_base",
                                                  "/tmp/accept96_base.py")
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
    text = str(text or "")
    spans = _protected_spans(text)
    res = {"own": [], "protected": [], "euphemism": []}
    for label, pat in ROOT_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            tail = text[m.start():m.start() + 30]
            wm = re.match(r"[а-яёА-ЯЁa-zA-Z\-]+", tail)
            word = wm.group(0) if wm else m.group(0)
            s, e = max(0, m.start() - 40), min(len(text), m.end() + 40)
            rec = {"root": label, "word": word,
                   "ctx": " ".join(text[s:e].split())}
            if word.lower() in EUPHEMISM_WORDS:
                res["euphemism"].append(rec)
                continue
            span = next((sp for sp in spans
                         if sp[0] <= m.start() < sp[1]), None)
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
    with_mat = [p for p in parts if scan_own(p)["own"]]
    return {"sentences": len(parts), "sentences_with_mat": len(with_mat)}


# ═══════════════════════════ spies ═════════════════════════════════════════

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
                "mode_line": next((m for m, marker in MODE_LINE_MARKERS.items()
                                   if marker in system), ""),
                "expected_text_present": bool(EXPECT["text"]) and (
                    EXPECT["text"] in system),
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
        CURRENT["step"] = str(kw.get("step") or "")
        CURRENT["module"] = str(kw.get("module") or "")
        CURRENT["via"] = via
        sys_txt = ""
        for m in (messages or []):
            if isinstance(m, dict) and str(m.get("role")) == "system":
                sys_txt = str(m.get("content") or "")
                break
        rec["system_chars"] = len(sys_txt)
        rec["system_sha12"] = sha12(sys_txt)
        rec["has_marker"] = "<Expression_Settings>" in sys_txt
        rec["mode_line"] = next((m for m, marker in MODE_LINE_MARKERS.items()
                                 if marker in sys_txt), "")
        rec["expected_text_present"] = bool(EXPECT["text"]) and (
            EXPECT["text"] in sys_txt)
        if STORE_SYSTEM_TEXT and str(kw.get("step")) == "l2_writer":
            rec["system_text"] = sys_txt[:24000]
        CALLS.append(rec)
        try:
            result = await fn(messages, **kw)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = type(exc).__name__
            raise
        try:
            rec["raw"] = str(result or "")[:4000]
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
            "module": CURRENT.get("module"), "step": CURRENT.get("step"),
            "model": model or payload.get("model"),
            "n_messages": len(msgs),
            "payload_sha12": sha12(json.dumps(payload, sort_keys=True,
                                              ensure_ascii=False)),
            "has_marker": "<Expression_Settings>" in sys_txt,
            "has_examples_marker": "<Expression_Examples>" in sys_txt,
            "mode_line": next((m for m, marker in MODE_LINE_MARKERS.items()
                               if marker in sys_txt), ""),
            "expected_text_present": bool(EXPECT["text"]) and (
                EXPECT["text"] in sys_txt),
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
    st, body = await api.req("GET", "/api/speech/expression",
                             chat_id=chat_id)
    return {"http": st, "body": body}


async def set_chat_mode(base, api, chat_id, mode):
    st, body = await api.req("POST", "/api/speech/expression",
                             chat_id=chat_id,
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
    try:
        preview_eq = (sha12((view.get("body") or {}).get("rendered_text"))
                      == resolved["text_sha12"])
    except Exception:
        preview_eq = None
    return {"write_http": st, "write_body": body, "reread": view,
            "resolved": resolved, "preview_eq_resolve": preview_eq,
            "pg_doc_after": await pg_chat_expr_doc(base, chat_id)}


async def pg_chat_expr_doc(base, chat_id):
    """Read-after-write на уровне хранилища: doc/revision chat-scope (PG)."""
    try:
        rows = await base.pg_fetch(
            "SELECT (chat_params->'overrides'->'character.expression')::text "
            "AS doc, chat_params->'overrides'->'character.expression'->>"
            "'revision' AS revision, chat_params->'overrides'->"
            "'character.expression'->>'updated_at' AS updated_at "
            "FROM chat_profiles WHERE chat_id=$1", (chat_id,))
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}


async def wait_reread(api, chat_id, mode, tries=5, delay=20.0):
    """Reread из ПРОД-процесса (без рестарта): NOTIFY-инвалидация/TTL 120 c."""
    view = await api_view(api, chat_id)
    for _ in range(tries - 1):
        eff = (((view.get("body") or {}).get("effective") or {})
               .get("profanity") or {})
        if str(eff.get("value")) == mode:
            break
        await asyncio.sleep(delay)
        view = await api_view(api, chat_id)
    return view


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


async def resolve_expected(chat_id):
    from services import prompt_composer as pc
    ref = await pc.resolve_expression_settings(int(chat_id))
    return {"mode": str(getattr(ref, "mode", "") or ""),
            "source": str(getattr(ref, "source", "") or ""),
            "revision": str(getattr(ref, "revision", "") or ""),
            "text_sha12": sha12(str(getattr(ref, "text", "") or "")),
            "text_chars": len(str(getattr(ref, "text", "") or "")),
            "skip_reason": str(getattr(ref, "skip_reason", "") or ""),
            "enabled": bool(getattr(ref, "enabled", False)),
            "text": str(getattr(ref, "text", "") or "")[:4000]}


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
    turn = {
        "label": label, "chat_id": chat_id, "mode": mode, "context": context,
        "phrase": phrase, "status": res.get("status"),
        "error": res.get("error"),
        "correlation_id": res.get("correlation_id"),
        "elapsed_s": res.get("elapsed_s"),
        "plan_meta": res.get("plan_meta"),
        "sends": sends,
        "answer": answer[:6000],
        "answer_scan": scan,
        "sentences": sentence_stats(answer),
        "llm_calls": CALLS[calls_before:],
        "wire": WIRE[wire_before:],
        "composes": COMPOSES[comp_before:],
        "usage": res.get("usage"),
    }
    return turn, res.get("_last_msg"), res


async def wave(base, api, chat_id, mode, probes, *, wave_name, timeout=300):
    """Одна волна: режим → anchor → пробы. Возврат dict волны."""
    out("WAVE", "%s: set chat-scope profanity=%s chat=%s"
        % (wave_name, mode, chat_id))
    switch = await set_chat_mode(base, api, chat_id, mode)
    EXPECT["mode"] = mode
    EXPECT["text"] = str((switch.get("resolved") or {}).get("text") or "")
    EXPECT["revision"] = str((switch.get("resolved") or {}).get("revision")
                             or "")
    out("WAVE", "%s: write_http=%s effective=%s source=%s rev=%s"
        % (wave_name, switch["write_http"],
           ((switch.get("reread") or {}).get("body") or {}).get(
               "effective", {}).get("profanity", {}).get("value"),
           ((switch.get("reread") or {}).get("body") or {}).get(
               "effective", {}).get("profanity", {}).get("source"),
           (switch.get("resolved") or {}).get("revision")))
    anchor = await base.CTX.rec.send_message(
        chat_id,
        "🧪 Приёмка 2.58.96 ADD-EXP · волна «%s» (контролируемая проверка; "
        "сообщения удаляются)" % mode)
    wave_rec = {
        "wave": wave_name, "mode": mode, "chat_id": chat_id,
        "switch": switch, "anchor_mid": getattr(anchor, "message_id", None),
        "turns": [],
    }
    mid = int(getattr(anchor, "message_id", 0) or MID_BASE)
    fallback_mid = MID_BASE
    last_msg = anchor
    for i, (context, human, phrase) in enumerate(probes):
        label = "%s-%02d-%s" % (mode, i + 1, context)
        turn, last_msg_new, _res = await do_turn(
            base, chat_id, phrase, label=label, context=context, mode=mode,
            anchor_msg=last_msg, mid=mid, timeout=timeout)
        wave_rec["turns"].append(turn)
        if last_msg_new is not None:
            last_msg = last_msg_new
            mid = int(getattr(last_msg_new, "message_id", 0) or fallback_mid)
        else:
            fallback_mid += 1
            mid = fallback_mid
        out("TURN", "%s | %s | status=%s | own_mat=%d | %s"
            % (label, human, turn["status"], turn["answer_scan"]["own_count"],
               head(turn["answer"], 90)))
    try:
        from services import mca_events
        flushed = await mca_events.flush_events(base.CTX.db)
        wave_rec["flushed_events"] = flushed
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
    out("BOOT", "bot=%s pg=%s" % (getattr(base.CTX.me, "id", None),
                                  bool(getattr(base.CTX.pg, "pool", None))))
    install_spies(base)
    api = base.Api()
    base.CTX.api = api
    results: dict = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.gmtime()),
                     "chat_a": CHAT_A}

    # ── P0: pre-state (read-only) ─────────────────────────────────────────
    p0: dict = {"wave_start_epoch": wave_start}
    p0["view_a"] = await api_view(api, CHAT_A)
    p0["view_global"] = await api_view(api, None)
    p0["resolve_a"] = await resolve_expected(CHAT_A)
    # production preview vs resolve (тот же builder)
    try:
        p0["preview_eq_resolve"] = (
            sha12((p0["view_a"]["body"] or {}).get("rendered_text"))
            == p0["resolve_a"]["text_sha12"])
    except Exception:
        p0["preview_eq_resolve"] = None
    # чаты (для изоляции)
    try:
        p0["chats"] = await base.sqlite_fetch(
            "SELECT chat_id, COUNT(*) AS n, MAX(timestamp) AS last_ts "
            "FROM smart_messages GROUP BY chat_id "
            "ORDER BY last_ts DESC LIMIT 12")
    except Exception as exc:  # noqa: BLE001
        p0["chats"] = "failed:%s" % type(exc).__name__
    # библиотека примеров
    try:
        st, body = await api.req("GET", "/api/speech/examples", chat_id=CHAT_A)
        p0["examples_view"] = {"http": st, "starter": (body or {}).get(
            "starter"), "counts": (body or {}).get("count")}
    except Exception as exc:  # noqa: BLE001
        p0["examples_view"] = "failed:%s" % type(exc).__name__
    # остаток-долг 95a: идентификация фото (mid 1166467/1166469)
    try:
        p0["residual_asset"] = await base.sqlite_fetch(
            "SELECT asset_id, message_key, chat_id, tg_message_id, "
            "asset_kind, mime, byte_size, created_at FROM mca_media_assets "
            "WHERE asset_id='a88867d9ba305b7232359a08d6a536de'")
        p0["residual_assets_window"] = await base.sqlite_fetch(
            "SELECT asset_id, tg_message_id, asset_kind, mime, byte_size, "
            "created_at FROM mca_media_assets WHERE chat_id=? AND "
            "tg_message_id BETWEEN 1166460 AND 1166475 "
            "ORDER BY tg_message_id", (CHAT_A,))
        p0["residual_parents"] = await base.sqlite_fetch(
            "SELECT tg_message_id, parent_tg_message_id FROM "
            "bot_reply_parents WHERE chat_id=? AND (tg_message_id IN "
            "(1166467,1166469) OR parent_tg_message_id IN (1166467,1166469))",
            (CHAT_A,))
        p0["residual_smart"] = await base.sqlite_fetch(
            "SELECT tg_message_id, user_id, substr(text,1,80) AS head FROM "
            "smart_messages WHERE chat_id=? AND tg_message_id IN "
            "(1166467,1166468,1166469)", (CHAT_A,))
        p0["residual_replies"] = await base.sqlite_fetch(
            "SELECT tg_message_id, substr(text,1,80) AS head FROM "
            "bot_replies WHERE chat_id=? AND tg_message_id IN "
            "(1166467,1166469)", (CHAT_A,))
    except Exception as exc:  # noqa: BLE001
        p0["residual_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    # точное восстановление: исходные overrides чата A (PG)
    try:
        p0["chat_a_overrides"] = await base.pg_fetch(
            "SELECT (SELECT array_agg(k ORDER BY k) FROM "
            "jsonb_object_keys(chat_params->'overrides') k) AS keys, "
            "(chat_params->'overrides'->'character.expression')::text "
            "AS expr FROM chat_profiles WHERE chat_id=$1", (CHAT_A,))
    except Exception as exc:  # noqa: BLE001
        p0["chat_a_overrides"] = "failed:%s" % type(exc).__name__
    base.save("p0-pre-state.json", p0)
    out("P0", "preview_eq_resolve=%s chats=%s residual_asset=%s"
        % (p0.get("preview_eq_resolve"), len(p0.get("chats") or []),
           json.dumps(p0.get("residual_asset"), ensure_ascii=False)[:200]))

    # ── выбор чата B (изоляция) ───────────────────────────────────────────
    chat_b = None
    fallback_b = None
    for row in (p0.get("chats") or []):
        try:
            cid = int(row.get("chat_id") or 0)
            n = int(row.get("n") or 0)
        except Exception:
            continue
        if not cid or cid == CHAT_A:
            continue
        if fallback_b is None:
            fallback_b = cid
        if n >= 20:
            chat_b = cid
            break
    if chat_b is None:
        chat_b = fallback_b
    results["chat_b"] = chat_b
    out("CHAT_B", "selected=%s" % chat_b)
    p0["chat_b_overrides"] = None
    if chat_b:
        try:
            p0["chat_b_overrides"] = await base.pg_fetch(
                "SELECT (SELECT array_agg(k ORDER BY k) FROM "
                "jsonb_object_keys(chat_params->'overrides') k) AS keys, "
                "(chat_params->'overrides'->'character.expression')::text "
                "AS expr FROM chat_profiles WHERE chat_id=$1", (chat_b,))
        except Exception as exc:  # noqa: BLE001
            p0["chat_b_overrides"] = "failed:%s" % type(exc).__name__
        base.save("p0-pre-state.json", p0)

    # ── P1: seed черновиков (идемпотентно) + not_owner_approved база ──────
    p1: dict = {}
    st, body = await api.req("POST", "/api/speech/examples/seed",
                             chat_id=CHAT_A)
    p1["seed_run1"] = {"http": st, "body": body}
    st2, body2 = await api.req("POST", "/api/speech/examples/seed",
                               chat_id=CHAT_A)
    p1["seed_run2"] = {"http": st2, "body": body2}
    try:
        p1["rows"] = await base.sqlite_fetch(
            "SELECT technique, status, owner_approved, COUNT(*) AS n FROM "
            "humor_samples WHERE technique='expression_register' "
            "GROUP BY 1,2,3")
    except Exception as exc:  # noqa: BLE001
        p1["rows"] = "failed:%s" % type(exc).__name__
    base.save("p1-seed.json", p1)
    out("P1", "seed1=%s seed2=%s" % (
        json.dumps((p1["seed_run1"]["body"] or {}) if isinstance(
            p1["seed_run1"]["body"], dict) else {}, ensure_ascii=False)[:200],
        json.dumps((p1["seed_run2"]["body"] or {}) if isinstance(
            p1["seed_run2"]["body"], dict) else {}, ensure_ascii=False)[:160]))

    # ── волны A: off → occasional → frequent ─────────────────────────────
    turns_used = 0
    waves = {}
    for mode, probes, name in (
            ("off", WAVE_OFF, "off"),
            ("occasional", WAVE_OCC, "occasional"),
            ("frequent", WAVE_FREQ, "frequent")):
        w = await wave(base, api, CHAT_A, mode, probes, wave_name=name)
        waves[mode] = w
        turns_used += len(probes)
        base.save("wave-%s.json" % name, w)

    # ── пре-декларированные доборы (граница критериев; кап ≤30 ходов) ─────
    hedges: list = []

    def conv_stats(w):
        conv = [t for t in w["turns"] if t["context"].split("_")[0]
                in CONVERSATIONAL]
        with_mat = [t for t in conv if t["answer_scan"]["own_count"] > 0]
        return conv, with_mat

    occ_conv, occ_mat = conv_stats(waves["occasional"])
    if not occ_mat and turns_used < TURNS_BUDGET:
        out("HEDGE", "occasional: 0/%d разговорных с матом — добор 1 проба"
            % len(occ_conv))
        w = await wave(base, api, CHAT_A, "occasional", (HEDGE_OCC,),
                       wave_name="occasional-hedge")
        waves["occasional"]["turns"].extend(w["turns"])
        waves["occasional"]["hedge"] = w["switch"]
        turns_used += 1
        hedges.append("occasional+1")
        base.save("wave-occasional.json", waves["occasional"])
    freq_conv, freq_mat = conv_stats(waves["frequent"])
    need = -(-len(freq_conv) // 2)          # ceil(50%)
    if len(freq_mat) < need and len(freq_mat) + 1 >= (
            len(freq_conv) + 1) / 2 and turns_used < TURNS_BUDGET:
        out("HEDGE", "frequent: %d/%d — добор 1 проба (порог 50%%)"
            % (len(freq_mat), len(freq_conv)))
        w = await wave(base, api, CHAT_A, "frequent", (HEDGE_FREQ,),
                       wave_name="frequent-hedge")
        waves["frequent"]["turns"].extend(w["turns"])
        waves["frequent"]["hedge"] = w["switch"]
        turns_used += 1
        hedges.append("frequent+1")
        base.save("wave-frequent.json", waves["frequent"])
    results["hedges"] = hedges
    results["turns_used"] = turns_used

    # ── изоляция: чат B с off при frequent на A ──────────────────────────
    iso: dict = {"chat_b": chat_b}
    if chat_b:
        try:
            b_switch = await set_chat_mode(base, api, chat_b, "off")
            iso["switch_b"] = b_switch
            iso["view_a_while_b_off"] = await api_view(api, CHAT_A)
            EXPECT["mode"] = "off"
            EXPECT["text"] = str((b_switch.get("resolved") or {}).get("text")
                                 or "")
            anchor_b = await base.CTX.rec.send_message(
                chat_b,
                "🧪 Приёмка 2.58.96 ADD-EXP · изоляция (чат B: без мата; "
                "сообщения удаляются)")
            iso["anchor_b_mid"] = getattr(anchor_b, "message_id", None)
            iso["turns"] = []
            mid_b = int(getattr(anchor_b, "message_id", 0) or MID_BASE)
            fallback_mid_b = MID_BASE + 500
            last_b = anchor_b
            for i, (context, human, phrase) in enumerate((
                    ("banter", "дружеский стёб",
                     "бот, ну ты и выдал вчера с докладом, это было эпично"),
                    ("short", "короткий ответ", "бот, ты в деле завтра?"))):
                turn, last_new, _r = await do_turn(
                    base, chat_b, phrase, label="iso-B-%02d-%s" % (i + 1,
                                                                   context),
                    context=context, mode="off", anchor_msg=last_b,
                    mid=mid_b)
                iso["turns"].append(turn)
                if last_new is not None:
                    last_b = last_new
                    mid_b = int(getattr(last_new, "message_id", 0)
                                or fallback_mid_b)
                else:
                    fallback_mid_b += 1
                    mid_b = fallback_mid_b
                out("ISO", "B %s | status=%s | own_mat=%d"
                    % (context, turn["status"],
                       turn["answer_scan"]["own_count"]))
        except Exception as exc:  # noqa: BLE001
            iso["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            out("ISO", "FAILED %s" % iso["error"])
    else:
        iso["note"] = ("второго чата нет — изоляция проверяется на уровне "
                       "резолвера/payload (честная альтернатива)")
    base.save("isolation.json", iso)

    # ── маршруты: authorial (compose) + Initiative (writer-вызов) ────────
    routes: dict = {}
    resolved_a_freq = await resolve_expected(CHAT_A)
    EXPECT["mode"] = "frequent"
    EXPECT["text"] = str(resolved_a_freq.get("text") or "")
    EXPECT["revision"] = str(resolved_a_freq.get("revision") or "")
    routes["resolved_a_before_routes"] = resolved_a_freq
    try:
        from services import mca_authorial_speech as mas
        system, manifest = await mas.authorial_system(
            chat_id=CHAT_A, writer="nostalgia_writer", genre="nostalgia",
            legacy_canon="Ты пишешь тёплый ностальгический текст о прошлом.",
            channel="plain")
        layers = []
        try:
            import services.prompt_composer as pc
            layers = [t for t in pc.manifest_for_events(manifest)["layers"]
                      if t.get("layer") in ("expression", "few_shot")]
        except Exception:
            pass
        routes["authorial"] = {
            "writer": "nostalgia_writer",
            "system_chars": len(system or ""),
            "has_marker": "<Expression_Settings>" in str(system or ""),
            "mode_line": next((m for m, marker in MODE_LINE_MARKERS.items()
                               if marker in str(system or "")), ""),
            "layers": layers,
        }
        out("ROUTE", "authorial has_marker=%s mode_line=%s"
            % (routes["authorial"]["has_marker"],
               routes["authorial"]["mode_line"]))
    except Exception as exc:  # noqa: BLE001
        routes["authorial"] = {"error": "%s: %s" % (type(exc).__name__,
                                                    str(exc)[:160])}
    try:
        from services import usage_events as _ue
        corr_init = _ue.new_correlation_id()
        calls_before = len(CALLS)
        wire_before = len(WIRE)
        comp_before = len(COMPOSES)
        text = await base.CTX.svc.generate_initiative_reply(
            CHAT_A, {"kind": "unanswered_question", "origin": "accept96",
                     "goal": "в чате недавно спрашивали про интернет и "
                             "роутер — прояви инициативу и предложи проверку"},
            correlation_id=corr_init)
        routes["initiative"] = {
            "correlation_id": corr_init,
            "reply": str(text or "")[:1500],
            "reply_scan": scan_own(text),
            "llm_calls": CALLS[calls_before:],
            "wire": WIRE[wire_before:],
            "composes": COMPOSES[comp_before:],
        }
        out("ROUTE", "initiative reply_len=%s own_mat=%s"
            % (len(str(text or "")), routes["initiative"]["reply_scan"]
               ["own_count"]))
    except Exception as exc:  # noqa: BLE001
        routes["initiative"] = {"error": "%s: %s" % (type(exc).__name__,
                                                     str(exc)[:160])}
    base.save("routes.json", routes)

    # ── «Проверить вживую» — 1 проба через штатный endpoint ──────────────
    lc: dict = {}
    try:
        st, body = await api.req(
            "POST", "/api/speech/expression/live-check", chat_id=CHAT_A,
            json_body={"message": "ну ты и выдал вчера с докладом, это было "
                                  "эпично"})
        lc = {"http": st, "body": body}
        out("LIVE_CHECK", "http=%s mode=%s diag=%s marker=%s len=%s"
            % (st, (body or {}).get("mode"), (body or {}).get("diag_class"),
               (body or {}).get("expression_marker"),
               (body or {}).get("reply_chars")))
    except Exception as exc:  # noqa: BLE001
        lc = {"error": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
        out("LIVE_CHECK", "FAILED %s" % lc["error"])
    base.save("live-check.json", lc)

    # ── restore: точное снятие chat-scope у A и B ────────────────────────
    restore: dict = {"chat_a": await reset_chat_mode(api, CHAT_A)}
    if chat_b:
        restore["chat_b"] = await reset_chat_mode(api, chat_b)
    restore["global_view_after"] = await api_view(api, None)
    restore["a_view_after"] = await api_view(api, CHAT_A)
    try:
        restore["chat_a_overrides_after"] = await base.pg_fetch(
            "SELECT (SELECT array_agg(k ORDER BY k) FROM "
            "jsonb_object_keys(chat_params->'overrides') k) AS keys, "
            "(chat_params->'overrides'->'character.expression')::text "
            "AS expr FROM chat_profiles WHERE chat_id=$1", (CHAT_A,))
        if chat_b:
            restore["chat_b_overrides_after"] = await base.pg_fetch(
                "SELECT (SELECT array_agg(k ORDER BY k) FROM "
                "jsonb_object_keys(chat_params->'overrides') k) AS keys, "
                "(chat_params->'overrides'->'character.expression')::text "
                "AS expr FROM chat_profiles WHERE chat_id=$1", (chat_b,))
    except Exception as exc:  # noqa: BLE001
        restore["overrides_check"] = "failed:%s" % type(exc).__name__
    base.save("restore.json", restore)
    out("RESTORE", "a=%s b=%s"
        % (restore["chat_a"]["http"],
           (restore.get("chat_b") or {}).get("http")))

    # ── агрегат критериев + диагностика ──────────────────────────────────
    try:
        from services import mca_events
        await mca_events.flush_events(base.CTX.db)
    except Exception:
        pass
    summary = await build_summary(base, waves, iso, routes, p0, p1, lc,
                                  restore, wave_start, turns_used, hedges)
    base.save("summary.json", summary)
    out("SUMMARY", json.dumps({
        "turns_used": summary.get("turns_used"),
        "off": summary["criteria"]["off"]["verdict"],
        "occasional": summary["criteria"]["occasional"]["verdict"],
        "frequent": summary["criteria"]["frequent"]["verdict"],
        "isolation": summary["criteria"]["isolation"]["verdict"],
    }, ensure_ascii=False)[:400])

    # ── cleanup spec ─────────────────────────────────────────────────────
    delete_mids: dict = {}
    for cid, recs in ((CHAT_A, [waves[m] for m in ("off", "occasional",
                                                   "frequent")]),
                      (chat_b, [iso] if chat_b else [])):
        mids = []
        for w in recs:
            if not isinstance(w, dict):
                continue
            anchor = w.get("anchor_mid") or w.get("anchor_b_mid")
            if anchor:
                mids.append(int(anchor))
            for t in w.get("turns") or []:
                for s in t.get("sends") or []:
                    if s.get("message_id"):
                        mids.append(int(s["message_id"]))
        delete_mids[str(cid)] = sorted(set(mids))
    # остаток 95a: удаляем только при надёжной идентификации
    residual = {"candidates": [1166467, 1166469], "delete": [],
                "identification": []}
    try:
        asset_rows = p0.get("residual_asset") or []
        for row in asset_rows:
            if int(row.get("tg_message_id") or 0) == 1166469:
                residual["delete"].append(1166469)
                residual["identification"].append(
                    "mca_media_assets.asset_id=a88867d9ba305b7232359a08d6a536de"
                    " -> tg_message_id=1166469")
        if not residual["delete"]:
            for row in (p0.get("residual_parents") or []):
                if int(row.get("tg_message_id") or 0) == 1166469:
                    residual["delete"].append(1166469)
                    residual["identification"].append(
                        "bot_reply_parents: 1166469 -> %s"
                        % row.get("parent_tg_message_id"))
    except Exception as exc:  # noqa: BLE001
        residual["error"] = type(exc).__name__
    spec = {
        "chat_a": CHAT_A, "chat_b": chat_b,
        "delete_mids": delete_mids,
        "residual_95a": residual,
        "synth_user": SYNTH_USER,
        "notes": ("удалить все сообщения бота тестовых волн A/B; остаток 95a "
                  "(mid 1166469) — только при подтверждённой идентификации"),
    }
    with open(SPEC, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(spec, ensure_ascii=False, indent=1))
    out("SPEC", "delete A=%d B=%d residual=%s"
        % (len(delete_mids.get(str(CHAT_A)) or []),
           len(delete_mids.get(str(chat_b)) or []),
           residual.get("delete")))

    await base._close()
    return 0


async def build_summary(base, waves, iso, routes, p0, p1, lc, restore,
                        wave_start, turns_used, hedges):
    def conv(turns):
        return [t for t in turns
                if t["context"].split("_")[0] in CONVERSATIONAL]

    crit: dict = {}
    for mode in ("off", "occasional", "frequent"):
        w = waves[mode]
        turns = w["turns"]
        ok_turns = [t for t in turns if t["status"] == "ok" and t["answer"]]
        c = conv(ok_turns)
        with_mat = [t for t in c if t["answer_scan"]["own_count"] > 0]
        contexts = sorted({t["context"].split("_")[0] for t in with_mat})
        words = [wd for t in with_mat for wd in t["answer_scan"]["own_words"]]
        repeated_words = sorted({wd for wd in words if words.count(wd) > 1})
        every_sentence = [t["label"] for t in with_mat
                          if t["sentences"]["sentences"] > 1
                          and t["sentences"]["sentences_with_mat"]
                          == t["sentences"]["sentences"]]
        # «без повтора одного слова» (источник §1: «без бессмысленного спама
        # одинаковыми словами»): спам внутри одной реплики (≥2 вхождения
        # одного слова) или одно-слово-гиммик (одно слово во ВСЕХ матерных
        # репликах при ≥3 репликах) — провал; повтор слова в НЕСКОЛЬКИХ
        # разных репликах фиксируется как наблюдение (живой голос повторяет
        # частотные междометия).
        within_reply = []
        for t in with_mat:
            counts = {}
            for r in t["answer_scan"]["own"]:
                key = r["word"].lower()
                counts[key] = counts.get(key, 0) + 1
            for wd, n in counts.items():
                if n >= 2:
                    within_reply.append({"label": t["label"], "word": wd,
                                         "count": n})
        per_word_turns = {}
        for t in with_mat:
            for wd in set(t["answer_scan"]["own_words"]):
                per_word_turns.setdefault(wd, []).append(t["label"])
        dominant = ""
        if len(with_mat) >= 3:
            for wd, labels in per_word_turns.items():
                if len(labels) == len(with_mat):
                    dominant = wd
                    break
        crit[mode] = {
            "probes_total": len(turns), "ok_turns": len(ok_turns),
            "conversational": len(c), "conversational_with_mat": len(with_mat),
            "share": (round(len(with_mat) / len(c), 3) if c else None),
            "contexts_with_mat": contexts,
            "mat_words": sorted(set(words)),
            "repeated_across_replies": {
                wd: labels for wd, labels in per_word_turns.items()
                if len(labels) > 1},
            "same_word_within_reply": within_reply,
            "dominant_word_all_replies": dominant,
            "all_sentences_matted": every_sentence,
            "per_context": {
                t["context"]: {"own_mat": t["answer_scan"]["own_count"],
                               "words": t["answer_scan"]["own_words"],
                               "status": t["status"]}
                for t in turns},
            "quote_preserved": None,
        }
    # жанровые пробы
    try:
        off_quote = next((t for t in waves["off"]["turns"]
                          if t["context"] == "genre_quote"), None)
        crit["off"]["quote_preserved"] = bool(
            off_quote and "нахуй" in (off_quote.get("answer") or ""))
        crit["off"]["quote_own_mat"] = (off_quote or {}).get(
            "answer_scan", {}).get("own_count")
    except Exception:
        pass
    try:
        freq_sum = next((t for t in waves["frequent"]["turns"]
                         if t["context"] == "genre_summary"), None)
        facts = ("68", "961", "2.58.96")
        crit["frequent"]["summary_facts"] = {
            f: bool(freq_sum and f in (freq_sum.get("answer") or ""))
            for f in facts}
        crit["frequent"]["summary_own_mat"] = (freq_sum or {}).get(
            "answer_scan", {}).get("own_count")
    except Exception:
        pass
    occ_n = crit["occasional"]["conversational_with_mat"]
    freq_n = crit["frequent"]["conversational_with_mat"]
    crit["occasional"]["verdict"] = (
        "PASS" if (0 < occ_n and crit["occasional"]["share"] is not None
                   and crit["occasional"]["share"] <= 0.40) else "FAIL")
    crit["frequent"]["verdict"] = (
        "PASS" if (crit["frequent"]["share"] is not None
                   and crit["frequent"]["share"] >= 0.50
                   and freq_n >= 2 * max(1, occ_n)
                   and len(crit["frequent"]["contexts_with_mat"]) >= 3
                   and not crit["frequent"]["all_sentences_matted"]
                   and not crit["frequent"]["same_word_within_reply"]
                   and not crit["frequent"]["dominant_word_all_replies"])
        else "FAIL")
    crit["off"]["verdict"] = (
        "PASS" if crit["off"]["conversational_with_mat"] == 0 else "FAIL")
    # изоляция
    iso_turns = iso.get("turns") or []
    iso_own = sum(t["answer_scan"]["own_count"] for t in iso_turns)
    a_view = ((iso.get("view_a_while_b_off") or {}).get("body") or {})
    b_view = ((iso.get("switch_b") or {}).get("reread") or {}).get("body") or {}
    crit["isolation"] = {
        "chat_b": iso.get("chat_b"),
        "error": iso.get("error"),
        "b_effective": (b_view.get("effective") or {}).get("profanity"),
        "a_effective_while_b_off": (a_view.get("effective") or {}).get(
            "profanity"),
        "b_turns": len(iso_turns), "b_own_mat": iso_own,
        "verdict": ("PASS" if (iso.get("chat_b") and iso_turns
                               and iso_own == 0
                               and (b_view.get("effective") or {}).get(
                                   "profanity", {}).get("value") == "off"
                               and (a_view.get("effective") or {}).get(
                                   "profanity", {}).get("value")
                               == "frequent") else
                    ("FAILED_B" if iso.get("error") else
                     ("PARTIAL" if iso.get("chat_b") else "NO_SECOND_CHAT"))),
    }
    # wire/preview/reread
    wire_all = []
    comp_all = []
    for mode in ("off", "occasional", "frequent"):
        for t in waves[mode]["turns"]:
            wire_all.extend(t.get("wire") or [])
            comp_all.extend(t.get("composes") or [])
    expr_comp = [c for c in comp_all if isinstance(c.get("expr"), dict)
                 and (c.get("expr") or {}).get("layer") == "expression"]
    expr_rendered = [c for c in expr_comp
                     if (c.get("expr") or {}).get("rendered")]
    expr_skipped = [c for c in expr_comp
                    if not (c.get("expr") or {}).get("rendered")]
    few_comp = [c for c in comp_all if isinstance(c.get("expr_examples"),
                                                  dict)]
    checks = {
        "wire_calls_total": len(wire_all),
        "wire_with_marker": sum(1 for w in wire_all if w.get("has_marker")),
        "wire_with_mode_line": sum(1 for w in wire_all
                                   if w.get("mode_line")),
        "wire_expected_text_present": sum(
            1 for w in wire_all if w.get("expected_text_present")),
        "composes_total": len(comp_all),
        "expression_layer_rendered": len(expr_rendered),
        "expression_layer_skipped": [
            {"writer": c.get("writer"),
             "reason": (c.get("expr") or {}).get("skip_reason")}
            for c in expr_skipped],
        "expression_examples_traces": [
            {"writer": c.get("writer"),
             "rendered": (c.get("expr_examples") or {}).get("rendered"),
             "skip_reason": (c.get("expr_examples") or {}).get("skip_reason")}
            for c in few_comp][:20],
        "preview_eq_resolve": p0.get("preview_eq_resolve"),
        "preview_eq_resolve_per_wave": {
            m: waves[m]["switch"].get("preview_eq_resolve")
            for m in ("off", "occasional", "frequent")},
        "runtime_wired": (p0.get("view_a", {}).get("body") or {}).get(
            "runtime_wired"),
        "reread_after_write": {
            m: {
                "write_http": waves[m]["switch"]["write_http"],
                "reread_value": (((waves[m]["switch"].get("reread") or {}
                                   ).get("body") or {}).get("effective", {})
                                 .get("profanity", {}).get("value")),
                "reread_source": (((waves[m]["switch"].get("reread") or {}
                                    ).get("body") or {}).get("effective", {})
                                  .get("profanity", {}).get("source")),
                "revision": (waves[m]["switch"].get("resolved") or {}).get(
                    "revision"),
            } for m in ("off", "occasional", "frequent")},
        "restore": {
            "a_http": restore["chat_a"]["http"],
            "a_inheritance": ((restore["a_view_after"].get("body") or {})
                              .get("inheritance")),
            "b_http": (restore.get("chat_b") or {}).get("http"),
            "global_revision_after": ((restore["global_view_after"].get(
                "body") or {}).get("document") or {}).get("revision"),
            "a_overrides_before": p0.get("chat_a_overrides"),
            "a_overrides_after": restore.get("chat_a_overrides_after"),
            "b_overrides_before": p0.get("chat_b_overrides"),
            "b_overrides_after": restore.get("chat_b_overrides_after"),
            "global_doc_before": ((p0.get("view_global") or {}).get(
                "body") or {}).get("document"),
            "global_doc_after": ((restore.get("global_view_after") or {}
                                  ).get("body") or {}).get("document"),
            "a_inheritance_after": ((restore.get("a_view_after") or {}
                                     ).get("body") or {}).get("inheritance"),
        },
    }
    # диагностические события §6
    diag = []
    try:
        diag = await base.sqlite_fetch(
            "SELECT ts, event_name, outcome, level, stage, status, "
            "reason_code, chat_id FROM mca_events WHERE ts >= ? AND "
            "event_name IN ('expression_diag','prompt_layers') "
            "ORDER BY ts", (wave_start,))
    except Exception as exc:  # noqa: BLE001
        diag = [{"error": type(exc).__name__}]
    # not_owner_approved live
    noa = [c for c in few_comp
           if (c.get("expr_examples") or {}).get("skip_reason")
           == "not_owner_approved"]
    examples_in_payload = sum(
        1 for c in comp_all if c.get("has_examples_marker"))
    examples_in_wire = sum(
        1 for w in wire_all if w.get("has_examples_marker"))
    checks["not_owner_approved"] = {
        "composes_with_not_owner_approved": len(noa),
        "examples_marker_in_composed_systems": examples_in_payload,
        "examples_marker_in_wire": examples_in_wire,
        "seed_run1": (p1.get("seed_run1", {}).get("body") or {}),
        "seed_run2": (p1.get("seed_run2", {}).get("body") or {}),
        "rows": p1.get("rows"),
    }
    # llm calls итог
    calls_all = []
    for mode in ("off", "occasional", "frequent"):
        for t in waves[mode]["turns"]:
            calls_all.extend(t.get("llm_calls") or [])
    init_calls = (routes.get("initiative") or {}).get("llm_calls") or []
    checks["llm_calls_total"] = len(calls_all) + len(init_calls)
    checks["llm_steps"] = {}
    for c in calls_all + init_calls:
        key = "%s/%s" % (c.get("module"), c.get("step"))
        checks["llm_steps"][key] = checks["llm_steps"].get(key, 0) + 1
    # raw (LLM) vs доставленный текст: мат не подавлен постпроцессором/egress
    raw_vs_delivered = []
    for mode in ("off", "occasional", "frequent"):
        for t in waves[mode]["turns"]:
            raw_scan = {}
            for c in (t.get("llm_calls") or []):
                if str(c.get("step")) == "l2_writer" and c.get("raw_scan"):
                    raw_scan = c["raw_scan"]
            if not raw_scan:
                continue
            if raw_scan.get("own_count", 0) > 0 and \
                    t["answer_scan"]["own_count"] == 0 and mode != "off":
                raw_vs_delivered.append({
                    "label": t["label"], "mode": mode,
                    "raw_words": raw_scan.get("own_words"),
                    "delivered_len": len(t.get("answer") or "")})
    checks["raw_vs_delivered_profanity_removed"] = raw_vs_delivered
    return {
        "now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "wave_start_epoch": wave_start,
        "turns_used": turns_used, "hedges": hedges,
        "criteria": crit, "checks": checks, "diag_events": diag[:200],
        "live_check": lc, "routes": {
            "authorial": (routes.get("authorial") or {}),
            "initiative": {k: v for k, v in (routes.get("initiative") or {}
                                             ).items()
                           if k in ("correlation_id", "reply_len")}},
        "usage_totals": None,
    }


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("ACC96 FATAL | %s: %s" % (type(exc).__name__, str(exc)[:400]),
              flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("ACC96 RC=%d" % rc, flush=True)
    os._exit(rc)
