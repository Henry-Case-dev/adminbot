# -*- coding: utf-8 -*-
"""Осознанное переиздание счётчиковых пинов каталога после 2.58.151
(MEME-PIPELINE-REFACTOR-01 P2, commit 07627068; PINS-258151).

Почему переиздание вообще нужно (и почему оно МИНИМАЛЬНО):

* P2 добавил ДВА PG-only prompt-ключа `prompts.meme_joke` и
  `prompts.meme_image` (категория `prompts`) — санкционированная Δ каталога,
  уже зафиксированная в `tests/fixtures/round1025/f8_baseline.json`
  (REGISTRY 595→597, GROUPS 120→121, _TAB_BY_GROUP 118→119).
* Формула `len([s for s in pc.REGISTRY.values() if s.category is not None])`
  («categorized») выросла 570→572 ровно на эти два ключа. Часть файлов P2-лейн
  переиздал (test_budget_settings_round1019, test_help_guide_round1014 и др.),
  а девять копий того же литерала остались на 570 → красные контракты.
* Литерал сохранён (пин ловит дрейф: любая будущая Δ каталога снова покраснеет),
  меняется только число + фиксируется rationale.

Что делает инструмент (идемпотентно):

1. считает фактический `categorized` из `services.param_catalog`;
2. проверяет САНКЦИЮ: фактический счётчик обязан быть ровно PREV + 2 и оба
   ключа обязаны существовать в категории `prompts`; иначе — ABORT (значит
   дрейф шире санкции, переиздавать нельзя);
3. проставляет новое число в девять пинов + rationale-NOTE (один раз);
4. `--check` проверяет, что все девять пинов равны фактическому счётчику и
   несут rationale.

Запуск:
  python tools/_pins_258151_reissue_catalog.py            # переиздать
  python tools/_pins_258151_reissue_catalog.py --check    # проверить (EXIT 0/1)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import param_catalog as pc  # noqa: E402

PREV = 570
SANCTIONED_KEYS = ("prompts.meme_joke", "prompts.meme_image")
MARKER = "PINS-258151 reissue"

PINS = (
    "tests/test_decision_making_round1026.py",
    "tests/test_summary_fact_package.py",
    "tests/test_summary_l1_clusterizer.py",
    "tests/test_summary_l2_writer.py",
    "tests/test_summary_logging_runid.py",
    "tests/test_summary_publish_integration_round1026.py",
    "tests/test_summary_test_run.py",
    "tests/test_telegram_reactions_round1026.py",
    "tests/test_tool_coordinator_round1026.py",
)

_HEAD_RE = re.compile(
    r'^(?P<ind>\s*)assert len\(\[s for s in pc\.REGISTRY\.values\(\)\s*$')
_VALUE_RE = re.compile(
    r'^(?P<ind>\s*)if s\.category is not None\]\)\s*==\s*(?P<n>\d+)(?P<tail>.*)$')

_NOTE_TMPL = (
    "# PINS-258151 reissue (MEME-PIPELINE-REFACTOR-01 P2, 07627068):",
    "# +2 PG-only prompt-ключа prompts.meme_joke/prompts.meme_image →",
    "# categorized {prev}→{new} (REGISTRY 597/GROUPS 121/TAB 119 переизданы",
    "# тем же лейном). Санкция: P2 spec §13; F8 emit+check EXIT=0.",
)


def _note(expected: int) -> tuple:
    return tuple(t.format(prev=PREV, new=expected) for t in _NOTE_TMPL)


def categorized() -> int:
    return len([s for s in pc.REGISTRY.values() if s.category is not None])


def sanction_problems(expected: int) -> list:
    """Санкция P2: Δ ровно на два названных ключа, ничего больше."""
    problems = []
    got = categorized()
    if got != expected:
        problems.append(
            f"categorized={got} != санкционированные {expected} "
            f"(P2: {PREV}+2) — дрейф каталога шире санкции")
    for key in SANCTIONED_KEYS:
        spec = pc.REGISTRY.get(key)
        if spec is None:
            problems.append(f"нет санкционированного ключа {key}")
        elif spec.category != "prompts":
            problems.append(f"{key}: категория {spec.category!r} != 'prompts'")
    return problems


def _locate(lines: list) -> tuple:
    """(индекс строки с числом, старое число, отступ) для categorized-пина."""
    for i, ln in enumerate(lines):
        head = _HEAD_RE.match(ln.rstrip("\r\n"))
        if not head or i + 1 >= len(lines):
            continue
        val = _VALUE_RE.match(lines[i + 1].rstrip("\r\n"))
        if val:
            return i + 1, int(val.group("n")), head.group("ind")
    raise SystemExit("categorized-пин не найден")


def reissue(path: Path, expected: int) -> bool:
    raw = path.read_bytes()
    eol = "\r\n" if b"\r\n" in raw else "\n"
    lines = raw.decode("utf-8").splitlines(keepends=True)
    idx, old, ind = _locate(lines)
    changed = False
    if not any(MARKER in ln for ln in lines[max(0, idx - 12):idx]):
        block = [ind + t + eol for t in _note(expected)]
        lines[idx - 1:idx - 1] = block
        idx += len(block)
        changed = True
    line = lines[idx]
    new_line = line.replace(f"== {old}", f"== {expected}", 1)
    if new_line != line:
        lines[idx] = new_line
        changed = True
    if changed:
        path.write_bytes("".join(lines).encode("utf-8"))
    return changed


def check(path: Path, expected: int) -> list:
    lines = path.read_text(encoding="utf-8").splitlines()
    idx, got, _ind = _locate(lines)
    problems = []
    if got != expected:
        problems.append(f"PIN STALE {path.as_posix()}: {got} != {expected}")
    if not any(MARKER in ln for ln in lines[max(0, idx - 12):idx]):
        problems.append(f"RATIONALE MISSING {path.as_posix()}")
    return problems


def main(argv) -> int:
    check_only = "--check" in argv
    expected = PREV + len(SANCTIONED_KEYS)
    problems = sanction_problems(expected)

    if check_only:
        problems += [p for rel in PINS
                     for p in check(ROOT / rel, expected)]
        if problems:
            print("CHECK FAILED")
            for p in problems:
                print(" -", p)
            return 1
        print(f"CHECK OK: categorized={categorized()} "
              f"({len(PINS)} пинов переизданы, санкция P2 цела)")
        return 0

    if problems:
        for p in problems:
            print(" -", p)
        print("REISSUE ABORTED: санкция P2 не выполняется")
        return 1

    touched = [rel for rel in PINS if reissue(ROOT / rel, expected)]
    for rel in PINS:
        for problem in check(ROOT / rel, expected):
            print("REISSUE FAILED:", problem)
            return 1
    print(f"categorized={categorized()} (было {PREV}, санкция P2 +2)")
    print("изменено:", ", ".join(touched) or "ничего (идемпотентно)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
