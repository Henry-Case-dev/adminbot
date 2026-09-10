"""Редизайн 10.5 (T-1146/T-1147) — поставка субсета шрифта Material Symbols.

Маркеры: build-скрипт оффлайн/идемпотентный; build-dep отдельно от runtime;
в git — только субсет + Apache-2.0 LICENSE; @font-face + PUA-рендер;
источник 5.11 МиБ gitignored.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(".")
SUBSET = ROOT / "web" / "static" / "fonts" / "material-symbols-rounded.woff2"
LICENSE = ROOT / "web" / "static" / "fonts" / "LICENSE-material-symbols.txt"
SOURCE = ROOT / "MaterialSymbolsRounded[FILL,GRAD,opsz,wght].woff2"
BUILD_SCRIPT = ROOT / "scripts" / "build_font_subset.py"
BUILD_REQS = ROOT / "scripts" / "requirements-font.txt"


def test_subset_shipped_small():
    assert SUBSET.exists(), "субсет должен быть в git"
    size = SUBSET.stat().st_size
    assert 3000 < size < 60_000, size            # ~13 КБ, «лёгкий»
    assert SUBSET.read_bytes()[:4] == b"wOF2"


def test_license_apache():
    assert LICENSE.exists()
    text = LICENSE.read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0" in text


def test_build_script_offline_and_idempotent():
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "instantiateVariableFont" in text
    assert 'flavor=woff2' in text                    # pyftsubset
    assert "GSUB" in text                            # оффлайн PUA-деривация
    assert "unicodes-file" in text
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
    html = open("web/index.html", encoding="utf-8").read()
    assert "font-family: 'Material Symbols Rounded'" in html
    assert "/static/fonts/material-symbols-rounded.woff2" in html
    assert "woff2-variations" in html
    assert "unicode-range" not in html.split("@font-face")[1].split("}")[0]
    js = open("web/app.js", encoding="utf-8").read()
    # Рендер по PUA-кодпоинту (карта ICONS), а не по текстовому имени.
    assert "var ICONS = {" in js
    assert "'\\ue887'" in js          # help (10.7: account_balance_wallet удалён)
    assert "tabMat: function (id)" in js
