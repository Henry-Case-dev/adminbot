"""Мутационная проверка PVR-S6: аудит полей обязан уметь падать.

Запуск из корня worktree с реализацией PVR-S5/S6:

    py -3 plans/features/prompt-versioning-ux/evidence/pvr-s6/mutations.py --repo .

Каждая мутация вносится побайтово, прогоняется один адресный тест, затем файл
восстанавливается ИЗ ИСХОДНЫХ БАЙТ (не текстовым режимом — иначе CRLF/LF
нормализуются и «восстановление» меняет файл). В конце печатается
``restored byte-identical: True`` и контрольный прогон аудита.

Ожидаемый результат: все строки ``CAUGHT``.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys

CATALOG = "services/param_catalog.py"
REGISTRY = "services/prompt_registry.py"
POLICY = "services/prompt_release_policy.py"
AUDIT = "tests/test_prompt_field_audit.py"

#: (имя, файл, [(байты-искать, байты-заменить)], адресный тест)
MUTATIONS = [
    # (a) зарегистрированный редактируемый промпт без достижимого редактора:
    # ключ прячется в каталоге параметров, поверхности у блока не остаётся.
    ("A: промпт скрыт в каталоге без альтернативной поверхности", CATALOG,
     [(b'_HIDDEN_CATALOG_PG_KEYS: frozenset[str] = frozenset({\n'
       b'    "prompts.summary_cover_style_id",\n})',
       b'_HIDDEN_CATALOG_PG_KEYS: frozenset[str] = frozenset({\n'
       b'    "prompts.summary_cover_style_id",\n'
       b'    "prompts.search_system_prompt",\n})')],
     f"{AUDIT}::test_every_editable_prompt_has_reachable_surface"),

    # (b) pg_key/block_id: у документа Core второй блок теряет имя поля
    # (`pg_doc_field`), из-за чего адрес значения `character.core` становится
    # неоднозначным: две обычные записи на один pg_key.
    ("B: блок документа без pg_doc_field делит pg_key", REGISTRY,
     [(b'pg_key="character.core", pg_doc_field="compact_text",',
       b'pg_key="character.core",')],
     f"{AUDIT}::test_shared_pg_key_is_an_explicit_document"),

    # (c) рантайм-страж обхода журнала выключен: прямой write_chat_params
    # проходит без журнального токена.
    ("C: страж PromptJournalBypass больше не поднимается", POLICY,
     [(b"    raise PromptJournalBypass(\n"
       b'        f"{spec.pg_key}:',
       b"    return\n"
       b"    raise PromptJournalBypass(\n"
       b'        f"{spec.pg_key}:')],
     f"{AUDIT}::test_guard_rejects_direct_chat_override_write_for_every_prompt"),
]


def _run_pytest(root: pathlib.Path, target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, timeout=900)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="корень worktree с PVR-S6")
    args = parser.parse_args()
    root = pathlib.Path(args.repo).resolve()

    touched = sorted({rel for _n, rel, _e, _t in MUTATIONS})
    before = {p: hashlib.sha256((root / p).read_bytes()).hexdigest()
              for p in touched}
    problems = 0
    for name, rel, edits, target in MUTATIONS:
        path = root / rel
        original = path.read_bytes()
        text = original
        for old, new in edits:
            if old not in text:
                print(f"SKIP (anchor missing): {name}")
                problems += 1
                break
            text = text.replace(old, new, 1)
        else:
            path.write_bytes(text)
            try:
                proc = _run_pytest(root, target)
                tail = [ln for ln in proc.stdout.splitlines()
                        if "passed" in ln or "failed" in ln or "error" in ln]
                verdict = "CAUGHT" if proc.returncode != 0 else "MISSED"
                print(f"{verdict} | {name} | {tail[-1] if tail else '?'}")
                if proc.returncode == 0:
                    problems += 1
            finally:
                path.write_bytes(original)
        if path.read_bytes() != original:      # страховка восстановления
            path.write_bytes(original)

    after = {p: hashlib.sha256((root / p).read_bytes()).hexdigest()
             for p in touched}
    print("restored byte-identical:", before == after)
    control = _run_pytest(root, AUDIT)
    print("post-restore:", control.stdout.strip().splitlines()[-1])
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
