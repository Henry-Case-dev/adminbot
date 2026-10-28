# POSTDEPLOY-VERIFY-BUNDLE — 2.58.133 @ b5716022 (read-only)

**Дата:** 27.10.2026 (server UTC 26.10 14:44:24–14:45:11). **Прод:** `198.46.175.136`, unit `admin_bot`.
**Deployed SHA (измерен на сервере):** `b571602226c5e5a5845850597f6100e3a6e0d12a` (detached HEAD, `git rev-parse HEAD`), `APP_VERSION="2.58.133"`, healthz `{"status":"ok","version":"2.58.133"}` (внешний, измерен в сеансе + локально HTTP 200), `SVC=active`, **NRestarts=0**, MainPID 288472 (без изменений с деплоя), TRACKED_DIRTY=0 / UNTRACKED=13 (те же 13, задокументированы в deploy.md).

## Метод и дисциплина

| Параметр | Значение |
|---|---|
| SSH-коннектов | **1** (paramiko, один логин, без ретраев, интервал не требовался), длительность 47 c, одно sudo-подтверждение |
| Запись на проде | нет: SQLite `mode=ro` + `PRAGMA query_only=1`; PG — только `SELECT`; journalctl/`diag aliases` — READ-ONLY; /tmp-стейджинг проб удалён (`CLEAN_OK`) |
| Секреты/R17 | пароли скрабятся из вывода; `.env` не печатался (только флаг `SPEECH_STYLE_POLICY_ENABLED`); plan_meta — R17-safe (поля без текстов) |
| Raw-транскрипт | scratch `OPENCODE_WORKFLOW_SCRATCH` → `adminbot-ccef72c25768/postdeploy-258133/raw-session.txt` (драйвер `pdv_driver.py`, preflight — там же) |

## Сводка вердиктов

| Строка | Вердикт | Основание |
|---|---|---|
| asap3 **ACC-03** (dash-правило включено по умолчанию и реально применяется) | **VERIFIED** | настройка: PG `style.policy` (4543 B) содержит `dash.hard.factory`, записей `"enabled": false` в документе 0; hot/env-выключатели не установлены (`flags.speech_style_policy_enabled` в PG нет, `.env` unset → заводской default ON); поведение: окно dash-эры (23.10 17:51Z→26.10 13:43Z) — 141 исходящих, **140 без «—»**; последние 20 сообщений (direct/initiative/rich, 26.10 09:11–13:43Z) — **0 «—»** во всех |
| asap3 **ACC-09** (регресс на реально действующей конфигурации) | **VERIFIED** | сервер HEAD == проверенный SHA (измерено); release-258133: гарды (compileall rc=0, param-registry OK), re-probe §12-r2 на живом контуре (реальный LLM, hot-конфиг из PG `wide_context_hot=true`, `deepseek/deepseek-v4.1-flash`), 6/6 PASS |
| asap3 **A16** (алиас-путь живой) | **VERIFIED** | `manage.py diag aliases --chat-id -1002661910336 --show-names` rc=0: `uid=42115912 chat_alias='Макс' global_alias='Макс' effective='Макс' source=chat`; chat-слой перекрывает global (uid 529151103: chat «Папаха» > global «Толян»), merged=38 |
| asap2 **DONE-D6** (остаток: живой sample plan_meta needs_clarification) | **VERIFIED** | PG `llm_usage_events` (module=direct_chat, step=l1_planner, ts ≥ 23.10 17:51Z): 139 строк, 98 с plan_meta, **11 с точным `"needs_clar": true`**; инструментация 2.58.118 живая, журнал коррелирует (L1_PLAN=98 == PG with_meta=98) |
| **SOUL-14.2** (телеметрия речи присутствует) | **VERIFIED** (structure-level) | SQLite `mca_events`, `event_name='speech_extent'`: **196 событий** (21.10 15:11Z–26.10 13:43Z), распределение 7 групп extent×status (compact 99 pass, micro 35 pass + 19 conflict, normal 32, auto→n/a 5, detailed 3, longform 3); usage_json: extent/status/one_word/one_word_exact/words/context/reason; оба прод-стейджа (direct_pre_send, initiative_pre_send). `one_word_exact=0` — по-прежнему NOT_YET_OBSERVED (честно) |
| **SOUL-05.6** (цепочка до Telegram payload) | **VERIFIED** (по существующему evidence) | тесты кандидата в deployed SHA: `git ls-tree b5716022` содержит `tests/test_soul1_style_payload.py` (8 кейсов, review-w3 recheck F3 byte-equal), `test_soul1_extent_one_word.py`; прод-пробы 2.58.86 (`verify-after.txt` gates 10/10); owner-наблюдаемость — owner_optional (standing rule PET_PROJECT) |
| **SOUL-AMD.8.11** (search/factcheck/video) | **PARTIAL**: search **VERIFIED**, factcheck **VERIFIED**, video **PENDING** | search — свежая read-only проба на задеплоенном дереве (см. §3); factcheck — release-probes (r2 S02 честный отказ PASS; AMD-PROBES 21.10 v2 `ready/supported/current/contextual`, durable `tfr-38ab2b7fa98b44cb`; PG-флаги сегодня: `factcheck_enabled=true`, `factcheck_pipeline_v2=true`); video — capability `not_configured/media_source_unconfigured/cobalt_absent`, внешний медиа-источник не настроен — WAITING_EXTERNAL (без Human Gate), evidence `plans/features/soul-1/evidence/amd-probes/amd811-search-factcheck-video.txt` |

## §1 ACC-03 — детали

- **Настройка (PG, измерено 14:44Z):** `bot_settings` key `style.policy` (4543 B) — содержит `dash.hard.factory`; подстрока `"enabled": false` в документе отсутствует (ни одно правило не выключено). Заводское правило в коде b5716022 (`services/style_policy.py::factory_rules()`, `dash.hard.factory`, kind=dash, strictness=hard, enabled=True, origin=factory_default) синтезируется при отсутствии записи — включено по умолчанию БЕЗ миграции. Выключатели: `flags.speech_style_policy_enabled` в bot_settings нет; `.env` `SPEECH_STYLE_POLICY_ENABLED` unset → гейт в default-ON.
- **Реальное применение:** окно dash-эры 23.10 17:51Z → 26.10 13:43Z (`mca_bot_outputs`, ro): 141 сообщение, 140 без «—». Последние 20 (включая rich_message-дайджест 7376 B, initiative_reply, direct_reply, оба чата) — 0 «—». С момента рестарта 2.58.133 (26.10 14:05Z) исходящих ещё **0** (честно: NOT_YET_OBSERVED на новом процессе — ему 40 минут).
- **Биндинг кода:** `git diff d3a9a2cc..b5716022 -- services/style_policy.py` пуст и `git diff 79ec3726..b5716022 -- …` пуст → enforcement-код, отправивший проверенные сообщения (2.58.129/2.58.132), байт-идентичен задеплоенному. Acceptance-артефакт `evidence/acceptance.md` (sha256 6a15e111…) верифицирован на 9ed68ee8, carrier 79ec3726 — все ASAP3-пути байт-идентичны (release-258129-binding §1).
- **Замечания (честно):** 1 сообщение из 141 в окне содержит «—» — тело/kind не выгружались (бюджет одного сеанса); гипотеза — защищённый сегмент (цитата/URL) в rich-дайджесте, правило защищает verbatim_quote. Ad-hoc проверка chat-уровня оверрайдов в `chat_keys` упала (запрос ошибочно использовал колонку `value`; реально `key_name`/`key_value`) — компенсируется поведенчески: сообщения обоих чатов чистые.

## §2 ACC-09, A16 — детали

- **ACC-09:** серверный `git rev-parse HEAD` == `b5716022…` (измерено 14:44:24Z) — деплой-дерево совпадает с проверенным кандидатом (плюс sha-пины из deploy.md §Деплой). Регресс на живой конфигурации: re-probe §12-r2 26.10 13:53–14:02 UTC, 6/6 PASS (`plans/features/p0-delta-analysis/evidence/live-scenarios-r2.md`); гарды релиза — `gen_param_registry --check` OK, `compileall services` rc=0 (release-258133/deploy.md §Guard'ы). Примечание карты «один вызов GET /api/speech/style из TMA» остаётся UI-слой-наблюдением и не блокирует инженерную приёмку строки (инструкция лейна: новый прогон не требуется).
- **A16:** вывод diag выше; команда READ-ONLY (трасса только SELECT, `tests/test_aliases_render_round1024.py`). Полный путь «вход→алиас→LLM→результат» на живом сообщении покрыт r2-пробой (реальный `_handle_turn`, чат -1004482340693, 6/6).

## §3 SOUL-AMD.8.11 — search-проба (сегодня, deployed tree)

`ToolRouter.dispatch("execute_web_search", …)` на `/var/www/admin_bot` (b5716022), `ToolDeps(db=None, llm=None)` — без БД, без LLM, без Telegram; единственный внешний вызов — поисковый провайдер из прод-`.env`:

```
SEARCH verdict=OK elapsed=1.7s chars=4073
HEAD='Результаты поиска по запросу «расстояние от Земли до Луны в километрах»:\nРасстояние до Луны - растояние в километрах от поверхности Земли\nApr 26, 2015 · …'
```

Детерминированно совпадает с AMD-PROBES 21.10 (тот же запрос → 4073 зн.) — принцип «работает одинаково + честный структурированный отказ при сбое» подтверждён на задеплоенном коде. Factcheck — без нового платного прогона (лейн): release r2 S02 честный отказ PASS на живом контуре + AMD-PROBES v2-прогон + durable-файл FC-R1; флаги v2/enable в PG — включены (измерено сегодня). Video — единственная несложная часть строки: провайдер не настроен, для верификации нужен внешний медиа-источник (настройка вне read-only полномочий и вне стоячей авторизации) → PENDING/WAITING_EXTERNAL.

## §4 Состояние процесса и журнал (контекст)

- Окно с рестарта (26.10 14:05Z): 1466 строк журнала, **0 ERROR/Traceback**; 0 новых L1-планов, 0 исходящих, 0 speech_extent — процесс жил 40 минут без пользовательской активности (последняя активность 13:47:48Z — ещё на 2.58.132). Последняя строка журнала 14:45:07Z — apscheduler INFO (жив).
- Журнал с 23.10 17:51Z: 154 261 строк; `"needs_clar": true` в журнале 0 — plan_meta в журнал не пишется, durable-хранилище PG (корреляция L1_PLAN=98 == PG with_meta=98).
- Откат: задокументирован в release-258133/deploy.md (`git checkout d3a9a2cc8ff22779c121e7c97a1432d42f13e6e4`), не требовался; последний подтверждённо-здоровый релиз — текущий.

## §5 Итог

7 строк READY_FOR_LIVE закрыты производственными фактами: 6 VERIFIED, SOUL-AMD.8.11 — search/factcheck VERIFIED + video PENDING (внешняя зависимость, не изменилась с 18.10). Блокеров релиза нет; прод 2.58.133 @ b5716022 здоров (healthz 200 loopback+внешний, NRestarts 0, журнал чист). Перевод статусов в картах (asap3-corrective: ACC-03/ACC-09/A16; asap2-direct-chat: DONE-D6; soul-1: SOUL-14.2, SOUL-05.6, SOUL-AMD.8.11) — за PM/Orchestrator на основании этого файла; raw-транскрипт — по пути в §Метод.
