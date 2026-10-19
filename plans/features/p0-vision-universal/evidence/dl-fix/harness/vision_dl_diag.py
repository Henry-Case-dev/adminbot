"""VISION-DL-FIX — read-only прод-диагностика скачивания локального Bot API.

Один SSH-коннект (fail2ban-дисциплина), только чтение: docker ps/inspect,
ls/stat каталогов, HTTP-пробы к локальному Bot API, версия aiogram, ключи .env
(не секреты). Токен НИКОГДА не печатается: и argv, и stdout маскируются.

Запуск: py -3 tools/_vision_dl_diag.py [--out PATH]
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
APP = "/var/www/admin_bot"
CREDS = Path(__file__).resolve().parents[1] / "deploy_commands.txt"

REMOTE = r'''
import json, os, re, subprocess, urllib.error, urllib.request

APP = "/var/www/admin_bot"
ENV = os.path.join(APP, ".env")
CONTAINER_ROOT = "/var/lib/telegram-bot-api"
HOST_BIND = os.path.join(APP, "docker", "telegram-bot-api")

def mask(text):
    t = str(text or "")
    t = re.sub(r"\d{6,}:[A-Za-z0-9_-]{6,}", "<token:masked>", t)
    return t

def sh(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        out = p.stdout or ""
        if (p.stderr or "").strip():
            out += "\n[stderr] " + p.stderr[:400]
        return mask(out.strip())[:1200]
    except Exception as exc:                       # noqa: BLE001
        return "ERR %s: %s" % (type(exc).__name__, mask(str(exc))[:200])

def env_value(key):
    try:
        for line in open(ENV, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""

def http(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, len(r.read())
    except urllib.error.HTTPError as exc:
        try:
            body = len(exc.read() or b"")
        except Exception:                          # noqa: BLE001
            body = -1
        return exc.code, body
    except Exception as exc:                       # noqa: BLE001
        return "ERR", type(exc).__name__

res = {}
res["host"] = sh("hostname; id -un; uname -sr")
res["bot_service"] = sh("systemctl is-active admin_bot 2>/dev/null; "
                        "systemctl cat admin_bot 2>/dev/null | "
                        "grep -E '^(ExecStart|WorkingDirectory|User)=' | head -5")
res["docker_botapi"] = sh(
    "docker ps --format '{{.Names}} | {{.Image}} | {{.Ports}}' 2>/dev/null "
    "| grep -i telegram-bot-api || echo none")
res["docker_botapi_cmd"] = sh(
    "docker inspect --format '{{.Name}} cmd={{.Config.Cmd}} "
    "mounts={{range .Mounts}}{{.Source}}=>{{.Destination}} {{end}}' "
    "adminbot-telegram-bot-api 2>/dev/null | head -c 700 || echo none")
res["docker_botapi_env"] = sh(
    "docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "
    "adminbot-telegram-bot-api 2>/dev/null | grep -E '^TELEGRAM_' | "
    "sed -E 's/^(TELEGRAM_API_HASH)=.*/\\1=<masked>/' | head -5 || echo none")
res["container_root_on_host"] = sh("ls -ld %s 2>&1 || echo MISSING" % CONTAINER_ROOT)
res["host_bind_dir"] = sh("ls -ld %s 2>&1 || echo MISSING" % HOST_BIND)
res["host_bind_entries"] = sh(
    "echo count=$(ls -1 %s 2>/dev/null | wc -l); "
    "ls -1 %s 2>/dev/null | sed -E 's/^[0-9]{6,}:.*$/<token-dir:masked>/' | head -5"
    % (HOST_BIND, HOST_BIND))
res["photos_dir"] = sh(
    "ls -ld %s/*/photos 2>&1 | sed -E 's/[0-9]{6,}:[A-Za-z0-9_-]+/<token:masked>/g' | head -3; "
    "echo files=$(ls -1 %s/*/photos 2>/dev/null | wc -l)"
    % (HOST_BIND, HOST_BIND))
res["photos_tail"] = sh(
    "ls -lt %s/*/photos 2>/dev/null | head -6 | "
    "sed -E 's/[0-9]{6,}:[A-Za-z0-9_-]+/<token:masked>/g'" % HOST_BIND)
res["file_1317"] = sh(
    "ls -l %s/*/photos/file_1317.jpg 2>&1 | "
    "sed -E 's/[0-9]{6,}:[A-Za-z0-9_-]+/<token:masked>/g' | head -3" % HOST_BIND)
res["file_1317_owner"] = sh(
    "stat -c 'owner=%%U:%%G mode=%%a size=%%s' "
    "%s/*/photos/file_1317.jpg 2>&1 | head -2" % HOST_BIND)
res["botapi_version"] = sh(
    "docker exec adminbot-telegram-bot-api telegram-bot-api --version 2>&1 | head -3 "
    "|| echo none")
res["py"] = sh("for p in %s/venv/bin/python %s/.venv/bin/python3 python3; do "
               "if \"$p\" -c 'import aiogram' 2>/dev/null; then echo PY=$p; "
               "\"$p\" -c 'import aiogram;print(\"aiogram=\"+aiogram.__version__)'; "
               "break; fi; done" % (APP, APP))
res["env"] = {
    "LOCAL_BOT_API_URL": mask(env_value("LOCAL_BOT_API_URL")),
    "TELEGRAM_API_FILES_DIR": mask(env_value("TELEGRAM_API_FILES_DIR")),
    "DOWNLOAD_ENABLED": mask(env_value("DOWNLOAD_ENABLED")),
    "TELEGRAM_LOCAL": mask(env_value("TELEGRAM_LOCAL")),
    "API_TOKEN": "present(len=%d)" % len(env_value("API_TOKEN") or ""),
}

tok = env_value("API_TOKEN")
base = (env_value("LOCAL_BOT_API_URL") or "http://localhost:8081").rstrip("/")
http_res = {}
if tok:
    # Каталог данных сервера: <container_root>/<token>/<path> (локальный режим
    # отдаёт абсолютный путь). URL-формы: (а) абсолютный контейнерный путь,
    # (б) относительный, (в) host-эквивалент bind-каталога. Сами URL наружу
    # НЕ печатаются (в них токен) — только статус/размер.
    tok_dir = tok
    abs_container = "%s/%s/photos/file_1317.jpg" % (CONTAINER_ROOT, tok_dir)
    rel_path = "photos/file_1317.jpg"
    host_equiv = "%s/%s/photos/file_1317.jpg" % (
        HOST_BIND.replace(APP, ""), tok_dir)
    http_res["getMe"] = http("%s/bot%s/getMe" % (base, tok))
    http_res["file_abs_container"] = http(
        "%s/file/bot%s%s" % (base, tok, abs_container))
    http_res["file_rel"] = http("%s/file/bot%s/%s" % (base, tok, rel_path))
    http_res["file_abs_host_equiv"] = http(
        "%s/file/bot%s%s" % (base, tok, host_equiv))
else:
    http_res["error"] = "API_TOKEN absent in .env"
res["http"] = http_res

print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
'''


def _pwd() -> str:
    m = re.search(r"^pass:\s*(\S+)\s*$",
                  CREDS.read_text(encoding="utf-8", errors="replace"), re.M)
    if not m:
        raise SystemExit("credential 'pass' not found")
    return m.group(1)


def main() -> int:
    out_path = None
    if "--out" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("--out") + 1])
    pw = _pwd()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, pw, timeout=30, banner_timeout=30,
                   auth_timeout=30, allow_agent=False, look_for_keys=False)
    try:
        payload = base64.b64encode(REMOTE.encode("utf-8")).decode("ascii")
        _in, out, err = client.exec_command(
            "python3 -c \"import base64,sys;exec(base64.b64decode('%s'))\""
            % payload, timeout=180)
        text = out.read().decode("utf-8", "replace")
        etext = err.read().decode("utf-8", "replace")
        if etext.strip():
            text += "\n[stderr] " + etext[:800]
        text = text.replace(pw, "***")
    finally:
        client.close()
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print("saved: %s (%d bytes)" % (out_path, len(text)))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
