# -*- coding: utf-8 -*-
"""ADD-SAMPLES-UX — UI-контракт §4: pytest-обёртка e2e `tools/ui_samples_ux_e2e.py`.

Прогоняет реальный браузерный e2e по настоящим `web/index.html` +
`web/app.js` + `web/static/app.css` (Playwright, stateful /api-стабы,
Telegram SDK — route-mock) и проверяет результат как контракт среза §4:

  * DOM-иерархия экрана списка §4.1 (вкладки одной строкой → покатегорийные
    счётчики → поиск/фильтр → карточки) и одна колонка карточек;
  * карточка без SQL/JSON/тегов/ревизий, с подписью категории/происхождения;
  * редактор — ОТДЕЛЬНЫЙ экран, категория предзаполнена, «Мат» — видимый
    выбор режима, «Общие» — без техники/режима; «Назад» предупреждает;
  * «Сохранено» только после ответа API + перечитывание с сервера;
  * заводская карточка: плашка, «Посмотреть исходный», restore только по
    подтверждению; экран сравнения с «Отменой» по умолчанию;
  * правка/удаление заводской карточки переживают reload; удалённая
    (tombstone) видна в честной группе, не возвращается молча;
  * отсутствие горизонтального overflow на portrait/landscape/desktop.

Запуск:
  .venv/Scripts/python.exe -m pytest tests/test_samples_ui_e2e.py -x -q

TEST-LIFECYCLE: CONTRACT owner=SAMPLES-UX/SU-UI.* (§4 директивы)
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "ui_samples_ux_e2e.py"

# Реальный браузерный прогон (6 сценариев, Chromium) — точечный таймаут.
pytestmark = pytest.mark.timeout(900)

REQUIRED_CASES = (
    "list-360x740",
    "editor-390x844",
    "factory-390x844",
    "persist-reload-390",
    "landscape-667x375",
    "desktop-1280x800",
)


@pytest.fixture(scope="module")
def ui_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("samples_ui") / "samples_ui.json"
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--json", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=900)
    tail = (proc.stdout or "")[-4000:] + (proc.stderr or "")[-2000:]
    assert proc.returncode == 0, (
        "ui_samples_ux_e2e.py завершился с ошибкой:\n" + tail)
    assert out.exists(), "e2e не создал JSON-отчёт:\n" + tail
    report = json.loads(out.read_text(encoding="utf-8"))
    return report


def test_no_failures_and_required_cases(ui_report):
    assert ui_report["failures"] == [], (
        "регрессии UI-контракта §4 «Примеры»:\n  - "
        + "\n  - ".join(ui_report["failures"]))
