# Deploy 2.58.170 — VMQ-V, SELF-DIAG-01 D1, MEMORY-08 S3, EXP-FIX (M5A), schema v45

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`).

## 1. Границы выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.170` = `42f068df22edeeb82062525446b71d7022a6006b` |
| Кандидат на ревью | `33707364` (продуктовый код идентичен) |
| Bump-коммит | `42f068df` — только `APP_VERSION`, пины тестов, F8-мета (29 строк) |
| Предыдущий прод | `b2fed707` @ `release/2.58.169`, healthz 2.58.169, schema 44 |
| MUTABLE_WORKTREE_REQUIRED | **no** — immutable checkout по SHA, `dirty_tracked=0` |
| Repo write scope | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 24 test-файла |
| Δ DDL | **+1** миграция `voice_transcript_v45` (аддитивные колонки) |

### Дельта `b2fed707..33707364` (7 коммитов)

| Коммит | Суть |
|---|---|
| `2b791233` | docs: отчёт выкладки 2.58.169 (продуктового кода нет) |
| `0c6dc58d` | SELF-DIAG-01 D1: локальный backend логов чекапа, Better Stack удалён из чекапа |
| `b8617cbb` | VMQ-V: голосовой source-ref → версия расшифровки → payload Writer (v45) |
| `f71dfb56` | D1: честная fallback-приписка чекапа |
| `d0127c29` | MEMORY-08 S3: omnibox «Найти в памяти» + гейт `flags.memory_search_enabled` |
| `4e07817e` | EXP-FIX-01..07/09/10: durable checkpoint, дренаж, typed parse/write, тик, dedup, discovery |
| `33707364` | пины головы схемы 44→45 |

Продуктовые файлы: `bot.py`, `config/settings.py`, `handlers/voice_transcription.py`,
`services/{checkup_prompts,config_cache,database,direct_chat_service,llm_probe,mca_experience,mca_experience_jobs,mca_gates,memory_maintenance,param_catalog,prompt_registry,smartmodule_phrases,system_logs_fetcher,voice_transcripts}.py`,
`web/api/{cognitive_map,memory_overview}.py`, `web/{app.js,index.html,static/app.css,static/cognitive-map.js}`.
Посторонних продуктовых правок в дельте нет.

## 2. Предрелизная проверка (точно на кандидате)

| Набор | Результат |
|---|---|
| voice/direct + checkup (vmq_v, voice_transcription, media_transcribe, checkup_prompts, cfg07 x2) | **280 passed** |
| memory/communities + mem08 + cog-map widget | **154 passed, 1 failed** |
| experience (exp_fix semantic checkpoint, asap8 b02) + pins (evol014/016, mca17c, ur_c_sched) | **104 passed** |
| F8-каталог `--check` | `CHECK OK: 595`, R17-чисто |
| JS mem08 omnibox | `MEM-08-S3-OK checks=103` |
| version-пины после bump | **73 passed** |

**Классификация падения:** `test_evol_cog_map_widget.py::test_cmv_node_suites_run` →
`tests/js/evol_cog_scene_test.js`: `this._cogBlitLabel is not a function`.
Воспроизведено на базовом `b2fed707` в отдельном worktree (тот же TypeError) — **предсуществующее**,
дельтой не затронуто (`d0127c29` участок `_cogBlitLabel` не менял; метод есть в обоих деревьях).

Аудит «мёртвого» ключа: `flags.memory_search_enabled` имеет потребителя —
`mca_gates.py:660,816` (гейт), `web/api/cognitive_map.py:904,1000` (409), `config_cache.py:120` (factory ON),
`param_catalog.py:3584` (ParamSpec). Блокер снят.

## 3. Выкладка

- Снапшот: `pre_migration_20261108_220853.db` создан самим backup-guard (`VACUUM INTO` + read-back ok,
  `user_version 44`, 1 696 137 216 B) — **до** применения шага.
- Мой контрольный снапшот после миграции: `/tmp/predeploy-258170.db` (1 773 735 936 B,
  sha256 `50724a70…`, read-back `user_version 45`, `quick_check ok`).
- `git fetch origin release/2.58.170` → `git checkout -B release/2.58.170 42f068df` → `dirty_tracked=0`.
- `systemctl restart admin_bot` → старт 22:08:49Z, миграция 22:08:53→22:09:11, healthz 2.58.170.

## 4. Пост-деплой

| Проверка | Факт |
|---|---|
| Unit | `active (running)`, **NRestarts=0**, MainPID `3233804`, старт 2026-11-08T22:08:49Z |
| `/healthz` локально | `{"status":"ok","version":"2.58.170"}` |
| `/healthz` публично (`admin-bot.duckdns.org`) | 200, `2.58.170` |
| Журнал | `Traceback` **0**; ` ERROR ` **2** — `anticliche_worker` fetch (посторонний конвейер, не дельта) |
| Served asset | `/web/app.js` sha256 `e6fdef1f2210a28fef3dab636e1a866558044cef` = файл в checkout |
| Планировщик | 20 job'ов; `_tick_experience_review`, `_tick_communities` зарегистрированы; `VisionMediaWorker._tick` тикает |
| Чекап | `Checkup log source: systemd invocation=aa277a539c6b482da432dd2ef7b20e68 unit=admin_bot.service pid=3233804` |

## 5. Миграция v44 → v45

| Метрика | PRE (22:08:53, v44) | POST (22:11, v45) |
|---|---|---|
| `user_version` | 44 | **45** |
| `schema_migrations` | 33 | **34** (`voice_transcript_v45`) |
| `quick_check` | — | **ok** |
| `smart_messages` | 2 074 529 | 2 074 529 |
| `nodes` | 33 501 | 33 501 |
| `edges` | 65 188 | 65 188 |
| `graph_facts` | 23 354 | 23 354 |
| `transcript_*` колонки | нет | `transcript_status TEXT NOT NULL DEFAULT ''`, `transcript_revision INTEGER NOT NULL DEFAULT 0`, `transcript_updated_at INTEGER NULL`, `transcript_reason TEXT NOT NULL DEFAULT ''` |

Backfill отсутствует: `media_type='voice'` — 843 строки, из них с `transcript_status<>''` — **0**.
Журнал: `migration v45: smart_messages transcript columns`, применена за 0.0 c, вся цепочка 18.4 c
(из них 18.4 c — backup-guard).

## 6. Чекап: локальный источник, без обращения к удалённому провайдеру

- Startup-строка (выше) — `systemd`, unit и invocation взяты из собственного cgroup процесса.
- В коде чекапа нет HTTP-клиента: `system_logs_fetcher.py` не содержит `httpx/requests/urllib`
  (только докстрока, что клиента нет), `CHECKUP_BETTERSTACK*` отсутствует в `config/`, `services/`, `bot.py`.
- В журнале единственные упоминания Better Stack — глобальный ingest логов
  (`[betterstack] attached | host=…`) и `shutdown flush`; к чекапу они не относятся.
- `.env` всё ещё содержит 4 мёртвых ключа `CHECKUP_BETTERSTACK_SQL_*` — код их больше не читает
  (incidental: кандидат на удаление, включая секрет).

## 7. Effective-state флагов

| Ключ | Значение |
|---|---|
| `flags.memory_search_enabled` | **True** (factory ON, env `MCA_MEMORY_SEARCH_ENABLED` не задан) |
| `flags.memory_communities_enabled` | **True** (env `MCA_MEMORY_COMMUNITIES_ENABLED` не задан) |
| `memory.experience_learning_enabled` | **True** (финал MAC-EXP-06) |

Резолверы на живом кэше: `search=True`, `communities=True` для `None` и трёх чатов.

MAC-EXP-06 — отдельное доказательство: `plans/features/mod-acl-ux-01/evidence/mac-exp-06-live-2.58.170.md`.

## 8. Откат

- **Код:** `git checkout release/2.58.169` (`b2fed707`) + `systemctl restart admin_bot`.
  Runner старого кода видит `current=45`, `pending=[]` → no-op; прод-код не делает
  `SELECT * FROM smart_messages`, аддитивные колонки игнорируются. v45-схема совместима.
- **Данные:** `backups/` дневная копия `local_database_20261108.db` (00:00),
  `/tmp/predeploy-258169.db` (v44, 19:28Z, 1 745 891 328 B), `/tmp/predeploy-258170.db` (v45),
  `pre_migration_20261108_220853.db` (v44, read-back ok).
- Диск: 30G/99G (33 %).

## 9. Что осталось внешним

- **VOICE L-01** — нужен реальный голосовой месседж владельца в одном из 2 чатов.
  Условие и проверка после: новая строка `smart_messages` с `media_type='voice'`,
  `transcript_status='ready'`, `transcript_revision>=1`, непустой `text` = фактическая расшифровка,
  и Writer получает её как источник. Сам тест в прод-чаты не отправлялся.
- Первый автоматический тик после финального ON — 22:54:13Z: `[mca16] experience review tick | status=completed`,
  `task_jobs kind='experience.review'` 36 → **37** (`7b455b74199d40db95c13ce210413cfa`, completed).
