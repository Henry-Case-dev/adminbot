"""Run the NEXT-02 final paired harness on ONE side (baseline or candidate).

Copies the read-only production DB copy to a run-local derived file
(sqlite3.backup from `mode=ro&immutable=1`), runs the harness against it and
deletes the derived copy afterwards. Nothing writes to the source copy.
"""
import os
import sqlite3
import subprocess
import sys

SRC = (r"C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489"
       r"\vmq-onto-01-3689dd92710d\probe-d86a98460c\prod-copy.db")
HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "next2final-harness.py")
SAMPLE = os.path.join(HERE, os.environ.get("SAMPLE_FILE",
                              "next2final-sample.json"))
ENV_FILE = r"C:\Code\Python\adminbot\.env"

side = sys.argv[1]                      # base | cand
root = sys.argv[2]                      # CODE_ROOT
tag = sys.argv[3]                       # run tag
rerank_on = sys.argv[4] if len(sys.argv) > 4 else "0"
derived = os.path.join(HERE, "derived-%s.db" % tag)
out = os.path.join(HERE, "next2final-raw-%s-%s.json" % (side, tag))

src = sqlite3.connect("file:%s?mode=ro&immutable=1" % SRC.replace("\\", "/"),
                      uri=True)
dst = sqlite3.connect(derived)
with dst:
    src.backup(dst)
print("derived", derived, os.path.getsize(derived))
dst.close()
src.close()

env = dict(os.environ)
env.update({
    "CODE_ROOT": root, "DB_PATH": derived, "OUT": out,
    "SAMPLE": SAMPLE, "ENV_FILE": ENV_FILE, "TAG": "%s-%s" % (side, tag),
    "MODE": "real", "RERANK_SEAM": os.environ.get("SEAM", "llm"),
    "RERANK_ON": rerank_on, "SEAM_KEEP": os.environ.get("SEAM_KEEP", "0"),
    "EMBED_JSON": os.path.join(HERE, "next2final-embeddings.json"),
    "BATCH_CAP_S": os.environ.get("BATCH_CAP_S", "5400"),
    "Q_CAP_S": os.environ.get("Q_CAP_S", "240"),
    "PYTHONIOENCODING": "utf-8",
})
log = open(os.path.join(HERE, "next2final-raw-%s-%s.log.txt"
                        % (side, tag)), "w", encoding="utf-8")
proc = subprocess.run([sys.executable, HARNESS], env=env, cwd=root,
                      stdout=log, stderr=subprocess.STDOUT)
log.close()
print("exit", proc.returncode, "out", out)
if os.path.exists(derived):
    os.remove(derived)
    print("derived removed")
sys.exit(proc.returncode)
