# -*- coding: utf-8 -*-
"""2.58.198 bump: APP_VERSION + all 30 version pins, exactly the 2.58.197 pattern.

Byte-safe: no newline translation (repo files are LF; Windows text mode would
rewrite them as CRLF). Touches only:
  config/settings.py                          (APP_VERSION line + release note)
  plans/docs/param-registry-round1025.meta.md (APP_VERSION line)
  24 python pin-guard tests (25 assertions)
   4 javascript pin-guard tests
No other change. Verifies every expected occurrence before writing.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
NEW = "2.58.198"
OLD = "2.58.197"

PY_PINS = {
    "tests/test_decision_making_round1026.py": 1,
    "tests/test_image_context_memory_round1026.py": 1,
    "tests/test_mca17c_invariants_round1047.py": 1,
    "tests/test_round1025_f8_registry.py": 1,
    "tests/test_scope_selector_round1025.py": 1,
    "tests/test_summary_deploy_round1026.py": 1,
    "tests/test_summary_fact_package.py": 1,
    "tests/test_summary_logging_runid.py": 1,
    "tests/test_summary_publish_integration_round1026.py": 1,
    "tests/test_summary_test_run.py": 1,
    "tests/test_telegram_reactions_round1026.py": 1,
    "tests/test_tool_coordinator_round1026.py": 1,
    "tests/test_unified_image_request_round1026.py": 1,
    "tests/test_webapp_design_tokens_round1025.py": 1,
    "tests/test_webapp_f11_round1025.py": 1,
    "tests/test_webapp_f6_round1025.py": 1,
    "tests/test_webapp_f7_round1025.py": 1,
    "tests/test_webapp_f9_round1025.py": 1,
    "tests/test_webapp_hotfix10_round1025.py": 1,
    "tests/test_webapp_hotfix6_round1025.py": 1,
    "tests/test_webapp_hotfix7_round1025.py": 1,
    "tests/test_webapp_hotfix8_round1025.py": 1,
    "tests/test_webapp_hotfix9_round1025.py": 1,
    "tests/test_webapp_round1026_polygon.py": 2,
}
JS_PINS = [
    "tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js",
    "tests/js/round1025_hotfix8_shell_aurora_test.js",
    "tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js",
    "tests/js/round1025_hotfix10_glass_geometry_bg_test.js",
]

HEAD_NOTE = (
    "2.58.198 - Самодиагностика (SELF-DIAG-01): на СУЩЕСТВУЮЩЕЙ странице "
    "«Статус» один read-only снимок фактического состояния процесса/хоста и "
    "аналитика существующего события inspect_runtime_called (триггеры, вызовы, "
    "доли частичных, стадии, p50/p95, последний успех) — где источника нет, "
    "печатается null/measured=false, а не ноль; покрытие измеренного "
    "output-enforcement по типам доставки, а не «общий счётчик >= всего»; "
    "identity деплоя (release/checkout/upstream/локальная верификация — verified "
    "не выдумывается) и одобренный read-only git-коллектор (закрытые наборы "
    "команд, shell=False); локальное чтение собственного checkout только при "
    "точном совпадении owner/name; секрет-политика и маскирование в чекапе; "
    "инструмент prompt_readback — чтение эффективного промпта без правок и без "
    "записи, с честным отказом по RBAC; золотой детерминированный набор "
    "самопроверки. Схема не меняется (v47, DDL=0); новых промптов, моделей, "
    "страниц, агентов и планировщиков нет; каталог параметров 643→644 "
    "(flags.self_diag_repo_origin, заводское значение, сохранённые настройки не "
    "сбрасываются), добавлены только env-only пределы проб SELF_DIAG_PROBE_* и "
    "необязательный ADMINBOT_DEPLOYED_SHA. База: 454727ed (кандидат self-diag/final, "
    "docs 8797cd83)."
)

changed: list[tuple[str, str, str]] = []


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bump_settings() -> None:
    path = ROOT / "config/settings.py"
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    pat = re.compile(r'^APP_VERSION = "2\.58\.197"   # (.*)$', re.M)
    matches = pat.findall(text)
    if len(matches) != 1:
        raise SystemExit("settings: expected 1 APP_VERSION line, got %d" % len(matches))
    note = matches[0]
    head = re.sub(r"^\(\d{2}\.\d{2}\.\d{4}\): ", "", note)
    if not head.startswith("2.58.197 - "):
        raise SystemExit("settings: head is not 2.58.197: %r" % head[:40])
    old_line = 'APP_VERSION = "2.58.197"   # ' + note
    new_line = 'APP_VERSION = "%s"   # (13.11.2026): %s Prior %s' % (NEW, HEAD_NOTE, head)
    old_b = old_line.encode("utf-8")
    if raw.count(old_b) != 1:
        raise SystemExit("settings: old line not found exactly once")
    path.write_bytes(raw.replace(old_b, new_line.encode("utf-8"), 1))
    changed.append(("config/settings.py", "1 APP_VERSION line", digest(path)))


def bump_meta() -> None:
    path = ROOT / "plans/docs/param-registry-round1025.meta.md"
    raw = path.read_bytes()
    old = ("- **APP_VERSION:** `%s`" % OLD).encode("utf-8")
    if raw.count(old) != 1:
        raise SystemExit("meta: expected 1 APP_VERSION pin")
    new = ("- **APP_VERSION:** `%s`" % NEW).encode("utf-8")
    path.write_bytes(raw.replace(old, new, 1))
    changed.append(("plans/docs/param-registry-round1025.meta.md",
                    "1 APP_VERSION pin", digest(path)))


def bump_py() -> None:
    for rel, count in PY_PINS.items():
        path = ROOT / rel
        raw = path.read_bytes()
        old = ('"%s"' % OLD).encode("ascii")
        seen = raw.count(old)
        if seen != count:
            raise SystemExit("%s: expected %d quoted pins, got %d" % (rel, count, seen))
        path.write_bytes(raw.replace(old, ('"%s"' % NEW).encode("ascii")))
        changed.append((rel, "%d pin(s)" % count, digest(path)))


def bump_js() -> None:
    old = b"2\\.58\\.197"
    for rel in JS_PINS:
        path = ROOT / rel
        raw = path.read_bytes()
        seen = raw.count(old)
        if seen != 1:
            raise SystemExit("%s: expected 1 escaped pin, got %d" % (rel, seen))
        path.write_bytes(raw.replace(old, b"2\\.58\\.198"))
        changed.append((rel, "1 pin", digest(path)))


def main() -> int:
    bump_settings()
    bump_meta()
    bump_py()
    bump_js()
    print("files_changed=%d" % len(changed))
    for rel, what, sha in changed:
        print("%-62s %-14s %s" % (rel, what, sha[:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
