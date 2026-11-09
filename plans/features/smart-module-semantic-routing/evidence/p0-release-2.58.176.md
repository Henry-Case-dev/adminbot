# SMR P0 (semantic routing) — выкладка 2.58.176

Артефакт выкладки DevOps. Только факты прогона: собранный релизный поезд, проверка
идентичности кода, тесты, живой прод и живые пробы. Секретов нет.

## 1. Что выкачено

| Поле | Значение |
|---|---|
| Версия | `2.58.176` |
| Задеплоенный SHA | `2b7e9c7f1915b6e3221f9a4fff49483a671b2418` |
| Ветка | `release/2.58.176` (immutable checkout по SHA на сервере) |
| Предыдущий прод | `2.58.175` @ `34213999` |
| Сервер | `192.255.209.205`, `/var/www/admin_bot`, unit `admin_bot` |
| Схема | `user_version=46`, `schema_migrations=35`, `quick_check=ok` — **без DDL** |
| Откат | `git checkout --detach 34213999` + `systemctl restart admin_bot` + `backups/predeploy-258176.db` |
| Рабочее дерево для деплоя | не требуется: прод — detached checkout по SHA |

## 2. Состав поезда (cherry-pick поверх `34213999`)

| # | Исходный SHA | В релизе | Что |
|---|---|---|---|
| 1 | `368a738a` | `efed4461` | P0-B, промежуточный контракт — **в финальном дереве его подхода нет** (см. §3) |
| 2 | `f1b97ce2` | `1c7bdf90` | P0-A: у лексики нет права решать генерацию изображения |
| 3 | `468ee956` | `272a6888` | P0-A: до L1 остаётся только явная команда, без semantic veto |
| 4 | `67063aa5` | `a1793ef1` | P0-B final: только «транскрипт» и «че за видос» — команды |
| 5 | `6fec18d2` | `0538e487` | help: справка больше не рекламирует удалённые видео-команды |
| — | — | `2b7e9c7f` | `chore(release): 2.58.176` — bump `APP_VERSION` + 25 version-пинов |

`368a738a` включён намеренно: `f1b97ce2` и `67063aa5` написаны поверх него, а его
подход (выбор видео-задачи по «текущему сообщению» с лексикой) полностью заменён
финальным контрактом `67063aa5`.

## 3. Идентичность продукта проверенному кандидату

### 3.1. Продуктовые файлы релиза байт-идентичны `6fec18d2`

`git diff --stat 34213999 2b7e9c7f -- services handlers web bot.py` — ровно 6 файлов,
и каждый равен версии из `6fec18d2` (blob из `git rev-parse`):

| Путь | blob в выкате | blob в `6fec18d2` | Равно |
|---|---|---|---|
| `handlers/youtube.py` | `d52537c33f39` | `d52537c33f39` | да |
| `services/command_registry.py` | `0cce7abd7c4d` | `0cce7abd7c4d` | да |
| `services/direct_capabilities.py` | `670e28d9f1c7` | `670e28d9f1c7` | да |
| `services/direct_chat_service.py` | `0d6c15fdbd86` | `0d6c15fdbd86` | да |
| `services/image_generation.py` | `702ac558fd67` | `702ac558fd67` | да |
| `services/info_service.py` | `9dc9f21789f7` | `9dc9f21789f7` | да |

Плюс `info_text.md` и `README.md`: в `info_text.md` файл совпадает с `6fec18d2`
(единственная разница по `README.md` — строка версии в шапке `v2.58.174`, она в
проде уже такая и релизом не менялась: `2.58.175` тоже её не трогал).

### 3.2. Формальная проверка «diff пустой» и её честный результат

`git diff 6fec18d2 2b7e9c7f -- services handlers web bot.py` **не пустой**: 7 файлов.
Это НЕ остаток P0-работ, а ровно та часть интеграционной линии, которая в прод
сознательно не входит (SELF-DIAG-01 D2 `98bc424e` + параллельная реализация
MOD-ACL на линии кандидата):

| Путь | В выкате | В `6fec18d2` | Факт |
|---|---|---|---|
| `handlers/checkup.py` | `dc18b1e2` | другой | равен `34213999` — D2-правка не пришла |
| `services/access.py` | `2e70f6d3` | другой | равен `34213999` |
| `services/tool_router.py` | `500669c8` | другой | равен `34213999` |
| `web/api/access.py` | `d29119da` | другой | равен `34213999` |
| `services/diagnostic_policy.py` | отсутствует | присутствует | D2-файл, в проде нет |
| `services/output_projection.py` | отсутствует | присутствует | D2-файл, в проде нет |
| `services/telegram_role_check.py` | отсутствует | присутствует | D2-файл, в проде нет |

То есть по всему продуктовому коду, который этот релиз **меняет**, дерево совпадает с
проверенным кандидатом байт-в-байт; по остальным путям сохранён ровно тот код, который
уже работает в проде с 2.58.175. Ни один файл D2/ACL-линии в прод не протёк.

## 4. Остатки отвергнутого подхода

`git grep -n "mentions_video\|_has_video_target\|_has_trigger\|_addressed_to_bot" -- services handlers` — 9 попаданий:

| Место | Классификация |
|---|---|
| `handlers/youtube.py:342` `def _has_video_target` | живой код, существовал до релиза; определяет, является ли ссылка видео-целью |
| `handlers/youtube.py:677` `_has_foreign_url` → `not _has_video_target(text)` | живой код, существовал до релиза; «ссылка-статья → ветка 0f» |
| `handlers/youtube.py:451` (docstring `_resolve_video_media`) | **только комментарий**: упоминает уже удалённый `_has_trigger` |
| `handlers/web.py:64`, `:93` `_has_trigger` | живой код группы `web` (0f), не менялся релизом |
| `services/video_intent.py:254` `def mentions_video` | живой код-определение, но в дереве релиза **вызовов нет** (мёртвый публичный хелпер); окно соседних видео выключено: `handlers/youtube.py:809` вызывает `resolve_request(..., allow_window=False)` |
| `services/initiative_observer.py:1893`, `:1980` `_window_all_addressed_to_bot` | живой код инициативы, к видео-маршруту отношения не имеет |

Удалено финальным контрактом (проверено сравнением с `34213999`): `_has_trigger` и
`_addressed_to_bot` из `handlers/youtube.py`, а также `video_context = canonical or
video_intent.mentions_video(text)` — источник обоих симптомов инцидента.

## 5. Схема, данные, промпты

- `services/database.py` не менялся: blob `5ba74e1e64b6` и в `34213999`, и в выкате.
- `git diff --name-only 34213999 2b7e9c7f -- services/database.py migrate_history/ scripts/` — пусто.
- После рестарта: `user_version=46`, `schema_migrations=35`, `quick_check=ok` — миграций не было.
- `config/settings.py`: единственная изменённая строка — `APP_VERSION` (+25 version-пинов в тестах,
  как в предыдущих релизах). Новых полей Settings, флагов, ключей каталога нет.
- Промпты не менялись. Из «текстовых» путей в дельте только справка:
  `info_text.md`, `services/info_service.py` (`DEFAULT_INFO_TEXT`), `INFO_CANON_VERSION 9→10`,
  прежний текст сохранён (`PREV_P0B_DEFAULT_INFO_TEXT`, длина 12 625; на проде после старта —
  лог `info canon migrated | v=9→10`).

## 6. Тесты на точном релизном дереве

Прогон локально на `2b7e9c7f` (Python 3.12, `.venv` проекта).

| Набор | Итог |
|---|---|
| P0-A capability/image/quota + P0-B video/registry/direct/planner/executor + help/info (39 файлов, `pytest_a.txt`) | **1 401 passed, 4 failed** |
| meme/cover/initiative (47 файлов, `pytest_b.txt`) | **906 passed, 6 failed** |
| smart_cache/avatars/permsoc (6 файлов, `pytest_c.txt`) | **110 passed, 3 failed** |

Все 13 падений воспроизведены на задеплоенном родителе `34213999` (`smr-p0-parent-34213999`) —
значит они не привнесены релизом:

| Тест | Причина | На `34213999` |
|---|---|---|
| `test_unified_image_request_round1026::...out_of_diff_vs_baseline` | исторический bounds-тест: `git diff` против тега `e8646af`, ловит `db/`-префикс | падает так же |
| `test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff` | то же, базовая точка `pre-round1026-a1` | падает так же |
| `test_addtr_tools_minifix::test_l1_seam_announce_then_execute_once` | `AttributeError: 'DirectChatService' object has no attribute 'llm'` — фикстура теста не задаёт атрибут | падает так же, тот же текст |
| `test_help_ui_round1020::test_tabs_ids_and_order_unchanged` | ожидает прежний список вкладок (`mod_time`/`oversight` пришли с UI 2.58.17x) | падает так же |
| `test_initiative_coordination` (4 теста) | известный набор инициативы | падают так же |
| `test_asap5_graphrag_recovery::test_warning_coalesced_not_repeated` | известный набор | падает так же |
| `test_webapp_asap_cover_ui_v21::test_history_shows_activation_date` | известный набор UI | падает так же |
| `test_webapp_avatars_ui::test_close_and_fullscreen_buttons` | известный набор UI | падает так же |
| `test_permsoc_f7_round1025` (2 теста) | `TypeError` в tz-пути | падают так же |

`get_smart_cache`-ошибки («18 errors») в этом прогоне не воспроизвелись: `tests/test_smart_cache.py`
в изолированном прогоне проходит; набор из 18 ошибок связан с общим прогоном всего пакета,
а не с релизом (в дельте нет ни одного файла кэша/смарт-кэша).

## 7. Пост-деплой факты

| Проверка | Факт |
|---|---|
| `/healthz` локально | `{"status":"ok","version":"2.58.176"}` |
| `/healthz` публично | `{"status":"ok","version":"2.58.176"}` |
| Сервис | `SubState=running`, `MainPID=3466895`, `ExecMainStatus=0`, **`NRestarts=0`** |
| Журнал с рестарта | 195 строк, `Traceback=0`, `ERROR=0`, `CRITICAL=0`, unit-фейлов 0 |
| Канон справки на старте | `[config_cache] info canon migrated \| v=9→10` |
| `/web/app.js` отданный | sha256 `f91ce8ec1ec6446a6fa9daf034a5df93750b8e31c1401ba5fd930b7b69dcca91` |
| `/web/app.js` в checkout | тот же sha256 — **совпадает** |
| `/web/app.js` в 2.58.175 | тот же sha256 `f91ce8ec…` — **не отличается**, потому что релиз не меняет `web/` (0 файлов): фронтенд байт-в-байт прежний |
| `/web/index.html` | подстановка `?v=2.58.176` — 17 вхождений; `2.58.175` — 0 |
| Схема после рестарта | `user_version=46`, `quick_check=ok`, `schema_migrations=35` |
| Снапшот перед выкладом | `backups/predeploy-258176.db`, 1 833 639 936 B, sha256 `cfbaf19b59f949c3a299398d1ac3528d5119ae941aca86b82e19ebb79383875a`, read-back `quick_check=ok` / `user_version=46` |

Идентичность кода на сервере (sha256 файлов в checkout): `config/settings.py` `5cc42547…`,
`services/database.py` `4d078c27…`, `handlers/youtube.py` `a5043703…`,
`services/command_registry.py` `baee3dd8…`, `services/info_service.py` `533447d9…`,
`info_text.md` `3966ea85…`.

## 8. Живые пробы на выкаченном дереве (in-process, без отправок и без платных вызовов)

Прогон интерпретатором юнита в `/var/www/admin_bot`; ни одного сообщения в чаты, ни одного
вызова провайдера, ни одной записи в БД.

| Проверка | Наблюдено |
|---|---|
| `APP_VERSION` процесса | `2.58.176` |
| Реестр `youtube` | `["транскрипт", "че за видос"]` — ровно две |
| `matches_group('о чем видео' / 'поясни за видос' / 'че по видосу' / 'выжимка из видео')` | все `False` |
| `INFO_CANON_VERSION` | `10` |
| Канон содержит «о чем видео» / «поясни за видос» / «че по видосу» / «выжимка из видео» | все `False` |
| Канон содержит «транскрипт» / «че за видос» | `True` / `True` |
| «Бот, что происходит в чате?» → `_triggered_body` / `_handle_unclassified` | `None` / `UNHANDLED` |
| «что происходит в чате, народ?» | `None` / `UNHANDLED` |
| «Бот, чем отличается манга от не манги?» | `None` / `UNHANDLED` |
| «Бот, транскрипт» → `_triggered_body` | `'транскрипт'` |
| «Бот, че за видос» → `_triggered_body` | `'че за видос'` |
| «Бот, что происходит в чате, че за видос» (проза) | `None` — команда внутри прозы не выполняется |
| Команда «Бот, нарисуй кота»: `is_image_keyword` / `extract_prompt` | `True` / `'кота'` |
| Команда: `detect_action_intent` | `create_image`, `actionable=True`, `reason=create_image_command` |
| Манга-фраза: `is_image_keyword` | `False` |
| Манга-фраза: `detect_action_intent` | intent пустой, `actionable=False` |
| Манга-фраза: `_image_capability_gate` (реальный сервис) | `False`, отправлено **0** сообщений — ни генерации, ни текста про квоту |
| Команда: `_image_capability_gate` | `True`, 1 сообщение — **управляемый шаблон**, потому что capability сейчас `not_configured` |
| `caps.resolve("image_generation")` | `available=False`, `status=not_configured`, `reason=image_provider_unconfigured` |

**Честная граница:** платный вызов провайдера и реальная отправка в чат в пробах не
выполнялись (по условию «без отправок»). «Сквозной» путь команды подтверждён на уровне
реального сервиса до входа в генерацию; фактическая генерация на проде сейчас невозможна
не из-за релиза: capability изображений в проде `not_configured` (не задан ключ провайдера),
и это состояние не менялось ни этим релизом, ни предыдущим.

## 9. Гейт требований (`requirements_gate.py --stage release`)

| Прогон | Результат |
|---|---|
| `--candidate 2b7e9c7f --deployed-commit 2b7e9c7f…` (весь map) | `scoped=212 errors=274` |
| `--slice P0-A` | `scoped=19 errors=37` |
| `--slice P0-B` | `scoped=88 errors=126` |

Остаток — не технический дефект выката, а незакрытая привязка доказательств: строки
`PENDING` (живые/владельческие наблюдения), отсутствие `candidate`-привязанных артефактов
и `deployed_commit` в карте (в карте до сих пор `candidate_commit=468ee956`).
Это работа PM (привязка `2b7e9c7f` + переиздание доказательств), не DevOps; карту я не
переписываю и `VERIFIED` не выставляю. Пока гейт не зелёный, срез P0 **не объявляется
завершённым**.

## 10. Откат

`cd /var/www/admin_bot && git checkout --detach 34213999 && systemctl restart admin_bot`;
данные — `backups/predeploy-258176.db` (read-back проверен). Старый SHA и снапшот на
сервере присутствуют. Схема на откате совместима: DDL в релизе нет (v46 в обе стороны).

## 11. Что проверить владельцу в реальном чате

1. «Бот, чем отличается манга от не манги? Тем что её японцы рисуют или форматом страниц или чем?» —
   обычный ответ по смыслу, без картинки и без сообщения про квоту.
2. «что происходит в чате» — обычный ответ по переписке, без вопроса «какой из двух роликов».
3. «Бот, че за видос» — детерминированная видео-команда (при reply на ролик — разбор ролика;
   без цели — прежняя фраза «нет цели»).
4. «Бот, транскрипт» — расшифровка ролика (reply/своё видео/ссылка).
5. Обычное упоминание видео в разговоре (например, «гляньте, какое видео вчера вышло») —
   анализ НЕ запускается.
6. «Бот, нарисуй кота» — сейчас вернёт управляемый отказ «не настроено»: ключ провайдера
   изображений в проде не задан (состояние до релиза, не регресс).
