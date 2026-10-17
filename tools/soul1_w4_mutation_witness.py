"""W4 — фальсификация критичных сторожей (мутационный прогон).

Мутируем по одному условию и убеждаемся, что соответствующий тест ПАДАЕТ:
иначе защита не является несущей. Каждая мутация выполняется во временной
копии дерева (оригинальные файлы не меняются), прогон — подпроцессом pytest.

Запуск: `py -3 tools/soul1_w4_mutation_witness.py`
Выход: `plans/features/soul-1/evidence/w4/mutation-witness.json`
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = (REPO / "plans" / "features" / "soul-1" / "evidence" / "w4"
       / "mutation-witness.json")

#: (файл, что искать, на что заменить, тест, короткое имя мутации)
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("services/mca_sample_library.py",
     'if scope == "chat":\n            if row_chat is None or int(row_chat) != int(chat_id or 0):',
     'if scope == "chat":\n            if False:',
     "tests/test_soul1_w4_sample_library.py::"
     "test_cross_chat_isolation_is_hard",
     "снята cross-chat изоляция выбора примеров"),
    ("services/mca_sample_library.py",
     "        if scan_sensitivity(row.get(\"input_text\"), row.get(\"reply_text\")):\n"
     "            excluded.append({\"id\": rid, \"reason\": \"leakage_guard\"})\n"
     "            continue",
     "        if False:\n"
     "            excluded.append({\"id\": rid, \"reason\": \"leakage_guard\"})\n"
     "            continue",
     "tests/test_soul1_w4_sample_library.py::"
     "test_leakage_guard_double_defence_on_selection",
     "снят leakage-guard на отборе"),
    ("services/mca_sample_library.py",
     "        if not bool(row.get(\"owner_approved\")):",
     "        if False:",
     "tests/test_soul1_w4_sample_library.py::"
     "test_selection_returns_only_owner_approved_globals",
     "черновики допущены в runtime как эталоны"),
    ("services/mca_humor_feedback.py",
     "        if explicit:\n            confirmed = True\n",
     "        if False:\n            confirmed = True\n",
     "tests/test_soul1_w4_humor_feedback.py::"
     "test_single_explicit_request_applies_immediately",
     "явное указание владельца больше не применяется мгновенно"),
    ("services/mca_humor_feedback.py",
     '            elif int(obs.reactions_distinct or 0) > MAX_REACTORS_PER_MESSAGE:\n'
     '                guards.add("guard_brigading")\n'
     '                worse.append(obs)',
     '            elif False:\n'
     '                guards.add("guard_brigading")\n'
     '                worse.append(obs)',
     "tests/test_soul1_w4_humor_feedback.py::"
     "test_brigading_and_engagement_gaming_are_guarded",
     "снят бригандинг-сторож"),
    ("services/mca_humor_feedback.py",
     "        if users:\n"
     "            share = max(sum(1 for o in chosen",
     "        if False:\n"
     "            share = max(sum(1 for o in chosen",
     "tests/test_soul1_w4_humor_feedback.py::"
     "test_small_n_single_user_and_topic_are_guarded",
     "снят сторож «один пользователь»"),
    ("services/mca_humor_craft.py",
     "    if weight <= 0.05:",
     "    if False:",
     "tests/test_soul1_w4_humor_craft.py::"
     "test_negative_feedback_weakens_strategy_in_context",
     "контекстный штраф перестал гасить приём"),
    ("services/mca_humor_craft.py",
     "    if _serious_context(structure, tone):",
     "    if False:",
     "tests/test_soul1_w4_humor_craft.py::"
     "test_selection_requires_l1_advice_and_respects_serious_context",
     "серьёзный контекст перестал защищаться"),
    ("services/mca_humor_feedback.py",
     "    if not gate_on():\n        return {\"captured\": False",
     "    if False:\n        return {\"captured\": False",
     "tests/test_soul1_w4_humor_feedback.py::"
     "test_capture_send_writes_bounded_episode",
     "снят гейт оси обратной связи при отправке"),
    # ── FIX-W4 (REVIEW-W4 F1/F2/F3): правки тоже под мутационным свидетелем ──
    ("web/api/speech.py",
     "    await _guard_sample_chat_scope(sample_id, chat_id)\n"
     "    view, reason = await samples_lib.set_approval(",
     "    view, reason = await samples_lib.set_approval(",
     "tests/test_soul1_w4_examples_scope.py::"
     "test_foreign_chat_approve_and_archive_are_forbidden",
     "снята проверка чата на approve (F1)"),
    ("services/mca_humor_feedback.py",
     "task_type = ?\" + chat_filter, (SEND_TASK_TYPE,) + args)",
     "task_type = ?\" + chat_filter, args)",
     "tests/test_soul1_w4_examples_scope.py::"
     "test_telemetry_counts_captured_sends",
     "снят биндинг счётчика отправок (F2)"),
    ("web/api/speech.py",
     "             \"state\": str(examples_card[\"state\"]),",
     "             \"state\": \"not_implemented\",",
     "tests/test_soul1_w4_examples_scope.py::"
     "test_overview_cards_reflect_delivered_sections",
     "карточка «Примеры» снова врёт про поставку (F3)"),
    # ── C1 (RECHECK-W4): расширение итератора полей отправки ──
    ("services/mca_humor_feedback.py",
     "    for name in SEND_FIELDS:",
     "    for name in list(SEND_FIELDS) + [\"secret_prompt\", \"raw_text\"]:",
     "tests/test_soul1_w4_humor_feedback.py::"
     "test_send_metadata_is_bounded_and_typed",
     "итератор полей расширен секрето-именами (M11 ревьюера, C1)"),
    ("services/mca_humor_feedback.py",
     "    for name in SEND_FIELDS:",
     "    for name in fields:",
     "tests/test_soul1_w4_humor_feedback.py::"
     "test_send_metadata_is_bounded_and_typed",
     "проходят ВСЕ переданные kwargs, а не закрытый набор (C1)"),
)


def run_case(case) -> dict:
    rel, needle, replacement, test, name = case
    tmp = Path(tempfile.mkdtemp(prefix="w4-mut-"))
    root = tmp / "repo"
    try:
        for item in ("services", "tests", "config", "web", "tools"):
            src = REPO / item
            if src.exists():
                shutil.copytree(src, root / item,
                                ignore=shutil.ignore_patterns(
                                    "__pycache__", "*.pyc"))
        target = root / rel
        text = target.read_text(encoding="utf-8")
        if needle not in text:
            return {"mutation": name, "test": test, "applied": False,
                    "detail": "условие не найдено (код изменился)"}
        target.write_text(text.replace(needle, replacement, 1),
                          encoding="utf-8", newline="\n")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", test, "-q", "--no-header",
             "-p", "no:cacheprovider"],
            cwd=str(root), capture_output=True, text=True, timeout=600)
        tail = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()][-3:]
        return {"mutation": name, "test": test, "applied": True,
                "killed": proc.returncode != 0,
                "exit_code": proc.returncode, "tail": tail}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    results = []
    for case in MUTATIONS:
        result = run_case(case)
        results.append(result)
        status = ("KILLED" if result.get("killed") else
                  ("NOT-APPLIED" if not result.get("applied") else "SURVIVED"))
        print("%-9s %s" % (status, result["mutation"]))
    killed = sum(1 for r in results if r.get("killed"))
    out = {
        "slice": "soul-1/W4",
        "tool": "tools/soul1_w4_mutation_witness.py",
        "note": ("Мутация применяется во временной копии дерева; "
                 "оригинальные файлы не изменяются."),
        "results": results,
        "killed": killed,
        "total": len(results),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print("killed=%d/%d → %s" % (killed, len(results), OUT))
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
