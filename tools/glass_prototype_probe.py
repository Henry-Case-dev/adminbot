"""T-2816/T-2829 (ADR-1025-17 D5): объективная проверка прототипа стекла.

Поднимает локальный сервер над `tools/glass_prototype/`, монтирует vendored
`@liquidglassjs/core` 0.5.3 на реальном (анимированном) фоне и ДОКАЗЫВАЕТ, что
стекло читает содержимое ПОЗАДИ, а не фильтрует собственный декоративный слой:

  1. Рендер страницы с фоном `?bg=A` и `?bg=B` (паттерн позади сдвинут).
  2. Скриншот ОБЛАСТИ СТЕКЛА в обоих режимах → сравнение пикселей.
     Если стекло преломляет/сэмплит фон ПОЗАДИ, картинка стекла обязана
     измениться; если бы оно рисовало только свой декор — совпала бы.
  3. Проверяем, что в SVG-фильтре есть `feDisplacementMap` (смещение, не blur)
     с ненулевым `scale`, а `.ps-glass__surface` использует backdrop-фильтр
     (same-origin, inline style библиотеки; в ПЕРВОПАРТИЙНОМ CSS проекта
     url()-фильтр отсутствует).

Скриншоты сохраняются в `tools/_hotfix9_glass_probe/`. JPEG-артефактов нет —
PNG декодируем чистой стандартной библиотекой (zlib), без Pillow/numpy.

Запуск: .venv/Scripts/python.exe tools/glass_prototype_probe.py
"""
import json
import os
import struct
import sys
import threading
import zlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
PORT = 8792
OUT = os.path.join(REPO, "tools", "_hotfix9_glass_probe")


class _Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):  # noqa: N802
        p = path.split("?")[0]
        if p.startswith("/static/"):
            rel = "web/static/" + p[len("/static/"):]
        elif p.startswith("/web/"):
            rel = p[1:]
        elif p in ("/", "", "/index.html"):
            rel = "tools/glass_prototype/index.html"
        elif p == "/glass-mount.js":
            rel = "tools/glass_prototype/glass-mount.js"
        else:
            rel = p.lstrip("/")
        return os.path.join(REPO, rel.replace("/", os.sep))

    def log_message(self, *args):
        pass


def _png_pixels(path):
    """Минимальный PNG-декодер (8-bit, color type 2/6, без интерлейса)."""
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not png"
    pos = 8
    width = height = color = None
    idat = bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, depth, color, comp, filt, interlace = struct.unpack(
                ">IIBBBBB", chunk)
            assert depth == 8 and interlace == 0, "unsupported png"
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    bpp = 4 if color == 6 else 3
    stride = width * bpp
    out = bytearray(width * height * bpp)
    prev = bytearray(stride)
    ip = 0
    for y in range(height):
        f = raw[ip]
        ip += 1
        line = bytearray(raw[ip:ip + stride])
        ip += stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return width, height, bpp, out


def _mean_abs_diff(path_a, path_b):
    wa, ha, ba, pa = _png_pixels(path_a)
    wb, hb, bb, pb = _png_pixels(path_b)
    assert (wa, ha) == (wb, hb), "size mismatch"
    n = min(len(pa), len(pb))
    total = 0
    for i in range(0, n, 4):          # каждый пиксель: R+G+B (alpha не считаем)
        total += abs(pa[i] - pb[i]) + abs(pa[i + 1] - pb[i + 1]) \
            + abs(pa[i + 2] - pb[i + 2])
    return total / (n / 4 * 3)


def main() -> int:
    from playwright.sync_api import sync_playwright

    os.makedirs(OUT, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    result = {"mounted": False, "error": None, "hasDisplacement": False,
              "displacementScale": None, "surfaceBackdrop": None,
              "diffGlass": None, "diffHole": None, "failures": []}
    failures = result["failures"]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 900, "height": 600})
            console = []
            page.on("console", lambda m: (
                console.append("%s: %s" % (m.type, m.text[:200]))
                if m.type == "error" else None))
            page.on("pageerror", lambda e: console.append("pageerror: " + str(e)[:300]))

            def shot(tag):
                page.goto("http://127.0.0.1:%d/index.html?bg=%s" % (PORT, tag),
                          wait_until="load")
                page.wait_for_timeout(900)
                box = page.evaluate(
                    "() => { var r = document.querySelector('[data-probe=glass]')"
                    ".getBoundingClientRect();"
                    " var h = document.querySelector('[data-probe=hole]')"
                    ".getBoundingClientRect();"
                    " return {g:[r.x,r.y,r.width,r.height],"
                    "         h:[h.x,h.y,h.width,h.height]}; }")
                g = box["g"]
                page.screenshot(path=os.path.join(OUT, "glass_%s.png" % tag),
                                clip={"x": g[0], "y": g[1],
                                      "width": g[2], "height": g[3]})
                h = box["h"]
                page.screenshot(path=os.path.join(OUT, "hole_%s.png" % tag),
                                clip={"x": h[0], "y": h[1],
                                      "width": h[2], "height": h[3]})

            shot("A")
            result["mounted"] = bool(page.evaluate("window.__glassMounted"))
            result["error"] = page.evaluate("window.__glassError")
            result["hasDisplacement"] = bool(page.evaluate(
                "() => !!document.querySelector('filter feDisplacementMap')"))
            result["surfaceBackdrop"] = page.evaluate(
                "() => { var s = document.querySelector('.ps-glass__surface');"
                " return s ? (s.style.backdropFilter || s.style.webkitBackdropFilter"
                " || getComputedStyle(s).backdropFilter) : null; }")
            shot("B")

            # T-2816 (reviewer Low): «смещение, не blur» — читаем фактический
            # `scale` активного feDisplacementMap: нулевой scale = не преломление.
            result["displacementScale"] = page.evaluate(
                "() => { var f = document.querySelector("
                "'filter feDisplacementMap');"
                " return f ? parseFloat(f.getAttribute('scale') || '0') : 0; }")

            result["diffGlass"] = round(_mean_abs_diff(
                os.path.join(OUT, "glass_A.png"),
                os.path.join(OUT, "glass_B.png")), 3)
            result["diffHole"] = round(_mean_abs_diff(
                os.path.join(OUT, "hole_A.png"),
                os.path.join(OUT, "hole_B.png")), 3)
            result["console"] = console
            browser.close()
    finally:
        httpd.shutdown()

    if not result["mounted"]:
        failures.append("прототип: mountGlass не смонтировался (%s)"
                        % result["error"])
    if result["diffHole"] is not None and result["diffHole"] < 8:
        failures.append("фон позади не отличается A/B (diffHole=%s)"
                        % result["diffHole"])
    if result["diffGlass"] is not None and result["diffGlass"] < 4.0:
        # Стекло обязано зависеть от фона ПОЗАДИ: его изображение заметно
        # меняется при сдвиге фона (доказывает сэмплирование содержимого позади).
        # Если бы фильтровался только собственный декор — кадр совпал бы (≈0).
        failures.append(
            "стекло не реагирует на содержимое позади (diffGlass=%s)"
            % result["diffGlass"])
    if result["mounted"] and not result["hasDisplacement"]:
        failures.append("SVG-фильтр без feDisplacementMap (не преломление)")
    if result["mounted"] and not (result["displacementScale"] or 0) > 0:
        # Прозрачность/blur дали бы ненулевой diffGlass, но НЕ смещение;
        # нулевой scale доказывает, что задний контент не преломляется.
        failures.append(
            "feDisplacementMap без смещения (scale=%s)"
            % result["displacementScale"])

    print(json.dumps(result, ensure_ascii=False, indent=1))
    with open(os.path.join(OUT, "probe.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("[glass-probe] failures:", len(failures))
    for f_ in failures:
        print("  !", f_)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
