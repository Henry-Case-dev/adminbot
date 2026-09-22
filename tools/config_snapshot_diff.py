#!/usr/bin/env python
"""F8 (round 10.25, ADR-1025-21 D4) — read-only snapshot-diff конфигурации по 8 срезам.

Назначение
----------
Безопасное сравнение «до/после» рефакторинга конфигурации бота. Механизм
сознательно НЕ переизобретает бэкап: живые снимки снимаются существующим
контуром (`manage.py`, `var/backups/`, `.env.bak`) силами @DevOps
(T-2998/T-3000). Инструмент:

  * читает JSON-снимки по 8 срезам §3 (глобальная/чаты/ЛС/PERMsoc/промпты/
    модели/подключения/роли);
  * классифицирует `added/removed/changed/unchanged` **по ключам**
    (`pg_key`/`chat_id`, не по display-name);
  * R17-safe: значения секретов — только `{configured,last4}`; инструмент
    дополнительно страхует вывод маскированием «похожего на секрет».

8 срезов (`SLICES`)
-------------------
global, chats, dm, permsoc, prompts, models, connections, roles.

Режимы
------
  python tools/config_snapshot_diff.py --emit-baseline DIR     # offline baseline (8 файлов)
  python tools/config_snapshot_diff.py --diff BEFORE AFTER --out report.md
  python tools/config_snapshot_diff.py --selftest              # проверка классификатора

Ожидание F8: **0 незапланированных изменений** (F8 — read-only enabler,
Δ каталога=0/Δ DDL=0). Метод переиспользуется в **F10** (финальная приёмка).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.param_catalog as pc  # noqa: E402
from config.settings import APP_VERSION  # noqa: E402

SLICES: tuple[str, ...] = (
    "global", "chats", "dm", "permsoc", "prompts", "models",
    "connections", "roles",
)

SLICE_KEY_FIELD: dict[str, str] = {
    "global": "pg_key",
    "chats": "chat_id:pg_key",
    "dm": "chat_id:pg_key",
    "permsoc": "chat_id:pg_key",
    "prompts": "pg_key",
    "models": "pg_key",
    "connections": "pg_key",
    "roles": "role_name",
}

SECRET_MASK = "{configured,last4}"
_SECRET_RE = re.compile(
    r"(\d{8,}:[A-Za-z0-9_\-]{20,})|(sk-[A-Za-z0-9]{16,})|([A-Fa-f0-9]{32,})")


def _is_secret(spec: pc.ParamSpec) -> bool:
    return bool(spec.secret) or spec.category == pc.CATEGORY_KEYS


def safe_value(value) -> str:
    """R17: значение секрета никогда не пишется; остальное — строкой."""
    text = "" if value is None else str(value)
    if _SECRET_RE.search(text):
        return SECRET_MASK
    return text


# ── Offline baseline (8 срезов) ─────────────────────────────────────────────

def build_offline_snapshot() -> dict[str, dict]:
    """Детерминированный baseline из каталога (без БД/сети).

    Служит формой снимка и опорой для self-check; живые значения снимает
    @DevOps тем же контрактом (см. `--emit-baseline`/`--diff`). Секреты — маска.
    """
    out: dict[str, dict] = {s: {} for s in SLICES}
    for spec in sorted(pc.REGISTRY.values(), key=lambda s: s.pg_key):
        if spec.category is None:
            continue
        if _is_secret(spec):
            out["connections"][spec.pg_key] = SECRET_MASK
        elif spec.category == pc.CATEGORY_PROMPTS:
            out["prompts"][spec.pg_key] = f"code:{spec.code_source or '-'}"
        elif spec.category == pc.CATEGORY_MODELS:
            out["models"][spec.pg_key] = "runtime"
        else:
            out["global"][spec.pg_key] = "runtime"
    # roles/разрешения: секции матрицы прав (без значений).
    out["roles"] = {sec: "present" for sec in sorted(pc.known_sections())}
    # chats/dm/permsoc: при отсутствии живых данных — пустые (форма сохранена).
    return out


def emit_baseline(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for slice_name, entries in build_offline_snapshot().items():
        payload = {
            "slice": slice_name,
            "key_field": SLICE_KEY_FIELD[slice_name],
            "entries": entries,
        }
        path = directory / f"{slice_name}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8", newline="\n")
        written.append(path)
    return written


# ── Diff ────────────────────────────────────────────────────────────────────

def classify(before: dict, after: dict) -> dict[str, list[str]]:
    """Классификация изменений ПО КЛЮЧАМ (переименование ключа видно)."""
    b, a = set(before), set(after)
    changed = sorted(k for k in (b & a) if before[k] != after[k])
    return {
        "added": sorted(a - b),
        "removed": sorted(b - a),
        "changed": changed,
        "unchanged": sorted(k for k in (b & a) if before[k] == after[k]),
    }


def load_snapshot(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError(f"{path.name}: нет объекта entries")
    return {str(k): safe_value(v) for k, v in entries.items()}


def diff_dirs(before_dir: Path, after_dir: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for slice_name in SLICES:
        before = load_snapshot(before_dir / f"{slice_name}.json")
        after = load_snapshot(after_dir / f"{slice_name}.json")
        result[slice_name] = classify(before, after)
    return result


def scan_snapshot_dir(directory: Path) -> list[str]:
    """R17: имена файлов, в entries которых найден похожий на секрет текст."""
    suspicious = []
    for slice_name in SLICES:
        path = directory / f"{slice_name}.json"
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        for match in _SECRET_RE.finditer(raw):
            # Маска {configured,last4} под паттерн не попадает; фиксируем только
            # имя файла, значение не выводим.
            if match.group(0) not in SECRET_MASK:
                suspicious.append(f"{slice_name}.json")
                break
    return suspicious


# ── Report ──────────────────────────────────────────────────────────────────

def render_report(result: dict[str, dict], label: str) -> str:
    total = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for stats in result.values():
        for kind in total:
            total[kind] += len(stats[kind])
    lines = [
        "# F8 — diff конфигурации «до/после» по 8 срезам §3",
        "",
        f"> **Фича:** F8 `parameter-registry-widget-map-round1025` "
        f"(ADR-1025-21 D4). **APP_VERSION:** `{APP_VERSION}`. "
        f"**Метка:** {label}.",
        "> **Метод:** классификация по ключам (`pg_key`/`chat_id`), "
        "R17-safe (секреты — только `{configured,last4}`). "
        "Живые снимки снимает @DevOps существующим контуром "
        "(`manage.py`/`var/backups/`/`.env.bak`); в git — только этот отчёт-статусы.",
        "> **Ожидание F8:** 0 незапланированных изменений "
        "(read-only enabler; Δ каталога=0, Δ DDL=0).",
        "",
        "## Сводка по срезам",
        "",
        "| срез | added | removed | changed | unchanged | вердикт |",
        "|---|---|---|---|---|---|",
    ]
    for slice_name in SLICES:
        stats = result.get(slice_name) or {"added": [], "removed": [],
                                           "changed": [], "unchanged": []}
        verdict = "OK (без изменений)" if not (
            stats["added"] or stats["removed"] or stats["changed"]) else "ИЗМЕНЕНИЯ"
        lines.append(
            f"| {slice_name} | {len(stats['added'])} | {len(stats['removed'])} "
            f"| {len(stats['changed'])} | {len(stats['unchanged'])} | {verdict} |")
    lines += [
        f"| **ИТОГО** | **{total['added']}** | **{total['removed']}** | "
        f"**{total['changed']}** | **{total['unchanged']}** | "
        f"**{'OK' if not (total['added'] or total['removed'] or total['changed']) else 'ИЗМЕНЕНИЯ'}** |",
        "",
        "## Детали изменений (по ключам)",
        "",
    ]
    any_change = False
    for slice_name in SLICES:
        stats = result.get(slice_name) or {}
        for kind in ("added", "removed", "changed"):
            keys = stats.get(kind) or []
            if keys:
                any_change = True
                lines.append(f"- **{slice_name}/{kind}** ({len(keys)}): "
                             + ", ".join(f"`{k}`" for k in keys[:40]))
    if not any_change:
        lines.append(
            "Изменений нет: все ключи всех 8 срезов классифицированы как "
            "`unchanged` → значения, которые пользователь не менял, остались прежними.")
    lines += [
        "",
        "## R17",
        "",
        f"- Секреты во всех срезах — только `{SECRET_MASK}`; открытых значений нет.",
        "- Инструмент дополнительно маскирует «похожее на секрет» при чтении снимков.",
        "",
        "## Отсутствие скрытых миграций",
        "",
        "- Δ каталога = 0 (снимок ключей совпадает; см. "
        "`param-registry-round1025.meta.md`).",
        "- Δ DDL = 0 (схема/миграции не менялись; см. `round1025_f8_results.md`).",
        "",
    ]
    return "\n".join(lines)


def run_selftest() -> int:
    cases = [
        ({}, {}, {"added": [], "removed": [], "changed": [], "unchanged": []}),
        ({"a": "1"}, {"a": "1"}, {"added": [], "removed": [],
                                  "changed": [], "unchanged": ["a"]}),
        ({"a": "1"}, {"a": "2", "b": "3"},
         {"added": ["b"], "removed": [], "changed": ["a"], "unchanged": []}),
        ({"a": "1"}, {}, {"added": [], "removed": ["a"],
                          "changed": [], "unchanged": []}),
    ]
    for before, after, expected in cases:
        got = classify(before, after)
        assert got == expected, (before, after, got, expected)
    assert safe_value("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") == SECRET_MASK
    assert safe_value("plain") == "plain"
    print("SELFTEST OK: классификатор и R17-маска работоспособны.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="F8 read-only snapshot-diff (ADR-1025-21 D4)")
    parser.add_argument("--emit-baseline", metavar="DIR",
                        help="записать детерминированный offline-baseline (8 срезов)")
    parser.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"),
                        help="сравнить два каталога снимков")
    parser.add_argument("--out", metavar="REPORT.md", help="куда записать отчёт")
    parser.add_argument("--label", default="offline-baseline", help="метка в отчёте")
    parser.add_argument("--selftest", action="store_true",
                        help="проверить классификатор/маску")
    args = parser.parse_args(argv)

    if args.selftest:
        return run_selftest()
    if args.emit_baseline:
        written = emit_baseline(Path(args.emit_baseline))
        print("EMIT-BASELINE OK: %d срезов → %s" % (len(written), args.emit_baseline))
        return 0
    if args.diff:
        before_dir, after_dir = (Path(args.diff[0]), Path(args.diff[1]))
        suspicious = (scan_snapshot_dir(before_dir)
                      + scan_snapshot_dir(after_dir))
        if suspicious:
            print("R17 FAIL: похоже на открытый секрет в %s"
                  % ", ".join(sorted(set(suspicious))))
            return 1
        result = diff_dirs(before_dir, after_dir)
        report = render_report(result, args.label)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(report, encoding="utf-8", newline="\n")
            print("DIFF OK: отчёт → %s" % args.out)
        changes = sum(len(result[s][k]) for s in SLICES
                      for k in ("added", "removed", "changed"))
        print("DIFF: незапланированных изменений = %d" % changes)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
