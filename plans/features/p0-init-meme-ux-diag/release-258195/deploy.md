# Деплой 2.58.195 — финальный корректирующий поезд P0IM (durability, честные поля, BAN-CONFLATE)

Адресат: **production** (192.255.209.205, `/var/www/admin_bot`).
База: выложенный `6c11fc08` (2.58.194). Схема БД не меняется (v47, DDL=0),
новых флагов, настроек, эндпоинтов и промптов нет.
**Эпик НЕ закрыт:** выложен только текущий одобренный поезд.

## 1. Привязка кандидата

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.195`, deployed SHA `c134f93d5c4a68f0ea906498cb9e0b78fc795f1e` |
| Reviewed candidate | `4c2d7ef66390c891c2a007c239f6da2bdc4d12c3` (код `2d41f2b3`), вердикт `Approved` — `evidence/final-train/review-5d599ca1.md` |
| База релиза | `6c11fc08` (2.58.194), линейный потомок без rebase/merge |
| MUTABLE_WORKTREE_REQUIRED | **no** — на проде checkout по SHA, рабочее дерево чистое |
| Repo write scope выкладки | 47 файлов: 17 файлов кандидата + 30 файлов пинов версии |

Ветка создана от `6c11fc08`, кандидат взят `git merge --ff-only 4c2d7ef6`
(Fast-forward, конфликтов нет), затем один bump-коммит `c134f93d`.

| # | Коммит | Тип | Что |
|---|---|---|---|
| 1 | `77b9110d` | код | терминальная строка попытки удерживается при отказе обоих носителей |
| 2 | `f984f06a` | код | устаревание данных, счётчики вызовов/генераций, длительность и ID запроса шага |
| 3 | `43d72f14` | docs | привязка `f984f06a` |
| 4 | `926b093a` | код | удержанная строка переносится любым экземпляром того же журнала |
| 5 | `262f7f18` | docs | привязка `926b093a` + ревью Needs Fixes |
| 6 | `2d41f2b3` | код | «сгенерировано» по доказанной картинке, не по этапу publish (BAN-CONFLATE) |
| 7 | `5d599ca1` | docs | привязка `2d41f2b3` |
| 8 | `4c2d7ef6` | docs | ревью кандидата (Approved `5d599ca1`) |
| 9 | `c134f93d` | bump | 2.58.194 → 2.58.195: `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, 24 py-пина, 4 js-пина |

**Дельта `6c11fc08..c134f93d` = 47 файлов, +2313/−63**, все `M` (41) и `A` (6),
удалений (`D`) нет. Состав: 11 файлов кода/тестов кандидата (побайтно те же,
что в `4c2d7ef6` — сверено `git rev-parse <sha>:<path>`), 6 evidence-документов,
30 файлов пинов версии. Полный список — `git diff --name-status 6c11fc08 c134f93d`.

Проверки состава (безопасность выкладки):

- DDL: `CREATE TABLE|ALTER TABLE|ADD COLUMN|DROP TABLE|CREATE INDEX` в дельте
  `services/ web/ config/` — **0**; `user_version` 47 до и после;
- новых маршрутов `@*.router.get/post/put/delete/patch` — **0**;
- новых полей `Settings`, `_env_bool`, `os.getenv`, `settings.<NEW>` — **0**
  (в `config/settings.py` изменена только строка `APP_VERSION`);
- новых файлов кода/страниц/агентов/планировщиков — **0** (6 новых файлов — только
  evidence-документы); `add_job|AsyncIOScheduler|scheduler\.|register_page` — 0;
- логических хардкодов чатов (`-100…`) и вторых пайплайнов — **0**;
- `web/app.js` / `web/index.html` взяты из линии релиза (не из `master`):
  app.js 2 284 920 б, blob `33f07dd1`.

## 2. Преддеплойная валидация (worktree `release/2.58.195`)

| Проверка | Результат | База `6c11fc08` |
|---|---|---|
| `test_evol014_meme_initiative.py` | **58 passed** | — |
| `test_initiative_publications_api.py` | **35 passed** | — |
| `test_meme_init_diagnostics.py` | **44 passed** (вместе с предыдущим файлом — **79**) | 43 на 2.58.194 |
| `test_p0im_s6_fresh.py` | **10 passed** | — |
| `test_p0im_s5_meme_marker_interrupt.py` | **15 passed** | — |
| `test_publication_binding_delivery.py` | **8 passed** | — |
| `tests/js/p0im_ov_honesty_test.js` | `P0IM-OV-HONESTY-OK` | — |
| `tests/js/initiative_ui_rework_test.js` | `INITIATIVE-UI-OK` | — |
| `tests/test_webapp_js_unit.py` | **45 passed** | — |
| `tests/ui_initiative_rework_e2e.py` | `failures=2` (те же две строки про снятие override: «Состояние неизвестно · журнал недоступен», 1536 и 390) | те же 2 |
| `tests/ui_meme_ui_fields_e2e.py` | `failures=0` | — |
| 22 файла meme/initiative/publication/diagnostic | **510 passed / 4 failed** | **494 passed / 4 failed** на `6c11fc08`, список `FAILED` совпадает побайтово |
| `tests/test_web*.py` (68 файлов) | **1539 passed / 11 failed** | **1539 passed / 11 failed** на `6c11fc08`, те же 11 тестов |

4 падения — ровно `test_initiative_coordination.py`: `test_act_on_opportunity_conflict_defers_to_intent`,
`test_evaluate_phase_precheck_blocks_before_llm`, `test_t1_nostalgia_delegated_refusal_sends_nothing`,
`test_t5_every_text_send_site_passes_publish_guard`. 11 падений web/api — тот же набор
файлов и тестов на базе и на кандидате (сверено списком `FAILED`).

Состав 19-файлового прогона 2.58.194 нигде не записан поимённо, поэтому взят
широкий набор из 22 файлов по именам модулей и **обе** линии прогнаны одним и тем
же набором: +16 тестов кандидата, новых падений 0. Все прогоны — с `-s`
(особенность локальной оболочки: fd-захват pytest падает на `OSError [WinError 6]`).

Замечание по прогонам: e2e-стенды перезаписывают PNG в
`plans/features/evol/audit/evidence/` — правки восстановлены `git checkout --`
до коммита, в релиз не попали.

## 3. Преддеплойное состояние прода

| Проверка | Значение |
|---|---|
| HEAD / ветка | `6c11fc08ddade1edf0c4fb274e7f1bf93f852a26` / `release/2.58.194` |
| tracked-изменения | 0 (только ожидаемое `?? .cache/`) |
| systemd | `active`, `NRestarts=0`, поднят 2026-11-11 23:19:15 UTC |
| `GET /healthz` | `{"status":"ok","version":"2.58.194"}` |
| файл БД | 2 502 549 504 б |
| journal 2 ч до | `ERROR=0`; одна строка, содержащая `Traceback` (не разбиралась — доп. SSH-сеанс не расходовался) |
| свободно на `/` | 45 G (53 % занято) |
| прежние снимки | `/tmp/predeploy-258193.db` 2 421 288 960 б, `/tmp/predeploy-258194.db` 2 441 658 368 б |
| суточный бэкап | `backups/local_database_20261112.db` 2 319 933 440 б (00:00 12.11) |

Сделан штатный снимок данных: `/tmp/predeploy-258195.db` — **2 502 684 672 б**,
`user_version 47`, `quick_check ok`, 325 объектов схемы, 36 с.

## 4. Деплой (один основной SSH-сеанс, без ретраев)

- `git fetch --prune origin` → `origin/release/2.58.195` = `c134f93d` (сверено до checkout;
  при расхождении скрипт прерывается);
- проверено `git merge-base --is-ancestor HEAD c134f93d` (fast-forward возможен);
- `git checkout -B release/2.58.195 c134f93d` → HEAD совпал, tracked-правок 0;
- `APP_VERSION = "2.58.195"`, `web/app.js` blob `33f07dd1`, 2 284 920 б;
- `systemctl restart admin_bot` в **2026-11-12T05:24:29Z**; healthz отдал `2.58.195`
  на второй попытке (~6 с); `ActiveEnterTimestamp=05:24:31Z`, `NRestarts=0`.

## 5. Постдеплой (read-only, окно 05:24:29Z → 05:24:38Z + живые проверки до 05:36Z)

| Проверка | Значение |
|---|---|
| `HEAD` на сервере | `c134f93d5c4a68f0ea906498cb9e0b78fc795f1e` = релиз |
| ветка / tracked-изменения | `release/2.58.195` / 0 |
| `GET /healthz` | `{"status":"ok","version":"2.58.195"}` |
| systemd | `active`/`running`, `NRestarts=0` |
| journal 10 мин (671 строка) | `TRACEBACK=0`, `CRITICAL=0`, `ERROR=0`, `WARNING=1`, `attempt LOST=0` |
| схема живой БД | `user_version 47` |
| отданный `web/app.js` | 200, 2 284 920 б, sha256 `f81d1e07…11cdb0` — совпадает с файлом на диске |

`WARNING` — прежнее фоновое поведение; новых ошибок старта нет.

## 6. Эффективная конфигурация (P0IM-AC-SETTINGS)

Снимки до/после одинаковыми read-only GET'ами (владельческая initData, оба чата),
хеши в `settings-parity-2.58.195.json`:

| Поверхность | sha256 до = после |
|---|---|
| `GET /api/prompts/catalog` (19 семейств, 112 промптов) | `55d4bf80…e6567` |
| `GET /api/prompts/{key}/versions` × 4 (`prompts.meme_image`, `prompts.meme_joke`, `initiative.meme.summary`, `internal.initiative_observer`) | `eeafa543…6ad18` |
| `GET /api/config` (глобальный) | `36ac4f34…d88d5` |
| `GET /api/config/overrides-map` | `cb29eb79…b2056` |
| `GET /api/config` X-Chat-Id, чат A / чат B | `305b38d8…3692` / `fef0e21c…220c` |
| `GET /api/initiative/meme-settings` — сохранённые блоки (settings, prompts, template, image_prefix, length_limit, defaults, quota, delivery, master_key, own_key, day, schema_present) | оба чата **SAME** |

Полный payload `meme-settings` отличается только живыми блоками
`analytics` (лента попыток за минуты), `availability` (обратный отсчёт) и
`generated_at` — это не сохранённые настройки. Ни один сохранённый промпт,
модель или значение не изменился. Версия `2.58.19x` в этих поверхностях не
встречается, поэтому совпадение хешей не маскируется bump'ом.

## 7. Живые проверки на реальных данных (агентские, без сообщений в чаты)

Оба реальных чата: `-1004482340693` (A) и `-1002661910336` (B).
`live-diag-chatA/chatB-2.58.195.json`, `live-ui*.json`, `live-*.png`.

**Обзор (payload + экран).**

- `mechanism-diagnostics` 200 на обоих чатах; `degraded: []`, `data_state: ok`;
  `stale:false`, `stale_reason: window_not_recorded`, `stale_window_seconds: null` —
  «устарело» не выдумано там, где окно не записано;
- условия: `initiative_enabled=true, meme_enabled=true, image_ready=true,
  schema_present=true, cooldown_ready=false`;
- квота: `limit 3, used 1, remaining 2, delivered 1, not_delivered 0`, сброс
  `2026-11-13T00:00:00+00:00`;
- последняя доставка подтверждена: мемы A `#11107`, B `#1210875`; текст A `#10435`, B `#1210123`;
- экран (Playwright, оба чата, 0 ошибок консоли): «Последнее действие: 12.11 05:29 ·
  Текстовая инициатива — пропущено», пояс «пояс чата не задан — UTC (заводское
  значение, не часы сервера)», «снимок: 12.11 05:32 (сервер)», слои решения по
  каждому гейту, «Показать попытку →» присутствует, вхождений «нет данных» на
  карточке — 0;
- вкладка «Мемы»: «Генерации сегодня: 1 / 3 · Осталось: 2 · сброс 2026-11-13T00:00Z ·
  часовой пояс: UTC (utc_fallback)», строка условий `cooldown_ready=нет ·
  image_ready=да · …`, последняя попытка с честной причиной `cooldown_active`.

**Публикации: фильтры, пагинация, retention (`live-checks-2.58.195.json`).**

| Проверка | Результат |
|---|---|
| `kind=meme` | 200, total 298, все строки `kind=meme` |
| `kind=text_initiative` | 200, total 26, все строки `kind=text_initiative` (токен UI — `app.js:4924`; мой предварительный `kind=text` — неизвестное значение, сервер отдаёт пустой набор) |
| `mode=auto` | 200, total 324, все `mode=auto`; `mode=manual` — 0 (ручных попыток в окне нет) |
| `outcome=published` | 200, total 13, все `published` |
| `outcome=deferred` | 200, total 5, все `deferred` |
| `outcome=failed` | 200, total 0 |
| `reason=cooldown_active` | 200, total 92, у всех в `reason_codes` |
| `days=7 / 0 / 90` | total 324 / 440 / 440 (вся история укладывается в 90 дней) |
| `limit=1&offset=0/1/5` | разные `attempt_id`, `next_offset` 1/2/6, total стабилен |
| `days=91`, `limit=0`, `limit=500`, `offset=-1` | 422 с точной причиной валидации |
| retention ≤ 90 дней | самая старая строка окна 90 дней — `age 24.57 дней` |

Счётчики окна (7 дней, чат A): `total/checked/decided 324`, **`generated 1`**,
`published 13`, `delivered 13`, `deferred/pending 5`, `not_delivered 306`,
`llm_calls 2`, `images 1`, `text 26`, `meme 298`. `generated` (доказанная картинка)
не совпадает с `published`/`delivered` — ровно та семантика BAN-CONFLATE.

**Трасса попытки: честные null (`live-detail-2.58.195.json`).**

Цепочка реальной попытки: у шагов `duration_ms: null` + `duration_reason:
step_timing_not_recorded`, `request_id` из записи (`request_id_source:
journal_job_id`), блок `llm` = `provider/model/slot: null`, `recorded_keys: []`,
`reason: not_recorded_in_stage_record`. Нулевых выдуманных длительностей — 0.

**P0IM-OV-SAMPLE (семантика четырёх строк образца, `live-ov-sample-2.58.195.json`).**

1. «Мемы · Разрешено: ВКЛ | Сейчас: пауза N мин» — подтверждено: ось «включено —
   глобальный выключатель», `ready=false`, `ready_reason=cooldown_active`,
   `cooldown.remaining_seconds` (на проверке 4002 с); формулировка отличается,
   семантика совпадает;
2. «Последний запуск: … изображение создано, отправка отложена» — **живого случая
   в текущем окне нет**: единственная попытка мема сегодня — пропуск по кулдауну,
   а 5 `deferred`-строк — текстовая инициатива (этап `precheck`, не картинка).
   Семантика этого случая обеспечена полями `generated`/`delivered` и ветвью UI
   `web/app.js:11113-11117` («генерация успешна, отправка отложена координацией»);
   живое наблюдение — предмет отдельного реального события;
3. «Последняя подтверждённая отправка: … Telegram #1234» — подтверждено
   (`status=confirmed`, `message_id` на обоих чатах);
4. действие «Показать попытку» — кнопка присутствует и включена на обоих чатах;
   detail-эндпоинт возвращает реальную цепочку. Клик по кнопке в живом UI не
   прокликивался (проверен API-путь трассы).

## 8. P0IM-AC-NODUP / P0IM-AC-MATRIX-RBAC

- **NODUP:** в дельте `6c11fc08..c134f93d` нет новых страниц/агентов/планировщиков,
  второго пайплайна мемов и логического хардкода; новых настроек/флагов — 0;
  сохранённые настройки не изменены (§6). Новые файлы — только evidence.
- **RBAC/секреты:** диагностика, публикации и detail сканировались на ключи
  `authorization/x-api-key/password/secret/cookie` и формы токена бота —
  **0 совпадений** (`live-checks-2.58.195.json → secret_scan`). InitData и токен
  в артефакты не попадают.

## 9. Гейт требований (не зелёный — бухгалтерия карты, не продукт)

- `requirements_gate.py check --stage release --candidate 4c2d7ef6
  --deployed-commit c134f93d --strict-evidence` → `errors=217`
  (`stage=release inventory=42 manual=90 scoped=114`), `gate-release-c134f93d.txt`;
- слайс `S2-ID` → `errors=26` (`gate-release-slice-S2-ID.txt`), в том числе
  «map deployed_commit does not match actual deployment» и «no evidence bound to
  reviewed candidate»;
- все ошибки — ведение карты: `candidate_commit`/`deployed_commit` в карте всё ещё
  `6c11fc08`, строки этого поезда (`P0IM-ID-CONC`, `P0IM-PB-VOCAB`, `P0IM-PB-COUNT`,
  `P0IM-PB-STEP`, `P0IM-BAN-CONFLATE`) в карте отсутствуют, прежние привязки не
  перепечатаны на новый кандидат. Гейт не отключался и не «зеленился» вручную.
  Это работа PM/Orchestrator, не дефект продукта.

## 10. Откат

```
git checkout -B release/2.58.194 6c11fc08ddade1edf0c4fb274e7f1bf93f852a26 && systemctl restart admin_bot
```

Данные не откатываются: DDL=0, миграций нет, `user_version 47` до и после;
`/tmp/predeploy-258195.db` (2 502 684 672 б, `quick_check ok`) — страховка.
Последняя заведомо рабочая версия — 2.58.194 (`6c11fc08`).

## 11. Побочное наблюдение (вне приёмочного объёма, pre-existing)

На вкладке «Мемы» время в строке «Последняя попытка» печатается в поясе браузера
(`_tsStatusLabel` → `toLocaleString('ru-RU')`, `web/app.js:1916`), тогда как обзор
печатает время в поясе чата. При незаданном поясе чата (UTC) на устройстве
владельца (UTC+12/13) два блока показывают одно событие с разницей 12–13 часов.
Функция и композиция существуют на `6c11fc08` и этим поездом не менялись —
дефект pre-existing, низкая/средняя важность, влияет только на подпись времени.
Запись для `plans/backlog.md` — за PM (файл на `master` ушёл вперёд, правка в
релизной ветке дала бы конфликт).

## 12. Честные границы

- Журнал и БД перечитывались только в основном сеансе (окно 05:24:29–05:24:38Z);
  дополнительный SSH-сеанс не расходовался (fail2ban-бюджет), длительного
  наблюдения за процессом нет.
- Строка `Traceback` в 2-часовом окне **до** выкладки не разбиралась.
- OV-SAMPLE п.2 не имеет живого экземпляра в текущем окне (см. §7).
- Клик «Показать попытку» в живом UI не прокликивался; проверен detail-эндпоинт.
- Строки `P0IM-PB-LLM` (полный пункт), `P0IM-PB-ACCESS`, `P0IM-PB-MANUAL`,
  `P0IM-S6-EFFECTIVE`, `P0IM-AC-MATRIX-FAIL`, `P0IM-AC-DONE` **не заявляются** —
  остаются открытыми для следующего поезда.
