"""CMV-PERF: пиксельное сравнение снимков «до/после» (parity визуала).

Правки производительности в слое `fx` (пакетный декор, спрайты подписей,
целые позиции ореолов) не должны менять картинку. Инструмент читает два набора
снимков (`ui_cmv_perf_shots.py` для базовой ревизии и для кандидата) и считает:
  * долю пикселей, отличающихся сильнее порога;
  * среднюю/максимальную разницу по каналам;
  * ограничивающий прямоугольник отличий (чтобы «всё поехало» было видно).

Запуск:
  python tools/ui_cmv_perf_parity.py --a DIR --b DIR [--out FILE]
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

try:
    from PIL import Image, ImageChops
except Exception as exc:  # noqa: BLE001
    print("PIL недоступен:", exc)
    raise SystemExit(3)

THRESHOLD = 12       # 0..255: ниже — разница сглаживания/субпикселя
STRICT_PCT = 1.5     # % пикселей выше порога, при котором снимок «другой»


def compare(a_path, b_path):
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    if a.size != b.size:
        return {"size_mismatch": [a.size, b.size], "ok": False}
    diff = ImageChops.difference(a, b)
    gray = diff.convert("L")
    hist = gray.histogram()
    total = a.size[0] * a.size[1]
    over = sum(hist[THRESHOLD + 1:])
    bbox = gray.point(lambda v: 255 if v > THRESHOLD else 0).getbbox()
    # Средняя разница по каналам
    stat_sum = 0
    stat_max = 0
    for ch in diff.split():
        h = ch.histogram()
        n = sum(h) or 1
        stat_sum += sum(i * c for i, c in enumerate(h)) / n
        for i in range(255, -1, -1):
            if h[i]:
                stat_max = max(stat_max, i)
                break
    return {
        "ok": (100.0 * over / total) <= STRICT_PCT,
        "diff_pct": round(100.0 * over / total, 4),
        "mean_channel_diff": round(stat_sum / 3.0, 3),
        "max_channel_diff": stat_max,
        "diff_bbox": bbox,
        "size": list(a.size),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    report = {"threshold": THRESHOLD, "strict_pct": STRICT_PCT, "pairs": []}
    names = sorted(f for f in os.listdir(args.a) if f.endswith(".png"))
    fails = 0
    for name in names:
        suffix = name.split("-", 1)[1] if "-" in name else name
        other = os.path.join(args.b, "cand-" + suffix)
        # метка набора вырезается: base-<device>-<state>.png ↔ cand-<device>-<state>.png
        cand = other if os.path.exists(other) else None
        if not cand:
            matches = [f for f in os.listdir(args.b)
                       if f.endswith("-" + suffix)]
            cand = os.path.join(args.b, matches[0]) if matches else None
        if not cand:
            continue
        row = compare(os.path.join(args.a, name), cand)
        row["shot"] = suffix
        report["pairs"].append(row)
        if not row.get("ok"):
            fails += 1
        print("  %-28s diff %6.3f %%  mean %5.2f  max %3d  %s"
              % (suffix, row.get("diff_pct", -1), row.get("mean_channel_diff", -1),
                 row.get("max_channel_diff", -1),
                 "ok" if row.get("ok") else "DIFF"))
    report["fails"] = fails
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
        print("->", args.out)
    print("pairs=%d fails=%d" % (len(report["pairs"]), fails))
    return 0 if fails == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
