# REVIEW-PERSIST-FIX — независимое ревью центрального фикса сохранения (P0 save/init §2)

| Поле | Значение |
|---|---|
| Кандидат | uncommitted-правки поверх HEAD `8c88bbda`; 14 файлов лейна (5 кода + 8 тестов + 1 новый); sha12 (git-blob) всех 14 сверены с `report.md` — **совпали** |
| Входы | `persistence-audit.md` (§3.1–3.5, B4/B5, §8.5–8.6), `evidence/persist-fix/**` (RED/GREEN/SWEEP/атрибуция) |
| Вердикт | **Approved** — все 10 chat-записей реально получают пул, честные ветки и валидация подтверждены; остатки (§8) зафиксированы, live-приёмка — postdeploy |

## 1. pg ×10 — прочитано в коде, все десять (плюс бонус)

1. `_write_document` (chat): `pg=_doc_pg(cache)`, чтение `get_all_chat_params(pg=)` + запись `set_chat_params(pg=)`;
2. `_write_core_meta` (chat) — так же; 3. `_write_expression` (chat) — так же; 4. `post_expression_reset_chat` — RMW-чтение и запись с pg;
5. `save_policy_document` ← `post_style(pg=_doc_pg(cache))`; 6. `reset_chat_policy` ← `post_style_reset_chat(pg=…)`;
7. `write_speech_value` ← `post_block(pg=… при chat-scope)` (+ бонус: `post_block_rollback` тоже с pg); 8. `reset_chat_override` ← `post_block_reset(pg=…)`, причём **RMW-чтение в prompt_factory идёт через `get_root(chat_id, pg=pg)`**;
9. `set_paused` ← `post_learning_humor(pg=)`; 10. `reset_learning` ← `pg=` (+ сбой записи документа больше не глотается).

**Честная ветка «пула нет»:** `chat_params.set_chat_params` без пула поднимает `ChatLorePgUnavailable` → API отдаёт **503 с человеческим текстом** (`WRITE_UNAVAILABLE_DETAIL`/`RESET_UNAVAILABLE_DETAIL`, конфликт — 409 с человеческой причиной; «write_error» в UI больше не диагноз) ✓ — подтверждено тестом `test_no_pool_is_explicit_error_not_fake_success`.

## 2. ConfigCache.set — PG-first

`set`: сперва PG-upsert, затем память; нет пула → `ConfigCacheUnavailableError`, память не меняется; сбой PG-записи → исключение (память не расходится с хранилищем). Мои прогоны: оба новых теста — зелёные; **RED-факт воспроизведён на чистом коде: `assert 9000 == 8000`** (B5 из аудита).

## 3. chat-Core — 3 дефекта закрыты

full/compact текст → 200 + read-after-write из БД + изоляция чатов; `/core/meta` → 200 только при реальном применении (RED был 200/`ok:false`; теперь неприменённая запись → 503); `reset(mode=chat)` → 200 (RED 500), повтор → честный `no_chat_override`.

## 4. Прочие пути

humor craft (chat) → 200 + документ в БД; **examples policy**: побочно закрыт shadow-баг — `/speech/examples/{seed,policy,why}` перекрывались маршрутом `{sample_id}` (422); теперь `{sample_id:int}` (sample id — `INTEGER AUTOINCREMENT`, клиент шлёт `row.id`), числовые `{sample_id}`/`approve`/`archive`/`DELETE` не изменены; литералы достижимы, новый тест шлёт `/api/speech/examples/policy` → 200 + read-after-write `humor.selection`; learning pause/resume/reset → 200 + `humor.feedback` в БД (RED 409 `write_error`), реальный сбой → 503 человеческий; оба «Сбросить в inherited»: style — реальный `ok/200` и 503 при сбое (RED — ложное «переопределения не было»), expression — 200.

## 5. unknown kind / `_as_doc`

`fatal_document_issues` (rule_kind_unknown:*, rule_not_object, soft_not_object, …) → `applied:false reason=document_invalid` + `blocking_issues` → POST /speech/style **409 с человеческим текстом**; документ НЕ записан (валидация не подавлена, ISSUES сохранены). `_as_doc` применён в `_expression_document`/`_core_payload`/`_write_expression`/`_write_core_meta`/`_write_document` (латентный JSON-string C1).

## 6. Тесты (мой прогон)

* Кандидат, 5-файловый набор → **145 passed** (сходится).
* **RED на чистом HEAD** (мой worktree + финальные тесты) → **17 failed / 40 passed**, тот же состав классов дефектов (в лог-е лейна 16f — на один меньше: `test_style_chat_conflict_returns_409_without_data_loss` ужесточён в финальном тесте; на чистой базе падает и он — RED только усилился).
* Sweep 130 файлов (список лейна) → **2985 passed / 1 failed** (`mca12 js_ui_suite`) — сходится.
* Полный pytest (мой, случайный из-за пустого фильтра) → **14236 passed / 9 failed**; атрибуция подтверждена спотом на чистом HEAD: t5150×5 и asap7×2 и mca01×1 падают без правок лейна; mca12 `js_ui_suite` на чистом HEAD **зелёный** → падает из-за чужой uncommitted правки `web/app.js` ✓.
* Новый файл — реальный HTTP (`TestClient` + `speech_router` + TMA-auth) и реальные `chat_params`/`ConfigCache` поверх temp-SQLite шима; виновный вызов (`set_chat_params`) не подменяется (только оси/токен + явная инъекция «пул снят»); фикстура W6 переведена на тот же реальный путь.

## 7. Дисциплина дерева

Маркеры `PERSIST-FIX` присутствуют только в 5 кодовых + 7 тестовых файлах лейна (плюс рабочий state родителя); чужие uncommitted-файлы (nostalgia/INIT/`web/app.js` и пр.) маркеров не несут; мои проверки sha12 не показали посторонних правок в 14 файлах лейна.

## 8. Остатки (подтверждены, не блокеры)

* `set_many` без пула по-прежнему пишет только память (код прочитан; web-путь гейтится `cache.pg_available`, `routes.py:1161`) — вне мандата, кандидат в следующий P0;
* провенанс пишется ДО значения в `_write_chat_speech_value` (порядок `_mark_provenance` → `set_root` подтверждён) — низкая важность;
* live-приёмка на реальной БД — **postdeploy** (сейчас не засчитывать).

## 9. Решения леджеру

* **Закрываемо кодом+артефактами сейчас:** `P0A-PERSIST-AUDIT` (аудит покрывает цепочку §3.1–3.5/B4/B5/§8), `P0A-PERSIST-CAUSE` (первопричина классифицирована; `write_error` не принимается как диагноз), `P0A-PERSIST-CENTRAL` (общий механизм, 3 названных симптома через общий путь, smoke — sweep 2985).
* **Код-половина закрыта, runtime-половина — live:** `P0A-PERSIST-SECTIONS` (все типы настроек — интеграционным файлом), `P0A-PERSIST-TRUTH` (валидация не подавлена, искусственного 200 нет, успех = read-after-write в тестах; «применение в runtime» — live).
* **Live postdeploy (реальная БД):** `P0A-PERSIST-APPLY` (effective/hot без рестарта), `P0A-PERSIST-PAYLOADS` (LLM payloads), `P0A-ACCEPT-PERSIST` (цикл на реальной БД), `P0A-ACCEPT-PERSIST-EDGE` (её приёмка прямо требует интеграционных тестов на **реальном PostgreSQL**, а не на шиме → не закрывать сейчас).
* **Interplay `SOUL-AMD.8.3`:** остаётся RFL; именно этот код-фикс устраняет её blocking-остаток «во всех путях» (chat-scope save) — после деплоя live-цикл может снять остаток; cross-ref amendment-карты на P0A-PERSIST корректен, статус сейчас не трогать.

Микро-нит (не блокер): опечатка в докстринге `config_cache.set` — «отсутствиепула».
