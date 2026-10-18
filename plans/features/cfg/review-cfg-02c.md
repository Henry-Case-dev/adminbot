# REVIEW-CFG-02C — независимое ревью изоляции `user_image` ↔ `summary_cover`

| Поле | Значение |
|---|---|
| Кандидат | uncommitted поверх `1d367e4c` (база сборки `f7a14994`): 9 файлов кода/UI/теста + новый `tests/test_cfg02c_image_isolation.py` + 4 пин-файла + e2e-инструмент — sha256_12 все совпали |
| Вердикт | **Approved** — двусторонняя изоляция подтверждена кодом, RED→GREEN и blast-наборами; 1 scope-амендмент (2 стаба) + 1 нит (README «9 строк» vs фактических 13); `CFG-02C.5` → RFL |

## 1. Таксономия/рут — явный параметр от call-site
`image_generation.py`: `CONSUMPTION_USER/COVER` + `COVER_STAGE_*` (base/styled_edit/retry_recovery/fallback); тип едет **явным параметром** `generate_image_verbose(consumption_type=…, cover_stage=…)` → `_cover_charge` → `worker_budget.reserve_image(consumption_type=…)` → журнал `image_reservation.source='summary_cover:<stage>'`; из промпта/имени инструмента тип не выводится (§02C.2) ✓. Пользовательские пути (`generate_and_send`) остаются `user_image` (`direct|tool`) ✓. Бюджетные стадии: только `base` (fallback — внутри одного списания `_generate_image_verbose_inner`); styled/recovery контур бюджета не трогают — тесты-охраны зелёные и на базе (пре-существующее поведение сохранено) ✓.

## 2. worker_budget — shared-only для обложек
`reserve_image(consumption_type=COVER)` резервирует **только** shared (per-chat `image_calls` не инкрементируется, даже при живой user-квоте/`0`) ✓; `release_image` читает `source` строки журнала и для cover **не откатывает per-chat** (иначе «одолжил» бы пользовательскую квоту) ✓; `journal_consumption_type` — единый маппер (forward-only: исторические `direct|tool` = user_image) ✓; агрегаты: `RESERVATION_DAY_SQL` исключает `summary_cover%` (витрина — только пользовательские), `RESERVATION_COVER_DAY_SQL` — разбивка обложек того же дня/чата; `RESERVATION_SHARED_COVER_SQL` считает cover-расход в shared-дне по `created_at AT TIME ZONE WORKER_BUDGET_TZ` (журнальный `day` — день чата, TZ может не совпадать) ✓; `cover_used` — аддитивно в shared-блоке `get_day_summary`; `image_usage_summary.cover` — отдельная разбивка ✓.

## 3. Отказы/TZ — истинный источник
`_reserve_or_consume`: `limit_global` больше не схлопывается в `budget` — `shared_budget` (свежий deny и replay journaled-отказа) ✓; `capability_registry["shared_budget"]="quota_exhausted"` (класс шаблона; §17.2-код — `financial_limit_reached`) ✓; shared-текст — `image_shared_budget_note` c TZ `WORKER_BUDGET_TZ`, user-строка — прежняя с TZ чата ✓; `image_denial_details` различает `image_shared_limit`/`image_daily_limit` через единый `_caps.image_quota_state` ✓.

## 4. Двусторонние негативы — перепрогон
* Новый файл: **19 passed** ✓; **RED на чистом `f7a14994` + финальный тест-файл: 16 failed / 3 passed** (лог лейна 17f/2p — расхождение на 1: `test_user_quota_note_keeps_chat_tz` на базе зелёный по конструкции (охрана неизменённого user-поведения); 2 задокументированных base-pass = styled/recovery охраны) — RED подтверждён.
* Свидетели (≥4, из base-падений): `test_direct_and_tool_memes_do_not_touch_cover_contour` (spy `_cover_charge`: **0 вызовов** на direct+tool путях), `test_cover_journal_is_typed_shared_only` (`source='summary_cover:base'`, `chat_used=0`, `shared_used=1`), `test_base_cover_works_when_user_daily_zero_and_freq_on`, `test_user_denial_by_daily_quota_does_not_write_cover_rows`, `test_cover_retry/fallback_does_not_touch_user_counters`, `test_cover_provider_error_releases_shared_keeps_user_clean`, `test_parallel_user_and_cover_isolated`, `test_inflight_cover_reservation_does_not_block_user` ✓.

## 5. Числа (мои прогоны)
Набор 116 → **135** (=116+19 новых) ✓; **308** ✓; **286** ✓; **263** ✓; **176** ✓; 110 → 90 (мой состав чуть уже; всё зелёное); **22** ✓; JS-sweep `tests/js/*.js` → **88/0** ✓; UI e2e `tools/ui_cfg02c_image_isolation_e2e.py` → **RESULT: PASS**, `console_errors=[]`, повторный прогон не изменил evidence (0 изменений — детерминизм) ✓; F8 `--check` → **579 OK** ✓. Полный `tests/` сам не перезапускал (12 мин): атрибуция 9 подтверждена компонентно — t5150×5/asap7×2/mca01×1 красные на чистом HEAD в этой же среде (проверено в REV-VISION-CORE), mca09 — order-flake (в изоляции зелёный) — новых падений от CFG-02C нет.

## 6. Вне-скоупные стабы — **принимаю с note**
`tests/test_asap7_cover_preview.py` и `tests/test_extra_cover_style_runtime.py` — механические `+**kwargs`-зеркала сигнатуры `generate_image_verbose` (диффы прочитаны: только подпись + комментарии; поведение тестов не изменено). Требование 02C.2 меняет сигнатуру → без правки 9 тестов падали бы TypeError. **Scope-амендмент**: добавить 2 файла в write_scope CFG-02C (или явно санкционировать при биндинге). `services/capability_registry.py` — вне списка write_scope, но **покрыт его note-условием** («read-only, если честная диагностика потребует правок») и README §1.4 → санкционировано, не девиация.

## 7. DDL Δ=0 — подтверждено
`services/pg_db.py` не тронут (`git diff` пуст); тип потребления живёт в **существующей** колонке `image_reservation.source` (enum-пространство `summary_cover:<stage>`); `RESERVATION_RELEASE_SELECT_SQL` лишь добавляет `source` в SELECT — не DDL ✓.

## 8. Дисциплина
Фактически тронуто: 5 сервисов + `web/app.js`/`web/index.html` + `web/api/summary_test.py` + 1 новый тест + 4 пин-файла + e2e-инструмент + evidence; **`services/mca_vision.py`, `web/api/routes.py`, `services/direct_chat_service.py`, `handlers/direct_chat.py` не тронуты** ✓; `budget_limits/worker_settings/pg_db/usage_events/cover_style_pipeline/cover_style_jobs` не менялись (осознанно, ΔDDL=0) ✓. Чужих WIP в дереве по этим файлам нет.

## Леджер
* **Код → VERIFIED** (evidence этого лейна): `CFG-02C.1`, `.2`, `.3`, `.4`, `.6`, `.7`, `CFG-02.AC8`, `CFG-02.AC9`, `ADD-1.T2`, `CFG-02.F`, `CFG-02C.D`, `CFG-02C.B`.
* **`CFG-02C.5` → READY_FOR_LIVE** (live_required, preprod): локально — детерминированный e2e + rendered-просмотр; живая preprod/прод-витрина — релизный лейн (Ф6), сейчас не заявляется ✓.
* **Ниты для биндинга:** (a) README говорит «9 строк слайса», фактически в карте **13** (гейт: `scoped=13`) — evidence нужен на все 13 (4 алиас-строки: ADD-1.T2, CFG-02.F, CFG-02C.D, CFG-02C.B — тем же эвиденсом + обоснованием «не дублируется»); (b) scope-амендмент для 2 стабов (см. §6); (c) shared-семантика (один физический потолок обеих ветвей, разбивка из журнала) — зафиксировать в note строк CFG-02C.4/AC9, чтобы «один счётчик не выдавался за другой» читалось из карты.

## Итог

Изоляция реализована жёстко и двусторонне: обложки не тратят пользовательскую квоту и не блокируются ею (в т.ч. при `0` и при частотном лимите), пользовательские пути не пишут cover-строк и не трогают cover-контур, shared-потолок назван честно (свой TZ/строка/код), жизненный цикл обложки — один платный вызов = одно типизированное списание с commit/release. Гейт — пред-бинднговый (13 PENDING + rolling-candidate), как у CFG-01/02A/02B. **Approved** (CFG-02C.5 — RFL; ниты §Леджер — рутина биндинга).
