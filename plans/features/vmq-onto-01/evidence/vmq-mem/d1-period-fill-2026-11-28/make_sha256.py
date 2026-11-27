import hashlib
import pathlib

root = pathlib.Path(__file__).resolve().parent
lines = []
for path in sorted(root.iterdir()):
    if path.name in ("sha256.txt", "make_sha256.py") or not path.is_file():
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest}  {path.name}")
(root / "sha256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
