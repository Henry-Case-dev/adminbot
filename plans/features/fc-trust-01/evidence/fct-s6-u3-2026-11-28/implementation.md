# FCT-S6 U3 — панель и API сводных показателей (Builder, 28.11.2026)

Ветка: `feat/fct-s6-u3-aggregate-api-2026-11-28`
База: выложенный **`3a78484b92a6f3ba1273360e4a34de396dcf52f1`** (2.58.271, схема v50).
Продуктовый кандидат (до evidence-коммита):
**`f6cd011e0ef73fdce9633185f7b2889c2bf7e3fe`**.

Вход: `plans/features/fc-trust-01/evidence/fct-s5-s6-scoping-2026-11-28/
scoping.md` §S6 + `decisions.md`; приёмка
`.../fct-s7-acceptance-2026-11-28/acceptance.md` sha `208dc68a…` (§3 FCT-901/903/194,
§3 FCT-316).

---

## 1. API

`GET /api/factcheck/temporal/aggregate` в существующем `web/api/routes.py`:

* RBAC — global admin (тот же `_ctx_global_admin`, что у
  `/api/factcheck/temporal/runs`); без initData — 401, не-admin — 403;
* query: `since`/`until` (unix, `ge=0`), `limit` 1..100 (по умолчанию 100);
  `since > until` → 422;
* тело — ровно `temporal_factcheck.summarize_factcheck_aggregates`
  (S6-U2): `runs`, `execution_status`, `execution_cause`,
  `snippet_only_share`, `date_unknown_share`, `verdict_mismatch_share`,
  `entity_collision_share`/`media_partial_share` (честно `null`), `period`,
  `truncated`;
* никаких секретов/текстов: ответ — только числа/доли/null (тест с
  sentinel-claim в БД проверяет отсутствие `SECRET-CLAIM-TEXT`, URL, ключей).

## 2. Пин routes (осознанный re-pin)

```
было:  b8f63355495c388a4240f9a96a0bebc3f1a99af663a7883ddfc4ab352a13c78a
стало: 5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf
```

`ROUTES_SHA256_F11` обновлён в `tests/test_round1025_f8_registry.py`;
`routes-инвентарь f8_baseline.json` переиздан (+1 путь). Diff `routes.py` —
**только** добавление нового endpoint (см. `git diff`); других правок тела
нет. Пин-тесты зелёные: `test_routes_file_unchanged`,
`test_routes_set_unchanged`, `test_routes_sha256_f11_intact`.

## 3. UI (существующая вкладка «Временной фактчек»)

`web/app.js` + `web/index.html`, минимально:

* state `temporalAggregate` (+ busy/at/scope/epoch);
* `loadTemporalAggregate(force)` → существующий `this.api(...)`, кэш 30 с,
  scope-guard как у runs, fail-open → null;
* компактная строка `temporalAggregateText()` под заголовком карточки:
  прогоны, распределение статусов, доли; отсутствующий сигнал подписан
  «не измеряется» (не 0);
* кнопка ⟳ существующей карточки обновляет и runs, и сводку.

Живой Playwright-сценарий не выполнялся: MiniApp-страница требует
Telegram initData/авторизованную сессию, которой в этом контуре нет.
Проверка — структурная (наличие состояния/лоадера/блока/подписи) +
`node --check web/app.js` (Node v24, exit 0); это честно ограничение, а не
«визуально проверено».

## 4. Заводской флаг v2

`config/settings.py`: `FACTCHECK_PIPELINE_V2_ENABLED` factory-default
**True** (правило проекта 09.11.2026). Приоритет не менялся:
hot/PG `flags.factcheck_pipeline_v2` → env → factory. Тесты:
`test_factory_default_v2_is_enabled` (AST-литерал завода) и
`test_hot_override_preserved` (сохранённый hot/PG-выбор False не
перезаписывается; default ведёт к True). PG не мигрировал и не сбрасывался.
Docstring `pipeline_v2_enabled` обновлён под новое заводское значение.

Следствие для тестов legacy-пути: файлы, проверяющие legacy handler/медиа,
явно фиксируют v2 OFF (`_pipeline_v2_enabled → False`); эти тесты не
меняли смысл. `test_factcheck_planner_cfg06` обновлён: factory ON +
явный OFF-рубильник по-прежнему возвращает None.

## 5. RED / GREEN

Новый `tests/test_fc_trust_s6_aggregate_api.py` — **9 тестов** (API 4,
UI 2, factory 2, routes-pin 1).

| Прогон | Результат | raw |
|---|---|---|
| новый файл на базе `3a78484b9` | **7 failed / 2 passed** (endpoint/pin/UI/factory отсутствуют; node-check и hot-override проходят) | `raw/red-base-3a78484b9.txt` |
| новый файл на кандидате | **9 passed** | `raw/green-api.txt` |
| обязательный набор (api + aggregates + run_link + p0_fc + verdict + registry + pin + mca20) | **144 passed** | `raw/green-mandated.txt` |
| широкий (все `*factcheck*` + `test_cfg07*` + `test_fc_trust_*` + bgs01 + evol-style + registry + mca20) | **1248 passed** | `raw/green-broad.txt` |

## 6. Дельта строк (предложение; карту не правил)

| req_id | было → стало | evidence.ref | остаток |
|---|---|---|---|
| FCT-901 | PENDING/REVIEW → **REVIEW** (агрегаты доступны через global-admin API + блок панели) | §1/§3/§5 | live-проверка на проде после деплоя |
| FCT-902 | REVIEW → **REVIEW** | — | расширенные стадийные поля — вне U1/U3 |
| FCT-903 | REVIEW → **REVIEW** (счётчики показаны; без durable-сигнала — null) | §1/§3 | `entity_collision`/`media_partial` требуют сохранения сигнала; live |
| FCT-904 | PENDING → **REVIEW** (legacy-run + панель; полный перечень запрещённого — S6-U3 не входил) | §5 | тест-инвентарь публичных путей — отдельный шаг |
| FCT-905 | PENDING | — | тест «ключи/сырой чат не попадают» — вне этого юнита |
| FCT-316 | PENDING → **REVIEW** (factory ON, overrides сохранены) | §4 | подтверждение effective на проде — после деплоя |
| FCT-194 | PENDING → **REVIEW** (панель получает данные) | §1/§3 | живая проверка на проде |

## 7. Границы

* DDL нет (схема v50), новых таблиц/LLM-стадий/флагов нет;
* `factcheck_prompts.py` не менялся;
* изменены: `web/api/routes.py` (только endpoint), `web/app.js`,
  `web/index.html`, `config/settings.py` (только литерал), docstring
  orchestrator, тесты/фикстуры/пин.

## 8. Артефакты `raw/`

`red-base-3a78484b9.txt`, `green-api.txt`, `green-mandated.txt`,
`green-broad.txt`.

---

## RV-S6U3-01 (review r1, IN_SCOPE) — второй пин `test_mca23`

**Причина:** осознанный re-pin `routes.py` был обновлён в каноне
`tests/test_round1025_f8_registry.py` и новом тесте, но не в существующем
guard `tests/test_mca23_planned_vs_actual.py::TestResponseEndpoints::
test_routes_pin_untouched` — там оставался старый `b8f63355…`; на кандидате
guard падал.

**Фикс (минимальный):** обновлена захардкоженная константа только в
`tests/test_mca23_planned_vs_actual.py`:
`b8f63355…` → **`5c20750a0a273651600a2baf1fe0a74a842585742af1e1a846cf1f8ecff79bdf`**
(фактический sha256 `web/api/routes.py`, перепроверен). Выбран вариант
«обновить константу», а не dedup-импорт канона, чтобы guard оставался
независимой копией и на базе доказуемо падал при другом sha; канон —
`f8_registry`. `routes.py` не менялся (`5c20750a…`).

* Тестовый файл sha256: **`a155eb35e6737f1bf9c72c2e09ec8097f60ce189d4c73639baa37d72c2e32510`**
* diff — одна константа + комментарий (см. `git diff`/raw).

**Проверка guard на базе (доказывает, что пин реально сторожит):**
на чистом `3a78484b9` с этим обновлённым тестовым файлом
`test_routes_pin_untouched` **падает**: ожидается `5c20750a…`, фактический
sha базы — `b8f63355…` (`raw/rv-base-pin-fails.txt`).

**Пять обязательных прогонов на кандидате (`raw/rv-five-per-file.txt`,
`raw/rv-five-runs.txt`):**

```
tests/test_mca23_planned_vs_actual.py        => 24 passed
tests/test_round1025_f8_registry.py          => 29 passed
tests/test_fc_trust_s6_aggregate_api.py      =>  9 passed
tests/test_fc_trust_s6_aggregates.py         =>  9 passed
tests/test_factcheck_p0_fc.py                => 37 passed
combined                                     => 108 passed, 0 failed
```

