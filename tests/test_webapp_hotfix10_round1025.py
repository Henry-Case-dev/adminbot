"""hotfix10 round 10.25 — маркер-гейт `hotfix10-liquidglass-rollback-shell-geometry-round1025`.

Задачи T-2843…T-2864 (ADR-1025-18 D1–D6). Поведение (DOM/Playwright) —
в `tests/js/round1025_hotfix10_glass_geometry_bg_test.js` (запускается из
`tests/test_webapp_js_unit.py`) и `tools/ui_round1025_matrix.py`. Здесь —
атомарные маркеры и инварианты:

  * A — откат стекла: `[data-glass-surface]` единственная цель; dispose чистит
    `.ps-glass*`; флаг default OFF.
  * B — контракт GlassSurface (isolation/contain/декор ниже контента).
  * C — единая рабочая поверхность Main (нет max-width:1440, `--work-surface-bg`).
  * D — единая высота: второй вычет safe-area снят.
  * E — `.status-block` без стекла; дизайн сердцебиения не тронут.
  * F — OGL-фон: экспорт/вызов `resize`, пересчёт buffer/viewport/uniforms.
  * Δ DDL = 0, Δ каталога = 0; CSP/zero-build.
"""
import dataclasses
import re
from pathlib import Path

from config.settings import Settings

ROOT = Path(".")
APP_CSS = (ROOT / "web" / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
TG_INIT = (ROOT / "web" / "static" / "telegram-init.js").read_text(encoding="utf-8")
AURORA = (ROOT / "web" / "static" / "aurora-flow.js").read_text(encoding="utf-8")
GLASS = (ROOT / "web" / "static" / "glass.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
ROUTES = (ROOT / "web" / "api" / "routes.py").read_text(encoding="utf-8")
MATRIX = (ROOT / "tools" / "ui_round1025_matrix.py").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


class TestGlassRollback:
    def test_flag_default_off(self):
        assert re.search(
            r"UI_LIQUID_GLASS_LIB: ClassVar\[bool\] = _env_bool\(\s*"
            r'"UI_LIQUID_GLASS_LIB", False\)', SETTINGS), \
            "UI_LIQUID_GLASS_LIB должен иметь default OFF (безопасное состояние)"
        assert "UI_LIQUID_GLASS_LIB" in ROUTES
        assert "UI_LIQUID_GLASS_LIB" in ENV_EXAMPLE
        assert "UI_LIQUID_GLASS_LIB" in APP_JS

    def test_flag_still_env_only_not_in_catalog(self):
        from services import param_catalog as pc
        assert "UI_LIQUID_GLASS_LIB" not in pc.REGISTRY

    def test_single_isolated_target(self):
        assert "var SELECTOR = '[data-glass-surface]'" in GLASS
        # Функциональные цели НЕ в коде выборки (комментарии не считаем).
        code = re.sub(r"/\*[\s\S]*?\*/", "", GLASS)
        assert ".scope-trigger" not in code
        assert ".header-fs-btn" not in code
        assert ".status-block" not in code
        assert "data-glass-surface" in INDEX

    def test_dispose_removes_all_nodes(self):
        assert "function purge" in GLASS
        assert ".ps-glass__tint" in GLASS and ".ps-glass__surface" in GLASS
        assert "data-lg-mounted" in GLASS and "data-lg-failed" in GLASS
        assert "data-lg-mode" in GLASS  # честный режим

    def test_honest_mode(self):
        assert "return 'refraction'" in GLASS
        assert "return 'frosted'" in GLASS
        assert ".ps-glass__refract" in GLASS

    def test_opacity_not_used_as_cure(self):
        # Лечение белых прямоугольников opacity запрещено: стекло снято.
        assert "data-lg-mounted" in GLASS
        glass_block = APP_CSS[APP_CSS.index(".glass-surface {"):]
        glass_block = glass_block[:glass_block.index("}") + 1]
        assert "opacity" not in glass_block


class TestGlassSurfaceContract:
    def test_css_contract(self):
        m = re.search(r"^    \.glass-surface \{([\s\S]*?)^    \}", APP_CSS, re.M)
        assert m, "нет правила .glass-surface"
        block = m.group(1)
        assert "isolation: isolate" in block
        assert "contain: layout paint" in block
        assert "pointer-events: none" in block
        assert "--glass-paper: var(--surface-1)" in block

    def test_decor_below_content(self):
        # Декор из vendored CSS — over content? Проверяем z-index контента.
        m = re.search(r"\.glass-surface > \.glass-surface__content \{"
                      r"[\s\S]{0,80}z-index:\s*1", APP_CSS)
        assert m, "контент GlassSurface должен быть z-index:1 над декором"


class TestMainSurface:
    def test_max_width_removed_from_main(self):
        m = re.search(r"^      \.app-shell\.ia-v2 main\.scroll-area \{([\s\S]*?)"
                      r"^      \}", APP_CSS, re.M)
        assert m, "нет правила desktop main.scroll-area"
        block = m.group(1)
        assert "max-width: none" in block
        assert "1440" not in block
        assert "margin-inline: 0" in block
        assert "var(--work-surface-bg)" in block

    def test_card_limit_kept(self):
        assert re.search(r"\.module-list \{[\s\S]{0,160}max-width:\s*1100px",
                         APP_CSS)
        assert re.search(r"\.module-quick-wrap \{[\s\S]{0,120}max-width:\s*1100px",
                         APP_CSS)
        assert re.search(r"\.module-toolbar \{[\s\S]{0,120}max-width:\s*1100px",
                         APP_CSS)

    def test_no_negative_margins(self):
        assert not re.search(r"margin(?:-left|-inline)?:\s*-", APP_CSS)


class TestHeight:
    def test_fullscreen_scroll_area_no_safe_area(self):
        m = re.search(r"^    \.fullscreen-mode \.scroll-area \{([\s\S]*?)^    \}",
                      APP_CSS, re.M)
        assert m
        code = re.sub(r"/\*[\s\S]*?\*/", "", m.group(1))
        assert "env(safe-area-inset-bottom" not in code
        assert "padding-bottom: 1rem" in code

    def test_more_sheet_single_offset(self):
        m = re.search(r"^    \.more-sheet \{([\s\S]*?)^    \}", APP_CSS, re.M)
        assert m
        code = re.sub(r"/\*[\s\S]*?\*/", "", m.group(1))
        assert "--tg-viewport-bottom-offset" in code
        # Нет сложения offset + max(safe-area…).
        assert not re.search(r"max\(env\(safe-area-inset-bottom[\s\S]{0,160}"
                             r"\+ var\(--tg-viewport-bottom-offset", code)

    def test_usable_height_single_source(self):
        assert "--app-usable-height" in TG_INIT
        assert "computeBottomOffset" in TG_INIT
        assert "innerHeight" in TG_INIT


class TestStatusCard:
    def test_status_block_without_glass(self):
        idx = INDEX.index('class="card p-4 status-block"')
        head = INDEX[idx:idx + 200]
        assert "data-glass" not in head
        assert ".status-block { max-width: 100%; overflow: hidden; }" in APP_CSS

    def test_heartbeat_design_untouched(self):
        assert re.search(r"\.hb-wrap \{[^}]*min-height: 56px", APP_CSS)
        assert "status-block__pulse" in INDEX


class TestReviewFixes:
    """H-1 / L-H10-1 / L-1 / L-2 (round1025 hotfix-review)."""

    def test_h1_status_grid_row_not_collapsed(self):
        # auto-строка grid'а должна брать реальную высоту контента (иначе
        # `.status-block` схлопывался до 34px и обрезал метрики).
        assert "main.scroll-area { grid-auto-rows: max-content; }" in APP_CSS
        # Дизайн сердебиения и ограничение карточки не тронуты.
        assert ".status-block { max-width: 100%; overflow: hidden; }" in APP_CSS
        assert re.search(r"\.hb-wrap \{[^}]*min-height: 56px", APP_CSS)

    def test_h1_matrix_gate_strengthened(self):
        # §5-гейт проверяет обрезку (scrollHeight/clientHeight) и hit-test
        # центра `.hb-canvas`/`__bot`/`__server` (не только innerText/height>0).
        assert "def _h10_status_card_failures" in MATRIX
        for key in ("statusBlock", "hbHit", "botHit", "serverHit"):
            assert key in MATRIX, key
        assert "scrollH=%d > clientH=%d" in MATRIX

    def test_lh101_placeholder_hidden_when_off(self):
        # Пустой декоративный контейнер не рендерится при UI_LIQUID_GLASS_LIB=OFF.
        assert 'v-if="liquidGlassLib"' in INDEX
        assert re.search(r'v-if="liquidGlassLib"[\s\S]{0,120}data-glass-surface',
                         INDEX)
        assert "пустой GlassSurface не скрыт при OFF" in MATRIX

    def test_l1_clear_library_attrs_and_inline_props(self):
        code = re.sub(r"/\*[\s\S]*?\*/", "", GLASS)
        assert "data-uid" in code and "data-glass" in code
        assert "indexOf('--g-')" in code
        assert "removeProperty" in code

    def test_l2_env_example_actual(self):
        assert "только frost-fallback" not in ENV_EXAMPLE
        assert "UI_LIQUID_GLASS_LIB (default OFF)" in ENV_EXAMPLE
        assert "data-glass-surface" in ENV_EXAMPLE


class TestAuroraResize:
    def test_resize_exported(self):
        assert "resize: resize" in AURORA
        assert "function measure" in AURORA
        assert "gl.viewport(0, 0, bw, bh)" in AURORA
        assert "uniforms.uRes.value = [bw, bh]" in AURORA

    def test_resize_wired_in_app(self):
        assert "_auroraResize();" in APP_JS
        assert re.search(r"_onResize = function[\s\S]{0,400}_auroraResize\(\)",
                         APP_JS)
        assert re.search(r"setFullscreenFromTma:[\s\S]{0,900}_auroraResize\(\)",
                         APP_JS)
        assert "_onVV" in APP_JS


class TestVersionAndInvariants:
    def test_app_version_bumped(self):
        m = re.search(r'APP_VERSION = "([\d.]+)"', SETTINGS)
        assert m and m.group(1) == "2.58.27", m and m.group(1)

    def test_catalog_invariants(self):
        from services import param_catalog as pc
        assert len(pc.REGISTRY) == 469
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426

    def test_csp_no_external(self):
        assert not re.search(r'src="https?://', INDEX)
        assert not re.search(r"backdrop-filter\s*:\s*url\(", APP_CSS)

    def test_matrix_hotfix10_probes(self):
        for probe in ("H10_PROBE_JS", "H10_GLASS_ISOLATION_JS",
                      "_h10_failures", "_h10_glass_failures",
                      "ME_GLASS_OFF", "_h10_glass_off_failures",
                      "hotfix10_glass_off"):
            assert probe in MATRIX, probe
