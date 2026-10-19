# -*- coding: utf-8 -*-
"""ACCEPTANCE-95 (c): generate the long PNG screenshot fixture with known
ground-truth text lines (vision-adapt live check).

Deterministic (seed=95): same bytes on every run. Opaque RGB PNG (no alpha,
no tRNS) — the prod ffmpeg backend must NOT skip it (NF-1 guard only skips
transparent PNG). Target: > 700 000 bytes (payload_over budget) and
< 4 000 000 px (prep_max_pixels), so the adaptive plan picks
strategy=optimize / reason=payload_over.

Output:
  fixture-95.png            — the screenshot document
  fixture-ground-truth.json — tokens/sha256/dims/bytes

Run: py -3 make_fixture.py
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent
W, H = 960, 4000
SEED = 95

GT_TOKENS = [
    "ZEBRA77", "QUARTZ88", "LOTUS99", "FALCON42",
    "ORBIT21", "MAPLE13", "RIVER64", "COMET35",
]
GT_LINES = ["GT-LINE-%02d: %s" % (i + 1, tok)
            for i, tok in enumerate(GT_TOKENS)]
GT_CYR = ["КОНТРОЛЬНАЯ-СТРОКА-А", "КОНТРОЛЬНАЯ-СТРОКА-Б"]
TITLE = "ACCEPTANCE 2.58.95 - VISION ADAPT - LONG SCREENSHOT"
BOTTOM = "END-OF-SCREENSHOT-MARKER-GT-END"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\verdana.ttf",
]


def _font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def main() -> int:
    rnd = random.Random(SEED)
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    # top colour band (visual context, part of the "screenshot")
    for i in range(180):
        shade = 40 + (i * 120) // 180
        d.line([(0, i), (W, i)], fill=(shade, 90, 160))

    f_title = _font(40)
    f_big = _font(46)
    f_mid = _font(34)
    f_small = _font(26)

    d.text((30, 40), TITLE, font=f_title, fill=(255, 255, 255))
    d.text((30, 220), "Ground-truth text lines (for OCR check):",
           font=f_small, fill=(30, 30, 30))

    y = 280
    for i, line in enumerate(GT_LINES):
        # alternating black/white text panels for OCR contrast
        panel_h = 96
        bg = (255, 255, 255) if i % 2 == 0 else (235, 235, 235)
        d.rectangle([20, y, W - 20, y + panel_h], fill=bg,
                    outline=(60, 60, 60))
        d.text((40, y + 22), line, font=f_big, fill=(10, 10, 10))
        y += panel_h + 26

    d.text((30, y + 10), GT_CYR[0], font=f_big, fill=(10, 10, 10))
    d.text((30, y + 80), GT_CYR[1], font=f_big, fill=(10, 10, 10))
    y += 170

    # photographic-ish region: seeded noise + gradient (raises PNG weight
    # and gives the vision model real visual context)
    noise_top = y
    noise_h = 1500
    px = img.load()
    for yy in range(noise_top, min(noise_top + noise_h, H)):
        base = 120 + ((yy - noise_top) * 80) // max(1, noise_h)
        for xx in range(0, W, 2):
            v = rnd.randint(-42, 42)
            r, g, b = base + v, base + v // 2, 200 - base // 3 + v
            px[xx, yy] = (max(0, min(255, r)), max(0, min(255, g)),
                          max(0, min(255, b)))
    y = noise_top + noise_h + 20

    # colourful shapes (screenshot-like widgets)
    colors = [(220, 60, 60), (60, 160, 220), (80, 180, 90), (230, 180, 40)]
    for i in range(12):
        x0 = 40 + (i % 4) * 230
        y0 = y + (i // 4) * 130
        d.rounded_rectangle([x0, y0, x0 + 190, y0 + 100], radius=12,
                            fill=colors[i % len(colors)])
        d.text((x0 + 14, y0 + 30), "W-%02d" % (i + 1), font=f_mid,
               fill=(255, 255, 255))
    y += 3 * 130 + 40

    d.text((30, y), BOTTOM, font=f_big, fill=(120, 20, 20))

    out_png = OUT_DIR / "fixture-95.png"
    img.save(out_png, "PNG", optimize=False)

    raw = out_png.read_bytes()
    meta = {
        "file": "fixture-95.png",
        "width": W, "height": H,
        "pixels": W * H,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sha256_12": hashlib.sha256(raw).hexdigest()[:12],
        "png_color_type": raw[25],
        "png_has_trns": b"tRNS" in raw[:4000],
        "gt_tokens": GT_TOKENS,
        "gt_lines": GT_LINES,
        "gt_cyr": GT_CYR,
        "title": TITLE,
        "bottom_marker": BOTTOM,
        "payload_chars_est": len(raw) * 4 // 3 + 256,
        "over_request_max_bytes_700k": len(raw) > 700_000,
        "over_payload_chars_933589": len(raw) * 4 // 3 + 256 > 933_589,
        "under_prep_max_pixels_4m": W * H <= 4_000_000,
        "seed": SEED,
    }
    (OUT_DIR / "fixture-ground-truth.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps({k: v for k, v in meta.items()
                      if k not in ("gt_lines", "gt_tokens")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
