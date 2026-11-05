# PVR-S7 - независимая приёмка пакета версионирования промптов (Reviewer)

Дата: 04.11.2026. Кандидат: `evol/impl` @ `986d50e0` (отдельный worktree, detached). Прод: 2.58.155 @ `f4a44167`. Ревьюер не менял код приложения.

## 1. Вердикт

**Needs Fixes (узкий, только тесты).** Функционально пакет состоятелен: 9 из 10 открытых строк закрываются доказательствами этой сессии. Не закрывается пункт `PVR-REV-01`: нет durable-доказательств успешного `restore_backup`/`rollback` с сохранением истории и 409-без-записи именно на пути промпта. Это `open_item P1` (уже помечен `blocks_parent_done: true`), а не дефект поведения.

## 2. Что проверено

Переиспользованы существующие раннеры на кандидате:
- pytest 8 файлов версионирования (field_audit, evol017, evol018, history_pagination, baseline, enforcement, evol016_activation, evol016_journal_v39): **136 passed, 1 skipped**;
- `node tests/js/prompt_version_card_test.js`: `PVR-S4-CARD-OK`;
- `tests/ui_prompt_version_card_e2e.py`: `PVR-S4-OK`, failures=0 на 1536/1366/768/390/360, 37 скриншотов, 3 экрана (библиотечный редактор, мемы с 2 полями, «Характер»/Core).

Собственные пробы ревьюера (не из набора Builder): `confirm_probe` (Chromium, реальные web-ассеты, контракт API по форме сервера) 13/13 ok; `code_only_probe` 0 провалов; `long_actor_probe` (in-memory журнал, 130 013 символов) round-trip байт-в-байт.

## 3. Строки

| Строка | Вердикт | Доказательство |
|---|---|---|
| `PVR-GOAL-01` | **VERIFIED** | `test_every_editable_prompt_has_reachable_surface` + `test_every_editable_block_is_reachable_in_ui` + `test_version_ui_routes_exist_for_every_prompt` (машинная полнота: у каждого PG-блока есть поверхность и маршруты версий); `PVR-S4-OK` покрывает 3 экрана на 5 ширинах; я сам открыл карточку мемов и получил рабочие «История версий»/просмотр/сравнение. Прод: журнал, `/versions`, курсорная пагинация из `deployment_binding`. Декоративных act:/fac: не осталось: в панели человекочитаемые «ручная/базовая/из кода» + «кто». |
| `PVR-APPLY-01` | **VERIFIED** | Серверная семантика доказана ранее (S2/S4). UI закрыт моей пробой: сообщение «Назначить эту версию базовой? Меняется только эталон ... Действующий текст промпта останется прежним.» показано **до** действия; отмена дает **0 POST**; подтверждение дает **ровно один** `POST /api/prompts/prompts.meme_joke/baseline`, `/activate` не вызывается; после: «Базовая версия изменена, действующий текст пока прежний». |
| `PVR-UX-BASECONFIRM-01` | **VERIFIED** | Та же проба: подтверждение и для назначения, и для «Восстановить базовую для чата» («Действующий текст чата станет равен базовой версии. Другие чаты не затрагиваются»); отмена восстановления дает 0 записей. Кнопки без подтверждения нет: все три действия идут через `window.confirm`. |
| `PVR-UX-02` | **VERIFIED** | В карточке `[data-ini-prompt='joke']` (той же, что владеет «Историей версий») видимы и кликабельны «Отменить несохранённое» и «Сохранить», есть textarea, служебных хешей в поле нет. |
| `PVR-STD-04` | **VERIFIED** | 55 code-only блоков реестра, **ни у одного** нет `pg_key`, значит серверное правило `manageable=false`. В реальной панели истории строки есть, причина честная: «code-only: значение задаётся кодом, а не в базе, историю можно смотреть, применять нечего»; кнопок «Применить эту версию»/«Назначить базовой» нет. «Скопировать глобально» остается: это создание новой ревизии, а не включение. |
| `PVR-REV-01` | **FAILED (частично)** | Остальное зелено: поверхности и маршруты версий, батч-сейв со снимками, отсутствие потолка истории (1000+), pin/unpin, отказ чужой/retired/несовместимой, 503 без потери текста. Нет durable-доказательства успешного `restore_backup`/`rollback` с сохранением истории и 409-без-записи на пути промпта (есть только `test_restore_backup_refuses_without_journal`, а CAS-409 покрыт общим `test_asap8_v63_b10r09_settings_409_race` на слое chat_params, не через API промпта). Это `open_item P1`. |
| `PVR-REV-02` | **VERIFIED** | Два мемных поля дают две карточки одного компонента (`PVR-S4-OK`); `POST /api/initiative/meme-settings` пишет событие и значение, одинаковые байты не дублируют ревизию, 503 журнала без записи, пустой промпт снимает override со снимком (`test_meme_settings_*`); лимит 800 считается от фактического effective template (`test_meme_pipeline_stages`), append-режим при placeholders=0 объяснён в UI (`PVR-S4-OK`: «добавится после шаблона»). |
| `PVR-REV-03` | **VERIFIED** | `PVR-S4-OK` на 5 ширинах (включая 390/360) и моя проба на 1440: редактор, просмотр, сравнение, включение, назначение/восстановление эталона, ошибки, черновик. Скриншоты: `runs/pv-s7/shots`, `assign_dialog_state.png`, `code_only_panel.png`. Метки человекочитаемые, полные id только в деталях. |
| `PVR-REV-04` | **VERIFIED** | Конкурентные правки: `test_parallel_apply_single_activation`, CAS-токен через `set_chat_params`; чужая ревизия/чат: 403 и 0 активаций (`test_chat_isolation`, `test_activation_of_foreign_chat_revision_is_refused`); сбой вставки ревизии: 503 и значение не записано (тест и мой прогон); рестарт в ходе миграции: `test_v39_restart_is_true_noop`, `test_activation_drift_on_plain_restart_is_true_noop`; journal/config mismatch: честный drift без угадывания; пустой чатовый override: `test_meme_settings_empty_prompt_removes_override_with_snapshot`; legacy: fallback только без журнала, снимок до cutover; 1000+: `test_full_history_of_1000_revisions_has_no_cap` (1200 записей, 12 страниц); pinned/unpinned заводская поставка: `test_pinned_global_scope_survives_new_factory_release` и `test_unpinned_global_scope_keeps_release_policy`; специализированный endpoint: `test_config_global_write_goes_through_journal`, `test_speech_block_write_and_reset_go_through_journal`. **Мои пробы**: очень длинный промпт 130 013 символов дал applied, совпавший `sha256_12`, тело байт-в-байт, chars=130013; юникод и переводы строк тоже; неизвестный actor: ревизия пишется с пустым actor (без выдуманного имени) и реальным временем. |
| `PVR-EXEC-01` | **VERIFIED** | Ревью независимое (собственные пробы, не отчёт Builder), отчёт на русском, человеческих гейтов не создавалось, релиз и сверка прода выполнены DevOps (2.58.155, content identity). Остаточный пункт P1 - тестовый долг, не нарушение DoD. |

## 4. Запреты пакета держатся

- Тексты промптов не изменены: `test_body_sha_of_meme_prompts_matches_package_baseline` зелёный, `PVR-BYTES-01`/`PVR-INV-01` подтверждены.
- Второго журнала нет; baseline это метаданные существующей политики, без нового хранилища: `test_journal_ddl_gains_no_baseline_storage`, `test_release_migration_assigns_no_baseline`.
- Новых LLM-вызовов, бюджетов и DDL пакет не вводит (таблица v39 относится к более раннему EVOL-016).

## 5. Блокирующее (узкое, Builder)

**P1 - durable-регрессии.** Добавить два теста: (1) два конкурентных сохранения промпта с одинаковым `updated_at`, второй получает 409, значение и журнал содержат только первую правку; (2) успешный `prompt_factory.restore_backup(..., apply=True)` и rollback: история ревизий сохраняется, активации не теряются, повторный прогон дает no-op. Перепроверка: эти два теста плюс `test_prompt_versioning_enforcement.py`.

## 6. Неблокирующие наблюдения

- Пустой `actor` на пути записи принимается и сохраняется пустым, хотя другие пути требуют непустой actor. Поведение честное, но несогласованное: в бэклог, не блокер.
- `app.css` в проде отличался от одобренного кандидата (`A3`); после слияния 2.58.155 в `evol/impl` (`986d50e0`) правка z-index вошла в ветку, визуальная проверка этой сессии на текущем кандидате прошла.

## 7. Счёт

Закрыто этой сессией: **9 строк** (`PVR-GOAL-01`, `PVR-APPLY-01`, `PVR-UX-02`, `PVR-UX-BASECONFIRM-01`, `PVR-STD-04`, `PVR-REV-02`, `PVR-REV-03`, `PVR-REV-04`, `PVR-EXEC-01`). Остается **1** (`PVR-REV-01`, частично) до закрытия P1. После синхронизации карты: 57/58 VERIFIED, 1 PENDING.

**Пакет нельзя объявлять завершённым** до закрытия P1 (два теста), даже при полностью рабочем поведении.

---

# Re-review (PVR-REV-01)

Кандидат: evol/impl @ cd17ec91 (база 32ab5312, отдельный worktree). Дельта - только тесты: tests/test_prompt_versioning_enforcement.py (+73) и новый tests/test_pvr_rev01_prompt_conflict_no_write.py (+164). Код приложения, промпты и карты кандидат не меняет.

## Вердикт: **Approved**

PVR-REV-01 закрывается. Все 10 открытых строк закрываемы.

## 1. Что утверждают тесты (по телам, не по именам)

- test_restore_backup_apply_keeps_history_and_adds_revision: две ручные правки через реальный POST /api/config, затем prompt_factory.restore_backup(apply=True). Проверяется наблюдаемое: (а) значение вернулось к байтам бэкапа; (б) старые id ревизий входят в новый набор, новых ровно ОДНА, она origin=restored, scope=global, chat_id=None, тело = текст бэкапа; (в) добавлено ровно ОДНО событие manual_rollback/applied с id восстановленной ревизии и actor=owner, прежние события сохранены по порядку; (г) публичное чтение list_versions отдаёт 3 ревизии, активна восстановленная, прежние тела читаемы через get_revision_source; (д) повтор того же отката - no-op (applied пусто, planned_changed=0, ни ревизии, ни события).
- test_prompt_cas_conflict_writes_nothing: первая правка с токеном updated_at проходит; вторая с ТЕМ ЖЕ токеном даёт 409 conflict, несёт актуальный current_updated_at и applied пусто; после отказа значение, словарь ревизий и список событий те же, отклонённый текст в журнале отсутствует; чатовый срез - 1 ревизия и одно событие manual_edit/applied; повтор с токеном из 409 проходит (отказ не залипает) и даёт 2-ю ревизию с событием, указывающим на неё.
- Мемные байты не тронуты: test_body_sha_of_meme_prompts_matches_package_baseline зелёный; независимая сверка в кандидате даёт 2f30ca1f9a6b... / f81fe7e4b505..., совпадает с evidence/pvr-s1/prompt-bytes-baseline.json.

Ассерты содержательные: проверяют состояние, значения и идентификаторы, а не "вызов был".

## 2. Мутации (внесены мной в кандидата, затем git checkout)

- skip revision insert on restore: в prompt_release_policy._insert_revision_once не вставлять ревизию при origin == "restored" -> test_restore_backup_apply_keeps_history_and_adds_revision FAILED (len(new_ids) == 1 получил 0).
- CAS off: в chat_params убрать CAS-ветку (expected_updated_at игнорируется, обычный UPDATE_PARAMS_SQL) -> test_prompt_cas_conflict_writes_nothing FAILED на assert conflict.status_code == 409: получен 200.

Обе мутации - в прод-коде, не в тестовых двойниках: тесты пинят серверную семантику, а не свою же подделку. После откатов дерево кандидата чистое.

## 3. Честно о слое двойников

- Двойники: in-memory MemoryPromptJournal (журнал ревизий и событий) и _CasProfileConn (PG-двойник профиля). Настоящие: chat_params.set_chat_params, write_prompt_values, restore_backup, роуты, кэш. Двойник профиля эмулирует ровно форму прод-SQL UPDATE chat_profiles ... WHERE chat_id=$1 AND updated_at=$3::timestamptz: при несовпадении токена возвращает None (0 строк) -> реальный ChatParamsConflict -> 409; это и подтвердила мутация CAS-ветки.
- Чего двойник не доказывает и что добавил бы живой PostgreSQL: корректность самого SQL (колонки, ::timestamptz, равенство метки с микросекундной точностью, а не сравнение ISO-строк в двойнике), блокировку строки при конкурентных транзакциях, реальный откат незакоммиченных вставок журнала при 409, доставку pg_notify и chat_lore_history. Для этой строки (история сохранена, на отказе ноль записи) связки "двойник хранилища + настоящий слой записи" достаточно; ограничение зафиксировано.

## 4. Своя независимая проба (не из набора Builder)

Сценарий, которого в тестах нет: A -> B -> откат к A -> новая правка B -> ПОВТОРНЫЙ откат к A. Ожидание: значение A, история цела, у второго отката ровно одно новое событие, активный указатель на восстановленную ревизию. Наблюдено ровно это: 3 ревизии (manual A, manual B, restored A), 5 событий, active = восстановленная ревизия, list_versions отдаёт 3 записи. Id ревизии переиспользуется (content-addressed, вставка идемпотентна), но событие отката пишется заново и действующее значение корректно - контракту не противоречит.

## 5. Прогон

pytest tests/test_prompt_versioning_enforcement.py tests/test_pvr_rev01_prompt_conflict_no_write.py -q -> 29 passed (28 + 1), 1 warning (deprecation starlette), 5.1 s, на чистом кандидате.

## 6. Статус строк

- PVR-REV-01 -> VERIFIED на кандидате cd17ec91.
- Остальные 9 строк прошлого прохода (PVR-GOAL-01, PVR-APPLY-01, PVR-UX-02, PVR-UX-BASECONFIRM-01, PVR-STD-04, PVR-REV-02, PVR-REV-03, PVR-REV-04, PVR-EXEC-01) остаются VERIFIED: дельта tests-only, затронутых ими путей поведения не касается, живой прод 2.58.155 не менялся.
- Для карты: после синхронизации 58/58 VERIFIED, P1 закрыт. Дальше - только регистрация доказательств PM/Orchestrator, без нового цикла реализации.
