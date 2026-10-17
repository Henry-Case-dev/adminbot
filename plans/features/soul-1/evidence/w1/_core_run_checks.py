"""CORE-DOC evidence: прогон проверок и снимок их вывода (UTF-8).

Запуск из корня репозитория:
    .venv\\Scripts\\python.exe plans/features/soul-1/evidence/w1/_core_run_checks.py

Пишет рядом ``_core_tests.txt`` (pytest: паритет OFF, сьюты SOUL-1, новые
файлы, периметр) и ``_core_checks.txt`` (каталог round1025 + состояние флагов +
отпечатки файлов кандидата).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
HERE = pathlib.Path(__file__).resolve().parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
os.chdir(ROOT)

SUITES = [
    ("[1] W2 OFF-паритет (13/13 обязателен)",
     ["tests/test_soul1_composer_parity_off.py"]),
    ("[2] новые файлы CORE-DOC",
     ["tests/test_soul1_core_doc_text.py",
      "tests/test_soul1_core_registry_api.py",
      "tests/test_soul1_core_composer_integration.py"]),
    ("[3] сьюты SOUL-1 целиком",
     ["tests", "-k", "soul1"]),
    ("[4] каталог/реестр/промпты (фокус)",
     ["tests/test_round1025_f8_registry.py", "tests/test_prompt_migrations.py",
      "tests/test_soul1_registry_completeness.py",
      "tests/test_soul1_registry_legacy_removal.py",
      "tests/test_soul1_factory_defaults.py"]),
    ("[5] периметр soul1|catalog|registry|prompt|direct_chat|summary|config "
     "(без tests/test_summary_memory.py — предсуществующий teardown aiosqlite)",
     ["tests", "-k", "soul1 or catalog or registry or prompt or direct_chat "
                     "or summary or config",
      "--ignore=tests/test_summary_memory.py"]),
]

FILES = [
    "services/prompt_registry.py", "services/prompt_factory.py",
    "services/prompt_composer.py", "services/chat_prompts.py",
    "tests/test_soul1_core_doc_text.py",
    "tests/test_soul1_core_registry_api.py",
    "tests/test_soul1_core_composer_integration.py",
    "tests/test_soul1_core_version_propagation.py",
]


def sha12(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()[:12]


def run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run([PY, "-m", "pytest", *args, "-q", "-p", "no:randomly"],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-4:])
    return proc.returncode, tail


def main() -> None:
    lines: list[str] = ["CORE-DOC / проверки (кандидат без коммита)", ""]
    for title, args in SUITES:
        code, tail = run(args)
        lines += [f"{title}: exit={code}", tail, ""]
        print(title, "exit", code, "|", tail.replace("\n", " | "))
    (HERE / "_core_tests.txt").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8", newline="\n")

    check = subprocess.run([PY, "tools/gen_param_registry_round1025.py", "--check"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    flags = subprocess.run(
        [PY, "-c",
         "import os, json; from services import mca_gates as g;"
         "print(json.dumps({'env_UNIFIED_COMPOSER_ENABLED': "
         "'UNIFIED_COMPOSER_ENABLED' in os.environ,"
         "'env_enabled': g.unified_composer_env_enabled(),"
         "'effective_enabled': g.unified_composer_enabled(),"
         "'character_core_enabled': g.character_core_enabled(),"
         "'speech_style_policy_enabled': g.speech_style_policy_enabled(),"
         "'humor_library_enabled': g.humor_library_enabled(),"
         "'humor_feedback_enabled': g.humor_feedback_enabled()},"
         "ensure_ascii=False))"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    check_lines = [
        "CORE-DOC / каталог, флаги, отпечатки кандидата", "",
        f"gen_param_registry_round1025.py --check: exit={check.returncode}",
        (check.stdout or "").strip(), "",
        "флаги (код-дефолты; прод не тронут):",
        (flags.stdout or "").strip(), "",
        "sha256_12 кандидата:",
        *[f"  {sha12(path)} {path}" for path in FILES],
        "", "git status --porcelain:",
        (status.stdout or "").strip() or "(пусто)",
    ]
    (HERE / "_core_checks.txt").write_text("\n".join(check_lines) + "\n",
                                           encoding="utf-8", newline="\n")
    print("WROTE", HERE / "_core_tests.txt")
    print("WROTE", HERE / "_core_checks.txt")
    print((check.stdout or "").strip())


if __name__ == "__main__":
    main()
