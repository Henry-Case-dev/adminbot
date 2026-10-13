# C03A (v6, P0) — recovery-контур styled cover. Отчёт Builder-лейны C03A

Кандидат на дереве, НЕ закоммичен. Базовый HEAD `6230fde`. Провайдер/image-генерация
в тестах замоканы; durable-контур (`task_jobs` через `DatabaseService(":memory:")`) —
реальный. В дереве также присутствует незакоммиченный кандидат параллельной лейны
C06A (`services/memory_maintenance.py`, `services/status_service.py`,
`tests/test_mca09_intents_block_b_round1040.py`) — моей зоной не тронут.

## 0. ADR: выбранный механизм retry/resume (Architect-заметка)

**Выбран гибрид «inline-публикация + возобновляемый durable job + recovery-sweep»,
минимально-рискованный из двух вариантов RCA.**

* Публикация остаётся inline (второй очереди/консьюмера `kind=cover_style` НЕТ —
  §42/Q6 REUSE-контракт не создаём). Style-вызов остаётся внутри
  `_publish_rich_document_impl`.
* Durable job при этом становится настоящей стадией: `_maybe_apply_cover_style`
  переводит строку `task_jobs` в `running` (`mark_running`, attempt+1) и держит
  `heartbeat` через новый колбэк `run_style_job(heartbeat=...)` →
  `TaskJobStore.heartbeat` (прежде heartbeat писался только в mca_events — RCA R2).
  Рестарт посреди вызова → `recover_stale` (уже помечает `interrupted`, fencing) →
  recovery-sweep дообрабатывает.
* Recovery-sweep — `cover_style_jobs.recover_cover_style_jobs(db)` + неблокирующий
  `kick_cover_style_recovery(db)`; шов — одна fail-open вставка в
  `mca_watchdog.sweep()` (периодический цикл И `startup_check` на старте бота,
  `bot.py:801-802` уже вызывает оба). Это ЕДИНСТВЕННАЯ точка выхода за
  перечисленный WRITE_SCOPE (`cover_*`/summary style-участок): recovery без
  триггера — мёртвый код, а sweep — существующая точка периодического+стартап
  recovery. Изменение: +10 строк, guard `try/except`, результат-ключ
  `cover_style_recovery_kicked`.
* Идентификация кандидатов sweep'а: `kind='cover_style'` И (status=`interrupted`
  ИЛИ stale-`queued` (зомби прежних деплоев, RCA R2) ИЛИ status=`completed` с
  STYLE_FAILED в checkpoint). `running` не трогается (живая инлайн-стадия или
  зона `recover_stale`/fencing). Preview-джобы (`kind=cover_style_preview`) —
  вне селектора, их requeue-контур не задет.
* **Base не генерируется второй раз**: байты Base копируются в recovery-каталог
  (`COVER_STYLE_RECOVERY_DIR`, default `var/cover_style_recovery`, bounded prune
  до 200 файлов) ДО платного вызова; retry использует сохранённый файл. Компиляция
  retry-промпта — детерминированным компилятором из durable-компонент Base-манифеста
  run'а (STORY_SCENE/SUMMARY_CONTEXT/BASE_STYLE из `record_base_cover_manifest`);
  недоступен манифест/файл Base/профиль → честный permanent-фейл
  (`base_asset_missing` / `style_inputs_missing` / `profile_missing`), НЕ слепой
  retry. Issue-номер — прежний (существующий pin-контракт `resolve_issue_number`,
  §27 retry reuse).
* **Семантика восстановления (выбор по существующему publication contract,
  опция RCA A2 «только артефакт»)**: восстановленный styled НЕ отправляется в
  Telegram заново и не редактирует опубликованный пост (`edit_message_media` в
  стеке нет; новый пост = дубль публикации, запрещено v6). Связь с тем же run:
  durable styled-артефакт (`state.styled_asset_path`), обновлённый
  `state.prompt_manifest` (`styled_status`), новая append-only provenance-строка
  (attempt-trail; единственный финальный исход — state/manifest, R4-полуидемпотентность
  задокументирована). Отправка восстановленной обложки в чат — owner-выбор
  (отдельное решение, кодового блокера нет).
* task_jobs.status остаётся семантикой ПУБЛИКАЦИИ (style-фейл с опубликованной Base
  → `completed`+reason_code — существующий пин сохранён); стиль-жизненный цикл —
  в checkpoint-state (`styled_status`/`retry_count`/`styled_fail_reason`/`styled_route`).
  Это осознанно: новые значения статусов сломали бы читателей oversight-UI.
* Bounded: `COVER_STYLE_RECOVERY_MAX_ATTEMPTS` (default 2, env), backoff
  `set_next_retry` 5→60 мин, batch limit 1 job/sweep по умолчанию, process-local
  lock; permanent-причины (`classify_style_failure`: конфигурационные/контрактные
  коды и http_4xx — permanent; timeout/network/5xx/rate-limit — transient;
  неизвестное — permanent, безопаснее против зацикливания).

## 1. Кейсы v6 §C03A — реализация и доказательство

Файл: `tests/test_asap8_v6_c03a_style_recovery.py` (34 теста, все зелёные).
Прогон: `pytest tests/test_asap8_v6_c03a_style_recovery.py tests/test_asap8_f3_style_preservation.py
tests/test_extra_cover_style_jobs.py tests/test_asap44_cover_final_closure.py
tests/test_cover_style_wave_b_asap4.py tests/test_asap43_cover_style_surgical.py … -q`
→ **465 passed** (полный список ниже, §3).

1. **Happy path → styled привязан к тому же run** — `TestCase1HappyPath`:
   publication уезжает со styled-байтами; provenance styled с
   `summary_run_id=RID`, `job_id=cov_*`, base/final asset_id; durable
   styled-артефакт; `load_run_cover_prompts` → style-манифест
   (`cover_prompts_status.style=ok`) c `styled_status=styled`; Base-манифест того
   же run на месте.
2. **Style fail → Base + честный статус → retry без второго Base и без дубля** —
   `TestCase2RetryWithoutSecondBase`:
   * transient (`timeout`): Base опубликована, image-генератор вызван 1 раз;
     `styled_status=retry_scheduled{reason,route,attempt}`, job completed с
     reason_code, событие `COVER_STYLE_RETRY_SCHEDULED`; recovery-проход →
     `recovered`: генератор Base по-прежнему 1 вызов, edit ровно 2 (fail+retry),
     в обоих промптах тот же `ВЫПУСК 1` (pin), rich-отправка НЕ повторялась
     (0 дублей), styled связан с тем же run (provenance/manifest/state).
   * permanent (`edit_unsupported`): `styled_status=failed`, recovery не ретраит
     (actions=[]), edit не вызывался снова.
3. **Restart mid-style → job не completed, bounded recovery, permanent не
   зацикливается** — `TestCase3RestartSafety`: зомби собран продукционными
   хелперами (begin → mark_running → Base-артефакт → STYLE_SUBMITTED → протухший
   heartbeat); `recover_stale` → `interrupted` (НЕ completed); sweep →
   `recovered` с сохранённой Base. Bounded: transient-фейл → scheduled с backoff
   (раньше времени — no-op), попытка 2 → `failed` при `retry_count == max`,
   третий проход — строго no-op (edit ровно max раз). Watchdog-шов:
   `wd.sweep()` → kick → фон-таска → зомби восстановлен.
4. **Explicit Style OFF → `style_disabled`, не false success / false
   style_failed** — `TestCase4StyleDisabled`: без выбранного стиля Base
   опубликован как финал, `COVER_PIPELINE_DONE fallback=style_disabled`,
   style-джобы для run нет (нет и ложного успеха); master kill-switch →
   `skip_out=style_disabled`. Гранулярные причины потери ВЫБРАННОГО стиля
   (`profile_missing` и пр.) сохраняются как есть (честнее generic).
5. **Content-loss сигнал** — `TestCase5SemanticSignal`: детерминированная
   payload-валидация результата edit (`_styled_payload_signal`): текстовый ответ
   провайдера → `semantic_preservation_failed` + Base + provenance
   fallback_mode; бинарный мусор → `invalid_image_payload` + Base (RCA R3
   bonus-дефект «битый payload публикуется как успех» закрыт); валидное
   изображение → честная метка `manifest.semantic_verification={status:
   unverified, note: no_automated_image_semantic_check}` (автоматический
   semantic-compare изображения ненадёжен; owner visual check остаётся
   visual-only gate). Оба фейла — permanent (recovery не зацикливается).
6. **Два сюжета + один profile ≠ generic scene (pipeline-часть)** —
   `TestCase6StoryIdentityDistinct`: story identity каждого сюжета доезжает
   в соответствующий промпт (F3-компилятор не тронут, регресс-охрана).

## 2. Изменения

* `services/cover_style_jobs.py` (+~650) — reason-коды/события recovery
  (`style_disabled`, `semantic_preservation_failed`, `invalid_image_payload`,
  `base_asset_missing`, `style_inputs_missing`, `recovery_exhausted`;
  `COVER_STYLE_RETRY_SCHEDULED`, `COVER_STYLE_RECOVERED`), RU-детали,
  `STYLE_REASON_CODES` (без generic-схлопывания); `classify_style_failure`,
  гейты `recovery_enabled`/`recovery_max_attempts`/backoff;
  `CoverJobState`+`base_asset_path/styled_asset_path/styled_status/
  styled_fail_reason/styled_route/retry_count` (additive, backward-compatible
  to_json/from_json); `persist_style_artifact`+prune; `set_styled_status`
  (state+manifest); payload-валидация и semantic-метка в `run_style_job`
  (success/fail пути), `heartbeat`-колбэк в `_run_with_heartbeat` (все 3 точки
  вызова); recovery-машина `recover_cover_style_jobs`/`_recover_one_cover_style_job`/
  `kick_cover_style_recovery`.
* `services/summary_generator.py` (style-участок, +~90) — `_maybe_apply_cover_style`:
  `mark_running`+`heartbeat`, персист Base-артефакта ДО вызова, retry_scheduled
  при transient+бюджете, `skip_out` (кейс 4); `_publish_rich_document_impl`:
  `_style_skip` → `cover_reason` (честная классификация `COVER_PIPELINE_DONE`).
* `services/mca_watchdog.py` (+10) — шов sweep→kick (см. ADR; единственная точка
  вне исходного WRITE_SCOPE, обоснование в ADR).
* Тесты: НОВЫЙ `tests/test_asap8_v6_c03a_style_recovery.py` (34);
  пин-замены фикстур в 5 существующих файлах — только константы «успешного
  ответа провайдера»: текстовые заглушки (`b"STYLED"`, `b"STYLED-BYTES"`,
  `b"S"`, `b"F3-STYLED-BYTES"`, `b"STYLED-ASAP44-BYTES"`) → валидные JPEG-байты
  (`\xff\xd8\xff\xe0…`). Обоснование: старые пины утверждали публикацию
  НЕ-изображения как styled-успех — это ровно RCA R3-дефект, который v6 C03A
  запрещает; producer/assortment-логика тестов не менялась (в asap44 значение
  у единой константы `STYLED_BYTES`, все сравнения консистентны).

## 3. Acceptance-прогон (финальное дерево, HEAD 6230fde + кандидат)

```
pytest tests/test_asap8_v6_c03a_style_recovery.py tests/test_asap8_f3_style_preservation.py \
  tests/test_extra_cover_style_jobs.py tests/test_asap44_cover_final_closure.py \
  tests/test_cover_style_wave_b_asap4.py tests/test_asap43_cover_style_surgical.py \
  tests/test_asap5_cover_prompt_manifest.py tests/test_asap5_cover_manifest_web.py \
  tests/test_extra_cover_style_pipeline.py tests/test_summary_cover_style_wave_f_asap41.py \
  tests/test_asap42_step3_style_integration.py tests/test_asap7_cover_readpath.py \
  tests/test_asap7_cover_fix.py tests/test_asap7_cover_preview.py \
  tests/test_cover_styles_contract_asap32.py tests/test_extra_cover_style_runtime.py \
  tests/test_extra_cover_styles_api.py tests/test_summary_wave8_ladder_matrix_asap41.py \
  tests/test_mca17_summary_instrumentation.py tests/test_mca17a_observability_core_round1027.py \
  tests/test_summary_test_run.py tests/test_asap8_f2_summary_execution_input.py
→ 465 passed, 3 warnings
```
Примечание: имена `tests/test_cover_style_jobs.py` из брифа в репо нет — актуальный
файл этого покрытия `tests/test_extra_cover_style_jobs.py` (прогнан).
`tests/test_summary_publish_integration_round1026.py::TestOnDelivery::test_on_l1_not_usable_level2_l2_publishes_article`
— красный ДО и ПОСЛЕ кандидата одинаково (проверено git stash-прогоном) — известный
pre-existing из f3-report §6 (зона F2), к C03A не относится.

## 4. Telemetry/Inspector-маппинг (существующие структуры, web/* не тронут)

* `load_run_cover_prompts(db, run_id)` → style-манифест теперь содержит
  `styled_status = {status: styled|retry_scheduled|failed, reason, route,
  attempt}` и `semantic_verification` — читается существующим
  analytics/cover-prompts API и UI-манифестом без изменений web/*.
* `cover_prompts_status` — прежняя модель (ok / *_missing / legacy_run).
* task_jobs: `status` (публикация), `reason_code` (точная причина), `attempt`
  (mark_running/requeue), `next_retry_at` (backoff), `checkpoint_ref`/payload
  cursor (CoverJobState с recovery-полями) — видимо в существующем
  jobs/oversight-инспекторе.
* События: `COVER_STYLE_RETRY_SCHEDULED` (skipped/failed), `COVER_STYLE_RECOVERED`
  (success) — R17-safe (id/enum/числа).

## 5. Инцидентальные находки

* `related-nonblocking`: recovery-каталог (`var/cover_style_recovery`) — свой
  bounded prune (200 файлов) внутри модуля; общий GC для него не нужен, но при
  появлении общего retention-механизма для cover-артефактов стоит объединить
  (`services/disk_retention.py` сейчас не знает этот каталог; файл в DO_NOT_TOUCH).
* `related-nonblocking` (R4-хвост): `cover_style_provenance` остаётся append-only
  без ключа идемпотентности — при retry появляются attempt-строки. Читателя
  «последняя строка win» в сервисах нет; единственный финальный исход —
  state/manifest. Если появится reader — нужна дедуп-семантика (Architect).
* `unrelated/pre-existing`: красный тест `test_summary_publish_integration_round1026`
  (см. §3, stash-подтверждён) — зона F2/Orchestrator.
* `unrelated/pre-existing`: строки task_jobs kind=cover_style никем не prune'ятся
  (prune вызывают только random/intents для своих kind) — терминальные cover-строки
  копятся; ретенция объявлена, но не реализована (вне лейна).
* R17: секретов/полных промптов в логах/событиях/тестах нет; recovery-каталог —
  синтетические/продовые байты обложек, имена файлов — sha256-префикс run_id.

## 6. Остаточный риск / owner-live pending

* Прод-поведение recovery-контура (рестарт в момент style-вызова на живом
  деплое) — `CODE_PRESENT_LIVE_UNVERIFIED`: механизм покрыт интеграционными
  тестами на реальном task_jobs-контуре; живой prod-срез (§3 RCA: task_jobs/
  mca_events/provenance по чату владельца) — за DevOps/owner-гейтом.
* Визуальное качество восстановленного styled (semantic) — `UNVERIFIED_SEMANTIC`
  по дизайну; owner visual check — visual-only gate.
* Отправка восстановленного styled в чат (новый пост/редакт) — осознанно НЕ
  реализована (запрет дублей + отсутствие edit-message-media); требует
  owner-решения, см. ADR §0.

## 7. REV-WAVE-B F1 (Critical) — recovery идемпотентен для успешных styled

**Дефект** (воспроизведён ревьюером): `recover_cover_style_jobs` выбирал
`status='completed'` без фильтра по исходу, а единственная защита в
`_recover_one_cover_style_job` — `state.state == STATE_DONE`, который
production-инлайн-путь никогда не ставит (DONE — только cover_style_preview).
Permanent-гвард требовал непустого `last_fail`, которого у успешной джобы нет.
Итог на durable-состоянии «как после инлайн-успеха»: sweep 1 → `recovered`
(платный edit №2), sweep 2 → `recovered` (edit №3), sweep 3 → ложный
`failed/recovery_exhausted`; watchdog дергает sweep системно. Legacy-успехи
(completed без `base_asset_path`) первым же sweep валились в
`failed/base_asset_missing`.

**Фикс** (`services/cover_style_jobs.py::_recover_one_cover_style_job`, сразу
после разбора cursor, ~строка 2707): УЖЕ УСПЕШНЫЙ styled не перезапускается —

```python
if row.get("status") == "completed" and (
        state.state == STATE_STYLE_SUCCEEDED
        or state.styled_status == RESULT_STYLED):
    return None
```

Идемпотентность: 0 edit-вызовов, task_jobs/manifest/state не изменяются.
Остальная логика recovery (кейс 2 fail→recovery, bounded/permanent, зомби)
не тронута.

**Регресс-тесты** (`tests/test_asap8_v6_c03a_style_recovery.py`,
`TestCaseRecoveryIdempotentSuccess`, TEST-LIFECYCLE: REGRESSION
owner=ASAP8-v6/C03A):
1. `test_happy_path_recovery_makes_no_paid_calls` — реальный инлайн-успех →
   три recovery-прохода подряд → `actions == []`, edit-вызов ровно 1 (инлайн),
   task_jobs остаётся completed с прежним reason_code, cursor остаётся
   STATE_STYLE_SUCCEEDED/styled, manifest побайтово не изменён;
2. `test_legacy_completed_styled_not_failed_by_sweep` — legacy-успехи
   (completed, cursor без base_asset_path; оба признака успеха:
   styled_status='styled' и голый STATE_STYLE_SUCCEEDED) → sweep не делает
   ничего, failed-строк не появляется.
Чувствительность проверена: без гварда оба теста падают (воспроизводя баг).

**Ретест**: recovery-набор 36/36 (34 старых + 2 новых; кейс 2 fail→recovery
зелёный); смежные cover-сюиты — recovery+jobs+preview+registry+pipeline+
contract+asap43: 166 passed; summary-cover-контуры (round1023/wave_f/
model_compat/asap44/runtime/prompt_manifest): 122 passed. Итого 288 green.
Чужие незакоммиченные зоны (memory_maintenance/status_service — C06A,
summary_memory — D06) не затронуты; кандидат C03A больше нигде не менялся.
