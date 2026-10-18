# CFG-02C — evidence: жёсткая изоляция `user_image` ↔ `summary_cover`

**Лейн:** CFG-02C-BUILD (writer; без коммита — на ревью). **Дата:** 19.10.2026.
**База кандидата:** `f7a14994` (master, VISION-UI закоммичен; рабочее дерево
`services/`+`web/` чистое). **Прод:** 2.58.90 — не трогался (SSH не
использовался).
**Источник истины:** `plans/features/cfg/requirements-map.json` (9 строк
слайса CFG-02C) + `plans/features/cfg/prep-cfg-02c.md` + гейт
`requirements_gate.py`.

---

## 1. Design (Ф1)

### 1.1 Таксономия типа потребления (явный параметр, не из промпта)

`services/image_generation.py`:

| Константа | Значение | Кто передаёт |
|---|---|---|
| `CONSUMPTION_USER` | `user_image` | пользовательские пути (`generate_and_send` → legacy/`reserve`) |
| `CONSUMPTION_COVER` | `summary_cover` | все call-sites обложек (явно) |
| `COVER_STAGE_BASE` | `base` | `summary_generator` (Base-обложка), `web/api/summary_test.py`, `cover_style_preview` |
| `COVER_STAGE_STYLED_EDIT` | `styled_edit` | таксономия (стилевой edit бюджет image-контура НЕ тратит — сохраняется) |
| `COVER_STAGE_RETRY_RECOVERY` | `retry_recovery` | таксономия (bounded recovery — без image-бюджета) |
| `COVER_STAGE_FALLBACK` | `fallback` | таксономия (image-fallback — в рамках ОДНОГО списания Base) |

Тип едет **параметром вызова** от call-site до журнала:
`generate_image_verbose(..., consumption_type=CONSUMPTION_COVER, cover_stage=COVER_STAGE_BASE)`
→ `_cover_charge` → `worker_budget.reserve_image(consumption_type=...)` →
журнал `image_reservation.source = "summary_cover:base"`. Из текста промпта или
имени инструмента тип не выводится (§02C.2).

### 1.2 Судьба shared-бюджета (решение и обоснование)

**Решение:** один физический потолок (`WORKER_DAILY_IMAGE_CALLS_GLOBAL`,
scope `global`, метрика `image_calls`) — **общий технический** бюджет обеих
ветвей (L100 прямо разрешает: «провайдер/ключ/баланс/защитный бюджет вправе
ограничивать обе ветки»). Пользовательская метрика `chat:<id>.image_calls`
(ключ `limits.image_daily_limit`) — **только `user_image`**.

Альтернатива «отдельная метрика `image_calls_cover` со своим потолком»
отклонена: она удвоила бы физическую защиту провайдера (200 + 200 вместо
200) и создала бы второй счётчик, что противоречит D6 прецедента A5
(«журнал — источник агрегатов, не второй счётчик»). Разбивка расхода по типам
берётся из **типизированного журнала** (`image_reservation.source`), а не из
второго счётчика.

Следствия (двусторонний негатив):
* обложки **не** повышают `chat:<id>.image_calls` → суточная пользовательская
  квота ими не съедается, витрина `used`/`remaining`/`requests` — только
  пользовательские;
* обложки **не** проходят частотный лимитер (§02B.5 — сохранено) и **не**
  блокируются `limits.image_daily_limit = 0`;
* пользовательская генерация **не** расходует специализированную квоту
  Summary (её нет) и **не** создаёт строк журнала `summary_cover`;
* исчерпание shared-потолка честно называется техническим бюджетом
  (см. §1.4), а не «пользовательской квотой».

### 1.3 Журнал/DDL: Δ DDL = 0 (forward-only)

Тип потребления едет в **существующей** колонке `image_reservation.source`
(enum-пространство `summary_cover:<stage>`; пользовательские строки —
`direct`/`tool`). Аддитивная колонка `consumption_type` **не** вводится:
её PG-only `ALTER` изменил бы пины DDL-счётчиков
(`tests/test_pg_db.py::len(create_tables)==25*2`,
`tests/test_budget_guardrails_round1024.py::len(DDL_STATEMENTS)==54`), которые
вне write_scope слайса, и prep Ф1 ожидает Δ=0. Тип в API/агрегатах
материализуется единым helper'ом `worker_budget.journal_consumption_type(source)`
(один источник правил, без второй копии).

Историчность: старые строки журнала (`direct`/`tool`) — это **и только**
пользовательские генерации (обложки в журнал не писались вовсе) → отображение
в `user_image` корректно, перезаписи истории нет (R4). Forward-only.

### 1.4 Honesty-фикс (carry-over review-cfg-02a §65)

`_reserve_or_consume` больше не схлопывает `limit_global` в `budget`:
отказ по shared-потолку → `reason="shared_budget"` (свежий deny и replay
journaled-отказа `limit_global`). Тексты:
* shared-отказ → «Технический бюджет генераций (общий для всех чатов)
  исчерпан: обновится {stamp} ({WORKER_BUDGET_TZ})» — TZ **shared**, не чата;
* user-отказ → прежняя честная строка суточной квоты (TZ **чата**);
* `capability_registry._FAILURE_CODE_BY_REASON["shared_budget"] =
  "quota_exhausted"` (класс шаблона), §17.2-код события —
  `financial_limit_reached`;
* `image_denial_details` различает источник через detail
  `image_shared_limit` / `image_daily_limit` (одна копия правил —
  `capability_registry._image_quota`).

### 1.5 Жизненный цикл обложки (один платный вызов = одно списание)

Cover-ветка `generate_image_verbose`: `reserve_image(type=summary_cover)`
(только shared-контур) → генерация (bounded retry/shorter-retry/fallback —
внутри одного списания) → `commit_image` (успех) / `release_image` (терминальный
сбой: квота возвращается). Паритет количества списаний с прежним
`_consume_budget` (один раз на вызов), но с типизированным журналом и честным
возвратом при сбое. Kill-switch `IMAGE_DAILY_LIMIT_ENABLED=OFF` / master OFF /
PG-down → **legacy shared-only** списание без журнала (fail-open-паритет;
per-chat контур обложками не трогается **ни в одном** режиме).

`release_image` для cover-строк **не** откатывает per-chat счётчик
(журнал-строка типизирована; иначе откат «одолжил» бы пользовательскую квоту).

### 1.6 UI (§02C.5)

Секция «Лимиты генерации» получает явную подпись «Пользовательские
изображения» + пояснение «Обложки сводок здесь не учитываются» (витрина
группы в `web/app.js` + блок фактов в `web/index.html`). Карточка общего
технического бюджета получает разбивку «в том числе обложки сводок: N» из
типизированного журнала (одно число не выдаётся за другое). Новых
настроек/ключей нет: лимитов обложек не существует (факт, не выдумываем
ключ) → **Δ каталога = 0**, re-pin каталога не требуется.

### 1.7 Что осознанно НЕ меняется

* `services/usage_events.py` — аналитика LLM-событий (`source='image'`)
  остаётся как есть: разбивка по типам живёт в бюджетном контуре
  (журнал+API), это источник истины для квот; новых значений source-домена
  не вводим (Δ=0, пины домена не трогаются).
* Pipeline обложек (base/style/recovery/fallback), идемпотентность, durable
  jobs, `recovery_max_attempts` — не меняются (R1).
* Каталог/сентинелы `limits.image_daily_limit` — не меняются (CFG-02.F).

---

## 2. Файлы, затронутые слайсом (sha256_12, рабочее дерево)

| Файл | sha12 | Что |
|---|---|---|
| `services/image_generation.py` | `ac028768eb86` | таксономия типа, `_cover_charge`/`_cover_settle`/`_generate_image_verbose_inner`, честный `shared_budget` + shared-note |
| `services/worker_budget.py` | `33e7b0eb8779` | типизированный журнал (`journal_consumption_type`), shared-only резерв обложек, cover-разбивка агрегатов, `cover_used` |
| `services/capability_registry.py` | `360c663ee8c5` | `shared_budget` → класс шаблона `quota_exhausted` |
| `services/summary_generator.py` | `c29cd6ee3038` | Base-обложка: `consumption_type=summary_cover`, `cover_stage=base` |
| `services/cover_style_preview.py` | `394c2b10c7f7` | preview Base (Test Style) — стадия `base` |
| `web/api/summary_test.py` | `681bac561fb9` | test-run обложки — стадия `base` |
| `web/app.js` | `44642c5a2b3e` | витринное описание группы «Пользовательские изображения… Обложки сводок здесь не учитываются» |
| `web/index.html` | `94289f4e0932` | подпись секции + пояснение + разбивка общего бюджета по источникам |
| `tests/test_cfg02c_image_isolation.py` | `c76b62e8a29d` | новый CONTRACT/REGRESSION-набор (19 тестов) |
| `tests/test_image_daily_limit_round1026.py` | `931061929a55` | PG-стаб: типизированные агрегаты журнала (user/cover/shared-day) |
| `tests/test_hotfix5_summary_cover_window_round1025.py` | `daa53423cff9` | пин перенацелен на `_cover_charge` |
| `tests/test_asap7_cover_preview.py` | `813c02f98949` | стаб зеркалит сигнатуру (+**kwargs) |
| `tests/test_extra_cover_style_runtime.py` | `63895a4c659b` | стаб зеркалит сигнатуру (+**kwargs) |
| `tools/ui_cfg02c_image_isolation_e2e.py` | `641267a1e601` | Playwright e2e витрины (desktop+mobile 390) |

**Скоуп-примечание (для ревью):** `tests/test_asap7_cover_preview.py` и
`tests/test_extra_cover_style_runtime.py` не перечислены в `write_scope`
графа, но являются прямыми пинами контракта вызова файлов слайса
(`web/api/summary_test.py`, `services/summary_generator.py`): требование
02C.2 (явный параметр типа от call-site) меняет сигнатуру
`generate_image_verbose`, поэтому стабы обязаны её зеркалить (правка
механическая, +**kwargs; поведение тестов не изменено). Без неё 9 тестов
падали бы TypeError'ом. Если Orchestrator/PM предпочтёт иное решение —
правку можно откатить точечно, но тогда требование 02C.2 не выполняется.

Полный список прогонов/бласт-радиуса — `blast-radius.txt`; RED→GREEN —
`red-green.txt`; скриншоты — `ui/*.png`; sha256_12 кандидата — `fingerprint.txt`.

---

## 3. Ревью-чеклист и остатки

**Что НЕ менялось (осознанно, с обоснованием):**

* `services/pg_db.py` — **Δ DDL = 0**: тип потребления едет в существующей
  колонке `image_reservation.source`; аддитивная колонка потребовала бы
  PG-only `ALTER`, а это сдвигает пин-счётчики DDL
  (`tests/test_pg_db.py`, `tests/test_budget_guardrails_round1024.py`) вне
  write_scope слайса. Prep Ф1 ожидал Δ=0.
* `services/usage_events.py` — аналитика (`source='image'`) без изменений:
  разбивка по типам живёт в бюджетном контуре (журнал + API), это источник
  истины для квот; новых значений source-домена не вводим.
* `services/budget_limits.py`, `services/worker_settings.py` — сентинелы и
  резолв-путь не переписывались (CFG-02.F: те же ключи/reserve/journal).
* `services/cover_style_jobs.py`, `services/cover_style_pipeline.py` —
  pipeline обложек (style/recovery/fallback, идемпотентность, durable jobs)
  не изменён; стилевой edit/recovery image-бюджета не тратят (сохранено,
  покрыто spy-негативами).
* Каталог `param_catalog` — Δ = 0 (re-pin не требуется; F8-чек `--check`
  exit=0, 579/120).

**Остатки для ревьюера / релиза:**

1. `CFG-02C.5` помечена `live_required=true, live_when=preprod`: в этом лейне
   доказано детерминированным Playwright-e2e + реальным rendered-просмотром
   (Browser Use, desktop + 390px). **Живая preprod-проверка витрины остаётся
   за релизным лейном (Ф6)** — здесь не заявляется VERIFIED.
2. Live-проверки §Ф6 (user daily=0 + freq ON → Base/Style Edit работают;
   ретрай обложки не меняет user burst; мем не меняет cover-учёт;
   shared-потолок называет истинный источник) — прод/SSH в лейне не
   использовались.
3. Полный прогон `tests/`: **9 failed / 14466 passed** (12:06). Атрибуция:
   5 — `test_t5150_startup_migrations_round1046.py` (SQLite lock-тайминги),
   2 — `test_asap7_direct_settings.py` (миграции v35/backup-guard),
   1 — `test_mca01_tx_task_supervisor_round1027.py` (single writer),
   воспроизведены на **чистом worktree HEAD без диффа**; 1 —
   `test_mca09_intents_block_e_round1040.py::test_candidate_ready_defers_
   intent_backoff` — order-dependent flake общего прогона (в изоляции
   зелёный и в main-дереве, и на чистой базе). Новых падений от CFG-02C нет;
   итог совпадает с baseline окружения (14447/9). Подробно —
   `blast-radius.txt`.
4. Вне-скоупные механические пин-стабы (см. примечание выше) — просьба
   подтвердить или отклонить явно.

