"""ROWA2 — пиксельные доказательства рендера (без PIL/numpy).

1) BUTTON PIXELS: для каждого кейса и каждой фазы сравниваются два кадра —
   с кнопкой и с `visibility:hidden` у той же кнопки (`_rowa2_<tag>_<phase>_nobtn.png`).
   diff = ровно отрисованные пиксели контрола → bbox в CSS px обязан лежать
   внутри content_safe_area (обе оси). Это пиксельная, а не только DOM-проверка.
2) NO-SHIFT: кадры before/after в ПОЛОСЕ ШАПКИ для кейсов с нулевыми инсетами
   обязаны совпадать пиксель-в-пиксель (минимальный визуальный сдвиг).
3) SHIFT-VISIBLE: для кейсов с right=44 кадры before/after в полосе шапки
   отличаются (правка реально меняет рендер; в фазе before бокс выходил за
   safe-край — см. п.1 по before).

PNG декодируется чистым Python (zlib + отмена фильтров scanline).
Координаты — device px (device_scale_factor=2); CSS px = /2.
Полоса шапки = y ≤ (headerBottom + 8) CSS px — вне неё в приложении есть
анимации (графики/ленты), которые делают полнокадровый diff нестабильным.

Запуск: .venv/Scripts/python.exe <evidence>/ui_rowa2_pixel_diff.py
Артефакт: <evidence>/_rowa2_pixel_diff.json
"""
import json
import os
import struct
import sys
import zlib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

EVIDENCE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(EVIDENCE, "_rowa2_pixel_diff.json")

# tag, css_width, css_height, right_inset, left_inset, top_inset, kind
#   kind: inline_inset — inline-слот + горизонтальный инсет (дефект был виден
#                        пиксельно в фазе before; шапка сдвигается в after);
#         inline_zero  — нулевые инсеты (рендер шапки обязан совпасть);
#         float        — float-слот (геометрия кнопки от базового правила не
#                        зависит → пиксели кнопки before == after; шапка
#                        при инсете сдвигается).
CASES = [
    ("320x700_right44", 320, 700, 44, 0, 0, "inline_inset"),
    ("390x844_right44", 390, 844, 44, 0, 0, "inline_inset"),
    ("667x375_right44", 667, 375, 44, 0, 20, "inline_inset"),
    ("390_zero_inset", 390, 844, 0, 0, 0, "inline_zero"),
    ("667x375_float_right44", 667, 375, 44, 0, 36, "float"),
    ("390_csa56_float_right44", 390, 844, 44, 0, 56, "float"),
]


def decode_png(path):
    """→ (w, h, bpp, rows) — 8-bit, non-interlaced PNG."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG: %s" % path)
    pos, idat, ihdr = 8, [], None
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        typ = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif typ == b"IDAT":
            idat.append(chunk)
        elif typ == b"IEND":
            break
    w, h, bd, ct, _c, _f, inter = ihdr
    if bd != 8 or inter != 0:
        raise ValueError("unsupported PNG (bd=%s inter=%s)" % (bd, inter))
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(b"".join(idat))
    stride = w * bpp
    prev = bytearray(stride)
    rows, p = [], 0
    for _y in range(h):
        ft = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ft == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif ft != 0:
            raise ValueError("bad filter %s" % ft)
        rows.append(bytes(line))
        prev = line
    return w, h, bpp, rows


def diff_bbox(a_path, b_path, y_max_px=None, threshold=8):
    aw, ah, abpp, arows = decode_png(a_path)
    bw, bh, bbpp, brows = decode_png(b_path)
    if (aw, ah, abpp) != (bw, bh, bbpp):
        raise ValueError("size mismatch %s vs %s" % (a_path, b_path))
    y_to = ah if y_max_px is None else min(ah, int(y_max_px))
    diff_px, max_delta = 0, 0
    min_x, max_x, min_y, max_y = 1 << 30, -1, 1 << 30, -1
    for y in range(y_to):
        ra, rb = arows[y], brows[y]
        if ra == rb:
            continue
        for i in range(0, len(ra), abpp):
            d = (abs(ra[i] - rb[i]) + abs(ra[i + 1] - rb[i + 1])
                 + abs(ra[i + 2] - rb[i + 2]))
            if abpp == 4:
                d += abs(ra[i + 3] - rb[i + 3])
            if d > threshold:
                diff_px += 1
                x = i // abpp
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
                if d > max_delta:
                    max_delta = d
    if max_x < 0:
        return {"size": {"w": aw, "h": ah}, "diffPixels": 0, "maxDelta": 0,
                "bboxDevicePx": None, "bboxCssPx": None}
    return {"size": {"w": aw, "h": ah}, "diffPixels": diff_px,
            "maxDelta": max_delta,
            "bboxDevicePx": {"minX": min_x, "maxX": max_x, "minY": min_y, "maxY": max_y},
            "bboxCssPx": {"minX": min_x / 2, "maxX": max_x / 2,
                          "minY": min_y / 2, "maxY": max_y / 2}}


def path(tag, phase, nobtn=False):
    return os.path.join(EVIDENCE, "_rowa2_%s_%s%s.png"
                        % (tag, phase, "_nobtn" if nobtn else ""))


def main():
    rows = []
    for tag, vw, vh, r_ins, l_ins, t_ins, kind in CASES:
        row = {"tag": tag, "kind": kind, "viewport": {"w": vw, "h": vh},
               "safeAreaInset": {"top": t_ins, "bottom": 0, "left": l_ins,
                                 "right": r_ins},
               "safeEdgeCss": {"left": l_ins, "right": vw - r_ins,
                               "top": t_ins, "bottom": vh},
               "phase": {}}
        # ── 1) пиксели контрола: кадр с кнопкой vs кадр без неё ──
        for phase in ("before", "after"):
            main_png, nobtn_png = path(tag, phase), path(tag, phase, True)
            if not (os.path.isfile(main_png) and os.path.isfile(nobtn_png)):
                row["phase"][phase] = {"status": "MISSING_PNG"}
                continue
            # полоса шапки: 180 CSS px — с запасом покрывает row A + row B
            res = diff_bbox(main_png, nobtn_png, y_max_px=180 * 2)
            bb = res["bboxCssPx"]
            inside = None
            if bb:
                inside = {
                    "left": bb["minX"] >= l_ins,
                    "right": bb["maxX"] <= vw - r_ins,
                    "top": bb["minY"] >= t_ins,
                    "bottom": bb["maxY"] <= vh,
                }
            row["phase"][phase] = {
                "controlPixels": res["diffPixels"],
                "controlBBoxCssPx": bb,
                "insideSafeArea": inside,
                "insideBothAxes": (None if inside is None else all(inside.values())),
                "maxDelta": res["maxDelta"],
            }
        # ── 2/3) кадры шапки before vs after (полоса шапки) ──
        if os.path.isfile(path(tag, "before")) and os.path.isfile(path(tag, "after")):
            hd = diff_bbox(path(tag, "before"), path(tag, "after"), y_max_px=180 * 2)
            row["headerBandDiffBeforeAfter"] = {
                "diffPixels": hd["diffPixels"],
                "bboxCssPx": hd["bboxCssPx"],
                "maxDelta": hd["maxDelta"],
            }
        a = row["phase"].get("after", {})
        b = row["phase"].get("before", {})
        hb = row.get("headerBandDiffBeforeAfter", {})
        has_h_inset = bool(r_ins or l_ins)
        checks = {
            # пиксельный бокс контрола внутри safe-area в фазе after (обе оси)
            "afterPixelsInsideSafeArea": a.get("insideBothAxes") is True,
            # дефект воспроизводился пиксельно (бокс before выходил за safe-край)
            "beforeViolationReproduced": (
                (b.get("insideBothAxes") is False and b.get("controlBBoxCssPx")
                 and b["controlBBoxCssPx"]["maxX"] > vw - r_ins)
                if kind == "inline_inset" else True),
            # нулевые инсеты → шапка рендерится пиксель-в-пиксель как до фикса
            "noHeaderShiftWhenNoInset": (hb.get("diffPixels") == 0)
            if not has_h_inset else True,
            # инсеты есть → рендер шапки действительно изменился
            "headerShiftWhenInset": (hb.get("diffPixels", 0) > 0)
            if has_h_inset else True,
            # float-слот: геометрия пикселей кнопки не зависит от базового
            # правила (bbox строго равен; счётчик пикселей — с допуском на
            # шум рендера/анимации стекла, ±5% или ±50 px)
            "floatControlUnchanged": (
                (a.get("controlBBoxCssPx") == b.get("controlBBoxCssPx")
                 and abs(a.get("controlPixels", 0) - b.get("controlPixels", 0))
                 <= max(50, 0.05 * max(a.get("controlPixels", 0),
                                       b.get("controlPixels", 0))))
                if kind == "float" else True),
        }
        row["checks"] = checks
        row["ok"] = all(checks.values())
        rows.append(row)
        print("[rowa2px] %-24s afterPxBox=%-38s beforePxBox=%-38s hdrBandDiff=%-6s ok=%s"
              % (tag, a.get("controlBBoxCssPx"), b.get("controlBBoxCssPx"),
                 hb.get("diffPixels"), row["ok"]))
        for k, v in checks.items():
            if not v:
                print("           FAIL %s" % k)
    with open(RAW, "w", encoding="utf-8") as fh:
        json.dump({"generated": "2026-10-16", "phase": "before-vs-after",
                   "method": "pure-python PNG decode; control pixels = main frame "
                             "minus frame with visibility:hidden button; "
                             "header band y<=180 CSS px; device_scale_factor=2",
                   "cases": rows}, fh, ensure_ascii=False, indent=2)
    bad = [r["tag"] for r in rows if not r["ok"]]
    print("[rowa2px] FAIL: %s" % (bad or "none"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
