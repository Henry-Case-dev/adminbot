# Deploy 2.58.165 — MEMORY-06: единый retrieval ответного пути

Итог: **выложено и проверено на проде** (192.255.209.205, `/var/www/admin_bot`).
Релиз закрывает одобренную границу MEM-06.1…06.10. Строка **`MEM-06-RUNTIME`
остаётся `NOT_VERIFIED`** (живое качество/полнота выдачи), родительский эпик
`memory-cognitive-02` **не DONE** — см. §7–§8.

## 1. Источник деплоя

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.165` = `74ea64cbf14d2b75706520b397f685aa1718627b` |
| Ветка релиза | `integ/unify-release` → push в `release/2.58.165` |
| Предыдущий прод | 2.58.164 @ `8aada85e` (healthz 2.58.164 до деплоя) |
| MUTABLE_WORKTREE_REQUIRED | **no** — деплой по неизменяемому SHA; серверное дерево после checkout чистое (`dirty_after=0`, единственный untracked — `.cache/`) |
| Repo write scope релиза | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 28 пин-файлов (24 py + 4 js) |

Дельта `8aada85e..74ea64cb` (8 коммитов, `git log --oneline`):

| Коммит | Тип | Покрытие ревью |
|---|---|---|
| `72cf7cf4` | продукт: MEMORY-06 первая реализация (MEM-06.1…06.10) | база стека; ре-ревью закончилось Needs Fixes |
| `40ae401a` | продукт: все чтения памяти через `retrieve`, структурная изоляция архива, bounded-batch | два раунда Needs Fixes → исправлено в `90e67277` |
| `90e67277` | продукт: субъект-канал (профиль по субъекту), паритет direct-RAG | **Reviewer Approved**; evidence `evidence/memory-06-unified-retrieval-90e67277.md`, sha256 `fc31ce83…69e141` (сверен) |
| `14219da9` | только тесты: пере-пины 4 контрактов под 2.58.164 | одобрено |
| `fa3fae9b` | только тесты: reason-код census 320 → 325 | одобрено; фактические `len(REASON_CODES) = 325` |
| `3ce01d21`, `2d3b66b2`, `d9005182` | docs/plans (запись деплоя 2.58.164, карты, привязка MEM-06) | документация |

Проверено, что в дельте **нет продукта вне MEMORY-06**: `services/` меняют
только `database.py` (+bounded read-only `get_nodes_by_ids` и 4 колонки в
`get_facts_with_edges`), `mca_retrieval_context.py`, `direct_chat_service.py`,
`tool_router.py`, `summary_memory.py`, `mca_events.py` (+5 reason-кодов).
**DDL/миграций нет**: в дельте ни `CREATE TABLE`, ни `ALTER TABLE`, ни
`user_version`/`_SCHEMA_VERSION`; `mca_entity_canonical` (v43) только читается.
Веток/флагов: новых env-гейтов и kill-switch в дельте **нет**.

## 2. Преддеплойная проверка (кандидат `74ea64cb`)

Интерпретатор `C:\Code\Python\adminbot\.venv\Scripts\python.exe`, cwd — релизное дерево, `-p no:cacheprovider`.

| Проверка | Команда (сокращённо) | Результат |
|---|---|---|
| Изменённая поверхность | `pytest tests/test_memory_unified_retrieval_06.py test_mca07_retrieval_context_round1027.py test_memory_lookup_round1026.py test_tool_router.py test_direct_chat.py test_speech_p0_a2_memory.py test_history_isolation.py` | **358 passed, 1 failed** (предсуществующий, §3) |
| Срез память/графы/MCA | `pytest tests -k "memory or graphrag or mca07 or mca22 or dossier or retrieval"` | **1581 passed, 3 failed, 1 error** — ровно как в записи PM на `90e67277` |
| Срез history/direct/tools | `pytest tests -k "history or direct_chat or tool_router or memory_lookup"` | **974 passed, 10 failed, 1 skipped** — ровно как в записи PM |
| Census (ранее красные) | `pytest test_mca10b…1041 test_mca17c…1047 test_mca19…1043 test_mca20…1045 test_mca20_rework1_f1_f2` | **зелёные** (после `fa3fae9b`); на кандидате повторно 0 падений по пинам |
| Версионные пины после bump | 24 py-файла | **860 passed, 0 failed** |
| JS-пины версии | `node tests/js/round1025_hotfix{7,8,9,10}*.js` | 4/4 OK |
| Ядро MEM-06 после bump | `pytest test_memory_unified_retrieval_06 + census + mca07 + memory_lookup` | **208 passed, 1 failed** (тот же предсуществующий) |

## 3. Предсуществующие красные (не из этой дельты)

`test_mca20_rework1_f1_f2.py::TestValidatorStage::test_evidence_injection_stays_data_not_instructions`
падает **идентично** на базе деплоя: отдельный прогон в чистом worktree на
`8aada85e` даёт то же `AssertionError: '&lt;/evidence&gt;' in ...` (1 failed).
Reviewer уже классифицировал его как несвязанный с кандидатом. Остальные
красные (3 + 10 из §2) воспроизводятся ровно в том же составе, который зафиксирован
в записи PM/Reviewer для `40ae401a` и `90e67277`, и перечислены в
`plans/backlog.md` (non-blocking test-maintenance).

## 4. Деплой

`git fetch --prune origin` → проверка объекта `74ea64cb^{commit}` →
снимок БД `sqlite3 backup` API → `/tmp/predeploy-258165.db` (1 738 051 584 байт) →
`git checkout -B release/2.58.165 74ea64cb` → `systemctl restart admin_bot`.
Миграций в дельте нет: DDL = 0, `user_version` до и после — **43**.

## 5. Пост-деплойная проверка

| Пункт | Факт |
|---|---|
| Версия | `healthz` локально **и публично**: `{"status":"ok","version":"2.58.165"}`, HTTP 200 |
| HTTP-поверхности | `/web/` 200, `/api/health` 200, `/healthz` 200 |
| Сервис | `active/running`, `NRestarts=0`, `MainPID 2993197` |
| Журнал (окно 3 мин с рестарта) | 285 строк, `Traceback` — 0, `ERROR` — 0, `WARNING` — 1 предсуществующий (`embedding generation not serviceable / smart_archive / superseded / FTS-only`) |
| Схема | `user_version` 43 до и после, `schema_migrations` 32 → 32, `quick_check ok` |
| Память/воркеры | `MemoryMaintenance started`, 6 job'ов (`wal/merge/review/embed_reprobe/intent_hb/initiative`), `sqlite-vec loaded (dim=3072, int8=True)`, `embedding index serviceable | graph_facts_vec | ADMITTED_COMPATIBLE` |
| Served asset identity | `web/app.js` — **2 062 901 байт, sha256 `495d4882…c3050c6`**, БАЙТ-В-БАЙТ равен файлу в чекауте и в дереве кандидата (`cmp identical`) |
| Подстановка версии | только HTML: `/web/` — 0 плейсхолдеров `__APP_VERSION__`, маркеров `2.58.165` — 17, `2.58.164`/`2.58.163` — 0 |

## 6. Пост-деплойная проверка качества (только чтение; прод-данные не менялись)

A. **Embedding/KNN живой, реальные векторы**

| Проверка | Факт |
|---|---|
| sqlite-vec | `vec_version() = v0.1.9`, загружается в процесс (журнал: `sqlite-vec loaded (dim=3072, int8=True)`) |
| Непустой индекс | `graph_facts_vec` — **23 393** строки, `graph_facts_vec_rowids` — 23 393, `graph_facts` — 23 280 |
| Реальный KNN | `MATCH` + `k=5` на 3072-мерном векторе вернул 5 строк с дистанциями (ближайшая 0.9385) — путь vec0 исполняется, не FTS-фолбэк |
| Статусы фактов | `confirmed` 22 169, `unconfirmed` 610, `tentative` 333, `chat_meme` 113, `dossier_portrait` 55, `archived_fact` **0** |

B. **Архив (`archived_fact`) не протекает в обычную выдачу** — проверено не вакуумно:
на копии БД (`/tmp`, прод не менялся) добавлены две синтетические строки одного
субъекта: `confirmed` (контроль) и `archived_fact` (проверка). Чтение субъекта
вернуло **13** строк из 13 (контроль присутствует), архивную — нет;
`retrieve(..., channels=("subject",))` — `status=ok`, контроль есть, архивной строки нет.
Причина структурная: чтение субъекта жёстко фильтрует `status='confirmed'`;
`include_archived` поднимает только явный исторический путь `graph_facts`.
В прод-данных архивных строк сейчас **0**, поэтому «живого» протекания наблюдать
было нельзя — изоляция доказана на копии + кодом.

C. **Профиль возвращает факты субъекта, в тексте которых нет имени**
(живой код на живом корпусе, пройдены настоящие uid и `subject_ref_id`):

- Канал `subject` жив: `retrieve(purpose="dossier", channels=("subject",), subject_entity_ids=(<uid>))` → `status=ok`, `channels=('subject',)`.
- Legacy-субъект (нет `subject_ref_id`): вернулось **8 фактов, все 8 без имени в тексте** (например «тихий дон оценка не понравился…»); контрольный лексический запрос по тому же имени вернул **20 фактов, 0 без имени** — именно тот разрыв, который закрывает MEM-06.
- Субъект со `subject_ref_id`/uid (реальная пара uid `138811255` ↔ ref `15612`, 12 подтверждённых фактов): профиль вернул 5 кандидатов, включая синтетический контрольный; архивный не вернулся.
- Перекрёстной утечки не наблюдалось: у каждого чтения `channels=('subject',)` и `subject_entity_id` = объявленный субъект.

**Не проверено (честно):** фактическое качество ранжирования KNN/MMR на реальных
эмбеддингах и то, насколько состав `<RAG_Memory>`/профилей совпадает с прежней
выдачей на живых данных. Это можно доказать только реальной перепиской (живой
диалог с публикацией ответа) — строка `MEM-06-RUNTIME` остаётся `NOT_VERIFIED`.

## 7. Наблюдения после выкладки (не блокируют релиз, адресат — Builder/Reviewer)

1. **Полнота профиля при `subject_ref_id`.** На субъекте с 12 подтверждёнными
   фактами профильный `retrieve` вернул 5 кандидатов: ID-политика ADR-1020-1
   (`resolve_item_id` → `tg:<tg_message_id>`) схлопывает несколько фактов одного
   сообщения в один кандидат. Механизм **предсуществующий** и не введён MEMORY-06,
   но профиль теперь идёт через него, поэтому фактов на выходе может быть меньше,
   чем строк в БД. Нужно решение Builder/Reviewer: это принятая группировка по
   источнику или потеря на строку `MEM-06-RUNTIME` («возвращает все известные
   подтверждённые факты»). DevOps это не правит.
2. Схема данных по субъектам смешанная: у части людей `graph_facts.subject_ref_id`
   заполнен (`mca_source_refs.source_ref_id`), у части — `NULL` (legacy по
   `target_user`). Оба пути работают, но фактическое покрытие разное
   (18 из 23 субъектов имеют факты без имени в тексте).
3. Архив пуст (0 строк) — первое реальное вытеснение по квоте будет первым
   живым наблюдением изоляции; структурной проверки достаточно для релиза,
   но повторная сверка при первом архивировании полезна.

## 8. Gate и границы релиза

`requirements_gate.py check --stage release --candidate 74ea64cb --deployed-commit 74ea64cb`
по `plans/features/memory-cognitive-02/requirements-map.json`:
`stage=release inventory=153 manual=146 scoped=146 errors=148`, exit 1.

Разбор: ни одна строка `MEM-06.*` и ни `MEM-06-RUNTIME` **не падают** (гейт
принимает evidence, привязанный к предку задеплоенного коммита, и допускает
`READY_FOR_LIVE` на release-стадии). Все 148 ошибок — это
(а) `candidate mismatch; map candidate_commit must match --candidate`
(карта на уровне эпика привязана к `2141b020`, перевязка — работа PM) и
(б) незакрытые чужие строки эпика (`INV-*`, `MEM-02..05`, `MEM-07..09` и др.).
Поэтому: **эпик не DONE, MEMORY-06 как контейнер тоже PENDING** — это корректное
состояние, а не дефект выкладки.

## 9. Откат

- Предыдущий прод: `8aada85e` (2.58.164) — объект на сервере есть,
  `git rev-parse --verify 8aada85e^{commit}` подтверждён; сервис `enabled`.
- Процедура: `git checkout release/2.58.164 && systemctl restart admin_bot`.
- Снимок данных перед деплоем: `/tmp/predeploy-258165.db` (1 738 051 584 б, sqlite backup API).
- Схема не менялась (v43), откат чисто кодовый: `mca_entity_canonical` (v43) старым кодом не читается.
- Независимый бэкап владельца: `WorkspaceData/backups/adminbot-postmigration-2026-10-29/`.

## 10. Гигиена

Прогоны/скрипты проверки: `…\WorkspaceData\runs\c742e4de9e92c489\memory-cognitive-02-52a705214107\probe-aa99caf349\`
(`deploy_258165.sh`, `postdeploy_*.sh`, `gate-release-258165.txt`, логи pytest) —
сохранены намеренно для воспроизведения находок §7; будут сняты после решения
Builder/Reviewer. Прод-данные не изменялись: все мутации §6B выполнялись только
над копией в `/tmp`.
