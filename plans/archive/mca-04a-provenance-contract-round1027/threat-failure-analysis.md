# `mca-04a-provenance-contract` — threat & failure analysis (R3, ADR-1027-6 D1–D13)

> **Обоснование R3:** происхождение и семантика личного факта определяют всю
> память. Ошибка ведёт к ложному подтверждению, чужому субъекту, необратимому
> «переименованию» позднего подтверждения в оригинал или к удалению памяти.
> Каскад затрагивает досье, RAG, retrieval, убеждения/парадигмы. Артефакт
> обязателен (spec §Risk; T-3835).

## 1. Границы и активы

- **Активы:** `mca_source_refs`, `mca_evidence_links`, `mca_provenance_status`;
  6 provenance-колонок `graph_facts`; существующие `source_ids`/`tg_message_id`/
  `message_source_records`/`message_revisions` (REUSE); FTS; kill-switch'и.
- **Вне scope:** полная пересборка досье/job-состояния (`mca-04b`), retrieval/
  EvidenceBundle (`mca-07`), subject/speaker расширение (`mca-18`).

## 2. Модель угроз (R17: значения не цитируются без нужды)

| # | Угроза | Вектор | Контрмера | Остаток |
|---|---|---|---|---|
| T1 | Ложный `original` | старый факт + похожий текст/вектор | backfill/recon **никогда** не ставит `original`; `original` только при сохранённом прямом `tg_message_id`; recon даёт `reconstructed_support`/`tentative` | Low |
| T2 | Самоподтверждение бота | факт о человеке из ответа бота | `independence='self_referential'` для `bot_self_reply`/`bot_direct_reply`; в подтверждении участвуют только `independent`+`verified` | Low |
| T3 | Двойной учёт одного события (A10) | два вывода из одного сообщения | общий `source_ref_id`; `evidence_independent_count` считает уникальные SourceRef | Low |
| T4 | Чужой субъект | `target=asker`, совпадение имени | субъект — устойчивый ID (`store=telegram`,`entity_type=user`,`entity_id=user_id`); **одноимённые не сливаются**: ≥2 различных `user_id` по имени → `unresolved` (стабильное канон-имя, без выдуманного TG ID); self-report — субъект = `user_id` говорящего (не резолв по имени) | Low |
| T5 | Общие знания как личный факт | новости/этимология/запрос-ответ бота | `assertion_kind`/`attribution_method='world_knowledge'`; читатели исключают world_knowledge/self-referential (A85) | Low |
| T6 | Выдуманный Telegram ID при импорте | нет TG ID | `resolution='unresolved'` со стабильным source `entity_id`; `tg_message_id` отдельно и только для message | Low |
| T7 | «Переименование» восстановленного в оригинал | повторный прогон recon | ранний выход при наличии `derived_from`/`supports`; `original` не переписывается | Low |
| T8 | Удаление неподтверждённой памяти | ошибка/пропуск при восстановлении | recon/backfill аддитивны; старые строки/ID/FTS не трогаются; fail-open сохраняет запись | Low |
| T9 | Смешение источников двух чанков | одинаковый локальный номер | row-bound по окну/чанку — **подключён** в `lore_worker` (`row_count=len(window)`/`len(chunk)`); `message_lookup` existence (врезка — 04b); разные SourceRef для разных окон (A88) | Low |
| T10 | Смешение ID-пространств | SQLite/PG/TG id как числа | `entity_id` opaque в (`store`,`entity_type`); `dedup_key` включает store/type; не сравниваются | Low |
| T11 | Утечка секретов через логи/события | basis/checks/context | `basis`≤160 без CoT; `checks_json` — коды/enum; events через MCA-13 (`sanitize()`); SourceRef вместо сырого контекста | Low |
| T12 | Регрессия/неидемпотентность DDL | повторный init/усечённая legacy | self-guard `sqlite_master`/`PRAGMA table_info`; повтор — no-op; guard по колонкам для индекса/backfill | Low |

## 3. Режимы отказа

| F | Отказ | Обнаружение | Действие | Тест |
|---|---|---|---|---|
| F1 | Ошибка БД при записи SourceRef/Link | exception | fail-open, факт остаётся; сырой контекст не логируется | `test_kill_switch_off_parity` |
| F2 | Нет однозначного совпадения при recon | 0 или ≥2 кандидата | `tentative` (не выдумываем источник) | `test_reconstruct_ambiguous_tentative` |
| F3 | Сбой Layer B (портрет) | exception | person_facts Layer A уже сохранены (`unconfirmed`+SourceRef) | `test_fix_p3_person_facts_saved_independent` |
| F4 | Невалидное evidence (out-of-range/missing) | валидатор | кандидат отброшен (`evidence_out_of_range`/`evidence_missing`), не пишется | `test_fix_p5_filter_row_bounds` |
| F5 | Неразрешённый/неоднозначный субъект | нет `user_id` либо ≥2 одноимённых | `unresolved` stable source (без выдуманного TG ID); self-report — по `user_id` говорящего | `test_subject_ref_stable_id_and_unresolved`, `test_same_name_not_merged`, `test_self_report_uses_speaker_user_id` |
| F6 | OFF kill-switch | env | точный legacy-путь (паритет baseline) | `test_kill_switch_off_parity` |
| F7 | Повторный `initialize()` | v17 уже применён | no-op (0 дублей, `user_version=17`) | `test_v17_idempotent_noop` |

## 4. Carry-over / границы (решением @Architect)

- **L-MCA03-8** (отпечаток namespace `abspath|size`) — **не** в 04a; обязательный
  вход `mca-04b` (версионировать отпечаток при фиксе; `legacy_import_v1` не
  переприсваивается).
- Врезка локальный→постоянный SourceRef в chunk-пайплайн (`message_lookup`)
  — `mca-04b` (в 04a — валидатор + конвертер + row-bound + тесты).
- Прод-вызов `reconstruct_fact_provenance` (D-MCA04A-2) и реальная выборка досье
  A95 (D-MCA04A-3) — вход `mca-04b` (см. `tasks.md` «Carry-over»).
- Оценка стоимости provenance-записи на объёме батча (D-MCA04A-7) —
  вход `mca-04b`/`mca-release`.
- Реальный объём backfill/пересечения импорт↔live на прод-БД — вход `mca-release`.
