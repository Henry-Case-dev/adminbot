# Rollback — SMART-CORRECTIVE-01 / 2.58.203

## Target

- Code: **`0beed63df8037002ccfaacef019b8ea948d957f6`** (2.58.202)
- Version: **2.58.202**
- Schema: **47** (code-only rollback; схема и данные не откатываются)
- Manifest до деплоя: `0beed63d / 2.58.202`, `previous_sha=409f4e8a` / 2.58.201
- DB backup этого прогона:
  `backups/pre_deploy_258203_20261114T185501Z.db` (3 007 090 688 B,
  integrity ok, user_version 47)

## Exact commands (не выполнялись; deploy прошёл)

```bash
cd /var/www/admin_bot

# 1) код точно на предыдущий релиз
git switch --detach 0beed63df8037002ccfaacef019b8ea948d957f6

# 2) честный rollback-манифест (version 2.58.202, previous=c97c06e4)
venv/bin/python tools/release_manifest.py --effect rollback
chown adminbot:adminbot .deploy/release.json
chmod 644 .deploy/release.json

# 3) рестарт и health
systemctl restart admin_bot
# ждать 200:  curl -fsS http://127.0.0.1:8000/healthz
# ожидаемо: {"status":"ok","version":"2.58.202"}
```

## Final deploy rollback state

```text
status        not_executed
reason        deployment_checks_passed
recorded_utc  2026-11-14T19:08:51Z
```

`raw/verify203.json` — `ok=true`, `failed=[]`; health 200 `2.58.203`; схема
47; бюджеты OFF; caps 0; capacity 1 048 576/32 768 `provider_catalog`
verified; identity `verified_deployed`; журнал 0 traceback/0 CRITICAL
(2 ERROR — существующий anticliche-сбой, был и до релиза); digest настроек
изменён только в ожидаемой строке; manual-редакция владельца сохранена.

## Data / prompt journal note

Откат **только кода**: PostgreSQL `prompt_revisions`/`prompt_activations`,
`bot_settings` и `chat_profiles` не откатываются. После релиза 2.58.203:

- активация 2944 — `rev:a2a369bba312` (global, `factory_activate`, `applied`,
  `fac:93c42f967ef8`);
- активация 2945 — `factory_superseded_manual` (`skipped_same`) для
  сохранённой редакции `rev:d31300ef35a0`;
- тело manual-редакции (12 469 симв., sha256 `31d17506…`) и chat-override
  владельца не изменялись; global-слой содержит заводской текст
  3 462/`3140bb36…`.

Кодовый откат эти записи не удаляет. Полный откат данных (если когда-либо
потребуется) — отдельная санкционированная операция через историю ревизий,
не ручная перезапись тел SQL.
