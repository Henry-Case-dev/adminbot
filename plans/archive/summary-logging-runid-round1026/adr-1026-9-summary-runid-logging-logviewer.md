# ADR-1026-9 — S7 «Логирование Саммари»: сквозной `run_id`, каталог событий §108/§109, §110-фильтр в существующем log viewer, Δ DDL=0

- **Статус:** ✅ **Accepted** (Step 2 @Architect, 24.09.2026 — Proposed; финализирован **T-3406** при Merge `plans/ARCHITECTURE.md` **§78**: merge + deploy T-3408 **VERIFIED** (`APP_VERSION` **2.58.26**), 24.09.2026)
- **Фича:** S7 `summary-logging-runid-round1026` (Эпик 2, шаги «Логирование» §108–§110)
- **Тип:** backend (логи/телеметрия, аддитивно) + UI (Mini App log viewer, zero-build)
- **Связано:** **ADR-1026-5/-6/-7/-8** (S3/S4/S5/S9 — модули/контуры, REUSE); **ADR-1025-24 D4** (публикационный гейт S6/S10 — governed-by); **ADR-1026-1/-4** (S1/S2 логи, REUSE); **ADR-1022-4/1023-6/1023-7** (2-вызовность/`correlation_id`, REUSE); §104 (обложка) — REUSE read-only; §106 (fail-closed) — REUSE; §111 (ExecutionGraph) — boundary S8
- **Baseline (заявлено; подтверждает @DevOps T-3380):** HEAD `59e5b12` == `origin/master`, `APP_VERSION` 2.58.25, pytest `.venv` 8854/0, JS 44/44, каталог 469/426/444/100/98/21, Δ DDL=0 (SQLite v12)

## Контекст

§108 требует: «Каждый запуск Саммари получает `run_id`. Все этапы логируются с этим идентификатором» + перечень событий. §109 задаёт поля по каждому `*_COMPLETE` и обязательные детали ошибки, запрещая голую «Ошибка Саммари». §110 требует использовать **существующий** log viewer внизу Статуса и добавить фильтр по событиям Саммари, «если это не требует неоправданного усложнения», сохранив раскрытие и копирование.

Факты кода: `_run` уже создаёт сквозной `correlation_id = usage_events.new_correlation_id()` (UUID4 hex, `summary_generator.py:348`) и передаёт его в `_apply_filter`/`_restore`/`_run_hybrid_l2`/`run_l1`/`build_fact_package`/`run_l2`; события `FILTER_*`/`RESTORE_*`/`L1_*`/`L2_*` **уже** пишут `run_id=<correlation_id>`. Отсутствуют: жизненный цикл `SUMMARY_*`, `FORMAT_START/COMPLETE` (есть только `FORMAT_ERROR`-даунгрейд), `COVER_*`. Токены/стоимость уже учитываются в `llm_usage_events` (PG) по `correlation_id`. Log viewer читает `GET /api/status/logs` (`routes.py:1671`) из ring-buffer (`log_ring.py`, `sanitize()` маскирует секреты).

Открытые вопросы Step 1 (a)–(i): список событий/полей; новая PG-таблица/DDL; формат `run_id`; retention; deploy/bump; граница S8; точки `SUMMARY_*`; механизм §110-фильтра; статус `COVER_*`.

## Решения

**D1. `run_id` = существующий `correlation_id` (UUID4 hex); одна точка создания на прогон.**
- Второй идентификатор не вводится: живой путь — `summary_generator.py:348`; dry-run — `summary_test_run.py:495`. Все этапы получают его **параметром**; дублей нет. Публикация (GATED) зарезервирована, но не реализуется.
- Альтернатива «отдельный короткий `run_id`» отклонена: ломает существующую корреляцию с `llm_usage_events` (§112) и создаёт второй id без выигрыша.

**D2. Каталог событий §108: переиспользуем существующий формат, добавляем `SUMMARY_*`/`FORMAT_START/COMPLETE`/`COVER_*`; `PUBLISH_*` — GATED.**
- Существующие `FILTER_*`/`RESTORE_*`/`L1_*`/`L2_*`/`TEST_*` сохраняются (аддитивны); новые `SUMMARY_START/COMPLETE/FAILED` (жизненный цикл), `FORMAT_START/COMPLETE` (+`run_id/reason` в `FORMAT_ERROR`), `COVER_START/COMPLETE/ERROR`. Поля — §109 (см. spec §5).
- `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` **не реализуются** (S6/D4) — только перечислены как GATED.
- Для S8: переиспользуемы `run_id`, этап/`kind`, `provider`, `model`, `tokens_in/out`, `duration_ms`, `status`, `cost`; узлы S7 не создаёт.
- Альтернатива «новые параллельные имена событий» отклонена: дублирование и разрыв существующих логов.

**D3. Телеметрия: Δ DDL=0 — новых таблиц/колонок нет.**
- События → ring-buffer + файловые логи (retention `LOG_RING_MAX_ENTRIES` не меняется); токены/стоимость → существующая `llm_usage_events` по `run_id`. Сбор контекста прогона — in-memory. При подтверждённой необходимости — вернуть @Architect (санкция), не вводить самовольно.
- Известный follow-up: dedicated-слот не пишет analytics (`R-R1026S3-1`) → «Нет данных» (S6/S8).

**D4. §110: клиентский фильтр в существующем viewer; без нового endpoint и без diff `routes.py`.**
- Переключатель/чип «Саммари» (`web/app.js:9457–9607`): активирует `logLevel='INFO'` и фильтрует загруженные `this.logs` по маркерам Саммари; раскрытие/копирование — существующие; ошибка показывается понятной формулировкой + `run_id/время/модель/причина/подробности`.
- Альтернатива «backend query-параметр `?source=summary`» отклонена: требует diff `routes.py` и дублирования логики — «неоправданное усложнение» (§110).

**D5. Dry-run S9 сохраняет 0/0/0 и получает `run_id`.**
- Тест-контур не эмитит `SUMMARY_*`/`PUBLISH_*`; коды `TEST_*` + этапные события с тем же `run_id`; второй контур логирования не создаётся.

**D6. Fail-closed и единый формат ошибок §109.**
- `*_ERROR` у каждого этапа + `SUMMARY_FAILED` при провале; helper: `run_id/stage/model/provider(host)/http_status/error_type/reason/attempts`; `provider` — host, не URL/ключ; недоступность лог-стора не прерывает пайплайн; голая «Ошибка Саммари» запрещена; R17 (без секретов/промптов/сырых текстов/ответов).

**D7. Инварианты.**
- **Δ DDL=0**; **Δ каталога=0** (`param_catalog.py` вне diff; новых ключей/env нет; F8 не переиздаётся); **CSP/zero-build**; 0 новых зависимостей; **R17/R18**.
- **2-вызовность** сохранена (0 новых LLM-вызовов); **§104/обложка** — только аддитивные `COVER_*`, модель/провайдер/ключ/промпт/порядок не тронуты.
- **«OFF/legacy байт-в-байт»** уточняется как неизменность **поведения/артефактов** (возвраты, число/состав LLM-вызовов, публикация, XML, файлы) и смысла OFF-ветки; **аддитивные лог-строки разрешены** на всех путях (прямое требование §108). Это документированное уточнение (ограничение ТЗ разрешает выбор), санкция владельца не требуется.

**D8. Deploy = ДА; bump `APP_VERSION` 2.58.25 → 2.58.26.**
- Меняются рантайм-модули и наблюдаемые логи/UI → маркер версии обязателен: bump + `README.md` + cache-bust; перед деплоем — §114-тесты; подтвердить, что публикационный путь не изменён.
- **hot-OFF не требуется** (события аддитивны, поведение не меняют); откат — annotated-тег `pre-round1026-s7` + `git revert`. Альтернатива **NOT_APPLICABLE** отклонена: оставила бы прод/master рассинхронизированными.

## AMEND / REUSE-карта

| Ранее | Действие | Что именно |
|---|---|---|
| **ADR-1026-5/-6/-7/-8** (S3/S4/S5/S9) | **REUSE** | Контракты/модули не меняются; S7 добавляет аддитивные логи и `run_id`-формализацию |
| **ADR-1026-1 / ADR-1026-4** (S1/S2 логи) | **REUSE** | `FILTER_*`/`RESTORE_*` сохраняются; только `run_id` формализуется как общий |
| **ADR-1022-4 / ADR-1023-6 / ADR-1023-7** (2-вызовность, `correlation_id`) | **REUSE** | `correlation_id` становится формальным `run_id`; 2 вызова не нарушаются |
| **ADR-1025-24 D4** (публикационный гейт) | **governed-by** | `PUBLISH_*` GATED; публикация не трогается |
| **ADR-1026-2** (frozen-артефакты F8) | **не запускается** | Δ каталога=0 |
| **§104 / `image_generation.py` / обложка** | **REUSE (read-only)** | Только `COVER_*`-логи; модель/провайдер/ключ/промпт/порядок без изменений |
| **§106** | **REUSE** | Fail-closed; без бесконечных повторов |
| **ADR-1026-9** | **НОВЫЙ** | Step 2 @Architect |

## Карта D1–D8 → реализация (факт T-3406; merge §78 + deploy 2.58.26 VERIFIED)

| D | Решение | Реализация (факт) | Верификация |
|---|---|---|---|
| **D1** | `run_id` = `correlation_id` | `services/summary_run_log.py` (`RunContext`/`finish_run`); одна точка — `summary_generator._run` / `summary_test_run.run_summary_test`; проброс параметром; `llm.generate(correlation_id=)` | `test_single_run_id_all_events`, `test_hybrid_events_same_run_id` (SC-01/SC-11) |
| **D2** | Каталог событий §108 | `summary_run_log.py` (`log_summary_*`/`log_format_*`/`log_cover_*`), `summary_generator` (жизненный цикл, `FORMAT_*`/`COVER_*`), `summary_l1_clusterizer`/`summary_l2_writer` (+`http_status`/`attempts`), `summary_test_run` (dry-run `FORMAT_*`); `PUBLISH_*` отсутствуют | SC-03…SC-06; `test_publish_events_absent_gated` (SC-15) |
| **D3** | Δ DDL=0 | ring-buffer/файлы (retention без изменений); `llm_usage_events` по `run_id`; `RunContext` in-memory; `db/**` вне diff; F8 не переиздавался | SC-11/SC-12 (review T-3404) |
| **D4** | §110 клиентский фильтр | `web/app.js` (`logSummaryOnly`/`isSummaryLog`/`summaryErrorLabel`/`toggleLogSummary`/`shownLogs`), `web/index.html`, `web/static/app.css`; `web/api/routes.py` вне diff | `tests/js/round1026_s7_log_summary_filter_test.js` (SC-09/SC-10) |
| **D5** | Dry-run S9: 0/0/0 + `run_id` | `services/summary_test_run.py`, `web/api/summary_test.py`; `TEST_*` без `SUMMARY_*`/`PUBLISH_*`/`COVER_*`; второй контур не создан | `TestDryRunContour` (SC-14) |
| **D6** | Fail-closed §109/R17 | `summary_run_log.py` (`provider_host`/`http_status_of`/`attempts_of`); `*_ERROR` + `SUMMARY_FAILED`; best-effort лог-стор | `TestStageErrorDetails`, R17-пины (SC-07/SC-08) |
| **D7** | Инварианты | 0 новых зависимостей; `param_catalog.py`/`db/**`/§104/XML/публикация вне diff; 2-вызовность (`await_count==2`) | review T-3403/T-3404: pytest 8890/0, JS 45/45, каталог 469/426/444/100/98/21 (Δ=0) |
| **D8** | Deploy 2.58.26 | `config/settings.py` (`APP_VERSION`), `README.md`, cache-bust; `deployment.md` **VERIFIED**; откат `pre-round1026-s7` → `f774ecc` | `test_app_version_bumped`; прод: health 200, `/healthz` 2.58.26 (SC-16) |

## Последствия

- Каждый прогон Саммари (живой и dry-run) наблюдаем сквозным `run_id`; ошибки диагностируемы по §109 без утечек (R17).
- §110 даёт фильтр/раскрытие/копирование в существующем viewer без backend-изменений и без роста каталога.
- Метрики §112 и будущие узлы S8 опираются на тот же `run_id`/`llm_usage_events` — второй учёт не создаётся.
- Ограничения (документируются): `PUBLISH_*` отсутствуют до S6/D4; dedicated-слот → токены/стоимость «Нет данных»; ring-buffer ограничен `LOG_RING_MAX_ENTRIES` (события — операционные, не архив); формальные узлы ExecutionGraph — S8; §115 — S10.

## Ссылки

- `plans/features/summary-logging-runid-round1026/{spec.md, tasks.md, evidence.md, review.md, deployment.md}`; `plans/ARCHITECTURE.md` **§78** (S7 — Merge T-3406); baseline-тег `pre-round1026-s7` → `f774ecc`.
- Код: `services/summary_generator.py` (`_run`/`_run_hybrid_l2`/`_apply_filter`/`_restore`/`_deliver_l2_rich`/`_deliver_l2_plain`, `correlation_id`), `services/summary_l1_clusterizer.py` (`_log_*`), `services/summary_l2_writer.py` (`_log_*`), `services/summary_article_formatter.py` (`format_*`), `services/summary_test_run.py` (`TEST_*`, `run_id`), `services/usage_events.py` (`new_correlation_id`), `services/log_ring.py` (`sanitize`/`get_entries`), `web/api/routes.py` (`GET /api/status/logs`), `web/app.js` (`loadLogs`/`logText`/`copyLogRow`), `web/index.html`.
- Архивы: ADR-1026-1/-4/-5/-6/-7/-8, ADR-1022-4, ADR-1023-6/-7, ADR-1025-24, ADR-1026-2.
