# -*- coding: utf-8 -*-
"""SOUL-14.0 A/B — восстановление после аварии провайдера (21.10.2026).

Во время W2 apinet.cloud отдавал 500/503 волнами. Два прогона одной HEAD-
копии (запуск мёртвой сессии ~21:17, завершён 21:32 -> сохранён владельцем
кероса как results-run1-outage.json; запуск этой сессии 21:27-21:36 ->
results.json) дали ВЗАИМНО ДОПОЛНЯЮЩИЕСЯ успешные слоты (0 пересечений:
одновременные клиенты на троттлинг-ящем провайдере). Слияние спасает
оплаченную работу обоих прогонов без новых вызовов.

Метод (честно фиксируется в capture.merge_note):
  - на каждый слот (scene, arm) берётся непустой ответ; при непустых в обоих
    прогонах предпочтение парной согласованности: пара целиком из run2,
    иначе пара целиком из run1, иначе слот из любого (run1 приоритет) —
    смешанные пары считаются и документируются;
  - провенанс каждой записи: "src_run": 1|2;
  - отпечатки HEAD-копии обоих прогонов обязаны совпасть (иначе abort);
  - capture = скелет run2 + merged runs; кумулятивный расход ведётся в
    spend-ledger.json (вызовы-инвокации vs оплаченные генерации: 5xx не
    биллятся).

Режимы:
  merge   — слить два прогона -> results.json + results-partial.jsonl
            (только непустые записи: заполение дыр через resume-харнес);
  ledger  — дописать факт прогона в spend-ledger.json (инвокации/успехи).

TEST-LIFECYCLE: PROVISIONAL owner=SOUL-14.0 (evidence-стадия; не тест)
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
EVID = HERE.parent
LEDGER = EVID / "spend-ledger.json"


def load(name: str) -> dict:
    return json.loads((EVID / name).read_text(encoding="utf-8"))


def stage_merge() -> int:
    r1, r2 = load("results-run1-outage.json"), load("results.json")
    if r1["head_fingerprints"] != r2["head_fingerprints"]:
        print("AB merge | FATAL: head fingerprints drift between runs")
        return 3
    if r1["model"] != r2["model"] or r1["temperature"] != r2["temperature"]:
        print("AB merge | FATAL: model/temperature mismatch")
        return 3
    by1 = {(r["scene_id"], r["arm"]): r for r in r1["runs"]}
    by2 = {(r["scene_id"], r["arm"]): r for r in r2["runs"]}
    if set(by1) != set(by2):
        print("AB merge | FATAL: slot sets differ")
        return 3
    merged: list[dict] = []
    mixed_pairs = 0
    for scene_id in sorted({k[0] for k in by1}):
        off1, on1 = by1[(scene_id, "off")], by1[(scene_id, "on")]
        off2, on2 = by2[(scene_id, "off")], by2[(scene_id, "on")]
        ok = lambda r: bool(r["reply"])  # noqa: E731
        if ok(off2) and ok(on2):
            picks = [("off", off2, 2), ("on", on2, 2)]
        elif ok(off1) and ok(on1):
            picks = [("off", off1, 1), ("on", on1, 1)]
        else:
            picks = []
            if ok(off1):
                picks.append(("off", off1, 1))
            elif ok(off2):
                picks.append(("off", off2, 2))
            if ok(on1):
                picks.append(("on", on1, 1))
            elif ok(on2):
                picks.append(("on", on2, 2))
        srcs = {s for _, _, s in picks}
        if len(srcs) > 1:
            mixed_pairs += 1
        for arm, rec, src in sorted(picks):
            out = dict(rec)
            out["src_run"] = src
            merged.append(out)
    ok_n = sum(1 for r in merged if r["reply"])
    missing = [k for k in sorted(by1) if not (by1[k]["reply"]
                                              or by2[k]["reply"])]
    capture = dict(r2)
    capture["runs"] = merged
    capture["merge_note"] = (
        "provider-outage recovery: run1 (dead-session launch, finished "
        "%s UTC, saved as results-run1-outage.json) + run2 (this session); "
        "disjoint ok-slots merged per-slot, pair-consistency preferred; "
        "src_run provenance per record; missing slots refilled via resume "
        "(results-partial.jsonl = non-empty union)") % r1["date_utc"]
    capture["merge_stats"] = {
        "run1_ok": sum(1 for r in r1["runs"] if r["reply"]),
        "run2_ok": sum(1 for r in r2["runs"] if r["reply"]),
        "union_ok": ok_n, "missing_slots": missing,
        "mixed_provenance_pairs": mixed_pairs,
        "fingerprint_equal": True,
    }
    (EVID / "results.json").write_text(
        json.dumps(capture, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    # partial для добора: только непустые записи (resume пропустит их)
    part = EVID / "results-partial.jsonl"
    lines = [json.dumps({"_meta": {
        "head_fingerprints": r2["head_fingerprints"],
        "model": r2["model"],
        "note": "recovery union; fill pass generates ONLY missing slots"
    }}, ensure_ascii=False)]
    for r in merged:
        if r["reply"]:
            lines.append(json.dumps(r, ensure_ascii=False))
    part.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("AB merge | union ok=%d/66 missing=%d mixed_pairs=%d -> "
          "results.json + partial(%d)" % (
              ok_n, len(missing), mixed_pairs, len(lines) - 1))
    return 0


def stage_ledger() -> int:
    """py ab_recover_merge.py ledger <invocations> <ok> <note>"""
    inv, ok, note = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    doc = (json.loads(LEDGER.read_text(encoding="utf-8"))
           if LEDGER.exists() else {
               "kind": "soul1_ab_spend_ledger",
               "note": "invocations = LLM generate() calls; billable = "
                       "successful generations (provider 5xx not billed)",
               "entries": []})
    doc["entries"].append({"invocations": inv, "billable": ok, "note": note})
    doc["totals"] = {
        "invocations": sum(e["invocations"] for e in doc["entries"]),
        "billable": sum(e["billable"] for e in doc["entries"])}
    LEDGER.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8", newline="\n")
    print("AB ledger | +%d inv / +%d billable | totals: %s" % (
        inv, ok, doc["totals"]))
    return 0


def _merge_union(sources: list[tuple[str, dict]], scene_ids: list[str]) -> tuple[list[dict], int]:
    """Общий union-мердж: на слот — непустой ответ, при полных парах из
    одного источника предпочтение парной согласованности; провенанс
    src_run = номер источника (1..n)."""
    by = [{(r["scene_id"], r["arm"]): r for r in cap["runs"] if r["reply"]}
          for _, cap in sources]
    merged: list[dict] = []
    mixed_pairs = 0
    for scene_id in scene_ids:
        picks: list[tuple[str, dict, int]] = []
        # 1) пара целиком из одного источника (первый по приоритету)
        pair_done = False
        for i, b in enumerate(by):
            if (scene_id, "off") in b and (scene_id, "on") in b:
                picks = [("off", b[(scene_id, "off")], i + 1),
                         ("on", b[(scene_id, "on")], i + 1)]
                pair_done = True
                break
        # 2) иначе — любой непустой по слотам
        if not pair_done:
            for arm in ("off", "on"):
                for i, b in enumerate(by):
                    if (scene_id, arm) in b:
                        picks.append((arm, b[(scene_id, arm)], i + 1))
                        break
        if len({s for _, _, s in picks}) > 1:
            mixed_pairs += 1
        for arm, rec, src in sorted(picks):
            out = dict(rec)
            out["src_run"] = src
            merged.append(out)
    return merged, mixed_pairs


def stage_merge3() -> int:
    """Аварийное восстановление: union трёх источников成功的 генераций.
    run1 = results-run1-outage.json (мёртвая сессия), pass1 = бэкап вывода
    fill-прохода 1 (там union run1+run2 с src_run), run3 = убитый
    дублирующий проход (healthy-окно, results-run3-killed-partial.jsonl)."""
    run1 = load("results-run1-outage.json")
    pass1 = load("results-run2-merged-backup.json")
    run3_lines = (EVID / "results-run3-killed-partial.jsonl").read_text(
        encoding="utf-8").splitlines()
    run3_recs = []
    for l in run3_lines[1:]:
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("reply"):
            r["src_run"] = 3
            run3_recs.append(r)
    run3 = {"runs": run3_recs, "head_fingerprints": pass1["head_fingerprints"],
            "model": pass1["model"], "temperature": pass1["temperature"],
            "date_utc": "killed-duplicate-pass (partial)"}
    sources = [("run1-dead-session", run1), ("pass1-union", pass1),
               ("run3-killed-pass", run3)]
    for _, cap in sources:
        if cap["head_fingerprints"] != pass1["head_fingerprints"]:
            print("AB merge3 | FATAL: fingerprint drift")
            return 3
    scene_ids = sorted({r["scene_id"] for r in pass1["runs"]})
    merged, mixed_pairs = _merge_union(sources, scene_ids)
    ok_n = sum(1 for r in merged if r["reply"])
    all_slots = {(s, a) for s in scene_ids for a in ("off", "on")}
    missing = sorted("%s:%s" % k for k in all_slots
                     if k not in {(r["scene_id"], r["arm"])
                                  for r in merged if r["reply"]})
    capture = dict(pass1)
    capture["runs"] = merged
    capture["date_utc"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    capture["merge_note"] = (
        "provider-outage recovery, 3 sources: run1 = dead-session launch "
        "(results-run1-outage.json), run2 = this-session launch (folded "
        "into pass1 union), run3 = killed duplicate pass (healthy window, "
        "results-run3-killed-partial.jsonl); per-slot union of non-empty "
        "replies, whole-pair single-source preferred, src_run provenance "
        "per record; remaining holes refilled via resume partial")
    capture["merge_stats"] = {
        "run1_ok": sum(1 for r in run1["runs"] if r["reply"]),
        "pass1_union_ok": sum(1 for r in pass1["runs"] if r["reply"]),
        "run3_ok": len(run3_recs),
        "union_ok": ok_n, "missing_slots": missing,
        "mixed_provenance_pairs": mixed_pairs,
        "fingerprint_equal": True,
    }
    (EVID / "results.json").write_text(
        json.dumps(capture, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    part = EVID / "results-partial.jsonl"
    lines = [json.dumps({"_meta": {
        "head_fingerprints": pass1["head_fingerprints"],
        "model": pass1["model"],
        "note": "post-merge3 union; fill pass generates ONLY missing slots"
    }}, ensure_ascii=False)]
    for r in merged:
        if r["reply"]:
            lines.append(json.dumps(r, ensure_ascii=False))
    part.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("AB merge3 | union ok=%d/66 missing=%s mixed_pairs=%d" % (
        ok_n, missing or "none", mixed_pairs))
    return 0


def main() -> int:
    stage = sys.argv[1] if len(sys.argv) > 1 else "merge"
    if stage == "merge":
        return stage_merge()
    if stage == "merge3":
        return stage_merge3()
    if stage == "ledger":
        return stage_ledger()
    print("unknown stage (merge|merge3|ledger)")
    return 4


if __name__ == "__main__":
    sys.exit(main())
