# -*- coding: utf-8 -*-
"""W5 mutation witnesses — критичные защиты слайса (kill → restore).

Каждая мутация ломает ОДНУ защиту в рабочем коде и обязана быть убита
тестами слайса (RED). После прогона файл восстанавливается байт-в-байт.

Запуск: py -3 tools/_soul1_w5_mutations.py
Выход: plans/features/soul-1/evidence/w5/mutation-witness.json
"""
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "plans" / "features" / "soul-1" / "evidence" / "w5" / \
    "mutation-witness.json"

PY = sys.executable

MUTATIONS = [
    {
        "id": "M1",
        "name": "health≠outcome: «возможности есть, сообщений нет» "
                "выдаётся за ok",
        "file": "services/initiative_diagnostics.py",
        "old": '    if delivered == 0:\n        base.update({\n'
               '            "state": "opportunities_no_messages",',
        "new": '    if delivered == 0:\n        base.update({\n'
               '            "state": "ok",',
        "test": ["tests/test_soul1_w5_initiative_vitality.py::"
                 "test_opportunities_without_messages_is_a_warning"],
    },
    {
        "id": "M2",
        "name": "mock-send проверки публикует в реальный чат",
        "file": "services/initiative_diagnostics.py",
        "old": "        use_mock = not (publish and publish_axis and confirm_publish)",
        "new": "        use_mock = False",
        "test": ["tests/test_soul1_w5_initiative_vitality.py::"
                 "test_check_publish_is_off_without_owner_axis"],
    },
    {
        "id": "M3",
        "name": "снят анти-спам min_gap (пауза после реплики бота)",
        "file": "services/initiative_observer.py",
        "old": "            age = await self._last_bot_output_age(chat_id)\n"
               "            if age is not None and age < int(profile[\"min_gap_seconds\"]):",
        "new": "            age = await self._last_bot_output_age(chat_id)\n"
               "            if False:",
        "test": ["tests/test_soul1_w5_observer_gates.py::"
                 "test_min_gap_after_bot_reply_still_blocks"],
    },
    {
        "id": "M4",
        "name": "инициативный Writer теряет владельческий кадр личности "
                "(identity Direct≠Initiative)",
        "file": "services/direct_chat_service.py",
        "old": "                character_block=persona_block, response_plan=response_plan,",
        "new": "                character_block=\"\", response_plan=response_plan,",
        "test": ["tests/test_soul1_w5_observer_gates.py::"
                 "test_initiative_writer_shares_core_style_and_persona"],
    },
    {
        "id": "M5",
        "name": "мягкая цель поднимает жёсткий дневной лимит",
        "file": "services/initiative_observer.py",
        "old": "        if behind and base_gap > 0:",
        "new": "        out[\"max_replies_per_day\"] = max(\n"
               "            int(profile[\"max_replies_per_day\"] or 0), soft_day)\n"
               "        if behind and base_gap > 0:",
        "test": ["tests/test_soul1_w5_observer_gates.py::"
                 "test_day_cap_still_hard_with_soft_target"],
    },
    {
        "id": "M6",
        "name": "возврат задушенности: not_enough снова сбрасывает накопленное "
                "окно и штамп интервала",
        "file": "services/initiative_observer.py",
        "old": "            if pending < int(profile[\"eval_min_messages\"]):\n"
               "                self._skip_eval(payload, chat_id, SKIP_NOT_ENOUGH,\n"
               "                                eval_due=False)",
        "new": "            if pending < int(profile[\"eval_min_messages\"]):\n"
               "                self._skip_eval(payload, chat_id, SKIP_NOT_ENOUGH)",
        "test": ["tests/test_soul1_w5_observer_gates.py::"
                 "test_not_enough_keeps_pending_and_interval_stamp"],
    },
    {
        "id": "M6b",
        "name": "интервал проверок снова «съедает» накопленное окно",
        "file": "services/initiative_observer.py",
        "old": "            if now - int(entry.get(\"last_eval_ts\") or 0) < \\\n"
               "                    int(profile[\"eval_min_interval_seconds\"]):\n"
               "                self._skip_eval(payload, chat_id, SKIP_EVAL_NOT_DUE,\n"
               "                                eval_due=False)",
        "new": "            if now - int(entry.get(\"last_eval_ts\") or 0) < \\\n"
               "                    int(profile[\"eval_min_interval_seconds\"]):\n"
               "                self._skip_eval(payload, chat_id, SKIP_EVAL_NOT_DUE)",
        "test": ["tests/test_soul1_w5_observer_gates.py::"
                 "test_eval_not_due_keeps_pending_for_later"],
    },
    {
        "id": "M7",
        "name": "причина инициативного молчания снова отбрасывается "
                "контрактом событий",
        "file": "services/mca_events.py",
        "old": '    "default", "recent_reply",',
        "new": '    "recent_reply",',
        "test": ["tests/test_soul1_w5_initiative_vitality.py::"
                 "test_initiative_reason_codes_survive_event_contract"],
    },
    {
        "id": "M8",
        "name": "UI-проверка инициативы перестаёт быть mock по умолчанию",
        "file": "web/app.js",
        "old": "body: JSON.stringify({ chat_id: chatId, hours: 24,\n"
               "                                   publish: false, "
               "confirm_publish: false }),",
        "new": "body: JSON.stringify({ chat_id: chatId, hours: 24,\n"
               "                                   publish: true, "
               "confirm_publish: true }),",
        "test": None,
        "node": "tests/js/soul1_w5_initiative_panel_test.js",
    },
]


def run_pytest(nodes):
    proc = subprocess.run([PY, "-m", "pytest", *nodes, "-q", "-p",
                           "no:randomly"], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=600)
    return proc.returncode, (proc.stdout or "")[-1500:]


def run_node(script):
    proc = subprocess.run(["node", script], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=300)
    return proc.returncode, (proc.stdout or "")[-800:]


def main() -> int:
    results = []
    for spec in MUTATIONS:
        path = ROOT / spec["file"]
        original = path.read_bytes()
        text = original.decode("utf-8")
        if spec["old"] not in text:
            results.append({"id": spec["id"], "name": spec["name"],
                            "status": "NOT_APPLIED",
                            "detail": "исходный фрагмент не найден"})
            continue
        mutated = text.replace(spec["old"], spec["new"], 1)
        path.write_bytes(mutated.encode("utf-8"))
        try:
            if spec.get("node"):
                code, out = run_node(spec["node"])
            else:
                code, out = run_pytest(spec["test"])
            killed = code != 0
            detail = ("тест упал на мутации (KILLED)" if killed
                      else "тест прошёл на мутации (ALIVE — плохо)")
        finally:
            path.write_bytes(original)
        results.append({"id": spec["id"], "name": spec["name"],
                        "status": "KILLED" if killed else "ALIVE",
                        "detail": detail, "tail": out.strip()[-400:]})
        print("%-3s %-8s %s" % (spec["id"], results[-1]["status"],
                                spec["name"]))
    payload = {
        "candidate": "рабочее дерево (без коммита)",
        "total": len(results),
        "killed": sum(1 for r in results if r["status"] == "KILLED"),
        "alive": sum(1 for r in results if r["status"] == "ALIVE"),
        "not_applied": sum(1 for r in results
                           if r["status"] == "NOT_APPLIED"),
        "mutations": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print("witness:", payload["killed"], "/", payload["total"], "killed")
    return 0 if payload["alive"] == 0 and payload["not_applied"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
