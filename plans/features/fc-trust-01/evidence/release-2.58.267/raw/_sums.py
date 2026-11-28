import hashlib
from pathlib import Path

d = Path(__file__).resolve().parents[1]
rows = []
for p in sorted(list(d.glob("*.md")) + list((d / "raw").glob("*"))):
    if p.name == "SHA256SUMS" or p.is_dir():
        continue
    rel = p.relative_to(d).as_posix()
    rows.append(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + rel)
(d / "raw" / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")
print("\n".join(rows))
