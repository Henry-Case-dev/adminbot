# Deploy 2.58.189 — UR-F «инспектор хода», шаг 1 (UR-20.6 + UR-20.7)

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`).
Согласие владельца (PET_PROJECT) стоячее: отдельного разрешения на выкат готового
и отревьюенного среза не требовалось.

## 1. Границы выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.189` = `edd7d47255c36ec5ce4504a086c5db87798518cf` |
| Дерево деплоя | `ba196a9b71011b1c31705e7048a6e4cbfa67d514` (сервер: `git rev-parse edd7d472^{tree}` — совпало) |
| Принятый кандидат | порт `f328611f` (база `c087253d`) |
| Предыдущий прод | `c087253d` @ 2.58.188, schema 47 |
| MUTABLE_WORKTREE_REQUIRED | **no** — неизменяемый checkout по SHA, `dirty_tracked=0` до и после |
| Repo write scope | `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, 25 python-пин-файлов (26 строк), 4 JS-пина, `tests/test_round1025_f8_registry.py` |
| Δ DDL / Δ migration / Δ flag | **0 / 0 / 0**, схема остаётся v47 |

Ветка `ur/f-inspector-step1` **не выкладывалась**: второй независимый ревьюер
измерил расхождение с `f328611f` в 121 файл при идентичных `routes.py`,
`turn_trace.py`, `index.html` и JS-тесте (`app.js` отличается только
комментарием). Выложен порт.

## 2. Дельта `c087253d..edd7d472`

49 файлов, **1864 вставки / 100 удалений**: 18 файлов среза + 2 релизных
коммита (31 строка пинов версии и 1 строка digest'а проекции).

Срез: `services/direct_chat_service.py` (+73/−16), `services/turn_trace.py`
(+25/−4), `web/api/routes.py` (+9), `web/app.js` (+358/−10),
`web/index.html` (+42/−6), `tests/test_ur_f_inspector_step1.py`,
`tests/test_ur_f_inspector_step2.py`, `tests/test_ur_f_inspector_step3_ui.py`,
`tests/js/ur_f_inspector_step3_test.js`, `tests/test_auto_budget_asap31.py`
(двойник LLM приведён к форме адаптера Q6 — тестовый файл, поведение продукта
не меняет), `tools/ui_urf_visual_e2e.py`, 8 файлов evidence.

Инварианты (blob-id равны в `c087253d` и `edd7d472`):

```
services/permissions.py   e20d46ebf1591bfa4f1c9df622d6babcb33d7ccb
web/api/avatars.py        3b8be940b539d608c92b8d145af47a23c186dd1d
web/api/deps.py           509b387d4894dda8575b6d36ab307e6fbb2a848c
services/pg_db.py         00c641333703fe28c6bb75819d17cb3fefeb4f4a
services/param_catalog.py fc4b6217567a33b739412128a7a0b698bce01c35
```

- `services/database.py` не менялся → `_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47`;
  `delta DDL = 0`, файлов миграций/`.sql` в дельте нет, `pg_db.py` байт-в-байт.
- `services/param_catalog.py` байт-в-байт → Δ каталога = 0.
- Новых импортов сторонних библиотек, новых env/`settings`-ключей в дельте нет.
- **Ни одна строка 2.58.186–188 не потеряна**: автопроверка «каждая добавленная
  в 186–188 строка присутствует в релизе» дала 32 расхождения, и все 32 —
  намеренно перепинованные строки (31 пин версии + 1 digest `ROUTES_SHA256_F11`).
  Продуктовых строк предыдущих релизов потеряно 0.

## 3. Гейты и тесты (на `edd7d472`, из release-worktree)

| Проверка | Результат |
|---|---|
| `tests/test_ur_f_inspector_step1.py` | **59 passed** (exit 0) |
| `tests/test_ur_f_inspector_step2.py` | **19 passed** (exit 0) |
| `tests/test_ur_f_inspector_step3_ui.py` | **44 passed** (exit 0) |
| `node tests/js/ur_f_inspector_step3_test.js` | **UR-F-STEP3-OK** (exit 0) |
| `tests/test_round1025_f8_registry.py` (byte-freeze/pins/DDL/routes) | **29 passed** (exit 0) |
| 4 JS-пина `round1025_hotfix{7,8,9,10}` (были на 2.58.187) | HOTFIX7/8/9/10 … **-OK** |
| 23 python-файла пинов версии | **829 passed, 2 failed** — оба падения предсуществующие |
| `requirements_gate.py check --stage release --slice UR-F --candidate edd7d472` | **EXIT 1**, `inventory=206 manual=139 scoped=29 errors=132` |

Классификация двух падений (воспроизведены на проде `c087253d` в отдельном
worktree, идентичный текст ошибки):

| Тест | Причина |
|---|---|
| `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff` | guard считает `git diff --name-only pre-round1026-a1` (историческая метка) и видит накопленный санкционированный дрейф прошлых волн — 8448 путей |
| `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` | то же для `web/`-allowlist |

Гейт требований: вывод **побайтово совпадает** с прогоном на `c087253d`
(`Compare-Object` → 0 различий), т.е. кандидат не добавил ни одной ошибки.
Ошибки — состояние карты (строки `UR-20.6`/`UR-20.7` и зависимости UR-A/B/C
в статусе PENDING без evidence), это книжная работа PM как единственного
писателя карты; прецедент — `plans/features/_audit-2026-10-23/release-258124/deploy.md:73`.

### Осознанное переутверждение пинов (reles-коммиты)

- `ROUTES_SHA256_F11`: `0d15c690…484860` → `4c7af646…877bb`. Проекция
  СУЩЕСТВУЮЩЕГО `GET /api/direct/turn-diagnostics` законно расширена
  (`slot`, `reply_to_ts`, `reason`); маршрутов **75 → 75** декораторов
  `@api_router`, уникальных путей 62 → 62, `f8_baseline` не переиздавался.
  Сервер после выкладки отдаёт ровно `4c7af646…877bb`.
- Пины версии: `config/settings.py`, мета param-registry, 25 python-пин-файлов,
  4 JS-пина. Четыре JS-пина отстали ещё в релизе 2.58.188 (bump-коммит
  `c087253d` их не тронул) — здесь они догнали фактическую версию.

## 4. Выкладка

- pre: `release/2.58.188` @ `c087253d`, `dirty_tracked=0`, `APP_VERSION=2.58.188`,
  unit `active`, `NRestarts=0`.
- `git fetch origin release/2.58.189` → объект `edd7d472` = commit, дерево `ba196a9b`.
- Снапшот SQLite: `/tmp/predeploy-258189.db`, **2 346 483 712 B**, read-back
  `user_version=47`, `PRAGMA quick_check=ok`, `mca_events` 265 572 строк,
  48 колонок `smart_messages`.
- `git checkout -f -B release/2.58.189 edd7d472` → `HEAD=edd7d472`,
  `dirty_tracked=0`, `APP_VERSION="2.58.189"`.
- `systemctl restart admin_bot` в **2026-11-11T12:35:36Z**; MainPID 4023576,
  `ExecMainStatus=0`.

## 5. Пост-деплой (read-only)

| Проверка | Факт |
|---|---|
| `git rev-parse HEAD` на сервере | `edd7d47255c36ec5ce4504a086c5db87798518cf`, ветка `release/2.58.189` |
| `/healthz` (локально, :8000) | 200 `{"status":"ok","version":"2.58.189"}` |
| Unit | `active`, **NRestarts=0**, MainPID 4023576 (тот же процесс), active since 12:35:37Z |
| Журнал с рестарта (531 строка) | `Traceback` **0**, `CRITICAL` **0**, ` ERROR ` **0**, `database is locked` **0**, WARNING 13 |
| 13 WARNING | все предсуществующих семейств, те же в окне до рестарта: `SmartModule … superseded (A06)`, APScheduler `run time missed by 0:00:04.8`, `model_capacity unknown model 'z-ai/glm-5.3-flash-uncensored'`, `graphrag RAG int8 chat-scope KNN partial`, `[direct] l1 planner outage → deterministic fallback (LLMBadResponseError)`, `correction frame claim truncated` |
| Схема | `user_version=47` — не изменилась |
| Секрето-подобных строк в дельте | 0 (скан 1908 добавленных строк) |

### Отданные файлы Mini App

| URL | sha256 | Сверка |
|---|---|---|
| `/web/app.js` | `0c4c1c283385c3fafb64daefe1868cacbf0a27c5c5268dfcd091ff1f49c3c340` | = blob релиза |
| `/web/index.html` | `54f9ce57993e3d0afb11dc73dafee90498d448295a4cd83a40bae5a23a0b4425` | = релизный `index.html` (`01bd4aee…`) с подстановкой `__APP_VERSION__`→`2.58.189`; в отданном HTML 17 × `?v=2.58.189`, остатков `__APP_VERSION__` 0 |
| `/web/static/app.css` | `f349b8ae0ce4e055da27359ab855ba1d3950a84a502035ef49f330e4b80d30c4` | не менялся в этом релизе |

### Живая проверка на РЕАЛЬНОЙ трассе (0 отправленных сообщений)

Ход, записанный ботом уже после выкладки: `trace_id=71a18f9a940041a7af749a75936da6d1`,
чат `-1004482340693`, `ts=1794400696` (12:38:16Z), цепочка из 9 событий
(`retrieved`, `tool_phase`, `reply_search_evidence`, `direct_turn_writer`,
`direct_self_correction_delivery`, `direct_turn_delivery`,
`direct_turn_selection`, `speech_extent`, `direct_turn_context`).

`GET /api/direct/turn-diagnostics?chat_id=-1004482340693&trace_id=…` (валидный
initData администратора, выдан в процессе) → **200, `available: true`**:

- `context.l1.slot = "main"` — **реальное значение из записи этого хода**
  (`plan_source: llm`, `model: z-ai/glm-5.3-flash-uncensored`);
- `source.reply_to_ts` присутствует в схеме ответа (`null` — этот ход не был
  ответом на сообщение);
- `delivery.reason` присутствует (`null` — доставка `success` без причины
  остановки), `delivery.outcome = "success"`,
  ops: `reasoning_marker_strip, evidence_egress_guard, owner_style_punctuation,
  plain_render, egress_sanitize, telegram_chunk`;
- выбор по умолчанию (`turn=1`, без `trace_id`) вернул тот же ход, `l1.slot=main`.

Честная пустота подтверждена на реальном ходе из прошлой версии
(`trace_id=21956e9445f74fc99a52d356d9c735b7`, ответ на сообщение):
`reply_to_id=10450`, `reply_to_author_id=8802473181`, `reply_to_alias="Базовичок"`,
но `reply_to_ts=null` и `l1` без `slot` — трасса записана до появления полей,
значение не выдумывается.

Неизвестный код: шесть реальных delivery-ops не имеют подписей в словаре
`app.js` → карточка рендерит их как `код: <op>` (fallback `TURN_UNKNOWN_CODE =
'код: '`); отданный `app.js` побайтово равен протестированному blob'у, JS-тест
проверяет именно этот случай (`'код: mystery_op'`).

## 6. Откат

- Код: `git checkout -f -B release/2.58.188 c087253d` + `systemctl restart admin_bot`.
  Объект на сервере есть: `git cat-file -t c087253d…` = `commit`,
  `APP_VERSION` в нём = `2.58.188`.
- Данные откатывать **не нужно**: схема v47 до и после, `Δ DDL = 0`, миграций нет.
- Точка восстановления: `/tmp/predeploy-258189.db` (2 346 483 712 B, v47,
  `quick_check ok`) — на случай расхождения данных, не для откатa кода.

## 7. Что осталось открытым

- `UR-20.6` / `UR-20.7` в карте остаются **PENDING без evidence**: привязку
  строк и `deployed_commit` делает PM/Orchestrator (единственный писатель карты).
  Из-за этого же `requirements_gate --stage release` даёт EXIT 1 — ровно те же
  132 ошибки, что и на проде `c087253d` (0 новых).
- Наблюдение (не блокер): шесть delivery-ops показываются как `код: …` —
  контрактный fallback; подписи для них можно добавить отдельной задачей.
