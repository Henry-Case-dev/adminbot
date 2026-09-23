"""EXTRA round 10.26 `polygonal-luminescence-round1026` (ADR-1026-3) —
атомарные маркеры/инварианты эпика. Поведение рендерера — в
`tests/js/round1026_polygon_background_test.js` (запускается из
`tests/test_webapp_js_unit.py`); здесь — vendor/флаги/CSP/один рендерер/версия.

Инварианты (нарушение = НЕ принято):
  * Δ DDL = 0 (SQLite user_version=12; БД/миграции/`services/**` вне диффа).
  * Δ каталога = 0 (`param_catalog.py` не тронут; флаг — env-only `ClassVar`
    ∉ `pc.REGISTRY`; числа 467/426/442/100/98/21).
  * CSP `script-src 'self'`, zero-build рантайма: vendored same-origin, без CDN.
  * Один активный фоновый рендерер; `aurora-flow.js` сохранён (soft-откат).
"""
import dataclasses
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from config.settings import APP_VERSION, Settings

ROOT = Path(".")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
APP_CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
POLY = (ROOT / "web" / "static" / "polygon-background.js").read_text(
    encoding="utf-8")
AURORA = (ROOT / "web" / "static" / "aurora-flow.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
VENDOR_README = (ROOT / "web" / "static" / "vendor" / "README.md").read_text(
    encoding="utf-8")
DELAUNATOR = ROOT / "web" / "static" / "vendor" / "delaunator.5.0.0.min.js"

FLAG = "UI_POLYGON_BG_ENABLED"
DELAUNATOR_SHA = (
    "7707D7FE750559D4D31DBDEBEA5E41024487520BC1CC9967AC9795B4A682C1BE")


class TestVendor:
    def test_delaunator_artifact_present(self):
        assert DELAUNATOR.exists(), "нет web/static/vendor/delaunator.5.0.0.min.js"

    def test_delaunator_sha256(self):
        digest = hashlib.sha256(DELAUNATOR.read_bytes()).hexdigest().upper()
        assert digest == DELAUNATOR_SHA, digest
        assert DELAUNATOR_SHA in VENDOR_README

    def test_vendor_readme_license(self):
        # ISC-лицензия delaunator 5.0.0 зафиксирована в таблице vendor README.
        row = [l for l in VENDOR_README.splitlines()
               if "delaunator.5.0.0.min.js" in l]
        assert row, "нет строки delaunator в vendor README"
        assert "5.0.0" in row[0] and "ISC" in row[0], row[0]

    def test_package_pin(self):
        pkg = (ROOT / "tools" / "vendor" / "package.json").read_text(
            encoding="utf-8")
        assert '"delaunator": "5.0.0"' in pkg, "delaunator должен быть pinned 5.0.0"
        build = (ROOT / "tools" / "vendor" / "build.mjs").read_text(
            encoding="utf-8")
        assert "delaunator.5.0.0.min.js" in build, "нет esbuild-шага delaunator"
        assert (ROOT / "tools" / "vendor" / ".delaunator-entry.mjs").exists()

    def test_no_cdn_hosts(self):
        srcs = re.findall(r'<script[^>]*\ssrc="([^"]+)"', INDEX)
        for s in srcs:
            assert "http" not in s, "CDN в script: " + s

    def test_script_order(self):
        i_del = INDEX.find("/static/vendor/delaunator.5.0.0.min.js")
        i_aurora = INDEX.find("/static/aurora-flow.js")
        i_poly = INDEX.find("/static/polygon-background.js")
        i_app = INDEX.find("/web/app.js")
        assert -1 < i_del < i_poly < i_app
        assert -1 < i_aurora < i_poly, "aurora-flow.js сохранён до polygon"
        assert "/static/vendor/delaunator.5.0.0.min.js?v=__APP_VERSION__" in INDEX


class TestSingleRenderer:
    def test_polygon_module_and_contract(self):
        for m in ("start", "stop", "pause", "resume", "resize",
                  "getDiagnostics", "mode"):
            assert m in POLY, m
        assert "window.__PolygonBackground" in POLY
        assert "window.__AuroraFlowLegacy" in POLY
        assert "__polygonAdapter" in POLY

    def test_aurora_preserved_for_rollback(self):
        assert "window.__AuroraFlow" in AURORA
        assert "resize: resize" in AURORA  # откатный контракт не тронут
        assert INDEX.find("/static/aurora-flow.js") >= 0

    def test_app_selects_one_renderer(self):
        assert "polygonBgEnabled: function" in APP_JS
        assert "__PolygonBackground" in APP_JS
        assert "_legacyAuroraFlow" in APP_JS
        assert "classList.toggle('polygon-bg'" in APP_JS
        # Aurora/legacy стартуют только при OFF-ветке.
        assert re.search(
            r"if \(polygon\)[\s\S]{0,220}__PolygonBackground\.start\(\)", APP_JS)

    def test_css_single_layer(self):
        m = re.search(r"\.polygon-background-canvas \{([^}]*)\}", APP_CSS)
        assert m
        body = m.group(1)
        assert "position: fixed" in body
        assert "pointer-events: none" in body
        assert "z-index: 0" in body
        assert re.search(r"html\.polygon-bg \.aurora-flow-canvas \{ display: none",
                         APP_CSS)
        assert re.search(r"html\.polygon-bg \.aurora-bg \{ display: none", APP_CSS)
        assert re.search(r"html\.polygon-bg body::before", APP_CSS)

    def test_no_second_height_mechanism(self):
        # Переиспользуется существующий viewport-адаптер: resize приходит из
        # тех же точек, что и _auroraResize (без второго источника высоты).
        assert "_auroraResize();" in APP_JS
        assert POLY.count("ResizeObserver") >= 1


class TestFlagsAndInvariants:
    def test_env_only_flag(self):
        assert f'{FLAG}: ClassVar[bool] = _env_bool(' in SETTINGS
        assert '"' + FLAG + '", True' in SETTINGS, "default ON"
        assert FLAG in ROUTES, "не доставлен в ui_flags"
        assert FLAG in APP_JS, "не читается фронтом"
        assert FLAG in ENV_EXAMPLE, "нет в .env.example"

    def test_flag_not_in_catalog(self):
        from services import param_catalog as pc
        assert FLAG not in pc.REGISTRY, "Δ каталога ≠ 0"

    def test_catalog_invariants(self):
        from services import param_catalog as pc
        # Базовые числа round1026: 467/426/442/100/98/21 — эпик их не меняет.
        assert len(pc.REGISTRY) == 468
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426

    def test_app_version_bumped(self):
        assert APP_VERSION == "2.58.22", APP_VERSION
        assert "v2.58.22" in README, "README не синхронизирован"
        assert 'APP_VERSION = "2.58.22"' in SETTINGS

    def test_zero_ddl(self):
        # Δ DDL = 0: никаких новых таблиц/миграций эпиком не добавляется.
        migrations = list((ROOT / "db").rglob("*.sql")) if (
            ROOT / "db").exists() else []
        for p in migrations:
            assert "polygon" not in p.read_text(encoding="utf-8").lower()

    def test_glass_still_default_off(self):
        assert re.search(
            r'UI_LIQUID_GLASS_LIB: ClassVar\[bool\] = _env_bool\(\s*'
            r'"UI_LIQUID_GLASS_LIB", False\)', SETTINGS)
        glass = (ROOT / "web" / "static" / "glass.js").read_text(encoding="utf-8")
        # Стекло по-прежнему только на изолированном [data-glass-surface],
        # без mountGlass без источника (защита от hotfix10).
        assert "SELECTOR = '[data-glass-surface]'" in glass


class TestGlowFlickerSlowdown:
    """Правка владельца (v2.58.20): «мерцание свечения» фона замедлено ровно
    ×2 (частота ÷2 → период ×2). Мерцание свечения = импульсы свечения узлов
    (§8.3) и «дыхание» радиуса фонового свечения (§7.1). Регресс-гейт: возврат
    прежней скорости (0.05/0.15/0.06 rad/s) роняет тест."""

    BASE = {"PULSE_SPEED_MIN": 0.05, "PULSE_SPEED_MAX": 0.15,
            "GLOW_SHIMMER_SPEED": 0.06}

    def _const(self, name: str) -> float:
        m = re.search(name + r"\s*=\s*([0-9.]+)", POLY)
        assert m, f"нет константы {name}"
        return float(m.group(1))

    def test_glow_flicker_slowed_by_two(self):
        for name, base in self.BASE.items():
            val = self._const(name)
            assert abs(val * 2 - base) < 1e-12, (name, val, base)

    def test_glow_uses_named_constants(self):
        assert "pulseSp: PULSE_SPEED_MIN +" in POLY
        assert "rng() * (PULSE_SPEED_MAX - PULSE_SPEED_MIN)" in POLY
        assert "Math.sin(t * GLOW_SHIMMER_SPEED + cl.ph)" in POLY

    def test_old_speeds_removed(self):
        assert "pulseSp: 0.05 + rng() * 0.10" not in POLY
        assert "Math.sin(t * 0.06 + cl.ph)" not in POLY

    def test_non_flicker_timings_untouched(self):
        # движение узлов §9 / morph §8.1 / дрейф световых центров §8.2.
        assert "sp1: 0.10 + rng() * 0.22" in POLY
        assert "sp2: 0.08 + rng() * 0.18" in POLY
        assert "return 0.5 + 0.5 * Math.sin(t * 0.06 + ph);" in POLY
        assert "Math.sin(t * 0.045 + cl.ph)" in POLY
        assert "Math.cos(t * 0.038 + cl.ph * 1.3)" in POLY

    def test_topology_cap_unchanged(self):
        # §6.4/SC-15: топология пересчитывается ≤4 Гц (не «мерцание свечения»).
        assert "TOPO_HZ = 4" in POLY


class TestJsSyntax:
    def test_node_check(self):
        node = shutil.which("node")
        if not node:
            pytest.skip("node недоступен")
        for f in ("web/static/polygon-background.js",
                  "web/static/aurora-flow.js", "web/app.js"):
            res = subprocess.run([node, "--check", f], capture_output=True,
                                 text=True, timeout=60)
            assert res.returncode == 0, (f, res.stderr)
