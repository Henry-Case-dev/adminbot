#!/usr/bin/env python3
"""Пересчёт R-09 live proof ТОЛЬКО по JSON — независимая проверка приёмки.

Читает `plans/features/remove-legacy-rephrasing/evidence/r09/r09-live-proof.json`
и заново считает всё, что можно пересчитать без повторного прогона:

* `other_char_delta` и `punct_only` — по полным текстам из `text_diff`;
* что ни один символ diff'а не скрыт (`hidden_chars`, длины span'ов);
* полноту diff-списка s5 (`truncated_ops`, `total_ops`);
* соответствие `forced` у s5 фактически отправленному `max_tokens`;
* наличие обязательных полей s3/s7 (`correlation_id`, `model`,
  `finish_reason`, `usage`, `http_calls`);
* что счётчик вызовов s7 равен фактическим HTTP-отправкам;
* фактические HTTP-статусы ног fallback у s4 (401);
* что у s6 6 операций и все `changed=false`;
* что транспорт Telegram подменён (ничего не отправлялось).

Запуск:
    py -3 tools/rlr_r09_verify.py [--map <path>] [--out <utf8 file>]

Код возврата: 0 — всё PASS, 1 — есть FAIL.
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MAP = os.path.join(
    "plans", "features", "remove-legacy-rephrasing", "evidence", "r09",
    "r09-live-proof.json")

#: Разрешённая пунктуационная нормализация (`owner_style_punctuation`):
#: длинное тире → дефис, «ёлочки» → прямые кавычки.
PUNCT = {"\u2014": "-", "\u00ab": '"', "\u00bb": '"'}


def _norm(text: str) -> str:
    for src, dst in PUNCT.items():
        text = text.replace(src, dst)
    return text


def _non_punct_delta(raw: str, sent: str) -> int:
    a, b = _norm(raw), sent
    if a == b:
        return 0
    delta = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            delta += max(i2 - i1, j2 - j1)
    return delta


def verify(data: dict) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, cond, detail: str = "") -> None:
        checks.append((name, bool(cond), detail))

    scenarios = data.get("scenarios") or {}
    for key in ("s1", "s2", "s3", "s4b", "s5", "s6"):
        v = scenarios.get(key)
        if v is None:
            check("%s: scenario present" % key, False)
            continue
        td = v["delivered"]["text_diff"]
        raw, sent = td["raw_text"], td["sent_text"]
        recomputed = _non_punct_delta(raw, sent)
        check("%s: other_char_delta recomputed from full texts" % key,
              recomputed == td["other_char_delta"],
              "%s == %s" % (recomputed, td["other_char_delta"]))
        check("%s: no hidden diff chars" % key,
              td["hidden_chars"] == 0
              and len(td["removed_span"]) == (td.get("removed_chars") or 0)
              and len(td["added_span"]) == (td.get("added_chars") or 0)
              and td["truncated"] is False,
              "removed %s/%s, added %s/%s" % (
                  len(td["removed_span"]), td.get("removed_chars"),
                  len(td["added_span"]), td.get("added_chars")))
        if key == "s3":
            # У инициативы нет turn_trace → сравнивать digest не с чем.
            check("s3: no trace digest (not comparable, not a mismatch)",
                  v["raw_final"]["digest_trace"] is None
                  and v["delivered"]["written_equals_sent"] is True,
                  "digest_trace=%s" % v["raw_final"]["digest_trace"])
        else:
            check("%s: author digest equals trace digest" % key,
                  v["raw_final"]["digest_agrees"] is True,
                  "%s vs %s" % (v["raw_final"]["digest_runner"],
                                v["raw_final"]["digest_trace"]))
        if key in ("s1", "s2", "s4b", "s5"):
            check("%s: divergence is punctuation-only" % key,
                  td["punct_only"] is True and td["other_char_delta"] == 0)

    s5 = scenarios.get("s5") or {}
    td5 = (s5.get("delivered") or {}).get("text_diff") or {}
    diff_ops = td5.get("diff_ops") or {}
    check("s5: full text stored (not a fragment)",
          len(td5.get("raw_text") or "") == td5.get("raw_chars")
          == (s5.get("raw_final") or {}).get("chars")
          and len(td5.get("sent_text") or "") == td5.get("sent_chars"),
          "raw %s, sent %s" % (len(td5.get("raw_text") or ""),
                               len(td5.get("sent_text") or "")))
    check("s5: whole diff list without truncation",
          diff_ops.get("truncated_ops") is False
          and diff_ops.get("total_ops") == len(diff_ops.get("ops") or ()),
          "ops=%s" % diff_ops.get("total_ops"))
    check("s5: other_char_delta = 0 on the full text",
          td5.get("other_char_delta") == 0, str(td5.get("other_char_delta")))
    forced = s5.get("forced") or {}
    check("s5: forced matches reality (env/sent/http bodies)",
          forced.get("env_DIRECT_LONGFORM_MAX_OUTPUT_TOKENS") == 120
          and forced.get("max_tokens_sent") == 120
          and 120 in (forced.get("max_tokens_in_http_calls") or ()),
          json.dumps(forced, ensure_ascii=False))
    check("s5: continuation really happened",
          (s5.get("continuation_calls") or 0) >= 1
          and s5.get("finish_reason") == "length",
          "continuation_calls=%s" % s5.get("continuation_calls"))

    s3 = scenarios.get("s3") or {}
    for field in ("correlation_id", "model", "provider", "finish_reason",
                  "usage", "http_calls"):
        check("s3: field %s filled" % field,
              s3.get(field) not in (None, "", []), str(s3.get(field))[:60])
    check("s3: http_calls carry real 200 statuses",
          [c.get("http_status") for c in (s3.get("http_calls") or ())]
          == [200, 200],
          str([c.get("http_status") for c in (s3.get("http_calls") or ())]))
    check("s3: text delivered byte-for-byte",
          (s3.get("delivered") or {}).get("written_equals_sent") is True)

    s7 = scenarios.get("s7") or {}
    for field in ("model", "usage_total", "finish_reasons", "llm_calls_total",
                  "http_calls"):
        check("s7: field %s filled" % field,
              s7.get(field) not in (None, "", []), str(s7.get(field))[:60])
    calls = s7.get("http_calls") or ()
    check("s7: call counter equals real HTTP sends",
          s7.get("llm_calls_total") == len(calls) == 2,
          "%s vs %s" % (s7.get("llm_calls_total"), len(calls)))
    check("s7: every call has status 200 and usage",
          all(c.get("http_status") == 200 and isinstance(c.get("usage"), dict)
              for c in calls))
    check("s7: correlation_id null with explicit reason",
          s7.get("correlation_id") is None
          and bool(s7.get("correlation_id_note")))

    s4 = scenarios.get("s4") or {}
    leg = s4.get("fallback_leg") or {}
    check("s4: fallback leg really answered 401",
          leg.get("fallback_statuses") == [401, 401],
          json.dumps(leg, ensure_ascii=False))
    check("s4: no author text existed",
          (s4.get("raw_final") or {}).get("chars") == 0)

    s6 = scenarios.get("s6") or {}
    ops = s6.get("ops") or ()
    check("s6: six ops, all changed=false",
          len(ops) == 6 and all(o.get("changed") is False for o in ops),
          ",".join("%s=%s" % (o.get("op"), o.get("changed")) for o in ops))
    check("s6: text delivered unchanged",
          (s6.get("delivered") or {}).get("written_equals_sent") is True)
    check("s6: model itself set preserve_source_facts",
          (s6.get("l1_plan_fields") or {}).get("preserve_source_facts") is True)

    meta = data.get("meta") or {}
    check("meta: Telegram transport stubbed",
          "stubbed" in str(meta.get("telegram_send", "")),
          str(meta.get("telegram_send")))
    check("meta: runner sha and clean worktree recorded",
          bool(meta.get("runner_sha256"))
          and meta.get("worktree_dirty") is False,
          "%s / dirty=%s" % (str(meta.get("runner_sha256"))[:16],
                             meta.get("worktree_dirty")))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", default=DEFAULT_MAP)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    path = args.map if os.path.isabs(args.map) else os.path.join(REPO, args.map)
    with io.open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    checks = verify(data)
    passed = sum(1 for _, cond, _ in checks if cond)
    failed = [c for c in checks if not c[1]]

    lines = [("%s %s%s" % ("PASS" if cond else "FAIL", name,
                           " | " + detail if detail else ""))
             for name, cond, detail in checks]
    lines.append("")
    lines.append("RESULT: %d/%d PASS" % (passed, len(checks)))
    text = "\n".join(lines)

    if args.out:
        with io.open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
