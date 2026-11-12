import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ids14 import IDS  # noqa: E402

PY = r"C:\Code\Python\adminbot\.venv\Scripts\python.exe"


def run(tree: str, tag: str) -> dict:
    base = Path(__file__).parent
    log = base / ("ids14-%s.log" % tag)
    args = [PY, "-m", "pytest", *IDS, "-q", "--timeout=120", "-p", "no:cacheprovider",
            "--basetemp=%s" % (base / "tmp" / ("ids14-" + tag)),
            "--junitxml=%s" % (base / ("ids14-%s.xml" % tag))]
    proc = subprocess.run(args, cwd=tree, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=1800)
    log.write_text((proc.stdout or "") + "\n--- STDERR ---\n" + (proc.stderr or ""),
                   encoding="utf-8")
    import xml.etree.ElementTree as ET
    tree_xml = ET.parse(base / ("ids14-%s.xml" % tag))
    status = {}
    for case in tree_xml.iter("testcase"):
        name = "%s::%s" % (case.get("classname", ""), case.get("name", ""))
        bad = any(child.tag in ("failure", "error") for child in case)
        status[name] = "FAIL" if bad else "PASS"
    print("%s: exit=%s" % (tag, proc.returncode))
    for k in sorted(status):
        print("  %-100s %s" % (k, status[k]))
    return status


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
