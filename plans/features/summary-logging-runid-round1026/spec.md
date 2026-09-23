# S7 `summary-logging-runid-round1026` — спецификация (Step 2 @Architect, T-3381)

- **Эпик:** 2 «Summary Hybrid Pipeline», Раунд 10.26. **Тип:** backend (логи/телеметрия) + UI (log viewer). **P0.**
- **Источник:** `plans/current_task.md` **§107–§113** (verbatim; файл — только чтение, R17/R18) + `tasks.md` (T-3380…T-3409, вопросы (a)–(i)).
- **Статус:** Proposed → Accepted по T-3406. **ADR:** `adr-1026-9-summary-runid-logging-logviewer.md` (D1–D8).
- **Зависит от:** S5 (§76, MERGED, deploy 2.58.24 VERIFIED) и S9 (§77, MERGED, deploy 2.58.25). Ядро S7 **верифицируемо без S6**.
- **Гейт D4 (ADR-1025-24):** `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` **GATED** вместе с S6 — **не реализуются** в S7.

## 1. Область и исключения

**Входит:** сквозной `run_id`; события `SUMMARY_*`/`FILTER_*`/`RESTORE_*`/`L1_*`/`L2_*`/`FORMAT_*`/`COVER_*` (аддитивно, R17); поля §109; единый формат ошибок §109; §110-фильтр Саммари в существующем log viewer; связка с `llm_usage_events`; dry-run S9 с `run_id`.

**Не входит (границы):** публикационные события `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` и §109 publish-детали (S6/D4 — GATED); узлы/визуализация ExecutionGraph (§111 — S8); вторая система логирования для dry-run (§113 — S9, переиспользуется); изменение публикации, §104, обложки (`generate_image`/модель/провайдер/промпт/порядок), XML, промптов Редактора/Рассказчика; изменение `web/api/routes.py` (log viewer — клиентский фильтр).

## 2. Трассируемость REQ → SC

| REQ | §ТЗ | SC |
|---|---|---|
| REQ-S7-01 | §108 run_id на запуск, все этапы | SC-01, SC-02 |
| REQ-S7-02 | §108 список событий (без PUBLISH_*) | SC-03…SC-06 |
| REQ-S7-03 | §108 PUBLISH_RICH/TEXT_* | SC-15 (GATED) |
| REQ-S7-04 | §109 FILTER_COMPLETE поля | SC-03 |
| REQ-S7-05 | §109 L1/L2_COMPLETE поля | SC-04, SC-05 |
| REQ-S7-06 | §109 COVER_COMPLETE (статус/длительность) | SC-06 |
| REQ-S7-07 | §109 PUBLISH_* поля | SC-15 (GATED) |
| REQ-S7-08 | §109 ошибки; запрет «Ошибка Саммари» без деталей | SC-07, SC-08 |
| REQ-S7-09 | §110 фильтр/раскрытие/копирование | SC-09, SC-10 |
| REQ-S7-10 | §112 источник токенов/стоимости; `correlation_id` | SC-11 |
| REQ-S7-11 | R17/Δ DDL=0/Δ каталога=0/CSP/R18 | SC-12 |
| REQ-S7-12 | §107 deploy/bump | SC-16 |
| REQ-S7-13 | §111/§100–§106/§113 границы | SC-13…SC-15 |

## 3. Наблюдаемое поведение и отказы

- Живой путь (`_run`) и ON-ветка (`_run_hybrid_l2`) логируют жизненный цикл и каждый этап **с одним** `run_id`; при любом исходе (успех/пусто/деградация/ошибка) исход различим.
- Ошибка любого этапа логируется с деталями §109 и **никогда** не маскируется под успех; строка «Ошибка Саммари» без деталей запрещена.
- Ошибка логирования не влияет на пайплайн (best-effort, fail-open для логирования).
- В логах/UI — только числа/коды/id/host/HTTP-статус/тип ошибки/причина/попытки; секреты маскирует существующий `sanitize()`; сырые тексты/промпты/ответы LLM/ключи не выводятся.

## 4. D1 — сквозной `run_id`

- **Формат:** UUID4 hex (32 симв.), **тот же**, что существующий `correlation_id` (`services/usage_events.py:62 new_correlation_id()`). Второй идентификатор **не вводится** — «`run_id` = `correlation_id` прогона».
- **Точка создания (ровно одна на прогон):** живой путь — `services/summary_generator.py:348` (`_run`); dry-run S9 — `services/summary_test_run.py:495` (`run_summary_test`). `_run_hybrid_l2`/`run_l1`/`build_fact_package`/`run_l2`/форматтер/обложка получают его **параметром**, не создают.
- **Проброс:** `_run → _apply_filter → _restore → _run_hybrid_l2 → run_l1 → build_fact_package → run_l2 → _deliver_l2_* (форматтер/обложка)`. Существующие `run_id=%s` в `FILTER_*`/`RESTORE_*`/`L1_*`/`L2_*`/`TEST_*` уже используют `correlation_id` — **совместимо**, новых полей-дублей нет.
- **Публикация** (`PUBLISH_*`) — GATED (D2/D6), `run_id` для неё зарезервирован, не реализуется.
- Новые `SUMMARY_START`/`SUMMARY_COMPLETE`/`SUMMARY_FAILED` несут `run_id` (п.5).

## 5. D2 — каталог событий §108/§109 (точные имена/поля)

**Жизненный цикл (новые, `_run`/`_run_hybrid_l2`):**

| Событие | Поля (R17-safe) |
|---|---|
| `SUMMARY_START` | `run_id`, `chat_id`, `mode` (`off`\|`hybrid_l2`), `manual`, `source_count` (если известен), `has_trigger` |
| `SUMMARY_COMPLETE` | `run_id`, `chat_id`, `mode`, `status` (`ok`\|`empty`\|`degraded`), `duration_ms`, `source_count`, `saved_count`, `restored_count`, `threads`, `paragraphs`, `cover_status` |
| `SUMMARY_FAILED` | `run_id`, `chat_id`, `stage`, `model`, `provider`, `http_status`, `error_type`, `reason`, `attempts` |

**Этапные (переиспользование существующего формата; поля аддитивны):**

| Событие | Поля |
|---|---|
| `FILTER_START` | `run_id`, `chat_id`, `source_count` (уже есть) |
| `FILTER_COMPLETE` | `run_id`, `chat_id`, `source_count`, `saved_count`, `restored_count`, `drop_percent`, `status`, `duration_ms` (уже есть) |
| `FILTER_ERROR` / `FILTER_EMPTY_FALLBACK` | `run_id`, `chat_id`, `source_count`, `duration_ms` (уже есть) |
| `RESTORE_START/COMPLETE/ERROR` | `run_id`, `chat_id`, `status`, `restored_count`, `parent_count`, `neighbor_count`, `skipped_count`, `budget_*`, `duration_ms` (уже есть) |
| `L1_START/COMPLETE/ERROR` | `run_id`, `chat_id`, `provider`, `model`, `tokens_in`, `tokens_out`, `tokens_estimated`, `threads`, `facts`, `chunks`, `auto_unassigned`, `skipped`, `truncated`, `status`, `invalid_reason`, `duration_ms` (уже есть) |
| `L2_START/COMPLETE/ERROR/SKIPPED` | `run_id`, `chat_id`, `provider`, `model`, `tokens_in`, `tokens_out`, `paragraphs`, `reason`, `duration_ms` (уже есть) |
| `FORMAT_START` **(новое)** | `run_id`, `chat_id`, `channel` (`rich`\|`plain`) |
| `FORMAT_COMPLETE` **(новое)** | `run_id`, `chat_id`, `channel`, `paragraphs`, `status`, `duration_ms` |
| `FORMAT_ERROR` **(расширить)** | + `run_id`, `reason` (сейчас `chat_id`, `channel`) |
| `COVER_START` **(новое)** | `run_id`, `chat_id`, `provider` |
| `COVER_COMPLETE` **(новое)** | `run_id`, `chat_id`, `status` (`ok`\|`unavailable`), `duration_ms` |
| `COVER_ERROR` **(новое)** | `run_id`, `chat_id`, `provider`, `error_type`, `reason`, `duration_ms` |

**GATED (не реализуется):** `PUBLISH_RICH_START/COMPLETE/ERROR`, `PUBLISH_TEXT_START/COMPLETE/ERROR` (§108/§109 publish-поля — S6/D4).

**Тест-контур (dry-run S9, существующие):** коды `TEST_*` + `SUMMARY_TEST_*` (уже с `run_id`); этапные `L1_*`/`L2_*`/`FORMAT_*` переиспользуются с тем же `run_id`; `SUMMARY_START/COMPLETE/FAILED` **не** эмитятся (чтобы не смешивать тест с прод-жизненным циклом).

**§111/S8-примечание (не дублировать):** для будущих узлов ExecutionGraph переиспользуемы `run_id`, этап/`kind`, `provider`, `model`, `tokens_in/out`, `duration_ms`, `status`, `cost` (из `llm_usage_events`). S7 узлы **не создаёт**.

## 6. D3 — хранилище/DDL: **Δ DDL = 0**

- **События** → существующий ring-buffer `services/log_ring.py` (`LOG_RING_MAX_ENTRIES`, дефолт 1000) + файловые логи. Retention **не меняется**.
- **Токены/стоимость (§112)** → существующая `llm_usage_events` (PG; `module='summary'`, `step ∈ {l1_clusterizer,l2_writer}`), ключ корреляции — `correlation_id`=`run_id`. Новых таблиц/колонок/индексов **нет**.
- **Сбор контекста прогона** (T-3386) — in-memory/существующие структуры (`_filter_metrics`), без новой таблицы.
- Новый DDL/таблица не запрашивается; при подтверждённой необходимости Builder возвращает @Architect (санкция), не вводит самовольно.
- Известное ограничение (follow-up, не блокер): dedicated-слот L1/L2 (`_post`) не пишет analytics (`R-R1026S3-1`) → токены/стоимость «Нет данных»; вынести в S8/S6.

## 7. D4 — §110 log viewer (Mini App, F11 §20)

- **Механизм — клиентский** (без нового endpoint, `web/api/routes.py` вне diff): переключатель/чип **«Саммари»** в существующем viewer (`web/app.js:9457–9607`). При активации: `logLevel → 'INFO'` (чтобы INFO-события были видны) и фильтрация уже загруженного `this.logs` по маркерам Саммари (`SUMMARY_`, `FILTER_`, `RESTORE_`, `L1_`, `L2_`, `FORMAT_`, `COVER_`, `TEST_`, `run_id=`).
- **Раскрытие/копирование** — существующие (`expanded`, `logText`, `copyLogRow`) **сохраняются**; новых действий нет.
- **Ошибка** показывается понятной формулировкой из кода события (`L1_ERROR` → «Саммари: ошибка кластеризации»; `L2_ERROR` → «Саммари: ошибка генерации статьи»; `FORMAT_ERROR`/`COVER_ERROR` — аналогично), с раскрытием `run_id`/время/модель/причина/подробности (из текста строки).
- **Обоснование «без неоправданного усложнения»:** backend-параметр `?source=summary` потребовал бы diff `routes.py` и дублирование логики; клиентский фильтр аддитивен, CSP/zero-build соблюдён.
- Уровне-фильтр, счётчики `counts` и столбцы/viewer не ломаются.

## 8. D5 — dry-run S9

- Тест-контур сохраняет инвариант **0 публикаций / 0 памяти / 0 `generate_image`**; `PUBLISH_*` не эмитятся.
- `run_id` в dry-run — существующий `correlation_id`/`test_id` (`summary_test_run.py:495`); этапные события несут его; ошибки — `TEST_*` с §109-деталями.
- Второй контур логирования не создаётся — переиспользуются те же этапные логгеры.

## 9. D6 — fail-closed и ошибки

- Каждый этап имеет `*_ERROR`-ветку; `SUMMARY_FAILED` эмитится при провале этапа (после `SUMMARY_START`, вместо `SUMMARY_COMPLETE`).
- Единый helper ошибок §109: `run_id, stage, model, provider(host), http_status, error_type, reason, attempts`. `provider` — **host** (`provider_host()`), не полный URL/ключ.
- Недоступность лог-стора (ring/файл) → логирование best-effort, **не** прерывает и **не** искажает пайплайн.
- R17: без секретов/промптов/сырых текстов/сырых ответов; маскировка — `sanitize()`; запрещена голая «Ошибка Саммари».

## 10. D7 — инварианты

- **Δ DDL = 0**; **Δ каталога = 0** (`param_catalog.py` вне diff; новых ключей/env нет); **CSP/zero-build**; 0 новых внешних зависимостей; **R18** (бэкапы/теги не удалять).
- **R17/R18** соблюдены (п.9).
- **2-вызовность не нарушена:** логирование добавляет 0 LLM-вызовов (`await_count==2` в живом и dry-run пути).
- **§104/обложка не тронуты:** только аддитивные `COVER_*`-строки; `generate_image`/модель/провайдер/ключ/промпт/порядок — без изменений.
- **«OFF/legacy байт-в-байт»:** инвариант относится к **поведению и артефактам** (возвраты, число/состав LLM-вызовов, публикация, XML, файлы) и к неизменности тела OFF-ветки по смыслу. **Аддитивные лог-строки разрешены на всех путях** (это прямое требование §108 «все этапы логируются»); это документированное уточнение, а не изменение поведения.
- **Δ каталога=0** — F8 **не переиздаётся** (ADR-1026-2 не запускается).

## 11. D8 — deploy / bump

- **Deploy = ДА; bump `APP_VERSION` 2.58.25 → 2.58.26** + `README.md` (`test_app_version_matches_readme`) + cache-bust: меняются рантайм-модули и наблюдаемые логи/UI.
- **hot-OFF не требуется:** события аддитивны и не меняют поведение; откат — annotated-тег `pre-round1026-s7` + `git revert`. Альтернатива **NOT_APPLICABLE** отклонена (рантайм/UI меняются → рассинхрон прод/master).

## 12. Приёмочные сценарии (SC)

- **SC-01:** на прогон ровно один `run_id`; каждая этапная строка содержит его; второй идентификатор не создаётся.
- **SC-02:** `SUMMARY_START`/`SUMMARY_COMPLETE`/`SUMMARY_FAILED` различимы; пустое окно → `SUMMARY_COMPLETE status=empty`; сбой → `SUMMARY_FAILED` с §109-деталями.
- **SC-03:** `FILTER_COMPLETE` несёт исходные/сохранённые/восстановленные/процент отсева/длительность.
- **SC-04:** `L1_COMPLETE` несёт провайдера/модель/tokens_in/tokens_out/темы/длительность.
- **SC-05:** `L2_COMPLETE` несёт провайдера/модель/tokens_in/tokens_out/абзацы/длительность.
- **SC-06:** `FORMAT_START/COMPLETE/ERROR` и `COVER_START/COMPLETE/ERROR` присутствуют; `COVER_COMPLETE` — статус/длительность; 0 новых LLM-вызовов.
- **SC-07:** каждая `*_ERROR`-ветка содержит `run_id/stage/model/provider/http_status/error_type/reason/attempts`; «Ошибка Саммари» без деталей отсутствует.
- **SC-08:** R17-тесты: нет ключей/промптов/сырых текстов/ответов в событиях и UI.
- **SC-09:** §110-фильтр «Саммари» работает; уровне-фильтр/счётчики не сломаны.
- **SC-10:** раскрытие и копирование строки сохранены; ошибка показывает `run_id/время/модель/причину/подробности`.
- **SC-11:** события коррелируют с `llm_usage_events` по `run_id`; источник токенов/стоимости не дублируется.
- **SC-12:** Δ DDL=0, Δ каталога=0, CSP/zero-build, R18 подтверждены.
- **SC-13:** OFF/legacy-путь по поведению/артефактам неизменен; 2-вызовность; §104/обложка/XML вне diff.
- **SC-14:** dry-run — 0/0/0 и `run_id`; второй контур не создан.
- **SC-15:** `PUBLISH_*` отсутствуют в diff (GATED); S8-узлы не создаются; S9 переиспользует контур.
- **SC-16:** bump 2.58.26 + `README.md` + cache-bust; откат `pre-round1026-s7`/`git revert`.

## 13. Зависимости

S5 (§76), S9 (§77) — поставлены. Внешние сервисы не требуются. S6/S8/S10 — вне S7 (границы).

## 14. Стратегия тестов/деплоя/отката

- **Тесты:** unit на `run_id` и события; покрытие `*_ERROR` каждого этапа; R17-тесты; JS-маркеры §110-фильтра; регресс полного pytest ≥ baseline, JS зелёные, `git diff --check`=0, Δ DDL=0, Δ каталога=0.
- **Деплой:** минимальные §114-тесты; bump 2.58.26; `/api/health` 200; `database is locked`=0; подтвердить, что публикационный путь не изменён.
- **Откат:** annotated-тег `pre-round1026-s7` + `git revert`; hot-OFF не требуется.

## 15. Закрытие вопросов (a)–(i)

(a) D2 (каталог/поля) · (b) D3 (Δ DDL=0) · (c) D1 (UUID4 hex = `correlation_id`) · (d) D3 (retention без изменений) · (e) D8 (2.58.26, hot-OFF не нужен) · (f) D2/S8-примечание · (g) D1/D5 (точки `SUMMARY_*` — живой путь; dry-run — `TEST_*`) · (h) D4 (клиентский фильтр) · (i) `COVER_*` не GATED, §104 не затронут (D2/D7).
