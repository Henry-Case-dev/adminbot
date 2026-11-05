"""Мутационная проверка PVR-S3: тесты обязаны уметь падать.

Запуск из корня worktree с реализацией PVR-S3:

    py -3 plans/features/prompt-versioning-ux/evidence/pvr-s3/mutations.py \
        --repo .

Каждая мутация вносится побайтово, прогоняется один адресный тест, затем файл
восстанавливается ИЗ ИСХОДНЫХ БАЙТ (не текстовым режимом — иначе CRLF/LF
нормализуются и «восстановление» меняет файл). В конце печатается
`restored byte-identical: True` и контрольный прогон целевого набора.

Ожидаемый результат: все строки `CAUGHT`.
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys

PKG = "services/prompt_release_policy.py"
REG = "services/prompt_registry.py"
SPEECH = "web/api/speech.py"
TEST = "tests/test_prompt_history_pagination.py"

#: (имя, файл, [(байты-искать, байты-заменить)], адресный тест)
MUTATIONS = [
    ("N1: pinned-проверка снова ПОСЛЕ cutover", REG,
     [("    # 3) Закреплённый владельцем scope (owner baseline): новая поставка "
       "кода".encode(),
       ("    if not has_import:\n"
        "        return ActivationPlan(PLAN_LEGACY_CUTOVER, \"legacy_import\", \"\",\n"
        "                              \"cutover\", code_revision,\n"
        "                              applied_factory_revision)\n"
        "    # 3) Закреплённый владельцем scope (owner baseline): новая поставка "
        "кода").encode())],
     f"{TEST}::test_pinned_scope_first_labelled_release_keeps_value"),

    ("N2: copy-to-global отдаёт запрошенный reason вместо сохранённого", PKG,
     [(b"            if stored_reason:\n                copy_reason = stored_reason",
       b"            if stored_reason and False:\n                copy_reason = stored_reason")],
     f"{TEST}::test_copy_to_global_reports_stored_reason"),

    ("Потолок истории: страница урезается до 50", PKG,
     [(b"    return max(1, min(size, HISTORY_PAGE_MAX))",
       b"    return max(1, min(size, 50))")],
     f"{TEST}::test_full_history_of_1000_revisions_has_no_cap"),

    ("Тело ревизии попадает в список (стор → поле → ответ)", PKG,
     [(b'    detail_code: str = ""\n    activation_id: int = 0',
       b'    detail_code: str = ""\n    activation_id: int = 0\n    body: str = ""'),
      (b'            content_sha12=r.content_sha12, chars=len(r.body or ""),',
       b'            content_sha12=r.content_sha12, chars=len(r.body or ""),\n'
       b'            body=r.body,'),
      (b'            "body_available": bool(row.entry_type == ENTRY_REVISION\n'
       b'                                   or row.revision_id),',
       b'            "body_available": True,\n            "body": row.body,')],
     f"{TEST}::test_list_never_contains_bodies"),

    ("Статус игнорирует retired", PKG,
     [(b'    if retired:\n        return "retired"',
       b'    if retired and False:\n        return "retired"')],
     f"{TEST}::test_retired_and_incompatible_are_readable_but_never_actionable"),

    ("Курсор включительный (сдвиг страницы)", PKG,
     [(b'              if cursor is None or _history_key(r) < (cursor["ts"],\n'
       b'                                                      cursor["sort_id"])]',
       b'              if cursor is None or _history_key(r) <= (cursor["ts"],\n'
       b'                                                       cursor["sort_id"])]')],
     f"{TEST}::test_cursor_is_stable_when_new_rows_appear"),

    ("Чат-фильтр отключён (утечка истории чата)", PKG,
     [(b"            if r.block_id == block_id and _row_matches_chat(r, chat_id)]\n"
       b"        acts = []",
       b"            if r.block_id == block_id]\n        acts = []")],
     f"{TEST}::test_chat_history_is_not_readable_through_another_chat"),

    # B1 (ревью PVR-S3): событие обязано наследовать retired/несовместимость
    # СВОЕЙ ревизии — иначе строка события и строка версии противоречат друг
    # другу в одном списке и S4 предлагает «Применить» снятой версии.
    ("B1: событие не наследует retired/несовместимость своей ревизии", PKG,
     [(b"            linked = self.revisions.get(a.revision_id) "
       b"if a.revision_id else None",
       b"            linked = None")],
     f"{TEST}::test_event_rows_agree_with_their_revision_state"),

    ("Speech-история снова ограничена 12", SPEECH,
     [(b"SPEECH_HISTORY_PAGE = 50", b"SPEECH_HISTORY_PAGE = 12")],
     f"{TEST}::test_speech_history_comes_from_journal_without_12_cap"),
]


def _run_pytest(root: pathlib.Path, target: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", target, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True, timeout=900)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".", help="корень worktree с PVR-S3")
    args = parser.parse_args()
    root = pathlib.Path(args.repo).resolve()

    touched = (PKG, REG, SPEECH)
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
    control = _run_pytest(root, TEST)
    print("post-restore:", control.stdout.strip().splitlines()[-1])
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
