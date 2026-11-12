# SELF-DIAG-01 D1 — полный инвентарь вхождений Better Stack на `2587616759de` (2.58.197)

Дата: 2026-11-12. Автор: Builder (D1-closure), не Reviewer и не автор
предыдущего evidence. Артефакт закрывает **SD1-D1-07** (F-2) и служит
исходной таблицей для перепривязки evidence (F-3).

**Статус инвентаря.** Это статический read-only скан git-дерева на
production-коммите `2587616759de31283585ffc105c91e7193c2e89e`; production не изменялся, БД не
читалась и не менялась, SSH не использовался. Значения секретов не
печатались и не копировались.

## 0. Привязка и метод

| Поле | Значение |
|---|---|
| production | `2.58.197`, `2587616759de31283585ffc105c91e7193c2e89e` |
| worktree | `...\WorkspaceData\worktrees\c742e4de9e92c489\self-diag-01-0ccfa8fbf52b-01b13f1c` (detached на 25876167) |
| ветка артефактов | `self-diag/d1-closure` (docs-only; код не менялся) |
| метод | `git grep -n -I -i -E` по индексированному дереву HEAD |
| шаблоны | `betterstack`, `checkup_betterstack`, `CHECKUP_JOURNALCTL_CMD`, `models_checkup`, `keys_betterstack`, `logtail`, `BETTERSTACK_HOST`, `checkup_betterstack_sql`, `models.checkup` |
| варианты с пробелом | `better stack`, `better-stack`, `беттерстак`, `беттер стек` (учтены отдельно; +34 строк) |
| исключено | `.git`, `node_modules`, `vendor` (проверено: в `web/static/vendor` и `tools/vendor` совпадений 0), build-артефакты |
| JSON | `d1-inventory-25876167.json` — каждая строка отдельно (path:line, шаблоны, сниппет, sha256 строки для не-docs) |

Команда воспроизведения:

```
git grep -n -I -i -E 'betterstack|checkup_betterstack|CHECKUP_JOURNALCTL_CMD|models_checkup|keys_betterstack|logtail|BETTERSTACK_HOST|checkup_betterstack_sql|models\.checkup' -- . ':(exclude).git' ':(exclude)node_modules'
```

## 1. Счётчики

| Срез | Значение |
|---|---|
| вхождений (token-шаблоны) | **1385** |
| файлов | **231** |
| из них `plans/**` | 177 файлов |
| runtime-код (`services/**`, `config/**`, `web/**`, `bot.py`; включая `requirements.txt`) | 12 файлов; checkup-only упоминания Better Stack — только мёртвые id в `web/app.js` |
| tests | 35 файлов |
| env/README/tools/fixtures | 6 файлов |
| docs-line-only (нет на 25876167) | 139 строк в 18 файлах (пакет D1 на master + user-owned `current_task.md`) |

По disposition (с учётом точечных overrides):

| Disposition | Строк |
|---|---|
| `mark-historical` | 992 |
| `keep` | 390 |
| `remove` | 3 |

По владельцу:

| Owner | Строк | Смысл |
|---|---|---|
| `historical-doc` | 757 | исторический план/отчёт/архив — не исполняется |
| `global-logging-keep` | 252 | глобальный Better Stack logging/observability — сохранить (D1-11) |
| `historical-evidence` | 219 | историческое evidence/харнесс прошлого релиза |
| `active-doc` | 47 | живой документ с историческими/смежными упоминаниями |
| `d1-guard` | 45 | тест/гард, доказывающий отсутствие Better Stack в чекапе |
| `reference-doc` | 32 | справочный/сгенерированный снимок каталога |
| `test-fixture-name` | 11 | имя удалённого ключа как синтетическая метка теста |
| `d1-tool-historical` | 8 | одноразовый D1-инструмент, runtime-потребителей нет |
| `d1-adjacent-keep` | 7 | смежный код/комментарий D1-пути — сохранить |
| `dead-id` | 3 | мёртвые id групп в UI-исходнике — удалить (BACKLOG B-1) |
| `canon-doc` | 2 | канон промптов (текст CHECKUP_SYSTEM_PROMPT) |
| `active-doc-stale` | 1 | устаревшее current-state утверждение — исправить в doc-касании |
| `dead-id-guard` | 1 | JS-тест, удерживающий мёртвый id как фикстуру |

«Может влиять на приёмку D1»: **да** — 120 строк
(гарды, evidence, исторические доказательства линии D1, persisted-строки),
**нет** — 1265 строк (глобальный logging, архивы,
справочные снимки).

Ключевой вывод для D1-07: **в runtime-коде потребителей нет**. Во всём
дереве на 25876167 остались только 3 runtime-строки — мёртвые id групп в
`web/app.js` (92, 192, 193), которые ничего не рендерят (групп в каталоге
нет). Всё остальное — тесты-гарды, исторические документы/харнессы и
глобальный Better Stack logging, который D1-11 требует сохранить.

### 1.1. Покрытие областей, названных в D1-07

| Область D1-07 | Где в инвентаре | Итог |
|---|---|---|
| fetcher | `services/system_logs_fetcher.py` — 0; `handlers/checkup.py` — 0; `services/checkup_service.py` — 0 | потребителей нет |
| settings | `config/settings.py` — 0; гард `tests/test_settings_helpers.py`; исторические Settings-снапшоты | атрибутов нет |
| hot config | `services/hot_config.py` — 0 | hot-чтения нет |
| API read/write | `web/api/routes.py` — 0; `/api/config` через `get_all()`; `POST` — 422 | мёртвых items нет |
| UI | `web/index.html` — 0; `web/app.js:92,192-193` — мёртвые id | невидимый cleanup (B-1) |
| tests | §3 (35 файлов) | гарды + исторические фикстуры |
| fixtures | `tests/fixtures/**`, снимки soul-1 | маски/история |
| docs | §5 (177 файлов `plans/**`) + `README.md`/`ARCHITECTURE.md` | historical/keep |
| DI | `bot.py` (DI чекап-фетчера, строка 570) | Better Stack в DI нет |
| старые креды | `plans/features/cfg/evidence/cfg-03/*`, `prod-params-audit-2026-09.md`, 5 persisted-строк | значения в repo отсутствуют; строки удалены |
| глобальный logging (не D1) | `betterstack_handler.py`, `external_log.py`, env, `.env.example`, README, scripts | keep (D1-11) |

## 2. Runtime-код


| Файл | Строки | N | kind | owner | disposition | D1? | Назначение |
|---|---|---|---|---|---|---|---|
| services/betterstack_handler.py | 1,3-5,17,23,29,62,69,139,150-151,171,178-179,192,216,223,229,249,275,279,326,362 | 24 | code | global-logging-keep | keep | нет | Собственный logging handler Better Stack (буфер 2000, батч-флашер, Bearer-контракт ADR-1019-1). |
| services/checkup_prompts.py | 51,72,99,129 | 4 | code | d1-adjacent-keep | keep | нет | Канон/предыдущие версии CHECKUP_SYSTEM_PROMPT: фраза «логи (Betterstack или локальные)» — текстовая инструкция LLM. |
| services/external_log.py | 242 | 1 | code | global-logging-keep | keep | нет | Докстринг внешнего лог-канала (грепа/алерта Betterstack) — комментарий глобального logging-контура. |
| services/llm_client.py | 1180,1210,1421,1488 | 4 | code | global-logging-keep | keep | нет | Комментарии диагностического контракта: инцидентный сигнал уходит в Betterstack как ERROR-лог; никаких сетевых вызовов к Better Stack. |
| services/log_ring.py | 7,87-88,91,99,128 | 6 | code | global-logging-keep | keep | нет | Ring-buffer логов админки: фильтр logtail* против рекурсии LogtailHandler + комментарий про BetterStackHandler. |
| services/output_projection.py | 255,404 | 2 | code | global-logging-keep | keep | нет | Список env-секретов для редакции вывода: LOGTAIL_SOURCE_TOKEN маскируется в диагностических снимках. |
| services/param_catalog.py | 1086-1087,1090,4451 | 4 | code | global-logging-keep | keep | нет | Env-only ParamSpec глобального logging: LOGTAIL_SOURCE_TOKEN (secret) и BETTERSTACK_HOST (не secret). |
| services/prompt_composer.py | 1804 | 1 | code | d1-adjacent-keep | keep | нет | Эвристика functional-writer: маркер 'betterstack' в base-промпте отключает speech-base (рядом с 'checkup', 'summary'). |
| services/smartmodule_utils.py | 279 | 1 | code | global-logging-keep | keep | нет | Комментарий: полный трейс уходит в Betterstack (глобальный лог). |
| bot.py | 15-16,31,165,168-171,174,176,181-182,184-186,193,210,213,215,220-223,229,231,236,240,570,1136,1504,1601,1603-1604 | 33 | code | global-logging-keep | keep | нет | Инициализация BetterStackHandler из env LOGTAIL_SOURCE_TOKEN + BETTERSTACK_HOST, стартовый маркер и shutdown-flush. |
| requirements.txt | 14-15 | 2 | code | global-logging-keep | keep | нет | Комментарий: библиотека logtail-python удалена, используется собственный services/betterstack_handler.py. |
| web/app.js | 92,192-193 | 3 | code | dead-id | remove | нет | Зеркальные id групп mod_checkup в TABS: models_checkup/keys_betterstack (строки 192-193) + комментарий-зеркало (92). |

**services/checkup_prompts.py**

- `L51` — Предыдущая версия CHECKUP_SYSTEM_PROMPT: «логи (Betterstack или локальные)».
- `L72` — Предыдущая версия CHECKUP_SYSTEM_PROMPT: та же фраза.
- `L99` — PREV-канон: «Betterstack или локальные» в инструкции анализа.
- `L129` — Предыдущий канон отчёта: «логи Betterstack или локальные журналы».

**services/param_catalog.py**

- `L1086` — Env-only LOGTAIL_SOURCE_TOKEN (secret=True): глобальный logging-токен.
- `L1087` — Комментарий ADR-1018-1 D3: US ingest host BetterStack.
- `L1090` — Env-only BETTERSTACK_HOST (не secret): регион ingest.
- `L4451` — TAB_RULES-комментарий: D1 убрал checkup-группы с вкладки LLM Провайдеров; зеркало проверяется test_frontend_tab_mapping. (owner=d1-adjacent-keep)

**services/prompt_composer.py**

- `L1804` — Маркер 'betterstack' в эвристике functional-writer (рядом с 'checkup').

**bot.py**

- `L31` — Комментарий: Sentry (Better Stack Errors) — глобальный error-tracking, не чекап.
- `L570` — DI-комментарий: источник журнала чекапа выбирается в рантайме, Better Stack из чекапа удалён. (owner=d1-adjacent-keep)

**web/app.js**

- `L92` — Комментарий-зеркало TAB_RULES упоминает удалённые группы; обновить вместе со строками 192-193.
- `L192` — Источник mod_checkup: группа models_checkup (каталога нет → 0 items).
- `L193` — Источник mod_checkup: группа keys_betterstack (каталога нет → 0 items).

Примечание: `services/betterstack_handler.py` (24 строк) и `services/external_log.py` (1) — глобальный logging; SHA совпали с c134f93d по review. Удаление любого из них нарушило бы SD1-D1-11.

### 2.1. D1-runtime файлы с 0 вхождений (ожидаемо)

| Файл | Вхождений | Почему это важно |
|---|---|---|
| `services/system_logs_fetcher.py` | 0 | новый портируемый backend; `betterstack` в исходнике запрещён тестом |
| `handlers/checkup.py` | 0 | единственный источник — `_fetcher.fetch()` |
| `services/checkup_service.py` | 0 | нет HTTP/SQL-пути чекапа |
| `web/api/routes.py` | 0 | нет `/api/checkup` и спец-обработки ключей |
| `config/settings.py` | 0 | нет `CHECKUP_BETTERSTACK_SQL_*` и `CHECKUP_JOURNALCTL_CMD` |
| `services/hot_config.py` | 0 | нет hot-чтения удалённых ключей |
| `services/chat_keys.py` | 0 | BYOK-allowlist не содержит checkup-ключей |
| `services/pg_db.py` | 0 | нет пере-сида удалённых строк |
| `web/index.html` | 0 | 0 упоминаний Better Stack/checkup (D1-17) |

Ноль вхождений — ожидаемый и проверяемый результат D1; таблица выше
фиксирует его явно, чтобы «нет вхождений» не путалось с «не искали».

## 3. Тесты

| Файл | Строки | N | kind | owner | disposition | D1? | Назначение |
|---|---|---|---|---|---|---|---|
| tests/conftest.py | 66 | 1 | test | global-logging-keep | keep | нет | Комментарий-пояснение к reload config.settings в тестах handler'а. |
| tests/js/round1020_ui_rework_test.js | 148,150,161,163,213,215 | 6 | test | test-fixture-name | mark-historical | нет | Исторический JS-тест round1020: метки CHECKUP_BETTERSTACK_SQL_* в фикстурах маскирования. |
| tests/js/round1021_ui_audit_test.js | 170,176 | 2 | test | test-fixture-name | mark-historical | нет | Исторический JS-тест round1021: метка CHECKUP_BETTERSTACK_SQL_PASSWORD в фикстуре маскирования. |
| tests/js/round1025_f5_workspace_route_test.js | 365 | 1 | test | dead-id-guard | keep | нет | Инвариант покрытия workspace: использует models_checkup как пример потерянной группы (строка 365). |
| tests/js/routing_test.js | 1285,1291,1299 | 3 | test | test-fixture-name | keep | нет | JS-тест маскирования секретов использует 'keys.checkup_betterstack_sql_password' как произвольную фикстуру-имя. |
| tests/test_betterstack_handler.py | 1,3,11-12,32-33,35,74,83,87,95,111,117,134,166-167,174,176,181,188,200,205,207,213,218,223,235,257-258,263,269,273,276,293-294,296-297,312-313,343-344,348,352,373-374,378,382,399-400,412,414,430-431,435,443,455,461,464,475,490,510-511,515,527,536,538,588,612,614,617,621,628,659,669-672,688-689,693,695,700,703,709,712,716,719,728-729,739,745,748,754,757,760 | 95 | test | global-logging-keep | keep | нет | Тесты глобального BetterStackHandler: контракт, редиректы, счётчики. |
| tests/test_betterstack_probe.py | 18,61-62 | 3 | test | global-logging-keep | keep | нет | Тест scripts/betterstack_host_token_probe.py (env host/token). |
| tests/test_bot_main_flow.py | 69 | 1 | test | global-logging-keep | keep | нет | delenv LOGTAIL_SOURCE_TOKEN перед прогоном main-flow (изоляция глобального logging). |
| tests/test_cfg07_backstage_contract.py | 166 | 1 | test | d1-guard | keep | да | CFG-07 backstage-контракт: 'betterstack' не упоминается в notice. |
| tests/test_cfg07_egress_dictionary.py | 519,530 | 2 | test | d1-guard | keep | да | Словарь egress: 'betterstack' отсутствует в CHECKUP_FALLBACK_NOTICE. |
| tests/test_checkup_logs_fetcher.py | 14,232,436,439,446,449-454,458,462-465,470 | 17 | test | d1-guard | keep | да | D1-гард: fetcher без betterstack/create_subprocess_shell, legacy Settings-поля отсутствуют, в каталоге нет checkup-ключей/групп, bare-чекап 0 сетевых вызовов. |
| tests/test_checkup_prompts.py | 195 | 1 | test | d1-guard | keep | да | Гард честного fallback-текста: betterstack/journalctl/401/http/sql запрещены в CHECKUP_FALLBACK_NOTICE. |
| tests/test_diagnostic_policy.py | 1658 | 1 | test | global-logging-keep | keep | нет | Фикстура LOGTAIL_SOURCE_TOKEN для политики редакции диагностики. |
| tests/test_frontend_tab_mapping.py | 148,299-300,306-307 | 5 | test | d1-guard | keep | да | D1-гард: групп models_checkup/keys_betterstack нет в каталоге; комментарий о Δ D1. |
| tests/test_help_guide_round1014.py | 5 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога раунда). |
| tests/test_llm_client.py | 344 | 1 | test | global-logging-keep | keep | нет | Проверка диагностического маркера kind=embed (контракт BetterStack). |
| tests/test_log_ring.py | 5,131,134 | 3 | test | global-logging-keep | keep | нет | Тест фильтра logtail* в ring-buffer (рекурсия глобального handler'а). |
| tests/test_monitoring_smoke.py | 1,3-5,32,38,40-42,50,59-60,63,66-67,75,77,90-92 | 20 | test | global-logging-keep | keep | нет | Smoke глобального monitoring: BetterStackHandler получает записи, env BETTERSTACK_HOST/LOGTAIL_SOURCE_TOKEN. |
| tests/test_p0_checkup_core_contract.py | 56,157 | 2 | test | d1-guard | keep | да | Контракт ядра чекапа: запрещённые технические формулировки (Betterstack/401/journalctl) в ответе. |
| tests/test_param_catalog.py | 312,314-315,332,337-339,355,689 | 9 | test | global-logging-keep | keep | нет | Инварианты env-only каталога: BETTERSTACK_HOST (не secret), LOGTAIL_SOURCE_TOKEN (secret); комментарий о Δ D1. |
| tests/test_round1025_f8_registry.py | 375 | 1 | test | d1-guard | keep | да | F8-реестр: комментарий о санкционированной Δ D1 (удалённые ключи, добавленные env-only). |
| tests/test_round106_ia_smoke.py | 32,216-217 | 3 | test | d1-guard | keep | да | IA-smoke: 'checkup_betterstack' не в KNOWN_BLOCKS + счётчик env-only каталога (BETTERSTACK_HOST). |
| tests/test_self_reflection_provider_round1014.py | 67 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |
| tests/test_settings_helpers.py | 163,186-187,189-194,201-204 | 13 | test | d1-guard | keep | да | D1-гард: CHECKUP_BETTERSTACK_SQL_*/CHECKUP_JOURNALCTL_CMD отсутствуют как атрибуты Settings; дефолты CHECKUP_LOG_*. |
| tests/test_settings_persistence_round1014.py | 37 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (PG-only счётчик). |
| tests/test_settings_worker_sync_round1018.py | 546-547 | 2 | test | global-logging-keep | keep | нет | Изоляция env глобального logging в тесте worker-sync. |
| tests/test_summary_inc01_exit.py | 5,112-113,271 | 4 | test | global-logging-keep | keep | нет | Инцидент Summary: проверка '[betterstack] shutdown flush' при выходе; env-изоляция глобального logging. |
| tests/test_summary_inc01_shutdown.py | 85 | 1 | test | global-logging-keep | keep | нет | Env-изоляция глобального logging в тесте shutdown. |
| tests/test_webapp_parity_smoke.py | 52 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |
| tests/test_webapp_round1010_ui.py | 196 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |
| tests/test_webapp_round1011_ui.py | 157 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |
| tests/test_webapp_round1012_ui.py | 189 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |
| tests/test_webapp_round1013_ui.py | 32 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |
| tests/test_webapp_round1014_ui.py | 34 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |
| tests/test_webapp_round109_ui.py | 223 | 1 | test | global-logging-keep | keep | нет | Комментарий о +1 env-only BETTERSTACK_HOST (счётчик каталога). |

**tests/js/round1025_f5_workspace_route_test.js**

- `L365` — g2-инвариант: models_checkup обязан считаться потерянным при снятии вкладки «Модели».

**tests/js/routing_test.js**

- `L1285` — Фикстура keyDrafts: произвольная метка удалённого ключа.
- `L1291` — Фикстура item: title «Пароль», secret=true.
- `L1299` — Assertion: черновик секрета очищается (generic-поведение).

**tests/test_cfg07_egress_dictionary.py**

- `L530` — Честная админ-справка со словом «беттерстак» не блокируется backstage-фильтром (negative-case, не D1-путь).

**tests/test_checkup_logs_fetcher.py**

- `L14` — Docstring модуля: Better Stack в runtime-пути чекапа отсутствует.
- `L232` — Docstring: старое имя юнита (в т.ч. из CHECKUP_JOURNALCTL_CMD) не подменяет invocation.
- `L436` — Заголовок D1-гарда: Better Stack в runtime-пути чекапа отсутствует.
- `L439` — Класс D1-гарда: Better Stack отсутствует в runtime-пути чекапа.
- `L449` — Гард: CHECKUP_JOURNALCTL_CMD отсутствует в Settings.
- `L464` — Гард: группы models_checkup нет в каталоге.
- `L465` — Гард: группы keys_betterstack нет в каталоге.
- `L470` — Docstring интеграционного теста: 0 обращений к Better Stack.

**tests/test_frontend_tab_mapping.py**

- `L299` — Комментарий D1: checkup-only группы удалены из каталога.

**tests/test_param_catalog.py**

- `L689` — Комментарий: санкционированная Δ D1 — удалены checkup SQL-ключи и journalctl, добавлены env-only.

**tests/test_round1025_f8_registry.py**

- `L375` — Комментарий-пин: Δ D1 в F8-реестре.

**tests/test_round106_ia_smoke.py**

- `L216` — Комментарий D1: checkup-only Better Stack probe удалён из чекапа.
- `L217` — Assertion: 'checkup_betterstack' не входит в KNOWN_BLOCKS.

**tests/test_settings_helpers.py**

- `L163` — Docstring: Better Stack SQL-ключи и journalctl удалены целиком.
- `L186` — D1-гард: legacy checkup-поля отсутствуют как атрибуты Settings.
- `L187` — Docstring D1-гарда: legacy Better Stack и shell-команда удалены.

## 4. Env / README / tools / fixtures

| Файл | Строки | N | kind | owner | disposition | D1? | Назначение |
|---|---|---|---|---|---|---|---|
| .env.example | 56,58-59,61,66-67,69 | 7 | env | global-logging-keep | keep | нет | Пример env глобального logging: LOGTAIL_SOURCE_TOKEN и BETTERSTACK_HOST (не чекап). |
| README.md | 457,686-687,1048,1051,1053-1054,1056 | 8 | readme | global-logging-keep | keep | нет | Пользовательская документация глобального Better Stack logging (токен, host, панель, свой handler). |
| scripts/betterstack_host_token_probe.py | 2,15-16,30,95,122,127-128,130 | 9 | tool | global-logging-keep | keep | нет | Ручной curl-матрикс ingest-контракта BetterStack (host/token, Bearer vs path) для DevOps-диагностики. |
| tests/fixtures/round1025/catalog_baseline.json | 291,556 | 2 | fixture | global-logging-keep | keep | нет | F8-baseline каталога: env-only BETTERSTACK_HOST и LOGTAIL_SOURCE_TOKEN. |
| tests/fixtures/round1025/f8_baseline.json | 89 | 1 | fixture | historical-doc | mark-historical | да | F8-baseline: superseded_by-текст фиксирует санкционированную Δ каталога D1 (удалены 5 ключей + journalctl, добавлены 2 env-only). |
| tools/_selfdiag01_d1_reissue_f8.py | 5-6,8,69-71,73,76 | 8 | tool | d1-tool-historical | mark-historical | да | Одноразовый reissue F8-пинов каталога для D1 (docstring перечисляет удалённые checkup-ключи и Δ каталога). |

**.env.example**

- `L56` — Секция Better Stack Monitoring: SENTRY_DSN (глобальный error-tracking).
- `L58` — Комментарий: BetterStack logs — глобальный handler, пусто = handler не создаётся.
- `L59` — Комментарий: единственное имя токена — LOGTAIL_SOURCE_TOKEN.
- `L61` — Комментарий: ingest POST https://{BETTERSTACK_HOST} + Authorization: Bearer.
- `L66` — Плейсхолдер LOGTAIL_SOURCE_TOKEN (не значение).
- `L67` — Комментарий: US ingest host проекта.
- `L69` — Плейсхолдер BETTERSTACK_HOST (не значение).

**README.md**

- `L457` — Описание модуля «Диагностика»: диагностика и BetterStack — глобальный logging.
- `L686` — Env-таблица: LOGTAIL_SOURCE_TOKEN — глобальный стриминг логов.
- `L687` — Env-таблица: BETTERSTACK_HOST обязателен вместе с токеном.
- `L1048` — Таблица интеграций: Better Stack (свой handler) — глобальный лог.
- `L1051` — Детали BetterStackHandler: батчи, Bearer, счётчики отправки.
- `L1053` — Деталь logging: aiogram.event INFO-спам заглушён, чтобы не лить в панель.
- `L1054` — Инструкция смотреть логи в панели betterstack.com.
- `L1056` — Локальный режим: без Better Stack логи идут в консоль.

**tests/fixtures/round1025/f8_baseline.json**

- `L89` — superseded_by: полная история санкционированных Δ каталога, включая SELF-DIAG-01 D1.

**tools/_selfdiag01_d1_reissue_f8.py**

- `L5` — Docstring: адресное удаление Better Stack ИЗ ЧЕКАПА.
- `L6` — Docstring: список удалённых checkup-ключей и env-only замен.
- `L8` — Docstring: удалены группы models_checkup/keys_betterstack.
- `L69` — SUPERSEDED-текст: −5 checkup-only ключей и journalctl.
- `L70` — SUPERSEDED-текст: удалённые ParamSpec checkup SQL.
- `L71` — SUPERSEDED-текст: удалён CHECKUP_JOURNALCTL_CMD.
- `L73` — SUPERSEDED-текст: удалены группы «Диагностики».
- `L76` — SUPERSEDED-текст: глобальный betterstack_handler.py не затронут.

### 4.1. Прочие docs вне `plans/`

| Файл | Строки | N | kind | owner | disposition | D1? | Назначение |
|---|---|---|---|---|---|---|---|
| UI_AUDIT_REPORT.md | 100 | 1 | docs | historical-doc | mark-historical | нет | Исторический UI-аудит: упоминание betterstack в таблице модулей. |

## 5. `plans/**` — полный перечень (историческое/справочное)

Все строки ниже — `mark-historical`/`keep` для документов; ни один файл не исполняется в runtime. Строки с точечными overrides помечены в §5.1.

| Файл | Строки | N | kind | owner | disposition | D1? | Назначение |
|---|---|---|---|---|---|---|---|
| plans/ARCHITECTURE.md | 119,177,198,200,215,230,250,260,263,265,267,275,277,279,412,418,420,429,476,593-594,774,776,786,796,800,843,845,847,851,869,891,949,955,957,965,2452,3260,3761,3771,3795,4584,4629 | 43 | docs | active-doc | keep | нет | Живой ARCHITECTURE: секции раундов про глобальный Better Stack logging + исторические утверждения о secret=True checkup-ключей. |
| plans/MEMORY.md | 79 | 1 | docs | active-doc | keep | нет | Memory-заметка: root cause 401 BetterStack (ingest-контракт). |
| plans/archive/MEMORY-full-snapshot-2026-10-15.md | 20,46,214,235,251,253,302,305-306,308,362,370,374,385,389,392,395,404-405,411-412,422-425,427,430,474,477,481-482,496,508-509,513,519,522,535,547,1043,1423,1462,1629,1658,1684,1717,1755,2019-2020,2074,2100,2127-2128,2349,2383-2384,2405,2448,2498,2566,2651,2741,2794,2845-2846,2927,2938,2949,2960,2976 | 70 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/admin-ui-bugfixes-round107/tasks.md | 413,421 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/agentic-events-graph-round1026/review-T-3702.md | 79,112 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/agentic-verification-round1026/adr-1026-23-verification-gate.md | 23 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/agentic-verification-round1026/evidence.md | 61 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/agentic-verification-round1026/spec.md | 268 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/agentic-verification-round1026/tasks.md | 264,329 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap-4-1-durable-whole-window-summary-round1031/evidence.md | 1058 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap-4-1-durable-whole-window-summary-round1031/review.md | 80,82,363,421 | 4 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap-4-embedding-graphrag-cover-runtime-round1030/review.md | 511 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap5-final-fixes-round1049/deployment.md | 72 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap5-final-fixes-round1049/full_pytest_t5274.log | 53,55,226 | 3 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap5-final-fixes-round1049/startup_prod_p0_42f8963.log | 9 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap5-final-fixes-round1049/startup_prod_t5273.log | 9 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/asap5-final-fixes-round1049/startup_prod_t5274.log | 9 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/backlog-history-2026-10-15.md | 166,334,369,699,715,717,1168,1185,1188,1237,1258,1288,1301,1311,1372,1383,1396,1466-1469,1503,1524,1561,1576,2412,2763,2780,2836,3056,3189,3191,3193,3195,3197,3211,3213 | 37 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-ingest-bearer-contract/adr-1019-1-ingest-bearer-contract.md | 1,5,8,12-14,16,25,40,47,52,57-58,66,68-70 | 17 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-ingest-bearer-contract/spec.md | 1,3,11,13,19-24,26-28,32,47-50,52,88-89,97,99,107-109,113,120,129,137,148 | 31 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-ingest-bearer-contract/tasks.md | 1,6-7,13,18,23-27,29-31,36,50,53,73-74,80,92,102 | 21 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-lore-prompts-round5/spec.md | 1,3,6,8,20,33,42,44-45,78,82,87,96-97,99,105,108-109,111,114-116,123-125,127-128,130,140-141,153,396,409,413,444,465-466,469,489,498,508,548,551,554 | 44 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-lore-prompts-round5/tasks.md | 1,3,5,20,24,26,28-31,52,58-59 | 13 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-own-handler-video-memory-cmds/spec.md | 1,3,9,25,38,46,53,55-57,59,94,101,103,105,107,110-111,130,147,149,154-155,157-158,167-168,170,173,175,177,180-182,187,514-516,535,556,558,564-565,568,599,606,618,622,630-631 | 50 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-own-handler-video-memory-cmds/tasks.md | 1,5,19,21,23,25,27,73 | 8 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-us-region-401/adr-1018-1-betterstack-host-token.md | 1,3,10,12,14,16-17,22-24,26,30-31,38-39,41,52-53,60,68,78,81,83,91,97,99,101 | 27 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-us-region-401/spec.md | 1,4,7,11,13,15,21-24,26-29,33-35,42,45,58-59,61-63,65,68,72-76,79,86,96,110-111,113-114,117,122,127-128,134-135,143,145,148,152-155 | 51 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/betterstack-us-region-401/tasks.md | 1,4,7-9,14,17,19,24-26,36,61,67-71,81,89 | 20 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/core-llm-error-fixes-round1024/ADR-1024-6.md | 39 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/direct-sandbox-budget-investigation/spec.md | 153 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/direct-sandbox-budget-investigation/tasks.md | 89 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/features/asap6-current-task-closure/review-final-w2w3.md | 84 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/features/asap7-cognitive-direct-pipeline/sweep-fix-report.md | 12,33-34,40,109 | 5 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/features/mca-20-temporal-factcheck/startup_prod_t5150r.log | 44 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/features/mca-21-guides/evidence.md | 80 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/features/mca-21-guides/report.md | 69 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/features/mca-21-guides/review.md | 68 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/features/mca-asap-summary-hotfix/deployment.md | 26 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/frontend-llm-providers-layout/spec.md | 17 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/frontend-llm-providers-layout/tasks.md | 13,15,29-30 | 4 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/graph-physics-stabilization/tasks.md | 8 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/history-import-hybrid-memory/tasks.md | 3 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/hotfix7-shell-glass-heartbeat-round1025/deployment.md | 74 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/ia-shell-navigation-round1025/tasks.md | 127 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/logging-infra-round1024/ADR-1024-1.md | 51 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-12-miniapp-stories-round1046/startup_prod_t5174.log | 70,273 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-17c-analytics-matrix-round1047/deployment.md | 32 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-17c-analytics-matrix-round1047/startup_prod_t5198.log | 69,273 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-asap31-auto-budgets-capacity-react-round1028/evidence.md | 19 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-asap31-auto-budgets-capacity-react-round1028/review.md | 168,193 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-release-round1048/deployment.md | 42 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-release-round1048/evidence_lane_b.md | 58-59 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-release-round1048/release_report.md | 49,108 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/mca-release-round1048/startup_prod_t5216.log | 40,247 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/metafact-penalty-extractor-prompt/tasks.md | 8 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/metrics-2026-10-15.md | 20-21,71,87,152,187,234,286,362,364,374,376,378,390,399,413,1618,1630,1721,1733,1745,1747 | 22 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/post-asap4-corrective-pass-round1030/evidence.md | 72 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/providers-kostik-round1012/tasks.md | 345 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/audit_backlog.md | 676,700,708,711,714-715,725,751,1041,1358 | 10 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/full_audit_results.md | 90,183,1144,1456,1671,1820,1831,1833-1834,1839,1845,1865,2506,2509 | 14 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/global_map.md | 311,317,324,331,338,701,703,715,746,788,790,793-796,1093,1126,1360,1376 | 19 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round10.12_scanner_audit.md | 97 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round10.18_scanner_audit.md | 6,8,43,45,64,66-68,72,130,132-133,135,181,184,214,486 | 17 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round10.19_scanner_audit.md | 5,10,19,57,59,106,152,171-172,196,615,675 | 12 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round10.6_scanner_audit.md | 52,145 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1020_ui_rework_reviewer.md | 16,30,130,158,161 | 5 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1023_f5_reviewer.md | 15,22,24,176,191 | 5 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1024_f11_reviewer.md | 208 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1024_f12_reviewer.md | 13,25 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1024_f1_reviewer.md | 20,33 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1024_f2_reviewer.md | 100 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1025_f9_secrets_checklist.md | 30-31,45 | 3 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1025_hotfix_scanner_audit.md | 67 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1026_a10_acceptance.md | 135,163 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/reports/round1026_epic3_aggregate_review.md | 188 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/role-matrix-settings-actualization/adr-1018-6-role-matrix-actualization.md | 38 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/role-matrix-settings-actualization/spec.md | 100,151 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/role-matrix-settings-actualization/tasks.md | 8 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/round1020-ui-rework/adr/ui-rework-1020.md | 10,44-45 | 3 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/round1020-ui-rework/spec.md | 120,125-126,147,285,304,319,330,345,359 | 10 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/round1020-ui-rework/tasks.md | 30,43,63,86,129,195,235 | 7 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/round1020-ui-rework/ui-contract.md | 70 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/secrets-and-save-states-round1025/spec.md | 57 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/settings-persistence-audit-round1014/inventory.tsv | 71-75 | 5 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/settings-worker-sync/spec.md | 215,217 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/settings-worker-sync/tasks.md | 65 | 1 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/sleep-manual-cascade-badges/tasks.md | 177,196 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/tma-ia-modules-rework/design-project.md | 293-294,327,331,347,362,493,499,591,594,787,791,806,853 | 14 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/tma-ia-modules-rework/spec.md | 11,171,208-209,229,287,352,388,400,500-501,505,507-508,548,572,598,601 | 18 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/tma-ia-modules-rework/tasks.md | 113,146,378,409,518,529,552,568,570,617 | 10 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/tma-relume-redesign/design-project.md | 357,1580,1681,2161,2244 | 5 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/tma-relume-redesign/tasks.md | 553,1248,1339 | 3 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/tool-coordinator-round1026/deployment.md | 43,109 | 2 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/video-multimodal-pipeline-and-incidents/spec.md | 1,13,24,73,75-76,431,438,441,444-446,448,455,457,465-466,488,511-512,535-537,542,570,574,576 | 27 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/archive/video-multimodal-pipeline-and-incidents/tasks.md | 3,15,47,49,51,57,59 | 7 | docs | historical-doc | mark-historical | нет | Архивный план/отчёт/лог исторического раунда: Better Stack упоминается в историческом контексте, не исполняется. |
| plans/backlog.md | 162,283,310 | 3 | docs | active-doc | keep | нет | Активный backlog: записи о средофлейке test_betterstack_handler (глобальный logging). |
| plans/docs/canon/architecture.md | 23 | 1 | docs | canon-doc | keep | нет | Канон промптов/бэклога: дословный CHECKUP_SYSTEM_PROMPT (фраза «Betterstack или локальные»). |
| plans/docs/canon/backlog.md | 56 | 1 | docs | canon-doc | keep | нет | Канон промптов/бэклога: дословный CHECKUP_SYSTEM_PROMPT (фраза «Betterstack или локальные»). |
| plans/docs/memory-import-research.md | 162 | 1 | docs | reference-doc | keep | нет | Справочный/сгенерированный документ (registry/screen-map/audit/memory): исторические снимки каталога, включая env-only и старые prod-значения. |
| plans/docs/memory-project-overview.md | 19,62,64,66,71-72,74,76-78,86-87,89,91-93,99-100,105,127 | 20 | docs | reference-doc | keep | нет | Справочный/сгенерированный документ (registry/screen-map/audit/memory): исторические снимки каталога, включая env-only и старые prod-значения. |
| plans/docs/multi-chat-scaling-research.md | 84 | 1 | docs | reference-doc | keep | нет | Справочный/сгенерированный документ (registry/screen-map/audit/memory): исторические снимки каталога, включая env-only и старые prod-значения. |
| plans/docs/param-registry-round1025.meta.md | 28,187 | 2 | docs | reference-doc | keep | нет | Справочный/сгенерированный документ (registry/screen-map/audit/memory): исторические снимки каталога, включая env-only и старые prod-значения. |
| plans/docs/param-registry-round1025.tsv | 3,430 | 2 | docs | reference-doc | keep | нет | Справочный/сгенерированный документ (registry/screen-map/audit/memory): исторические снимки каталога, включая env-only и старые prod-значения. |
| plans/docs/prod-params-audit-2026-09.md | 326-328,360 | 4 | docs | reference-doc | keep | нет | Справочный/сгенерированный документ (registry/screen-map/audit/memory): исторические снимки каталога, включая env-only и старые prod-значения. |
| plans/docs/screen-map-round1025.md | 10,437 | 2 | docs | reference-doc | keep | нет | Справочный/сгенерированный документ (registry/screen-map/audit/memory): исторические снимки каталога, включая env-only и старые prod-значения. |
| plans/features/_audit-2026-10-23/summary-triage/raw/silent_death_probe.txt | 16,30,57,71,98,111,122 | 7 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/add-exp/evidence/f4/harness/accept97_base.py | 319-329 | 11 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/add-exp/evidence/release-25896/acceptance/harness/accept96_base.py | 318-328 | 11 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/add-exp/evidence/unified-core/trace-checkup-chat-command.txt | 7,55 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/add-exp/evidence/unified-core/trace-internal-checkup-tool-loop.txt | 7 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_exit_diagnosis.txt | 7,13 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_exit_fullstack_after_output.txt | 1,297 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_exit_fullstack_before_output.txt | 1,298 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_exit_probe_child_exit.py | 7 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_exit_probe_full_stack.py | 7,88,110-111,114,116-117 | 7 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_exit_regression_surface.txt | 1 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/_shutdown_sigterm_demo.py | 85 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/incident-summary-01/main.txt | 1146,6676 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/evidence/release-25883/pytest_source_pins.txt | 75-76 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/asap8-v6-3-live-correction/final-audit-current-task.md | 89 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/asap8-v6-3-live-correction/incident-summary-01-shutdown-report.md | 116,206,281 | 3 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/asap8-v6-3-live-correction/release-25882-report.md | 41,76,82-83 | 4 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/asap8-v6-3-live-correction/release-25883-report.md | 45 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/asap8-v6-3-live-correction/review-incident-summary-01.md | 211-212,264,272 | 4 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/asap8-v6-3-live-correction/w1-reports/W1-REPIN.md | 91 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/cfg/evidence/cfg-03/inventory-baseline.tsv | 21,81-85,88,284 | 8 | docs | historical-evidence | mark-historical | да | CFG-03 inventory: исходная каталогизация checkup Better Stack SQL-ключей (key/pg_key/secret, без значений). |
| plans/features/cfg/evidence/cfg-03/inventory.json | 776-778,792,802,3184-3187,3192,3198,3200,3225-3228,3233,3239,3241,3267-3268,3275,3281,3283,3308-3311,3316,3322,3324,3349-3352,3357,3363,3365,3478-3479,3492,3494,11725-11727,11741,11751-11752 | 48 | docs | historical-evidence | mark-historical | да | CFG-03 inventory: исходная каталогизация checkup Better Stack SQL-ключей (key/pg_key/secret, без значений). |
| plans/features/cfg/evidence/cfg-03/inventory.tsv | 21,81-85,88,287 | 8 | docs | historical-evidence | mark-historical | да | CFG-03 inventory: исходная каталогизация checkup Better Stack SQL-ключей (key/pg_key/secret, без значений). |
| plans/features/cfg/evidence/cfg-07a/07a1-audit.md | 58-59 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/cfg/evidence/cfg-07a/07a1-corpus.json | 65 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/cfg/evidence/cfg-07a/07a1-corpus.md | 90 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/cfg/evidence/cfg-07a/07a2-summary.md | 46 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/cfg/evidence/release-25897/cleanup/authorship-audit.json | 425,435 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/cfg/evidence/release-25897/cleanup/authorship-audit.md | 82-83 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/cfg/evidence/release-25897/deploy/journal97-tail.txt | 136 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/cfg/requirements-map.json | 9249 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/embed-identity-compat/evidence/fix-b1b3.md | 159 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/embed-identity-compat/review-r2.md | 77 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/evol/audit/w13-evidence-routing.md | 225 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/evol/slice-graph.json | 156 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/memory-cognitive-02/reports/deploy-2.58.170.md | 22,96-99 | 5 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-corrective-factcheck-speech/arch-checkup-transfer.md | 32,69 | 2 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/p0-corrective-factcheck-speech/arch-design.md | 140 | 1 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/p0-corrective-factcheck-speech/evidence/canary/raw/report.json | 191,204,206 | 3 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-corrective-factcheck-speech/evidence/canary/report.md | 13,48,56 | 3 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-corrective-factcheck-speech/evidence/checkup-core.md | 96 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-corrective-factcheck-speech/evidence/forensic.md | 176,186,194,225 | 4 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-corrective-factcheck-speech/evidence/withheld/raw/classification.json | 161,165 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-corrective-factcheck-speech/evidence/withheld/texts/checkup.base.system.txt | 2 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-corrective-factcheck-speech/requirements-map.json | 2381,2405,2429,2453,3170,3175,3183,3207,3830,3835,3843,4166,4171,4179,4187,4328,4333,4341,11912,12000,12024,12048,12072,12096 | 24 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/p0-corrective-factcheck-speech/slice-graph.json | 360,499 | 2 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/p0-corrective-factcheck-speech/source-2026-10-24.md | 483,572,676,694,739,775 | 6 | docs | historical-doc | mark-historical | нет | Map/spec/plan прошлого эпика: Better Stack в историческом или смежном контексте. |
| plans/features/p0-delta-analysis/evidence/impl.md | 148 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-delta-analysis/evidence/review-delta.md | 66 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-nostalgia-rework/evidence/w1.md | 194 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25891/acceptance/cleanup-register.json | 41,49 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25891/acceptance/harness/accept91_live.py | 307-317 | 11 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25891/acceptance/scenario-1-coldstart.json | 97,109,117,122 | 4 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25891/acceptance/scenario-1-retry.json | 42,72 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25891/acceptance/summary.json | 83,91 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25892/acceptance/harness/accept92_base.py | 307-317 | 11 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25894/acceptance/harness/accept94_base.py | 316-326 | 11 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/p0-vision-universal/evidence/release-25895/acceptance/harness/accept95_base.py | 322-332 | 11 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/release-then-migrate/evidence/inventory-old-vps.md | 139-140 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/release-then-migrate/evidence/prep-git-new-vps.md | 119 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/release-then-migrate/evidence/sync-preflight.md | 69 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/mobile-prompts/_r3_config-payload-after.json | 1 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/mobile-prompts/_r3r_config-payload-red.json | 1 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/mobile-prompts/config-payload-before.json | 1 | 1 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/release-soul-25886/diag-first-attempt-boot-window.txt | 58,67 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/release-soul-25886/fixture-committed-stale.json | 2379,3944 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/release-soul-25886/fixture-regenerated-by-dump-script.json | 2672,4237 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/soul-release/payload-verification/stand-output.json | 2595,2613 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/soul-release/postfix/stand-output.json | 2566,2584 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/w1/backup-speech-config.json | 211,221,227,233 | 4 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/features/soul-1/evidence/w6/api-fixture.json | 2379,3944 | 2 | docs | historical-evidence | mark-historical | нет | Историческое evidence/harness прошлого релиза; снимок на момент эпика, на текущем SHA не исполняется. |
| plans/progress_scope.json | 176 | 1 | docs | active-doc | keep | нет | Леджер: длинная source_note прошлого P0-среза с историческим упоминанием Betterstack. |

### 5.1. Точечные пояснения по документам


**plans/ARCHITECTURE.md**

- `L119` — ТЕКУЩАЯ сводная таблица §6 (не исторический раунд) устарела: «Checkup = Betterstack → journalctl fallback». После D1 — портируемый локальный backend (systemd/container/standalone). Требуется однострочная правка в doc-касании (BACKLOG D1-DOC-1); на runtime/acceptance не влияет. (owner=active-doc-stale)
- `L215` — Секция «Провайдеры и системы»: глобальный Better Stack (свой handler) — keep.
- `L949` — Round1025 narrative: «оба Betterstack-ключа остаются secret=True» — на момент раунда; D1 это supersede-ит.
- `L955` — Round1025 narrative: каталог-Δ=0, оба Betterstack-поля secret=True (историческое утверждение).
- `L965` — Скриншот-приёмка round1025: маска Betterstack в UI (историческая).
- `L2452` — Секрет-чеклист round1025: группа keys_betterstack среди 20 UI-секретов (исторический перечень).

**plans/docs/canon/architecture.md**

- `L23` — Канон CHECKUP_SYSTEM_PROMPT: «логи (Betterstack или локальные)».

**plans/docs/canon/backlog.md**

- `L56` — Канон R42-6: дословный CHECKUP_SYSTEM_PROMPT с той же фразой.

**plans/docs/memory-project-overview.md**

- `L19` — Memory overview: мониторинг Sentry/Better Stack/journald.

**plans/docs/multi-chat-scaling-research.md**

- `L84` — Research: алерт в status_service/Betterstack (глобальный logging).

**plans/docs/param-registry-round1025.meta.md**

- `L28` — Registry meta: betterstack_host.
- `L187` — Registry meta: logtail_source_token.

**plans/docs/param-registry-round1025.tsv**

- `L3` — Registry TSV: betterstack_host env-only.
- `L430` — Registry TSV: logtail_source_token env-only secret.

**plans/docs/prod-params-audit-2026-09.md**

- `L326` — Audit 2026-09: фактическое prod-значение models.checkup_betterstack_sql_host (не секрет; историческая запись).
- `L327` — Audit 2026-09: models.checkup_betterstack_sql_query было пустым.
- `L328` — Audit 2026-09: models.checkup_betterstack_sql_table (имя таблицы, не секрет).
- `L360` — Audit 2026-09: перечень пустых строк, включая query.

**plans/docs/screen-map-round1025.md**

- `L10` — Screen-map: betterstack_host — env-only, вне UI.
- `L437` — Screen-map: logtail_source_token — env-only secret.

**plans/features/memory-cognitive-02/reports/deploy-2.58.170.md**

- `L22` — Deploy-отчёт: SELF-DIAG-01 D1 (локальный backend логов чекапа) в поезде 2.58.170 — evidence линии D1. (owner=historical-evidence; D1=да)
- `L97` — Наблюдение деплоя: единственные упоминания Better Stack в журнале — глобальный ingest (D1-свойство подтверждено live-наблюдением). (owner=historical-evidence; D1=да)

## 6. docs-line-only: пакет D1 на master (отсутствует на 25876167)

| Файл | Строки | N | owner | disposition | D1? | Примечание |
|---|---|---|---|---|---|---|
| plans/current_task.md | 9513,9525,9648,9652,9660,9662,9666-9668,9672,9849,9903,9927,9963,9965,9996 | 16 | user-owned-doc | keep | да | пользовательский ТЗ (read-only, untracked) |
| plans/features/self-diag-01/d0-discovery.md | 16,18,56 | 3 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/cleanup-2026-11-12/cleanup-2026-11-12.md | 28-32,34-35,40,42,54,57,61,72-76,84-88,95,114 | 24 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/cleanup-2026-11-12/cleanup-report.txt | 6,9,14-19,22-26,28,32,35-39,50-54 | 25 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/cleanup-2026-11-12/scripts/remote_cleanup.py | 29-33,36-37,94,156-157,221,264-266,268,274,278-279,307,309,390-391 | 22 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/cleanup-2026-11-12/scripts/verify_post.sh | 15-17 | 3 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/d1-evidence-c134f93d.md | 27,48-49,56,72,76,78,80,91-95,97-98 | 15 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/d1-probe-c134f93d.txt | 26,31,40,43,45,47,63,118-120,164-166 | 13 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/sd1_d1_07.json | 9-10 | 2 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/sd1_d1_10.json | 10 | 1 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/sd1_d1_11.json | 9 | 1 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/sd1_d1_13.json | 9-10 | 2 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/sd1_d1_14.json | 10 | 1 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/evidence/d1/sd1_d1_17.json | 9 | 1 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/plan.md | 65,69,122 | 3 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/reports/deploy-2.58.188.md | 127,131 | 2 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/reports/pm-d2-rebind-2.58.188.md | 92 | 1 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |
| plans/features/self-diag-01/requirements-map.json | 95,117,122,1285 | 4 | d1-evidence | keep | да | пакет D1; на 25876167 отсутствует |

Важно: `plans/features/self-diag-01/**` и `plans/current_task.md` **не
существуют** в дереве `25876167` (проверено `git ls-tree`), поэтому в
per-occurrence JSON они вынесены в отдельную секцию `docs_line_only`.
Пакет живёт в docs-линии master: `522e2728` (D1 evidence), `6691ef7e`
(cleanup 5 строк), `e618451f` (state). Инвентарь на 25876167 их не
содержит и не должен.

## 7. Persisted-строки `bot_settings` (не файлы)

На момент ревью (review-d1-2026-11-12) на production 2.58.197 оставались
5 осиротевших строк; **на момент этого инвентаря они уже удалены**
(см. §8). Инвентарь фиксирует их как объект D1-10/14/AC-08:

| Ключ | Длина | Секрет | Потребитель | Выдача `/api/config` |
|---|---|---|---|---|
| `keys.checkup_betterstack_sql_password` | 66 | да | нет (`get_by_pg_key` → None) | `{configured,last4}` только global admin |
| `keys.checkup_betterstack_sql_user` | 35 | да | нет | `{configured,last4}` только global admin |
| `models.checkup_betterstack_sql_host` | 40 | нет | нет | raw (категория models, не secret) |
| `models.checkup_betterstack_sql_query` | 2 | нет | нет | raw |
| `models.checkup_betterstack_sql_table` | 20 | нет | нет | raw |

Источник значений/длин — `d1-probe-c134f93d.txt` и review; этот скан
значения не читал.

## 8. Что уже сделано с persisted-строками (состояние на момент среза)

Делегированный бриф описывал состояние **до** cleanup. Фактически DevOps уже
выполнил targeted cleanup:

- commit **`6691ef7e`** `docs(self-diag): D1 cleanup of 5 orphaned Better Stack keys (backup outside repo, verified)`;
- артефакт: `plans/features/self-diag-01/evidence/d1/cleanup-2026-11-12/`;
- pre-count 5 → одна транзакция `DELETE ... WHERE key IN (5) RETURNING key` → 5;
- backup вне репозитория (локальная копия существует, sha256
  `706b61f3…8dd969`, 1327 б, ровно 5 ключей; значения не печатались);
- после одного рестарта: БД `count=0`, `GET /api/config` 623→**618** items,
  matched **0**, `/healthz` ok v2.58.197, новых ошибок нет.

Локальный focused-пробник на 25876167 (без БД/сети) подтвердил механизм:
`ConfigCache.get_all()` отдаёт 5 ключей при старом RAM-снапшоте и 0 — после
перезагрузки; синтетика каталога их не воссоздаёт. Поэтому удаление
достаточно только вместе с рестартом (что и было сделано).

Мой бриф утверждал «5 строк остаются» — это состояние **до** `6691ef7e`.
Никакой повторный DELETE не нужен и не выполнялся. План/факт и
re-verification checklist — в `d1-cleanup-plan.md`.

## 9. Проверка «известных пропущенных» записей из ревью


- **tests/js/routing_test.js** — found=`true`; строки 1285,1291,1299. фикстура-метка удалённого ключа; BACKLOG B-4 (переименовать)
- **tests/test_round106_ia_smoke.py** — found=`true`; строки 32,216-217. KNOWN_BLOCKS + env-only счётчик
- **old harness files with CHECKUP_JOURNALCTL_CMD** — found=`true`; `plans/features/p0-vision-universal/evidence/release-25891/acceptance/harness/accept91_live.py`; `plans/features/p0-vision-universal/evidence/release-25892/acceptance/harness/accept92_base.py`; `plans/features/p0-vision-universal/evidence/release-25894/acceptance/harness/accept94_base.py`; `plans/features/p0-vision-universal/evidence/release-25895/acceptance/harness/accept95_base.py`; `plans/features/add-exp/evidence/release-25896/acceptance/harness/accept96_base.py`; `plans/features/add-exp/evidence/f4/harness/accept97_base.py`. исторические снимки; на 25876167 settings-поля нет → файл не исполним, хранить как lineage
- **plans/features/cfg/evidence/cfg-03/*** — found=`true`; `plans/features/cfg/evidence/cfg-03/inventory.json`; `plans/features/cfg/evidence/cfg-03/inventory.tsv`; `plans/features/cfg/evidence/cfg-03/inventory-baseline.tsv`. исходная каталогизация 5 ключей; значения секретов отсутствуют
- **tools/_selfdiag01_d1_reissue_f8.py** — found=`true`; строки 5-6,8,69-71,73,76. одноразовый reissue; runtime-потребителей нет
- **.env.example / README** — found=`true`; `.env.example`; `README.md`. только глобальный logging (LOGTAIL_SOURCE_TOKEN/BETTERSTACK_HOST)
- **dead ids web/app.js:192-193** — found=`true`; строки 192-193. плюс комментарий-зеркало строка 92; BACKLOG B-1
- **services/betterstack_handler.py** — found=`true`; строки 1,3-5,17,23,29,62,69,139,150-151,171,178-179,192,216,223,229,249,275,279,326,362. глобальный logging — keep
- **services/external_log.py** — found=`true`; строки 242. глобальный logging — keep
- **BETTERSTACK_HOST env** — found=`true`; `.env.example`; `README.md`; `services/param_catalog.py`; `scripts/betterstack_host_token_probe.py`; `bot.py`; `plans/docs/param-registry-round1025.tsv`; `plans/docs/screen-map-round1025.md`; `tests/fixtures/round1025/catalog_baseline.json`. env-only глобального logging; не чекап
- **keys_betterstack global UI group** — found=`true`; `web/app.js`; `tests/test_frontend_tab_mapping.py`; `tests/test_checkup_logs_fetcher.py`; `plans/features/cfg/evidence/cfg-03/inventory.json`. в каталоге группы нет; UI-источник мёртв (BACKLOG B-1)

Дополнительно найдено (не было в списке ревью): `plans/docs/canon/architecture.md`
и `plans/docs/canon/backlog.md` (дословный CHECKUP_SYSTEM_PROMPT с фразой
«Betterstack или локальные»), `plans/docs/prod-params-audit-2026-09.md`
(исторические не-секретные значения 3 `models.checkup_betterstack_sql_*`),
`plans/features/soul-1/evidence/mobile-prompts/*.json` (снимки `/api/config` с
маскированным `{configured,last4}`), `plans/features/release-then-migrate/evidence/inventory-old-vps.md`
(только имена env, без значений), 6 харнесс-снимков с `CHECKUP_JOURNALCTL_CMD`.

## 10. Исправления к предыдущим утверждениям evidence

1. **«`CHECKUP_JOURNALCTL_CMD` — 0 вхождений во всём репозитории»** —
   неверно. На 25876167: **19 файлов / 26 строк** (регистронезависимо;
   включает `tests/test_settings_helpers.py`, `tests/test_checkup_logs_fetcher.py`,
   `tests/test_param_catalog.py`, `tests/test_round1025_f8_registry.py`,
   `tests/fixtures/round1025/f8_baseline.json`, `tools/_selfdiag01_d1_reissue_f8.py`,
   `plans/features/cfg/evidence/cfg-03/*`, 6 harness-снимков,
   `plans/archive/tma-ia-modules-rework/design-project.md`,
   3 снимка `/api/config` soul-1). Правильная формулировка: **0 атрибутов
   Settings и 0 runtime-потребителей**; исторические/тестовые упоминания
   остаются.
2. **`web/app.js`** — мёртвых id два: строки **192 и 193** (плюс
   комментарий-зеркало 92), а не только 193.
3. **Cleanup-отчёт DevOps** «упоминания остались в 16 файлах» — неточно:
   `checkup_betterstack_sql` встречается в **37** файлах, полный набор
   шаблонов — в **231** файле. На решение об удалении это не влияло:
   runtime-scope grep действительно дал 0.
4. **8/8 vs 5/8** (F-3) — вне этого инвентаря; перепривязку делает PM.
   Инвентарь сам по себе привязан к `25876167`.
5. **`plans/ARCHITECTURE.md:119`** — текущая (не историческая) таблица §6
   всё ещё говорит «Checkup = Betterstack → journalctl fallback». Это
   doc-drift, не runtime; BACKLOG D1-DOC-1.

## 11. Находки и классификация

**IN_SCOPE (закрыто этим артефактом):**
- D1-07: полный per-occurrence инвентарь на 25876167 (этот файл + JSON).
- Подтверждение отсутствия runtime-потребителей и точного набора
  исторических/тестовых вхождений.

**IN_SCOPE (данные, уже исполнено DevOps):**
- D1-10/D1-14/AC-08 — 5 строк удалены targeted-транзакцией с backup и
  post-verification (`6691ef7e`); повторно не выполнять.

**CRITICAL_OUT_OF_SCOPE:** нет. Секрет был in-scope D1-10/14 и удалён;
бэкап лежит вне репозитория с ограниченными правами. В файлах, содержащих
имя ключа, литеральных значений секрета не найдено: только имена, длины и
маски `{configured,last4:"0000"}` в исторических фикстурах (точечный скан
без печати значений).

**BACKLOG_ONLY (не блокирует D1):**
- **B-1** `web/app.js:92,192,193` — удалить мёртвые id; требует правки
  `tests/js/round1025_f5_workspace_route_test.js:365` (g2 использует
  `models_checkup` как фикстуру).
- **B-4** `tests/js/routing_test.js:1285,1291,1299` — переименовать
  синтетическую метку удалённого ключа.
- **D1-DOC-1** `plans/ARCHITECTURE.md:119` — обновить current-state строку
  Checkup (портируемый локальный backend вместо Betterstack→journalctl).
- **D1-DOC-2** `services/checkup_prompts.py:51,72,99,129` + канон
  `plans/docs/canon/*` — фраза «логи (Betterstack или локальные)» устарела;
  правка требует prompt-versioning и не входит в D1-closure.
- **D1-DOC-3** исторические harness-снимки (6 файлов) вызывают
  `settings.CHECKUP_JOURNALCTL_CMD`; на 25876167 поле удалено → при
  исполнении упадут. Хранить как lineage, не исполнять.
- **D1-DOC-4** `tools/_selfdiag01_d1_reissue_f8.py` — одноразовый reissue,
  runtime-потребителей нет; удалить при уборке tools.

## 12. Что этот инвентарь не доказывает

- Не доказывает runtime-поведение: это статический скан. Live-доказательства
  D1 (journalctl/invocation, 0 сетевых вызовов) остаются в
  `d1-evidence-c134f93d.md` / probe.
- Не перечитывает production-БД: состояние после cleanup взято из
  `6691ef7e`/`cleanup-2026-11-12` (DevOps), а не из нового подключения.
  Read-only re-check остаётся за Reviewer/DevOps.
- Не заменяет rebind evidence (F-3) и map/gate — это PM.
- Пространственные варианты ограничены перечисленными шаблонами; другие
  написания (например, транслитерации вне `беттерстак`) не сканировались.
