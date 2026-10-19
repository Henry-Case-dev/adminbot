# -*- coding: utf-8 -*-
"""Self-test (PROVISIONAL, scratch only) of ACCEPTANCE-97 scanner + criteria.

Feeds synthetic turn data through the real `scan_own`, `sentence_stats` and
`build_summary` so the verdict math is proven before the paid live wave.
"""
from __future__ import annotations

import importlib.util
import sys


def load():
    spec = importlib.util.spec_from_file_location(
        "acc97", r"C:\Users\main\AppData\Local\Temp\opencode\__none__.py")
    # real path is passed via argv
    path = sys.argv[1]
    spec = importlib.util.spec_from_file_location("acc97", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def turn(M, label, context, answer, status="ok"):
    return {
        "label": label, "chat_id": -1, "mode": "x", "context": context,
        "phrase": "p", "status": status, "error": "", "correlation_id": "c",
        "elapsed_s": 1.0, "plan_meta": {}, "sends": [], "answer": answer,
        "answer_sha12": M.sha12(answer), "answer_scan": M.scan_own(answer),
        "sentences": M.sentence_stats(answer), "raw": answer,
        "raw_sha12": M.sha12(answer), "raw_scan": M.scan_own(answer),
        "raw_eq_delivered": True, "llm_calls": [
            {"step": "l2_writer", "has_marker": True,
             "system_text": "<Expression_Settings> x"},
        ],
        "wire": [{"seq": 1, "has_marker": True, "has_examples_marker": False,
                  "mode_line": "frequent", "modes_in_system": ["frequent"],
                  "matched_text_modes": ["frequent"]}],
        "composes": [],
    }


def empty_wave(M, mode):
    return {"wave": mode, "mode": mode, "chat_id": -1,
            "switch": {"write_http": 200, "preview_eq_resolve": True,
                       "resolved": {"text": "T-%s" % mode, "revision": "r"},
                       "reread": {"body": {"effective": {"profanity": {
                           "value": mode, "source": "chat"}}}}},
            "anchor_mid": 1, "turns": []}


def build(M, spec):
    waves = {m: empty_wave(M, m) for m in ("off", "occasional", "frequent")}
    waves["frequent"]["turns"] = [
        turn(M, "f%d" % i, ctx, ans) for i, (ctx, ans) in enumerate(
            spec["frequent"])]
    for t in waves["frequent"]["turns"]:
        for w in t["wire"]:
            w["mode_line"] = "frequent"
            w["matched_text_modes"] = ["frequent"]
    waves["occasional"]["turns"] = [
        turn(M, "o%d" % i, ctx, ans) for i, (ctx, ans) in enumerate(
            spec["occasional"])]
    for t in waves["occasional"]["turns"]:
        for w in t["wire"]:
            w["mode_line"] = "occasional"
            w["matched_text_modes"] = ["occasional"]
    waves["off"]["turns"] = [
        turn(M, "x%d" % i, ctx, ans) for i, (ctx, ans) in enumerate(
            spec["off"])]
    for t in waves["off"]["turns"]:
        for w in t["wire"]:
            w["mode_line"] = "off"
            w["matched_text_modes"] = ["off"]
    iso = {"view_a_while_b_off": {"body": {"effective": {"profanity": {
               "value": "frequent"}}}},
           "view_b_off": {"body": {"effective": {"profanity": {
               "value": "off"}}}}}
    restore = {"equal": {"a": {"keys_equal": True, "expr_equal": True},
                         "b": {"keys_equal": True, "expr_equal": True}},
               "chat_a": {"http": 200}, "chat_b": {"http": 200}}
    p0 = {"preview_eq_resolve_a": True, "wave_start_epoch": 1,
          "view_a": {"body": {"runtime_wired": True}},
          "expression_rows": [{"technique": "expression_register",
                               "owner_approved": 0, "n": 12}]}
    return M.build_summary(p0, waves, iso, restore, {"app_version": "2.58.97"})


def main() -> int:
    M = load()
    # 1) scanner sanity
    s = M.scan_own("Бля, ну ты и выдал. Пиздец просто.")
    assert s["own_count"] == 2, s
    st = M.sentence_stats("Бля, ну ты и выдал. Пиздец просто.")
    assert st["sentences"] == 2 and st["max_roots_in_sentence"] == 1, st
    st2 = M.sentence_stats("Бля, пиздец, хуйня какая-то.")
    assert st2["max_roots_in_sentence"] >= 2, st2
    q = M.scan_own("Петя написал: «ну и хуйня этот ваш рефакторинг, я устал»")
    assert q["own_count"] == 0 and q["protected_count"] == 1, q
    print("SCANNER OK own=%d protected=%d" % (s["own_count"], q["protected_count"]))

    # 2) GREEN matrix
    green = {
        "frequent": [
            ("banter", "Ну ты и оратор, бля. Куда тебе до техподдержки."),
            ("banter", "Совет хороший, но тариф ты выбрал хуёво."),
            ("argument", "С кэшем ты устроишь пиздец, а не оптимизацию."),
            ("argument", "Стиралку зови, нахуй ждать."),
            ("joke_short", "Отчёт? Бля, он тебя уже переписывает."),
            ("joke_short", "Выспался, хули."),
            ("genre_summary", "admin-bot, версия 2.58.97. Диск 71%, память "
                              "940 МБ, аптайм 6 дней."),
        ],
        "occasional": [
            ("everyday", "Соседу скажи, что сверлить в восемь — бля."),
            ("everyday", "Пароль от вайфая на наклейке роутера."),
            ("argument", "Дедлайн перенесли — работай."),
            ("everyday", "Курица с рисом, скучно но надёжно."),
            ("joke_short", "Извинись, это дешевле."),
            ("banter", "Кот победил, признай."),
            ("everyday", "Ноутбук чисти от пыли."),
            ("argument", "Удалёнка лучше, но не для всех."),
            ("joke_short", "Погода завтра — как повезёт."),
            ("banter", "Начни с первого пункта."),
        ],
        "off": [
            ("banter", "Виноват тот, кто сломал, а не тот, кто заметил."),
            ("joke_short", "Иди, там будет скучно."),
            ("genre_quote", "Петя написал: «ну и хуйня этот ваш "
                            "рефакторинг, я устал»"),
        ],
    }
    g = build(M, green)
    print("GREEN verdicts:", {k: g["criteria"][k]["verdict"]
                              for k in ("off", "occasional", "frequent")},
          "F4=", g["verdict"]["F4"], "wire_ok=", g["checks"]["wire_ok"],
          "examples=", g["checks"]["examples_marker_total"])
    assert g["criteria"]["frequent"]["verdict"] == "PASS", g["criteria"]["frequent"]
    assert g["criteria"]["occasional"]["verdict"] == "PASS", g["criteria"]["occasional"]
    assert g["criteria"]["off"]["verdict"] == "PASS", g["criteria"]["off"]
    assert g["criteria"]["frequent"]["summary"]["verdict"] == "PASS"
    assert g["verdict"]["F4"] == "PASS"

    # 3) RED matrices
    red = dict(green)
    red["occasional"] = [("everyday", "Соседу скажи вежливо.")] * 10
    r = build(M, red)
    assert r["criteria"]["occasional"]["verdict"] == "FAIL", r["criteria"]["occasional"]
    assert r["verdict"]["F4"] == "FAIL"

    red2 = dict(green)
    red2["frequent"] = [("banter", "Ну ты и оратор."),
                        ("banter", "Совет хороший."),
                        ("argument", "С кэшем сложнее."),
                        ("argument", "Стиралку зови."),
                        ("joke_short", "Отчёт сам себя не перепишет."),
                        ("joke_short", "Выспался."),
                        ("genre_summary", "admin-bot, версия 2.58.97. Диск "
                                          "71%, память 940 МБ, аптайм 6 дней.")]
    r2 = build(M, red2)
    assert r2["criteria"]["frequent"]["verdict"] == "FAIL", r2["criteria"]["frequent"]
    print("RED occasional:", r["criteria"]["occasional"]["conversational_with_mat"],
          "RED frequent:", r2["criteria"]["frequent"]["conversational_with_mat"])

    # 4) root-per-sentence violation blocks PASS
    red3 = dict(green)
    red3["frequent"] = list(green["frequent"])
    red3["frequent"][0] = ("banter", "Бля, пиздец, хуйня какая-то.")
    r3 = build(M, red3)
    assert r3["criteria"]["frequent"]["root_per_sentence_violations"], r3["criteria"]["frequent"]
    assert r3["criteria"]["frequent"]["verdict"] == "FAIL"
    print("ROOT_PER_SENTENCE OK")
    print("SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
