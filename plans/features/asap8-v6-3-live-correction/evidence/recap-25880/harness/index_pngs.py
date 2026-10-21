"""RECAP-25880 — PNG index: IHDR size + bytes + sha256 for every evidence PNG."""
import hashlib
import json
import os
import struct

OUT = r"C:\Code\Python\adminbot\plans\features\asap8-v6-3-live-correction\evidence\recap-25880"


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(33)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    w, h = struct.unpack(">II", head[16:24])
    return w, h


def main():
    out = {}
    for root, _dirs, files in os.walk(OUT):
        for fn in sorted(files):
            if not fn.lower().endswith(".png"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, OUT).replace("\\", "/")
            w, h = png_size(path)
            with open(path, "rb") as f:
                data = f.read()
            out[rel] = {"width": w, "height": h, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()}
    dest = os.path.join(OUT, "png_index.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump({"count": len(out), "files": out}, f,
                  ensure_ascii=False, indent=1)
    print("pngs=%d -> %s" % (len(out), dest))
    for fn, m in out.items():
        print("%-58s %sx%s" % (fn, m["width"], m["height"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
