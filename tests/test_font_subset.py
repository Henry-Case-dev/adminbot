"""Редизайн 10.5 (T-1146/T-1147) + раунд 10.8 (T-1249, R10.7-4) — субсет шрифта.

Маркеры: build-скрипт оффлайн/идемпотентный (с учётом ICON_NAMES); build-dep
отдельно от runtime; в git — только субсет + Apache-2.0 LICENSE; @font-face +
PUA-рендер; источник 5.11 МиБ gitignored.

Раунд 10.8 (R10.7-4): паритет `ICONS` (JS) ↔ `ICON_NAMES` (билд-скрипт) и
проверка каждого PUA-кода в реальном cmap WOFF2 (не только в JS) — ловит tofu.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(".")
SUBSET = ROOT / "web" / "static" / "fonts" / "material-symbols-rounded.woff2"
LICENSE = ROOT / "web" / "static" / "fonts" / "LICENSE-material-symbols.txt"
SOURCE = ROOT / "MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2"
BUILD_SCRIPT = ROOT / "scripts" / "build_font_subset.py"
BUILD_REQS = ROOT / "scripts" / "requirements-font.txt"
APP_JS = ROOT / "web" / "app.js"
INDEX_HTML = ROOT / "web" / "index.html"

# 6 мёртвых имён 10.7 — не должны вернуться (spec §2.4/§2.5 Test D).
DEAD_ICONS = {
    "account_balance_wallet", "speed", "stop_circle", "theater_comedy",
    "toggle_off", "toggle_on",
}
# Пиктографические emoji, заменённые в 10.8 §2.2 (disclosure ▶ исключён явно).
REPLACED_EMOJI = (
    "🎭", "🙈", "👁", "🧩", "📊", "🧠", "🛡", "🗑", "🌟", "🛰",
    "👥", "⚙", "💾", "📜", "📝", "🤖", "🚚", "👑", "🔄", "⏹",
    "🖥", "📈", "🔑",
)


def _parse_icons() -> dict[str, int]:
    """`var ICONS = { name: '\\uXXXX', … }` из web/app.js → {name: codepoint}."""
    js = APP_JS.read_text(encoding="utf-8")
    start = js.index("var ICONS = {")
    end = js.index("};", start)
    block = js[start:end]
    pairs = re.findall(r"(\w+):\s*'(\\u[0-9a-fA-F]{4})'", block)
    return {name: int(cp[2:], 16) for name, cp in pairs}


def _parse_icon_names() -> set[str]:
    """Кортеж `ICON_NAMES` из scripts/build_font_subset.py."""
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = text.index("ICON_NAMES")
    end = text.index(")", start)
    return set(re.findall(r'"([A-Za-z_]+)"', text[start:end]))


def test_subset_shipped_small():
    assert SUBSET.exists(), "субсет должен быть в git"
    size = SUBSET.stat().st_size
    assert 3000 < size < 60_000, size            # ~18 КБ, «лёгкий»
    assert SUBSET.read_bytes()[:4] == b"wOF2"


def test_license_apache():
    assert LICENSE.exists()
    text = LICENSE.read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0" in text


def test_build_script_offline_idempotent_and_names_aware():
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "instantiateVariableFont" in text
    assert 'flavor=woff2' in text                    # pyftsubset
    assert "GSUB" in text                            # оффлайн PUA-деривация
    assert "unicodes-file" in text
    # 10.8 (§2.4): маркер идемпотентности учитывает ICON_NAMES; экспорт codepoints.
    assert "ICON_NAMES" in text
    assert "_marker_key" in text
    assert "icon_codepoints" in text
    # без сети
    assert "http" not in text.replace("http://www.apache.org", "").replace(
        "https://github.com", "")


def test_fonttools_not_runtime_dep():
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "fonttools" not in runtime
    assert "brotli" not in runtime
    build = BUILD_REQS.read_text(encoding="utf-8").lower()
    assert "fonttools" in build and "brotli" in build


def test_source_gitignored_subset_tracked():
    for target in ("MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2", "build/"):
        res = subprocess.run(["git", "check-ignore", target],
                             capture_output=True, text=True)
        assert res.returncode == 0, target
    # субсет — НЕ игнорируется (пойдёт в git).
    res = subprocess.run(
        ["git", "check-ignore", "web/static/fonts/material-symbols-rounded.woff2"],
        capture_output=True, text=True)
    assert res.returncode != 0


def test_fontface_and_pua_rendering():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    assert "font-family: 'Material Symbols Rounded'" in html
    assert "/static/fonts/material-symbols-rounded.woff2" in html
    assert "woff2-variations" in html
    assert "unicode-range" not in html.split("@font-face")[1].split("}")[0]
    # Рендер по PUA-кодпоинту (карта ICONS), а не по текстовому имени.
    assert "var ICONS = {" in js
    assert "tabMat: function (id)" in js


# ── Раунд 10.8 (T-1249/R10.7-4): паритет + cmap ──────────────────────────
def test_icons_parity_with_icon_names():
    """Test A: множество ICONS == множество ICON_NAMES (нет drift/мёртвых)."""
    icons = _parse_icons()
    names = _parse_icon_names()
    assert set(icons) == names, (
        "ICONS \\ ICON_NAMES: %s; ICON_NAMES \\ ICONS: %s"
        % (sorted(set(icons) - names), sorted(names - set(icons))))


def test_every_icon_codepoint_in_subset_cmap():
    """Test B (R10.7-4): каждый PUA-код ICONS есть в cmap пересобранного WOFF2."""
    import pytest
    pytest.importorskip("fontTools")
    from fontTools.ttLib import TTFont

    icons = _parse_icons()
    cmap = TTFont(str(SUBSET)).getBestCmap()
    missing = [name for name, cp in icons.items() if cp not in cmap]
    assert not missing, "нет глифов в субсете (tofu): %s" % missing


def test_icon_names_count_37():
    """10.8 §2.4: 20 базовых + 17 новых = 37 имён."""
    assert len(_parse_icon_names()) == 37
    assert len(_parse_icons()) == 37


def test_no_dead_icon_names_10_7():
    """Test D: 6 мёртвых имён 10.7 не вернулись."""
    names = _parse_icon_names()
    assert not (DEAD_ICONS & names), sorted(DEAD_ICONS & names)
    assert not (DEAD_ICONS & set(_parse_icons()))


def test_no_replaced_pictographic_emoji():
    """Test C: в web/ не осталось заменённых pictographic-emoji."""
    for path in (APP_JS, INDEX_HTML):
        text = path.read_text(encoding="utf-8")
        for glyph in REPLACED_EMOJI:
            assert glyph not in text, (path.name, glyph)
