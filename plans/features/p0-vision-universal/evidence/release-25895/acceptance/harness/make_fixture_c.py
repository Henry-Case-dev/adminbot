# -*- coding: utf-8 -*-
"""ACCEPTANCE-95c: leaner long-PNG fixture (3 large GT tokens + visual areas),
still > 700 KB so the adaptive path (payload_over) is exercised.

Wave 95b showed the free vision model returns NON-JSON (parse_error) for a
dense-text 4000px screenshot; this variant keeps the same weight but far less
text so a compliant JSON answer is plausible.

Output: fixture95c.png + fixture95c-ground-truth.json
Run: py -3 make_fixture_c.py
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).resolve().parent
W, H = 960, 2600
SEED = 195
GT_TOKENS = ["ZEBRA77", "QUARTZ88", "LOTUS99"]
TITLE = "ACCEPTANCE 2.58.95c VISION ADAPT"
BOTTOM = "END-OF-SCREENSHOT-MARKER-GT-END-C"

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
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
    # top colour band
    for i in range(140):
        shade = 40 + (i * 130) // 140
        d.line([(0, i), (W, i)], fill=(shade, 80, 150))
    f_title = _font(44)
    f_big = _font(72)
    d.text((28, 34), TITLE, font=f_title, fill=(255, 255, 255))
    y = 200
    for i, tok in enumerate(GT_TOKENS):
        d.rectangle([20, y, W - 20, y + 150], fill=(250, 250, 250),
                    outline=(50, 50, 50), width=4)
        d.text((50, y + 34), tok, font=f_big, fill=(10, 10, 10))
        y += 170
    # big visual area (keeps the PNG weight high; real visual context)
    noise_top = y + 20
    noise_h = 1300
    px = img.load()
    for yy in range(noise_top, min(noise_top + noise_h, H)):
        base = 110 + ((yy - noise_top) * 90) // max(1, noise_h)
        for xx in range(0, W, 2):
            v = rnd.randint(-46, 46)
            r, g, b = base + v, base + v // 2, 210 - base // 3 + v
            px[xx, yy] = (max(0, min(255, r)), max(0, min(255, g)),
                          max(0, min(255, b)))
    y = noise_top + noise_h + 20
    colors = [(220, 60, 60), (60, 160, 220), (80, 180, 90)]
    for i in range(3):
        x0 = 60 + i * 290
        d.rounded_rectangle([x0, y, x0 + 240, y + 110], radius=14,
                            fill=colors[i % len(colors)])
        d.text((x0 + 20, y + 30), "W-%02d" % (i + 1), font=f_title,
               fill=(255, 255, 255))
    d.text((30, y + 140), BOTTOM, font=_font(40), fill=(120, 20, 20))

    out_png = OUT_DIR / "fixture95c.png"
    img.save(out_png, "PNG", optimize=False)
    raw = out_png.read_bytes()
    meta = {
        "file": "fixture95c.png", "width": W, "height": H, "pixels": W * H,
        "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "sha256_12": hashlib.sha256(raw).hexdigest()[:12],
        "png_color_type": raw[25], "png_has_trns": b"tRNS" in raw[:4000],
        "gt_tokens": GT_TOKENS, "title": TITLE, "bottom_marker": BOTTOM,
        "payload_chars_est": len(raw) * 4 // 3 + 256,
        "over_request_max_bytes_700k": len(raw) > 700_000,
        "over_payload_chars_933589": len(raw) * 4 // 3 + 256 > 933_589,
        "under_prep_max_pixels_4m": W * H <= 4_000_000,
        "seed": SEED,
    }
    (OUT_DIR / "fixture95c-ground-truth.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
