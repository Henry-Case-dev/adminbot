"""CMV-A: точечный живой прогон «Когнитивной карты» (S1–S3) на стенде W15.

Зачем: полный `ui_evol_w15_composition_e2e.py` гоняет все разделы W15 (долго и
шумно). Пакету A нужен ровно существующий сценарий карты: виджет на «Статусе»,
карточка узла/ребра с происхождением, Back/Esc, возврат фокуса, поиск/фильтры,
полный экран, мобильный layout. Сценарий не копируется — вызывается та же
функция `run_cog_map` на том же стенде (`ui_round1025_matrix` + фикстура W15).

Требование: §13 спеки (функциональные пункты) и §1.2 «сохранить функции».

Запуск:
  .venv/Scripts/python.exe tools/ui_cmv_a_cog_map_live.py [--out DIR]
Выход: `<out>/cog-map-live.json`; код 0 — 0 замечаний, 2 — есть замечания.
"""
import argparse
import json
import os
import sys
import traceback

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
os.chdir(REPO)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    repo = os.path.abspath(args.repo) if args.repo else REPO
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(
        repo, "plans", "features", "epic-cm-visual-01", "evidence", "cmv-a")
    os.makedirs(out_dir, exist_ok=True)

    import ui_round1025_matrix as M              # noqa: E402
    import ui_evol_w15_composition_e2e as W15     # noqa: E402
    from playwright.sync_api import sync_playwright  # noqa: E402

    # Порт 0 = свободный: на Windows второй bind с SO_REUSEADDR
    # разрешён, и на фиксированный порт может ответить чужой стенд.
    M.PORT = 0
    server = M._start_server()
    port = server.server_address[1]
    base = "http://127.0.0.1:%d/web/index.html" % port
    report = {}
    fails = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                W15.run_cog_map(browser, base, report, fails, out_dir)
            finally:
                browser.close()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        fails.append("fatal: " + traceback.format_exc()[-400:])
    finally:
        server.shutdown()

    section = report.get("cog_map") or {}
    data = {"repo": repo, "fails": fails, "checks": section.get("checks", 0),
            "viewports": list((section.get("viewports") or {}).keys()),
            "report": section}
    path = os.path.join(out_dir, "cog-map-live.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("checks=%s fails=%d" % (data["checks"], len(fails)))
    for f in fails[:20]:
        print("FAIL: " + str(f)[:200])
    print("report: " + path)
    print("COG-MAP-LIVE " + ("OK" if not fails else "FAIL"))
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
