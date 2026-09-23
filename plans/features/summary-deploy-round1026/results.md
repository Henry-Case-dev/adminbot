# S10 `summary-deploy-round1026` — обязательные результаты Эпика 2 (§117)

- **Источник:** `plans/current_task.md` §117 «После Эпика 2 предоставить» (14 пунктов, строки 3645–3660).
- **Фича:** S10 (Эпик 2, §107/§114/§115/§117), **ADR-1026-12 D5** (REQ-S10-12; SC-12); статус ADR — Proposed → Accepted по merge (T-3476).
- **Дата:** 24.09.2026. **Автор:** @Builder (Step 4, T-3470-вход). Трассировка к артефактам S1–S10.
- **Инварианты:** R17 (без ключей/промптов/сырых текстов), R18 (теги/бэкапы не удаляются), Δ DDL=0, Δ каталога=0.

| # | Пункт §117 (verbatim) | Артефакт S10 / S1–S9 | Статус |
|---|---|---|---|
| 1 | **Схему нового пайплайна** | `services/summary_generator.py::_run` → `_run_hybrid_l2`: **filter (S1)** → **restore (S2)** → **L1 (S3)** → **пакет фактов (S4)** → **L2 (S5)** → **форматтер (S5)** → **публикация (S6)**, ровно 2 LLM-вызова. Проверки пути — `tests/test_summary_deploy_round1026.py::TestSec114Scenarios`; merge-схема — `plans/ARCHITECTURE.md` §81 (T-3476) | ✅ |
| 2 | **Список новых параметров** | env-only `ClassVar` (вне каталога, Δ каталога=0): `SUMMARY_L1_BASE_URL`/`SUMMARY_L1_MODEL_NAME`/`SUMMARY_L1_API_KEY` (S3), `SUMMARY_L2_BASE_URL`/`SUMMARY_L2_MODEL_NAME`/`SUMMARY_L2_API_KEY` (S5), `SUMMARY_HYBRID_L2_ENABLED` (S5, **default ON с S10**), `SUMMARY_TEST_UI_ENABLED` (S9, default ON). Каталожные S1-параметры фильтра (`flags.summary_filter_enabled`, `limits.summary_filter_*`) — без изменений. Проверка: `TestActivation::test_no_catalog_key_and_classvar`, `TestFilterAndRouting::test_independent_l1_l2_slots` | ✅ |
| 3 | **Новые промпты L1/L2** | `services/summary_prompts.py` (канон L1 + L2) + `services/prompt_migrations.py` (`PREV_*`/ROLLBACK/эталон-канон); **в S10 не менялись** (вне diff), загружаются штатно. §115 п.4 | ✅ (S3/S5) |
| 4 | **Схему независимого роутинга** | Раздельные слоты `SUMMARY_L1_*`/`SUMMARY_L2_*` — независимые env-only резолверы (`summary_l1_clusterizer`/`summary_l2_writer`, hot-first `models.summary_l1_*`/`models.summary_l2_*`); «не выбрано» (пусто) → глобальная основная модель. Проверка: `TestFilterAndRouting::test_independent_l1_l2_slots` | ✅ |
| 5 | **JSON Schema L1** | `services/summary_l1_contract.py` (§95: строгая схема, ID-пространства DB↔TG, fail-closed `L1Result`); контракт — S3/ADR-1026-5 | ✅ (S3) |
| 6 | **Формат пакета фактов** | `services/summary_fact_package.py` (§96: `FactPackage` v1 — `name`=topic verbatim, `description`=детерминированная агрегация фактов, `chronology` ASC, `facts`/`evidence_ids`, `fragments`, `service{response_mode,cover_prompt}`, `budget`); 0 LLM | ✅ (S4) |
| 7 | **Пример статьи L2** | Эталон §99-документа L2 и его рендер — `procedure-115.md` §2 (`<h1>Как прошёл вечер</h1>` + абзацы); тесты `::test_scenario_10_rich_message_h1`/`::test_scenario_11_plain_text_fallback`; живой пример — первый прогон §115 (деплой) | ✅ (рендер) / ⏳ live |
| 8 | **Проверку Rich Message** | `::test_scenario_10_rich_message_h1`: `<img>` → настоящий `<h1>` → `<p>`, `content_format="html"`, обложка сверху; артефакт — `procedure-115.md` §2. Live-подтверждение — скриншот владельца (§115) | ✅ (тест) / ⏳ live |
| 9 | **Проверку текстового fallback** | `::test_scenario_09_cover_error_plain_fallback` (обложка не создана → текст) и `::test_scenario_11_plain_text_fallback` (`<b>title</b>` + абзацы, без `<h1>`); no-loss/чанки — S6-тесты | ✅ |
| 10 | **Подтверждение сохранности generate_image** | `services/image_generation.py` — **вне diff** (пустой `git diff --name-only pre-round1026-s10`), §104-контур не тронут; тест `TestBounds::test_forbidden_paths_unchanged` | ✅ |
| 11 | **Пример логов полного запуска** | R17-safe сквозной `run_id` (`services/summary_run_log.py`, S7): `SUMMARY_START(mode=hybrid_l2)` → `FILTER_COMPLETE` → `L1_COMPLETE` → `L2_COMPLETE` → `FORMAT_COMPLETE` → `COVER_COMPLETE` → `PUBLISH_RICH_COMPLETE`/`PUBLISH_TEXT_COMPLETE` → `SUMMARY_COMPLETE`. Шаблон (без ключей/промптов/сырых текстов) — S10 evidence; живой фрагмент — §115 (§110-viewer) | ✅ (шаблон) / ⏳ live |
| 12 | **Скриншот новых этапов в общей карте токенов** | S8 `services/execution_graph_source.py` (`filter`/`l1_clusterizer`/`l2_writer`/`formatting`/`publication`) + `web/static/execution_graph.js`; узлы не переписаны (S8 reuse). Скриншот §110-карты — @DevOps/владелец после прогона | ✅ (код) / ⏳ скриншот |
| 13 | **Результаты первого рабочего запуска** | Процедура §115 (`procedure-115.md`, 7 проверок) — выполняется @DevOps/владельцем после деплоя 2.58.29 | ⏳ post-deploy |
| 14 | **Подтверждение успешной публикации в Telegram** | `PUBLISH_RICH_COMPLETE`/`PUBLISH_TEXT_COMPLETE` (+`message_id`) + скриншот; §115 п.7; live-приёмка — владелец (SC-18) | ⏳ post-deploy |

## Итог

Все 14 пунктов §117 **оформлены и трассированы**; пункты 7/8/11/12/13/14 имеют «живую» составляющую, которая появляется **после деплоя** и фиксируется @DevOps/владельцем (§115). Отсутствие любого пункта = §117 не выполнен (ADR D5).
