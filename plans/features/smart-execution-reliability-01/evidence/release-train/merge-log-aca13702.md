# SMART-EXECUTION-RELIABILITY-01 — release train 01: merge log

- **База линии:** `d20a7f73` (`chore(release): 2.58.199`) — деплой-подтверждённый прод-кандидат.
- **Финальный SHA поезда (код-кандидат):** `aca13702` (ветка `smart/release-train-01`).
  Поверх него лежит один docs-only коммит с этим логом и `raw/` — код он не
  меняет.
- **SHA для приёмки S17/S12 и системного аудита капов: `aca13702`**
  (ровно этот код; доказательства привязаны к нему). Если приёмка идёт по HEAD
  линии, берётся `git rev-parse smart/release-train-01` — он отличается от
  `aca13702` только этим логом.
- Объём относительно базы: 320 файлов, +47264 / −13053; 16 новых тест-файлов,
  109 новых evidence-файлов.
- Деплой в рамках этой задачи НЕ выполнялся.

## 1. История слияний (first-parent, снизу вверх)

| # | Коммит | Тип | Ветка/второй родитель | Предмет | Δ к родителю (first-parent) |
|---|---|---|---|---|---|
| 1 | `fc912fb1` | merge | `6953f1a6` — S13–S16 finalize + S1 + capacity D (плюс линейный вход `ab42343e..d238f808`: C1, E, G, H) | фактчек S13/S14/S15/S16, S1, capacity D, G, H, C1, E | 126 файлов, +31870/−9533 |
| 2 | `ff3c5041` | fix (не merge) | — | интеграционная правка предыдущей сессии: регистрация S13-промпта в каталоге, allowlist `prompt_readback` метки, частичное обновление аудит-пинов | 5 файлов, +76/−23 |
| 3 | `71c13064` | merge | `2382cc92` — F safe-fetch | привязка соединения к проверенным адресам (DNS rotation) | 4 файла, +518/−32 |
| 4 | `2e468864` | merge | `76d60678` — I1 | одиночный писатель журнала + ограниченное ожидание | 3 файла, +833/−75 |
| 5 | `d487a405` | merge | `9be4227e` — I2 | слив свежего потока опыта + честный лаг | 8 файлов, +1734/−187 |
| 6 | `19f1e80b` | merge | `d471309a` — I3 | машинная applicability урока не является запрещённым эффектом | 4 файла, +517/−11 |
| 7 | `cdd35f70` | merge | `4bf11400` — I4 | producer reason codes для unmapped mca-событий | 7 файлов, +349/−5 |
| 8 | `5bdb80cb` | merge | `c84e77d5` — I56 | chat-scope KNN по rowid + полный текст оспариваемой реплики | 18 файлов, +1240/−97 |
| 9 | `e89e1ef0` | fix | — | интеграционная волна S13-каталога + honest checkup header + пины | 68 файлов, +272/−101 |
| 10 | `aca13702` | fix | — | categorized-пины каталога 618→619 | 16 файлов, +16/−16 |

Слияния 3–8 выполнены в этой сессии поверх состояния `d487a405`
(предыдущая сессия успела слить 1, 2 и I2 до падения backend'а).
Все три оставшихся слияния прошли `ort`-стратегией **без конфликтных маркеров**
и без ручного разрешения.

## 2. Конфликты и перекрытия

Единственная зона текстуальной близости — `services/direct_chat_service.py`
(I56 против уже слитых S13–S16/I1/I2):

| Файл | Сторона A (поезд) | Сторона B (I56) | Решение | Как проверено |
|---|---|---|---|---|
| `services/direct_chat_service.py` | `_chain_timeout_seconds()` → fuse=0 = без дедлайна (~8570), `_recover_l2_overflow` + обработка `LLMContextOverflowError` (~9362) | снятие `_CORRECTION_OWN_TEXT_CAP=800` (~4095) и передача полного claim/quote в рамку исправления (~14809) | авто-merge (hunks disjoint); оба намерения сохранены: fuse-политика не тронута, символьный кап не вернулся | `git merge` без маркеров; фокусные `test_smart_exec_memory_scope`; широкий прогон (раздел 4) |

`services/mca_experience.py` (I3) и `services/mca_events.py` (I4) поезд не менял —
конфликтов нет. `services/summary_memory.py` меняет только I56.

## 3. Интеграционные правки внутри поезда (не новые фичи)

### 3.1 `ff3c5041` (предыдущая сессия, унаследован)
- `prompts.factcheck_subject_system_prompt` зарегистрирован в `param_catalog`
  (иначе `/api/config` отбивал правку S13-промпта как неизвестный ключ),
  блок `factcheck.subject` объявлен в `prompt_registry`, метка
  `prompt_readback.RESOURCE_KIND_PROMPT` внесена в allowlist с причиной,
  печать набора `FACTORY_SET_SHA256_12` переутверждена (`5c9b8200b681` → `330952838067`).
- Правка была **неполной**: F8-артефакты/фикстуры/пины и аудит полей промптов
  остались в старом состоянии. Это выявлено широким прогоном и закрыто ниже.

### 3.2 `e89e1ef0` — волна S13-каталога + honest checkup header
- `tools/_s13_reissue_catalog.py` (прецедент `tools/_vmq_mem_time_reissue_catalog.py`):
  переэмиссия `plans/docs/param-registry-round1025.{tsv,meta.md}`,
  `screen-map-round1025.md`, фикстур `tests/fixtures/round1025/{f8,catalog}_baseline.json`
  (байт-сохраняющая запись, CRLF сохранён) → REGISTRY 644→645, delta 243→244.
- Пины счётчиков каталога/TSV/хелпера: 50+ исторических тестов 644→645,
  `len(tsv)-1 == 645`, meta `"645"/"411"/"244"`, `PARAM_CATALOG_SHA256_FOLLOWUP`,
  `categorized`-пины в `test_webapp_api` (618→619).
- `services/diagnostic_collector.py`: строка `[facts_unknown] not_checked=…`
  больше не встаёт ПЕРЕД заголовком контейнера — заголовок
  `DIAGNOSTIC_EVIDENCE` снова первая строка фактов чекапа (инвариант
  data-контейнера), unknown-строка дописывается в конец. Оба намерения SXR-H5
  сохранены: неизвестность видна, контейнер не подменяется.
- `services/param_catalog.py`: описание S13-ключа без техножаргона
  («data-only JSON» → «машиночитаемый ответ») — требование
  `test_webapp_round109_ui::test_no_forbidden_jargon`.
- `services/prompt_registry.py` не менялся; allowlist `factcheck.subject`
  (scope=code + pg_key, с причиной) — в `tests/test_prompt_field_audit.py`;
  §2 контракта `docs/prompt-versioning-contract.md` обновлён вместе с пинами
  (114 блоков / 113 с текстом и печатью / 104 метки / 40 с pg_key).
- Пины, которые `ff3c5041` пропустил: `FACTORY_SET_SHA256_12` в
  `test_p0_prompts_core` и `test_expression_isolation_followup`
  (`ae40ca11c77b` → `330952838067`), `prompts == 28` → 29
  (`test_ui_verbilizer_tabs_round1023`), `test_prompt_field_audit` счётчики.
- Код-пути слайсов, затронутые этими правками, не менялись (только
  описание/порядок строки фактов); поведение проверено фокусными и широким прогоном.

### 3.3 `aca13702`
- 16 исторических тестов пинили `len(categorized) == 618`; с S13-ключом
  фактическое значение 619 → пины обновлены (числовая волна, без изменения
  проверяемой семантики).

### 3.4 Тесты, приведённые к принятому поведению слайсов (не ослабление)
| Тест | Причина | Что сделано |
|---|---|---|
| `test_epic33_router_isolation::test_album_reply_uses_buffered_caption_full_pipeline` | S13: медиа-цель без известной даты публикации теперь получает честный envelope (`date_source=unknown`) и проходит единым temporal-путём вместо отказа контура | мок отвечает `check_claim_envelope`; проверки сохранены: ровно 1 ответ, target = 3-е фото, claim-текст = caption, честная оговорка о распознавании, `<chat_context` в контексте |
| `test_history_isolation::test_episode_span_crossing_old_edge_clipped` | SXR-C2-01: заводской потолок эпизода 40 снят — coherent эпизод целиком, продолжение одной помеченной строкой | ожидаемое «ещё 29 сообщ.» → «119» (окно ±120/60 вокруг хита 252), инварианты клипа в P0 сохранены |

## 4. Широкий прогон `pytest tests` — сравнение с базой

Команда (все прогоны): `python -m pytest tests -q --tb=no -rf -p no:cacheprovider`
(контрольный прогон кандидата — с `-rfE`, чтобы получить идентификаторы ошибок).

| Линия | Итог | Файлы-идентификаторы |
|---|---|---|
| База `d20a7f73` | **124 failed, 20569 passed, 41 skipped, 25 errors** | `evidence/release-train/raw/broad-base-d20a7f73.txt` |
| Поезд до правки пинов `5bdb80cb` | 194 failed, 20852 passed, 41 skipped, 25 errors | `raw/broad-train-before-pinfix-d487a405-plus-merges.txt` |
| **Кандидат `aca13702`** | **118 failed, 20928 passed, 41 skipped, 25 errors** | `raw/broad-candidate-aca13702.txt` |

Классификация относительно базы (сравнение множеств ID, прогон `-rfE`):

- **Только на кандидате — 0.** Регрессий относительно базы не осталось.
- В первом финальном прогоне (`aca13702`, `-rf`) всплывал один флейк
  `tests/test_dream_worker.py::TestDistillation::test_cluster_distilled_to_belief`;
  в контрольном прогоне того же SHA он прошёл (25 passed отдельно на базе и
  на кандидате) → флейк порядка/таймингов, не дефект поезда.
- **Только на базе — 6** (поезд исправил): `test_evol018_prompt_audit` ×2,
  `test_evol014_meme_initiative`, `test_asap2_clar_contract`,
  `test_mca10b_..._block_d::test_blockE_f8_check_green_and_baselines`,
  `test_mca19_...::test_screen_map_and_registry_artifacts_regenerated`.
- **Общие (пре-существующие на базе) — 118**: детерминированные падения линии
  2.58.199, не относятся к слайсам поезда (примеры:
  `test_mca20_rework1_f1_f2::test_evidence_injection_stays_data_not_instructions`,
  `test_addtr_tools_minifix::test_l1_seam_announce_then_execute_once`,
  `test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface`).
- **25 errors** — ровно те же на базе и кандидате, по компонентам:
  `tests/test_youtube_multimodal_download_round1024.py` 18,
  `tests/test_evol_fc_admission.py` 4,
  `tests/test_verbilizer_response_modes_round1023.py` 2,
  `tests/test_samples_ui_e2e.py` 1. Точечная сверка этих файлов на базе и
  кандидате даёт идентичный результат (20 errors в двух файлах / 1 error в
  двух других; паритет сторон). Коллекция чистая: `--collect-only` даёт
  21111 тестов и 0 ошибок сбора.

Фокусные прогоны по слайсам (кандидат `aca13702`):
`test_sxr_i3_lesson_effects` + `test_lesson_strategy_contract` 18 passed;
`test_mca16_experience_block_{a,b,c}` + `test_asap8_v63_b02` + `test_asap8_v6_d05` 88 passed;
`test_smart_i4_reason_codes` + пины reason-codes 114 passed (в составе набора);
`test_smart_exec_memory_scope` + `test_smart_exec_learning_incidents` +
`test_asap8_v6_d06_isolation` 19 passed; `test_summary_memory` +
`test_memory_contracts` + `test_mca17_summary_instrumentation` 162 passed;
`test_smart_exec_evidence`/`selfdiag`/`i4`/`i3`/`memory_scope`/`learning_incidents`/
`asap8_v6_d06`/`mca16_a`/`lesson_strategy` 139 passed.

Реальный sqlite-vec путь I56 перепроверен в этом окружении:
`plans/features/smart-execution-reliability-01/evidence/i-memory/probe_vec0_rowid.py`
— `rowid IN (SELECT id FROM facts WHERE chat_id = ?)` внутри vec0 KNN работает
(в т.ч. int8-путь), пустой scope даёт пустую выдачу, план запроса — SCAN vec-таблицы
с LIST SUBQUERY.

## 5. Остаточные риски и известные дефекты

1. **Пре-существующие падения линии 2.58.199** (118 шт. в `raw/broad-candidate-aca13702.txt`)
   не входят в приёмку поезда; каждое воспроизводится на базе.
2. **Env-хрупкие пре-существующие тесты** (проходят только в общем прогоне,
   падают отдельным запуском и на базе, и на кандидате):
   `test_tool_coordinator_round1026::test_canon_twelve_tools` (17 vs 18 инструментов
   в зависимости от порядка), `test_tool_coordinator_round1026::test_forbidden_paths_out_of_diff`
   (диф против тега `pre-round1026-a1`). BACKLOG, не блокер поезда.
3. **Whitespace-шум в `git diff --check`** от CRLF-файлов слайса AB (`027282a7`,
   уже был в поезде до этой сессии): с `-c core.whitespace=cr-at-eol` проверка чистая.
   Новые правки этой сессии дополнительного шума не дают.
4. **Поведенческие сдвиги, принятые слайсами** (тесты приведены к ним, см. §3.4):
   временной envelope для медиа с неизвестной датой; снятие потолка эпизода;
   переработанная подача фактчека (S16). Живой прод-проверки в этой задаче нет —
   деплой не выполнялся.
5. **`test_dream_worker`** — единственное отличие первого финального прогона
   кандидата (1 падение), в контрольном прогоне того же SHA прошёл; флейк
   порядка/таймингов, наблюдать в повторных прогонах.
6. Инструмент `tools/_s13_reissue_catalog.py` оставлен в репозитории как
   воспроизводимый генератор переэмиссии (прецедент существующих `_*_reissue_*.py`).

## 6. Приёмка S17/S12 и системный аудит капов

- S17/S12 принимаются **строго на `aca13702`** (или на его потомке, прошедшем
  такое же независимое ревью); любой последующий фикс меняет SHA и требует
  повторной привязки evidence.
- Системный аудит капов (в т.ч. запрет самостоятельных квот инструкций LLM)
  выполняется на этом же SHA: S13-ключ добавлен в каталог без бюджета/обрезки,
  I56 снимает символьный кап оспариваемой реплики (800), ограничения — только
  техническое окно модели/источника.
