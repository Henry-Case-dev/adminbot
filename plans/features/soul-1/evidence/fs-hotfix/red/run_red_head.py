"""FS-HOTFIX: RED-прогон того же probe на снимке HEAD (pre-fix web/).

Доказывает исходный дефект (наблюдения владельца 18.10) на РЕАЛЬНОМ коде
HEAD (prod-эквивалент: float-резерв + tdesktop hidden + стеклянная кнопка):

  * S1 320/390 → кнопка в float (position:fixed) со стеклянной подложкой
    ::before (крупный круг + backdrop-filter) — «крупная кнопка/Liquid Glass»;
  * S2 390 + safe=24/csa=36 (реальный Android: статус-бар + Telegram-зона) →
    кнопка на y=42 внутри зоны 0..60 → «под нативными, частично перекрыта»
    (пересечение с зоной native-кнопок > 0);
  * S3 tdesktop → кнопки НЕТ вовсе (`.header-fs-btn` не появляется) —
    «диагностическая заглушка вместо рабочей кнопки».

Снимок HEAD строится в временный каталог и НЕ попадает в репозиторий.
Запуск (из корня репо, .venv):
  .venv/Scripts/python.exe plans/features/soul-1/evidence/fs-hotfix/red/run_red_head.py
Результат: plans/features/soul-1/evidence/fs-hotfix/red/red_head_results.json
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

def _find_repo():
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            raise RuntimeError("repo root not found")
        d = nd


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = _find_repo()
sys.stdout.reconfigure(encoding="utf-8")

SNAP = os.path.join(tempfile.gettempdir(), "fs-hotfix-head-web")
SHOTS = os.path.join(tempfile.gettempdir(), "fs-hotfix-head-shots")

sys.path.insert(0, os.path.join(REPO, "tools"))
import ui_asap8_w2_fullscreen_e2e as T   # noqa: E402
import ui_round1025_matrix as M          # noqa: E402


def build_snapshot():
    if os.path.isdir(SNAP):
        shutil.rmtree(SNAP)
    os.makedirs(SNAP)
    tar = os.path.join(SNAP, "..", "fs-hotfix-head-web.tar")
    with open(tar, "wb") as fh:
        subprocess.check_call(["git", "archive", "HEAD", "web"], cwd=REPO,
                              stdout=fh)
    subprocess.check_call(["tar", "-xf", tar, "-C", SNAP], cwd=REPO)
    os.remove(tar)
    return SNAP


def main():
    from playwright.sync_api import sync_playwright
    build_snapshot()
    os.makedirs(SHOTS, exist_ok=True)
    M.REPO = SNAP            # _Handler.translate_path читает модульный REPO
    os.chdir(SNAP)

    httpd = T._start_server()
    print("[RED] server on %d, snapshot %s" % (T.PORT, SNAP))
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in (T.scenario_android_inline, T.scenario_windowed_zero_insets,
                   T.scenario_tdesktop):
            try:
                c, extra = fn(browser, SHOTS)
                status = "PASS" if not c.failures else "FAIL"
                print("[RED] %-24s %s (%d checks)" % (c.name, status, c.count))
                for f in c.failures:
                    print("    FAIL: %s" % f)
                results.append({"scenario": c.name, "status": status,
                                "checks": c.count, "failures": c.failures})
            except Exception as exc:  # noqa: BLE001
                print("[RED] %-24s ERROR: %s" % (fn.__name__, exc))
                results.append({"scenario": fn.__name__, "status": "ERROR",
                                "error": str(exc)[:300]})
        browser.close()
    httpd.shutdown()
    with open(os.path.join(HERE, "red_head_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    print("[RED] evidence:", os.path.join(HERE, "red_head_results.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
