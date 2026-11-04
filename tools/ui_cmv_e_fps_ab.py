"""CMV-E: чередующееся A/B-сравнение FPS (§10.2) кандидата и базовых ревизий.

Каждый прогон `ui_cmv_e_fps_campaign.py` — один проход по наборам/состояниям
камеры в ОДНОМ процессе (свой сервер, свой Chromium). Драйвер запускает
проходы РЕВИЗИЙ ЧЕРЕДУЯ (cand, base, cand, base, ...), чтобы разброс машины
(фоновая нагрузка, троттлинг) не приписывался коду, и сводит медианы.

Запуск:
  .venv/Scripts/python.exe tools/ui_cmv_e_fps_ab.py \
      --roots "cand=<wt>/cmv-e-accept,pcmv=<wt>/base-9e238d06,dbase=<wt>/base-dfba4080" \
      --passes 3 --ms 1500 --out plans/features/epic-cm-visual-01/evidence/cmv-e/cmv-e-fps-ab.json
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CAMPAIGN = os.path.join(HERE, "ui_cmv_e_fps_campaign.py")


def parse_roots(text):
    out = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        label, _, path = chunk.partition("=")
        out.append((label.strip(), os.path.abspath(path.strip())))
    return out


def git_rev(root):
    try:
        return subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            text=True).strip()
    except Exception:  # noqa: BLE001
        return None


def run_pass(label, root, out_dir, index, ms, fixtures, full_fx):
    out = os.path.join(out_dir, "fps-%s-p%d.json" % (label, index))
    cmd = [sys.executable, CAMPAIGN, "--repo", root, "--label", label,
           "--revision", git_rev(root) or "", "--out", out,
           "--ms", str(ms), "--fixtures", fixtures,
           "--fullscreen-fixtures", full_fx]
    started = time.time()
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    took = time.time() - started
    print("[%s pass %d] %.0fs rc=%d" % (label, index, took, proc.returncode))
    if proc.returncode != 0:
        print((proc.stdout or "")[-1500:])
        print((proc.stderr or "")[-800:])
        return None
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


def key_of(case):
    return (case["fixture"], case["mode"], case["state"])


def summarise(passes_by_label):
    """Медиана метрик по проходам, плюс каждый проход отдельно."""
    merged = {}
    for label, reports in passes_by_label.items():
        buckets = {}
        for report in reports:
            if not report:
                continue
            for case in report["cases"]:
                buckets.setdefault(key_of(case), []).append(case)
        for key, cases in buckets.items():
            stats = [c["stats"] for c in cases if c.get("stats")]
            if not stats:
                continue
            merged.setdefault("%d|%s|%s" % key, {})[label] = {
                "median": round(statistics.median(
                    [s["median"] for s in stats]), 1),
                "p95": round(statistics.median([s["p95"] for s in stats]), 1),
                "p99": round(statistics.median([s["p99"] for s in stats]), 1),
                "worst": round(min(s["worst"] for s in stats), 1),
                "jank": sum(s.get("jank", 0) for s in stats),
                "per_pass": [{"median": s["median"], "p95": s["p95"],
                              "p99": s["p99"]} for s in stats],
                "canvas": cases[0].get("canvas"),
                "hidden": cases[0].get("hidden"),
                "lod": cases[0].get("lod"),
                "ratio_got": cases[0].get("ratio_got"),
            }
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", required=True,
                    help='cand=<path>,pcmv=<path>,dbase=<path>')
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--ms", type=int, default=1500)
    ap.add_argument("--fixtures", default="10,100,702")
    ap.add_argument("--fullscreen-fixtures", default="702")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    roots = parse_roots(args.roots)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    runs_dir = tempfile.mkdtemp(prefix="cmv-e-fps-")
    passes = {label: [] for label, _ in roots}
    order = []
    for i in range(1, args.passes + 1):
        for label, root in roots:                     # чередование ревизий
            order.append((label, root, i))
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    for label, root, i in order:
        rep = run_pass(label, root, runs_dir, i, args.ms, args.fixtures,
                       args.fullscreen_fixtures)
        passes[label].append(rep)

    merged = summarise(passes)
    doc = {
        "started_at": started,
        "passes": args.passes,
        "ms_per_sample": args.ms,
        "roots": [{"label": label, "repo": root, "revision": git_rev(root)}
                  for label, root in roots],
        "fixtures": args.fixtures,
        "fullscreen_fixtures": args.fullscreen_fixtures,
        "env": next((r["env"] for rs in passes.values() for r in rs if r), None),
        "host": next(({"platform": r.get("host"), "render_mode": r.get(
            "render_mode"), "launch_args": r.get("launch_args")}
            for rs in passes.values() for r in rs if r), None),
        "fixture_sha256": next((r.get("fixture_sha256") for rs in passes.values()
                                for r in rs if r), None),
        "cases": merged,
        "per_run_dir": runs_dir,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)

    labels = [label for label, _ in roots]
    print("\nнабор | режим | состояние | " + " | ".join(labels))
    for key in sorted(merged, key=lambda k: [int(k.split("|")[0])] + [k]):
        fixture, mode, state = key.split("|")
        cells = []
        for label in labels:
            m = merged[key].get(label)
            cells.append("—" if not m else "%.1f / %.1f / %.1f"
                         % (m["median"], m["p95"], m["p99"]))
        print("%s | %s | %s | %s" % (fixture, mode, state, " | ".join(cells)))
    print("\n-> %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
