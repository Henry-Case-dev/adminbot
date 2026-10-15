# review-w1 — независимое ревью Wave 1 (asap8-v6-3-live-correction)

Ревьюер: REV-W1 (read-only, родительский lens A+B). Дата: 15.10.2026.
Кандидат: HEAD **f1418d7**, Wave 1 = **1e24eca** (backend), docs bc91b90.
Метод: код и тесты проверены напрямую (не по отчётам лейнов); прогон
сфокусированных и смежных сюитов; diff-анализ ослабления тестов vs bc91b90.

## Прогоны (выполнены ревьюером)

- Фокус: b01+b02+b03+b09+b04_edit+b04_scene+b06+b07+direct_chat_concurrency → **108 passed** (29+15+60+4; collect совпадает с заявлениями лейнов).
- Смежные: test_graphrag_memory + test_mca01_tx_task_supervisor (single-writer пин) + test_direct_chat + test_chat_params + **test_pg_db** + test_summary_scheduler → **426 passed** (join-фиксы Settings-ClassVar и mca01-пина подтверждены живым прогоном).
- Anti-fake: сверены пины 561→571/536→546 (механические, санкция B01, F8-check EXIT=0), перезаписи test_asap8_f3 (смена контракта F3→B04 санкционирована ТЗ: story-floor был самим дефектом), TTL-тесты graphrag (переписаны под НОВЫЙ контракт владельца B03, ассерты сильнее: expired присутствует, помечен, ниже свежего), B10-фикс (только пин L1 OFF по канону F1 + 2 FakeDB-заглушки; ассерты не тронуты).
- RED/GREEN D06 подтверждён анализом старого кода (bc91b90: глобальный KNN `k=fetch_k*2` → `_filter_vec_rows` ПОСЛЕ — ровно анти-паттерн; displacement-тест с 400 строго более близкими чужими фактами на нём падает).

## Вердикты по требованиям (код-уровень «IMPLEMENTED+TESTED»)

| Требование | Вердикт | Ключевые доказательства (файл:что) |
|---|---|---|
| B01 | **APPROVED** (live canary 24–48ч — Wave 4) | `initiative_observer.py`: LLM не на каждую реплику — окно ≤14, eval_min_interval/бюджеты (`_evaluate_phase`), SILENT легален, no timer-forced send (отправка только из evaluated opportunity), «24ч ноль» → `initiative_observer_diagnostic` (`_diagnose_phase`, тест), независимость от Direct-гейта (тест `test_b01_independent_of_direct_entrypoint_gate`), `initiative_writer_unavailable` вместо молчания (2 теста: observer + heartbeat), инъекции: фиксированный system-промпт, чат-текст только user-role, настройки только из каталога/hot; per-chat профиль+лимиты (тест); two-chat/reboot/chat OFF (тесты); Writer-синглтон создаётся безусловно (bot.py:593) — lifecycle отвязан от Direct-триггера |
| B02 | **APPROVED** (прод-метрики/≥10 E2E на живых данных — Wave 4) | `mca_experience_jobs.py`: семантический extractor — основной (`_semantic_extract`, батч ≤4 чата × ≤10 строк, ОДИН LLM-вызов), regex — структурный фильтр (`_semantic_window`); слух/шутка/спор/opinion/low-confidence → reject (`semantic_rejection`, тесты по каждому); personality-инъекция отбрасывается (whitelist 8 kind без personality + тест); курсоры двигаются только после durable-записи (X1, тест restart/dedup); bounded backfill только явным вызовом (тест); lifecycle до outcome — существующий контур record_feedback→lesson→apply→outcome (E2E-тест до counters) |
| B03 | **APPROVED** (прод-латентность/Status-блок — Wave 4) | `summary_memory.py::_vec_candidates` — staged overfetch scope ДО top-K (`_staged_knn_scope` ×4 до cap 512, partial+WARNING честно); expired не удаляются в infinite (`invalidate_graph_fact` — UPDATE vec вместо DELETE; тест no-delete); fresh-first + expired top-up с пенальти 0.25 и as-of-пометкой, expired без touch/воскрешения (тесты); supersede ≠ delete (тест); per-chat infinite override (тест); overview bounded COUNT (тест) |
| B09 | **NEEDS_FIXES** — 1 блокер, остальное OK | `chat_migration.py`: 0 DELETE (тест контракта), backup до записи, идемпотентность, рестарт-тест (переоткрытие файловой БД), verify честно репортит residual; write-фаза в `db.serialized()` (mca01-пин зелёный). **Блокер: backup-cap обрывает backup, но перенос продолжается — см. F1** |
| B04 | **APPROVED** (live-доставка styled/vision — Wave 4, честно LIVE_UNVERIFIED) | `cover_style_jobs.py`: EDIT без повторной сцены (`compile_style_edit_components`; тест «summary not retransferred»; 528 chars vs 1133), semantic dedupe не подстрочный (Jaccard/overlap, тест), preflight headroom + overflow → `prompt_limit_exceeded` без платного вызова (тесты run-уровня), `prompt_limit` permanent — нет платных ретраев (`classify_style_failure` + `_PERMANENT_STYLE_REASONS`), preview = ТОТ ЖЕ `compile_style_prompt` (`style_edit_preview_report` + join-фикс web/api/cover_styles.py → `edit_report`), Base fallback только на real impossibility (overflow/semantic_preservation_failed), `format_valid` ≠ `scene_preserved` (тесты), vision env-gated с честным unknown (тест «production default no compare budget»), доставка: env-off default, `editMessageMedia` идемпотентно, `rich_message_edit_unsupported` без дубль-публикации (тесты) |
| B06 | **APPROVED** (прод-матрица — Wave 4) | `summary_scheduler.py::summary_effective_enabled` — единый резолвер emergency→chat→global; применён в cron `_tick`, в `generate_and_send` ДО слота пула (queue/trigger/manual/retry), в `/summary` (группы; ЛС — global, F-14), producer в bot.py расширен `summary_any_chat_opted_in` (флаг в If — AST-тест §18H(2)); матрица ON/OFF на РЕАЛЬНОЙ генерации (FakeLLM 0/1 вызовов + UX при manual-off) — тесты `TestMatrixRealGeneration`; global-only override → 422 гвардом routes.py:672 (см. N4) |
| B07 | **APPROVED** (прод-сид — постдеплой) | `pg_db.SEED_CATEGORIES +temporal`, `_seed_settings_into` INSERT..DO NOTHING (тест идемпотентности Δowner=0); `factcheck_temporal` visibility=hidden → нет в `registry_for_frontend()` (тест выдачи); `temporal.tool_enabled` через hot (тест POST→hot→reload→restart); Factcheck OFF скрывает `fact_check`, Direct не сломан (тест); Settings-backed синтетика без создания строк (тест) |
| B10-тестфикс | **APPROVED** | `test_direct_chat_concurrency.py`: +19 строк, ассерты не тронуты; пин L1 OFF — канон F1 (файл проверяет конкуренцию слотов, не топологию L1; L1 покрыт своим файлом); RED на исходнике воспроизведён лейном (L1 default-ON добавлял 3 вызова) |

## Блокеры

**F1 [BLOCKER — B09 «safe backup», данные]** `services/chat_migration.py:124-157` (row-таблицы) и `:162-184` (vec): backup читается с `LIMIT 200_000`; при таблице больше капа (в основном прод-чате `smart_messages` > 1M сообщений по ТЗ) backup покрывает первые 200k строк, cap-hit даёт только WARNING — и **перенос всё равно выполняется** для не-забэкапленных строк. Нарушает явный acceptance B09 «Автоматическая массовая миграция/удаление без safe backup не разрешена» и заявленное лейном правило «неполный backup → перенос не начинается» (в коде оно верно только для ошибок записи backup, не для cap).
**Минимальный фикс:** чанковый backup-цикл до исчерпания (`WHERE rowid > last` порциями по капу) ИЛИ при cap-hit — abort переноса с ошибкой в result (как при incomplete backup). **Recheck:** юнит-тест с monkeypatch `_BACKUP_ROW_CAP` (малое значение) → либо полный backup, либо честный abort; существующие 4 теста b09 остаются зелёными.

## Non-blocking замечания

- **N1** `chat_migration.py:119,197` — аварийные пути возвращают `None` (голый `return`), а `handlers/chat_lifecycle.py` (`on_chat_migrated`) делает `mig.get("errors")` → AttributeError, глотаемый fail-open'ом: миграция безопасно отменена, но честная причина теряется. Фикс: `return result`.
- **N2** B01.1 «thread/reply привязки»: `reply_to_id` выбирается в `_window_rows`, но не попадает в eval-промпт (`build_eval_user_prompt` — только user_id/author/text). Дедуп и identity есть; reply-структура не видна оценщику — маленькое улучшение качества, не блокер.
- **N3** B01: REACT фиксируется как решение (delivery `l1_react`), текстовой/emoji-реакции нет; отдельное событие recheck-плеча для ephemeral-кандидатов не пишется (сам SendRecheck выполняется) — плечо `recheck` canary-воронки не будет видно в событиях. Дисклеймлено лейном; учесть при интерпретации canary Wave 4.
- **N4** B06 «422 на inert override»: серверный гвард pre-existing (routes.py:672), но покрыт source-string тестом, не поведенческим HTTP-тестом. Рекомендован один поведенческий тест в W2 вместе с read-only UI.
- **N5** B02: прежний regex-детектор сохранён как «hybrid-вход» помимо структурного фильтра. ТЗ разрешает детерминированные правила на фильтрацию мусора; hybrid-канал смягчён валидационным lifecycle (candidate→validated) — осознанное решение, риск ограничен, владельцу на заметку.
- **N6** B04.6: scene-verification требует ЯВНОГО env даже на preview (платный compare) — дефолт прод/preview = `unknown` с причиной политики. Для canary Wave 4 включить `COVER_STYLE_SCENE_VERIFY=preview`, иначе «scene_preserved» останется unknown в доказательстве.

## Ledger-свода

- VERIFIED (код+тесты, ревьюером): B01, B02, B03, B04, B06, B07, B10-фикс.
- NEEDS_FIXES: B09 (F1; остальная механика VERIFIED).
- UNVERIFIED вне зоны Wave 1 (честно PENDING-live, Wave 4/постдеплой): canary 24–48ч B01 воронка/≥1 SEND; прод-метрики B02 и ≥1 доказанный lesson; прод-латентность B03 на 1M+; реальная доставка styled/replace в Telegram и vision-прогон B04; прод-матрица Summary B06; прод-сид temporal B07; живой supergroup-перенос B09.

## Binding

Кандидат: 1e24eca (в составе HEAD f1418d7). Любое изменение chat_migration.py/covered-файлов инвалидирует соответствующие пункты — перепроверить F1-фикс точечно.

---

## Fix-note (Orchestrator, пост-ревью)

**F1 (BLOCKER, B09) — исправлен коммитом после ревью:** backup переведён на
чанковое чтение до исчерпания (_BACKUP_CHUNK=5000, rowid-курсор,
row-таблицы), аварийный потолок _BACKUP_HARD_CAP=5M даёт явную ошибку
ackup_hard_cap и abort переноса; vec-таблицы читаются с тем же чанком.
N1 закрыт тем же коммитом: migrate_chat_memory возвращает dict на всех
аварийных путях. Recheck (предписанный Reviewer'ом): 39 passed
(test_asap8_v63_b09_migration.py включая 2 новых REGRESSION-теста
test_chunked_backup_covers_all_rows_rev_w1_f1 / test_backup_hard_cap_aborts_move_rev_w1_f1
+ mca01 single-writer пин). Итог по B09: IMPLEMENTED+TESTED (fix applied),
live-проба переноса остаётся за Wave 4.

**Non-blocking N2–N5** — приняты к сведению, в backlog (не блокируют
acceptance). **N6** — задача Wave 4: на canary включить env
COVER_STYLE_SCENE_VERIFY=preview/all (иначе scene_preserved=unknown).
