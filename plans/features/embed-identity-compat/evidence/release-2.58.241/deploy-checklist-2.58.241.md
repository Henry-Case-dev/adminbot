# Deploy checklist — 2.58.241 (EMBED-SIMPLIFY / `SIMPLIFY`)

- **Исполнитель:** DevOps (агент), хост `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot`.
- **Условие запуска:** независимое ревью **дельты релиза** дало `APPROVED_FOR_DEPLOY`
  (`requirements_gate review --slice SIMPLIFY --candidate <tip> --repo …`).
- **Выкладывается ровно:** tip ветки `release/embed-simplify-2.58.241`, `APP_VERSION 2.58.241`.
  Content-коммиты: `3ffa6f2df`, `c9ef3dfa7`; bump: `0d97fec12` (tree `8e6058e2…`); evidence-коммит —
  только документация (`git diff 0d97fec12..<tip>` не содержит кода).
- **Режим:** code-only. DDL 0, миграций 0, новых флагов/настроек 0, миграции данных нет.
- **Гейт окружения** (`vmq-env/verify-2026-11-24.md`) доказан на 2.58.240. Код совместимости в
  2.58.241 **другой**, поэтому §4–§7 ниже — обязательная проверка именно на выкаченном SHA,
  а не ссылка на прежний прогон.

## 1. Preflight (read-only)

| Что | Как | Ожидание |
|---|---|---|
| HEAD | `git -C /var/www/admin_bot rev-parse HEAD` | `f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9` |
| tracked dirty | `git status --porcelain` (tracked) | 0 |
| версия/сервис | `curl -s http://127.0.0.1:8000/healthz`; `systemctl show admin_bot -p ActiveState -p NRestarts -p MainPID` | `{"status":"ok","version":"2.58.240"}`, `active`, `NRestarts=0` |
| схема | `adminbot` venv: `PRAGMA user_version` + `sqlite_master` count; startup `pending` | `48`, 130 таблиц, `pending=[]` |
| диск | `df -B1 /var/www` | avail ≥ (размер БД + 3 GB) |
| хост-манифест | `cat /var/www/admin_bot/.deploy/release.json` | `deployed_sha=f7e20e15d…`, `version=2.58.240` |

## 2. Backup и выкладка

1. Pre-deploy backup штатным способом (`VACUUM INTO` из read-only подключения, `.partial` →
   rename только после `quick_check=ok`), имя `backups/predeploy-258241-<UTC>.db`,
   записать **bytes, sha256, quick_check, user_version, tables, owner/mode**.
   PG-дамп не нужен: схема PG не меняется.
2. `git fetch --prune origin`; `git cat-file -t <tip>`; `git checkout --detach <tip>`;
   `git rev-parse HEAD^{tree}` = ожидаемое дерево; tracked dirty = 0;
   файлов `migrations/`, `web/`, `services/database.py`, `services/graphrag_rebuild.py`
   в дельте `f7e20e15d..HEAD` — **0**.
3. `tools/release_manifest.py --effect deploy --deployer <name>` → `dirty_tracked=false`,
   `previous_sha=f7e20e15d…`, `previous_version=2.58.240`, `version=2.58.241`.
4. `systemctl restart admin_bot` **после** записи манифеста (иначе identity не будет
   `verified_deployed`); health с 1–2 попыток.

## 3. Post-deploy: базовые проверки

| Проверка | Ожидание |
|---|---|
| `/healthz` local + public | 200, `version=2.58.241` |
| Service | `active`, `NRestarts=0`, 1 процесс |
| Identity | `code=verified_deployed`, `deployed_sha == checkout_sha == tip`, `runtime == manifest == 2.58.241`, `dirty=false` |
| SQLite | `user_version=48`, 130 таблиц (как до), startup `pending=[]`, **DDL 0** |
| `web/app.js` | blob/диск/sha256 **без изменений** относительно 2.58.240 (`d97fca59a05b10ecc96a8684f55a66494ad0ab6ec47f6ae01bc45fa6c77b807a`, 2 657 173 B) — `web/*` в дельте 0 |
| `web/index.html` | пины подставляются рантаймом: `app.css?v=2.58.241`, `app.js?v=2.58.241` |
| Journal (первые 3–5 мин) | 0 Traceback, 0 CRITICAL; ERROR только известные pre-existing классы |
| Диск | `python manage.py disk audit`; `python manage.py disk cleanup --apply` (deploy-пул keep=2); свои временные файлы удалить |

## 4. Effective config (аудит §7 п.1–3)

1. PG `bot_settings` (**значения ключей не выбирать**):
   `models.embedding_base_url`, `models.embedding_model_name`, `models.embedding_dim`,
   `models.embedding_fallback{1,2}_base_url|_model`, `models.embedding_fallback2_quota_group`.
   Ожидание: primary `https://api.nano-gpt.com/api/v1`, fallbacks
   `https://generativelanguage.googleapis.com/v1beta/openai`, модель `gemini-embedding-001`,
   dims `3072`. Записать фактический источник каждого значения (hot/env/default).
2. Реестр поколений (read-only): `mca_embedding_index_generations`
   (`index_name, namespace, generation, status, model, dims, preprocessing_version, fingerprint`),
   `graph_facts_vec.count()`, `graph_facts.count()`, `smart_archive*`.
   Отдельно записать: есть ли ACTIVE-строки с `model` в namespace-форме
   (`models/…`, `google/…`) — это ровно кейс `SIMPL-R1-F1`.
3. Резолвер на текущем конфиге (read-only): `resolve_index_compat(...)` для `graph_facts_vec` →
   `state=compatible`, `class=ADMITTED_COMPATIBLE`, `serviceable=true`, `needs_probe=false`;
   в логе нет `identity changed — rebuild required`.

## 5. Один реальный embed на каждую ногу (SIMPL-01/02, окружение)

`POST /api/llm/test` c `{"block":"embeddings_main"}` → затем `embeddings_fallback1`,
`embeddings_fallback2` (global-admin TMA-сессия).
Ожидание: `ok=true`, HTTP 200, factor `3072`; записать latency и (если отдаётся) `key_slot`/provider.
Запрещено: править настройки, отключать primary, менять ключи.

## 6. Одна запись + одно семантическое чтение (SIMPL-01/02, данные)

1. **До записи** (read-only) зафиксировать `graph_facts` / `graph_facts_vec` counts и последнюю
   строку `mca_embedding_index_generations` для `graph_facts_vec`.
2. **Запись:** обычный путь «запомни» (`MemoryManager.remember_user_fact`, как в vmq-env §3 —
   без LLM-извлечения), затем:
   `graph_facts` +1, `graph_facts_vec` +1, `vec_length(embedding)=3072`, `embedding_i8` заполнен.
   В логе вокруг записи: **нет** `EMBEDDING_COMPAT_INCOMPATIBLE`, **нет** старта rebuild,
   **нет** `vector writes blocked` на этой ноге; запись не ушла в text-only по причине
   «несовместимость» (проверить по `_index_generation_writable`/`_vec_write_allowed` и логу).
3. **Чтение:** семантический запрос по смыслу записанного текста через приложение
   (`GET /api/memory/search?q=…&chat_id=…` или `MemoryManager._vec_candidates`) →
   целевая запись находится, записать `rank`, `cosine`, число кандидатов, `vector_leg` в ответе.
4. Уборка: тестовая запись живёт по `expires_at` (TTL 1 день); при необходимости удалить только её
   `graph_facts.id` / `graph_facts_vec.fact_id` (+ кэш двух текстов). Полные копии БД не создавать.

## 7. Логи: что обязано измениться (аудит §7 п.7 + новый код)

Один и тот же grep **до** и **после** (окно ≤ 1 сут, `journalctl -u admin_bot -S -1d`):

```
grep -E "not serviceable|COMPAT_|compat_insufficient|vector writes blocked|embed credential auth_failed|fallback route not admitted"
```

Дополнительно по новому коду:

| Шаблон | Ожидание после 2.58.241 |
|---|---|
| `identity changed — rebuild required` | не появляется при смене только провайдера/ключа/namespace модели |
| `compatibility probe pending` | появляется только при реально неизвестной совместимости (`insufficient`), не при `compatible` |
| `EMBEDDING_COMPAT_INSUFFICIENT` | допустим (warning, `degraded`), без паузы сборки и без старта rebuild |
| `EMBEDDING_COMPAT_INCOMPATIBLE` | только при доказанной другой модели/размерности; на namespace-only смене — **0** |
| `embed credential auth_failed` | не растёт на здоровых ключах; заменённый ключ не наследует `auth_failed` (TTL 900 s) |
| `fallback route not admitted` | 0 при совместимой ноге (гейт по MSI, не по провайдеру) |

## 8. Откат

`git checkout --detach f7e20e15d66de5d4d2f4ab787f26c0ac7b7141c9` (2.58.240) + рестарт.
**DDL 0, флагов 0, миграции данных нет**, схема `48`; pre-deploy backup на месте,
предыдущий backup из deploy-пула — тоже.

Триггеры отката: старт rebuild/`controlled_migration` без доказанной другой модели/размерности;
запись остаётся text-only дольше окна пробы без вердикта; `auth_failed` держится на ротированном
ключе; `incompatible` на legacy-строке с namespace-формой модели (регрессия F1).

## 9. Что записать в deploy-evidence

Фактический SHA/tree, версия (local+public), identity, схема/таблицы/DDL, диск (before/after/cleanup),
effective config по каждому значению с источником, поколения реестра (в т.ч. наличие namespace-строк),
три embed-ответа с latency, id тестовой записи и счётчики +1, результат semantic read (`rank`, `cosine`),
grep до/после по обоим шаблонам, политика retention и удаление своих временных файлов.
Чего нет — писать как «не проверено», а не как успех. Owner-QA не назначается: проверки выполняет
DevOps/Builder.
