# DIAG-SUMMARY-DEGRADED — FIND-2 (run 718e9ea6, чат -1002661910336)

Дата: 2026-10-22 (diag 13:29 UTC). Режим: read-only (journal + код HEAD fbf9013d).
SSH: 2 коннекта (одиночный nik, без поллеров). Прод не менялся, сообщений 0.

## 1. Найденный прогон

`run_id=718e9ea64810446399970ed4ea01a2f1`, старт 13:00:00 UTC (18:00+05), 2.58.110,
source_count=566, WHOLE_WINDOW (36.6k tok, budget auto, модель deepseek-v4.1-flash @ nano-gpt).

Трейс (journal + mca_events):
- 13:05:39 L1_START; attempt=1 parse ok но raw 123 774 chars → L1_CORRECTION_RETRY `bad_schema_version`;
  attempt=2 parse ok (5 857 chars) → L1_COMPLETE **threads=12, facts=0, auto_unassigned=339, status=ok, map_degraded=False**, L1_STAGE usage: **anchor_mode=true**.
- 13:10:50 L2_START (writer_source, окно 566) → 13:11:06 L2_COMPLETE chars=6703.
- 13:11:20 L2_REVIEW **unusable** (`l2_review_unusable`) → L2_ERROR → LEGACY_FALLBACK(`l2_unusable`).
- 13:11:22–13:12:15 legacy: 3 LLM-вызова success (25.6/12.7/14.0 s, attempt=1) → SUMMARY_TEXT_READY (stage=legacy).
- 13:12:15–13:14:18 cover: base ok (89.8 s), style-обложка qwen-image-3-pro в опросе (COVER_STYLE_RUNNING).
- **13:14:20 плановый рестарт деплоя убил процесс**: APScheduler `_tick → _legacy_fallback("l2_unusable") → _run_legacy_pipeline` — CancelledError-Traceback (это тот самый «1 Traceback при остановке», вне нового процесса, pre-existing).
- Итог: publication НЕ было (`publication_status=-`), SUMMARY_COMPLETE записан при отмене со status=ok, RUN_DONE usage: `coverage=0.0, source_total=566, source_considered=0, fallback=none, package_grade=semantic, pipeline_health=degraded`.

## 2. Соседние прогоны того же чата (все 2.58.110 и раньше)

| UTC старт | source | L1 итог | coverage | fallback | publication | health |
|---|---|---|---|---|---|---|
| 10-21 13:00 | 145 | threads=16, facts=0, retry `bad_schema_version`, anchor_mode=true | **0.0** | none | ok (rich) | ok |
| 10-21 19:00 | 415 | threads=24, facts=0, retry `invalid_json`, anchor_mode=true | **0.0** | legacy (l2_review_unusable) | ok | degraded |
| 10-22 01:00 | 39 | threads=12, facts=0, retry `bad_schema_version`, anchor_mode=true | **0.0** | legacy (l2_review_rejected) | ok | degraded |
| 10-22 07:00 | 400 | **L1 invalid (`unknown_field`)** → fallback-пакет (fragments=30, chronology=400) | **100.0** | legacy (l2_review_rejected) | ok | degraded |
| 10-22 13:00 (FIND-2) | 566 | threads=12, facts=0, retry `bad_schema_version`, anchor_mode=true | **0.0** | none (прерван рестартом) | **— (не публиковался)** | degraded |

Вывод из таблицы: coverage=0.0/considered=0 — **устойчивая сигнатура**, 4 из 5 прогонов за 24 ч,
началась минимум 10-21 13:00Z (задолго до поезда). Контрпример 07:00: тот же чат/контент, но L1
упал → детерминированный fallback-пакет → coverage=100.0. Значит «норма для контента» исключена;
провайдерных 5xx/таймаутов в деградации нет (все LLM-вызовы success).

## 3. Корневая причина (код HEAD fbf9013d)

**Несоответствие контракта map v1/v2 в синтезе FactView (anchor-mode путь):**

- На этом чате L1 работает в semantic-map режиме с **anchor_mode=true** (L1_STAGE usage во всех
  затронутых прогонах) → валидатор `validate_semantic_map_v2` канонизирует карту в **v2-форму**:
  topics несут `source_anchors`, top-level — `unassigned_anchors`
  (`services/summary_l1_semantic_map.py:678-682`, поля v2 `:105-113`).
- Генератор: `map_payload = l1_result.payload` при writer_source
  (`services/summary_generator.py:2313-2317`) → `build_fact_view_from_map(map_payload, …)`
  (`:2386-2390`).
- Но `build_fact_view_from_map` читает **только v1-поля**: `topic.get("message_ids")` и
  `map_payload.get("unassigned_message_ids")` (`services/summary_fact_view.py:149-176`).
  В v2-карте этих полей НЕТ → `ids=[]` по всем темам → все темы пропущены →
  **пакет {threads: [], unassigned_message_ids: []}, но status="ok", deliverable=True,
  package_grade="semantic"** (`:208`, `:228-238`).
- EMPTY-PACKAGE GUARD (`summary_generator.py:2434`) не срабатывает: требует `fallback_used=True`,
  а ветка fact-view — не fallback.
- Coverage-блок (`:2460-2470`) честно считает `compute_package_coverage(пустой_view, 566)` →
  considered=0, coverage=0.0 и **перезаписывает** writer_source-100.0, выставленный строками
  `:2456-2459` (гарантия T-4608 «никогда не 0/839» де-факто отменяется перезаписью).
- RUN_DONE: coverage=0.0/considered=0 → `health_of` → **degraded** (§57 сработал как задуман —
  деградация ВИДИМА; ложна сама метрика, не её видимость). Summary-текст при этом реальный:
  Writer работает от полного окна (T-4608), пользователь получает саммари.
- Тесты покрывают только v1: `tests/test_summary_writer_source_asap41.py` — все фикстуры карт
  с `message_ids`/`unassigned_message_ids`; v2-anchors через FactView не покрыты никем.

Путь не менялся поездом: в delta 2.58.110→2.58.111 (deploy.json `blob_sha256_vs_candidate`)
нет `summary_generator.py` / `summary_fact_view.py` / `summary_l1_semantic_map.py` →
дефект pre-existing и **присутствует на 2.58.111**.

## 4. Проверка воспроизведения на 2.58.111

После рестарта 13:14:31Z до момента диаг (13:29Z) завершённых SUMMARY-прогонов нет вообще
(0 SUMMARY_COMPLETE в journal; cron чата 0,6,12,18 +05 → следующий тик 00:00+05 = 19:00Z 22.10).
Прямого воспроизведения ещё нет; по неизменности кода ожидается повтор 0.0/0 на первом же
успешном map-прогоне этого чата.

## 5. Классификация и маршрут

**(b) Устойчивый дефект домена summary (эпоха ASAP-4.2 anchor-mode), pre-existing, НЕ регрессия
2.58.111.** НЕ «разовый сбой» (4/5 прогонов, разные окна, LLM без ошибок) и НЕ «норма контента»
(контрпример 07:00 → 100.0). На качество самого саммари влияет косвенно (L2 теряет semantic-индекс
карты и работает от сырого окна; иначе пайплайн жив).

Маршрут: **fix-lane (summary-домен, W-волна)** + наблюдение после 19:00Z. Кандидаты фикса:
1. `build_fact_view_from_map` понимает v2 (source_anchors→message_ids через payload items/AnchorSpace)
   ИЛИ fail-closed `not_built` при 0 материализованных id (не «ok» с пустым пакетом).
2. Coverage-блок не перезаписывает writer_source-100% пакетом с нулевым материалом (или
   EMPTY-GUARD применять и к fact-view).
3. (related-nonblocking) Прерванный рестартом прогон логирует `SUMMARY_COMPLETE status=ok` при
   `publication_status=-` — отмену честнее помечать failed/interrupted.

## 6. Артефакты

- Диаг-скрипты/выводы: `OPENCODE_WORKFLOW_SCRATCH/rel-258111/diag_summary_degraded{,2}.py`,
  `…_out.txt`, `…2_out.txt` (journal-JSON срезы 10-21 12:00Z→13:29Z, R17-соблюдён).
- Находка-источник: `plans/features/asap-speech-arch/release-258111/deploy.json` FIND-2.
