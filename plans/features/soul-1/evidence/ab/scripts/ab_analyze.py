# -*- coding: utf-8 -*-
"""SOUL-14.0 A/B — анализ: скриптовые метрики + слепые ручные оценки.

Вход: results.json + blind-scores.json (ручные, слепые) + private-mapping.json.
Скриптовые метрики ПЕРЕСЧИТЫВАЮТСЯ из захваченных сырых ответов независимо от
флагов стадии run (прецедент amd82-verdict-recheck: расхождение фиксируется).
Развейнинг — ПОСЛЕ загрузки ручных оценок, внутри этой стадии.

Выход: analysis.md + analysis-data.json + verdict-recheck.json.
Без LLM-судьи (acceptance запрещает вердикт по баллу судьи); итог —
ОПИСАТЕЛЬНАЯ сводка, «победа» по одному удачному случаю не объявляется.

TEST-LIFECYCLE: PROVISIONAL owner=SOUL-14.0 (evidence-стадия; не тест)
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
EVID = HERE.parent
sys.path.insert(0, str(HERE))
from ab_harness import (  # noqa: E402
    MANUAL_DIMS, MANUAL_DIMS_RU, PII_PATTERNS, scripted_flags)
import os
os.environ.setdefault("UNIFIED_COMPOSER_ENABLED", "1")


def norm_words(text: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", str(text or "").lower())


def ngrams(words: list[str], n: int = 3) -> set[str]:
    if len(words) < n:
        return set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def main() -> int:
    results = json.loads((EVID / "results.json").read_text(encoding="utf-8"))
    scores_doc = json.loads((EVID / "blind-scores.json").read_text(
        encoding="utf-8"))
    mapping = json.loads((EVID / "private-mapping.json").read_text(
        encoding="utf-8"))
    runs = results["runs"]
    by = {(r["scene_id"], r["arm"]): r for r in runs}
    # кумулятивная стоимость (fill-проходы через resume добирают пустые):
    calls_total = dict(results.get("calls_cumulative") or results["calls"])
    if "llm" not in calls_total and "invocations" in calls_total:
        calls_total["llm"] = calls_total["invocations"]
    billable = int(calls_total.get("llm_billable",
                                   calls_total.get("billable",
                                                   calls_total.get("llm", 0))
                                   ) or 0)

    # ── 1. recheck скриптовых метрик из сырых ответов ───────────────────────
    recheck_mismatch = []
    for r in runs:
        fresh = scripted_flags(r["reply"])
        if (fresh["profanity_hits"] != r["flags"]["profanity_hits"]
                or fresh["echo_marker_hit"] != r["flags"]["echo_marker_hit"]
                or fresh["prompt_leak_hits"] != r["flags"]["prompt_leak_hits"]
                or fresh["profanity_flood"] != r["flags"]["profanity_flood"]):
            recheck_mismatch.append(r["scene_id"] + ":" + r["arm"])
    for r in runs:
        for name, rx in PII_PATTERNS:
            if rx.search(r["reply"]):
                recheck_mismatch.append("PII_REPLY:%s:%s:%s" % (
                    r["scene_id"], r["arm"], name))
    recheck = {"kind": "soul1_ab_verdict_recheck",
               "method": "scripted flags recomputed from raw captured replies",
               "runs": len(runs), "mismatches": recheck_mismatch,
               "result": "OK" if not recheck_mismatch else "MISMATCH"}
    (EVID / "verdict-recheck.json").write_text(
        json.dumps(recheck, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")

    # ── 2. ручные слепые оценки -> развейнинг ───────────────────────────────
    wins = {arm: {d: 0 for d in MANUAL_DIMS} for arm in ("on", "off")}
    ties = {d: 0 for d in MANUAL_DIMS}
    quality_sum = {arm: {d: 0 for d in MANUAL_DIMS} for arm in ("on", "off")}
    notes = []
    for entry in scores_doc["pairs"]:
        mp = mapping["pairs"][entry["pair_id"]]
        arm_at = {"pos0": mp["pos0"], "pos1": mp["pos1"]}
        note = str(entry.get("note", "") or "").strip()
        for d in MANUAL_DIMS:
            v0 = int(entry["p0"].get(d, 0))
            v1 = int(entry["p1"].get(d, 0))
            if v0 > v1:
                wins[arm_at["pos0"]][d] += 1
            elif v1 > v0:
                wins[arm_at["pos1"]][d] += 1
            else:
                ties[d] += 1
            quality_sum[arm_at["pos0"]][d] += v0
            quality_sum[arm_at["pos1"]][d] += v1
        if note:
            notes.append({"pair_id": entry["pair_id"],
                          "scene": mp.get("scene_id", ""),
                          "note": note})
    n_pairs = len(scores_doc["pairs"])

    # ── 3. скриптовые сводки по рукам ───────────────────────────────────────
    arm_stats = {}
    for arm in ("on", "off"):
        rs = [r for r in runs if r["arm"] == arm]
        one_word = [r for r in rs if r["explicit_form"] == "one_word"]
        longform = [r for r in rs if r["explicit_form"] == "longform"]
        ow_exact = sum(1 for r in one_word
                       if r["extent_check"]["status"] == "pass")
        ow_repaired = sum(1 for r in one_word
                          if r["extent_check"]["status"] == "repaired")
        ow_fail = sum(1 for r in one_word
                      if r["extent_check"]["status"] in ("failed", "conflict"))
        lf_ok = sum(1 for r in longform
                    if r["extent_check"]["status"] in ("pass", "repaired",
                                                       "not_applicable"))
        # разнообразие: межсценовое 3-граммное перекрытие внутри типа
        type_overlap = []
        types = sorted({r["scene_type"] for r in rs})
        for t in types:
            trs = [r for r in rs if r["scene_type"] == t]
            for i in range(len(trs)):
                for j in range(i + 1, len(trs)):
                    type_overlap.append(jaccard(
                        ngrams(norm_words(trs[i]["reply"])),
                        ngrams(norm_words(trs[j]["reply"]))))
        openers = {}
        for r in rs:
            head = " ".join(norm_words(r["reply"])[:5])
            openers[head] = openers.get(head, 0) + 1
        arm_stats[arm] = {
            "runs": len(rs),
            "empty_replies": sum(1 for r in rs if not r["reply"]),
            "profanity_hits_total": sum(r["flags"]["profanity_hits"]
                                        for r in rs),
            "profanity_scenes": sum(1 for r in rs
                                    if r["flags"]["profanity_hits"] > 0),
            "profanity_flood_scenes": sum(1 for r in rs
                                          if r["flags"]["profanity_flood"]),
            "one_word": {"n": len(one_word), "exact_pass": ow_exact,
                         "repaired": ow_repaired, "failed": ow_fail},
            "longform": {"n": len(longform), "ok": lf_ok},
            "extent_violations": sum(
                1 for r in rs if r["explicit_form"] == ""
                and r["extent_check"]["status"] in ("failed", "conflict")),
            "injection": {
                "echo_marker_hit": sum(1 for r in rs
                                       if r["flags"]["echo_marker_hit"]),
                "prompt_leak_scenes": sorted(
                    r["scene_id"] for r in rs
                    if r["flags"]["prompt_leak_hits"]),
                "mat_flood_scenes": sorted(
                    r["scene_id"] for r in rs
                    if r["flags"]["profanity_flood"])},
            "diversity": {
                "mean_same_type_3gram_jaccard": round(
                    sum(type_overlap) / len(type_overlap), 4)
                    if type_overlap else None,
                "pairs_compared": len(type_overlap),
                "duplicate_openers": {k: v for k, v in openers.items()
                                      if v > 1},
                "duplicate_replies": sum(
                    1 for i in range(len(rs)) for j in range(i + 1, len(rs))
                    if rs[i]["reply_sha12"] == rs[j]["reply_sha12"])},
            "system": {"chars_mean": round(sum(r["system_chars"]
                                              for r in rs) / len(rs), 1),
                       "core_tokens_mean": round(sum(r["core_tokens"]
                                                     for r in rs) / len(rs), 1)
                           if any(r["core_tokens"] for r in rs) else 0},
        }

    # слои/сборка ON (манифесты обязательны)
    on_runs = [r for r in runs if r["arm"] == "on"]
    rendered = sorted({l for r in on_runs for l in r["rendered_layers"]})
    skips = {}
    for r in on_runs:
        for layer, reason in r["skip_reasons"].items():
            skips.setdefault(layer, {}).setdefault(reason or "-", 0)
            skips[layer][reason or "-"] += 1
    conflicts = sorted({c for r in on_runs for c in r["conflicts"]})
    expression_modes = sorted({r["expression_mode"] for r in on_runs
                               if r["expression_mode"]})
    build = {"on": {"rendered_layers": rendered, "skip_reasons": skips,
                    "conflicts": conflicts,
                    "expression_modes": expression_modes,
                    "core_detail": next((r["core_detail"] for r in on_runs
                                         if r["core_detail"]), ""),
                    "core_tokens_first": on_runs[0]["core_tokens"]},
            "off": {"composer_gate": "unified_composer_enabled=False "
                                     "(env-ось OFF, сборка "
                                     "compose_verbalizer_system + хвосты)"}}

    data = {
        "kind": "soul1_ab_analysis",
        "source_results_sha12_note": "results.json рядом",
        "seed": mapping["seed"], "pairs": n_pairs,
        "recheck": recheck["result"],
        "manual": {"wins": wins, "ties": ties,
                   "quality_mean": {arm: {
                       d: round(quality_sum[arm][d] / n_pairs, 2)
                       for d in MANUAL_DIMS} for arm in ("on", "off")}},
        "scripted": arm_stats, "build": build,
        "runs_meta": {"calls": calls_total,
                      "model": results["model"],
                      "temperature": results["temperature"],
                      "head_root_sha": results["head_root_sha"],
                      "empty_replies": results["empty_replies"],
                      "systems_equal": results["systems_equal"],
                      "character_block_chars":
                          results["character_block_chars"],
                      "character_block_error":
                          results["character_block_error"]},
        "notes": notes,
    }
    (EVID / "analysis-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")

    # ── 4. analysis.md ──────────────────────────────────────────────────────
    L = ["# SOUL-14.0/14.3 — слепой A/B-анализ: старая (OFF) vs новая (ON) "
         "композиция",
         "",
         "HEAD-копия: `%s` | модель: %s | temperature: %s | LLM-инвокаций: "
         "%d (оплачено генераций: %d, 5xx не биллятся) | пар: %d | seed: %s"
         % (
             results["head_root_sha"][:12], results["model"],
             results["temperature"], calls_total["llm"], billable, n_pairs,
             mapping["seed"]),
         "",
         "Процедура: пары и позиции рук перемешаны seeded-рандомом ДО разбора; "
         "ручные оценки записаны в `blind-scores.json` по слепым файлам; "
         "развейнинг — только внутри этой стадии (private-mapping.json). "
         "Скриптовые метрики пересчитаны из сырых ответов независимо "
         "(verdict-recheck: %s)." % recheck["result"],
         "",
         "## Ручные размерности (слепой разбор, 33 пары)",
         "",
         "| Размерность | ON лучше | OFF лучше | ничья | ON ср. | OFF ср. |",
         "|---|---|---|---|---|---|",
         ]
    for d in MANUAL_DIMS:
        L.append("| %s | %d | %d | %d | %s | %s |" % (
            MANUAL_DIMS_RU[d], wins["on"][d], wins["off"][d], ties[d],
            data["manual"]["quality_mean"]["on"][d],
            data["manual"]["quality_mean"]["off"][d]))
    L += ["",
          "## Скриптовые метрики (детерминированные, пересчёт из ответов)",
          "",
          "| Метрика | ON | OFF |",
          "|---|---|---|"]
    for key, label in (
            ("one_word exact pass", lambda s: "%d/%d" % (
                s["one_word"]["exact_pass"], s["one_word"]["n"])),
            ("one_word repaired", lambda s: "%d/%d" % (
                s["one_word"]["repaired"], s["one_word"]["n"])),
            ("one_word failed/conflict", lambda s: "%d/%d" % (
                s["one_word"]["failed"], s["one_word"]["n"])),
            ("longform ok", lambda s: "%d/%d" % (
                s["longform"]["ok"], s["longform"]["n"])),
            ("корней мата всего", lambda s: str(s["profanity_hits_total"])),
            ("сцен с матом", lambda s: str(s["profanity_scenes"])),
            ("мат-флуд (инъекция)", lambda s: str(
                s["injection"]["mat_flood_scenes"])),
            ("эхо-маркер инъекции", lambda s: str(
                s["injection"]["echo_marker_hit"])),
            ("утечка промпта", lambda s: str(
                s["injection"]["prompt_leak_scenes"])),
            ("3-граммное перекрытие (меньше = разнообразнее)", lambda s: str(
                s["diversity"]["mean_same_type_3gram_jaccard"])),
            ("дубли открытий", lambda s: str(
                len(s["diversity"]["duplicate_openers"]))),
            ("средняя длина system", lambda s: str(s["system"]["chars_mean"])),
            ):
        L.append("| %s | %s | %s |" % (key, label(arm_stats["on"]),
                                       label(arm_stats["off"])))
    L += ["",
          "## Сборка рук (манифесты)",
          "",
          "ON rendered-слои: %s" % ", ".join(rendered),
          "Core: %s (токенов в первом ходе: %d)" % (
              build["on"]["core_detail"], build["on"]["core_tokens_first"]),
          "ON skip-причины: %s" % json.dumps(skips, ensure_ascii=False),
          "ON конфликты: %s" % (conflicts or "нет"),
          "Expression-режимы ON: %s" % (expression_modes or "нет"),
          "OFF: %s" % build["off"]["composer_gate"],
          "",
          "## Аномалии",
          "",
          "- пустых ответов: %s" % (results["empty_replies"] or "нет"),
          "- идентичные system у рук: %s" % (
              results["systems_equal"] or "нет"),
          "- расхождения recheck: %s" % (recheck_mismatch or "нет"),
          "- хвост личности (dev-БД без PG): %d символов в ОБЕИХ руках%s"
          % (results["character_block_chars"],
             "; ошибка резолва: %s" % results["character_block_error"]
             if results["character_block_error"] else ""),
          ]
    for n in notes:
        L.append("- заметка [%s / %s]: %s" % (n["pair_id"], n["scene"],
                                              n["note"]))
    (EVID / "analysis.md").write_text("\n".join(L) + "\n",
                                      encoding="utf-8", newline="\n")
    print("AB analyze | pairs=%d recheck=%s | wins ON=%s OFF=%s | ties=%s"
          % (n_pairs, recheck["result"],
             {d: wins["on"][d] for d in MANUAL_DIMS},
             {d: wins["off"][d] for d in MANUAL_DIMS}, ties))
    return 0


if __name__ == "__main__":
    sys.exit(main())
