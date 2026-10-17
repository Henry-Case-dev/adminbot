"""W7: генератор реплея существующего mock-e2e v6.3 (S1–S8) в scratch.

Исходный tools/ui_asap8_w2_fullscreen_e2e.py пишет PNG в соседский
каталог v6.3 (незакоммиченные файлы) — здесь путь и порт перенаправлены
в scratch, а import tools/ остаётся исходным. Код проверок не меняется.
"""
import io
import os

REPO = r"C:\Code\Python\adminbot"
SCRATCH = os.environ["OPENCODE_WORKFLOW_SCRATCH"]
SRC = os.path.join(REPO, "tools", "ui_asap8_w2_fullscreen_e2e.py")
DST = os.path.join(SCRATCH, "w7", "w2_e2e_replay.py")

src = io.open(SRC, encoding="utf-8").read()
src = src.replace(
    "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))",
    'sys.path.insert(0, r"' + os.path.join(REPO, "tools") + '")')
src = src.replace("PORT = M.PORT + 9", "PORT = M.PORT + 33")
src = src.replace(
    'EVIDENCE = os.path.join(REPO, "plans", "features", "asap8-v6-3-live-correction",\n'
    '                        "w2-evidence-fullscreen")',
    'EVIDENCE = os.path.join(r"' + os.path.join(SCRATCH, "w7",
                                                "w2-fullscreen-replay") + '")')
assert "M.PORT + 33" in src, "PORT не переписан"
assert "w2-fullscreen-replay" in src, "EVIDENCE не переписан"
io.open(DST, "w", encoding="utf-8", newline="\n").write(src)
print("written:", DST)
print([l for l in src.splitlines() if l.startswith("EVIDENCE")])
