# Deploy 2.58.166 — MEMORY-06: профиль субъекта больше не теряет факты

Адресат: **production** (192.255.209.205, `/var/www/admin_bot`).
Причина выкладки: hotfix-фикс `1412baa8` (дедуп кандидатов по сущности), независимо
одобрен Reviewer после воспроизведения дефекта на родителе `174e1f16`.

## 1. Привязка кандидата

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.166` = `b2744b58fce42066b26bc76b3ebbae41c7deaf1e` |
| Одобренный кандидат | `1412baa8` (parent `174e1f16`, база `74ea64cb`) |
| Релизный коммит | `b2744b58` = `1412baa8` + бамп версии (31 файл, 33/33) |
| Предыдущий прод | 2.58.165 @ `74ea64cb` |
| MUTABLE_WORKTREE_REQUIRED | **no** — иммutабельный checkout по SHA; сервер после деплоя `dirty_after=0` |
| Repo write scope выкладки | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 24 py-пина + 4 js-пина |

Дельта `74ea64cb..1412baa8` (4 файла, 374 вставки / 9 удалений):

| Файл | Суть |
|---|---|
| `services/mca_retrieval_context.py` (+56/−9) | аддитивное `RetrievalCandidate.dedup_id`, `_candidate_identity()`, дедуп и ключи `fact_rows` по идентичности сущности |
| `tests/test_memory_unified_retrieval_06.py` (+155) | 6 регрессионных тестов (RED на коде до фикса) |
| `plans/backlog.md`, `reports/deploy-2.58.165.md` | docs |

**DDL = 0**, `user_version` не менялся (43), `CREATE/ALTER TABLE` в дельте нет,
PG no-op, новых env-гейтов/kill-switch нет (`os.environ/getenv` в диффе отсутствуют).
Каталог параметров не менялся (Δ = 0), F8 переиздавать не требовалось.

## 2. Преддеплойная валидация (точный кандидат, локально)

Python `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, cwd — worktree кандидата,
`-p no:cacheprovider`.

| Проверка | Результат |
|---|---|
| MEMORY-06 suite (`tests/test_memory_unified_retrieval_06.py`, 49 тестов) | **49 passed** |
| 3-файловый набор MEMORY-06 (06 + mca07 + memory_lookup) | **133 passed** |
| `tests -k "memory or graphrag or mca07 or mca22 or dossier or retrieval"` | **1587 passed, 3 failed, 1 error** |
| `tests -k "history or direct_chat or tool_router or memory_lookup"` | **974 passed, 10 failed, 1 skipped** |
| Census-файлы (mca10b_1041 ×4, mca17c_1047 ×2, mca19_1043 ×7, mca20_1045, mca20_rework1) | **237 passed, 1 failed** |
| Пины версии после бампа (24 py) | **860 passed, 0 failed** |
| JS-пины после бампа (hotfix 7/8/9/10) | **4/4 OK** |
| MEMORY-06 suite после бампа | **133 passed** |

Классификация падений (сравнение с `74ea64cb` в отдельном чистом worktree):

| Набор | На кандидате | На `74ea64cb` | Вывод |
|---|---|---|---|
| memory-подмножество | 3 failed + 1 error | **те же 3 + 1 error** | pre-existing |
| history-подмножество | 10 failed | **те же 10 failed** | pre-existing |
| census | 1 failed (`test_evidence_injection_stays_data_not_instructions`) | воспроизведён ранее на базе; файл вне дельты | pre-existing |

Конкретно: `test_warning_coalesced_not_repeated`, `test_not_serviceable_warning_coalesced`,
`test_style_anchors_not_broken`, youtube-`test_multimodal_success_writes_no_memory`
(двойник без retired `get_smart_cache`), 10 history/direct-тестов + webapp history.
Все они не касаются изменённого файла и воспроизводятся на базе — релиз не блокируют
(числа совпадают с прогоном при выкладке 2.58.165).

## 3. Деплой

`git fetch --prune origin` → объект `b2744b58^{commit}` есть →
снимок данных `sqlite3 backup` API → `/tmp/predeploy-258166.db`
(**1 738 412 032 б**) → `git checkout -B release/2.58.166 b2744b58` →
`systemctl restart admin_bot` (2026-11-08T04:23:48Z).
Ретенция снимков: удалены 10 старых `/tmp/predeploy-2581{45..64}.db`,
сохранены **258165** и **258166** (диск: 27G занято / 67G свободно).

## 4. Постдеплойная проверка

| Проверка | Факт |
|---|---|
| `/healthz` локально | `{"status":"ok","version":"2.58.166"}`, HTTP **200** |
| `/web/`, `/api/health` | 200, 200 |
| Публично `https://admin-bot.duckdns.org/healthz` | 200, `{"status":"ok","version":"2.58.166"}` |
| Публично `/web/` | 200, 1 276 327 б, `2.58.166` — **17** вхождений, `2.58.165` — **0** |
| Сервис | `active`, `enabled`, `NRestarts=0`, `MainPID 3015325` |
| Журнал, окно 3 мин после рестарта | 302 строки, `Traceback` — **0**, `ERROR` — **0**, `WARNING` — **1** (известный `embedding generation not serviceable / smart_archive / superseded`) |
| Журнал, финальное окно 10 мин (после прогрева) | 554 строки, `Traceback` — **0**, `ERROR` — **2** (`services.anticliche_worker`: `step=fetch reason=sources_unavailable` + `step=refresh reason=wikipedia` — та же предсуществующая пара, что зафиксирована при выкладке 2.58.165 и живёт вне памяти), `WARNING` — 3 |
| База сравнения, 24 ч ДО деплоя | 66 772 строки, `Traceback` — 15, `ERROR` — 72 (те же источники: llm_client, mca_events, anticliche, summary) |
| Схема | `user_version` **43** (не менялась), `schema_migrations` 32, `quick_check ok`, `graph_facts` 23 281, `confirmed` 22 170, `archived_fact` 0 |
| sqlite-vec | `vec_version v0.1.9`, `graph_facts_vec` **23 394** строки, `embedding index serviceable | graph_facts_vec | ADMITTED_COMPATIBLE` |
| Memory-воркеры | `MemoryMaintenance started (merge/7d, review/3d, wal/6h, embed_reprobe=600s, intent_hb=300s)`, `sqlite-vec loaded (dim=3072, int8=True)` |
| Served asset | `/web/app.js` 2 062 901 б, sha256 `495d4882…c3050c6`, **`cmp` = identical** с checkout; инъекция версии только в HTML |

## 5. Пост-деплойное функциональное доказательство ЭТОГО фикса (read-only)

Данные прода не менялись: проба исполнялась на копии преддеплойного снимка
(`/tmp/predeploy-258166.db` → `/tmp/probe-258166.db`), запросы только на чтение.

**Найденный реальный субъект:** `mca_source_refs.source_ref_id=15612` ↔ uid `138811255`,
чат `-1002661910336`, **12 подтверждённых** `graph_facts`, **4 разных** `tg_message_id`,
распределение по сообщениям: `1134501 × 6`, `1160394 × 4`, `1130674 × 1`, `1142152 × 1`.
Именно этот субъект фигурировал в находке 12 → 5 при выкладке 2.58.165 (§7 прошлого отчёта).
В БД: 12 строк = 12 различных текстов фактов.

Проба воспроизводит ровно тот путь, которым идёт потребитель: `retrieve()` с полями
из `ToolRouter._memory_lookup_unified` (`purpose="dossier"`, `mode="specific"`,
`top_k=max_items`, `channels=("subject",)`, `subject_entity_ids=(uid,)`,
`preserve_channel_order=True`), затем маппинг `fact_rows[graph_facts.id]` по
`candidate.entity_id` (критерий `_memory_lookup_unified_items`).

| Кэп purpose | БЫЛО (код `74ea64cb` = 2.58.165) | СТАЛО (код `b2744b58` = 2.58.166) |
|---|---|---|
| identity, cap 5 | 2 кандидата / 2 строки → **1 факт в конверте** | 5 / 5 → **5 фактов**, 5 уникальных текстов |
| biography, cap 10 | 3 / 3 → **1 факт** | 10 / 10 → **10 фактов**, 10 уникальных |
| general, cap 8 | 3 / 3 → **1 факт** | 8 / 8 → **8 фактов**, 8 уникальных |
| hard cap 20 | 4 / 4 → **2 факта** | 12 / 12 → **12 фактов** = все подтверждённые факты субъекта |

Дубликатов нет ни в одном случае (`dup_texts=0`, `unique_rows == envelope_facts`).
То есть кэпы purpose (identity 5 / biography 10 / general 8 / потолок 20) сохранены,
а потери текстов больше нет: до фикса 12 хранимых фактов давали 1–2 на выходе.

**Схлопывание настоящего повтора из разных каналов сохранено:** запрос с каналами по
умолчанию (`subject+lexical`, cap 20) → 20 кандидатов, **16** строк `fact_rows`,
**16** фактов в конверте, **16 уникальных текстов, 0 дублей** (было: 12 строк → 10 фактов).

Архивная изоляция и разделение subject/uid структурно не тронуты фиксом (дельта не
касается фильтров статуса и `subject_entity_id`), в прод-данных `archived_fact` = 0.

## 6. Покрытие требований

| Строка карты | Чем закрыта в этой выкладке |
|---|---|
| MEM-06.10 (get_user_context через единый retrieval, «1 факт из 4») | дефект устранён: 49 тестов MEMORY-06 + прод-проба §5 (1→5, 1→10, 1→8, 2→12) |
| MEM-06.1/2/3 (единый контракт, схема запроса, каналы) | код не менял контракт: `retrieve()` единственный вход, `fact_rows` аддитивно переключены на идентичность сущности; 133 теста набора |
| MEM-06.5 (max_items — кап инструмента, без слепых квот) | кэпы 5/10/8/20 подтверждены на проде (§5) |
| MEM-06-RUNTIME (живой корпус) | доказана полнота профиля на реальных прод-данных после деплоя; см. §7 |

## 7. Что НЕ проверено

- **Живой ответ в реальном чате** (полный путь ответа с реальными эмбеддингами,
  KNN/MMR-ранжированием и композицией `<RAG_Memory>`) не наблюдался: проба шла по
  каналам `subject`/`lexical`, канал `vector` требует реального вызова эмбеддингов;
  отправка live-сообщений в чаты владельца без отдельного разрешения не выполнялась.
- Качество ранжирования на живых эмбеддингах и совпадение состава профилей с прежней
  выдачей — по-прежнему требуют живого диалога.
- Владельческие UI/устройство-проверки — вне объёма (owner_optional).

Поэтому **MEM-06-RUNTIME остаётся `READY_FOR_LIVE`, а не `VERIFIED`**: live-corpus
часть (полнота профиля на реальных данных, до/после) теперь доказана и привязана к
`b2744b58`, а «ранжирование в живом ответе» требует реальной переписки. Перевязку
строки карты (evidence + status) делает PM/Orchestrator; карта в релизном worktree
не редактировалась (в ней есть незакоммиченные правки другого владельца).

## 8. Gate

`requirements_gate.py check --repo . --map plans/features/memory-cognitive-02/requirements-map.json
--stage release --candidate b2744b58 --deployed-commit b2744b58`:
`inventory=153 manual=146 scoped=146 errors=148`, exit 1. Ни одна строка `MEM-06.*`
и `MEM-06-RUNTIME` в списке ошибок не значится: 148 замечаний — это (а) привязка
карты уровня эпика к `2141b020` (`candidate mismatch`) и (б) незакрытые чужие строки
(`INV-*`, `MEM-00`, `MEM-02..05` и др.). Эпик остаётся не-DONE — это корректное
состояние, а не дефект выкладки.

## 9. Откат

- Кодовый откат: `git checkout release/2.58.165` (= `74ea64cb`) → `systemctl restart admin_bot`.
  Объект `74ea64cb^{commit}` на сервере подтверждён, сервис `enabled`.
- Снимки данных: `/tmp/predeploy-258166.db` (1 738 412 032 б) и `/tmp/predeploy-258165.db`.
- Схема не менялась (`user_version` 43), откат чисто кодовый; v43-таблица
  `mca_entity_canonical` старым кодом не читается.
- Независимый бэкап владельца: `WorkspaceData/backups/adminbot-postmigration-2026-10-29/`.

## 10. Гигиена

Прогоны и вывод проб: `…\WorkspaceData\runs\c742e4de9e92c489\memory-cognitive-02-52a705214107\probe-ca814f0b85\`
(`recon_258166.sh`, `deploy_258166.sh`, `probe_258166.sh`, `probe2_258166.sh`, `final_258166.sh`,
`deploy-258166.out`, `probe-258166.out`, `probe2-258166.out`, `final-258166.out`, логи pytest, gate-вывод) —
сохранены намеренно для воспроизведения §5; снимутся при закрытии эпика.
На сервере удалены мои одноразовые артефакты проб (`/tmp/probe-258166.db`,
`/tmp/served-app-258166.js`, `/tmp/served-index-258166.html`, `/tmp/old_rc_258165.py`);
сохранены только снимки `predeploy-258165.db` и `predeploy-258166.db`.
Временный worktree для базового сравнения `74ea64cb` снят после прогона
(в реестре housekeeping осталась запись об уже удалённом каталоге — безвредна).
Прод-данные не изменялись: все пробы §5 — на копии снимка.
