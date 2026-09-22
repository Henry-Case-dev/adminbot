#!/usr/bin/env python
"""F8 (round 10.25, ADR-1025-21 D2) — read-only генератор реестра параметров и карты экранов.

Назначение
----------
Детерминированно (без timestamp) собрать committed-артефакты F8 из ЕДИНОГО
источника — `services.param_catalog` (каталог 459/98/96/21/418):

  * `plans/docs/param-registry-round1025.tsv`      — реестр 459 (12 полей §2 + производные);
  * `plans/docs/param-registry-round1025.meta.md`  — провенанс (HEAD/APP_VERSION/счётчики/дельта);
  * `plans/docs/screen-map-round1025.md`           — карта «Старый экран → Параметр → Новый экран → API».

Ограничения (read-only enabler, §1/§6 spec):
  * stdlib + импорт `services.param_catalog`; БД/сеть НЕ используются;
  * значения секретов НИКОГДА не выводятся (R17): только форма `{configured,last4}`;
  * запись только в `plans/docs/`; рантайм/CSP не затронуты (скрипт вне рантайма);
  * Δ каталога = 0 (только чтение), Δ DDL = 0 (не трогает БД/схему).

Режимы
------
  python tools/gen_param_registry_round1025.py            # emit (перезаписать артефакты)
  python tools/gen_param_registry_round1025.py --check    # exit≠0 при расхождении с committed

Дельта 411 → 459 = 48: ключи каталога, отсутствующие в
`plans/archive/settings-persistence-audit-round1014/inventory.tsv`, помечаются
`status=new` и явно перечисляются в `.meta.md`.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

try:  # Windows-консоль: не падать на «→»/кириллице.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import services.param_catalog as pc  # noqa: E402
from config.settings import APP_VERSION, settings as settings_obj  # noqa: E402

TSV_PATH = ROOT / "plans" / "docs" / "param-registry-round1025.tsv"
META_PATH = ROOT / "plans" / "docs" / "param-registry-round1025.meta.md"
SCREEN_PATH = ROOT / "plans" / "docs" / "screen-map-round1025.md"
WIDGET_PATH = ROOT / "plans" / "docs" / "widget-map-round1025.md"
INVENTORY_PATH = (
    ROOT / "plans" / "archive"
    / "settings-persistence-audit-round1014" / "inventory.tsv"
)

# 12 полей §2 + производные (ADR-1025-21 D3: +category/group/per_chat/secret/
# hidden/ui_visibility/widget/storage/runtime_consumer/read_fn/status).
TSV_COLUMNS: tuple[str, ...] = (
    "internal_key", "display_name", "description", "data_type",
    "current_value", "default_value", "scope", "inheritance",
    "read_api", "write_api", "validation", "permissions",
    "category", "group", "per_chat", "secret", "hidden", "ui_visibility",
    "widget", "storage", "runtime_consumer", "read_fn", "status",
)

SECRET_MASK = "{configured,last4}"
RUNTIME_VALUE = "runtime"

# IA §4 (spec §3.4): целевые разделы. `Модули/ИИ/Память/PERMsoc` — настройки;
# `Статус/Справка/Доступы` — публичные/админ-разделы без ParamSpec.
NEW_SCREEN_BY_NAV: dict[str, str] = {
    pc.NAV_MODULES: "Модули",
    pc.NAV_AI: "ИИ",
    pc.NAV_MEMORY: "Память",
    pc.NAV_PERMSOC: "PERMsoc",
}

# Паттерны, похожие на секрет (belt-and-suspenders к флагу ParamSpec.secret).
_SECRET_RE = re.compile(
    r"(\d{8,}:[A-Za-z0-9_\-]{20,})|(sk-[A-Za-z0-9]{16,})|([A-Fa-f0-9]{32,})"
)


# ── Хелперы источников ──────────────────────────────────────────────────────

def _read_inventory() -> dict[str, dict]:
    """pg_key → строка inventory.tsv (411 baseline-ключей, 10.14)."""
    out: dict[str, dict] = {}
    if not INVENTORY_PATH.exists():
        return out
    with INVENTORY_PATH.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            key = (row.get("pg_key") or "").strip()
            if key:
                out[key] = row
    return out


def _is_secret(spec: pc.ParamSpec) -> bool:
    return bool(spec.secret) or spec.category == pc.CATEGORY_KEYS


def _clean(value: str, limit: int = 220) -> str:
    """TSV-safe: без табов/переводов строк, с ограничением длины."""
    text = str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _default_value(spec: pc.ParamSpec) -> str:
    """default_value: секреты → маска; prompts → указатель на код-канон; иначе «-».

    Значение по умолчанию сознательно НЕ берётся из `Settings`: env-derived
    дефолты процесса недетерминированы (`.env`/`ADMINBOT_SKIP_DOTENV`) и сломали
    бы байт-идемпотентность `--check`. Источник истины дефолтов — `Settings`
    (+ PG-сид); в committed-артефакте фиксируется документированное «-».
    """
    if _is_secret(spec):
        return SECRET_MASK
    if spec.code_source:
        return f"code:{spec.code_source}"
    return "-"


def _validation(spec: pc.ParamSpec) -> str:
    parts = [spec.type or "str"]
    if spec.widget == "select" and spec.select_options:
        parts.append("one-of[" + "|".join(spec.select_options) + "]")
    if spec.type == "str" and spec.category in (
            pc.CATEGORY_PROMPTS, pc.CATEGORY_CONTENT):
        parts.append("непустая строка")
    if spec.category is None:
        return "n/a (env)"
    return "; ".join(parts)


def _permissions(spec: pc.ParamSpec) -> str:
    if spec.hidden:
        return "UI: скрыт; реестр/права: сохранён"
    if spec.category is None:
        return "n/a (env-only)"
    if spec.category == pc.CATEGORY_KEYS:
        return "view/edit: global_admin (BYOK); raw недоступен"
    if spec.per_chat:
        return "view: role-matrix; edit: local_admin/global_admin"
    return "view: role-matrix; edit: global_admin"


def _scope_inheritance(spec: pc.ParamSpec) -> tuple[str, str]:
    if spec.category is None:
        return "global(infra)", "n/a"
    if spec.per_chat:
        return "global|chat|direct", "global → chat(override)"
    return "global", "global"


def _read_write_api(spec: pc.ParamSpec) -> tuple[str, str]:
    if spec.category is None:
        return "нет API (env-only)", "нет API (env-only)"
    if spec.hidden:
        return "нет API (hidden)", "нет API (hidden)"
    if _is_secret(spec):
        return (
            "GET /api/config (маска {configured,last4}); "
            "GET /api/config/keys/own; GET /api/config/keys/status",
            "PUT /api/config/keys/own; DELETE /api/config/keys/own/{key_name}",
        )
    read = "GET /api/config; GET /api/config/params-meta"
    if spec.per_chat:
        write = ("POST /api/config (X-Chat-Id); "
                 "DELETE /api/config/chat/{key} (сброс override)")
    else:
        write = "POST /api/config"
    return read, write


def _old_screen(spec: pc.ParamSpec) -> str:
    if spec.category is None:
        return ".env (infra)"
    tab = pc.group_tab(spec.group) if spec.group else None
    if tab:
        return pc.CONFIG_TAB_TITLES.get(tab, tab)
    if spec.category == pc.CATEGORY_CONTENT:
        return "Справка (legacy info-content)"
    return "(нет вкладки)"


def _new_screen(spec: pc.ParamSpec) -> str:
    if spec.category is None:
        return ".env (инфраструктура, вне UI)"
    tab = pc.group_tab(spec.group) if spec.group else None
    if tab:
        nav = pc.tab_nav(tab)
        if nav in NEW_SCREEN_BY_NAV:
            return NEW_SCREEN_BY_NAV[nav]
    if spec.category == pc.CATEGORY_CONTENT:
        return "Справка"
    if spec.category == pc.CATEGORY_MEMORY:
        return "Память"
    if spec.category in (pc.CATEGORY_PROMPTS, pc.CATEGORY_MODELS,
                         pc.CATEGORY_KEYS):
        return "ИИ"
    return "Модули"


def _ui_visibility(spec: pc.ParamSpec) -> str:
    """visible | hidden | api-only. `api-only` — есть в каталоге/env, но UI-места
    нет (≠ сохранено в UI; D3/REQ-F8-08)."""
    if spec.hidden:
        return "hidden"
    if spec.category is None:
        return "api-only"
    return "visible"


def _storage(spec: pc.ParamSpec, inv: dict | None) -> str:
    if inv and inv.get("storage"):
        return inv["storage"]
    if spec.category is None:
        return "env/.env"
    if spec.per_chat:
        return "bot_settings + chat_profiles.chat_params.overrides"
    return "bot_settings"


# ── Построение реестра ──────────────────────────────────────────────────────

def build_rows() -> list[dict]:
    """Все 459 записей каталога, отсортированные по internal_key (pg_key)."""
    inventory = _read_inventory()
    rows: list[dict] = []
    for spec in sorted(pc.REGISTRY.values(), key=lambda s: s.pg_key):
        inv = inventory.get(spec.pg_key)
        read_api, write_api = _read_write_api(spec)
        scope, inheritance = _scope_inheritance(spec)
        rows.append({
            "internal_key": spec.pg_key,
            "display_name": _clean(spec.title_ru),
            "description": _clean(spec.description) or "-",
            "data_type": spec.type,
            "current_value": SECRET_MASK if _is_secret(spec) else RUNTIME_VALUE,
            "default_value": _default_value(spec),
            "scope": scope,
            "inheritance": inheritance,
            "read_api": read_api,
            "write_api": write_api,
            "validation": _validation(spec),
            "permissions": _permissions(spec),
            "category": spec.category or "infra",
            "group": spec.group or "-",
            "per_chat": "true" if spec.per_chat else "false",
            "secret": "true" if _is_secret(spec) else "false",
            "hidden": "true" if spec.hidden else "false",
            "ui_visibility": _ui_visibility(spec),
            "widget": spec.widget or "-",
            "storage": _storage(spec, inv),
            "runtime_consumer": (inv or {}).get("runtime_consumer")
            or "ConfigCache / hot.get|get_chat_param",
            "read_fn": (inv or {}).get("read_fn") or "hot.get|get_chat_param",
            "status": "new" if inv is None else ((inv.get("status") or "OK")),
        })
    return rows


def render_tsv(rows: list[dict]) -> str:
    """Детерминированный TSV: header + строки, сортировка по internal_key, LF."""
    lines = ["\t".join(TSV_COLUMNS)]
    for row in rows:
        lines.append("\t".join(_clean(row[c], 500) for c in TSV_COLUMNS))
    return "\n".join(lines) + "\n"


_SCREEN_COLUMNS = (
    "old_screen", "param_key", "new_screen", "read_api", "write_api",
    "ui_visibility", "secret", "hidden", "status",
)


def build_screen_rows() -> list[dict]:
    """Карта экранов: строка на каждый из 459 ключей (D3/REQ-F8-04/05/06)."""
    inventory = _read_inventory()
    out: list[dict] = []
    for spec in sorted(pc.REGISTRY.values(), key=lambda s: s.pg_key):
        read_api, write_api = _read_write_api(spec)
        out.append({
            "old_screen": _old_screen(spec),
            "param_key": spec.pg_key,
            "new_screen": _new_screen(spec),
            "read_api": read_api,
            "write_api": write_api,
            "ui_visibility": _ui_visibility(spec),
            "secret": "true" if _is_secret(spec) else "false",
            "hidden": "true" if spec.hidden else "false",
            "status": "new" if spec.pg_key not in inventory
            else ((inventory[spec.pg_key].get("status") or "OK")),
        })
    return out


def render_screen_map(rows: list[dict] | None = None) -> str:
    """Карта экранов (D3): old_screen → param_key → new_screen → read/write → ui_visibility."""
    if rows is None:
        rows = build_screen_rows()
    head = [
        "# F8 — Карта экранов `screen-map-round1025.md` (ADR-1025-21 D3)",
        "",
        "> Сгенерировано `tools/gen_param_registry_round1025.py` (read-only). "
        "Провенанс — `param-registry-round1025.meta.md`.",
        "> Инвариант «ни один параметр не остался без нового места»: "
        "`set(param_key) ⊇ REGISTRY(459)`, «без места» = 0. "
        "Неизвестные ключи (нет в каталоге) → секция `registry-only` реестра.",
        "> `ui_visibility ∈ {visible,hidden,api-only}`; **api-only ≠ сохранено** "
        "(REQ-F8-08). Секреты без открытого значения (R17).",
        "",
        "| " + " | ".join(_SCREEN_COLUMNS) + " |",
        "|" + "---|" * len(_SCREEN_COLUMNS),
    ]
    for row in rows:
        head.append("| " + " | ".join(
            _clean(row[c], 300) for c in _SCREEN_COLUMNS) + " |")
    # registry-only: ключи карты ⊇ REGISTRY; неизвестных нет (каталог — источник).
    head += [
        "",
        "## registry-only (неизвестные каталогу параметры)",
        "",
        "Нет: множество `internal_key` каталога == множество `REGISTRY` == 459; "
        "все ключи получили новое место. Расхождений нет.",
        "",
    ]
    return "\n".join(head)


def render_meta(rows: list[dict]) -> str:
    """Провенанс вне TSV (D2): HEAD/APP_VERSION/счётчики/дельта, без значений."""
    delta = sorted(r["internal_key"] for r in rows if r["status"] == "new")
    inv_count = len(rows) - len(delta)
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip() or "-"
    except Exception:
        head = "-"
    lines = [
        "# F8 — `param-registry-round1025` — провенанс `.meta.md`",
        "",
        f"- **APP_VERSION:** `{APP_VERSION}`",
        f"- **HEAD (short):** `{head}`",
        f"- **Источник:** `services/param_catalog.py` (REGISTRY/GROUPS/"
        f"_TAB_BY_GROUP/TAB_RULES) + `inventory.tsv` (10.14) для дельты.",
        f"- **Счётчики каталога:** REGISTRY **{len(pc.REGISTRY)}** / "
        f"GROUPS **{len(pc.GROUPS)}** / `_TAB_BY_GROUP` **{len(pc._TAB_BY_GROUP)}** / "
        f"TAB_RULES **{len(pc.TAB_RULES)}**.",
        f"- **Реестр:** {len(rows)} строк == REGISTRY.",
        f"- **inventory.tsv (10.14):** {inv_count} baseline-ключей.",
        f"- **Дельта 411 → 459 = {len(delta)}** новых ключей (`status=new`).",
        "- **Команда генерации:** "
        "`python tools/gen_param_registry_round1025.py`",
        "- **Проверка (маркер):** "
        "`python tools/gen_param_registry_round1025.py --check`",
        "",
        "## Схема реестра (TSV)",
        "",
        "`" + " | ".join(TSV_COLUMNS) + "`",
        "",
        "## Семантика (R17-safe)",
        "",
        f"- `current_value`: `{RUNTIME_VALUE}` — значение живёт в bot_settings/"
        "scope рантайма и статически не экспортируется; читается через `read_api`.",
        f"- `current_value`/`default_value` для `secret=true`/`category=keys`: "
        f"только `{SECRET_MASK}` (R17); открытое значение НИГДЕ не выводится.",
        "- `default_value`: `code:<module.attr>` для промптов (код-канон) | "
        "`-` для прочих (дефолт живёт в `Settings`/PG-сиде и env-зависим, "
        "поэтому в committed-артефакт не экспортируется — детерминизм).",
        "- `-` = поле неприменимо/отсутствует (документированное отсутствие).",
        "- `ui_visibility=api-only` — ключ существует (env/каталог), но UI-места "
        "нет → **не** считается сохранённым в UI.",
        "",
        "## Дельта 411 → 459 = %d (ключи, отсутствовавшие в inventory.tsv)"
        % len(delta),
        "",
    ]
    lines += [f"- `{k}`" for k in delta]
    lines += [
        "",
        "## Инварианты (Δ=0)",
        "",
        "- **Δ каталога = 0:** генератор только читает `param_catalog`.",
        "- **Δ DDL = 0:** БД/схема не затрагиваются.",
        "- **R17:** секреты — только форма `{configured,last4}`.",
        "- **Аддитивность:** артефакты новые, существующие контракты не менялись.",
        "",
    ]
    return "\n".join(lines)


# ── R17-скан артефактов ─────────────────────────────────────────────────────

def _dotenv_values() -> dict[str, str]:
    """Пары KEY=VALUE из ROOT/.env (read-only; значения только в памяти, R17)."""
    out: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return out
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def collect_secret_values() -> list[tuple[str, str]]:
    """(имя-поля/env, значение) для секретных параметров — ТОЛЬКО в памяти."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    dotenv = _dotenv_values()
    for spec in pc.REGISTRY.values():
        if not _is_secret(spec):
            continue
        candidates = []
        if spec.settings_field and hasattr(settings_obj, spec.settings_field):
            candidates.append(("settings:" + spec.settings_field,
                               getattr(settings_obj, spec.settings_field)))
        for holder in (dotenv, os.environ):
            if spec.env_name and holder.get(spec.env_name):
                candidates.append(("env:" + spec.env_name,
                                   holder[spec.env_name]))
        for name, value in candidates:
            if isinstance(value, str) and len(value) >= 6 and value not in seen:
                seen.add(value)
                out.append((name, value))
    return out


def scan_for_open_secrets(text: str) -> list[str]:
    """Имена параметров, чьё открытое значение найдено в `text` (без значений)."""
    return [name for name, value in collect_secret_values() if value in text]


def scan_for_secret_patterns(text: str) -> list[str]:
    """Грубый скан на «похоже на секрет» (belt-and-suspenders)."""
    return [m.group(0) for m in _SECRET_RE.finditer(text)][:5]


# ── CLI ─────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _parse_screen_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in _normalize(text).splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= len(_SCREEN_COLUMNS) and cells[0] not in _SCREEN_COLUMNS:
            keys.add(cells[1])
    return keys


def run_check() -> int:
    problems: list[str] = []
    rows = build_rows()
    expected_tsv = render_tsv(rows)
    expected_screen = render_screen_map()

    if not TSV_PATH.exists():
        problems.append(f"нет committed-файла {TSV_PATH.relative_to(ROOT)}")
    elif _normalize(TSV_PATH.read_text(encoding="utf-8")) != expected_tsv:
        problems.append("TSV расходится с каталогом (устарел/правлен вручную)")

    if not SCREEN_PATH.exists():
        problems.append(f"нет committed-файла {SCREEN_PATH.relative_to(ROOT)}")
    else:
        committed = _normalize(SCREEN_PATH.read_text(encoding="utf-8"))
        if committed != expected_screen:
            problems.append("screen-map расходится с каталогом")
        map_keys = _parse_screen_keys(committed)
        reg_keys = {r["internal_key"] for r in rows}
        missing = reg_keys - map_keys
        if missing:
            problems.append(
                "параметры без нового места: %d (пример: %s)"
                % (len(missing), sorted(missing)[:3]))

    if not WIDGET_PATH.exists():
        problems.append(f"нет committed-файла {WIDGET_PATH.relative_to(ROOT)}")
    else:
        wtext = WIDGET_PATH.read_text(encoding="utf-8")
        if "widget-map-round1025" not in wtext:
            problems.append("widget-map: отсутствует маркер round1025")

    # R17: артефакты не должны содержать открытых секретов.
    artifacts = []
    for p in (TSV_PATH, SCREEN_PATH, META_PATH, WIDGET_PATH):
        if p.exists():
            artifacts.append(p.read_text(encoding="utf-8"))
    blob = "\n".join(artifacts)
    leaks = scan_for_open_secrets(blob)
    if leaks:
        problems.append("R17: открытые секреты в артефактах: %s" % ", ".join(leaks))

    if problems:
        print("CHECK FAILED:")
        for p in problems:
            print("  - " + p)
        return 1
    print("CHECK OK: реестр %d == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны."
          % len(rows))
    return 0


def run_emit() -> int:
    rows = build_rows()
    _write(TSV_PATH, render_tsv(rows))
    _write(SCREEN_PATH, render_screen_map())
    _write(META_PATH, render_meta(rows))
    delta = sum(1 for r in rows if r["status"] == "new")
    print("EMIT OK: %s (%d строк; дельта 411→%d=%d)"
          % (TSV_PATH.relative_to(ROOT), len(rows), len(rows), delta))
    print("EMIT OK: %s" % SCREEN_PATH.relative_to(ROOT))
    print("EMIT OK: %s" % META_PATH.relative_to(ROOT))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="F8 read-only генератор реестра/карты экранов (ADR-1025-21 D2)")
    parser.add_argument("--check", action="store_true",
                        help="не писать; exit≠0 при расхождении с committed-артефактом")
    args = parser.parse_args(argv)
    return run_check() if args.check else run_emit()


if __name__ == "__main__":
    raise SystemExit(main())
