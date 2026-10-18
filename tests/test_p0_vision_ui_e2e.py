# -*- coding: utf-8 -*-
"""P0 Vision — UI-контракт D10–D12 + §4 (Android): pytest-обёртка.

Прогоняет реальный браузерный e2e `tools/ui_vision_ui_e2e.py` по настоящим
`web/index.html` + `web/app.js` + `web/static/app.css` (Playwright, route-стабы
`/api/*`) и проверяет результат как контракт среза:

  * ни в одном состоянии секции Vision нет артефакта
    `function () { [native code] }` (D10/P0V-UI-NATIVE);
  * факты фактического подключения (провайдер/модель/тип/результат) показаны
    из `GET /api/vision/state` в обоих местах (D12/P0V-UI-DISPLAY);
  * причины пробы — человеческие, внутренние коды не текут
    (D11/P0V-UI-REASONS);
  * ни documentElement, ни main.scroll-area не переполняются по горизонтали
    на 320–430 portrait, в ландшафте и при крупном системном шрифте Android
    (P0V-UI-OVERFLOW);
  * значение ключа не попадает в DOM (P0V-UI-SECRETS);
  * console_errors = 0 во всех сценариях.

Запуск:
  .venv/Scripts/python.exe -m pytest tests/test_p0_vision_ui_e2e.py -x -q

TEST-LIFECYCLE: CONTRACT owner=P0V-UI-* (§4 директивы; D10–D12).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "ui_vision_ui_e2e.py"

# Реальный браузерный прогон (26 сценариев, Chromium) длится ~70-90 с —
# осознанное превышение глобального `timeout = 60` из pytest.ini (тот рассчитан
# на юнит-уровень); таймаут поднят точечно для этого контракта.
pytestmark = pytest.mark.timeout(1800)

REQUIRED_CASES = (
    "llm-320x640",
    "llm-360x740",
    "llm-390x844",
    "llm-430x932",
    "llm-640x360-land",
    "llm-844x390-land",
    "llm-no-state",
    "llm-320x640-font20",
    "llm-360x740-font24",
    "mod-320x640",
    "mod-390x844",
    "mod-settings-360x740",
    "probe-auth",
    "probe-rate",
    "probe-modality",
    "probe-timeout",
    "probe-server5xx",
    "probe-empty",
    "probe-config",
    "probe-fallback-auth",
    "probe-ok",
)


@pytest.fixture(scope="module")
def ui_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("p0v_ui") / "vision_ui.json"
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--json", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    tail = (proc.stdout or "")[-4000:] + (proc.stderr or "")[-2000:]
    assert proc.returncode == 0, (
        "ui_vision_ui_e2e.py завершился с ошибкой:\n" + tail)
    assert out.exists(), "e2e не создал JSON-отчёт:\n" + tail
    report = json.loads(out.read_text(encoding="utf-8"))
    return report


def test_no_failures_and_required_cases(ui_report):
    assert ui_report["failures"] == [], (
        "регрессии UI контракта Vision:\n  - "
        + "\n  - ".join(ui_report["failures"]))
    missing = [c for c in REQUIRED_CASES if c not in ui_report["cases"]]
    assert not missing, "нет обязательных сценариев: %s" % missing


def test_no_native_code_artifact_anywhere(ui_report):
    bad = [name for name, case in ui_report["cases"].items()
           if case.get("nativeText")]
    assert not bad, "артефакт `[native code]` в состояниях: %s" % bad


def test_no_console_errors_anywhere(ui_report):
    bad = {name: case.get("consoleErrors") for name, case
           in ui_report["cases"].items() if case.get("consoleErrors")}
    assert not bad, "console_errors не пусты: %s" % bad


def test_no_horizontal_overflow_in_any_case(ui_report):
    bad = {name: (case["docScrollWidth"], case["innerWidth"],
                  case["mainScrollWidth"], case["mainClientWidth"])
           for name, case in ui_report["cases"].items()
           if case.get("overflow") or case.get("mainOverflow")
           or case.get("controlIssues")}
    assert not bad, "горизонтальное переполнение: %s" % bad


def test_facts_present_with_actual_values(ui_report):
    """D12: факты — в LLM-секции и карточке модуля, из /api/vision/state."""
    for name in ("llm-390x844", "mod-390x844"):
        case = ui_report["cases"][name]
        assert case["factsPresent"], "%s: нет блока фактов" % name
        facts = case["facts"]
        assert facts.get("provider", "").endswith("openrouter.ai"), (
            "%s: провайдер не показан: %r" % (name, facts))
        assert "google/gemma-4-31b-it:free" in facts.get("model", ""), (
            "%s: модель не показана: %r" % (name, facts))
        assert "OpenAI-совместимый" in facts.get("api_type", ""), (
            "%s: тип подключения не показан: %r" % (name, facts))
        assert "Провайдер временно недоступен" in facts.get("result", ""), (
            "%s: результат проверки не показан: %r" % (name, facts))
    # «state нет» — линия/факты честно скрыты, без техмусора.
    no_state = ui_report["cases"]["llm-no-state"]
    assert not no_state["factsPresent"] and not no_state["effLine"]


def test_human_reasons_without_raw_codes(ui_report):
    """D11: тост/статус пробы — человеческий текст без внутренних кодов."""
    raw = ("vision_unavailable", "vision_rate_limited", "vision_unsupported",
           "image_modality_unsupported", "empty_completion",
           "api_type_unsupported", "http_401", "http_429", "http_5xx")
    expectations = {
        "probe-auth": "Неверный ключ",
        "probe-rate": "Превышен лимит",
        "probe-modality": "Модель не принимает изображения",
        "probe-timeout": "таймаут",
        "probe-server5xx": "временно недоступен",
        "probe-empty": "пустой ответ",
        "probe-config": "не поддерживается",
        "probe-fallback-auth": "Неверный ключ",
        "probe-ok": "изображение поддерживается",
    }
    for name, want in expectations.items():
        case = ui_report["cases"][name]
        texts = [case.get("statusText") or ""] + list(case.get("toastTexts") or [])
        assert any(want in t for t in texts), (
            "%s: нет «%s» в %r" % (name, want, texts))
        for t in texts:
            for code in raw:
                assert code not in t, (
                    "%s: внутренний код %r виден в %r" % (name, code, t))


def test_secrets_not_rendered(ui_report):
    bad = [name for name, case in ui_report["cases"].items()
           if case.get("hasRawSecret") or any(case.get("secretInputs") or [])]
    assert not bad, "значение ключа попало в UI: %s" % bad
