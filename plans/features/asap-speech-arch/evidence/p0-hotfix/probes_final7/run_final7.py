#!/usr/bin/env python3
"""ONE-session read-only live run for P0 LIVE-META-FINAL (134ac385).

Uploads a git-archive of the exact candidate to /tmp/p0-final7, symlinks the
prod .env/SQLite read-only, runs the committed harness (--self-check + 8 cases),
two stand runs of the SAME committed fallback the service applies, the exact
final6 E1/E2 guard recheck, and the offline analysis. Downloads evidence.
No deploy, no writes to prod, no Telegram, no keys printed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import time

import paramiko

BASE = pathlib.Path(r"C:\Code\Python\adminbot")
SCRATCH = pathlib.Path(
    r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\final7")
WT = pathlib.Path(r"C:\Code\Python\adminbot-wt-speech-p0")
EVID = WT / "plans" / "features" / "asap-speech-arch" / "evidence" / "p0-hotfix" / "probes_final6"
DEPLOY = BASE / "deploy_commands.txt"
CANDIDATE = "134ac3856f8f39ea0df3b88facbf67a422ad8c5d"
OLD_PROD = "534ac7dda6713fb407e0789fdddfa563251cdab4"
REMOTE = "/tmp/p0-final7"
REMOTE_ROOT = REMOTE + "/new"
HOST = "198.46.175.136"
USER = "nik"
PORT = 22

EXPECTED_MODULES = {
    "services/chat_prompts.py": "d6cba9a7639f7841fb86f4068678e8eb0b66c10d747b5ecd5633a0acd454cbae",
    "services/direct_l1.py": "23d608dabc149c66a6843ece215a0e476feee6141ac196c856883eb3d6cba432",
    "services/prompt_style_blocks.py": "9e0a5293d70be44f4be9bfdefda9bb5917aff8fc2fddff6400e70d00bc9e275a",
    "services/response_extent.py": "c97c7b33c130596b83b96946336b4a2b59694ff603a33659d9798a0c24cc9a1e",
    "services/direct_chat_service.py": "96811474b91b4a42e933ed8436a0a9c393e6f9016efd014dcc58318b91f18465",
    "services/summary_memory.py": "1c3810b7506574bce324739de4c9e5d513509fad8d68939262e79acb73fe9d6b",
    "services/prompt_composer.py": "60fada1200d2ba8099a6d2f170fdc02154a964bfa3d6dbe9450c2c4515d3661f",
    "services/prompt_registry.py": "6ff70744b85ab084a5ffa45954e42c665d2db7cba1870a0ae7f9f381fb5acc2c",
}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def password():
    text = DEPLOY.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"(?m)^pass:\s*(\S+)\s*$", text)
    if not m:
        raise SystemExit("password line not found")
    return m.group(1)


class Session:
    def __init__(self, client):
        self.client = client
        self.log = []

    def run(self, cmd, timeout=600, label=""):
        t0 = time.time()
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        rec = {"label": label or cmd[:80], "cmd": cmd, "rc": rc,
               "elapsed_s": round(time.time() - t0, 1),
               "stdout": out[-9000:], "stderr": err[-3000:]}
        self.log.append(rec)
        print("[%s] rc=%s %.1fs" % (label or "cmd", rc, rec["elapsed_s"]))
        if out.strip():
            print(out[-1600:])
        if err.strip():
            print("STDERR:", err[-900:])
        return rec


def main():
    local = {
        "tar": SCRATCH / "new_code.tar.gz",
        "harness": WT / "probes_full" / "harness_probe_full.py",
        "extra": EVID / "harness_extra.py",
        "effective": EVID / "harness_effective.py",
        "analysis": SCRATCH / "analysis_final7.py",
        "guard": SCRATCH / "guard_check_final7.py",
    }
    for p in local.values():
        if not p.is_file():
            raise SystemExit("missing %s" % p)
    local_sha = {k: sha256_file(v) for k, v in local.items()}
    print("local sha:", json.dumps(local_sha, indent=1))

    started = dt.datetime.now(dt.timezone.utc)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=password(),
                   timeout=20, banner_timeout=20, auth_timeout=20,
                   allow_agent=False, look_for_keys=False, compress=True)
    client.get_transport().set_keepalive(30)
    s = Session(client)
    s.run("date -u +%FT%TZ; hostname; df -h /tmp | tail -1", 60, "clock")
    s.run("cd /var/www/admin_bot && git rev-parse HEAD && "
          "git status --porcelain | wc -l && "
          "stat -c '%Y %s' local_database.db && "
          "readlink -f .env && readlink -f local_database.db", 60, "prod_before")

    s.run("rm -rf %s && mkdir -p %s/raw" % (REMOTE, REMOTE), 60, "reset_stage")
    sftp = client.open_sftp()
    sftp.put(str(local["tar"]), REMOTE + "/new.tar.gz")
    s.run("mkdir -p %s && tar -xzf %s/new.tar.gz -C %s" %
          (REMOTE_ROOT, REMOTE, REMOTE_ROOT), 240, "extract")
    s.run(("ln -sfn /var/www/admin_bot/.env {root}/.env; "
           "ln -sfn /var/www/admin_bot/local_database.db {root}/local_database.db; "
           "printf '%s' '{cand}' > {root}/PROBE_COMMIT; "
           "find {root} -type f | wc -l; du -sh {root}; "
           "readlink -f {root}/.env; readlink -f {root}/local_database.db"
           ).format(root=REMOTE_ROOT, cand=CANDIDATE), 120, "stage")
    sftp.put(str(local["harness"]), REMOTE_ROOT + "/probes_full/harness_probe_full.py")
    sftp.put(str(local["extra"]), REMOTE_ROOT + "/probes_full/harness_extra.py")
    sftp.put(str(local["effective"]), REMOTE_ROOT + "/probes_full/harness_effective.py")
    sftp.put(str(local["analysis"]), REMOTE_ROOT + "/analysis_final7.py")
    sftp.put(str(local["guard"]), REMOTE_ROOT + "/guard_check_final7.py")
    sftp.close()
    sha = s.run("cd %s && sha256sum %s probes_full/harness_probe_full.py "
                "probes_full/harness_extra.py probes_full/harness_effective.py "
                "analysis_final7.py guard_check_final7.py"
                % (REMOTE_ROOT, " ".join(EXPECTED_MODULES)), 120, "sha_server")
    server = {}
    for line in sha["stdout"].splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            server[parts[1]] = parts[0]
    modules_ok = all(server.get(k) == v for k, v in EXPECTED_MODULES.items())
    harness_ok = server.get("probes_full/harness_probe_full.py") == local_sha["harness"]
    extras_ok = (
        server.get("probes_full/harness_extra.py") == local_sha["extra"]
        and server.get("probes_full/harness_effective.py") == local_sha["effective"]
        and server.get("analysis_final7.py") == local_sha["analysis"]
        and server.get("guard_check_final7.py") == local_sha["guard"])
    print("binding modules_ok=%s harness_ok=%s extras_ok=%s"
          % (modules_ok, harness_ok, extras_ok))
    if not (modules_ok and harness_ok and extras_ok):
        client.close()
        raise SystemExit("staging binding mismatch; probes not run")

    det = s.run(
        "PYBIN=''; for cand in /var/www/admin_bot/venv/bin/python "
        "/var/www/admin_bot/.venv/bin/python "
        "/var/www/admin_bot/venv/bin/python3 "
        "/var/www/admin_bot/.venv/bin/python3; do "
        "if [ -x \"$cand\" ] && \"$cand\" -c "
        "'import aiosqlite, dotenv, aiogram, asyncpg' 2>/dev/null; then "
        "PYBIN=\"$cand\"; break; fi; done; "
        "if [ -z \"$PYBIN\" ]; then echo NO_PYBIN; "
        "ls -l /var/www/admin_bot/venv/bin/python* "
        "/var/www/admin_bot/.venv/bin/python* 2>&1; exit 9; fi; "
        "echo PYBIN=$PYBIN; \"$PYBIN\" -V", 120, "detect_pybin")
    m = re.search(r"PYBIN=(\S+)", det["stdout"])
    if det["rc"] != 0 or not m:
        client.close()
        raise SystemExit("no app venv interpreter; see session log")
    py = m.group(1)
    print("using", py)

    s.run("rm -rf %s/raw && mkdir -p %s/raw" % (REMOTE, REMOTE), 60, "reset_raw")
    sc = s.run("cd %s && %s probes_full/harness_probe_full.py --root . "
               "--self-check > %s/selfcheck_new.txt 2>&1; RC=$?; "
               "head -c 600 %s/selfcheck_new.txt; echo; "
               "grep -c '\"self_check\": \"PASS\"' %s/selfcheck_new.txt; "
               "grep -c '\": true' %s/selfcheck_new.txt; "
               "echo SELFCHECK_RC=$RC"
               % (REMOTE_ROOT, py, REMOTE, REMOTE, REMOTE, REMOTE), 300, "selfcheck")
    if "SELFCHECK_RC=0" not in sc["stdout"] or '"self_check": "PASS"' not in (sc["stdout"]):
        client.close()
        raise SystemExit("self-check failed; probes not run")

    cases = [
        ("new_A", "%s probes_full/harness_probe_full.py --root . "
                  "--label new_A --case A --repeats 2 --use-code-l1-canon "
                  "--out %s/raw/raw_new_A.json" % (py, REMOTE)),
        ("new_B", "%s probes_full/harness_probe_full.py --root . "
                  "--label new_B --case B --repeats 2 --use-code-l1-canon "
                  "--out %s/raw/raw_new_B.json" % (py, REMOTE)),
        ("eff_A", "%s probes_full/harness_effective.py --name A --root . "
                  "--repeats 2 --out %s/raw/raw_eff_A.json" % (py, REMOTE)),
        ("eff_B", "%s probes_full/harness_effective.py --name B --root . "
                  "--repeats 2 --out %s/raw/raw_eff_B.json" % (py, REMOTE)),
        ("new_C", "%s probes_full/harness_extra.py --name C --root . "
                  "--repeats 2 --out %s/raw/raw_new_C.json" % (py, REMOTE)),
        ("new_D", "%s probes_full/harness_extra.py --name D --root . "
                  "--repeats 2 --out %s/raw/raw_new_D.json" % (py, REMOTE)),
        ("new_E", "%s probes_full/harness_extra.py --name E --root . "
                  "--repeats 2 --out %s/raw/raw_new_E.json" % (py, REMOTE)),
        ("new_F", "%s probes_full/harness_extra.py --name F --root . "
                  "--repeats 2 --out %s/raw/raw_new_F.json" % (py, REMOTE)),
        ("forced_A", "%s probes_full/harness_probe_full.py --root . "
                     "--label forced_A --case A --repeats 2 "
                     "--use-code-l1-canon --force-plan research "
                     "--force-extent normal --force-structure answer "
                     "--out %s/raw/raw_forced_A.json" % (py, REMOTE)),
        ("forced_B", "%s probes_full/harness_probe_full.py --root . "
                     "--label forced_B --case B --repeats 2 "
                     "--use-code-l1-canon --force-plan research "
                     "--force-extent normal --force-structure answer "
                     "--out %s/raw/raw_forced_B.json" % (py, REMOTE)),
    ]
    for label, inner in cases:
        cmd = ("cd %s && timeout 420 %s > %s/raw/%s.out 2> %s/raw/%s.err; "
               "echo RC=$?; tail -c 900 %s/raw/%s.out; "
               "tail -c 500 %s/raw/%s.err"
               % (REMOTE_ROOT, inner, REMOTE, label, REMOTE, label,
                  REMOTE, label, REMOTE, label))
        s.run(cmd, 480, "probe_" + label)

    s.run("cd %s && %s analysis_final7.py %s %s > %s/analysis.out 2> "
          "%s/analysis.err; echo RC=$?; tail -c 4500 %s/analysis.out; "
          "tail -c 900 %s/analysis.err"
          % (REMOTE_ROOT, py, REMOTE_ROOT, REMOTE, REMOTE, REMOTE, REMOTE,
             REMOTE), 600, "analysis")
    s.run("cd %s && %s guard_check_final7.py %s > %s/guard_check.json "
          "2> %s/guard_check.err; echo RC=$?; tail -c 2500 %s/guard_check.json; "
          "tail -c 700 %s/guard_check.err"
          % (REMOTE_ROOT, py, REMOTE_ROOT, REMOTE, REMOTE, REMOTE, REMOTE),
          180, "guard_check")

    s.run("cd /var/www/admin_bot && git rev-parse HEAD && "
          "git status --porcelain | wc -l && "
          "stat -c '%Y %s' local_database.db; date -u +%FT%TZ", 60,
          "prod_after")
    s.run("ls -l %s/raw | head -40; sha256sum %s/raw/*.json | head -20"
          % (REMOTE, REMOTE), 60, "raw_list")

    dest = SCRATCH / "evidence"
    (dest / "raw").mkdir(parents=True, exist_ok=True)
    sftp = client.open_sftp()
    for name in ("analysis.json", "manifest.json", "selfcheck_new.txt",
                 "analysis.out", "analysis.err", "guard_check.json",
                 "guard_check.err"):
        try:
            sftp.get(REMOTE + "/" + name, str(dest / name))
        except OSError as exc:
            print("download miss", name, exc)
    for attr in sftp.listdir_attr(REMOTE + "/raw"):
        if attr.filename.endswith((".json", ".out", ".err")):
            sftp.get(REMOTE + "/raw/" + attr.filename,
                     str(dest / "raw" / attr.filename))
    sftp.close()
    client.close()
    finished = dt.datetime.now(dt.timezone.utc)
    session = {
        "lane": "LIVE-META-FINAL",
        "candidate": CANDIDATE,
        "prod_baseline": OLD_PROD,
        "started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_utc": finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_s": round((finished - started).total_seconds(), 1),
        "host": HOST, "user": USER, "staging": REMOTE_ROOT, "pybin": py,
        "local_sha256": local_sha,
        "binding": {"modules_ok": modules_ok, "harness_ok": harness_ok,
                    "extras_ok": extras_ok},
        "commands": s.log,
    }
    (dest / "session.json").write_text(json.dumps(session, ensure_ascii=False,
                                                   indent=1), encoding="utf-8")
    print("DONE", session["elapsed_s"], "s ->", dest)


if __name__ == "__main__":
    main()
