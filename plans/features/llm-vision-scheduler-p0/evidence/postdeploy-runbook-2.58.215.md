# Postdeploy runbook — 2.58.215 (P0 train: L1 + Vision + Scheduler)

**Тип:** docs-only артефакт. Сам файл не меняет продуктовый код и не запускает миграции;
приведённые команды выполняет дежурный DevOps отдельно. Платные вызовы (L1 ×1, Vision ×9 download
+ до 9 анализов) и записи `task_jobs` выполняются только на шагах D/E по явной команде дежурного.
**База:** production `ea9f760f398a5859c5e8b981c1710b1c8bf9e787` / `2.58.214`, rollback-цель — он же.
**Кандидат:** поезд из трёх независимых веток от `ea9f760f`, bump `APP_VERSION = 2.58.215`;
release-ветка `release/p0-2.58.215`, content tip
`2b00ad035f4c19cb32f718383c429611172c0709` (3 merge + bump; evidence-коммит
следует за ним и продукт не меняет).
**Продуктовые строки:** `LVS-L1-31/32/34/37`, `LVS-EXEC-02/04/05/06`, `LVS-OUT-01/02/03`,
`LVS-VIS-02/03/05/06/07`, `LVS-SCH-01/02/03`.
**Δ DDL = 0** (ожидаемая схема — `user_version = 47`, без изменения набора таблиц).

## 0. Переменные и правила

```bash
set -euo pipefail
cd /var/www/admin_bot
source venv/bin/activate          # штатный интерпретатор юнита; нужен для `python manage.py`
export TZ=UTC
BASE=ea9f760f398a5859c5e8b981c1710b1c8bf9e787
ROLLBACK=$BASE
DOMAIN=admin-bot.duckdns.org
CHAT=-1002661910336
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
NEW_SHA=$(git rev-parse HEAD)   # фактический checkout (record it); product-tree обязан совпасть с content tip 2b00ad03 (docs-only коммиты допустимы, сверка git diff 2b00ad03..HEAD -- . ':(exclude)plans')
RELEASE_BRANCH=release/p0-2.58.215
```

* Секреты: печатать только `present/absent`, `len`, `last4`. Ни одного значения
  `API_TOKEN`, `keys.*` или URL с токеном в выводе и в evidence.
* Каждый блок выполняется на хосте под `root` из `/var/www/admin_bot`; временные файлы — только
  `/tmp/*` с удалением в конце блока (`rm -f`) согласно P0-PROD-DISK-01.
* Порядок: A (preflight) → deploy → B (identity) → C (config post) → D (L1) → E (Vision) →
  F (Scheduler) → G (rollback-решение). D/E/F пишут в разные подсистемы и не пересекаются, но
  выполняются последовательно: иначе evidence нельзя приписать конкретному шагу.
* Вердикт по каждому блоку — PASS/FAIL по таблице критериев; «примерно» не используется.

## A. Preflight (до деплоя, read-only)

```bash
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD
git status --porcelain=v1 --untracked-files=no | wc -l
grep -m1 '^APP_VERSION' config/settings.py
python - <<'PY'
import json
print(json.dumps(json.load(open(".deploy/release.json")), sort_keys=True, ensure_ascii=False))
PY
systemctl show admin_bot -p ActiveState -p SubState -p NRestarts -p ExecMainStatus -p ActiveEnterTimestamp
pgrep -af 'deploy|git fetch|pip install|git pull' || true
test -e .git/index.lock && echo INDEX_LOCK_PRESENT || echo INDEX_LOCK_ABSENT
curl -sS -o /dev/null -w 'healthz=%{http_code}\n' "https://$DOMAIN/healthz"
curl -sS "https://$DOMAIN/healthz"; echo
curl -sS -o /dev/null -w 'api_health=%{http_code}\n' "https://$DOMAIN/api/health"
```

Свободное место и копия БД (порог — как у `services/memory_backup._FREE_SPACE_SAFETY = 2.0`):

```bash
DB=local_database.db
DB_BYTES=$(stat -c %s "$DB")
WAL_BYTES=0; [ -f "$DB-wal" ] && WAL_BYTES=$(stat -c %s "$DB-wal")
AVAIL=$(df -B1 --output=avail backups | tail -1 | tr -d ' ')
NEED=$(( (DB_BYTES + WAL_BYTES) * 2 ))
echo "db=$DB_BYTES wal=$WAL_BYTES avail=$AVAIL need=$NEED"
[ "$AVAIL" -ge "$NEED" ] && echo SPACE_OK || { echo SPACE_INSUFFICIENT; exit 1; }

TARGET="backups/predeploy-258215-$STAMP.db"
python - "$TARGET" <<'PY'
import os, sqlite3, sys
target = sys.argv[1]
esc = target.replace("'", "''")
src = sqlite3.connect("file:local_database.db?mode=ro", uri=True)
src.execute(f"VACUUM INTO '{esc}'")
src.close()
copy = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
print("integrity:", copy.execute("PRAGMA integrity_check").fetchone()[0])
print("user_version:", copy.execute("PRAGMA user_version").fetchone()[0])
copy.close()
print("bytes:", os.path.getsize(target))
PY
sha256sum "$TARGET"
df -B1 --output=avail backups | tail -1 | tr -d ' '
python manage.py disk audit 2>&1 | head -40 || true
```

Если `VACUUM INTO` на read-only соединении отвергнут (`database is locked`/`unable to open`),
повторить ровно один раз через `sqlite3 local_database.db ".backup '$TARGET'"` и всё равно выполнить
read-back выше; при повторном отказе — не деплоить.

| Критерий | PASS |
|---|---|
| identity | HEAD = ожидаемый release commit, `tracked dirty = 0`, `.deploy/release.json` от предыдущего деплоя (`previous_version=2.58.214`), `APP_VERSION` = версия манифеста |
| unit | `ActiveState=active`, `SubState=running`, `NRestarts=0`, `ExecMainStatus=0` |
| деплои | `INDEX_LOCK_ABSENT`, нет живых `git fetch/pip/deploy` процессов |
| health | `healthz=200` и JSON `version` = `2.58.214` |
| backup | `integrity=ok`, `user_version=47`, `sha256` записан, `bytes` > 0 |
| место | `avail >= 2 × (db + wal)` **до** копии, и `avail` после копии ≥ 1.5 × db |

## B. Identity после деплоя

```bash
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD
git status --porcelain=v1 --untracked-files=no | wc -l
grep -m1 '^APP_VERSION' config/settings.py
python - <<'PY'
import json
print(json.dumps(json.load(open(".deploy/release.json")), sort_keys=True, ensure_ascii=False))
PY
systemctl show admin_bot -p ActiveState -p SubState -p NRestarts -p ExecMainStatus -p ActiveEnterTimestamp
curl -sS "https://$DOMAIN/healthz"; echo
curl -sS -o /dev/null -w 'api_health=%{http_code}\n' "https://$DOMAIN/api/health"
python - <<'PY'
import sqlite3
c = sqlite3.connect("file:local_database.db?mode=ro", uri=True)
print("user_version:", c.execute("PRAGMA user_version").fetchone()[0])
print("tables:", c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0])
print("slot_claims_rows:", c.execute("SELECT count(*) FROM slot_claims").fetchone()[0])
PY
python manage.py disk audit 2>&1 | head -40 || true
python manage.py disk cleanup --apply
```

Критерии: `HEAD = зафиксированный NEW_SHA` (фактический checkout, а не content tip), `product-tree = 2b00ad03…` (docs-only коммиты не меняют продукт), `APP_VERSION = 2.58.215`, `release.json` c `version=2.58.215` и
`previous_sha = ea9f760f…`, `/healthz` = `{"status":"ok","version":"2.58.215"}`, `user_version = 47`
(никаких миграций), `NRestarts = 0`. `disk cleanup --apply` — обязательный шаг после деплоя
(deploy-пул keep=2): подтвердить, что удалён только устаревший `predeploy-*`, свежий `$TARGET`
и ежедневный `local_database_*.db` на месте.

## C. Effective config — pre/post

Один и тот же дамп снимается дважды. Блок C1 выполняется **до** деплоя (в той же shell-сессии,
где шёл A), блок C2 — после B. Если сессия прерывалась, перед C2 переопределить `dump_cfg` из C1.

### C1. Определение и pre-dump (до деплоя)

```bash
dump_cfg() {
python - <<'PY'
import os
from config.settings import settings
from services import media_download as md, mca_vision as mv
print("TELEGRAM_API_FILES_DIR=", settings.TELEGRAM_API_FILES_DIR)
print("MEDIA_DOWNLOAD_CLOUD_FALLBACK_raw=", repr(os.getenv("MEDIA_DOWNLOAD_CLOUD_FALLBACK")))
print("MEDIA_DOWNLOAD_CLOUD_FALLBACK_effective=", md.cloud_fallback_enabled())
print("VISION_TICK_SECONDS=", mv.VISION_TICK_SECONDS)
print("DIRECT_L1_env_present=", ",".join(sorted(k for k in os.environ if k.startswith("DIRECT_L1_"))) or "-")
print("LLM_MODEL_NAME_env=", settings.LLM_MODEL_NAME)
print("LLM_BASE_URL_env=", settings.LLM_BASE_URL)
print("LLM_API_KEY_env_len=", len(os.getenv("LLM_API_KEY", "")))
print("API_TOKEN_len=", len(os.getenv("API_TOKEN", "")))
PY
}
dump_cfg > /tmp/cfg-pre-258215.txt
```

### C2. Post-dump и сравнение (после деплоя)

```bash
dump_cfg > /tmp/cfg-post-258215.txt
diff -u /tmp/cfg-pre-258215.txt /tmp/cfg-post-258215.txt || true
cat /tmp/cfg-post-258215.txt
rm -f /tmp/cfg-pre-258215.txt /tmp/cfg-post-258215.txt
```

PG-слой (hot-first) — значения и «последняя запись», без ключей. Пользователь/БД контейнера
берутся из его окружения (печатаются только они, пароль в выборку не попадает):

```bash
docker exec adminbot-postgres env | grep -E '^POSTGRES_(USER|DB)='
# -U/-d ниже — значения по умолчанию compose; при отличии подставить фактические
docker exec adminbot-postgres psql -U adminbot -d adminbot -At -F '|' -c "
SELECT key, value::text, updated_at
FROM bot_settings
WHERE key IN ('models.llm_model_name','models.llm_base_url','models.llm_display_name',
              'models.vision_model','models.vision_api_base_url',
              'limits.chat_context_budget_tokens','models.chat_model_context_window')
ORDER BY key;"
```

Присутствие ключей (без значений; ожидается **пусто**, если владелец их не задавал):

```bash
docker exec adminbot-postgres psql -U adminbot -d adminbot -At -c "
SELECT key FROM bot_settings
WHERE key LIKE 'models.direct_l1%' OR key LIKE 'keys.direct_l1%'
   OR key LIKE 'limits.direct_l1%' OR key LIKE 'flags.direct_l1%'
ORDER BY key;"
```

Ключ main-слота — только длина/last4:

```bash
docker exec adminbot-postgres psql -U adminbot -d adminbot -At -F '|' -c "
SELECT 'keys.llm_api_key',
       length(value #>> '{}'),
       right(value #>> '{}', 4)
FROM bot_settings WHERE key='keys.llm_api_key';"
```

| Параметр | Ожидание 2.58.215 | Источник |
|---|---|---|
| `models.llm_model_name` | `z-ai/glm-5.3-uncensored` | PG (env `LLM_MODEL_NAME` перекрыт) |
| `models.llm_base_url` | `https://nano-gpt.com/api/v1` | PG |
| `models.llm_display_name` | подпись может остаться `NanoGPT Deepseek` — **информационно**, не блокер | PG |
| `models.direct_l1_*`, `keys.direct_l1_*`, `limits.direct_l1_*`, `flags.direct_l1_*` | **отсутствуют** (owner override не задавал); если какие-то строки всё же есть — записать значение/источник отдельно, это не автоматический FAIL, но и не «expected empty» | PG |
| `DIRECT_L1_*` env | **не заданы** | `dump_cfg` |
| `limits.direct_l1_timeout_seconds` / `…_max_output_tokens` | отсутствуют ⇒ L1 не получает 15 s/512 ни из PG, ни из env; действует transport policy 180/360 и контрактный бюджет | `dump_cfg` + PG |
| `MEDIA_DOWNLOAD_CLOUD_FALLBACK` | env отсутствует ⇒ `effective=True` (default ON в `services/media_download.py`) | `dump_cfg` |
| `TELEGRAM_API_FILES_DIR` | `docker/telegram-bot-api` (или ровно то же значение, что в env; сравнить pre/post) | `dump_cfg` |
| `VISION_TICK_SECONDS` | `5` — это **кодовая константа**, не настройка; значение не должно меняться поездом | `dump_cfg` |

Pre/post diff обязан быть пустым: любое расхождение означает, что деплой изменил конфигурацию, и
требует объяснения до шага D. (`APP_VERSION` в дамп не входит — он проверяется в B.)

## D. L1 — один контролируемый реальный вызов

Механика: штатный `LLMClient` + штатный резолвер маршрута L1 + штатный системный промпт и
`build_l1_context`. Сообщение никуда не публикуется и в Telegram не отправляется; `chat_id`
передаётся только в резолвер маршрута, а сам вызов идёт **без** `chat_id` — per-chat ключи и
бюджеты не задействуются, запись настроек не выполняется. Ровно **один** вызов; ремонт/повтор
harness не делает (второй вызов — отдельное решение дежурного). `resolve_l1_route` может потратить
несколько секунд на резолв capability провайдера — это ожидаемо. Строки `LLM request OK`
печатаются в stderr harness'а (отдельный процесс, journald их не увидит) и служат счётчиком
фактических запросов.

```bash
cd /var/www/admin_bot
venv/bin/python - 2>/tmp/l1-probe-258215.err <<'PY'
import asyncio, inspect, json, logging, time
from services.pg_db import PgDatabase
from services.param_catalog import normalize_value
from services.hot_config import set_config_cache
from services import hot_config as hot
from services import direct_l1 as l1
from services.llm_client import LLMClient
from services.prompt_style_blocks import resolve_prompt
from services.chat_prompts import DIRECT_L1_PLANNER_SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
CHAT_ID = -1002661910336


class _RoHot:
    """Read-only hot-cache: те же значения bot_settings, что видит бот.

    Не вызывает `PgDatabase.init()`/`ConfigCache.init()` — значит нет ни DDL,
    ни сидов, ни записи настроек; и не отдаёт `.pg`, поэтому usage-строка
    из harness в PG не пишется (расход фиксируется по `usage` ответа).
    """

    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


def _a(obj, name):
    value = getattr(obj, name, None)
    return list(value) if isinstance(value, (list, tuple, set)) else value


async def main():
    pg = PgDatabase()
    await pg.connect()
    if pg.pool is None:
        print(json.dumps({"error": "pg_unavailable"}))
        return
    async with pg.pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM bot_settings")
    set_config_cache(_RoHot({r["key"]: normalize_value(r["key"], r["value"])
                             for r in rows}))
    try:
        llm = LLMClient(hot.get("models.llm_base_url", ""),
                        hot.get("keys.llm_api_key", ""),
                        hot.get("models.llm_model_name", ""),
                        hot.get("models.embedding_model_name", ""))
        slot = l1.resolve_l1_model(CHAT_ID)
        route = await l1.resolve_l1_route(slot, llm)
        system_prompt = resolve_prompt("prompts.direct_l1_planner_system_prompt",
                                       DIRECT_L1_PLANNER_SYSTEM_PROMPT)
        context = l1.build_l1_context(
            query="Постдеплой-проверка L1: верни план на нейтральное сообщение.",
            speaker="проверка", addressee="чат", capabilities=())
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": context}]
        kwargs = {"step": "l1_planner", "module": "direct_chat",
                  "max_output_tokens": route.max_output_tokens}
        if "output_field" in inspect.signature(
                llm.generate_with_metadata).parameters:
            kwargs["output_field"] = route.output_field
        started = time.monotonic()
        completion, error = None, None
        try:
            completion = await asyncio.wait_for(
                llm.generate_with_metadata(messages, **kwargs),
                timeout=float(route.deadline_seconds or 360.0))
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:160]}"
        elapsed_ms = int((time.monotonic() - started) * 1000)
        plan = l1.parse_l1_plan(completion.text) if completion else None
        print(json.dumps({
            "route": {"model": route.model, "provider": route.provider,
                      "endpoint": route.endpoint, "key_slot": route.key_slot,
                      "dedicated": route.dedicated, "usable": route.usable,
                      "timeout_seconds": route.timeout_seconds,
                      "deadline_seconds": route.deadline_seconds,
                      "timeout_source": route.timeout_source,
                      "output_field": route.output_field,
                      "max_output_tokens": route.max_output_tokens,
                      "output_reserve": route.output_reserve,
                      "output_source": route.output_source,
                      "max_output_ceiling": route.max_output_ceiling,
                      "context_window": route.context_window,
                      "context_source": route.context_source,
                      "window_confidence": route.window_confidence,
                      "window_estimated": route.window_estimated,
                      "supports_reasoning": route.supports_reasoning},
            "elapsed_ms": elapsed_ms, "error": error,
            "completion": None if completion is None else {
                "model": completion.model, "provider": completion.provider,
                "finish_reason": completion.finish_reason,
                "max_output_tokens_sent": completion.max_output_tokens_sent,
                "attempt": completion.attempt, "usage": completion.usage,
                "fallback_chain": list(getattr(completion,
                                               "fallback_chain", ()))},
            "plan": None if plan is None else {
                "action": _a(plan, "action"),
                "response_act": _a(plan, "response_act"),
                "execution_mode": _a(plan, "execution_mode"),
                "confidence_bucket": _a(plan, "confidence_bucket"),
                "capabilities_needed": _a(plan, "capabilities_needed")},
            "failure_mode": l1.resolve_failure_mode(
                plan_present=plan is not None),
        }, ensure_ascii=False, indent=2))
    finally:
        await pg.close()

asyncio.run(main())
PY
```

| Критерий | PASS | FAIL-сигнал |
|---|---|---|
| model/endpoint | `route.model = z-ai/glm-5.3-uncensored`, `route.provider = nanogpt`, `route.endpoint = nano-gpt.com`, `key_slot=main`, `dedicated=false` | другой model/host ⇒ конфиг перетёрт |
| payload | `completion.max_output_tokens_sent == route.max_output_tokens` (> 512, ожидаемо 4608); `route.output_field` — имя поля, которое клиент обязан отправить (`max_tokens` для GLM по capability); фактическое применение подтверждают HTTP 200 и совпадение отправленного бюджета | `max_output_tokens_sent` пуст/512 ⇒ старый дефолт жив; 400/422 ⇒ несовместимое поле |
| дедлайн | `route.timeout_seconds = 180`, `route.deadline_seconds = 360`, `timeout_source=transport_policy` | 15/360 или `owner` без owner-override |
| ответ | `finish_reason` ≠ `length`; `plan` не `null`; `failure_mode = success` | `length`+`plan=null` ⇒ бюджет снова мал; `plan=null` при `stop` ⇒ валидатор/формат |
| стоимость | `usage.prompt_tokens`/`completion_tokens` заполнены; ровно одна строка `LLM request OK` в stderr | 2+ строки без явного решения |
| fallback | `fallback_chain` пуст | непустой chain ⇒ провайдер/ключ |

```bash
grep -c 'LLM request OK' /tmp/l1-probe-258215.err
grep 'LLM request OK' /tmp/l1-probe-258215.err
rm -f /tmp/l1-probe-258215.err
```

Стоимость: harness читает `bot_settings` из PG **только на чтение** (короткий пул без
`init()`/DDL/сидов) и не отдаёт клиенту PG-провайдер, поэтому `llm_usage_events` отдельной строкой
не пополняется — расход фиксируется по `usage` из ответа в evidence.

**Один вызов.** Ожидаемая стоимость — `in/out` токены из `usage` по тарифу провайдера; потолок
ответа — `route.max_output_tokens`, вход — L1-контекст, собранный `build_l1_context` с бюджетом по
умолчанию (код-дефолт `limits.direct_l1_context_tokens = 1600`, если владелец не задал иное).
Второй вызов допустим только как отдельно зафиксированное решение (например, `plan=null` при
`finish_reason=length`), и тогда в evidence пишутся оба вызова.

`failure_mode = success` из harness — это факт транспорта и парсера, **не** полный ход. Реальный
`event=L1_PLAN` (с полями хода) появится только после живого сообщения — см. §7.

Поля `L1_PLAN`, которые теперь есть в событии (N1/N4 закрыты коррективами L1), проверяются
по журналу после первого живого хода — без второго вызова и без записи настроек:

```bash
journalctl -u admin_bot --since "$DEPLOY_TS" -o cat | grep 'event=L1_PLAN' | tail -5
```

Ожидание в строке события: `finish_reason` = `stop` (не пусто и не `length` при
`failure_mode=success`), `provider=nanogpt`, `endpoint_host=nano-gpt.com`,
`key_slot=main`, `model=z-ai/glm-5.3-uncensored`; `output_field=max_tokens`,
`output_limit` > 512, `attempts` = 1 при `success`. `provider`/`endpoint_host`/`key_slot`
называют **primary** маршрут хода; при `failure_mode=provider_fallback` это первая нога,
а не та, что дала план (N4 residual — `limitations.md`, не FAIL деплоя).

## E. Vision — re-drive девяти asset'ов

### E1. Точный список (read-only)

```bash
cd /var/www/admin_bot
venv/bin/python - <<'PY'
import sqlite3, json
PREFIXES = ("08898876","86cc901e","37bef817","6df01f88","3758bc84",
            "e471f16e","3c670dd4","6aa46816","eed4777c")
c = sqlite3.connect("file:local_database.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row
q = f"""
SELECT a.asset_id, a.asset_kind, a.size_variant, a.mime, a.byte_size, a.created_at,
       j.job_id, j.status, j.attempt, j.max_attempts, j.reason_code, j.error_code,
       j.next_retry_at, j.finished_at, j.created_at AS job_created_at
FROM mca_media_assets a
LEFT JOIN task_jobs j
  ON j.coalesce_key = 'vision:asset:' || a.asset_id
 AND j.kind IN ('vision.media','vision.backfill')
WHERE a.chat_id = ?
  AND substr(a.asset_id,1,8) IN ({",".join("?"*len(PREFIXES))})
  AND a.created_at BETWEEN strftime('%s','2026-11-17 08:50:00')
                       AND strftime('%s','2026-11-17 09:25:00')
ORDER BY a.asset_id;
"""
rows = [dict(r) for r in c.execute(q, (-1002661910336, *PREFIXES))]
print(json.dumps(rows, ensure_ascii=False, indent=2))
print("count=", len(rows))
PY
```

Ожидание: `count=9`, у каждого `status=failed`, `attempt=3`, `max_attempts=4`,
`reason_code=vision_unavailable`, `error_code` пуст (дефект до фикса: класс не сохранялся),
`mca_media_analyses` для этих asset'ов отсутствует. Если на asset приходится несколько job-строк
(терминальная + активная), `count` будет > 9 — брать строку с максимальным `job_created_at` и
зафиксировать фактическое число строк в evidence. Зафиксировать 9 `asset_id` и 9 `job_id`
(полные значения); дальше используются только они.

Контроль «до»:

```bash
venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("file:local_database.db?mode=ro", uri=True)
print("analyses:", c.execute(
    "SELECT count(*) FROM mca_media_analyses WHERE asset_id IN "
    "(SELECT asset_id FROM mca_media_assets WHERE chat_id=? AND created_at BETWEEN "
    "strftime('%s','2026-11-17 08:50:00') AND strftime('%s','2026-11-17 09:25:00'))",
    (-1002661910336,)).fetchone()[0])
print("failed_jobs:", c.execute(
    "SELECT count(*) FROM task_jobs WHERE status='failed' AND kind='vision.media'").fetchone()[0])
PY
```

### E2. Постановка в очередь существующим механизмом

Используется та же операция, что делает `POST /api/oversight/jobs/{job_id}/action`
(`action=retry` → `TaskJobStore.set_next_retry`): прямых SQL-правок `task_jobs` нет, второго
воркера нет. `attempt` не сбрасывается (продуктовая семантика), поэтому каждый job получает
**ровно одну** новую попытку (3 → 4 из 4); `finished_at` прошлой попытки остаётся — это
продуктовое поведение `retry`, а не признак активной задачи. Корректив планировщика на этот шаг
не влияет.

```bash
cd /var/www/admin_bot
venv/bin/python - <<'PY'
import asyncio, json, time
from config.settings import settings
from services.database import DatabaseService
from services.task_supervisor import TaskJobStore

JOB_IDS = [
    "<job_id 1 из E1>", "<job_id 2>", "<job_id 3>", "<job_id 4>", "<job_id 5>",
    "<job_id 6>", "<job_id 7>", "<job_id 8>", "<job_id 9>",
]

async def main():
    db = DatabaseService(settings.DB_PATH)
    await db.initialize_existing()      # существующая БД, без DDL/миграций
    store = TaskJobStore(db)
    out = []
    now = int(time.time())
    for job_id in JOB_IDS:
        row = await store.get(job_id)
        if row is None:
            out.append({"job_id": job_id, "action": "missing"}); continue
        before = {"status": row["status"], "attempt": row["attempt"],
                  "reason_code": row["reason_code"], "error_code": row["error_code"]}
        if row["status"] in ("queued", "running"):
            out.append({"job_id": job_id, "action": "already_active", "before": before}); continue
        changed = await store.set_next_retry(job_id, now)
        out.append({"job_id": job_id, "action": "retry", "changed": bool(changed),
                    "before": before})
    await db.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))

asyncio.run(main())
```

Ожидание: 9 строк `"action": "retry"`, `"changed": true`. Тик (`VISION_TICK_SECONDS = 5`,
`ANALYSIS_CONCURRENCY = 2`) забирает их в пределах 60 с. Circuit breaker in-process сбрасывается
рестартом деплоя и держится 60 с после трёх подряд `vision_unavailable`; если в журнале после
E2 снова появилось 3 таких подряд — breaker открыт, ждать ≤ 60 с, повторно jobs не трогать.

### E3. Проверка исходов

```bash
cd /var/www/admin_bot
venv/bin/python - <<'PY'
import asyncio, json
from config.settings import settings
from services.database import DatabaseService
from services import mca_vision

ASSETS = ["<asset_id 1>", "<asset_id 2>", "<asset_id 3>", "<asset_id 4>", "<asset_id 5>",
          "<asset_id 6>", "<asset_id 7>", "<asset_id 8>", "<asset_id 9>"]
CHAT = -1002661910336

async def main():
    db = DatabaseService(settings.DB_PATH)
    await db.initialize_readonly()
    marks = ",".join("?" * len(ASSETS))
    cur = await db.db.execute(
        f"SELECT asset_id, status, error_reason, analyzer_model, completed_at "
        f"FROM mca_media_analyses WHERE asset_id IN ({marks})", ASSETS)
    analyses = [dict(r) for r in await cur.fetchall()]
    cur = await db.db.execute(
        f"SELECT job_id, status, attempt, reason_code, error_code, next_retry_at, finished_at "
        f"FROM task_jobs WHERE coalesce_key IN "
        f"({','.join('?' * len(ASSETS))})",
        [f"vision:asset:{a}" for a in ASSETS])
    jobs = [dict(r) for r in await cur.fetchall()]
    cur = await db.db.execute(
        f"SELECT ts, stage, outcome, reason_code, attempt, error_json FROM mca_events "
        f"WHERE event_name='vision_media' AND operation_id IN ({marks}) "
        f"ORDER BY ts DESC LIMIT 60", ASSETS)
    events = [dict(r) for r in await cur.fetchall()]
    snap = await mca_vision.runtime_snapshot(db, CHAT)
    print(json.dumps({"analyses": analyses, "jobs": jobs, "events": events,
                      "queue": snap.get("queue"), "last": snap.get("last"),
                      "last_error": snap.get("last_error")},
                     ensure_ascii=False, indent=2))
    await db.close()

asyncio.run(main())
```

Критерии:

| Исход | PASS | FAIL |
|---|---|---|
| download | в `events` есть `stage=download/outcome=success` или `get_file`/`local_read`+`cloud_download` успех; `error_json` больше не пуст ни на одном отказе | повторный пустой `error_json` |
| cloud fallback | при недоступном локальном файле — `outcome=cloud_fallback` в `diagnostics` и ровно одна строка `[vision] cloud fallback used \| file_id=<id> \| local=<class>` (site для Vision-пути — `vision`; формат из `services/media_download.py`); `error_json.stage=cloud_download` при отказе | cloud-путь не сработал при `MEDIA_DOWNLOAD_CLOUD_FALLBACK=True` |
| analysis | `status` ∈ {`ready`,`no_text`} для asset'а, либо типизированный `error_reason` с непустым `error_json.class` | `status` отсутствует/`pending` после 5 мин без ошибки |
| durable | job терминален (`completed`/`failed`) с `reason_code`/`error_code` | job остался `queued`/`running` > 10 мин |
| snapshot | если остались failed-job'ы — `last_error.error_code` содержит класс; если все job'ы завершились успешно, `last_error = null` допустим | `last_error.error_code = NULL` при наличии failed-job'ов |

Живой локальный Bot API (только счётчик, пути/токен не печатаются):

```bash
DEPLOY_TS=$(systemctl show admin_bot -p ActiveEnterTimestamp --value | awk '{print $2"T"$3"Z"}')
find docker/telegram-bot-api -type f ! -name '*.binlog' -newermt "$DEPLOY_TS" | wc -l
```

`0` — локальный Bot API по-прежнему не материализует файлы (работает только cloud fallback,
см. §7 п.4); `> 0` — локальный путь ожил, и тогда успешный download обязан идти **через него**
(`stage=local_read`/`aiogram_transport`), а не через облако. Оба варианта допустимы для деплоя;
различать их обязательно, чтобы не записать «Vision починен» без локального пути.

Если локальный Bot API по-прежнему не материализует файлы, PASS по download достигается через
cloud fallback — это штатный путь после фикса, но корневая причина локального Bot API **этим
поездом не устранена** (см. §7). Девять asset'ов с `status=failed` и `error_code` класса
`missing_local_file` — честный FAIL по доставке; анализ дополнительно не форсировать.

Финальный grep (после прогона, только хвост):

```bash
journalctl -u admin_bot --since "-10 min" -o cat | grep -E '\[vision\]|cloud fallback' | tail -40 || true
# точные формы (site='vision', класс в конце строки):
#   [vision] cloud fallback used | file_id=<id> | local=<error_class>
#   [vision] cloud fallback failed | class=<error_class>
```

## F. Scheduler

### F1. Механизм: замер блокировки loop на одном и том же классе

Замер воспроизводит именно то, что исправлено: вызывающий код. `--mode sync` повторяет базовый
call-site (`store.try_claim` прямо в loop), `--mode thread` — поставленный
(`asyncio.to_thread`). Оба режима используют один и тот же `SqliteSlotClaimStore` из
задеплоенного кода, временную БД и удержанный внешний write-lock; продовая БД не участвует.

```bash
cd /var/www/admin_bot
cat > /tmp/lag_probe_258215.py <<'PY'
import asyncio, os, sqlite3, sys, tempfile, threading, time
sys.path.insert(0, "/var/www/admin_bot")
from services.slot_claims import SqliteSlotClaimStore

MODE = sys.argv[1] if len(sys.argv) > 1 else "thread"
HOLD_S = 1.5


def _claim(store):
    return store.try_claim(kind="probe", chat_id=1, local_date="2026-01-01",
                           local_slot="06", slot_utc_instant=1,
                           config_version="probe", claimed_at=1)


def _hold_lock(path, hold_s, ready):
    # Держатель лока — отдельный поток: снять лок в конце claim'а нельзя,
    # иначе мёртвая блокировка (claim ждёт лок, лок ждёт claim).
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT INTO slot_claims (kind, chat_id, local_date, local_slot, "
                 "slot_utc_instant, config_version, claimed_at, fired, reason_code) "
                 "VALUES ('probe', 99, '2026-01-01', '00', 0, '', 0, 0, '')")
    ready.set()
    time.sleep(hold_s)
    conn.execute("ROLLBACK")
    conn.close()


async def main():
    tmp = tempfile.mkdtemp(prefix="lagprobe-")
    path = os.path.join(tmp, "claims.db")
    store = SqliteSlotClaimStore(path)
    store.apply_schema()
    ready = threading.Event()
    holder = threading.Thread(target=_hold_lock, args=(path, HOLD_S, ready),
                              daemon=True)
    holder.start()
    await asyncio.to_thread(ready.wait, 5.0)
    gaps, done = [], asyncio.Event()
    last = time.monotonic()

    async def ticker():
        nonlocal last
        while True:
            now = time.monotonic()
            gaps.append((now - last) * 1000.0)   # gap фиксируется ДО проверки done
            last = now
            if done.is_set():
                return
            await asyncio.sleep(0.005)

    t = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    if MODE == "sync":
        try:                                  # базовый call-site: прямо в loop
            _claim(store)
        except Exception:
            pass
    else:
        try:                                  # поставленный call-site: worker-thread
            await asyncio.to_thread(_claim, store)
        except Exception:
            pass
    claim_ms = (time.monotonic() - t0) * 1000.0
    done.set()
    await t
    holder.join(timeout=10)
    print(f"mode={MODE} claim_ms={claim_ms:.0f} max_loop_gap_ms={max(gaps):.1f}")
    for name in os.listdir(tmp):
        os.remove(os.path.join(tmp, name))
    os.rmdir(tmp)

asyncio.run(main())
PY
venv/bin/python /tmp/lag_probe_258215.py sync
venv/bin/python /tmp/lag_probe_258215.py thread
rm -f /tmp/lag_probe_258215.py
```

Ожидание (порядок величин проверен на коде ветки планировщика: `sync` — claim 1531 мс / gap
1531 мс, `thread` — claim 1531 мс / gap 16 мс): `claim_ms ≈ 1500` в обоих режимах; `max_loop_gap_ms`
≈ `claim_ms` в `sync` и **< 100 мс** в `thread`. Это измерение механизма на задеплоенном коде;
поведение живого процесса подтверждается F2. Условия действительности: `claim_ms ≥ 0.9 × HOLD_S`
(иначе лок не удержан — повторить) и claim завершился без `database is locked` (`HOLD_S` заведомо
меньше `busy_timeout = 5000` мс).

### F2. Живой процесс: четыре job'а, отсутствие WARN, непрерывность heartbeat

```bash
DEPLOY_TS=$(systemctl show admin_bot -p ActiveEnterTimestamp --value | awk '{print $2"T"$3"Z"}')
echo "deploy_ts=$DEPLOY_TS"
journalctl -u admin_bot --since "$DEPLOY_TS" -o cat | grep -iE 'Added job.*(nostalgia|goodmorning|uptime|summary)' || true
journalctl -u admin_bot --since "$DEPLOY_TS" -o cat | grep -c 'was missed by' || true
journalctl -u admin_bot --since "$DEPLOY_TS" -o cat | grep 'Run time of job' | tail -20 || true
journalctl -u admin_bot --since "$DEPLOY_TS" -o cat | grep -c 'skipped: maximum number of running instances' || true
```

```bash
docker exec adminbot-postgres psql -U adminbot -d adminbot -At -F '|' -c "
WITH w AS (
  SELECT ts, lag(ts) OVER (ORDER BY ts) AS prev
  FROM uptime_events
  WHERE ts > now() - interval '3 hours'
)
SELECT to_char(ts,'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),
       EXTRACT(EPOCH FROM (ts - prev))::int AS gap_s
FROM w
WHERE prev IS NOT NULL AND ts - prev > interval '90 seconds'
ORDER BY ts;"

docker exec adminbot-postgres psql -U adminbot -d adminbot -At -F '|' -c "
SELECT date_trunc('minute', ts) AS minute, count(*) AS rows
FROM uptime_events
WHERE ts > now() - interval '3 hours'
GROUP BY 1 HAVING count(*) > 1 ORDER BY 1;"
```

Ожидание: все 4 job'а зарегистрированы в журнале старта; `was missed by` = 0 (после деплоя, вне
окна рестарта); `gap_s` пусто (один пропуск минуты во время рестарта допустим — исключается окном
±3 мин от `ActiveEnterTimestamp`); `rows > 1` пусто, кроме минуты рестарта. Серии
`skipped: maximum number of running instances` для `summary_job` **ожидаемы** (долгий прогон,
семантика `max_instances=1`), их наличие само по себе не FAIL; FAIL — только если они идут
непрерывно > 15 мин без завершённого прогона.

### F3. Сверка `slot_claims` ↔ `summary_runs` и дубли

**КАН��НИЧЕСКИЙ SQL** — `plans/features/llm-vision-scheduler-p0/evidence/sch/sch_reconcile.sql`
(корректирующий коммит `491066378`, файл в этой же ветке; provisional-запрос
заменён, второй копии в runbook нет). Окно слота — `[slot_utc_instant,
следующий слот чата)`, последний слот — `+86400` с. Запросы read-only:
Q1 — прогоны по каждому `fired=1` слоту, Q2 — сводка, Q3 — обратная сторона.

```bash
cd /var/www/admin_bot
sqlite3 -readonly -header -column local_database.db \
        < plans/features/llm-vision-scheduler-p0/evidence/sch/sch_reconcile.sql
```

Для окна «с даты деплоя» добавить в CTE `summary_slots` условие
`AND local_date >= '<YYYY-MM-DD>'` (комментарий в самом файле); фильтр по
`claimed_at >= since` не использовать — канонический запрос считает окна по
слотам, а не по времени записи.

Ожидание 2.58.215: Q2 `gaps_no_run = 0`, `dups_multi_run = 0`,
`ok_one_run` = число отработанных слотов; Q3 — **0 строк**.

| Результат | Вывод |
|---|---|
| `runs_in_window = 1` у каждого claim | PASS: слот отработан ровно один раз |
| `runs_in_window = 0` при рестарте ровно в окне `claimed_at … +2 мин` | допустимое crash-window (claim до падения процесса, прогон не начался), фиксируется как известное ограничение; повторный слот не досоздаётся |
| `runs_in_window = 0` без рестарта рядом | FAIL: слот потерян |
| `runs_in_window > 1` | FAIL: дубль прогона на слот |
| Q3 вернул строки | FAIL: auto-прогон без покрывающего `fired=1` слота |

Дополнительно — отсутствие дублей за сутки по каждому чату:

```bash
docker exec adminbot-postgres psql -U adminbot -d adminbot -At -F '|' -c "
SELECT chat_id, to_char(ts,'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS ts, status
FROM uptime_events WHERE ts > now() - interval '24 hours' ORDER BY ts DESC LIMIT 5;"
```

Слоты summary — 00/06/12/18 локального времени чата (`SLOT_TIMES`, due-window 120 с, grace тика
30 с). Если после деплоя до ближайшего слота далеко, F3 по `slot_claims` выполняется на **первом
слоте после деплоя**; до этого пункт остаётся `pending (bounded observation)` и не мешает
остальным шагам — но и не помечается PASS.

### F4. Grace-инвариант (явный `misfire_grace_time`)

Поезд заменил заводской 1 s APScheduler на явные значения; для hot/конструктор-параметризуемых
интервалов действует инвариант `grace = max(1, min(константа, фактический интервал))`
(`_job_grace` в `memory_maintenance.py`, те же клампы в `nostalgia_worker`,
`uptime_heartbeat`, `dream_worker`, `lore_worker`). Фиксированные интервалы:
summary/goodmorning/nostalgia/uptime 30, uptime-cleanup 300, lore 60, dream 300,
maintenance 60/300/3600, backup 3600.

Проверка на задеплоенном коде (тесты контракта, без записи в БД):

```bash
cd /var/www/admin_bot
venv/bin/python -m pytest tests/test_p0_scheduler_loop.py::TestSchedulerJobContract -q
```

Ожидание: **3 passed** — все запущенные джобы объявляют ожидаемый grace, `coalesce=True`,
`max_instances=1`, `grace <= interval` для `IntervalTrigger`, и grace клампится к
эффективному (hot) интервалу, а не к заводскому. Если интервал в PG/env меньше константы
(например `limits.qnd_heartbeat_seconds=10`, `heartbeat_seconds=10`,
`limits.lore_tick_minutes=1`, `limits.db_wal_checkpoint_hours=0.05`), джоба обязана получить
`grace = max(1, min(константа, интервал))` — это и проверяет второй тест. Журнальный признак
нарушения — `Run time of job … was missed by …` серией после старта (F2). Grace **не**
воссоздаёт пропущенную минуту uptime: поздний sample пишется, разрыв в истории остаётся честным.

## G. Rollback

Цель — `ea9f760f398a5859c5e8b981c1710b1c8bf9e787` (`2.58.214`). Данные не сбрасываются: поезд
не содержит DDL, `user_version` остаётся 47; всё, что пишет новая версия (`slot_claims`,
`task_jobs`, `mca_media_analyses`, `mca_events`, `summary_runs`), — существующие аддитивные
таблицы, старый код их либо читает, либо игнорирует.

```bash
cd /var/www/admin_bot
git status --porcelain=v1 --untracked-files=no | wc -l          # обязан быть 0 перед переключением
git fetch --tags origin
git checkout --detach "$ROLLBACK"
git rev-parse HEAD                          # = ea9f760f…
grep -m1 '^APP_VERSION' config/settings.py  # = 2.58.214
systemctl restart admin_bot
```

Условия запуска (любое одно):

1. `/healthz` не 200 после деплоя, `NRestarts > 0` по причине кода, краш-луп; identity
   (`HEAD`/`APP_VERSION`/`release.json`) не совпадает с манифестом.
2. L1: `deterministic_fallback` на первом же реальном ходе при валидном ключе/маршруте, либо
   `failure_mode=failed` с `TimeoutError` на 360 с; либо расход/петля повторов выше одного
   планового вызова.
3. Vision: после re-drive 9/9 остаются `failed` с `missing_local_file` **и** cloud fallback
   выключен/недоступен, т.е. анализ не восстанавливается ни одним путём; либо новые регрессии
   download для голоса/video (общий транспорт).
4. Scheduler: дубли (`summary_runs > 1` на слот, `uptime` два ряда в минуту) или потеря слота
   без рестарта; `was missed by` продолжается с той же периодичностью.

После rollback: `curl /healthz` → `2.58.214`, `user_version=47`, 5 минут журнала без новых
`ERROR/Traceback`; восстановление из `$TARGET` **не требуется** (только при доказанном
повреждении БД, отдельная процедура mca-14). `git checkout --detach` не удаляет ветки и не
трогает чужие worktree; force/reset не используются. Учесть: `.deploy/release.json` — untracked
файл последнего **деплоя**, после rollback он описывает 2.58.215; identity отката подтверждается
только `git rev-parse HEAD` и `/healthz`, а не этим файлом.

## 7. Честные ограничения (что останется unverified)

1. **Реальный L1-ход** (`event=L1_PLAN` с `failure_mode=success` и полями хода) требует живого
   Telegram-сообщения; harness доказывает транспорт/маршрут/бюджет/парсер, но не сборку хода и
   не публикацию. До первого живого сообщения — `unverified`, **не** VERIFIED и **не** блокер
   деплоя. Проверяется агентом по журналу после появления трафика:
   `journalctl -u admin_bot -o cat | grep 'event=L1_PLAN'`.
2. **Смена модели без рестарта** (`LVS-L1-32`) требует записи в PG и окна без трафика; в этом
   runbook не выполняется — `unverified`, отдельное решение владельца/дежурного.
3. **Доставка Vision-результата в контекст ответа** (не «строка готова», а «учтена в реплике»)
   требует живого хода. Доказано только наличие `ready`-строки и её доступность потребителю по
   `asset_id`/scope; включение в ответ — `unverified`.
4. **Причина остановки локального Bot API 16.11 15:11** не устранена поездом: файлы могут
   продолжать не материализоваться, и тогда работает только cloud fallback. Это записывается как
   отдельный дефект/фон, а не как «Vision починен полностью».
5. **Scheduler-crash-window**: claim с `fired=1` без прогона при падении процесса между claim и
   генерацией — известное ограничение; F3 отличает его от потери слота только по близости
   рестарта. Гарантии «ни один слот не потерян при жёстком kill» нет.
6. **`nostalgia`/`goodmorning`**: проверяется отсутствие misfire и регистрация job'ов, а не факт
   публикации сообщения (зависит от флагов чатов и расписания).
7. **Grace не воссоздаёт пропущенную минуту uptime**: одиночный пропуск в минуту рестарта —
   ожидаемое поведение, а не дефект.

Ни один пункт §7 не блокирует деплой; ни один не закрывает строки как VERIFIED.

## 8. Placeholder'ы: статус на сборке 2.58.215

| # | Что | Статус |
|---|---|---|
| 1 | **SCH F2**: канонический SQL сверки `slot_claims(fired=1)` ↔ `summary_runs` | **ЗАКРЫТО** — `evidence/sch/sch_reconcile.sql` (r2 `491066378`); §F3 запускает именно этот файл, второй копии в runbook нет |
| 2 | **L1 N1**: реальный `finish_reason` в `L1_PLAN` для main-ноги | **ЗАКРЫТО** — поле `l1_finish_reason` есть в `L1_PLAN`/plan_meta (`b733e29e`); проверка в §D по журналу |
| 3 | **L1 N4**: `provider`/`endpoint_host`/`key_slot` в `L1_PLAN` | **ЗАКРЫТО для primary маршрута** — поля в whitelist события `L1_PLAN` и turn-diagnostics (durable `plan_meta` не расширялся); residual при `provider_fallback` описан в §D/`limitations.md` и не блокирует деплой |
| 4 | **SCH F3** (`grace <= interval` для env-интервалов) | **ЗАКРЫТО** — кламп `max(1, min(константа, интервал))` в r2 (`491066378`); проверка — §F4 (`TestSchedulerJobContract`, 3 passed) |
| 5 | **VIS**: точная формулировка warning'а cloud fallback | **ЗАКРЫТО** — `[vision] cloud fallback used \| file_id=<id> \| local=<error_class>` (`services/media_download.py`); проверка в §E |
| 6 | **Релизный манифест**: `NEW_SHA` и имя release-ветки | **ЗАКРЫТО на сборке** — `release/p0-2.58.215`, content tip `2b00ad03…` (`manifest-dry-run.json`); deploy-time фиксируется фактический `git rev-parse HEAD` как `NEW_SHA`; product-tree сверяется с content tip `2b00ad03` |

## 9. Evidence (заполняется по ходу)

Один компактный блок в `plans/features/llm-vision-scheduler-p0/evidence/` (без дублей
Markdown/JSON), поля:

```text
release_version=2.58.215
release_branch=release/p0-2.58.215
release_sha=2b00ad035f4c19cb32f718383c429611172c0709
previous_sha=ea9f760f398a5859c5e8b981c1710b1c8bf9e787
predeploy_snapshot=<backups/predeploy-258215-...db>
predeploy_snapshot_sha256=<sha256>
predeploy_snapshot_readback=integrity:ok user_version:47 bytes:<N>
pre_state=HEAD:<sha> branch:<name> version:2.58.214 dirty:0 unit:active NRestarts:0
post_state=HEAD:<sha> branch:<name> version:2.58.215 dirty:0 unit:active NRestarts:0
live_user_version=47
healthz={"status":"ok","version":"2.58.215"}
config_diff=empty|explained:<что именно>
l1_route=model:z-ai/glm-5.3-uncensored provider:nanogpt endpoint:nano-gpt.com key_slot:main dedicated:false
l1_route_policy=timeout:180 deadline:360 source:transport output_field:max_tokens limit:<N> reserve:<N>
l1_call=finish_reason:<x> max_output_tokens_sent:<N> attempt:1 failure_mode:success usage_in:<N> usage_out:<N> calls:1
l1_plan=action:<x> response_act:<x> execution_mode:<x> confidence:<x>
vision_redrive=jobs:9 retried:9 completed:<N> ready:<N> no_text:<N> typed_error:<N>
vision_errors=class:<x> stage:<x> count:<N>
vision_fallback=cloud_used:<N> cloud_failed:<N>
vision_snapshot=queue_failed:<N> last_error_class:<x|NULL>
sched_probe=sync_claim_ms:<N> sync_gap_ms:<N> thread_claim_ms:<N> thread_gap_ms:<N>
sched_journal=missed_by:0 uptime_gaps>90s:<N> uptime_dup_minutes:<N>
sched_slots=claims:<N> runs:1:<N> runs:0:<N> runs>1:<N>
sched_duplicates=0
unverified=real_l1_turn,model_switch_without_restart,vision_context_in_reply,local_bot_api_root_cause
verdict=<PASS|PASS WITH UNVERIFIED ITEMS|FAIL + rollback>
checked_at=<UTC>
```

`PASS WITH UNVERIFIED ITEMS` — нормальный итог при отсутствии живого трафика: обязательные
механические проверки пройдены, §7 честно открыт, строки `live_required` не закрываются.
