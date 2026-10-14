# F1 — Summary L2 validator reliability + granular diagnostics (отчёт)

Baseline: master `0c4f3a5` (release 2.58.74). Слайс: architecture §1 (F1), ТЗ §2
(P0 Summary), §19 S1–S4, §28. Коммит НЕ сделан (по инструкции — после Reviewer).

## 1. Что изменено по файлам

### `services/summary_l2_repair.py` (НОВЫЙ, чистый модуль — без LLM/IO)
- `detect_paragraph_defects(doc, package) -> [Defect{code, index, chars}]` —
  детекция зеркалит канонизацию `_validate` (cleanup → strip → пусто?/>900? →
  strip сырых ID → пусто?): `paragraph_bad_type` / `paragraph_empty` /
  `paragraph_too_long` / `paragraph_empty_after_cleanup` /
  `document_no_paragraphs` (index=-1, когда контентных абзацев 0).
- `repair_document(doc, package) -> (doc' | None, actions)`:
  - `paragraph_too_long` → split по sentence boundary (regex `[.!?…]+\s`),
    жадная упаковка ≤900, ВЕСЬ текст сохраняется (склейка частей == исходный
    текст); `evidence_message_ids` наследуются каждой частью (shared evidence
    разрешён §50.7); emphasis-поля переносятся как есть — их пересчитывает
    штатный канонизатор на revalidate (невалидные подстроки отбрасываются
    детерминированно); одиночное предложение >900 НЕ режется (никогда не trim,
    §28.2) → `split_skipped_single_sentence` (correctionable);
  - `paragraph_empty` / `paragraph_empty_after_cleanup` → удалить ТОЛЬКО
    дефектный элемент;
  - всё опустело → `(None, actions)` → причина `document_no_paragraphs`;
  - вход не мутируется; actions bounded (≤32), R17-safe (action/code/index/parts).
- `REASON_GROUPS` (аддитивная reason-модель §1.2): `reason` = гранулярный код,
  `reason_group` = umbrella (`invalid_paragraph` / `invalid_evidence` /
  `quote_attribution` / `structural`) — обратная совместимость аналитики.
- `CORRECTIONABLE_REASONS` (§2.4/таблица §1.2): 5 paragraph-кодов +
  `invalid_evidence` + `quote_attribution` + `invalid_json`.
  НЕ correctionable: `too_many_paragraphs`, `too_long` (>32000),
  `empty_response`, `llm_error`/`llm_timeout`, `internal_error` (conform таблице
  §1.2; `empty_response` в таблице не указан — выбран консервативный вариант,
  см. §6 решений).

### `services/summary_l2_writer.py`
- **Инвариант :10-14 заменён ЯВНО** (§1.3): happy path = 1 вызов L2, максимум =
  2 (attempt + РОВНО ОДИН correction); детерминированный repair всегда первый
  и бесплатный; бюджет ≤5 генераций на run не тронут (L1+L2+correction ≤3).
- `validate_l2_document` — оркестрация: первый проход `_validate` → при reject
  с `invalid_paragraph` granular detect → deterministic repair → revalidate
  (один проход). Точки вставки — те самые `_reject` :934-943/:1046-1047
  (repair вызывается, когда первый проход ушёл в `invalid_paragraph`).
  Аддитивные metrics: `reason_code`, `reason_group`, `paragraph_index`,
  `chars`, `repair_actions`, `repairs_applied`, `repair_defects`.
  Не-`invalid_paragraph` отказы (invented evidence, quote_attribution,
  структура) — БЕЗ paragraph-ремонта (fail-closed, §2.3). Anchor-путь получает
  тот же ремонт автоматически (через внутренний вызов `validate_l2_document`).
- `run_l2` — extension :1409-1424 → attempt+correction: если документ невалиден
  И причина correctionable → РОВНО ОДИН LLM-correction: исходные messages +
  machine reason в user-контент (`_correction_messages`: defect code,
  paragraph_index, paragraph_chars; для `invalid_json` — требование валидного
  JSON; текст абзаца/промпта — НИКОГДА, R17). Transport-фейл correction →
  fail-closed с ПЕРВОЙ причиной. Metrics: `l2_calls` (1|2), `correction_used`.
- Docstring `run_l2`/`_make_llm_call` синхронизированы с новым инвариантом.

### Anchor-path fix (rework REV-F1, CRITICAL)

**Root cause.** `validate_l2_document_anchors` пробрасывал `source_anchors` из
`repaired_paras` (выход `repair_l2_evidence`, 1:1 с raw-входом) в канонические
абзацы через `zip(canonical["paragraphs"], repaired_paras)`. До F1 канонизация
была 1:1 с входом — zip был безопасен. После F1 repair внутри
`validate_l2_document` меняет число абзацев: split добавляет части, drop
удаляет элементы → zip (a) молча отбрасывал «хвост» canonical при split
(потеря текста, reason=ok), (b) смещал якоря на один абзац при drop (paraC
получал якорь удалённого пустого). Anchor-путь — прод-дефолт
(`SUMMARY_SOURCE_ANCHORS_ENABLED=True`, `SUMMARY_L2_EVIDENCE_REPAIR_ENABLED=True`),
дефект прошёл через отсутствие anchors-кейсов в F1-тестах.

**Решение (полноценный проброс + fail-closed):**
- `summary_l2_repair.repair_projection(document, package)` — детерминированная
  проекция выхода repair по raw-индексам: `[(raw_index, kind, parts)]`, kind ∈
  {keep, skip, drop, split}; пустой список = identity (ремонт не применялся).
  `repair_document` рефакторен на использование проекции (единый источник
  раскладки — дрейф между repair и anchor-маппингом невозможен);
- `validate_l2_document_anchors`: раскладка якорей строится из проекции bridge-
  документа — split-части наследуют якоря исходного абзаца (симметрично
  shared-evidence правилу §50.7), drop исключает якоря удалённого абзаца;
- **fail-closed**: `len(расширенной проекции) != len(canonical)` → warning +
  `reason=internal_error/structural`, документ НЕ публикуется (смещённый
  якорями документ недопустим). Guard достижим только при внутреннем баге —
  в норме проекция точна по построению (repair и проекция — один код).

**Тесты** (`TestAnchorRepairAlignment` в test_asap8_f1_summary_l2_repair.py;
REGRESSION REV-F1):
1. anchor-split: [Первый(m0000), long(m0001), Третий(m0002)] → опубликованы
   ВСЕ 4 абзаца, склейка частей == исходный текст, части несут m0001,
   Третий — m0002 (RED→GREEN: до фикса 3 абзаца, вторая часть 713 симв.
   выброшена, якоря смещены);
2. anchor-drop: [paraA(m0000), пустой(m0001), paraC(m0002)] → paraC несёт
   m0002 (до фикса — смещённый m0001);
3. guard: сломанная проекция (monkeypatch `_repair_projection`) → fail-closed,
   `document=None`, `internal_error`;
4. identity-совместимость: без repairable-дефектов anchor-путь прежний
   (`invalid_refs_repaired`/`evidence_anchor_space` — как в wiring-тестах).

### `services/summary_generator.py` (pass-through, без логики L2)
- `_l2_durable_status()` — честный durable-статус L2: `ok` (публикация или
  Reviewer-отказ после bounded repair) / **`attempted_invalid`** (validator-
  invalid, §2.5/§1.5: стадия выполнена, вывод отвергнут валидатором) /
  `failed` (только transport/структурный провал).
- `SUMMARY_L2_STAGE`-вызов получает `status`/`metrics`/`reviewer_reject`.
- WARN `L2_ERROR` (:2303) дополнен: `reason`, `reason_group`,
  `paragraph_index`, `chars`, `l2_calls`, `correction_used`,
  `repair_actions=N` — только коды/числа (R17).
- `calls_so_far` считает реальные writer-вызовы: `_l2_writer_calls()` (1|2) на
  writer-source, plain и paged путях (+review/revision как раньше).

### `services/pipeline_events.py`
- `l2_stage(...)`: honest-исход. Транспорт mca-13 enum-ограничен
  (`mca_events.build_event` дропает неизвестный `outcome`; словарь REASON_CODES
  в mca_events.py — вне write-scope F1), поэтому:
  - `status` события = `ok` / **`attempted_invalid`** / `failed`
    (`outcome` — ближайший enum `failed`);
  - counts (usage_json): `reason_code` (гранулярный), `stage_status`,
    `reason_group`, `paragraph_index`, `chars` (длина, НИКОГДА текст),
    `l2_calls`, `correction_used`, `repair_actions[]` (≤16).
  Проверено реальным транспортом: `build_event` принимает
  `status=attempted_invalid` (code-field, `_safe_value`), usage_json проходит
  sanitize.

### `services/pipeline_analytics.py`
- `_classify`: `SUMMARY_L2_STAGE` со статусом `attempted_invalid` → узел L2
  FAILED (не success).
- `build_run_view`, узел L2: для attempted_invalid — `state=failed`,
  `status_label="выполнено, отвергнуто валидатором"`, reason_code берётся из
  usage_json (гранулярный; топ-уровень события enum-фильтрован), detail:
  Итог / Причина (RU + [код]) / Correction; explain-блок открывается кликом.
- `_coverage_breakdown`:
  - ось `source` = **ingested** (input_count из `SUMMARY_SOURCE_WINDOW`),
    percent считается от ingested/total — Legacy-overwrite
    (`usage.source_considered/coverage`) больше не показывает «0/865» у
    полного окна (симптом §2.5);
  - новая ось **`l2_accepted`** (total/considered/accepted/result/
    reason_code/reason_group/l2_calls/correction_used): ok /
    attempted_invalid / failed; ось отсутствует при not_run;
  - `writer` (вход писателя) — прежние поля; вердикт L2 не красит вход (UI);
  - `final` — как раньше (Legacy-overwrite влияет только на неё); `health_of`
    не тронут (деградирует по final-оси как раньше).
- `REASONS_RU`: человеческие формулировки для `invalid_paragraph`,
  `paragraph_bad_type`, `paragraph_empty`, `paragraph_too_long`,
  `paragraph_empty_after_cleanup`, `document_no_paragraphs`,
  `invalid_evidence`, `quote_attribution`, `invalid_json` (клиентский
  Decision Trace/узлы берут reason_ru отсюда).

### `web/app.js`
- `statusRu` Decision Trace: + `attempted_invalid: 'выполнено, отвергнуто
  валидатором'`; granular reason-fallback `pipelineReasonRu` (метод над
  модульным `PIPELINE_L2_REASON_RU`; stageRow использует модульную функцию
  напрямую — работает на минимальных тест-ctx).
- `pipelineCoverageRows`: + ось **«L2 · Принято (Hybrid)»** (accepted/total ·
  принято | выполнено, отвергнуто валидатором | не выполнено · granular reason
  · correction-пометка); ось «Вход писателя» больше не красится вердиктом L2
  (warn только при неполном входе).
- `pipelineCoverageLine` (единый скаляр coverage в headline) **удалён** —
  §1.5 «единый скаляр usage.coverage из headline убирается».

### `web/index.html`
- Убрана first-class карточка-скаляр (pipelineCoverageLine + «✕ Неполное
  саммари»); coverage — только карточка «Покрытие источника — по стадиям»
  (раз дельные оси; комментарий §61.6/ASAP 8 F1 в разметке). `:4688`
  (Decision Trace writer-строка) правки не потребовал — рендерит status_ru +
  reason_ru из обновлённого API.

## 2. Тесты

### Новый `tests/test_asap8_f1_summary_l2_repair.py` (35 тестов;
TEST-LIFECYCLE: CONTRACT owner=ASAP8/F1)
- **S1**: 952-символьный много-предложенческий абзац → deterministic split
  (≥2 абзаца, склейка == исходный текст, ≤900 каждый, refs наследуются) →
  `run_l2` публикует Hybrid, `llm.calls == 1` (repair бесплатен, без
  correction).
- **S2**: пустой абзац среди валидных → удалён только пустой → publish Hybrid,
  1 вызов.
- **S3**: invented evidence (`424242` вне id-space) — fail-closed: repair
  чинит абзац, но revalidate ловит evidence → документ не публикуется, ссылка
  нигде не «легализована»; и через `run_l2` (2 вызова — correction не помог,
  `invalid_evidence` финальная причина).
- **S4**: `l2_stage` событие несёт `status=attempted_invalid` + granular
  counts; `_l2_durable_status` маппинг; `build_run_view` различает
  attempted_invalid (узел failed + honest detail + ось l2_accepted
  rejected) от not_run (оси/узла нет); `_classify` считает attempted_invalid
  failed-узлом.
- Гранулярные reason-коды и reason_group (совместимость: umbrella
  `invalid_paragraph` сохраняется), correction-матрица (correctionable vs
  structural/llm_error), correction recovery/fail-closed/transport-фейл,
  R17 (machine reason без текста абзаца), golden-совместимость (валидный
  документ: `repair_actions == []`, 1 вызов; `unknown_field` не ремонтируется).

### Обновлённые существующие тесты (намеренно — пиннули заменённый контракт)
| тест | было | стало | почему |
|---|---|---|---|
| `test_summary_l2_writer.py::test_invalid_document_no_publication` | `llm.calls == 1` (invalid_json без correction) | `== 2` + метрики l2_calls/correction_used | пин «correction retry НЕ вводится» — контракт заменён владельцем (§2.4, architecture §1.3) |
| `test_summary_l2_integration.py::test_l1_not_usable_level2_fallback_package` | 1 вызов | 2 вызова + `L2_CORRECTION` в логе | тот же заменённый инвариант |
| `test_summary_publish_integration_round1026.py::test_on_l2_unusable_level3_legacy_guard` | 3 вызова, «L2 correction retry НЕ вводится» | 4 (L1+L1corr+L2+L2corr), ровно 1 `L2_CORRECTION`, `correction_used=True` в WARN | тот же |
| `tests/js/round1030_pipeline_inspector_test.js` | пины `pipelineCoverageLine` и «Неполное саммари» | пины ОТСУТСТВИЯ скаляра + наличие осей | headline-скаляр удалён контрактом §1.5 |

Остальное golden-множество не тронуто (в т.ч. `test_one_call_ok`,
`test_no_legacy_fallback_on_llm_error`, hard-cap 498, LLMError → 1 вызов,
zone-G coverage-оси, `test_call_budget_ceiling_six_calls` review-модуля).

## 3. Результаты проверок

- `pytest tests/test_asap8_f1_summary_l2_repair.py tests/test_summary_l2_writer.py`
  → **79 passed** (35 новых + 44 writer); после rework — **83 passed** (39 новых,
  включая 4 anchor-alignment теста REV-F1).
- `pytest tests/test_asap8_f1_summary_l2_repair.py
  tests/test_summary_anchors_wiring_asap42.py` → **54 passed**.
- `pytest tests/test_pipeline_analytics_asap4.py tests/test_summary_inspector_zone_g_asap41.py
  tests/test_asap5_summary_domain.py tests/test_mca17_summary_instrumentation.py
  tests/test_summary_wave_d_asap4.py tests/test_asap44_l2_review_closure.py
  tests/test_summary_anchors_wiring_asap42.py tests/test_summary_asap2_acceptance_round1027.py
  tests/test_summary_asap_hotfix_round1027.py` → **262 passed**.
- Полный sweep `pytest tests/ -k "summary"` → **зелёный: 1661 passed**
  (подтверждено Reviewer; финальный rework-прогон — см. финальный ответ).
- `node --check web/app.js` → OK (обязательно по acceptance).
- JS-харнессы: `round1030_pipeline_inspector_test.js`,
  `asap41_zone_g_inspector_test.js`, `asap5_decision_trace_test.js` → OK.
- Транспорт mca_events (real `build_event`): `SUMMARY_L2_STAGE` с
  `status=attempted_invalid` + granular usage_json — событие строится и
  персистится (ручная проверка + unit).

## 4. Live/визуальные проверки (UI-часть S4)

Локальный visual-сервер (scratch `f1_visual_server.py`, порт 8933): раздаёт
web/ + stub-API; `/api/analytics/pipeline/inspector` отдаёт run, собранный
РЕАЛЬНЫМ `pipeline_analytics.build_run_view` из synthetic-событий
attempted_invalid-сценария (S4: 865 сообщений, L1 ok, L2 отвергнут
валидатором, Legacy fallback, Final 0/865).

- **Playwright deterministic** (desktop 1280×800 + mobile 390×844):
  - карточка «Покрытие источника — по стадиям»: `✓ Источник 865 / 865 · 100%`,
    `✓ L1 · Структурирование 865 · результат: ok`, `✓ Вход писателя 865 · —`,
    `✕ L2 · Принято (Hybrid) 0 / 865 · выполнено, отвергнуто валидатором ·
    абзац > 900 символов`, `⚠ Финальный текст (источник) 0 / 865 · 0%`;
  - timeline: `✕ L2 · Писатель — выполнено, отвергнуто валидатором — Абзац
    длиннее технического лимита (900 симв.)…`; раскрытие узла: Итог / Причина
    (`… [paragraph_too_long]`) / Correction («использован (не помог)») /
    код: paragraph_too_long;
  - scalar-headline «Неполное саммари» отсутствует;
  - mobile 390: блок видим, горизонтального overflow нет, строки не переполняются;
  - console: **0 errors**.
  Скриншоты: scratch `f1_inspector_desktop_1280.png`,
  `f1_inspector_mobile_390.png` (playwright) + BU-скриншот.
- **Browser Use real render** (отдельный Chrome, TMA-stub): desktop-скриншот
  подтверждает сохранение визуальной идентичности (бейджи health, timeline,
  карточки) и новые честные тексты. Visual Neighborhood Sweep: посторонних
  дефектов вокруг изменённой зоны не видно; попутно исправлен найденный на
  рендере дефект интеграции (`pipelineReasonRu` ошибочно был в `computed` →
  перенесён в `methods`, иначе блок Inspector падал при рендере).
- ВАЖНО (честная оговорка): live-prod proof (реальный прогон на проде с
  repair/correction на живом LLM) — owner gate деплой-волны, не выполнен в
  этой среде; детерминированные контуры покрыты тестами/визуально.

## 5. Инцидентальные находки

- **Уточнение REV-F1**: более ранние «2 pre-existing failures»
  (`test_t3959_10_l1_dead_level2_l2_called_and_cover_fallback`,
  `test_on_l1_not_usable_level2_l2_publishes_article`) — артефакт ЛОКАЛЬНОЙ
  среды прогона, НЕ дефект кандидата: Reviewer подтвердил, что полный sweep
  зелёный (1661) и оба теста проходят и в изоляции, и на чистом HEAD.
  Локальная причина установлена: `_rich_media_supported()` (summary_generator
  :334, кэш на процесс) возвращает False при aiogram 3.29.1 — в песочнице
  `InputRichMessage` есть, но поля `media` нет → DoD-14 fallback-cover уходит
  в plain; в окружении ревью aiogram с полем `media` → rich-путь работает,
  тесты зелёные. К кандидату отношения не имеет; исправлений не требует.
- `mca_events.REASON_CODES` не содержит гранулярных кодов → top-level
  `reason_code` события SUMMARY_L2_STAGE остаётся None (как и раньше для
  `invalid_paragraph`); гранулярный код доставляется через `usage_json` и
  durable stage rows. Если владелец захочет top-level enum — точечное
  расширение словаря в mca_events.py (вне write-scope F1).
- Review-модуль `summary_l2_review.py` (вне write-scope): его бюджет-строка
  «writer 1 + reviewer ≤3 + revision ≤2 = ≤6» физически может стать 7, когда
  writer использовал correction (review вызывает тот же `run_l2`). Контрактно
  §1.3/§1.4 это предусмотрено (correction внутри run_l2, «сломанная плитка —
  не сносим дом»); явный пересчёт бюджета review-стадии — решение владельца.

## 6. Решения в серых зонах (не отступления от контракта)

1. `empty_response` НЕ correctionable: в таблице §1.2 указан только «JSON parse
   fail»; пустой ответ повторным запросом с тем же контекстом чинить —
   расширение таблицы. Консервативно: Legacy как раньше.
2. Event-transport: honest-исход `attempted_invalid` несёт `status`-поле
   события + `counts.stage_status` + durable stage row; `outcome` события —
   enum `failed` (mca_events вне write-scope). Потребители (analytics/UI)
   обновлены под `status`. Семантика §2.5/§1.5 соблюдена: UI нигде не говорит
   «не выполнено» для validator-invalid.
3. Ось «Вход писателя»: убрана краска вердикта L2 (вход полный → ✓; неполный →
   ⚠) — вердикт живёт на своей оси l2_accepted (§2.5 не включает вход-ось в
   headline; строка осталась как соседняя зона G).
4. Ось `source` теперь ingested-семантика (§2.5 «Source ingested: 865/865»):
   percent считается от ingested/total; для старых run без source-window
   событий — прежнее поведение (fallback на source_considered).

## 7. Остаточные риски

- R1 (валидатор): прикрыто S1–S3 + golden-свитом (1657 passed в первом
  прогоне sweep, повторный полный sweep — см. финальный ответ); repair
  детерминированный и покрывается revalidate тем же кодом валидатора.
- Correction добавляет ≤1 LLM-вызов на L2-стадию: бюджет ≤5 генераций держится
  на архитектурной арифметике (§1.3); физический worst-case review-пути
  описан в §5.
- Prod live proof repair/correction на реальном LLM — ожидает деплой-волны
  (owner gate), детерминированная часть доказана тестами.
