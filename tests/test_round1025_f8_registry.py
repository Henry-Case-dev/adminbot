"""F8 round 10.25 — маркер-тесты реестра/карт/сохранности (T-3011/T-3012, ADR-1025-21 D6).

Доказывают (read-only enabler):
  * полноту реестра: `{internal_key}` == REGISTRY == 459; пустых ячеек нет;
  * дельту 411 → 459 = 48 (перечислена явно, `status=new`);
  * отсутствие открытых секретов во всех артефактах F8 (R17);
  * идемпотентность генератора `--check` (и детект искусственного расхождения);
  * карту экранов: 0 параметров «без нового места»; `api-only` помечены;
  * карту виджетов: присутствует, покрывает обязательные виджеты, `api-only` выделен;
  * diff по 8 срезам без реальных изменений; классификатор/R17-маску;
  * инварианты: Δ DDL=0, Δ каталога=0, роуты `web/api/routes.py` и `APP_VERSION`
    не изменены, `tools/*` не импортируются рантаймом (read-only/CSP).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402
import tools.config_snapshot_diff as csd  # noqa: E402
from services import param_catalog as pc  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "round1025" / "f8_baseline.json")
    .read_text(encoding="utf-8"))
CATALOG_BASELINE = json.loads(
    (ROOT / "tests" / "fixtures" / "round1025" / "catalog_baseline.json")
    .read_text(encoding="utf-8"))
INVENTORY = ROOT / "plans" / "archive" / "settings-persistence-audit-round1014" / "inventory.tsv"
ARTIFACTS = [ROOT / p for p in FIXTURE["artifacts"]]

# F11 (ADR-1025-23 D6) + L-F11S-1: строгий byte-freeze `web/api/routes.py`
# восстановлен НОВЫМ baseline-хэшем F11 (исторический fixture
# `tests/fixtures/round1025/f8_baseline.json` НЕ меняется — L-F9S-4).
# Хэш покрывает только АДДИТИВНЫЕ изменения F11:
#   * env-only `UI_STATUS_GRID_V2` в `/api/me.ui_flags` (bool);
#   * аддитивное поле `counts` в `/api/status/logs` (H-F11S-1).
# Ни новых endpoint'ов, ни изменений схемы/каталога (`test_routes_set_unchanged`
# и `test_param_catalog_unchanged` продолжают замораживать свои срезы).
ROUTES_SHA256_F11 = (
    "76bcab3c96fec5c55c4f8ec4e50b30593fd91b98ca6322270c3a71dca5653306")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry_keys() -> set[str]:
    return {s.pg_key for s in pc.REGISTRY.values()}


def _inventory_keys() -> set[str]:
    keys = set()
    for i, line in enumerate(INVENTORY.read_text(encoding="utf-8").splitlines()):
        if i == 0:
            continue
        cells = line.split("\t")
        if len(cells) > 2 and cells[2]:
            keys.add(cells[2])
    return keys


def _read_registry_rows() -> list[dict]:
    lines = (ROOT / FIXTURE["artifacts"][0]).read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


def _parse_screen_keys() -> set[str]:
    text = (ROOT / "plans/docs/screen-map-round1025.md").read_text(encoding="utf-8")
    keys = set()
    for line in text.replace("\r\n", "\n").splitlines():
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 9 and cells[0] != "old_screen":
            keys.add(cells[1])
    return keys


# ── Δ каталога = 0 / Δ DDL = 0 / роуты / версия ─────────────────────────────

class TestFrozenInvariants:
    def test_param_catalog_unchanged(self):
        assert _sha256(ROOT / "services/param_catalog.py") == \
            FIXTURE["sha256"]["services/param_catalog.py"]

    def test_ddl_source_unchanged(self):
        assert _sha256(ROOT / "services/pg_db.py") == \
            FIXTURE["sha256"]["services/pg_db.py"]

    def test_routes_file_unchanged(self):
        # F11 (ADR-1025-23 D6 + L-F11S-1): строгий byte-freeze восстановлен.
        # Исторический fixture `f8_baseline.json` НЕ меняется (L-F9S-4), поэтому
        # новый baseline-хэш F11 зафиксирован константой `ROUTES_SHA256_F11`
        # (едва выше). Изменения F11 — строго аддитивные (kill-switch bool +
        # поле `counts` в существующем эндпоинте), новых endpoint'ов нет.
        assert _sha256(ROOT / "web/api/routes.py") == ROUTES_SHA256_F11, (
            "web/api/routes.py изменился вне аддитивных правок F11 — "
            "обновите baseline осознанно (L-F11S-1)")

    def test_counts_frozen(self):
        assert len(pc.REGISTRY) == FIXTURE["counts"]["REGISTRY"] == 459
        assert len(pc.GROUPS) == FIXTURE["counts"]["GROUPS"] == 98
        assert len(pc._TAB_BY_GROUP) == FIXTURE["counts"]["TAB_BY_GROUP"] == 96
        assert len(pc.TAB_RULES) == FIXTURE["counts"]["TAB_RULES"] == 21

    def test_registry_keys_match_catalog_baseline(self):
        # F1-baseline фиксирует ключи REGISTRY (settings_field/env), не pg_key.
        assert set(pc.REGISTRY.keys()) == set(CATALOG_BASELINE["registry_keys"])

    def test_app_version_recorded(self):
        # L-F9S-3: маркер F8 не ослабляется. Fixture — исторический baseline
        # F8 (2.58.15, файл не менялся), а текущая версия пинится СТРОГО
        # (F11/ADR-1025-23 D6 поднял 2.58.16 → 2.58.17; без `>=`-послабления).
        assert FIXTURE["app_version"] == "2.58.15"
        from config.settings import APP_VERSION
        assert APP_VERSION == "2.58.17"

    def test_routes_set_unchanged(self):
        import re
        txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
        routes = sorted(set(re.findall(
            r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', txt)))
        assert routes == FIXTURE["routes"]

    def test_tools_not_imported_by_runtime(self):
        """Read-only: рантайм-модули не импортируют `tools/*` (CSP/zero-build)."""
        for sub in ("services", "web", "handlers"):
            for path in (ROOT / sub).rglob("*.py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                # Запрещены только F8-инструменты (прочие `tools/*` — легаси).
                for token in FIXTURE["runtime_import_forbidden"]:
                    assert token not in text, f"{path}: импорт {token}"


# ── Реестр: полнота / дельта / R17 ──────────────────────────────────────────

class TestRegistry:
    def test_rows_complete_no_empty(self):
        rows = _read_registry_rows()
        assert len(rows) == 459
        assert [r["internal_key"] for r in rows] == sorted(_registry_keys())
        assert all(v != "" for r in rows for v in r.values())
        assert len(rows[0]) == len(gen.TSV_COLUMNS) == 23

    def test_delta_48_explicit(self):
        delta = _registry_keys() - _inventory_keys()
        assert len(delta) == FIXTURE["counts"]["delta"] == 48
        new_rows = {r["internal_key"] for r in _read_registry_rows()
                    if r["status"] == "new"}
        assert new_rows == delta

    def test_secret_rows_masked(self):
        rows = _read_registry_rows()
        secret_rows = [r for r in rows if r["secret"] == "true"]
        assert len(secret_rows) == 28
        for row in secret_rows:
            assert row["current_value"] == gen.SECRET_MASK
            assert row["default_value"] == gen.SECRET_MASK

    def test_hidden_key_preserved(self):
        rows = _read_registry_rows()
        hidden = [r for r in rows if r["hidden"] == "true"]
        assert len(hidden) == 1
        assert hidden[0]["internal_key"] == "limits.factcheck_context_messages"
        # hidden сохранён в реестре/правах, но вне UI.
        assert hidden[0]["ui_visibility"] == "hidden"

    def test_no_open_secrets_in_artifacts(self):
        blob = "\n".join(p.read_text(encoding="utf-8") for p in ARTIFACTS)
        assert gen.scan_for_open_secrets(blob) == []

    def test_meta_provenance(self):
        meta = (ROOT / "plans/docs/param-registry-round1025.meta.md").read_text(
            encoding="utf-8")
        assert "459" in meta and "411" in meta and "48" in meta
        assert FIXTURE["app_version"] in meta


# ── Карта экранов ───────────────────────────────────────────────────────────

class TestScreenMap:
    def test_all_params_have_a_place(self):
        keys = _parse_screen_keys()
        assert keys == _registry_keys()  # ⊇ и == (каталог — источник)
        assert len(keys) == 459

    def test_no_empty_new_screen(self):
        text = (ROOT / "plans/docs/screen-map-round1025.md").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("| ") and not line.startswith("| old_screen"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 9:
                    assert cells[2], "пустое новое место: %s" % cells[1]

    def test_ui_visibility_domain(self):
        text = (ROOT / "plans/docs/screen-map-round1025.md").read_text(encoding="utf-8")
        values = set()
        for line in text.splitlines():
            if line.startswith("| ") and not line.startswith("| old_screen"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 9:
                    values.add(cells[5])
        assert values <= {"visible", "hidden", "api-only"}
        assert "api-only" in values  # 25 env-only ключей помечены


# ── Карта виджетов ──────────────────────────────────────────────────────────

class TestWidgetMap:
    def test_marker_and_required_widgets(self):
        text = (ROOT / "plans/docs/widget-map-round1025.md").read_text(encoding="utf-8")
        assert "widget-map-round1025" in text
        for marker in ("Граф связей", "Логи", "Живая лента досье",
                       "Мониторинг интеллекта", "Карта LLM-вызовов",
                       "Системные метрики", "Живое сердцебиение"):
            assert marker in text, marker

    def test_api_only_section_present(self):
        text = (ROOT / "plans/docs/widget-map-round1025.md").read_text(encoding="utf-8")
        assert "api-only" in text
        assert "/api/debug/config" in text
        assert "≠ сохранено" in text


# ── Генератор: идемпотентность --check + детект расхождения ─────────────────

class TestGeneratorIdempotency:
    def test_check_passes_on_committed(self):
        assert gen.run_check() == 0

    def test_check_subprocess_exit_zero(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools/gen_param_registry_round1025.py"),
             "--check"], cwd=str(ROOT), capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_check_detects_tsv_mismatch(self, monkeypatch, tmp_path):
        bogus = tmp_path / "param-registry-round1025.tsv"
        bogus.write_text("internal_key\tbogus\n", encoding="utf-8", newline="\n")
        monkeypatch.setattr(gen, "TSV_PATH", bogus)
        assert gen.run_check() != 0

    def test_check_detects_screen_mismatch(self, monkeypatch, tmp_path):
        bogus = tmp_path / "screen-map-round1025.md"
        bogus.write_text("# bogus\n", encoding="utf-8", newline="\n")
        monkeypatch.setattr(gen, "SCREEN_PATH", bogus)
        assert gen.run_check() != 0


# ── Snapshot-diff: 8 срезов, 0 изменений ────────────────────────────────────

class TestSnapshotDiff:
    def test_selftest(self):
        assert csd.run_selftest() == 0

    def test_no_changes_on_identical_snapshots(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        csd.emit_baseline(before)
        csd.emit_baseline(after)
        result = csd.diff_dirs(before, after)
        assert set(result) == set(csd.SLICES)
        total = {k: sum(len(result[s][k]) for s in csd.SLICES)
                 for k in ("added", "removed", "changed")}
        assert total == {"added": 0, "removed": 0, "changed": 0}

    def test_classifier_detects_real_changes(self):
        got = csd.classify({"a": "1", "b": "2"}, {"a": "1", "c": "3"})
        assert got == {"added": ["c"], "removed": ["b"],
                       "changed": [], "unchanged": ["a"]}

    def test_report_has_all_slices(self):
        result = {s: {"added": [], "removed": [], "changed": [],
                      "unchanged": []} for s in csd.SLICES}
        report = csd.render_report(result, "test")
        for s in csd.SLICES:
            assert f"| {s} |" in report
        assert "0" in report

    def test_safe_value_masks_secret_like(self):
        assert csd.safe_value("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ012345") == \
            csd.SECRET_MASK
        assert csd.safe_value("plain-value") == "plain-value"

    def test_committed_report_exists(self):
        report = (ROOT / "plans/reports/round1025_f8_config_diff.md").read_text(
            encoding="utf-8")
        for s in csd.SLICES:
            assert f"| {s} |" in report
