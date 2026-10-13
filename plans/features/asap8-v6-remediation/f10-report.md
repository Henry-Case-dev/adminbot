# F10 / v6 — финальная reconciliation запуска ASAP 8 v6 (C01–C10, D01–D14)

- Дата: 14.10.2026. Автор: D14-лейн (финал). Правило вердиктов: код / тесты /
  коммит / прод-подтверждение — четыре разные сущности (v6 §A.2).
- **Baseline:** `1e98027` (`1e980275ce5c857b825860b50a34a2486c790359`,
  release 2.58.77, деплой на прод подтверждён healthz 200 — ledger-c).
- **Финальный кандидат:** HEAD `217c965` + некоммитнутый кандидат D14
  (help-каноны INFO v9 / GUIDE v6, отчёт d14-report.md). Fingerprints — после
  коммита Orchestrator'ом.
- **Deployed SHA:** __PENDING__ (ожидается 2.58.78 после деплоя; до деплоя
  ни один ID не может быть помечен VERIFIED_LIVE).
- Первоисточники: ledger-c.md, ledger-d.md, requirements-map.md, forensic.md,
  волновые отчёты (wa1/wa2/wa3, wc-direct, c03a, c06a, d05, d06, d07,
  p1-d091011, d1213), rca-c03a/rca-c06a.

## 1. Волны запуска (baseline 1e98027 → HEAD 217c965)

| Волна | Коммиты | Состав | Reviewer |
|---|---|---|---|
| Wave A | `bfbc3df` (D02), `e606ec8` (D08+D09-полночь), `6230fde` (D01+D09-гейт) | supergroup migration, Random-тумблер, dossier stale-guard | REV-WAVE-A Approved |
| Wave B | `cadd432` (D06), `5c521fd` (C06A), `8700628` (C03A) | isolation scope-before-topK, initiative hot-toggle+funnel, styled recovery | REV-WAVE-B Approved |
| Wave C | `2ef6189` (D03+D04+D07) | Direct L1 authorize/accounting/temperature, execution modes+orchestrator+evidence, overrides-map | REV-WAVE-C Approved |
| P1 | `f2192b6` (D05), `2e40615` (D09+D10+D11) | Experience hybrid detector+usefulness, dream/GraphRAG/temporal/registry | REV-P1 Approved |
| UI | `217c965` (D12+D13) | truthful Status run-cards, universal save contract, mobile shell | REV-UI-D1213 Approved |
| D14 | кандидат в дереве (не закоммичен) | help-каноны v9/v6 + f10/runtime_task | эта лейн; независимый REV — Orchestrator |

## 2. C01–C10 (повторная проверка F1–F9 +-owner симптомы)

Статусы на момент отчёта: живые прод-пробы не выполнялись (деплой 2.58.78
pending), поэтому VERIFIED_LIVE никто не заявляет. «REV» = волновое
независимое ревью зашло.

| ID | Статус | Реализация/тесты (evidence) | Что закрывает VERIFIED_LIVE |
|---|---|---|---|
| C01 Summary L2 | CODE_PRESENT, REV F1; prod-проба pending owner | `summary_l2_repair.py` + 39 тестов; ledger-c §C01 | 1 живой run: нет регрессии Hybrid→Legacy на repairable, reason/index/coverage правдивы |
| C02 Summary parity | CODE_PRESENT, REV F2; prod-проба pending | `summary_execution_input.py` + parity-фикстура fingerprint | dry-run vs production на одном fixture на проде |
| C03 Style preservation | CODE_PRESENT, REV F3; prod-проба + OWNER_VISUAL_PENDING | preservation P0/story P1/fail-soft Base; 13 тестов | живой styled-run: изображение опубликовано, сюжет сохранён (owner visual) |
| C03A Base есть/styled нет | ЗАКРЫТО КОДОМ (`8700628`), REV-WAVE-B Approved; live owner pending | recovery-каталог, durable job+heartbeat, bounded retry, semantic_preservation_failed, UNVERIFIED_SEMANTIC; 36 тестов (`test_asap8_v6_c03a_style_recovery.py`) | наблюдаемый владельцем случай сбоя style → recovery на проде |
| C04 Prompt truth UX | CODE_PRESENT, REV F4; prod-проба pending | `/analytics/pipeline/runs/latest`, cover_prompts_status, preview-compile v2; 18 тестов | открытие last-run на прод-UI, payload==manifest |
| C05 Module decouple | CODE_PRESENT, REV F5; prod-проба pending | роутеры безусловно, runtime-гейты, Random master; 19+48 тестов | рестарт с Summary OFF + hot-toggle на проде |
| C06 Initiative E2E | CODE_PRESENT; live owner pending | producer→intent→decision→L2→SendRecheck→send; 23 теста | живой цикл created→due→decided→sent на рабочем чате |
| C06A Status «не запускалось» | ЗАКРЫТО КОДОМ (`5c521fd`), REV-WAVE-B Approved; live owner pending | hot-toggle симметрия, durable liveness, funnel 7 полей + top_block_reason в UI; `test_asap8_v6_c06a_*` | контролируемое наблюдение на проде (план — rca-c06a §5) |
| C07 Stories UI | CODE_PRESENT, REV F7; prod-проба pending | display names/карточки/collapsed dev-details; 9+sweep тестов | живой чат: имена/коллизии на прод-данных |
| C08 Embeddings | CODE_PRESENT, REV F8; prod-проба pending | quota-groups/rotation/recovery tick; 10+79 тестов | 3 prod-ключа: 429 → rotation/cooldown своей группы |
| C09 YouTube proxy | CODE_PRESENT, REV F9; prod-проба pending | 407 permanent, unified proxy, health API; 41+265 тестов | `/api/youtube/proxy/health` + test на проде после фикса credentials |
| C10 Final reconciliation | ЗАКРЫВАЕТСЯ ЭТИМ ОТЧЁТОМ | f10 (этот файл) + D14 help-sync + runtime_task.md; test-re-pin `3f5b912`/`855a3e5` не считались закрытием | deployed SHA + prod-пробы в строках выше |

## 3. D01–D14

| ID | Реализовано | Тесты | Коммит | Live |
|---|---|---|---|---|
| D01 dossier/settings races | dossier guard (request_token,chat,participant) на 8 путях, scope-тосты, dirty-черновик | 15 JS + 9 py | `6230fde` | pending (прод-проба) |
| D02 supergroup migration | link≠proof, идемпотентный доснос, merge-поля, роли без эскалации, real-storage тест | 13 новых +115 | `bfbc3df` | pending (реальное событие миграции) |
| D03 Direct L1 creds/accounting/temp | authorize_l1_call, usage обеих попыток, dedicated temperature + Inspector | 58 (в т.ч. `test_asap8_v6_wc_direct_d03.py`) | `2ef6189` | pending |
| D04 Direct modes/orchestrator/evidence | none/simple_tools/adaptive, bounded orchestrator, fair-allocation evidence, L2 fallback-репак, честная деградация | 37+матрица (`wc_direct_d04/matrix`) | `2ef6189` | pending |
| D05 Experience hybrid/usefulness | детектор без LLM, durable-курсоры, ключи уроков, preference supersede, цепочка UI, usefulness+unknown | 18 py + JS (`test_asap8_v6_d05_experience.py`) | `f2192b6` | pending |
| D06 chat isolation scope-before-topK | стадийный overfetch/dedup только своего чата, телеметрия; RED 7/9 | 9 (CONTRACT D06) | `cadd432` | pending |
| D07 overrides persistence+badges | API semantics + avatar stack/popover/bulk confirm; overrides-map | 11+9 (`test_asap8_v6_d07_overrides.py`) | `2ef6189` | pending |
| D08 Random module/toggle | синтез 69 PG-only ключей, тумблер жив, secrets masked | 27 (`test_asap8_v6_wa1_config_cache.py`) | `e606ec8` | pending (владелец щёлкает на проде) |
| D09 Dream/Deep Sleep/GraphRAG | deferred-группы exactly-once, честные стадии, полночь 00:00, broad freshness, GraphRAG исходы | 56 P1 (`test_asap8_v6_p1_d09_*`, wa1/wa2 hours) | `e606ec8`+`6230fde`+`2e40615` | pending (ночные прогоны) |
| D10 Temporal factcheck evidence | fetch/parse дат публикаций, date_parse_failed без now(), allowlist evidence на 3 call sites | `test_asap8_v6_p1_d10_temporal.py` | `2e40615` | pending |
| D11 Registry completeness | Vision/Nostalgia/Sleep/Factcheck product-модули, подмодули, anchors | `test_asap8_v6_p1_d11_registry.py` | `2e40615` | pending |
| D12 Status/Analytics truth | Unified Run Card (Summary/Инициатива/Уроки) на durable-данных, honest in-memory метка, один Sleep-виджет, 0 синтетического IQ | JS 78 + Playwright 34 | `217c965` | OWNER_VISUAL_PENDING (прод-данные) |
| D13 Save contract + mobile shell | футер удалён, sticky dirty-only, dirty-leave guard, верхняя mobile-nav, route inventory | JS + Playwright desktop/mobile/landscape | `217c965` | OWNER_VISUAL_PENDING |
| D14 Help + reconciliation | каноны INFO v9/GUIDE v6, слепки байт-в-байт, миграции, f10+runtime_task | 24 NEW + 226 соседей | кандидат в дереве | прод-доставка канона после деплоя |

## 4. Осознанные остатки (backlog с обоснованием — не «забытые» P0)

| Остаток | Откуда | Обоснование | Что нужно для закрытия |
|---|---|---|---|
| `search_result` producer | C06/C06A | v6 §C06A прямо запрещает включать событие «ради счётчика» без настоящего корректного продюсера; схема готова | решение владельца, нужен ли источник; затем настоящий producer + тесты |
| GraphRAG `_vec_candidates` scope | D06 finding | тот же анти-паттерн «глобальный KNN → фильтр», но отдельная поверхность; helper уже в дереве; фикс симметричен D06 | отдельный мини-слайс по образцу `cadd432` + RED-тесты |
| Partition key DDL | D06 | sqlite-vec 0.1.9 не даёт auxiliary-WHERE в KNN — доказан staged overfetch; честный per-chat partition требует изменения схемы индекса | апгрейд vec-хранилища/индекса + миграция + бенчмарк |
| 7 виджетов D12 (§18I.12: memory-flow, Sankey, latency/cost waterfall, durable heatmap, dependency map, date timeline, overrides-виджет) | d1213-report §4 | рендер-работы; durable-данные уже готовы (Unified Run Card shipped); переименование 5 табов — владельческий naming-pass | по одному рендер-слайсу на виджет + owner naming-pass |
| `demote_reason` детализация | wc-direct (D04) | evidence/бюджетный фолбэк фиксирует l2_capacity_reason/demote_reason, но человекочитаемая дифференциация «что именно порезано» — уточнение диагностики | расширить reason-словарь + Inspector-лейблы |
| Diction `style_job_failed` | C04/C03A хвост | статус-код и причины видны, но словарная подача конкретно `style_job_failed` в одном месте Inspector лаконичнее контракта | 1 строка человекочитаемого текста + пин |
| Stories recall-эмиттер | C07/F7 | «использовалась ли история» показывается через честный прокси (excluded_from_retrieval); настоящий «кто дёрнул историю» требует эмиттера на retrieval-пути | emitters на retrieval-call-sites + флаг включения |

## 5. OWNER_VISUAL_PENDING (только визуальные/живые оценки владельца)

- Вкус размещения Save-чипа (шапка) на живых данных — D13 (позиция approved
  ревью, вкус — владелец).
- Прод-данные в run-карточках (Summary coverage/health, Инициатива воронка,
  Уроки usefulness) на реальных чатах — D12/C01/C06A.
- Живое поведение стиля обложек: styled сохраняет сюжет на реальном выпуске;
  recovery после реального сбоя — C03/C03A (после деплоя 2.58.78).
- Живое поведение Инициативы на рабочем чате (цикл + воронка 24ч) — C06/C06A.

## 6. Машинная проверка покрытия

- Ledger C01–C10/D01–D14 полный; каждый ID имеет строку в §2/§3; ни один P0
  не переопределён в backlog без явного обоснования (§4 — только не-P0 либо
  owner-запреты).
- Help-каноны синхронизированы с shipped-рантаймом; соответствие
  help-утверждение → файл/тест — в d14-report §2; grep-запреты — тестом.
- Stop rule v6: после деплоя 2.58.78 остаются только prod-пробы и
  OWNER_VISUAL_PENDING — кодовых незакрытых P0 нет.

## 7. Артефакты

`requirements-map.md`, `forensic.md`, `ledger-c.md`, `ledger-d.md`,
`architecture-decisions` — в рамках волн; `wa1/wa2/wa3/wc-direct/c03a/c06a/
d05/d06/d07/p1-d091011/d1213/d14` отчёты; этот f10; `plans/runtime_task.md`
финализирован. R17: секретов нет.
