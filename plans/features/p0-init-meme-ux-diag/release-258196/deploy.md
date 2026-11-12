# Деплой 2.58.196 — выложен и откатан: живая проверка OV-LIST не прошла

Итог: **FAILED** (прод возвращён на 2.58.195 `c134f93d`). Остальные обязательные
проверки на выложенном кандидате прошли; дефект — пользовательская подпись
«способ попытки» в обзоре. Данные не откатывались (схема 47, DDL=0).

## 1. Привязка

| Поле | Значение |
|---|---|
| База | `c134f93d` (2.58.195, был задеплоен) |
| Кандидат (Reviewer Approved) | `12974a26` (код `21a3aef7`, docs `e314dd3f`) |
| Дельта кандидата | `3b1c4ba9..21a3aef7 -- services web handlers` пуста; изменён только `tests/test_initiative_coordination.py` (+11/−3) и evidence |
| Релизная ветка | `release/2.58.196` → `e8e2619b` (bump 2.58.196), запушена |
| Кумулятивно `c134f93d..e8e2619b` | **48 файлов (45 M, 3 A, 0 D), +2651/−89** — 7 файлов кода, 8 файлов тестов, 3 evidence, 30 пинов версии |
| Проверки состава | DDL 0, новых флагов/настроек/промптов/моделей 0, планировщиков/агентов/страниц/второго пайплайна 0, хардкода чатов 0, новых маршрутов 0 |
| DEPLOY_SOURCE | `release/2.58.196`, deployed SHA `e8e2619b251dc6f01367975edf0bdef955d6c4a7` |
| MUTABLE_WORKTREE_REQUIRED | no (checkout по SHA на проде) |
| Откат | `c134f93d` (2.58.195), выполнен |

Первая попытка 2.58.196 была остановлена до выкладки из-за нового падения
`test_command_marks_priority_before_generation` (стаб не принимал `job_id`);
исправлено тестом `21a3aef7`, повторно ревью — Approved.

## 2. Обязательные тесты на `e8e2619b`

| Проверка | Результат | База `c134f93d` |
|---|---|---|
| 7 файлов closure | **204 passed** | 204 |
| `tests/test_initiative_coordination.py` | **56 passed / 4 failed** | 56/4, те же четыре |
| `…::test_command_marks_priority_before_generation` | **1 passed** | 1 |
| 22 файла meme/initiative/publication/diagnostic | **519 passed / 4 failed** | 510/4, те же четыре |
| JS `initiative_ui_rework_test.js` / `p0im_ov_honesty_test.js` | `INITIATIVE-UI-OK` / `P0IM-OV-HONESTY-OK` | то же |
| `tests/test_webapp_js_unit.py` | **45 passed** | 45 |
| `tests/test_web*.py` (68 файлов) | **1539 passed / 11 failed** | 1539/11 |
| `ui_inspector_exact_e2e.py` | `checks=142, failures=0` | 0 |
| `ui_meme_ui_fields_e2e.py` | `failures=0` | 0 |
| `ui_initiative_rework_e2e.py` | `failures=2` (те же 1536/390) | те же 2 |

## 3. Преддеплой и выкладка

- снапшот: `backups/predeploy-258196-20261112T085424Z.db` — 2 557 394 944 б,
  sha256 `ba138b61a1dd249d1a19ec39ff43378345177a2230ef38da4c55e260bfb3b6d6`,
  read-back `integrity=ok`, `user_version=47`, 130 таблиц, 68 с;
- прод до выкладки: `c134f93d` / `release/2.58.195`, tracked-правок 0, unit active,
  `NRestarts=0`, `/healthz` 2.58.195, свободно 42G;
- `git fetch --prune origin` → `origin/release/2.58.196 = e8e2619b`; проверено
  `merge-base --is-ancestor HEAD e8e2619b` (fast-forward возможен);
- `git checkout -B release/2.58.196 e8e2619b` (эквивалент ff-pull, без reset/force),
  HEAD совпал, tracked-правок 0, `APP_VERSION=2.58.196`, `web/app.js` blob
  `df756602`, 2 297 972 б;
- `systemctl restart admin_bot` в **2026-11-12T08:55:40Z**; unit active,
  `NRestarts=0`, `ActiveEnterTimestamp=08:55:43Z`; `/healthz` отдал 2.58.196
  с первой попытки;
- пост-проверка 08:55:57Z: HEAD `e8e2619b`, tracked 0, `user_version=47`,
  журнал 15 мин: `Traceback=0`, `ERROR=2` (две записи `mca_events INCIDENT`
  в 08:55:16Z, ДО рестарта), `CRITICAL=0`, `attempt LOST=0`;
- отданный `/web/app.js` независимо скачан и сверен: sha256
  `949810cc16cde382ed02964d304c85fa05f859420bc2cb9c1b213b382442d170`,
  2 297 972 б — совпадает с файлом коммита (путь `/app.js` — 404-заглушка,
  в проверке деплоя использовался не тот URL).

## 4. Эффективная конфигурация (P0IM-AC-SETTINGS)

До (08:52:21Z) и после (08:55:50Z) — одинаковые read-only GET'ы владельческой
initData, `settings-parity-2.58.196.json`:

| Поверхность | До = после |
|---|---|
| `GET /api/config` (глобальный) | sha256 `e6119b0f…` = `e6119b0f…` |
| `GET /api/config/overrides-map` | `7c14840b…` = `7c14840b…` |
| `GET /api/config` X-Chat-Id A / B | `77511d2b…` / `a2713a9f…` — расходятся только на волатильном `modules/3/gate/observed_at` (две подряд идентичные выборки отличаются ровно этим ключом); у всех 623 items `updated_at` ≤ 2026-11-11T13:14 |
| `GET /api/prompts/catalog` | `aafd645a…` = `aafd645a…` |
| `GET /api/prompts/{key}/versions` × 4 | `57e84967…` = `57e84967…` (все 4 ключа совпали) |
| `GET /api/initiative/meme-settings` сохранённые блоки | чат A совпал; чат B отличается только живыми блоками `delivery.events` / `quota` (реальные попытки), конфигурационные блоки (`settings/prompts/template/image_prefix/limit/defaults/keys`) стабильны |

Сохранённые промпты, модели и настройки не менялись.

## 5. Живые проверки (агентские, без сообщений в чаты)

Оба чата: `-1004482340693` (A), `-1002661910336` (B). Артефакты:
`live-checks-2.58.196.json`, `live-extra-2.58.196.json`, `live-ui*.json`, `*.png`.

| Проверка | Результат |
|---|---|
| `/healthz` 2.58.196, schema 47 | ок |
| `mechanism-diagnostics` оба чата | 200, `degraded=[]`; `image_provider` available/configured/model=qwen-image-3-pro; гейт `image_module` в `configuration.layers` с `layer=global`, `enabled=true`; `heartbeat`-блок присутствует (`ok=false`, `last_tick_ts=null` — тика ещё не было, честно) |
| квоты | A: 2/3, delivered 2; B: 2/3, delivered 1, not_delivered 1 (`publisher_not_bound`) |
| `PB-FILTERS` (6 фильтров) | оба чата: kind=meme/text, mode=auto/manual, outcome=published/deferred/failed, reason=cooldown_active — 200 и корректная выборка; `days=7/0/90`; пагинация limit/offset; `days=91`, `limit=0/500`, `offset=-1` → 422 |
| трасса попытки | A: `meme:…:a64d3b07` (2 шага, скип по кулдауну); B: `meme:…:1da028d2` (7 шагов, `generated=true`, `outcome=deferred`, `publisher_not_bound`, `deferred.size=1 843 784`, sha256) |
| `PB-ACCESS` | корреляция: своя/чужая/несуществующая → `not_recorded`, `requested_correlation_recorded=false`, без `preview/hierarchy/skip_reasons`, секреты маскируются, retention 24; обычный Inspector по-прежнему отдаёт preview; не-админ (KOSTIK) → **403** на обоих чатах. Положительный случай (запись кольца) пока не наблюдался: после рестарта ни одна попытка не дошла до LLM |
| `PB-LLM` | **живого случая нет**: 4 (A) и 2 (B) попытки после рестарта остановились до вызова LLM; поля `llm/prompt/api` покрыты 204-набором и появятся на первой реальной LLM-попытке |
| `PB-MANUAL` | маркер в данных: `manual_priority_until`, `manual_priority_active=false`, `expired=true`; живого ручного `/meme` не запускали (запрещено), слияние факта снятия покрыто тестами |
| `OV-LIST` | **FAILED** — см. §6 |
| `S6-EFFECTIVE` | `image_module` присутствует всегда и как общий слой; `image_provider` и `heartbeat` — проекции существующих вычислений, отдельных панелей нет |
| `OV-SAMPLE` | (1) «Мемы · ВКЛ / пауза» — `meme_enabled=true`, `cooldown_ready=false`; (2) «картинка создана, отправка отложена» — **живой случай есть**: B 08:53:39, `generated=true`, `deferred publisher_not_bound`, размер/sha; (3) «последняя подтверждённая отправка» — A #10435, B #1210123; (4) «Показать попытку» — кнопка присутствует |
| `AC-NODUP` | дельта 48 файлов: новых страниц/агентов/планировщиков/второго пайплайна/логического хардкода нет; отданный app.js = файл коммита |
| `AC-MATRIX-RBAC` | скан собранных payload'ов (81 965 симв.) на `authorization/x-api-key/password/secret/cookie/Bearer/токен-бота` — **0**; не-админ 403; чужой чат текста не получает |
| `AC-MATRIX-FAIL` | покрыто тестами (204); в проде отказ провайдера не провоцировался |

Скриншоты: `live-overview-chatA/chatB-2.58.196.png`, `live-memes-chatA/chatB-2.58.196.png`
(реальный Chrome, 0 ошибок консоли, только warning'и Telegram WebApp версии).

## 6. Дефект, из-за которого откат

`P0IM-OV-LIST` на живых данных показывает «способ не записан» для ВСЕХ
мем-попыток, хотя режим записан.

Причина: сервер пишет `attempt_mode = "automatic"` (`services/meme_initiative.py:255-256`,
`:2057`), серверный нормализатор `attempt_mode_of()` умеет `automatic → auto`
(`:1963-1975`), но UI-обзор сравнивает сырое значение только с `'auto'`/`'manual'`
(`web/app.js:10762-10763`), поэтому `automatic` не распознаётся.

Доказательства: `live-ui-events-2.58.196.json` (все строки «способ не записан»),
`analytics-shape-2.58.196.json` (в тех же строках `detail = {"attempt_mode":"automatic",…}`),
`live-ui-2.58.196.json`, скриншоты обзора.

Почему тесты не поймали: JS-фикстура использует `'{"attempt_mode":"auto"}'`
(`tests/js/initiative_ui_rework_test.js:2760`), а не реальное значение
`automatic`; проверка OV-LIST была на view-model уровне, не на живом payload.

Минимальное исправление (Builder + Reviewer): нормализовать `automatic → auto`
в `initiativeRecentEvents` (или переиспользовать то же отображение), обновить
JS-фикстуру на реальное значение пайплайна и добавить кейс «строка с
`attempt_mode=automatic` показывает «автоматически»». Затем патч-релиз
(2.58.197) и повторные живые проверки.

## 7. Откат

```
git checkout -B release/2.58.195 c134f93d
systemctl restart admin_bot
```

- выполнен в **2026-11-12T09:08:28Z**, рестарт 09:08:31Z, `/healthz`
  2.58.195 с первой попытки, unit active, `NRestarts=0`;
- прод сейчас: `c134f93d` / `release/2.58.195`, tracked-правок 0, `user_version=47`;
- данные не откатывались: DDL/migrations нет; снапшот
  `predeploy-258196-20261112T085424Z.db` остаётся страховкой.

## 8. Прочие наблюдения и границы

- В журнале 09:00:30–09:08:20Z (время 2.58.196) — 2 `ERROR` от
  `services.anticliche_worker` (`pipeline_step` fetch: `sources_unavailable`,
  `fetch_error wikipedia`) и 2 заголовка `Traceback` в том же окне; воркер
  релизом не менялся, это фоновый шум. Тела traceback не разбирались.
- `PB-ACCESS` положительный случай и `PB-LLM` живые поля требуют реальной
  LLM-попытки; принудительно не вызывались.
- Хартбит после рестарта честно `null` (тика ещё не было) — не «здоров».
- SELF-DIAG-01 D1 не трогался: 0 файлов в дельте, доказательства
  `plans/features/self-diag-01/evidence/d1/` (anchor `c134f93d`) остаются
  в силе; повторные SSH-пробы не выполнялись.
- Гейт release-стадии не запускался: выкладка откачена, кандидат не принят.
- **Эпик НЕ закрыт**: финальную карту/гейт делает PM/Orchestrator.
