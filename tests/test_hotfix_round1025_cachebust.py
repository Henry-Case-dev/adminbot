"""ASAP-хотфикс round1025 (T-2470/T-2471) — cache-bust ассетов миниаппа.

Проверяем, что единый источник версии `config.settings.APP_VERSION`
подставляется в `?v=` ОДНОВРЕМЕННО для трёх ассетов (`tailwind.css`/`app.css`/
`app.js`) + шрифта (`app.css @font-face`) и что версия поднята над до-хотфиксной.
"""
from pathlib import Path

from config.settings import APP_VERSION
from web.app import _render_app_css, _render_index

ROOT = Path(__file__).resolve().parents[1]

# Версия до хотфикса (cache-bust вскрыт в round1025): не пиним текущую —
# требуем СТРОГО БОЛЬШУЮ (bump) + согласованность с README.
_PRE_HOTFIX_VERSION = "2.58.0"


def _ver(value: str) -> tuple:
    return tuple(int(part) for part in value.split("."))


def test_three_assets_share_single_version():
    html = _render_index()
    assert f"/static/vendor/tailwind.css?v={APP_VERSION}" in html
    assert f"/static/app.css?v={APP_VERSION}" in html
    assert f"/web/app.js?v={APP_VERSION}" in html
    assert "__APP_VERSION__" not in html          # заглушка заменена


def test_css_font_version_substituted():
    css = _render_app_css()
    assert f"material-symbols-rounded.woff2?v={APP_VERSION}" in css
    assert "__APP_VERSION__" not in css


def test_telegram_init_versioned():
    assert f"/static/telegram-init.js?v={APP_VERSION}" in _render_index()


def test_version_bumped_and_matches_readme():
    # T-2470: версия обязана быть СТРОГО выше до-хотфиксной (bump), иначе
    # WebView держит старый app.js при новом index.html → ReferenceError в
    # config-разделах. Значение не пиним — сравниваем версии.
    assert _ver(APP_VERSION) > _ver(_PRE_HOTFIX_VERSION)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert ("v" + APP_VERSION) in readme


def test_no_previous_version_in_rendered_index():
    assert f"?v={_PRE_HOTFIX_VERSION}" not in _render_index()
