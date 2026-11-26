"""M1-C probe — MAC-S10-13: промпты внутри ГРУППОВОГО чата по resource ACL.

Воспроизводимая проверка на выкаченном коде `ffdc6eadf` (2.58.251), а не
тест-сьют: файл лежит в evidence и вызывается вручную.

```
.venv/Scripts/python.exe plans/features/mod-acl-ux-01/evidence/m1/m1c/probe_prompt_chat_acl.py
```

Что проверяется (реальные роутеры `web/api/routes.py`, реальный RBAC
`services.roles.access_for` / `services.access`, реальный матричный резолвер;
двойники — только хранилище: роли/админы/chat_admins/param_permissions и
in-memory журнал промптов):

  1. `local_admin` этого чата + дефолтная матрица ключа → история 200,
     активация НЕ 403 (право есть);
  2. ТОТ ЖЕ актор + override матрицы `edit_roles: []` → история 200,
     активация 403 — просмотр и запись различаются, запись режется ACL;
  3. обычный участник без гранта → история 403 (изоляция чужого чата),
     активация 403;
  4. `local_admin` чата A, запрос по чату B → 403 (чужой scope не отдаётся);
  5. глобальный админ → 200 и не 403 (положительный контроль стенда).

Дискриминирующая строка — №2: если бы запись не была привязана к матрице,
она осталась бы разрешённой.

Границы: живой Telegram-клиент и живой групповой чат не используются; initData
подписан ЛОКАЛЬНЫМ тестовым токеном (не production).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "..", ".."))
sys.path.insert(0, REPO)
os.chdir(REPO)

from fastapi.testclient import TestClient  # noqa: E402

from services import prompt_registry as pr  # noqa: E402
from services import prompt_release_policy as prp  # noqa: E402
from services import access as access_srv  # noqa: E402
from services.config_cache import ConfigCache  # noqa: E402
from web.api import deps as deps_mod  # noqa: E402
from web.api import routes as routes_mod  # noqa: E402
from web.app import create_app  # noqa: E402

# Готовый стенд MOD-ACL (роли/админы/pool) — переиспользуется как есть.
from tests.test_mod_acl_ux_m4c_acl_hardening import (  # noqa: E402
    LOCAL_ADMIN_ID, OWNER_ID, PLAIN_USER_ID, TEST_TOKEN, _Conn, _Db, _Pg,
    _seed, make_init_data,
)

# Тот же ЛОКАЛЬНЫЙ тестовый токен, которым подписан initData (не production).
deps_mod.settings = __import__("types").SimpleNamespace(API_TOKEN=TEST_TOKEN)

CHAT_A = -1001000000001
CHAT_B = -1001000000002
BLOCK = "summary.base.narrator"
PG_KEY = "prompts.summary_narrator_system_prompt"
FACTORY = "ЗАВОДСКОЙ текст рассказчика (probe M1-C).\n"


class ChatConn(_Conn):
    """Двойник хранилища + гранты `chat_admins` (реальный SQL читает роль)."""

    def __init__(self, db, chat_grants: dict):
        super().__init__(db)
        self.chat_grants = dict(chat_grants)
        self.perm_rows: dict[str, dict] = {}

    async def fetchrow(self, sql, *args):
        low = " ".join(sql.lower().split())
        if "from chat_admins" in low:
            key = (int(args[0]), int(args[1]))
            role = self.chat_grants.get(key)
            return {"role_name": role} if role else None
        if "from param_permissions" in low and low.startswith("select"):
            row = self.perm_rows.get(args[0])
            return dict(row) if row else None
        return await super().fetchrow(sql, *args)

    async def fetch(self, sql, *args):
        if "from param_permissions" in " ".join(sql.lower().split()):
            return [dict(row) for row in self.perm_rows.values()]
        return await super().fetch(sql, *args)


def _client(chat_grants: dict, perm_overrides: dict) -> TestClient:
    # TTL-кэш override'ов (`param_permissions`) модульный: без сброса матрица
    # прошлого кейса жила бы 60 с и следующий кейс проверял бы не то.
    access_srv.reset_param_permissions_cache()
    db = _Db()
    conn = ChatConn(db, chat_grants)
    for key, value in (perm_overrides or {}).items():
        conn.perm_rows[key] = {"key": key, "value": json.dumps(value),
                               "updated_at": "2026-11-26T00:00:00+00:00"}
    cache = ConfigCache(pg=_Pg(conn), retry_attempts=1, retry_delay=0)
    _seed(cache, db)
    journal = prp.MemoryPromptJournal()
    routes_mod._prompt_journal = lambda cache_: journal
    prp.default_journal = lambda cache_: journal
    client = TestClient(create_app(cache))
    client.cache = cache
    client.journal = journal
    return client


def _hdr(user_id: int, chat_id: int | None = None) -> dict:
    out = {"X-Telegram-Init-Data": make_init_data(user_id)}
    if chat_id is not None:
        out["X-Chat-Id"] = str(chat_id)
    return out


def _revision_id(client, text: str, chat_id: int) -> str:
    rid = pr.revision_id_for(BLOCK, "chat", chat_id, "manual", pr.sha12(text))
    client.journal.revisions[rid] = prp.RevisionRow(
        revision_id=rid, block_id=BLOCK, scope="chat", origin="manual",
        content_sha12=pr.sha12(text), body=text, pg_key=PG_KEY,
        chat_id=chat_id, created_at="2026-11-26T00:00:00+00:00")
    return rid


def main() -> int:
    results = []

    def run(name, grants, overrides, actor, chat_id, expect_view, expect_edit_403):
        client = _client(grants, overrides)
        rev = _revision_id(client, FACTORY, CHAT_A)
        view = client.get(f"/api/prompts/{PG_KEY}/versions",
                          headers=_hdr(actor, chat_id))
        edit = client.post(f"/api/prompts/{PG_KEY}/activate",
                           json={"revision_id": rev},
                           headers=_hdr(actor, chat_id))
        results.append({
            "case": name, "actor": actor, "chat": chat_id,
            "view_status": view.status_code,
            "edit_status": edit.status_code,
            "edit_body": edit.text[:120],
            "view_expected": expect_view,
            "edit_403_expected": expect_edit_403,
            "ok": (view.status_code == expect_view
                   and (edit.status_code == 403) == expect_edit_403),
        })

    default_grants = {(CHAT_A, LOCAL_ADMIN_ID): "local_admin"}
    run("1 local_admin, дефолтная матрица (право записи есть)",
        default_grants, {}, LOCAL_ADMIN_ID, CHAT_A, 200, False)
    run("2 local_admin, override edit_roles=[] (запись режется ACL)",
        default_grants, {PG_KEY: {"view_roles": ["local_admin"],
                                  "edit_roles": []}},
        LOCAL_ADMIN_ID, CHAT_A, 200, True)
    run("3 local_admin вне view_roles/update (просмотр режется ACL)",
        default_grants, {PG_KEY: {"view_roles": ["moderator"],
                                  "edit_roles": ["moderator"]}},
        LOCAL_ADMIN_ID, CHAT_A, 403, True)
    run("4 участник без гранта (изоляция чужого/группового чата)",
        default_grants, {}, PLAIN_USER_ID, CHAT_A, 403, True)
    run("5 local_admin чата A читает чат B (чужой scope)",
        default_grants, {}, LOCAL_ADMIN_ID, CHAT_B, 403, True)
    run("6 глобальный админ (положительный контроль стенда)",
        default_grants, {}, OWNER_ID, CHAT_A, 200, False)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    bad = [r for r in results if not r["ok"]]
    print()
    if bad:
        print("PROMPT-CHAT-ACL-GAP: %d из %d строк не совпали"
              % (len(bad), len(results)))
        return 1
    print("PROMPT-CHAT-ACL-ENFORCED: %d/%d строк — просмотр и запись "
          "решаются ACL в контексте группового чата "
          "(постоянный замок: tests/test_mod_acl_ux_01_m1c_prompt_chat_acl.py)"
          % (len(results), len(results)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
