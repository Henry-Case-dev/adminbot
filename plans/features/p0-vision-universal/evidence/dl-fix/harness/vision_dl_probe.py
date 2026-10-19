"""VISION-DL-FIX — живая прод-проба путей скачивания (read-only, 1 коннект).

Сравнивает на прод-хосте (aiogram 3.31.0, локальный Bot API):
  A) текущая конфигурация: is_local=True + BareFilesPathWrapper (чтение ФС по
     пути контейнера) → ожидаемо FileNotFoundError (RED);
  B) фикс-кандидат: is_local=True + SimpleFilesPathWrapper(container_root →
     host bind dir) → ожидаем байты (GREEN);
  C) облачная сессия — контроль размера (эталон).
Плюс: содержимое host-bind каталога и появление файла в нём после get_file.
Токен не печатается: маскирование путей и никакого вывода URL.

Запуск: py -3 tools/_vision_dl_probe.py [--out PATH]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import paramiko

HOST = "198.46.175.136"
USER = "nik"
CREDS = Path(__file__).resolve().parents[1] / "deploy_commands.txt"

REMOTE = r'''
import asyncio, io, json, os, re, time

APP = "/var/www/admin_bot"
ENV = os.path.join(APP, ".env")
CONTAINER_ROOT = "/var/lib/telegram-bot-api"
HOST_BIND = os.path.join(APP, "docker", "telegram-bot-api")
WORK_CHAT = -1002661910336
ASSET_MID = 1165720

def mask(text):
    t = str(text or "")
    return re.sub(r"\d{6,}:[A-Za-z0-9_-]{6,}", "<token:masked>", t)

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

def listing(path):
    try:
        return sorted(os.listdir(path))[:12]
    except OSError as exc:
        return "ERR %s" % type(exc).__name__

async def main():
    import sqlite3
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import (SimpleFilesPathWrapper,
                                         TelegramAPIServer)

    token = env_value("API_TOKEN")
    base = (env_value("LOCAL_BOT_API_URL") or "http://localhost:8081").rstrip("/")
    res = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "host_bind_listing": listing(HOST_BIND),
           "token_dir_listing": "n/a"}

    # file_id тестового актива из прод-SQLite (read-only)
    db_path = os.path.join(APP, "local_database.db")
    file_id = ""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=10)
        row = con.execute(
            "SELECT file_id FROM mca_media_assets WHERE chat_id=? AND "
            "tg_message_id=? AND asset_kind='photo' LIMIT 1",
            (WORK_CHAT, ASSET_MID)).fetchone()
        con.close()
        file_id = str(row[0]) if row else ""
    except Exception as exc:                       # noqa: BLE001
        res["db_error"] = type(exc).__name__
    res["file_id_present"] = bool(file_id)

    token_dir = os.path.join(HOST_BIND, token)
    res["token_dir_listing"] = mask(str(listing(token_dir)))
    res["photos_on_host_before"] = mask(str(listing(
        os.path.join(token_dir, "photos"))))

    if not file_id:
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        return 0

    # A) текущая конфигурация (BareFilesPathWrapper, путь контейнера)
    try:
        sess = AiohttpSession(api=TelegramAPIServer.from_base(base,
                                                              is_local=True))
        bot = Bot(token=token, session=sess)
        f = await bot.get_file(file_id)
        raw = str(getattr(f, "file_path", "") or "")
        local = str(sess.api.wrap_local_file.to_local(raw))
        res["A_current"] = {"file_path_masked": mask(raw),
                            "to_local_masked": mask(local),
                            "exists": os.path.exists(local)}
        try:
            buf = io.BytesIO()
            await bot.download(f, destination=buf)
            res["A_current"]["download"] = True
            res["A_current"]["bytes"] = len(buf.getvalue())
        except Exception as exc:                   # noqa: BLE001
            res["A_current"]["download"] = False
            res["A_current"]["error"] = mask("%s: %s" % (type(exc).__name__,
                                                         str(exc)[:160]))
        await bot.session.close()
    except Exception as exc:                       # noqa: BLE001
        res["A_current"] = {"error": mask("%s: %s" % (type(exc).__name__,
                                                      str(exc)[:160]))}

    res["photos_on_host_after"] = mask(str(listing(
        os.path.join(token_dir, "photos"))))

    # B) фикс-кандидат: путь контейнера → host bind каталог
    try:
        wrapper = SimpleFilesPathWrapper(CONTAINER_ROOT, HOST_BIND)
        sess2 = AiohttpSession(api=TelegramAPIServer.from_base(
            base, is_local=True, wrap_local_file=wrapper))
        bot2 = Bot(token=token, session=sess2)
        f2 = await bot2.get_file(file_id)
        local2 = str(sess2.api.wrap_local_file.to_local(f2.file_path))
        res["B_fix"] = {"to_local_masked": mask(local2),
                        "exists": os.path.exists(local2)}
        got = False
        for attempt in range(1, 5):                # локальный API пишет файл
            try:                                   # с задержкой ~1-2с
                buf2 = io.BytesIO()
                await bot2.download(f2, destination=buf2)
                res["B_fix"]["download"] = True
                res["B_fix"]["bytes"] = len(buf2.getvalue())
                res["B_fix"]["attempt"] = attempt
                got = True
                break
            except Exception as exc:               # noqa: BLE001
                res["B_fix"]["last_error"] = mask(
                    "%s: %s" % (type(exc).__name__, str(exc)[:120]))
                await asyncio.sleep(1.0)
        if not got:
            res["B_fix"]["download"] = False
        await bot2.session.close()
    except Exception as exc:                       # noqa: BLE001
        res["B_fix"] = {"error": mask("%s: %s" % (type(exc).__name__,
                                                  str(exc)[:160]))}

    # C) облачная сессия — контроль байтов
    try:
        bot3 = Bot(token=token)
        f3 = await bot3.get_file(file_id)
        buf3 = io.BytesIO()
        await bot3.download(f3, destination=buf3)
        res["C_cloud"] = {"bytes": len(buf3.getvalue())}
        await bot3.session.close()
    except Exception as exc:                       # noqa: BLE001
        res["C_cloud"] = {"error": mask("%s: %s" % (type(exc).__name__,
                                                    str(exc)[:160]))}

    a = res.get("A_current", {}).get("bytes")
    b = res.get("B_fix", {}).get("bytes")
    c = res.get("C_cloud", {}).get("bytes")
    res["verdict"] = {"fix_matches_cloud": bool(b and c and b == c),
                      "current_failed": res.get("A_current", {}).get(
                          "download") is False,
                      "bytes": {"current": a, "fix": b, "cloud": c}}
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0

if __name__ == "__main__":
    asyncio.run(main())
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
        cmd = ("cat > /tmp/vision_dl_probe.py <<'PYEOF'\n%s\nPYEOF\n"
               "/var/www/admin_bot/venv/bin/python /tmp/vision_dl_probe.py"
               % REMOTE)
        _in, out, err = client.exec_command(cmd, timeout=300)
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
