# PVR-S0 + PVR-S1 — независимое ревью Reviewer

- Кандидат: ветка `pv/write-layer` @ `7dd02046` (база `2841a6ef`).
- Нормативная база: `plans/features/prompt-versioning-ux/arch/versioning-ux-contract.md` разделы 1-5, 7; источник владельца `plans/owner_inputs/2026-11-04-epic-prompt-versioning-ux-01.md` разделы 0, 1, 3, 5, 6.
- Дата ревью: 04.11.2026. Проверялся сам кандидат, а не отчёт Builder.

## Вердикт

**Approved: срез PVR-S0/PVR-S1 можно сливать**, поведение проверено независимо. S2 (baseline) и S3 (history) могут начинаться от точки слияния.

Два условия, не относящиеся к коду среза:

1. `MAP_SYNC_REQUIRED` (владелец PM). Карты требований эпика нет: `plans/features/epic-prompt-versioning-ux-01/requirements-map.json` отсутствует; в `plans/progress_scope.json` задача `epic-prompt-versioning-ux-01` имеет `maps: []` и `coverage_complete: false`, вход `OI-2026-11-04-PROMPT-VERSIONING-UX` имеет `reconciled: false`; в `plans/workflow_state.md` эпик не упомянут. Гейт `requirements_gate.py --stage review --slice PVR-S1` без карты не прогоняется. Это `REQUIREMENT_DRIFT` у PM, а не дефект реализации: код переделывать не нужно.
2. Пост-деплойная сверка ЖИВЫХ байтов промптов в PG (пункт 7): локальный артефакт доказывает неизменность код-констант, но не значений владельца в `bot_settings` и `chat_profiles.overrides`. ТЗ (раздел 0.1) требует сверку именно действующих значений; выполняет DevOps после выката.

## Три опоры приёмки

- **Implementation**: прочитаны `services/prompt_release_policy.py` (`write_prompt_values`, `remove_prompt_override`, `capture_pre_versioning_values`, `activate_revision`, `assert_prompt_write_allowed`, PG- и память-сторы), `services/config_cache.py`, `services/chat_params.py` (`_apply_chat_patch`, рантайм-страж), `services/prompt_factory.py` (сбросы, restore_backup), `web/api/routes.py` (`/api/config` global+chat, meme-settings, DELETE chat key), `web/api/speech.py` (write/reset/rollback). По существу контракта 3.2: все решения (`skipped_same`, `read_applied`, полный набор overrides) читаются ВНУТРИ транзакции на её коннекте; значение, ревизия и событие фиксируются одним commit; путь best-effort "значение записано, журнал нет" удалён.
- **Test validity**: прочитаны тела 27 тестов `tests/test_prompt_versioning_enforcement.py`. Они проверяют фактическое значение в PG-двойнике, наличие ровно одной ревизии с ожидаемыми `origin/scope/chat/body`, `kind/outcome` события, отсутствие дубля текстовой ревизии на тех же байтах и неизменность значения при 503. Слабые места: (а) общий двойник `_ProfileConn` игнорирует CAS-токен, поэтому 409 доказывался только шпионом передачи токена, а не отказом; (б) матрица не покрывает `.../rollback` и успешный `restore_backup`. Оба места закрыты моими пробами и вынесены в задачи Builder.
- **Independent challenge**: 18 собственных проб на копии стенда (не из набора Builder): журнал недоступен на 5 путях, занятый лок, строгий PG-двойник с честным CAS, пакет "промпт + настройка" с падением второго этапа, третья мутация стража (speech-обработчик), cutover и рестарт с той же меткой, захват legacy-значений, чужой scope. Все 18 PASS; наблюдаемые значения ниже.

## По пунктам задания

### 1. Инвентарь обходов: PROVEN, с одной дополнительной точкой

Все 10 путей контракта 1.4 переведены на единый слой: `/api/config` (global и chat), `POST /api/initiative/meme-settings`, `DELETE /api/config/chat/{key}`, speech write/reset(mode=chat)/reset(mode=factory)/rollback, `apply_factory_reset`, `reset_chat_override`, `restore_backup`, релизная поставка (журнал не менялся, добавлен захват). Проверено по коду и по 5 HTTP-путям пробой: `web/api/routes.py` больше не пишет значение промпта перед журналом, `_prompt_record_saved_snapshots` и `record_manual_activation` удалены.

Дополнительная точка, которой нет ни в отчёте Builder, ни в перечне 1.4: `scripts/migrate_env_to_pg.py` пишет ВСЕ ключи каталога (включая `prompts.*`) напрямую `INSERT INTO bot_settings`; с флагом `--force` это перезапись живого текста промпта без ревизии. Это офлайн-скрипт, не API-путь, поэтому S0/S1 не блокирует, но должен попасть в runbook DevOps / S6 (не запускать `--force` по промптам до миграции скрипта на журнал).

Остаточные границы, признанные контрактом: прямой SQL `UPDATE prompt_revisions SET body` (риск R5) и raw-SQL операции `pg_db`/скриптов вне `ConfigCache`/`chat_params`; страж 5.3 на них не распространяется по определению.

### 2. Атомарность и честный 503: PROVEN

Инъекция `routes_mod._prompt_journal -> None` и `prp.default_journal -> None` (существующая точка, не доверял тесту):

- `POST /api/initiative/meme-settings` -> 503, `overrides` не изменились (`None`), ревизий 0.
- `POST /api/config` (global) -> 503, `cache.get(key)` = `None`.
- `POST /api/config` (chat) -> 503, override не записан.
- `POST /api/speech/block/{id}` (global) -> 503, прежнее значение `"исходный"` на месте.
- `DELETE /api/config/chat/{key}` -> 503, текст остаётся `"должен остаться"`.
- Занятый лок: подмена `transaction()` на исключение `LockNotAvailableError` -> 503, значения и ревизий нет (`JournalUnavailable("lock_timeout")`).

### 3. Байт-в-байт, CAS, пакет: PROVEN

- Повтор тех же байтов: chat и global -> HTTP 200, `skipped_same` = `[prompts.meme_joke]`, число ревизий не выросло (0 новых), значение не изменилось.
- CAS (два админа): общий двойник `_ProfileConn` токен игнорирует, поэтому я собрал строгий двойник (`UPDATE ... WHERE updated_at = $3` возвращает 0 строк). Наблюдено: `POST /api/initiative/meme-settings` с устаревшим `updated_at` -> 409, CAS-SQL дошёл до PG (`cas_updates=1`), в PG ничего не записано, ревизий 0, событий 0. То же для `POST /api/config` (chat) -> 409, без записи. Без токена CAS-SQL не выполняется (`cas_updates=0`), запись идёт и даёт ровно 1 ревизию и 1 событие.
- Устаревший global-токен: значение `bot_settings.updated_at` в сторе и `updated_at` в запросе различаются -> 409, ключ в кэше не появился, ревизий 0.
- Пакет "промпт + настройка": оба сохранены (промпт через журнал, `limits.search_max_symbols` прежним путём), `prompt_snapshots` содержит только промптный ключ.
- Падение второго этапа пакета: подмена `_write_chat_overrides_with_retry` на `ChatParamsConflict` -> 503, `code=partial_save`, `applied=[prompts.meme_joke]`, `rejected=[limits.search_max_symbols]`, при этом промпт реально записан, настройка нет. Т.е. обратный порядок и выдуманное "сохранено" исключены.

### 4. Рантайм-страж: PROVEN (две мутации Builder + моя третья)

- Мутация 1 (подмена `_write_prompt_items` на прямой `chat_params.set_chat_params` из meme-эндпоинта): `PromptJournalBypass`, значение в PG `None`, ревизий 0.
- Мутация 2 (подмена на `cache.set_many` для global): `PromptJournalBypass`, значение не записано, ревизий 0.
- Моя мутация 3, которой у Builder нет: подмена `prompt_factory.write_speech_value` на прямой `set_chat_params(...)` из `POST /api/speech/block/{id}` -> `PromptJournalBypass`, значение блока в PG осталось пустым, ревизий 0. Страж закрывает не только два известных места, а любой путь через `ConfigCache`/`chat_params`.
- Негативный контроль: тот же ключ внутри `journal_write_scope(...)` пишется нормально; правка только `detail_level`/`enabled` документа Core проходит без токена, а изменение `full_text` без токена отвергается.

### 5. reset-to-inherit: PROVEN

Цепочка: чатовая правка `"текст перед снятием"` -> пустая строка в meme-settings (снятие override). Наблюдено: override удалён (`None`), последняя активация `(chat_inherit_reset, recorded)`, `revision_id` указывает на ревизию с ровно тем текстом, ревизия в истории есть и не дублируется, а `read_applied` НЕ сдвинут (`active_after.revision_id == active_before.revision_id`). То же для `DELETE /api/config/chat/{key}` (проверено тестом среза и кодом).

### 6. Первый захват до версионирования: PROVEN, cutover не сломан

Прямой вызов `capture_pre_versioning_values` на сторе с ручными байтами (global и chat): захвачены ровно те значения, ревизии `origin=legacy`, `reason=pre_versioning_import`; все события `kind=legacy_import`, `outcome=recorded`; `read_applied` не появился; значения в PG не изменились; повторный вызов вернул 0 и не добавил ревизий. Это закрывает дыру с мемными промптами, введёнными после применения метки.

Влияние на cutover проверено эмпирически через `apply_release`:

- Холодный cutover с ручным текстом: захват создаёт legacy-ревизию, затем применяется заводской текст (`bot_settings` = factory), есть и `legacy_import/recorded`, и применяющая активация.
- Второй запуск с той же меткой: истинный no-op (ни ревизий, ни активаций).
- Владелец правит текст ПОСЛЕ метки, рестарт с той же меткой: ручной текст СОХРАНЁН, добавлена legacy-ревизия с ним, `read_applied` и `factory_revision_applied` не сдвинуты. То есть поведение "ручная правка остаётся активной" не сломано.

Нюанс, который следует знать S2/S3: захват делает `has_import=true` для блоков, которые раньше шли через `PLAN_LEGACY_CUTOVER`, поэтому для холодного журнала план становится `PLAN_ACTIVATE` (detail `new_factory_revision` вместо `cutover`). Итоговое значение и наличие legacy-снимка те же; `_HAS_CUTOVER_SQL` участвует только в вычислении `has_import`. Регрессии нет, но тексты отчётов/аудита будут отличаться.

### 7. Байт-идентичность промптов: код-часть PROVEN, живые байты PG NOT PROVEN

Пересчитал артефакт `evidence/pvr-s1/prompt-bytes-baseline.json` независимо от Builder:

- Блоков с `pg_key`: 39 (38 уникальных ключей).
- `diff blocks: []` по всем 39 блокам; агрегат `sha256` всех блоков = `51425b07d299e0beefd0510b7cdadd9049100b5de9a615fbe859263cd3d2e2ad` (совпал).
- `initiative.meme.joke` (`prompts.meme_joke`): `sha256 2f30ca1f9a6b6e0fb93ffaaf4946b49e300e0846a80afdc255a6086375452d58`, 95 байт.
- `initiative.meme.image` (`prompts.meme_image`): `sha256 f81fe7e4b5052635297b4270a7d15fecab0adea8ad6fa27e96e957fdb086276c`, 51 байт.
- `FACTORY_SET_SHA256_12` в коде = `54ac2b8ac34b` = значение в артефакте; `tests/test_evol018_prompt_audit.py` не менялся и зелёный; `services/prompt_registry.py` и `services/chat_prompts.py` диффом не тронуты.

Честная граница: скрипт захвата хеширует `pr.factory_text`, то есть КОД-константы, а не живые значения из PG (поле `source` артефакта при этом говорит "live configuration layer", что вводит в заблуждение). Требование владельца (раздел 0.1) относится к действующим значениям, которые он ввёл в админке. Их сверка возможна только на деплое: прочитать `bot_settings`/`chat_profiles.overrides` до выката и после, сравнить с этими же хешами. Это задача DevOps, а не блокер среза (пакет значений не пишет).

### 8. Чужая ревизия: PROVEN

- Ревизия `scope=chat`, `chat_id=-100777` -> активация в `chat_id=CHAT_A`: `applied=false`, `reason=revision_foreign_scope`, событий 0, значение в PG не изменилось.
- Глобальная ревизия -> активация в чате: тоже `revision_foreign_scope` (перепривязка чужого `revision_id` запрещена, перенос делается новой ревизией `origin=restored`, это S2).
- Ревизия своего чата активируется успешно (`applied=true`).
- Фронтенд эту операцию не предлагает: в чатовой области список отдаёт только строки своего `chat_id` (`_LIST_REVISIONS_SQL`), поэтому регрессии для пользователя нет.

### 9. Пробелы регистрации: приемлемо для S0/S1 при условиях

Фактические цифры: 39 блоков с `pg_key` (38 ключей); 28 ключей и 28 блоков с `ui=catalog` есть в каталоге параметров; 11 блоков (10 ключей) имеют `ui=catalog_pending` и в каталоге отсутствуют: `character.core` (2 блока-поля) и 9 управляемых сообщений `content.image_failure.*` + `content.image_request_clarify`. Они объявлены в `NON_CATALOG_SURFACES` с причиной, и есть тест против загнивания списка. Ни один из этих ключей не редактируется через `/api/config` (их нет в `param_catalog`), поэтому требование "промпт, отображаемый для редактирования, обязан иметь версии" на них сейчас не распространяется; в истории они read-only.

Условие: PM обязан зафиксировать в карте, что (а) 9 управляемых сообщений остаются read-only в истории до появления поверхности редактирования, (б) `character.core` редактируется экраном "Характер" (журнальный путь), (в) если какое-либо из них станет редактируемым - это S4/S6, а не "уже закрыто". Иначе пробел превратится в незаметный пропуск.

`prompt_migrations.normalize_legacy_speech`/`rollback_legacy_speech`: в продакшн-коде ВЫЗОВОВ НЕТ (только тесты `test_soul1_registry_legacy_removal.py`), то есть путь спящий; объявлен явно, пишет WARNING с id миграции и имеет собственный неизменяемый снимок и откат в `character.migration_snapshots`. Для S0/S1 приемлемо с условием: при первом реальном запуске миграции её нужно перевести на `write_prompt_values` (сейчас её правки попадут в историю только через последующий `capture_pre_versioning_values`). Владелец задачи - S6.

### 10. Тексты не изменены; audit-тест не тронут; sha-пин: PROVEN

- Диффом не затронуты `services/prompt_registry.py`, `services/chat_prompts.py`, `tests/test_evol018_prompt_audit.py`; новых маршрутов нет (`+ @api_router...` в диффе отсутствует, routes=0).
- `tests/test_evol018_prompt_audit.py` зелёный (41 passed вместе с 016/017), печать набора `54ac2b8ac34b` совпадает с эталоном.
- Переутверждение sha-пина `tests/test_round1025_f8_registry.py` - только тест, с прежней конвенцией L-F11S-1 и явным обоснованием в комментарии; новый хеш соответствует фактическому `web/api/routes.py` (тест зелёный, `160 passed`).

## Что именно запускалось (worktree кандидата, python из .venv основного репозитория)

- `tests/test_prompt_versioning_enforcement.py`: 27 passed.
- `tests/test_evol018_prompt_audit.py`, `test_evol016_prompt_activation.py`, `test_evol017_prompt_history_ui.py`: 41 passed, 1 skipped.
- `test_meme_pipeline_api.py`, `test_soul1_factory_defaults.py`, `test_soul1_w6_speech_ui.py`, `test_webapp_api.py`, `test_soul1_direct_prompt_reads.py`: 218 passed.
- `test_round1025_f8_registry.py`, `test_hotfix4_cover_nav_shell_round1025.py`, `test_evol016_prompt_journal_v39.py`, `test_soul1_registry_legacy_removal.py`, `test_soul1_core_registry_api.py`, `test_soul1_capability_fallbacks.py`, `test_asap_prompt_history_integrity.py`: 160 passed, 1 skipped.
- Широкий срез `-k "prompt or speech or config or meme or soul1 or hot_config or factory"`: 2132 passed, 2 skipped, 1 failed - `tests/test_asap2_clar_contract.py::test_34_factory_and_ladder_and_custom_preserved`. Падение ПРЕДСУЩЕСТВУЮЩЕЕ: ожидает метку `l1-planner-tech-reasoning`, в реестре (и на базе `2841a6ef`, и в кандидате) стоит `l1-planner-decision-profile`; ни тест, ни реестр диффом не тронуты. К срезу отношения не имеет, в бэклог.
- Мои 18 независимых проб: 18 passed (файл `probe_pv_s0s1.py` в WorkspaceData/runs/c742e4de9e92c489/prompt-versioning-ux-review-61114e229234/temp-0efbb868e8; в репозиторий не добавлялся).

## Замечания (не блокируют слияние S0/S1, у каждого есть владелец)

1. `Builder`, до закрытия S6: добавить долговечный тест на CAS-409 без записи для промптного пути (нужен строгий двойник, как в моей пробе) и расширить матрицу на `.../rollback` и успешный `restore_backup`. Сейчас эти контракты доказаны моими пробами, но не защищены регрессионно.
2. `DevOps`/`PM`: пост-деплойная сверка живых байтов мемных промптов и правка поля `source` в артефакте эталона (сейчас оно называет код-константы "live configuration layer").
3. `DevOps`/`S6`: `scripts/migrate_env_to_pg.py --force` может перезаписать текст промпта без ревизии; исключить промптные ключи или перевести на журнал, зафиксировать в runbook.
4. `Builder` (S2/S4): `PromptJournalBypass`, возникший на втором этапе пакета (запись непромптных настроек), сейчас отдаётся как 500; лучше честный 409/503 в формате `partial_save`. Данные не теряются (страж как раз предотвращает тихую перезапись).
5. `Builder` (S2): `activate_revision(scope=chat)` пишет override прямым SQL (`_SET_CHAT_OVERRIDE_SQL`, `updated_at` поднимается), минуя `chat_params_history`; это предсуществующее поведение, но baseline restore в S2 должен его учитывать.
6. Предсуществующее: `tests/test_asap2_clar_contract.py::test_34` (см. выше) - вне среза.

## Привязка приёмки

- Кандидат: `7dd02046` (ветка `pv/write-layer`), база `2841a6ef`; окружение: Windows, Python 3.12.0, окружение основного репозитория; сеть/LLM не использовались.
- Ledger среза: VERIFIED - пункты 2, 3, 4, 5, 6, 8, 10 (и 1 по коду, с дополнительной точкой `migrate_env_to_pg`); VERIFIED по код-части - пункт 7; NOT PROVEN - живые байты PG (пункт 7, пост-деплой); п.9 - принято с условием и владельцами (S4/S6) для 10 ключей `catalog_pending` и спящей миграции.
- Гейт карты требований: не прогонялся, карты нет (`REQUIREMENT_DRIFT` у PM).

## Слияние и следующие шаги

Слияние S0/S1 разрешаю: контракты 3.1-3.7, 5.1-5.3 и 7.3 (п.1-3, 6-8) на кандидате доказаны, тексты промптов не изменены. S2 и S3 можно начинать от точки слияния, но обе SERIALIZE на `services/prompt_release_policy.py` - вторая ветка обязана быть перебазирована на merge-коммит S0/S1, а не на `2841a6ef`.
