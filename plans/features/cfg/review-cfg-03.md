# REVIEW-CFG-03 — независимое ревью аудита параметров MiniApp (579)

| Поле | Значение |
|---|---|
| Кандидат | uncommitted поверх `61ecd034`: `services/param_catalog.py` `4886ff03…`, new `tests/test_cfg03_param_audit.py` `91c56e1c…`, new `tools/cfg03_param_inventory.py` `a6c08290…`, new `tools/ui_cfg03_descriptions_e2e.py` `78bdb56e…`, `tests/test_round1025_f8_registry.py` `1d57b0db…`, TSV `2259fdab…`, meta `6c2297fb…` — все sha256_12 совпали |
| Вердикт | **Approved** — инвентарь, честные описания, тесты и бласт подтверждены; F2 (2 type-mismatch) — backlog с готовым рецептом; live-строки → RFL |

## 1. Инвентарь (R1) — счётные факты и мой спот
`inventory.json`: **579** записей; `consumer_status`: **runtime 552 / dynamic 13 / none 14**; `ui_visibility`: visible 552 / api-only 25 / hidden 2; **ui_missing=0**, orphan-группы 0, дубли settings-полей {}; `inconsistencies=3` (1 исключение category-группы + 2 deferred type-mismatch); `with_test_refs=456`.
* **Спот 14 записей** (каждая 41-я): у 13 runtime-строк потребитель реально найден в runtime-скоупе (`bot.py/manage.py/config/handlers/services/web/filters/scripts/SmartModule`), у строки `none` — только определение/комментарий. Проверил адресно: `limits.chat_budget_response_ratio`, `limits.chat_lock_max_entries` — только `config/settings.py` (дефиниция) + каталог; `limits.memory_backup_keep` — только дефиниция + **комментарий** в `services/memory_backup.py:12` (комментарии в аудите вырезаются) → «нет потребителя» подтверждено ✓.
* **14 «без потребителя»**: 7 видимых «мёртвых ручек» (с tab) + 7 api-only env-only (`cobalt_http_proxy`, `media_base`, `postgres_db/password/user`, `telegram_api_id/hash`); из них **6 в docker-compose** (проверил grep), `media_base` — вне docker ✓ (совпадает с README).
* **13 динамических** — шаблон `f"limits.{name}"` + слаг в `services/user_relations.py:61` (единый резолвер RELATIONS) ✓; live-подтверждение — существующие зелёные тесты `test_relations_service` (в бласте).
* **UI_missing=0**: `content_media` (tab=None) рендерится synthetic-группой — `web/app.js:_syntheticGroup('content','content_media')` (3157/3392) ✓; e2e-скрин `ui/03-module-video-content-media.png` (окно «Выжимка видео» с лимитами) осмотрел — группа видна ✓.

## 2. Честные описания и каталог
Дифф `param_catalog.py` = **только 5 текстов описаний** (`CHAT_LOCK_MAX_ENTRIES`, `CHAT_BUDGET_RESPONSE_RATIO`, `YOUTUBE_TRANSCRIPT_PROXY_LOCATIONS/RETRIES`, `DIG_YEAR_BACK_WINDOW_DAYS`) с честной формулой «Не влияет: значение сохраняется в конфиге, но рантайм его не читает…»; ключи/группы/типы/widget'ы/счётчики не тронуты → **Δ каталога = 0** ✓ (у `memory_backup_keep` и `random_quantum_provider` честные тексты уже были — не менялись ✓). f8 re-pin осознан: `PARAM_CATALOG_SHA256_FOLLOWUP` = `4886ff036b0e52db…` = sha256 кандидата ✓ (комментарий с обоснованием L-F11S-1 и ссылкой на F2-deferred); `tools/gen_param_registry_round1025.py --check` → **579 OK** ✓; TSV/meta переэмитированы генератором (5 строк).

## 3. Тесты
Новый файл — **16 passed** ✓; набор препа+пинов (10 файлов) — **256 passed** ✓; RED (лог) — 3 падения ровно по доказанным дефектам (5 нечестных описаний; 2 type-family; float-каст) ✓. `TYPE_FAMILY_EXCEPTIONS` в тесте — **не ослабление**: тест явно перечисляет 2 задокументированных исключения и проверяет согласованность всех остальных ключей ✓.

## 4. Бласт/UI
JS-sweep `tests/js/*.js` → **88/0** ✓; e2e `tools/ui_cfg03_descriptions_e2e.py` → **RESULT: PASS**, `console_errors=[]`, повторный прогон не изменил evidence (0) ✓; скриншоты (честные описания, synthetic-группа) осмотрены. Бласт 115 файлов: я подтвердил на **базовом worktree `71c12bfe`** 2 детерминированных pre-existing (`test_asap7_direct_settings` v35 ×2 ✓); третий (`test_summary_publish_integration_round1026`) в изоляции **зелёный и на базе, и на кандидате** (72 passed) → его падение в полном прогоне — order/env-флейк (атрибуция «не от CFG-03» сохраняется; нит для леджера: помечать как флейк, не «детерминированный pre-existing»).

## 5. Дисциплина
`web/app.js`/`web/index.html` **не тронуты** (Δ web = 0) ✓; CFG-04/07B не задеты ✓; параллельные vision-файлы в дельту CFG-03 не попали ✓; фактический след лейна = `param_catalog.py` (M) + 3 новых инструмента/теста + f8-репин + TSV/meta + evidence ✓.

## 6. F2 (2 type-mismatch) — рекомендация: **backlog, не расширение scope сейчас**
`limits.image_freq_limit_cooldown_seconds` (каталог int vs Settings float) и `limits.youtube_transcript_proxy_retries` (int vs str): пины типов живут в тестах **других слайсов** (`test_cfg02b_image_freq_limits.py:266`, `test_hot_migration.py:225`) — вне write_scope CFG-03; функциональный вес мал (cooldown — секунды, дробное `300.5` не кастится; `retries` — мёртвая ручка с честным описанием). Оба расхождения **задокументированы** (тест-исключения, `failures.md`, `inventory/audit-summary`). Рецепт мини-коммита уже описан (§3.4: catalog delta + переэмиссия TSV/meta + re-pin f8/factory + правка 2 пин-тестов) — выполнить отдельной малой задачей, когда её scope будет санкционирован (PM).

## Леджер (19 строк CFG-03; гейт: `scoped=19 errors=20` — 19 PENDING + rolling-candidate, pre-binding)

* **Код-сторона → VERIFIED**: `CFG-03.1` (инвентарь 579/UI_missing=0), `.2` (классификация матрицей), `.3` (read/write/reload — фикстуры/переиспользованный P0/CFG-01), `.5` (описания честные; F2 задокументирован), `.7` (runtime-пути), `.8` (изоляция фикстур), `.9` (устойчивые автотесты), `.10` (независимый Reviewer-аудит — этот вердикт + биндинг; 100% не объявляется), `R1` (манифест), `R2` (owner-summary.md), `R3` (failures.md), `ADD-1.T3`, `CFG-03.F`, `CFG-03.M` (цепочка на каждый параметр).
* **Live → READY_FOR_LIVE (Ф6, preprod/postdeploy)**: `CFG-03.4` (hot-проверка без рестарта), `CFG-03.6` (честность в живом проде), `CFG-03.11`/`.12` (выборочные негативы/OFF-ON) + `R4`-список (manual-checks.md; PET: device-чек-лист отменён владельцем, авто-проверки достаточны) — в этом лейне не заявляются.
* **Note**: F2 — backlog с готовым рецептом; «3 pre-existing» в бласте — фактически 2 детерминированных + 1 order/env-флейк (см. §4).

## Итог

Аудит выполнен по-настоящему сквозным: машинный инвентарь на все 579 параметров (552 static + 13 dynamic, UI_missing=0), честные описания для «мёртвых ручек» без изменения каталога, контрактные тесты и негативы, бласт с подтверждённой атрибуцией, e2e/визуальный контроль. Блокеров нет; F2 — малый backlog; live — Ф6. **Approved**.
