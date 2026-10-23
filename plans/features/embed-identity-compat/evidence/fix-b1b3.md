# EMBED-IDENTITY-COMPAT — закрытие блокеров ревью B1/B3

**Лейн:** `EMBED-IDENTITY-FIX2` (Builder).
**Родительский кандидат:** `30a2f868` (+ evidence `02f5473f`), ревью
`plans/features/embed-identity-compat/review.md`.
**Кандидат исправлений:** `570e1eee` (код + тесты), evidence — отдельный коммит.
**Режим:** только код/тесты/evidence; карта требований, UI и прод не тронуты.

## 1. B1 — пауза «до вердикта» не переживала рестарт

**Причина.** Пауза ставилась `pause_rebuild()` с `reason_code="paused"` —
байт-в-байт как операторская, а снималась только при членстве индекса в
process-set `ecp._PAUSED_BY_COMPAT`. После рестарта set пуст: доказанная
несовместимость не возобновляла сборку, `_ensure_job` уважительно не трогал
`paused`, планировщик отдавал `[]` — индекс навсегда оставался FTS-only, а
панель показывала «сборка идёт».

**Repro (real SQLite + sqlite-vec, мок только HTTP-embed), до фикса:**

```text
B1 {insufficient_state: insufficient,
    job_after_pause: [paused, paused],
    verdict_after_restart: incompatible,
    job_after_restart_verdict: [paused, paused],     # ← дефект
    scheduler: [],                                   # ← дефект
    panel_state: build_in_progress, panel_reindex_required: true}
```

**После фикса (тот же скрипт, тот же сценарий):**

```text
B1 {insufficient_state: insufficient,
    job_after_pause: [paused, paused_compat_insufficient],
    verdict_after_restart: incompatible,
    job_after_restart_verdict: [queued, compat_resume],
    scheduler: [graph_facts_vec],
    panel_state: build_in_progress, panel_reindex_required: true,
    live_rows: 20, docs: 20}
```

**Что изменено.**

* `services/graphrag_rebuild.py:110` — `COMPAT_PAUSE_REASON =
  "paused_compat_insufficient"` (durable маркер в `task_jobs.reason_code`,
  ΔDDL=0: колонка существует).
* `:2279 pause_rebuild(..., *, reason_code="paused")` — причина паузы теперь
  параметр; операторская пауза остаётся `paused`.
* `:2294 _compat_paused_jobs` / `:2323 _release_compat_pause` /
  `:2338 resume_compat_paused` / `:2347 cancel_compat_paused` — снятие
  паузы по **durable** `reason_code` (+ CAS `paused→queued|cancelled`), а не
  по process-set. Операторскую `paused` не матчит другой `reason_code`.
* `:1936 _build_state_from_job` — compat-пауза больше не выдаётся за
  `build_in_progress`: состояние `compat_insufficient` + честный
  `reason_code` (панель/`generation_status` не врут).
* `:1976 maybe_schedule_rebuilds` — при `incompatible` снимает compat-паузу
  перед планированием (то же делает резолвер на старте).
* `services/embedding_control_plane.py:3483 _pause_rebuild_under` — пауза с
  `COMPAT_PAUSE_REASON`; `:3500 _resume_rebuild_under` — авторитет durable
  `reason_code` (работает после рестарта); `:3517 _cancel_compat_pause_under`
  — снятие паузы при adopt; `:3565-3568` (уже доказанный допуск),
  `:3573` (ветка `incompatible` без пробы) и `:3625` (ветка после пробы)
  возобновляют/снимают сборку; `:3690` adopt отменяет «висящую» compat-паузу,
  даже если строки реестра под её fp уже нет.

**Поведение по состояниям (frozen-семантика сохранена):**

| Вердикт | Действие с compat-паузой |
|---|---|
| `incompatible` | `paused → queued`, миграция планируется (`scheduler=[index]`) |
| `compatible` | adopt + `paused → cancelled` (лишняя сборка не нужна) |
| `insufficient` | пауза остаётся, reason `paused_compat_insufficient`, rebuild не стартует |
| операторский `paused` | не трогается никогда (тест `test_b1_operator_pause_is_never_auto_resumed`) |

## 2. B3 — legacy-метаданные старых поколений (29.09)

**Причина.** `generation_space_identity()` подставлял
`preprocessing_version=""` для NULL-поля, из-за чего MSI старой строки не мог
совпасть с текущим → `incompatible` → `ensure_current_generation`
регистрировал target и запускал полную перевекторизацию.

**Repro (legacy-строка: `preprocessing_version=NULL`, `fingerprint`
воспроизводим), до фикса:**

```text
B3 {state: incompatible, reason_code: identity_changed,
    action: controlled_migration, needs_probe: false,
    candidate_fp: "", target_registered_after_resolve: true,   # ← rebuild
    ensure_current_generation: true, live_rows: 20}
```

**После фикса (та же строка):**

```text
B3 {state: insufficient, reason_code: compat_not_proven,
    action: retry_canary, needs_probe: true, candidate_fp: 84e3019891e8,
    target_registered_after_resolve: false,                    # ← rebuild нет
    ensure_current_generation: false, active_generation: true,
    live_rows: 20, docs: 20}
```

**Правило резолвера для legacy-строк (без ослабления порогов):**

1. `preprocessing_version` сохранён → MSI как раньше (единственное изменение —
   добавлена ветка ниже).
2. NULL → версия предобработки **выводится однозначно** из сохранённого
   fingerprint (`sha256(provider|model|dims|preproc|endpoint)`, формула
   неизменна с MCA-07 D4). Воспроизвелось → MSI полный, дальше обычная проба
   старых векторов → `compatible`/adopt либо `incompatible`, если проба
   докажет расхождение (A0-ожидание: прод даёт adopt, а не rebuild).
3. Не воспроизвелось / нет `model|dims` → **`insufficient`**
   `legacy_metadata_missing`, `action=need_old_vectors`: ни rebuild, ни adopt,
   `needs_probe=false` (доказывать нечего — некому приписать провенанс).
4. Модель или размерность **доказуемо** другие (`identity_changed` /
   `dimension_changed`) → прежняя контролируемая миграция: это настоящая
   смена пространства, а не пробел в метаданных (иначе сломались бы
   легитимные сценарии 3/4/`test_graphrag_identity_reindex`).

Реализация: `services/embedding_control_plane.py:2522 generation_space_identity`,
`:2548 _row_fingerprint_matches`, `:2573 _row_preprocessing_version`,
`:2588 generation_space_provenance`, `:2596 _row_space_differs_provably`;
резолвер — `:3162` (ACTIVE-ветка `:3266-3273`, no-ACTIVE ветка `:3336-3348`).

## 3. Тесты

Новый файл `tests/test_embed_identity_compat_restart_legacy.py` (9 тестов,
`TEST-LIFECYCLE: REGRESSION owner=EMBED-IDENTITY-COMPAT/B1+B3`):

| Тест | Что фиксирует |
|---|---|
| `test_b1_restart_then_incompatible_resumes_migration` | pause → рестарт → incompatible: job `queued`, `scheduler==[index]`, live неизменен |
| `test_b1_restart_then_insufficient_keeps_pause_without_rebuild` | pause → рестарт → insufficient: job остаётся `paused`, `scheduler==[]`, панель `compat_insufficient`/`reindex_required=false` |
| `test_b1_adopt_cancels_orphaned_compat_pause` | adopt снимает compat-паузу без строки реестра под её fp |
| `test_b1_compatible_admission_cancels_stale_compat_pause` | крэш между записью допуска и отменой сборки не оставляет вечную паузу |
| `test_b1_operator_pause_is_never_auto_resumed` | `reason_code='paused'` не трогается даже при доказанной несовместимости |
| `test_b3_legacy_null_preprocessing_derives_space_and_adopts` | legacy NULL-preproc: `insufficient(compat_not_proven)` → проба → adopt, target не регистрируется, live цел |
| `test_b3_legacy_without_derivable_msi_is_insufficient` | недоказуемый провенанс: `insufficient(legacy_metadata_missing)`, ни rebuild, ни adopt, данные целы |
| `test_b3_active_legacy_without_msi_never_rebuilds` | ACTIVE без MSI: `insufficient`, не `incompatible`, провенанс не перезаписывается |
| `test_b3_resolver_is_read_only` | резолвер не мутирует реестр |

RED: на коде `30a2f868` те же тесты — **6 failed / 2 passed** (падают B1-resume,
B1-adopt-cancel, B1-панель, все три B3; 2 «зелёных» — anti-regression guard'ы
«операторская пауза» и «резолвер read-only»). GREEN на `570e1eee` —
**9 passed** (`test_b1_compatible_admission_cancels_stale_compat_pause`
добавлен после финального прогона, изолированно `29 passed` вместе с
контрактным файлом).

**Прогоны (кандидат `570e1eee`):**

* `tests/test_embed_identity_compat_restart_legacy.py` — **9 passed**
  (+ контрактный файл: `29 passed`);
* смежный набор (контрактный `test_embed_identity_compat.py` + asap5 identity +
  asap6 generations + graphrag identity + webapp memory API + tx-supervisor +
  новый файл) — **116 passed**;
* полный `pytest -q` — **15285 passed / 39 skipped / 8 failed**. Из них
  **7 детерминированно pre-existing**: `assert 37 == 35`
  (`test_t5150_startup_migrations_round1046` ×5 — падают и standalone,
  `test_asap7_direct_settings` ×2): схемы v36/v37 введены 17–20.10 до
  кандидата, ΔDDL этого лейна = 0. Восьмой —
  `test_betterstack_handler.py::TestNoRedirect::test_real_302_not_followed_by_opener`
  (реальный HTTP-редирект): standalone `1 passed` → сетевой флейк.
  Второй полный прогон того же кандидата дал ровно 7 (только pre-existing).

## 4. Инварианты лейна

* **ΔDDL = 0**: новых таблиц/колонок/сервисов нет; compat-маркер живёт в
  существующей `task_jobs.reason_code`, все `write_transaction` — прежние
  `op_name` (allowlist tx-supervisor не менялся). Единственные SQL-запросы —
  `SELECT ... WHERE kind/coalesce_key/status/reason_code` по `task_jobs` и
  существующие CAS/`_registry_resume`.
* **Пороги пробы не тронуты** (`COMPAT_PROBE_*`).
* **`5877810d` сохранён**: `_repoint_job_to_generation` и `_ensure_job`
  (A→B→A / `build_failed`) не менялись; `resume_rebuild` (операторский API,
  TypeError-fix) не менялся — compat-путь идёт отдельными функциями.
* Карта требований, `web/**`, `plans/current_task.md`, прод/SSH не тронуты.

## 5. Что теперь для legacy-строк (прод)

На проде (`graph_facts_vec`, 2 строки `building` от 29.09, fp `96f808…`):

* если `model`/`dims`/`provider`/`endpoint_fingerprint` сохранены и
  fingerprint воспроизводится с текущей `casefold-strip-v1` → MSI выводится
  (provenance `fingerprint`) → `insufficient(compat_not_proven)` → проба на
  16 003 старых векторах → по A0 (`mean=1.0, min=1.0, hit5=1.0`) `compatible`
  → adopt. **Перевекторизации нет.**
* если какое-то из полей отсутствует/невоспроизводимо → `insufficient`
  `legacy_metadata_missing`, rebuild/adopt не запускаются: нужен разбор
  провенанса, а не «перестроим».
* если модель/размерность в строке доказуемо другие → прежняя контролируемая
  миграция (это не legacy-пробел).

A0-рецепту (rework B3 из ревью) теперь достаточно зафиксировать
`resolve_index_compat(...).state/reason_code/action/candidate` — ожидаемо
`insufficient(compat_not_proven)` или `compatible`, и **не** `incompatible`
по space-mismatch.

## 6. Остаточные риски

1. Вывод preprocessing из fingerprint опирается на неизменность формулы
   legacy-fingerprint (она frozen с MCA-07 D4); при будущем изменении формулы
   старые строки уйдут в `legacy_metadata_missing` (безопасно, без rebuild).
2. `resume_compat_paused` без `fp` возобновляет последнюю compat-паузу
   индекса; джоба под устаревший fp после этого остаётся `queued` и не
   выбирается планировщиком (он работает по текущему fp) — мёртвая строка, не
   влияющая на сборку (stale-worker guard §8.5).
3. Композитный скрипт A0 и evidence ревью относятся к родительскому
   кандидату `30a2f868`; числа пробы после этого лейна не переизмерялись
   (код пробы/порогов не менялся).
