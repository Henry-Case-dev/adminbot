"""AMD26 — фальсификация критичных склеек проводки «Летописца».

Мутируем по одному условию и убеждаемся, что соответствующий тест ПАДАЕТ:
ибо иначе сторож не несущий. Каждая мутация применяется во временной копии
дерева (оригинальные файлы не меняются), прогон — подпроцессом pytest.

Склейки: (M1) OFF-паритет композера, (M2) ON-жанровая рамка, (M3) жанр/id
на реальном публикующем пути, (M4) инъекция-гард (материал чата в system),
(M5) подстановка темы в канон, (M6) запись фактов истории (payload).

Запуск: `py -3 tools/soul1_amd26_mutation_witness.py`
Выход: `plans/features/soul-1/evidence/amd26/mutation-witness.json`
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = (REPO / "plans" / "features" / "soul-1" / "evidence" / "amd26"
       / "mutation-witness.json")

WIRING_TESTS = "tests/test_soul1_amd26_authorial_wiring.py"

#: (файл, что искать, на что заменить, тест, короткое имя мутации)
MUTATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("services/mca_authorial_speech.py",
     "        if not pc.composer_enabled_now(gates):\n"
     "            return str(legacy_canon or \"\"), None",
     "        if False:\n"
     "            return str(legacy_canon or \"\"), None",
     WIRING_TESTS + "::test_lore_story_off_parity_byte_for_byte",
     "M1: композер OFF больше не держит паритет (канон подменяется сборкой)"),
    ("services/mca_authorial_speech.py",
     "    return f\"{rules}\\n\\n{canon}\"",
     "    return canon",
     WIRING_TESTS + "::test_lore_story_on_gets_core_and_lore_genre",
     "M2: жанровая рамка выпала из base (ON-сборка без жанра)"),
    ("services/lore_compiler_service.py",
     "writer=\"lore_writer\", genre=\"lore\",",
     "writer=\"lore_writer\", genre=\"lore_unknown\",",
     WIRING_TESTS + "::test_lore_story_on_gets_core_and_lore_genre",
     "M3: на публикующем пути потерян жанр (сборка тихо вернула канон)"),
    ("services/lore_compiler_service.py",
     "        canon = LORE_STORY_SYSTEM_PROMPT.replace(\"{topic}\", clean)",
     "        canon = LORE_STORY_SYSTEM_PROMPT.replace(\"{topic}\", clean)"
     " + \"\\n\" + user",
     WIRING_TESTS + "::test_chat_material_never_leaks_into_system",
     "M4: материал чата вшит в system (инъекция-гард)"),
    ("services/lore_compiler_service.py",
     "LORE_STORY_SYSTEM_PROMPT.replace(\"{topic}\", clean)",
     "LORE_STORY_SYSTEM_PROMPT",
     WIRING_TESTS + "::test_lore_story_off_parity_byte_for_byte",
     "M5: тема не подставляется в канон ({topic} уходит в модель)"),
    ("services/lore_compiler_service.py",
     "await self.db.upsert_lore_story(chat_id, topic_key, clean, story,",
     "await self.db.upsert_lore_story(chat_id, topic_key, clean, canon,",
     WIRING_TESTS + "::test_story_write_contract_unchanged_with_composer_on",
     "M6: в хранилище уходит канон вместо рассказа (payload искажён)"),
)


def run_case(case) -> dict:
    rel, needle, replacement, test, name = case
    tmp = Path(tempfile.mkdtemp(prefix="amd26-mut-"))
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
        "slice": "soul-1/AMD26",
        "tool": "tools/soul1_amd26_mutation_witness.py",
        "note": ("Мутация применяется во временной копии дерева; "
                 "оригинальные файлы не изменяются."),
        "results": results,
        "killed": killed,
        "total": len(results),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="\n")
    print("killed=%d/%d → %s" % (killed, len(results), OUT))
    return 0 if killed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
