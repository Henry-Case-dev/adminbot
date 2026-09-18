# spec.md — F8 `dossier-rebuild-async-ui-round1022`

> **Раунд 10.22 (UPD3)** · Приоритет **P0** · Шаг 2b @Architect · Тип: backend (job-store/API) + frontend `web/**` + data-safety/rollback
> **ADR:** **`ADR-1022-8.md`** (**Accepted**). **Задачи:** `tasks.md` (T-2077…T-2089).
> **ТЗ:** `plans/current_task.md`, **UPD3 §2** «Новая фича UI (Кнопка пересборки Досье)» (строки **252–256**) + **UPD3 §1** (247–249).
> **R17/R18:** `plans/current_task.md` untracked; SSH-креды не цитировать и не коммитить.
> **Baseline:** HEAD `acd9311`; pytest **6779/0**; каталог **439/409/414/92/90/20**; SQLite **v12**; APP_VERSION 2.57.0; прод `a923310`.
> **Зависит от:** F1 (`urgent-rebuild-dossiers-target-chat-round1022`) — тот же движок + confirmed-cleanup; F2 — ступень `web/**`.
> **Карта гейта:** `plans/features/round1022-human-gate-map.md`.

---

## 0. Контекст и факты аудита кода (Step 2)

| Факт | Точка в коде |
|---|---|
| Досье-модалка UI | `web/index.html:2667-2739`; логика `web/app.js:2739-2795` (`openDossier`/`loadDossier`/`closeDossier`/`saveDossier`); стейт `web/app.js:881-893` |
| API досье | `web/api/chat_lore.py:906-959` (`GET`/`PUT dossier`), payload `_dossier_payload` `:838-902`, `_dossier_name` `:820-835`, RBAC `_require_chat` `:917`/`:938` |
| Движок пересборки (F1/10.21) | `services/memory_rebuild.py:400` `rebuild_dossiers(...)`; `:130` `create_safety_backup`; `:175-229` `_archive_generated_rows`/`_archive_and_delete`; `:95-120` `delete_generated_facts`; allowlist `:46-82` |
| Pipeline | `services/lore_worker.py:691-717` `rebuild_dossier_for_chat(chat_id, *, window_hours, limit)` (окно `smart_messages` — **только чтение**); запись производных `:749-825` (`chat_meme`/`dossier_portrait`) |
| Что показывает «Досье» | `services/database.py:4410-4437` `get_persona_card` (`target_user=name AND status='confirmed'`) + `dossier_portrait` + `edges`-links |
| Паттерн прогресса (мост/троттлинг/fail-open) | `services/progress_reporter.py:92-264` |
| Паттерн фоновой задачи + статус-эндпоинты | `web/api/memory_agi.py:323-337` (`_launch_dream`, `asyncio.create_task`, 202/409), `:455` (`deep_sleep_status`), `:530` (`cognition_status`) |
| fsync-хелпер | `services/memory_maintenance.py::_flush_fsync_and_dir` |
| Схема/инварианты | `graph_facts` (`services/database.py:318`), `kind ∈ {fact,belief}`, `status ∈ {confirmed,chat_meme,dossier_portrait,...}` |

### 0.1. Расхождения/уточнения ТЗ

- ТЗ говорит «в мини-аппе в меню Досье (карточка юзера)». Кнопка живёт в **модалке Досье**
  (`web/index.html:2667-2739`), т.к. «меню Досье» — это список участников → карточка.
- «Пересборка досье» из UI-карточки **user-scoped**: снапшот/откат затронут только производные
  целевого юзера (не весь чат). Confirmed-cleanup поддерживает `target_user` (F1 §2.5).
- Бэкап «на старте» — **точечный снапшот производных юзера** (малый, быстрый), а не полный
  дамп БД (~724 МБ на каждый UI-клик неприемлем). Инварианты сырой истории/overrides делают
  точечный снапшот достаточным.

### 0.2. Ключевой инвариант data-safety

- **`imported-history-immutable`:** `smart_messages`/FTS/vec/`import_checkpoints` не мутируются
  (окно — только чтение; `RAW_HISTORY_TABLES`/`assert_derived_table` сохраняются).
- **`manual-overrides-immutable`:** `persona_dossier_overrides` не трогается ни пересборкой, ни rollback.
- **beliefs/paradigms (`kind='belief'`) и `nodes`/`edges`** — не мутируются.

---

## 1. Цель

Дать владельцу в мини-аппе (модалка **Досье**, карточка юзера) кнопку **«Пересобрать досье»**
с выбором периода **30 / 90 / 180 дней / Всё время**: запуск **фоновой задачи**, **понятный
прогресс-бар** («обработано X/Y чанков»), **persistence** при закрытии/открытии мини-аппа,
**«Отмена» с откатом (rollback)** производных юзера из снапшота, сделанного на старте.

## 2. Архитектура

### 2.1. Поток

```
[UI: модалка Досье, карточка юзера]
   Klick «Пересобрать досье» + period (30|90|180|all, default 180)
        │  POST .../dossier/{user_id}/rebuild {period}
        ▼
[API chat_lore.py] RBAC(_require_chat) → валидация period → per-(chat,user) lock
        │  202 {job_id, status, total, ...}
        ▼
[Job runner: asyncio.create_task]
   1. snapshot(user, chat)      → rollback_<job_id>.jsonl (fsync)
   2. cleanup(user, chat)       → archive(JSONL) → guarded DELETE confirmed-фактов (F1 §2.5)
   3. extract(chunks)           → Layer A по чанкам окна; progress_cb(processed,total,'extract'); cancel_cb между чанками
   4. synthesize                → Layer B (агрегированные кандидаты user-scoped)
   5. write + finalize          → dossier_portrait/chat_meme для юзера; counts «до/после»
        │  GET .../rebuild/{job_id} (poll / reopen)   ← job-store (персистентный)
        ▼
[UI: прогресс-бар «X/Y чанков»; кнопка «Отмена»; после done — reload досье]
   POST .../rebuild/{job_id}/cancel → cooperative stop → ROLLBACK из снапшота
```

### 2.2. Job-store (персистентный, без DDL)

- **Новый модуль** `services/dossier_rebuild_jobs.py` (F8-эксклюзив).
- Хранилище: файл `dossier_rebuild_jobs.json` в каталоге задач
  (`<MEMORY_BACKUP_DIR>/dossier_jobs/`, каталог создаётся; вне каталога `param_catalog`).
- **Атомарная запись:** `*.tmp` → `os.replace` + `_flush_fsync_and_dir` (fsync файла/каталога).
- **Retention:** хранить последние **50** завершённых job'ов или **7 дней** (что меньше);
  rollback-снапшоты удаляются вместе с job по retention. Активные job'ы не вытесняются.
- **Один писатель:** `asyncio.Lock` модуля + in-process registry `job_id → asyncio.Task`.
- **Схема записи job (R17-safe — без текстов фактов):**

```jsonc
{
  "job_id": "32hex",
  "chat_id": -1002661910336,
  "user_id": 123,
  "target_name": "Никита",          // резолв канона (для удаления/записи)
  "actor_id": 123456,                // кто запустил (аудит)
  "period": "180",                  // "30"|"90"|"180"|"all"
  "window_hours": 4320,             // 720/2160/4320/0
  "chunk_size": 40,
  "status": "queued|running|cancelling|done|failed|cancelled|interrupted",
  "stage": "snapshot|cleanup|extract|synthesize|write|finalize|rollback",
  "total": 180, "processed": 0,     // «X/Y чанков»
  "cleaned": 0, "rebuilt": 0,
  "snapshot_ref": "rollback_<job_id>.jsonl",   // basename (не полный путь)
  "rollback": {"done": false, "restored_facts": 0, "reason": ""},
  "cancel_requested": false,
  "error_code": null,
  "created_at": 0, "updated_at": 0, "started_at": 0, "finished_at": null
}
```

- **Статусы/переходы:** `queued → running → (done | failed)`; `running → cancelling → cancelled`
  (после успешного rollback); незавершённые при рестарте процесса → `interrupted`
  (`reason=process_restart`); `interrupted → cancel → cancelled` (rollback доступен).

### 2.3. API (в `web/api/chat_lore.py`; RBAC как у досье)

| Метод | Путь | Успех | Ошибки |
|---|---|---|---|
| `POST` | `/api/chat_lore/{chat_id}/dossier/{user_id}/rebuild` body `{period}` | **202** `{job_id, status, period, window_hours, total, processed}` | 403 RBAC; 422 bad period; **409** `{code:"already_running", job_id}`; 503 нет БД/job-store; 404 если `DOSSIER_REBUILD_UI_ENABLED=false` |
| `GET` | `.../dossier/{user_id}/rebuild/{job_id}` | **200** job-view (идемпотентно) | 404 чужой/неизвестный job; 403 |
| `GET` | `.../dossier/{user_id}/rebuild/latest` | **200** последний job юзера **или** `204` | 403; 503 (fail-open → 204) |
| `POST` | `.../rebuild/{job_id}/cancel` | **202** `{status:"cancelling"}`; для terminal — **200** `{status, rollback}` | 404; 403; 409 (уже `cancelling`) |

- `name` резолвится серверно через `_dossier_name(chat_id, user_id, name)` (R16).
- Job-view (R17): числа/коды/`snapshot_ref`-basename; **без** текстов фактов, полных путей и секретов.
- Все чтения — **fail-open**: ошибка job-store → нейтральный ответ, UI не падает.

### 2.4. Прогресс «X/Y чанков»

- `total = ceil(window_message_count / chunk_size)`, где `window_message_count` — **дешёвый**
  `COUNT` по `smart_messages` в окне `[now − window_hours, now]` (индекс чата; без тяжёлого скана).
- `chunk_size` — env-константа `settings.DOSSIER_REBUILD_CHUNK_SIZE` (default **40**),
  **вне `param_catalog`** (Δ каталога = 0).
- `processed` инкрементируется после каждого чанка Layer A через `progress_cb`; запись в
  job-store **троттлится** (≥1 c либо смена `stage`; same-state guard — паттерн
  `services/progress_reporter.py:171-183`); **fail-open** (прогресс не роняет пересборку).
- «Всё время» (`all`, `window_hours=0`): `total` всё равно bounded через `max_msgs`; UI показывает
  предупреждение о стоимости (Δ каталога нет — чисто UI).

### 2.5. Движок: аддитивный user-scoped чанковый контракт

F8 добавляет в `services/lore_worker.py` **additive** метод (существующий
`rebuild_dossier_for_chat` не меняет поведение — CLI F1 нетронут):

```
async def rebuild_dossier_for_user(
    self, chat_id: int, *, target_user: str, window_hours: int = 4320,
    limit: int | None = None, chunk_size: int | None = 40,
    progress_cb=None, cancel_cb=None) -> int
```

- `progress_cb(processed, total, stage)` — async/sync; вызывается после каждого чанка и на
  переходах стадий; исключения проглатываются (fail-open).
- `cancel_cb() -> bool` — проверяется **между чанками и стадиями**; `True` → кооперативный
  abort (поднять `asyncio.CancelledError` наружу в job runner).
- `target_user` — запись `dossier_portrait`/`chat_meme` только для этого target
  (`services/lore_worker.py:749-825`); остальные участники не дублируются.
- `chunk_size=None` → текущее одноразовое поведение (совместимость).
- `window_hours=0` → без ограничения по времени (в пределах `limit`/`max_msgs`).

### 2.6. Стартовый снапшот + rollback

**Снапшот (на старте job, до любого DELETE):**
- Выборка производных только целевого юзера: `graph_facts WHERE chat_id=? AND target_user=?
  AND kind='fact' AND status IN ('confirmed','chat_meme','dossier_portrait')`; сохранить
  `{table, id, columns...}` строки (вкл. `id`) + FTS `fact` + флаг наличия vec.
- Файл `rollback_<job_id>.jsonl` (fsync) в каталоге задач. Без успешного снапшота job
  **не стартует** (fail-closed, status `failed`, `error_code=snapshot_failed`).

**Отмена (rollback):**
1. Выставить `cancel_requested=true`; runner ловит abort между чанками.
2. Текущие производные юзера архивируются в `cancelled_<job_id>.jsonl` (аудит) и удаляются
   через guard (`delete_generated_facts`).
3. Из снапшота **восстанавливаются** строки `graph_facts` (с исходными `id`, `INSERT OR REPLACE`)
   + FTS; vec — **best-effort** (при наличии эмбеддера; иначе `vec_restored=0`, reason в отчёте).
4. `rollback.done=true`, `restored_facts=N`; job → `cancelled`. **Идемпотентно** (повторный
   cancel на terminal job не дублирует строки; `INSERT OR REPLACE` по `id`).
5. При ошибке rollback → job `failed`, `rollback.done=false`, `error_code=rollback_failed`,
   снапшот сохранён; UI показывает «откат не удался, повторить» (повторный cancel).

**Не трогается rollback'ом:** `persona_dossier_overrides`, `smart_messages`+FTS/vec,
`kind='belief'`, `nodes`/`edges`, чужие производные.

### 2.7. Конкурентность и рестарт

- **Одна задача на `(chat_id, user_id)`:** повторный POST при активной → **409** + `job_id`.
- **Cross-process lock (vs CLI F1):** файл-lock `<jobs_dir>/rebuild_<chat_id>.lock`
  (`O_CREAT|O_EXCL`, внутри `pid`+`ts`); F1 CLI (T-2090) использует тот же lock. Stale-детект —
  по TTL (default 6 ч) и, best-effort, по `pid`; stale → перехват с WARNING.
- **Рестарт бота:** job-store **переживает** рестарт (файл), но **живое исполнение — нет**:
  при старте non-terminal job'ы → `interrupted`. Авто-возобновление LLM-пересборки **не
  делается** (небезопасно/неидемпотентно); UI показывает `interrupted` и кнопку отката.
  Обоснование — ADR-1022-8 §Decision.

### 2.8. Frontend

1. **Кнопка + селектор периода** (30/90/180/Всё время; default **180**) в модалке Досье
   (`web/index.html:2667-2739`, стейт/логика `web/app.js:881-893`, `:2739-2795`).
2. **Прогресс-бар:** «обработано `{processed}/{total}` чанков» + метка `stage`; polling
   `GET .../rebuild/{job_id}` каждые ~2 c только пока job активен.
3. **Persistence:** при открытии модалки — `GET .../rebuild/latest`; активный job → сразу
   рисуем прогресс; `visibilitychange`/reopen → повторный GET. `localStorage` хранит лишь
   подсказку `{chat_id,user_id,job_id}` (источник истины — сервер). Любая ошибка GET → нейтральное
   состояние, **ничего не падает**.
4. **Отмена:** кнопка + подтверждение → `POST cancel` → polling до `cancelled`/`failed` →
   reload досье. Защита от гонок (повторные клики/закрытие модалки/reopen).
5. После `done` — reload досье (`GET dossier`), чтобы показать свежие `portrait`/`patterns`.

## 3. Контракты

- `period → window_hours`: `30→720`, `90→2160`, `180→4320`, `all→0`.
- Job-view содержит `total`/`processed`/`percent`/`status`/`stage`/`rollback` — **только числа/коды**.
- Инварианты (тесты): `smart_messages`/FTS/vec и `persona_dossier_overrides` неизменны
  после start/done/cancel; beliefs/nodes/edges не тронуты.
- F1-примитив `cleanup_confirmed_dossier_facts` вызывается job-раннером (reuse), не дублируется.

## 4. Feature Flags / Progressive Delivery

- `DOSSIER_REBUILD_UI_ENABLED` — env-only `ClassVar`, **default ON**, Δ каталога = **0**.
- OFF → rebuild-эндпоинты `404`, кнопка скрыта; остальной функционал досье не затронут.
- Поэтапная раскатка % **не требуется** (прецедент 10.21/10.22).

## 5. Kill-switch / fallback / откат

- **Kill-switch:** флаг OFF (без редеплоя).
- **Fallback:** ошибка job-store/снапшота → job `failed` без мутаций; UI fail-open.
- **Откат данных:** `rollback_<job_id>.jsonl` (точечный) + `cancelled_<job_id>.jsonl` (аудит) +
  JSONL-архив confirmed-cleanup; второй рубеж — авто-бэкап F1.
- **Откат кода:** флаг OFF / `git revert`.

## 6. Стоимость / латентность

- Стоимость LLM: Layer A × число чанков + Layer B (1). Линейна по окну/`max_msgs`;
  chunking выравнивает latency и даёт прогресс. `all` — дорого → предупреждение.
- Job идёт в фоне, HTTP не блокируется. Логи — только counts/коды (R17).

## 7. Риски

| ID | Sev | Риск | Митигация |
|---|---|---|---|
| R1 | Critical | rollback затирает свежие/ручные данные | Только производные юзера из стартового снапшота; `overrides`/`smart_messages`/beliefs/nodes/edges неприкосновенны; сверка counts |
| R2 | High | job теряется при restart/краше | Персистентный job-store; `interrupted`; ручной rollback из снапшота (не авто-resume) |
| R3 | High | Тяжёлый расчёт прогресса на БД ~2M строк | `total` из дешёвого `COUNT` окна; chunking; троттлинг; fail-open |
| R4 | High | Некооперативная отмена → частичный результат | `cancel_cb` между чанками/стадиями + **обязательный rollback**; статус не `done` |
| R5 | Medium | Гонки/reopen во фронте | Единый источник истины — серверный job-store; идемпотентный GET |
| R6 | Medium | Конкурент с CLI-прогоном F1 | Lock per chat (файл) + уникальность per `(chat,user)`; 409 |
| R7 | Medium | «Всё время» + двойная стоимость LLM | Default 180; предупреждение для `all`; bounded `max_msgs` |
| R8 | R17/R18 | Секреты/тексты в логах/отчётах | Только counts/коды/`snapshot_ref`-basename |

## 8. Открытые вопросы

- Нет (Д-4/Д-5/Д-8 закрыты UPD3). Follow-up: авто-resume после рестарта / orphan-edge GC —
  вне раунда.

## 9. Задачи

См. `tasks.md` (T-2077…T-2089). Настоящий spec фиксирует: job-store (файл, без DDL), 4 эндпоинта,
`rebuild_dossier_for_user` (аддитивный чанковый контракт), прогресс «X/Y», снапшот+rollback,
lock per chat, `interrupted`-семантику рестарта, флаг `DOSSIER_REBUILD_UI_ENABLED`.
