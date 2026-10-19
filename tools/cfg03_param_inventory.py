"""CFG-03 Ф1 — машинный инвентарь 579 параметров MiniApp по 11-звенной цепочке.

Chain (CFG-03.M): UI-экран/контрол → Registry ID/тип/границы/Factory Default →
scope/наследование → API read/write → DB → кэш/уведомления → effective resolver →
фактический runtime consumer → observable behavior → тест/доказательство.

Что делает (read-only; единственные записи — отчётные файлы в --out):
  * читает REGISTRY/GROUPS/TAB_RULES из services.param_catalog (истина);
  * читает артефакты реестра (TSV 23 колонки) и карту экранов (screen-map);
  * однопроходно индексирует runtime-код (bot.py, config/, handlers/,
    services/, web/ (+app.js/index.html/static JS), filters/, scripts/,
    SmartModule/) — строковые литералы и идентификаторы (комментарии
    вырезаются, чтобы упоминание в комментарии не считалось потребителем);
  * для каждого ключа вычисляет static-потребителей:
      - literal pg_key (в коде, не в комментарии),
      - settings-поле (идентификатор или строковый литерал),
      - env-имя,
      - динамические шаблоны `f"<cat>.{var}<suffix>"` + литерал слага
        (прецеденты: user_relations._limit, llm_client._worker_profile,
        model_slots) — отдельная метка `dynamic`;
      - читатели-диагностики (debug_config/status_service/manage.py) — метка
        `diagnostic`;
  * метка declared ≠ verified: колонка TSV runtime_consumer у 168 новых
    ключей — шаблон-заглушка, не доказательство (prep-cfg-03 §3.1);
  * классифицирует по матрице CFG-03.2 (13 классов) консервативно;
  * собирает UI_missing / сирот / несогласованности (ключи/группы/подписи/
    дефолты/select/типы) и env-only потолки (CFG-03.7);
  * собирает ссылки на тесты (tests/**) как звено «тест/доказательство» R1.

Использование:
    python tools/cfg03_param_inventory.py --out plans/features/cfg/evidence/cfg-03
    python tools/cfg03_param_inventory.py --out <scratch> --quiet
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import Settings  # noqa: E402
from services import param_catalog as pc  # noqa: E402

RUNTIME_DIRS = ("config", "handlers", "services", "web", "filters", "scripts",
                "SmartModule")
RUNTIME_ROOT_FILES = ("bot.py", "manage.py")
WEB_EXTRA = ("web/app.js", "web/index.html")
WEB_JS_GLOB = ("web/static/*.js",)

# Файлы, где встречается сам каталог/его экспорт — не считаются потребителями
# настройки (это определение/миграция, а не runtime-чтение значения).
_NON_CONSUMER_FILES = {
    "services/param_catalog.py",
    "scripts/migrate_env_to_pg.py",
}

# Диагностические читатели каталога (CFG-03.7: диагностика администратору).
# Только «чистые» диагностические поверхности: их чтение — не runtime-потребитель
# значения. Сейчас пусто по факту (debug_config читает spec.settings_field
# generically и пер-параметровых хитов не создаёт) — оставлено как механизм.
_DIAGNOSTIC_FILES: set[str] = set()

LITERAL_RE = re.compile(r'"([^"\n]{1,120})"|\'([^\'\n]{1,120})\'')
IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
DYN_TEMPLATE_RE = re.compile(
    r"""f["']([A-Za-z0-9_.]*)\{([A-Za-z_]\w*)\}([A-Za-z0-9_.]*)["']""")

CLASSES = (
    "working", "save_only", "runtime_not_consumed", "wrong_scope",
    "stale_cache", "restart_required", "invalid_default", "UI_missing",
    "UI_present_but_not_discoverable", "effective_value_mismatch",
    "inaccessible", "duplicate_conflict", "unknown",
)

# Документированные специальные экраны (не config-вкладки):
#  * «Справка» (#/info) — группы content_* без вкладки (prep-cfg-03 §1.1);
#  * synthetic-группы app.js (`_syntheticGroup(category, gid)`) — сейчас
#    только content_media в окне модуля mod_video_summary (app.js:3154-3159,
#    3390-3394); наличие проверяется по факту в web/app.js.
SPECIAL_SCREEN_GROUPS = {
    "content_info": "#/info (Справка)",
}
SYNTHETIC_GROUP_SCREEN = "module:mod_video_summary (synthetic group)"


def _strip_comment_py(line: str) -> str:
    """Грубое вырезание #-комментария (вне кавычек — по прецеденту строк)."""
    in_s = in_d = False
    prev = ""
    for i, ch in enumerate(line):
        if ch == "'" and not in_d and prev != "\\":
            in_s = not in_s
        elif ch == '"' and not in_s and prev != "\\":
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
        prev = ch
    return line


def _strip_comment_js(line: str) -> str:
    in_s = in_d = False
    prev = ""
    for i, ch in enumerate(line):
        if ch == "'" and not in_d and prev != "\\":
            in_s = not in_s
        elif ch == '"' and not in_s and prev != "\\":
            in_d = not in_d
        elif ch == "/" and not in_s and not in_d and i + 1 < len(line) \
                and line[i + 1] == "/":
            return line[:i]
        prev = ch
    return line


def _runtime_files() -> list[Path]:
    files: list[Path] = []
    for name in RUNTIME_ROOT_FILES:
        p = ROOT / name
        if p.exists():
            files.append(p)
    for d in RUNTIME_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    for rel in WEB_EXTRA:
        p = ROOT / rel
        if p.exists():
            files.append(p)
    for pattern in WEB_JS_GLOB:
        files.extend(sorted(ROOT.glob(pattern)))
    return files


def _test_files() -> list[Path]:
    return sorted((ROOT / "tests").rglob("*.py")) + \
        sorted((ROOT / "tests" / "js").glob("*.js"))


def build_index(files: list[Path]) -> tuple[dict, dict, list, set, dict]:
    """(literals, idents, dyn_templates, all_literals_set, file_literals)."""
    literals: dict[str, list] = {}
    idents: dict[str, list] = {}
    dyn_templates: list[tuple] = []
    all_literals: set[str] = set()
    file_literals: dict[str, set] = {}
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        is_js = path.suffix in (".js", ".html")
        fset: set = set()
        for i, raw in enumerate(text.splitlines(), 1):
            line = _strip_comment_js(raw) if is_js else _strip_comment_py(raw)
            for m in LITERAL_RE.finditer(line):
                lit = m.group(1) or m.group(2)
                literals.setdefault(lit, []).append((rel, i, line.strip()))
                all_literals.add(lit)
                fset.add(lit)
            for m in IDENT_RE.finditer(line):
                idents.setdefault(m.group(1), []).append((rel, i, line.strip()))
            for m in DYN_TEMPLATE_RE.finditer(line):
                dyn_templates.append((m.group(1), m.group(2), m.group(3),
                                      rel, i))
        file_literals[rel] = fset
    return literals, idents, dyn_templates, all_literals, file_literals


def _load_registry_tsv() -> dict[str, dict]:
    tsv = ROOT / "plans/docs/param-registry-round1025.tsv"
    lines = tsv.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    out: dict[str, dict] = {}
    for line in lines[1:]:
        cells = line.split("\t")
        row = dict(zip(header, cells))
        out[row["internal_key"]] = row
    return out


def _load_screen_map() -> dict[str, dict]:
    text = (ROOT / "plans/docs/screen-map-round1025.md").read_text(encoding="utf-8")
    out: dict[str, dict] = {}
    for line in text.replace("\r\n", "\n").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 9 and cells[0] != "old_screen":
            out[cells[1]] = {
                "old_screen": cells[0], "new_screen": cells[2],
                "read_api": cells[3], "write_api": cells[4],
                "ui_visibility": cells[5], "secret": cells[6],
                "hidden": cells[7], "status": cells[8],
            }
    return out


def _settings_field_info(field: str | None) -> dict:
    if not field:
        return {"exists": False, "kind": "none", "annotation": None,
                "default": None}
    info: dict = {"exists": hasattr(Settings, field), "kind": "missing",
                  "annotation": None, "default": None}
    if not info["exists"]:
        return info
    dc_fields = {f.name: f for f in dataclasses.fields(Settings)}
    ann = getattr(Settings, "__annotations__", {}).get(field)
    info["annotation"] = str(ann)
    if field in dc_fields:
        info["kind"] = "dataclass_field"
    else:
        info["kind"] = "classvar" if "ClassVar" in str(ann) else "class_attr"
    info["default"] = getattr(Settings, field, None)
    return info


def _expected_py_type(spec_type: str, annotation: str | None = None) -> tuple:
    base = {
        "str": ("str",),
        "int": ("int",),
        "float": ("float", "int"),
        "bool": ("bool",),
        "json": ("str", "list", "dict", "tuple", "NoneType"),
    }.get(spec_type, ())
    if annotation and "None" in annotation:
        base = base + ("NoneType",)
    return base


def _select_default_problem(spec: pc.ParamSpec) -> str | None:
    if spec.widget != "select" or not spec.select_options:
        return None
    info = _settings_field_info(spec.settings_field)
    if not info["exists"] or info["default"] is None:
        return None
    sval = str(info["default"])
    if sval not in spec.select_options:
        return f"default={sval!r} not in options={spec.select_options!r}"
    return None


def _is_definition_line(rel: str, field: str | None, env: str | None,
                        line: str) -> bool:
    """Строка-объявление поля Settings (не считается потребителем)."""
    if rel != "config/settings.py":
        return False
    s = line.strip()
    if field and (s.startswith(field + ":") or s.startswith(field + " :")):
        return True
    if env and (s.startswith(f'"{env}"') or s.startswith(f"'{env}'")):
        return True
    return False


def audit() -> dict:
    files = _runtime_files()
    literals, idents, dyn_templates, all_literals, file_literals = \
        build_index(files)
    test_literals, _, _, _, _ = build_index(_test_files())
    tsv = _load_registry_tsv()
    screen = _load_screen_map()

    app_js = (ROOT / "web/app.js").read_text(encoding="utf-8")
    synthetic_groups = set(re.findall(
        r"_syntheticGroup\(\s*'([a-z_]+)'\s*,\s*'([a-z_]+)'\s*\)", app_js))
    docker_text = ""
    _dc = ROOT / "docker-compose.yml"
    if _dc.exists():
        docker_text = _dc.read_text(encoding="utf-8", errors="ignore")

    group_ids = {g.id for g in pc.GROUPS}
    groups_by_id = {g.id: g for g in pc.GROUPS}
    tab_by_group = dict(pc._TAB_BY_GROUP)

    keys_slot_groups: set[str] = set()
    for _tid, rules in pc.TAB_RULES:
        for _cat, _sel in rules:
            if _cat == pc.CATEGORY_KEYS and isinstance(_sel, frozenset):
                keys_slot_groups |= set(_sel)

    entries: list[dict] = []
    ui_missing: list[dict] = []
    inconsistencies: list[dict] = []
    no_consumer: list[dict] = []
    dynamic_consumers: list[dict] = []
    diagnostic_only: list[dict] = []
    group_param_count: dict[str, int] = {}
    used_settings_fields: dict[str, list[str]] = {}

    for key, spec in sorted(pc.REGISTRY.items()):
        pg_key = spec.pg_key
        row = tsv.get(pg_key, {})
        scr = screen.get(pg_key, {})
        field = spec.settings_field
        env = spec.env_name
        field_info = _settings_field_info(field)

        lit_hits = [(rel, ln, txt) for rel, ln, txt in literals.get(pg_key, [])
                    if rel not in _NON_CONSUMER_FILES]
        field_hits = []
        if field:
            field_hits = [(rel, ln, txt)
                          for rel, ln, txt in literals.get(field, [])
                          if rel not in _NON_CONSUMER_FILES
                          and not _is_definition_line(rel, field, env, txt)]
            field_hits += [(rel, ln, f"ident {field}")
                           for rel, ln, txt in idents.get(field, [])
                           if rel not in _NON_CONSUMER_FILES
                           and not _is_definition_line(rel, field, env, txt)]
            used_settings_fields.setdefault(field, []).append(key)
        env_hits = []
        if env:
            env_hits = [(rel, ln, txt) for rel, ln, txt in literals.get(env, [])
                        if rel not in _NON_CONSUMER_FILES
                        and not _is_definition_line(rel, field, env, txt)]

        # динамические шаблоны: f"<head>{var}<tail>" + литерал середины
        # (прецеденты: user_relations._limit `limits.{name}`,
        # llm_client._worker_profile `models.{slug}_base_url`,
        # mca_exploration `memory.random_uses_{use}`). Слаг-проверка:
        # середина — литерал В ТОМ ЖЕ файле и похожа на слаг (есть «_» либо
        # длина ≥ 6) — защита от generic-совпадений вида `f"media_{i}"`.
        dyn_hits: list[str] = []
        for head, _var, tail, rel, ln in dyn_templates:
            if not head or not pg_key.startswith(head):
                continue
            if tail and not pg_key.endswith(tail):
                continue
            middle = pg_key[len(head):len(pg_key) - len(tail) if tail else None]
            if not middle or middle not in file_literals.get(rel, set()):
                continue
            if "_" not in middle and len(middle) < 6:
                continue
            dyn_hits.append(
                f"{rel}:{ln} (f\"{head}{{{_var}}}{tail}\" + {middle!r})")

        def _is_diag(h):
            return h[0] in _DIAGNOSTIC_FILES

        runtime_hits = [h for h in lit_hits + field_hits + env_hits
                        if not _is_diag(h)]
        diag_hits = [h for h in lit_hits + field_hits + env_hits if _is_diag(h)]

        if runtime_hits:
            consumer_status = "runtime"
        elif dyn_hits:
            consumer_status = "dynamic"
        elif diag_hits:
            consumer_status = "diagnostic"
        else:
            consumer_status = "none"

        consumer_files = sorted({h[0] for h in runtime_hits} |
                                {h[0] for h in diag_hits})
        read_ctx = [f"{h[0]}:{h[1]}" for h in runtime_hits
                    if any(tok in h[2] for tok in
                           ("hot.get", "get_chat_param", "settings.",
                            "getattr(settings", "resolve_setting"))]
        test_refs = sorted({rel for rel, _ln, _t in test_literals.get(pg_key, [])})
        if not test_refs and field:
            test_refs = sorted({rel for rel, _ln, _t in
                                test_literals.get(field, [])})

        # UI-цепочка
        group = spec.group
        tab = tab_by_group.get(group) if group else None
        special = SPECIAL_SCREEN_GROUPS.get(group)
        synth = (spec.category, group) in synthetic_groups if group else False
        if spec.category is None:
            ui_place = "env/.env (infra, вне UI)"
        elif spec.hidden:
            ui_place = "hidden (ADR-1023-2; вне UI-каталога)"
        elif tab:
            ui_place = f"tab:{tab}"
        elif special:
            ui_place = f"special:{special}"
        elif synth:
            ui_place = SYNTHETIC_GROUP_SCREEN
        else:
            ui_place = None

        ui_visibility = scr.get("ui_visibility", row.get("ui_visibility", "?"))
        if ui_place is None and ui_visibility == "visible":
            ui_missing.append({"key": pg_key, "group": group,
                               "category": spec.category, "title": spec.title_ru})

        if group:
            group_param_count[group] = group_param_count.get(group, 0) + 1

        # consistency
        if spec.category is not None and group not in group_ids:
            inconsistencies.append({"key": pg_key, "kind": "group_not_in_GROUPS",
                                    "group": group})
        elif group and group in groups_by_id and \
                groups_by_id[group].category != spec.category:
            if not (spec.category == pc.CATEGORY_KEYS
                    and group in keys_slot_groups):
                inconsistencies.append({
                    "key": pg_key, "kind": "group_category_mismatch",
                    "group": group,
                    "group_category": groups_by_id[group].category,
                    "param_category": spec.category})
        if spec.type not in ("str", "int", "float", "bool", "json"):
            inconsistencies.append({"key": pg_key, "kind": "bad_type",
                                    "type": spec.type})
        if field and not field_info["exists"]:
            inconsistencies.append({"key": pg_key,
                                    "kind": "settings_field_missing",
                                    "field": field})
        if not spec.title_ru or not spec.title_ru.strip():
            inconsistencies.append({"key": pg_key, "kind": "empty_title"})
        sel_problem = _select_default_problem(spec)
        if sel_problem:
            inconsistencies.append({"key": pg_key, "kind": "select_default",
                                    "detail": sel_problem})
        if field and field_info["exists"] and spec.type != "str":
            val = field_info["default"]
            typ = type(val).__name__
            if typ not in _expected_py_type(spec.type, field_info["annotation"]):
                inconsistencies.append({
                    "key": pg_key, "kind": "default_type_mismatch",
                    "catalog_type": spec.type, "settings_type": typ,
                    "settings_kind": field_info["kind"],
                    "settings_default": repr(val)[:80]})
        if ui_visibility == "visible" and not spec.description and \
                spec.category is not None:
            inconsistencies.append({"key": pg_key,
                                    "kind": "empty_description"})

        if consumer_status == "none" and spec.category is not None:
            no_consumer.append({"key": pg_key, "group": group, "tab": tab,
                                "title": spec.title_ru,
                                "description": spec.description,
                                "storage": row.get("storage", "?")})
        docker_ref = bool(env and consumer_status == "none"
                          and spec.category is None and env in docker_text)
        if consumer_status == "dynamic":
            dynamic_consumers.append({"key": pg_key, "hits": dyn_hits[:3]})
        if consumer_status == "diagnostic":
            diagnostic_only.append({"key": pg_key,
                                    "hits": [f"{h[0]}:{h[1]}" for h in diag_hits][:4]})

        classification = "unknown"
        notes = ""
        if ui_place is None:
            classification = "UI_missing"
        elif spec.category is None:
            classification = "working" if consumer_status != "none" else \
                "runtime_not_consumed"
            notes = "env/infra (вне UI-каталога; документировано)"
            if docker_ref:
                notes = ("env/infra; потребитель вне Python-рантайма "
                         "(docker-compose.yml)")
        elif consumer_status == "none":
            classification = "runtime_not_consumed"
        elif consumer_status == "diagnostic":
            classification = "save_only"
            notes = "потребитель — только диагностика каталога (CFG-03.7)"
        else:
            classification = "working"
            notes = {"runtime": "static read-context" if read_ctx
                     else "static literal/field",
                     "dynamic": "dynamic template"}.get(
                consumer_status, consumer_status)

        entries.append({
            "key": key,
            "pg_key": pg_key,
            "title": spec.title_ru,
            "description": spec.description,
            "type": spec.type,
            "secret": spec.secret,
            "hidden": spec.hidden,
            "category": spec.category,
            "group": group,
            "tab": tab,
            "ui_place": ui_place,
            "ui_visibility": ui_visibility,
            "widget": spec.widget,
            "per_chat": spec.per_chat,
            "settings_field": field,
            "settings_kind": field_info["kind"],
            "env_name": env,
            "code_source": spec.code_source,
            "stage": spec.stage,
            "storage": row.get("storage", "?"),
            "read_api": row.get("read_api", scr.get("read_api", "?")),
            "write_api": row.get("write_api", scr.get("write_api", "?")),
            "declared_consumer": row.get("runtime_consumer", "?"),
            "consumer_status": consumer_status,
            "consumer_files": consumer_files[:12],
            "read_ctx_hits": read_ctx[:6],
            "dyn_hits": dyn_hits[:3],
            "docker_ref": docker_ref,
            "test_refs": test_refs[:6],
            "classification": classification,
            "class_note": notes,
        })

    orphan_groups = [g.id for g in pc.GROUPS if g.id not in group_param_count]
    dup_fields = {f: ks for f, ks in used_settings_fields.items() if len(ks) > 1}

    known_keys = {s.pg_key for s in pc.REGISTRY.values()}
    known_envs = {s.env_name for s in pc.REGISTRY.values() if s.env_name}
    env_read_re = re.compile(
        r"(?:os\.environ(?:\.get)?\(|os\.getenv\(|environ\.get\()"
        r"\s*[\"']([A-Z][A-Z0-9_]{3,})[\"']")
    env_only_ceilings: list[dict] = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel in _NON_CONSUMER_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        is_js = path.suffix in (".js", ".html")
        for i, raw in enumerate(text.splitlines(), 1):
            line = _strip_comment_js(raw) if is_js else _strip_comment_py(raw)
            for m in env_read_re.finditer(line):
                name = m.group(1)
                if name in known_envs or name in known_keys:
                    continue
                env_only_ceilings.append({"env": name, "file": rel, "line": i})

    summary = {
        "registry": len(pc.REGISTRY),
        "groups": len(pc.GROUPS),
        "tab_by_group": len(pc._TAB_BY_GROUP),
        "tab_rules": len(pc.TAB_RULES),
        "ui_missing": len(ui_missing),
        "no_consumer": len(no_consumer),
        "inconsistencies": len(inconsistencies),
        "orphan_groups": len(orphan_groups),
        "dup_settings_fields": len(dup_fields),
        "dynamic_consumers": len(dynamic_consumers),
        "diagnostic_only": len(diagnostic_only),
        "with_test_refs": sum(1 for e in entries if e["test_refs"]),
        "consumer_status_counts": {},
        "classification_counts": {},
        "ui_visibility_counts": {},
    }
    for e in entries:
        for bucket, val in (("consumer_status_counts", e["consumer_status"]),
                            ("classification_counts", e["classification"]),
                            ("ui_visibility_counts", e["ui_visibility"])):
            summary[bucket][val] = summary[bucket].get(val, 0) + 1

    return {
        "entries": entries,
        "ui_missing": ui_missing,
        "no_consumer": no_consumer,
        "inconsistencies": inconsistencies,
        "orphan_groups": orphan_groups,
        "dup_settings_fields": dup_fields,
        "dynamic_consumers": dynamic_consumers,
        "diagnostic_only": diagnostic_only,
        "env_only_ceilings": env_only_ceilings,
        "summary": summary,
    }


def write_reports(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "inventory.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    cols = [
        "pg_key", "title", "type", "category", "group", "tab", "ui_place",
        "ui_visibility", "widget", "per_chat", "settings_field", "env_name",
        "storage", "read_api", "write_api", "consumer_status",
        "classification", "class_note", "test_refs",
    ]
    lines = ["\t".join(cols)]
    for e in result["entries"]:
        row = []
        for c in cols:
            v = e.get(c, "")
            if isinstance(v, list):
                v = ";".join(v[:3])
            row.append(str(v).replace("\t", " ").replace("\n", " "))
        lines.append("\t".join(row))
    (out_dir / "inventory.tsv").write_text("\n".join(lines) + "\n",
                                           encoding="utf-8")

    (out_dir / "audit-summary.json").write_text(
        json.dumps({
            "summary": result["summary"],
            "ui_missing": result["ui_missing"],
            "orphan_groups": result["orphan_groups"],
            "dup_settings_fields": result["dup_settings_fields"],
            "inconsistencies": result["inconsistencies"],
            "no_consumer": result["no_consumer"],
            "dynamic_consumers": result["dynamic_consumers"],
            "diagnostic_only": result["diagnostic_only"],
            "env_only_ceilings": result["env_only_ceilings"][:200],
        }, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    result = audit()
    write_reports(result, Path(args.out))
    if not args.quiet:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=1))
        print("ui_missing:", result["ui_missing"][:20])
        print("no_consumer:", [x["key"] for x in result["no_consumer"]])
        print("inconsistencies:",
              [(x["key"], x["kind"]) for x in result["inconsistencies"]])
        print("orphan_groups:", result["orphan_groups"])
        print("dynamic_consumers:", [x["key"] for x in result["dynamic_consumers"]])
        print("diagnostic_only:", [x["key"] for x in result["diagnostic_only"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
