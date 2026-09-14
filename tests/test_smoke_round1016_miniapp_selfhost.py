"""F4 10.16 (miniapp-mobile-round1016, ADR-1016-2) — smoke self-host/CSP.

Статические проверки (без браузера): ни одного внешнего CDN в index.html/app.js,
все бандлы лежат локально, CSS вынесен в файл, inline-скриптов/стилей нет,
CSP допускает рантайм-компилятор Vue (теперь `'unsafe-eval'` — ревью-итер. 1).

ПОВЕДЕНЧЕСКИЙ гейт (T-1659, ревью-итер. 1): `tests/js/vue_mount_test.js`
загружает self-host бандл Vue, реально компилирует шаблон, симулирует CSP без
`'unsafe-eval'` (компиляция обязана упасть) и проверяет отсутствие inline/
внешних ресурсов. Запускается здесь через `node` (skip, если node нет).

Поведенческие проверки раздачи/CSP-заголовков — в
`tests/test_webapp_api.py::TestStatic` (маршруты /web/, /static/*).
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(".")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
VENDOR = ROOT / "web" / "static" / "vendor"

# Внешние хосты, из-за которых на Android возникал net::ERR_NAME_NOT_RESOLVED
# и «~1 минута» (блокирующие DNS-таймауты). Все должны быть self-host.
EXTERNAL_CDN = (
    "cdn.tailwindcss.com", "unpkg.com", "cdn.jsdelivr.net",
    "telegram.org/js", "fonts.googleapis.com", "fonts.gstatic.com",
)


def test_no_external_cdn_hosts():
    for text, name in ((INDEX, "index.html"), (APP_JS, "app.js")):
        for host in EXTERNAL_CDN:
            assert host not in text, "%s: %s" % (name, host)
    # В index.html не остаётся вообще ни одной внешней ссылки.
    assert "https://" not in INDEX
    assert "http://" not in INDEX


def test_no_inline_scripts_or_styles():
    """CSP `script-src 'self'` без 'unsafe-inline'/nonce требует external."""
    assert "<script>" not in INDEX
    assert "<style>" not in INDEX


def test_vendor_bundles_present():
    for name in ("telegram-web-app.js", "vue.global.prod.min.js",
                 "chart.umd.min.js", "dompurify-3.4.15.min.js",
                 "tailwind.css"):
        path = VENDOR / name
        assert path.exists(), name
        assert path.stat().st_size > 0, name


def test_vendor_versions_pinned():
    vue = (VENDOR / "vue.global.prod.min.js").read_text(
        encoding="utf-8", errors="ignore")[:200]
    chart = (VENDOR / "chart.umd.min.js").read_text(
        encoding="utf-8", errors="ignore")[:220]
    assert "vue v3.5.42" in vue
    assert "Chart.js v4.5.1" in chart


def test_local_assets_referenced():
    assert '/static/vendor/telegram-web-app.js' in INDEX
    assert '/static/vendor/vue.global.prod.min.js' in INDEX
    assert '/static/vendor/chart.umd.min.js' in INDEX
    assert '/static/vendor/tailwind.css' in INDEX
    assert '/static/app.css?v=__APP_VERSION__' in INDEX
    assert '/static/telegram-init.js' in INDEX


def test_csp_constant_strict():
    from web.app import _CSP_HTML
    assert "default-src 'self'" in _CSP_HTML
    script_src = _CSP_HTML.split("script-src", 1)[1].split(";", 1)[0]
    assert "'self'" in script_src
    assert "'unsafe-inline'" not in script_src
    assert "nonce-" not in script_src
    # Ревью-итер.1 (Critical): full-сборка Vue использует Function() —
    # CSP обязан разрешать 'unsafe-eval', иначе приложение не монтируется.
    assert "'unsafe-eval'" in script_src
    assert "style-src 'self' 'unsafe-inline'" in _CSP_HTML
    assert "frame-ancestors https://web.telegram.org" in _CSP_HTML
    assert "object-src 'none'" in _CSP_HTML


def test_vue_runtime_compiler_behavioral_gate():
    """ПОВЕДЕНЧЕСКИЙ гейт (T-1659): реальная компиляция шаблона self-host
    бандлом + CSP-симуляция + отсутствие inline/внешних ресурсов."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node недоступен — поведенческий JS-гейт пропущен")
    script = Path(__file__).resolve().parent / "js" / "vue_mount_test.js"
    proc = subprocess.run(
        [node, str(script)], cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (
        f"vue_mount_test.js упал (exit={proc.returncode}):\n"
        f"{proc.stdout}\n{proc.stderr}")
    assert "VUE-MOUNT-OK" in proc.stdout


def test_tailwind_build_inputs_present():
    """Рантайм — zero-build; сборка Tailwind оффлайн, результат закоммичен."""
    assert (ROOT / "tailwind.config.js").exists()
    input_css = ROOT / "web" / "static" / "tailwind.input.css"
    assert input_css.exists()
    assert "@tailwind utilities" in input_css.read_text(encoding="utf-8")


def test_render_app_css_missing_file_no_crash(monkeypatch):
    """Ревью-итер.1 (Low): без собранного web/static/app.css `_render_app_css`
    не падает, а отдаёт пустой CSS (симметрично skip-mount /static)."""
    from pathlib import Path as _Path

    from web import app as web_app

    def _boom(self, *a, **k):
        raise OSError("app.css отсутствует (чистый клон)")

    monkeypatch.setattr(_Path, "read_text", _boom)
    assert web_app._render_app_css() == ""
