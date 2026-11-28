"""SHA256SUMS for raw/ artefacts of release 2.58.268."""
import hashlib
from pathlib import Path

RAW = Path(__file__).resolve().parent
EV = RAW.parent
rows = []
for p in sorted(RAW.iterdir()):
    if p.name == "SHA256SUMS" or not p.is_file():
        continue
    rows.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  raw/{p.name}")
for p in sorted(EV.glob("*.md")):
    rows.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
(RAW / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")
print("\n".join(rows))
