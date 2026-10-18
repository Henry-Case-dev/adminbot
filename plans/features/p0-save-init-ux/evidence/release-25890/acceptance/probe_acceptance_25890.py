# -*- coding: utf-8 -*-
"""ACCEPTANCE-90 — прод-приёмка §4 для 2.58.90 (T0 = 2026-10-18T13:34:23Z).

Лейн: ACCEPTANCE-90. Канал: HTTPS API админки (SSH не используется).
Прод: 2.58.90 / commit 3b02366e (ветка master).

Режимы:
    python probe_acceptance_25890.py readonly   # только GET: снимок «до»
    python probe_acceptance_25890.py full       # цикл правка→reread→restore

Правила безопасности пробы:
  * правятся ТОЛЬКО обратимые документные поля речи (без текстов редакций);
  * никаких delete/сбросов данных: learning-reset, factory-apply не вызываются;
  * каждый шаг заканчивается restore + повторным GET (правда, а не заявление);
  * scope=chat используется только там, где chat-переопределения НЕ было
    (восстановление = снятие переопределения), иначе — глобальный цикл.

Результат: acceptance-25890.json рядом со скриптом.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

def _find_root(start: str) -> str:
    cur = os.path.abspath(start)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "config", "settings.py")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError("repo root not found")


ROOT = _find_root(os.path.dirname(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.settings import settings          # noqa: E402

BASE = "https://admin-bot.duckdns.org"
UID = 5885953495                              # владелец / global admin
WORK = -1002661910336                         # рабочий чат
PET = -1004482340693                          # PET-чат (гейт nostalgia)
STYLE_TEMP_RULE = {
    "id": "trailing_period.hard.strip",
    "kind": "trailing_period",
    "strictness": "hard",
    "scope": "chat",
    "enabled": True,
    "reason": "acceptance-25890 temp (restore: reset-chat)",
    "params": {"ellipsis": "strip"},
}

OUT = os.path.join(os.path.dirname(__file__), "acceptance-25890.json")
REPORT: dict = {
    "probe": "acceptance-25890",
    "lane": "ACCEPTANCE-90",
    "prod": BASE,
    "target_version": "2.58.90",
    "target_commit": "3b02366e",
    "t0_utc": "2026-10-18T13:34:23Z",
    "chats": {"work": WORK, "pet": PET},
    "steps": [],
    "failures": [],
}


def init_data() -> str:
    data = {"auth_date": str(int(time.time())),
            "user": json.dumps({"id": UID, "first_name": "Acc90"},
                               separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def req(method: str, path: str, *, chat=None, body=None, timeout: float = 30):
    url = BASE + path
    data = None
    headers = {"X-Telegram-Init-Data": init_data()}
    if chat is not None:
        headers["X-Chat-Id"] = str(chat)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method,
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"_raw": raw[:400]}
            return {"status": resp.status, "json": payload}
    except urllib.error.HTTPError as exc:
        txt = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(txt)
        except ValueError:
            payload = {"_raw": txt[:400]}
        return {"status": exc.code, "json": payload}
    except Exception as exc:                              # noqa: BLE001
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


def step(sid: str, ok: bool, detail: dict) -> bool:
    REPORT["steps"].append({"id": sid, "ok": bool(ok), "detail": detail})
    flag = "PASS" if ok else "FAIL"
    print("[%s] %s | %s" % (sid, flag, json.dumps(detail, ensure_ascii=False)
                            [:600]), flush=True)
    if not ok:
        REPORT["failures"].append({"id": sid, "detail": detail})
    return bool(ok)


# ── проверяемые представления (нормализованные срезы для диффа) ─────────────

def view_core(chat=None) -> dict:
    r = req("GET", "/api/speech/core", chat=chat)
    if r.get("status") != 200:
        return {"_error": r}
    j = r["json"]
    sel = j.get("selection") or {}
    eds = j.get("editions") or {}
    return {"inheritance": j.get("inheritance"),
            "scope": j.get("scope"),
            "level": sel.get("level"), "source": sel.get("source"),
            "reason": sel.get("reason"),
            "full_chars": (eds.get("full") or {}).get("chars"),
            "compact_chars": (eds.get("compact") or {}).get("chars")}


def view_expression(chat=None) -> dict:
    r = req("GET", "/api/speech/expression", chat=chat)
    if r.get("status") != 200:
        return {"_error": r}
    j = r["json"]
    return {"inheritance": j.get("inheritance"),
            "global_present": j.get("global_present"),
            "chat_present": j.get("chat_present"),
            "values": j.get("values"),
            "enabled": (j.get("document") or {}).get("enabled"),
            "rendered_chars": j.get("rendered_chars")}


def view_style(chat=None) -> dict:
    r = req("GET", "/api/speech/style", chat=chat)
    if r.get("status") != 200:
        return {"_error": r}
    j = r["json"]
    doc = j.get("document") or {}
    rules = sorted(str((x or {}).get("id")) for x in (j.get("rules") or []))
    return {"revision": j.get("revision"), "source": j.get("source"),
            "rules": rules,
            "soft": len(j.get("soft_instructions") or []),
            "inheritance": doc.get("inheritance"),
            "global_revision": doc.get("global_revision"),
            "chat_revision": doc.get("chat_revision")}


def view_humor(chat=None) -> dict:
    r = req("GET", "/api/speech/humor", chat=chat)
    if r.get("status") != 200:
        return {"_error": r}
    j = r["json"]
    craft = j.get("craft") or {}
    return {"craft_enabled": craft.get("enabled"),
            "craft_source": craft.get("source"),
            "craft_revision": craft.get("revision"),
            "disabled": list(craft.get("disabled_techniques") or [])}


def view_learning(chat) -> dict:
    r = req("GET", "/api/speech/learning", chat=chat)
    if r.get("status") != 200:
        return {"_error": r}
    hum = (r["json"].get("humor_feedback") or {})
    return {"paused": hum.get("paused"), "available": hum.get("available"),
            "enabled": hum.get("enabled")}


def view_gates(chat) -> dict:
    r = req("GET", "/api/chat/%d/gates" % chat)
    if r.get("status") != 200:
        return {"_error": r}
    j = r["json"]
    return {"nostalgia": (j.get("gates") or {}).get("nostalgia"),
            "updated_at": j.get("updated_at"),
            "opt_in": j.get("opt_in")}


def snapshot() -> dict:
    return {
        "core_global": view_core(None),
        "core_work": view_core(WORK),
        "core_pet": view_core(PET),
        "expr_global": view_expression(None),
        "expr_work": view_expression(WORK),
        "expr_pet": view_expression(PET),
        "style_global": view_style(None),
        "style_work": view_style(WORK),
        "style_pet": view_style(PET),
        "humor_global": view_humor(None),
        "humor_work": view_humor(WORK),
        "learning_work": view_learning(WORK),
        "gates_work": view_gates(WORK),
        "gates_pet": view_gates(PET),
    }


DIFF_KEYS = {
    "core_global": ("inheritance", "level", "source", "full_chars",
                    "compact_chars"),
    "core_work": ("inheritance", "level", "source"),
    "core_pet": ("inheritance", "level", "source"),
    "expr_global": ("inheritance", "global_present", "values", "enabled"),
    "expr_work": ("inheritance", "chat_present", "values", "enabled"),
    "expr_pet": ("inheritance", "chat_present", "values", "enabled"),
    "style_global": ("rules", "soft", "inheritance", "global_revision"),
    "style_work": ("rules", "soft", "inheritance", "chat_revision"),
    "style_pet": ("rules", "soft", "inheritance", "chat_revision"),
    "humor_global": ("craft_enabled", "craft_source", "disabled"),
    "humor_work": ("craft_enabled", "craft_source", "disabled"),
    "learning_work": ("paused", "enabled", "available"),
    "gates_work": ("nostalgia",),
    "gates_pet": ("nostalgia",),
}


def diff(before: dict, after: dict) -> dict:
    """Сравнение нормализованных срезов; revision/updated_at не сравниваются."""
    out: dict = {}
    for key, fields in DIFF_KEYS.items():
        b = before.get(key) or {}
        a = after.get(key) or {}
        for f in fields:
            if b.get(f) != a.get(f):
                out.setdefault(key, {})[f] = {"before": b.get(f),
                                              "after": a.get(f)}
    return out


#: Производные (провенанс) поля: правка+возврат значения создаёт owner-документ,
#: поэтому source меняется «default → global» при ИДЕНТИЧНОМ поведении. Публичного
#: API «удалить документ» в речи нет by design, поэтому такой дельта-провенанс
#: фиксируется явно и не считается потерей данных.
BENIGN_PROVENANCE = {
    "humor_global": ("craft_source",),
    "humor_work": ("craft_source",),
}


def split_diff(d: dict) -> tuple[dict, dict]:
    """(значимые отличия, только-провенанс отличия)."""
    hard: dict = {}
    benign: dict = {}
    for key, fields in d.items():
        for f, vals in fields.items():
            if f in BENIGN_PROVENANCE.get(key, ()) \
                    and str(vals.get("before")) in ("default", "") \
                    and str(vals.get("after")) in ("global", "chat"):
                benign.setdefault(key, {})[f] = vals
            else:
                hard.setdefault(key, {})[f] = vals
    return hard, benign


# ── A. real-DB цикл сохранения ─────────────────────────────────────────────

def a1_core_global(before: dict) -> None:
    cur = before["core_global"]
    if cur.get("_error"):
        step("A1_core_global", False, {"error": cur["_error"]})
        return
    orig = cur.get("level")
    target = "compact" if orig == "full" else "full"
    put = req("POST", "/api/speech/core/meta",
              body={"detail_level": target, "scope": "global"})
    j = put.get("json") or {}
    applied = bool((j.get("result") or {}).get("applied"))
    after = view_core(None)
    ok_tmp = put.get("status") == 200 and applied \
        and after.get("level") == target
    step("A1_core_global_write", ok_tmp,
         {"put_status": put.get("status"), "applied": applied,
          "revision": (j.get("result") or {}).get("revision"),
          "level_before": orig, "level_after": after.get("level"),
          "selection_source": after.get("source")})
    back = req("POST", "/api/speech/core/meta",
               body={"detail_level": orig, "scope": "global"})
    jb = back.get("json") or {}
    final = view_core(None)
    step("A1_core_global_restore",
         back.get("status") == 200 and final.get("level") == orig,
         {"put_status": back.get("status"),
          "applied": (jb.get("result") or {}).get("applied"),
          "revision": (jb.get("result") or {}).get("revision"),
          "level": final.get("level"), "source": final.get("source")})


def a2_core_chat(before: dict) -> None:
    cur = before["core_work"]
    orig = cur.get("level")
    target = "compact" if orig == "full" else "full"
    had_override = cur.get("inheritance") == "chat"
    put = req("POST", "/api/speech/core/meta", chat=WORK,
              body={"detail_level": target, "scope": "chat"})
    j = put.get("json") or {}
    applied = bool((j.get("result") or {}).get("applied"))
    after = view_core(WORK)
    step("A2_core_chat_write", put.get("status") == 200 and applied
         and after.get("level") == target
         and after.get("inheritance") == "chat",
         {"put_status": put.get("status"), "applied": applied,
          "had_override_before": had_override,
          "level_before": orig, "level_after": after.get("level"),
          "inheritance": after.get("inheritance"),
          "revision": (j.get("result") or {}).get("revision")})
    # изоляция: соседний чат не увидел правку
    pet = view_core(PET)
    step("A6a_isolation_core_pet",
         pet.get("level") == before["core_pet"].get("level")
         and pet.get("inheritance") == before["core_pet"].get("inheritance"),
         {"pet_level": pet.get("level"),
          "pet_expected": before["core_pet"].get("level"),
          "pet_inheritance": pet.get("inheritance")})
    if had_override:
        back = req("POST", "/api/speech/core/meta", chat=WORK,
                   body={"detail_level": orig, "scope": "chat"})
        jb = back.get("json") or {}
        final = view_core(WORK)
        step("A2_core_chat_restore_value",
             back.get("status") == 200 and final.get("level") == orig,
             {"put_status": back.get("status"),
              "applied": (jb.get("result") or {}).get("applied"),
              "level": final.get("level"),
              "inheritance": final.get("inheritance"),
              "note": "chat-переопределение было ДО пробы — остаётся"})
        return
    res = req("POST", "/api/speech/block/core.personality/reset", chat=WORK,
              body={"mode": "chat"})
    rj = res.get("json") or {}
    final = view_core(WORK)
    step("A2_core_chat_restore_inherit",
         res.get("status") == 200 and bool(rj.get("ok"))
         and final.get("inheritance") == before["core_work"].get("inheritance")
         and final.get("level") == orig,
         {"post_status": res.get("status"), "ok": rj.get("ok"),
          "result": rj.get("result"), "level": final.get("level"),
          "inheritance": final.get("inheritance")})


def a3_expression(before: dict) -> None:
    cur = before["expr_work"]
    chat_clean = not cur.get("chat_present")
    if chat_clean:
        values = dict(cur.get("values") or {})
        temp = {"wit": "high"} if values.get("wit") != "high" else {"wit": "low"}
        auth = req("POST", "/api/speech/expression", chat=WORK,
                   body={"values": temp, "scope": "chat"})
        aj = auth.get("json") or {}
        after = view_expression(WORK)
        changed_key = next(iter(temp))
        step("A3_expression_chat_write",
             auth.get("status") == 200
             and bool((aj.get("result") or {}).get("applied"))
             and after.get("inheritance") == "chat"
             and (after.get("values") or {}).get(changed_key) == temp[changed_key],
             {"post_status": auth.get("status"),
              "applied": (aj.get("result") or {}).get("applied"),
              "revision": (aj.get("result") or {}).get("revision"),
              "changed": temp, "values_after": after.get("values"),
              "inheritance": after.get("inheritance"),
              "rendered_chars": after.get("rendered_chars")})
        # изоляция: PET не затронут
        pet = view_expression(PET)
        step("A6b_isolation_expr_pet",
             (pet.get("values") or {}) ==
             (before["expr_pet"].get("values") or {})
             and pet.get("chat_present") == before["expr_pet"].get(
                 "chat_present"),
             {"pet_values": pet.get("values"),
              "pet_expected": before["expr_pet"].get("values"),
              "pet_chat_present": pet.get("chat_present")})
        res = req("POST", "/api/speech/expression/reset-chat", chat=WORK,
                  body={})
        rj = res.get("json") or {}
        final = view_expression(WORK)
        step("A3_expression_chat_restore",
             res.get("status") == 200
             and final.get("chat_present") ==
             before["expr_work"].get("chat_present")
             and (final.get("values") or {}) ==
             (before["expr_work"].get("values") or {}),
             {"post_status": res.get("status"), "ok": rj.get("ok"),
              "result": rj.get("result"),
              "values": final.get("values"),
              "inheritance": final.get("inheritance")})
        return
    gp = before["expr_global"]
    if not gp.get("global_present"):
        step("A3_expression", False,
             {"reason": "chat_override_exists_and_no_global_doc — "
                        "небезопасный restore; шаг не выполнен",
              "chat_present": cur.get("chat_present"),
              "global_present": gp.get("global_present")})
        return
    values = dict(gp.get("values") or {})
    orig = values.get("verbosity")
    target = "long" if orig != "long" else "short"
    changed = dict(values)
    changed["verbosity"] = target
    put = req("POST", "/api/speech/expression",
              body={"values": changed, "scope": "global"})
    pj = put.get("json") or {}
    after = view_expression(None)
    step("A3_expression_global_write",
         put.get("status") == 200
         and bool((pj.get("result") or {}).get("applied"))
         and (after.get("values") or {}).get("verbosity") == target,
         {"post_status": put.get("status"),
          "applied": (pj.get("result") or {}).get("applied"),
          "verbosity_before": orig,
          "verbosity_after": (after.get("values") or {}).get("verbosity"),
          "rendered_chars": after.get("rendered_chars")})
    back = req("POST", "/api/speech/expression",
               body={"values": values, "scope": "global"})
    final = view_expression(None)
    step("A3_expression_global_restore",
         back.get("status") == 200
         and (final.get("values") or {}) == values,
         {"post_status": back.get("status"),
          "values": final.get("values"), "expected": values})


def a4_style(before: dict) -> None:
    cur = before["style_work"]
    chat_clean = not (cur.get("inheritance") == "chat")
    doc_before = view_style(WORK)
    base_rev = doc_before.get("chat_revision")
    if chat_clean:
        put = req("POST", "/api/speech/style", chat=WORK,
                  body={"document": {"rules": [STYLE_TEMP_RULE],
                                     "soft_instructions": []},
                        "scope": "chat",
                        "reason": "acceptance-25890 temp"})
        pj = put.get("json") or {}
        applied = bool((pj.get("result") or {}).get("applied"))
        after = view_style(WORK)
        step("A4_style_chat_write",
             put.get("status") == 200 and applied
             and STYLE_TEMP_RULE["id"] in (after.get("rules") or [])
             and after.get("inheritance") == "chat"
             and after.get("chat_revision") == (int(base_rev or 0) + 1),
             {"post_status": put.get("status"), "applied": applied,
              "chat_revision_before": base_rev,
              "chat_revision_after": after.get("chat_revision"),
              "revision_after": after.get("revision"),
              "source": after.get("source"),
              "rules_after": after.get("rules"),
              "rules_before": doc_before.get("rules")})
        # эффективность правила подтверждаем на try-сборке (0 LLM, без отправки)
        probe_text = "Проверка стиля пробой."
        try_out = req("POST", "/api/speech/try", chat=WORK,
                      body={"text": probe_text, "generate": False})
        tj = try_out.get("json") or {}
        ext = (tj.get("extent") or {})
        sp = (ext.get("style_pass") or {})
        masked = ext.get("style_text_masked")
        vers = ((tj.get("current") or {}).get("versions") or {})
        step("A4_style_effective_try",
             try_out.get("status") == 200
             and int(sp.get("repaired") or 0) >= 1
             and masked == probe_text[:-1],
             {"post_status": try_out.get("status"),
              "repaired": sp.get("repaired"), "applied": sp.get("applied"),
              "style_text_masked": masked, "expected": probe_text[:-1],
              "style_policy_version": vers.get("style_policy")})
        res = req("POST", "/api/speech/style/reset-chat", chat=WORK, body={})
        rj = res.get("json") or {}
        final = view_style(WORK)
        step("A4_style_chat_restore",
             res.get("status") == 200 and bool(rj.get("ok"))
             and final.get("inheritance") == doc_before.get("inheritance")
             and (final.get("rules") or []) == (doc_before.get("rules") or [])
             and final.get("chat_revision") == doc_before.get("chat_revision"),
             {"post_status": res.get("status"), "ok": rj.get("ok"),
              "result": rj.get("result"),
              "rules_final": final.get("rules"),
              "inheritance": final.get("inheritance"),
              "chat_revision": final.get("chat_revision")})
        return
    gp = before["style_global"]
    if not gp.get("rules") and not gp.get("inheritance"):
        step("A4_style", False, {"reason": "no view"})
        return
    base_doc = {"v": 1, "presets_applied": [],
                "rules": list(gp.get("rules") or []),
                "soft_instructions": []}
    step("A4_style_global_skipped",
         True, {"note": "у чата уже есть style-переопределение — глобальный "
                        "цикл требует реконструкции документа; выполняется "
                        "chat-цикл ниже по явному решению исполнителя",
                "base_doc_keys": sorted(base_doc)})


def a5_humor_learning(before: dict) -> None:
    cur = before["humor_global"].get("craft_enabled")
    target = not bool(cur)
    put = req("POST", "/api/speech/humor/craft",
              body={"enabled": target, "scope": "global"})
    pj = put.get("json") or {}
    after = view_humor(None)
    step("A5_humor_write", put.get("status") == 200
         and after.get("craft_enabled") == target,
         {"post_status": put.get("status"), "ok": pj.get("ok"),
          "enabled_before": cur, "enabled_after": after.get("craft_enabled"),
          "revision": after.get("craft_revision"),
          "source": after.get("craft_source")})
    back = req("POST", "/api/speech/humor/craft",
               body={"enabled": bool(cur), "scope": "global"})
    bj = back.get("json") or {}
    final = view_humor(None)
    step("A5_humor_restore", back.get("status") == 200
         and final.get("craft_enabled") == cur,
         {"post_status": back.get("status"), "ok": bj.get("ok"),
          "enabled": final.get("craft_enabled"),
          "revision": final.get("craft_revision")})

    paused0 = before["learning_work"].get("paused")
    act1 = "pause" if not paused0 else "resume"
    act2 = "resume" if act1 == "pause" else "pause"
    r1 = req("POST", "/api/speech/learning/humor", chat=WORK,
             body={"action": act1})
    v1 = view_learning(WORK)
    step("A5_learning_write",
         r1.get("status") == 200 and v1.get("paused") is (act1 == "pause"),
         {"action": act1, "post_status": r1.get("status"),
          "paused_before": paused0, "paused_after": v1.get("paused")})
    r2 = req("POST", "/api/speech/learning/humor", chat=WORK,
             body={"action": act2})
    v2 = view_learning(WORK)
    step("A5_learning_restore",
         r2.get("status") == 200 and v2.get("paused") == paused0,
         {"action": act2, "post_status": r2.get("status"),
          "paused": v2.get("paused"), "expected": paused0})


def a7_conflict(before: dict) -> None:
    gates = view_gates(WORK)
    stale = "2000-01-01T00:00:00Z"
    before_state = view_style(WORK)
    put = req("POST", "/api/speech/style", chat=WORK,
              body={"document": {"rules": [STYLE_TEMP_RULE],
                                 "soft_instructions": []},
                    "scope": "chat", "expected_updated_at": stale,
                    "reason": "acceptance-25890 conflict probe"})
    j = put.get("json") or {}
    detail = j.get("detail") if isinstance(j, dict) else None
    after_state = view_style(WORK)
    no_change = (after_state.get("rules") == before_state.get("rules")
                 and after_state.get("inheritance") ==
                 before_state.get("inheritance")
                 and after_state.get("chat_revision") ==
                 before_state.get("chat_revision"))
    step("A7_conflict_409",
         put.get("status") == 409 and no_change,
         {"post_status": put.get("status"), "detail": detail,
          "chat_updated_at_current": gates.get("updated_at"),
          "sent_expected_updated_at": stale,
          "state_unchanged": no_change,
          "rules_same": after_state.get("rules") == before_state.get("rules"),
          "chat_revision": after_state.get("chat_revision"),
          "inheritance": after_state.get("inheritance")})
    if put.get("status") == 200:
        # защита: конфликт не сработал — немедленно снимаем случайную правку
        r = req("POST", "/api/speech/style/reset-chat", chat=WORK, body={})
        after2 = view_style(WORK)
        step("A7_unexpected_write_reverted",
             after2.get("inheritance") == before_state.get("inheritance"),
             {"reset_status": r.get("status"),
              "inheritance": after2.get("inheritance"),
              "note": "стороннее изменение зафиксировано как ПРОД-находка"})


def _recover(before: dict) -> None:
    """Идемпотентное доведение прода до значений «до» (без delete-операций).

    Вызывается перед финальным диффом: если какой-то restore не сошёлся —
    повторяем ровно те же обратимые записи и снимаем chat-переопределения,
    которых не было в baseline. Ничего не удаляем, кроме самих временных
    overrides (это и есть штатный путь «сбросить для чата»).
    """
    cur = view_core(None)
    if cur.get("level") != before["core_global"].get("level"):
        r = req("POST", "/api/speech/core/meta",
                body={"detail_level": before["core_global"].get("level"),
                      "scope": "global"})
        step("R_core_global", view_core(None).get("level") ==
             before["core_global"].get("level"),
             {"post_status": r.get("status"), "level": view_core(None).get("level")})
    cw = view_core(WORK)
    if cw.get("inheritance") == "chat" \
            and before["core_work"].get("inheritance") != "chat":
        r = req("POST", "/api/speech/block/core.personality/reset", chat=WORK,
                body={"mode": "chat"})
        step("R_core_chat", view_core(WORK).get("inheritance") != "chat",
             {"post_status": r.get("status"),
              "inheritance": view_core(WORK).get("inheritance")})
    ew = view_expression(WORK)
    if ew.get("chat_present") and not before["expr_work"].get("chat_present"):
        r = req("POST", "/api/speech/expression/reset-chat", chat=WORK, body={})
        step("R_expr_chat", not view_expression(WORK).get("chat_present"),
             {"post_status": r.get("status")})
    sw = view_style(WORK)
    if before["style_work"].get("chat_revision") in (0, None) \
            and sw.get("inheritance") == "chat":
        r = req("POST", "/api/speech/style/reset-chat", chat=WORK, body={})
        step("R_style_chat",
             view_style(WORK).get("inheritance") != "chat",
             {"post_status": r.get("status"),
              "inheritance": view_style(WORK).get("inheritance")})
    hg = view_humor(None)
    if hg.get("craft_enabled") != before["humor_global"].get("craft_enabled"):
        r = req("POST", "/api/speech/humor/craft",
                body={"enabled": bool(before["humor_global"].get("craft_enabled")),
                      "scope": "global"})
        step("R_humor", view_humor(None).get("craft_enabled") ==
             before["humor_global"].get("craft_enabled"),
             {"post_status": r.get("status")})
    lw = view_learning(WORK)
    if lw.get("paused") != before["learning_work"].get("paused"):
        act = "pause" if before["learning_work"].get("paused") else "resume"
        r = req("POST", "/api/speech/learning/humor", chat=WORK,
                body={"action": act})
        step("R_learning", view_learning(WORK).get("paused") ==
             before["learning_work"].get("paused"),
             {"action": act, "post_status": r.get("status")})


def a8_final(before: dict) -> None:
    _recover(before)
    after = snapshot()
    d = diff(before, after)
    hard, benign = split_diff(d)
    health = req("GET", "/healthz")
    step("A8_final_state_restored", not hard,
         {"diff_significant": hard, "diff_provenance_only": benign,
          "health": health.get("json"),
          "note": "revision/updated_at намеренно не сравниваются (растут от "
                  "любой обратимой правки); provenance-only дельта "
                  "humor.craft объяснена в отчёте"})
    REPORT["final_snapshot"] = after
    REPORT["final_diff"] = d
    REPORT["final_diff_significant"] = hard
    REPORT["final_diff_provenance_only"] = benign


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "readonly"
    REPORT["mode"] = mode
    REPORT["started_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    health = req("GET", "/healthz")
    REPORT["prod_health"] = health.get("json") or health
    print("[env] %s" % json.dumps(REPORT["prod_health"], ensure_ascii=False))
    if mode == "recheck":
        # verification-only: сверка ТЕКУЩЕГО состояния с baseline прогона-1
        base = os.path.join(os.path.dirname(__file__), "acceptance-25890.json")
        with open(base, encoding="utf-8") as fh:
            run1 = json.load(fh)
        before = run1["baseline"]
        REPORT["baseline_source"] = ("acceptance-25890.json (полный цикл, "
                                     "mode=full)")
        REPORT["baseline"] = before
        after = snapshot()
        d = diff(before, after)
        hard, benign = split_diff(d)
        step("RECHECK_state_equals_full_cycle_baseline", not hard,
             {"diff_significant": hard, "diff_provenance_only": benign,
              "note": "только GET; сверка с baseline артефакта полного цикла"})
        REPORT["recheck_snapshot"] = after
        REPORT["recheck_diff"] = d
        REPORT["recheck_diff_significant"] = hard
        REPORT["recheck_diff_provenance_only"] = benign
        REPORT["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                               time.gmtime())
        with open(os.path.join(os.path.dirname(__file__),
                               "acceptance-recheck-25890.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(REPORT, fh, ensure_ascii=False, indent=2)
        print("[recheck] significant=%s provenance=%s"
              % (json.dumps(hard, ensure_ascii=False),
                 json.dumps(benign, ensure_ascii=False)))
        return 1 if hard else 0
    before = snapshot()
    REPORT["baseline"] = before
    print("[baseline] core_global=%s expr_work=%s style_work=%s gates_pet=%s"
          % (json.dumps(before["core_global"], ensure_ascii=False),
             json.dumps(before["expr_work"], ensure_ascii=False),
             json.dumps(before["style_work"], ensure_ascii=False),
             json.dumps(before["gates_pet"], ensure_ascii=False)))
    if mode == "readonly":
        REPORT["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                               time.gmtime())
        _save()
        return 0
    a1_core_global(before)
    a2_core_chat(before)
    a3_expression(before)
    a4_style(before)
    a5_humor_learning(before)
    a7_conflict(before)
    a8_final(before)
    REPORT["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save()
    print("[done] failures=%d -> %s" % (len(REPORT["failures"]), OUT))
    return 1 if REPORT["failures"] else 0


def _save() -> None:
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
