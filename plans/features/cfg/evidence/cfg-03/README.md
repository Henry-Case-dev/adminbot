# CFG-03 — evidence: аудит всех 579 параметров MiniApp

**Лейн:** CFG-03-BUILD (writer; **без коммита** — на независимое ревью).
**Дата:** 19.10.2026. **База лейна:** `71c12bfe` (F0 CFG-03). **Родительский
HEAD на момент сборки:** `61ecd034` (чужие лейны коммитили во время работы;
мои файлы ими не затронуты). **Кандидат:** рабочее дерево = HEAD `61ecd034`
+ дельта CFG-03 (ниже); прод не трогался, SSH не использовался.

**Источник требований:** `plans/features/cfg/requirements-map.json`
(19 строк слайса CFG-03) + `plans/features/cfg/prep-cfg-03.md` + гейт
`requirements_gate.py`. P0/B06/SOUL-1/CFG-01/02A/02B/02C-эвиденс
**переиспользуется** (prep §2), не перепрогоняется.

---

## 1. Дельта кандидата (файлы)

| Файл | Δ | Содержание |
|---|---|---|
| `services/param_catalog.py` | M (+9/−6) | 5 описаний «мёртвых ручек» → честные («рантайм значение не читает»); ключи/группы/типы/счётчики НЕ менялись |
| `plans/docs/param-registry-round1025.tsv` | M (5 строк) | переэмиссия генератором (описания) |
| `plans/docs/param-registry-round1025.meta.md` | M (HEAD) | переэмиссия генератором |
| `tests/test_round1025_f8_registry.py` | M (+12/−1) | осознанный re-pin `PARAM_CATALOG_SHA256_FOLLOWUP` (`4886ff03…`, L-F11S-1) + документирующий комментарий |
| `tests/test_cfg03_param_audit.py` | new | контракт-тест (16 кейсов): UI-покрытие, consumer-покрытие, согласованность, класс-негативы, пины |
| `tools/cfg03_param_inventory.py` | new | генератор манифеста R1 (inventory.tsv/json + audit-summary.json) |
| `tools/ui_cfg03_descriptions_e2e.py` | new | Playwright e2e честной витрины + `--serve` (Browser Use) |
| `plans/features/cfg/evidence/cfg-03/**` | new | этот пакет |

Δ каталога = 0 (ключи/группы/вкладки/widget'ы не менялись) → процедура §3.4
в режиме «только re-pin SHA» + переэмиссия артефактов; count-pin-файлы не
затронуты. Screen-map — без изменений (в нём нет описаний).

## 2. Ф1 — машинный инвентарь (R1)

`inventory.tsv` (579 строк × 19 колонок цепочки) + `inventory.json`
(детали: consumer-файлы, read-context, dyn-хиты, ссылки на тесты) +
`audit-summary.json` (сводка/находки). Генератор: `tools/cfg03_param_inventory.py`
(один проход по runtime-коду: `bot.py`, `manage.py`, `config/`, `handlers/`,
`services/`, `web/` (+`app.js`/`index.html`/`static JS`), `filters/`,
`scripts/`, `SmartModule/`; комментарии вырезаются).

**Счётные факты кандидата (579 записей):**

| Метрика | Значение |
|---|---|
| REGISTRY / GROUPS / `_TAB_BY_GROUP` / TAB_RULES | 579 / 120 / 118 / 23 |
| Видимость (screen-map) | visible **552** / api-only **25** / hidden **2** |
| Consumer: static runtime | **552** |
| Consumer: dynamic (шаблон+слаг) | **13** (все `limits.relations_*`) |
| Consumer: отсутствует | **14** = 7 видимых документированных «мёртвых ручек» + 7 env-only (6 docker-контур + `media_base`) |
| UI_missing | **0** (552/552 visible имеют место рендера) |
| Записей со ссылками на тесты | **456** |
| Сироты-группы / дубли settings-полей | 0 / 0 |
| env-only потолки вне каталога (CFG-03.7) | 13 имён (см. `audit-summary.json`) |

Базовый (RED-состояние) срез сохранён: `audit-baseline.json`,
`inventory-baseline.tsv` (находки до правок).

### Design (формат манифеста и правила)

* **Формат** — расширение схемы P0A-PERSIST-AUDIT (§3.4 prep): колонки
  `pg_key, title, type, category, group, tab, ui_place, ui_visibility, widget,
  per_chat, settings_field, env_name, storage, read_api, write_api,
  consumer_status, classification, class_note, test_refs` + JSON-детали.
* **«Verified consumer»** — эталон: тест/спай/live; **static grep — только
  кандидат** (prep §5). В манифесте: `consumer_status ∈ {runtime, dynamic,
  none}` + `test_refs` (звено «тест/доказательство»). Колонка TSV
  `runtime_consumer` у 168 новых ключей — шаблон-заглушка, в отчёт НЕ
  подставляется как доказательство (R4).
* **Динамические потребители** — отдельная метка: шаблон
  `f"<head>{var}<tail>"` + литерал середины в том же файле (прецеденты:
  `user_relations._limit`, `llm_client._worker_profile`,
  `mca_exploration.USE_SETTING_KEYS`). 13 RELATIONS-лимитов не «сироты».
* **Политика api-only/hidden**: `hidden` (2 ключа, ADR-1023-2) и `api-only`
  (25 env-only) — документированное отсутствие UI, **не** `UI_missing`
  (REQ-F8-08). `content_media` (tab=None) рендерится **synthetic-группой**
  в окне Модуля 6 (`web/app.js:3154-3159`, `3390-3394`) — проверено e2e.
* **Границы/единицы**: каталог-тип сверяется с семейством factory-дефолта
  `Settings`; 2 расхождения — внешние пины (см. failures.md, deferred).
* **restart/multiprocess**: прод — один процесс; класс-негативы резолвера
  выполнены на in-memory PG-фикстуре (без моков резолвера); рестарт/
  многопроцессность Direct-лимитов — переиспользован P0/CFG-01 эвиденс.

## 3. Ф2/Ф3 — RED → фиксы → GREEN

**RED (база, до правок):** `red-baseline.txt` — 3 падения, все указывают на
доказанные дефекты:
1. `TestConsumerCoverage::test_dead_knobs_honest_descriptions` — 5 видимых
   «мёртвых ручек» описаны как действующие (CFG-03.6);
2. `TestCatalogConsistency::test_settings_field_type_family` — 2 расхождения
   каталог-тип ↔ Settings-дефолт (CFG-03.5);
3. `TestClassNegatives::test_normalize_value_type_classes` — float-каст
   `cooldown` не работал из-за каталог-типа `int`.

**IMPL (минимальные аудит-обусловленные правки):**
* честные описания 5 ключей: `limits.chat_budget_response_ratio`,
  `limits.chat_lock_max_entries`, `limits.dig_year_back_window_days`,
  `limits.youtube_transcript_proxy_locations`,
  `limits.youtube_transcript_proxy_retries` — добавлено «Не влияет:
  значение сохраняется в конфиге, но рантайм его не читает…» (видно в
  карточках MiniApp — e2e);
* `limits.memory_backup_keep` («НЕ действует…») и `keys.random_quantum_provider`
  («Информационное имя…») — уже честные, оставлены как есть;
* типы каталога **не менялись**: int-пины CFG-02B и hot-migration — вне
  write_scope (см. failures.md, R3-deferred); исключения задокументированы
  в тесте (`TYPE_FAMILY_EXCEPTIONS`).

**GREEN (кандидат):** `red-green.txt` — 16/16 новый тест; прогон набора
препа 128 passed; полный бласт (все тесты, импортирующие каталог) —
3652 passed / 3 failed pre-existing.

## 4. Ф4 — бласт-радиус и живые проверки

* `blast-radius.txt` — 115 файлов (все, кто импортирует `param_catalog`) +
  `test_chat_params`/`test_direct_chat`/`test_persistent_throttling`/
  `test_cfg02c_image_isolation`: **3652 passed, 3 failed — все pre-existing**
  (первопричина подтверждена на базовом worktree `71c12bfe`:
  `test_asap7_direct_settings` v35 ×2, `test_summary_publish_integration_round1026`
  ×1 — падают и на базе).
* `py -3 tools/gen_param_registry_round1025.py --check` → OK (579, R17-чисто,
  идемпотентно) — внутри f8-пары (29 passed).
* JS-sweep: `node tests/js/*.js` — **88 файлов, 0 failed**.
* E2E (`e2e-log.json` + `ui/*.png`, Playwright на реальных
  `web/index.html`+`app.js`, `/api/*` — стабы из реального каталога):
  честные описания видны в «Память» и модалках «Ответы в чате»/«Выжимка
  видео»; synthetic `content_media` (Медиа-шара) рендерится; мобильный
  390px без оверфлоу; консоль чистая. **RESULT: PASS.**
* Browser Use (реальный рендер, живой каталог): описания и synthetic-группа
  наблюдались глазами — `ui/05-browseruse-video-modal.png`,
  `ui/06-browseruse-memory-honest.png`.

## 5. Что НЕ делалось (границы слайса)

* Формы/save/dirty/клавиатура/поворот (CFG-04) — не трогались.
* `web/app.js` НЕ менялся (UI-место для UI_missing не потребовалось:
  synthetic-группа уже есть; Δ web = 0).
* Типы 2 ключей (image-freq cooldown, youtube retries) — deferred: их пины
  в тестах чужих слайсов (`test_cfg02b_image_freq_limits.py:266`,
  `test_hot_migration.py:225`), вне write_scope; нужна правка scope или
  отдельный мини-коммит.
* Live preprod-проверки (.4 hot, .6 честность в проде, .11/.12 выборочные
  негативы) — Ф6 (релиз-поезд), в этом лейне не выполнялись; статусы строк
  карты не закрываются этим пакетом (03.10: 100% не объявляется).

## 6. Остаточный риск

* Статический скан — кандидат-уровень (R4): «нет потребителя» для 7 ручек
  подтверждено repo-wide сканом (литералы/поля/env/динамические шаблоны,
  включая JS-витрину и комментарии), но это не live-наблюдение; для 5
  исправленных ключей риск закрыт честной витриной (они и не должны
  влиять).
* `media_base` (env-only, не читается даже docker-контуром) — задокументирован
  в R4-списке; вывод из `.env` — отдельное решение владельца, не требуется
  (api-only, вне UI).
* Динамические потребители (13 RELATIONS) подтверждены шаблоном+слагом;
  live-подтверждение — существующие тесты `tests/test_relations_service.py`
  (в бласте, зелёные).

---

## 7. Переэмиссия снапшота 579 → 582 (CFG-03-WAVE-A, 21.10.2026)

Каталог вырос 579 → **582** (коммит `46303ecd`, CFG-06): +3 тумблера
фактчек-конвейера v2 (`flags.factcheck_wide_context`,
`flags.factcheck_suitability_gate`, `flags.factcheck_pipeline_v2`,
группа `flags_module_factcheck`, вкладка `mod_factcheck`). REMOVED = пусто.

**Метод — идентичен исходному** (§2): инвентарь переэмиссирован тем же
генератором без правок кода/тестов:

```text
py -3 tools/cfg03_param_inventory.py --out plans/features/cfg/evidence/cfg-03
```

(один проход по runtime-коду: `bot.py`, `manage.py`, `config/`, `handlers/`,
`services/`, `web/` + `app.js`/`index.html`/static JS, `filters/`,
`scripts/`, `SmartModule/`; комментарии вырезаются; источник —
`services/param_catalog.py` + реестр-TSV + screen-map). Обновлены:
`inventory.tsv`, `inventory.json`, `audit-summary.json` (в JSON добавлен
блок `_generation` с HEAD/датой/командой — метод зафиксирован в самом
артефакте). `inventory-baseline.*`/`audit-baseline.json` (RED 19.10)
не тронуты; история 579-снапшота — в Git.

**Счётчики на HEAD `e0c11306`** (сверка с F8: `--check` → CHECK OK,
реестр 582 == REGISTRY; `test_cfg03_param_audit.py` → 16 passed):

| Метрика | 579 (19.10) | 582 (21.10) |
|---|---|---|
| REGISTRY / GROUPS / `_TAB_BY_GROUP` / TAB_RULES | 579 / 120 / 118 / 23 | **582** / 120 / 118 / 23 |
| Consumer: static runtime | 552 | **555** (+3) |
| Consumer: dynamic (шаблон+слаг) | 13 | 13 (без изм.) |
| Consumer: отсутствует | 14 | 14 (те же 7 видимых + 7 env-only) |
| UI_missing | 0 | **0** |
| with_test_refs | 456 | **459** (+3) |
| working / runtime_not_consumed | 565 / 14 | **568** / 14 |
| inconsistencies | 3 | 3 (те же документированные: 1 group_category + 2 type-family) |

**Классификация 3 новых флагов — `working` (runtime, static read-context):**

| Ключ | Потребитель (file:line) | Тест |
|---|---|---|
| `flags.factcheck_wide_context` | `services/factcheck_context.py:80` | `tests/test_factcheck_context_cfg06.py` |
| `flags.factcheck_suitability_gate` | `services/factcheck_suitability.py:106` | `tests/test_factcheck_gate_cfg06.py` |
| `flags.factcheck_pipeline_v2` | `services/factcheck_planner.py:70`, `services/factcheck_orchestrator.py:194`; маршрут: `handlers/factcheck.py:515` | `tests/test_factcheck_orchestrator_cfg06.py` |

Все три default OFF (рубильники отката v2-конвейера, включение — за
владельцем после смоука, вне CFG-03). 2 type-family расхождения — внешние
пины тестов чужих слайсов (F2-исправление НЕ входит в CFG-03, backlog,
см. failures.md); 5 честных dead-handle описаний — без изменений.
