# MOD-ACL-UX-01 · M1-B — единый предикат «глобальный админ», границы доступа и секретов

**База (деплой):** `a64ecb89b0a5930bb37e9a6e73931174f7a8e7ba` — 2.58.250, ветка
`release/ur-gb-2.58.250`. Работа — в отдельном worktree
`WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-ux-01-1e46be007668-ed629f84`,
ветка `feat/mod-acl-m1b` (не от `master`: master `b371d583a`/`ddc66d995` не
содержат выкаченного ACL-кода).

**Метод.** Сначала — воспроизведение дефекта поведением на базе (RED-лог
`red-base-pytest.txt`), затем минимальная правка, затем тот же набор тестов
(GREEN). Продуктовый код вне назначенной области записи не менялся:
`git diff --name-only -- web/ services/roles.py services/direct_chat_service.py`
пуст, блоб `web/api/deps.py` совпадает с базой
(`509b387d4894dda8575b6d36ab307e6fbb2a848c` в обоих случаях).

## Что именно было неверно на `a64ecb89b`

| Проверка | Факт базы |
|---|---|
| `services/chat_access.is_admin` | `telegram_id == ADMIN_USER_ID` **или** строка роли `admin` |
| `web/api/deps.user_is_global_admin` | `wildcard` **или** `role_type == "global_admin"` **или** строка роли `admin` |
| Следствие | глобальный админ Mini App (`role_type=global_admin` / wildcard) в чате — `user` |
| Потребители | `direct_chat_service` `privilege(...) == "user"` (2 места), `mca_style_scope._has_chat_admin_rights` → `style_request_denied` |

RED на базе (23 теста нового файла: 15 упали, 12 прошли — прошедшие
фиксируют уже корректное поведение): `red-base-pytest.txt`
(`15 failed, 12 passed`).

## MAC-S4-174 — HTTP, фоновые задачи и tool calls говорят одной семантикой

**Реализовано.** В `services/chat_access.py` введён
`is_global_admin(telegram_id)` — единственный ответ бот-стороны на вопрос
«глобальный админ». Правило не переписано: решение принимает существующая
канонная функция `services.roles.is_effective_global_admin_role(role_name,
role_data)` (её docstring прямо фиксирует «ровно канон
`web.api.deps.user_is_global_admin`»), т.е. разбор ролей (`role_type`,
legacy-имя, wildcard) в `chat_access` не дублируется. `is_admin` = этот канон
**или** `settings.ADMIN_USER_ID` — единственное намеренное расширение
бот-стороны (фолбэк R6: без PG/кэша владелец сохраняет админку в чате). В
`web/api/deps` такого клауза нет и не появилось — поведение админки
байт-в-байт прежнее.

**Доказательства.** `tests/test_mod_acl_ux_01_m1_predicate.py::TestPredicateParity`
— матрица из 7 форм роли на ОДНОМ живом снимке `ConfigCache(pg=None)`:
`chat_access.is_global_admin(tid) is deps.user_is_global_admin(cache, tid)`
для `role_type=global_admin` (прав нет, имя не `admin`), wildcard-custom,
legacy `admin`, custom с секцией `access`, `moderator`, `user`, отсутствующего
id. На базе падают ровно две строки, задающие дефект (RED-лог). Плюс
`test_owner_shortcut_is_bot_only_and_documented` — асимметрия `ADMIN_USER_ID`
зафиксирована обеими сторонами явно, чтобы не разрасталась молча;
`test_no_cache_is_fail_closed` и `test_broken_cache_does_not_raise` —
горячий путь бота не бросает и не открывает доступ при сбое кэша.

**Потребители.** `TestConsumers`: `privilege(global_admin) == "admin"`,
`is_moderator(global_admin) is True`, `mca_style_scope._has_chat_admin_rights`
для глобального админа `True` (на базе `False`), для обычного юзера `False`
(модель не ослаблена). `direct_chat_service` (`privilege` в 2 местах) — тот же
предикат, отдельного теста модуля не добавлено: импорт 17k-строчного сервиса
в unit-тест тянет весь бот, а ветвление там ровно по `privilege(...)`.

**Остаточное (честно).** `web/api/deps.py` по-прежнему записывает те же три
клауза сам — свести его к вызову `chat_access.is_global_admin` нельзя в
назначенной области записи (`web/api/*` исключён). Паритет сегодня
удерживается тестом, а не общим импортом; вывод `deps.user_is_global_admin` на
канон — однострочная правка в `web/api/*`, которую нужно взять отдельным
инкрементом. Websocket/SSE на этой сборке отсутствует (аудит 2.58.180 §2 —
только polling), поэтому эта часть acceptance неприменима к 2.58.250, а не
«проверена».

## MAC-S4-172 — ключи/токены не выходят наружу

**Уже корректно на `a64cb89b`, теперь заперто тестом (не изменением).**
`TestSecretsDoNotLeave`:
* посаженный литеральный секрет (`M1B-LITERAL-PLANT-9f3c1d`, без
  `sk-`/Bearer/URI-шаблона) и префиксный (`sk-m1bplanted0123456789`) не
  появляются в **отданных байтах** `GET /api/status/logs` (запрос от обычного
  пользователя — худший случай);
* положительный контроль: до маскировки оба секрета в записи присутствуют
  (`raw` содержит их), т.е. отсутствие в ответе — не пустой ответ;
* контроль чувствительности: без литерала каталога тот же литеральный секрет
  **не** маскируется (`sanitize(s) == s`), значит его исчезновение даёт именно
  литеральное правило маскировки, а не общий регэксп;
* `SecretMaskFilter` (продовый фильтр консоли/journald) маскирует саму запись
  до форматирования, безопасный маркер остаётся;
* без сессии журнал не отдаётся вовсе (401), т.е. пустой ответ не выдаётся за
  «секретов нет».

Прочие пути ответов (маскирование `/api/config`, `/api/status`,
`/api/debug/config`, маска ключа при записи) в этом инкременте не менялись —
их регресс-утверждения (`tests/test_byok_image_key_round1024.py`,
`tests/test_chat_keys.py`, `tests/test_debug_config.py`,
`tests/test_log_ring.py`) прогоняются полным набором (см. `green-full.txt`).

**Граница.** Сплошной скан `web/app.js`/HTML не входит в инкремент
(`web/*` вне области записи); этот пробел уже зафиксирован аудитом 2.58.180
§3. Вывод секретов в Telegram-сообщения здесь не аудировался.

## MAC-S4-171 — 401 ≠ 403 ≠ 404 ≠ 503

**Уже корректно на базе, теперь заперто на уровне отданных байт.**
`TestAccessStates` на реальных роутерах (`create_app`):
| Состояние | Запрос | Статус | Тело |
|---|---|---|---|
| нет сессии | `GET /api/admins` | 401 | `missing init data` |
| битая подпись | `GET /api/admins` + испорченный `hash` | 401 | `invalid init data` |
| нет права | `GET /api/admins` (роль `user`) | 403 | `permission denied` |
| нет маршрута | `GET /api/no-such-route-m1b` | 404 | `Not Found` |
| нет ресурса при валидном админе | `DELETE /api/access/diagnostic_policy/__m1b_absent_cap__` | 404 | `нет такой возможности: …` |
| backend недоступен при валидном админе | `PUT /api/access/param_permissions/limits.x` (PG отсутствует) | 503 | `PostgreSQL недоступен (R6)` |

`test_four_states_are_pairwise_distinct` собирает 401/403/404/503 в одном
прогоне и требует четыре разных тела — «нет доступа» не может подменить ни
отсутствие сессии, ни недоступность backend.

**Граница.** Это backend-уровень; UI-тосты (`web/app.js`) вне области записи и
в инкременте не проверялись (аудит 2.58.180 §5 их уже разобрал по коду).

## MAC-S10-13 — секреты в ответах/HTML/логах; промпты по resource ACL

Часть «секреты не попадают в network responses/логи» — покрыта разделом
MAC-S4-172 выше. Часть «промпты видны строго по resource ACL» в инкременте не
менялась: механизм — `web/api/routes.py::_prompt_require_view/_prompt_require_edit`
(второй ACL не вводится), вне области записи. **Остаточное:** видимость
промптов именно в контексте группового чата (SELF-DIAG) требует живого чата и
в этом инкременте не упражнялась; изменение `chat_access` на неё не влияет
(промпт-ACL читает `AccessCtx`/матрицу прав, а не `is_admin`).

## Конфигурация и флаги

Новых флагов, kill-switch, гейтов и порогов нет — правило проекта о включении
готовой функции при первом деплое здесь неприменимо по существу (нечего
включать). Поведение определяется существующими `settings.ADMIN_USER_ID` и
снимком `ConfigCache` (`bot_roles.role_type` / `permissions.wildcard` /
`bot_admins`). Пользовательских override, которые бы сбрасывались, нет.

Проверка фактической конфигурации (не «воображаемого флага»):
`services/pg_db.py` создаёт колонку идемпотентно
(`ALTER TABLE bot_roles ADD COLUMN IF NOT EXISTS role_type TEXT`) и сидит
встроенные роли с `role_type`; `DEFAULT_ROLES` содержит
`{"role_name": "admin", "permissions": {"wildcard": True}, ...}`. Поэтому:
* владелец (`ADMIN_USER_ID` = `5885953495`, роль `admin`) остаётся админом
  и по wildcard, и по legacy-имени — даже если на какой-то базе `role_type`
  ещё NULL, поведение не ухудшается относительно базы;
* назначенная роль с `role_type=global_admin` теперь даёт админку в чате —
  ровно то, что уже давала в Mini App.

## Файлы инкремента

* `services/chat_access.py` — `is_global_admin` + `is_admin` через канон
  (`is_effective_global_admin_role`), `is_moderator`/`privilege` не менялись.
* `tests/test_chat_access.py` — снимок ролей мока приведён к форме реального
  `ConfigCache.roles()` (+`roles()`), добавлен `TestGlobalAdminCanon`.
* `tests/test_mod_acl_ux_01_m1_predicate.py` — паритет сторон, потребители,
  четыре состояния доступа, секреты с положительным контролем.
* `plans/features/mod-acl-ux-01/evidence/m1/m1b/**` — этот файл и логи прогонов.

## Как воспроизвести

```
# из worktree кандидата
python -m pytest tests/test_mod_acl_ux_01_m1_predicate.py tests/test_chat_access.py -v
python -m pytest tests -q            # полный набор: pre-existing падения
                                     # сравниваются с базой по списку node id
# RED на базе: вернуть services/chat_access.py к a64ecb89b
git checkout a64ecb89b -- services/chat_access.py
python -m pytest tests/test_mod_acl_ux_01_m1_predicate.py -q
```

## Прогоны (фактические числа)

| Прогон | Команда | Результат | Файл |
|---|---|---|---|
| RED инкремента на базе `a64ecb89b` | `pytest tests/test_mod_acl_ux_01_m1_predicate.py -q` | **15 failed, 12 passed** | `red-base-pytest.txt` |
| GREEN инкремента | `pytest tests/test_mod_acl_ux_01_m1_predicate.py tests/test_chat_access.py -v` | **40 passed** | `green-increment.txt` |
| Регрессия затронутых швов (62 файла: потребители предиката, ACL/RBAC, секреты/логи, память-команды) | `pytest @scoped-files.txt -q` | **2304 passed, 13 failed** | `scoped-regression.txt` |
| Те же 13 node id на базовом `services/chat_access.py` | `pytest @scoped-failed.txt -q` | **те же 13 failed** — множество падений совпадает побитово (`only candidate: []`, `only base: []`) | `base-same-13.txt` |

Вывод: ни одно падение регрессионного набора не связано с инкрементом. Это
известное семейство «сверок с базлайном/каноном» (`test_canon_twelve_tools`,
`test_forbidden_paths_out_of_diff`, `test_canon_unchanged`,
`test_identical_quotes…`, `test_stale_token…`) — согласуется с исторически
зафиксированным списком пре-существующих падений проекта
(`plans/reports/final-report-p0-cycle-2026-10-27.md`: «40 failed — побитовый
пре-существующий список»).

**Полный набор 23 176 тестов в этой сессии до конца не пройден.**
Первый запуск (`full-suite-attempt1-aborted.txt`) прервался на 27% дампом
`pytest-timeout` (`pytest.ini: timeout = 60, timeout_method = thread` — по
таймауту поток убивает весь прогон). Второй (`--timeout=300`,
`full-suite-attempt2-stopped-5pct.txt`) остановлен вручную на 5%: в этой среде
темп ~10 мин на 5% (~3 ч на весь набор), что не является разумным гейтом для
правки одного модуля; в нём те же 16 отметок падений, что и в первом, все — в
файлах вне дифа. Падения находятся в файлах, которых диф не касается
(например `test_104_backend_additions.py::test_user_facing_text_updated` читает
`web/index.html` — он байт-в-байт равен базе; `git diff --name-only a64ecb89b`
= только `services/chat_access.py` и тесты). Поэтому доставленный регрессионный
результат — 62-файловый набор затронутых швов плюс побитовое сравнение его
падений с базовым кодом, а не «проверенный зелёный полный набор».


## Остаточные наблюдения (не дефекты этого инкремента)
* `GET /api/status/logs` отдаёт журнал любому авторизованному пользователю
  (маскирование сделано при записи — так и задумано в docstring маршрута); это
  существующее поведение, инкремент его не менял и не расширял.
* `web/api/deps.py` дублирует канон выражением (см. остаточное по MAC-S4-174).
* Прочие `settings.ADMIN_USER_ID`-проверки в `services/*`
  (`direct_chat_service.persona_access` 16982, `/persona list` 17115,
  `debug_config.is_debug_admin` 170, `info_service` 2755+, `mca_experience_jobs`,
  `mca_humor_feedback`) — это **владелец**, а не право «глобальный админ»
  (в коде так и написано: «только ADMIN_USER_ID»), и они не являются
  потребителями `chat_access`. Класс расхождения тот же, но другие файлы вне
  области записи этого инкремента; кандидат для отдельного триажа —
  `debug_config.is_debug_admin` (право debug, `role_type` не читает, аудит
  2.58.180 §1 п.14).
* Фоновые задачи не принимают решений о правах пользователя (системные), поэтому
  их ветка acceptance MAC-S4-174 закрывается тем же предикатом там, где они
  вообще спрашивают о правах через `chat_access`/`AccessCtx`.

## Гигиена рабочего пространства (retention)

* Worktree `mod-acl-ux-01-1e46be007668-ed629f84` — активная линия инкремента,
  зарегистрирован (`housekeeping register-worktree --epic mod-acl-ux-01
  --unit m1b`), **сохраняется** до закрытия ревью/релиза.
* Временная копия `services/chat_access.py` для сравнения с базой
  (`%TEMP%\opencode\m1b-chat_access.py`) и файл сообщения коммита **удалены**
  после употребления; `git hash-object` до и после восстановления совпал
  (`e435fd829d421463d854f08b1bd8550e46481917`).
* Логи прогонов — компактные текстовые файлы в этом каталоге (10 файлов,
  < 120 КБ суммарно); тяжёлых копий БД/данных не создавалось.
* `housekeeping inventory` по репозиторию: новых незарегистрированных
  артефактов этой сессии нет (`owned_count` — чужие активные юниты прошлых
  линий, не трогались).


