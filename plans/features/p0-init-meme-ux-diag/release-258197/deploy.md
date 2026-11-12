# Деплой 2.58.197 — финальный корректирующий поезд P0IM (после отката 2.58.196)

Итог: **VERIFIED для выкладки** — релиз `2.58.197` выложен и живые обязательные
проверки прошли, включая точный дефект, из-за которого был откачен 2.58.196.
Эпик **НЕ закрыт**: финальную карту/гейт делает PM.

## 1. Привязка

| Поле | Значение |
|---|---|
| База | `c134f93d` (2.58.195, прод после отката 2.58.196) |
| Кандидат (Reviewer Approved) | `6f63e1a6` (код `895764e2`, docs `b5841bac`) |
| Дельта кандидата | `21a3aef7..895764e2 -- services handlers web/api` пуста; изменены `web/app.js` (+18/−7) и JS-тест |
| Релизная ветка | `release/2.58.197` → `2587616759de31283585ffc105c91e7193c2e89e` (bump 2.58.197), запушена |
| Кумулятивно `c134f93d..25876167` | **48 файлов (45 M, 3 A, 0 D), +2788/−91** — 7 кода, 8 тестов, 3 evidence, 30 пинов |
| Проверки состава | DDL 0; новых флагов/настроек/промптов/моделей 0; планировщиков/агентов/страниц/второго пайплайна 0; хардкода чатов 0; новых маршрутов 0 |
| DEPLOY_SOURCE | `release/2.58.197`, deployed SHA `2587616759de31283585ffc105c91e7193c2e89e` |
| MUTABLE_WORKTREE_REQUIRED | no |
| Откат | `c134f93d` (2.58.195), не потребовался |

`2.58.196` (откаченный) не переиспользовался; ветка создана заново от `c134f93d`.

## 2. Обязательные тесты на `25876167`

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

Отданный `web/app.js` побайтово равен проверенному файлу кандидата:
sha256 `29817d9b927cb510f9896f4ea61d4a698f3cde18ba6cc9655608fe5251d759d8`
(2 298 542 б; совпал на диске, в коммите и по HTTPS `/web/app.js`).

## 3. Преддеплой и выкладка

- до выкладки: `c134f93d` / `release/2.58.195`, tracked-правок 0, unit active,
  `NRestarts=0`, `/healthz` 2.58.195;
- снапшот: `backups/predeploy-258197-20261112T094016Z.db` — 2 557 874 176 б,
  sha256 `5b59134f4a6223ff69a0ede5bf843ab68093f579a268237b1884896da93561ea`,
  read-back `integrity=ok`, `user_version=47`, 130 таблиц, 73.4 с;
- `git fetch --prune origin` → `origin/release/2.58.197 = 25876167`; проверено
  `merge-base --is-ancestor HEAD 25876167` (`FF_OK`);
- `git checkout -B release/2.58.197 25876167` (эквивалент ff-pull, без reset/force),
  HEAD совпал, tracked-правок 0, `APP_VERSION=2.58.197`;
- `systemctl restart admin_bot` в **2026-11-12T09:41:37Z**; unit active,
  `NRestarts=0`, `ActiveEnterTimestamp=09:41:39Z`; `/healthz` 2.58.197
  с первой попытки;
- пост-проверка 09:41:54Z: HEAD `25876167`, tracked 0, `user_version=47`,
  журнал 15 мин: `Traceback=1`, `ERROR=0`, `CRITICAL=0`, `attempt LOST=0`.
  Единственная строка `Traceback` и две `ERROR` — фоновый
  `services.anticliche_worker` (pipeline fetch: `sources_unavailable`,
  `fetch_error wikipedia`, 09:46:42Z), файл релизом не менялся
  (`recon-258197.txt`).

## 4. Эффективная конфигурация (P0IM-AC-SETTINGS)

До/после — одинаковые read-only GET'ы владельческой initData,
`settings-parity-2.58.197.json`:

| Поверхность | До = после |
|---|---|
| `GET /api/config` (глобальный) | sha256 совпал |
| `GET /api/config/overrides-map` | совпал |
| `GET /api/prompts/catalog` | совпал |
| `GET /api/prompts/{key}/versions` × 4 | все 4 совпали |
| `GET /api/initiative/meme-settings` сохранённые блоки, оба чата | **совпали** |
| `GET /api/config` X-Chat-Id A / B | расходятся только на волатильном `modules/3/gate/observed_at` (две подряд выборки отличаются ровно им); latest `updated_at` у всех 623 items — 2026-11-11, до релиза |

Сохранённые промпты, модели, `chat_params` и настройки не менялись.

## 5. Живые проверки (без сообщений в чаты)

Артефакты: `live-checks-2.58.197.json`, `live-extra-2.58.197.json`,
`live-ov-list-2.58.197.json`, `live-overview-2.58.197.json`, PNG.

| Проверка | Результат |
|---|---|
| **P0IM-OV-LIST** (дефект 2.58.196) | **PASS**: в обоих чатах все 5 строк обзора показывают **«автоматически»**, 0 строк «способ не записан»; в analytics 10 jobs, у всех терминальная строка `attempt_mode="automatic"` (`live-ov-list-2.58.197.json`). Живой сценарий 2.58.196 («способ не записан» при записанном режиме) больше не воспроизводится; скриншоты `live-overview-chatA/chatB-2.58.197.png` |
| manual/unknown в OV-LIST | ручных попыток в окне нет (0) — «вручную (/meme)» живьём не наблюдался; строк без записанного режима в окне нет — честная ветка «способ не записан» покрыта JS-тестами (и наблюдалась в 2.58.196) |
| `/healthz` 2.58.197, schema 47 | ок |
| diagnostics оба чата | 200, `degraded=[]`; `image_module` присутствует как `layer=global`; `image_provider` available/configured/model=qwen-image-3-pro; `heartbeat`-блок присутствует (`ok=false`, `last_tick_ts=null` — тика ещё не было, честно); квоты A 2/3, B 2/3 |
| `PB-FILTERS` | 6 фильтров + `days=7/0/90` + пагинация — 200 и корректные выборки; `days=91`, `limit=0/500`, `offset=-1` → 422 (оба чата) |
| трасса попытки | A `meme:…` (considered→skipped кулдаун), B `meme:…1da028d2` (7 шагов, `generated=true`, `outcome=deferred`, `publisher_not_bound`, размер 1 843 784, sha256) |
| `PB-ACCESS` | обычный Inspector отдаёт preview/hierarchy; корреляция (своя/чужая/несуществующая) → `not_recorded`, без preview, маскирование, retention 24; не-админ (KOSTIK) → **403** оба чата. Положительный ring-случай не наблюдался: после рестарта ни одна попытка не дошла до LLM |
| `PB-LLM` | живых полей пока нет: 3 (A) и 4 (B) попытки после рестарта остановились до LLM; поля покрыты 204-набором, появятся на первой реальной LLM-попытке |
| `PB-MANUAL` | маркер/TTL в данных: `manual_priority_until`, `active=false`, `expired=true`, `state=released`; ручной `/meme` не запускался (запрещено), слияние факта снятия — тесты |
| `S6-EFFECTIVE` | `image_module` всегда в `configuration.layers` с `layer=global`; `image_provider`/`heartbeat` — проекции существующих вычислений, новых панелей нет |
| `OV-SAMPLE` | (1) «ВКЛ / пауза» — `meme_enabled=true`, `cooldown_ready=false`; (2) «картинка создана, отправка отложена» — живой случай B 08:53:39 (`generated=true`, `deferred publisher_not_bound`, размер/sha); (3) подтверждённые отправки A #10435 / B #1210123; (4) «Показать попытку» — кнопка есть |
| `AC-NODUP` | дельта 48 файлов: новых страниц/агентов/планировщиков/второго пайплайна/хардкода нет; отданный app.js = проверенный файл |
| `AC-MATRIX-RBAC` | скан payload'ов (68 414 симв.) на `authorization/x-api-key/password/secret/cookie/Bearer/токен-бота` — **0**; не-админ 403; чужой чат текста не получает |
| `AC-MATRIX-FAIL` | покрыто тестами (204); в проде отказ провайдера не провоцировался |

## 6. Откат

Не потребовался. Готовность: `git checkout -B release/2.58.195 c134f93d &&
systemctl restart admin_bot`; данные не откатываются (схема 47, DDL=0),
страховка — снапшот §3.

## 7. Честные границы

- Положительный ring-случай `PB-ACCESS` и живые поля `PB-LLM` требуют реальной
  LLM-попытки; принудительно не вызывались. По контракту ревью это не было
  обязательной предрелизной live-строкой ( Reviewer относил к live только
  OV-SAMPLE, PB-FILTERS, AC-SETTINGS, AC-DONE).
- `heartbeat` после рестарта честно `null` (первого тика не было) — не «здоров».
- SELF-DIAG-01 D1 не трогался (0 файлов), доказательства `evidence/d1/`
  на `c134f93d` остаются; повторных SSH-проб не было.
- Release-гейт не запускался — это финальная бухгалтерия карты PM.
- **Эпик НЕ закрыт.**
